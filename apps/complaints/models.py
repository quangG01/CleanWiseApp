# apps/complaints/models.py

from django.conf import settings
from django.db import models


class ComplaintIssueType(models.Model):
    class Stage(models.TextChoices):
        BEFORE_SERVICE = 'BEFORE_SERVICE', 'Trước khi thực hiện'
        IN_SERVICE = 'IN_SERVICE', 'Đang thực hiện'
        AFTER_SERVICE = 'AFTER_SERVICE', 'Sau khi hoàn thành'
        ANY = 'ANY', 'Mọi thời điểm'

    code = models.CharField(
        max_length=50,
        unique=True,
    )

    name = models.CharField(
        max_length=150,
    )

    description = models.TextField(
        blank=True,
        default='',
    )

    stage = models.CharField(
        max_length=30,
        choices=Stage.choices,
        default=Stage.ANY,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        db_table = 'complaint_issue_types'
        ordering = ['stage', 'name']

    def __str__(self):
        return self.name


class Complaint(models.Model):
    class Stage(models.TextChoices):
        BEFORE_SERVICE = 'BEFORE_SERVICE', 'Trước khi thực hiện'
        IN_SERVICE = 'IN_SERVICE', 'Đang thực hiện'
        AFTER_SERVICE = 'AFTER_SERVICE', 'Sau khi hoàn thành'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        IN_REVIEW = 'IN_REVIEW', 'Đang xem xét'
        RESOLVED = 'RESOLVED', 'Đã xử lý'
        REJECTED = 'REJECTED', 'Bị từ chối'
        CANCELLED = 'CANCELLED', 'Đã hủy'

    schedule = models.ForeignKey(
        'bookings.BookingSchedule',
        on_delete=models.DO_NOTHING,
        related_name='complaints',
        null=True,
        blank=True,
    )
    
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='complaints',
    )

    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.DO_NOTHING,
        related_name='complaints',
    )

    issue_type = models.ForeignKey(
        ComplaintIssueType,
        on_delete=models.PROTECT,
        related_name='complaints',
    )

    # Backend tự xác định từ Booking.status.
    stage = models.CharField(
        max_length=30,
        choices=Stage.choices,
    )

    # Khách có thể bỏ trống.
    # Nội dung chi tiết không bắt buộc vì issue_type đã thể hiện lý do.
    content = models.TextField(
        blank=True,
        default='',
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='resolved_complaints',
        blank=True,
        null=True,
    )

    resolution_note = models.TextField(
        blank=True,
        null=True,
    )

    resolved_at = models.DateTimeField(
        blank=True,
        null=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.booking} - {self.issue_type.name}'
    

def complaint_attachment_path(instance, filename):
    return f'complaints/{instance.complaint_id}/{filename}'

class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='attachments')
    file = models.ImageField(upload_to=complaint_attachment_path)
    file_type = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaint_attachments'

    def __str__(self):
        return self.file