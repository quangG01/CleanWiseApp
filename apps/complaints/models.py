from django.conf import settings
from django.db import models


class Complaint(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        IN_REVIEW = 'IN_REVIEW', 'Đang xem xét'
        RESOLVED = 'RESOLVED', 'Đã xử lý'
        REJECTED = 'REJECTED', 'Bị từ chối'
        CANCELLED = 'CANCELLED', 'Đã hủy'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='complaints')
    booking = models.ForeignKey('bookings.Booking', on_delete=models.DO_NOTHING, related_name='complaints')
    reason = models.CharField(max_length=150)
    content = models.TextField()
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='resolved_complaints', blank=True, null=True)
    resolution_note = models.TextField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.booking} - {self.reason}'


class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.DO_NOTHING, related_name='attachments')
    file = models.CharField(max_length=255)
    file_type = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaint_attachments'

    def __str__(self):
        return self.file
