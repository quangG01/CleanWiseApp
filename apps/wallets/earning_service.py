from decimal import ROUND_HALF_UP, Decimal
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from apps.bookings.models import BookingSchedule
from apps.payments.models import Payment
from . import wallet_service
from .models import WalletTransaction, WorkerEarning
from datetime import timedelta
from django.conf import settings
from django.db.models import Q

# Hoa hồng của app: 10% trên mọi dịch vụ.
COMMISSION_RATE = Decimal('0.10')
EARNING_HOLD_HOURS = getattr(settings, 'EARNING_HOLD_HOURS', 24)

_VND = Decimal('1')


def _round_vnd(value):
    return value.quantize(_VND, rounding=ROUND_HALF_UP)


def _detect_payment_method(booking):
    """Có Payment CASH -> tiền mặt; còn lại là trả trước online (app giữ tiền)."""
    if Payment.objects.filter(booking=booking, method=Payment.Method.CASH).exists():
        return WorkerEarning.PaymentMethod.CASH
    return WorkerEarning.PaymentMethod.ONLINE


def calculate_gross_amount(schedule, booking):
    """Giá 1 buổi tính trên subtotal (trước voucher) để nhân viên không chịu voucher.
    Chia theo sessions_count chốt lúc tạo đơn, không đổi khi hủy bớt buổi."""
    breakdown = booking.price_breakdown or {}
    unit_price = breakdown.get('unit_price')
    if unit_price is not None:
        try:
            return _round_vnd(Decimal(str(unit_price)))
        except (TypeError, ValueError, ArithmeticError):
            pass

    base = booking.subtotal_amount or booking.total_amount
    sessions = breakdown.get('sessions_count') or booking.schedules.count()
    if not base or not sessions:
        return Decimal('0')
    return _round_vnd(base / sessions)


def calculate_commission(gross_amount):
    return _round_vnd(gross_amount * COMMISSION_RATE)


@transaction.atomic
def reserve_cash_commission(*, schedule, booking, worker, assignment):
    """
    Giữ chỗ hoa hồng ngay lúc worker nhận đơn tiền mặt — trừ ví ngay,
    để tránh trường hợp nhận dồn nhiều đơn cash rồi lúc check-out ví
    không đủ trừ (race condition đã biết trước).

    Raise serializers.ValidationError nếu ví không đủ tiền -> nơi gọi
    (claim_schedule/claim_booking_package) tự xử lý theo tình huống của nó.
    """
    commission = calculate_commission(calculate_gross_amount(schedule, booking))
    if commission <= 0:
        return

    wallet_service.debit_wallet(
        user=worker,
        amount=commission,
        type=WalletTransaction.Type.ADJUSTMENT,
        booking=booking,
        note=f'Giữ chỗ hoa hồng buổi {schedule.sequence_no} - {booking.booking_code}',
    )
    assignment.commission_reserved = commission
    assignment.save(update_fields=['commission_reserved'])


def release_cash_commission(*, assignment):
    """Hoàn lại phần hoa hồng đã giữ chỗ — gọi khi hủy nhận việc trước khi
    check-out (worker tự hủy, hết hạn check-in, hoặc admin gán lại người khác)."""
    if not assignment.commission_reserved:
        return
    wallet_service.credit_wallet(
        user=assignment.worker,
        amount=assignment.commission_reserved,
        type=WalletTransaction.Type.ADJUSTMENT,
        booking=assignment.schedule.booking,
        note=f'Hoàn giữ chỗ hoa hồng buổi {assignment.schedule.sequence_no} - '
             f'{assignment.schedule.booking.booking_code}',
    )
    assignment.commission_reserved = None
    assignment.save(update_fields=['commission_reserved'])


@transaction.atomic
def record_schedule_earning(*, schedule, booking, worker):
    """
    Gọi trong check_out. Idempotent.
    ONLINE: chỉ ghi sổ, tiền vào ví sau EARNING_HOLD_HOURS (release_held_earnings).
    CASH: xử lý hoa hồng như cũ.
    """
    existing = WorkerEarning.objects.filter(schedule=schedule).first()
    if existing:
        return existing

    gross = calculate_gross_amount(schedule, booking)
    if gross <= 0:
        return None
    commission = calculate_commission(gross)
    worker_amount = gross - commission
    method = _detect_payment_method(booking)

    earning = WorkerEarning.objects.create(
        worker=worker,
        schedule=schedule,
        booking=booking,
        payment_method=method,
        gross_amount=gross,
        commission_rate=COMMISSION_RATE,
        commission_amount=commission,
        worker_amount=worker_amount,
        completed_at=schedule.actual_end,
    )

    if method == WorkerEarning.PaymentMethod.CASH and commission > 0:
        assignment = schedule.assignments.filter(worker=worker, status='ACCEPTED').first()
        reserved = getattr(assignment, 'commission_reserved', None)

        if reserved:
            assignment.commission_reserved = None
            assignment.save(update_fields=['commission_reserved'])
            earning.settled_at = timezone.now()
            earning.save(update_fields=['settled_at'])
        else:
            try:
                wallet_service.debit_wallet(
                    user=worker,
                    amount=commission,
                    type=WalletTransaction.Type.ADJUSTMENT,
                    booking=booking,
                    note=f'Hoa hồng buổi {schedule.sequence_no} - {booking.booking_code}',
                )
                earning.settled_at = timezone.now()
                earning.save(update_fields=['settled_at'])
            except serializers.ValidationError:
                pass

    return earning


def _has_open_complaint(earning):
    from apps.complaints.models import Complaint
    return Complaint.objects.filter(
        booking_id=earning.booking_id,
        status__in=(Complaint.Status.PENDING, Complaint.Status.IN_REVIEW),
    ).filter(Q(schedule_id=earning.schedule_id) | Q(schedule__isnull=True)).exists()


def release_held_earnings():
    """Cộng ví các khoản ONLINE đã qua thời gian chờ và không có khiếu nại đang mở."""
    cutoff = timezone.now() - timedelta(hours=EARNING_HOLD_HOURS)
    ids = list(
        WorkerEarning.objects.filter(
            payment_method=WorkerEarning.PaymentMethod.ONLINE,
            wallet_credited_at__isnull=True,
            completed_at__lte=cutoff,
        ).values_list('id', flat=True)
    )
    for earning_id in ids:
        with transaction.atomic():
            earning = WorkerEarning.objects.select_for_update().select_related(
                'worker', 'booking', 'schedule',
            ).get(pk=earning_id)
            if earning.wallet_credited_at or _has_open_complaint(earning):
                continue
            if earning.worker_amount > 0:
                wallet_service.credit_wallet(
                    user=earning.worker,
                    amount=earning.worker_amount,
                    type=WalletTransaction.Type.EARNING,
                    booking=earning.booking,
                    note=f'Thu nhập buổi {earning.schedule.sequence_no} - {earning.booking.booking_code}',
                    idempotency_key=f'earning:{earning.id}',
                )
            earning.wallet_credited_at = timezone.now()
            earning.save(update_fields=['wallet_credited_at'])