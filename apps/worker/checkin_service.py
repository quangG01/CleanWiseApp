from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import Booking, BookingSchedule, BookingScheduleImage
from apps.common.cloudinary_storage import upload_image
from apps.notifications.models import Notification
from apps.vouchers.voucher_service import mark_user_voucher_used

from .models import BookingAssignment
from apps.wallets import earning_service


def _get_my_accepted_schedule(*, schedule_id, worker, for_update=True):
    """Lấy schedule + đảm bảo worker chính là người đã nhận (ACCEPTED) buổi này."""
    if not BookingAssignment.objects.filter(
        schedule_id=schedule_id, worker=worker,
        status=BookingAssignment.Status.ACCEPTED,
    ).exists():
        raise serializers.ValidationError({'schedule': 'Bạn chưa nhận buổi làm việc này.'})

    queryset = BookingSchedule.objects.select_related('booking')
    if for_update:
        queryset = queryset.select_for_update(of=('self',))

    return get_object_or_404(queryset, pk=schedule_id)


@transaction.atomic
def check_in(*, schedule_id, worker):
    schedule = _get_my_accepted_schedule(schedule_id=schedule_id, worker=worker)
    booking = schedule.booking

    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc không ở trạng thái chờ thực hiện.'})
    if booking.status not in (Booking.Status.ASSIGNED, Booking.Status.IN_PROGRESS):
        raise serializers.ValidationError({'schedule': 'Đơn hàng không ở trạng thái có thể bắt đầu.'})

    now = timezone.now()
    schedule.actual_start = now
    schedule.status = BookingSchedule.Status.IN_PROGRESS
    schedule.save(update_fields=['actual_start', 'status', 'updated_at'])

    if booking.status == Booking.Status.ASSIGNED:
        booking.status = Booking.Status.IN_PROGRESS
        booking.save(update_fields=['status', 'updated_at'])

    if booking.user_voucher_id:
        mark_user_voucher_used(user_voucher_id=booking.user_voucher_id)

    Notification.objects.create(
        user=booking.customer,
        title='Nhân viên đã bắt đầu',
        message=f'Nhân viên đã bắt đầu thực hiện dịch vụ cho đơn {booking.booking_code}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )
    return schedule


@transaction.atomic
def check_out(*, schedule_id, worker):
    schedule = _get_my_accepted_schedule(schedule_id=schedule_id, worker=worker)
    booking = Booking.objects.select_for_update(of=('self',)).get(pk=schedule.booking_id)

    if schedule.status != BookingSchedule.Status.IN_PROGRESS:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc chưa được Check-in hoặc đã hoàn thành.'})

    now = timezone.now()
    schedule.actual_end = now
    schedule.status = BookingSchedule.Status.COMPLETED
    schedule.save(update_fields=['actual_end', 'status', 'updated_at'])

    # Còn buổi nào chưa xong (PENDING/IN_PROGRESS) -> booking vẫn IN_PROGRESS.
    # Hết buổi -> booking COMPLETED.
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
        message=f'Nhân viên đã hoàn thành dịch vụ cho đơn {booking.booking_code}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )
    return schedule


@transaction.atomic
def upload_schedule_image(*, schedule_id, worker, file, image_type, note=None):
    schedule = _get_my_accepted_schedule(schedule_id=schedule_id, worker=worker, for_update=False)

    if schedule.status != BookingSchedule.Status.IN_PROGRESS:
        raise serializers.ValidationError({'schedule': 'Chỉ được thêm ảnh khi buổi làm việc đang thực hiện.'})

    uploaded = upload_image(
        file,
        folder=f'schedules/{schedule.id}',
        public_id_prefix=image_type.lower(),
        field_name='image',
    )

    last_order = BookingScheduleImage.objects.filter(schedule=schedule).count()

    return BookingScheduleImage.objects.create(
        uploaded_by=worker,
        schedule=schedule,
        image_type=image_type,
        image=uploaded['url'],
        note=note or None,
        sort_order=last_order,
    )
