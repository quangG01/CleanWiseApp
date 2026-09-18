from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.ai_engine.models import AIAssignmentLog
from apps.services.models import Service
from .models import (
    Area,
    Booking,
    BookingAssignment,
    BookingSchedule,
    CustomerAddress,
    UserVoucher,
    Voucher,
)
from .voucher_service import validate_and_calculate_voucher

User = get_user_model()


class SchemaFlowTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='customer',
            email='customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.worker = User.objects.create_user(
            username='worker',
            email='worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        self.area = Area.objects.create(name='Bến Nghé', city='TP.HCM')
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            receiver_name='Nguyễn Văn An',
            receiver_phone='0912345678',
            address_line='01 Nguyễn Huệ',
            ward='Bến Nghé',
            city='TP.HCM',
        )
        self.service = Service.objects.create(
            code='HOME_CLEANING',
            section_code='CLEANING',
            name='Dọn nhà',
            description='Dịch vụ dọn nhà',
            form_schema={'fields': []},
            pricing_config={'base_price': 200000},
            is_active=True,
        )

    def test_address_api_uses_two_level_administrative_address(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-address-list-create'), {
            'receiver_name': 'Nguyễn Văn B',
            'receiver_phone': '0987654321',
            'address_line': '02 Nguyễn Huệ',
            'ward': 'Bến Nghé',
            'city': 'TP.HCM',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['ward'], 'Bến Nghé')
        self.assertEqual(response.data['data']['city'], 'TP.HCM')

    def test_booking_schedule_assignment_and_ai_log_share_schedule(self):
        booking = Booking.objects.create(
            booking_code='CW-0001',
            customer=self.customer,
            service=self.service,
            service_data={'hours': 2},
            address=self.address,
            pricing_status=Booking.PricingStatus.CALCULATED,
            subtotal_amount=Decimal('200000'),
            total_amount=Decimal('200000'),
        )
        start = timezone.now() + timedelta(days=1)
        schedule = BookingSchedule.objects.create(
            booking=booking,
            sequence_no=1,
            scheduled_start=start,
            scheduled_end=start + timedelta(hours=2),
        )
        assignment = BookingAssignment.objects.create(schedule=schedule, worker=self.worker)
        log = AIAssignmentLog.objects.create(
            schedule=schedule,
            requested_by=self.customer,
            selected_worker=self.worker,
        )

        self.assertEqual(assignment.schedule_id, schedule.id)
        self.assertEqual(log.schedule_id, schedule.id)


class VoucherTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='voucher-customer',
            email='voucher-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.admin = User.objects.create_user(
            username='voucher-admin',
            email='voucher-admin@example.com',
            password='CleanWise@2026!',
            role=User.Role.ADMIN,
        )

    def create_voucher(self, **overrides):
        now = timezone.now()
        values = {
            'code': 'SAVE10',
            'name': 'Giảm 10%',
            'distribution_type': Voucher.DistributionType.PUBLIC,
            'discount_type': Voucher.DiscountType.PERCENT,
            'discount_value': Decimal('10'),
            'min_order_amount': Decimal('100000'),
            'start_at': now - timedelta(days=1),
            'end_at': now + timedelta(days=1),
        }
        values.update(overrides)
        return Voucher.objects.create(**values)

    def test_discount_calculation_uses_simplified_voucher(self):
        voucher = self.create_voucher()
        UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.PUBLIC,
        )

        result = validate_and_calculate_voucher(
            code=voucher.code,
            customer=self.customer,
            subtotal_amount=Decimal('200000'),
        )
        self.assertEqual(result['discount_amount'], Decimal('20000.00'))

    def test_customer_can_validate_voucher_and_preview_amounts(self):
        voucher = self.create_voucher()
        UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.CODE,
        )
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-voucher-validate'), {
            'code': ' save10 ',
            'subtotal_amount': '200000',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['discount_amount'], Decimal('20000.00'))
        self.assertEqual(response.data['data']['total_amount'], Decimal('180000.00'))

    def test_admin_can_create_voucher_with_only_writable_fields(self):
        now = timezone.now()
        self.client.force_authenticate(self.admin)

        response = self.client.post(reverse('admin-voucher-list-create'), {
            'code': ' welcome20 ',
            'name': 'Ưu đãi khách hàng mới',
            'description': 'Giảm 20%, tối đa 50.000đ.',
            'distribution_type': Voucher.DistributionType.PUBLIC,
            'discount_type': Voucher.DiscountType.PERCENT,
            'discount_value': '20.00',
            'max_discount_amount': '50000.00',
            'min_order_amount': '200000.00',
            'issuance_limit': 1000,
            'start_at': now.isoformat(),
            'end_at': (now + timedelta(days=30)).isoformat(),
            'is_active': True,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['code'], 'WELCOME20')
        self.assertEqual(response.data['data']['issued_count'], 0)
        self.assertEqual(response.data['data']['remaining_issuance'], 1000)

    def test_admin_cannot_set_maximum_discount_for_fixed_voucher(self):
        now = timezone.now()
        self.client.force_authenticate(self.admin)

        response = self.client.post(reverse('admin-voucher-list-create'), {
            'code': 'GIAM50K',
            'name': 'Giảm ngay 50.000đ',
            'distribution_type': Voucher.DistributionType.CODE_ONLY,
            'discount_type': Voucher.DiscountType.FIXED,
            'discount_value': '50000.00',
            'max_discount_amount': '100000.00',
            'start_at': now.isoformat(),
            'end_at': (now + timedelta(days=30)).isoformat(),
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('max_discount_amount', response.data['errors'])

    def test_admin_can_get_voucher_detail_by_code_case_insensitively(self):
        voucher = self.create_voucher(code='ADMINCODE')
        self.client.force_authenticate(self.admin)

        response = self.client.get(reverse(
            'admin-voucher-detail-by-code',
            kwargs={'code': 'admincode'},
        ))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['id'], voucher.id)
        self.assertEqual(response.data['data']['code'], 'ADMINCODE')

    def test_customer_can_claim_public_voucher_by_code(self):
        voucher = self.create_voucher(issuance_limit=2)
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-voucher-claim-by-code'), {
            'code': voucher.code.lower(),
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['source'], UserVoucher.Source.PUBLIC)
        self.assertEqual(response.data['data']['status'], UserVoucher.Status.AVAILABLE)
        voucher.refresh_from_db()
        self.assertEqual(voucher.issued_count, 1)

    def test_customer_can_claim_code_only_voucher_by_code(self):
        voucher = self.create_voucher(
            code='SECRET50',
            distribution_type=Voucher.DistributionType.CODE_ONLY,
        )
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-voucher-claim-by-code'), {
            'code': ' secret50 ',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['voucher']['id'], voucher.id)
        self.assertEqual(response.data['data']['source'], UserVoucher.Source.CODE)
        voucher.refresh_from_db()
        self.assertEqual(voucher.issued_count, 1)

    def test_customer_cannot_claim_same_public_voucher_twice(self):
        voucher = self.create_voucher(issuance_limit=2)
        self.client.force_authenticate(self.customer)
        url = reverse('customer-voucher-claim-by-code')
        payload = {'code': voucher.code}

        first_response = self.client.post(url, payload, format='json')
        second_response = self.client.post(url, payload, format='json')

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED, first_response.data)
        self.assertEqual(second_response.status_code, status.HTTP_400_BAD_REQUEST, second_response.data)
        voucher.refresh_from_db()
        self.assertEqual(voucher.issued_count, 1)

    def test_customer_cannot_claim_exhausted_public_voucher(self):
        voucher = self.create_voucher(issuance_limit=1, issued_count=1)
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-voucher-claim-by-code'), {
            'code': voucher.code,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserVoucher.objects.filter(user=self.customer, voucher=voucher).exists())

    def test_customer_cannot_self_claim_assigned_voucher(self):
        voucher = self.create_voucher(
            code='ONLYYOU',
            distribution_type=Voucher.DistributionType.ASSIGNED,
        )
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-voucher-claim-by-code'), {
            'code': voucher.code,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(UserVoucher.objects.filter(user=self.customer, voucher=voucher).exists())

    def test_customer_can_list_only_vouchers_in_own_wallet(self):
        own_voucher = self.create_voucher(code='MYVOUCHER')
        other_voucher = self.create_voucher(code='OTHERVOUCHER')
        other_customer = User.objects.create_user(
            username='other-voucher-customer',
            email='other-voucher-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        UserVoucher.objects.create(
            user=self.customer,
            voucher=own_voucher,
            source=UserVoucher.Source.PUBLIC,
        )
        UserVoucher.objects.create(
            user=other_customer,
            voucher=other_voucher,
            source=UserVoucher.Source.PUBLIC,
        )
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('customer-voucher-wallet-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(len(response.data['data']), 1)
        self.assertEqual(response.data['data'][0]['voucher']['code'], 'MYVOUCHER')
        self.assertTrue(response.data['data'][0]['is_usable'])

    def test_customer_list_excludes_voucher_already_received(self):
        voucher = self.create_voucher(issued_count=1)
        UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.PUBLIC,
        )
        self.client.force_authenticate(self.customer)

        response = self.client.get(reverse('customer-voucher-list'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data'], [])

    def test_customer_cannot_receive_same_voucher_twice(self):
        voucher = self.create_voucher()
        UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.PUBLIC,
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            UserVoucher.objects.create(
                user=self.customer,
                voucher=voucher,
                source=UserVoucher.Source.CODE,
            )

    def test_user_voucher_can_only_belong_to_one_booking(self):
        voucher = self.create_voucher()
        user_voucher = UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.PUBLIC,
        )
        service = Service.objects.create(
            code='AC_REPAIR',
            section_code='APPLIANCE_MAINTENANCE',
            name='Sửa máy lạnh',
            description='Dịch vụ sửa máy lạnh',
            form_schema={'fields': []},
            pricing_config={'pricing_mode': 'QUOTE'},
            is_active=True,
        )
        address = CustomerAddress.objects.create(
            customer=self.customer,
            receiver_name='Nguyễn Văn An',
            receiver_phone='0912345678',
            address_line='01 Nguyễn Huệ',
            ward='Bến Nghé',
            city='TP.HCM',
        )
        booking_values = {
            'customer': self.customer,
            'service': service,
            'user_voucher': user_voucher,
            'service_data': {'goi_dich_vu': 'ca_le'},
            'address': address,
            'pricing_status': Booking.PricingStatus.WAITING_QUOTE,
        }
        Booking.objects.create(booking_code='CW-VOUCHER-1', **booking_values)

        with self.assertRaises(IntegrityError), transaction.atomic():
            Booking.objects.create(booking_code='CW-VOUCHER-2', **booking_values)



class BookingCreationTests(APITestCase):
    def setUp(self):
        self.customer = User.objects.create_user(
            username='booking-customer',
            email='booking-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            receiver_name='Nguyễn Văn An',
            receiver_phone='0912345678',
            address_line='01 Nguyễn Huệ',
            ward='Bến Nghé',
            city='TP.HCM',
        )
        self.service = Service.objects.create(
            code='HOME_CLEANING_HOURLY',
            section_code='HOME_CLEANING',
            name='Dọn dẹp nhà - Ca lẻ',
            description='Dịch vụ dọn dẹp nhà theo giờ.',
            form_schema={
                'fields': [
                    {
                        'key': 'duration',
                        'type': 'SINGLE_SELECT',
                        'label': 'Thời gian làm việc',
                        'required': True,
                        'options': [
                            {'label': '2 giờ', 'value': '2_HOURS'},
                            {'label': '3 giờ', 'value': '3_HOURS'},
                        ],
                    },
                    {
                        'key': 'additional_services',
                        'type': 'MULTI_SELECT',
                        'label': 'Dịch vụ thêm',
                        'required': False,
                        'options': [
                            {'label': 'Nấu ăn', 'value': 'COOKING'},
                        ],
                    },
                ],
            },
            pricing_config={
                'currency': 'VND',
                'base_prices': {'2_HOURS': 150000, '3_HOURS': 210000},
                'additional_services': {'COOKING': 50000},
            },
            is_active=True,
        )

    def _valid_schedule(self, hours_ahead=24):
        start = timezone.now() + timedelta(hours=hours_ahead)
        return {
            'scheduled_start': start.isoformat(),
            'scheduled_end': (start + timedelta(hours=2)).isoformat(),
        }

    def test_customer_can_create_booking_with_correct_price(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {'duration': '3_HOURS', 'additional_services': ['COOKING']},
            'schedules': [self._valid_schedule()],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        data = response.data['data']
        self.assertEqual(Decimal(str(data['subtotal_amount'])), Decimal('260000'))
        self.assertEqual(Decimal(str(data['total_amount'])), Decimal('260000'))
        self.assertEqual(len(data['schedules']), 1)
        booking = Booking.objects.get(booking_code=data['booking_code'])
        self.assertEqual(booking.schedules.count(), 1)
        self.assertEqual(booking.pricing_status, Booking.PricingStatus.CALCULATED)

    def test_booking_rejects_invalid_option_value(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {'duration': '5_HOURS'},
            'schedules': [self._valid_schedule()],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('service_data', response.data['errors'])
        self.assertFalse(Booking.objects.exists())

    def test_booking_rejects_missing_required_field(self):
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {},
            'schedules': [self._valid_schedule()],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('duration', response.data['errors']['service_data'])

    def test_booking_rejects_schedule_in_the_past(self):
        self.client.force_authenticate(self.customer)
        past = timezone.now() - timedelta(hours=1)

        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {'duration': '2_HOURS'},
            'schedules': [{
                'scheduled_start': past.isoformat(),
                'scheduled_end': (past + timedelta(hours=2)).isoformat(),
            }],
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertFalse(Booking.objects.exists())

    def test_booking_with_voucher_reduces_total_and_marks_used(self):
        voucher = Voucher.objects.create(
            code='BOOKTEST10',
            name='Giảm 10%',
            distribution_type=Voucher.DistributionType.PUBLIC,
            discount_type=Voucher.DiscountType.PERCENT,
            discount_value=Decimal('10'),
            min_order_amount=Decimal('0'),
            start_at=timezone.now() - timedelta(days=1),
            end_at=timezone.now() + timedelta(days=1),
        )
        user_voucher = UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.PUBLIC,
        )
        self.client.force_authenticate(self.customer)

        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {'duration': '2_HOURS'},
            'schedules': [self._valid_schedule()],
            'voucher_code': voucher.code,
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        data = response.data['data']
        self.assertEqual(Decimal(str(data['subtotal_amount'])), Decimal('150000'))
        self.assertEqual(Decimal(str(data['discount_amount'])), Decimal('15000.00'))
        self.assertEqual(Decimal(str(data['total_amount'])), Decimal('135000.00'))
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.USED)

    def test_customer_can_only_see_own_bookings(self):
        other_customer = User.objects.create_user(
            username='other-booking-customer',
            email='other-booking-customer@example.com',
            password='CleanWise@2026!',
            role=User.Role.CUSTOMER,
        )
        other_address = CustomerAddress.objects.create(
            customer=other_customer,
            receiver_name='Trần Thị B',
            receiver_phone='0987654321',
            address_line='02 Lê Lợi',
            ward='Bến Thành',
            city='TP.HCM',
        )
        self.client.force_authenticate(other_customer)
        self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': other_address.id,
            'service_data': {'duration': '2_HOURS'},
            'schedules': [self._valid_schedule()],
        }, format='json')

        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('customer-booking-list-create'))

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data'], [])
