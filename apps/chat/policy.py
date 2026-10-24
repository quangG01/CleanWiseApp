from datetime import timedelta

from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import APIException

from .models import ChatRestriction, ChatViolation


class ChatPolicyError(APIException):
    def __init__(self, detail):
        self.default_code = detail['code']
        self.status_code = 403 if detail['code'] == 'CHAT_SEND_LOCKED' else 400
        # Keep numeric counters numeric (APIException converts scalars to strings).
        super().__init__(detail)
        self.detail = detail


def policy_status(user, restriction=None):
    now = timezone.now()
    if restriction is None:
        restriction = ChatRestriction.objects.filter(user=user).first()
    until = restriction.locked_until if restriction and restriction.locked_until and restriction.locked_until > now else None
    count = ChatViolation.objects.filter(
        user=user, created_at__gte=now - timedelta(days=settings.CHAT_VIOLATION_WINDOW_DAYS),
    ).count()
    return {
        'violation_count': count,
        'warning_limit': settings.CHAT_WARNING_LIMIT,
        'window_days': settings.CHAT_VIOLATION_WINDOW_DAYS,
        'locked_until': until.isoformat() if until else None,
        'is_locked': bool(until),
    }


def locked_detail(status):
    return {'code': 'CHAT_SEND_LOCKED', 'message': 'Bạn đang bị tạm khóa gửi chat. Bạn vẫn có thể đọc, nhận tin và liên hệ hỗ trợ.', **status}


def record_violation(user, conversation, categories, restriction):
    previous = policy_status(user, restriction)['violation_count']
    count = previous + 1
    limit = settings.CHAT_WARNING_LIMIT
    days = settings.CHAT_LOCK_DAYS[min(count - limit - 1, len(settings.CHAT_LOCK_DAYS) - 1)] if count > limit else 0
    if days:
        restriction.locked_until = timezone.now() + timedelta(days=days)
        restriction.save(update_fields=['locked_until', 'updated_at'])
    ChatViolation.objects.create(user=user, conversation=conversation, categories=categories,
                                 action='LOCK' if days else 'WARN', locked_until=restriction.locked_until if days else None)
    status = policy_status(user, restriction)
    if days:
        return locked_detail(status)
    remaining = max(0, limit - count)
    warning = (f'Thông tin không được phép đã được ẩn hoặc chặn. Bạn đã vi phạm {count}/{limit} lần cảnh báo '
               f'trong {settings.CHAT_VIOLATION_WINDOW_DAYS} ngày. ')
    warning += f'Còn {remaining} lần cảnh báo trước khi khóa gửi chat.' if remaining else f'Lần vi phạm tiếp theo sẽ khóa gửi chat {settings.CHAT_LOCK_DAYS[0]} ngày.'
    return {'code': 'CHAT_CONTENT_REDACTED', 'message': warning, **status}
