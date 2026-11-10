from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.bookings.models import Booking, BookingSchedule
from apps.services.models import Service
from apps.worker.models import BookingAssignment

from .models import Complaint, ComplaintIssueType


class ComplaintAttachmentTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.customer = users.create_user(username='customer', email='customer@example.test', role='CUSTOMER')
        cls.worker = users.create_user(username='worker', email='worker@example.test', role='WORKER')
        address = CustomerAddress.objects.create(customer=cls.customer, address_line='Địa chỉ mẫu', city='TP.HCM')
        service = Service.objects.create(
            name='Dọn nhà', code='CLEAN', section_code='HOME_CLEANING', form_schema={}, pricing_config={},
        )
        booking = Booking.objects.create(
            booking_code='CW-DEMO', customer=cls.customer, address=address, service=service,
            service_data={}, status=Booking.Status.COMPLETED,
        )
        end = timezone.now() - timedelta(hours=1)
        schedule = BookingSchedule.objects.create(
            booking=booking, sequence_no=1, scheduled_start=end - timedelta(hours=2),
            scheduled_end=end, status=BookingSchedule.Status.COMPLETED,
        )
        BookingAssignment.objects.create(
            schedule=schedule, worker=cls.worker, status=BookingAssignment.Status.ACCEPTED,
        )
        issue = ComplaintIssueType.objects.create(code='OTHER', name='Sự cố khác')
        cls.payload = {'booking': booking.pk, 'schedule': schedule.pk, 'issue_type': issue.pk, 'content': 'Ảnh minh chứng'}

    @patch('apps.complaints.views.upload_image')
    def test_uploaded_files_are_returned_in_the_complaint_detail(self, upload_image):
        with BytesIO() as buffer:
            Image.new('RGB', (2, 2), 'blue').save(buffer, format='PNG')
            image = buffer.getvalue()

        def upload(file, **kwargs):
            self.assertEqual(file.read(), image)
            return {'url': 'https://example.test/complaints/proof.png', 'public_id': 'complaints/proof'}

        upload_image.side_effect = upload
        for role in ('customer', 'worker'):
            with self.subTest(role=role):
                self.client.force_authenticate(getattr(self, role))
                response = self.client.post(
                    reverse(f'{role}-complaint-list-create'),
                    {**self.payload, 'attachments': SimpleUploadedFile('proof.png', image, content_type='image/png')},
                    format='multipart',
                )
                self.assertEqual(response.status_code, 201, response.data)
                complaint = Complaint.objects.get(reporter=getattr(self, role))
                detail = self.client.get(reverse(f'{role}-complaint-detail', args=[complaint.pk]))
                self.assertEqual(detail.status_code, 200)
                self.assertEqual(len(detail.data['attachments']), 1)
                self.assertEqual(detail.data['attachments'][0]['file'], 'https://example.test/complaints/proof.png')
                self.assertEqual(complaint.attachments.get().public_id, 'complaints/proof')
        self.assertEqual(upload_image.call_count, 2)

    def test_text_in_place_of_an_attachment_is_rejected(self):
        for role in ('customer', 'worker'):
            with self.subTest(role=role):
                self.client.force_authenticate(getattr(self, role))
                response = self.client.post(
                    reverse(f'{role}-complaint-list-create'),
                    {**self.payload, 'attachments': '[object Object]'},
                    format='multipart',
                )
                self.assertEqual(response.status_code, 400, response.data)
                self.assertIn('attachments', response.data)
        self.assertFalse(Complaint.objects.exists())

    def test_complaint_can_still_be_submitted_without_optional_photos(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-complaint-list-create'), self.payload, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data['attachments'], [])
