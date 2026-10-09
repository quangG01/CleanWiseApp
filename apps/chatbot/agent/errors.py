"""Classify provider failures without exposing exception text or request data."""
import httpx


def failure_code(error):
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, (TimeoutError, httpx.TimeoutException)):
            return 'CHATBOT_MODEL_TIMEOUT'
        status = getattr(current, 'code', None)
        if not isinstance(status, int):
            status = getattr(current, 'status_code', None)
        if status in (500, 502, 503, 504):
            return 'CHATBOT_PROVIDER_BUSY'
        if status == 429:
            return 'CHATBOT_RATE_LIMITED'
        if status in (400, 401, 403, 404):
            return 'CHATBOT_PROVIDER_CONFIG_ERROR'
        current = current.__cause__ or current.__context__
    return 'CHATBOT_REPLY_FAILED'


def retryable_model_error(error):
    return failure_code(error) in ('CHATBOT_PROVIDER_BUSY', 'CHATBOT_MODEL_TIMEOUT')
