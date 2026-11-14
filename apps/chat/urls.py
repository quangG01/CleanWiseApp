from django.urls import path

from .views import (
    ConversationByAssignmentView, ConversationDetailView, ConversationListView,
    MessageListView, MessageReadView, MessageSendView, SupportConversationView,
)


urlpatterns = [
    path('support/<int:user_id>/', SupportConversationView.as_view(), name='chat-support-conversation'),
    path('assignments/<int:assignment_id>/conversation/', ConversationByAssignmentView.as_view(), name='chat-by-assignment'),
    path('conversations/', ConversationListView.as_view(), name='chat-conversations'),
    path('conversations/<int:conversation_id>/', ConversationDetailView.as_view(), name='chat-conversation-detail'),
    path('messages/list/', MessageListView.as_view(), name='chat-message-list'),
    path('messages/send/', MessageSendView.as_view(), name='chat-message-send'),
    path('messages/read/', MessageReadView.as_view(), name='chat-message-read'),
]
