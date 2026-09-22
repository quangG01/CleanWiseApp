from datetime import timedelta

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
            address=self.address, service_data={},
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

    def test_claim_reuses_conversation_and_creates_private_notices(self):
        first = self.claim()
        second = self.claim(schedule=self.make_schedule(72))
        self.assertEqual(ChatConversation.objects.count(), 1)
        self.assertEqual(ChatConversationAssignment.objects.count(), 2)
        self.assertEqual(ChatMessage.objects.filter(message_type='SYSTEM').count(), 4)

        self.client.force_authenticate(self.customer)
        customer_listing = self.client.get(reverse('chat-conversations')).data['data']['results'][0]
        self.assertIn('Nhân viên', customer_listing['last_message'])
        self.assertNotIn('Bạn đã nhận lịch', customer_listing['last_message'])
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
        self.assertEqual(len(customer_messages.data['data']['results']), 2)
        self.assertTrue(all(row['recipient_id'] == self.customer.id for row in customer_messages.data['data']['results']))
        self.client.force_authenticate(self.worker)
        worker_listing = self.client.get(reverse('chat-conversations')).data['data']['results'][0]
        self.assertIn('Bạn đã nhận lịch', worker_listing['last_message'])
        worker_messages = self.client.post(reverse('chat-message-list'), {'conversation_id': conversation_id}, format='json')
        self.assertEqual(len(worker_messages.data['data']['results']), 2)
        self.assertTrue(all(row['recipient_id'] == self.worker.id for row in worker_messages.data['data']['results']))

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
        self.assertEqual(listing.data['data']['results'][0]['unread_count'], 2)
        self.assertEqual(listing.data['data']['total_unread'], 2)
        read = self.client.post(reverse('chat-message-read'), {'conversation_id': conversation.id}, format='json')
        self.assertEqual(read.data['data']['marked_read'], 2)
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
        self.assertEqual(before['results'][0]['unread_count'], 2)
        self.assertEqual(before['total_unread'], 2)
        read = self.client.post(reverse('chat-message-read'), {
            'conversation_id': conversation.id,
        }, format='json')
        self.assertEqual(read.data['data']['marked_read'], 2)
        after = self.client.get(reverse('chat-conversations')).data['data']
        self.assertEqual(after['results'][0]['unread_count'], 0)
        self.assertEqual(after['total_unread'], 0)

    def test_same_pair_reuses_chat_across_bookings(self):
        first = self.claim()
        second_booking = Booking.objects.create(
            booking_code='CHAT-002', customer=self.customer, service=self.service,
            address=self.address, service_data={},
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
        self.assertEqual(len(older['results']), 2)
        self.assertIsNone(older['next_cursor'])
