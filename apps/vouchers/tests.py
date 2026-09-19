from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from .models import UserVoucher, Voucher


User = get_user_model()


class AdminVoucherAssignmentTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='voucher-admin', email='voucher-admin@example.com',
            password='CleanWise@2026!', role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username='voucher-customer', email='voucher-customer@example.com',
            password='CleanWise@2026!', role=User.Role.CUSTOMER,
        )
        self.worker = User.objects.create_user(
            username='voucher-worker', email='voucher-worker@example.com',
            password='CleanWise@2026!', role=User.Role.WORKER,
        )
        self.voucher = Voucher.objects.create(
            code='VIP100K',
            name='Ưu đãi khách hàng thân thiết',
            distribution_type=Voucher.DistributionType.ASSIGNED,
            discount_type=Voucher.DiscountType.FIXED,
            discount_value=Decimal('100000.00'),
            min_order_amount=Decimal('200000.00'),
            issuance_limit=2,
            start_at=timezone.now() - timedelta(days=1),
            end_at=timezone.now() + timedelta(days=30),
        )
        self.url = reverse('admin-voucher-assign')

    def _payload(self, **overrides):
        payload = {
            'voucher_id': self.voucher.id,
            'customer_id': self.customer.id,
            'note': 'Tặng khách hàng thân thiết',
        }
        payload.update(overrides)
        return payload

    def test_admin_can_assign_voucher_to_customer(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user_voucher = UserVoucher.objects.get(user=self.customer, voucher=self.voucher)
        self.assertEqual(user_voucher.source, UserVoucher.Source.ADMIN)
        self.assertEqual(user_voucher.status, UserVoucher.Status.AVAILABLE)
        self.assertEqual(user_voucher.assigned_by, self.admin)
        self.assertEqual(user_voucher.note, 'Tặng khách hàng thân thiết')
        self.assertEqual(response.data['data']['voucher_id'], self.voucher.id)
        self.assertEqual(response.data['data']['customer_id'], self.customer.id)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.issued_count, 1)

    def test_non_admin_cannot_assign_voucher(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, response.data)
        self.assertFalse(UserVoucher.objects.exists())

    def test_admin_cannot_assign_voucher_to_non_customer(self):
        self.client.force_authenticate(self.admin)

        response = self.client.post(self.url, self._payload(customer_id=self.worker.id), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserVoucher.objects.exists())

    def test_admin_cannot_assign_public_voucher(self):
        self.voucher.distribution_type = Voucher.DistributionType.PUBLIC
        self.voucher.save(update_fields=['distribution_type'])
        self.client.force_authenticate(self.admin)

        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserVoucher.objects.exists())

    def test_admin_cannot_assign_same_voucher_twice(self):
        UserVoucher.objects.create(
            user=self.customer,
            voucher=self.voucher,
            source=UserVoucher.Source.ADMIN,
            assigned_by=self.admin,
        )
        self.voucher.issued_count = 1
        self.voucher.save(update_fields=['issued_count'])
        self.client.force_authenticate(self.admin)

        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertEqual(UserVoucher.objects.filter(user=self.customer, voucher=self.voucher).count(), 1)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.issued_count, 1)

    def test_admin_cannot_assign_exhausted_voucher(self):
        self.voucher.issuance_limit = 1
        self.voucher.issued_count = 1
        self.voucher.save(update_fields=['issuance_limit', 'issued_count'])
        self.client.force_authenticate(self.admin)

        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserVoucher.objects.exists())

    def test_admin_cannot_assign_expired_voucher(self):
        self.voucher.start_at = timezone.now() - timedelta(days=2)
        self.voucher.end_at = timezone.now() - timedelta(days=1)
        self.voucher.save(update_fields=['start_at', 'end_at'])
        self.client.force_authenticate(self.admin)

        response = self.client.post(self.url, self._payload(), format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserVoucher.objects.exists())
