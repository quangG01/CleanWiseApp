import json
import struct

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from .help_content import IMAGE_ROOT, validate_guide_sections
from .models import HelpArticle
from .services.response import build_cards


class PaymentGuideContentTests(SimpleTestCase):
    def test_all_topics_have_bilingual_steps_and_correct_png_dimensions(self):
        article = json.loads((IMAGE_ROOT.parent / 'customer_payment_guide.json').read_text(encoding='utf-8'))[0]
        self.assertEqual(len(article['sections']), 12)
        self.assertEqual(article['version'], 3)
        self.assertEqual(sum(len(s['steps']) for s in article['sections']), 36)
        screenshots = [step['image'] for section in article['sections'] for step in section['steps']
                       if step['image']['file'].startswith('payment-v3-')]
        self.assertEqual(len(screenshots), 12)
        topup = next(s for s in article['sections'] if s['id'] == 'nap-tien')
        self.assertIn('cùng yêu cầu', topup['steps'][2]['text'])
        self.assertIn('same request', topup['steps'][2]['text_en'])
        validate_guide_sections(article['sections'])
        for section in article['sections']:
            self.assertTrue(section['heading_en'])
            self.assertTrue(section['text_en'])
            for step in section['steps']:
                for field in ('title', 'text', 'result', 'title_en', 'text_en', 'result_en'):
                    self.assertTrue(step[field].strip())
                image = step['image']
                contents = (IMAGE_ROOT / image['file']).read_bytes()
                self.assertEqual(contents[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', contents[16:24]), (image['width'], image['height']))
                self.assertIn('minh họa', image['alt'])
        bank = next(s for s in article['sections'] if s['id'] == 'ngan-hang')
        self.assertIn('chưa dùng để rút tiền', bank['text'])
        withdraw = next(s for s in article['sections'] if s['id'] == 'rut-tien')
        self.assertIn('6 số', withdraw['text'])
        self.assertIn('Gửi mã OTP', withdraw['text'])


class PaymentGuideAPITests(APITestCase):
    def test_current_chapter_deep_links_images_and_immutable_revisions(self):
        customer = get_user_model().objects.create_user(username='payment-guide-customer', role='CUSTOMER')
        self.client.force_authenticate(customer)
        call_command('import_chatbot_help', publish=True, verbosity=0)
        article = HelpArticle.objects.get(slug='thanh-toan-va-vi', status='PUBLISHED')
        response = self.client.get(f'/api/chatbot/help-articles/{article.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Hướng dẫn thanh toán và sử dụng Ví CleanWise')
        self.assertEqual(len(response.data['sections']), 12)
        for section in article.sections:
            cards = build_cards(customer.pk, [{'type': 'help', 'id': article.pk, 'section_id': section['id']}])
            self.assertEqual(cards[0]['section_id'], section['id'])
        call_command('import_chatbot_help', publish=True, verbosity=0)
        self.assertEqual(HelpArticle.objects.filter(slug=article.slug).count(), 1)
        self.client.force_authenticate(None)
        image = article.sections[0]['steps'][0]['image']['file']
        response = self.client.get(f'/api/chatbot/help-images/{image}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        response.close()
