import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.services.models import Service
from apps.addresses.models import CustomerAddress
from apps.vouchers.models import UserVoucher
from apps.vouchers.voucher_service import validate_and_calculate_voucher

from .models import Booking, BookingSchedule
from .service_data_validation import validate_service_data


PRICE_DRIVEN_KEYS = ('base_prices', 'price_matrix', 'unit_prices')
TWO_PLACES = Decimal('0.01')


def _q(amount):
    """Làm tròn 2 chữ số thập phân."""
    if amount is None:
        return None
    return Decimal(amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def is_computable_pricing(pricing_config):
    return any(k in (pricing_config or {}) for k in PRICE_DRIVEN_KEYS)


def _find_field_by_option_values(fields, candidate_values, exclude_key=None):
    for f in fields:
        if f.get('key') == exclude_key:
            continue

        options = f.get('options')

        if not options or 'when' in options[0]:
            continue

        if any(o.get('value') in candidate_values for o in options):
            return f

    return None


def get_unit_price_for_item(pricing_config, item_fields, item):
    if not pricing_config.get('unit_prices'):
        return None

    node = pricing_config['unit_prices']

    for sub in item_fields:
        # QUANTITY và BOOLEAN không dùng để lookup giá
        if sub.get('type') in ('QUANTITY', 'BOOLEAN'):
            continue

        if not isinstance(node, dict):
            return None

        key = sub['key']
        value = item.get(key)

        if value is not None and value in node:
            node = node[value]
        else:
            return None

    try:
        return Decimal(str(node))
    except (TypeError, ValueError, ArithmeticError):
        return None


def get_item_total_price(pricing_config, item_fields, item):
    unit_price = get_unit_price_for_item(
        pricing_config,
        item_fields,
        item,
    )

    if unit_price is None:
        return None

    qty = item.get('quantity', 1)

    try:
        qty = Decimal(str(qty))
    except (TypeError, ValueError, ArithmeticError):
        return None

    total = unit_price * qty

    for f in item_fields:
        if f.get('type') == 'BOOLEAN' and item.get(f['key']):
            surcharge = pricing_config.get(f"{f['key']}_price")

            if surcharge is not None:
                try:
                    total += Decimal(str(surcharge)) * qty
                except (TypeError, ValueError, ArithmeticError):
                    pass

    return _q(total)


def calculate_booking_price(service, service_data):
    """
    Tính giá booking dựa trên pricing_config của Service.
    Trả về Decimal nếu tính được, None nếu chưa đủ thông tin.
    """

    pricing_config = service.pricing_config or {}
    fields = (service.form_schema or {}).get('fields', [])

    total = Decimal('0')
    has_base = False

    if pricing_config.get('price_matrix'):
        price_matrix = pricing_config['price_matrix']

        outer_field = _find_field_by_option_values(
            fields,
            list(price_matrix.keys()),
        )

        outer_value = (
            service_data.get(outer_field['key'])
            if outer_field
            else None
        )

        inner_map = (
            price_matrix.get(outer_value)
            if outer_value
            else None
        )

        if inner_map:
            inner_field = _find_field_by_option_values(
                fields,
                list(inner_map.keys()),
                exclude_key=(
                    outer_field['key']
                    if outer_field
                    else None
                ),
            )

            inner_value = (
                service_data.get(inner_field['key'])
                if inner_field
                else None
            )

            price = inner_map.get(inner_value)

            if price is not None:
                try:
                    total += Decimal(str(price))
                    has_base = True
                except (TypeError, ValueError, ArithmeticError):
                    pass


    elif pricing_config.get('base_prices'):
        base_prices = pricing_config['base_prices']

        field = _find_field_by_option_values(
            fields,
            list(base_prices.keys()),
        )

        value = (
            service_data.get(field['key'])
            if field
            else None
        )

        price = base_prices.get(value)

        if price is not None:
            try:
                total += Decimal(str(price))
                has_base = True
            except (TypeError, ValueError, ArithmeticError):
                pass


    for key, val in pricing_config.items():
        if key.endswith('_surcharge') and isinstance(val, dict):
            field = _find_field_by_option_values(
                fields,
                list(val.keys()),
            )

            value = (
                service_data.get(field['key'])
                if field
                else None
            )

            price = val.get(value)

            if price is not None:
                try:
                    total += Decimal(str(price))
                except (TypeError, ValueError, ArithmeticError):
                    pass


    if pricing_config.get('additional_services'):
        additional_services = pricing_config['additional_services']

        field = next(
            (
                f
                for f in fields
                if f.get('type') == 'MULTI_SELECT'
            ),
            None,
        )

        selected = (
            service_data.get(field['key'], [])
            if field
            else []
        )

        for value in selected:
            price = additional_services.get(value)

            if price is not None:
                try:
                    total += Decimal(str(price))
                except (TypeError, ValueError, ArithmeticError):
                    pass


    if pricing_config.get('unit_prices'):
        group_field = next(
            (
                f
                for f in fields
                if f.get('type') == 'REPEATABLE_GROUP'
            ),
            None,
        )

        if group_field:
            group_key = group_field['key']
            items = service_data.get(group_key, [])

            for item in items:
                item_total = get_item_total_price(
                    pricing_config,
                    group_field.get('item_fields', []),
                    item,
                )

                if item_total is not None:
                    total += item_total
                    has_base = True


    if not has_base and total == 0:
        return None

    result = _q(total)

    return result


def _generate_booking_code():
    return f"CW-{uuid.uuid4().hex[:10].upper()}"


def _validate_schedules(schedules):
    if not schedules:
        raise serializers.ValidationError(
            {'schedules': 'Cần ít nhất 1 buổi làm việc.'}
        )

    now = timezone.now()

    for idx, sch in enumerate(schedules, start=1):
        if sch['scheduled_start'] <= now:
            raise serializers.ValidationError(
                {
                    'schedules':
                    f'Buổi {idx}: thời gian bắt đầu phải ở tương lai.'
                }
            )

        if sch['scheduled_start'] >= sch['scheduled_end']:
            raise serializers.ValidationError(
                {
                    'schedules':
                    f'Buổi {idx}: giờ bắt đầu phải trước giờ kết thúc.'
                }
            )


@transaction.atomic
def create_booking(
    *,
    customer,
    service_id,
    address_id,
    service_data,
    schedules,
    note=None,
    voucher_code=None,
):
    service = get_object_or_404(
        Service.objects.select_for_update(),
        pk=service_id,
        is_active=True,
    )

    address = get_object_or_404(
        CustomerAddress.objects.select_for_update(),
        pk=address_id,
        customer=customer,
        is_active=True,
    )

    validate_service_data(
        service.form_schema,
        service_data,
    )

    _validate_schedules(schedules)

    subtotal = None

    if is_computable_pricing(service.pricing_config):
        subtotal = calculate_booking_price(
            service,
            service_data,
        )

        if subtotal is None:
            raise serializers.ValidationError(
                {
                    'service_data':
                    'Chưa đủ thông tin để tính giá dịch vụ.'
                }
            )

    discount = Decimal('0')
    user_voucher = None

    if voucher_code:
        if subtotal is None:
            raise serializers.ValidationError(
                {
                    'voucher_code':
                    'Dịch vụ này cần báo giá thủ công, '
                    'chưa thể áp dụng voucher.'
                }
            )

        result = validate_and_calculate_voucher(
            code=voucher_code,
            customer=customer,
            subtotal_amount=subtotal,
            lock=True,
        )

        user_voucher = result['user_voucher']
        discount = result['discount_amount']

    total = (
        _q(subtotal - discount)
        if subtotal is not None
        else None
    )

    booking_code = _generate_booking_code()

    booking = Booking.objects.create(
        booking_code=booking_code,
        customer=customer,
        service=service,
        user_voucher=user_voucher,
        service_data=service_data,
        address=address,
        note=note,

        # Model hiện tại không còn PricingStatus.
        # Booking mới luôn bắt đầu ở PENDING.
        status=Booking.Status.PENDING,

        # payment_status không cần truyền,
        # model sẽ tự default = UNPAID.

        subtotal_amount=subtotal,
        discount_amount=discount,
        total_amount=total,

        price_breakdown={
            'subtotal_amount': (
                str(subtotal)
                if subtotal is not None
                else None
            ),
            'discount_amount': str(discount),
            'total_amount': (
                str(total)
                if total is not None
                else None
            ),
            'pricing_config_snapshot': service.pricing_config,
        },
    )

    for idx, sch in enumerate(schedules, start=1):
        BookingSchedule.objects.create(
            booking=booking,
            sequence_no=idx,
            scheduled_start=sch['scheduled_start'],
            scheduled_end=sch['scheduled_end'],
        )

    if user_voucher:
        user_voucher.status = UserVoucher.Status.USED
        user_voucher.used_at = timezone.now()

        user_voucher.save(
            update_fields=[
                'status',
                'used_at',
                'updated_at',
            ]
        )

    return booking