from payos import PayOS
from payos.types import CreatePaymentLinkRequest
from django.conf import settings
import time
from .models import Payment

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


def create_payos_payment_link(payment: Payment, *, return_url: str, cancel_url: str):
    """orderCode dùng luôn payment.id (đã unique) để khỏi phải thêm field mới.
    description payOS giới hạn tối đa 25 ký tự."""
    client = get_payos_client()
    result = client.payment_requests.create(payment_data=CreatePaymentLinkRequest(
        order_code=payment.id,
        amount=int(payment.amount),
        description=f'DH{payment.booking_id}'[:25],
        return_url=return_url,
        cancel_url=cancel_url,
        expired_at=int(time.time()) + 5 * 60,  # hết hạn sau 5 phút
    ))
    return {
        'checkout_url': result.checkout_url,
        'qr_code': result.qr_code,          # render thành ảnh QR ở FE (vd: qrcode.react)
        'payment_link_id': result.payment_link_id,
    }