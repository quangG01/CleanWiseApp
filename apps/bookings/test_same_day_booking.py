from datetime import datetime, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.services.models import Service

from .booking_service import build_booking_schedules
from .models import Booking


class SameDayBookingTests(APITestCase):
    day = '2026-11-10'

    @classmethod
    def setUpTestData(cls):
        cls.customer = get_user_model().objects.create_user(
            username='same-day', email='same-day@test.com', role='CUSTOMER',
        )
        cls.address = CustomerAddress.objects.create(
            customer=cls.customer, address_line='Địa chỉ mẫu', city='TP.HCM',
        )
        cls.service = Service.objects.create(
            name='Dọn nhà', code='SAME_DAY_TEST', section_code='HOME_CLEANING',
            form_schema={'fields': [
                {'key': 'date', 'type': 'DATE', 'required': True, 'min_days_from_now': 1},
                {'key': 'start_time', 'type': 'TIME', 'required': True},
                {'key': 'duration', 'type': 'SINGLE_SELECT', 'options': [{'value': '2_HOURS'}]},
            ]},
            pricing_config={'base_prices': {'2_HOURS': 150000}},
            is_active=True,
        )

    def setUp(self):
        self.client.force_authenticate(self.customer)

    def post_at(self, now, start_time, *, date=None, route='customer-booking-list-create'):
        now = timezone.make_aware(datetime.combine(datetime.fromisoformat(self.day).date(), now))
        payload = {
            'service_id': self.service.pk,
            'address_id': self.address.pk,
            'service_data': {'date': date or self.day, 'start_time': start_time, 'duration': '2_HOURS'},
        }
        if route == 'customer-booking-list-create':
            payload['payment_method'] = 'CASH'
        with patch('apps.bookings.booking_service.timezone.now', return_value=now):
            with patch('apps.bookings.views.BookingListCreateView.get_throttles', return_value=[]):
                return self.client.post(reverse(route), payload, format='json')

    def test_exactly_two_hours_before_start_is_valid(self):
        response = self.post_at(time(15), '17:00')
        self.assertEqual(response.status_code, 201, response.data)
        start = Booking.objects.get(customer=self.customer).schedules.get().scheduled_start
        self.assertEqual(timezone.localtime(start).time(), time(17))

    def test_rejects_insufficient_notice_before_creating_booking_or_preview(self):
        for route in ('customer-booking-list-create', 'customer-booking-favorite-worker-availability'):
            response = self.post_at(time(15), '16:59', route=route)
            self.assertEqual(response.status_code, 400, response.data)
            self.assertIn('120 phút', str(response.data['errors']['schedules']))
        self.assertFalse(Booking.objects.filter(customer=self.customer).exists())

    def test_last_start_is_available_at_exact_cutoff_only(self):
        self.assertEqual(self.post_at(time(16), '18:00').status_code, 201)
        for now, start_time in ((time(16, 0, 1), '18:00'), (time(15), '18:01')):
            with self.subTest(now=now, start_time=start_time):
                response = self.post_at(now, start_time)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('schedules', response.data['errors'])

    def test_tomorrow_remains_available_after_cutoff(self):
        response = self.post_at(time(16, 1), '08:00', date='2026-11-11')
        self.assertEqual(response.status_code, 201, response.data)

    @override_settings(BOOKING_MIN_ADVANCE_MINUTES=1440)
    def test_recurring_still_starts_no_earlier_than_tomorrow(self):
        schema = {'schedule_type': 'RECURRING_WEEKLY', 'fields': [
            {'key': 'weekdays', 'type': 'WEEKDAY_MULTI_SELECT', 'options': [{'value': 'WED'}]},
            {'key': 'start_time', 'type': 'TIME'},
            {'key': 'package_duration', 'type': 'SINGLE_SELECT', 'options': [{'value': '1_MONTH'}]},
        ]}
        self.service.form_schema = schema
        now = timezone.make_aware(datetime(2026, 11, 10, 16))
        with patch('apps.bookings.booking_service.timezone.now', return_value=now):
            schedules = build_booking_schedules(self.service, {
                'weekdays': ['WED'], 'start_time': '08:00', 'package_duration': '1_MONTH',
            })
        self.assertEqual(len(schedules), 4)
        self.assertEqual(timezone.localtime(schedules[0]['scheduled_start']).isoformat(),
                         '2026-11-11T08:00:00+07:00')

    @override_settings(BOOKING_MIN_ADVANCE_MINUTES=90)
    def test_service_detail_returns_current_policy_to_app(self):
        response = self.client.get(reverse('service-detail', args=[self.service.pk]))
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['booking_policy'], {
            'time_zone': 'Asia/Ho_Chi_Minh',
            'min_advance_minutes': 90,
            'open_time': '08:00',
            'last_start_time': '18:00',
        })
