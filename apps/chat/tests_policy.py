from datetime import timedelta
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase, TransactionTestCase, override_settings, RequestFactory, skipUnlessDBFeature
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from . import tests_websocket as fixtures
from .admin import ChatRestrictionAdmin
from .models import ChatMessage, ChatViolation, ChatRestriction, ChatRestrictionAudit, ChatSendAttempt
from .redaction import redact_contacts
from .service import ensure_chat_for_assignment


class RedactionTests(SimpleTestCase):
    def test_redacts_all_contacts_preserving_original_prose(self):
        original = 'Chị đến 9h30, phòng 1205. Gọi ０９１２\u200b３４５６７８; a [at] mail [dot] com; https://example.org/contact'
        safe, categories, meaningful = redact_contacts(original)
        self.assertEqual(safe, 'Chị đến 9h30, phòng 1205. Gọi [SĐT đã ẩn]; [Email đã ẩn]; [Liên kết đã ẩn]')
        self.assertEqual(set(categories), {'PHONE_NUMBER', 'EMAIL_ADDRESS', 'EXTERNAL_LINK'})
        self.assertTrue(meaningful)

    def test_contact_only_and_spoken_phone(self):
        self.assertFalse(redact_contacts('0912345678')[2])
        self.assertEqual(redact_contacts('SĐT không chín một hai ba bốn năm sáu bảy tám')[0], 'SĐT [SĐT đã ẩn]')
        self.assertEqual(redact_contacts('a@example.org')[0], '[Email đã ẩn]')

    @override_settings(CHAT_ALLOWED_LINK_HOSTS=('cleanwise.vn',))
    def test_exact_allowlist_and_external_url_variants(self):
        self.assertEqual(redact_contacts('Xem https://cleanwise.vn/help')[1], [])
        for url in ('example.com', 'www.example.org/a', 'https://cleanwise.vn.evil.org/a',
                    'https://cleanwise.vn@evil.org/a', 'https://evil.org/cleanwise.vn',
                    'https://help.cleanwise.vn', 'ftp://cleanwise.vn/a', 'https://example.org/0912345678'):
            with self.subTest(url=url):
                self.assertEqual(redact_contacts(url)[0], '[Liên kết đã ẩn]')
        self.assertEqual(redact_contacts('https://cléanwise.vn/help')[0], '[Liên kết đã ẩn]')

    def test_work_details_are_not_contacts(self):
        for text in ('Đến 9h30, tầng 12, phòng 1205, diện tích 100m2.',
                     'Địa chỉ 123 Nguyễn Trãi, mã đơn CW202610230001.', 'STK 0912345678'):
            self.assertEqual(redact_contacts(text)[0], text)
            self.assertEqual(redact_contacts(text)[1], [])


@override_settings(ALLOWED_HOSTS=['testserver'])
class ChatPolicyTests(TransactionTestCase):
    def setUp(self):
        fixtures.ChatWebSocketTests.setUp(self)
        self.conversation = ensure_chat_for_assignment(self.assignment)
        self.client = APIClient()
        self.client.force_authenticate(self.customer)

    def send(self, text='Gọi 0912345678 nhé', key=None):
        payload = {'conversation_id': self.conversation.pk, 'message': text}
        if key:
            payload['client_message_id'] = key
        return self.client.post(reverse('chat-message-send'), payload, format='json')

    def expire_lock(self):
        ChatRestriction.objects.filter(user=self.customer).update(locked_until=timezone.now() - timedelta(seconds=1))

    def test_warning_masking_preview_and_history_for_both_roles(self):
        for user in (self.customer, self.worker):
            self.client.force_authenticate(user)
            response = self.send('Đến 9h30 nhé, 0912345678 a@example.com example.org')
            self.assertEqual(response.status_code, 201, response.data)
            data = response.data['data']
            self.assertEqual(data['moderation']['violation_count'], 1)
            self.assertEqual(data['message'], 'Đến 9h30 nhé, [SĐT đã ẩn] [Email đã ẩn] [Liên kết đã ẩn]')
            inbox = self.client.get(reverse('chat-conversations')).data['data']['results'][0]
            self.assertNotIn('0912345678', inbox['last_message'])
            history = self.client.post(reverse('chat-message-list'), {'conversation_id': self.conversation.pk}, format='json')
            self.assertNotIn('0912345678', str(history.data))
        self.assertEqual(ChatViolation.objects.count(), 2)
        self.assertFalse(ChatRestriction.objects.filter(locked_until__isnull=False).exists())

    def test_escalation_lock_expiry_and_unaffected_reading(self):
        for count in range(1, 8):
            before = timezone.now()
            response = self.send(key=f'violation-{count}')
            self.assertEqual(ChatViolation.objects.filter(user=self.customer).count(), count)
            if count <= 3:
                self.assertEqual(response.status_code, 201, response.data)
                continue
            self.assertEqual(response.status_code, 403, response.data)
            self.assertEqual(response.data['error_code'], 'CHAT_SEND_LOCKED')
            days = {4: 1, 5: 3}.get(count, 7)
            until = ChatRestriction.objects.get(user=self.customer).locked_until
            self.assertAlmostEqual((until - before).total_seconds(), days * 86400, delta=5)
            blocked = self.send('Chào bạn', key=f'locked-{count}')
            self.assertEqual(blocked.status_code, 403)
            self.assertEqual(ChatViolation.objects.filter(user=self.customer).count(), count)
            self.assertEqual(self.client.get(reverse('chat-conversation-detail', args=[self.conversation.pk])).status_code, 200)
            self.assertEqual(self.client.post(reverse('chat-message-list'), {'conversation_id': self.conversation.pk}).status_code, 200)
            self.customer.refresh_from_db()
            self.assertTrue(self.customer.is_active)
            self.expire_lock()
            self.assertEqual(self.send('Đến lúc 9h30 nhé').status_code, 201)

    def test_idempotency_of_saved_and_rejected_sends(self):
        first = self.send(key='saved')
        second = self.send(key='saved')
        self.assertEqual(first.data['data']['id'], second.data['data']['id'])
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(ChatViolation.objects.count(), 1)
        for _ in range(2):
            response = self.send('0912345678', key='contact-only')
            self.assertEqual(response.status_code, 400)
        self.assertEqual(ChatViolation.objects.count(), 2)
        self.assertEqual(ChatMessage.objects.count(), 1)
        self.assertEqual(self.send('Thay nội dung', key='saved').status_code, 403)
        self.assertNotIn('0912345678', str(list(ChatSendAttempt.objects.values())))

    def test_locked_threshold_rejection_commits_and_deduplicates(self):
        for number in range(3):
            self.send(key=f'warning-{number}')
        for _ in range(2):
            response = self.send(key='lock-threshold')
            self.assertEqual(response.status_code, 403)
        self.assertEqual(ChatViolation.objects.count(), 4)
        self.assertEqual(ChatMessage.objects.count(), 3)
        self.assertTrue(ChatRestriction.objects.get(user=self.customer).locked_until)

    def test_rolling_window_and_unauthorized_attempts(self):
        self.send()
        ChatViolation.objects.update(created_at=timezone.now() - timedelta(days=31))
        self.assertEqual(self.send().data['data']['moderation']['violation_count'], 1)
        self.client.force_authenticate(self.outsider)
        self.assertEqual(self.send().status_code, 404)
        self.assertFalse(ChatViolation.objects.filter(user=self.outsider).exists())

    def test_admin_unlock_audited_without_erasing_history(self):
        for _ in range(4):
            self.send()
        request = RequestFactory().post('/admin/')
        request.user = self.worker
        model_admin = ChatRestrictionAdmin(ChatRestriction, AdminSite())
        model_admin.unlock_chat(request, ChatRestriction.objects.filter(user=self.customer))
        self.assertIsNone(ChatRestriction.objects.get(user=self.customer).locked_until)
        self.assertEqual(ChatRestrictionAudit.objects.get().administrator, self.worker)
        self.assertEqual(ChatViolation.objects.count(), 4)
        self.assertEqual(self.send('Chào bạn').status_code, 201)

    def test_blocked_solicitation_is_recorded_without_publishing(self):
        with patch('apps.chat.service.publish_message') as publish:
            self.assertEqual(self.send('Lần tới mình làm riêng cho tiện nha').status_code, 400)
            publish.assert_not_called()
        self.assertEqual(ChatViolation.objects.count(), 1)
        self.assertFalse(ChatMessage.objects.exists())

    def test_count_and_lock_apply_across_conversations(self):
        from apps.worker.models import BookingAssignment
        from django.contrib.auth import get_user_model
        worker = get_user_model().objects.create_user(username='second-worker', role='WORKER')
        from apps.bookings.models import BookingSchedule
        first_schedule = self.assignment.schedule
        schedule = BookingSchedule.objects.create(booking=first_schedule.booking, sequence_no=2,
                                                   scheduled_start=first_schedule.scheduled_start + timedelta(days=1),
                                                   scheduled_end=first_schedule.scheduled_end + timedelta(days=1))
        assignment = BookingAssignment.objects.create(schedule=schedule, worker=worker, status='ACCEPTED')
        other_conversation = ensure_chat_for_assignment(assignment)
        for _ in range(3):
            self.send()
        original = self.conversation
        self.conversation = other_conversation
        self.assertEqual(self.send().status_code, 403)
        self.conversation = original
        self.assertEqual(self.send('Chào bạn').status_code, 403)
        # The other participant retains their own sending permissions.
        self.client.force_authenticate(self.worker)
        self.assertEqual(self.send('Tôi đến lúc 9h30').status_code, 201)

    @skipUnlessDBFeature('has_select_for_update')
    def test_concurrent_sends_cannot_skip_lock_threshold(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from django.db import close_old_connections
        from .service import send_text_message
        from .policy import ChatPolicyError
        self.send()
        self.send()
        barrier = Barrier(2)

        def send(number):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                try:
                    send_text_message(self.customer, {'conversation_id': self.conversation.pk,
                                                      'message': 'Gọi 0912345678 nhé', 'client_message_id': f'parallel-{number}'})
                    return 'SENT'
                except ChatPolicyError as exc:
                    return exc.default_code
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(send, (1, 2)))
        self.assertCountEqual(outcomes, ['SENT', 'CHAT_SEND_LOCKED'])
        self.assertEqual(ChatViolation.objects.count(), 4)
