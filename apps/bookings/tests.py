from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework import serializers
from rest_framework.test import APITestCase
from datetime import timedelta
from decimal import Decimal

from apps.authentication.models import CustomerProfile
from services.models import Service, ServiceCategory

from .models import Area, Booking, BookingVoucher, CustomerAddress, UserVoucher, Voucher
from .voucher_service import validate_and_calculate_voucher


User = get_user_model()


class CustomerAddressAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='address-customer',
            email='address-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        CustomerProfile.objects.create(user=self.customer)
        self.other_customer = User.objects.create_user(
            username='other-customer',
            email='other-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        CustomerProfile.objects.create(user=self.other_customer)
        self.list_url = reverse('customer-address-list-create')
        self.payload = {
            'label': 'Nhà',
            'receiver_name': 'Nguyễn Văn An',
            'receiver_phone': '0912345678',
            'city': 'Thành phố Hồ Chí Minh',
            'ward': 'Phường Sài Gòn',
            'address_line': '01 Nguyễn Huệ',
            'latitude': '10.7731000',
            'longitude': '106.7032000',
        }
        self.client.force_authenticate(self.customer)

    def create_address(self, customer=None, **overrides):
        customer = customer or self.customer
        data = {**self.payload, **overrides}
        return CustomerAddress.objects.create(
            customer=customer,
            label=data['label'],
            receiver_name=data['receiver_name'],
            receiver_phone=data['receiver_phone'],
            city=data['city'],
            ward=data['ward'],
            address_line=data['address_line'],
            latitude=data.get('latitude'),
            longitude=data.get('longitude'),
            is_default=data.get('is_default', False),
        )

    def test_first_address_is_automatically_default(self):
        response = self.client.post(self.list_url, self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        address = CustomerAddress.objects.get(customer=self.customer)
        self.assertTrue(address.is_default)
        self.assertTrue(address.is_active)
        self.assertNotIn('district', response.data['data'])

    def test_creating_new_default_unsets_previous_default(self):
        first = self.create_address(is_default=True)
        payload = {
            **self.payload,
            'label': 'Công ty',
            'address_line': '02 Nguyễn Huệ',
            'is_default': True,
        }

        response = self.client.post(self.list_url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(CustomerAddress.objects.get(pk=response.data['data']['id']).is_default)

    def test_list_returns_only_current_customer_active_addresses(self):
        own = self.create_address(is_default=True)
        deleted = self.create_address(label='Đã xóa')
        deleted.is_active = False
        deleted.save(update_fields=['is_active'])
        self.create_address(customer=self.other_customer, label='Người khác')

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data['data']], [own.id])

    def test_patch_updates_only_requested_field(self):
        address = self.create_address(is_default=True)
        url = reverse('customer-address-detail', args=[address.id])

        response = self.client.patch(url, {'label': 'Văn phòng'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        address.refresh_from_db()
        self.assertEqual(address.label, 'Văn phòng')
        self.assertEqual(address.address_line, self.payload['address_line'])

    def test_customer_cannot_access_another_customer_address(self):
        other_address = self.create_address(customer=self.other_customer)
        url = reverse('customer-address-detail', args=[other_address.id])

        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_soft_deletes_and_promotes_replacement_default(self):
        first = self.create_address(is_default=True)
        second = self.create_address(label='Công ty')
        url = reverse('customer-address-detail', args=[first.id])

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)

    def test_set_default_endpoint_changes_default_address(self):
        first = self.create_address(is_default=True)
        second = self.create_address(label='Công ty')
        url = reverse('customer-address-set-default', args=[second.id])

        response = self.client.patch(url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertTrue(second.is_default)


    def test_rejects_invalid_coordinates(self):
        payload = {**self.payload, 'latitude': '91.0000000'}

        response = self.client.post(self.list_url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('latitude', response.data['errors'])

    def test_cannot_unset_current_default_directly(self):
        address = self.create_address(is_default=True)
        url = reverse('customer-address-detail', args=[address.id])

        response = self.client.patch(url, {'is_default': False}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('is_default', response.data['errors'])
        address.refresh_from_db()
        self.assertTrue(address.is_default)

    def test_worker_cannot_manage_customer_addresses(self):
        worker = User.objects.create_user(
            username='address-worker',
            email='address-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.client.force_authenticate(worker)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AdminVoucherAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='voucher-admin',
            email='voucher-admin@example.com',
            password='Admin@2026!',
            role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username='voucher-customer',
            email='voucher-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(self.admin)
        now = timezone.now()
        self.payload = {
            'code': ' welcome20 ',
            'name': 'Giảm 20%',
            'description': 'Voucher chào mừng',
            'discount_type': Voucher.DiscountType.PERCENT,
            'discount_value': '20.00',
            'max_discount_amount': '50000.00',
            'min_order_amount': '200000.00',
            'usage_limit': 100,
            'per_user_limit': 1,
            'start_at': (now - timedelta(days=1)).isoformat(),
            'end_at': (now + timedelta(days=10)).isoformat(),
            'is_active': True,
        }
        self.list_url = reverse('admin-voucher-list-create')

    def create_voucher(self, **overrides):
        now = timezone.now()
        values = {
            'code': 'TEST20',
            'name': 'Voucher test',
            'discount_type': Voucher.DiscountType.PERCENT,
            'discount_value': Decimal('20.00'),
            'max_discount_amount': Decimal('50000.00'),
            'min_order_amount': Decimal('100000.00'),
            'usage_limit': 100,
            'per_user_limit': 1,
            'start_at': now - timedelta(days=1),
            'end_at': now + timedelta(days=10),
            'is_active': True,
        }
        values.update(overrides)
        return Voucher.objects.create(**values)

    def test_admin_can_create_voucher_and_code_is_normalized(self):
        response = self.client.post(self.list_url, self.payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        voucher = Voucher.objects.get()
        self.assertEqual(voucher.code, 'WELCOME20')
        self.assertEqual(response.data['data']['lifecycle_status'], 'ACTIVE')

    def test_admin_can_list_and_search_vouchers(self):
        voucher = self.create_voucher(code='SEARCHME')

        response = self.client.get(self.list_url, {'search': 'search'})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data['data']], [voucher.id])

    def test_admin_can_patch_unused_voucher(self):
        voucher = self.create_voucher()
        url = reverse('admin-voucher-detail', args=[voucher.id])

        response = self.client.patch(url, {'discount_value': '25.00'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        voucher.refresh_from_db()
        self.assertEqual(voucher.discount_value, Decimal('25.00'))

    def test_financial_fields_are_locked_after_usage(self):
        voucher = self.create_voucher(used_count=1)
        url = reverse('admin-voucher-detail', args=[voucher.id])

        response = self.client.patch(url, {'discount_value': '25.00'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('locked_fields', response.data['errors'])

    def test_delete_soft_disables_voucher(self):
        voucher = self.create_voucher()
        url = reverse('admin-voucher-detail', args=[voucher.id])

        response = self.client.delete(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        voucher.refresh_from_db()
        self.assertFalse(voucher.is_active)

    def test_non_admin_cannot_manage_vouchers(self):
        self.client.force_authenticate(self.customer)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class VoucherServiceTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='service-voucher-customer',
            email='service-voucher-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        now = timezone.now()
        self.voucher = Voucher.objects.create(
            code='SAVE20',
            name='Giảm 20%',
            discount_type=Voucher.DiscountType.PERCENT,
            discount_value=Decimal('20.00'),
            max_discount_amount=Decimal('50000.00'),
            min_order_amount=Decimal('100000.00'),
            usage_limit=100,
            per_user_limit=1,
            start_at=now - timedelta(days=1),
            end_at=now + timedelta(days=10),
        )

    def test_percentage_discount_respects_maximum_discount(self):
        result = validate_and_calculate_voucher(
            code=' save20 ',
            customer=self.customer,
            subtotal_amount=Decimal('300000.00'),
        )

        self.assertEqual(result['discount_amount'], Decimal('50000.00'))
        self.assertEqual(result['total_amount'], Decimal('250000.00'))

    def test_fixed_discount_never_exceeds_subtotal(self):
        self.voucher.discount_type = Voucher.DiscountType.FIXED
        self.voucher.discount_value = Decimal('500000.00')
        self.voucher.min_order_amount = Decimal('0.00')
        self.voucher.save(update_fields=['discount_type', 'discount_value', 'min_order_amount'])

        result = validate_and_calculate_voucher(
            code='SAVE20',
            customer=self.customer,
            subtotal_amount=Decimal('200000.00'),
        )

        self.assertEqual(result['discount_amount'], Decimal('200000.00'))
        self.assertEqual(result['total_amount'], Decimal('0.00'))

    def test_expired_voucher_is_rejected(self):
        self.voucher.end_at = timezone.now() - timedelta(minutes=1)
        self.voucher.save(update_fields=['end_at'])

        with self.assertRaises(serializers.ValidationError):
            validate_and_calculate_voucher(
                code='SAVE20',
                customer=self.customer,
                subtotal_amount=Decimal('300000.00'),
            )

    def test_per_user_limit_counts_reserved_and_used_vouchers(self):
        category = ServiceCategory.objects.create(name='Dọn dẹp')
        service = Service.objects.create(
            category=category,
            name='Dọn nhà',
            base_price=Decimal('300000.00'),
            duration_minutes=120,
        )
        address = CustomerAddress.objects.create(
            customer=self.customer,
            receiver_name='Nguyễn Văn An',
            receiver_phone='0912345678',
            address_line='01 Tràng Tiền',
            ward=area.name,
            city=area.city,
        )
        now = timezone.now()
        booking = Booking.objects.create(
            booking_code='BOOK-VOUCHER-001',
            customer=self.customer,
            service=service,
            address=address,
            scheduled_start=now + timedelta(days=1),
            scheduled_end=now + timedelta(days=1, hours=2),
            subtotal_amount=Decimal('300000.00'),
            total_amount=Decimal('250000.00'),
        )
        BookingVoucher.objects.create(
            booking=booking,
            voucher=self.voucher,
            discount_amount=Decimal('50000.00'),
            status=BookingVoucher.Status.RESERVED,
            reserved_at=now,
        )

        with self.assertRaises(serializers.ValidationError):
            validate_and_calculate_voucher(
                code='SAVE20',
                customer=self.customer,
                subtotal_amount=Decimal('300000.00'),
            )


class CustomerVoucherWalletAPITests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='wallet-customer',
            email='wallet-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.other_customer = User.objects.create_user(
            username='wallet-other-customer',
            email='wallet-other-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.client.force_authenticate(self.customer)
        self.public_voucher = self.create_voucher(
            code='PUBLIC10',
            distribution_type=Voucher.DistributionType.PUBLIC,
        )
        self.code_voucher = self.create_voucher(
            code='SECRET10',
            distribution_type=Voucher.DistributionType.CODE_ONLY,
        )
        self.assigned_voucher = self.create_voucher(
            code='PRIVATE10',
            distribution_type=Voucher.DistributionType.ASSIGNED,
        )

    def create_voucher(self, **overrides):
        now = timezone.now()
        values = {
            'code': 'WALLET10',
            'name': 'Voucher ví',
            'discount_type': Voucher.DiscountType.PERCENT,
            'distribution_type': Voucher.DistributionType.PUBLIC,
            'discount_value': Decimal('10.00'),
            'min_order_amount': Decimal('0.00'),
            'usage_limit': 100,
            'per_user_limit': 1,
            'start_at': now - timedelta(days=1),
            'end_at': now + timedelta(days=10),
            'is_active': True,
        }
        values.update(overrides)
        return Voucher.objects.create(**values)

    def test_available_list_only_returns_claimable_public_vouchers(self):
        response = self.client.get(reverse('customer-voucher-available'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [item['id'] for item in response.data['data']],
            [self.public_voucher.id],
        )

    def test_customer_can_claim_public_voucher_without_duplicates(self):
        url = reverse('customer-voucher-claim', args=[self.public_voucher.id])

        first_response = self.client.post(url, {}, format='json')
        second_response = self.client.post(url, {}, format='json')

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            UserVoucher.objects.filter(
                user=self.customer,
                voucher=self.public_voucher,
            ).count(),
            1,
        )
        self.public_voucher.refresh_from_db()
        self.assertEqual(self.public_voucher.used_count, 0)

    def test_customer_can_claim_code_only_voucher_by_code(self):
        response = self.client.post(
            reverse('customer-voucher-claim-code'),
            {'code': ' secret10 '},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user_voucher = UserVoucher.objects.get(user=self.customer)
        self.assertEqual(user_voucher.voucher, self.code_voucher)
        self.assertEqual(user_voucher.source, UserVoucher.Source.CUSTOMER_CLAIM)

    def test_customer_cannot_claim_assigned_voucher_by_code(self):
        response = self.client.post(
            reverse('customer-voucher-claim-code'),
            {'code': self.assigned_voucher.code},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(UserVoucher.objects.filter(user=self.customer).exists())

    def test_customer_cannot_claim_expired_voucher(self):
        self.public_voucher.end_at = timezone.now() - timedelta(minutes=1)
        self.public_voucher.save(update_fields=['end_at'])

        response = self.client.post(
            reverse('customer-voucher-claim', args=[self.public_voucher.id]),
            {},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_wallet_only_exposes_current_customer_vouchers(self):
        own = UserVoucher.objects.create(
            user=self.customer,
            voucher=self.public_voucher,
            source=UserVoucher.Source.CUSTOMER_CLAIM,
        )
        UserVoucher.objects.create(
            user=self.other_customer,
            voucher=self.code_voucher,
            source=UserVoucher.Source.CUSTOMER_CLAIM,
        )

        response = self.client.get(reverse('customer-voucher-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data['data']], [own.id])

    def test_customer_cannot_access_another_wallet_item(self):
        other = UserVoucher.objects.create(
            user=self.other_customer,
            voucher=self.public_voucher,
            source=UserVoucher.Source.CUSTOMER_CLAIM,
        )

        response = self.client.get(reverse('customer-voucher-detail', args=[other.id]))

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_customer_can_hide_and_restore_wallet_item(self):
        user_voucher = UserVoucher.objects.create(
            user=self.customer,
            voucher=self.public_voucher,
            source=UserVoucher.Source.CUSTOMER_CLAIM,
        )
        url = reverse('customer-voucher-detail', args=[user_voucher.id])

        hide_response = self.client.delete(url)
        list_response = self.client.get(reverse('customer-voucher-list'))
        restore_response = self.client.patch(url, {'is_visible': True}, format='json')

        self.assertEqual(hide_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.data['data'], [])
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK)
        user_voucher.refresh_from_db()
        self.assertTrue(user_voucher.is_visible)


class AdminUserVoucherAPITests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='wallet-admin',
            email='wallet-admin@example.com',
            password='Admin@2026!',
            role=User.Role.ADMIN,
        )
        self.customer = User.objects.create_user(
            username='assigned-customer',
            email='assigned-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        now = timezone.now()
        self.voucher = Voucher.objects.create(
            code='ASSIGNED20',
            name='Voucher cấp riêng',
            discount_type=Voucher.DiscountType.PERCENT,
            distribution_type=Voucher.DistributionType.ASSIGNED,
            discount_value=Decimal('20.00'),
            min_order_amount=Decimal('0.00'),
            usage_limit=100,
            per_user_limit=1,
            start_at=now - timedelta(days=1),
            end_at=now + timedelta(days=10),
        )
        self.list_url = reverse('admin-user-voucher-list-create')
        self.client.force_authenticate(self.admin)

    def assign_voucher(self):
        return UserVoucher.objects.create(
            user=self.customer,
            voucher=self.voucher,
            source=UserVoucher.Source.ADMIN,
            created_by=self.admin,
        )

    def test_admin_can_assign_voucher_to_customer(self):
        response = self.client.post(self.list_url, {
            'user_id': self.customer.id,
            'voucher_id': self.voucher.id,
            'admin_note': 'Chăm sóc khách hàng',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        user_voucher = UserVoucher.objects.get()
        self.assertEqual(user_voucher.source, UserVoucher.Source.ADMIN)
        self.assertEqual(user_voucher.created_by, self.admin)
        self.assertEqual(user_voucher.admin_note, 'Chăm sóc khách hàng')

    def test_assigning_same_voucher_is_idempotent(self):
        payload = {'user_id': self.customer.id, 'voucher_id': self.voucher.id}

        first_response = self.client.post(self.list_url, payload, format='json')
        second_response = self.client.post(self.list_url, payload, format='json')

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        self.assertEqual(UserVoucher.objects.count(), 1)

    def test_admin_can_filter_assignments(self):
        user_voucher = self.assign_voucher()

        response = self.client.get(self.list_url, {
            'user_id': self.customer.id,
            'status': UserVoucher.Status.AVAILABLE,
        })

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item['id'] for item in response.data['data']], [user_voucher.id])

    def test_admin_can_revoke_and_restore_voucher(self):
        user_voucher = self.assign_voucher()
        url = reverse('admin-user-voucher-detail', args=[user_voucher.id])

        delete_response = self.client.delete(url)
        user_voucher.refresh_from_db()
        self.assertEqual(delete_response.status_code, status.HTTP_200_OK)
        self.assertEqual(user_voucher.status, UserVoucher.Status.REVOKED)
        self.assertFalse(user_voucher.is_visible)
        self.assertIsNotNone(user_voucher.revoked_at)

        restore_response = self.client.patch(
            url,
            {'status': UserVoucher.Status.AVAILABLE, 'admin_note': 'Cấp lại'},
            format='json',
        )
        self.assertEqual(restore_response.status_code, status.HTTP_200_OK, restore_response.data)
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.AVAILABLE)
        self.assertTrue(user_voucher.is_visible)
        self.assertIsNone(user_voucher.revoked_at)
        self.assertEqual(user_voucher.admin_note, 'Cấp lại')

    def test_non_admin_cannot_manage_user_vouchers(self):
        self.client.force_authenticate(self.customer)

        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_cannot_assign_voucher_to_worker(self):
        worker = User.objects.create_user(
            username='voucher-worker',
            email='voucher-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )

        response = self.client.post(self.list_url, {
            'user_id': worker.id,
            'voucher_id': self.voucher.id,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('user_id', response.data['errors'])

    def test_admin_cannot_change_owner_or_voucher_after_assignment(self):
        user_voucher = self.assign_voucher()
        other_customer = User.objects.create_user(
            username='replacement-customer',
            email='replacement-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )

        response = self.client.patch(
            reverse('admin-user-voucher-detail', args=[user_voucher.id]),
            {'user_id': other_customer.id},
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('immutable_fields', response.data['errors'])
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.user, self.customer)
