# apps/common/idempotency.py
"""
Chống xử lý trùng cho API đụng tiền.

Cách dùng:
    @idempotent                      # header tùy chọn (hành vi cũ, tương thích ngược)
    @idempotent(required=True)       # BẮT BUỘC có header Idempotency-Key; thiếu -> 400; Redis sập -> 503 (fail-closed)

FE sinh 1 UUID mỗi lần user bấm nút, dùng lại ĐÚNG key đó khi tự retry do lỗi mạng,
và sinh key MỚI cho lần bấm mới.

Cơ chế:
- SET NX "đặt cọc" TRƯỚC khi chạy view: 2 request cùng key song song chỉ 1 cái được chạy.
- Lưu dấu vân tay (sha256 của body): cùng key nhưng body khác -> 422, không trả nhầm kết quả cũ.
- Kết quả thành công lưu 24h: retry muộn vẫn nhận lại đúng response cũ, không chạy lại.
- Lỗi 4xx/5xx hoặc exception -> xóa chỗ đặt cọc để client sửa/gọi lại được.
"""
import hashlib
import json
import re
from functools import wraps

from rest_framework.response import Response

from .redis_client import get_redis_client

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60   # giữ kết quả thành công 24h
LOCK_WAIT_TTL_SECONDS = 120              # đủ cho 1 lần gọi mạng ra payOS
_KEY_RE = re.compile(r'[A-Za-z0-9._:\-]{8,100}')


def _error(detail, code, http_status):
    return Response({'detail': detail, 'error_code': code}, status=http_status)


def _fingerprint(request):
    try:
        body = request.body
    except Exception:
        body = b''
    return hashlib.sha256(body or b'').hexdigest()


def idempotent(view_func=None, *, required=False):
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, request, *args, **kwargs):
            idempotency_key = (request.headers.get('Idempotency-Key') or '').strip()

            if not idempotency_key:
                if required:
                    return _error(
                        'Thiếu header Idempotency-Key.', 'IDEMPOTENCY_KEY_REQUIRED', 400,
                    )
                return fn(self, request, *args, **kwargs)

            if not _KEY_RE.fullmatch(idempotency_key):
                return _error(
                    'Idempotency-Key không hợp lệ (8-100 ký tự chữ, số, . _ : -).',
                    'IDEMPOTENCY_KEY_INVALID', 400,
                )

            redis_client = get_redis_client()
            if redis_client is None:
                if required:
                    # Không có Redis thì không thể đảm bảo chống trùng -> từ chối, KHÔNG chạy tiếp.
                    return _error(
                        'Hệ thống tạm thời chưa xử lý được yêu cầu này, vui lòng thử lại sau.',
                        'IDEMPOTENCY_UNAVAILABLE', 503,
                    )
                return fn(self, request, *args, **kwargs)

            cache_key = f'idem:{request.user.id}:{request.method}:{request.path}:{idempotency_key}'
            fingerprint = _fingerprint(request)

            acquired = redis_client.set(
                cache_key,
                json.dumps({'status': 'PROCESSING', 'fp': fingerprint}),
                nx=True,
                ex=LOCK_WAIT_TTL_SECONDS,
            )
            if not acquired:
                raw = redis_client.get(cache_key)
                if raw is None:
                    # Vừa hết hạn/bị xóa giữa chừng -> bảo client thử lại.
                    return _error(
                        'Yêu cầu đang được xử lý, vui lòng thử lại sau ít giây.',
                        'IDEMPOTENCY_PROCESSING', 409,
                    )
                payload = json.loads(raw)
                if payload.get('fp') != fingerprint:
                    return _error(
                        'Idempotency-Key này đã được dùng cho một yêu cầu khác.',
                        'IDEMPOTENCY_KEY_REUSED', 422,
                    )
                if payload.get('status') == 'PROCESSING':
                    return _error(
                        'Yêu cầu đang được xử lý, vui lòng thử lại sau ít giây.',
                        'IDEMPOTENCY_PROCESSING', 409,
                    )
                return Response(payload['data'], status=payload['status'])

            try:
                response = fn(self, request, *args, **kwargs)
            except Exception:
                # Chạy lỗi (exception) -> xóa chỗ đặt cọc để client gọi lại được ngay.
                redis_client.delete(cache_key)
                raise

            if 200 <= response.status_code < 300:
                redis_client.setex(
                    cache_key,
                    IDEMPOTENCY_TTL_SECONDS,
                    json.dumps(
                        {'data': response.data, 'status': response.status_code, 'fp': fingerprint},
                        default=str,
                    ),
                )
            else:
                # Lỗi nghiệp vụ (4xx/5xx) -> không cache, xóa chỗ đặt cọc để client sửa data rồi gọi lại.
                redis_client.delete(cache_key)

            return response

        return wrapper

    # Hỗ trợ cả @idempotent lẫn @idempotent(required=True)
    if view_func is not None:
        return decorator(view_func)
    return decorator