from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.bookings.models import Booking, BookingSchedule
from apps.worker.models import BookingAssignment

from .models import ChatConversation, ChatConversationAssignment, ChatMessage
from .realtime import publish_conversation, publish_message, publish_read
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


@transaction.atomic
def send_text_message(user, data):
    params = MessageSendInputSerializer(data=data)
    params.is_valid(raise_exception=True)
    values = params.validated_data
    conversation = participant_conversation(values['conversation_id'], user)
    if not can_send(conversation):
        raise PermissionDenied('Hiện không có lịch phân công còn hiệu lực để gửi tin.')
    message = ChatMessage.objects.create(
        conversation=conversation, sender=user,
        message=values['message'], message_type=ChatMessage.MessageType.TEXT,
    )
    ChatConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
    transaction.on_commit(lambda: publish_message(message.id))
    return message


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
