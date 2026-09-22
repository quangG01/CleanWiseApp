import asyncio
import logging
import time

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from django.http import Http404
from rest_framework.exceptions import APIException, ValidationError
from rest_framework_simplejwt.authentication import JWTAuthentication

from .realtime import user_group
from .service import can_send, mark_messages_read, participant_conversation, send_text_message


logger = logging.getLogger(__name__)


@database_sync_to_async
def typing_recipient(user, conversation_id):
    conversation = participant_conversation(conversation_id, user)
    if not can_send(conversation):
        return None
    return conversation.worker_id if conversation.customer_id == user.id else conversation.customer_id


@database_sync_to_async
def authenticate_access_token(raw_token):
    try:
        auth = JWTAuthentication()
        token = auth.get_validated_token(raw_token)
        return auth.get_user(token), int(token['exp'])
    except (APIException, KeyError, TypeError, ValueError):
        return AnonymousUser(), None


class ChatConsumer(AsyncJsonWebsocketConsumer):
    """One authenticated socket per app session, carrying all of a user's chats."""

    async def connect(self):
        self.user = None
        self.group_name = None
        self.expiry_task = None
        self.typing_conversations = {}
        await self.accept()
        self.auth_timeout_task = asyncio.create_task(self._close_if_unauthenticated())

    async def disconnect(self, close_code):
        self.auth_timeout_task.cancel()
        if self.expiry_task:
            self.expiry_task.cancel()
        if self.group_name:
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
        if self.user:
            for conversation_id, recipient_id in self.typing_conversations.items():
                await self._publish_typing(conversation_id, recipient_id, False)

    async def _close_if_unauthenticated(self):
        await asyncio.sleep(10)
        if self.user is None:
            await self.close(code=4401)

    async def _close_when_token_expires(self, expires_at):
        await asyncio.sleep(max(0, expires_at - time.time()))
        await self.close(code=4401)

    async def receive_json(self, content, **kwargs):
        if not isinstance(content, dict):
            await self.send_json({'type': 'error', 'code': 'invalid_payload'})
            return

        action = content.get('type')
        if self.user is None:
            if action != 'auth' or not isinstance(content.get('access_token'), str):
                await self.close(code=4401)
                return
            raw_token = content['access_token']
            if not raw_token or len(raw_token) > 4096:
                await self.close(code=4401)
                return
            user, expires_at = await authenticate_access_token(raw_token)
            if not user.is_authenticated:
                await self.close(code=4401)
                return
            self.user = user
            self.group_name = user_group(user.id)
            await self.channel_layer.group_add(self.group_name, self.channel_name)
            self.auth_timeout_task.cancel()
            self.expiry_task = asyncio.create_task(self._close_when_token_expires(expires_at))
            await self.send_json({'type': 'auth.ok', 'user_id': user.id})
            return

        try:
            if action == 'message.send':
                message = await database_sync_to_async(send_text_message)(self.user, content)
                await self.send_json({'type': 'message.accepted', 'message_id': message.id})
            elif action == 'messages.read':
                count = await database_sync_to_async(mark_messages_read)(self.user, content)
                await self.send_json({'type': 'messages.read.ack', 'marked_read': count})
            elif action in ('typing.start', 'typing.stop'):
                conversation_id = content.get('conversation_id')
                if type(conversation_id) is not int or conversation_id <= 0:
                    raise ValidationError({'conversation_id': 'ID cuộc trò chuyện không hợp lệ.'})
                recipient_id = await typing_recipient(self.user, conversation_id)
                if recipient_id is None:
                    raise ValidationError({'conversation_id': 'Không thể gửi tin trong cuộc trò chuyện này.'})
                is_typing = action == 'typing.start'
                if is_typing:
                    self.typing_conversations[conversation_id] = recipient_id
                else:
                    self.typing_conversations.pop(conversation_id, None)
                await self._publish_typing(conversation_id, recipient_id, is_typing)
            elif action == 'ping':
                await self.send_json({'type': 'pong'})
            else:
                await self.send_json({'type': 'error', 'code': 'unknown_action'})
        except Http404:
            await self.send_json({'type': 'error', 'code': 'not_found'})
        except ValidationError as exc:
            await self.send_json({'type': 'error', 'code': 'validation_error', 'detail': exc.detail})
        except APIException as exc:
            await self.send_json({'type': 'error', 'code': exc.default_code, 'detail': str(exc.detail)})
        except Exception:
            logger.exception('Unexpected chat WebSocket error')
            await self.send_json({'type': 'error', 'code': 'internal_error'})

    async def chat_message(self, event):
        await self.send_json({'type': 'message.created', 'message': event['payload']})

    async def chat_read(self, event):
        await self.send_json({'type': 'messages.read', **event['payload']})

    async def _publish_typing(self, conversation_id, recipient_id, is_typing):
        await self.channel_layer.group_send(user_group(recipient_id), {
            'type': 'chat.typing',
            'payload': {
                'conversation_id': conversation_id,
                'user_id': self.user.id,
                'is_typing': is_typing,
            },
        })

    async def chat_typing(self, event):
        await self.send_json({'type': 'typing.changed', **event['payload']})
