from django.urls import path
from .help_images import HelpImageView

from .views import (ConversationDetailView, ConversationListCreateView, MessageListCreateView, RunDetailView,
                    HelpArticleListView, HelpArticleDetailView)

urlpatterns = [
    path('help-images/<str:name>/', HelpImageView.as_view(), name='chatbot-help-image'),
    path('help-articles/', HelpArticleListView.as_view(), name='chatbot-help-articles'),
    path('help-articles/<int:pk>/', HelpArticleDetailView.as_view(), name='chatbot-help-article-detail'),
    path('conversations/', ConversationListCreateView.as_view(), name='chatbot-conversations'),
    path('conversations/<int:pk>/', ConversationDetailView.as_view(), name='chatbot-conversation-detail'),
    path('conversations/<int:pk>/messages/', MessageListCreateView.as_view(), name='chatbot-messages'),
    path('runs/<uuid:pk>/', RunDetailView.as_view(), name='chatbot-run-detail'),
]
