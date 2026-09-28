import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import Booking, BookingSchedule
from apps.notifications.models import Notification
from apps.chat.service import ensure_chat_for_assignment
from apps.payments.models import Payment
from apps.vouchers.voucher_service import (
    mark_user_voucher_used,
    release_user_voucher,
)
from apps.wallets import earning_service

from .constants import MIN_CANCEL_HOURS
from .models import BookingAssignment, WorkerWorkingArea

User = get_user_model()

OPEN_BOOKING_STATUSES = (
    Booking.Status.PENDING,
    Booking.Status.ASSIGNED,
    Booking.Status.IN_PROGRESS,
)
ACTIVE_SCHEDULE_STATUSES = (
    BookingSchedule.Status.PENDING,
    BookingSchedule.Status.IN_PROGRESS,
)

CHECKOUT_GRACE_MINUTES = getattr(settings, 'CHECKOUT_GRACE_MINUTES', 60)
CHECKIN_MISSED_GRACE_MINUTES = getattr(settings, 'CHECKIN_MISSED_GRACE_MINUTES', 60)


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
    return getattr(worker, 'worker_profile', None)


def _get_claimable_profile(worker):
    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE':
        raise serializers.ValidationError({'profile': 'Hồ sơ chưa được duyệt nên chưa thể nhận việc.'})
    if not profile.registered_service_id:
        raise serializers.ValidationError({'profile': 'Bạn chưa chọn dịch vụ đăng ký.'})
    return profile


def _has_cash_payment(booking):
    return Payment.objects.filter(booking=booking, method=Payment.Method.CASH).exists()


def _is_bookable(booking):
    return booking.payment_status == Booking.PaymentStatus.PAID or _has_cash_payment(booking)


_CITY_PREFIX_RE = re.compile(r'^(thành phố|tp\.?|tỉnh)\s+', re.IGNORECASE)


def _norm(value):
    v = (value or '').strip().lower()
    v = _CITY_PREFIX_RE.sub('', v)
    return v.strip()


def _worker_area_keys(worker):
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
    sessions = (
        BookingSchedule.objects.filter(booking=OuterRef('booking'))
        .exclude(status=BookingSchedule.Status.CANCELLED)
        .order_by()
        .values('booking')
        .annotate(c=Count('id'))
        .values('c')
    )
    return queryset.annotate(total_sessions=Subquery(sessions))


def _annotate_available_sessions(queryset, available_ids):
    counts = (
        BookingSchedule.objects.filter(booking=OuterRef('booking'), id__in=available_ids)
        .order_by()
        .values('booking')
        .annotate(c=Count('id'))
        .values('c')
    )
    return queryset.annotate(available_sessions=Subquery(counts))


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
        if booking.user_voucher_id:
            mark_user_voucher_used(user_voucher_id=booking.user_voucher_id)


def get_cancel_deadline(schedule):
    return schedule.scheduled_start - timedelta(hours=MIN_CANCEL_HOURS)


@transaction.atomic
def handle_missed_checkins():
    """
    Lazy check — gọi ngay đầu expire_unclaimed_schedules(), trước khi quét
    MISSED, để giải phóng các assignment bị "bỏ rơi": worker đã ACCEPTED
    nhưng quá scheduled_start + CHECKIN_MISSED_GRACE_MINUTES vẫn chưa
    Check-in (schedule vẫn PENDING, actual_start vẫn NULL).

    Không tự chuyển schedule sang MISSED ở đây — chỉ hủy assignment và
    trả schedule về trống. Nếu không ai nhận lại kịp, lượt quét
    expire_unclaimed_schedules() ngay sau đó (cùng 1 lần gọi) sẽ tự xử lý
    tiếp thành MISSED/FAILED như bình thường.
    """
    now = timezone.now()
    cutoff = now - timedelta(minutes=CHECKIN_MISSED_GRACE_MINUTES)

    stale_assignments = (
        BookingAssignment.objects.select_for_update(of=('self',))
        .filter(
            status=BookingAssignment.Status.ACCEPTED,
            schedule__status=BookingSchedule.Status.PENDING,
            schedule__scheduled_start__lt=cutoff,
        )
        .select_related('schedule', 'schedule__booking', 'worker')
    )

    for assignment in stale_assignments:
        schedule = assignment.schedule
        booking = schedule.booking

        assignment.status = BookingAssignment.Status.CANCELLED
        assignment.response_note = 'Tự động hủy do nhân viên không check-in đúng hạn.'
        assignment.responded_at = now
        assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

        if booking.status == Booking.Status.ASSIGNED:
            booking.status = Booking.Status.PENDING
            booking.save(update_fields=['status', 'updated_at'])

        Notification.objects.create(
            user=booking.customer,
            title='Đang tìm nhân viên khác',
            message=f'Nhân viên không xác nhận đến làm đúng giờ cho buổi '
                     f'{schedule.sequence_no} của đơn {booking.booking_code}. '
                     f'CleanWise đang tìm nhân viên khác cho bạn.',
            type=Notification.Type.ASSIGNMENT,
            related_booking=booking,
        )

        _notify_admins(
            title='Worker không check-in đúng hạn',
            message=f'{assignment.worker.username} đã nhận nhưng không check-in '
                     f'buổi {schedule.sequence_no} của đơn {booking.booking_code}.',
            related_booking=booking,
        )


@transaction.atomic
def expire_unclaimed_schedules():
    handle_missed_checkins() 

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
                was_paid = booking.payment_status == Booking.PaymentStatus.PAID
                booking.status = Booking.Status.FAILED
                booking.cancel_reason = 'Không có nhân viên nhận việc trong thời gian yêu cầu.'
                booking.cancelled_at = now
                update_fields = ['status', 'cancel_reason', 'cancelled_at', 'updated_at']
                if was_paid:
                    booking.payment_status = Booking.PaymentStatus.REFUNDED
                    update_fields.append('payment_status')
                booking.save(update_fields=update_fields)

                if was_paid:
                    from apps.wallets import wallet_service
                    wallet_service.credit_wallet(
                        user=booking.customer,
                        amount=booking.total_amount,
                        booking=booking,
                        note=f'Hoàn tiền do không tìm được nhân viên - {booking.booking_code}',
                    )

                if booking.user_voucher_id:
                    release_user_voucher(
                        user_voucher_id=booking.user_voucher_id,
                        allow_used=True,
                    )


@transaction.atomic
def handle_missed_checkouts():
    now = timezone.now()
    cutoff = now - timedelta(minutes=CHECKOUT_GRACE_MINUTES)

    overdue_schedules = (
        BookingSchedule.objects.select_for_update(of=('self',))
        .filter(status=BookingSchedule.Status.IN_PROGRESS, scheduled_end__lt=cutoff)
        .select_related('booking', 'booking__customer')
    )

    for schedule in overdue_schedules:
        assignment = schedule.assignments.filter(
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker').first()
        if not assignment:
            continue

        worker = assignment.worker

        schedule.actual_end = max(schedule.scheduled_end, schedule.actual_start or schedule.scheduled_end)
        schedule.status = BookingSchedule.Status.COMPLETED
        schedule.save(update_fields=['actual_end', 'status', 'updated_at'])

        booking = schedule.booking
        still_active = booking.schedules.filter(
            status__in=(BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS),
        ).exclude(pk=schedule.pk).exists()

        if not still_active and booking.status == Booking.Status.IN_PROGRESS:
            booking.status = Booking.Status.COMPLETED
            booking.save(update_fields=['status', 'updated_at'])

        earning_service.record_schedule_earning(schedule=schedule, booking=booking, worker=worker)

        Notification.objects.create(
            user=booking.customer,
            title='Dịch vụ đã hoàn thành',
            message=f'Buổi {schedule.sequence_no} của đơn {booking.booking_code} đã hoàn thành.',
            type=Notification.Type.ASSIGNMENT,
            related_booking=booking,
        )

def run_lazy_expiry(*, checkouts=False):
    """Dọn dẹp kiểu lazy trong request, CHỈ khi không có Celery Beat lo
    (dev với CELERY_EAGER=1 và test). Có worker + beat thật thì các task
    trong apps/worker/tasks.py chạy định kỳ, request không phải gánh."""
    if not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        return
    expire_unclaimed_schedules()
    if checkouts:
        handle_missed_checkouts()

# ---------------------------------------------------------------- queries


def list_available_schedules_for_worker(
    worker, *, booking_id=None, date_from=None, date_to=None, group_by_booking=False,
):
    run_lazy_expiry()

    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE' or not profile.registered_service_id:
        return BookingSchedule.objects.none()

    section_code = profile.registered_service.section_code

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
            booking__service__section_code=section_code,
        )
        .exclude(assignments__status=BookingAssignment.Status.ACCEPTED)
        .exclude(Exists(my_overlapping))
        .select_related('booking', 'booking__service', 'booking__address')
    )

    cash_payment_subquery = Payment.objects.filter(booking=OuterRef('booking'), method=Payment.Method.CASH)
    queryset = queryset.annotate(has_cash=Exists(cash_payment_subquery)).filter(
        Q(booking__payment_status=Booking.PaymentStatus.PAID) | Q(has_cash=True)
    )

    if booking_id:
        queryset = queryset.filter(booking_id=booking_id)

    all_matched = [
        s for s in queryset.order_by('scheduled_start', 'id')
        if _norm(s.booking.address.city) in area_keys
    ]
    all_ids = [s.id for s in all_matched]

    if date_from or date_to:
        def _in_range(s):
            d = timezone.localtime(s.scheduled_start).date()
            return (not date_from or d >= date_from) and (not date_to or d <= date_to)

        matched = [s for s in all_matched if _in_range(s)]
    else:
        matched = all_matched
    matched_ids = [s.id for s in matched]

    if group_by_booking and not booking_id:
        nearest_ids, seen = [], set()
        for s in matched:
            if s.booking_id in seen:
                continue
            seen.add(s.booking_id)
            nearest_ids.append(s.id)
        result = BookingSchedule.objects.filter(id__in=nearest_ids)
        result = _annotate_available_sessions(result, all_ids)
    else:
        result = BookingSchedule.objects.filter(id__in=matched_ids)

    result = result.select_related('booking', 'booking__service', 'booking__address')
    return _annotate_total_sessions(result).order_by('scheduled_start', 'id')


def list_my_schedules(worker, schedule_status=None, booking_id=None):
    run_lazy_expiry(checkouts=True)

    queryset = BookingSchedule.objects.filter(
        assignments__worker=worker,
        assignments__status=BookingAssignment.Status.ACCEPTED,
    ).select_related('booking', 'booking__service', 'booking__address')
    if schedule_status:
        queryset = queryset.filter(status=schedule_status)
    if booking_id:
        queryset = queryset.filter(booking_id=booking_id)
    return _annotate_total_sessions(queryset).order_by('scheduled_start')


def list_booking_schedules_for_worker(worker, *, booking_id):
    run_lazy_expiry()

    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE' or not profile.registered_service_id:
        return BookingSchedule.objects.none()

    booking = get_object_or_404(
        Booking.objects.select_related('service', 'address'), pk=booking_id,
    )

    same_section = booking.service.section_code == profile.registered_service.section_code
    in_area = _norm(booking.address.city) in _worker_area_keys(worker)
    already_assigned = BookingAssignment.objects.filter(
        schedule__booking=booking, worker=worker, status=BookingAssignment.Status.ACCEPTED,
    ).exists()

    if not already_assigned and not (same_section and in_area):
        return BookingSchedule.objects.none()

    queryset = (
        BookingSchedule.objects.filter(booking=booking)
        .exclude(status=BookingSchedule.Status.CANCELLED)
        .select_related('booking', 'booking__service', 'booking__address')
    )
    return _annotate_total_sessions(queryset).order_by('scheduled_start', 'id')

# ---------------------------------------------------------------- commands

@transaction.atomic
def claim_schedule(*, schedule_id, worker):
    profile = _get_claimable_profile(worker)
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',))
        .select_related('booking', 'booking__address', 'booking__service'),
        pk=schedule_id,
    )
    booking = schedule.booking

    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không còn nhận nhân viên.'})
    if not _is_bookable(booking):
        raise serializers.ValidationError({'schedule': 'Đơn hàng chưa thanh toán, chưa thể nhận việc.'})
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không còn khả dụng.'})
    if schedule.scheduled_start <= timezone.now():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã quá giờ bắt đầu.'})

    if booking.service.section_code != profile.registered_service.section_code:
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

    # Đơn tiền mặt: giữ chỗ hoa hồng ngay -> nếu ví không đủ, raise ở đây
    # sẽ làm toàn bộ transaction rollback (nhờ @transaction.atomic), tức
    # là KHÔNG nhận được việc luôn, không cần dọn dẹp gì thêm.
    if _has_cash_payment(booking):
        earning_service.reserve_cash_commission(
            schedule=schedule, booking=booking, worker=worker, assignment=assignment,
        )

    _sync_booking_status_after_claim(booking)
    ensure_chat_for_assignment(assignment)
    return assignment


@transaction.atomic
def claim_booking_package(*, booking_id, worker, schedule_ids=None):
    profile = _get_claimable_profile(worker)

    booking = get_object_or_404(
        Booking.objects.select_related('service', 'address'),
        pk=booking_id,
    )

    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'booking': 'Đơn hàng không còn nhận nhân viên.'})
    if not _is_bookable(booking):
        raise serializers.ValidationError({'booking': 'Đơn hàng chưa thanh toán, chưa thể nhận việc.'})
    if booking.service.section_code != profile.registered_service.section_code:
        raise serializers.ValidationError({'booking': 'Gói này không thuộc dịch vụ bạn đã đăng ký.'})
    if _norm(booking.address.city) not in _worker_area_keys(worker):
        raise serializers.ValidationError({'booking': 'Gói này nằm ngoài khu vực làm việc của bạn.'})

    base_qs = BookingSchedule.objects.select_for_update(of=('self',)).filter(
        booking=booking,
        status=BookingSchedule.Status.PENDING,
        scheduled_start__gt=timezone.now(),
    ).order_by('id')

    skipped = []

    if schedule_ids is not None:
        schedule_ids = list(dict.fromkeys(schedule_ids))
        found = {s.id: s for s in base_qs.filter(id__in=schedule_ids)}
        schedules = []
        for sid in schedule_ids:
            schedule = found.get(sid)
            if schedule is None:
                skipped.append({
                    'schedule_id': sid,
                    'reason': 'Buổi làm việc không hợp lệ hoặc không còn khả dụng.',
                })
                continue
            schedules.append(schedule)
        schedules.sort(key=lambda s: s.scheduled_start)
    else:
        schedules = list(base_qs.order_by('scheduled_start'))

    if not schedules and not skipped:
        raise serializers.ValidationError({'booking': 'Gói này không còn buổi nào khả dụng.'})

    now = timezone.now()
    claimed = []
    is_cash = _has_cash_payment(booking)
    
    for schedule in schedules:
        if BookingAssignment.objects.filter(
            schedule=schedule, status=BookingAssignment.Status.ACCEPTED,
        ).exists():
            skipped.append({'schedule_id': schedule.id, 'reason': 'Buổi làm việc này đã có người nhận.'})
            continue
        if _has_time_conflict(worker, schedule):
            skipped.append({'schedule_id': schedule.id, 'reason': 'Trùng khung giờ với buổi khác của bạn.'})
            continue

        # Dùng .save() thay vì .create() để gắn được cờ _skip_assignment_notify
        # trước khi post_save fire — tránh signal bắn N thông báo lẻ khi
        # nhận cả gói nhiều buổi (xem notify_customer_worker_assigned_batch
        # ở cuối hàm, gửi 1 thông báo gộp thay thế).
        assignment = BookingAssignment(
            schedule=schedule, worker=worker,
            assigned_method=BookingAssignment.AssignedMethod.MANUAL,
            status=BookingAssignment.Status.ACCEPTED, assigned_at=now, responded_at=now,
        )
        assignment._skip_assignment_notify = True
        assignment.save()

        BookingAssignment.objects.filter(
            schedule=schedule, status=BookingAssignment.Status.PENDING,
        ).exclude(pk=assignment.pk).update(
            status=BookingAssignment.Status.CANCELLED,
            response_note='Tự động hủy do đã có nhân viên khác nhận việc.',
            responded_at=now, updated_at=now,
        )

        if is_cash:
            try:
                earning_service.reserve_cash_commission(
                    schedule=schedule, booking=booking, worker=worker, assignment=assignment,
                )
            except serializers.ValidationError:
                # Không đủ ví cho buổi này -> hủy ngay assignment vừa tạo,
                # bỏ qua buổi này, KHÔNG làm hỏng các buổi khác trong gói.
                assignment.status = BookingAssignment.Status.CANCELLED
                assignment.response_note = 'Không đủ số dư ví để giữ chỗ hoa hồng.'
                assignment.responded_at = now
                assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])
                skipped.append({
                    'schedule_id': schedule.id,
                    'reason': 'Không đủ số dư ví ký quỹ để nhận buổi tiền mặt này.',
                })
                continue

        claimed.append(assignment)

    if not claimed:
        raise serializers.ValidationError(
            {'booking': 'Không nhận được buổi nào (đã có người nhận, trùng lịch của bạn, hoặc buổi không hợp lệ).'}
        )

    from apps.notifications.services import notify_customer_worker_assigned_batch
    notify_customer_worker_assigned_batch(booking, worker, len(claimed))

    _sync_booking_status_after_claim(booking)

    return {'claimed': claimed, 'skipped': skipped}


@transaction.atomic
def cancel_assignment(*, assignment_id, worker, reason):
    reason = (reason or '').strip()
    if not reason:
        raise serializers.ValidationError({'reason': 'Vui lòng nhập lý do hủy.'})

    assignment_lookup = get_object_or_404(
        BookingAssignment.objects.filter(
            pk=assignment_id, worker=worker, status=BookingAssignment.Status.ACCEPTED,
        ),
    )
    schedule = BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking').get(
        pk=assignment_lookup.schedule_id,
    )
    assignment = get_object_or_404(
        BookingAssignment.objects.select_for_update(of=('self',)),
        pk=assignment_id, worker=worker, status=BookingAssignment.Status.ACCEPTED,
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

    assignment.status = BookingAssignment.Status.CANCELLED
    assignment.response_note = reason
    assignment.responded_at = now
    assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

    earning_service.release_cash_commission(assignment=assignment)

    from apps.notifications.services import notify_customer_worker_cancelled_schedule
    notify_customer_worker_cancelled_schedule(schedule, reason)

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

    old_assignments = list(
        BookingAssignment.objects.select_for_update(of=('self',)).filter(
            schedule=schedule,
            status__in=[BookingAssignment.Status.ACCEPTED, BookingAssignment.Status.PENDING],
        ).select_related('worker')
    )
    for old in old_assignments:
        if old.status == BookingAssignment.Status.ACCEPTED:
            earning_service.release_cash_commission(assignment=old)
            from apps.notifications.services import notify_worker_removed_from_schedule
            notify_worker_removed_from_schedule(schedule, old.worker)

    BookingAssignment.objects.filter(pk__in=[o.pk for o in old_assignments]).update(
        status=BookingAssignment.Status.CANCELLED,
        response_note='Admin gán lại nhân viên khác.',
        responded_at=now, updated_at=now,
    )

    assignment = BookingAssignment.objects.create(
        schedule=schedule, worker=worker, assigned_by=admin_user,
        assigned_method=BookingAssignment.AssignedMethod.MANUAL,
        status=BookingAssignment.Status.ACCEPTED, assigned_at=now, responded_at=now, response_note=note,
    )

    if _has_cash_payment(booking):
        earning_service.reserve_cash_commission(
            schedule=schedule, booking=booking, worker=worker, assignment=assignment,
        )

    from apps.notifications.services import notify_worker_new_job
    notify_worker_new_job(assignment)

    _sync_booking_status_after_claim(booking)
    ensure_chat_for_assignment(assignment)
    return assignment