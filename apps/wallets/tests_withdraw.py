"""
Test luồng rút tiền với mock payout (4 số cuối STK quyết định kịch bản).
Chạy: python manage.py test apps.wallets.tests_withdraw

LƯU Ý: chỉnh hàm _make_user cho khớp model User của bạn (field bắt buộc: phone_number, email...).
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from apps.common.encryption import encrypt_value
from apps.payments.models import UserPaymentMethod

from . import wallet_service, withdraw_service
from .models import Wallet, WalletTransaction, WithdrawRequest

User = get_user_model()


def _make_user():
    return User.objects.create_user(
        username='cust_withdraw', email='cust_withdraw@test.local',
        password='x', role='CUSTOMER',
    )


@override_settings(
    PAYOUT_MODE='mock', TOPUP_MODE='mock', PAYOUT_ALLOW_MOCK=True,
    PAYOUT_METHOD_COOLDOWN_HOURS=0,
)
class WithdrawFlowTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = _make_user()
        wallet_service.credit_wallet(
            user=self.user, amount=Decimal('1000000'),
            type=WalletTransaction.Type.TOPUP, idempotency_key='seed-balance',
        )

    # ---- helpers
    def _bank(self, last4):
        return UserPaymentMethod.objects.create(
            user=self.user,
            method_type=UserPaymentMethod.MethodType.BANK_ACCOUNT,
            usage_type=UserPaymentMethod.UsageType.PAYMENT,
            bank_bin='970422', bank_code='MB', bank_name='MBBank',
            account_holder_name='NGUYEN VAN A',
            account_number_encrypted=encrypt_value(f'000000{last4}'),
            account_number_last4=last4,
            is_default=True,
        )

    def _withdraw(self, last4, amount='50000'):
        self._bank(last4)
        return withdraw_service.create_withdraw(user=self.user, amount=Decimal(amount))

    def _balance(self):
        return Wallet.objects.get(user=self.user).balance

    # ---- kịch bản
    def test_success_immediately(self):
        w = self._withdraw('5555')
        self.assertEqual(w.status, WithdrawRequest.Status.SUCCESS)
        self.assertEqual(self._balance(), Decimal('950000'))

    def test_rejected_first_call_refunds_once(self):
        w = self._withdraw('2222')
        self.assertEqual(w.status, WithdrawRequest.Status.FAILED)
        self.assertEqual(self._balance(), Decimal('1000000'))

    def test_bank_failed_refunds_once_and_finalize_is_idempotent(self):
        w = self._withdraw('0000')
        self.assertEqual(w.status, WithdrawRequest.Status.FAILED)
        self.assertEqual(self._balance(), Decimal('1000000'))
        withdraw_service._finalize(w.pk, success=False, reason='gọi lại')
        withdraw_service._finalize(w.pk, success=True)
        self.assertEqual(self._balance(), Decimal('1000000'))  # không hoàn lần 2
        w.refresh_from_db()
        self.assertEqual(w.status, WithdrawRequest.Status.FAILED)

    def test_pending_stays_processing_and_balance_held(self):
        w = self._withdraw('1111')
        self.assertEqual(w.status, WithdrawRequest.Status.PROCESSING)
        self.assertEqual(self._balance(), Decimal('950000'))

    def test_network_error_then_retry_succeeds_without_refund(self):
        w = self._withdraw('3333')
        self.assertEqual(w.status, WithdrawRequest.Status.PROCESSING)
        self.assertTrue(w.had_unknown_result)
        w = withdraw_service.refresh_withdraw(w, force=True)
        self.assertEqual(w.status, WithdrawRequest.Status.SUCCESS)
        self.assertEqual(self._balance(), Decimal('950000'))

    def test_unknown_then_rejected_goes_to_review_and_never_refunds(self):
        w = self._withdraw('4444')
        self.assertTrue(w.had_unknown_result)
        w = withdraw_service.refresh_withdraw(w, force=True)
        self.assertEqual(w.status, WithdrawRequest.Status.PROCESSING)
        self.assertTrue(w.needs_review)
        self.assertEqual(self._balance(), Decimal('950000'))  # TIỀN KHÔNG ĐƯỢC HOÀN

        # task đồng bộ không được đụng vào lệnh needs_review nữa
        withdraw_service.sync_processing_withdraws(min_age_seconds=0)
        w.refresh_from_db()
        self.assertTrue(w.needs_review)
        self.assertEqual(self._balance(), Decimal('950000'))

    def test_admin_resolve_failed_refunds_exactly_once(self):
        w = self._withdraw('4444')
        w = withdraw_service.refresh_withdraw(w, force=True)
        admin = User.objects.create_user(
            username='adm_withdraw', email='adm_withdraw@test.local',
            password='x', role='ADMIN',
        )
        withdraw_service.resolve_review(
            withdraw_id=w.pk, success=False, admin_user=admin, note='Đã tra dashboard payOS: chưa chi',
        )
        self.assertEqual(self._balance(), Decimal('1000000'))
        with self.assertRaises(Exception):  # chốt lần 2 phải bị chặn
            withdraw_service.resolve_review(
                withdraw_id=w.pk, success=False, admin_user=admin, note='Gọi lại lần hai',
            )
        self.assertEqual(self._balance(), Decimal('1000000'))

    def test_daily_limit_blocks_excess(self):
        self._bank('5555')
        with override_settings(WALLET_WITHDRAW_DAILY_MAX=100000):
            withdraw_service.create_withdraw(user=self.user, amount=Decimal('60000'))
            with self.assertRaises(Exception):
                withdraw_service.create_withdraw(user=self.user, amount=Decimal('60000'))

    def test_insufficient_balance(self):
        self._bank('5555')
        with self.assertRaises(Exception):
            withdraw_service.create_withdraw(user=self.user, amount=Decimal('1500000'))
        self.assertEqual(self._balance(), Decimal('1000000'))