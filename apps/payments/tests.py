from unittest.mock import Mock, patch

import requests
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from apps.common.encryption import decrypt_value

from .bank_catalog import CACHE_KEY
from .models import UserPaymentMethod


User = get_user_model()


class CustomerPaymentMethodTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='payment-customer',
            email='payment-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.other_customer = User.objects.create_user(
            username='other-payment-customer',
            email='other-payment-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.worker = User.objects.create_user(
            username='payment-worker',
            email='payment-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.list_url = reverse('customer-payment-method-list-create')
        self.client.force_authenticate(self.customer)

    def _payload(self, **overrides):
        payload = {
            'bank_bin': '970436',
            'bank_code': 'VCB',
            'bank_name': 'Vietcombank',
            'account_number': '0123456789',
            'account_holder_name': 'NGUYEN VAN A',
        }
        payload.update(overrides)
        return payload

    def test_customer_can_add_bank_account_without_exposing_account_number(self):
        response = self.client.post(self.list_url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        method = UserPaymentMethod.objects.get(user=self.customer)
        self.assertNotEqual(method.account_number_encrypted, '0123456789')
        self.assertEqual(decrypt_value(method.account_number_encrypted), '0123456789')
        self.assertEqual(method.account_number_last4, '6789')
        self.assertTrue(method.is_default)
        self.assertEqual(method.verification_status, UserPaymentMethod.VerificationStatus.UNVERIFIED)

        response_body = str(response.data)
        self.assertNotIn('0123456789', response_body)
        self.assertNotIn(method.account_number_encrypted, response_body)
        self.assertEqual(response.data['data']['account_number_masked'], '******6789')

    def test_rejects_duplicate_bank_account(self):
        first = self.client.post(self.list_url, self._payload(), format='json')
        second = self.client.post(self.list_url, self._payload(), format='json')

        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(UserPaymentMethod.objects.filter(user=self.customer).count(), 1)

    def test_setting_default_unsets_previous_method(self):
        first_response = self.client.post(self.list_url, self._payload(), format='json')
        second_response = self.client.post(
            self.list_url,
            self._payload(
                bank_bin='970422',
                bank_code='MB',
                bank_name='MBBank',
                account_number='0987654321',
            ),
            format='json',
        )
        first_id = first_response.data['data']['id']
        second_id = second_response.data['data']['id']

        response = self.client.patch(
            reverse('customer-payment-method-set-default', kwargs={'pk': second_id}),
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(UserPaymentMethod.objects.get(pk=first_id).is_default)
        self.assertTrue(UserPaymentMethod.objects.get(pk=second_id).is_default)

    def test_deleting_default_promotes_another_active_method(self):
        first_response = self.client.post(self.list_url, self._payload(), format='json')
        second_response = self.client.post(
            self.list_url,
            self._payload(
                bank_bin='970422',
                bank_code='MB',
                bank_name='MBBank',
                account_number='0987654321',
            ),
            format='json',
        )
        first_id = first_response.data['data']['id']
        second_id = second_response.data['data']['id']

        response = self.client.delete(
            reverse('customer-payment-method-detail', kwargs={'pk': first_id})
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertFalse(UserPaymentMethod.objects.get(pk=first_id).is_active)
        self.assertTrue(UserPaymentMethod.objects.get(pk=second_id).is_default)

    def test_customer_cannot_access_another_customers_method(self):
        method = UserPaymentMethod.objects.create(
            user=self.other_customer,
            method_type=UserPaymentMethod.MethodType.BANK_ACCOUNT,
            usage_type=UserPaymentMethod.UsageType.PAYMENT,
            bank_bin='970436',
            bank_code='VCB',
            bank_name='Vietcombank',
            account_number_encrypted='not-readable',
            account_number_last4='6789',
        )

        response = self.client.get(
            reverse('customer-payment-method-detail', kwargs={'pk': method.pk})
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_worker_cannot_use_customer_payment_method_api(self):
        self.client.force_authenticate(self.worker)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_can_add_payout_bank_account_through_worker_api(self):
        self.client.force_authenticate(self.worker)

        response = self.client.post(
            reverse('worker-payment-method-list-create'),
            self._payload(),
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        method = UserPaymentMethod.objects.get(user=self.worker)
        self.assertEqual(method.usage_type, UserPaymentMethod.UsageType.PAYOUT)
        self.assertTrue(method.is_default)
        self.assertEqual(response.data['data']['account_number_masked'], '******6789')


class CustomerBankCatalogTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='bank-catalog-customer',
            email='bank-catalog-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(self.customer)
        cache.delete(CACHE_KEY)

    @patch('apps.payments.bank_catalog.requests.get')
    def test_bank_catalog_normalizes_vietqr_response(self, mock_get):
        response_mock = Mock()
        response_mock.raise_for_status.return_value = None
        response_mock.json.return_value = {
            'code': '00',
            'data': [{
                'id': 17,
                'name': 'Ngân hàng Ngoại thương Việt Nam',
                'code': 'VCB',
                'bin': '970436',
                'shortName': 'Vietcombank',
                'logo': 'https://example.com/vcb.png',
                'transferSupported': 1,
                'lookupSupported': 1,
            }],
        }
        mock_get.return_value = response_mock

        response = self.client.get(reverse('customer-payment-method-banks'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        bank = response.data['data'][0]
        self.assertEqual(bank['bin'], '970436')
        self.assertEqual(bank['short_name'], 'Vietcombank')
        self.assertTrue(bank['transfer_supported'])

    @patch(
        'apps.payments.bank_catalog.requests.get',
        side_effect=requests.RequestException('offline'),
    )
    def test_bank_catalog_uses_fallback_when_provider_is_unavailable(self, mock_get):
        response = self.client.get(reverse('customer-payment-method-banks'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertGreater(len(response.data['data']), 0)
