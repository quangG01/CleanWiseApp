from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from .models import Booking, BookingAssignment, BookingSchedule, Notification

User = get_user_model()

FREE_CANCEL_HOURS = 6
LATE_CANCEL_HOURS = 2


def _hours_between(now, target):
    return round((target - now).total_seconds() / 3600, 2)


def _notify_admins(*, title, message, related_booking=None):
    admins = User.objects.filter(role='ADMIN', is_active=True)
    Notification.objects.bulk_create([
        Notification(
            user=admin, title=title, message=message,
            type=Notification.Type.ASSIGNMENT, related_booking=related_booking,
        )
        for admin in admins
    ])


def _sync_booking_status_after_claim(booking):
    total = booking.schedules.count()
    accepted = (
        BookingAssignment.objects.filter(
            schedule__booking=booking, status=BookingAssignment.Status.ACCEPTED,
        )
        .values('schedule_id').distinct().count()
    )
    if total and accepted >= total and booking.status in (
        Booking.Status.PENDING, Booking.Status.WAITING_ASSIGNMENT,
    ):
        booking.status = Booking.Status.ASSIGNED
        booking.save(update_fields=['status', 'updated_at'])


def list_available_schedules_for_worker(worker):
    """Tất cả buổi làm đang mở, chưa ai nhận. Chưa lọc theo chuyên môn/khu vực
    vì DB hiện tại không có bảng lưu thông tin đó cho worker."""
    return (
        BookingSchedule.objects
        .filter(
            status=BookingSchedule.Status.PENDING,
            scheduled_start__gt=timezone.now(),
            booking__status=Booking.Status.WAITING_ASSIGNMENT,
        )
        .exclude(assignments__status=BookingAssignment.Status.ACCEPTED)
        .select_related('booking', 'booking__service', 'booking__address')
        .order_by('scheduled_start')
    )


def list_my_schedules(worker, schedule_status=None):
    qs = (
        BookingSchedule.objects.filter(
            assignments__worker=worker,
            assignments__status=BookingAssignment.Status.ACCEPTED,
        )
        .select_related('booking', 'booking__service', 'booking__address')
        .order_by('scheduled_start')
    )
    if schedule_status:
        qs = qs.filter(status=schedule_status)
    return qs


@transaction.atomic
def claim_schedule(*, schedule_id, worker):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update().select_related('booking'),
        pk=schedule_id,
    )
    booking = schedule.booking

    if booking.status != Booking.Status.WAITING_ASSIGNMENT:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không ở trạng thái chờ nhận việc.'})
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không còn khả dụng.'})
    if schedule.scheduled_start <= timezone.now():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã quá giờ bắt đầu.'})
    if BookingAssignment.objects.filter(
        schedule=schedule, status=BookingAssignment.Status.ACCEPTED,
    ).exists():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc này đã có người nhận.'})

    now = timezone.now()
    assignment = BookingAssignment.objects.create(
        schedule=schedule, worker=worker,
        assigned_method=BookingAssignment.AssignedMethod.MANUAL,
        status=BookingAssignment.Status.ACCEPTED,
        assigned_at=now, responded_at=now,
    )
    BookingAssignment.objects.filter(
        schedule=schedule, status=BookingAssignment.Status.PENDING,
    ).exclude(pk=assignment.pk).update(
        status=BookingAssignment.Status.CANCELLED,
        response_note='Tự động hủy do đã có nhân viên khác nhận việc.',
        responded_at=now, updated_at=now,
    )
    _sync_booking_status_after_claim(booking)
    return assignment


@transaction.atomic
def cancel_assignment(*, assignment_id, worker, reason):
    reason = (reason or '').strip()
    if not reason:
        raise serializers.ValidationError({'reason': 'Vui lòng nhập lý do hủy.'})

    assignment = get_object_or_404(
        BookingAssignment.objects.select_for_update().select_related('schedule', 'schedule__booking'),
        pk=assignment_id, worker=worker, status=BookingAssignment.Status.ACCEPTED,
    )
    schedule = BookingSchedule.objects.select_for_update().get(pk=assignment.schedule_id)
    booking = schedule.booking
    now = timezone.now()

    if schedule.status in (BookingSchedule.Status.COMPLETED, BookingSchedule.Status.CANCELLED):
        raise serializers.ValidationError({'assignment': 'Buổi làm việc đã kết thúc hoặc đã hủy trước đó.'})
    if now >= schedule.scheduled_end:
        raise serializers.ValidationError({
            'assignment': 'Đã quá giờ kết thúc buổi làm, vui lòng liên hệ admin để xử lý.',
        })

    hours_before = _hours_between(now, schedule.scheduled_start)

    assignment.status = BookingAssignment.Status.CANCELLED
    assignment.response_note = reason
    assignment.responded_at = now
    assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

    schedule.status = BookingSchedule.Status.PENDING
    schedule.save(update_fields=['status', 'updated_at'])
    if booking.status == Booking.Status.ASSIGNED:
        booking.status = Booking.Status.WAITING_ASSIGNMENT
        booking.save(update_fields=['status', 'updated_at'])

    if hours_before < FREE_CANCEL_HOURS:
        urgency = 'GẤP (dưới 2 tiếng)' if hours_before < LATE_CANCEL_HOURS else 'trễ (dưới 6 tiếng)'
        _notify_admins(
            title=f'Worker hủy nhận việc {urgency}',
            message=(
                f'{worker} vừa hủy nhận việc cho đơn {booking.booking_code}, '
                f'còn {hours_before} tiếng nữa tới giờ hẹn. Lý do: {reason}'
            ),
            related_booking=booking,
        )

    return assignment


@transaction.atomic
def admin_assign_worker(*, schedule_id, worker_id, admin_user, note=None):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update().select_related('booking'),
        pk=schedule_id,
    )
    booking = schedule.booking
    worker = get_object_or_404(User, pk=worker_id, role='WORKER', is_active=True)

    if schedule.status == BookingSchedule.Status.COMPLETED:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã hoàn thành, không thể gán lại.'})

    now = timezone.now()
    BookingAssignment.objects.filter(
        schedule=schedule,
        status__in=[BookingAssignment.Status.ACCEPTED, BookingAssignment.Status.PENDING],
    ).update(
        status=BookingAssignment.Status.CANCELLED,
        response_note='Admin gán lại nhân viên khác.',
        responded_at=now, updated_at=now,
    )
    assignment = BookingAssignment.objects.create(
        schedule=schedule, worker=worker, assigned_by=admin_user,
        assigned_method=BookingAssignment.AssignedMethod.MANUAL,
        status=BookingAssignment.Status.ACCEPTED,
        assigned_at=now, responded_at=now, response_note=note,
    )
    schedule.status = BookingSchedule.Status.PENDING
    schedule.save(update_fields=['status', 'updated_at'])
    _sync_booking_status_after_claim(booking)
    return assignment