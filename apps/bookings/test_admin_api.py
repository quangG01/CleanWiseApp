from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.payments.models import Payment
from apps.services.models import Service
from apps.wallets.models import Wallet
from apps.worker.models import Area, BookingAssignment, WorkerWorkingArea

from .booking_service import create_booking
from .models import Booking, BookingActivity

User = get_user_model()


class AdminBookingApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='booking-admin', email='booking-admin@example.com',
            password='test', role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username='booking-customer-admin-test',
            email='booking-customer-admin-test@example.com',
            password='test', role=User.Role.CUSTOMER,
            first_name='An', last_name='Nguyen', phone_number='0911111111',
        )
        self.worker = User.objects.create_user(
            username='booking-worker-admin-test',
            email='booking-worker-admin-test@example.com',
            password='test', role=User.Role.WORKER,
            first_name='Binh', last_name='Tran', phone_number='0922222222',
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            receiver_name='Nguyễn Văn An', receiver_phone='0911111111',
            address_line='01 Nguyễn Huệ', ward='Bến Nghé', city='TP.HCM',
        )
        self.service = Service.objects.create(
            code='ADMIN_BOOKING_SERVICE', section_code='HOME_CLEANING',
            name='Dọn nhà admin test', description='Test',
            form_schema={
                'fields': [
                    {'key': 'date', 'type': 'DATE', 'label': 'Ngày', 'required': True},
                    {'key': 'start_time', 'type': 'TIME', 'label': 'Giờ', 'required': True},
                    {
                        'key': 'duration', 'type': 'SINGLE_SELECT',
                        'label': 'Thời lượng', 'required': True,
                        'options': [{'label': '2 giờ', 'value': '2_HOURS'}],
                    },
                ],
            },
            pricing_config={'currency': 'VND', 'base_prices': {'2_HOURS': 150000}},
            is_active=True,
        )
        WorkerProfile.objects.create(
            user=self.worker, status=WorkerProfile.Status.ACTIVE,
            registered_service=self.service, average_rating=Decimal('4.80'),
        )
        area = Area.objects.create(name='Quận 1', city='TP.HCM')
        WorkerWorkingArea.objects.create(worker=self.worker, area=area)
        Wallet.objects.create(user=self.worker, balance=Decimal('500000'))
        self.booking = self._create_booking()
        self.schedule = self.booking.schedules.get()
        self.client.force_authenticate(self.admin)

    def _service_data(self, days=2):
        start = timezone.localtime(timezone.now() + timedelta(days=days))
        return {
            'date': start.strftime('%Y-%m-%d'),
            'start_time': start.strftime('%H:%M'),
            'duration': '2_HOURS',
        }

    def _create_booking(self, days=2):
        return create_booking(
            customer=self.customer,
            service_id=self.service.id,
            address_id=self.address.id,
            service_data=self._service_data(days),
            payment_method='CASH',
        )

    def test_admin_can_list_filter_and_view_booking(self):
        response = self.client.get(reverse('admin-booking-list-create'), {
            'search': self.booking.booking_code,
            'status': Booking.Status.PENDING,
            'unassigned': 'true',
        })
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['count'], 1)
        self.assertEqual(response.data['data']['results'][0]['booking_code'], self.booking.booking_code)

        detail = self.client.get(reverse('admin-booking-detail', args=[self.booking.id]))
        self.assertEqual(detail.status_code, status.HTTP_200_OK, detail.data)
        self.assertEqual(detail.data['data']['schedules'][0]['id'], self.schedule.id)

    def test_non_admin_cannot_list_bookings(self):
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('admin-booking-list-create'))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_can_create_booking_for_customer(self):
        response = self.client.post(reverse('admin-booking-list-create'), {
            'customer_id': self.customer.id,
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': self._service_data(3),
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        created = Booking.objects.get(pk=response.data['data']['id'])
        self.assertEqual(created.customer, self.customer)
        self.assertTrue(created.activities.filter(
            event_type=BookingActivity.EventType.BOOKING_CREATED,
            actor=self.admin,
        ).exists())

    def test_available_workers_and_direct_assignment(self):
        available = self.client.get(reverse('admin-schedule-workers', args=[self.schedule.id]))
        self.assertEqual(available.status_code, status.HTTP_200_OK, available.data)
        self.assertEqual(available.data['data']['count'], 1)
        self.assertEqual(available.data['data']['results'][0]['id'], self.worker.id)

        assigned = self.client.post(
            reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
            {'worker_id': self.worker.id, 'reason': 'Đã xác nhận'},
            format='json',
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED, assigned.data)
        assignment = BookingAssignment.objects.get(schedule=self.schedule)
        self.assertEqual(assignment.status, BookingAssignment.Status.ACCEPTED)
        self.assertEqual(assignment.assigned_by, self.admin)

    def test_admin_can_unassign_worker(self):
        self.client.post(
            reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
            {'worker_id': self.worker.id}, format='json',
        )
        response = self.client.post(
            reverse('admin-schedule-unassign', args=[self.schedule.id]),
            {'reason': 'Đổi kế hoạch'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(
            BookingAssignment.objects.get(schedule=self.schedule).status,
            BookingAssignment.Status.CANCELLED,
        )

    def test_admin_can_reschedule_pending_schedule(self):
        new_start = timezone.now() + timedelta(days=5)
        response = self.client.patch(
            reverse('admin-schedule-update', args=[self.schedule.id]),
            {
                'scheduled_start': new_start.isoformat(),
                'scheduled_end': (new_start + timedelta(hours=2)).isoformat(),
                'reason': 'Khách yêu cầu đổi lịch',
            },
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.schedule.refresh_from_db()
        self.assertAlmostEqual(self.schedule.scheduled_start, new_start, delta=timedelta(seconds=1))

    def test_admin_can_cancel_booking_and_read_timeline(self):
        response = self.client.post(
            reverse('admin-booking-cancel', args=[self.booking.id]),
            {'reason': 'Khách yêu cầu qua tổng đài'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Booking.Status.CANCELLED)

        timeline = self.client.get(reverse('admin-booking-timeline', args=[self.booking.id]))
        self.assertEqual(timeline.status_code, status.HTTP_200_OK, timeline.data)
        events = {item['event_type'] for item in timeline.data['data']['results']}
        self.assertIn(BookingActivity.EventType.BOOKING_CANCELLED, events)

    def test_bulk_assign_returns_per_schedule_result(self):
        response = self.client.post(reverse('admin-schedule-bulk-assign'), {
            'booking_id': self.booking.id,
            'schedule_ids': [self.schedule.id],
            'worker_id': self.worker.id,
            'reason': 'Phân công gói',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['assigned'][0]['schedule_id'], self.schedule.id)

    def test_admin_can_complete_in_progress_schedule(self):
        assigned = self.client.post(
            reverse('admin-booking-schedule-assign', args=[self.schedule.id]),
            {'worker_id': self.worker.id}, format='json',
        )
        self.assertEqual(assigned.status_code, status.HTTP_201_CREATED, assigned.data)
        self.schedule.status = self.schedule.Status.IN_PROGRESS
        self.schedule.actual_start = timezone.now() - timedelta(hours=1)
        self.schedule.save(update_fields=['status', 'actual_start', 'updated_at'])
        self.booking.status = Booking.Status.IN_PROGRESS
        self.booking.save(update_fields=['status', 'updated_at'])

        response = self.client.post(
            reverse('admin-schedule-complete', args=[self.schedule.id]),
            {'reason': 'Ứng dụng nhân viên gặp lỗi', 'completion_note': 'Đã gọi xác nhận'},
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.schedule.refresh_from_db()
        self.booking.refresh_from_db()
        self.assertEqual(self.schedule.status, self.schedule.Status.COMPLETED)
        self.assertEqual(self.booking.status, Booking.Status.COMPLETED)

    def test_customer_cancel_records_cancel_and_refund_timeline(self):
        self.booking.payment_status = Booking.PaymentStatus.PAID
        self.booking.save(update_fields=['payment_status', 'updated_at'])
        payment = self.booking.payments.get()
        payment.status = Payment.Status.SUCCESS
        payment.paid_at = timezone.now()
        payment.save(update_fields=['status', 'paid_at', 'updated_at'])

        self.client.force_authenticate(self.customer)
        response = self.client.post(
            reverse('customer-booking-cancel', args=[self.booking.id]),
            {'reason': 'Thay đổi kế hoạch'}, format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        events = set(self.booking.activities.values_list('event_type', flat=True))
        self.assertIn(BookingActivity.EventType.BOOKING_CANCELLED, events)
        self.assertIn(BookingActivity.EventType.REFUND_CREATED, events)
        self.assertIn(BookingActivity.EventType.REFUND_COMPLETED, events)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.REFUNDED)
