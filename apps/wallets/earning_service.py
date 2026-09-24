from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

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


@transaction.atomic
def record_schedule_earning(*, schedule, booking, worker):
    """
    Gọi trong check_out ngay sau khi buổi được đánh dấu COMPLETED.

    Giá của 1 buổi = total_amount / số buổi chưa hủy, đúng công thức
    get_price ở WorkerScheduleSerializer để số nhân viên thấy lúc nhận việc
    khớp với số được ghi nhận thu nhập.

    Idempotent: buổi đã có dòng thu nhập thì trả về dòng cũ, không cộng lại.
    """
    existing = WorkerEarning.objects.filter(schedule=schedule).first()
    if existing:
        return existing

    total = booking.total_amount
    sessions = booking.schedules.exclude(status=BookingSchedule.Status.CANCELLED).count()
    if not total or not sessions:
        return None

    gross = _round_vnd(total / sessions)
    commission = _round_vnd(gross * COMMISSION_RATE)
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

    # Đơn online: app đang giữ tiền của khách -> cộng phần nhân viên vào ví.
    # Đơn tiền mặt: nhân viên đã cầm tiền, không cộng ví; hoa hồng nằm ở
    # WorkerEarning (settled_at null = chưa nộp cho app).
    if method == WorkerEarning.PaymentMethod.ONLINE and worker_amount > 0:
        wallet_service.credit_wallet(
            user=worker,
            amount=worker_amount,
            type=WalletTransaction.Type.EARNING,
            booking=booking,
            note=f'Thu nhập buổi {schedule.sequence_no} - {booking.booking_code}',
        )

    return earning