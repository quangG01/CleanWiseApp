import functools
import logging
import time

logger = logging.getLogger(__name__)

DEFAULT_DELAYS = (3, 5)  # chờ 3s sau lần 1, 5s sau lần 2 -> tối đa 3 lần thử


def retry_on(retryable, delays=DEFAULT_DELAYS):
    """
    retryable: tuple các Exception nên retry, hoặc hàm (exc) -> bool.
    Lỗi không thuộc nhóm này ném ra ngay, không retry.
    """
    def should_retry(exc):
        if callable(retryable) and not isinstance(retryable, tuple):
            return retryable(exc)
        return isinstance(exc, retryable)

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for attempt, delay in enumerate((*delays, None), start=1):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    if delay is None or not should_retry(exc):
                        raise
                    logger.warning(
                        '%s lỗi tạm thời (lần %s): %r. Thử lại sau %ss.',
                        func.__name__, attempt, exc, delay,
                    )
                    time.sleep(delay)
        return wrapper
    return decorator