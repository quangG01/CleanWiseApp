import os
import redis

_redis_client = None

def get_redis_client():
    global _redis_client
    url = os.environ.get('REDIS_URL')
    if not url:
        return None
    if _redis_client is None:
        _redis_client = redis.from_url(
            url,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
            health_check_interval=30,
        )
    return _redis_client