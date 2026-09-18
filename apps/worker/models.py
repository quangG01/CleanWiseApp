from django.conf import settings
from django.db import models


class Area(models.Model):
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'areas'
        constraints = [models.UniqueConstraint(fields=['city', 'name'], name='areas_city_name_unique')]
        ordering = ['city', 'name']

    def __str__(self):
        return f'{self.name}, {self.city}'


class WorkerWorkingArea(models.Model):
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='working_areas')
    area = models.ForeignKey(Area, on_delete=models.DO_NOTHING, related_name='workers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'worker_working_areas'
        constraints = [models.UniqueConstraint(fields=['worker', 'area'], name='worker_working_areas_worker_area_unique')]

    def __str__(self):
        return f'{self.worker} - {self.area}'


class WorkerAvailability(models.Model):
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='availabilities')
    weekday = models.IntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'worker_availability'
        constraints = [
            models.CheckConstraint(condition=models.Q(weekday__gte=0) & models.Q(weekday__lte=6), name='worker_availability_weekday_check'),
            models.CheckConstraint(condition=models.Q(start_time__lt=models.F('end_time')), name='worker_availability_time_check'),
        ]
        ordering = ['worker_id', 'weekday', 'start_time']

    def __str__(self):
        return f'{self.worker} - {self.weekday} {self.start_time}-{self.end_time}'


class BookingAssignment(models.Model):
    class AssignedMethod(models.TextChoices):
        MANUAL = 'MANUAL', 'Thủ công'
        AI = 'AI', 'AI'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ phản hồi'
        ACCEPTED = 'ACCEPTED', 'Đã nhận'
        REJECTED = 'REJECTED', 'Từ chối'
        CANCELLED = 'CANCELLED', 'Đã hủy'
        EXPIRED = 'EXPIRED', 'Đã hết hạn'

    schedule = models.ForeignKey('bookings.BookingSchedule', on_delete=models.DO_NOTHING, related_name='assignments')
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='booking_assignments')
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='assigned_booking_schedules', blank=True, null=True)
    assigned_method = models.CharField(max_length=20, choices=AssignedMethod.choices, default=AssignedMethod.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    response_note = models.TextField(blank=True, null=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(blank=True, null=True)
    expired_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'booking_assignments'
        indexes = [
            models.Index(fields=['schedule', 'status'], name='ba_schedule_status_idx'),
            models.Index(fields=['worker', 'status'], name='ba_worker_status_idx'),
        ]
        ordering = ['-assigned_at']

    def __str__(self):
        return f'{self.schedule} - {self.worker}'
