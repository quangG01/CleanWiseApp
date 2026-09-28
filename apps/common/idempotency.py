# apps/common/idempotency.py

import json
from functools import wraps

from rest_framework.response import Response

from .redis_client import get_redis_client

IDEMPOTENCY_TTL_SECONDS = 300
LOCK_WAIT_TTL_SECONDS = 30 


def idempotent(view_func):
    """
    Decorator cho method của APIView/GenericAPIView.
    Client gửi kèm header 'Idempotency-Key' (1 UUID do FE tự sinh mỗi lần
    user bấm nút hành động, KHÔNG đổi khi tự động retry do lỗi mạng).

    Nếu key đã xử lý xong trước đó (còn trong TTL) -> trả lại response cũ,
    KHÔNG chạy lại view_func.

    ĐỔI: dùng SET key value NX (atomic ở tầng Redis) để "đặt cọc chỗ"
    TRƯỚC khi chạy view_func, thay vì chỉ ghi SAU khi chạy xong. Trước
    đây 2 request cùng key gửi gần như đồng thời đều đọc thấy cache rỗng
    (vì chưa ai kịp ghi) -> cả 2 cùng chạy view_func thật -> mất tác dụng
    chống trùng đúng lúc cần nhất. SET NX đảm bảo chỉ 1 request thắng
    được quyền chạy, request thua phải đợi rồi đọc lại kết quả.
    """
    @wraps(view_func)
    def wrapper(self, request, *args, **kwargs):
        idempotency_key = request.headers.get('Idempotency-Key')

        if not idempotency_key:
            return view_func(self, request, *args, **kwargs)

        redis_client = get_redis_client()
        if redis_client is None:
            return view_func(self, request, *args, **kwargs)
        cache_key = f'idem:{request.path}:{request.user.id}:{idempotency_key}'

        cached = redis_client.get(cache_key)
        if cached:
            payload = json.loads(cached)
            if payload.get('status') != 'PROCESSING':
                return Response(payload['data'], status=payload['status'])
            return Response(
                {
                    'detail': 'Yêu cầu đang được xử lý, vui lòng thử lại sau ít giây.',
                    'error_code': 'IDEMPOTENCY_PROCESSING',  # THÊM: tín hiệu rõ ràng để FE tự động retry, không nhầm với conflict nghiệp vụ thật
                },
                status=409,
            )

        acquired = redis_client.set(
            cache_key,
            json.dumps({'status': 'PROCESSING'}),
            nx=True,
            ex=LOCK_WAIT_TTL_SECONDS,
        )
        if not acquired:
            return Response(
                {
                    'detail': 'Yêu cầu đang được xử lý, vui lòng thử lại sau ít giây.',
                    'error_code': 'IDEMPOTENCY_PROCESSING',  # THÊM
                },
                status=409,
            )

        try:
            response = view_func(self, request, *args, **kwargs)
        except Exception:
            # Chạy lỗi (exception) -> xóa chỗ đã đặt cọc để client được phép
            # gọi lại ngay, không phải chờ hết LOCK_WAIT_TTL_SECONDS.
            redis_client.delete(cache_key)
            raise

        if 200 <= response.status_code < 300:
            redis_client.setex(
                cache_key,
                IDEMPOTENCY_TTL_SECONDS,
                json.dumps({'data': response.data, 'status': response.status_code}),
            )
        else:
            # Lỗi nghiệp vụ (4xx) -> không cache kết quả lỗi, xóa chỗ đặt
            # cọc để client sửa data rồi gọi lại được ngay.
            redis_client.delete(cache_key)

        return response

    return wrapper