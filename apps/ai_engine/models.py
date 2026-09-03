from django.db import models
from django.conf import settings


class ChatbotSession(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Đang mở'
        CLOSED = 'CLOSED', 'Đã đóng'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='chatbot_sessions')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chatbot_sessions'
        ordering = ['-created_at']

    def __str__(self):
        return f"Chatbot session #{self.pk} - {self.customer}"


class ChatbotMessage(models.Model):
    class SenderType(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Khách hàng'
        BOT = 'BOT', 'Bot'
        SYSTEM = 'SYSTEM', 'Hệ thống'

    session = models.ForeignKey(ChatbotSession, on_delete=models.DO_NOTHING, related_name='messages')
    sender_type = models.CharField(max_length=20, choices=SenderType.choices)
    message = models.TextField()
    intent = models.CharField(max_length=100, blank=True, null=True)
    metadata = models.JSONField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chatbot_messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender_type}: {self.message[:40]}"


class AIAssignmentLog(models.Model):
    class Status(models.TextChoices):
        SUCCESS = 'SUCCESS', 'Thành công'
        NO_CANDIDATE = 'NO_CANDIDATE', 'Không có ứng viên'
        FAILED = 'FAILED', 'Thất bại'

    booking = models.ForeignKey('bookings.Booking', on_delete=models.DO_NOTHING, related_name='ai_assignment_logs')
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='requested_ai_assignment_logs'
    )
    selected_worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='selected_ai_assignment_logs',
        blank=True,
        null=True
    )
    candidate_data = models.JSONField(blank=True, null=True)
    ai_result = models.JSONField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'ai_assignment_logs'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booking} - {self.status}"
