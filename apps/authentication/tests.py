from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch
from datetime import timedelta

from apps.common.encryption import decrypt_value, encrypt_value
from .models import CustomerProfile, WorkerProfile, WorkerVerificationDocument


User = get_user_model()


class WorkerRegisterAPITests(APITestCase):
    def setUp(self):
        self.url = reverse('worker-register')
        self.payload = {
            'username': 'worker01',
            'email': 'worker01@example.com',
            'phone_number': '0912345678',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
            'first_name': 'An',
            'last_name': 'Nguyen',
        }

    def test_register_worker_creates_draft_profile_and_tokens(self):
        response = self.client.post(self.url, self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='worker01')
        self.assertEqual(user.role, User.Role.WORKER)
        self.assertTrue(user.check_password(self.payload['password']))
        self.assertEqual(user.worker_profile.status, WorkerProfile.Status.DRAFT)
        self.assertFalse(CustomerProfile.objects.filter(user=user).exists())
        self.assertEqual(response.data['data']['profile_status'], WorkerProfile.Status.DRAFT)
        self.assertIn('access', response.data['data'])
        self.assertIn('refresh', response.data['data'])

    def test_register_worker_ignores_client_role(self):
        payload = {**self.payload, 'role': User.Role.CUSTOMER}

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        user = User.objects.get(username='worker01')
        self.assertEqual(user.role, User.Role.WORKER)
        self.assertEqual(user.worker_profile.status, WorkerProfile.Status.DRAFT)

    def test_register_worker_rejects_duplicate_email(self):
        User.objects.create_user(
            username='existing',
            email=self.payload['email'],
            password='Existing@2026!',
        )

        response = self.client.post(self.url, self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username='worker01').exists())


class WorkerProfileUpdateAPITests(APITestCase):
    def setUp(self):
        self.url = reverse('worker-profile')
        self.user = User.objects.create_user(
            username='worker-profile',
            email='worker-profile@example.com',
            phone_number='0911111111',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.profile = WorkerProfile.objects.create(user=self.user)
        self.client.force_authenticate(self.user)

    def test_partial_update_keeps_draft_and_returns_missing_fields(self):
        response = self.client.patch(
            self.url,
            {'full_name': 'Nguyễn Văn An', 'gender': WorkerProfile.Gender.MALE},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.full_name, 'Nguyễn Văn An')
        self.assertEqual(self.profile.status, WorkerProfile.Status.DRAFT)
        self.assertFalse(response.data['data']['is_complete'])
        self.assertIn('identity_front', response.data['data']['missing_fields'])

    def test_identity_images_must_be_uploaded_as_a_pair(self):
        response = self.client.patch(
            self.url,
            {
                'identity_front': SimpleUploadedFile(
                    'front.jpg', b'front', content_type='image/jpeg'
                ),
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('identity_documents', response.data['errors'])
        self.assertFalse(self.user.verification_documents.exists())

    @patch('apps.authentication.serializers.upload_file')
    @patch('apps.authentication.serializers.upload_image')
    def test_complete_update_moves_profile_to_pending_and_encrypts_bank_account(
        self,
        upload_image_mock,
        upload_file_mock,
    ):
        upload_image_mock.return_value = {
            'url': 'https://cdn.example.com/portrait.jpg',
            'public_id': 'portrait',
        }
        upload_file_mock.side_effect = [
            {'url': 'https://cdn.example.com/identity-front.jpg', 'public_id': 'front'},
            {'url': 'https://cdn.example.com/identity-back.jpg', 'public_id': 'back'},
            {'url': 'https://cdn.example.com/certificate.pdf', 'public_id': 'certificate'},
        ]
        today = timezone.localdate()
        payload = {
            'full_name': 'Nguyễn Văn An',
            'gender': WorkerProfile.Gender.MALE,
            'birth_date': '1990-01-01',
            'portrait': SimpleUploadedFile('portrait.jpg', b'portrait', content_type='image/jpeg'),
            'identity_number': '001090123456',
            'identity_issued_date': str(today - timedelta(days=365)),
            'identity_issued_place': 'Cục Cảnh sát QLHC về TTXH',
            'identity_front': SimpleUploadedFile('front.jpg', b'front', content_type='image/jpeg'),
            'identity_back': SimpleUploadedFile('back.jpg', b'back', content_type='image/jpeg'),
            'province': 'Thành phố Hồ Chí Minh',
            'ward': 'Phường Bến Nghé',
            'address_line': '01 Lê Lợi',
            'certificate_file': SimpleUploadedFile(
                'certificate.pdf', b'certificate', content_type='application/pdf'
            ),
            'certificate_number': 'CLEAN-2026-001',
            'certificate_expiry_date': str(today + timedelta(days=365)),
            'bank_code': 'VCB',
            'bank_account_number': '1234567890',
            'bank_account_holder': 'NGUYEN VAN AN',
            'terms_accepted': True,
        }

        response = self.client.patch(self.url, payload, format='multipart')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.PENDING)
        self.assertIsNotNone(self.profile.submitted_at)
        self.assertNotEqual(self.profile.bank_account_number_encrypted, '1234567890')
        self.assertEqual(decrypt_value(self.profile.bank_account_number_encrypted), '1234567890')
        self.assertEqual(response.data['data']['bank_account_number'], '******7890')
        self.assertTrue(response.data['data']['is_complete'])
        self.assertEqual(response.data['data']['missing_fields'], [])

    def test_customer_cannot_update_worker_profile(self):
        customer = User.objects.create_user(
            username='customer-profile',
            email='customer-profile@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(customer)

        response = self.client.patch(self.url, {'full_name': 'Customer'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_pending_profile_can_still_be_updated(self):
        self.profile.status = WorkerProfile.Status.PENDING
        self.profile.submitted_at = timezone.now() - timedelta(days=1)
        self.profile.save(update_fields=['status', 'submitted_at'])

        response = self.client.patch(
            self.url,
            {'address_line': '02 Nguyễn Huệ'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.address_line, '02 Nguyễn Huệ')
        self.assertEqual(self.profile.status, WorkerProfile.Status.PENDING)

    def test_active_profile_can_update_non_sensitive_address(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])

        response = self.client.patch(
            self.url,
            {'province': 'Hà Nội', 'ward': 'Phường Ba Đình'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.province, 'Hà Nội')
        self.assertEqual(self.profile.ward, 'Phường Ba Đình')
        self.assertEqual(self.profile.status, WorkerProfile.Status.ACTIVE)

    def test_active_profile_cannot_update_sensitive_information(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.full_name = 'Tên đã duyệt'
        self.profile.save(update_fields=['status', 'full_name'])

        response = self.client.patch(
            self.url,
            {'full_name': 'Tên muốn thay đổi'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('sensitive_fields', response.data['errors'])
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.full_name, 'Tên đã duyệt')
        self.assertEqual(self.profile.status, WorkerProfile.Status.ACTIVE)


class AdminWorkerProfileAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin-reviewer',
            email='admin-reviewer@example.com',
            password='Admin@2026!',
            role=User.Role.ADMIN,
        )
        self.pending_user = User.objects.create_user(
            username='pending-worker',
            email='pending-worker@example.com',
            phone_number='0922222222',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.pending_profile = WorkerProfile.objects.create(
            user=self.pending_user,
            status=WorkerProfile.Status.PENDING,
            submitted_at=timezone.now(),
        )
        self.draft_user = User.objects.create_user(
            username='draft-worker',
            email='draft-worker@example.com',
            phone_number='0933333333',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.draft_profile = WorkerProfile.objects.create(
            user=self.draft_user,
            status=WorkerProfile.Status.DRAFT,
        )
        self.client.force_authenticate(self.admin)

    def _complete_pending_profile(self):
        today = timezone.localdate()
        profile = self.pending_profile
        profile.full_name = 'Nguyễn Văn Duyệt'
        profile.gender = WorkerProfile.Gender.MALE
        profile.birth_date = today.replace(year=today.year - 25)
        profile.identity_number = '001090654321'
        profile.identity_issued_date = today - timedelta(days=365)
        profile.identity_issued_place = 'Cục Cảnh sát QLHC về TTXH'
        profile.avatar = 'https://cdn.example.com/portrait.jpg'
        profile.province = 'Thành phố Hồ Chí Minh'
        profile.ward = 'Phường Bến Nghé'
        profile.address_line = '01 Đồng Khởi'
        profile.certificate_number = 'CERT-001'
        profile.certificate_expiry_date = today + timedelta(days=365)
        profile.bank_code = 'VCB'
        profile.bank_account_number_encrypted = encrypt_value('1234567890')
        profile.bank_account_last4 = '7890'
        profile.bank_account_holder = 'NGUYEN VAN DUYET'
        profile.terms_accepted_at = timezone.now()
        profile.save()
        for document_type in (
            WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
            WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
            WorkerVerificationDocument.DocumentType.CERTIFICATE,
        ):
            WorkerVerificationDocument.objects.create(
                worker=self.pending_user,
                document_type=document_type,
                file=f'https://cdn.example.com/{document_type.lower()}.jpg',
                file_type=WorkerVerificationDocument.FileType.IMAGE,
            )
        return profile

    def test_list_defaults_to_pending_profiles(self):
        response = self.client.get(reverse('admin-worker-profile-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item['id'] for item in response.data]
        self.assertIn(self.pending_profile.id, returned_ids)
        self.assertNotIn(self.draft_profile.id, returned_ids)

    def test_list_can_filter_draft_profiles(self):
        response = self.client.get(
            reverse('admin-worker-profile-list'),
            {'status': WorkerProfile.Status.DRAFT},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [item['id'] for item in response.data]
        self.assertIn(self.draft_profile.id, returned_ids)
        self.assertNotIn(self.pending_profile.id, returned_ids)

    def test_admin_can_approve_complete_pending_profile(self):
        self._complete_pending_profile()
        url = reverse('admin-worker-status-update', args=[self.pending_profile.id])

        response = self.client.patch(
            url,
            {'status': WorkerProfile.Status.ACTIVE},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.pending_profile.refresh_from_db()
        self.assertEqual(self.pending_profile.status, WorkerProfile.Status.ACTIVE)
        self.assertEqual(self.pending_profile.approved_by, self.admin)
        self.assertIsNotNone(self.pending_profile.approved_at)

    def test_rejection_requires_reason(self):
        url = reverse('admin-worker-status-update', args=[self.pending_profile.id])

        response = self.client.patch(
            url,
            {'status': WorkerProfile.Status.REJECTED},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('reason', response.data['errors'])
        self.pending_profile.refresh_from_db()
        self.assertEqual(self.pending_profile.status, WorkerProfile.Status.PENDING)

    def test_non_admin_cannot_review_worker_profile(self):
        self.client.force_authenticate(self.pending_user)
        url = reverse('admin-worker-status-update', args=[self.pending_profile.id])

        response = self.client.patch(
            url,
            {'status': WorkerProfile.Status.REJECTED, 'reason': 'Không hợp lệ'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
