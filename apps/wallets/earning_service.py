from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import BookingSchedule
from apps.payments.models import Payment

from . import wallet_service
from .models import WalletTransaction, WorkerEarning

# Hoa hồng của app: 10% trên mọi dịch vụ.
COMMISSION_RATE = Decimal('0.10')

_VND = Decimal('1')


def _round_vnd(value):
    return value.quantize(_VND, rounding=ROUND_HALF_UP)


def _detect_payment_method(booking):
    """Có Payment CASH -> tiền mặt; còn lại là trả trước online (app giữ tiền)."""
    if Payment.objects.filter(booking=booking, method=Payment.Method.CASH).exists():
        return WorkerEarning.PaymentMethod.CASH
    return WorkerEarning.PaymentMethod.ONLINE


def calculate_gross_amount(schedule, booking):
    """Giá 1 buổi — cùng công thức với WorkerScheduleSerializer.get_price,
    để số tiền giữ chỗ lúc nhận đơn khớp số nhân viên đã thấy khi xem đơn."""
    breakdown = booking.price_breakdown or {}
    unit_price = breakdown.get('unit_price')
    if unit_price is not None:
        try:
            return _round_vnd(Decimal(str(unit_price)))
        except (TypeError, ValueError, ArithmeticError):
            pass

    total = booking.total_amount
    sessions = booking.schedules.exclude(status=BookingSchedule.Status.CANCELLED).count()
    if not total or not sessions:
        return Decimal('0')
    return _round_vnd(total / sessions)


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
    Gọi trong check_out ngay sau khi buổi được đánh dấu COMPLETED.
    Idempotent: buổi đã có dòng thu nhập thì trả về dòng cũ, không cộng lại.
    """
    existing = WorkerEarning.objects.filter(schedule=schedule).first()
    if existing:
        return existing

    total = booking.total_amount
    sessions = booking.schedules.exclude(status=BookingSchedule.Status.CANCELLED).count()
    if not total or not sessions:
        return None

    gross = calculate_gross_amount(schedule, booking)
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

    if method == WorkerEarning.PaymentMethod.ONLINE and worker_amount > 0:
        wallet_service.credit_wallet(
            user=worker,
            amount=worker_amount,
            type=WalletTransaction.Type.EARNING,
            booking=booking,
            note=f'Thu nhập buổi {schedule.sequence_no} - {booking.booking_code}',
        )
    elif method == WorkerEarning.PaymentMethod.CASH and commission > 0:
        # Dùng related_name 'assignments' trên BookingSchedule, tránh phải
        # import model BookingAssignment (khác app) vào đây.
        assignment = schedule.assignments.filter(worker=worker, status='ACCEPTED').first()
        reserved = getattr(assignment, 'commission_reserved', None)

        if reserved:
            # Đã giữ chỗ (trừ ví) sẵn lúc nhận việc -> chỉ đánh dấu đã nộp,
            # KHÔNG trừ ví lần nữa.
            assignment.commission_reserved = None
            assignment.save(update_fields=['commission_reserved'])
            earning.settled_at = timezone.now()
            earning.save(update_fields=['settled_at'])
        else:
            # Không có khoản giữ chỗ (dữ liệu cũ trước bản vá, hoặc admin
            # gán tay không qua claim_schedule) -> thử trừ ví ngay bây giờ.
            # Nếu ví không đủ, để nợ (settled_at=null), KHÔNG chặn check-out.
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