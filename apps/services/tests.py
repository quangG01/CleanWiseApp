import json
from io import BytesIO
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from cloudinary.exceptions import Error as CloudinaryError

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.http import Http404
from rest_framework.test import APIClient, APITestCase

from apps.addresses.models import CustomerAddress
from apps.bookings.booking_service import create_booking
from apps.bookings.models import Booking
from .models import Service

User = get_user_model()


class ServiceManagementTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_user(username='service-admin', role='ADMIN', email='service-admin@test.com')
        self.customer = User.objects.create_user(username='service-customer', role='CUSTOMER', email='service-customer@test.com')
        self.service = Service.objects.create(code='HOME_CLEANING_HOURLY', section_code='HOME_CLEANING', name='Dọn nhà',
            description='Dọn nhà theo giờ', form_schema={'fields': [{'key': 'task_checklist_anchor', 'type': 'TASK_CHECKLIST', 'label': ''}], 'version': 6},
            pricing_config={'base_prices': {'2_HOURS': 150000}, 'currency': 'VND'})
        self.url = f'/api/admin/services/{self.service.pk}/'
        self.client.force_authenticate(self.admin)
        self.public = APIClient()

    def payload(self, response):
        data = response.json()
        while isinstance(data, dict) and 'data' in data:
            data = data['data']
        return data

    def option_image_file(self):
        output = BytesIO()
        Image.new('RGB', (2, 2), 'blue').save(output, format='PNG')
        return SimpleUploadedFile('option.png', output.getvalue(), content_type='image/png')

    @patch('apps.services.views.upload_image')
    def test_upload_option_image_and_save_url_in_nested_schema(self, upload):
        url = 'https://res.cloudinary.com/test/image/upload/service_option.png'
        upload.return_value = {'url': url}
        response = self.client.post('/api/admin/services/option-images/', {'image': self.option_image_file()}, format='multipart')
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.payload(response)['url'], url)
        self.assertEqual(upload.call_args.kwargs['field_name'], 'image')
        self.assertTrue(upload.call_args.kwargs['folder'].endswith('/option_images'))
        schema = {'fields': [{'key': 'items', 'type': 'REPEATABLE_GROUP', 'label': 'Thiết bị', 'item_fields': [
            {'key': 'capacity', 'type': 'SINGLE_SELECT', 'label': 'Công suất', 'options_by': 'machine_type',
             'options': [{'when': {'machine_type': 'CEILING_SUSPENDED'}, 'items': [{'label': 'Áp trần', 'value': 'STANDARD', 'image': url}]}]}
        ]}]}
        response = self.client.patch(self.url, {'form_schema': schema}, format='json')
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.form_schema, schema)

    @patch('apps.services.views.upload_image')
    def test_option_upload_rejects_missing_invalid_and_disallowed_files(self, upload):
        for data in ({}, {'image': SimpleUploadedFile('bad.png', b'not an image', content_type='image/png')},
                     {'image': SimpleUploadedFile('bad.svg', b'<svg/>', content_type='image/svg+xml')}):
            self.assertEqual(self.client.post('/api/admin/services/option-images/', data, format='multipart').status_code, 400)
        upload.assert_not_called()

    @override_settings(SERVICE_IMAGE_MAX_SIZE=10)
    @patch('apps.services.views.upload_image')
    def test_option_upload_rejects_large_files(self, upload):
        self.assertEqual(self.client.post('/api/admin/services/option-images/', {'image': self.option_image_file()}, format='multipart').status_code, 400)
        upload.assert_not_called()

    @patch('apps.services.views.upload_image')
    def test_customer_cannot_upload_option_image(self, upload):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.post('/api/admin/services/option-images/', {'image': self.option_image_file()}, format='multipart').status_code, 403)
        upload.assert_not_called()

    @patch('apps.services.views.logging.getLogger')
    @patch('apps.services.views.upload_image', side_effect=CloudinaryError('provider failed'))
    def test_option_upload_provider_failure_leaves_schema_unchanged(self, upload, logger):
        previous = self.service.form_schema
        response = self.client.post('/api/admin/services/option-images/', {'image': self.option_image_file()}, format='multipart')
        self.assertEqual(response.status_code, 503)
        self.service.refresh_from_db()
        self.assertEqual(self.service.form_schema, previous)

    def test_edit_general_info_preserves_schema_and_prices(self):
        response = self.client.patch(self.url, {'name': 'Tên mới', 'description': 'Mô tả mới'}, format='json')
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.name, 'Tên mới')
        self.assertEqual(self.service.form_schema['fields'][0]['label'], '')
        self.assertEqual(self.service.pricing_config['base_prices']['2_HOURS'], 150000)

    @patch('apps.services.serializers.save_service_icon')
    def test_menu_icon_upload_is_returned_in_admin_list(self, upload_icon):
        upload_icon.return_value = 'https://res.cloudinary.com/test/image/upload/menu.png'
        icon = SimpleUploadedFile('menu.png', b'test-image-content', content_type='image/png')
        response = self.client.patch(self.url, {'icon_file': icon}, format='multipart')
        self.assertEqual(response.status_code, 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.icon, upload_icon.return_value)
        upload_icon.assert_called_once()
        self.assertEqual(self.payload(self.client.get('/api/admin/services/'))[0]['icon'], upload_icon.return_value)
        self.assertEqual(self.service.pricing_config['base_prices']['2_HOURS'], 150000)

    def test_disable_hides_public_service_but_admin_can_read_and_reenable(self):
        self.assertEqual(len(self.payload(self.public.get('/api/services/'))), 1)
        self.assertEqual(self.public.get(f'/api/services/{self.service.pk}/').status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(self.url, {'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(self.public.get('/api/services/')), [])
        self.assertEqual(self.public.get(f'/api/services/{self.service.pk}/').status_code, 404)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(self.url, {'is_active': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.payload(self.public.get('/api/services/'))), 1)

    def test_disabled_service_cannot_create_new_booking(self):
        self.service.is_active = False
        self.service.save()
        with self.assertRaises(Http404):
            create_booking(customer=self.customer, service_id=self.service.pk, address_id=0, service_data={}, payment_method='CASH')
        self.assertEqual(Booking.objects.count(), 0)

    def test_new_prices_and_disabling_leave_existing_booking_amounts_unchanged(self):
        address = CustomerAddress.objects.create(customer=self.customer, receiver_name='Test', receiver_phone='0900000000', address_line='123 Test')
        booking = Booking.objects.create(booking_code='SERVICE-EXISTING', customer=self.customer, service=self.service, address=address,
            service_data={}, total_amount=Decimal('150000'), subtotal_amount=Decimal('150000'), price_breakdown={'unit_price': 150000})
        response = self.client.patch(self.url, {'pricing_config': {'base_prices': {'2_HOURS': 200000}}, 'is_active': False}, format='json')
        self.assertEqual(response.status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.total_amount, Decimal('150000'))
        self.assertEqual(booking.price_breakdown, {'unit_price': 150000})
        self.assertEqual(booking.status, 'PENDING')

    def test_service_code_is_immutable(self):
        response = self.client.patch(self.url, {'code': 'NEW_CODE'}, format='json')
        self.assertEqual(response.status_code, 400)
        self.service.refresh_from_db()
        self.assertEqual(self.service.code, 'HOME_CLEANING_HOURLY')

    def test_customer_cannot_edit_or_disable(self):
        self.client.force_authenticate(self.customer)
        self.assertEqual(self.client.patch(self.url, {'is_active': False}, format='json').status_code, 403)
        self.service.refresh_from_db()
        self.assertTrue(self.service.is_active)

    def test_imported_schemas_and_prices_can_round_trip_without_losing_metadata(self):
        rows = json.loads((Path(__file__).parent / 'fixtures' / 'services_from_sql.json').read_text(encoding='utf-8'))
        for row in rows:
            original = row['fields']
            response = self.client.patch(self.url, {'form_schema': original['form_schema'], 'pricing_config': original['pricing_config']}, format='json')
            self.assertEqual(response.status_code, 200)
            self.service.refresh_from_db()
            self.assertEqual(self.service.form_schema, original['form_schema'])
            self.assertEqual(self.service.pricing_config, original['pricing_config'])

    def test_invalid_json_shape_does_not_partially_update_service(self):
        response = self.client.patch(self.url, {'name': 'Should not save', 'pricing_config': []}, format='json')
        self.assertEqual(response.status_code, 400)
        self.service.refresh_from_db()
        self.assertEqual(self.service.name, 'Dọn nhà')
