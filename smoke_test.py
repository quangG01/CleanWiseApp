"""
Smoke test BE CleanWise. Đặt file này ở thư mục gốc (cạnh manage.py), chạy:
    python smoke_test.py

- Toàn bộ chạy trong 1 transaction rồi ROLLBACK -> không để lại dữ liệu trong DB dev.
- Cần trong DB dev có sẵn: 1 khách có địa chỉ active, 1 Service active, 1 ADMIN, 1 WORKER.
- Đã chặn gửi push/realtime thật.
- Nếu settings của bạn không phải core.settings.dev, đặt biến môi trường DJANGO_SETTINGS_MODULE.
"""
import os
import random
import sys
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.dev')
django.setup()

from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import Http404
from django.utils import timezone
from rest_framework import serializers as drf

from apps.addresses.models import CustomerAddress
from apps.bookings import booking_service, expiry_service
from apps.bookings.models import Booking, BookingSchedule
from apps.complaints.models import Complaint, ComplaintIssueType
from apps.complaints.serializers import ComplaintResolveSerializer
from apps.notifications import services as notif
from apps.payments.models import Payment
from apps.payments.webhook_service import handle_payos_webhook
from apps.services.models import Service
from apps.wallets import earning_service, refund_service, wallet_service
from apps.wallets.models import WalletTransaction, WorkerEarning
from apps.worker import assignment_service
from apps.worker.models import BookingAssignment

# Chặn push / realtime thật
notif.send_push_to_user = lambda *a, **k: None
notif.push_unread_count = lambda *a, **k: None

User = get_user_model()
D = Decimal
results = []


class _Rollback(Exception):
    pass


def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('PASS' if cond else 'FAIL'), '-', name, '' if cond else f'   [{detail}]')


def bal(user):
    w, _ = wallet_service.get_or_create_wallet(user)
    w.refresh_from_db()
    return w.balance


def raises(fn):
    try:
        with transaction.atomic():
            fn()
    except (drf.ValidationError, Http404):
        return True
    return False


def reload(obj):
    obj.refresh_from_db()
    return obj


def section(title):
    print(f'\n=== {title} ===')


def run():
    now = timezone.now()

    addr = CustomerAddress.objects.filter(is_active=True, customer__role='CUSTOMER').first()
    service = Service.objects.filter(is_active=True).first()
    admin = User.objects.filter(role='ADMIN', is_active=True).first()
    worker = User.objects.filter(role='WORKER', is_active=True).first()
    assert addr and service and admin, 'Thiếu dữ liệu: cần khách có địa chỉ, Service, ADMIN.'
    C = addr.customer

    def mk_booking(sessions=1, total=200000, method=Payment.Method.BANK_TRANSFER, paid=True):
        total = D(total)
        code = 'T-' + uuid.uuid4().hex[:10].upper()
        b = Booking.objects.create(
            booking_code=code, customer=C, service=service, service_data={}, address=addr,
            status=Booking.Status.PENDING,
            payment_status=Booking.PaymentStatus.PAID if paid else Booking.PaymentStatus.UNPAID,
            subtotal_amount=total, discount_amount=0, total_amount=total,
            price_breakdown={'unit_price': str(total / sessions), 'sessions_count': sessions},
        )
        for i in range(1, sessions + 1):
            start = now + timedelta(days=3 + i)
            BookingSchedule.objects.create(
                booking=b, sequence_no=i, scheduled_start=start, scheduled_end=start + timedelta(hours=2),
            )
        Payment.objects.create(
            customer=C, booking=b, amount=total, method=method,
            status=Payment.Status.SUCCESS if paid else Payment.Status.PENDING,
            paid_at=now if paid else None, order_code=random.randint(10**9, 10**12),
        )
        return b

    def hook(payment, amount):
        return SimpleNamespace(order_code=payment.order_code, amount=int(amount), reference='R' + uuid.uuid4().hex[:12])

    # ------------------------------------------------------------------ PHẦN MỚI
    section('M1. Admin điều chỉnh số dư ví')
    b0 = bal(C)
    tx = wallet_service.admin_adjust_wallet(user=C, amount=D(50000), direction='CREDIT', reason='test', admin_user=admin)
    check('CREDIT +50.000', bal(C) == b0 + 50000, bal(C))
    check('direction=CREDIT, created_by=admin', tx.direction == 'CREDIT' and tx.created_by_id == admin.id)
    wallet_service.admin_adjust_wallet(user=C, amount=D(20000), direction='DEBIT', reason='test', admin_user=admin)
    check('DEBIT -20.000', bal(C) == b0 + 30000, bal(C))
    check('DEBIT quá số dư bị chặn', raises(lambda: wallet_service.admin_adjust_wallet(
        user=C, amount=D(999999999), direction='DEBIT', reason='x', admin_user=admin)))
    check('Thiếu lý do bị chặn', raises(lambda: wallet_service.admin_adjust_wallet(
        user=C, amount=D(1000), direction='CREDIT', reason='  ', admin_user=admin)))

    section('M2. Trả bằng ví (debit)')
    b0 = bal(C)
    t = wallet_service.debit_wallet(user=C, amount=D(10000), type=WalletTransaction.Type.PAYMENT)
    check('Trừ ví, direction=DEBIT', bal(C) == b0 - 10000 and t.direction == 'DEBIT')
    check('Thiếu tiền bị chặn', raises(lambda: wallet_service.debit_wallet(user=C, amount=D(999999999))))

    section('M3. Khách hủy theo buổi')
    b = mk_booking(sessions=4, total=400000)
    s2 = b.schedules.get(sequence_no=2)
    b0 = bal(C)
    booking_service.cancel_schedule_by_customer(schedule_id=s2.id, customer=C, reason='t')
    reload(b); reload(s2)
    check('Hủy buổi 2: ví +1/4', bal(C) == b0 + 100000, bal(C) - b0)
    check('Buổi 2 CANCELLED, đơn vẫn PENDING', s2.status == 'CANCELLED' and b.status == 'PENDING', (s2.status, b.status))
    check('refunded_amount = 100.000', b.refunded_amount == 100000, b.refunded_amount)
    check('Hủy cả đơn nhiều buổi (đã trả) bị chặn', raises(lambda: booking_service.cancel_booking(
        booking_id=b.id, customer=C, reason='t')))

    b1 = mk_booking(sessions=1, total=200000)
    b0 = bal(C)
    booking_service.cancel_schedule_by_customer(schedule_id=b1.schedules.first().id, customer=C, reason='t')
    reload(b1)
    check('Đơn 1 buổi: đơn CANCELLED, hoàn đủ', b1.status == 'CANCELLED' and bal(C) == b0 + 200000, (b1.status, bal(C) - b0))
    check('Đơn REFUNDED', b1.payment_status == 'REFUNDED', b1.payment_status)

    b3 = mk_booking(sessions=3, total=100000)  # 33.333 x 2 + 33.334
    b0 = bal(C)
    for sc in list(b3.schedules.order_by('sequence_no')):
        booking_service.cancel_schedule_by_customer(schedule_id=sc.id, customer=C, reason='t')
    reload(b3)
    check('Hủy hết 3 buổi: tổng hoàn đúng 100.000 (không lệch làm tròn)', bal(C) == b0 + 100000, bal(C) - b0)
    check('Đơn CANCELLED + REFUNDED', b3.status == 'CANCELLED' and b3.payment_status == 'REFUNDED', (b3.status, b3.payment_status))

    section('M4. Admin hoàn tiền thủ công')
    b = mk_booking(sessions=1, total=300000)
    b0 = bal(C)
    refund_service.admin_refund_booking(booking_id=b.id, admin_user=admin, reason='t', amount=D(100000))
    reload(b)
    check('Hoàn 100.000 lần 1', bal(C) == b0 + 100000 and b.refunded_amount == 100000, bal(C) - b0)
    check('Hoàn vượt phần còn lại bị chặn', raises(lambda: refund_service.admin_refund_booking(
        booking_id=b.id, admin_user=admin, reason='t', amount=D(250000))))
    refund_service.admin_refund_booking(booking_id=b.id, admin_user=admin, reason='t')
    reload(b)
    check('Hoàn phần còn lại -> REFUNDED, tổng = total', b.payment_status == 'REFUNDED' and b.refunded_amount == 300000,
          (b.payment_status, b.refunded_amount))
    bc = mk_booking(sessions=1, total=100000, method=Payment.Method.CASH, paid=True)
    check('Đơn tiền mặt không hoàn qua ví', raises(lambda: refund_service.admin_refund_booking(
        booking_id=bc.id, admin_user=admin, reason='t')))

    section('M5. Khiếu nại RESOLVED kèm hoàn tiền')
    b = mk_booking(sessions=1, total=200000)
    it = ComplaintIssueType.objects.create(code='T_' + uuid.uuid4().hex[:8], name='test')
    cp = Complaint.objects.create(customer=C, booking=b, issue_type=it, stage=Complaint.Stage.AFTER_SERVICE, content='x')
    ctx = {'request': SimpleNamespace(user=admin)}
    b0 = bal(C)
    ser = ComplaintResolveSerializer(cp, data={'status': 'RESOLVED', 'resolution_note': 'ok', 'refund_amount': '50000'}, context=ctx)
    ser.is_valid(raise_exception=True)
    ser.save()
    reload(cp)
    check('Resolve + hoàn 50.000', bal(C) == b0 + 50000 and cp.refund_amount == 50000, (bal(C) - b0, cp.refund_amount))
    ser2 = ComplaintResolveSerializer(cp, data={'status': 'RESOLVED', 'refund_amount': '50000'}, context=ctx)
    check('Xử lý lại khiếu nại đã đóng bị chặn', not ser2.is_valid())

    # ------------------------------------------------------------------ BUG 1-18
    section('Bug 1,2,3: webhook đến sau khi đơn hủy')
    b = mk_booking(sessions=1, total=200000, paid=False)
    p = b.payments.first()
    booking_service.cancel_booking(booking_id=b.id, customer=C, reason='t')
    b0 = bal(C)
    handle_payos_webhook(hook(p, 200000))
    reload(p)
    check('Tiền đến muộn -> ví +200.000, Payment REFUNDED', bal(C) == b0 + 200000 and p.status == 'REFUNDED', (bal(C) - b0, p.status))
    handle_payos_webhook(hook(p, 200000))
    check('Webhook lặp -> ví không tăng thêm', bal(C) == b0 + 200000, bal(C) - b0)

    section('Bug 3: refund_booking idempotent theo key')
    b = mk_booking(sessions=1, total=200000)
    b0 = bal(C)
    refund_service.refund_booking(booking=b, key='k:' + b.booking_code, note='t', amount=D(50000))
    refund_service.refund_booking(booking=reload(b), key='k:' + b.booking_code, note='t', amount=D(50000))
    check('Gọi 2 lần cùng key -> chỉ hoàn 1 lần', bal(C) == b0 + 50000, bal(C) - b0)

    section('Bug 10: chuyển thiếu / dư / đủ')
    b = mk_booking(sessions=1, total=200000, paid=False)
    p = b.payments.first()
    b0 = bal(C)
    handle_payos_webhook(hook(p, 150000))
    reload(b)
    check('Thiếu: hoàn 150.000 vào ví, đơn CANCELLED', bal(C) == b0 + 150000 and b.status == 'CANCELLED', (bal(C) - b0, b.status))

    b = mk_booking(sessions=1, total=200000, paid=False)
    p = b.payments.first()
    b0 = bal(C)
    handle_payos_webhook(hook(p, 250000))
    reload(b)
    check('Dư: đơn PAID, phần dư 50.000 vào ví', b.payment_status == 'PAID' and bal(C) == b0 + 50000, (b.payment_status, bal(C) - b0))

    b = mk_booking(sessions=1, total=200000, paid=False)
    p = b.payments.first()
    b0 = bal(C)
    handle_payos_webhook(hook(p, 200000))
    reload(b)
    check('Đủ: đơn PAID, ví không đổi', b.payment_status == 'PAID' and bal(C) == b0, (b.payment_status, bal(C) - b0))

    section('Bug 8: đơn online quá hạn thanh toán')
    b = mk_booking(sessions=1, total=200000, paid=False)
    Booking.objects.filter(pk=b.pk).update(created_at=now - timedelta(minutes=31))
    expiry_service.expire_unpaid_bookings()
    reload(b)
    check('Quá 30 phút -> CANCELLED', b.status == 'CANCELLED', b.status)

    section('Bug 6: buổi không ai nhận -> MISSED + hoàn 1/4')
    b = mk_booking(sessions=4, total=400000)
    s1 = b.schedules.get(sequence_no=1)
    BookingSchedule.objects.filter(pk=s1.pk).update(scheduled_start=now - timedelta(minutes=5), scheduled_end=now + timedelta(hours=1))
    b0 = bal(C)
    assignment_service.expire_unclaimed_schedules()
    reload(b); reload(s1)
    check('Buổi 1 MISSED', s1.status == 'MISSED', s1.status)
    check('Ví khách +100.000', bal(C) == b0 + 100000, bal(C) - b0)
    check('Đơn còn mở (chưa FAILED)', b.status in ('PENDING', 'ASSIGNED'), b.status)

    section('Bug 2/6: đơn 1 buổi không ai nhận -> FAILED + hoàn đủ')
    b = mk_booking(sessions=1, total=200000)
    s = b.schedules.first()
    BookingSchedule.objects.filter(pk=s.pk).update(scheduled_start=now - timedelta(minutes=5), scheduled_end=now + timedelta(hours=1))
    b0 = bal(C)
    assignment_service.expire_unclaimed_schedules()
    reload(b)
    check('Đơn FAILED, hoàn đủ 200.000', b.status == 'FAILED' and bal(C) == b0 + 200000, (b.status, bal(C) - b0))
    check('payment_status REFUNDED', b.payment_status == 'REFUNDED', b.payment_status)

    section('Bug 11: lương tính trên giá trước voucher')
    b = mk_booking(sessions=1, total=200000)
    Booking.objects.filter(pk=b.pk).update(
        subtotal_amount=250000, total_amount=200000, price_breakdown={'unit_price': '250000', 'sessions_count': 1})
    reload(b)
    check('gross = 250.000 (không phải 200.000)', earning_service.calculate_gross_amount(b.schedules.first(), b) == 250000)

    if worker:
        W = worker
        section('Bug 4: khách hủy đơn tiền mặt -> hoàn hoa hồng giữ chỗ')
        wallet_service.credit_wallet(user=W, amount=D(1000000), type=WalletTransaction.Type.ADJUSTMENT, note='seed')
        b = mk_booking(sessions=1, total=200000, method=Payment.Method.CASH, paid=False)
        s = b.schedules.first()
        a = BookingAssignment.objects.create(
            schedule=s, worker=W, assigned_method=BookingAssignment.AssignedMethod.MANUAL,
            status=BookingAssignment.Status.ACCEPTED, assigned_at=now, responded_at=now)
        w0 = bal(W)
        earning_service.reserve_cash_commission(schedule=s, booking=b, worker=W, assignment=a)
        check('Giữ chỗ hoa hồng 20.000', bal(W) == w0 - 20000, w0 - bal(W))
        booking_service.cancel_booking(booking_id=b.id, customer=C, reason='t')
        reload(a)
        check('Hoa hồng được hoàn lại cho nhân viên', bal(W) == w0, w0 - bal(W))
        check('Assignment CANCELLED', a.status == 'CANCELLED', a.status)

        section('Bug 5: nhân viên không check-in -> hoàn hoa hồng')
        b = mk_booking(sessions=1, total=200000, method=Payment.Method.CASH, paid=False)
        s = b.schedules.first()
        a = BookingAssignment.objects.create(
            schedule=s, worker=W, assigned_method=BookingAssignment.AssignedMethod.MANUAL,
            status=BookingAssignment.Status.ACCEPTED, assigned_at=now, responded_at=now)
        w0 = bal(W)
        earning_service.reserve_cash_commission(schedule=s, booking=b, worker=W, assignment=a)
        BookingSchedule.objects.filter(pk=s.pk).update(scheduled_start=now - timedelta(hours=2), scheduled_end=now - timedelta(hours=1))
        Booking.objects.filter(pk=b.pk).update(status='ASSIGNED')
        assignment_service.handle_missed_checkins()
        reload(a)
        check('Assignment bị gỡ', a.status == 'CANCELLED', a.status)
        check('Hoa hồng được hoàn lại', bal(W) == w0, w0 - bal(W))

        section('Bug 12: thu nhập online giữ 24 giờ')
        b = mk_booking(sessions=1, total=200000)
        s = b.schedules.first()
        BookingSchedule.objects.filter(pk=s.pk).update(status='COMPLETED', actual_start=now - timedelta(hours=2), actual_end=now)
        reload(s)
        e = earning_service.record_schedule_earning(schedule=s, booking=b, worker=W)
        check('Ghi sổ ONLINE, worker nhận 180.000', e.payment_method == 'ONLINE' and e.worker_amount == 180000, (e.payment_method, e.worker_amount))
        earning_service.release_held_earnings()
        reload(e)
        check('Chưa đủ 24 giờ -> chưa vào ví', e.wallet_credited_at is None)
        WorkerEarning.objects.filter(pk=e.pk).update(completed_at=now - timedelta(hours=25))
        earning_service.release_held_earnings()
        reload(e)
        key = f'earning:{e.id}'
        check('Qua 24 giờ -> vào ví', e.wallet_credited_at is not None and WalletTransaction.objects.filter(idempotency_key=key).count() == 1)
        earning_service.release_held_earnings()
        check('Chạy lại không cộng thêm', WalletTransaction.objects.filter(idempotency_key=key).count() == 1)

        section('Bug 13: khiếu nại đang mở chặn giải ngân')
        b = mk_booking(sessions=1, total=200000)
        s = b.schedules.first()
        BookingSchedule.objects.filter(pk=s.pk).update(status='COMPLETED', actual_start=now - timedelta(hours=2), actual_end=now)
        reload(s)
        e = earning_service.record_schedule_earning(schedule=s, booking=b, worker=W)
        cp = Complaint.objects.create(customer=C, booking=b, schedule=s, issue_type=it, stage=Complaint.Stage.AFTER_SERVICE)
        WorkerEarning.objects.filter(pk=e.pk).update(completed_at=now - timedelta(hours=25))
        earning_service.release_held_earnings()
        reload(e)
        check('Có khiếu nại PENDING -> không giải ngân', e.wallet_credited_at is None)
        Complaint.objects.filter(pk=cp.pk).update(status='RESOLVED')
        earning_service.release_held_earnings()
        reload(e)
        check('Khiếu nại đóng -> giải ngân', e.wallet_credited_at is not None)
    else:
        print('\n(Bỏ qua bug 4, 5, 12, 13: DB dev chưa có WORKER)')

    print('\n' + '=' * 50)
    print(f'TỔNG: {sum(results)}/{len(results)} PASS')
    print('Chưa test bằng script (test qua API/Postman): bug 9 (payment-link), 14 (upload ảnh), 15, 16, 17, 18 (thông báo).')


try:
    with transaction.atomic():
        run()
        raise _Rollback()
except _Rollback:
    print('Đã ROLLBACK, DB dev không bị thay đổi.')
sys.exit(0 if all(results) else 1)