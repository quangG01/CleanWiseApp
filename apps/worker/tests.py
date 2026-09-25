from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.services.models import Service

from .models import BookingAssignment, CustomerFavoriteWorker


User = get_user_model()


class CustomerFavoriteWorkerAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='favorite-customer', email='favorite-customer@example.com',
            password='CleanWise@2026!', role=User.Role.CUSTOMER,
        )
        self.other_customer = User.objects.create_user(
            username='other-favorite-customer', email='other-favorite-customer@example.com',
            password='CleanWise@2026!', role=User.Role.CUSTOMER,
        )
        self.worker = User.objects.create_user(
            username='favorite-worker', email='favorite-worker@example.com',
            password='CleanWise@2026!', role=User.Role.WORKER,
            first_name='Tùng', last_name='Nguyễn',
        )
        WorkerProfile.objects.create(
            user=self.worker, status=WorkerProfile.Status.ACTIVE,
            bio='Nhân viên vệ sinh', experience_years=2,
            average_rating='4.50', total_completed_jobs=7,
        )
        self.service = Service.objects.create(
            code='FAVORITE_WORKER_TEST', section_code='TEST',
            name='Dịch vụ kiểm thử yêu thích', description='Dịch vụ dùng trong test.',
            form_schema={}, pricing_config={},
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer, receiver_name='Khách hàng',
            receiver_phone='0900000001', address_line='01 Đường test', city='TP.HCM',
        )
        self.booking = Booking.objects.create(
            booking_code='FAVORITE-TEST-001', customer=self.customer,
            service=self.service, service_data={}, address=self.address,
        )
        now = timezone.now()
        self.schedule = BookingSchedule.objects.create(
            booking=self.booking, sequence_no=1,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=2),
        )
        self.assignment = BookingAssignment.objects.create(
            schedule=self.schedule, worker=self.worker,
            status=BookingAssignment.Status.ACCEPTED,
        )
        self.detail_url = reverse(
            'customer-favorite-worker-detail', kwargs={'worker_id': self.worker.id},
        )

    def test_customer_can_add_favorite_worker(self):
        self.client.force_authenticate(self.customer)
        response = self.client.put(self.detail_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data['data']['is_favorite'])
        self.assertEqual(response.data['data']['worker_id'], self.worker.id)
        self.assertTrue(CustomerFavoriteWorker.objects.filter(
            customer=self.customer, worker=self.worker,
        ).exists())

    def test_add_is_idempotent(self):
        self.client.force_authenticate(self.customer)
        first_response = self.client.put(self.detail_url, {}, format='json')
        second_response = self.client.put(self.detail_url, {}, format='json')

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(CustomerFavoriteWorker.objects.filter(
            customer=self.customer, worker=self.worker,
        ).count(), 1)

    def test_delete_hard_deletes_and_is_idempotent(self):
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        self.client.force_authenticate(self.customer)
        first_response = self.client.delete(self.detail_url)
        second_response = self.client.delete(self.detail_url)

        self.assertEqual(first_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(second_response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(CustomerFavoriteWorker.objects.filter(
            customer=self.customer, worker=self.worker,
        ).exists())

    def test_list_returns_only_authenticated_customers_favorites(self):
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('customer-favorite-worker-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['count'], 1)
        result = response.data['data']['results'][0]
        self.assertEqual(result['worker_id'], self.worker.id)
        self.assertEqual(result['experience_years'], 2)
        self.assertNotIn('email', result)
        self.assertNotIn('phone_number', result)

    def test_customer_cannot_favorite_unassigned_worker(self):
        self.client.force_authenticate(self.other_customer)
        response = self.client.put(self.detail_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        self.assertFalse(CustomerFavoriteWorker.objects.filter(
            customer=self.other_customer, worker=self.worker,
        ).exists())

    def test_customer_cannot_favorite_inactive_worker(self):
        self.worker.worker_profile.status = WorkerProfile.Status.SUSPENDED
        self.worker.worker_profile.save(update_fields=['status'])
        self.client.force_authenticate(self.customer)
        response = self.client.put(self.detail_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

    def test_worker_role_cannot_use_customer_favorite_api(self):
        self.client.force_authenticate(self.worker)
        response = self.client.put(self.detail_url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)

    def test_worker_profile_returns_favorite_state(self):
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse(
            'customer-worker-profile', kwargs={'worker_id': self.worker.id},
        ))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['data']['is_favorite'])

    def test_booking_worker_summary_returns_favorite_state(self):
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse(
            'customer-booking-detail', kwargs={'pk': self.booking.id},
        ))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        worker_data = response.data['data']['schedules'][0]['worker']
        self.assertTrue(worker_data['is_favorite'])

    def test_database_prevents_duplicate_favorite(self):
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)

        with self.assertRaises(IntegrityError), transaction.atomic():
            CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.worker)
