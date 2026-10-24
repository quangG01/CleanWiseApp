from django.conf import settings
from django.db import models


class ChatConversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Đang mở'
        CLOSED = 'CLOSED', 'Đã đóng'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='customer_chat_conversations')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='worker_chat_conversations')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_conversations'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['customer', 'worker'], name='chat_conversation_pair_unique'),
            models.CheckConstraint(condition=~models.Q(customer=models.F('worker')), name='chat_conversation_distinct_users'),
        ]

    def __str__(self):
        return f'{self.customer} - {self.worker}'


class ChatConversationAssignment(models.Model):
    conversation = models.ForeignKey(ChatConversation, on_delete=models.PROTECT, related_name='assignment_links')
    assignment = models.OneToOneField('worker.BookingAssignment', on_delete=models.PROTECT, related_name='chat_link')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_conversation_assignments'


class ChatMessage(models.Model):
    class MessageType(models.TextChoices):
        TEXT = 'TEXT', 'Văn bản'
        IMAGE = 'IMAGE', 'Hình ảnh'
        FILE = 'FILE', 'Tệp'
        SYSTEM = 'SYSTEM', 'Hệ thống'

    conversation = models.ForeignKey(ChatConversation, on_delete=models.DO_NOTHING, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='chat_messages', blank=True, null=True)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='received_chat_system_messages', blank=True, null=True)
    related_assignment = models.ForeignKey('worker.BookingAssignment', on_delete=models.PROTECT, related_name='chat_system_messages', blank=True, null=True)
    message = models.TextField()
    message_type = models.CharField(max_length=20, choices=MessageType.choices, default=MessageType.TEXT)
    attachment = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    client_message_id = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at', 'id']
        indexes = [
            models.Index(fields=['conversation', 'id'], name='chat_message_convo_id_idx'),
            models.Index(fields=['conversation', 'recipient', 'is_read'], name='chat_message_unread_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(message_type='SYSTEM', sender__isnull=True, recipient__isnull=False, related_assignment__isnull=False)
                    | models.Q(message_type__in=['TEXT', 'IMAGE', 'FILE'], sender__isnull=False, recipient__isnull=True, related_assignment__isnull=True)
                ),
                name='chat_message_actor_check',
            ),
            models.UniqueConstraint(
                fields=['related_assignment', 'recipient'],
                condition=models.Q(message_type='SYSTEM'),
                name='chat_system_assignment_recipient_unique',
            ),
        ]

    def __str__(self):
        return f'{self.sender}: {self.message[:40]}'


class ChatRestriction(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    locked_until = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class ChatViolation(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(ChatConversation, on_delete=models.PROTECT)
    categories = models.JSONField(default=list)
    action = models.CharField(max_length=20)
    locked_until = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'created_at'], name='chat_violation_user_time')]


class ChatSendAttempt(models.Model):
    """Idempotent outcomes, including rejected sends; never store raw content."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    conversation = models.ForeignKey(ChatConversation, on_delete=models.PROTECT)
    client_message_id = models.CharField(max_length=100)
    fingerprint = models.CharField(max_length=64)
    message = models.ForeignKey(ChatMessage, on_delete=models.PROTECT, null=True)
    outcome = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'client_message_id'], name='chat_send_attempt_unique')]


class ChatRestrictionAudit(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    administrator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    previous_locked_until = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)
