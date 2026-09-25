from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.services.models import Service
from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.vouchers.models import UserVoucher, Voucher
from apps.payments.models import Payment
from apps.payments.webhook_service import handle_payos_webhook
from apps.worker.assignment_service import claim_schedule
from apps.worker.models import Area, WorkerWorkingArea

from .models import Booking
from .booking_service import create_booking


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
                        'key': 'date',
                        'type': 'DATE',
                        'label': 'Ngày làm việc',
                        'required': True,
                    },
                    {
                        'key': 'start_time',
                        'type': 'TIME',
                        'label': 'Giờ bắt đầu',
                        'required': True,
                    },
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

    def _valid_service_data(self, hours_ahead=24):
        start = timezone.localtime(timezone.now() + timedelta(hours=hours_ahead))
        return {
            'date': start.strftime('%Y-%m-%d'),
            'start_time': start.strftime('%H:%M'),
        }

    def _create_user_voucher(self, *, code='BOOKTEST10'):
        voucher = Voucher.objects.create(
            code=code,
            name='Giảm 10%',
            distribution_type=Voucher.DistributionType.PUBLIC,
            discount_type=Voucher.DiscountType.PERCENT,
            discount_value=Decimal('10'),
            min_order_amount=Decimal('0'),
            start_at=timezone.now() - timedelta(days=1),
            end_at=timezone.now() + timedelta(days=1),
        )
        return UserVoucher.objects.create(
            user=self.customer,
            voucher=voucher,
            source=UserVoucher.Source.PUBLIC,
        )

    def _post_booking_with_voucher(self, user_voucher, *, payment_method='CASH', hours_ahead=24):
        self.client.force_authenticate(self.customer)
        return self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {
                **self._valid_service_data(hours_ahead),
                'duration': '2_HOURS',
            },
            'voucher_code': user_voucher.voucher.code,
            'payment_method': payment_method,
        }, format='json')

    def test_customer_can_create_booking_with_correct_price(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {
                **self._valid_service_data(),
                'duration': '3_HOURS',
                'additional_services': ['COOKING'],
            },
            'schedules': [self._valid_schedule()],
            'payment_method': 'CASH',
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
            'service_data': {**self._valid_service_data(), 'duration': '5_HOURS'},
            'schedules': [self._valid_schedule()],
            'payment_method': 'CASH',
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
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)
        self.assertIn('duration', response.data['errors']['service_data'])

    def test_booking_rejects_schedule_in_the_past(self):
        self.client.force_authenticate(self.customer)
        past = timezone.now() - timedelta(hours=1)
        response = self.client.post(reverse('customer-booking-list-create'), {
            'service_id': self.service.id,
            'address_id': self.address.id,
            'service_data': {
                'date': timezone.localtime(past).strftime('%Y-%m-%d'),
                'start_time': timezone.localtime(past).strftime('%H:%M'),
                'duration': '2_HOURS',
            },
            'schedules': [{
                'scheduled_start': past.isoformat(),
                'scheduled_end': (past + timedelta(hours=2)).isoformat(),
            }],
            'payment_method': 'CASH',
        }, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST, response.data)

    def test_booking_with_voucher_reduces_total_and_reserves_voucher(self):
        user_voucher = self._create_user_voucher()
        response = self._post_booking_with_voucher(user_voucher)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        data = response.data['data']
        self.assertEqual(Decimal(str(data['discount_amount'])), Decimal('15000.00'))
        self.assertEqual(Decimal(str(data['total_amount'])), Decimal('135000.00'))
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.RESERVED)
        self.assertIsNotNone(user_voucher.reserved_at)
        self.assertIsNone(user_voucher.used_at)

    def test_reserved_voucher_cannot_be_used_for_a_second_active_booking(self):
        user_voucher = self._create_user_voucher(code='ONLYONCE')
        first = self._post_booking_with_voucher(user_voucher)
        second = self._post_booking_with_voucher(user_voucher, hours_ahead=48)

        self.assertEqual(first.status_code, status.HTTP_201_CREATED, first.data)
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST, second.data)
        self.assertIn('voucher_code', second.data['errors'])
        self.assertEqual(Booking.objects.filter(user_voucher=user_voucher).count(), 1)

    def test_cancelling_booking_releases_voucher_for_reuse(self):
        user_voucher = self._create_user_voucher(code='REUSABLE')
        created = self._post_booking_with_voucher(
            user_voucher,
            payment_method=Payment.Method.BANK_TRANSFER,
        )
        booking_id = created.data['data']['id']
        payment = Payment.objects.get(booking_id=booking_id)

        cancelled = self.client.post(
            reverse('customer-booking-cancel', kwargs={'pk': booking_id}),
            {'reason': 'Thay đổi kế hoạch'},
            format='json',
        )
        self.assertEqual(cancelled.status_code, status.HTTP_200_OK, cancelled.data)
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.AVAILABLE)
        self.assertIsNone(user_voucher.reserved_at)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.CANCELLED)

        late_webhook = handle_payos_webhook(SimpleNamespace(
            order_code=payment.id,
            amount=payment.amount,
            reference='PAYOS-TOO-LATE',
        ))
        self.assertIsNone(late_webhook)
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.AVAILABLE)

        reused = self._post_booking_with_voucher(user_voucher, hours_ahead=48)
        self.assertEqual(reused.status_code, status.HTTP_201_CREATED, reused.data)
        self.assertEqual(Booking.objects.filter(user_voucher=user_voucher).count(), 2)

    def test_payment_creation_failure_rolls_back_booking_and_voucher_reservation(self):
        user_voucher = self._create_user_voucher(code='ROLLBACK')

        with patch(
            'apps.bookings.booking_service.Payment.objects.create',
            side_effect=RuntimeError('payment storage unavailable'),
        ):
            with self.assertRaises(RuntimeError):
                create_booking(
                    customer=self.customer,
                    service_id=self.service.id,
                    address_id=self.address.id,
                    service_data={**self._valid_service_data(), 'duration': '2_HOURS'},
                    voucher_code=user_voucher.voucher.code,
                    payment_method=Payment.Method.CASH,
                )

        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.AVAILABLE)
        self.assertEqual(Booking.objects.filter(user_voucher=user_voucher).count(), 0)

    def test_bank_transfer_webhook_marks_voucher_used_and_is_idempotent(self):
        user_voucher = self._create_user_voucher(code='BANKPAID')
        created = self._post_booking_with_voucher(
            user_voucher,
            payment_method=Payment.Method.BANK_TRANSFER,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED, created.data)
        payment = Payment.objects.get(booking_id=created.data['data']['id'])
        webhook = SimpleNamespace(
            order_code=payment.id,
            amount=payment.amount,
            reference='PAYOS-PAID-1',
        )

        handled = handle_payos_webhook(webhook)
        duplicate = handle_payos_webhook(webhook)

        self.assertEqual(handled.status, Payment.Status.SUCCESS)
        self.assertIsNone(duplicate)
        user_voucher.refresh_from_db()
        self.assertEqual(user_voucher.status, UserVoucher.Status.USED)
        self.assertIsNotNone(user_voucher.used_at)

    def test_failed_bank_transfer_releases_reserved_voucher(self):
        user_voucher = self._create_user_voucher(code='BANKFAILED')
        created = self._post_booking_with_voucher(
            user_voucher,
            payment_method=Payment.Method.BANK_TRANSFER,
        )
        payment = Payment.objects.get(booking_id=created.data['data']['id'])

        handle_payos_webhook(SimpleNamespace(
            order_code=payment.id,
            amount=payment.amount - Decimal('1'),
            reference='PAYOS-FAILED-1',
        ))

        payment.refresh_from_db()
        user_voucher.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.FAILED)
        self.assertEqual(user_voucher.status, UserVoucher.Status.AVAILABLE)

    def test_cash_booking_marks_voucher_used_when_worker_accepts(self):
        user_voucher = self._create_user_voucher(code='CASHACCEPTED')
        created = self._post_booking_with_voucher(
            user_voucher,
            payment_method=Payment.Method.CASH,
        )
        booking = Booking.objects.get(pk=created.data['data']['id'])
        worker = User.objects.create_user(
            username='voucher-cash-worker',
            email='voucher-cash-worker@example.com',
            password='CleanWise@2026!',
            role=User.Role.WORKER,
        )
        WorkerProfile.objects.create(
            user=worker,
            status=WorkerProfile.Status.ACTIVE,
            registered_service=self.service,
        )
        area = Area.objects.create(name='Khu vực test', city='TP.HCM')
        WorkerWorkingArea.objects.create(worker=worker, area=area)

        claim_schedule(schedule_id=booking.schedules.get().id, worker=worker)

        booking.refresh_from_db()
        user_voucher.refresh_from_db()
        self.assertEqual(booking.status, Booking.Status.ASSIGNED)
        self.assertEqual(user_voucher.status, UserVoucher.Status.USED)
        self.assertIsNotNone(user_voucher.used_at)

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
            'service_data': {**self._valid_service_data(), 'duration': '2_HOURS'},
            'schedules': [self._valid_schedule()],
            'payment_method': 'CASH',
        }, format='json')
        self.client.force_authenticate(self.customer)
        response = self.client.get(reverse('customer-booking-list-create'))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data['data']['count'], 0)
