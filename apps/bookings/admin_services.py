from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.addresses.models import CustomerAddress
from apps.notifications.services import (
    create_notification_with_push,
    notify_worker_booking_cancelled,
    notify_worker_removed_from_schedule,
    notify_customer_booking_completed,
)
from apps.notifications.models import Notification
from apps.payments.models import Payment
from apps.vouchers.voucher_service import release_user_voucher
from apps.wallets import earning_service, wallet_service
from apps.worker.models import BookingAssignment

from .activity_service import record_booking_activity
from .models import Booking, BookingActivity, BookingSchedule


@transaction.atomic
def update_booking_by_admin(*, booking_id, actor, validated_data):
    booking = get_object_or_404(
        Booking.objects.select_for_update().select_related('service'),
        pk=booking_id,
    )
    if booking.status in (Booking.Status.CANCELLED, Booking.Status.COMPLETED, Booking.Status.FAILED):
        raise serializers.ValidationError({'booking': 'Không thể sửa đơn đã kết thúc.'})

    old_data = {}
    new_data = {}
    update_fields = []

    if 'note' in validated_data:
        old_data['note'] = booking.note
        booking.note = validated_data['note'] or None
        new_data['note'] = booking.note
        update_fields.append('note')

    if 'address_id' in validated_data:
        address = get_object_or_404(
            CustomerAddress,
            pk=validated_data['address_id'],
            customer=booking.customer,
            is_active=True,
        )
        old_data['address_id'] = booking.address_id
        booking.address = address
        new_data['address_id'] = address.id
        update_fields.append('address')

    if 'delivery_address_id' in validated_data:
        address_count = (booking.service.form_schema or {}).get('address_count', 1)
        delivery_id = validated_data['delivery_address_id']
        if address_count >= 2 and not delivery_id:
            raise serializers.ValidationError(
                {'delivery_address_id': 'Dịch vụ này cần địa chỉ chuyển đến.'}
            )
        if address_count < 2 and delivery_id:
            raise serializers.ValidationError(
                {'delivery_address_id': 'Dịch vụ này không sử dụng địa chỉ chuyển đến.'}
            )
        delivery = None
        if delivery_id:
            delivery = get_object_or_404(
                CustomerAddress,
                pk=delivery_id,
                customer=booking.customer,
                is_active=True,
            )
        old_data['delivery_address_id'] = booking.delivery_address_id
        booking.delivery_address = delivery
        new_data['delivery_address_id'] = delivery.id if delivery else None
        update_fields.append('delivery_address')

    booking.save(update_fields=[*update_fields, 'updated_at'])
    record_booking_activity(
        booking=booking,
        actor=actor,
        event_type=BookingActivity.EventType.BOOKING_UPDATED,
        message=f'Admin cập nhật đơn {booking.booking_code}.',
        old_data=old_data,
        new_data=new_data,
    )
    return booking


@transaction.atomic
def update_schedule_by_admin(*, schedule_id, actor, validated_data):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking'),
        pk=schedule_id,
    )
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Chỉ được sửa buổi chưa bắt đầu.'})

    start = validated_data.get('scheduled_start', schedule.scheduled_start)
    end = validated_data.get('scheduled_end', schedule.scheduled_end)
    changing_time = start != schedule.scheduled_start or end != schedule.scheduled_end
    if start >= end:
        raise serializers.ValidationError({'scheduled_end': 'Giờ kết thúc phải sau giờ bắt đầu.'})
    if changing_time and start <= timezone.now():
        raise serializers.ValidationError({'scheduled_start': 'Thời gian mới phải ở tương lai.'})

    current_assignment = schedule.assignments.filter(
        status=BookingAssignment.Status.ACCEPTED,
    ).select_related('worker').first()
    if changing_time and current_assignment:
        conflict = BookingSchedule.objects.filter(
            assignments__worker=current_assignment.worker,
            assignments__status=BookingAssignment.Status.ACCEPTED,
            status__in=(BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS),
            scheduled_start__lt=end,
            scheduled_end__gt=start,
        ).exclude(pk=schedule.pk).exists()
        if conflict:
            raise serializers.ValidationError(
                {'scheduled_start': 'Lịch mới bị trùng với công việc khác của nhân viên.'}
            )

    old_data = {
        'scheduled_start': schedule.scheduled_start.isoformat(),
        'scheduled_end': schedule.scheduled_end.isoformat(),
        'note': schedule.note,
    }
    schedule.scheduled_start = start
    schedule.scheduled_end = end
    if 'note' in validated_data:
        schedule.note = validated_data['note'] or None
    schedule.reminder_sent_at = None if changing_time else schedule.reminder_sent_at
    schedule.save(update_fields=[
        'scheduled_start', 'scheduled_end', 'note', 'reminder_sent_at', 'updated_at',
    ])

    new_data = {
        'scheduled_start': schedule.scheduled_start.isoformat(),
        'scheduled_end': schedule.scheduled_end.isoformat(),
        'note': schedule.note,
        'reason': validated_data.get('reason'),
    }
    record_booking_activity(
        booking=schedule.booking,
        schedule=schedule,
        actor=actor,
        event_type=(
            BookingActivity.EventType.SCHEDULE_RESCHEDULED
            if changing_time else BookingActivity.EventType.BOOKING_UPDATED
        ),
        message=(
            f'Admin đổi lịch buổi {schedule.sequence_no}.'
            if changing_time else f'Admin cập nhật buổi {schedule.sequence_no}.'
        ),
        old_data=old_data,
        new_data=new_data,
    )

    if changing_time:
        message = (
            f'Buổi {schedule.sequence_no} của đơn {schedule.booking.booking_code} '
            f'đã được đổi lịch. Lý do: {validated_data.get("reason")}.'
        )
        create_notification_with_push(
            schedule.booking.customer,
            'Lịch dịch vụ đã thay đổi',
            message,
            Notification.Type.BOOKING,
            schedule.booking,
        )
        if current_assignment:
            create_notification_with_push(
                current_assignment.worker,
                'Lịch làm việc đã thay đổi',
                message,
                Notification.Type.ASSIGNMENT,
                schedule.booking,
            )
    return schedule


@transaction.atomic
def unassign_worker_by_admin(*, schedule_id, actor, reason):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking'),
        pk=schedule_id,
    )
    if schedule.status != BookingSchedule.Status.PENDING:
        raise serializers.ValidationError({'schedule': 'Chỉ được bỏ phân công buổi chưa bắt đầu.'})
    assignment = schedule.assignments.select_for_update(of=('self',)).filter(
        status=BookingAssignment.Status.ACCEPTED,
    ).select_related('worker').first()
    if not assignment:
        raise serializers.ValidationError({'assignment': 'Buổi này chưa có nhân viên.'})

    earning_service.release_cash_commission(assignment=assignment)
    assignment.status = BookingAssignment.Status.CANCELLED
    assignment.response_note = reason
    assignment.responded_at = timezone.now()
    assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])
    notify_worker_removed_from_schedule(schedule, assignment.worker)

    booking = schedule.booking
    if booking.status == Booking.Status.ASSIGNED:
        booking.status = Booking.Status.PENDING
        booking.save(update_fields=['status', 'updated_at'])

    record_booking_activity(
        booking=booking,
        schedule=schedule,
        actor=actor,
        event_type=BookingActivity.EventType.WORKER_UNASSIGNED,
        message=f'Admin bỏ phân công nhân viên khỏi buổi {schedule.sequence_no}.',
        old_data={'worker_id': assignment.worker_id, 'assignment_id': assignment.id},
        new_data={'reason': reason},
    )
    return assignment


@transaction.atomic
def cancel_booking_by_admin(*, booking_id, actor, reason):
    booking = get_object_or_404(
        Booking.objects.select_for_update(),
        pk=booking_id,
    )
    if booking.status not in (Booking.Status.PENDING, Booking.Status.ASSIGNED):
        raise serializers.ValidationError({'booking': 'Đơn không thể hủy ở trạng thái hiện tại.'})
    if booking.schedules.filter(status=BookingSchedule.Status.IN_PROGRESS).exists():
        raise serializers.ValidationError({'booking': 'Đơn đang được thực hiện, không thể hủy.'})

    previous_status = booking.status
    now = timezone.now()
    was_paid = booking.payment_status == Booking.PaymentStatus.PAID
    assignments = list(
        BookingAssignment.objects.select_for_update(of=('self',)).filter(
            schedule__booking=booking,
            status=BookingAssignment.Status.ACCEPTED,
        ).select_related('worker', 'schedule')
    )
    for assignment in assignments:
        earning_service.release_cash_commission(assignment=assignment)
        assignment.status = BookingAssignment.Status.CANCELLED
        assignment.response_note = reason
        assignment.responded_at = now
        assignment.save(update_fields=['status', 'response_note', 'responded_at', 'updated_at'])
        notify_worker_booking_cancelled(assignment.schedule, assignment.worker)

    booking.status = Booking.Status.CANCELLED
    booking.cancelled_by = actor
    booking.cancelled_at = now
    booking.cancel_reason = reason
    fields = ['status', 'cancelled_by', 'cancelled_at', 'cancel_reason', 'updated_at']
    if was_paid:
        booking.payment_status = Booking.PaymentStatus.REFUNDED
        fields.append('payment_status')
    booking.save(update_fields=fields)

    booking.schedules.exclude(
        status__in=(BookingSchedule.Status.COMPLETED, BookingSchedule.Status.CANCELLED),
    ).update(
        status=BookingSchedule.Status.CANCELLED,
        cancelled_by=actor,
        cancelled_at=now,
        cancel_reason=reason,
        updated_at=now,
    )
    booking.payments.filter(status=Payment.Status.PENDING).update(
        status=Payment.Status.CANCELLED,
        failure_reason='Booking đã bị quản trị viên hủy.',
        updated_at=now,
    )
    if was_paid:
        payment = booking.payments.filter(status=Payment.Status.SUCCESS).first()
        record_booking_activity(
            booking=booking,
            actor=actor,
            event_type=BookingActivity.EventType.REFUND_CREATED,
            message='Yêu cầu hoàn tiền đã được tạo.',
            metadata={'payment_id': payment.id if payment else None},
        )
        booking.payments.filter(status=Payment.Status.SUCCESS).update(
            status=Payment.Status.REFUNDED,
            updated_at=now,
        )
        wallet_service.credit_wallet(
            user=booking.customer,
            amount=booking.total_amount,
            booking=booking,
            note=f'Hoàn tiền do admin hủy đơn {booking.booking_code}',
        )
        record_booking_activity(
            booking=booking,
            actor=actor,
            event_type=BookingActivity.EventType.REFUND_COMPLETED,
            message='Đã hoàn tiền vào ví khách hàng.',
            metadata={'payment_id': payment.id if payment else None},
        )
    if booking.user_voucher_id:
        release_user_voucher(user_voucher_id=booking.user_voucher_id, allow_used=True)

    record_booking_activity(
        booking=booking,
        actor=actor,
        event_type=BookingActivity.EventType.BOOKING_CANCELLED,
        message=f'Admin hủy đơn {booking.booking_code}.',
        old_data={'status': previous_status},
        new_data={'status': Booking.Status.CANCELLED, 'reason': reason},
    )
    return booking


@transaction.atomic
def complete_schedule_by_admin(*, schedule_id, actor, reason, completion_note=None):
    schedule = get_object_or_404(
        BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking'),
        pk=schedule_id,
    )
    booking = Booking.objects.select_for_update(of=('self',)).get(pk=schedule.booking_id)
    if schedule.status != BookingSchedule.Status.IN_PROGRESS:
        raise serializers.ValidationError(
            {'schedule': 'Chỉ được xác nhận thủ công cho buổi đang thực hiện.'}
        )
    assignment = schedule.assignments.filter(
        status=BookingAssignment.Status.ACCEPTED,
    ).select_related('worker').first()
    if not assignment:
        raise serializers.ValidationError({'assignment': 'Buổi này không có nhân viên phụ trách.'})

    now = timezone.now()
    schedule.actual_end = now
    schedule.status = BookingSchedule.Status.COMPLETED
    schedule.completion_note = completion_note or f'Admin xác nhận: {reason}'
    schedule.save(update_fields=['actual_end', 'status', 'completion_note', 'updated_at'])

    earning_service.record_schedule_earning(
        schedule=schedule,
        booking=booking,
        worker=assignment.worker,
    )
    still_active = booking.schedules.filter(
        status__in=(BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS),
    ).exclude(pk=schedule.pk).exists()
    if not still_active and booking.status == Booking.Status.IN_PROGRESS:
        booking.status = Booking.Status.COMPLETED
        booking.save(update_fields=['status', 'updated_at'])
        notify_customer_booking_completed(booking)

    record_booking_activity(
        booking=booking,
        schedule=schedule,
        actor=actor,
        event_type=BookingActivity.EventType.CHECKED_OUT,
        message=f'Admin xác nhận hoàn thành thủ công buổi {schedule.sequence_no}.',
        old_data={'status': BookingSchedule.Status.IN_PROGRESS},
        new_data={
            'status': BookingSchedule.Status.COMPLETED,
            'reason': reason,
            'completion_note': schedule.completion_note,
        },
        metadata={'manual': True},
    )
    return schedule
