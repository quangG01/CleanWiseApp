import logging

import requests
from django.db import transaction

from .models import DeviceToken

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'

logger = logging.getLogger(__name__)


def deliver_push_to_user(user_id, title, message, data=None):
    """Gửi push thật tới Expo (chạy trong Celery worker).
    Raise RequestException khi Expo lỗi để Celery tự retry."""
    tokens = list(
        DeviceToken.objects.filter(user_id=user_id).values_list('token', flat=True)
    )
    if not tokens:
        return

    messages = [
        {
            'to': token,
            'title': title,
            'body': message,
            'data': data or {},
            'sound': 'default',
        }
        for token in tokens
    ]

    response = requests.post(EXPO_PUSH_URL, json=messages, timeout=5)
    response.raise_for_status()


def send_push_to_user(user, title, message, data=None):
    """Đưa push vào hàng đợi Celery, chỉ chạy sau khi transaction commit.
    Không bao giờ làm hỏng luồng gọi nó nếu hàng đợi có sự cố."""
    from .tasks import send_push_task

    user_id = user.pk
    payload = data or {}

    def enqueue():
        try:
            send_push_task.delay(user_id, title, message, payload)
        except Exception:
            logger.exception('Không đưa được push vào hàng đợi (user_id=%s)', user_id)

    transaction.on_commit(enqueue)