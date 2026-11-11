from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.bookings.booking_service import create_booking
from apps.bookings.models import Booking, BookingSchedule, BookingScheduleImage
from apps.complaints.models import Complaint, ComplaintIssueType
from apps.payments.models import Payment
from apps.payments.webhook_service import handle_payos_webhook
from apps.services.models import Service
from apps.worker.models import BookingAssignment

from .earning_service import record_schedule_earning, settle_pending_online_earnings
from .models import Wallet, WalletTransaction, WorkerEarning


class ImmediateEarningsTests(APITestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model().objects
        cls.customer = users.create_user(username='code07-customer', email='code07-customer@test.com', role='CUSTOMER')
        cls.worker = users.create_user(username='code07-worker', email='code07-worker@test.com', role='WORKER')
        cls.admin = users.create_user(username='code07-admin', email='code07-admin@test.com', role='ADMIN')
        cls.customer_wallet = Wallet.objects.create(user=cls.customer, balance=350000)
        cls.worker_wallet = Wallet.objects.create(user=cls.worker, balance=500000)
        address = CustomerAddress.objects.create(customer=cls.customer, address_line='Địa chỉ mẫu', city='TP.HCM')
        service = Service.objects.create(name='Dọn nhà', code='CODE07', section_code='HOME_CLEANING',
                                         form_schema={}, pricing_config={})
        cls.booking = Booking.objects.create(booking_code='CODE-07-TEST', customer=cls.customer,
            service=service, address=address, service_data={}, status=Booking.Status.COMPLETED,
            payment_status=Booking.PaymentStatus.PAID, total_amount=150000, subtotal_amount=150000)
        now = timezone.now()
        cls.schedule = BookingSchedule.objects.create(booking=cls.booking, sequence_no=1,
            scheduled_start=now - timedelta(hours=2), scheduled_end=now,
            actual_start=now - timedelta(hours=2), actual_end=now, status=BookingSchedule.Status.COMPLETED)
        cls.payment = Payment.objects.create(customer=cls.customer, booking=cls.booking, amount=150000,
            method=Payment.Method.WALLET, status=Payment.Status.SUCCESS, paid_at=now)
        cls.issue = ComplaintIssueType.objects.create(code='CODE07_QUALITY', name='Chất lượng dịch vụ')

    def complaint(self):
        return Complaint.objects.create(booking=self.booking, schedule=self.schedule, issue_type=self.issue,
            reporter=self.customer, reporter_role=Complaint.ReporterRole.CUSTOMER,
            worker=self.worker, stage=Complaint.Stage.AFTER_SERVICE)

    def record(self):
        return record_schedule_earning(schedule=self.schedule, booking=self.booking, worker=self.worker)

    def preview(self, complaint, outcome):
        return self.client.get(reverse('admin-complaint-preview', args=[complaint.pk]), {'outcome': outcome})

    def resolve(self, complaint, outcome, note='Đã xác minh bằng chứng'):
        return self.client.post(reverse('admin-complaint-resolve', args=[complaint.pk]), {
            'outcome': outcome, 'status': Complaint.Status.RESOLVED, 'resolution_note': note,
        }, format='json')

    def test_checkout_credits_wallet_immediately_with_open_complaint_and_no_double_credit(self):
        complaint = self.complaint()
        self.booking.status = Booking.Status.IN_PROGRESS
        self.booking.save(update_fields=['status'])
        self.schedule.status = BookingSchedule.Status.IN_PROGRESS
        self.schedule.actual_end = None
        self.schedule.save(update_fields=['status', 'actual_end'])
        BookingAssignment.objects.create(schedule=self.schedule, worker=self.worker, status=BookingAssignment.Status.ACCEPTED)
        for image_type in ('BEFORE', 'AFTER'):
            BookingScheduleImage.objects.create(schedule=self.schedule, uploaded_by=self.worker,
                                                image_type=image_type, image='code07.jpg')
        self.client.force_authenticate(self.worker)
        response = self.client.post(reverse('worker-schedule-check-out', args=[self.schedule.pk]), {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.schedule.refresh_from_db()
        earning = self.record()
        settle_pending_online_earnings()
        self.assertIsNotNone(earning.wallet_credited_at)
        self.worker_wallet.refresh_from_db()
        self.customer_wallet.refresh_from_db()
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PENDING)
        self.assertEqual(self.worker_wallet.balance, Decimal(635000))
        self.assertEqual(self.customer_wallet.balance, Decimal(350000))
        self.assertEqual(WalletTransaction.objects.filter(idempotency_key=f'earning:{earning.id}').count(), 1)

    def test_existing_pending_earnings_are_credited_without_waiting(self):
        self.complaint()
        earning = WorkerEarning.objects.create(worker=self.worker, schedule=self.schedule, booking=self.booking,
            payment_method=WorkerEarning.PaymentMethod.ONLINE, gross_amount=150000, commission_rate=Decimal('0.10'),
            commission_amount=15000, worker_amount=135000, completed_at=timezone.now())
        settle_pending_online_earnings()
        settle_pending_online_earnings()
        earning.refresh_from_db()
        self.worker_wallet.refresh_from_db()
        self.assertIsNotNone(earning.wallet_credited_at)
        self.assertEqual(self.worker_wallet.balance, Decimal(635000))

    def test_unpaid_online_earning_is_credited_when_transfer_succeeds(self):
        self.booking.payment_status = Booking.PaymentStatus.UNPAID
        self.booking.save(update_fields=['payment_status'])
        Payment.objects.filter(pk=self.payment.pk).update(
            method=Payment.Method.BANK_TRANSFER, status=Payment.Status.PENDING, paid_at=None,
        )
        earning = self.record()
        settle_pending_online_earnings()
        earning.refresh_from_db()
        self.assertIsNone(earning.wallet_credited_at)

        event = SimpleNamespace(order_code=self.payment.pk, amount=150000, reference='CODE07-TRANSFER')
        handle_payos_webhook(event)
        handle_payos_webhook(event)
        earning.refresh_from_db()
        self.booking.refresh_from_db()
        self.worker_wallet.refresh_from_db()
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertIsNotNone(earning.wallet_credited_at)
        self.assertEqual(self.worker_wallet.balance, Decimal(635000))
        self.assertEqual(WalletTransaction.objects.filter(idempotency_key=f'earning:{earning.id}').count(), 1)

    def test_cash_earning_deducts_only_the_commission_and_never_credits_worker_pay(self):
        Payment.objects.filter(pk=self.payment.pk).update(method=Payment.Method.CASH)
        earning = self.record()
        self.record()
        self.worker_wallet.refresh_from_db()
        self.assertEqual(earning.payment_method, WorkerEarning.PaymentMethod.CASH)
        self.assertIsNone(earning.wallet_credited_at)
        self.assertEqual(self.worker_wallet.balance, Decimal(485000))
        self.assertEqual(WalletTransaction.objects.filter(wallet=self.worker_wallet).count(), 1)

    def test_wallet_payment_debits_customer_at_booking_creation(self):
        service = self.booking.service
        service.form_schema = {'fields': [
            {'key': 'date', 'type': 'DATE'},
            {'key': 'start_time', 'type': 'TIME'},
            {'key': 'duration', 'type': 'SINGLE_SELECT', 'options': [{'value': '2_HOURS'}]},
        ]}
        service.pricing_config = {'base_prices': {'2_HOURS': 150000}}
        service.save(update_fields=['form_schema', 'pricing_config'])
        booking = create_booking(
            customer=self.customer, service_id=service.pk, address_id=self.booking.address_id,
            service_data={'date': (timezone.localdate() + timedelta(days=1)).isoformat(),
                          'start_time': '09:00', 'duration': '2_HOURS'},
            payment_method=Payment.Method.WALLET,
        )
        self.customer_wallet.refresh_from_db()
        self.assertEqual(self.customer_wallet.balance, Decimal(200000))
        self.assertEqual(booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertFalse(WorkerEarning.objects.filter(booking=booking).exists())

    def test_used_service_cannot_be_refunded_through_complaint(self):
        complaint = self.complaint()
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.preview(complaint, Complaint.Outcome.REFUND_CUSTOMER).status_code, 400)
        response = self.resolve(complaint, Complaint.Outcome.REFUND_CUSTOMER)
        self.assertEqual(response.status_code, 400, response.data)
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.PENDING)
        self.assertFalse(WalletTransaction.objects.filter(wallet=self.customer_wallet).exists())

    def test_unused_service_can_still_be_refunded_through_complaint(self):
        BookingSchedule.objects.filter(pk=self.schedule.pk).update(
            actual_start=None, actual_end=None, status=BookingSchedule.Status.PENDING,
        )
        complaint = self.complaint()
        self.client.force_authenticate(self.admin)
        outcome = Complaint.Outcome.REFUND_CUSTOMER
        self.assertEqual(self.preview(complaint, outcome).status_code, 200)
        response = self.resolve(complaint, outcome)
        self.assertEqual(response.status_code, 200, response.data)
        self.customer_wallet.refresh_from_db()
        self.assertEqual(self.customer_wallet.balance, Decimal(500000))

    def test_admin_can_recover_worker_pay_once_without_refunding_customer(self):
        earning = self.record()
        complaint = self.complaint()
        self.client.force_authenticate(self.admin)
        outcome = Complaint.Outcome.RECOVER_WORKER_EARNING
        preview = self.preview(complaint, outcome)
        self.assertEqual(preview.status_code, 200, preview.data)
        self.assertEqual(Decimal(preview.data['worker_delta']), Decimal(-135000))
        self.assertEqual(self.resolve(complaint, outcome, note='').status_code, 400)
        response = self.resolve(complaint, outcome)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.resolve(complaint, outcome).status_code, 400)
        self.assertEqual(self.resolve(self.complaint(), outcome).status_code, 400)

        earning.refresh_from_db()
        self.worker_wallet.refresh_from_db()
        self.customer_wallet.refresh_from_db()
        self.booking.refresh_from_db()
        complaint.refresh_from_db()
        self.assertIsNotNone(earning.voided_at)
        self.assertEqual(self.worker_wallet.balance, Decimal(500000))
        self.assertEqual(self.customer_wallet.balance, Decimal(350000))
        self.assertEqual(self.booking.payment_status, Booking.PaymentStatus.PAID)
        self.assertEqual(complaint.customer_delta, 0)
        self.assertEqual(complaint.worker_delta, Decimal(-135000))

    def test_worker_recovery_records_shortfall_and_never_makes_wallet_negative(self):
        self.record()
        Wallet.objects.filter(pk=self.worker_wallet.pk).update(balance=10000)
        complaint = self.complaint()
        self.client.force_authenticate(self.admin)
        response = self.resolve(complaint, Complaint.Outcome.RECOVER_WORKER_EARNING)
        self.assertEqual(response.status_code, 200, response.data)
        complaint.refresh_from_db()
        self.worker_wallet.refresh_from_db()
        self.assertEqual(self.worker_wallet.balance, 0)
        self.assertEqual(complaint.worker_delta, Decimal(-10000))
        self.assertEqual(complaint.shortfall, Decimal(125000))
