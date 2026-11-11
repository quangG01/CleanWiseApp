import uuid
from unittest.mock import patch

from django.test import SimpleTestCase

from .agent.factory import create_customer_agent, create_worker_agent
from .serializers import MessageInputSerializer


class ChatbotLanguageTests(SimpleTestCase):
    def test_message_language_defaults_to_vietnamese_and_rejects_unknown_values(self):
        data = {'text': 'Xin chào', 'client_message_id': str(uuid.uuid4())}
        for language in (None, 'vi', 'en', 'fr'):
            with self.subTest(language=language):
                payload = {**data, **({'language': language} if language else {})}
                serializer = MessageInputSerializer(data=payload)
                self.assertEqual(serializer.is_valid(), language != 'fr')
                if language != 'fr':
                    self.assertEqual(serializer.validated_data['language'], language or 'vi')
                    self.assertEqual(serializer.validated_data['text'], data['text'])

    @patch('apps.chatbot.agent.factory.create_agent')
    def test_both_agents_use_selected_language_without_mutating_shared_prompts(self, create):
        for factory in (create_customer_agent, create_worker_agent):
            with self.subTest(factory=factory.__name__):
                factory(None, None, language='en')
                prompt = create.call_args.kwargs['system_prompt']
                self.assertIn('Reply in English', prompt)
                self.assertNotIn('Trả lời tiếng Việt', prompt)
                self.assertIn('Keep names, addresses and booking codes unchanged', prompt)
                factory(None, None)
                self.assertIn('Trả lời tiếng Việt', create.call_args.kwargs['system_prompt'])
