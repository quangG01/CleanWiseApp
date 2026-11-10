from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.services.models import Service
from .models import PasswordResetOTP, WorkerEmailChange, WorkerProfile


class WorkerChangesTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.worker = users.create_user(
            username='worker', email='old@example.test', role='WORKER', password='WorkerPass2026!',
        )
        cls.admin = users.create_user(username='admin', email='admin@example.test', role='ADMIN')
        cls.old_service = Service.objects.create(
            name='Dọn nhà', code='CLEAN', section_code='HOME_CLEANING', form_schema={}, pricing_config={},
        )
        cls.new_service = Service.objects.create(
            name='Giặt ủi', code='LAUNDRY', section_code='LAUNDRY', form_schema={}, pricing_config={},
        )
        cls.profile = WorkerProfile.objects.create(
            user=cls.worker, status='ACTIVE', registered_service=cls.old_service,
        )

    def setUp(self):
        self.client.force_authenticate(self.worker)

    def test_active_worker_can_edit_work_info_but_not_bypass_identity_or_service_review(self):
        url = reverse('worker-profile')
        for data in ({'first_name': 'Tên khác'}, {'birth_date': '1990-01-01'},
                     {'identity_number': '123456789012'}, {'service_id': self.new_service.pk},
                     {'email': 'unverified@example.test'}):
            self.assertEqual(self.client.patch(url, data, format='json').status_code, 400)
        response = self.client.patch(url, {'bio': 'Giới thiệu mới', 'experience_years': 2}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, 'Giới thiệu mới')
        self.assertEqual(self.profile.experience_years, 2)
        self.assertEqual(self.profile.registered_service, self.old_service)
        self.assertEqual(self.profile.status, 'ACTIVE')

    def test_service_request_changes_service_only_after_admin_approval(self):
        url = reverse('worker-service-request')
        result = self.client.post(url, {'service_id': self.new_service.pk}, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.profile.refresh_from_db()
        token = str(self.profile.service_request_token)
        self.assertEqual(self.profile.registered_service, self.old_service)
        self.assertEqual(self.profile.requested_service, self.new_service)
        self.assertEqual(self.client.post(url, {'service_id': self.new_service.pk}, format='json').status_code, 400)
        review_url = reverse('admin-worker-service-review', args=[self.profile.pk])
        payload = {'decision': 'APPROVE', 'request_token': token}
        self.assertEqual(self.client.patch(review_url, payload, format='json').status_code, 403)

        self.client.force_authenticate(self.admin)
        result = self.client.patch(review_url, payload, format='json')
        self.assertEqual(result.status_code, 200, result.data)
        self.assertEqual(self.client.patch(review_url, payload, format='json').status_code, 409)
        self.profile.refresh_from_db()
        self.assertIsNone(self.profile.requested_service)
        self.assertEqual(self.profile.registered_service, self.new_service)
        self.assertEqual(list(self.profile.review_events.values_list('action', flat=True)), [
            'SERVICE_APPROVED', 'SERVICE_REQUESTED',
        ])

    def test_rejected_service_request_returns_reason_to_worker(self):
        url = reverse('worker-service-request')
        self.assertEqual(self.client.post(url, {'service_id': self.new_service.pk}, format='json').status_code, 200)
        self.profile.refresh_from_db()
        self.client.force_authenticate(self.admin)
        response = self.client.patch(reverse('admin-worker-service-review', args=[self.profile.pk]), {
            'request_token': str(self.profile.service_request_token), 'decision': 'REJECT', 'reason': 'Cần bổ sung kỹ năng.',
        }, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.registered_service, self.old_service)
        self.client.force_authenticate(self.worker)
        self.assertEqual(self.client.get(url).data['data'], {
            'action': 'SERVICE_REJECTED', 'reason': 'Cần bổ sung kỹ năng.',
        })

    def test_email_requires_password_and_verification_of_new_address(self):
        start = reverse('worker-email-change-request')
        confirm = reverse('worker-email-change-confirm')
        payload = {'email': 'NEW@example.test', 'password': 'WorkerPass2026!'}
        self.assertEqual(self.client.post(start, {**payload, 'password': 'wrong'}, format='json').status_code, 400)
        with patch('apps.authentication.worker_change_views.randbelow', return_value=123456), patch(
            'apps.authentication.worker_change_views.send_otp_email.delay',
        ) as send, self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(start, payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(send.call_args.args[0], 'new@example.test')
        self.assertIn('123456', send.call_args.args[2])
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.email, 'old@example.test')
        otp = PasswordResetOTP.objects.create(user=self.worker, code_hash='old-code', expires_at=timezone.now() + timedelta(minutes=5))

        self.assertEqual(self.client.post(confirm, {**payload, 'email': 'other@example.test', 'code': '123456'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(confirm, {**payload, 'code': '000000'}, format='json').status_code, 400)
        self.assertEqual(WorkerEmailChange.objects.get(user=self.worker).attempts, 1)
        response = self.client.post(confirm, {**payload, 'code': '123456'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.worker.refresh_from_db()
        otp.refresh_from_db()
        self.assertEqual(self.worker.email, 'new@example.test')
        self.assertIsNotNone(otp.used_at)
        self.assertFalse(WorkerEmailChange.objects.filter(user=self.worker).exists())

    def test_expired_or_exhausted_email_code_cannot_change_the_account(self):
        email = 'new@example.test'
        change = WorkerEmailChange.objects.create(
            user=self.worker, email=email, code_hash=WorkerEmailChange.make_code_hash(self.worker.pk, email, '123456'),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        payload = {'email': email, 'password': 'WorkerPass2026!', 'code': '123456'}
        url = reverse('worker-email-change-confirm')
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 400)
        change.expires_at = timezone.now() + timedelta(minutes=5)
        change.attempts = 5
        change.save(update_fields=['expires_at', 'attempts'])
        self.assertEqual(self.client.post(url, payload, format='json').status_code, 400)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.email, 'old@example.test')
