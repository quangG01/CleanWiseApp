from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from .models import WorkerProfile, WorkerProfileReviewEvent
from .serializers import WorkerProfileUpdateSerializer


class AdminWorkerContactTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.admin = users.create_user(
            username='contact-admin', email='contact-admin@example.test', role='ADMIN', first_name='Mai Linh',
        )
        cls.worker = users.create_user(
            username='contact-worker', email='contact-worker@example.test', role='WORKER',
            phone_number='0901234567', password='TestWorkerPhone123!',
        )
        cls.profile = WorkerProfile.objects.create(user=cls.worker, status=WorkerProfile.Status.ACTIVE)

    def setUp(self):
        self.client.force_authenticate(self.admin)
        self.url = reverse('admin-worker-contact-update', args=[self.profile.pk])
        self.payload = {
            'previous_phone_number': '0901234567',
            'phone_number': '+84912345678',
            'reason': 'Nhân viên xác nhận đã nhập nhầm số.',
            'confirmed_with_worker': True,
        }

    def test_phone_update_records_the_change_and_accepts_the_new_login_number(self):
        response = self.client.patch(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['data']['phone_number'], '0912345678')
        self.assertEqual(response.data['data']['status'], WorkerProfile.Status.ACTIVE)

        event = self.profile.review_events.get()
        self.assertEqual(event.actor, self.admin)
        self.assertEqual(event.actor_name, 'Mai Linh')
        self.assertEqual(event.action, WorkerProfileReviewEvent.Action.CONTACT_UPDATED)
        self.assertEqual(event.reason, self.payload['reason'])
        self.assertEqual(event.changes, {'phone_number': {'before': '0901234567', 'after': '0912345678'}})

        history = self.client.get(reverse('admin-worker-profile-review-history', args=[self.profile.pk]))
        self.assertEqual(history.data['results'][0]['changes'], event.changes)
        login = APIClient().post(
            reverse('login'), {'phone': '0912345678', 'password': 'TestWorkerPhone123!'}, format='json',
        )
        self.assertEqual(login.status_code, 200, login.data)

    def test_rejects_invalid_changes_and_duplicate_phone_in_another_format(self):
        get_user_model().objects.create_user(
            username='contact-other', email='contact-other@example.test', role='CUSTOMER',
            phone_number='+84912345678',
        )
        for invalid in [
            {'phone_number': '123'}, {'phone_number': '0901234567'}, {'phone_number': '0912345678'},
            {'reason': '   '}, {'identity_number': '123456789012'}, {'first_name': 'Tên mới'},
            {'service_id': 1}, {'confirmed_with_worker': False},
        ]:
            with self.subTest(invalid=invalid):
                response = self.client.patch(self.url, {**self.payload, **invalid}, format='json')
                self.assertEqual(response.status_code, 400, response.data)
        self.assertFalse(self.profile.review_events.exists())

    def test_worker_cannot_use_admin_contact_endpoint(self):
        self.client.force_authenticate(self.worker)
        response = self.client.patch(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.profile.review_events.exists())

    def test_stale_request_does_not_replace_new_phone_or_create_another_event(self):
        self.assertEqual(self.client.patch(self.url, self.payload, format='json').status_code, 200)
        response = self.client.patch(self.url, {**self.payload, 'phone_number': '0987654321'}, format='json')
        self.assertEqual(response.status_code, 409)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.phone_number, '0912345678')
        self.assertEqual(self.profile.review_events.count(), 1)

    def test_failed_audit_write_rolls_back_phone_update(self):
        with patch.object(WorkerProfileReviewEvent, 'record', side_effect=IntegrityError):
            response = self.client.patch(self.url, self.payload, format='json')
        self.assertEqual(response.status_code, 409)
        self.worker.refresh_from_db()
        self.assertEqual(self.worker.phone_number, '0901234567')
        self.assertFalse(self.profile.review_events.exists())

    def test_worker_edit_of_another_field_does_not_restore_stale_phone(self):
        stale_profile = WorkerProfile.objects.select_related('user').get(pk=self.profile.pk)
        edit = WorkerProfileUpdateSerializer(
            stale_profile, data={'bio': 'Hồ sơ mẫu'}, partial=True,
            context={'request': SimpleNamespace(user=self.worker)},
        )
        edit.is_valid(raise_exception=True)
        self.assertEqual(self.client.patch(self.url, self.payload, format='json').status_code, 200)
        edit.save()

        self.worker.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.bio, 'Hồ sơ mẫu')
        self.assertEqual(self.worker.phone_number, '0912345678')
