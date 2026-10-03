from .models import Notification
from .push import send_push_to_user
from django.utils import timezone
from .realtime import push_unread_count

def create_notification(user, title, message, type=Notification.Type.SYSTEM,
                        related_booking=None, related_schedule=None):
    notif = Notification.objects.create(
        user=user, title=title, message=message, type=type,
        related_booking=related_booking, related_schedule=related_schedule,
    )
    push_unread_count(user.id)
    return notif


def create_notification_with_push(user, title, message, type=Notification.Type.SYSTEM,
                                  related_booking=None, related_schedule=None):
    notif = create_notification(user, title, message, type, related_booking, related_schedule)
    send_push_to_user(user, title, message, {
        'notification_id': notif.id,
        'type': type,
        'booking_id': related_booking.id if related_booking else None,
        'schedule_id': related_schedule.id if related_schedule else None,
    })
    return notif


# ===================== CUSTOMER =====================

def notify_booking_success(booking):
    return create_notification_with_push(
        user=booking.customer,
        title='Đặt lịch thành công',
        message=f'Booking {booking.booking_code} đã được đặt thành công.',
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_payment_success(payment):
    return create_notification_with_push(
        user=payment.customer,
        title='Thanh toán thành công',
        message=f'Booking {payment.booking.booking_code} đã được thanh toán thành công.',
        type=Notification.Type.PAYMENT,
        related_booking=payment.booking,
    )


def notify_payment_failed(payment):
    return create_notification_with_push(
        user=payment.customer,
        title='Thanh toán thất bại',
        message=f'Thanh toán cho booking {payment.booking.booking_code} không thành công. Vui lòng thử lại.',
        type=Notification.Type.PAYMENT,
        related_booking=payment.booking,
    )


def notify_customer_worker_assigned(assignment):
    booking = assignment.schedule.booking
    return create_notification_with_push(
        user=booking.customer,
        title='Lịch đã được nhận',
        message=f'{assignment.worker.get_full_name() or assignment.worker.username} đã nhận buổi {assignment.schedule.sequence_no} của booking {booking.booking_code}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_customer_worker_assigned_batch(booking, worker, schedule_count):
    """Dùng khi worker nhận nhiều buổi cùng lúc (nhận cả gói) — gộp thành
    1 thông báo duy nhất thay vì bắn N thông báo rời rạc từng buổi."""
    return create_notification_with_push(
        user=booking.customer,
        title='Lịch đã được nhận',
        message=f'{worker.get_full_name() or worker.username} đã nhận {schedule_count} '
                 f'buổi của booking {booking.booking_code}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_customer_worker_cancelled_schedule(schedule, reason):
    booking = schedule.booking
    return create_notification_with_push(
        user=booking.customer,
        title='Nhân viên đã hủy buổi làm',
        message=f'Nhân viên đã hủy buổi {schedule.sequence_no} của booking '
                 f'{booking.booking_code}. Lý do: {reason}. CleanWise đang tìm nhân viên khác.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_customer_booking_cancelled(booking):
    who = booking.cancelled_by.get_full_name() if booking.cancelled_by else 'hệ thống'
    return create_notification_with_push(
        user=booking.customer,
        title='Booking đã bị hủy',
        message=f'Booking {booking.booking_code} đã bị hủy bởi {who}.',
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_customer_booking_failed(booking):
    message = f'Booking {booking.booking_code} không tìm được nhân viên nhận việc.'
    if booking.payment_status == 'PAID':
        message += ' Số tiền đã thanh toán sẽ được hoàn lại vào ví của bạn.'
    return create_notification_with_push(
        user=booking.customer,
        title='Không tìm được nhân viên',
        message=message,
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_customer_schedule_reminder(schedule):
    time_str = timezone.localtime(schedule.scheduled_start).strftime('%H:%M %d/%m')
    return create_notification_with_push(
        user=schedule.booking.customer,
        title='Nhắc lịch',
        message=f'Bạn có lịch dọn dẹp lúc {time_str}.',
        type=Notification.Type.BOOKING,
        related_booking=schedule.booking,
    )


def notify_customer_booking_completed(booking):
    return create_notification_with_push(
        user=booking.customer,
        title='Booking hoàn thành',
        message=f'Booking {booking.booking_code} đã hoàn thành. Đừng quên đánh giá dịch vụ nhé!',
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_customer_complaint_resolved(complaint):
    return create_notification_with_push(
        user=complaint.customer,
        title='Khiếu nại đã được xử lý',
        message=f'Khiếu nại của bạn cho booking {complaint.booking.booking_code} đã được giải quyết.',
        type=Notification.Type.COMPLAINT,
        related_booking=complaint.booking,
    )


# ===================== WORKER =====================

def notify_worker_new_job(assignment):
    time_str = timezone.localtime(assignment.schedule.scheduled_start).strftime('%H:%M %d/%m')
    return create_notification_with_push(
        user=assignment.worker,
        title='Có lịch mới',
        message=f'Bạn có một lịch dọn dẹp mới lúc {time_str}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=assignment.schedule.booking,
    )


def notify_worker_removed_from_schedule(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Bạn đã bị gỡ khỏi lịch làm',
        message=f'Quản trị viên đã gán buổi {schedule.sequence_no} của booking '
                 f'{schedule.booking.booking_code} cho nhân viên khác.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=schedule.booking,
    )


def notify_worker_booking_cancelled(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Booking đã bị hủy',
        message=f'Khách hàng đã hủy booking {schedule.booking.booking_code}.',
        type=Notification.Type.BOOKING,
        related_booking=schedule.booking,
    )


def notify_worker_schedule_reminder(schedule, worker):
    time_str = timezone.localtime(schedule.scheduled_start).strftime('%H:%M %d/%m')
    return create_notification_with_push(
        user=worker,
        title='Sắp đến giờ làm',
        message=f'Booking {schedule.booking.booking_code} bắt đầu lúc {time_str}.',
        type=Notification.Type.BOOKING,
        related_booking=schedule.booking,
    )


def notify_worker_profile_approved(worker_profile):
    return create_notification_with_push(
        user=worker_profile.user,
        title='Hồ sơ đã được duyệt 🎉',
        message='Hồ sơ nhân viên của bạn đã được CleanWise phê duyệt. Bạn có thể bắt đầu nhận lịch.',
        type=Notification.Type.SYSTEM,
    )


def notify_worker_profile_rejected(worker_profile):
    return create_notification_with_push(
        user=worker_profile.user,
        title='Hồ sơ bị từ chối',
        message=f'Hồ sơ nhân viên của bạn chưa được duyệt. {worker_profile.rejection_reason or ""}'.strip(),
        type=Notification.Type.SYSTEM,
    )


# ===================== ADMIN =====================

def notify_admin_announcement(users, title, message):
    notifs = Notification.objects.bulk_create([
        Notification(user=user, title=title, message=message, type=Notification.Type.SYSTEM)
        for user in users
    ])
    for user in users:
        send_push_to_user(user, title, message)
        push_unread_count(user.id)
    return notifs

def notify_customer_refund(booking, amount, reason=None):
    message = f'{int(amount):,}đ đã được hoàn vào ví của bạn (booking {booking.booking_code}).'
    if reason:
        message += f' {reason}'
    return create_notification_with_push(
        user=booking.customer,
        title='Đã hoàn tiền vào ví',
        message=message,
        type=Notification.Type.PAYMENT,
        related_booking=booking,
    )
    
def notify_wallet_adjustment(user, amount, direction, reason):
    sign = '+' if direction == 'CREDIT' else '-'
    return create_notification_with_push(
        user=user,
        title='Số dư ví được điều chỉnh',
        message=f'{sign}{int(amount):,}đ. Lý do: {reason}',
        type=Notification.Type.PAYMENT,
    )


def notify_worker_schedule_cancelled(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Khách đã hủy buổi làm',
        message=f'Khách hàng đã hủy buổi {schedule.sequence_no} của booking {schedule.booking.booking_code}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=schedule.booking,
        related_schedule=schedule,
    )