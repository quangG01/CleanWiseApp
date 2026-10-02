from datetime import datetime, time
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.services.models import Service
from apps.worker.models import BookingAssignment, WorkerAvailability
from .models import Booking, BookingSchedule

User = get_user_model()
ZONE = ZoneInfo('Asia/Ho_Chi_Minh')


class AdminWorkerScheduleTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='schedule-admin', email='s-admin@test.com', role='ADMIN')
        self.worker = User.objects.create_user(username='schedule-worker', email='s-worker@test.com', role='WORKER')
        self.other = User.objects.create_user(username='schedule-other', email='s-other@test.com', role='WORKER')
        self.customer = User.objects.create_user(username='schedule-customer', email='s-customer@test.com', role='CUSTOMER')
        address = CustomerAddress.objects.create(customer=self.customer, receiver_name='Test', receiver_phone='0900000000', address_line='123 Test', city='HCM')
        service = Service.objects.create(code='schedule-demo', section_code='HOME_CLEANING', name='Dọn nhà', description='', form_schema={}, pricing_config={})
        self.booking = Booking.objects.create(booking_code='SCHEDULE-TEST', customer=self.customer, service=service, address=address, service_data={})
        self.url = reverse('admin-worker-schedule', args=[self.worker.id])
        self.params = {'start': '2026-10-05', 'end': '2026-10-12'}
        self.client.force_authenticate(self.admin)

    def assign(self, sequence, start, end, worker=None, assignment_status='ACCEPTED'):
        schedule = BookingSchedule.objects.create(booking=self.booking, sequence_no=sequence,
            scheduled_start=datetime.fromisoformat(start).replace(tzinfo=ZONE),
            scheduled_end=datetime.fromisoformat(end).replace(tzinfo=ZONE))
        return BookingAssignment.objects.create(schedule=schedule, worker=worker or self.worker, status=assignment_status)

    def test_overlap_boundaries_and_worker_filter(self):
        included = self.assign(1, '2026-10-04T23:00', '2026-10-05T01:00')
        self.assign(2, '2026-10-04T22:00', '2026-10-05T00:00')
        self.assign(3, '2026-10-12T00:00', '2026-10-12T02:00')
        self.assign(4, '2026-10-06T09:00', '2026-10-06T11:00', worker=self.other)
        response = self.client.get(self.url, self.params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['id'] for item in response.data['data']['assignments']], [included.id])

    def test_effective_assignments_exclude_reassigned_and_cancelled(self):
        previous = self.assign(1, '2026-10-06T09:00', '2026-10-06T11:00', assignment_status='CANCELLED')
        BookingAssignment.objects.create(schedule=previous.schedule, worker=self.other, status='ACCEPTED')
        pending = self.assign(2, '2026-10-07T09:00', '2026-10-07T11:00', assignment_status='PENDING')
        BookingAssignment.objects.create(schedule=pending.schedule, worker=self.other, status='ACCEPTED')
        visible = self.assign(3, '2026-10-08T09:00', '2026-10-08T11:00', assignment_status='PENDING')
        self.assign(4, '2026-10-09T09:00', '2026-10-09T11:00', assignment_status='REJECTED')
        self.assign(5, '2026-10-10T09:00', '2026-10-10T11:00', assignment_status='EXPIRED')
        self.assertEqual([item['id'] for item in self.client.get(self.url, self.params).data['data']['assignments']], [visible.id])

    def test_availability_active_only_and_detail(self):
        WorkerAvailability.objects.create(worker=self.worker, weekday=0, start_time=time(8), end_time=time(17))
        WorkerAvailability.objects.create(worker=self.worker, weekday=1, start_time=time(8), end_time=time(17), is_active=False)
        assignment = self.assign(1, '2026-10-06T09:00', '2026-10-06T11:00')
        response = self.client.get(self.url, self.params)
        self.assertEqual(len(response.data['data']['availability']), 1)
        item = response.data['data']['assignments'][0]
        self.assertEqual(item['schedule_id'], assignment.schedule_id)
        self.assertEqual(item['booking_id'], self.booking.id)
        self.assertEqual(item['service_name'], 'Dọn nhà')
        self.assertEqual(item['address']['address_line'], '123 Test')
        self.assertEqual(item['images'], [])
        # Ensure datetime/time values also serialize through the real renderer.
        self.assertIn(b'scheduled_start', response.content)

    def test_invalid_ranges(self):
        for params in ({'start': 'bad'}, {'start': '2026-02-30'},
                       {'start': '2026-10-05', 'end': '2026-10-05'},
                       {'start': '2026-10-05', 'end': '2026-10-04'},
                       {'start': '2026-10-05', 'end': '2026-12-01'}):
            with self.subTest(params=params):
                self.assertEqual(self.client.get(self.url, params).status_code, 400)

    def test_empty_week_and_default_range(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['data']['assignments'], [])
        self.assertEqual((response.data['data']['end'] - response.data['data']['start']).days, 7)

    def test_permissions_and_missing_worker(self):
        for user in (self.customer, self.worker):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.url, self.params).status_code, 403)
        self.client.force_authenticate(None)
        self.assertIn(self.client.get(self.url, self.params).status_code, (401, 403))
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.get(reverse('admin-worker-schedule', args=[self.customer.id]), self.params).status_code, 404)
