from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction


def booking_watch_group(booking_id):
    return f'worker_booking_{booking_id}'


def publish_booking_changed(booking_id):
    def send():
        layer = get_channel_layer()
        if layer is not None:
            async_to_sync(layer.group_send)(booking_watch_group(booking_id), {
                'type': 'booking.changed', 'booking_id': booking_id,
            })

    transaction.on_commit(send, robust=True)
