from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase

User = get_user_model()


class AdminCustomerAccountTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='customer-admin', email='customer-admin@test.com', role='ADMIN')
        self.customer = User.objects.create_user(
            username='customer-detail', email='customer-detail@test.com', role='CUSTOMER', first_name='An',
        )
        self.worker = User.objects.create_user(username='customer-worker', email='customer-worker@test.com', role='WORKER')
        self.detail_url = reverse('admin-customer-detail', args=[self.customer.id])
        self.status_url = reverse('admin-customer-status', args=[self.customer.id])
        self.client.force_authenticate(self.admin)

    def test_customer_detail_is_read_only(self):
        response = self.client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id'], self.customer.id)
        self.assertNotIn('password', response.data)
        for method in ('patch', 'put', 'post', 'delete'):
            response = getattr(self.client, method)(self.detail_url, {'first_name': 'Changed'}, format='json')
            self.assertEqual(response.status_code, 405)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.first_name, 'An')

    def test_admin_can_deactivate_and_reactivate_customer(self):
        for active in (False, True):
            response = self.client.patch(self.status_url, {'is_active': active}, format='json')
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data['data']['is_active'], active)
            self.customer.refresh_from_db()
            self.assertEqual(self.customer.is_active, active)
            self.assertEqual(self.customer.first_name, 'An')

    def test_status_endpoint_rejects_profile_changes_and_invalid_values(self):
        for payload in ({}, {'is_active': None}, {'is_active': 'false'}, {'is_active': False, 'email': 'changed@test.com'}):
            response = self.client.patch(self.status_url, payload, format='json')
            self.assertEqual(response.status_code, 400, response.data)
        self.customer.refresh_from_db()
        self.assertTrue(self.customer.is_active)
        self.assertEqual(self.customer.email, 'customer-detail@test.com')

    def test_non_customer_accounts_are_not_exposed_or_modified(self):
        for account in (self.worker, self.admin):
            self.assertEqual(self.client.get(reverse('admin-customer-detail', args=[account.id])).status_code, 404)
            response = self.client.patch(reverse('admin-customer-status', args=[account.id]), {'is_active': False}, format='json')
            self.assertEqual(response.status_code, 404)
            account.refresh_from_db()
            self.assertTrue(account.is_active)

    def test_only_admin_can_access_customer_account_endpoints(self):
        for user in (self.customer, self.worker):
            self.client.force_authenticate(user)
            self.assertEqual(self.client.get(self.detail_url).status_code, 403)
            self.assertEqual(self.client.patch(self.status_url, {'is_active': False}, format='json').status_code, 403)
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(self.detail_url).status_code, 401)
        self.assertEqual(self.client.patch(self.status_url, {'is_active': False}, format='json').status_code, 401)
