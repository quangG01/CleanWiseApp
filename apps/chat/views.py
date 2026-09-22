from django.db.models import F, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from rest_framework import generics, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.worker.models import BookingAssignment

from .models import ChatConversation, ChatMessage
from .serializers import (
    ChatMessageSerializer, MessageListInputSerializer,
    MessageReadInputSerializer, MessageSendInputSerializer,
)
from .service import can_send, display_name, mark_messages_read, send_text_message


def visible_messages(conversation, user):
    return ChatMessage.objects.filter(conversation=conversation).filter(
        ~Q(message_type=ChatMessage.MessageType.SYSTEM)
        | Q(message_type=ChatMessage.MessageType.SYSTEM, recipient=user)
    )


def received_unread_messages(conversation, user):
    return visible_messages(conversation, user).filter(is_read=False).filter(
        Q(message_type=ChatMessage.MessageType.SYSTEM, recipient=user)
        | (~Q(message_type=ChatMessage.MessageType.SYSTEM) & ~Q(sender=user))
    )


def total_unread_messages(user):
    return ChatMessage.objects.filter(
        Q(conversation__customer=user) | Q(conversation__worker=user),
        is_read=False,
    ).filter(
        Q(message_type=ChatMessage.MessageType.SYSTEM, recipient=user)
        | (~Q(message_type=ChatMessage.MessageType.SYSTEM) & ~Q(sender=user))
    ).count()


def get_participant_conversation(conversation_id, user):
    return get_object_or_404(
        ChatConversation.objects.select_related('customer', 'worker'),
        Q(customer=user) | Q(worker=user),
        pk=conversation_id,
    )


def assignment_summary(assignment):
    schedule = assignment.schedule
    booking = schedule.booking
    return {
        'assignment_id': assignment.id,
        'assignment_status': assignment.status,
        'schedule_id': schedule.id,
        'schedule_status': schedule.status,
        'scheduled_start': schedule.scheduled_start,
        'scheduled_end': schedule.scheduled_end,
        'booking_id': booking.id,
        'booking_code': booking.booking_code,
        'booking_status': booking.status,
        'service_name': booking.service.name,
    }


def conversation_summary(conversation, user):
    other = conversation.worker if user.id == conversation.customer_id else conversation.customer
    avatar = other.avatar
    if other.id == conversation.worker_id:
        avatar = getattr(getattr(other, 'worker_profile', None), 'avatar', None) or avatar
    last = visible_messages(conversation, user).order_by('-id').first()
    latest_link = conversation.assignment_links.select_related(
        'assignment__schedule__booking__service',
    ).order_by('-assignment__assigned_at', '-assignment_id').first()
    return {
        'id': conversation.id,
        'customer_id': conversation.customer_id,
        'worker_id': conversation.worker_id,
        'status': conversation.status,
        'created_at': conversation.created_at,
        'updated_at': conversation.updated_at,
        'other_user': {
            'id': other.id,
            'name': display_name(other),
            'avatar': avatar,
            'role': other.role,
        },
        'last_message': last.message if last else None,
        'last_message_at': last.created_at if last else None,
        'latest_assignment': assignment_summary(latest_link.assignment) if latest_link else None,
        'unread_count': received_unread_messages(conversation, user).count(),
        'can_send': can_send(conversation),
    }


class ConversationPagination(PageNumberPagination):
    page_size = 20


class ConversationByAssignmentView(generics.GenericAPIView):
    def get(self, request, assignment_id):
        assignment = get_object_or_404(
            BookingAssignment.objects.select_related(
                'worker', 'schedule__booking__customer', 'schedule__booking__service',
                'chat_link__conversation__customer', 'chat_link__conversation__worker',
            ).filter(Q(worker=request.user) | Q(schedule__booking__customer=request.user)),
            pk=assignment_id,
            status=BookingAssignment.Status.ACCEPTED,
        )
        link = getattr(assignment, 'chat_link', None)
        if link is None:
            raise ValidationError({'assignment_id': 'Lịch này chưa có cuộc trò chuyện.'})
        return Response({
            'message': 'Lấy cuộc trò chuyện thành công.',
            'data': {
                'conversation': conversation_summary(link.conversation, request.user),
                'assignment': assignment_summary(assignment),
            },
        })


class ConversationListView(generics.GenericAPIView):
    pagination_class = ConversationPagination

    def get(self, request):
        last_visible = ChatMessage.objects.filter(conversation_id=OuterRef('pk')).filter(
            ~Q(message_type=ChatMessage.MessageType.SYSTEM)
            | Q(message_type=ChatMessage.MessageType.SYSTEM, recipient=request.user)
        ).order_by('-id')
        queryset = ChatConversation.objects.filter(
            Q(customer=request.user) | Q(worker=request.user)
        ).select_related('customer', 'worker', 'worker__worker_profile').annotate(
            last_visible_at=Subquery(last_visible.values('created_at')[:1]),
        ).order_by(F('last_visible_at').desc(nulls_last=True), '-id')
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        results = [conversation_summary(conversation, request.user) for conversation in page]
        return Response({
            'message': 'Lấy danh sách cuộc trò chuyện thành công.',
            'data': {
                'results': results,
                'count': paginator.page.paginator.count,
                'total_unread': total_unread_messages(request.user),
                'next': paginator.get_next_link(),
                'previous': paginator.get_previous_link(),
            },
        })


class ConversationDetailView(generics.GenericAPIView):
    def get(self, request, conversation_id):
        conversation = get_participant_conversation(conversation_id, request.user)
        links = conversation.assignment_links.select_related(
            'assignment__schedule__booking__service',
        ).order_by('-assignment__assigned_at', '-assignment_id')
        return Response({
            'message': 'Lấy chi tiết cuộc trò chuyện thành công.',
            'data': {
                'conversation': conversation_summary(conversation, request.user),
                'assignments': [assignment_summary(link.assignment) for link in links],
            },
        })


class MessageListView(generics.GenericAPIView):
    serializer_class = MessageListInputSerializer

    def post(self, request):
        params = self.get_serializer(data=request.data)
        params.is_valid(raise_exception=True)
        values = params.validated_data
        conversation = get_participant_conversation(values['conversation_id'], request.user)
        messages = visible_messages(conversation, request.user).order_by('-id')
        if values.get('cursor') is not None:
            messages = messages.filter(id__lt=values['cursor'])
        limit = values['limit']
        page = list(messages[:limit + 1])
        has_more = len(page) > limit
        page = page[:limit]
        return Response({
            'message': 'Lấy tin nhắn thành công.',
            'data': {
                'results': ChatMessageSerializer(reversed(page), many=True).data,
                'next_cursor': page[-1].id if has_more else None,
            },
        })


class MessageSendView(generics.GenericAPIView):
    serializer_class = MessageSendInputSerializer

    def post(self, request):
        message = send_text_message(request.user, request.data)
        return Response({
            'message': 'Gửi tin nhắn thành công.',
            'data': ChatMessageSerializer(message).data,
        }, status=status.HTTP_201_CREATED)


class MessageReadView(generics.GenericAPIView):
    serializer_class = MessageReadInputSerializer

    def post(self, request):
        count = mark_messages_read(request.user, request.data)
        return Response({'message': 'Đánh dấu đã đọc thành công.', 'data': {'marked_read': count}})
