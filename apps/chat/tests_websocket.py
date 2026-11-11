from datetime import timedelta

from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.contrib.auth import get_user_model
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from django.urls import reverse
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken

from apps.addresses.models import CustomerAddress
from apps.bookings.models import Booking, BookingSchedule
from apps.services.models import Service
from apps.worker.models import BookingAssignment
from core.asgi import application

from .service import ensure_chat_for_assignment
from .models import ChatMessage


User = get_user_model()


@override_settings(ALLOWED_HOSTS=['testserver'])
class ChatWebSocketTests(TransactionTestCase):
    def test_split_facebook_contact_is_blocked_via_http_for_both_participants(self):
        conversation = ensure_chat_for_assignment(self.assignment)
        client = APIClient()
        for user in (self.customer, self.worker):
            client.force_authenticate(user)
            response = client.post(reverse('chat-message-send'), {
                'conversation_id': conversation.id,
                'message': 'Nhan tin lien he qua face book em nhe',
            }, format='json')
            self.assertEqual(response.status_code, 400, response.data)
            self.assertEqual(response.data['error_code'], 'CHAT_CONTENT_BLOCKED')
        self.assertFalse(ChatMessage.objects.filter(conversation=conversation).exists())

    async def test_blocked_message_is_only_reported_to_sender_and_not_persisted(self):
        conversation = await database_sync_to_async(ensure_chat_for_assignment)(self.assignment)
        customer_socket = await self.connect_user(self.customer)
        worker_socket = await self.connect_user(self.worker)
        try:
            for sender, recipient, text in (
                (customer_socket, worker_socket, '0912345678'),
                (worker_socket, customer_socket, 'Lần tới mình làm riêng cho tiện nha'),
                (customer_socket, worker_socket, 'Nhan tin lien he qua face book em nhe'),
            ):
                await sender.send_json_to({
                    'type': 'message.send', 'conversation_id': conversation.id,
                    'message': text,
                })
                event = await sender.receive_json_from()
                self.assertEqual(event['type'], 'error')
                self.assertEqual(event['code'], 'CHAT_CONTENT_BLOCKED')
                self.assertEqual(event['conversation_id'], conversation.id)
                self.assertIn('Vui lòng chỉnh sửa', event['detail']['message'])
                self.assertTrue(await recipient.receive_nothing(timeout=0.1))
                self.assertEqual((await sender.receive_json_from())['type'], 'moderation.updated')
                self.assertTrue(await sender.receive_nothing(timeout=0.1))
            self.assertFalse(await database_sync_to_async(ChatMessage.objects.exists)())
        finally:
            await customer_socket.disconnect()
            await worker_socket.disconnect()

    def setUp(self):
        self.customer = User.objects.create_user(
            username='socket-customer', email='socket-customer@example.com',
            password='test', role=User.Role.CUSTOMER,
        )
        self.worker = User.objects.create_user(
            username='socket-worker', email='socket-worker@example.com',
            password='test', role=User.Role.WORKER,
        )
        self.outsider = User.objects.create_user(
            username='socket-outsider', email='socket-outsider@example.com',
            password='test', role=User.Role.CUSTOMER,
        )
        service = Service.objects.create(
            code='SOCKET_TEST', section_code='HOME', name='Dọn dẹp',
            description='Test', form_schema={}, pricing_config={},
        )
        address = CustomerAddress.objects.create(
            customer=self.customer, receiver_name='Khách', receiver_phone='0912345678',
            address_line='1 Nguyễn Huệ', city='TP.HCM',
        )
        booking = Booking.objects.create(
            booking_code='SOCKET-001', customer=self.customer, service=service,
            address=address, service_data={},
        )
        start = timezone.now() + timedelta(days=1)
        schedule = BookingSchedule.objects.create(
            booking=booking, sequence_no=1,
            scheduled_start=start, scheduled_end=start + timedelta(hours=2),
        )
        self.assignment = BookingAssignment.objects.create(
            schedule=schedule, worker=self.worker,
            status=BookingAssignment.Status.ACCEPTED,
        )

    async def connect_user(self, user):
        communicator = WebsocketCommunicator(
            application, '/ws/chat/', headers=[(b'origin', b'http://testserver')],
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.send_json_to({
            'type': 'auth', 'access_token': str(AccessToken.for_user(user)),
        })
        self.assertEqual((await communicator.receive_json_from())['type'], 'auth.ok')
        return communicator

    async def test_redaction_warnings_then_lock_are_enforced_over_socket(self):
        conversation = await database_sync_to_async(ensure_chat_for_assignment)(self.assignment)
        sender = await self.connect_user(self.customer)
        recipient = await self.connect_user(self.worker)
        try:
            for number in range(1, 5):
                await sender.send_json_to({
                    'type': 'message.send', 'conversation_id': conversation.pk,
                    'message': 'Đến 9h30 nhé, 0912345678', 'client_message_id': f'socket-{number}',
                })
                events = [await sender.receive_json_from() for _ in range(3 if number <= 3 else 2)]
                by_type = {event['type']: event for event in events}
                self.assertIn('moderation.updated', by_type)
                self.assertNotIn('0912345678', str(events))
                if number <= 3:
                    self.assertEqual(by_type['message.accepted']['moderation']['violation_count'], number)
                    event = await recipient.receive_json_from()
                    self.assertEqual(event['type'], 'message.created')
                    self.assertEqual(event['message']['message'], 'Đến 9h30 nhé, [SĐT đã ẩn]')
                    self.assertNotIn('moderation', event['message'])
                else:
                    self.assertEqual(by_type['error']['code'], 'CHAT_SEND_LOCKED')
                    self.assertTrue(await recipient.receive_nothing(timeout=0.1))
            # A retry of the locking attempt adds no violation or event.
            await sender.send_json_to({
                'type': 'message.send', 'conversation_id': conversation.pk,
                'message': 'Đến 9h30 nhé, 0912345678', 'client_message_id': 'socket-4',
            })
            self.assertEqual((await sender.receive_json_from())['code'], 'CHAT_SEND_LOCKED')
            self.assertTrue(await sender.receive_nothing(timeout=0.1))
            self.assertEqual(await database_sync_to_async(ChatMessage.objects.count)(), 3)
        finally:
            await sender.disconnect()
            await recipient.disconnect()

    async def test_conversation_update_without_notices_and_shared_text(self):
        customer_socket = await self.connect_user(self.customer)
        worker_socket = await self.connect_user(self.worker)
        outsider_socket = await self.connect_user(self.outsider)
        try:
            conversation = await database_sync_to_async(ensure_chat_for_assignment)(self.assignment)
            customer_event = await customer_socket.receive_json_from()
            worker_event = await worker_socket.receive_json_from()
            self.assertEqual(customer_event, {'type': 'conversation.updated', 'conversation_id': conversation.id})
            self.assertEqual(worker_event, customer_event)
            self.assertTrue(await customer_socket.receive_nothing(timeout=0.1))
            self.assertTrue(await worker_socket.receive_nothing(timeout=0.1))
            self.assertTrue(await outsider_socket.receive_nothing(timeout=0.1))

            await customer_socket.send_json_to({
                'type': 'typing.start', 'conversation_id': conversation.id,
            })
            typing_event = await worker_socket.receive_json_from()
            self.assertEqual(typing_event, {
                'type': 'typing.changed', 'conversation_id': conversation.id,
                'user_id': self.customer.id, 'is_typing': True,
            })
            self.assertTrue(await customer_socket.receive_nothing(timeout=0.1))
            self.assertTrue(await outsider_socket.receive_nothing(timeout=0.1))
            await customer_socket.send_json_to({
                'type': 'typing.stop', 'conversation_id': conversation.id,
            })
            self.assertFalse((await worker_socket.receive_json_from())['is_typing'])
            await outsider_socket.send_json_to({
                'type': 'typing.start', 'conversation_id': conversation.id,
            })
            self.assertEqual((await outsider_socket.receive_json_from())['code'], 'not_found')

            await customer_socket.send_json_to({
                'type': 'message.send', 'conversation_id': conversation.id,
                'message': 'Chào anh', 'sender_id': self.worker.id,
            })
            customer_events = [await customer_socket.receive_json_from() for _ in range(2)]
            worker_text = await worker_socket.receive_json_from()
            self.assertEqual({event['type'] for event in customer_events}, {'message.accepted', 'message.created'})
            self.assertEqual(worker_text['type'], 'message.created')
            self.assertEqual(worker_text['message']['sender_id'], self.customer.id)
            self.assertEqual(worker_text['message']['message'], 'Chào anh')
            self.assertTrue(await outsider_socket.receive_nothing(timeout=0.1))

            await worker_socket.send_json_to({
                'type': 'messages.read', 'conversation_id': conversation.id,
            })
            self.assertEqual((await worker_socket.receive_json_from())['type'], 'messages.read.ack')
            read_event = await customer_socket.receive_json_from()
            self.assertEqual(read_event['type'], 'messages.read')
            self.assertEqual(read_event['reader_id'], self.worker.id)

            await outsider_socket.send_json_to({
                'type': 'message.send', 'conversation_id': conversation.id, 'message': 'Lạ',
            })
            self.assertEqual((await outsider_socket.receive_json_from())['code'], 'not_found')
        finally:
            await customer_socket.disconnect()
            await worker_socket.disconnect()
            await outsider_socket.disconnect()

    async def test_invalid_token_is_rejected(self):
        communicator = WebsocketCommunicator(
            application, '/ws/chat/', headers=[(b'origin', b'http://testserver')],
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)
        await communicator.send_json_to({'type': 'auth', 'access_token': 'invalid'})
        event = await communicator.receive_output()
        self.assertEqual(event['type'], 'websocket.close')
        self.assertEqual(event['code'], 4401)
