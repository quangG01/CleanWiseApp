import uuid
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers

from apps.wallets import wallet_service
from apps.services.models import Service
from apps.addresses.models import CustomerAddress
from apps.vouchers.voucher_service import (
    release_user_voucher,
    reserve_user_voucher,
    validate_and_calculate_voucher,
)
from apps.payments.models import Payment

from .models import Booking, BookingSchedule
from .service_data_validation import validate_service_data
from .schedule_builder import build_schedules

CANCELLABLE_STATUSES = (Booking.Status.PENDING, Booking.Status.ASSIGNED)

PRICE_DRIVEN_KEYS = ('base_prices', 'price_matrix', 'unit_prices')
TWO_PLACES = Decimal('0.01')


def _q(amount):
    if amount is None:
        return None
    return Decimal(amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def is_computable_pricing(pricing_config):
    return any(key in (pricing_config or {}) for key in PRICE_DRIVEN_KEYS)


def _resolve_flat_options(field, service_data):
    options = field.get('options')
    if not options:
        return []
    if 'when' not in options[0]:
        return options
    options_by = field.get('options_by')
    if not options_by:
        return []
    current_value = service_data.get(options_by)
    for group in options:
        if group.get('when', {}).get(options_by) == current_value:
            return group.get('items', [])
    return []


def _find_field_by_option_values(fields, candidate_values, service_data, exclude_key=None):
    for field in fields:
        if field.get('key') == exclude_key:
            continue
        options = _resolve_flat_options(field, service_data)
        if not options:
            continue
        if any(option.get('value') in candidate_values for option in options):
            return field
    return None


def get_unit_price_for_item(pricing_config, item_fields, item):
    if not pricing_config.get('unit_prices'):
        return None
    node = pricing_config['unit_prices']
    for sub in item_fields:
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
    unit_price = get_unit_price_for_item(pricing_config, item_fields, item)
    if unit_price is None:
        return None
    qty = item.get('quantity', 1)
    try:
        qty = Decimal(str(qty))
    except (TypeError, ValueError, ArithmeticError):
        return None
    total = unit_price * qty
    for field in item_fields:
        if field.get('type') == 'BOOLEAN' and item.get(field['key']):
            surcharge = pricing_config.get(f"{field['key']}_price")
            if surcharge is not None:
                try:
                    total += (Decimal(str(surcharge)) * qty)
                except (TypeError, ValueError, ArithmeticError):
                    pass
    return _q(total)


def calculate_booking_price(service, service_data):
    """
    Trả về:
    - Nếu pricing_config.pricing_unit == 'PER_SESSION': giá của MỘT buổi
      (base_prices[duration] + additional_services đã chọn). Việc nhân
      với số buổi và trừ % giảm gói được xử lý riêng ở create_booking().
    - Ngược lại: tổng giá trọn gói như trước (price_matrix / unit_prices...).
    """
    pricing_config = service.pricing_config or {}
    fields = (service.form_schema or {}).get('fields', [])
    total = Decimal('0')
    has_base = False

    if pricing_config.get('price_matrix'):
        price_matrix = pricing_config['price_matrix']
        outer_field = _find_field_by_option_values(fields, list(price_matrix.keys()), service_data)
        outer_value = service_data.get(outer_field['key']) if outer_field else None
        inner_map = price_matrix.get(outer_value) if outer_value else None
        if inner_map:
            inner_field = _find_field_by_option_values(
                fields, list(inner_map.keys()), service_data,
                exclude_key=(outer_field['key'] if outer_field else None),
            )
            inner_value = service_data.get(inner_field['key']) if inner_field else None
            price = inner_map.get(inner_value)
            if price is not None:
                try:
                    total += Decimal(str(price))
                    has_base = True
                except (TypeError, ValueError, ArithmeticError):
                    pass

    elif pricing_config.get('base_prices'):
        base_prices = pricing_config['base_prices']
        field = _find_field_by_option_values(fields, list(base_prices.keys()), service_data)
        value = service_data.get(field['key']) if field else None
        price = base_prices.get(value)
        if price is not None:
            try:
                total += Decimal(str(price))
                has_base = True
            except (TypeError, ValueError, ArithmeticError):
                pass

    for key, value in pricing_config.items():
        if key.endswith('_surcharge') and isinstance(value, dict):
            field = _find_field_by_option_values(fields, list(value.keys()), service_data)
            selected_value = service_data.get(field['key']) if field else None
            price = value.get(selected_value)
            if price is not None:
                try:
                    total += Decimal(str(price))
                except (TypeError, ValueError, ArithmeticError):
                    pass

    if pricing_config.get('additional_services'):
        additional_services = pricing_config['additional_services']
        field = next((f for f in fields if f.get('type') == 'MULTI_SELECT'), None)
        selected = service_data.get(field['key'], []) if field else []
        for value in selected:
            price = additional_services.get(value)
            if price is not None:
                try:
                    total += Decimal(str(price))
                except (TypeError, ValueError, ArithmeticError):
                    pass

    if pricing_config.get('unit_prices'):
        group_field = next((f for f in fields if f.get('type') == 'REPEATABLE_GROUP'), None)
        if group_field:
            group_key = group_field['key']
            items = service_data.get(group_key, [])
            for item in items:
                item_total = get_item_total_price(pricing_config, group_field.get('item_fields', []), item)
                if item_total is not None:
                    total += item_total
                    has_base = True

    if not has_base and total == 0:
        return None
    return _q(total)


def get_package_discount_percent(service, service_data):
    """
    % giảm theo thời hạn gói, đọc từ pricing_config.package_discount_percent
    (key khớp option value của field package_duration, vd "2_MONTHS": 5).

    Chỉ áp dụng cho dịch vụ pricing_unit == 'PER_SESSION'. Dịch vụ không
    khai báo package_discount_percent, hoặc không match được field/giá trị
    -> trả về 0% (không giảm), không raise lỗi.
    """
    pricing_config = service.pricing_config or {}
    discount_map = pricing_config.get('package_discount_percent')
    if not discount_map:
        return Decimal('0')

    fields = (service.form_schema or {}).get('fields', [])
    field = _find_field_by_option_values(fields, list(discount_map.keys()), service_data)
    value = service_data.get(field['key']) if field else None
    percent = discount_map.get(value)
    if percent is None:
        return Decimal('0')
    try:
        return Decimal(str(percent))
    except (TypeError, ValueError, ArithmeticError):
        return Decimal('0')


def _generate_booking_code():
    return f"CW-{uuid.uuid4().hex[:10].upper()}"


def _validate_schedules(schedules):
    if not schedules:
        raise serializers.ValidationError({'schedules': 'Cần ít nhất 1 buổi làm việc.'})

    now = timezone.now()

    for idx, schedule in enumerate(schedules, start=1):
        if schedule['scheduled_start'] <= now:
            raise serializers.ValidationError(
                {'schedules': f'Buổi {idx}: thời gian bắt đầu phải ở tương lai.'}
            )
        if schedule['scheduled_start'] >= schedule['scheduled_end']:
            raise serializers.ValidationError(
                {'schedules': f'Buổi {idx}: giờ bắt đầu phải trước giờ kết thúc.'}
            )


def _validate_payment_method(payment_method):
    allowed_methods = {Payment.Method.CASH, Payment.Method.BANK_TRANSFER}
    if payment_method not in allowed_methods:
        raise serializers.ValidationError({'payment_method': 'Phương thức thanh toán không hợp lệ.'})


@transaction.atomic
def create_booking(
    *,
    customer,
    service_id,
    address_id,
    delivery_address_id=None,
    service_data,
    note=None,
    voucher_code=None,
    payment_method,
):
    """
    Tạo Booking và Payment trong cùng một transaction.

    Nếu một trong hai thao tác thất bại,
    toàn bộ transaction sẽ rollback.

    Lưu ý: không còn nhận `schedules` từ client — được BE tự sinh
    bên dưới từ service_data + service.form_schema.schedule_type
    (xem schedule_builder.py). Lý do: mỗi loại dịch vụ có cấu trúc
    lịch khác nhau (1 buổi cụ thể / định kỳ theo thứ...), để FE tự
    tính dễ lệch logic giữa các nơi dùng lại.

    ĐỔI: bỏ select_for_update() trên Service và CustomerAddress —
    hàm này chỉ ĐỌC 2 bảng này, không ghi/sửa gì lên chúng.

    ĐỔI: dịch vụ pricing_unit == 'PER_SESSION' (dọn dẹp định kỳ) tính giá
    = unit_price (giá 1 buổi) × sessions_count × (1 - package_discount_percent/100),
    thay vì trước đây dùng price_matrix cố định theo package_duration mà
    không phụ thuộc số ngày/tuần khách chọn (lỗ hổng giá đã sửa).

    ĐỔI: price_breakdown['unit_price'] giờ lưu giá/buổi ĐÃ TRỪ
    package_discount_percent (= subtotal / sessions_count), không còn là
    giá gốc trước giảm. Lý do: giảm giá gói (cam kết dài hạn) là mức giá
    thật của buổi làm, worker cùng chịu — khác với voucher (ưu đãi riêng
    cho khách, app gánh, không trừ vào lương worker vì unit_price tính từ
    subtotal chứ không phải total_amount). Giá trị này chốt 1 lần lúc tạo
    booking nên không đổi khi khách hủy bớt buổi khác trong gói. Giá gốc
    trước giảm được lưu riêng ở 'base_unit_price' để tham khảo/đối soát.
    """

    _validate_payment_method(payment_method)

    service = get_object_or_404(
        Service.objects,
        pk=service_id,
        is_active=True,
    )

    address = get_object_or_404(
        CustomerAddress.objects,
        pk=address_id,
        customer=customer,
        is_active=True,
    )

    address_count = (service.form_schema or {}).get('address_count', 1)
    delivery_address = None

    if address_count >= 2:
        if not delivery_address_id:
            raise serializers.ValidationError(
                {'delivery_address_id': 'Dịch vụ này cần chọn địa chỉ chuyển đến.'}
            )
        delivery_address = get_object_or_404(
            CustomerAddress.objects,
            pk=delivery_address_id,
            customer=customer,
            is_active=True,
        )
    elif delivery_address_id:
        raise serializers.ValidationError(
            {'delivery_address_id': 'Dịch vụ này không cần địa chỉ chuyển đến.'}
        )

    validate_service_data(
        service.form_schema,
        service_data,
    )

    schedules = build_schedules(service.form_schema, service_data)
    _validate_schedules(schedules)

    pricing_config = service.pricing_config or {}
    per_session = pricing_config.get('pricing_unit') == 'PER_SESSION'
    sessions_count = len(schedules)

    subtotal = None
    unit_price = None
    effective_unit_price = None
    package_discount_percent = Decimal('0')

    if is_computable_pricing(pricing_config):
        computed = calculate_booking_price(service, service_data)

        if computed is None:
            raise serializers.ValidationError(
                {
                    'service_data':
                    'Chưa đủ thông tin để tính giá '
                    'dịch vụ.'
                }
            )

        if per_session:
            # computed = giá gốc 1 buổi (base_prices[duration] + additional_services),
            # CHƯA trừ giảm giá gói — chỉ dùng để tính subtotal, KHÔNG dùng
            # để trả lương worker.
            unit_price = computed
            package_discount_percent = get_package_discount_percent(service, service_data)
            gross_subtotal = unit_price * sessions_count
            subtotal = _q(
                gross_subtotal * (Decimal('1') - package_discount_percent / Decimal('100'))
            )
            # Giá/buổi THẬT SỰ dùng để trả worker: đã trừ giảm giá gói,
            # chia đều trên subtotal (không dùng total vì total còn trừ
            # thêm voucher, voucher app gánh riêng, worker không chịu).
            effective_unit_price = (
                _q(subtotal / sessions_count) if sessions_count else unit_price
            )
        else:
            subtotal = computed

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
            error_field='voucher_code',
        )

        user_voucher = result['user_voucher']
        discount = result['discount_amount']

    total = (
        _q(subtotal - discount)
        if subtotal is not None
        else None
    )

    if total is None:
        raise serializers.ValidationError(
            {
                'payment_method':
                'Booking chưa có giá thanh toán. '
                'Vui lòng chỉ chọn phương thức thanh toán '
                'sau khi dịch vụ có giá.'
            }
        )

    if total <= 0:
        raise serializers.ValidationError(
            {
                'payment_method':
                'Tổng tiền thanh toán phải lớn hơn 0.'
            }
        )

    booking_code = _generate_booking_code()

    booking = Booking.objects.create(
        booking_code=booking_code,
        customer=customer,
        service=service,
        user_voucher=user_voucher,
        service_data=service_data,
        address=address,
        delivery_address=delivery_address,
        note=note,

        status=Booking.Status.PENDING,

        payment_status=Booking.PaymentStatus.UNPAID,

        subtotal_amount=subtotal,
        discount_amount=discount,
        total_amount=total,

        price_breakdown={
            'unit_price': (
                str(effective_unit_price)
                if effective_unit_price is not None
                else (str(unit_price) if unit_price is not None else None)
            ),
            'base_unit_price': str(unit_price) if unit_price is not None else None,
            'sessions_count': sessions_count,
            'package_discount_percent': str(package_discount_percent),
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
            'pricing_config_snapshot':
                service.pricing_config,
            'voucher': (
                {
                    'code': user_voucher.voucher.code,
                    'name': user_voucher.voucher.name,
                }
                if user_voucher
                else None
            ),
        },
    )

    BookingSchedule.objects.bulk_create([
        BookingSchedule(
            booking=booking,
            sequence_no=idx,
            scheduled_start=schedule['scheduled_start'],
            scheduled_end=schedule['scheduled_end'],
        )
        for idx, schedule in enumerate(schedules, start=1)
    ])

    payment = Payment.objects.create(
        customer=customer,
        booking=booking,
        amount=total,
        method=payment_method,
        status=Payment.Status.PENDING,
        transaction_code=(
            booking_code if payment_method == Payment.Method.BANK_TRANSFER else None
        ),
    )       

    if user_voucher:
        reserve_user_voucher(user_voucher_id=user_voucher.id)

    _ = payment

    return booking


@transaction.atomic
def cancel_booking(*, booking_id, customer, reason):
    booking = get_object_or_404(
        Booking.objects.select_for_update(),
        pk=booking_id,
        customer=customer,
    )

    if booking.status not in CANCELLABLE_STATUSES:
        raise serializers.ValidationError({'booking': 'Đơn hàng không thể hủy ở trạng thái hiện tại.'})

    if booking.schedules.filter(status=BookingSchedule.Status.IN_PROGRESS).exists():
        raise serializers.ValidationError({'booking': 'Đơn đang được thực hiện, không thể hủy.'})

    was_paid = booking.payment_status == Booking.PaymentStatus.PAID
    now = timezone.now()

    booking.status = Booking.Status.CANCELLED
    booking.cancelled_by = customer
    booking.cancelled_at = now
    booking.cancel_reason = reason
    update_fields = ['status', 'cancelled_by', 'cancelled_at', 'cancel_reason', 'updated_at']

    if was_paid:
        booking.payment_status = Booking.PaymentStatus.REFUNDED
        update_fields.append('payment_status')

    booking.save(update_fields=update_fields)

    booking.schedules.exclude(
        status__in=(BookingSchedule.Status.COMPLETED, BookingSchedule.Status.CANCELLED),
    ).update(
        status=BookingSchedule.Status.CANCELLED,
        cancelled_by=customer,
        cancelled_at=now,
        cancel_reason=reason,
    )

    booking.payments.filter(status=Payment.Status.PENDING).update(
        status=Payment.Status.CANCELLED,
        failure_reason='Booking đã bị khách hàng hủy.',
        updated_at=now,
    )

    if was_paid:
        wallet_service.credit_wallet(
            user=customer,
            amount=booking.total_amount,
            booking=booking,
            note=f'Hoàn tiền hủy đơn {booking.booking_code}',
        )

    if booking.user_voucher_id:
        release_user_voucher(
            user_voucher_id=booking.user_voucher_id,
            allow_used=True,
        )

    return booking
