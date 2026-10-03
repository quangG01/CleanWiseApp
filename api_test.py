"""
Test API CleanWise bằng DRF APIClient (đi qua view + route + serializer + permission thật).
Đặt cạnh manage.py, chạy:   python api_test.py

- Chạy trong 1 transaction rồi ROLLBACK -> không để lại dữ liệu trong DB dev.
- Đã chặn push/realtime, tắt throttle, mock PayOS (không gọi mạng thật).
- Cần DB dev có sẵn: khách có địa chỉ active, Service active, ADMIN, WORKER.
- (Tuỳ chọn) test đặt đơn bằng ví: tạo file create_payload.json cạnh script, nội dung là body
  POST /customer/bookings/ lấy từ tab Network của FE (BỎ payment_method; ngày giờ phải ở tương lai).
- Nếu settings không phải core.settings.dev, đặt biến môi trường DJANGO_SETTINGS_MODULE.
"""
import base64
import json
import os
import random
import re
import sys
import time
import traceback
import uuid
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.dev')
django.setup()

from django.conf import settings

settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ['testserver']
settings.SECURE_SSL_REDIRECT = False

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.urls import URLResolver, get_resolver
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle, SimpleRateThrottle

from apps.addresses.models import CustomerAddress
from apps.bookings.models import Booking, BookingSchedule
from apps.common.redis_client import get_redis_client
from apps.complaints.models import Complaint, ComplaintAttachment, ComplaintIssueType
from apps.notifications import services as notif
from apps.payments import payment_link_service as pls
from apps.payments.models import Payment
from apps.services.models import Service
from apps.wallets import wallet_service
from apps.wallets.models import Wallet, WalletTransaction

# ---- chặn tác dụng phụ ra ngoài
notif.send_push_to_user = lambda *a, **k: None
notif.push_unread_count = lambda *a, **k: None
SimpleRateThrottle.allow_request = lambda self, request, view: True
ScopedRateThrottle.allow_request = lambda self, request, view: True

User = get_user_model()
D = Decimal
results = []
TINY_PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
)


class _Rollback(Exception):
    pass


# ---------------------------------------------------------------- helpers
def _walk(patterns, prefix=''):
    for p in patterns:
        if isinstance(p, URLResolver):
            yield from _walk(p.url_patterns, prefix + str(p.pattern))
        else:
            yield prefix + str(p.pattern), p


def find_url(view_name, **kw):
    """Tìm URL thật theo tên class view, khỏi đoán prefix."""
    for route, p in _walk(get_resolver().url_patterns):
        vc = getattr(p.callback, 'view_class', None)
        if vc and vc.__name__ == view_name:
            url = '/' + route
            for k, v in kw.items():
                url = re.sub(r'<(?:\w+:)?%s>' % k, str(v), url)
            return url
    raise LookupError(view_name)


def call(user, method, url, data=None, fmt='json', **extra):
    c = APIClient()
    if user:
        c.force_authenticate(user=user)
    if method == 'get':
        return c.get(url, data, **extra)
    return getattr(c, method)(url, data, format=fmt, **extra)


def body(resp):
    d = getattr(resp, 'data', None)
    return d.get('data') if isinstance(d, dict) and 'data' in d else d


def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('PASS' if cond else 'FAIL'), '-', name, '' if cond else f'   [{detail}]')


def bal(user):
    w, _ = wallet_service.get_or_create_wallet(user)
    w.refresh_from_db()
    return w.balance


def reload(obj):
    obj.refresh_from_db()
    return obj


def section(title, fn):
    print(f'\n=== {title} ===')
    try:
        with transaction.atomic():
            fn()
    except Exception:
        results.append(False)
        print('FAIL - lỗi ngoài dự kiến:')
        traceback.print_exc(limit=4)


# ---------------------------------------------------------------- dữ liệu nền
NOW = timezone.now()
ADDR = CustomerAddress.objects.filter(is_active=True, customer__role='CUSTOMER').first()
SERVICE = Service.objects.filter(is_active=True).first()
ADMIN = User.objects.filter(role='ADMIN', is_active=True).first()
WORKER = User.objects.filter(role='WORKER', is_active=True).first()
assert ADDR and SERVICE and ADMIN, 'Thiếu dữ liệu: cần khách có địa chỉ, Service, ADMIN.'
C = ADDR.customer
OTHER = User.objects.filter(role='CUSTOMER', is_active=True).exclude(pk=C.pk).first()


def mk_booking(sessions=1, total=200000, method=Payment.Method.BANK_TRANSFER, paid=True):
    total = D(total)
    code = 'T-' + uuid.uuid4().hex[:10].upper()
    b = Booking.objects.create(
        booking_code=code, customer=C, service=SERVICE, service_data={}, address=ADDR,
        status=Booking.Status.PENDING,
        payment_status=Booking.PaymentStatus.PAID if paid else Booking.PaymentStatus.UNPAID,
        subtotal_amount=total, discount_amount=0, total_amount=total,
        price_breakdown={'unit_price': str(total / sessions), 'sessions_count': sessions},
    )
    for i in range(1, sessions + 1):
        start = NOW + timedelta(days=3 + i)
        BookingSchedule.objects.create(
            booking=b, sequence_no=i, scheduled_start=start, scheduled_end=start + timedelta(hours=2))
    Payment.objects.create(
        customer=C, booking=b, amount=total, method=method,
        status=Payment.Status.SUCCESS if paid else Payment.Status.PENDING,
        paid_at=NOW if paid else None, order_code=random.randint(10**9, 10**12))
    return b


# ---------------------------------------------------------------- các nhóm test
def t_urls():
    for name in ['BookingListCreateView', 'BookingDetailView', 'BookingCancelView', 'ScheduleCancelView',
                 'BookingPaymentLinkView', 'WalletDetailView', 'WalletTransactionListView',
                 'AdminBookingRefundView', 'AdminWalletAdjustView', 'AdminUserWalletView',
                 'ComplaintResolveView', 'ComplaintAttachmentUploadView', 'ComplaintDetailView',
                 'WorkerWalletTransactionListView', 'WorkerEarningSummaryView']:
        try:
            kw = {k: 1 for k in re.findall(r'<(?:\w+:)?(\w+)>', find_url(name))}
            print(f'  {name:36s} {find_url(name, **kw)}')
            results.append(True)
        except LookupError:
            check(f'Route cho {name} tồn tại', False, 'chưa đăng ký route / sai tên view')


def t_wallet_order():
    path = 'create_payload.json'
    if not os.path.exists(path):
        print('  (bỏ qua: không có create_payload.json)')
        return
    payload = json.load(open(path, encoding='utf-8'))
    payload['payment_method'] = 'WALLET'
    cust = CustomerAddress.objects.get(pk=payload['address_id']).customer
    url = find_url('BookingListCreateView')

    wallet_service.get_or_create_wallet(cust)
    Wallet.objects.filter(user=cust).update(balance=0)
    n0 = Booking.objects.filter(customer=cust).count()
    r = call(cust, 'post', url, payload)
    check('Ví 0đ -> 400', r.status_code == 400, (r.status_code, getattr(r, 'data', None)))
    check('Không tạo đơn khi thiếu tiền', Booking.objects.filter(customer=cust).count() == n0)

    wallet_service.credit_wallet(user=cust, amount=D(100000000), type=WalletTransaction.Type.ADJUSTMENT, note='seed')
    b0 = bal(cust)
    r = call(cust, 'post', url, payload)
    check('Ví đủ -> 201', r.status_code == 201, (r.status_code, getattr(r, 'data', None)))
    if r.status_code != 201:
        return
    bk = Booking.objects.get(pk=body(r)['id'])
    check('Đơn PAID ngay', bk.payment_status == 'PAID', bk.payment_status)
    check('Ví trừ đúng total_amount', bal(cust) == b0 - bk.total_amount, (b0 - bal(cust), bk.total_amount))
    tx = WalletTransaction.objects.filter(booking=bk, type='PAYMENT').first()
    check('Có giao dịch PAYMENT / DEBIT', tx is not None and tx.direction == 'DEBIT')

    sc = bk.schedules.order_by('sequence_no').first()
    before = bal(cust)
    r = call(cust, 'post', find_url('ScheduleCancelView', pk=sc.id), {'reason': 'test'})
    check('Hủy buổi qua API -> 200', r.status_code == 200, (r.status_code, getattr(r, 'data', None)))
    check('Ví khách được hoàn tiền', bal(cust) > before, bal(cust) - before)


def t_cancel_schedule_api():
    b = mk_booking(sessions=4, total=400000)
    s2 = b.schedules.get(sequence_no=2)
    url = find_url('ScheduleCancelView', pk=s2.id)

    r = call(C, 'post', url, {})
    check('Thiếu reason -> 400', r.status_code == 400, r.status_code)
    if OTHER:
        r = call(OTHER, 'post', url, {'reason': 't'})
        check('Khách khác hủy buổi của người ta -> 404', r.status_code == 404, r.status_code)
    r = call(WORKER or ADMIN, 'post', url, {'reason': 't'})
    check('Worker/Admin gọi API khách -> 403', r.status_code == 403, r.status_code)

    b0 = bal(C)
    r = call(C, 'post', url, {'reason': 'test'})
    check('Hủy buổi 2 -> 200', r.status_code == 200, (r.status_code, getattr(r, 'data', None)))
    d = body(r) or {}
    check('Response đủ field', {'schedule_id', 'schedule_status', 'booking_status', 'payment_status',
                                'refunded_amount'} <= set(d.keys()), list(d.keys()))
    check('Ví +100.000', bal(C) == b0 + 100000, bal(C) - b0)
    check('refunded_amount = 100000', D(str(d.get('refunded_amount', 0))) == 100000, d.get('refunded_amount'))

    r = call(C, 'post', url, {'reason': 'test'})
    check('Hủy lại buổi đã hủy -> 400', r.status_code == 400, r.status_code)
    r = call(C, 'post', find_url('BookingCancelView', pk=b.id), {'reason': 't'})
    check('Hủy cả đơn nhiều buổi đã trả -> 400', r.status_code == 400, r.status_code)

    r = call(C, 'get', find_url('BookingDetailView', pk=b.id))
    d = body(r) or {}
    check('Chi tiết đơn có refunded_amount / cancelled_at / cancel_reason',
          {'refunded_amount', 'cancelled_at', 'cancel_reason'} <= set(d.keys()), list(d.keys()))
    check('Chi tiết đơn có buổi CANCELLED',
          any(s.get('status') == 'CANCELLED' for s in d.get('schedules', [])))

    bu = mk_booking(sessions=2, total=200000, paid=False)
    r = call(C, 'post', find_url('BookingCancelView', pk=bu.id), {'reason': 't'})
    check('Đơn online chưa trả nhiều buổi: hủy cả đơn được -> 200', r.status_code == 200, (r.status_code, getattr(r, 'data', None)))


def t_customer_wallet_api():
    wallet_service.credit_wallet(user=C, amount=D(10000), type=WalletTransaction.Type.ADJUSTMENT, note='seed')
    r = call(C, 'get', find_url('WalletDetailView'))
    check('GET ví khách -> 200 có balance', r.status_code == 200 and 'balance' in (body(r) or {}), r.status_code)
    r = call(C, 'get', find_url('WalletTransactionListView'))
    res = (body(r) or {}).get('results', [])
    check('Lịch sử giao dịch có field direction', r.status_code == 200 and res and 'direction' in res[0],
          res[:1])
    r = call(WORKER or ADMIN, 'get', find_url('WalletDetailView'))
    check('Worker/Admin gọi ví khách -> 403', r.status_code == 403, r.status_code)


def t_admin_api():
    b = mk_booking(sessions=1, total=300000)
    url = find_url('AdminBookingRefundView', pk=b.id)

    r = call(C, 'post', url, {'reason': 't', 'amount': '100000'})
    check('Khách gọi API admin refund -> 403', r.status_code == 403, r.status_code)
    r = call(ADMIN, 'post', url, {'amount': '100000'})
    check('Thiếu reason -> 400', r.status_code == 400, r.status_code)

    b0 = bal(C)
    r = call(ADMIN, 'post', url, {'reason': 'test', 'amount': '100000'})
    d = body(r) or {}
    check('Admin hoàn 100.000 -> 200', r.status_code == 200, (r.status_code, getattr(r, 'data', None)))
    check('Ví khách +100.000', bal(C) == b0 + 100000, bal(C) - b0)
    check('Response có refunded_amount / payment_status', {'refunded_amount', 'payment_status'} <= set(d.keys()),
          list(d.keys()))
    r = call(ADMIN, 'post', url, {'reason': 'test', 'amount': '999999'})
    check('Hoàn vượt phần còn lại -> 400', r.status_code == 400, r.status_code)
    r = call(ADMIN, 'post', find_url('AdminBookingRefundView', pk=999999999), {'reason': 't'})
    check('Đơn không tồn tại -> 404', r.status_code == 404, r.status_code)
    bc = mk_booking(sessions=1, total=100000, method=Payment.Method.CASH, paid=True)
    r = call(ADMIN, 'post', find_url('AdminBookingRefundView', pk=bc.id), {'reason': 't'})
    check('Đơn tiền mặt -> 400', r.status_code == 400, r.status_code)

    adj = find_url('AdminWalletAdjustView')
    b0 = bal(C)
    r = call(ADMIN, 'post', adj, {'user_id': C.id, 'direction': 'CREDIT', 'amount': '50000', 'reason': 'thưởng'})
    check('Điều chỉnh CREDIT -> 201', r.status_code == 201 and bal(C) == b0 + 50000, (r.status_code, bal(C) - b0))
    check('Response có direction=CREDIT', (body(r) or {}).get('direction') == 'CREDIT', body(r))
    r = call(ADMIN, 'post', adj, {'user_id': C.id, 'direction': 'DEBIT', 'amount': '999999999', 'reason': 'x'})
    check('DEBIT quá số dư -> 400', r.status_code == 400, r.status_code)
    r = call(ADMIN, 'post', adj, {'user_id': C.id, 'direction': 'CREDIT', 'amount': '1000'})
    check('Thiếu reason -> 400', r.status_code == 400, r.status_code)
    r = call(ADMIN, 'post', adj, {'user_id': ADMIN.id, 'direction': 'CREDIT', 'amount': '1000', 'reason': 'x'})
    check('Điều chỉnh ví admin -> 400', r.status_code == 400, r.status_code)
    r = call(C, 'post', adj, {'user_id': C.id, 'direction': 'CREDIT', 'amount': '1000', 'reason': 'x'})
    check('Khách tự cộng ví -> 403', r.status_code == 403, r.status_code)

    r = call(ADMIN, 'get', find_url('AdminUserWalletView', user_id=C.id))
    d = body(r) or {}
    check('Admin xem ví user -> 200', r.status_code == 200 and {'balance', 'transactions', 'role'} <= set(d.keys()),
          (r.status_code, list(d.keys())))
    r = call(C, 'get', find_url('AdminUserWalletView', user_id=C.id))
    check('Khách xem ví qua API admin -> 403', r.status_code == 403, r.status_code)

    if get_redis_client() is None:
        print('  (bỏ qua test Idempotency-Key: không có Redis)')
        return
    key = uuid.uuid4().hex
    b0 = bal(C)
    r1 = call(ADMIN, 'post', adj, {'user_id': C.id, 'direction': 'CREDIT', 'amount': '7000', 'reason': 'idem'},
              HTTP_IDEMPOTENCY_KEY=key)
    r2 = call(ADMIN, 'post', adj, {'user_id': C.id, 'direction': 'CREDIT', 'amount': '7000', 'reason': 'idem'},
              HTTP_IDEMPOTENCY_KEY=key)
    check('Idempotency-Key: gọi 2 lần chỉ cộng 1 lần', bal(C) == b0 + 7000 and r1.status_code == r2.status_code == 201,
          (bal(C) - b0, r1.status_code, r2.status_code))


def t_complaint_api():
    b = mk_booking(sessions=1, total=200000)
    it = ComplaintIssueType.objects.create(code='T_' + uuid.uuid4().hex[:8], name='test')
    cp = Complaint.objects.create(customer=C, booking=b, issue_type=it,
                                  stage=Complaint.Stage.AFTER_SERVICE, content='x')
    url = find_url('ComplaintResolveView', pk=cp.id)

    r = call(C, 'post', url, {'status': 'RESOLVED'})
    check('Khách tự resolve khiếu nại -> 403', r.status_code == 403, r.status_code)
    r = call(ADMIN, 'post', url, {'status': 'IN_REVIEW', 'refund_amount': '1000'})
    check('refund_amount khi chưa RESOLVED -> 400', r.status_code == 400, r.status_code)

    b0 = bal(C)
    r = call(ADMIN, 'post', url, {'status': 'RESOLVED', 'resolution_note': 'ok', 'refund_amount': '50000'})
    check('Resolve + hoàn 50.000 -> 200', r.status_code == 200 and bal(C) == b0 + 50000,
          (r.status_code, bal(C) - b0, getattr(r, 'data', None)))
    check('Response có refund_amount = 50000',
          'refund_amount' in (r.data or {}) and D(str(r.data['refund_amount'])) == 50000, getattr(r, 'data', None))
    r = call(ADMIN, 'post', url, {'status': 'RESOLVED', 'refund_amount': '50000'})
    check('Resolve lại khiếu nại đã đóng -> 400 (không hoàn lần 2)', r.status_code == 400 and bal(C) == b0 + 50000,
          (r.status_code, bal(C) - b0))

    r = call(C, 'get', find_url('ComplaintDetailView', pk=cp.id))
    check('Khách xem chi tiết có refund_amount', r.status_code == 200 and 'refund_amount' in (r.data or {}), r.status_code)


def t_attachment_api():
    b = mk_booking(sessions=1, total=200000)
    it = ComplaintIssueType.objects.create(code='T_' + uuid.uuid4().hex[:8], name='test')
    cp = Complaint.objects.create(customer=C, booking=b, issue_type=it,
                                  stage=Complaint.Stage.AFTER_SERVICE, content='x')
    url = find_url('ComplaintAttachmentUploadView', pk=cp.id)

    r = call(C, 'post', url, {'file': SimpleUploadedFile('a.pdf', b'%PDF-1.4', content_type='application/pdf')},
             fmt='multipart')
    check('Upload PDF -> 400', r.status_code == 400, r.status_code)
    big = SimpleUploadedFile('big.png', TINY_PNG + b'0' * (6 * 1024 * 1024), content_type='image/png')
    r = call(C, 'post', url, {'file': big}, fmt='multipart')
    check('Upload ảnh > 5MB -> 400', r.status_code == 400, r.status_code)

    for i in range(5):  # tạo sẵn 5 bản ghi (không ghi file thật)
        ComplaintAttachment.objects.create(complaint=cp, file=f'complaints/test_{i}.png', file_type='image/png')
    r = call(C, 'post', url, {'file': SimpleUploadedFile('ok.png', TINY_PNG, content_type='image/png')},
             fmt='multipart')
    check('Ảnh thứ 6 -> 400', r.status_code == 400, r.status_code)

    Complaint.objects.filter(pk=cp.pk).update(status='RESOLVED')
    ComplaintAttachment.objects.filter(complaint=cp).delete()
    r = call(C, 'post', url, {'file': SimpleUploadedFile('ok.png', TINY_PNG, content_type='image/png')},
             fmt='multipart')
    check('Khiếu nại đã đóng, thêm ảnh -> 400', r.status_code == 400, r.status_code)


def t_payment_link_api():
    calls = []

    def fake_create(client, request):
        calls.append(request.order_code)
        n = len(calls)
        return SimpleNamespace(payment_link_id=f'pl{n}', checkout_url=f'http://fake/{n}', qr_code=f'qr{n}')

    pls._create_link = fake_create
    pls.get_payos_client = lambda: None

    b = mk_booking(sessions=1, total=200000, paid=False)
    url = find_url('BookingPaymentLinkView', pk=b.id)

    r1 = call(C, 'post', url)
    check('Tạo link lần 1 -> 200', r1.status_code == 200, (r1.status_code, getattr(r1, 'data', None)))
    r2 = call(C, 'post', url)
    check('Gọi lần 2 (link còn hạn) -> cùng link, không gọi PayOS lại',
          r2.status_code == 200 and body(r2).get('checkout_url') == body(r1).get('checkout_url') and len(calls) == 1,
          (len(calls), body(r2)))
    check('Response có expires_at', body(r1).get('expires_at'), body(r1))

    p = b.payments.first()
    old_code = reload(p).order_code
    Payment.objects.filter(pk=p.pk).update(link_expires_at=NOW - timedelta(minutes=1))
    time.sleep(0.02)
    r3 = call(C, 'post', url)
    check('Link hết hạn -> tạo link mới', r3.status_code == 200 and len(calls) == 2, (r3.status_code, len(calls)))
    check('order_code đổi (không lỗi trùng)', reload(p).order_code != old_code, (old_code, p.order_code))

    bp = mk_booking(sessions=1, total=200000, paid=True)
    r = call(C, 'post', find_url('BookingPaymentLinkView', pk=bp.id))
    check('Đơn đã trả -> 404', r.status_code == 404, r.status_code)
    bx = mk_booking(sessions=1, total=200000, paid=False)
    Booking.objects.filter(pk=bx.pk).update(status='CANCELLED')
    r = call(C, 'post', find_url('BookingPaymentLinkView', pk=bx.id))
    check('Đơn đã hủy -> 404', r.status_code == 404, r.status_code)


def t_worker_api():
    if not WORKER:
        print('  (bỏ qua: không có WORKER)')
        return
    wallet_service.credit_wallet(user=WORKER, amount=D(10000), type=WalletTransaction.Type.ADJUSTMENT, note='seed')
    r = call(WORKER, 'get', find_url('WorkerWalletTransactionListView'))
    res = (body(r) or {}).get('results', [])
    check('Ví nhân viên có direction', r.status_code == 200 and res and 'direction' in res[0], res[:1])
    r = call(C, 'get', find_url('WorkerWalletTransactionListView'))
    check('Khách gọi ví nhân viên -> 403', r.status_code == 403, r.status_code)

    r = call(WORKER, 'get', find_url('WorkerEarningSummaryView'))
    txt = json.dumps(getattr(r, 'data', None), default=str)
    check('Thu nhập -> 200', r.status_code == 200, r.status_code)
    check('Có online_earned và pending_release', 'online_earned' in txt and 'pending_release' in txt, txt[:300])
    check('Không còn net_settlement', 'net_settlement' not in txt, txt[:300])


def run_all():
    section('0. Route có đăng ký đủ không (in URL thật cho FE dùng)', t_urls)
    section('1. Đặt đơn bằng ví qua API (cần create_payload.json)', t_wallet_order)
    section('2. Hủy theo buổi / hủy đơn / chi tiết đơn', t_cancel_schedule_api)
    section('3. Ví khách', t_customer_wallet_api)
    section('4. API admin: hoàn tiền, điều chỉnh, xem ví, idempotency', t_admin_api)
    section('5. Khiếu nại resolve kèm hoàn tiền', t_complaint_api)
    section('6. Upload ảnh khiếu nại (bug 14)', t_attachment_api)
    section('7. Payment-link (bug 9, mock PayOS)', t_payment_link_api)
    section('8. App nhân viên: ví + thu nhập', t_worker_api)

    print('\n' + '=' * 50)
    print(f'TỔNG: {sum(results)}/{len(results)} PASS')
    print('Chưa test bằng script: bug 15 (đếm query), 17 (admin đổi địa chỉ), 18 (thông báo trùng) -> test tay.')


try:
    with transaction.atomic():  # bọc ngoài toàn bộ -> rollback hết, DB dev không đổi
        run_all()
        raise _Rollback()
except _Rollback:
    print('Đã ROLLBACK, DB dev không bị thay đổi.')
sys.exit(0 if all(results) else 1)