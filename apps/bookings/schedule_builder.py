from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

DURATION_HOURS = {'2_HOURS': 2, '3_HOURS': 3, '4_HOURS': 4}
PACKAGE_WEEKS = {'1_MONTH': 4, '2_MONTHS': 8, '3_MONTHS': 12, '6_MONTHS': 24}
WEEKDAY_INDEX = {'MON': 0, 'TUE': 1, 'WED': 2, 'THU': 3, 'FRI': 4, 'SAT': 5, 'SUN': 6}

FALLBACK_DURATION_HOURS = 3


def _resolve_duration_hours(form_schema, service_data):
    duration_key = service_data.get('duration')

    if duration_key is not None:
        hours = DURATION_HOURS.get(duration_key)
        if hours is None:
            raise ValueError(f"duration không hợp lệ: {duration_key!r}")
        return hours

    return form_schema.get('default_duration_hours', FALLBACK_DURATION_HOURS)


def build_once_schedules(form_schema, service_data):
    """Dịch vụ 1 lần: 1 buổi duy nhất từ date + start_time + duration."""
    naive_start = timezone.datetime.strptime(
        f"{service_data['date']} {service_data['start_time']}", '%Y-%m-%d %H:%M',
    )
    start = timezone.make_aware(naive_start)
    hours = _resolve_duration_hours(form_schema, service_data)
    end = start + timedelta(hours=hours)
    return [{'scheduled_start': start, 'scheduled_end': end}]


def build_weekly_recurring_schedules(form_schema, service_data):
    """Dịch vụ định kỳ: sinh đúng (số thứ/tuần × số tuần của gói) buổi,
    bắt đầu sớm nhất từ ngày mai.

    ĐỔI: trước đây build theo khoảng ngày dương lịch (first_day -> last_day
    qua _add_months), nên số buổi thực tế lệch theo số ngày trong tháng
    (dư/thiếu so với số buổi đã tính giá). Giờ build đúng
    total_sessions = len(weekdays) * PACKAGE_WEEKS[package_duration],
    khớp 100% với sessions_count dùng tính giá ở booking_service.py.
    """
    weekdays = {WEEKDAY_INDEX[d] for d in service_data['weekdays']}
    hour, minute = map(int, service_data['start_time'].split(':'))
    duration = _resolve_duration_hours(form_schema, service_data)
    total_sessions = len(weekdays) * PACKAGE_WEEKS[service_data['package_duration']]

    schedules = []
    current = timezone.localdate() + timedelta(days=1)
    while len(schedules) < total_sessions:
        if current.weekday() in weekdays:
            naive_start = timezone.datetime(current.year, current.month, current.day, hour, minute)
            start = timezone.make_aware(naive_start)
            schedules.append({
                'scheduled_start': start,
                'scheduled_end': start + timedelta(hours=duration),
            })
        current += timedelta(days=1)
    return schedules


SCHEDULE_BUILDERS = {
    'ONCE': build_once_schedules,
    'RECURRING_WEEKLY': build_weekly_recurring_schedules,
}


def build_schedules(form_schema, service_data):
    schedule_type = form_schema.get('schedule_type', 'ONCE')
    builder = SCHEDULE_BUILDERS.get(schedule_type)

    if builder is None:
        raise serializers.ValidationError(
            {'service_data': f'schedule_type "{schedule_type}" chưa được hỗ trợ.'}
        )

    try:
        schedules = builder(form_schema, service_data)
    except (KeyError, ValueError) as exc:
        raise serializers.ValidationError(
            {'service_data': f'Thiếu hoặc sai định dạng thông tin lịch: {exc}'}
        )

    if not schedules:
        raise serializers.ValidationError(
            {'service_data': 'Không tạo được buổi làm việc nào từ lựa chọn này.'}
        )

    return schedules