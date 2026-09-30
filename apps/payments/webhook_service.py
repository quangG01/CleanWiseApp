import logging

from django.db import transaction
from django.utils import timezone

from apps.bookings.activity_service import record_booking_activity
from apps.bookings.models import Booking, BookingActivity
from apps.vouchers.voucher_service import (
    mark_user_voucher_used,
    release_user_voucher,
)

from .models import Payment
from .payment_link_service import get_payos_client

logger = logging.getLogger(__name__)


def verify_and_parse_payos_webhook(raw_body: bytes):
    """Raise payos.WebhookError nếu chữ ký (HMAC-SHA256) sai."""
    return get_payos_client().webhooks.verify(raw_body)


@transaction.atomic
def handle_payos_webhook(webhook_data):
    order_code = webhook_data.order_code
    amount = webhook_data.amount

    candidate = Payment.objects.filter(pk=order_code).values('booking_id').first()
    if not candidate:
        logger.info('payOS webhook: không có Payment orderCode=%s', order_code)
        return None

    booking = Booking.objects.select_for_update().get(pk=candidate['booking_id'])

    try:
        payment = Payment.objects.select_for_update().get(
            pk=order_code,
            status=Payment.Status.PENDING,
        )
    except Payment.DoesNotExist:
        logger.info('payOS webhook: không có Payment PENDING orderCode=%s', order_code)
        return None

    if amount < payment.amount:
        payment.status = Payment.Status.FAILED
        payment.failure_reason = f'Số tiền chuyển ({amount}) nhỏ hơn số tiền cần ({payment.amount}).'
        payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
        if booking.user_voucher_id:
            release_user_voucher(user_voucher_id=booking.user_voucher_id)
        record_booking_activity(
            booking=booking,
            event_type=BookingActivity.EventType.PAYMENT_UPDATED,
            message=f'Thanh toán đơn {booking.booking_code} thất bại.',
            old_data={'status': Payment.Status.PENDING},
            new_data={'status': Payment.Status.FAILED, 'reason': payment.failure_reason},
        )
        return payment

    payment.status = Payment.Status.SUCCESS
    payment.transaction_code = webhook_data.reference or str(order_code)
    payment.paid_at = timezone.now()
    payment.save(update_fields=['status', 'transaction_code', 'paid_at', 'updated_at'])

    booking.payment_status = Booking.PaymentStatus.PAID
    booking.save(update_fields=['payment_status', 'updated_at'])
    if booking.user_voucher_id:
        mark_user_voucher_used(user_voucher_id=booking.user_voucher_id)
    record_booking_activity(
        booking=booking,
        event_type=BookingActivity.EventType.PAYMENT_UPDATED,
        message=f'Thanh toán đơn {booking.booking_code} thành công.',
        old_data={'status': Payment.Status.PENDING},
        new_data={'status': Payment.Status.SUCCESS, 'payment_id': payment.id},
    )
    return payment
