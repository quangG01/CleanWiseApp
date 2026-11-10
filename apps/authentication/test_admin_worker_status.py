from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.test import APITestCase

from .models import WorkerProfile, WorkerProfileReviewEvent
from .serializers import AdminWorkerStatusUpdateSerializer


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

    def test_rejection_validated_before_approval_cannot_overwrite_it(self):
        other_admin = User.objects.create_user(
            username='worker-status-other-admin',
            email='worker-status-other-admin@example.com',
            role=User.Role.ADMIN,
        )
        rejection = AdminWorkerStatusUpdateSerializer(
            self.profile,
            data={
                'status': 'REJECTED',
                'reason': 'Vui lòng cập nhật ảnh chân dung.',
                'rejected_fields': {'portrait': 'Ảnh chưa rõ mặt.'},
            },
            context={'request': SimpleNamespace(user=other_admin)},
        )
        rejection.is_valid(raise_exception=True)

        response = self.client.patch(self.url, {'status': 'ACTIVE'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        approved_at = WorkerProfile.objects.get(pk=self.profile.pk).approved_at

        with self.assertRaises(ValidationError) as error:
            rejection.save()

        self.assertIn('status', error.exception.detail)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.ACTIVE)
        self.assertEqual(self.profile.approved_by, self.admin)
        self.assertEqual(self.profile.approved_at, approved_at)
        self.assertIsNone(self.profile.rejection_reason)
        self.assertEqual(list(self.profile.review_events.values_list('action', flat=True)), ['APPROVED'])

    def test_history_preserves_decisions_and_can_be_read_in_pages(self):
        self.admin.first_name = 'Mai Linh'
        self.admin.save(update_fields=['first_name'])
        steps = [
            {'status': 'ACTIVE'},
            {'status': 'SUSPENDED', 'reason': 'Xác minh lại hồ sơ.'},
            {'status': 'ACTIVE'},
            {'status': 'DRAFT', 'reason': 'Cần bổ sung giấy tờ.', 'rejected_fields': {'portrait': 'Ảnh bị mờ.'}},
        ]
        for step in steps:
            response = self.client.patch(self.url, step, format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.admin.first_name = 'Tên mới'
        self.admin.save(update_fields=['first_name'])

        url = reverse('admin-worker-profile-review-history', args=[self.profile.pk])
        with patch('apps.authentication.views.WorkerProfileReviewHistoryPagination.page_size', 2):
            newest = self.client.get(url).data
            next_query = urlsplit(newest['next']).query
            older = self.client.get(f'{url}?{next_query}').data

        events = newest['results'] + older['results']
        self.assertEqual(
            [(event['action'], event['previous_status'], event['new_status']) for event in events],
            [
                ('REVOKED', 'ACTIVE', 'DRAFT'),
                ('REACTIVATED', 'SUSPENDED', 'ACTIVE'),
                ('SUSPENDED', 'ACTIVE', 'SUSPENDED'),
                ('APPROVED', 'PENDING', 'ACTIVE'),
            ],
        )
        self.assertEqual(events[0]['rejected_fields'], {'portrait': 'Ảnh bị mờ.'})
        self.assertEqual(events[2]['reason'], 'Xác minh lại hồ sơ.')
        self.assertTrue(all(event['actor_name'] == 'Mai Linh' and event['created_at'] for event in events))
        self.assertIsNone(older['next'])

    def test_status_update_rolls_back_if_history_cannot_be_saved(self):
        with patch.object(WorkerProfileReviewEvent, 'record', side_effect=IntegrityError):
            response = self.client.patch(self.url, {'status': 'ACTIVE'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.PENDING)
        self.assertIsNone(self.profile.approved_by)
        self.assertFalse(self.profile.review_events.exists())

    def test_history_is_admin_only_and_distinguishes_empty_and_missing_profiles(self):
        url = reverse('admin-worker-profile-review-history', args=[self.profile.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['results'], [])
        missing = reverse('admin-worker-profile-review-history', args=[self.profile.pk + 1])
        self.assertEqual(self.client.get(missing).status_code, status.HTTP_404_NOT_FOUND)

        self.client.force_authenticate(self.worker)
        self.assertEqual(self.client.get(url).status_code, status.HTTP_403_FORBIDDEN)

    def test_revoke_preserves_general_reason_and_field_notes(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])
        notes = {'portrait': 'Vui lòng cập nhật ảnh rõ mặt.'}
        response = self.client.patch(self.url, {
            'status': 'DRAFT', 'reason': 'Hồ sơ cần được xác minh lại.',
            'rejected_fields': notes,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.rejection_reason, 'Hồ sơ cần được xác minh lại.')
        self.assertEqual(self.profile.rejected_fields, notes)

    def test_reject_preserves_general_reason_separately_from_field_notes(self):
        notes = {'identity_number': 'Số CCCD không khớp ảnh giấy tờ.'}
        response = self.client.patch(self.url, {
            'status': 'REJECTED', 'reason': 'Vui lòng đối chiếu giấy tờ trước khi gửi lại.',
            'rejected_fields': notes,
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.rejection_reason, 'Vui lòng đối chiếu giấy tờ trước khi gửi lại.')
        self.assertEqual(self.profile.rejected_fields, notes)
        event = self.profile.review_events.get()
        self.assertEqual(event.action, WorkerProfileReviewEvent.Action.REJECTED)
        self.assertEqual(event.reason, self.profile.rejection_reason)
        self.assertEqual(event.rejected_fields, notes)

    def test_revoke_rejects_invalid_or_empty_field_notes(self):
        self.profile.status = WorkerProfile.Status.ACTIVE
        self.profile.save(update_fields=['status'])
        for notes in ({'unknown': 'Không hợp lệ.'}, {'portrait': ''}):
            response = self.client.patch(self.url, {
                'status': 'DRAFT', 'reason': 'Cần kiểm tra hồ sơ.', 'rejected_fields': notes,
            }, format='json')
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, WorkerProfile.Status.ACTIVE)
