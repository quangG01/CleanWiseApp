import json
import time
import uuid
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.utils import timezone
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.ai_engine.models import ChatbotMessage, ChatbotSession
from apps.bookings.models import Booking, BookingSchedule
from apps.payments.models import Payment
from apps.services.models import Service
from apps.worker.models import BookingAssignment
from .agent.factory import create_customer_agent, extract_answer
from .agent.schemas import AgentAnswer, AgentContext
from .agent.tools import CUSTOMER_TOOLS
from .exceptions import AgentUnavailable, ChatbotError
from .models import ChatbotRun
from .services import queries
from .services.conversation import _claim_run, _complete, committed_history
from .services.response import build_cards

User = get_user_model()


def create_fixture():
    customer = User.objects.create_user(username='bot-customer', email='bot-customer@test.com', role='CUSTOMER')
    other = User.objects.create_user(username='bot-other', email='bot-other@test.com', role='CUSTOMER')
    worker = User.objects.create_user(username='bot-worker', email='bot-worker@test.com', role='WORKER', first_name='Lan')
    service = Service.objects.create(code='HOME_CLEANING', section_code='HOME', name='Dọn nhà',
                                     description='Dọn căn hộ theo giờ', form_schema={'fields': []},
                                     pricing_config={'currency': 'VND', 'base_prices': {'3_HOURS': 210000}})
    address = CustomerAddress.objects.create(customer=customer, receiver_name='Khách', receiver_phone='0912345678',
                                              address_line='1 Đường A', ward='Phường A', city='TP.HCM')
    booking = Booking.objects.create(booking_code='CW-BOT-1', customer=customer, service=service,
                                     address=address, service_data={}, total_amount=Decimal('210000'), status='ASSIGNED')
    foreign_booking = Booking.objects.create(booking_code='CW-FOREIGN', customer=other, service=service,
                                             address=address, service_data={}, total_amount=Decimal('500000'))
    start = timezone.now() + timedelta(days=1)
    schedule = BookingSchedule.objects.create(booking=booking, sequence_no=1, scheduled_start=start,
                                               scheduled_end=start + timedelta(hours=3))
    BookingAssignment.objects.create(schedule=schedule, worker=worker, status='ACCEPTED')
    return customer, other, worker, service, booking, foreign_booking, schedule


class ChatbotApiTests(APITestCase):
    def setUp(self):
        cache.clear()
        (self.customer, self.other, self.worker, self.service, self.booking,
         self.foreign_booking, self.schedule) = create_fixture()
        self.conversation = ChatbotSession.objects.create(customer=self.customer)
        self.messages_url = f'/api/chatbot/conversations/{self.conversation.id}/messages/'
        self.client.force_authenticate(self.customer)

    def send(self, text='Đơn gần nhất của tôi?', key=None):
        return self.client.post(self.messages_url, {'text': text, 'client_message_id': str(key or uuid.uuid4())}, format='json')

    def test_authentication_and_customer_role(self):
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get('/api/chatbot/conversations/').status_code, 401)
        self.client.force_authenticate(self.worker)
        self.assertEqual(self.client.get('/api/chatbot/conversations/').status_code, 403)
        admin = User.objects.create_user(username='bot-admin', email='bot-admin@test.com', role='ADMIN', is_superuser=True)
        self.client.force_authenticate(admin)
        self.assertEqual(self.client.get('/api/chatbot/conversations/').status_code, 403)

    @patch('apps.chatbot.services.conversation.run_agent')
    def test_conversation_ownership_on_every_endpoint(self, agent):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(self.messages_url).status_code, 404)
        self.assertEqual(self.send().status_code, 404)
        url = f'/api/chatbot/conversations/{self.conversation.id}/'
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.patch(url, {'title': 'Changed'}).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)
        self.assertTrue(ChatbotSession.objects.filter(pk=self.conversation.id).exists())
        agent.assert_not_called()

    @patch('apps.chatbot.services.conversation.run_agent', return_value=AgentAnswer('Xin chào'))
    def test_delete_conversation_removes_transcript_and_runs_only_for_owner(self, agent):
        self.assertEqual(self.send().status_code, 201)
        other = ChatbotSession.objects.create(customer=self.other)
        url = f'/api/chatbot/conversations/{self.conversation.id}/'
        self.assertEqual(self.client.delete(url).status_code, 204)
        self.assertFalse(ChatbotSession.objects.filter(pk=self.conversation.id).exists())
        self.assertFalse(ChatbotMessage.objects.filter(session_id=self.conversation.id).exists())
        self.assertFalse(ChatbotRun.objects.filter(conversation_id=self.conversation.id).exists())
        self.assertTrue(ChatbotSession.objects.filter(pk=other.id).exists())
        self.assertEqual(self.client.get(self.messages_url).status_code, 404)
        self.assertEqual(self.client.delete(url).status_code, 404)

    def test_delete_busy_conversation_keeps_messages_and_run(self):
        run, _ = _claim_run(self.customer, self.conversation.id, 'Xin chào', uuid.uuid4())
        url = f'/api/chatbot/conversations/{self.conversation.id}/'
        self.assertEqual(self.client.delete(url).status_code, 409)
        self.assertTrue(ChatbotSession.objects.filter(pk=self.conversation.id).exists())
        self.assertTrue(ChatbotRun.objects.filter(pk=run.pk).exists())
        self.assertEqual(self.conversation.messages.count(), 1)

    @patch('apps.chatbot.services.conversation.connection')
    def test_delete_purges_all_checkpoint_attempts_for_only_this_conversation(self, db):
        db.vendor = 'postgresql'
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ('existing_table',)
        url = f'/api/chatbot/conversations/{self.conversation.id}/'
        self.assertEqual(self.client.delete(url).status_code, 204)
        deletes = [call for call in cursor.execute.call_args_list if call.args[0].startswith('DELETE')]
        self.assertEqual(len(deletes), 3)
        self.assertEqual(
            [call.args[0] for call in deletes],
            [f'DELETE FROM chatbot_checkpoints.{table} WHERE thread_id LIKE %s'
             for table in ('checkpoint_writes', 'checkpoint_blobs', 'checkpoints')],
        )
        for call in deletes:
            self.assertEqual(call.args[1], [f'cleanwise-chatbot:{self.conversation.id}:%'])

    def test_create_conversation_cannot_choose_owner(self):
        response = self.client.post('/api/chatbot/conversations/', {'title': 'Tư vấn', 'customer_id': self.other.id}, format='json')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(ChatbotSession.objects.get(pk=response.data['id']).customer_id, self.customer.id)

    @patch('apps.chatbot.services.conversation.run_agent')
    def test_reply_persistence_replay_and_card_validation(self, agent):
        agent.return_value = AgentAnswer('Đơn đã có nhân viên nhận.', [
            {'type': 'booking', 'id': self.foreign_booking.id},
            {'type': 'booking', 'id': self.booking.id},
            {'type': 'complaint', 'id': 1},
        ], {'total_tokens': 100})
        key = uuid.uuid4()
        response = self.send(key=key)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(len(response.data['assistant_message']['cards']), 1)
        self.assertEqual(response.data['assistant_message']['cards'][0]['booking_id'], self.booking.id)
        self.assertEqual(agent.call_args.kwargs['customer_id'], self.customer.id)
        replay = self.send(key=key)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.data['replayed'])
        self.assertEqual(ChatbotMessage.objects.filter(session=self.conversation).count(), 2)
        self.assertEqual(agent.call_count, 1)
        mismatch = self.send('Nội dung khác', key=key)
        self.assertEqual(mismatch.status_code, 422)
        history = self.client.get(self.messages_url)
        self.assertEqual(history.data['count'], 2)
        self.assertEqual([m['role'] for m in history.data['results']], ['user', 'assistant'])
        self.assertEqual(history.data['results'][0]['run_id'], str(ChatbotRun.objects.get().id))
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.title, 'Đơn gần nhất của tôi?')

    @patch('apps.chatbot.services.conversation.run_agent')
    def test_failure_is_retryable_without_duplicate_user_message(self, agent):
        agent.side_effect = [RuntimeError('sensitive provider detail'), AgentAnswer('Xin chào')]
        key = uuid.uuid4()
        first = self.send(key=key)
        self.assertEqual(first.status_code, 503)
        self.assertNotIn('sensitive provider detail', first.content.decode())
        self.assertEqual(ChatbotMessage.objects.get().status, 'FAILED')
        second = self.send(key=key)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(ChatbotMessage.objects.count(), 2)
        self.assertEqual(ChatbotRun.objects.get().attempts, 2)
        self.assertEqual(agent.call_args.kwargs['history'], [])

    @patch('apps.chatbot.services.conversation.run_agent', side_effect=AgentUnavailable('secret'))
    def test_missing_configuration_does_not_return_fake_reply(self, agent):
        response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(ChatbotRun.objects.get().error_code, 'CHATBOT_NOT_CONFIGURED')
        self.assertEqual(ChatbotMessage.objects.filter(sender_type='BOT').count(), 0)

    @patch('apps.chatbot.services.conversation.run_agent')
    def test_provider_error_is_classified_without_leaking_payload(self, agent):
        original = FakeProviderError('sensitive provider request')
        wrapped = RuntimeError('sensitive wrapper')
        wrapped.__cause__ = original
        agent.side_effect = wrapped
        response = self.send()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(ChatbotRun.objects.get().error_code, 'CHATBOT_PROVIDER_BUSY')
        self.assertNotIn('sensitive', response.content.decode())

    @patch('apps.chatbot.services.conversation.run_agent', side_effect=TimeoutError('sensitive timeout'))
    def test_model_timeout_has_distinct_code(self, agent):
        self.assertEqual(self.send().status_code, 503)
        self.assertEqual(ChatbotRun.objects.get().error_code, 'CHATBOT_MODEL_TIMEOUT')

    def test_busy_conversation_and_expired_attempt_fencing(self):
        key = uuid.uuid4()
        old, _ = _claim_run(self.customer, self.conversation.id, 'Xin chào', key)
        response = self.send(key=key, text='Xin chào')
        self.assertEqual(response.status_code, 409)
        ChatbotRun.objects.filter(pk=old.pk).update(lease_expires_at=timezone.now() - timedelta(seconds=1))
        new, _ = _claim_run(self.customer, self.conversation.id, 'Xin chào', key)
        self.assertNotEqual(old.attempt_id, new.attempt_id)
        self.assertNotEqual(old.checkpoint_thread_id, new.checkpoint_thread_id)
        with self.assertRaises(ChatbotError):
            _complete(old, AgentAnswer('Late reply'), [], 10)
        self.assertFalse(ChatbotMessage.objects.filter(sender_type='BOT').exists())

    @patch('apps.chatbot.services.conversation.run_agent', return_value=AgentAnswer('Được rồi'))
    def test_committed_history_only_and_outdated_retry(self, agent):
        first_key = uuid.uuid4()
        agent.side_effect = RuntimeError('Unavailable')
        self.assertEqual(self.send('Tin thất bại', first_key).status_code, 503)
        agent.side_effect = None
        self.assertEqual(self.send('Tin thành công').status_code, 201)
        self.assertEqual(self.send('Tin thất bại', first_key).status_code, 409)
        self.assertEqual(committed_history(self.conversation), [('Tin thành công', 'Được rồi')])
        self.send('Tiếp tục')
        self.assertEqual(agent.call_args.kwargs['history'], [('Tin thành công', 'Được rồi')])

    @patch('apps.chatbot.services.conversation.run_agent', return_value=AgentAnswer('Chào bạn'))
    def test_closed_conversation_input_limits_and_run_ownership(self, agent):
        self.assertEqual(self.send(' ').status_code, 400)
        self.assertEqual(self.send('x' * 2001).status_code, 400)
        self.assertEqual(self.client.post(self.messages_url, {'text': 'Hello', 'client_message_id': 'invalid'}, format='json').status_code, 400)
        response = self.send()
        run_url = '/api/chatbot/runs/' + response.data['run']['id'] + '/'
        self.assertEqual(self.client.get(run_url).status_code, 200)
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(run_url).status_code, 404)
        self.client.force_authenticate(self.customer)
        self.client.patch(f'/api/chatbot/conversations/{self.conversation.id}/', {'status': 'CLOSED'}, format='json')
        self.assertEqual(self.send().status_code, 409)

    def test_query_scope_accent_matching_payment_and_checkin(self):
        results = queries.search_services('don nha')['results']
        self.assertEqual(results[0]['id'], self.service.id)
        self.assertEqual(queries.list_my_bookings(self.customer.id)['count'], 1)
        with self.assertRaises(queries.ToolQueryError):
            queries.get_my_booking_detail(self.customer.id, str(self.foreign_booking.id))
        Payment.objects.create(booking=self.booking, customer=self.customer, amount=210000, method='CASH', status='PENDING')
        detail = queries.get_my_booking_detail(self.customer.id, self.booking.booking_code)
        self.assertTrue(detail['schedules'][0]['has_accepted_worker'])
        self.assertFalse(detail['schedules'][0]['has_checked_in'])
        self.assertEqual(detail['latest_payment']['status'], 'PENDING')
        self.assertNotIn('account_number', detail['latest_payment'])
        self.schedule.actual_start = timezone.now()
        self.schedule.save(update_fields=['actual_start'])
        self.assertTrue(queries.get_my_booking_detail(self.customer.id, self.booking.booking_code)['schedules'][0]['has_checked_in'])
        self.service.is_active = False
        self.service.save(update_fields=['is_active'])
        self.assertEqual(queries.search_services()['count'], 0)
        with self.assertRaises(queries.ToolQueryError):
            queries.get_service_details(self.service.id)
        self.assertEqual(build_cards(self.customer.id, [{'type': 'service', 'id': self.service.id}]), [])

    def test_schedule_pagination_remaining_count_and_date_filters(self):
        for sequence in range(2, 14):
            start = self.schedule.scheduled_start + timedelta(days=sequence)
            BookingSchedule.objects.create(booking=self.booking, sequence_no=sequence, scheduled_start=start,
                                             scheduled_end=start + timedelta(hours=3),
                                             status='CANCELLED' if sequence == 13 else 'PENDING')
        detail = queries.get_my_booking_detail(self.customer.id, self.booking.booking_code)
        self.assertEqual(detail['remaining_sessions'], 12)
        self.assertTrue(detail['schedules_has_next'])
        second = queries.get_my_booking_schedules(self.customer.id, self.booking.booking_code, page=2)
        self.assertEqual(len(second['results']), 3)
        local_day = timezone.localtime(self.schedule.scheduled_start).date().isoformat()
        self.assertEqual(queries.list_my_bookings(self.customer.id, date_from=local_day, date_to=local_day)['count'], 1)
        with self.assertRaises(queries.ToolQueryError):
            queries.list_my_bookings(self.customer.id, date_from='invalid')


class ScriptedChatModel(BaseChatModel):
    replies: list[Any]
    call_index: int = 0

    @property
    def _llm_type(self):
        return 'scripted-test-model'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.replies[self.call_index]
        self.call_index += 1
        if isinstance(message, Exception):
            raise message
        return ChatResult(generations=[ChatGeneration(message=message)])


class FakeProviderError(Exception):
    code = 503


class LangChainIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.customer, _, _, self.service, self.booking, self.foreign_booking, _ = create_fixture()

    def test_booking_filters_apply_before_latest_limit_and_pagination(self):
        self.booking.payment_status = 'PAID'
        self.booking.save(update_fields=['payment_status'])
        self.foreign_booking.customer = self.customer
        self.foreign_booking.save(update_fields=['customer'])
        latest = queries.list_my_bookings(self.customer.id, limit=1)
        self.assertEqual([b['id'] for b in latest['results']], [self.foreign_booking.id])
        self.assertTrue(latest['has_next'])
        paid = queries.list_my_bookings(self.customer.id, payment_status='PAID', limit=1)
        self.assertEqual([b['id'] for b in paid['results']], [self.booking.id])
        self.assertFalse(paid['has_next'])
        self.assertEqual(queries.list_my_bookings(self.customer.id, service_query='không tồn tại')['results'], [])
        matching = queries.list_my_bookings(self.customer.id, service_query=queries.normalized(self.service.name))
        self.assertEqual(matching['count'], 2)
        next_page = queries.list_my_bookings(self.customer.id, limit=1, page=2)
        self.assertEqual([b['id'] for b in next_page['results']], [self.booking.id])
        with self.assertRaises(queries.ToolQueryError):
            queries.list_my_bookings(self.customer.id, payment_status='INVALID')

    def test_agent_selects_one_relevant_card_from_discovery_list(self):
        self.foreign_booking.customer = self.customer
        self.foreign_booking.save(update_fields=['customer'])
        model = ScriptedChatModel(replies=[
            AIMessage(content='', tool_calls=[{'name': 'list_my_bookings', 'args': {},
                                               'id': 'discover', 'type': 'tool_call'}]),
            AIMessage(content='', tool_calls=[{'name': 'select_response_cards',
                'args': {'references': [{'type': 'booking', 'id': self.foreign_booking.id}]},
                'id': 'select', 'type': 'tool_call'}]),
            AIMessage(content=f'Đơn gần nhất là {self.foreign_booking.booking_code}.'),
        ])
        agent = create_customer_agent(model, InMemorySaver())
        result = agent.invoke({'messages': [HumanMessage(content='Đơn gần nhất?')]},
                              config={'configurable': {'thread_id': 'relevant-cards'}},
                              context=AgentContext(self.customer.id, time.monotonic() + 30))
        answer = extract_answer(result)
        self.assertEqual(answer.card_references, [{'type': 'booking', 'id': self.foreign_booking.id}])
        self.assertEqual([c['booking_id'] for c in build_cards(self.customer.id, answer.card_references)],
                         [self.foreign_booking.id])

    def test_real_prebuilt_agent_tool_loop_and_checkpoint_without_paid_model(self):
        model = ScriptedChatModel(replies=[
            AIMessage(content='', tool_calls=[{'name': 'list_my_bookings', 'args': {'customer_id': self.foreign_booking.customer_id, 'status': None}, 'id': 'call-1', 'type': 'tool_call'}]),
            AIMessage(content='', tool_calls=[{'name': 'get_my_booking_detail', 'args': {'booking_reference': self.booking.booking_code}, 'id': 'call-2', 'type': 'tool_call'}]),
            AIMessage(content='Đơn đã có nhân viên nhận, chưa có dữ liệu check-in.'),
        ])
        saver = InMemorySaver()
        agent = create_customer_agent(model, saver)
        config = {'configurable': {'thread_id': 'real-agent-test'}}
        result = agent.invoke({'messages': [HumanMessage(content='Đơn gần nhất?')]}, config=config,
                              context=AgentContext(self.customer.id, time.monotonic() + 30))
        answer = extract_answer(result)
        self.assertEqual(answer.usage['tool_calls'], 2)
        self.assertEqual(answer.usage['model_calls'], 3)
        self.assertTrue(any(ref['id'] == self.booking.id for ref in answer.card_references),
                        str([(type(m).__name__, m.content) for m in result['messages']]))
        self.assertNotIn(self.foreign_booking.booking_code, '\n'.join(str(m.content) for m in result['messages']))
        self.assertTrue(saver.get_tuple(config))

    @patch('langchain.agents.middleware.model_retry.time.sleep')
    def test_provider_503_retries_model_then_runs_booking_tool_once(self, sleep):
        model = ScriptedChatModel(replies=[
            FakeProviderError('private provider payload'),
            AIMessage(content='', tool_calls=[{'name': 'list_my_bookings', 'args': {},
                                               'id': 'retry-tool', 'type': 'tool_call'}]),
            AIMessage(content='Đơn gần nhất đã có nhân viên nhận.'),
        ])
        agent = create_customer_agent(model, InMemorySaver())
        result = agent.invoke({'messages': [HumanMessage(content='Đơn gần nhất?')]},
                              config={'configurable': {'thread_id': 'retry-booking'}},
                              context=AgentContext(self.customer.id, time.monotonic() + 30))
        answer = extract_answer(result)
        self.assertEqual(model.call_index, 3)
        self.assertEqual(answer.usage['tool_calls'], 1)
        self.assertEqual(answer.usage['model_calls'], 2)
        self.assertTrue(any(ref['id'] == self.booking.id for ref in answer.card_references))
        sleep.assert_called_once()

    @patch('langchain.agents.middleware.model_retry.time.sleep')
    def test_provider_503_stops_after_one_retry_without_fake_answer(self, sleep):
        model = ScriptedChatModel(replies=[FakeProviderError('first'), FakeProviderError('second')])
        agent = create_customer_agent(model, InMemorySaver())
        with self.assertRaises(FakeProviderError):
            agent.invoke({'messages': [HumanMessage(content='Đơn gần nhất?')]},
                         config={'configurable': {'thread_id': 'retry-exhausted'}},
                         context=AgentContext(self.customer.id, time.monotonic() + 30))
        self.assertEqual(model.call_index, 2)

    def test_provider_auth_error_is_not_retried(self):
        error = FakeProviderError('private key detail')
        error.code = 401
        model = ScriptedChatModel(replies=[error])
        agent = create_customer_agent(model, InMemorySaver())
        with self.assertRaises(FakeProviderError):
            agent.invoke({'messages': [HumanMessage(content='Đơn gần nhất?')]},
                         config={'configurable': {'thread_id': 'auth-error'}},
                         context=AgentContext(self.customer.id, time.monotonic() + 30))
        self.assertEqual(model.call_index, 1)

    def test_hidden_actor_and_no_write_or_complaint_tools(self):
        names = {tool.name for tool in CUSTOMER_TOOLS}
        self.assertEqual(names, {'search_services', 'get_service_details', 'list_my_bookings',
                                 'get_my_booking_detail', 'get_my_booking_schedules', 'select_response_cards', 'search_help_articles'})
        for tool in CUSTOMER_TOOLS:
            self.assertNotIn('runtime', tool.args)
            self.assertNotIn('customer_id', tool.args)

    def test_expired_run_does_not_call_model(self):
        model = ScriptedChatModel(replies=[AIMessage(content='Should not execute')])
        agent = create_customer_agent(model, InMemorySaver())
        with self.assertRaises(TimeoutError):
            agent.invoke({'messages': [HumanMessage(content='Dịch vụ?')]},
                         config={'configurable': {'thread_id': 'expired-test'}},
                         context=AgentContext(self.customer.id, time.monotonic() - 1))
        self.assertEqual(model.call_index, 0)

    @override_settings(CHATBOT_MAX_MODEL_CALLS=1)
    def test_model_call_budget_stops_tool_loop(self):
        model = ScriptedChatModel(replies=[
            AIMessage(content='', tool_calls=[{'name': 'search_services', 'args': {}, 'id': 'call-1', 'type': 'tool_call'}]),
            AIMessage(content='Should not execute'),
        ])
        agent = create_customer_agent(model, InMemorySaver())
        with self.assertRaises(Exception):
            agent.invoke({'messages': [HumanMessage(content='Dịch vụ?')]},
                         config={'configurable': {'thread_id': 'limit-test'}},
                         context=AgentContext(self.customer.id, time.monotonic() + 30))
        self.assertEqual(model.call_index, 1)


class ResponseCardSelectionTests(SimpleTestCase):
    def answer(self, tools, text='Kết quả phù hợp.'):
        return extract_answer({'messages': [HumanMessage(content='Tra đơn'), *tools, AIMessage(content=text)]})

    def discovery(self):
        return ToolMessage(content=json.dumps({'results': [
            {'id': 1, 'booking_code': 'CW-ONE'}, {'id': 2, 'booking_code': 'CW-TWO'}]}),
            name='list_my_bookings', tool_call_id='list', artifact={'cards': [
                {'type': 'booking', 'id': 1}, {'type': 'booking', 'id': 2}]})

    def test_unselected_discovery_list_is_not_automatically_sent(self):
        self.assertEqual(self.answer([self.discovery()]).card_references, [])
        self.assertEqual(self.answer([self.discovery()], 'Đơn CW-TWO đã thanh toán.').card_references,
                         [{'type': 'booking', 'id': 2}])

    def test_detail_does_not_include_other_discovered_orders(self):
        detail = ToolMessage(content='{}', name='get_my_booking_detail', tool_call_id='detail',
                             artifact={'cards': [{'type': 'booking', 'id': 2}]})
        self.assertEqual(self.answer([self.discovery(), detail]).card_references, [{'type': 'booking', 'id': 2}])

    def test_selection_requires_current_tool_results_and_preserves_order(self):
        selection = ToolMessage(content='OK', name='select_response_cards', tool_call_id='select',
            artifact={'selected_cards': [{'type': 'booking', 'id': 2}, {'type': 'booking', 'id': 99},
                                        {'type': 'booking', 'id': 1}, {'type': 'booking', 'id': 2}]})
        self.assertEqual(self.answer([self.discovery(), selection]).card_references,
                         [{'type': 'booking', 'id': 2}, {'type': 'booking', 'id': 1}])

    def test_empty_selection_does_not_fall_back_to_discovery_cards(self):
        selection = ToolMessage(content='OK', name='select_response_cards', tool_call_id='select',
                                artifact={'selected_cards': []})
        self.assertEqual(self.answer([self.discovery(), selection]).card_references, [])


class CheckpointConnectionTests(SimpleTestCase):
    @override_settings(CHATBOT_CHECKPOINT_DB_HOST='')
    def test_neon_checkpoint_uses_direct_endpoint_with_session_schema(self):
        from .agent.checkpoint import checkpoint_connection

        database = {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'test',
                    'HOST': 'ep-example-pooler.region.aws.neon.tech', 'OPTIONS': {'sslmode': 'require'}}
        with patch.dict(settings.DATABASES, {'default': database}), patch('psycopg.connect') as connect:
            checkpoint_connection()
        self.assertEqual(connect.call_args.kwargs['host'], 'ep-example.region.aws.neon.tech')
        self.assertEqual(connect.call_args.kwargs['sslmode'], 'require')
        self.assertIn('search_path=chatbot_checkpoints', connect.call_args.kwargs['options'])
        self.assertEqual(connect.call_args.kwargs['prepare_threshold'], 0)

    @override_settings(CHATBOT_CHECKPOINT_DB_HOST='direct.example.com')
    def test_explicit_checkpoint_host_overrides_main_database_pool(self):
        from .agent.checkpoint import checkpoint_connection

        database = {'ENGINE': 'django.db.backends.postgresql', 'NAME': 'test', 'HOST': 'pool.example.com'}
        with patch.dict(settings.DATABASES, {'default': database}), patch('psycopg.connect') as connect:
            checkpoint_connection()
        self.assertEqual(connect.call_args.kwargs['host'], 'direct.example.com')


class GeminiToolSchemaTests(SimpleTestCase):
    def test_converted_tool_schemas_have_no_empty_enum_values(self):
        from langchain_google_genai._function_utils import convert_to_genai_function_declarations

        def check_schema(value):
            if isinstance(value, dict):
                if 'enum' in value:
                    self.assertNotIn('', value['enum'])
                for nested in value.values():
                    check_schema(nested)
            elif isinstance(value, list):
                for nested in value:
                    check_schema(nested)

        tools = convert_to_genai_function_declarations(CUSTOMER_TOOLS)
        for tool in tools:
            check_schema(tool.model_dump(mode='json', exclude_none=True))

    def test_status_filter_is_optional_nullable_and_rejects_empty_enum(self):
        from pydantic import ValidationError
        from .agent.schemas import ListBookingsInput

        self.assertIsNone(ListBookingsInput().status)
        self.assertIsNone(ListBookingsInput(status=None).status)
        self.assertEqual(ListBookingsInput(status='IN_PROGRESS').status, 'IN_PROGRESS')
        with self.assertRaises(ValidationError):
            ListBookingsInput(status='')
