from datetime import timedelta

from celery import shared_task
from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.bookings.models import BookingSchedule

from .assignment_service import (
    expire_unclaimed_schedules,
    handle_missed_checkouts,
)
from .models import BookingAssignment

REMINDER_LEAD_MINUTES = 60


@shared_task
def expire_unclaimed_schedules_task():
    expire_unclaimed_schedules()


@shared_task
def handle_missed_checkouts_task():
    handle_missed_checkouts()


@shared_task
def send_schedule_reminders_task():
    from apps.notifications.services import (
        notify_customer_schedule_reminder,
        notify_worker_schedule_reminder,
    )

    now = timezone.now()
    accepted = BookingAssignment.objects.filter(
        schedule=OuterRef('pk'),
        status=BookingAssignment.Status.ACCEPTED,
    )
    schedules = (
        BookingSchedule.objects
        .filter(
            status=BookingSchedule.Status.PENDING,
            reminder_sent_at__isnull=True,
            scheduled_start__gt=now,
            scheduled_start__lte=now + timedelta(minutes=REMINDER_LEAD_MINUTES),
        )
        .filter(Exists(accepted))
        .select_related('booking', 'booking__customer')
    )

    for schedule in list(schedules):
        with transaction.atomic():
            # Chỉ một lần chạy giành được quyền gửi cho mỗi buổi
            claimed = BookingSchedule.objects.filter(
                pk=schedule.pk, reminder_sent_at__isnull=True,
            ).update(reminder_sent_at=now)
            if not claimed:
                continue

            assignment = (
                schedule.assignments
                .filter(status=BookingAssignment.Status.ACCEPTED)
                .select_related('worker')
                .first()
            )
            notify_customer_schedule_reminder(schedule)
            if assignment:
                notify_worker_schedule_reminder(schedule, assignment.worker)