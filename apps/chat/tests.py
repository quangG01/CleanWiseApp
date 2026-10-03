from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.services.models import Service
from apps.worker.assignment_service import admin_assign_worker, claim_schedule
from apps.worker.models import Area, WorkerWorkingArea

from .models import ChatConversation, ChatConversationAssignment, ChatMessage


User = get_user_model()


class ChatApiTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='chat-customer', email='chat-customer@example.com', password='test',
            first_name='Khách', role=User.Role.CUSTOMER,
        )
        self.worker = self.make_worker('chat-worker')
        self.other_worker = self.make_worker('other-worker')
        self.outsider = User.objects.create_user(
            username='chat-outsider', email='chat-outsider@example.com', password='test',
            role=User.Role.CUSTOMER,
        )
        self.admin = User.objects.create_user(
            username='chat-admin', email='chat-admin@example.com', password='test',
            role=User.Role.ADMIN,
        )
        self.service = Service.objects.create(
            code='CHAT_TEST', section_code='HOME', name='Dọn dẹp', description='Test',
            form_schema={}, pricing_config={},
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer, receiver_name='Khách', receiver_phone='0912345678',
            address_line='1 Nguyễn Huệ', city='TP.HCM',
        )
        self.area = Area.objects.create(name='TP.HCM', city='TP.HCM')
        for worker in (self.worker, self.other_worker):
            WorkerProfile.objects.create(user=worker, status=WorkerProfile.Status.ACTIVE, registered_service=self.service)
            WorkerWorkingArea.objects.create(worker=worker, area=self.area)
        self.booking = Booking.objects.create(
            booking_code='CHAT-001', customer=self.customer, service=self.service,
            address=self.address, service_data={}, payment_status=Booking.PaymentStatus.PAID,
        )
        self.schedule = self.make_schedule(48)

    @staticmethod
    def make_worker(username):
        return User.objects.create_user(
            username=username, email=f'{username}@example.com', password='test',
            first_name=username, role=User.Role.WORKER,
        )

    def make_schedule(self, hours_ahead, booking=None):
        booking = booking or self.booking
        start = timezone.now() + timedelta(hours=hours_ahead)
        return BookingSchedule.objects.create(
            booking=booking, sequence_no=booking.schedules.count() + 1,
            scheduled_start=start, scheduled_end=start + timedelta(hours=2),
        )

    def claim(self, schedule=None, worker=None):
        return claim_schedule(schedule_id=(schedule or self.schedule).id, worker=worker or self.worker)

    def test_claim_reuses_conversation_without_creating_messages(self):
        first = self.claim()
        second = self.claim(schedule=self.make_schedule(72))
        self.assertEqual(ChatConversation.objects.count(), 1)
        self.assertEqual(ChatConversationAssignment.objects.count(), 2)
        self.assertFalse(ChatMessage.objects.exists())

        self.client.force_authenticate(self.customer)
        customer_listing = self.client.get(reverse('chat-conversations')).data['data']['results'][0]
        self.assertIsNone(customer_listing['last_message'])
        self.assertEqual(customer_listing['unread_count'], 0)
        self.assertTrue(customer_listing['can_send'])
        self.assertEqual(customer_listing['latest_assignment']['assignment_id'], second.id)
        first_chat = self.client.get(reverse('chat-by-assignment', args=[first.id]))
        second_chat = self.client.get(reverse('chat-by-assignment', args=[second.id]))
        self.assertEqual(first_chat.status_code, 200, first_chat.data)
        self.assertEqual(first_chat.data['data']['conversation']['id'], second_chat.data['data']['conversation']['id'])
        self.assertEqual(first_chat.data['data']['assignment']['schedule_id'], self.schedule.id)

        booking_detail = self.client.get(reverse('customer-booking-detail', args=[self.booking.id]))
        self.assertEqual(booking_detail.data['data']['schedules'][0]['assignment_id'], first.id)
        self.assertEqual(
            booking_detail.data['data']['schedules'][0]['conversation_id'],
            first_chat.data['data']['conversation']['id'],
        )

        conversation_id = first_chat.data['data']['conversation']['id']
        customer_messages = self.client.post(reverse('chat-message-list'), {'conversation_id': conversation_id}, format='json')
        self.assertEqual(customer_messages.data['data']['results'], [])
        self.client.force_authenticate(self.worker)
        worker_listing = self.client.get(reverse('chat-conversations')).data['data']['results'][0]
        self.assertIsNone(worker_listing['last_message'])
        self.assertEqual(worker_listing['unread_count'], 0)
        worker_messages = self.client.post(reverse('chat-message-list'), {'conversation_id': conversation_id}, format='json')
        self.assertEqual(worker_messages.data['data']['results'], [])

    def test_send_read_and_outsider_access(self):
        self.claim()
        conversation = ChatConversation.objects.get()
        self.client.force_authenticate(self.customer)
        sent = self.client.post(reverse('chat-message-send'), {
            'conversation_id': conversation.id, 'message': '  Chào anh  ', 'sender_id': self.worker.id,
        }, format='json')
        self.assertEqual(sent.status_code, 201, sent.data)
        self.assertEqual(sent.data['data']['sender_id'], self.customer.id)
        self.assertEqual(sent.data['data']['message'], 'Chào anh')
        self.assertEqual(self.client.post(reverse('chat-message-send'), {
            'conversation_id': conversation.id, 'message': '  ',
        }, format='json').status_code, 400)

        self.client.force_authenticate(self.worker)
        listing = self.client.get(reverse('chat-conversations'))
        self.assertEqual(listing.data['data']['results'][0]['unread_count'], 1)
        self.assertEqual(listing.data['data']['total_unread'], 1)
        read = self.client.post(reverse('chat-message-read'), {'conversation_id': conversation.id}, format='json')
        self.assertEqual(read.data['data']['marked_read'], 1)
        read_listing = self.client.get(reverse('chat-conversations')).data['data']
        self.assertEqual(read_listing['results'][0]['unread_count'], 0)
        self.assertEqual(read_listing['total_unread'], 0)

        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.client.get(reverse('chat-conversation-detail', args=[conversation.id])).status_code, 404)
        self.assertEqual(self.client.post(reverse('chat-message-list'), {'conversation_id': conversation.id}, format='json').status_code, 404)
        self.assertEqual(self.client.post(reverse('chat-message-send'), {
            'conversation_id': conversation.id, 'message': 'Không được phép',
        }, format='json').status_code, 404)

    def test_customer_read_clears_conversation_and_tab_counts(self):
        self.claim()
        conversation = ChatConversation.objects.get()
        self.client.force_authenticate(self.worker)
        self.client.post(reverse('chat-message-send'), {
            'conversation_id': conversation.id, 'message': 'Tôi sẽ đến đúng giờ.',
        }, format='json')

        self.client.force_authenticate(self.customer)
        before = self.client.get(reverse('chat-conversations')).data['data']
        self.assertEqual(before['results'][0]['unread_count'], 1)
        self.assertEqual(before['total_unread'], 1)
        read = self.client.post(reverse('chat-message-read'), {
            'conversation_id': conversation.id,
        }, format='json')
        self.assertEqual(read.data['data']['marked_read'], 1)
        after = self.client.get(reverse('chat-conversations')).data['data']
        self.assertEqual(after['results'][0]['unread_count'], 0)
        self.assertEqual(after['total_unread'], 0)

    def test_same_pair_reuses_chat_across_bookings(self):
        first = self.claim()
        second_booking = Booking.objects.create(
            booking_code='CHAT-002', customer=self.customer, service=self.service,
            address=self.address, service_data={}, payment_status=Booking.PaymentStatus.PAID,
        )
        second = self.claim(schedule=self.make_schedule(96, booking=second_booking))
        self.assertEqual(first.chat_link.conversation_id, second.chat_link.conversation_id)
        self.assertEqual(ChatConversation.objects.count(), 1)
        self.assertEqual(ChatConversationAssignment.objects.count(), 2)

    def test_reassignment_keeps_old_history_private_and_stops_sending(self):
        first = self.claim()
        old_conversation = ChatConversation.objects.get()
        first.status = 'CANCELLED'
        first.save(update_fields=['status'])
        second = admin_assign_worker(
            schedule_id=self.schedule.id, worker_id=self.other_worker.id,
            admin_user=self.admin,
        )
        self.assertEqual(ChatConversation.objects.count(), 2)
        self.client.force_authenticate(self.worker)
        denied = self.client.post(reverse('chat-message-send'), {
            'conversation_id': old_conversation.id, 'message': 'Tin cũ',
        }, format='json')
        self.assertEqual(denied.status_code, 403)
        new_conversation = second.chat_link.conversation
        self.assertEqual(self.client.get(reverse('chat-conversation-detail', args=[new_conversation.id])).status_code, 404)
        self.client.force_authenticate(self.other_worker)
        self.assertEqual(self.client.get(reverse('chat-conversation-detail', args=[old_conversation.id])).status_code, 404)

    def test_cursor_returns_only_older_visible_messages(self):
        self.claim()
        conversation = ChatConversation.objects.get()
        self.client.force_authenticate(self.customer)
        for text in ('Một', 'Hai', 'Ba'):
            self.client.post(reverse('chat-message-send'), {
                'conversation_id': conversation.id, 'message': text,
            }, format='json')
        recent = self.client.post(reverse('chat-message-list'), {
            'conversation_id': conversation.id, 'limit': 2,
        }, format='json').data['data']
        older = self.client.post(reverse('chat-message-list'), {
            'conversation_id': conversation.id, 'limit': 2, 'cursor': recent['next_cursor'],
        }, format='json').data['data']
        self.assertEqual([row['message'] for row in recent['results']], ['Hai', 'Ba'])
        self.assertEqual([row['message'] for row in older['results']], ['Một'])
        self.assertIsNone(older['next_cursor'])

    def test_legacy_notices_are_hidden_and_do_not_count_as_unread(self):
        assignment = self.claim()
        conversation = ChatConversation.objects.get()
        messages = [
            (self.customer, 'Nhân viên Test đã nhận lịch làm ngày 01/10/2026 08:00. Bạn có thể liên hệ với nhân viên tại đây.'),
            (self.worker, 'Bạn đã nhận lịch làm ngày 01/10/2026 08:00 của khách hàng Test. Hãy liên hệ với khách hàng để trao đổi.'),
        ]
        for user, text in messages:
            notice = ChatMessage.objects.create(
                conversation=conversation, recipient=user, related_assignment=assignment,
                message_type='SYSTEM', message=text,
            )
            self.client.force_authenticate(user)
            listing = self.client.get(reverse('chat-conversations')).data['data']
            self.assertEqual(listing['count'], 1)
            self.assertEqual(listing['total_unread'], 0)
            self.assertIsNone(listing['results'][0]['last_message'])
            history = self.client.post(reverse('chat-message-list'), {'conversation_id': conversation.pk}, format='json')
            self.assertEqual(history.data['data']['results'], [])
            read = self.client.post(reverse('chat-message-read'), {'conversation_id': conversation.pk}, format='json')
            self.assertEqual(read.data['data']['marked_read'], 0)
            with patch('apps.chat.realtime.get_channel_layer') as layer:
                from .realtime import publish_message
                publish_message(notice.pk)
                layer.assert_not_called()
        self.assertEqual(ChatMessage.objects.count(), 2)

    def test_other_system_messages_and_user_text_are_preserved(self):
        assignment = self.claim()
        conversation = ChatConversation.objects.get()
        system = ChatMessage.objects.create(
            conversation=conversation, recipient=self.customer, related_assignment=assignment,
            message_type='SYSTEM', message='Cuộc trò chuyện đã được cập nhật.',
        )
        text = ChatMessage.objects.create(
            conversation=conversation, sender=self.worker,
            message='Nhân viên Test đã nhận lịch làm ngày mai.',
        )
        self.client.force_authenticate(self.customer)
        history = self.client.post(reverse('chat-message-list'), {'conversation_id': conversation.pk}, format='json')
        self.assertEqual({row['id'] for row in history.data['data']['results']}, {system.pk, text.pk})
        self.assertEqual(self.client.get(reverse('chat-conversations')).data['data']['total_unread'], 2)
        self.client.force_authenticate(self.worker)
        history = self.client.post(reverse('chat-message-list'), {'conversation_id': conversation.pk}, format='json')
        self.assertEqual([row['id'] for row in history.data['data']['results']], [text.pk])

    def test_repeated_chat_link_does_not_publish_another_conversation_event(self):
        assignment = self.claim()
        from .service import ensure_chat_for_assignment
        with patch('apps.chat.service.publish_conversation') as publish:
            with self.captureOnCommitCallbacks(execute=True):
                ensure_chat_for_assignment(assignment)
            publish.assert_not_called()
        self.assertFalse(ChatMessage.objects.exists())
