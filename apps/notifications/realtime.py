import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from apps.chat.realtime import user_group

logger = logging.getLogger(__name__)


def push_unread_count(user_id):
    """Đẩy số chưa đọc tới mọi socket của user, sau khi transaction commit."""

    def _send():
        from .models import Notification

        layer = get_channel_layer()
        if layer is None:
            return
        count = Notification.objects.filter(user_id=user_id, is_read=False).count()
        try:
            async_to_sync(layer.group_send)(
                user_group(user_id),
                {"type": "notification.unread", "payload": {"unread_count": count}},
            )
        except Exception:
            logger.warning("push_unread_count failed", exc_info=True)

    transaction.on_commit(_send)