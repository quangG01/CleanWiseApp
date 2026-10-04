from django.urls import path

from .consumers import ChatConsumer
from apps.notifications.consumers import AdminNotificationConsumer


websocket_urlpatterns = [
    path('ws/admin/notifications/', AdminNotificationConsumer.as_asgi()),
    path('ws/chat/', ChatConsumer.as_asgi()),
]
