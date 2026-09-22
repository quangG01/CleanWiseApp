"""
ASGI config for core project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

from dotenv import load_dotenv


load_dotenv()  # Load environment variables from .env file
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    raise RuntimeError('Set DJANGO_SETTINGS_MODULE before starting the ASGI server.')

django_asgi_application = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from apps.chat.routing import websocket_urlpatterns

application = ProtocolTypeRouter({
    'http': django_asgi_application,
    'websocket': URLRouter(websocket_urlpatterns),
})
