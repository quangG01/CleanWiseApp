from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import UserVoucher, Voucher


MONEY_QUANTIZER = Decimal('0.01')


def _validate_claimable_voucher(voucher):
    now = timezone.now()
    if not voucher.is_active:
        raise serializers.ValidationError({'voucher': 'Voucher đã ngừng hoạt động.'})
    if now < voucher.start_at:
        raise serializers.ValidationError({'voucher': 'Voucher chưa đến thời gian nhận.'})
    if now > voucher.end_at:
        raise serializers.ValidationError({'voucher': 'Voucher đã hết hạn.'})
    if voucher.issuance_limit is not None and voucher.issued_count >= voucher.issuance_limit:
        raise serializers.ValidationError({'voucher': 'Voucher đã được nhận hết.'})


@transaction.atomic
def claim_voucher_by_code(*, code, customer):
    """Nhận voucher PUBLIC hoặc CODE_ONLY bằng mã và tăng bộ đếm phát hành an toàn."""
    normalized_code = (code or '').strip().upper()
    if not normalized_code:
        raise serializers.ValidationError({'code': 'Vui lòng nhập mã voucher.'})
    try:
        voucher = Voucher.objects.select_for_update().get(code__iexact=normalized_code)
    except Voucher.DoesNotExist:
        raise serializers.ValidationError({'code': 'Mã voucher không tồn tại.'})

    source_by_distribution = {
        Voucher.DistributionType.PUBLIC: UserVoucher.Source.PUBLIC,
        Voucher.DistributionType.CODE_ONLY: UserVoucher.Source.CODE,
    }
    source = source_by_distribution.get(voucher.distribution_type)
    if source is None:
        raise serializers.ValidationError({'code': 'Voucher này chỉ được quản trị viên cấp riêng.'})
    return _claim_locked_voucher(voucher=voucher, customer=customer, source=source)


def _claim_locked_voucher(*, voucher, customer, source):
    _validate_claimable_voucher(voucher)
    if UserVoucher.objects.filter(user=customer, voucher=voucher).exists():
        raise serializers.ValidationError({'voucher': 'Bạn đã nhận voucher này rồi.'})

    user_voucher = UserVoucher.objects.create(
        user=customer,
        voucher=voucher,
        source=source,
    )
    voucher.issued_count += 1
    voucher.save(update_fields=['issued_count', 'updated_at'])
    return user_voucher


def _to_money(value, field_name='subtotal_amount'):
    try:
        amount = Decimal(str(value)).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        raise serializers.ValidationError({field_name: 'Số tiền không hợp lệ.'})
    if amount < 0:
        raise serializers.ValidationError({field_name: 'Số tiền không được âm.'})
    return amount


def calculate_voucher_discount(voucher, subtotal_amount):
    """Tính tiền giảm và tổng tiền, không truy cập hay thay đổi database."""
    subtotal = _to_money(subtotal_amount)
    if voucher.discount_type == Voucher.DiscountType.PERCENT:
        discount = subtotal * voucher.discount_value / Decimal('100')
        if voucher.max_discount_amount is not None:
            discount = min(discount, voucher.max_discount_amount)
    else:
        discount = voucher.discount_value

    discount = min(discount, subtotal).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)
    total = (subtotal - discount).quantize(MONEY_QUANTIZER, rounding=ROUND_HALF_UP)
    return {
        'subtotal_amount': subtotal,
        'discount_amount': discount,
        'total_amount': total,
    }


def validate_and_calculate_voucher(*, code, customer, subtotal_amount, lock=False):
    """
    Kiểm tra mọi điều kiện voucher và tính tiền.

    `lock=True` dành cho transaction tạo booking để khóa voucher của người dùng,
    tránh cùng một voucher được áp dụng đồng thời cho nhiều booking.
    """
    normalized_code = (code or '').strip().upper()
    if not normalized_code:
        raise serializers.ValidationError({'code': 'Vui lòng nhập mã voucher.'})

    if lock and not transaction.get_connection().in_atomic_block:
        raise RuntimeError('lock=True phải được gọi bên trong transaction.atomic().')

    queryset = UserVoucher.objects.select_related('voucher')
    if lock:
        queryset = queryset.select_for_update()
    user_voucher = queryset.filter(
        user=customer,
        voucher__code__iexact=normalized_code,
    ).first()
    if not user_voucher:
        raise serializers.ValidationError({'code': 'Voucher chưa có trong ví của bạn.'})

    if user_voucher.status != UserVoucher.Status.AVAILABLE:
        status_messages = {
            UserVoucher.Status.RESERVED: 'Voucher đang được giữ cho một booking khác.',
            UserVoucher.Status.USED: 'Voucher đã được sử dụng.',
            UserVoucher.Status.REVOKED: 'Voucher đã bị thu hồi.',
        }
        raise serializers.ValidationError({
            'code': status_messages.get(user_voucher.status, 'Voucher không thể sử dụng.')
        })

    voucher = user_voucher.voucher

    now = timezone.now()
    if not voucher.is_active:
        raise serializers.ValidationError({'code': 'Voucher đã ngừng hoạt động.'})
    if now < voucher.start_at:
        raise serializers.ValidationError({'code': 'Voucher chưa đến thời gian sử dụng.'})
    if now > voucher.end_at:
        raise serializers.ValidationError({'code': 'Voucher đã hết hạn.'})
    subtotal = _to_money(subtotal_amount)
    if subtotal < voucher.min_order_amount:
        raise serializers.ValidationError({
            'subtotal_amount': f'Đơn hàng tối thiểu phải đạt {voucher.min_order_amount}.'
        })

    amounts = calculate_voucher_discount(voucher, subtotal)
    return {
        'user_voucher': user_voucher,
        'voucher': voucher,
        **amounts,
    }
