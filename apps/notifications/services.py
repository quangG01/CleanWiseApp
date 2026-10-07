from django.utils import timezone

from .models import Notification
from .push import send_push_to_user
from .realtime import push_unread_count


# ===================== HELPERS =====================

def fmt_vnd(amount) -> str:
    return f"{int(amount):,}".replace(",", ".") + "đ"


def fmt_time(dt) -> str:
    return timezone.localtime(dt).strftime('%H:%M, %d/%m')


def code(booking) -> str:
    return f"#{booking.booking_code}"


def display_name(user) -> str:
    return user.get_full_name() or user.username


def create_notification(user, title, message, type=Notification.Type.SYSTEM,
                        related_booking=None, related_schedule=None):
    notif = Notification.objects.create(
        user=user, title=title, message=message, type=type,
        related_booking=related_booking, related_schedule=related_schedule,
    )
    push_unread_count(user.id)
    return notif


def create_notification_with_push(user, title, message, type=Notification.Type.SYSTEM,
                                  related_booking=None, related_schedule=None,
                                  extra_data=None):
    notif = create_notification(user, title, message, type, related_booking, related_schedule)
    send_push_to_user(user, title, message, {
        'notification_id': notif.id,
        'type': type,
        'booking_id': related_booking.id if related_booking else None,
        'schedule_id': related_schedule.id if related_schedule else None,
        **(extra_data or {}),
    })
    return notif


# ===================== CUSTOMER =====================

def notify_booking_success(booking):
    return create_notification_with_push(
        user=booking.customer,
        title='Đặt lịch thành công',
        message=f'Đơn {code(booking)} đã được tạo thành công.',
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_payment_success(payment):
    return create_notification_with_push(
        user=payment.customer,
        title='Thanh toán thành công',
        message=f'Đơn {code(payment.booking)} đã được thanh toán.',
        type=Notification.Type.PAYMENT,
        related_booking=payment.booking,
    )


def notify_payment_failed(payment):
    return create_notification_with_push(
        user=payment.customer,
        title='Thanh toán thất bại',
        message=f'Đơn {code(payment.booking)} chưa thanh toán được. Vui lòng thử lại.',
        type=Notification.Type.PAYMENT,
        related_booking=payment.booking,
    )


def notify_customer_worker_assigned(assignment):
    booking = assignment.schedule.booking
    return create_notification_with_push(
        user=booking.customer,
        title='Đã có nhân viên nhận việc',
        message=f'{display_name(assignment.worker)} đã nhận buổi {assignment.schedule.sequence_no} của đơn {code(booking)}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_customer_worker_assigned_batch(booking, worker, schedule_count):
    """Worker nhận nhiều buổi cùng lúc — gộp thành 1 thông báo."""
    return create_notification_with_push(
        user=booking.customer,
        title='Đã có nhân viên nhận việc',
        message=f'{display_name(worker)} đã nhận {schedule_count} buổi của đơn {code(booking)}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_customer_worker_cancelled_schedule(schedule, reason):
    booking = schedule.booking
    return create_notification_with_push(
        user=booking.customer,
        title='Nhân viên đã hủy buổi làm',
        message=f'Buổi {schedule.sequence_no} của đơn {code(booking)} đã bị hủy ({reason}). '
                f'Chúng tôi đang tìm nhân viên khác cho bạn.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_customer_booking_cancelled(booking):
    who = booking.cancelled_by.get_full_name() if booking.cancelled_by else 'hệ thống'
    return create_notification_with_push(
        user=booking.customer,
        title='Đơn đã bị hủy',
        message=f'Đơn {code(booking)} đã bị hủy bởi {who}.',
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_customer_booking_failed(booking):
    message = f'Đơn {code(booking)} chưa có nhân viên nhận việc.'
    if booking.payment_status == 'PAID':
        message += ' Tiền sẽ được hoàn vào ví CleanWise của bạn.'
    return create_notification_with_push(
        user=booking.customer,
        title='Chưa tìm được nhân viên',
        message=message,
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_customer_schedule_reminder(schedule):
    return create_notification_with_push(
        user=schedule.booking.customer,
        title='Sắp đến giờ dọn dẹp',
        message=f'Lịch dọn dẹp của bạn bắt đầu lúc {fmt_time(schedule.scheduled_start)}.',
        type=Notification.Type.BOOKING,
        related_booking=schedule.booking,
    )


def notify_customer_booking_completed(booking):
    return create_notification_with_push(
        user=booking.customer,
        title='Đơn đã hoàn thành',
        message=f'Đơn {code(booking)} đã hoàn thành. Hãy đánh giá dịch vụ nhé!',
        type=Notification.Type.BOOKING,
        related_booking=booking,
    )


def notify_customer_complaint_resolved(complaint):
    return create_notification_with_push(
        user=complaint.customer,
        title='Khiếu nại đã được xử lý',
        message=f'Khiếu nại cho đơn {code(complaint.booking)} đã được giải quyết.',
        type=Notification.Type.COMPLAINT,
        related_booking=complaint.booking,
    )


def notify_customer_preferred_declined(booking, worker):
    return create_notification_with_push(
        user=booking.customer,
        title='Nhân viên chưa nhận được đơn',
        message=f'{display_name(worker)} chưa thể nhận đơn {code(booking)}. '
                f'Đơn đã được mở cho các nhân viên khác.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )

# ===================== WORKER =====================

def notify_worker_new_job(assignment):
    booking = assignment.schedule.booking
    return create_notification_with_push(
        user=assignment.worker,
        title='Bạn có lịch mới',
        message=f'Đơn {code(booking)} bắt đầu lúc {fmt_time(assignment.schedule.scheduled_start)}.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
    )


def notify_worker_removed_from_schedule(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Bạn đã được gỡ khỏi lịch làm',
        message=f'Buổi {schedule.sequence_no} của đơn {code(schedule.booking)} đã được giao cho nhân viên khác.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=schedule.booking,
    )


def notify_worker_booking_cancelled(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Khách đã hủy đơn',
        message=f'Đơn {code(schedule.booking)} đã bị khách hàng hủy.',
        type=Notification.Type.BOOKING,
        related_booking=schedule.booking,
    )


def notify_worker_schedule_reminder(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Sắp đến giờ làm',
        message=f'Đơn {code(schedule.booking)} bắt đầu lúc {fmt_time(schedule.scheduled_start)}.',
        type=Notification.Type.BOOKING,
        related_booking=schedule.booking,
    )


def notify_worker_schedule_cancelled(schedule, worker):
    return create_notification_with_push(
        user=worker,
        title='Khách đã hủy buổi làm',
        message=f'Buổi {schedule.sequence_no} của đơn {code(schedule.booking)} đã bị khách hàng hủy.',
        type=Notification.Type.ASSIGNMENT,
        related_booking=schedule.booking,
        related_schedule=schedule,
    )


def notify_worker_profile_approved(worker_profile):
    return create_notification_with_push(
        user=worker_profile.user,
        title='Hồ sơ đã được duyệt 🎉',
        message='CleanWise đã phê duyệt hồ sơ của bạn. Bạn có thể bắt đầu nhận lịch.',
        type=Notification.Type.SYSTEM,
    )


def notify_worker_profile_rejected(worker_profile):
    reason = (worker_profile.rejection_reason or '').strip()
    return create_notification_with_push(
        user=worker_profile.user,
        title='Hồ sơ chưa được duyệt',
        message=f'Hồ sơ của bạn chưa được duyệt. {reason}'.strip(),
        type=Notification.Type.SYSTEM,
    )
    

def notify_worker_preferred_request(booking, worker, expires_at):
    first_schedule = (
        booking.schedules.filter(status='PENDING').order_by('scheduled_start').first()
    )
    message = f'{display_name(booking.customer)} muốn bạn làm đơn {code(booking)}.'
    if expires_at > timezone.now():
        message += f' Nhận việc trước {fmt_time(expires_at)} để giữ đơn.'
    return create_notification_with_push(
        user=worker,
        title='Khách chỉ định bạn',
        message=message,
        type=Notification.Type.ASSIGNMENT,
        related_booking=booking,
        related_schedule=first_schedule,
        extra_data={'source': 'available'},
    )


# ===================== WALLET / ADMIN =====================

def notify_customer_refund(booking, amount, reason=None):
    message = f'{fmt_vnd(amount)} đã được hoàn vào ví CleanWise. Đơn {code(booking)}.'
    if reason:
        message += f' {reason}'
    return create_notification_with_push(
        user=booking.customer,
        title='Hoàn tiền thành công',
        message=message,
        type=Notification.Type.PAYMENT,
        related_booking=booking,
    )


def notify_wallet_adjustment(user, amount, direction, reason):
    sign = '+' if direction == 'CREDIT' else '-'
    return create_notification_with_push(
        user=user,
        title='Số dư ví được điều chỉnh',
        message=f'{sign}{fmt_vnd(amount)}. Lý do: {reason}',
        type=Notification.Type.PAYMENT,
    )


def notify_admin_announcement(users, title, message):
    notifs = Notification.objects.bulk_create([
        Notification(user=user, title=title, message=message, type=Notification.Type.SYSTEM)
        for user in users
    ])
    for user in users:
        send_push_to_user(user, title, message)
        push_unread_count(user.id)
    return notifs