import copy
import json
import struct

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from rest_framework.test import APITestCase

from .help_content import IMAGE_ROOT, validate_guide_sections
from .models import HelpArticle
from .services.response import build_cards


class GuideContentTests(SimpleTestCase):
    def setUp(self):
        self.article = json.loads((IMAGE_ROOT.parent / 'customer_app_guide.json').read_text(encoding='utf-8'))[0]

    def test_complete_chapter_has_unique_topics_real_images_and_bilingual_steps(self):
        sections = self.article['sections']
        self.assertEqual(self.article['version'], 4)
        self.assertEqual(len(sections), 11)
        self.assertEqual(len({s['id'] for s in sections}), 11)
        self.assertEqual(sum(len(s['steps']) for s in sections), 29)
        validate_guide_sections(sections)
        for section in sections:
            self.assertTrue(section['text'])
            self.assertTrue(section['heading_en'])
            for step in section['steps']:
                for key in ['title_en', 'text_en', 'result_en']:
                    self.assertTrue(step[key])
                image = step['image']
                self.assertTrue(image['file'].startswith('app-v4-'))
                contents = (IMAGE_ROOT / image['file']).read_bytes()
                self.assertTrue(contents.startswith(b'\x89PNG\r\n\x1a\n'))
                self.assertEqual(struct.unpack('>II', contents[16:24]), (image['width'], image['height']))
                self.assertIn('ảnh chụp thật', image['alt'])
                self.assertIn('actual CleanWise', image['alt_en'])
        self.assertGreaterEqual(len({step['image']['file'] for section in sections for step in section['steps']}), 20)

    def test_unsafe_images_bad_markers_duplicate_ids_and_empty_steps_are_rejected(self):
        base = self.article['sections'][0]
        for change in ('../secret.png', 'https://example.org/a.png', 'missing-guide.png'):
            section = copy.deepcopy(base)
            section['steps'][0]['image']['file'] = change
            with self.assertRaises(ValidationError):
                validate_guide_sections([section])
        section = copy.deepcopy(base)
        section['steps'][0]['image']['markers'] = [{'x': 95, 'y': 0, 'width': 10, 'height': 10}]
        with self.assertRaises(ValidationError):
            validate_guide_sections([section])
        with self.assertRaises(ValidationError):
            validate_guide_sections([base, base])
        section = copy.deepcopy(base)
        section['steps'] = []
        with self.assertRaises(ValidationError):
            validate_guide_sections([section])
        validate_guide_sections([{'heading': 'Legacy', 'text': 'Legacy plain text.'}])


class GuideAPITests(APITestCase):
    def setUp(self):
        self.customer = get_user_model().objects.create_user(username='guide-customer', role='CUSTOMER')
        call_command('import_chatbot_help', publish=True, verbosity=0)
        self.article = HelpArticle.objects.get(slug='su-dung-app-khach-hang', status='PUBLISHED')

    def test_guide_metadata_and_images_are_available_without_exposing_other_files(self):
        self.client.force_authenticate(self.customer)
        response = self.client.get(f'/api/chatbot/help-articles/{self.article.pk}/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['title'], 'Hướng dẫn sử dụng ứng dụng khách hàng CleanWise')
        self.assertEqual(len(response.data['sections']), 11)
        self.client.force_authenticate(None)
        for image in {step['image']['file'] for section in self.article.sections for step in section['steps']}:
            response = self.client.get(f'/api/chatbot/help-images/{image}/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/png')
            response.close()
        for name in ['missing.png', 'secret.env', '..%2Fsecret.png']:
            self.assertEqual(self.client.get(f'/api/chatbot/help-images/{name}/').status_code, 404)

    def test_source_cards_only_link_to_real_section_ids(self):
        ref = {'type': 'help', 'id': self.article.pk, 'section_id': 'dia-chi'}
        card = build_cards(self.customer.pk, [ref])[0]
        self.assertEqual(card['section_id'], 'dia-chi')
        ref['section_id'] = 'not-a-section'
        self.assertNotIn('section_id', build_cards(self.customer.pk, [ref])[0])
