import calendar
from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers


class CustomerReviewFilterSerializer(serializers.Serializer):
    search = serializers.CharField(required=False, allow_blank=True, max_length=200)
    rating = serializers.IntegerField(required=False, min_value=1, max_value=5)
    period = serializers.ChoiceField(choices=['all', '30_days', '3_months', 'custom'], default='all')
    date_from = serializers.DateField(required=False, input_formats=['%Y-%m-%d'])
    date_to = serializers.DateField(required=False, input_formats=['%Y-%m-%d'])
    editable_only = serializers.BooleanField(default=False)
    ordering = serializers.ChoiceField(choices=['newest', 'oldest'], default='newest')

    def validate(self, attrs):
        start, end = attrs.get('date_from'), attrs.get('date_to')
        if attrs['period'] == 'custom':
            if not start or not end:
                raise serializers.ValidationError('Vui lòng chọn ngày bắt đầu và ngày kết thúc.')
            if start > end:
                raise serializers.ValidationError('Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.')
            if end == date.max:
                raise serializers.ValidationError('Ngày kết thúc vượt quá khoảng ngày hỗ trợ.')
        elif start or end:
            raise serializers.ValidationError('Khoảng ngày chỉ áp dụng khi chọn thời gian tùy chỉnh.')
        return attrs


def filter_customer_reviews(queryset, params):
    serializer = CustomerReviewFilterSerializer(data=params)
    serializer.is_valid(raise_exception=True)
    filters = serializer.validated_data
    search = filters.get('search', '')
    if search:
        # Each word may match a different part of the worker's full name.
        for word in search.split():
            queryset = queryset.filter(
                Q(comment__icontains=word)
                | Q(assignment__worker__first_name__icontains=word)
                | Q(assignment__worker__last_name__icontains=word)
                | Q(assignment__worker__username__icontains=word)
                | Q(assignment__schedule__booking__service__name__icontains=word)
            )
    if 'rating' in filters:
        queryset = queryset.filter(rating=filters['rating'])
    now = timezone.now()
    period = filters['period']
    if period == '30_days':
        queryset = queryset.filter(created_at__gte=now - timedelta(days=30), created_at__lte=now)
    elif period == '3_months':
        local_now = timezone.localtime(now)
        month_index = local_now.year * 12 + local_now.month - 1 - 3
        year, month = divmod(month_index, 12)
        month += 1
        start = local_now.replace(year=year, month=month, day=min(local_now.day, calendar.monthrange(year, month)[1]))
        queryset = queryset.filter(created_at__gte=start, created_at__lte=now)
    elif period == 'custom':
        start = timezone.make_aware(datetime.combine(filters['date_from'], time.min))
        end = timezone.make_aware(datetime.combine(filters['date_to'] + timedelta(days=1), time.min))
        queryset = queryset.filter(created_at__gte=start, created_at__lt=end)
    if filters['editable_only']:
        queryset = queryset.filter(created_at__gt=now - timedelta(days=30))
    ordering = ('created_at', 'id') if filters['ordering'] == 'oldest' else ('-created_at', '-id')
    return queryset.order_by(*ordering)
