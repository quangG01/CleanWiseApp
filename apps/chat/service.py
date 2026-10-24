from django.db import transaction
from django.contrib.auth import get_user_model
from django.utils.crypto import salted_hmac
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.bookings.models import Booking, BookingSchedule
from apps.worker.models import BookingAssignment

from .models import ChatConversation, ChatConversationAssignment, ChatMessage, ChatRestriction, ChatSendAttempt
from .moderation import detect_violation
from .redaction import redact_contacts
from .policy import ChatPolicyError, policy_status, locked_detail, record_violation
from .realtime import publish_conversation, publish_message, publish_read, publish_moderation
from .queries import unread_message_filter
from .serializers import MessageReadInputSerializer, MessageSendInputSerializer


def display_name(user):
    return user.get_full_name().strip() or user.username


def can_send(conversation):
    if conversation.status != ChatConversation.Status.ACTIVE:
        return False
    return conversation.assignment_links.filter(
        assignment__status=BookingAssignment.Status.ACCEPTED,
        assignment__schedule__status__in=(BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS),
        assignment__schedule__booking__status__in=(
            Booking.Status.PENDING, Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS,
        ),
    ).exists()


@transaction.atomic
def ensure_chat_for_assignment(assignment):
    """Link an accepted assignment to the pair's chat without creating messages."""
    if assignment.status != BookingAssignment.Status.ACCEPTED:
        raise ValueError('Only accepted assignments can create chat links.')

    assignment = BookingAssignment.objects.select_related(
        'worker', 'schedule__booking__customer',
    ).get(pk=assignment.pk)
    schedule = assignment.schedule
    customer = schedule.booking.customer
    worker = assignment.worker
    conversation, _ = ChatConversation.objects.get_or_create(customer=customer, worker=worker)
    _, created = ChatConversationAssignment.objects.get_or_create(
        assignment=assignment,
        defaults={'conversation': conversation},
    )
    if not created:
        return conversation

    ChatConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
    transaction.on_commit(lambda: publish_conversation(conversation.id))
    return conversation


def participant_conversation(conversation_id, user):
    return get_object_or_404(
        ChatConversation.objects.select_related('customer', 'worker'),
        Q(customer=user) | Q(worker=user), pk=conversation_id,
    )


def send_text_message(user, data):
    params = MessageSendInputSerializer(data=data)
    params.is_valid(raise_exception=True)
    values = params.validated_data
    # Return policy rejections from the transaction, then raise after committing.
    # Raising inside atomic would erase the violation and the newly applied lock.
    message, outcome = _send_text_transaction(user, values)
    if outcome.get('code') in ('CHAT_SEND_LOCKED', 'CHAT_CONTENT_BLOCKED'):
        raise ChatPolicyError(outcome)
    message.moderation = outcome or None
    return message


@transaction.atomic
def _send_text_transaction(user, values):
    conversation = participant_conversation(values['conversation_id'], user)
    if not can_send(conversation):
        raise PermissionDenied('Hiện không có lịch phân công còn hiệu lực để gửi tin.')
    # Serialize every send by this user, even across different conversations.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    key = values.get('client_message_id', '')
    fingerprint = salted_hmac('chat-send', f"{conversation.pk}:{values['message']}", algorithm='sha256').hexdigest()
    if key:
        attempt = ChatSendAttempt.objects.filter(user=user, client_message_id=key).select_related('message').first()
        if attempt:
            if attempt.conversation_id != conversation.pk or attempt.fingerprint != fingerprint:
                raise PermissionDenied('Mã lượt gửi đã được dùng cho nội dung khác.')
            return attempt.message, attempt.outcome
    restriction, _ = ChatRestriction.objects.get_or_create(user=user)
    status = policy_status(user, restriction)
    if status['is_locked']:
        return None, locked_detail(status)
    redacted, categories, has_content = redact_contacts(values['message'])
    # Preserve the existing off-platform solicitation/payment policy.
    remaining_violation = detect_violation(redacted)
    if remaining_violation:
        categories = sorted(set(categories + [remaining_violation.category]))
    outcome = {}
    if categories:
        outcome = record_violation(user, conversation, categories, restriction)
        transaction.on_commit(lambda: publish_moderation(user.pk))
        if outcome['is_locked'] or remaining_violation or not has_content:
            if not outcome['is_locked']:
                outcome = {**outcome, 'code': 'CHAT_CONTENT_BLOCKED', 'violation_type': categories[0],
                           'message': 'Vui lòng chỉnh sửa nội dung để tiếp tục. ' + outcome['message']}
            if key:
                ChatSendAttempt.objects.create(user=user, conversation=conversation, client_message_id=key,
                                               fingerprint=fingerprint, outcome=outcome)
            return None, outcome
    message = ChatMessage.objects.create(
        conversation=conversation, sender=user,
        message=redacted, message_type=ChatMessage.MessageType.TEXT, client_message_id=key,
    )
    if key:
        ChatSendAttempt.objects.create(user=user, conversation=conversation, client_message_id=key,
                                       fingerprint=fingerprint, message=message, outcome=outcome)
    ChatConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
    transaction.on_commit(lambda: publish_message(message.id))
    return message, outcome


@transaction.atomic
def mark_messages_read(user, data):
    params = MessageReadInputSerializer(data=data)
    params.is_valid(raise_exception=True)
    conversation = participant_conversation(params.validated_data['conversation_id'], user)
    unread = ChatMessage.objects.filter(conversation=conversation).filter(unread_message_filter(user))
    last_read_id = unread.order_by('-id').values_list('id', flat=True).first()
    count = unread.update(is_read=True)
    if last_read_id is not None:
        other_id = conversation.worker_id if user.id == conversation.customer_id else conversation.customer_id
        transaction.on_commit(lambda: publish_read(conversation.id, user.id, last_read_id, other_id))
    return count
