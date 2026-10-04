"""
Lịch sử thanh toán của khách: thanh toán đơn (online / ví) và các khoản hoàn tiền vào ví.

Nguồn dữ liệu:
- Payment (trừ tiền mặt): thanh toán đơn qua payOS (BANK_TRANSFER...) hoặc ví (WALLET).
- WalletTransaction loại PAYMENT / REFUND: khoản trả bằng ví và các khoản hoàn.
  PAYMENT trong ví bị bỏ qua nếu đơn đó đã có Payment(method=WALLET), tránh hiện 2 dòng cho 1 lần trả.

Gộp trong bộ nhớ (mỗi nguồn tối đa FETCH_CAP dòng mới nhất): dữ liệu của 1 khách nhỏ,
đổi lại FE chỉ cần gọi 1 API và phân trang đúng thứ tự thời gian.
"""
from decimal import Decimal
from math import ceil

from django.utils import timezone

from apps.wallets.models import WalletTransaction

from .models import Payment

FETCH_CAP = 500
SOURCES = ('all', 'wallet', 'online')
STATUSES = ('all', 'paid', 'pending', 'cancelled', 'refunded')




_PAID_STATUSES = (Payment.Status.SUCCESS, Payment.Status.REFUNDED)
_NOTE_STATUSES = (Payment.Status.FAILED, Payment.Status.CANCELLED, Payment.Status.REFUNDED)

def _match_status(item, status):
    s, k = item['status'], item['kind']
    if status == 'paid':
        return k == 'PAYMENT' and s == 'SUCCESS'
    if status == 'pending':
        return s == 'PENDING'
    if status == 'cancelled':
        return s in ('CANCELLED', 'FAILED')
    if status == 'refunded':
        return k == 'REFUND' or s == 'REFUNDED'
    return True

def _row(*, key, kind, channel, direction, title, method_display, amount, status,
         status_display, booking_id, booking_code, note, when):
    item = {
        'id': key,
        'kind': kind,                  # PAYMENT | REFUND
        'channel': channel,            # ONLINE | WALLET
        'direction': direction,        # DEBIT | CREDIT
        'title': title,
        'method_display': method_display,
        'amount': f'{amount:.2f}',
        'status': status,              # PENDING | SUCCESS | FAILED | CANCELLED | REFUNDED
        'status_display': status_display,
        'booking_id': booking_id,
        'booking_code': booking_code,
        'note': note,
        'created_at': timezone.localtime(when).isoformat(),
    }
    return when, item, Decimal(amount)


def _payment_row(p):
    code = p.booking.booking_code
    is_wallet = p.method == Payment.Method.WALLET
    return _row(
        key=f'payment-{p.id}', kind='PAYMENT',
        channel='WALLET' if is_wallet else 'ONLINE', direction='DEBIT',
        title=f'Thanh toán đơn {code}',
        method_display=p.get_method_display(),
        amount=p.amount, status=p.status, status_display=p.get_status_display(),
        booking_id=p.booking_id, booking_code=code,
        note=(p.failure_reason or '') if p.status in _NOTE_STATUSES else '',
        when=p.paid_at or p.created_at,
    )


def _wallet_row(tx):
    is_refund = tx.type == WalletTransaction.Type.REFUND
    code = tx.booking.booking_code if tx.booking_id else ''
    if is_refund:
        title = f'Hoàn tiền đơn {code}' if code else 'Hoàn tiền vào ví'
    else:
        title = f'Thanh toán đơn {code}' if code else 'Thanh toán bằng ví'
    return _row(
        key=f'wallet-{tx.id}', kind='REFUND' if is_refund else 'PAYMENT',
        channel='WALLET',
        direction=WalletTransaction.Direction.CREDIT if is_refund else WalletTransaction.Direction.DEBIT,
        title=title, method_display='Ví CleanWise',
        amount=tx.amount, status=tx.status, status_display=tx.get_status_display(),
        booking_id=tx.booking_id, booking_code=code, note=tx.note or '',
        when=tx.created_at,
    )


def get_payment_history(*, user, source='all', status='all', page=1, page_size=20):
    rows = []

    payments_qs = (
        Payment.objects.filter(customer=user)
        .select_related('booking')
    )
    if source == 'online':
        payments_qs = payments_qs.exclude(method=Payment.Method.WALLET)
    elif source == 'wallet':
        payments_qs = payments_qs.filter(method=Payment.Method.WALLET)
    payments = list(payments_qs.order_by('-created_at', '-id')[:FETCH_CAP])
    rows.extend(_payment_row(p) for p in payments)

    if source != 'online':
        wallet_paid_bookings = {
            p.booking_id for p in payments
            if p.method == Payment.Method.WALLET and p.status in _PAID_STATUSES
        }
        txs = (
            WalletTransaction.objects.filter(
                wallet__user=user,
                type__in=[WalletTransaction.Type.PAYMENT, WalletTransaction.Type.REFUND],
            )
            .select_related('booking')
            .order_by('-created_at', '-id')[:FETCH_CAP]
        )
        for tx in txs:
            if tx.type == WalletTransaction.Type.PAYMENT and tx.booking_id in wallet_paid_bookings:
                continue
            rows.append(_wallet_row(tx))

    rows.sort(key=lambda r: (r[0], r[1]['id']), reverse=True)

    paid_total = sum(
        (amt for _, it, amt in rows if it['kind'] == 'PAYMENT' and it['status'] in _PAID_STATUSES),
        Decimal('0'),
    )
    refunded_total = sum(
        (amt for _, it, amt in rows if it['kind'] == 'REFUND' and it['status'] == 'SUCCESS'),
        Decimal('0'),
    )
    if status != 'all':
        rows = [r for r in rows if _match_status(r[1], status)]
    count = len(rows)
    total_pages = max(1, ceil(count / page_size))
    start = (page - 1) * page_size
    return {
        'results': [it for _, it, _ in rows[start:start + page_size]],
        'count': count,
        'page': page,
        'total_pages': total_pages,
        'has_next': page < total_pages,
        'has_previous': page > 1,
        'summary': {
            'paid_total': f'{paid_total:.2f}',
            'refunded_total': f'{refunded_total:.2f}',
        },
    }