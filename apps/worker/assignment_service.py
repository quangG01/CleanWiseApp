import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.activity_service import record_booking_activity
from apps.bookings.models import Booking, BookingActivity, BookingSchedule
from apps.notifications.models import Notification
from apps.chat.service import ensure_chat_for_assignment
from apps.payments.models import Payment
from apps.vouchers.voucher_service import (
    mark_user_voucher_used,
    release_user_voucher,
)
from apps.wallets import earning_service, refund_service

from .constants import MIN_CANCEL_HOURS, AUTO_CANCEL_NOTE
from .models import BookingAssignment, CustomerFavoriteWorker, WorkerWorkingArea

from django.db.models import Case, Count, Exists, IntegerField, Max, Min, OuterRef, Q, Subquery, When
from django.db.models.functions import Coalesce

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

CHECKOUT_GRACE_MINUTES = getattr(settings, 'CHECKOUT_GRACE_MINUTES', 30)
CHECKIN_MISSED_GRACE_MINUTES = getattr(settings, 'CHECKIN_MISSED_GRACE_MINUTES', 30)
PREFERRED_WORKER_WINDOW = timedelta(hours=1)
PREFERRED_WORKER_START_BUFFER = timedelta(minutes=30)


# ---------------------------------------------------------------- helpers

def _lock_booking_of_schedule(schedule_id):
    booking_id = get_object_or_404(
        BookingSchedule.objects.only('booking_id'), pk=schedule_id,
    ).booking_id
    return Booking.objects.select_for_update(of=('self',)).get(pk=booking_id)


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


def _exclusive_to_other(booking, worker):
    """True nếu có buổi đang trong thời gian ưu tiên của nhân viên khác."""
    return booking.schedules.filter(
        preferred_worker__isnull=False,
        preferred_worker_expires_at__gt=timezone.now(),
    ).exclude(preferred_worker=worker).exists()


def validate_preferred_worker(*, customer, worker_id, service, address):
    worker = (
        User.objects
        .select_related('worker_profile', 'worker_profile__registered_service')
        .filter(
            pk=worker_id, role='WORKER', is_active=True,
            worker_profile__status='ACTIVE',
        )
        .first()
    )
    if worker is None or not CustomerFavoriteWorker.objects.filter(
        customer=customer, worker=worker,
    ).exists():
        raise serializers.ValidationError(
            {'preferred_worker_id': 'Nhân viên không có trong danh sách yêu thích của bạn.'}
        )
    profile = worker.worker_profile
    if (
        not profile.registered_service_id
        or profile.registered_service.section_code != service.section_code
    ):
        raise serializers.ValidationError(
            {'preferred_worker_id': 'Nhân viên này không làm dịch vụ bạn chọn.'}
        )
    if not _covers(_worker_area_index(worker), address):
        raise serializers.ValidationError(
            {'preferred_worker_id': 'Nhân viên này không hoạt động tại khu vực của bạn.'}
        )
    return worker


def activate_preferred_worker_request(booking):
    """Bắt đầu thời gian ưu tiên + báo nhân viên. Idempotent."""
    schedules = list(
        booking.schedules.select_for_update().filter(
            status=BookingSchedule.Status.PENDING,
            preferred_worker__isnull=False,
            preferred_worker_expires_at__isnull=True,
        ).order_by('scheduled_start')
    )
    if not schedules:
        return

    now = timezone.now()
    for schedule in schedules:
        schedule.preferred_worker_expires_at = min(
            now + PREFERRED_WORKER_WINDOW,
            schedule.scheduled_start - PREFERRED_WORKER_START_BUFFER,
        )
        schedule.save(update_fields=['preferred_worker_expires_at', 'updated_at'])

    from apps.notifications.services import notify_worker_preferred_request
    notify_worker_preferred_request(
        booking,
        schedules[0].preferred_worker,
        schedules[0].preferred_worker_expires_at,
    )

_CITY_PREFIX_RE = re.compile(r'^(thành phố|tp\.?|tỉnh)\s+', re.IGNORECASE)


def _norm(value):
    v = (value or '').strip().lower()
    v = _CITY_PREFIX_RE.sub('', v)
    return v.strip()


def _worker_area_index(worker):
    """(tập mã tỉnh, tập tên tỉnh đã chuẩn hóa) của các khu vực nhân viên đã chọn."""
    province_codes, city_keys = set(), set()
    rows = WorkerWorkingArea.objects.filter(
        worker=worker, area__is_active=True,
    ).values_list('area__province_code', 'area__city')
    for code, city in rows:
        if code:
            province_codes.add(code)
        if _norm(city):
            city_keys.add(_norm(city))
    return province_codes, city_keys


def _covers(index, address):
    """Nhân viên có phủ địa chỉ này không (khớp theo tỉnh/thành)."""
    province_codes, city_keys = index
    code = getattr(address, 'province_code', '') or ''
    if code:
        return code in province_codes
    # Địa chỉ cũ chưa có province_code: khớp theo tên tỉnh/thành
    return _norm(address.city) in city_keys


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


def validate_worker_for_schedule(*, schedule, worker):
    """Validation dùng chung cho admin gán việc và danh sách ứng viên."""
    profile = _get_claimable_profile(worker)
    booking = schedule.booking
    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không còn nhận nhân viên.'})
    if not _is_bookable(booking):
        raise serializers.ValidationError({'schedule': 'Đơn hàng chưa thanh toán, chưa thể phân công.'})
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Chỉ được phân công buổi chưa bắt đầu.'})
    if schedule.scheduled_start <= timezone.now():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã quá giờ bắt đầu.'})
    if booking.service.section_code != profile.registered_service.section_code:
        raise serializers.ValidationError({'worker': 'Nhân viên không đăng ký nhóm dịch vụ này.'})
    if not _covers(_worker_area_index(worker), booking.address):
        raise serializers.ValidationError({'worker': 'Nhân viên không hoạt động tại khu vực của đơn.'})
    if _has_time_conflict(worker, schedule):
        raise serializers.ValidationError({'worker': 'Nhân viên bị trùng lịch với buổi khác.'})
    return profile


def list_available_workers_for_schedule(*, schedule_id, search=None):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_related('booking', 'booking__service', 'booking__address'),
        pk=schedule_id,
    )
    booking = schedule.booking
    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không còn nhận nhân viên.'})
    if not _is_bookable(booking):
        raise serializers.ValidationError({'schedule': 'Đơn hàng chưa thanh toán, chưa thể phân công.'})
    if schedule.status != BookingSchedule.Status.PENDING or schedule.scheduled_start <= timezone.now():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không còn khả dụng.'})

    queryset = (
        User.objects.filter(
            role='WORKER',
            is_active=True,
            worker_profile__status='ACTIVE',
            worker_profile__registered_service__section_code=booking.service.section_code,
        )
        .select_related('worker_profile', 'worker_profile__registered_service', 'wallet')
        .prefetch_related('working_areas__area')
        .annotate(
            active_jobs_count=Count(
                'booking_assignments',
                filter=Q(
                    booking_assignments__status=BookingAssignment.Status.ACCEPTED,
                    booking_assignments__schedule__status__in=ACTIVE_SCHEDULE_STATUSES,
                ),
                distinct=True,
            ),
        )
    )
    if search:
        search = search.strip()
        queryset = queryset.filter(
            Q(username__icontains=search)
            | Q(first_name__icontains=search)
            | Q(last_name__icontains=search)
            | Q(phone_number__icontains=search)
        )

    is_cash = _has_cash_payment(booking)
    required_commission = earning_service.calculate_commission(
        earning_service.calculate_gross_amount(schedule, booking),
    ) if is_cash else 0
    workers = []
    for worker in queryset:
        if not _covers(_worker_area_index(worker), booking.address):
            continue
        if _has_time_conflict(worker, schedule):
            continue
        wallet = getattr(worker, 'wallet', None)
        cash_eligible = not is_cash or (wallet is not None and wallet.balance >= required_commission)
        if not cash_eligible:
            continue
        worker.matched_area = True
        worker.has_time_conflict = False
        worker.cash_balance_eligible = cash_eligible
        workers.append(worker)
    return workers


def _sync_booking_status_after_claim(booking):
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
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
    """Gỡ assignment ACCEPTED mà nhân viên không check-in quá CHECKIN_MISSED_GRACE_MINUTES."""
    now = timezone.now()
    cutoff = now - timedelta(minutes=CHECKIN_MISSED_GRACE_MINUTES)

    candidates = list(
        BookingAssignment.objects.filter(
            status=BookingAssignment.Status.ACCEPTED,
            schedule__status=BookingSchedule.Status.PENDING,
            schedule__scheduled_start__lt=cutoff,
        ).values_list('id', 'schedule__booking_id')
    )

    for assignment_id, booking_id in candidates:
        booking = Booking.objects.select_for_update().get(pk=booking_id)  # booking trước
        assignment = (
            BookingAssignment.objects.select_for_update(of=('self',))
            .select_related('schedule', 'worker').get(pk=assignment_id)
        )
        schedule = assignment.schedule
        if (
            assignment.status != BookingAssignment.Status.ACCEPTED
            or schedule.status != BookingSchedule.Status.PENDING
        ):
            continue

        assignment.status = BookingAssignment.Status.CANCELLED
        assignment.response_note = AUTO_CANCEL_NOTE
        assignment.responded_at = now
        assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])

        earning_service.release_cash_commission(assignment=assignment)

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
        record_booking_activity(
            booking=booking,
            schedule=schedule,
            event_type=BookingActivity.EventType.WORKER_UNASSIGNED,
            message=f'Tự động gỡ nhân viên do không check-in buổi {schedule.sequence_no}.',
            old_data={'worker_id': assignment.worker_id, 'assignment_id': assignment.id},
            new_data={'reason': assignment.response_note},
            metadata={'automatic': True},
        )


@transaction.atomic
def handle_missed_checkouts():
    now = timezone.now()
    cutoff = now - timedelta(minutes=CHECKOUT_GRACE_MINUTES)

    candidates = list(
        BookingSchedule.objects.filter(
            status=BookingSchedule.Status.IN_PROGRESS, scheduled_end__lt=cutoff,
        ).values_list('id', 'booking_id')
    )

    for schedule_id, booking_id in candidates:
        booking = Booking.objects.select_for_update().get(pk=booking_id)  # booking trước
        schedule = BookingSchedule.objects.select_for_update().get(pk=schedule_id)
        if schedule.status != BookingSchedule.Status.IN_PROGRESS:
            continue

        assignment = schedule.assignments.filter(
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker').first()
        if not assignment:
            continue
        worker = assignment.worker

        schedule.actual_end = max(schedule.scheduled_end, schedule.actual_start or schedule.scheduled_end)
        schedule.status = BookingSchedule.Status.COMPLETED
        schedule.save(update_fields=['actual_end', 'status', 'updated_at'])

        still_active = booking.schedules.filter(
            status__in=(BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS),
        ).exclude(pk=schedule.pk).exists()
        if not still_active and booking.status == Booking.Status.IN_PROGRESS:
            booking.status = Booking.Status.COMPLETED
            booking.save(update_fields=['status', 'updated_at'])

        earning_service.record_schedule_earning(schedule=schedule, booking=booking, worker=worker)

        if booking.status != Booking.Status.COMPLETED:
            Notification.objects.create(
                user=booking.customer,
                title='Dịch vụ đã hoàn thành',
                message=f'Buổi {schedule.sequence_no} của đơn {booking.booking_code} đã hoàn thành.',
                type=Notification.Type.ASSIGNMENT,
                related_booking=booking,
            )
        record_booking_activity(
            booking=booking,
            schedule=schedule,
            event_type=BookingActivity.EventType.CHECKED_OUT,
            message=f'Hệ thống tự động hoàn thành buổi {schedule.sequence_no}.',
            new_data={'actual_end': schedule.actual_end.isoformat()},
            metadata={'automatic': True},
        )


@transaction.atomic
def expire_unclaimed_schedules():
    handle_missed_checkins()

    now = timezone.now()
    stale = list(
        BookingSchedule.objects
        .filter(status=BookingSchedule.Status.PENDING, scheduled_start__lt=now)
        .exclude(assignments__status=BookingAssignment.Status.ACCEPTED)
        .values_list('id', 'booking_id')
    )

    for schedule_id, booking_id in stale:
        # Lock booking TRƯỚC, schedule SAU (cùng thứ tự với cancel_booking)
        booking = Booking.objects.select_for_update().get(pk=booking_id)
        schedule = BookingSchedule.objects.select_for_update().get(pk=schedule_id)

        # Có thể đã bị xử lý/nhận việc trong lúc chờ lock
        if schedule.status != BookingSchedule.Status.PENDING:
            continue
        if schedule.assignments.filter(status=BookingAssignment.Status.ACCEPTED).exists():
            continue
        if booking.status not in OPEN_BOOKING_STATUSES:
            continue

        schedule.status = BookingSchedule.Status.MISSED
        schedule.cancel_reason = 'Hết hạn, không có nhân viên nhận việc.'
        schedule.cancelled_at = now
        schedule.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])

        # [Bug 6] Hoàn tiền riêng cho buổi này
        if booking.payment_status == Booking.PaymentStatus.PAID:
            refund_service.refund_booking(
                booking=booking,
                amount=refund_service.per_session_refund_amount(booking),
                key=f'refund:schedule:{schedule.id}:missed',
                note=f'Hoàn tiền buổi {schedule.sequence_no} không có nhân viên - {booking.booking_code}',
            )

        record_booking_activity(
            booking=booking,
            schedule=schedule,
            event_type=BookingActivity.EventType.BOOKING_UPDATED,
            message=f'Buổi {schedule.sequence_no} hết hạn vì không có nhân viên nhận.',
            metadata={'automatic': True},
        )

        if booking.schedules.filter(status__in=ACTIVE_SCHEDULE_STATUSES).exists():
            continue

        # Không còn buổi nào chờ làm
        if booking.schedules.filter(status=BookingSchedule.Status.COMPLETED).exists():
            booking.status = Booking.Status.COMPLETED
            booking.save(update_fields=['status', 'updated_at'])
            continue

        # Chưa làm buổi nào -> đơn thất bại
        booking.status = Booking.Status.FAILED
        booking.cancel_reason = 'Không có nhân viên nhận việc trong thời gian yêu cầu.'
        booking.cancelled_at = now
        booking.save(update_fields=['status', 'cancel_reason', 'cancelled_at', 'updated_at'])

        # [Bug 2] Hủy payment đang chờ để webhook đến sau không set PAID nhầm
        booking.payments.filter(status=Payment.Status.PENDING).update(
            status=Payment.Status.CANCELLED, failure_reason=booking.cancel_reason, updated_at=now,
        )
        # Hoàn phần còn lại (làm tròn)
        if booking.payment_status == Booking.PaymentStatus.PAID:
            refund_service.refund_booking(
                booking=booking,
                key=f'refund:booking:{booking.id}:failed',
                note=f'Hoàn tiền do không tìm được nhân viên - {booking.booking_code}',
            )
        if booking.user_voucher_id:
            release_user_voucher(user_voucher_id=booking.user_voucher_id, allow_used=True)

        record_booking_activity(
            booking=booking,
            schedule=schedule,
            event_type=BookingActivity.EventType.BOOKING_FAILED,
            message=f'Đơn {booking.booking_code} thất bại vì không có nhân viên nhận.',
            new_data={'status': Booking.Status.FAILED, 'reason': booking.cancel_reason},
            metadata={'automatic': True},
        )


def run_lazy_expiry(*, checkouts=False):
    """Dọn dẹp kiểu lazy trong request, CHỈ khi không có Celery Beat lo
    (dev với CELERY_EAGER=1 và test). Có worker + beat thật thì các task
    trong apps/worker/tasks.py chạy định kỳ, request không phải gánh."""
    if not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
        return
    expire_unclaimed_schedules()
    from apps.bookings.expiry_service import expire_unpaid_bookings
    expire_unpaid_bookings()
    earning_service.release_held_earnings()
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

    area_index = _worker_area_index(worker)
    if not area_index[0] and not area_index[1]:
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
    
    now = timezone.now()
    queryset = queryset.filter(
        Q(preferred_worker__isnull=True)
        | Q(preferred_worker=worker)
        | Q(preferred_worker_expires_at__isnull=True)
        | Q(preferred_worker_expires_at__lte=now)
    )

    cash_payment_subquery = Payment.objects.filter(booking=OuterRef('booking'), method=Payment.Method.CASH)
    queryset = queryset.annotate(has_cash=Exists(cash_payment_subquery)).filter(
        Q(booking__payment_status=Booking.PaymentStatus.PAID) | Q(has_cash=True)
    )

    if booking_id:
        queryset = queryset.filter(booking_id=booking_id)

    all_matched = [
        s for s in queryset.order_by('scheduled_start', 'id')
        if _covers(area_index, s.booking.address)
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

    result = result.select_related(
        'booking', 'booking__service', 'booking__address',
        'booking__delivery_address', 'booking__customer',
    )
    return _annotate_total_sessions(result).annotate(
        preferred_rank=Case(
            When(
                preferred_worker=worker,
                preferred_worker_expires_at__gt=timezone.now(),
                then=0,
            ),
            default=1,
            output_field=IntegerField(),
        ),
    ).order_by('preferred_rank', 'scheduled_start', 'id')


MY_TABS = ('upcoming', 'today', 'completed', 'cancelled')


def _my_assignment_exists(worker):
    """Buổi 'của tôi': đang ACCEPTED, hoặc buổi MISSED mà assignment của tôi bị
    hệ thống tự hủy do không check-in (để còn xem và khiếu nại)."""
    A = BookingAssignment
    return Exists(
        A.objects.filter(schedule=OuterRef('pk'), worker=worker).filter(
            Q(status=A.Status.ACCEPTED)
            | Q(
                status=A.Status.CANCELLED,
                response_note=AUTO_CANCEL_NOTE,
                schedule__status=BookingSchedule.Status.MISSED,
            )
        )
    )


def _my_schedules_in_booking(worker):
    return BookingSchedule.objects.filter(booking=OuterRef('booking')).filter(
        _my_assignment_exists(worker)
    )


def _annotate_my_progress(queryset, worker):
    base = _my_schedules_in_booking(worker).order_by().values('booking')
    completed = base.filter(status=BookingSchedule.Status.COMPLETED).annotate(
        c=Count('id', distinct=True)).values('c')
    accepted = base.exclude(
        status__in=(BookingSchedule.Status.CANCELLED, BookingSchedule.Status.MISSED),
    ).annotate(c=Count('id', distinct=True)).values('c')
    return queryset.annotate(
        completed_sessions=Coalesce(Subquery(completed, output_field=IntegerField()), 0),
        accepted_sessions=Coalesce(Subquery(accepted, output_field=IntegerField()), 0),
    )


def _booking_anchor(worker, statuses, agg):
    """Mốc thời gian của cả đơn, để các buổi cùng đơn nằm sát nhau."""
    return Subquery(
        _my_schedules_in_booking(worker).filter(status__in=statuses)
        .order_by().values('booking').annotate(k=agg('scheduled_start')).values('k')
    )


def list_my_schedules(worker, schedule_status=None, booking_id=None, tab=None):
    run_lazy_expiry(checkouts=True)

    queryset = BookingSchedule.objects.filter(_my_assignment_exists(worker)).select_related(
        'booking', 'booking__service', 'booking__address',
        'booking__delivery_address', 'booking__customer',
    ).prefetch_related('images')
    if schedule_status:
        queryset = queryset.filter(status=schedule_status)
    if booking_id:
        queryset = queryset.filter(booking_id=booking_id)
    queryset = _annotate_total_sessions(queryset)

    if tab is None:
        return queryset.order_by('scheduled_start')

    S = BookingSchedule.Status
    queryset = _annotate_my_progress(queryset, worker)

    if tab == 'upcoming':
        # Đang làm ghim trên cùng, rồi tới buổi gần nhất; buổi cùng đơn nằm sát nhau.
        return queryset.filter(status__in=ACTIVE_SCHEDULE_STATUSES).annotate(
            booking_running=Exists(
                _my_schedules_in_booking(worker).filter(status=S.IN_PROGRESS)
            ),
            booking_anchor=_booking_anchor(worker, ACTIVE_SCHEDULE_STATUSES, Min),
        ).order_by('-booking_running', 'booking_anchor', 'booking_id', 'scheduled_start')

    if tab == 'today':
        return queryset.filter(
            scheduled_start__date=timezone.localdate(),
        ).exclude(status__in=(S.CANCELLED, S.MISSED)).order_by('scheduled_start', 'id')

    statuses = (S.COMPLETED,) if tab == 'completed' else (S.CANCELLED, S.MISSED)
    return queryset.filter(status__in=statuses).annotate(
        booking_anchor=_booking_anchor(worker, statuses, Max),
    ).order_by('-booking_anchor', 'booking_id', '-scheduled_start')
    

def list_booking_schedules_for_worker(worker, *, booking_id):
    run_lazy_expiry()

    profile = _get_worker_profile(worker)
    if profile is None or profile.status != 'ACTIVE' or not profile.registered_service_id:
        return BookingSchedule.objects.none()

    booking = get_object_or_404(
        Booking.objects.select_related('service', 'address'), pk=booking_id,
    )

    same_section = booking.service.section_code == profile.registered_service.section_code
    in_area = _covers(_worker_area_index(worker), booking.address)
    already_assigned = BookingAssignment.objects.filter(
        schedule__booking=booking, worker=worker, status=BookingAssignment.Status.ACCEPTED,
    ).exists()

    if not already_assigned and (
        not (same_section and in_area) or _exclusive_to_other(booking, worker)
    ):
        return BookingSchedule.objects.none()

    mine = BookingAssignment.objects.filter(
        schedule=OuterRef('pk'),
        worker=worker,
        status=BookingAssignment.Status.ACCEPTED,
    )

    # Toàn bộ buổi của booking: buổi của mình (mọi trạng thái, trừ CANCELLED)
    # + buổi còn PENDING (OPEN hoặc người khác đã nhận -> claim_state = TAKEN).
    queryset = (
        BookingSchedule.objects.filter(booking=booking)
        .annotate(is_mine=Exists(mine))
        .filter(Q(is_mine=True) | Q(status=BookingSchedule.Status.PENDING))
        .select_related(
            'booking', 'booking__service', 'booking__address',
            'booking__delivery_address', 'booking__customer',
        )
    )
    return _annotate_total_sessions(queryset).order_by('scheduled_start', 'id')

# ---------------------------------------------------------------- commands

@transaction.atomic
def claim_schedule(*, schedule_id, worker):
    profile = _get_claimable_profile(worker)
    User.objects.select_for_update().get(pk=worker.pk)
    _lock_booking_of_schedule(schedule_id)
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',))
        .select_related('booking', 'booking__address', 'booking__service'),
        pk=schedule_id,
    )
    booking = schedule.booking
    existing = BookingAssignment.objects.filter(
        schedule=schedule, status=BookingAssignment.Status.ACCEPTED,
    ).first()
    if existing:
        if existing.worker_id == worker.id:
            return existing
        raise serializers.ValidationError({'schedule': 'Buổi làm việc này đã có người nhận.'})

    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không còn nhận nhân viên.'})
    if not _is_bookable(booking):
        raise serializers.ValidationError({'schedule': 'Đơn hàng chưa thanh toán, chưa thể nhận việc.'})
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không còn khả dụng.'})
    if schedule.scheduled_start <= timezone.now():
        raise serializers.ValidationError({'schedule': 'Buổi làm việc đã quá giờ bắt đầu.'})
    if _exclusive_to_other(booking, worker):
        raise serializers.ValidationError(
            {'schedule': 'Đơn này đang dành riêng cho nhân viên khách đã chọn. Vui lòng quay lại sau.'}
        )
    if booking.service.section_code != profile.registered_service.section_code:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không thuộc dịch vụ bạn đã đăng ký.'})

    if not _covers(_worker_area_index(worker), booking.address):
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
    record_booking_activity(
        booking=booking,
        schedule=schedule,
        actor=worker,
        event_type=BookingActivity.EventType.WORKER_CLAIMED,
        message=f'{worker.get_full_name() or worker.username} nhận buổi {schedule.sequence_no}.',
        new_data={'worker_id': worker.id, 'assignment_id': assignment.id},
    )
    return assignment


@transaction.atomic
def claim_booking_package(*, booking_id, worker, schedule_ids=None):
    profile = _get_claimable_profile(worker)
    User.objects.select_for_update().get(pk=worker.pk)

    booking = get_object_or_404(
        Booking.objects.select_for_update(of=('self',)).select_related('service', 'address'),
        pk=booking_id,
    )

    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'booking': 'Đơn hàng không còn nhận nhân viên.'})
    if not _is_bookable(booking):
        raise serializers.ValidationError({'booking': 'Đơn hàng chưa thanh toán, chưa thể nhận việc.'})
    if _exclusive_to_other(booking, worker):
        raise serializers.ValidationError(
            {'booking': 'Đơn này đang dành riêng cho nhân viên khách đã chọn. Vui lòng quay lại sau.'}
        )
    
    if booking.service.section_code != profile.registered_service.section_code:
        raise serializers.ValidationError({'booking': 'Gói này không thuộc dịch vụ bạn đã đăng ký.'})
    if not _covers(_worker_area_index(worker), booking.address):
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
        schedules = sorted(base_qs, key=lambda s: s.scheduled_start)

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

    for assignment in claimed:
        record_booking_activity(
            booking=booking,
            schedule=assignment.schedule,
            actor=worker,
            event_type=BookingActivity.EventType.WORKER_CLAIMED,
            message=(
                f'{worker.get_full_name() or worker.username} nhận buổi '
                f'{assignment.schedule.sequence_no}.'
            ),
            new_data={'worker_id': worker.id, 'assignment_id': assignment.id},
        )

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
    _lock_booking_of_schedule(assignment_lookup.schedule_id)
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

    record_booking_activity(
        booking=booking,
        schedule=schedule,
        actor=worker,
        event_type=BookingActivity.EventType.WORKER_CANCELLED,
        message=f'{worker.get_full_name() or worker.username} hủy nhận buổi {schedule.sequence_no}.',
        old_data={'assignment_id': assignment.id, 'status': BookingAssignment.Status.ACCEPTED},
        new_data={'status': BookingAssignment.Status.CANCELLED, 'reason': reason},
    )

    return assignment


@transaction.atomic
def admin_assign_worker(*, schedule_id, worker_id, admin_user, note=None):
    _lock_booking_of_schedule(schedule_id)
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking'),
        pk=schedule_id,
    )
    booking = schedule.booking
    worker = get_object_or_404(User, pk=worker_id, role='WORKER', is_active=True)

    validate_worker_for_schedule(schedule=schedule, worker=worker)

    now = timezone.now()

    old_assignments = list(
        BookingAssignment.objects.select_for_update(of=('self',)).filter(
            schedule=schedule,
            status__in=[BookingAssignment.Status.ACCEPTED, BookingAssignment.Status.PENDING],
        ).select_related('worker')
    )
    old_worker_ids = [old.worker_id for old in old_assignments if old.status == BookingAssignment.Status.ACCEPTED]
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
    record_booking_activity(
        booking=booking,
        schedule=schedule,
        actor=admin_user,
        event_type=(
            BookingActivity.EventType.WORKER_REASSIGNED
            if old_worker_ids else BookingActivity.EventType.WORKER_ASSIGNED
        ),
        message=(
            f'Admin đổi nhân viên buổi {schedule.sequence_no}.'
            if old_worker_ids else f'Admin gán nhân viên cho buổi {schedule.sequence_no}.'
        ),
        old_data={'worker_ids': old_worker_ids},
        new_data={
            'worker_id': worker.id,
            'assignment_id': assignment.id,
            'note': note,
        },
    )
    return assignment


@transaction.atomic
def decline_preferred_request(*, booking_id, worker):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=booking_id)
    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'booking': 'Đơn hàng không còn nhận nhân viên.'})

    now = timezone.now()
    mine = list(
        booking.schedules.select_for_update().filter(
            preferred_worker=worker, status=BookingSchedule.Status.PENDING,
        )
    )
    if not mine:
        raise serializers.ValidationError({'booking': 'Đơn này không được chỉ định cho bạn.'})
    if BookingAssignment.objects.filter(
        schedule__booking=booking, worker=worker,
        status=BookingAssignment.Status.ACCEPTED,
    ).exists():
        raise serializers.ValidationError(
            {'booking': 'Bạn đã nhận đơn này, hãy dùng chức năng hủy nhận việc.'}
        )

    active_ids = [
        s.id for s in mine
        if s.preferred_worker_expires_at is None or s.preferred_worker_expires_at > now
    ]
    if not active_ids:
        return booking  # đã mở cho mọi người rồi, bấm lại cũng không lỗi

    BookingSchedule.objects.filter(pk__in=active_ids).update(
        preferred_worker_expires_at=now, updated_at=now,
    )

    record_booking_activity(
        booking=booking,
        actor=worker,
        event_type=BookingActivity.EventType.BOOKING_UPDATED,
        message=f'{worker.get_full_name() or worker.username} từ chối yêu cầu chỉ định, đơn mở cho mọi nhân viên.',
    )

    from apps.notifications.services import notify_customer_preferred_declined
    notify_customer_preferred_declined(booking, worker)
    return booking