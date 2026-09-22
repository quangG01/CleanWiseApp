"""Best-effort WebSocket delivery after chat rows have committed to the DB."""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import ChatMessage
from .serializers import ChatMessageSerializer


logger = logging.getLogger(__name__)


def user_group(user_id):
    return f'chat_user_{user_id}'


def publish_message(message_id):
    try:
        message = ChatMessage.objects.select_related('conversation').get(pk=message_id)
        recipients = (
            [message.recipient_id]
            if message.message_type == ChatMessage.MessageType.SYSTEM
            else [message.conversation.customer_id, message.conversation.worker_id]
        )
        payload = dict(ChatMessageSerializer(message).data)
        layer = get_channel_layer()
        for user_id in recipients:
            async_to_sync(layer.group_send)(
                user_group(user_id), {'type': 'chat.message', 'payload': payload},
            )
    except Exception:
        # The row is already committed. REST history remains the source of truth.
        logger.exception('Could not publish chat message %s', message_id)


def publish_read(conversation_id, reader_id, last_read_message_id, other_user_id):
    try:
        layer = get_channel_layer()
        async_to_sync(layer.group_send)(user_group(other_user_id), {
            'type': 'chat.read',
            'payload': {
                'conversation_id': conversation_id,
                'reader_id': reader_id,
                'last_read_message_id': last_read_message_id,
            },
        })
    except Exception:
        logger.exception('Could not publish chat read receipt for conversation %s', conversation_id)
