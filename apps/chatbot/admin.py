from django.contrib import admin

from apps.ai_engine.models import ChatbotMessage, ChatbotSession
from .models import ChatbotRun, HelpArticle


@admin.register(HelpArticle)
class HelpArticleAdmin(admin.ModelAdmin):
    list_display = ['title', 'slug', 'version', 'status', 'role', 'effective_from', 'published_at']
    list_filter = ['status', 'role']
    search_fields = ['title', 'slug', 'keywords']
    readonly_fields = ['published_at', 'updated_at']

    def get_readonly_fields(self, request, obj=None):
        fields = list(self.readonly_fields)
        if obj and obj.published_at:
            fields += ['slug', 'version', 'title', 'summary', 'sections', 'keywords', 'role',
                       'source_document', 'effective_from', 'effective_until']
        return fields


class ReadOnlyChatbotAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChatbotSession)
class ConversationAdmin(ReadOnlyChatbotAdmin):
    list_display = ['id', 'customer', 'title', 'status', 'updated_at']
    list_filter = ['status']
    search_fields = ['title', 'customer__username']


@admin.register(ChatbotMessage)
class MessageAdmin(ReadOnlyChatbotAdmin):
    list_display = ['id', 'session', 'sender_type', 'status', 'created_at']
    list_filter = ['sender_type', 'status']


@admin.register(ChatbotRun)
class RunAdmin(ReadOnlyChatbotAdmin):
    list_display = ['id', 'conversation', 'status', 'model_name', 'attempts', 'duration_ms']
    list_filter = ['status', 'model_name']
