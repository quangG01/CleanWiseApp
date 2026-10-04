import time
from datetime import datetime, timezone as dt_timezone

import httpx
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from payos import PayOS
from payos.types import CreatePaymentLinkRequest
from rest_framework import serializers

from apps.common.retry import retry_on

from .models import Payment

LINK_TTL_SECONDS = 5 * 60


def _payos_retryable(exc):
    return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError,
                            httpx.ReadError, httpx.RemoteProtocolError))


@retry_on(_payos_retryable)
def _create_link(client, request):
    return client.payment_requests.create(payment_data=request)


_client = None


def get_payos_client():
    global _client
    if _client is None:
        _client = PayOS(
            client_id=settings.PAYOS_CLIENT_ID,
            api_key=settings.PAYOS_API_KEY,
            checksum_key=settings.PAYOS_CHECKSUM_KEY,
        )
    return _client


def _payload(payment):
    return {
        'checkout_url': payment.checkout_url,
        'qr_code': payment.qr_code,
        'payment_link_id': payment.payment_link_id,
        'expires_at': payment.link_expires_at.isoformat() if payment.link_expires_at else None,
        'bank_bin': payment.bank_bin,
        'account_number': payment.account_number,
        'account_name': payment.account_name,
        'transfer_content': payment.transfer_content,
        'amount': int(payment.amount),
    }


def create_payos_payment_link(payment: Payment, *, return_url: str, cancel_url: str):
    """Link còn hạn -> trả lại link cũ. Hết hạn -> tạo link mới với orderCode mới
    (orderCode cũ đã bị payOS ghi nhận nên không dùng lại payment.id được)."""
    with transaction.atomic():
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status != Payment.Status.PENDING:
            raise serializers.ValidationError({'payment': 'Thanh toán không còn ở trạng thái chờ.'})

        if payment.checkout_url and payment.link_expires_at and payment.link_expires_at > timezone.now():
            return _payload(payment)

        expires_ts = int(time.time()) + LINK_TTL_SECONDS
        order_code = int(time.time() * 1000)  # < 2^53, unique nhờ constraint
        request = CreatePaymentLinkRequest(
            order_code=order_code,
            amount=int(payment.amount),
            description=f'DH{payment.booking_id}'[:25],
            return_url=return_url,
            cancel_url=cancel_url,
            expired_at=expires_ts,
        )
        result = _create_link(get_payos_client(), request)

        payment.order_code = order_code
        payment.payment_link_id = result.payment_link_id or ''
        payment.checkout_url = result.checkout_url or ''
        payment.qr_code = result.qr_code or ''
        payment.link_expires_at = datetime.fromtimestamp(expires_ts, tz=dt_timezone.utc)
        payment.bank_bin = getattr(result, 'bin', '') or ''
        payment.account_number = getattr(result, 'account_number', '') or ''
        payment.account_name = getattr(result, 'account_name', '') or ''
        payment.transfer_content = getattr(result, 'description', '') or ''
        payment.save(update_fields=[
            'order_code', 'payment_link_id', 'checkout_url', 'qr_code', 'link_expires_at',
            'bank_bin', 'account_number', 'account_name', 'transfer_content', 'updated_at',
        ])
        return _payload(payment)