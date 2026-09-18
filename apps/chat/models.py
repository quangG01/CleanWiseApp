from django.conf import settings
from django.db import models


class ChatConversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Đang mở'
        CLOSED = 'CLOSED', 'Đã đóng'

    booking = models.ForeignKey('bookings.Booking', on_delete=models.DO_NOTHING, related_name='chat_conversations', blank=True, null=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='customer_chat_conversations')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='worker_chat_conversations')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_conversations'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.customer} - {self.worker}'


class ChatMessage(models.Model):
    class MessageType(models.TextChoices):
        TEXT = 'TEXT', 'Văn bản'
        IMAGE = 'IMAGE', 'Hình ảnh'
        FILE = 'FILE', 'Tệp'

    conversation = models.ForeignKey(ChatConversation, on_delete=models.DO_NOTHING, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='chat_messages')
    message = models.TextField()
    message_type = models.CharField(max_length=20, choices=MessageType.choices, default=MessageType.TEXT)
    attachment = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']

    def __str__(self):
        return f'{self.sender}: {self.message[:40]}'
