from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.services.models import Service
from apps.worker.models import BookingAssignment

from .models import Review


User = get_user_model()


class ReviewApiTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='review-customer', email='review-customer@example.com',
            password='CleanWise@2026!', role=User.Role.CUSTOMER,
        )
        self.other_customer = User.objects.create_user(
            username='other-review-customer', email='other-review-customer@example.com',
            password='CleanWise@2026!', role=User.Role.CUSTOMER,
        )
        self.worker = User.objects.create_user(
            username='review-worker', email='review-worker@example.com',
            password='CleanWise@2026!', role=User.Role.WORKER,
        )
        self.worker_profile = WorkerProfile.objects.create(
            user=self.worker, status=WorkerProfile.Status.ACTIVE,
        )
        self.admin = User.objects.create_user(
            username='review-admin', email='review-admin@example.com',
            password='CleanWise@2026!', role=User.Role.ADMIN,
        )
        self.service = Service.objects.create(
            code='REVIEW_SERVICE', section_code='CLEANING',
            name='Dọn nhà để kiểm thử review', description='Dịch vụ kiểm thử.',
            form_schema={}, pricing_config={},
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer, receiver_name='Khách Review',
            receiver_phone='0900000001', address_line='01 Đường Review', city='TP.HCM',
        )
        self.other_address = CustomerAddress.objects.create(
            customer=self.other_customer, receiver_name='Khách Khác',
            receiver_phone='0900000002', address_line='02 Đường Review', city='TP.HCM',
        )
        self.booking = self._create_booking(self.customer, self.address, 'REVIEW-001')
        self.assignment = self._create_assignment(self.booking, 1, completed=True)
        self.second_assignment = self._create_assignment(self.booking, 2, completed=True)
        self.pending_assignment = self._create_assignment(self.booking, 3, completed=False)
        other_booking = self._create_booking(self.other_customer, self.other_address, 'REVIEW-002')
        self.other_assignment = self._create_assignment(other_booking, 1, completed=True)

    def _create_booking(self, customer, address, code):
        return Booking.objects.create(
            booking_code=code, customer=customer, service=self.service,
            address=address, service_data={}, status=Booking.Status.COMPLETED,
        )

    def _create_assignment(self, booking, sequence_no, completed):
        start = timezone.now() - timedelta(days=sequence_no, hours=2)
        schedule = BookingSchedule.objects.create(
            booking=booking, sequence_no=sequence_no,
            scheduled_start=start, scheduled_end=start + timedelta(hours=2),
            actual_start=start,
            actual_end=start + timedelta(hours=2) if completed else None,
            status=(BookingSchedule.Status.COMPLETED if completed else BookingSchedule.Status.PENDING),
        )
        return BookingAssignment.objects.create(
            schedule=schedule, worker=self.worker,
            status=BookingAssignment.Status.ACCEPTED,
        )

    def _create_review(self, assignment=None, rating=5, comment='Làm việc tốt.'):
        self.client.force_authenticate(self.customer)
        return self.client.post(reverse('customer-review-list-create'), {
            'assignment_id': (assignment or self.assignment).id,
            'rating': rating,
            'comment': comment,
        }, format='json')

    def _image_file(self, name='review.jpg', content_type='image/jpeg'):
        return SimpleUploadedFile(name, b'fake-image-content', content_type=content_type)

    def test_customer_can_review_completed_accepted_assignment(self):
        response = self._create_review()
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        review = Review.objects.get()
        self.assertEqual(review.assignment, self.assignment)
        self.assertEqual(review.rating, 5)
        self.worker_profile.refresh_from_db()
        self.assertEqual(self.worker_profile.average_rating, Decimal('5.00'))

    def test_customer_cannot_review_same_assignment_twice(self):
        self.assertEqual(self._create_review().status_code, status.HTTP_201_CREATED)
        response = self._create_review()
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(Review.objects.count(), 1)

    def test_customer_can_review_same_worker_for_different_schedules(self):
        first = self._create_review(self.assignment, rating=5)
        second = self._create_review(self.second_assignment, rating=4)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_201_CREATED, second.data)
        self.assertEqual(Review.objects.filter(assignment__worker=self.worker).count(), 2)
        self.worker_profile.refresh_from_db()
        self.assertEqual(self.worker_profile.average_rating, Decimal('4.50'))

    def test_customer_cannot_review_incomplete_schedule(self):
        response = self._create_review(self.pending_assignment)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('assignment_id', response.data['errors'])

    def test_customer_cannot_review_another_customers_assignment(self):
        response = self._create_review(self.other_assignment)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('assignment_id', response.data['errors'])

    def test_eligible_endpoint_only_returns_completed_unreviewed_assignments(self):
        self.assertEqual(self._create_review(self.assignment).status_code, status.HTTP_201_CREATED)
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('customer-review-eligible'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        assignment_ids = {item['assignment_id'] for item in response.data['data']}
        self.assertEqual(assignment_ids, {self.second_assignment.id})

    def test_customer_can_update_own_review_and_average(self):
        create_response = self._create_review(rating=5)
        review_id = create_response.data['data']['id']
        response = self.client.patch(reverse('customer-review-detail', args=[review_id]), {
            'rating': 3, 'comment': 'Cập nhật đánh giá.',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.worker_profile.refresh_from_db()
        self.assertEqual(self.worker_profile.average_rating, Decimal('3.00'))

    def test_worker_can_view_reviews_and_summary(self):
        self._create_review(self.assignment, rating=5)
        self._create_review(self.second_assignment, rating=3)
        self.client.force_authenticate(self.worker)
        list_response = self.client.get(reverse('worker-review-list'))
        summary_response = self.client.get(reverse('worker-review-summary'))
        self.assertEqual(list_response.status_code, status.HTTP_200_OK, list_response.data)
        self.assertEqual(len(list_response.data['data']), 2)
        self.assertEqual(summary_response.data['data']['average_rating'], '4.00')
        self.assertEqual(summary_response.data['data']['total_reviews'], 2)
        self.assertEqual(summary_response.data['data']['rating_distribution']['5'], 1)
        self.assertEqual(summary_response.data['data']['rating_distribution']['3'], 1)

    def test_admin_can_hide_and_reply_to_review(self):
        create_response = self._create_review(rating=5)
        review_id = create_response.data['data']['id']
        self.client.force_authenticate(self.admin)
        visibility_response = self.client.patch(
            reverse('admin-review-visibility', args=[review_id]),
            {'is_visible': False}, format='json',
        )
        reply_response = self.client.post(
            reverse('admin-review-reply', args=[review_id]),
            {'reply': 'Cảm ơn bạn đã góp ý.'}, format='json',
        )
        self.assertEqual(visibility_response.status_code, status.HTTP_200_OK, visibility_response.data)
        self.assertEqual(reply_response.status_code, status.HTTP_200_OK, reply_response.data)
        review = Review.objects.get(pk=review_id)
        self.assertFalse(review.is_visible)
        self.assertEqual(review.replied_by, self.admin)
        self.assertIsNotNone(review.replied_at)
        self.worker_profile.refresh_from_db()
        self.assertEqual(self.worker_profile.average_rating, Decimal('0.00'))

    @patch('apps.reviews.review_service.upload_image')
    def test_customer_can_create_review_with_multiple_images(self, upload_mock):
        upload_mock.side_effect = [
            {
                'url': 'https://res.cloudinary.com/demo/image/upload/v1/cleanwise/review_images/one.jpg',
                'public_id': 'cleanwise/review_images/one',
            },
            {
                'url': 'https://res.cloudinary.com/demo/image/upload/v1/cleanwise/review_images/two.png',
                'public_id': 'cleanwise/review_images/two',
            },
        ]
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-review-list-create'), {
            'assignment_id': self.assignment.id,
            'rating': 5,
            'comment': 'Có ảnh minh họa.',
            'images': [self._image_file(), self._image_file('review.png', 'image/png')],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(len(response.data['data']['images']), 2)
        self.assertEqual(Review.objects.get().images.count(), 2)
        self.assertEqual(upload_mock.call_count, 2)

    @patch('apps.reviews.review_service.ensure_cloudinary_configured')
    @patch('apps.reviews.review_service.cloudinary.uploader.destroy')
    @patch('apps.reviews.review_service.upload_image')
    def test_customer_can_add_and_delete_images_when_updating(
        self, upload_mock, destroy_mock, ensure_configured_mock,
    ):
        review = Review.objects.create(assignment=self.assignment, rating=5)
        old_image = review.images.create(
            image='https://res.cloudinary.com/demo/image/upload/v1/cleanwise/review_images/old.jpg'
        )
        upload_mock.return_value = {
            'url': 'https://res.cloudinary.com/demo/image/upload/v1/cleanwise/review_images/new.jpg',
            'public_id': 'cleanwise/review_images/new',
        }
        destroy_mock.return_value = {'result': 'ok'}
        self.client.force_authenticate(self.customer)

        response = self.client.patch(reverse('customer-review-detail', args=[review.id]), {
            'rating': 4,
            'images': [self._image_file('new.jpg')],
            'delete_image_ids': [old_image.id],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['rating'], 4)
        self.assertEqual(len(response.data['data']['images']), 1)
        self.assertIn('/new.jpg', response.data['data']['images'][0]['image'])
        self.assertFalse(review.images.filter(pk=old_image.id).exists())
        ensure_configured_mock.assert_called_once()
        destroy_mock.assert_called_once_with(
            'cleanwise/review_images/old', resource_type='image',
        )

    @patch('apps.reviews.review_service.upload_image')
    def test_review_rejects_more_than_maximum_images(self, upload_mock):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-review-list-create'), {
            'assignment_id': self.assignment.id,
            'rating': 5,
            'images': [self._image_file(f'review-{index}.jpg') for index in range(6)],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('images', response.data['errors'])
        upload_mock.assert_not_called()

    @patch('apps.reviews.review_service.upload_image')
    def test_review_rejects_unsupported_image_type(self, upload_mock):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-review-list-create'), {
            'assignment_id': self.assignment.id,
            'rating': 5,
            'images': [self._image_file('review.pdf', 'application/pdf')],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('images', response.data['errors'])
        upload_mock.assert_not_called()

    @override_settings(REVIEW_IMAGE_MAX_SIZE=10)
    @patch('apps.reviews.review_service.upload_image')
    def test_review_rejects_image_larger_than_configured_limit(self, upload_mock):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-review-list-create'), {
            'assignment_id': self.assignment.id,
            'rating': 5,
            'images': [SimpleUploadedFile('large.jpg', b'12345678901', content_type='image/jpeg')],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('images', response.data['errors'])
        upload_mock.assert_not_called()

    @patch('apps.reviews.review_service.ensure_cloudinary_configured')
    def test_customer_cannot_delete_image_from_another_review(self, ensure_configured_mock):
        first_review = Review.objects.create(assignment=self.assignment, rating=5)
        second_review = Review.objects.create(assignment=self.second_assignment, rating=4)
        other_image = second_review.images.create(
            image='https://res.cloudinary.com/demo/image/upload/v1/cleanwise/review_images/other.jpg'
        )
        self.client.force_authenticate(self.customer)

        response = self.client.patch(reverse('customer-review-detail', args=[first_review.id]), {
            'delete_image_ids': [other_image.id],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('delete_image_ids', response.data['errors'])
        self.assertTrue(second_review.images.filter(pk=other_image.id).exists())
        ensure_configured_mock.assert_called_once()

    @patch('apps.reviews.review_service.cloudinary.uploader.destroy')
    @patch('apps.reviews.review_service.upload_image')
    def test_cloudinary_failure_rolls_back_review_and_cleans_uploaded_images(
        self, upload_mock, destroy_mock,
    ):
        upload_mock.side_effect = [
            {
                'url': 'https://res.cloudinary.com/demo/image/upload/v1/cleanwise/review_images/first.jpg',
                'public_id': 'cleanwise/review_images/first',
            },
            RuntimeError('Cloudinary unavailable'),
        ]
        destroy_mock.return_value = {'result': 'ok'}
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-review-list-create'), {
            'assignment_id': self.assignment.id,
            'rating': 5,
            'images': [self._image_file('first.jpg'), self._image_file('second.jpg')],
        }, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(Review.objects.exists())
        destroy_mock.assert_called_once_with(
            'cleanwise/review_images/first', resource_type='image',
        )
