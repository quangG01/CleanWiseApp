from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import Booking
from apps.payments.models import Payment

from . import wallet_service
from .models import WalletTransaction, WorkerEarning

# Hoa hồng của app: 10% trên mọi dịch vụ.
COMMISSION_RATE = Decimal('0.10')

_VND = Decimal('1')


def _round_vnd(value):
    return value.quantize(_VND, rounding=ROUND_HALF_UP)


def _detect_payment_method(booking):
    """Có Payment CASH -> tiền mặt; còn lại là trả trước online."""
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


@transaction.atomic
def release_cash_commission(*, assignment):
    """Hoàn lại phần hoa hồng đã giữ chỗ — gọi khi hủy nhận việc trước khi
    check-out (worker tự hủy, hết hạn check-in, hoặc admin gán lại người khác).

    Khóa dòng assignment rồi đọc lại commission_reserved từ DB: 2 lần gọi song song
    (task hết hạn + worker tự hủy) không thể cùng hoàn ví 2 lần.
    """
    locked = (
        type(assignment).objects.select_for_update()
        .select_related('schedule__booking', 'worker')
        .get(pk=assignment.pk)
    )
    reserved = locked.commission_reserved
    if not reserved:
        assignment.commission_reserved = None
        return

    wallet_service.credit_wallet(
        user=locked.worker,
        amount=reserved,
        type=WalletTransaction.Type.ADJUSTMENT,
        booking=locked.schedule.booking,
        note=f'Hoàn giữ chỗ hoa hồng buổi {locked.schedule.sequence_no} - '
             f'{locked.schedule.booking.booking_code}',
    )
    locked.commission_reserved = None
    locked.save(update_fields=['commission_reserved'])
    assignment.commission_reserved = None  # đồng bộ object của nơi gọi


@transaction.atomic
def record_schedule_earning(*, schedule, booking, worker):
    """Ghi tiền công khi hoàn thành buổi và cộng ví ngay với đơn online đã thanh toán."""
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    existing = WorkerEarning.objects.select_for_update().filter(schedule=schedule).first()
    if existing:
        _credit_online_earning(existing, booking)
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

    if method == WorkerEarning.PaymentMethod.ONLINE:
        _credit_online_earning(earning, booking)
    elif commission > 0:
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
                # Ví không đủ: settled_at để null = nhân viên còn nợ hoa hồng (cần theo dõi/đối soát).
                pass

    return earning


def _credit_online_earning(earning, booking):
    if (earning.payment_method != WorkerEarning.PaymentMethod.ONLINE
            or earning.wallet_credited_at or earning.voided_at
            or booking.payment_status != Booking.PaymentStatus.PAID):
        return
    if earning.worker_amount > 0:
        wallet_service.credit_wallet(
            user=earning.worker,
            amount=earning.worker_amount,
            type=WalletTransaction.Type.EARNING,
            booking=booking,
            note=f'Thu nhập buổi {earning.schedule.sequence_no} - {booking.booking_code}',
            idempotency_key=f'earning:{earning.id}',
        )
    earning.wallet_credited_at = timezone.now()
    earning.save(update_fields=['wallet_credited_at'])


def settle_pending_online_earnings(*, booking_id=None):
    """Ghi có khoản cũ còn tồn hoặc khoản hoàn thành trước khi xác nhận thanh toán."""
    pending = WorkerEarning.objects.filter(
        payment_method=WorkerEarning.PaymentMethod.ONLINE,
        wallet_credited_at__isnull=True,
        voided_at__isnull=True,
        booking__payment_status=Booking.PaymentStatus.PAID,
    ).order_by('pk')
    if booking_id is not None:
        pending = pending.filter(booking_id=booking_id)
    for earning_id, earning_booking_id in list(pending.values_list('id', 'booking_id')):
        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=earning_booking_id)
            earning = WorkerEarning.objects.select_for_update(of=('self',)).select_related(
                'worker', 'schedule',
            ).get(pk=earning_id)
            _credit_online_earning(earning, booking)
