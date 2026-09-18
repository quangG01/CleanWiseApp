from django.contrib import admin

from .models import ChatConversation, ChatMessage


admin.site.register(ChatConversation)
admin.site.register(ChatMessage)
