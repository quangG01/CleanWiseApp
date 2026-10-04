import asyncio
import time
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from apps.chat.consumers import authenticate_access_token

from .realtime import ADMIN_REVIEW_GROUP


class AdminNotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = None
        self.groups_joined = []
        await self.accept()
        self.timeout = asyncio.create_task(self.expire(10))

    async def expire(self, seconds):
        await asyncio.sleep(seconds)
        await self.close(code=4401)

    async def disconnect(self, code):
        self.timeout.cancel()
        for group in self.groups_joined:
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        if self.user:
            if isinstance(content, dict) and content.get('type') == 'ping':
                await self.send_json({'type': 'pong'})
            return
        token = content.get('access_token') if isinstance(content, dict) and content.get('type') == 'auth' else None
        if not isinstance(token, str) or not token or len(token) > 4096:
            await self.close(code=4401)
            return
        user, expires = await authenticate_access_token(token)
        if not user.is_authenticated or not user.is_active or not (user.role == 'ADMIN' or user.is_superuser):
            await self.close(code=4403)
            return
        self.user = user
        self.groups_joined = [f"admin_notifications_{user.id}", ADMIN_REVIEW_GROUP]
        for group in self.groups_joined:
            await self.channel_layer.group_add(group, self.channel_name)
        self.timeout.cancel()
        self.timeout = asyncio.create_task(self.expire(max(0, expires - time.time())))
        await self.send_json({'type': 'auth.ok'})

    async def notification_unread(self, event):
        await self.send_json({'type': 'notification.unread', **event['payload']})

    async def profile_review_changed(self, event):
        await self.send_json({'type': 'profile.review.changed', **event['payload']})
