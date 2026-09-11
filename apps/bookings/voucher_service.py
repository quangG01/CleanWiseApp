from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from .models import BookingVoucher, Voucher


MONEY_QUANTIZER = Decimal('0.01')


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

    `lock=True` dành cho transaction tạo booking để khóa voucher, tránh vượt usage_limit.
    Hàm này không tăng used_count và không tạo BookingVoucher.
    """
    normalized_code = (code or '').strip().upper()
    if not normalized_code:
        raise serializers.ValidationError({'code': 'Vui lòng nhập mã voucher.'})

    if lock and not transaction.get_connection().in_atomic_block:
        raise RuntimeError('lock=True phải được gọi bên trong transaction.atomic().')

    queryset = Voucher.objects
    if lock:
        queryset = queryset.select_for_update()
    voucher = queryset.filter(code__iexact=normalized_code).first()
    if not voucher:
        raise serializers.ValidationError({'code': 'Voucher không tồn tại.'})

    now = timezone.now()
    if not voucher.is_active:
        raise serializers.ValidationError({'code': 'Voucher đã ngừng hoạt động.'})
    if now < voucher.start_at:
        raise serializers.ValidationError({'code': 'Voucher chưa đến thời gian sử dụng.'})
    if now > voucher.end_at:
        raise serializers.ValidationError({'code': 'Voucher đã hết hạn.'})
    if voucher.usage_limit is not None and voucher.used_count >= voucher.usage_limit:
        raise serializers.ValidationError({'code': 'Voucher đã hết lượt sử dụng.'})

    subtotal = _to_money(subtotal_amount)
    if subtotal < voucher.min_order_amount:
        raise serializers.ValidationError({
            'subtotal_amount': f'Đơn hàng tối thiểu phải đạt {voucher.min_order_amount}.'
        })

    customer_usage = BookingVoucher.objects.filter(
        voucher=voucher,
        booking__customer=customer,
        status__in=[BookingVoucher.Status.RESERVED, BookingVoucher.Status.USED],
    ).count()
    if customer_usage >= voucher.per_user_limit:
        raise serializers.ValidationError({'code': 'Bạn đã sử dụng hết số lượt cho voucher này.'})

    amounts = calculate_voucher_discount(voucher, subtotal)
    return {
        'voucher': voucher,
        **amounts,
    }
