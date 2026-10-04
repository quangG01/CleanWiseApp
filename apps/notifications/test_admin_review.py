from django.contrib.auth import get_user_model
from django.urls import reverse
from django.db import transaction
from rest_framework.test import APITestCase
from apps.authentication.models import WorkerProfile
from .models import Notification

User = get_user_model()


class AdminReviewNotificationTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='review-admin', email='review-admin@example.invalid', role='ADMIN')
        self.other = User.objects.create_user(username='other-admin', email='other-admin@example.invalid', role='ADMIN')
        User.objects.create_user(username='inactive-admin', email='inactive-admin@example.invalid', role='ADMIN', is_active=False)
        self.worker = User.objects.create_user(username='review-worker', email='review-worker@example.invalid', role='WORKER')
        self.profile = WorkerProfile.objects.create(user=self.worker)
        self.client.force_authenticate(self.admin)

    def submit(self):
        self.profile.status = 'PENDING'
        self.profile.save(update_fields=['status'])

    def test_submission_notifies_each_active_admin_once(self):
        self.submit()
        self.profile.save(update_fields=['status'])
        self.assertEqual(Notification.objects.filter(related_worker=self.profile).count(), 2)
        self.assertTrue(Notification.objects.filter(user=self.admin, related_worker=self.profile).exists())
        self.profile.status = 'DRAFT'
        self.profile.save(update_fields=['status'])
        self.submit()
        self.assertEqual(Notification.objects.filter(related_worker=self.profile).count(), 4)

    def test_read_count_is_independent_from_pending_count(self):
        self.submit()
        notification = Notification.objects.get(user=self.admin)
        response = self.client.post(reverse('notification-mark-read', args=[notification.id]))
        self.assertEqual(response.status_code, 200)
        summary = self.client.get(reverse('admin-notification-summary')).data['data']
        self.assertEqual(summary, {'pending_profiles': 1, 'unread_count': 0})
        self.profile.status = 'DRAFT'
        self.profile.save(update_fields=['status'])
        self.assertEqual(self.client.get(reverse('admin-notification-summary')).data['data']['pending_profiles'], 0)

    def test_admin_cannot_read_another_admin_notification(self):
        self.submit()
        data = self.client.get(reverse('notification-list')).data['data']
        self.assertEqual(data['count'], 1)
        self.assertEqual(data['results'][0]['related_worker'], self.profile.id)
        other = Notification.objects.get(user=self.other)
        self.assertEqual(self.client.post(reverse('notification-mark-read', args=[other.id])).status_code, 404)

    def test_worker_cannot_access_admin_summary(self):
        self.client.force_authenticate(self.worker)
        self.assertEqual(self.client.get(reverse('admin-notification-summary')).status_code, 403)

    def test_rolled_back_submission_does_not_leave_notifications(self):
        with transaction.atomic():
            self.submit()
            transaction.set_rollback(True)
        self.assertFalse(Notification.objects.filter(related_worker=self.profile).exists())
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, 'DRAFT')
