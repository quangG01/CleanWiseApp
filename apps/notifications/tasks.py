import requests
from celery import shared_task


@shared_task(
    autoretry_for=(requests.RequestException,),
    retry_backoff=5,
    retry_backoff_max=60,
    max_retries=4,
)
def send_push_task(user_id, title, message, data=None):
    from .push import deliver_push_to_user
    deliver_push_to_user(user_id, title, message, data)