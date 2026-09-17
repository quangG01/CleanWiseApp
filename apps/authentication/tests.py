from datetime import timedelta

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.bookings.models import Area, WorkerWorkingArea
from apps.services.models import Service
from .models import PasswordResetOTP, WorkerProfile, WorkerVerificationDocument

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
        self.assertIn('access', response.data['data'])
        self.assertIn('refresh', response.data['data'])

    def test_customer_registration_rejects_client_supplied_role(self):
        response = self.client.post(reverse('register'), {
            'username': 'not-a-worker',
            'email': 'not-a-worker@example.com',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
            'role': User.Role.WORKER,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('role', response.data['errors'])
        self.assertFalse(User.objects.filter(username='not-a-worker').exists())

    def test_customer_registration_normalizes_optional_blank_phone(self):
        response = self.client.post(reverse('register'), {
            'username': 'customer-phone',
            'email': 'CUSTOMER-PHONE@EXAMPLE.COM',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
            'phone_number': '',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username='customer-phone')
        self.assertEqual(user.email, 'customer-phone@example.com')
        self.assertIsNone(user.phone_number)

    def test_worker_registration_creates_pending_profile(self):
        response = self.client.post(reverse('worker-register'), {
            'username': 'worker01',
            'email': 'worker01@example.com',
            'phone_number': '0912345678',
            'first_name': 'An',
            'last_name': 'Nguyen',
            'gender': User.Gender.MALE,
            'birth_date': '1990-01-01',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user = User.objects.get(username='worker01')
        self.assertEqual(user.role, User.Role.WORKER)
        self.assertEqual(user.worker_profile.status, WorkerProfile.Status.DRAFT)
        self.assertEqual(
            response.data['data']['worker_profile'],
            {
                'id': user.worker_profile.id,
                'status': WorkerProfile.Status.DRAFT,
            },
        )

    def test_worker_registration_rejects_underage_user(self):
        underage_birth_date = timezone.localdate().replace(
            year=timezone.localdate().year - 17,
        )
        response = self.client.post(reverse('worker-register'), {
            'username': 'worker-underage',
            'email': 'worker-underage@example.com',
            'phone_number': '0987654321',
            'first_name': 'Binh',
            'last_name': 'Tran',
            'gender': User.Gender.OTHER,
            'birth_date': underage_birth_date.isoformat(),
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('birth_date', response.data['errors'])
        self.assertFalse(User.objects.filter(username='worker-underage').exists())

    def test_worker_registration_rejects_client_supplied_role(self):
        response = self.client.post(reverse('worker-register'), {
            'username': 'worker-role',
            'email': 'worker-role@example.com',
            'phone_number': '0901234567',
            'first_name': 'Chi',
            'last_name': 'Le',
            'gender': User.Gender.FEMALE,
            'birth_date': '1992-05-10',
            'password': 'CleanWise@2026!',
            'password_confirm': 'CleanWise@2026!',
            'role': User.Role.ADMIN,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('role', response.data['errors'])
        self.assertFalse(User.objects.filter(username='worker-role').exists())


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


class WorkerProfileServiceTests(APITestCase):
    def setUp(self):
        self.worker = User.objects.create_user(
            username='profile-service-worker',
            email='profile-service-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.profile = WorkerProfile.objects.create(user=self.worker)
        self.active_service = Service.objects.create(
            code='PROFILE_HOME_CLEANING',
            section_code='CLEANING',
            name='Dọn nhà',
            description='Dịch vụ dọn nhà',
            form_schema={},
            pricing_config={},
        )
        self.other_service = Service.objects.create(
            code='PROFILE_SOFA_CLEANING',
            section_code='CLEANING',
            name='Giặt sofa',
            description='Dịch vụ giặt sofa',
            form_schema={},
            pricing_config={},
        )
        self.inactive_service = Service.objects.create(
            code='PROFILE_INACTIVE_SERVICE',
            section_code='CLEANING',
            name='Dịch vụ tạm ngừng',
            description='Dịch vụ không còn nhận đăng ký',
            form_schema={},
            pricing_config={},
            is_active=False,
        )
        self.client.force_authenticate(self.worker)

    def test_worker_can_select_one_registered_service(self):
        response = self.client.patch(reverse('worker-profile'), {
            'service_id': self.active_service.id,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.registered_service_id, self.active_service.id)
        self.assertEqual(
            response.data['data']['registered_service']['id'],
            self.active_service.id,
        )
        self.assertNotIn('service_id', response.data['data'])

    def test_selecting_another_service_replaces_previous_service(self):
        self.profile.registered_service = self.active_service
        self.profile.save(update_fields=['registered_service'])

        response = self.client.patch(reverse('worker-profile'), {
            'service_id': self.other_service.id,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.registered_service_id, self.other_service.id)

    def test_worker_can_clear_registered_service(self):
        self.profile.registered_service = self.active_service
        self.profile.save(update_fields=['registered_service'])

        response = self.client.patch(reverse('worker-profile'), {
            'service_id': None,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.registered_service_id)
        self.assertIsNone(response.data['data']['registered_service'])

    def test_worker_cannot_select_inactive_service(self):
        response = self.client.patch(reverse('worker-profile'), {
            'service_id': self.inactive_service.id,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.registered_service_id)

    def test_service_list_only_returns_active_choices(self):
        response = self.client.get(reverse('service-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = {service['id'] for service in response.data['data']}
        self.assertIn(self.active_service.id, returned_ids)
        self.assertIn(self.other_service.id, returned_ids)
        self.assertNotIn(self.inactive_service.id, returned_ids)


class WorkerProfileReadAndCompletenessTests(APITestCase):
    def setUp(self):
        self.worker = User.objects.create_user(
            username='complete-profile-worker',
            email='complete-profile-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
            first_name='An',
            last_name='Nguyễn',
            phone_number='0911111111',
            gender=User.Gender.MALE,
            birth_date='1990-01-01',
        )
        self.profile = WorkerProfile.objects.create(user=self.worker)
        self.service = Service.objects.create(
            code='PROFILE_COMPLETENESS_SERVICE',
            section_code='CLEANING',
            name='Dọn nhà tiêu chuẩn',
            description='Dịch vụ dùng kiểm tra hồ sơ',
            form_schema={},
            pricing_config={},
        )
        self.client.force_authenticate(self.worker)

    def test_get_profile_returns_missing_fields_without_changing_status(self):
        response = self.client.get(reverse('worker-profile'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(response.data['data']['is_complete'])
        self.assertSetEqual(
            set(response.data['data']['missing_fields']),
            {'identity_number', 'portrait', 'service_id', 'identity_front', 'identity_back', 'working_areas'},
        )
        self.assertEqual(response.data['data']['status'], WorkerProfile.Status.DRAFT)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.DRAFT)

    def test_get_profile_reports_complete_when_all_required_data_exists(self):
        self.profile.identity_number = '012345678901'
        self.profile.avatar = 'https://example.com/portrait.jpg'
        self.profile.registered_service = self.service
        self.profile.save(update_fields=['identity_number', 'avatar', 'registered_service'])
        WorkerVerificationDocument.objects.create(
            worker=self.worker,
            document_type=WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
            file='https://example.com/front.jpg',
            file_type=WorkerVerificationDocument.FileType.IMAGE,
        )
        WorkerVerificationDocument.objects.create(
            worker=self.worker,
            document_type=WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
            file='https://example.com/back.jpg',
            file_type=WorkerVerificationDocument.FileType.IMAGE,
        )
        area = Area.objects.create(name='Bến Nghé profile', city='TP.HCM')
        WorkerWorkingArea.objects.create(worker=self.worker, area=area)

        response = self.client.get(reverse('worker-profile'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertTrue(response.data['data']['is_complete'])
        self.assertEqual(response.data['data']['missing_fields'], [])
        self.assertEqual(response.data['data']['completion_percent'], 100)

    def test_patch_cannot_change_read_only_approval_fields(self):
        response = self.client.patch(reverse('worker-profile'), {
            'role': User.Role.ADMIN,
            'status': WorkerProfile.Status.ACTIVE,
            'average_rating': '5.00',
            'total_completed_jobs': 99,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.worker.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.worker.role, User.Role.WORKER)
        self.assertEqual(self.profile.status, WorkerProfile.Status.DRAFT)
        self.assertEqual(self.profile.average_rating, 0)
        self.assertEqual(self.profile.total_completed_jobs, 0)

    def test_customer_cannot_read_worker_profile(self):
        customer = User.objects.create_user(
            username='profile-customer',
            email='profile-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(customer)

        response = self.client.get(reverse('worker-profile'))

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class WorkerProfileSubmitTests(APITestCase):
    def setUp(self):
        self.worker = User.objects.create_user(
            username='submit-profile-worker',
            email='submit-profile-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
            first_name='Bình',
            last_name='Trần',
            phone_number='0922222222',
            gender=User.Gender.MALE,
            birth_date='1992-02-02',
        )
        self.profile = WorkerProfile.objects.create(
            user=self.worker,
            identity_number='123456789012',
            avatar='https://example.com/submit-portrait.jpg',
        )
        self.service = Service.objects.create(
            code='PROFILE_SUBMIT_SERVICE',
            section_code='CLEANING',
            name='Dọn nhà chuyên sâu',
            description='Dịch vụ dùng kiểm tra gửi hồ sơ',
            form_schema={},
            pricing_config={},
        )
        WorkerVerificationDocument.objects.create(
            worker=self.worker,
            document_type=WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
            file='https://example.com/submit-front.jpg',
            file_type=WorkerVerificationDocument.FileType.IMAGE,
        )
        WorkerVerificationDocument.objects.create(
            worker=self.worker,
            document_type=WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
            file='https://example.com/submit-back.jpg',
            file_type=WorkerVerificationDocument.FileType.IMAGE,
        )
        self.area = Area.objects.create(name='Thảo Điền submit', city='TP.HCM')
        self.client.force_authenticate(self.worker)

    def test_complete_draft_profile_can_be_submitted(self):
        self.profile.registered_service = self.service
        self.profile.save(update_fields=['registered_service'])
        WorkerWorkingArea.objects.create(worker=self.worker, area=self.area)

        response = self.client.post(reverse('worker-profile-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.PENDING)
        self.assertEqual(response.data['data']['status'], WorkerProfile.Status.PENDING)
        self.assertTrue(response.data['data']['is_complete'])

    def test_incomplete_profile_remains_draft_and_returns_missing_fields(self):
        response = self.client.post(reverse('worker-profile-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.DRAFT)
        self.assertSetEqual(
            set(response.data['errors']['missing_fields']),
            {'service_id', 'working_areas'},
        )
        self.assertIn('completion_percent', response.data['errors'])

    def test_inactive_registered_service_blocks_submission(self):
        self.service.is_active = False
        self.service.save(update_fields=['is_active'])
        self.profile.registered_service = self.service
        self.profile.save(update_fields=['registered_service'])
        WorkerWorkingArea.objects.create(worker=self.worker, area=self.area)

        response = self.client.post(reverse('worker-profile-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('service_id', response.data['errors']['missing_fields'])

    def test_inactive_working_area_blocks_submission(self):
        self.profile.registered_service = self.service
        self.profile.save(update_fields=['registered_service'])
        self.area.is_active = False
        self.area.save(update_fields=['is_active'])
        WorkerWorkingArea.objects.create(worker=self.worker, area=self.area)

        response = self.client.post(reverse('worker-profile-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('working_areas', response.data['errors']['missing_fields'])

    def test_non_draft_profile_cannot_be_submitted_again(self):
        self.profile.status = WorkerProfile.Status.PENDING
        self.profile.save(update_fields=['status'])

        response = self.client.post(reverse('worker-profile-submit'), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('status', response.data['errors'])


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
