from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from .models import Wallet, WalletTransaction

# Mức ký quỹ tối thiểu nhân viên phải duy trì trong ví — không được rút xuống dưới mức này.
MIN_WORKER_ESCROW_BALANCE = Decimal('400000')


@transaction.atomic
def credit_wallet(*, user, amount, type=WalletTransaction.Type.REFUND, booking=None, note=None):
    """Cộng tiền vào ví (refund, adjustment...)."""
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    wallet.balance += Decimal(amount)
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=type, amount=amount, balance_after=wallet.balance,
        status=WalletTransaction.Status.SUCCESS, booking=booking, note=note,
    )


@transaction.atomic
def debit_wallet(*, user, amount, type=WalletTransaction.Type.PAYMENT, booking=None, note=None):
    """Trừ tiền trong ví (thanh toán bằng ví cho đơn khác)."""
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    if wallet.balance < amount:
        shortage = Decimal(amount) - wallet.balance
        raise serializers.ValidationError({
            'amount': f'Số dư ví không đủ. Cần nạp thêm {shortage:,.0f}đ.',
        })

    wallet.balance -= Decimal(amount)
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=type, amount=amount, balance_after=wallet.balance,
        status=WalletTransaction.Status.SUCCESS, booking=booking, note=note,
    )


@transaction.atomic
def request_withdraw(*, user, amount, min_remaining_balance=Decimal('0')):
    """Yêu cầu rút tiền — trừ balance ngay, tạo transaction PENDING chờ admin duyệt.

    min_remaining_balance: số dư tối thiểu phải còn lại sau khi rút.
    Khách hàng: 0 (rút hết được). Nhân viên ký quỹ: MIN_WORKER_ESCROW_BALANCE.
    """
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    remaining = wallet.balance - Decimal(amount)
    if remaining < min_remaining_balance:
        raise serializers.ValidationError({
            'amount': f'Số dư sau khi rút phải còn lại tối thiểu {min_remaining_balance:,.0f}đ.',
        })

    wallet.balance = remaining
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=WalletTransaction.Type.WITHDRAW, amount=amount,
        balance_after=wallet.balance, status=WalletTransaction.Status.PENDING,
    )


def request_worker_withdraw(*, user, amount):
    """Nhân viên rút tiền ký quỹ — bắt buộc chừa lại tối thiểu mức ký quỹ 400.000đ."""
    return request_withdraw(user=user, amount=amount, min_remaining_balance=MIN_WORKER_ESCROW_BALANCE)


@transaction.atomic
def admin_confirm_withdraw(*, transaction_id):
    """Admin xác nhận đã chuyển khoản thật cho khách."""
    tx = get_object_or_404(
        WalletTransaction.objects.select_for_update(),
        pk=transaction_id, type=WalletTransaction.Type.WITHDRAW, status=WalletTransaction.Status.PENDING,
    )
    tx.status = WalletTransaction.Status.SUCCESS
    tx.save(update_fields=['status', 'updated_at'])
    return tx


@transaction.atomic
def admin_reject_withdraw(*, transaction_id, reason=None):
    """Admin từ chối yêu cầu rút -> hoàn lại balance vào ví."""
    tx = get_object_or_404(
        WalletTransaction.objects.select_for_update(),
        pk=transaction_id, type=WalletTransaction.Type.WITHDRAW, status=WalletTransaction.Status.PENDING,
    )
    wallet = Wallet.objects.select_for_update().get(pk=tx.wallet_id)
    wallet.balance += tx.amount
    wallet.save(update_fields=['balance', 'updated_at'])

    tx.status = WalletTransaction.Status.FAILED
    tx.note = reason or tx.note
    tx.save(update_fields=['status', 'note', 'updated_at'])
    return tx