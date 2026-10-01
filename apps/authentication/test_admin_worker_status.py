from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import WorkerProfile


User = get_user_model()


class AdminWorkerStatusTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='worker-status-admin',
            email='worker-status-admin@example.com',
            password='CleanWise@2026!',
            role=User.Role.ADMIN,
        )
        self.worker = User.objects.create_user(
            username='worker-status-worker',
            email='worker-status-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.profile = WorkerProfile.objects.create(
            user=self.worker,
            status=WorkerProfile.Status.PENDING,
        )
        self.url = reverse('admin-worker-status-update', args=[self.profile.id])
        self.client.force_authenticate(self.admin)

    def test_admin_can_approve_pending_profile(self):
        response = self.client.patch(self.url, {'status': 'ACTIVE'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.ACTIVE)
        self.assertEqual(self.profile.approved_by, self.admin)
        self.assertIsNotNone(self.profile.approved_at)

    def test_admin_can_suspend_active_profile_with_reason(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])

        response = self.client.patch(
            self.url,
            {'status': 'SUSPENDED', 'reason': 'Vi phạm quy định nhận việc.'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.SUSPENDED)
        self.assertEqual(self.profile.rejection_reason, 'Vi phạm quy định nhận việc.')
        self.assertTrue(self.worker.is_active)

    def test_suspend_requires_reason(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])

        response = self.client.patch(self.url, {'status': 'SUSPENDED'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('reason', response.data['errors'])

    def test_admin_can_reactivate_suspended_profile(self):
        self.profile.status = WorkerProfile.Status.SUSPENDED
        self.profile.rejection_reason = 'Tạm khóa để kiểm tra.'
        self.profile.save(update_fields=['status', 'rejection_reason'])

        response = self.client.patch(self.url, {'status': 'ACTIVE'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.ACTIVE)
        self.assertIsNone(self.profile.rejection_reason)
        self.assertEqual(self.profile.approved_by, self.admin)

    def test_admin_can_revoke_active_approval_to_draft(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.approved_by = self.admin
        self.profile.approved_at = timezone.now()
        self.profile.save(update_fields=['status', 'approved_by', 'approved_at'])

        response = self.client.patch(
            self.url,
            {'status': 'DRAFT', 'reason': 'Duyệt nhầm hồ sơ, cần kiểm tra lại.'},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.DRAFT)
        self.assertEqual(self.profile.rejection_reason, 'Duyệt nhầm hồ sơ, cần kiểm tra lại.')
        self.assertIsNone(self.profile.approved_by)
        self.assertIsNone(self.profile.approved_at)

    def test_revoke_approval_requires_reason(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])

        response = self.client.patch(self.url, {'status': 'DRAFT'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('reason', response.data['errors'])

    def test_admin_cannot_reject_active_profile(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])

        response = self.client.patch(
            self.url,
            {
                'status': 'REJECTED',
                'reason': 'Không hợp lệ.',
                'rejected_fields': {'portrait': 'Ảnh không hợp lệ.'},
            },
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
