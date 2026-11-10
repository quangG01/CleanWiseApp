from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.bookings.models import Booking, BookingSchedule, BookingScheduleImage
from apps.services.models import Service

from .assignment_service import get_checkout_deadline, handle_missed_checkouts
from .models import BookingAssignment
from .serializers import WorkerMyScheduleSerializer


class CheckoutWindowTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        customer = users.create_user(username='checkout-customer', email='checkout-customer@test.com', role='CUSTOMER')
        cls.worker = users.create_user(username='checkout-worker', email='checkout-worker@test.com', role='WORKER')
        address = CustomerAddress.objects.create(customer=customer, receiver_name='Khách',
            receiver_phone='0900000001', address_line='01 Đường test', city='Hồ Chí Minh')
        service = Service.objects.create(code='CHECKOUT_TEST', section_code='HOME_CLEANING',
            name='Dọn nhà', form_schema={}, pricing_config={})
        cls.booking = Booking.objects.create(booking_code='CODE-05-TEST', customer=customer, address=address,
            service=service, status=Booking.Status.IN_PROGRESS, service_data={})
        cls.end = timezone.make_aware(datetime(2026, 11, 18, 11))
        cls.start = cls.end - timedelta(hours=2)
        cls.schedule = BookingSchedule.objects.create(booking=cls.booking, sequence_no=1,
            scheduled_start=cls.start, scheduled_end=cls.end, actual_start=cls.start,
            status=BookingSchedule.Status.IN_PROGRESS)
        BookingAssignment.objects.create(schedule=cls.schedule, worker=cls.worker,
                                         status=BookingAssignment.Status.ACCEPTED)
        for image_type in (BookingScheduleImage.ImageType.BEFORE, BookingScheduleImage.ImageType.AFTER):
            BookingScheduleImage.objects.create(schedule=cls.schedule, uploaded_by=cls.worker,
                                                image_type=image_type, image='checkout-test.jpg')

    def setUp(self):
        self.client.force_authenticate(self.worker)
        self.url = reverse('worker-schedule-check-out', args=[self.schedule.pk])

    def checkout_at(self, now):
        with patch('apps.worker.checkin_service.timezone.now', return_value=now):
            return self.client.post(self.url, {'completion_note': 'Đã làm xong'}, format='json')

    def test_blocks_immediate_checkout_and_times_before_scheduled_end(self):
        for now in (self.start, self.end - timedelta(minutes=15), self.end - timedelta(seconds=1)):
            with self.subTest(now=now):
                response = self.checkout_at(now)
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('11:00', str(response.data['errors']['schedule']))
                self.schedule.refresh_from_db()
                self.assertEqual(self.schedule.status, BookingSchedule.Status.IN_PROGRESS)
                self.assertIsNone(self.schedule.actual_end)

    def test_allows_checkout_at_scheduled_end(self):
        response = self.checkout_at(self.end)
        self.assertEqual(response.status_code, 200, response.data)
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.actual_end, self.end)
        self.assertEqual(self.schedule.status, BookingSchedule.Status.COMPLETED)

    def test_allows_checkout_fifteen_minutes_after_end(self):
        response = self.checkout_at(self.end + timedelta(minutes=15))
        self.assertEqual(response.status_code, 200, response.data)

    def test_includes_the_exact_deadline(self):
        deadline = get_checkout_deadline(self.schedule)
        result = WorkerMyScheduleSerializer(self.schedule).data
        self.assertEqual(datetime.fromisoformat(result['check_out_until']), deadline)
        with patch('apps.worker.assignment_service.timezone.now', return_value=deadline):
            handle_missed_checkouts()
        self.assertEqual(self.checkout_at(deadline).status_code, 200)

    def test_after_deadline_only_automatic_completion_can_finish_the_schedule(self):
        now = get_checkout_deadline(self.schedule) + timedelta(seconds=1)
        response = self.checkout_at(now)
        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn('không thể tự check-out', str(response.data['errors']['schedule']))
        with patch('apps.worker.assignment_service.timezone.now', return_value=now):
            handle_missed_checkouts()
        self.schedule.refresh_from_db()
        self.assertEqual(self.schedule.status, BookingSchedule.Status.COMPLETED)
        self.assertEqual(self.schedule.actual_end, self.end)

    def test_still_requires_both_photos_and_checkin(self):
        self.schedule.images.filter(image_type=BookingScheduleImage.ImageType.AFTER).delete()
        response = self.checkout_at(self.end)
        self.assertEqual(response.status_code, 400)
        self.assertIn('images', response.data['errors'])
        BookingSchedule.objects.filter(pk=self.schedule.pk).update(status=BookingSchedule.Status.PENDING)
        response = self.checkout_at(self.end)
        self.assertEqual(response.status_code, 400)
        self.assertIn('chưa được Check-in', str(response.data['errors']['schedule']))

    def test_only_the_assigned_worker_can_checkout(self):
        other = get_user_model().objects.create_user(
            username='checkout-other', email='checkout-other@test.com', role='WORKER',
        )
        self.client.force_authenticate(other)
        response = self.checkout_at(self.end)
        self.assertEqual(response.status_code, 400)
        self.assertIn('chưa nhận buổi làm việc', str(response.data['errors']['schedule']))
