from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.bookings.activity_service import record_booking_activity
from apps.bookings.booking_service import _generate_booking_code
from apps.bookings.models import Booking, BookingActivity, BookingSchedule
from apps.notifications.models import Notification
from apps.notifications.services import create_notification_with_push, fmt_vnd
from apps.payments.models import Payment
from apps.vouchers.models import Voucher
from apps.vouchers.voucher_service import assign_voucher_to_customer
from apps.wallets import earning_service, refund_service
from apps.wallets.models import WalletTransaction
from apps.worker.models import BookingAssignment
from apps.worker.invitation_service import send_invitation

from .models import Complaint, ComplaintEvent as Event, ComplaintProposal as Proposal
from .resolution_service import apply_outcome, net_schedule_refunded


def record(complaint, actor, kind, message, *, public=True):
    Event.objects.create(
        complaint=complaint, actor=actor, kind=kind, message=message, is_public=public,
    )


def notify(complaint, title, message):
    create_notification_with_push(
        user=complaint.reporter, title=title, message=f'{complaint.code}: {message}',
        type=Notification.Type.COMPLAINT, related_booking=complaint.booking,
        related_schedule=complaint.schedule,
    )


def require(condition, message):
    if not condition:
        raise serializers.ValidationError(message)


def refund_limit(complaint, scope):
    booking = complaint.booking
    remaining = (booking.total_amount or Decimal(0)) - booking.refunded_amount
    require(booking.payment_status == Booking.PaymentStatus.PAID and remaining > 0,
            'Đơn chưa thanh toán hoặc đã hoàn hết.')
    require(not booking.payments.filter(method=Payment.Method.CASH).exists()
            and booking.payments.filter(status=Payment.Status.SUCCESS).exists(),
            'Cần giao dịch thanh toán online thành công để hoàn vào ví.')
    if scope == Proposal.RefundScope.BOOKING:
        return remaining
    require(complaint.schedule_id, 'Cần chọn buổi dịch vụ để hoàn tiền buổi.')
    session_remaining = refund_service.per_session_refund_amount(booking) - net_schedule_refunded(complaint.schedule)
    return min(remaining, session_remaining)


def proposed_refund(complaint, scope, amount):
    if not scope:
        require(amount is None, 'Chọn phạm vi hoàn tiền.')
        return None
    if scope == Proposal.RefundScope.CASH:
        require(complaint.booking.payments.filter(method=Payment.Method.CASH).exists(),
                'Chỉ đối soát tiền mặt cho đơn thanh toán tiền mặt.')
        require(amount is not None and amount > 0, 'Nhập số tiền đã đối soát.')
        return amount
    if scope == Proposal.RefundScope.PARTIAL:
        require(amount is not None and 0 < amount <= refund_limit(complaint, scope),
                'Số tiền phải nằm trong phần còn có thể hoàn của buổi.')
        return amount
    require(amount is None, 'Số tiền hoàn toàn bộ do hệ thống tính.')
    amount = refund_limit(complaint, scope)
    require(amount > 0, 'Không còn số tiền có thể hoàn.')
    return amount


def create_proposal(complaint, data):
    scope = data.get('refund_scope', '')
    action = data.get('service_action', '')
    voucher = data.get('voucher')
    worker = data.get('worker')
    start = data.get('scheduled_start')
    if action:
        require(start and start > timezone.now(), 'Nhập lịch thực hiện trong tương lai.')
        require(worker and worker.role == get_user_model().Role.WORKER and worker.is_active,
                'Chọn tài khoản nhân viên đang hoạt động.')
        require(complaint.schedule_id, 'Phương án dịch vụ cần gắn với buổi bị khiếu nại.')
        if action == Proposal.ServiceAction.REDO:
            require(complaint.schedule.status == BookingSchedule.Status.COMPLETED,
                    'Chỉ tạo buổi làm lại cho buổi đã hoàn thành.')
        else:
            require(complaint.schedule.status == BookingSchedule.Status.PENDING,
                    'Chỉ đổi lịch hoặc nhân viên cho buổi chưa bắt đầu.')
    else:
        require(not start and not worker, 'Chọn phương án dịch vụ trước khi nhập lịch.')
    if voucher:
        now = timezone.now()
        require(voucher.distribution_type == Voucher.DistributionType.ASSIGNED
                and voucher.is_active and voucher.start_at <= now < voucher.end_at,
                'Chọn voucher cấp riêng đang hoạt động.')
    return Proposal.objects.create(
        complaint=complaint, message=data['message'], service_action=action,
        scheduled_start=start, worker=worker, voucher=voucher, refund_scope=scope,
        refund_amount=proposed_refund(complaint, scope, data.get('refund_amount')),
    )


def schedule_redo(complaint, proposal, actor):
    require(proposal.status == Proposal.Status.ACCEPTED and proposal.service_action == Proposal.ServiceAction.REDO,
            'Khách chưa đồng ý phương án làm lại.')
    if proposal.fulfilled_schedule_id:
        return
    source = complaint.booking
    original = complaint.schedule
    start = proposal.scheduled_start
    require(start > timezone.now() + timedelta(minutes=30), 'Lịch làm lại cần cách hiện tại hơn 30 phút.')
    gross = earning_service.calculate_gross_amount(original, source)
    require(gross > 0, 'Không xác định được tiền công của buổi gốc.')
    booking = Booking.objects.create(
        booking_code=_generate_booking_code(), customer=source.customer, service=source.service,
        address=source.address, delivery_address=source.delivery_address, service_data=source.service_data,
        note=f'Làm lại miễn phí theo khiếu nại {complaint.code}.',
        payment_status=Booking.PaymentStatus.PAID, subtotal_amount=0, total_amount=0,
        price_breakdown={
            'unit_price': str(gross), 'sessions_count': 1, 'total_amount': '0',
            'complaint_code': complaint.code, 'source_schedule_id': original.pk,
        },
    )
    schedule = BookingSchedule.objects.create(
        booking=booking, sequence_no=1, scheduled_start=start,
        scheduled_end=start + (original.scheduled_end - original.scheduled_start),
    )
    record_booking_activity(
        booking=booking, schedule=schedule, actor=actor,
        event_type=BookingActivity.EventType.BOOKING_CREATED, message=booking.note,
    )
    send_invitation(schedule_id=schedule.pk, worker_id=proposal.worker_id, admin_user=actor)
    proposal.fulfilled_schedule = schedule
    proposal.save(update_fields=['fulfilled_schedule'])
    record(complaint, actor, Event.Kind.ACK,
           f'Đã tạo đơn làm lại {booking.booking_code}. Đang chờ nhân viên nhận lịch.')
    notify(complaint, 'Đã tạo buổi làm lại', f'Đơn làm lại miễn phí {booking.booking_code} đang chờ nhân viên xác nhận.')


def confirm_service(complaint, proposal):
    if not proposal.service_action:
        return
    redo = proposal.service_action == Proposal.ServiceAction.REDO
    schedule = proposal.fulfilled_schedule if redo else complaint.schedule
    require(schedule, 'Cần liên kết buổi thực hiện phương án.')
    if redo:
        Booking.objects.select_for_update().only('id').get(pk=schedule.booking_id)
    schedule = BookingSchedule.objects.select_for_update(of=('self',)).select_related('booking').get(pk=schedule.pk)
    require(schedule.booking.customer_id == complaint.reporter_id
            and schedule.booking.service_id == complaint.booking.service_id
            and schedule.scheduled_start == proposal.scheduled_start,
            'Buổi thực hiện phải khớp khách, dịch vụ và lịch đã xác nhận.')
    require(BookingAssignment.objects.filter(
        schedule=schedule, worker_id=proposal.worker_id, status=BookingAssignment.Status.ACCEPTED,
    ).exists(), 'Nhân viên được đề xuất chưa nhận buổi này.')
    if redo:
        require(schedule.status == BookingSchedule.Status.COMPLETED and schedule.pk != complaint.schedule_id
                and schedule.booking.total_amount == Decimal(0),
                'Buổi làm lại phải hoàn thành và có giá bằng 0.')
    else:
        require(schedule.pk == complaint.schedule_id
                and schedule.status in (BookingSchedule.Status.PENDING, BookingSchedule.Status.IN_PROGRESS,
                                        BookingSchedule.Status.COMPLETED),
                'Cần cập nhật đúng buổi đang khiếu nại.')
    proposal.fulfilled_schedule = schedule


@transaction.atomic
def finish(complaint, proposal, actor, data):
    message = data['message']
    require(proposal.status == Proposal.Status.ACCEPTED, 'Khách chưa đồng ý phương án.')
    if proposal.service_action:
        Booking.objects.select_for_update().only('id').get(pk=complaint.booking_id)
    confirm_service(complaint, proposal)
    require(proposal.refund_scope != Proposal.RefundScope.CASH or data.get('cash_reference'),
            'Nhập mã hoặc căn cứ xác nhận đã hoàn tiền mặt.')
    notes = [message]
    if data.get('recover_worker_earning'):
        apply_outcome(complaint=complaint, admin=actor, outcome=Complaint.Outcome.RECOVER_WORKER_EARNING)
    if proposal.refund_scope == Proposal.RefundScope.CASH:
        record(complaint, actor, Event.Kind.VERIFY, f'Chứng từ tiền mặt: {data["cash_reference"]}', public=False)
        notes.append(f'Đã xác nhận hoàn {fmt_vnd(proposal.refund_amount)} qua phương thức đã thống nhất.')
    elif proposal.refund_scope:
        booking = Booking.objects.select_for_update().get(pk=complaint.booking_id)
        complaint.booking = booking
        amount = proposal.refund_amount
        require(amount and amount <= refund_limit(complaint, proposal.refund_scope),
                'Hạn mức đã thay đổi. Gửi lại phương án để khách xác nhận.')
        prefix = f'refund:schedule:{complaint.schedule_id}:' if proposal.refund_scope != Proposal.RefundScope.BOOKING else 'refund:booking:'
        key = f'{prefix}complaint-proposal:{proposal.pk}'
        refunded = refund_service.refund_booking(
            booking=booking, amount=amount, actor=actor, key=key,
            note=f'Hoàn tiền theo khiếu nại {complaint.code}.',
            reason=f'Phương án khiếu nại {complaint.code}.',
        )
        require(refunded == amount, 'Chưa xác nhận được giao dịch hoàn tiền.')
        proposal.refund_transaction = WalletTransaction.objects.get(idempotency_key=key)
        complaint.outcome = Complaint.Outcome.REFUND_CUSTOMER
        complaint.refund_amount = complaint.customer_delta = refunded
        notes.append(f'Đã hoàn {fmt_vnd(refunded)} vào Ví CleanWise. Mã giao dịch {proposal.refund_transaction.code}.')
    if proposal.voucher_id:
        proposal.issued_voucher = assign_voucher_to_customer(
            voucher_id=proposal.voucher_id, customer_id=complaint.reporter_id,
            admin_user=actor, note=f'Khiếu nại {complaint.code}',
        )
        notes.append(f'Voucher {proposal.voucher.code} đã có trong Voucher của tôi. Chọn voucher khi đặt dịch vụ.')
    proposal.status = Proposal.Status.COMPLETED
    proposal.save(update_fields=['status', 'fulfilled_schedule', 'refund_transaction', 'issued_voucher'])
    close(complaint, actor, Complaint.Status.RESOLVED, '\n'.join(notes))


def close(complaint, actor, status, message):
    complaint.status = status
    complaint.resolution_note = message
    complaint.resolved_by = actor
    complaint.resolved_at = timezone.now()
    complaint.next_update_at = None
    complaint.save()
    record(
        complaint, actor, Event.Kind.CLOSE if status == Complaint.Status.RESOLVED else Event.Kind.REJECT,
        message,
    )


def handle_admin(complaint, actor, data):
    action = data['action']
    message = data.get('message', '')
    proposal = complaint.proposals.first()
    if action == 'CLAIM':
        require(complaint.status in (Complaint.Status.PENDING, Complaint.Status.IN_REVIEW)
                and complaint.assigned_to_id is None, 'Hồ sơ đã có người phụ trách hoặc đã đóng.')
        complaint.assigned_to = actor
        complaint.assigned_at = timezone.now()
        complaint.status = Complaint.Status.IN_REVIEW
        complaint.save(update_fields=['status', 'assigned_to', 'assigned_at'])
        record(complaint, actor, Event.Kind.CLAIM, 'CSKH đã tiếp nhận hồ sơ.')
        return
    require(complaint.assigned_to_id, 'Cần nhận hồ sơ trước khi xử lý.')
    if complaint.assigned_to_id != actor.pk and not actor.is_superuser:
        raise PermissionDenied('Chỉ người phụ trách mới có thể cập nhật hồ sơ.')
    require(complaint.status == Complaint.Status.IN_REVIEW, 'Hồ sơ không còn ở trạng thái đang xem xét.')
    if action in ('COMPLETE', 'SCHEDULE_REDO'):
        require(proposal and proposal.pk == data.get('proposal_id'), 'Phương án đã thay đổi. Tải lại hồ sơ.')
        if action == 'SCHEDULE_REDO':
            schedule_redo(complaint, proposal, actor)
        else:
            finish(complaint, proposal, actor, data)
        return
    if action == 'REQUEST':
        record(complaint, actor, Event.Kind.REQUEST, message)
        notify(complaint, 'Cần bổ sung thông tin khiếu nại', message)
        return
    if action == 'ACK':
        next_update = data.get('next_update_at')
        require(next_update or complaint.next_update_at or complaint.events.filter(kind=Event.Kind.ACK).exists(),
                'Nhập mốc hẹn cập nhật khi phản hồi lần đầu.')
        if next_update:
            require(next_update > timezone.now(), 'Mốc cập nhật phải ở trong tương lai.')
            complaint.next_update_at = next_update
            complaint.save(update_fields=['next_update_at'])
        record(complaint, actor, Event.Kind.ACK, message)
        notify(complaint, 'CSKH đã phản hồi khiếu nại', message)
        return
    if action == 'VERIFY':
        record(complaint, actor, Event.Kind.VERIFY, message, public=False)
        return
    require(complaint.events.filter(kind=Event.Kind.ACK).exists(), 'Gửi xác nhận cho khách trước khi kết luận.')
    require(complaint.events.filter(kind=Event.Kind.VERIFY).exists(), 'Lưu kết quả xác minh trước khi gửi phương án.')
    if proposal and proposal.status in (Proposal.Status.SENT, Proposal.Status.ACCEPTED, Proposal.Status.DECLINED):
        require(proposal.pk == data.get('proposal_id'), 'Phương án đã thay đổi. Tải lại hồ sơ.')
        if proposal.fulfilled_schedule_id:
            require(proposal.fulfilled_schedule.status in (BookingSchedule.Status.CANCELLED, BookingSchedule.Status.MISSED),
                    'Đã có buổi làm lại. Hãy xử lý lịch buổi này trước khi thay đổi phương án.')
        if proposal.status != Proposal.Status.DECLINED:
            proposal.status = Proposal.Status.DECLINED
            proposal.save(update_fields=['status'])
    if action == 'REJECT':
        record(complaint, actor, Event.Kind.VERIFY, data['basis'], public=False)
        close(complaint, actor, Complaint.Status.REJECTED,
              f'{message}\nCăn cứ: {data["basis"]}\n{data["reopen_instructions"]}')
        return
    create_proposal(complaint, data)
    record(complaint, actor, Event.Kind.OFFER, message)
    notify(complaint, 'Có phương án xử lý khiếu nại', 'Mở hồ sơ để xem và phản hồi phương án.')


def handle_customer(complaint, actor, data):
    action = data['action']
    message = data.get('message', '')
    if action == 'REOPEN':
        require(complaint.status == Complaint.Status.REJECTED, 'Chỉ có thể yêu cầu xem xét lại hồ sơ bị từ chối.')
        complaint.status = Complaint.Status.IN_REVIEW
        complaint.resolution_note = None
        complaint.resolved_by = complaint.resolved_at = None
        complaint.save(update_fields=['status', 'resolution_note', 'resolved_by', 'resolved_at'])
        record(complaint, actor, Event.Kind.REOPEN, message)
        return
    require(complaint.status == Complaint.Status.IN_REVIEW, 'Hồ sơ chưa được tiếp nhận hoặc đã đóng.')
    if action == 'REPLY':
        record(complaint, actor, Event.Kind.REPLY, message)
        return
    proposal = complaint.proposals.first()
    require(proposal and proposal.pk == data.get('proposal_id') and proposal.status == Proposal.Status.SENT,
            'Phương án đã thay đổi. Tải lại hồ sơ.')
    accepted = action == 'ACCEPT'
    proposal.status = Proposal.Status.ACCEPTED if accepted else Proposal.Status.DECLINED
    proposal.save(update_fields=['status'])
    record(complaint, actor, Event.Kind.ACCEPT if accepted else Event.Kind.REVISE,
           'Khách đã đồng ý phương án.' if accepted else message)
