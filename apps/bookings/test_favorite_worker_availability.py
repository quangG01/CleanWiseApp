from datetime import datetime, time, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.payments.models import Payment
from apps.services.models import Service
from apps.worker.models import Area, BookingAssignment, CustomerFavoriteWorker, WorkerWorkingArea

from .models import Booking, BookingSchedule
from .schedule_builder import WEEKDAY_INDEX, build_schedules


User = get_user_model()


class FavoriteWorkerAvailabilityTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        cls.customer = User.objects.create_user(
            username='availability-customer', email='availability-customer@test.com', role='CUSTOMER',
        )
        cls.other_customer = User.objects.create_user(
            username='availability-other', email='availability-other@test.com', role='CUSTOMER',
        )
        cls.worker = User.objects.create_user(
            username='availability-worker', email='availability-worker@test.com', role='WORKER',
        )
        cls.service = Service.objects.create(
            code='AVAILABILITY_TEST', section_code='HOME_CLEANING', name='Dọn nhà',
            form_schema={'fields': [
                {'key': 'date', 'type': 'DATE', 'required': True},
                {'key': 'start_time', 'type': 'TIME', 'required': True},
                {'key': 'duration', 'type': 'SINGLE_SELECT', 'options': [{'value': '2_HOURS'}]},
            ], 'default_duration_hours': 2},
            pricing_config={'base_prices': {'2_HOURS': 150000}},
            is_active=True,
        )
        WorkerProfile.objects.create(
            user=cls.worker, status=WorkerProfile.Status.ACTIVE, registered_service=cls.service,
        )
        area = Area.objects.create(name='Hồ Chí Minh', city='Hồ Chí Minh', province_code='79')
        WorkerWorkingArea.objects.create(worker=cls.worker, area=area)
        cls.address = CustomerAddress.objects.create(
            customer=cls.customer, receiver_name='Khách', receiver_phone='0900000001',
            address_line='01 Đường test', city='Hồ Chí Minh', province_code='79',
        )
        cls.other_address = CustomerAddress.objects.create(
            customer=cls.other_customer, receiver_name='Khách khác', receiver_phone='0900000002',
            address_line='02 Đường test', city='Hồ Chí Minh', province_code='79',
        )
        CustomerFavoriteWorker.objects.create(customer=cls.customer, worker=cls.worker)
        cls.other_booking = Booking.objects.create(
            booking_code='AVAILABILITY-OTHER', customer=cls.other_customer, service=cls.service,
            address=cls.other_address, service_data={},
        )

    def setUp(self):
        self.client.force_authenticate(self.customer)
        self.url = reverse('customer-booking-favorite-worker-availability')
        self.start = timezone.make_aware(datetime.combine(timezone.localdate() + timedelta(days=2), time(9)))
        self.payload = {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {'date': self.start.date().isoformat(), 'start_time': '09:00'},
        }

    def assign(self, start, end, *, assignment_status=BookingAssignment.Status.ACCEPTED):
        schedule = BookingSchedule.objects.create(
            booking=self.other_booking, sequence_no=self.other_booking.schedules.count() + 1,
            scheduled_start=start, scheduled_end=end,
        )
        return BookingAssignment.objects.create(
            schedule=schedule, worker=self.worker, status=assignment_status,
        )

    def availability(self):
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def create_booking(self, **fields):
        with patch('apps.bookings.views.BookingListCreateView.get_throttles', return_value=[]):
            return self.client.post(reverse('customer-booking-list-create'), {
                **self.payload,
                'service_data': {**self.payload['service_data'], 'duration': '2_HOURS'},
                'payment_method': Payment.Method.CASH,
                **fields,
            }, format='json')

    def test_only_an_accepted_overlapping_job_makes_a_favorite_busy(self):
        self.assign(self.start - timedelta(hours=2), self.start)
        self.assign(self.start, self.start + timedelta(hours=1),
                    assignment_status=BookingAssignment.Status.PENDING)
        result = self.availability()
        self.assertEqual(result['session_count'], 1)
        self.assertEqual(result['first_schedule']['scheduled_end'], (self.start + timedelta(hours=2)).isoformat())
        self.assertEqual(result['results'][0]['availability'], 'AVAILABLE')

        conflict = self.assign(self.start + timedelta(hours=1), self.start + timedelta(hours=3))
        result = self.availability()['results'][0]
        self.assertEqual(result['worker_id'], self.worker.id)
        self.assertEqual(result['availability'], 'BUSY')
        self.assertNotIn('schedule_id', result)

        conflict.schedule.status = BookingSchedule.Status.CANCELLED
        conflict.schedule.save(update_fields=['status'])
        self.assertEqual(self.availability()['results'][0]['availability'], 'AVAILABLE')

        response = self.create_booking(preferred_worker_id=self.worker.id)
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(BookingSchedule.objects.get(booking__customer=self.customer).preferred_worker_id, self.worker.id)

    def test_recurring_package_checks_later_sessions(self):
        weekday = next(key for key, index in WEEKDAY_INDEX.items() if index == self.start.weekday())
        self.service.form_schema = {
            'schedule_type': 'RECURRING_WEEKLY',
            'default_duration_hours': 2,
            'fields': [
                {'key': 'weekdays', 'type': 'WEEKDAY_MULTI_SELECT', 'options': [{'value': weekday}]},
                {'key': 'start_time', 'type': 'TIME'},
                {'key': 'package_duration', 'type': 'SINGLE_SELECT', 'options': [{'value': '1_MONTH'}]},
            ],
        }
        self.service.save(update_fields=['form_schema'])
        self.payload['service_data'] = {'weekdays': [weekday], 'start_time': '09:00', 'package_duration': '1_MONTH'}
        later = build_schedules(self.service.form_schema, self.payload['service_data'])[1]
        self.assign(later['scheduled_start'], later['scheduled_end'])
        result = self.availability()
        self.assertEqual(result['session_count'], 4)
        self.assertEqual(result['results'][0]['availability'], 'BUSY')

    def test_create_rechecks_after_worker_becomes_busy(self):
        self.assertEqual(self.availability()['results'][0]['availability'], 'AVAILABLE')
        self.assign(self.start, self.start + timedelta(hours=2))

        response = self.create_booking(preferred_worker_id=self.worker.id)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('preferred_worker_id', response.data['errors'])
        self.assertFalse(Booking.objects.filter(customer=self.customer).exists())
        self.assertFalse(Payment.objects.filter(customer=self.customer).exists())

        response = self.create_booking()
        self.assertEqual(response.status_code, 201, response.data)
        self.assertIsNone(BookingSchedule.objects.get(booking__customer=self.customer).preferred_worker_id)

    def test_only_customer_owned_address_and_favorites_are_used(self):
        self.client.force_authenticate(self.other_customer)
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 404)

        self.payload['address_id'] = self.other_address.id
        self.assertEqual(self.availability()['results'], [])

        self.client.force_authenticate(self.worker)
        response = self.client.post(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 403)
