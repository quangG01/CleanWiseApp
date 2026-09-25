import re
from datetime import timedelta

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


def _has_cash_payment(booking):
    return Payment.objects.filter(booking=booking, method=Payment.Method.CASH).exists()


def _is_bookable(booking):
    """CASH nhận việc bất cứ lúc nào; BANK_TRANSFER chỉ nhận được sau khi PAID."""
    return booking.payment_status == Booking.PaymentStatus.PAID or _has_cash_payment(booking)


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


def _annotate_available_sessions(queryset, available_ids):
    """Số buổi còn trống (đúng bộ lọc của nhân viên) của cùng booking."""
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


# ---------------------------------------------------------------- queries


def list_available_schedules_for_worker(
    worker, *, booking_id=None, date_from=None, date_to=None, group_by_booking=False,
):
    """
    Buổi làm còn trống, đúng NHÓM dịch vụ (section_code) + khu vực của
    nhân viên, không trùng giờ.

    group_by_booking=True (và không có booking_id): mỗi booking chỉ trả 1 dòng
    là buổi trống GẦN NHẤT (trong khoảng ngày date_from..date_to nếu có), kèm
    annotation `available_sessions` = TỔNG số buổi trống của booking đó,
    KHÔNG phụ thuộc bộ lọc ngày (để card hiện "Còn 5/8 buổi" đúng dù đang
    lọc 1 ngày). Dùng cho danh sách chính để gộp gói định kỳ.
    """
    expire_unclaimed_schedules()

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

    # Lọc khu vực bằng Python (cần bỏ tiền tố "Thành phố"/"TP"/"Tỉnh").
    # order_by ở đây để buổi đầu tiên của mỗi booking chính là buổi gần nhất.
    # CHƯA lọc ngày ở DB: cần giữ lại tất cả buổi trống để đếm
    # available_sessions đúng cho từng booking.
    all_matched = [
        s for s in queryset.order_by('scheduled_start', 'id')
        if _norm(s.booking.address.city) in area_keys
    ]
    all_ids = [s.id for s in all_matched]

    if date_from or date_to:
        def _in_range(s):
            # Đổi sang giờ local (settings.TIME_ZONE) trước khi lấy ngày,
            # giống hành vi của lookup __date cũ. Cần TIME_ZONE = 'Asia/Ho_Chi_Minh'.
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
        # Đếm trên TẤT CẢ buổi trống của booking, không phụ thuộc bộ lọc ngày.
        result = _annotate_available_sessions(result, all_ids)
    else:
        result = BookingSchedule.objects.filter(id__in=matched_ids)

    result = result.select_related('booking', 'booking__service', 'booking__address')
    # 'id' là tie-breaker: order_by chỉ theo scheduled_start có thể làm
    # trùng/thiếu dòng giữa các trang khi nhiều buổi cùng giờ bắt đầu.
    return _annotate_total_sessions(result).order_by('scheduled_start', 'id')


def list_my_schedules(worker, schedule_status=None, booking_id=None):
    expire_unclaimed_schedules()

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
    """
    Toàn bộ buổi (trừ CANCELLED) của 1 booking, KHÔNG loại buổi đã có
    người nhận — dùng cho màn chi tiết gói để worker thấy đủ bức tranh:
    buổi mình đã nhận, buổi người khác đã nhận (không lộ danh tính), buổi
    còn trống. claim_state được serializer tính dựa trên assignments đã
    prefetch (ACCEPTED) + request.user.

    Điều kiện xem được: đúng nhóm dịch vụ + khu vực đăng ký của worker
    (như available), HOẶC worker đã có buổi ACCEPTED nào đó trong chính
    booking này (để dù khu vực/hồ sơ có đổi, worker vẫn xem lại được gói
    mình đang làm).
    """
    expire_unclaimed_schedules()

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

    # So khớp theo section_code (nhóm dịch vụ) thay vì service_id cụ thể,
    # để nhân viên đăng ký 1 nhóm (vd "Dọn dẹp nhà") nhận được cả buổi lẻ
    # lẫn buổi trong gói tháng thuộc cùng nhóm đó.
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
    _sync_booking_status_after_claim(booking)
    ensure_chat_for_assignment(assignment)
    return assignment


@transaction.atomic
def claim_booking_package(*, booking_id, worker, schedule_ids=None):
    """
    Nhận buổi trong 1 booking (gói định kỳ nhiều buổi).

    - schedule_ids=None -> nhận TOÀN BỘ buổi PENDING còn trống (hành vi cũ,
      dùng khi worker bấm "Nhận cả gói").
    - schedule_ids=[...] -> chỉ nhận đúng các buổi đó (worker tick chọn 1
      buổi hoặc 1 phần buổi trong gói ở màn chi tiết). id nào không thuộc
      booking này / không còn PENDING / đã qua giờ bắt đầu sẽ bị SKIP kèm
      lý do, KHÔNG raise lỗi ngay để các id còn lại vẫn được xử lý.

    Validate ở mức booking (payment/section_code/khu vực) một lần, rồi
    lock từng schedule để tránh race với claim_schedule() hoặc
    claim_booking_package() khác chạy song song trên cùng buổi.

    Trùng lịch: buổi nào trùng khung giờ với buổi khác đã ACCEPTED của
    worker (kể cả buổi vừa được ACCEPTED trong chính vòng lặp này, vì cùng
    nằm trong 1 transaction nên _has_time_conflict nhìn thấy được) sẽ bị
    SKIP kèm lý do 'Trùng khung giờ với buổi khác của bạn.' để FE báo cho
    nhân viên, thay vì cho nhận rồi mới phát hiện trùng.

    ĐỔI: KHÔNG còn gọi ensure_chat_for_assignment() ở đây — việc tạo chat
    được chuyển ra view, chạy SAU khi transaction này đã commit. Lý do:
    claim càng nhiều buổi thì vòng lặp tạo chat tuần tự càng kéo dài thời
    gian giữ transaction + giữ kết nối HTTP, tăng khả năng client bị rớt
    mạng (ERR_NETWORK) trước khi nhận được response dù DB đã ghi thành
    công. Tách ra để phần ghi DB cốt lõi (claim) trả lời nhanh nhất có thể.
    """
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
    )

    skipped = []

    if schedule_ids is not None:
        # Bỏ id trùng nhưng giữ thứ tự người dùng chọn để message/skipped
        # trả về theo đúng thứ tự FE gửi lên, dễ đối chiếu trên UI.
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

    for schedule in schedules:
        if BookingAssignment.objects.filter(
            schedule=schedule, status=BookingAssignment.Status.ACCEPTED,
        ).exists():
            skipped.append({'schedule_id': schedule.id, 'reason': 'Buổi làm việc này đã có người nhận.'})
            continue
        if _has_time_conflict(worker, schedule):
            skipped.append({'schedule_id': schedule.id, 'reason': 'Trùng khung giờ với buổi khác của bạn.'})
            continue

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
        claimed.append(assignment)

    if not claimed:
        raise serializers.ValidationError(
            {'booking': 'Không nhận được buổi nào (đã có người nhận, trùng lịch của bạn, hoặc buổi không hợp lệ).'}
        )

    _sync_booking_status_after_claim(booking)

    return {'claimed': claimed, 'skipped': skipped}


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
    ensure_chat_for_assignment(assignment)
    return assignment