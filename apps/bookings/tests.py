from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.services.models import Service
from apps.addresses.models import CustomerAddress
from apps.vouchers.models import UserVoucher, Voucher

from .models import Booking


User = get_user_model()


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
                        'options': [{'label': 'Nấu ăn', 'value': 'COOKING'}],
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
        self.assertEqual(response.data['data']['count'], 0)
