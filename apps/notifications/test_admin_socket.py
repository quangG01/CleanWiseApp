from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from rest_framework_simplejwt.tokens import AccessToken
from core.asgi import application
from apps.authentication.models import WorkerProfile


class AdminSocketTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(username='socket-review-admin', email='socket-review-admin@example.invalid', role='ADMIN')
        self.worker = User.objects.create_user(username='socket-review-worker', email='socket-review-worker@example.invalid', role='WORKER')
        self.profile = WorkerProfile.objects.create(user=self.worker)
        self.admin_token = str(AccessToken.for_user(self.admin))
        self.worker_token = str(AccessToken.for_user(self.worker))

    async def test_admin_receives_review_and_unread_events(self):
        socket = WebsocketCommunicator(application, '/ws/admin/notifications/')
        await socket.connect()
        await socket.send_json_to({'type': 'auth', 'access_token': self.admin_token})
        self.assertEqual((await socket.receive_json_from())['type'], 'auth.ok')
        def submit():
            self.profile.status = 'PENDING'
            self.profile.save(update_fields=['status'])
        await database_sync_to_async(submit)()
        events = [await socket.receive_json_from(), await socket.receive_json_from()]
        self.assertEqual({event['type'] for event in events}, {'notification.unread', 'profile.review.changed'})
        self.assertEqual(next(event for event in events if event['type'] == 'notification.unread')['unread_count'], 1)
        await database_sync_to_async(submit)()
        self.assertTrue(await socket.receive_nothing(timeout=0.05))
        def revoke_pending():
            self.profile.status = 'DRAFT'
            self.profile.save(update_fields=['status'])
        await database_sync_to_async(revoke_pending)()
        self.assertEqual((await socket.receive_json_from())['type'], 'profile.review.changed')
        await socket.disconnect()

    async def test_worker_is_denied(self):
        socket = WebsocketCommunicator(application, '/ws/admin/notifications/')
        await socket.connect()
        await socket.send_json_to({'type': 'auth', 'access_token': self.worker_token})
        self.assertEqual((await socket.receive_output())['code'], 4403)
        await socket.disconnect()
