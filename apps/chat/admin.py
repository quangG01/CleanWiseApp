from django.contrib import admin

from .models import ChatConversation, ChatConversationAssignment, ChatMessage


admin.site.register(ChatConversation)
admin.site.register(ChatConversationAssignment)
admin.site.register(ChatMessage)
