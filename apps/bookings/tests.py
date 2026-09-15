from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
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
        self.area = Area.objects.create(name='Trung tâm', district='Quận 1', city='TP.HCM')
        self.address = CustomerAddress.objects.create(
            customer=self.customer,
            area=self.area,
            receiver_name='Nguyễn Văn An',
            receiver_phone='0912345678',
            address_line='01 Nguyễn Huệ',
            ward='Bến Nghé',
            district='Quận 1',
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

    def test_address_api_requires_and_returns_area(self):
        self.client.force_authenticate(self.customer)
        response = self.client.post(reverse('customer-address-list-create'), {
            'area_id': self.area.id,
            'receiver_name': 'Nguyễn Văn B',
            'receiver_phone': '0987654321',
            'address_line': '02 Nguyễn Huệ',
            'ward': 'Bến Nghé',
            'district': 'Quận 1',
            'city': 'TP.HCM',
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data['data']['area']['id'], self.area.id)

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
    def test_discount_calculation_uses_simplified_voucher(self):
        now = timezone.now()
        customer = User.objects.create_user(
            username='voucher-user',
            email='voucher@example.com',
            password='CleanWise@2026!',
        )
        voucher = Voucher.objects.create(
            code='SAVE10',
            name='Giảm 10%',
            discount_type=Voucher.DiscountType.PERCENT,
            discount_value=Decimal('10'),
            min_order_amount=Decimal('100000'),
            start_at=now - timedelta(days=1),
            end_at=now + timedelta(days=1),
        )

        result = validate_and_calculate_voucher(
            code=voucher.code,
            customer=customer,
            subtotal_amount=Decimal('200000'),
        )
        self.assertEqual(result['discount_amount'], Decimal('20000.00'))
