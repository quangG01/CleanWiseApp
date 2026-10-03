from django.db.models import Q

from .models import ChatMessage


def assignment_notice_filter():
    """Legacy assignment notices remain stored but are no longer chat content."""
    return Q(
        message_type=ChatMessage.MessageType.SYSTEM,
        sender__isnull=True,
        recipient__isnull=False,
        related_assignment__isnull=False,
    ) & (
        Q(message__startswith='Nhân viên ', message__endswith='Bạn có thể liên hệ với nhân viên tại đây.')
        | Q(message__startswith='Bạn đã nhận lịch làm ngày ', message__endswith='Hãy liên hệ với khách hàng để trao đổi.')
    )


def visible_message_filter(user):
    return ~assignment_notice_filter() & (
        ~Q(message_type=ChatMessage.MessageType.SYSTEM)
        | Q(message_type=ChatMessage.MessageType.SYSTEM, recipient=user)
    )


def unread_message_filter(user):
    return visible_message_filter(user) & Q(is_read=False) & (
        Q(message_type=ChatMessage.MessageType.SYSTEM, recipient=user)
        | (~Q(message_type=ChatMessage.MessageType.SYSTEM) & ~Q(sender=user))
    )
