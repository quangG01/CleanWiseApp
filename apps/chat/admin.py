from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import ChatConversation, ChatConversationAssignment, ChatMessage, ChatRestriction, ChatViolation, ChatRestrictionAudit
from .realtime import publish_moderation


admin.site.register(ChatConversation)
admin.site.register(ChatConversationAssignment)
admin.site.register(ChatMessage)


@admin.register(ChatViolation)
class ChatViolationAdmin(admin.ModelAdmin):
    list_display = ('user', 'conversation', 'categories', 'action', 'locked_until', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'conversation', 'categories', 'action', 'locked_until', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChatRestriction)
class ChatRestrictionAdmin(admin.ModelAdmin):
    list_display = ('user', 'locked_until', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('user', 'locked_until', 'updated_at')
    actions = ('unlock_chat',)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description='Gỡ khóa gửi chat (có ghi nhật ký)', permissions=['change'])
    def unlock_chat(self, request, queryset):
        for selected in queryset.order_by('user_id'):
            with transaction.atomic():
                get_user_model().objects.select_for_update().get(pk=selected.user_id)
                restriction = ChatRestriction.objects.get(pk=selected.pk)
                if not restriction.locked_until or restriction.locked_until <= timezone.now():
                    continue
                ChatRestrictionAudit.objects.create(user_id=restriction.user_id, administrator=request.user,
                                                     previous_locked_until=restriction.locked_until)
                restriction.locked_until = None
                restriction.save(update_fields=['locked_until', 'updated_at'])
                transaction.on_commit(lambda uid=restriction.user_id: publish_moderation(uid))


@admin.register(ChatRestrictionAudit)
class ChatRestrictionAuditAdmin(admin.ModelAdmin):
    list_display = ('user', 'administrator', 'previous_locked_until', 'created_at')
    readonly_fields = ('user', 'administrator', 'previous_locked_until', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
