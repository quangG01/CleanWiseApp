import re
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import Booking, BookingSchedule
from apps.notifications.models import Notification

from .constants import MIN_CANCEL_HOURS
from .models import BookingAssignment, WorkerWorkingArea

User = get_user_model()

# Booking còn "sống": buổi nào chưa có người nhận thì vẫn nhận được.
# Gói tháng: booking có thể đã IN_PROGRESS mà buổi sau vẫn trống.
OPEN_BOOKING_STATUSES = (
    Booking.Status.PENDING,
    Booking.Status.ASSIGNED,
    Booking.Status.IN_PROGRESS,
)
ACTIVE_SCHEDULE_STATUSES = (
    BookingSchedule.Status.PENDING,
    BookingSchedule.Status.IN_PROGRESS,
)


# ---------------------------------------------------------------- helpers

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


def _get_worker_profile(worker):
    # Reverse OneToOne: thiếu hồ sơ thì ném RelatedObjectDoesNotExist
    # (là con của AttributeError) nên getattr có default vẫn an toàn.
    return getattr(worker, 'worker_profile', None)


def _get_claimable_profile(worker):
    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE':
        raise serializers.ValidationError({'profile': 'Hồ sơ chưa được duyệt nên chưa thể nhận việc.'})
    if not profile.registered_service_id:
        raise serializers.ValidationError({'profile': 'Bạn chưa chọn dịch vụ đăng ký.'})
    return profile


# Bỏ tiền tố hành chính ("Thành phố", "TP", "TP.", "Tỉnh") trước khi so
# khớp, vì worker đăng ký khu vực kiểu "TP Hồ Chí Minh" nhưng địa chỉ
# booking lại lưu kiểu "Thành phố Hồ Chí Minh" — hai chuỗi không so
# __iexact khớp nhau được nếu không bỏ tiền tố trước.
_CITY_PREFIX_RE = re.compile(r'^(thành phố|tp\.?|tỉnh)\s+', re.IGNORECASE)


def _norm(value):
    v = (value or '').strip().lower()
    v = _CITY_PREFIX_RE.sub('', v)
    return v.strip()


def _worker_area_keys(worker):
    """
    Tên khu vực (đã chuẩn hóa) mà nhân viên đăng ký. Booking chỉ có
    address.city nên so khớp với area.city hoặc area.name.
    """
    keys = set()
    rows = WorkerWorkingArea.objects.filter(
        worker=worker, area__is_active=True,
    ).values_list('area__city', 'area__name')
    for city, name in rows:
        for v in (city, name):
            if _norm(v):
                keys.add(_norm(v))
    return keys


def _annotate_total_sessions(queryset):
    """Tổng số buổi chưa hủy của booking, để FE hiện 'buổi 3/8'."""
    sessions = (
        BookingSchedule.objects.filter(booking=OuterRef('booking'))
        .exclude(status=BookingSchedule.Status.CANCELLED)
        .order_by()  # bỏ Meta.ordering, nếu không GROUP BY bị sai
        .values('booking')
        .annotate(c=Count('id'))
        .values('c')
    )
    return queryset.annotate(total_sessions=Subquery(sessions))


def _has_time_conflict(worker, schedule):
    return BookingSchedule.objects.filter(
        assignments__worker=worker,
        assignments__status=BookingAssignment.Status.ACCEPTED,
        status__in=ACTIVE_SCHEDULE_STATUSES,
        scheduled_start__lt=schedule.scheduled_end,
        scheduled_end__gt=schedule.scheduled_start,
    ).exclude(pk=schedule.pk).exists()


def _sync_booking_status_after_claim(booking):
    active = booking.schedules.exclude(status=BookingSchedule.Status.CANCELLED)
    total = active.count()
    accepted = active.filter(
        assignments__status=BookingAssignment.Status.ACCEPTED,
    ).distinct().count()
    if total and accepted >= total and booking.status == Booking.Status.PENDING:
        booking.status = Booking.Status.ASSIGNED
        booking.save(update_fields=['status', 'updated_at'])


def get_cancel_deadline(schedule):
    """Hạn chót để worker tự hủy (dùng cho FE hiển thị)."""
    return schedule.scheduled_start - timedelta(hours=MIN_CANCEL_HOURS)


@transaction.atomic
def expire_unclaimed_schedules():
    """
    Lazy expiry — được gọi ngay đầu các hàm list_* mỗi khi worker load
    danh sách, KHÔNG cần cron/Celery. Chạy rất nhẹ vì chỉ động tới các
    dòng đã thật sự quá hạn (status=PENDING và scheduled_start < now).

    - Buổi quá scheduled_start mà chưa có assignment ACCEPTED -> MISSED.
    - Nếu booking không còn buổi PENDING/IN_PROGRESS nào (toàn bộ đã
      CANCELLED/MISSED) VÀ chưa từng có worker nào ACCEPTED buổi nào của
      booking đó -> booking chuyển FAILED. (Booking gói tháng đã có ít
      nhất 1 buổi được nhận thì KHÔNG tự FAILED chỉ vì 1 buổi lẻ trễ hạn.)
    """
    now = timezone.now()

    stale_schedules = (
        BookingSchedule.objects.select_for_update(of=('self',))
        .filter(status=BookingSchedule.Status.PENDING, scheduled_start__lt=now)
        .exclude(assignments__status=BookingAssignment.Status.ACCEPTED)
        .select_related('booking')
    )

    for schedule in stale_schedules:
        schedule.status = BookingSchedule.Status.MISSED
        schedule.cancel_reason = 'Hết hạn, không có nhân viên nhận việc.'
        schedule.cancelled_at = now
        schedule.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])

        booking = schedule.booking
        if booking.status in (Booking.Status.PENDING, Booking.Status.ASSIGNED):
            still_active = booking.schedules.filter(
                status__in=(BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS),
            ).exists()
            ever_had_worker = BookingAssignment.objects.filter(
                schedule__booking=booking, status=BookingAssignment.Status.ACCEPTED,
            ).exists()

            if not still_active and not ever_had_worker:
                booking.status = Booking.Status.FAILED
                booking.cancel_reason = 'Không có nhân viên nhận việc trong thời gian yêu cầu.'
                booking.cancelled_at = now
                booking.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])


# ---------------------------------------------------------------- queries
# Không prefetch 'assignments' ở đây: view đã Prefetch có filter ACCEPTED.

def list_available_schedules_for_worker(worker, *, booking_id=None, date_from=None, date_to=None):
    """Buổi làm còn trống, đúng dịch vụ + khu vực của nhân viên, không trùng giờ."""
    expire_unclaimed_schedules()

    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE' or not profile.registered_service_id:
        return BookingSchedule.objects.none()

    area_keys = _worker_area_keys(worker)
    if not area_keys:
        return BookingSchedule.objects.none()

    my_overlapping = BookingSchedule.objects.filter(
        assignments__worker=worker,
        assignments__status=BookingAssignment.Status.ACCEPTED,
        status__in=ACTIVE_SCHEDULE_STATUSES,
        scheduled_start__lt=OuterRef('scheduled_end'),
        scheduled_end__gt=OuterRef('scheduled_start'),
    )

    queryset = (
        BookingSchedule.objects.filter(
            status=BookingSchedule.Status.PENDING,
            scheduled_start__gt=timezone.now(),
            booking__status__in=OPEN_BOOKING_STATUSES,
            booking__service_id=profile.registered_service_id,
        )
        .exclude(assignments__status=BookingAssignment.Status.ACCEPTED)
        .exclude(Exists(my_overlapping))
        .select_related('booking', 'booking__service', 'booking__address')
    )

    if booking_id:
        queryset = queryset.filter(booking_id=booking_id)
    if date_from:
        queryset = queryset.filter(scheduled_start__date__gte=date_from)
    if date_to:
        queryset = queryset.filter(scheduled_start__date__lte=date_to)

    # DB không tự bỏ tiền tố "Thành phố"/"TP"/"Tỉnh" được nên lọc khu vực
    # bằng Python sau khi đã lọc các điều kiện khác trên DB (dataset nhỏ
    # ở quy mô hiện tại, không đáng lo hiệu năng).
    matched_ids = [
        s.id for s in queryset
        if _norm(s.booking.address.city) in area_keys
    ]
    queryset = BookingSchedule.objects.filter(id__in=matched_ids).select_related(
        'booking', 'booking__service', 'booking__address',
    )

    return _annotate_total_sessions(queryset).order_by('scheduled_start')


def list_my_schedules(worker, schedule_status=None):
    expire_unclaimed_schedules()

    queryset = BookingSchedule.objects.filter(
        assignments__worker=worker,
        assignments__status=BookingAssignment.Status.ACCEPTED,
    ).select_related('booking', 'booking__service', 'booking__address')
    if schedule_status:
        queryset = queryset.filter(status=schedule_status)
    return _annotate_total_sessions(queryset).order_by('scheduled_start')


# ---------------------------------------------------------------- commands

@transaction.atomic
def claim_schedule(*, schedule_id, worker):
    profile = _get_claimable_profile(worker)
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking', 'booking__address'),
        pk=schedule_id,
    )
    booking = schedule.booking

    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không còn nhận nhân viên.'})
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không còn khả dụng.'})
    if schedule.scheduled_start <= timezone.now():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã quá giờ bắt đầu.'})
    if booking.service_id != profile.registered_service_id:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không thuộc dịch vụ bạn đã đăng ký.'})
    if _norm(booking.address.city) not in _worker_area_keys(worker):
        raise serializers.ValidationError({'schedule': 'Buổi làm việc nằm ngoài khu vực làm việc của bạn.'})
    if BookingAssignment.objects.filter(schedule=schedule, status=BookingAssignment.Status.ACCEPTED).exists():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc này đã có người nhận.'})
    if _has_time_conflict(worker, schedule):
        raise serializers.ValidationError({'schedule': 'Bạn đã có buổi làm khác trùng khung giờ này.'})

    now = timezone.now()
    assignment = BookingAssignment.objects.create(
        schedule=schedule, worker=worker,
        assigned_method=BookingAssignment.AssignedMethod.MANUAL,
        status=BookingAssignment.Status.ACCEPTED, assigned_at=now, responded_at=now,
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
        BookingAssignment.objects.select_for_update(of=('self',)),
        pk=assignment_id, worker=worker, status=BookingAssignment.Status.ACCEPTED,
    )
    schedule = BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking').get(
        pk=assignment.schedule_id,
    )
    booking = schedule.booking
    now = timezone.now()

    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'assignment': 'Chỉ được hủy buổi chưa bắt đầu.'})
    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'assignment': 'Đơn hàng đã kết thúc hoặc đã hủy.'})

    hours_before = _hours_between(now, schedule.scheduled_start)
    if hours_before < MIN_CANCEL_HOURS:
        raise serializers.ValidationError({
            'assignment': (
                f'Chỉ được tự hủy trước giờ làm ít nhất {MIN_CANCEL_HOURS} tiếng. '
                'Vui lòng liên hệ quản trị viên để được hỗ trợ.'
            ),
        })

    # Buổi vẫn PENDING -> nhân viên khác thấy lại và claim được
    assignment.status = BookingAssignment.Status.CANCELLED
    assignment.response_note = reason
    assignment.responded_at = now
    assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

    # Đơn đã đủ người (ASSIGNED) nay lại thiếu -> về PENDING.
    # Đơn IN_PROGRESS (gói tháng đang chạy) giữ nguyên.
    if booking.status == Booking.Status.ASSIGNED:
        booking.status = Booking.Status.PENDING
        booking.save(update_fields=['status', 'updated_at'])

    return assignment


@transaction.atomic
def admin_assign_worker(*, schedule_id, worker_id, admin_user, note=None):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking'),
        pk=schedule_id,
    )
    booking = schedule.booking
    worker = get_object_or_404(User, pk=worker_id, role='WORKER', is_active=True)

    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE':
        raise serializers.ValidationError({'worker': 'Hồ sơ nhân viên chưa được duyệt.'})
    if schedule.status in (BookingSchedule.Status.COMPLETED, BookingSchedule.Status.CANCELLED):
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã hoàn thành hoặc đã hủy, không thể gán.'})
    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng đã kết thúc hoặc đã hủy.'})

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
        status=BookingAssignment.Status.ACCEPTED, assigned_at=now, responded_at=now, response_note=note,
    )
    _sync_booking_status_after_claim(booking)
    return assignment