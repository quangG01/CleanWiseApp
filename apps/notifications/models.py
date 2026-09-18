from django.conf import settings
from django.db import models


class Notification(models.Model):
    class Type(models.TextChoices):
        BOOKING = 'BOOKING', 'Đặt lịch'
        PAYMENT = 'PAYMENT', 'Thanh toán'
        ASSIGNMENT = 'ASSIGNMENT', 'Phân công'
        COMPLAINT = 'COMPLAINT', 'Khiếu nại'
        SYSTEM = 'SYSTEM', 'Hệ thống'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField()
    type = models.CharField(max_length=30, choices=Type.choices, default=Type.SYSTEM)
    related_booking = models.ForeignKey('bookings.Booking', on_delete=models.DO_NOTHING, related_name='notifications', blank=True, null=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return self.title
