from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from .models import Wallet, WalletTransaction


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
        raise serializers.ValidationError({'amount': 'Số dư ví không đủ.'})

    wallet.balance -= Decimal(amount)
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=type, amount=amount, balance_after=wallet.balance,
        status=WalletTransaction.Status.SUCCESS, booking=booking, note=note,
    )


@transaction.atomic
def request_withdraw(*, user, amount):
    """Khách yêu cầu rút tiền — trừ balance ngay, tạo transaction PENDING chờ admin duyệt."""
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    if wallet.balance < amount:
        raise serializers.ValidationError({'amount': 'Số dư ví không đủ để rút.'})

    wallet.balance -= Decimal(amount)
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=WalletTransaction.Type.WITHDRAW, amount=amount,
        balance_after=wallet.balance, status=WalletTransaction.Status.PENDING,
    )


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