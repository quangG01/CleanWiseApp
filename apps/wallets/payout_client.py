"""
Lớp duy nhất nói chuyện với kênh chi tiền (payOS payout).

PAYOUT_MODE=mock  -> giả lập, không gọi mạng (chỉ chạy khi DEBUG=True hoặc PAYOUT_ALLOW_MOCK=1,
                     để quên đổi mode trên production không "rút thành công" mà không chuyển tiền thật).
PAYOUT_MODE=payos -> gọi payOS thật bằng bộ khoá PAYOS_PAYOUT_* (khác bộ khoá nhận tiền).

Quy ước lỗi, để withdraw_service biết nên hoàn ví hay chờ:
- PayoutRejected: payOS ĐÃ TRẢ LỜI và từ chối hẳn, tiền CHƯA đi -> hoàn ví (CHỈ khi trước đó
                  chưa từng có lần gọi "không rõ kết quả", việc này withdraw_service lo).
                  Message của exception là câu tiếng Việt an toàn để hiện cho người dùng.
- PayoutUnknown : timeout / mất kết nối / 5xx / 408 / 409 / 429, không biết tiền đã đi chưa
                  -> giữ PROCESSING, gọi lại cùng idempotency key.

Mock cho test (theo 4 số cuối số tài khoản):
  0000 -> payOS báo giao dịch FAILED          2222 -> bị từ chối ngay (PayoutRejected)
  1111 -> PENDING, thành công sau 20 giây      3333 -> lỗi mạng lần đầu, gọi lại thì thành công
  4444 -> lỗi mạng lần đầu, gọi lại bị TỪ CHỐI (mô phỏng "đã chi nhưng retry báo trùng") -> phải needs_review
  còn lại -> thành công ngay
"""
import logging
import re
import time
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

PENDING = 'PENDING'
SUCCESS = 'SUCCESS'
FAILED = 'FAILED'

MOCK_PENDING_SECONDS = 20

# Mã HTTP là lỗi tạm thời: payOS có thể đã nhận lệnh -> KHÔNG được coi là từ chối hẳn.
_TRANSIENT_STATUSES = (408, 409, 429)


class PayoutRejected(Exception):
    pass


class PayoutUnknown(Exception):
    pass


@dataclass
class PayoutResult:
    state: str  # PENDING | SUCCESS | FAILED
    payout_id: str = ''
    error: str = ''


def current_mode():
    mode = getattr(settings, 'PAYOUT_MODE', 'mock')
    if mode not in ('mock', 'payos'):
        raise ImproperlyConfigured("PAYOUT_MODE phải là 'mock' hoặc 'payos'.")
    if mode == 'mock' and not (settings.DEBUG or getattr(settings, 'PAYOUT_ALLOW_MOCK', False)):
        raise ImproperlyConfigured('PAYOUT_MODE=mock chỉ được dùng khi DEBUG=True.')
    return mode


def ensure_ready():
    """Gọi TRƯỚC khi trừ ví: cấu hình sai thì từ chối luôn, chưa đụng tiền."""
    mode = current_mode()
    if mode == 'payos':
        _get_client()
    return mode


# ------------------------------------------------------------------ dịch lỗi cho người dùng

MSG_BAD_ACCOUNT = 'Số tài khoản ngân hàng nhận không hợp lệ hoặc không tồn tại. Vui lòng kiểm tra lại.'
MSG_SYSTEM = 'Hệ thống chi tiền tạm thời chưa khả dụng. Tiền đã được hoàn vào ví, vui lòng thử lại sau.'
MSG_BANK_REJECT = 'Ngân hàng từ chối giao dịch. Tiền đã được hoàn vào ví.'

_ACCOUNT_HINTS = ('tài khoản đích', 'số tài khoản', 'tên tài khoản', 'invalid account', 'account number')
_SYSTEM_HINTS = ('địa chỉ ip', 'số dư', 'không đủ', 'balance', 'unauthorized', 'forbidden',
                 'api key', 'checksum', 'signature', 'chữ ký')


def friendly_error(raw):
    """
    Đổi lỗi thô của payOS thành câu an toàn cho người dùng.
    Lỗi nội bộ (IP, số dư kênh chi, khóa API...) không lộ ra ngoài; nguyên văn vẫn nằm trong log.
    """
    text = str(raw or '').lower()
    if any(h in text for h in _ACCOUNT_HINTS):
        return MSG_BAD_ACCOUNT
    if any(h in text for h in _SYSTEM_HINTS) or re.search(r'\bip\b', text):
        return MSG_SYSTEM
    return MSG_BANK_REJECT


def _is_definitive_rejection(exc):
    """
    True khi payOS ĐÃ trả lời và đó không phải lỗi tạm thời.
    Không có status_code (timeout, mất kết nối...) hoặc 5xx/408/409/429 -> chưa chắc -> False.
    """
    status = getattr(exc, 'status_code', None)
    if not isinstance(status, int):
        return False
    return not (status >= 500 or status in _TRANSIENT_STATUSES)


# ------------------------------------------------------------------ mock

def _mock_create(reference_id, account_number):
    tail = account_number[-4:]
    if tail == '2222':
        raise PayoutRejected(MSG_BAD_ACCOUNT)

    unknown_key = f'mock_payout_unknown:{reference_id}'
    if tail == '3333' and not cache.get(unknown_key):
        cache.set(unknown_key, 1, 3600)
        raise PayoutUnknown('Mock: lỗi mạng giả lập.')
    if tail == '4444':
        if not cache.get(unknown_key):
            cache.set(unknown_key, 1, 3600)
            raise PayoutUnknown('Mock: lỗi mạng giả lập.')
        raise PayoutRejected('Mock: gọi lại bị từ chối (trùng reference).')

    payout_id = f'mock-{reference_id}'
    if tail == '0000':
        return PayoutResult(FAILED, payout_id, MSG_BANK_REJECT)
    if tail == '1111':
        cache.set(f'mock_payout_started:{reference_id}', time.time(), 3600)
        return PayoutResult(PENDING, payout_id)
    return PayoutResult(SUCCESS, payout_id)


def _mock_status(payout_id):
    reference_id = payout_id.removeprefix('mock-')
    started = cache.get(f'mock_payout_started:{reference_id}')
    if started is not None and time.time() - started < MOCK_PENDING_SECONDS:
        return PayoutResult(PENDING, payout_id)
    return PayoutResult(SUCCESS, payout_id)


# ------------------------------------------------------------------ payos

_client = None


def _get_client():
    global _client
    if _client is None:
        from payos import PayOS

        creds = (
            settings.PAYOS_PAYOUT_CLIENT_ID,
            settings.PAYOS_PAYOUT_API_KEY,
            settings.PAYOS_PAYOUT_CHECKSUM_KEY,
        )
        if not all(creds):
            raise ImproperlyConfigured('Thiếu PAYOS_PAYOUT_CLIENT_ID / API_KEY / CHECKSUM_KEY.')
        _client = PayOS(client_id=creds[0], api_key=creds[1], checksum_key=creds[2])
    return _client


def _translate(payout):
    tx = payout.transactions[0] if payout.transactions else None
    tx_state = str(getattr(tx, 'state', '') or '').upper()
    approval = str(getattr(payout, 'approval_state', '') or '').upper()
    # Log state thật để đối chiếu với docs payOS.
    logger.info('payOS payout id=%s approval=%s tx_state=%s', payout.id, approval, tx_state)

    if tx_state == 'SUCCEEDED':
        return PayoutResult(SUCCESS, payout.id)
    if tx_state in ('FAILED', 'CANCELLED', 'REVERSED'):
        raw = getattr(tx, 'error_message', None) or getattr(tx, 'error_code', None) or tx_state
        logger.error('payOS payout thất bại id=%s: %s', payout.id, raw)
        return PayoutResult(FAILED, payout.id, friendly_error(raw))
    if approval in ('REJECTED', 'CANCELLED', 'FAILED'):
        logger.error('payOS payout bị từ chối id=%s approval=%s', payout.id, approval)
        return PayoutResult(FAILED, payout.id, MSG_BANK_REJECT)
    return PayoutResult(PENDING, payout.id)


def _payos_create(reference_id, amount, description, bank_bin, account_number):
    from payos import BadRequestError, ForbiddenError, NotFoundError, UnauthorizedError
    from payos.types import PayoutRequest

    client = _get_client()  # lỗi cấu hình cho nổ thẳng, không coi là "chưa rõ kết quả"
    request = PayoutRequest(
        reference_id=reference_id, amount=int(amount), description=description,
        to_bin=bank_bin, to_account_number=account_number,
    )
    try:
        payout = client.payouts.create(request, idempotency_key=reference_id)
    except (BadRequestError, UnauthorizedError, ForbiddenError, NotFoundError) as exc:
        logger.error('payOS payout bị từ chối ref=%s type=%s: %s', reference_id, type(exc).__name__, exc)
        raise PayoutRejected(friendly_error(exc)) from exc
    except Exception as exc:
        status = getattr(exc, 'status_code', None)
        if _is_definitive_rejection(exc):
            # payOS đã trả lời (vd APIError status=200 "Tài khoản đích không hợp lệ") -> tiền chưa đi.
            logger.error(
                'payOS payout bị từ chối ref=%s type=%s status=%s msg=%s',
                reference_id, type(exc).__name__, status, exc,
            )
            raise PayoutRejected(friendly_error(exc)) from exc
        logger.warning(
            'payOS payout chưa rõ kết quả ref=%s type=%s status=%s msg=%s',
            reference_id, type(exc).__name__, status, exc,
        )
        raise PayoutUnknown(str(exc)) from exc
    return _translate(payout)


def _payos_status(payout_id):
    client = _get_client()
    try:
        payout = client.payouts.get(payout_id)
    except Exception as exc:
        logger.warning(
            'payOS hỏi trạng thái lỗi id=%s type=%s status=%s msg=%s',
            payout_id, type(exc).__name__, getattr(exc, 'status_code', None), exc,
        )
        raise PayoutUnknown(str(exc)) from exc
    return _translate(payout)


# ------------------------------------------------------------------ public

def create_payout(*, reference_id, amount, description, bank_bin, account_number) -> PayoutResult:
    """Tạo lệnh chi. Gọi lại cùng reference_id là an toàn (idempotency key)."""
    if current_mode() == 'mock':
        return _mock_create(reference_id, account_number)
    return _payos_create(reference_id, amount, description, bank_bin, account_number)


def get_payout_status(payout_id) -> PayoutResult:
    if current_mode() == 'mock':
        return _mock_status(payout_id)
    return _payos_status(payout_id)