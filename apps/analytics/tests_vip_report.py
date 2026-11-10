from datetime import datetime, timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.bookings.models import Booking
from apps.services.models import Service
from apps.vouchers.models import UserVoucher, Voucher
from .models import MonthlyVipReward
from .report_service import ZONE

User = get_user_model()


class VipReportTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='vip-admin', email='vip-admin@test.com', role='ADMIN')
        self.customers = [User.objects.create_user(username=f'vip-{i}', email=f'vip-{i}@test.com', role='CUSTOMER') for i in range(2)]
        self.service = Service.objects.create(code='VIP-TEST', section_code='HOME_CLEANING', name='VIP test', description='', form_schema={}, pricing_config={})
        self.addresses = [CustomerAddress.objects.create(customer=c, receiver_name='Test', receiver_phone='0900000000', address_line='123 Test', city='HCM') for c in self.customers]
        for i in range(5):
            for ci in range(2):
                self.booking(ci, f'{ci}-{i}')
        now = timezone.now()
        self.voucher = Voucher.objects.create(code='VIP50', name='VIP', distribution_type='ASSIGNED', discount_type='FIXED', discount_value=50000,
            min_order_amount=300000, start_at=now-timedelta(days=1), end_at=now+timedelta(days=30), issuance_limit=10)
        self.client.force_authenticate(self.admin)
        self.params = {'year':2026,'month':10,'min_bookings':5}

    def booking(self, ci, code, status='COMPLETED', payment='PAID', created='2026-10-10T09:00:00+07:00', refunded=0):
        b = Booking.objects.create(booking_code='VIP-'+code,customer=self.customers[ci],address=self.addresses[ci],service=self.service,
            service_data={},status=status,payment_status=payment,total_amount=300000,refunded_amount=refunded)
        Booking.objects.filter(pk=b.pk).update(created_at=datetime.fromisoformat(created))
        return b

    def report(self, **extra):
        return self.client.get(reverse('admin-report-vip-customers'),{**self.params,**extra})

    def reward(self, **extra):
        return self.client.post(reverse('admin-report-vip-reward'),{**self.params,'voucher_id':self.voucher.pk,'customer_ids':[c.pk for c in self.customers],**extra},format='json')

    def test_month_basis_and_pagination(self):
        self.booking(0,'cancel',status='CANCELLED')
        self.booking(0,'unpaid',payment='UNPAID')
        self.booking(0,'refund',refunded=1)
        self.booking(0,'old',created='2026-09-30T23:59:59+07:00')
        self.booking(0,'next',created='2026-11-01T00:00:00+07:00')
        response=self.report(page_size=1)
        self.assertEqual(response.status_code,200,response.data)
        data=response.data['data']
        self.assertEqual(data['count'],2)
        self.assertTrue(data['has_next'])
        self.assertEqual(data['results'][0]['booking_count'],5)
        self.assertEqual(data['results'][0]['completed_value'],'1500000.00')
        self.assertEqual(self.report(page=3,page_size=1).status_code,400)

    def test_rewards_idempotent_across_voucher_codes_and_update_report(self):
        self.assertEqual(self.reward().data['data']['assigned_count'],2)
        self.assertEqual(self.reward().data['data']['skipped_count'],2)
        another=Voucher.objects.create(code='VIP100',name='VIP100',distribution_type='ASSIGNED',discount_type='FIXED',discount_value=100000,
            start_at=self.voucher.start_at,end_at=self.voucher.end_at)
        self.assertEqual(self.reward(voucher_id=another.pk).data['data']['assigned_count'],0)
        self.assertEqual(MonthlyVipReward.objects.count(),2)
        self.assertEqual(UserVoucher.objects.count(),2)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.issued_count,2)
        self.assertEqual(self.report().data['data']['summary']['rewarded'],2)

    def test_insufficient_capacity_rolls_back_entire_batch(self):
        self.voucher.issuance_limit=1
        self.voucher.save()
        self.assertEqual(self.reward().status_code,400)
        self.assertEqual(UserVoucher.objects.count(),0)
        self.assertEqual(MonthlyVipReward.objects.count(),0)
        self.voucher.refresh_from_db()
        self.assertEqual(self.voucher.issued_count,0)

    def test_rechecks_eligibility_and_rejects_public_expired_or_inactive(self):
        self.assertEqual(self.reward(min_bookings=6).status_code,400)
        for field,value in [('distribution_type','PUBLIC'),('end_at',timezone.now()-timedelta(minutes=1)),('is_active',False)]:
            original=getattr(self.voucher,field)
            setattr(self.voucher,field,value);self.voucher.save()
            self.assertEqual(self.reward().status_code,400)
            setattr(self.voucher,field,original);self.voucher.save()
        self.assertEqual(UserVoucher.objects.count(),0)

    def test_only_admin_can_access_reports_and_reward(self):
        self.client.force_authenticate(self.customers[0])
        self.assertEqual(self.report().status_code,403)
        self.assertEqual(self.reward().status_code,403)
        self.assertEqual(self.client.get(reverse('admin-report-audit')).status_code,403)

    @override_settings(DEBUG=True)
    def test_seed_repeatable_and_contains_vip_rewarded_and_audit_cases(self):
        args={'date':'2026-10-01','months':2,'stdout':StringIO()}
        call_command('seed_statistics_hub',**args)
        orders=Booking.objects.count()
        rewards=MonthlyVipReward.objects.count()
        call_command('seed_statistics_hub',**args)
        self.assertEqual(Booking.objects.count(),orders)
        self.assertEqual(MonthlyVipReward.objects.count(),rewards)
        self.assertGreater(self.report().data['data']['summary']['rewarded'],0)
        audit=self.client.get(reverse('admin-report-audit'),{'period':'month','date':'2026-10-01','kind':'missing_earning'})
        self.assertEqual(audit.status_code,200,audit.data)
        self.assertGreater(audit.data['data']['count'],0)
        self.assertEqual(self.client.get(reverse('admin-report-audit'),{'kind':'unknown'}).status_code,400)
