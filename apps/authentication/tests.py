from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import PasswordResetOTP, WorkerProfile

User = get_user_model()


class RegistrationTests(APITestCase):
    def test_customer_registration_stores_profile_fields_on_user(self):
        response = self.client.post(reverse('register'), {
            'username': 'customer01',
            'email': 'customer01@example.com',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
            'gender': User.Gender.FEMALE,
            'birth_date': '1995-01-01',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username='customer01')
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertEqual(user.gender, User.Gender.FEMALE)
        self.assertFalse(hasattr(user, 'customer_profile'))

    def test_worker_registration_creates_pending_profile(self):
        response = self.client.post(reverse('worker-register'), {
            'username': 'worker01',
            'email': 'worker01@example.com',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username='worker01')
        self.assertEqual(user.role, User.Role.WORKER)
        self.assertEqual(user.worker_profile.status, WorkerProfile.Status.PENDING)


class CustomerProfileTests(APITestCase):
    def test_profile_updates_user_table(self):
        user = User.objects.create_user(
            username='customer-profile',
            email='profile@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(user)
        response = self.client.patch(reverse('customer-profile'), {
            'gender': User.Gender.MALE,
            'birth_date': '1990-06-15',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        user.refresh_from_db()
        self.assertEqual(user.gender, User.Gender.MALE)
        self.assertEqual(str(user.birth_date), '1990-06-15')


class PasswordResetOTPTests(APITestCase):
    def test_otp_hash_and_expiration(self):
        user = User.objects.create_user(
            username='otp-user',
            email='otp@example.com',
            password='CleanWise@2026!',
        )
        otp = PasswordResetOTP.objects.create(
            user=user,
            code_hash=PasswordResetOTP.make_code_hash('123456'),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        self.assertTrue(otp.check_code('123456'))
        self.assertFalse(otp.is_expired)
        otp.mark_verified()
        self.assertTrue(otp.is_verified)
        otp.mark_used()
        self.assertTrue(otp.is_used)
