import uuid
from decimal import Decimal

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.services.models import Service

from .models import Booking, BookingSchedule, CustomerAddress, UserVoucher
from .voucher_service import validate_and_calculate_voucher

from .service_data_validation import validate_service_data

PRICE_DRIVEN_KEYS = ('base_prices', 'price_matrix', 'unit_prices')

from decimal import Decimal, ROUND_HALF_UP

TWO_PLACES = Decimal('0.01')


def _q(amount):
    """Làm tròn 2 chữ số thập phân, kiểu ngân hàng (HALF_UP) để khớp DecimalField(decimal_places=2)."""
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
        if not isinstance(node, dict):
            return None
        if sub.get('type') in ('QUANTITY', 'BOOLEAN'):
            continue
        value = item.get(sub['key'])
        if value is not None and value in node:
            node = node[value]
        else:
            return None
    return node if isinstance(node, (int, float)) else None


def get_item_total_price(pricing_config, item_fields, item):
    unit_price = get_unit_price_for_item(pricing_config, item_fields, item)
    if unit_price is None:
        return None
    qty = item.get('quantity', 1)
    total = Decimal(str(unit_price)) * qty
    for f in item_fields:
        if f.get('type') == 'BOOLEAN' and item.get(f['key']):
            surcharge = pricing_config.get(f"{f['key']}_price")
            if isinstance(surcharge, (int, float)):
                total += Decimal(str(surcharge)) * qty
    return _q(total)


def calculate_booking_price(service, service_data):
    """Port lại 1:1 logic servicePricing.ts (FE) sang Python.
    Trả về Decimal nếu tính được, None nếu service_data chưa đủ thông tin."""
    pricing_config = service.pricing_config or {}
    fields = (service.form_schema or {}).get('fields', [])
    total = Decimal('0')
    has_base = False

    if pricing_config.get('price_matrix'):
        price_matrix = pricing_config['price_matrix']
        outer_field = _find_field_by_option_values(fields, list(price_matrix.keys()))
        outer_value = service_data.get(outer_field['key']) if outer_field else None
        inner_map = price_matrix.get(outer_value) if outer_value else None
        if inner_map:
            inner_field = _find_field_by_option_values(
                fields, list(inner_map.keys()),
                exclude_key=outer_field['key'] if outer_field else None,
            )
            inner_value = service_data.get(inner_field['key']) if inner_field else None
            if isinstance(inner_map.get(inner_value), (int, float)):
                total += Decimal(str(inner_map[inner_value]))
                has_base = True
    elif pricing_config.get('base_prices'):
        base_prices = pricing_config['base_prices']
        field = _find_field_by_option_values(fields, list(base_prices.keys()))
        value = service_data.get(field['key']) if field else None
        if isinstance(base_prices.get(value), (int, float)):
            total += Decimal(str(base_prices[value]))
            has_base = True

    for key, val in pricing_config.items():
        if key.endswith('_surcharge') and isinstance(val, dict):
            field = _find_field_by_option_values(fields, list(val.keys()))
            value = service_data.get(field['key']) if field else None
            if isinstance(val.get(value), (int, float)):
                total += Decimal(str(val[value]))

    if pricing_config.get('additional_services'):
        additional_services = pricing_config['additional_services']
        field = next((f for f in fields if f.get('type') == 'MULTI_SELECT'), None)
        selected = service_data.get(field['key'], []) if field else []
        for v in selected:
            price = additional_services.get(v)
            if isinstance(price, (int, float)):
                total += Decimal(str(price))

    if pricing_config.get('unit_prices'):
        group_field = next((f for f in fields if f.get('type') == 'REPEATABLE_GROUP'), None)
        items = service_data.get(group_field['key'], []) if group_field else []
        for item in items:
            item_total = get_item_total_price(pricing_config, group_field.get('item_fields', []), item)
            if item_total is not None:
                total += item_total
                has_base = True

    if not has_base and total == 0:
        return None
    return _q(total)


def _generate_booking_code():
    return f"CW-{uuid.uuid4().hex[:10].upper()}"


def _validate_schedules(schedules):
    if not schedules:
        raise serializers.ValidationError({'schedules': 'Cần ít nhất 1 buổi làm việc.'})
    now = timezone.now()
    for idx, sch in enumerate(schedules, start=1):
        if sch['scheduled_start'] <= now:
            raise serializers.ValidationError(
                {'schedules': f'Buổi {idx}: thời gian bắt đầu phải ở tương lai.'}
            )
        if sch['scheduled_start'] >= sch['scheduled_end']:
            raise serializers.ValidationError(
                {'schedules': f'Buổi {idx}: giờ bắt đầu phải trước giờ kết thúc.'}
            )


@transaction.atomic
def create_booking(*, customer, service_id, address_id, service_data, schedules, note=None, voucher_code=None):
    service = get_object_or_404(Service.objects.select_for_update(), pk=service_id, is_active=True)
    address = get_object_or_404(
        CustomerAddress.objects.select_for_update(),
        pk=address_id, customer=customer, is_active=True,
    )

    validate_service_data(service.form_schema, service_data)
    _validate_schedules(schedules)

    subtotal = None
    if is_computable_pricing(service.pricing_config):
        subtotal = calculate_booking_price(service, service_data)
        if subtotal is None:
            raise serializers.ValidationError(
                {'service_data': 'Chưa đủ thông tin để tính giá dịch vụ.'}
            )
        pricing_status = Booking.PricingStatus.CALCULATED
    else:
        pricing_status = Booking.PricingStatus.WAITING_QUOTE

    discount = _q(result['discount_amount']) if voucher_code and subtotal is not None else Decimal('0')
    user_voucher = None
    if voucher_code:
        if subtotal is None:
            raise serializers.ValidationError(
                {'voucher_code': 'Dịch vụ này cần báo giá thủ công, chưa thể áp dụng voucher.'}
            )
        result = validate_and_calculate_voucher(
            code=voucher_code, customer=customer, subtotal_amount=subtotal, lock=True,
        )
        user_voucher = result['user_voucher']
        discount = result['discount_amount']

    total = _q(subtotal - discount) if subtotal is not None else None

    booking = Booking.objects.create(
        booking_code=_generate_booking_code(),
        customer=customer,
        service=service,
        user_voucher=user_voucher,
        service_data=service_data,
        address=address,
        note=note,
        pricing_status=pricing_status,
        status=(
            Booking.Status.WAITING_ASSIGNMENT
            if pricing_status == Booking.PricingStatus.CALCULATED
            else Booking.Status.PENDING
        ),
        subtotal_amount=subtotal,
        discount_amount=discount,
        total_amount=total,
        price_breakdown={
            'subtotal_amount': str(subtotal) if subtotal is not None else None,
            'discount_amount': str(discount),
            'total_amount': str(total) if total is not None else None,
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
        user_voucher.save(update_fields=['status', 'used_at', 'updated_at'])

    return booking