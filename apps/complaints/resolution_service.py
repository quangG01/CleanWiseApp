from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.activity_service import record_booking_activity
from apps.bookings.models import Booking, BookingActivity, BookingSchedule
from apps.payments.models import Payment
from apps.wallets import earning_service, refund_service, wallet_service
from apps.wallets.models import WalletTransaction as TX, WorkerEarning

from .models import Complaint

ZERO = Decimal('0')


def _is_cash(booking):
    return Payment.objects.filter(booking=booking, method=Payment.Method.CASH).exists()


def _sum_tx(prefix, direction):
    return TX.objects.filter(
        idempotency_key__startswith=prefix, direction=direction, status=TX.Status.SUCCESS,
    ).aggregate(s=Sum('amount'))['s'] or ZERO


def _clawed(schedule):
    return _sum_tx(f'clawback:schedule:{schedule.id}:', TX.Direction.DEBIT)


def _net_refunded(schedule):
    """Khách đã được hoàn bao nhiêu cho buổi này (đã trừ phần thu hồi)."""
    return _sum_tx(f'refund:schedule:{schedule.id}:', TX.Direction.CREDIT) - _clawed(schedule)


def _debit_up_to(*, user, owed, booking, note, key, admin):
    """Trừ tối đa `owed`, ví không âm. Trả (đã trừ, còn thiếu)."""
    wallet, _ = wallet_service.get_or_create_wallet_locked(user)
    take = min(owed, wallet.balance)
    if take > 0:
        wallet_service.debit_wallet(
            user=user, amount=take, type=TX.Type.ADJUSTMENT, booking=booking,
            note=note, created_by=admin, idempotency_key=key,
        )
        from apps.notifications.services import notify_wallet_adjustment
        transaction.on_commit(lambda: notify_wallet_adjustment(user, take, 'DEBIT', note))
    return take, owed - take


def _restore_booking_after_clawback(booking, taken):
    booking = Booking.objects.select_for_update().get(pk=booking.pk)
    booking.refunded_amount = max(ZERO, (booking.refunded_amount or ZERO) - taken)
    fields = ['refunded_amount', 'updated_at']
    if (booking.payment_status == Booking.PaymentStatus.REFUNDED
            and booking.refunded_amount < (booking.total_amount or ZERO)):
        booking.payment_status = Booking.PaymentStatus.PAID
        fields.append('payment_status')
        booking.payments.filter(status=Payment.Status.REFUNDED).update(
            status=Payment.Status.SUCCESS, updated_at=timezone.now(),
        )
    booking.save(update_fields=fields)


def _reverse_worker_earning(*, complaint, admin):
    schedule, booking = complaint.schedule, complaint.booking
    earning = WorkerEarning.objects.select_for_update().filter(schedule=schedule).first()
    if not earning or earning.voided_at:
        return ZERO, ZERO
    earning.voided_at = timezone.now()
    earning.save(update_fields=['voided_at'])
    if not earning.wallet_credited_at:   # đang giữ, chưa vào ví: chỉ cần hủy
        return ZERO, ZERO
    return _debit_up_to(
        user=earning.worker, owed=earning.worker_amount, booking=booking, admin=admin,
        note=f'Thu hồi thu nhập buổi {schedule.sequence_no} - {booking.booking_code} (khiếu nại #{complaint.id})',
        key=f'complaint:{complaint.id}:worker-clawback',
    )


def _refund_customer(*, complaint, admin, charge_worker):
    booking, schedule = complaint.booking, complaint.schedule
    if _is_cash(booking):
        raise serializers.ValidationError(
            {'outcome': 'Đơn tiền mặt: khách đã trả trực tiếp cho nhân viên, không hoàn qua ví được.'})

    cap = refund_service.per_session_refund_amount(booking) - _net_refunded(schedule)
    if cap <= 0:
        raise serializers.ValidationError({'outcome': 'Buổi này đã được hoàn đủ cho khách.'})

    refunded = refund_service.refund_booking(
        booking=booking, amount=cap, actor=admin,
        key=f'refund:schedule:{schedule.id}:complaint:{complaint.id}',
        note=f'Hoàn tiền buổi {schedule.sequence_no} - {booking.booking_code} (khiếu nại #{complaint.id})',
    )
    if not refunded:
        raise serializers.ValidationError({'outcome': 'Không hoàn được: đơn chưa thanh toán hoặc đã hoàn hết.'})

    taken = short = ZERO
    if charge_worker:
        taken, short = _reverse_worker_earning(complaint=complaint, admin=admin)
    return {'customer_delta': refunded, 'worker_delta': -taken, 'shortfall': short}


def _pay_worker(*, complaint, admin):
    booking, schedule, worker = complaint.booking, complaint.schedule, complaint.worker
    if worker is None:
        raise serializers.ValidationError({'outcome': 'Khiếu nại chưa xác định nhân viên.'})
    now = timezone.now()
    cash = _is_cash(booking)
    M = WorkerEarning.PaymentMethod
    earning = WorkerEarning.objects.select_for_update().filter(schedule=schedule).first()

    if earning and earning.voided_at:
        raise serializers.ValidationError({'outcome': 'Thu nhập buổi này đã bị thu hồi trước đó.'})
    if earning and earning.wallet_credited_at:
        raise serializers.ValidationError({'outcome': 'Nhân viên đã nhận thu nhập buổi này.'})

    if earning is None:      # buổi bị hệ thống hủy (MISSED), chưa có thu nhập
        gross = earning_service.calculate_gross_amount(schedule, booking)
        if gross <= 0:
            raise serializers.ValidationError({'outcome': 'Không tính được giá buổi.'})
        commission = earning_service.calculate_commission(gross)
        earning = WorkerEarning.objects.create(
            worker=worker, schedule=schedule, booking=booking,
            payment_method=M.CASH if cash else M.ONLINE,
            gross_amount=gross, commission_rate=earning_service.COMMISSION_RATE,
            commission_amount=commission, worker_amount=gross - commission,
            completed_at=schedule.scheduled_end, settled_at=now,
        )
        payout = earning.worker_amount
    elif earning.payment_method == M.CASH:
        # Đã trả hoa hồng mà không thu được tiền mặt -> bù đủ giá buổi.
        payout = earning.gross_amount if earning.settled_at else earning.worker_amount
        earning.settled_at = earning.settled_at or now
    else:
        payout = earning.worker_amount

    wallet_service.credit_wallet(
        user=worker, amount=payout, type=TX.Type.EARNING, booking=booking, created_by=admin,
        note=f'Thu nhập buổi {schedule.sequence_no} - {booking.booking_code} (khiếu nại #{complaint.id})',
        idempotency_key=f'earning:{earning.id}',
    )
    earning.wallet_credited_at = now
    earning.save(update_fields=['wallet_credited_at', 'settled_at'])

    owed = (
        max(ZERO, refund_service.per_session_refund_amount(booking) - _clawed(schedule))
        if cash else _net_refunded(schedule)
    )
    taken = short = ZERO
    if owed > 0:
        taken, short = _debit_up_to(
            user=booking.customer, owed=owed, booking=booking, admin=admin,
            note=f'Thu hồi tiền buổi {schedule.sequence_no} - {booking.booking_code} (khiếu nại #{complaint.id})',
            key=f'clawback:schedule:{schedule.id}:complaint:{complaint.id}',
        )
        if taken and not cash:
            _restore_booking_after_clawback(booking, taken)
    return {'customer_delta': -taken, 'worker_delta': payout, 'shortfall': short}


@transaction.atomic
def apply_outcome(*, complaint, admin, outcome, charge_worker=True):
    if complaint.schedule_id is None:
        raise serializers.ValidationError({'outcome': 'Khiếu nại chưa gắn buổi làm nên không xử lý tiền được.'})
    Booking.objects.select_for_update().get(pk=complaint.booking_id)
    BookingSchedule.objects.select_for_update().get(pk=complaint.schedule_id)

    if outcome == Complaint.Outcome.REFUND_CUSTOMER:
        r = _refund_customer(complaint=complaint, admin=admin, charge_worker=charge_worker)
    elif outcome == Complaint.Outcome.PAY_WORKER:
        r = _pay_worker(complaint=complaint, admin=admin)
    else:
        raise serializers.ValidationError({'outcome': 'Kết quả không hợp lệ.'})

    complaint.outcome = outcome
    complaint.customer_delta = r['customer_delta']
    complaint.worker_delta = r['worker_delta']
    complaint.shortfall = r['shortfall']
    complaint.refund_amount = max(r['customer_delta'], ZERO)

    record_booking_activity(
        booking=complaint.booking, schedule=complaint.schedule, actor=admin,
        event_type=BookingActivity.EventType.BOOKING_UPDATED,
        message=f'Xử lý tiền khiếu nại #{complaint.id}: {outcome}.',
        metadata={k: str(v) for k, v in r.items()},
    )
    return complaint