from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.bookings.models import Booking, BookingSchedule, BookingScheduleImage
from apps.common.cloudinary_storage import (
    upload_image,
    delete_uploaded_file,
)
from apps.notifications.models import Notification
from apps.vouchers.voucher_service import mark_user_voucher_used

from .models import BookingAssignment
from .assignment_service import OPEN_BOOKING_STATUSES
from apps.wallets import earning_service

CHECKIN_EARLY_MINUTES = getattr(settings, 'CHECKIN_EARLY_MINUTES', 60)
CHECKIN_LATE_MINUTES = getattr(settings, 'CHECKIN_LATE_MINUTES', 60)
CHECKOUT_GRACE_MINUTES = getattr(settings, 'CHECKOUT_GRACE_MINUTES', 60)

MAX_IMAGES_PER_TYPE = getattr(settings, 'MAX_SCHEDULE_IMAGES_PER_TYPE', 5)

def _get_my_accepted_schedule(*, schedule_id, worker, for_update=True):
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

    if booking.status not in OPEN_BOOKING_STATUSES:
        raise serializers.ValidationError({'schedule': 'Đơn hàng không ở trạng thái có thể bắt đầu.'})

    now = timezone.now()
    earliest = schedule.scheduled_start - timedelta(minutes=CHECKIN_EARLY_MINUTES)
    latest = schedule.scheduled_start + timedelta(minutes=CHECKIN_LATE_MINUTES)

    if now < earliest:
        raise serializers.ValidationError({
            'schedule': f'Chưa đến giờ check-in. Bạn chỉ có thể check-in từ '
                        f'{CHECKIN_EARLY_MINUTES} phút trước giờ hẹn.'
        })
    if now > latest:
        raise serializers.ValidationError({
            'schedule': f'Đã quá {CHECKIN_LATE_MINUTES} phút so với giờ hẹn, '
                        f'không thể check-in. Vui lòng liên hệ khách hàng/CleanWise.'
        })

    schedule.actual_start = now
    schedule.status = BookingSchedule.Status.IN_PROGRESS
    schedule.save(update_fields=['actual_start', 'status', 'updated_at'])

    if booking.status in (Booking.Status.PENDING, Booking.Status.ASSIGNED):
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
def check_out(*, schedule_id, worker, completion_note=None):
    schedule = _get_my_accepted_schedule(schedule_id=schedule_id, worker=worker)
    booking = Booking.objects.select_for_update(of=('self',)).get(pk=schedule.booking_id)

    if schedule.status != BookingSchedule.Status.IN_PROGRESS:
        raise serializers.ValidationError({'schedule': 'Buổi làm việc chưa được Check-in hoặc đã hoàn thành.'})

    now = timezone.now()
    checkout_deadline = schedule.scheduled_end + timedelta(minutes=CHECKOUT_GRACE_MINUTES)
    if now > checkout_deadline:
        raise serializers.ValidationError({
            'schedule': f'Đã quá {CHECKOUT_GRACE_MINUTES} phút so với giờ kết thúc dự kiến, '
                        f'không thể tự check-out. Hệ thống sẽ tự động hoàn thành buổi làm này.'
        })

    
    before_count = schedule.images.filter(image_type=BookingScheduleImage.ImageType.BEFORE).count()
    after_count = schedule.images.filter(image_type=BookingScheduleImage.ImageType.AFTER).count()
    if before_count == 0:
        raise serializers.ValidationError({'images': 'Cần ít nhất 1 ảnh trước khi làm.'})
    if after_count == 0:
        raise serializers.ValidationError({'images': 'Cần ít nhất 1 ảnh sau khi làm.'})

    schedule.actual_end = now
    schedule.status = BookingSchedule.Status.COMPLETED
    schedule.completion_note = completion_note  # THÊM
    schedule.save(update_fields=['actual_end', 'status', 'completion_note', 'updated_at'])  # SỬA thêm field

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


def upload_schedule_image(*, schedule_id, worker, file, image_type, note=None):
    schedule = _get_my_accepted_schedule(
        schedule_id=schedule_id,
        worker=worker,
        for_update=False,
    )

    if schedule.status != BookingSchedule.Status.IN_PROGRESS:
        raise serializers.ValidationError({
            'schedule': 'Chỉ được thêm ảnh khi buổi làm việc đang thực hiện.'
        })

    current_count = BookingScheduleImage.objects.filter(
        schedule=schedule,
        image_type=image_type,
    ).count()

    if current_count >= MAX_IMAGES_PER_TYPE:
        raise serializers.ValidationError({
            'image': f'Mỗi loại ảnh tối đa {MAX_IMAGES_PER_TYPE} ảnh.'
        })

    # 1. Upload ảnh lên Cloudinary
    uploaded = upload_image(
        file,
        folder=f'schedules/{schedule.id}',
        public_id_prefix=image_type.lower(),
        field_name='image',
    )

    try:
        # 2. Tạo record trong DB
        last_order = BookingScheduleImage.objects.filter(
            schedule=schedule
        ).count()

        return BookingScheduleImage.objects.create(
            uploaded_by=worker,
            schedule=schedule,
            image_type=image_type,
            image=uploaded['url'],
            note=note or None,
            sort_order=last_order,
        )

    except Exception:
        # 3. DB lỗi → xóa ảnh vừa upload trên Cloudinary
        delete_uploaded_file(
            public_id=uploaded.get('public_id'),
            resource_type=uploaded.get('resource_type', 'image'),
        )
        raise