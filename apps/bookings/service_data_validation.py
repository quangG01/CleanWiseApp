import re

from rest_framework import serializers

TIME_PATTERN = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


def _is_flat_options(options):
    return bool(options) and 'when' not in options[0]


def _resolve_options(field, sibling_values):
    options = field.get('options')
    if not options:
        return []
    if _is_flat_options(options):
        return options
    options_by = field.get('options_by')
    if not options_by:
        return []
    current_value = sibling_values.get(options_by)
    for group in options:
        if group.get('when', {}).get(options_by) == current_value:
            return group.get('items', [])
    return []


def _validate_field(field, value, sibling_values, path, errors):
    key = field['key']
    ftype = field.get('type')
    required = field.get('required', False)
    is_empty = value is None or value == '' or (
        ftype in ('MULTI_SELECT', 'WEEKDAY_MULTI_SELECT') and value == []
    )

    if is_empty:
        if required:
            errors[path] = 'Trường bắt buộc.'
        return

    if ftype == 'SINGLE_SELECT':
        valid_values = {o['value'] for o in _resolve_options(field, sibling_values)}
        if value not in valid_values:
            errors[path] = f'Giá trị "{value}" không hợp lệ.'

    elif ftype == 'MULTI_SELECT':
        if not isinstance(value, list):
            errors[path] = 'Phải là danh sách.'
            return
        valid_values = {o['value'] for o in _resolve_options(field, sibling_values)}
        invalid = [v for v in value if v not in valid_values]
        if invalid:
            errors[path] = f'Giá trị không hợp lệ: {invalid}.'

    elif ftype == 'WEEKDAY_MULTI_SELECT':
        if not isinstance(value, list):
            errors[path] = 'Phải là danh sách.'
            return
        valid_values = {o['value'] for o in (field.get('options') or [])}
        invalid = [v for v in value if v not in valid_values]
        if invalid:
            errors[path] = f'Giá trị không hợp lệ: {invalid}.'
        min_selections = field.get('min_selections')
        if min_selections and len(value) < min_selections:
            errors[path] = f'Cần chọn ít nhất {min_selections} ngày.'

    elif ftype == 'QUANTITY':
        if not isinstance(value, int) or isinstance(value, bool):
            errors[path] = 'Phải là số nguyên.'
            return
        # Mặc định không cho số âm dù schema không khai báo min.
        min_v = field.get('min', 0)
        max_v = field.get('max')
        if value < min_v:
            errors[path] = f'Không được nhỏ hơn {min_v}.'
        elif max_v is not None and value > max_v:
            errors[path] = f'Không được lớn hơn {max_v}.'

    elif ftype in ('TEXT', 'TEXTAREA'):
        if not isinstance(value, str):
            errors[path] = 'Phải là chuỗi ký tự.'
            return
        max_length = field.get('max_length')
        if max_length and len(value) > max_length:
            errors[path] = f'Không được vượt quá {max_length} ký tự.'

    elif ftype == 'BOOLEAN':
        if not isinstance(value, bool):
            errors[path] = 'Phải là true/false.'

    elif ftype == 'TIME':
        if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
            errors[path] = 'Định dạng giờ không hợp lệ (HH:MM).'

    elif ftype == 'REPEATABLE_GROUP':
        if not isinstance(value, list):
            errors[path] = 'Phải là danh sách.'
            return
        min_items = field.get('min_items', 0)
        max_items = field.get('max_items')
        if len(value) < min_items:
            errors[path] = f'Cần ít nhất {min_items} mục.'
            return
        if max_items is not None and len(value) > max_items:
            errors[path] = f'Không được vượt quá {max_items} mục.'
            return
        item_fields = field.get('item_fields', [])
        allowed_item_keys = {sub['key'] for sub in item_fields}
        for idx, item in enumerate(value):
            if not isinstance(item, dict):
                errors[f'{path}[{idx}]'] = 'Mục không hợp lệ.'
                continue
            extra_keys = set(item.keys()) - allowed_item_keys
            if extra_keys:
                errors[f'{path}[{idx}]'] = f'Trường không xác định: {sorted(extra_keys)}.'
                continue
            for sub in item_fields:
                _validate_field(
                    sub, item.get(sub['key']), item, f"{path}[{idx}].{sub['key']}", errors,
                )


def validate_service_data(form_schema, service_data):
    """Đối chiếu service_data với form_schema; raise ValidationError nếu sai
    field nào (giá trị không thuộc option hợp lệ, thiếu field bắt buộc,
    sai kiểu dữ liệu, có field lạ...). Gọi trước khi tính giá."""
    if not isinstance(service_data, dict):
        raise serializers.ValidationError({'service_data': 'Phải là object JSON.'})

    fields = (form_schema or {}).get('fields', [])
    allowed_keys = {f['key'] for f in fields}
    extra_keys = set(service_data.keys()) - allowed_keys

    errors = {}
    if extra_keys:
        errors['__extra__'] = f'Trường không xác định trong service_data: {sorted(extra_keys)}.'

    for field in fields:
        _validate_field(field, service_data.get(field['key']), service_data, field['key'], errors)

    if errors:
        raise serializers.ValidationError({'service_data': errors})
    """Đối chiếu service_data với form_schema; raise ValidationError nếu sai
    field nào (giá trị không thuộc option hợp lệ, thiếu field bắt buộc,
    sai kiểu dữ liệu...). Gọi trước khi tính giá."""
    if not isinstance(service_data, dict):
        raise serializers.ValidationError({'service_data': 'Phải là object JSON.'})

    errors = {}
    for field in (form_schema or {}).get('fields', []):
        _validate_field(field, service_data.get(field['key']), service_data, field['key'], errors)

    if errors:
        raise serializers.ValidationError({'service_data': errors})