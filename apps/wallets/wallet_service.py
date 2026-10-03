# apps/wallets/wallet_service.py

from decimal import Decimal

from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import serializers

from .models import Wallet, WalletTransaction

# Mức ký quỹ tối thiểu nhân viên phải duy trì trong ví — không được rút xuống dưới mức này.
MIN_WORKER_ESCROW_BALANCE = Decimal('400000')


def get_or_create_wallet_locked(user):
    """
    Lấy ví kèm lock (select_for_update), tự tạo nếu user chưa có ví.

    select_for_update() chỉ khóa được hàng ĐÃ TỒN TẠI. Nếu đây là lần đầu
    user thao tác ví, 2 request cùng lúc sẽ cùng "miss" (chưa có hàng để
    khóa) rồi cùng INSERT -> 1 trong 2 dính IntegrityError do OneToOneField
    unique trên user_id. Bắt lỗi đó trong 1 savepoint riêng (transaction.atomic
    lồng bên trong) để không làm hỏng transaction ngoài, rồi đọc lại lần nữa
    kèm lock — lúc này hàng đã tồn tại nên select_for_update lấy được bình
    thường.

    Dùng hàm này thay vì gọi thẳng Wallet.objects.select_for_update().get_or_create()
    ở MỌI nơi cần sửa balance.
    """
    wallet = Wallet.objects.select_for_update().filter(user=user).first()
    if wallet:
        return wallet, False

    try:
        with transaction.atomic():  # savepoint riêng, lỗi ở đây không kéo sập transaction cha
            wallet = Wallet.objects.create(user=user)
        return wallet, True
    except IntegrityError:
        # Request khác vừa tạo xong trong lúc mình insert -> lấy lại, lần này có lock thật
        return Wallet.objects.select_for_update().get(user=user), False


def get_or_create_wallet(user):
    """
    Bản không lock — dùng cho các view chỉ ĐỌC (GET số dư), không sửa balance.
    Vẫn cần bắt IntegrityError vì get_or_create() thường (không lock) cũng
    có thể dính race y hệt ở lần đầu.
    """
    try:
        return Wallet.objects.get_or_create(user=user)
    except IntegrityError:
        return Wallet.objects.get(user=user), False


@transaction.atomic
def credit_wallet(*, user, amount, type=WalletTransaction.Type.REFUND, booking=None, note=None,
                  idempotency_key=None, created_by=None):
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = get_or_create_wallet_locked(user)

    if idempotency_key:
        existing = WalletTransaction.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    wallet.balance += Decimal(amount)
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=type, amount=amount, balance_after=wallet.balance,
        status=WalletTransaction.Status.SUCCESS, booking=booking, note=note,
        idempotency_key=idempotency_key,
        direction=WalletTransaction.Direction.CREDIT, created_by=created_by,
    )


@transaction.atomic
def debit_wallet(*, user, amount, type=WalletTransaction.Type.PAYMENT, booking=None, note=None,
                 created_by=None):
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = get_or_create_wallet_locked(user)
    if wallet.balance < amount:
        shortage = Decimal(amount) - wallet.balance
        raise serializers.ValidationError({
            'amount': f'Số dư ví không đủ. Cần thêm {shortage:,.0f}đ.',
        })

    wallet.balance -= Decimal(amount)
    wallet.save(update_fields=['balance', 'updated_at'])

    return WalletTransaction.objects.create(
        wallet=wallet, type=type, amount=amount, balance_after=wallet.balance,
        status=WalletTransaction.Status.SUCCESS, booking=booking, note=note,
        direction=WalletTransaction.Direction.DEBIT, created_by=created_by,
    )

@transaction.atomic
def request_withdraw(*, user, amount, min_remaining_balance=Decimal('0')):
    """Yêu cầu rút tiền — trừ balance ngay, tạo transaction PENDING chờ admin duyệt.

    min_remaining_balance: số dư tối thiểu phải còn lại sau khi rút.
    Khách hàng: 0 (rút hết được). Nhân viên ký quỹ: MIN_WORKER_ESCROW_BALANCE.
    """
    if amount is None or amount <= 0:
        raise serializers.ValidationError({'amount': 'Số tiền phải lớn hơn 0.'})

    wallet, _ = get_or_create_wallet_locked(user)
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
        direction=WalletTransaction.Direction.DEBIT
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


@transaction.atomic
def admin_adjust_wallet(*, user, amount, direction, reason, admin_user, booking=None):
    reason = (reason or '').strip()
    if not reason:
        raise serializers.ValidationError({'reason': 'Vui lòng nhập lý do.'})

    note = f'[Admin {admin_user.username}] {reason}'
    fn = credit_wallet if direction == WalletTransaction.Direction.CREDIT else debit_wallet
    tx = fn(
        user=user, amount=amount, type=WalletTransaction.Type.ADJUSTMENT,
        booking=booking, note=note, created_by=admin_user,
    )

    from apps.notifications.services import notify_wallet_adjustment
    transaction.on_commit(lambda: notify_wallet_adjustment(user, amount, direction, reason))
    return tx