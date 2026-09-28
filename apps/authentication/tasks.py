from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives


@shared_task(
    autoretry_for=(Exception,),
    retry_backoff=5,
    retry_backoff_max=60,
    max_retries=4,
)
def send_otp_email(to_email, subject, text_body, html_body):
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email],
    )
    email.attach_alternative(html_body, 'text/html')
    email.send(fail_silently=False)