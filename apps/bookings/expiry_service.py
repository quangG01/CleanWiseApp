from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.payments.models import Payment
from apps.vouchers.voucher_service import release_user_voucher

from .activity_service import record_booking_activity
from .models import Booking, BookingActivity, BookingSchedule

UNPAID_BOOKING_TTL_MINUTES = getattr(settings, 'UNPAID_BOOKING_TTL_MINUTES', 30)


@transaction.atomic
def cancel_unpaid_booking(*, booking, reason):
    """Hủy đơn online chưa thanh toán. Caller phải đã lock booking."""
    now = timezone.now()
    booking.status = Booking.Status.CANCELLED
    booking.cancelled_at = now
    booking.cancel_reason = reason
    booking.save(update_fields=['status', 'cancelled_at', 'cancel_reason', 'updated_at'])

    booking.schedules.exclude(
        status__in=(BookingSchedule.Status.COMPLETED, BookingSchedule.Status.CANCELLED),
    ).update(
        status=BookingSchedule.Status.CANCELLED, cancelled_at=now,
        cancel_reason=reason, updated_at=now,
    )
    booking.payments.filter(status=Payment.Status.PENDING).update(
        status=Payment.Status.CANCELLED, failure_reason=reason, updated_at=now,
    )
    if booking.user_voucher_id:
        release_user_voucher(user_voucher_id=booking.user_voucher_id, allow_used=True)

    record_booking_activity(
        booking=booking,
        event_type=BookingActivity.EventType.BOOKING_CANCELLED,
        message=f'Đơn {booking.booking_code} tự hủy: {reason}',
        new_data={'status': Booking.Status.CANCELLED, 'reason': reason},
        metadata={'automatic': True},
    )


def expire_unpaid_bookings():
    cutoff = timezone.now() - timedelta(minutes=UNPAID_BOOKING_TTL_MINUTES)
    ids = list(
        Booking.objects.filter(
            status=Booking.Status.PENDING,
            payment_status=Booking.PaymentStatus.UNPAID,
            created_at__lt=cutoff,
            payments__method=Payment.Method.BANK_TRANSFER,
        ).values_list('id', flat=True).distinct()
    )
    for booking_id in ids:
        with transaction.atomic():
            booking = Booking.objects.select_for_update().get(pk=booking_id)
            if booking.status != Booking.Status.PENDING or booking.payment_status != Booking.PaymentStatus.UNPAID:
                continue
            cancel_unpaid_booking(booking=booking, reason='Quá hạn thanh toán online.')