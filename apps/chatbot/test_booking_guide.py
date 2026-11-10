import json
import struct

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from .help_content import IMAGE_ROOT, validate_guide_sections
from .models import HelpArticle
from .services.response import build_cards


class BookingGuideContentTests(SimpleTestCase):
    def test_complete_bilingual_chapter_and_image_integrity(self):
        article = json.loads((IMAGE_ROOT.parent / 'customer_booking_guide.json').read_text(encoding='utf-8'))[0]
        sections = article['sections']
        self.assertEqual(article['slug'], 'dat-don-dich-vu')
        self.assertEqual(len(sections), 15)
        self.assertEqual(len({section['id'] for section in sections}), 15)
        self.assertEqual(sum(len(section['steps']) for section in sections), 40)
        validate_guide_sections(sections)
        photos = set()
        for section in sections:
            self.assertTrue(section['heading_en'].strip())
            for suffix in ('', '_en'):
                self.assertEqual(section['text'+suffix], '\n\n'.join(
                    f'{i+1}. {step["title"+suffix]}. {step["text"+suffix]} {step["result"+suffix]}'
                    for i, step in enumerate(section['steps'])))
            for step in section['steps']:
                for field in ('title', 'text', 'result', 'title_en', 'text_en', 'result_en'):
                    self.assertTrue(step[field].strip())
                image = step['image']
                contents = (IMAGE_ROOT / image['file']).read_bytes()
                self.assertEqual(contents[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', contents[16:24]), (image['width'], image['height']))
                self.assertTrue(image['alt_en'])
                if 'Ảnh chụp' in image['alt']:
                    photos.add(image['file'])
                else:
                    self.assertIn('Sơ đồ minh họa', image['alt'])
        self.assertGreaterEqual(len(photos), 18)

    def test_booking_safety_and_service_specific_controls_are_documented(self):
        article = json.loads((IMAGE_ROOT.parent / 'customer_booking_guide.json').read_text(encoding='utf-8'))[0]
        sections = {section['id']: section for section in article['sections']}
        self.assertIn('Tiếp theo', sections['tam-tinh-xac-nhan']['text'])
        self.assertIn('chưa phải gửi đơn', sections['tam-tinh-xac-nhan']['text'])
        self.assertIn('dấu ✓', sections['lich-mot-lan']['text'])
        self.assertIn('Tiền mặt không xuất hiện', sections['phuong-thuc-thanh-toan']['text'])
        self.assertIn('chưa có nghĩa tiền đã được thu', sections['kiem-tra-don']['text'])
        self.assertIn('trước khi tạo đơn mới', sections['mat-mang-het-han']['text'])


class BookingGuideAPITests(APITestCase):
    def test_default_import_keeps_latest_revision_and_all_topic_links_work(self):
        legacy = next(item for item in json.loads((IMAGE_ROOT.parent / 'help_articles.json').read_text(encoding='utf-8'))
                      if item['slug'] == 'dat-don-dich-vu')
        old = HelpArticle(**legacy, status='PUBLISHED')
        old.save()
        call_command('import_chatbot_help', publish=True, verbosity=0)
        article = HelpArticle.objects.get(slug='dat-don-dich-vu', status='PUBLISHED')
        self.assertEqual(article.version, 3)
        old.refresh_from_db()
        self.assertEqual(old.status, 'RETIRED')
        call_command('import_chatbot_help', publish=True, verbosity=0)
        self.assertEqual(HelpArticle.objects.filter(slug=article.slug).count(), 2)
        customer = get_user_model().objects.create_user(username='booking-guide-customer', role='CUSTOMER')
        self.client.force_authenticate(customer)
        response = self.client.get(f'/api/chatbot/help-articles/{article.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['sections']), 15)
        self.assertEqual(self.client.get(f'/api/chatbot/help-articles/{old.pk}/').status_code, 404)
        for section in article.sections:
            cards = build_cards(customer.pk, [{'type': 'help', 'id': article.pk, 'section_id': section['id']}])
            self.assertEqual(cards[0]['section_id'], section['id'])
        self.client.force_authenticate(None)
        for name in {step['image']['file'] for section in article.sections for step in section['steps']}:
            response = self.client.get(f'/api/chatbot/help-images/{name}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/png')
            response.close()
