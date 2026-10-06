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
            for group in (user_group(user_id), f"admin_notifications_{user_id}"):
                async_to_sync(layer.group_send)(group, {
                    "type": "notification.unread", "payload": {"unread_count": count},
                })
        except Exception:
            logger.warning("push_unread_count failed", exc_info=True)

    transaction.on_commit(_send)

ADMIN_REVIEW_GROUP = "admin_profile_review"


def push_profile_review_changed(profile_id):
    def send():
        layer = get_channel_layer()
        if layer is None:
            return
        try:
            async_to_sync(layer.group_send)(ADMIN_REVIEW_GROUP, {
                'type': 'profile.review.changed', 'payload': {'profile_id': profile_id},
            })
        except Exception:
            logger.warning('Profile review broadcast failed', exc_info=True)
    transaction.on_commit(send)


def push_complaint_changed(complaint_id):
    def send():
        layer = get_channel_layer()
        if layer is None:
            return
        try:
            async_to_sync(layer.group_send)(ADMIN_REVIEW_GROUP, {
                'type': 'complaint.changed', 'payload': {'complaint_id': complaint_id},
            })
        except Exception:
            logger.warning('Complaint broadcast failed', exc_info=True)
    transaction.on_commit(send)