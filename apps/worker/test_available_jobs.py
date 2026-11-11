from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.chat.realtime import user_group
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.payments.webhook_service import handle_payos_webhook
from apps.services.models import Service

from .assignment_service import open_booking_for_workers
from .models import Area, WorkerWorkingArea


class AvailableJobsAPITests(APITestCase):
    def setUp(self):
        users = get_user_model().objects
        self.customer = users.create_user(
            username='customer', email='customer@example.test', phone_number='0900000001', role='CUSTOMER',
        )
        self.worker = users.create_user(
            username='worker', email='worker@example.test', phone_number='0900000002', role='WORKER',
        )
        self.service = Service.objects.create(
            name='Dọn nhà', code='CLEAN', section_code='HOME_CLEANING',
            form_schema={}, pricing_config={},
        )
        WorkerProfile.objects.create(user=self.worker, status='ACTIVE', registered_service=self.service)
        area = Area.objects.create(ward_code='001', name='Phường mẫu', province_code='79', city='TP.HCM')
        WorkerWorkingArea.objects.create(worker=self.worker, area=area)
        self.client.force_authenticate(self.worker)
        self.url = reverse('worker-schedule-available')
        self.start = (timezone.localtime() + timedelta(days=2)).replace(hour=9)

    def create_job(self, code, hour, latitude=None, sessions=1):
        address = CustomerAddress.objects.create(
            customer=self.customer, address_line=code, city='TP.HCM', province_code='79',
            latitude=latitude, longitude=106 if latitude is not None else None,
        )
        booking = Booking.objects.create(
            booking_code=code, customer=self.customer, service=self.service, address=address,
            service_data={}, payment_status=Booking.PaymentStatus.PAID,
        )
        for index in range(sessions):
            start = self.start + timedelta(hours=hour, days=index)
            BookingSchedule.objects.create(
                booking=booking, sequence_no=index + 1,
                scheduled_start=start, scheduled_end=start + timedelta(hours=1),
            )
        return booking

    def test_distance_orders_across_pages_with_time_and_missing_location_fallback(self):
        self.create_job('LEGACY', 0)
        self.create_job('FAR', 1, 11)
        self.create_job('NEAR-LATER', 3, 10)
        self.create_job('NEAR-PACKAGE', 2, 10, sessions=2)

        filters = {'group_by': 'booking', 'page_size': 1}
        by_time = self.client.get(self.url, filters).data['data']
        self.assertEqual(by_time['count'], 4)
        self.assertEqual(by_time['results'][0]['booking_code'], 'LEGACY')

        filters.update(sort='distance', latitude=10, longitude=106)
        for page, expected in enumerate(['NEAR-PACKAGE', 'NEAR-LATER', 'FAR', 'LEGACY'], start=1):
            with self.subTest(page=page):
                response = self.client.get(self.url, {**filters, 'page': page})
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data['data']['count'], 4)
                job = response.data['data']['results'][0]
                self.assertEqual(job['booking_code'], expected)
                if expected == 'NEAR-PACKAGE':
                    self.assertEqual(job['available_sessions'], 2)
                    self.assertAlmostEqual(job['distance_km'], 0, places=3)
                elif expected == 'LEGACY':
                    self.assertIsNone(job['distance_km'])

    def test_grouped_count_reflects_new_eligible_jobs_and_cancellations(self):
        filters = {'group_by': 'booking', 'page_size': 1}
        self.assertEqual(self.client.get(self.url, filters).data['data']['count'], 0)
        booking = self.create_job('PACKAGE', 0, sessions=2)
        self.assertEqual(self.client.get(self.url, filters).data['data']['count'], 1)
        booking.status = Booking.Status.CANCELLED
        booking.save(update_fields=['status'])
        self.assertEqual(self.client.get(self.url, filters).data['data']['count'], 0)

    def test_distance_requires_valid_coordinates(self):
        for latitude, longitude in [('NaN', 106), (91, 106), (10, 181), (10, '')]:
            with self.subTest(latitude=latitude, longitude=longitude):
                response = self.client.get(self.url, {
                    'sort': 'distance', 'latitude': latitude, 'longitude': longitude,
                })
                self.assertEqual(response.status_code, 400, response.data)

    @patch('apps.notifications.realtime.get_channel_layer')
    def test_paid_package_sends_one_notification_and_live_count_to_eligible_worker(self, channel_layer):
        layer = channel_layer.return_value
        layer.group_send = AsyncMock()
        booking = self.create_job('NOTIFY-PACKAGE', 0, sessions=2)
        booking.payment_status = Booking.PaymentStatus.UNPAID
        booking.save(update_fields=['payment_status'])
        payment = Payment.objects.create(
            booking=booking, customer=self.customer, method=Payment.Method.BANK_TRANSFER,
            amount=100000, status=Payment.Status.PENDING,
        )
        outside_worker = get_user_model().objects.create_user(
            username='outside-worker', email='outside@example.test', role='WORKER',
        )
        WorkerProfile.objects.create(user=outside_worker, status='ACTIVE', registered_service=self.service)
        outside_area = Area.objects.create(ward_code='002', name='Phường khác', province_code='01', city='Hà Nội')
        WorkerWorkingArea.objects.create(worker=outside_worker, area=outside_area)
        webhook = SimpleNamespace(order_code=payment.pk, amount=payment.amount, reference='NOTIFY-PAID')

        with self.captureOnCommitCallbacks(execute=True):
            open_booking_for_workers(booking)
        self.assertFalse(Notification.objects.filter(user=self.worker, related_booking=booking).exists())

        with self.captureOnCommitCallbacks(execute=True):
            handle_payos_webhook(webhook)
            handle_payos_webhook(webhook)

        notifications = Notification.objects.filter(related_booking=booking, navigation_source='available')
        notification = notifications.get()
        self.assertEqual(notification.user, self.worker)
        self.assertEqual(notification.related_schedule, booking.schedules.get(sequence_no=1))
        response = self.client.get(reverse('notification-list'))
        self.assertEqual(response.status_code, 200)
        row = next(item for item in response.data['data']['results'] if item['id'] == notification.pk)
        self.assertEqual((row['navigation_source'], row['related_booking'], row['related_schedule']),
                         ('available', booking.pk, notification.related_schedule_id))
        layer.group_send.assert_any_await(user_group(self.worker.pk), {
            'type': 'notification.unread',
            'payload': {'unread_count': Notification.objects.filter(user=self.worker, is_read=False).count()},
        })
