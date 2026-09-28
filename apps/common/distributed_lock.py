import contextlib

import redis

from apps.common.exceptions import ConcurrentUpdateError
from apps.common.redis_client import get_redis_client


@contextlib.contextmanager
def distributed_lock(name, *, ttl=10, wait=3):
    """
    ttl:  giữ lock tối đa bao nhiêu giây (tự nhả nếu process chết).
    wait: chờ lấy lock tối đa bao nhiêu giây, quá thì trả 409.
    Redis không có hoặc lỗi: bỏ qua lock, DB lock vẫn bảo vệ.
    """
    client = get_redis_client()
    lock = None

    if client is not None:
        try:
            candidate = client.lock(
                f'cw:lock:{name}', timeout=ttl, blocking_timeout=wait,
            )
            if not candidate.acquire():
                raise ConcurrentUpdateError(
                    'Yêu cầu đang được xử lý, vui lòng thử lại.',
                )
            lock = candidate
        except redis.exceptions.RedisError:
            lock = None

    try:
        yield
    finally:
        if lock is not None:
            try:
                lock.release()
            except redis.exceptions.RedisError:
                pass  