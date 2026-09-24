import calendar
from datetime import datetime, timedelta
from decimal import Decimal

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.permissions import IsWorkerRole

from .models import Wallet, WorkerEarning

WEEKDAY_LABELS = ['T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'CN']
HISTORY_LIMIT = 100

_ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=14, decimal_places=2))


def _sum(field, **kwargs):
    return Coalesce(Sum(field, **kwargs), _ZERO, output_field=DecimalField(max_digits=14, decimal_places=2))


# ---------------------------------------------------------------- helpers

def _parse_period(request):
    period = request.query_params.get('period', 'week').lower()
    if period not in ('week', 'month'):
        raise ValidationError({'period': "period phải là 'week' hoặc 'month'."})
    return period


def _resolve_period(period):
    """Tuần: thứ 2 -> chủ nhật của tuần hiện tại. Tháng: ngày 1 -> ngày cuối tháng."""
    today = timezone.localdate()
    if period == 'week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    else:
        start = today.replace(day=1)
        end = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return start, end


def _range_bounds(start, end):
    tz = timezone.get_current_timezone()
    lower = timezone.make_aware(datetime.combine(start, datetime.min.time()), tz)
    upper = timezone.make_aware(datetime.combine(end + timedelta(days=1), datetime.min.time()), tz)
    return lower, upper


def _build_series(period, end, rows):
    """Tuần: thu nhập theo từng ngày. Tháng: theo từng khoảng 7 ngày (1-7, 8-14, ...)."""
    if period == 'week':
        labels = WEEKDAY_LABELS
        buckets = [Decimal('0')] * 7
        for completed_at, amount in rows:
            buckets[timezone.localtime(completed_at).weekday()] += amount
    else:
        count = (end.day - 1) // 7 + 1
        labels = [f'{i * 7 + 1}-{min((i + 1) * 7, end.day)}' for i in range(count)]
        buckets = [Decimal('0')] * count
        for completed_at, amount in rows:
            buckets[(timezone.localtime(completed_at).day - 1) // 7] += amount
    return [{'label': label, 'amount': str(amount)} for label, amount in zip(labels, buckets)]


# ---------------------------------------------------------------- serializers

class WorkerEarningSerializer(serializers.ModelSerializer):
    booking_code = serializers.CharField(source='booking.booking_code', read_only=True)
    service_name = serializers.CharField(source='booking.service.name', read_only=True)

    class Meta:
        model = WorkerEarning
        fields = [
            'id', 'booking_code', 'service_name', 'completed_at', 'payment_method',
            'gross_amount', 'commission_amount', 'worker_amount',
        ]
        read_only_fields = fields


# ---------------------------------------------------------------- views

class WorkerEarningSummaryView(APIView):
    """GET /api/worker/earnings/summary/?period=week|month"""
    permission_classes = [IsWorkerRole]

    def get(self, request, *args, **kwargs):
        period = _parse_period(request)
        start, end = _resolve_period(period)
        lower, upper = _range_bounds(start, end)

        mine = WorkerEarning.objects.filter(worker=request.user)
        in_period = mine.filter(completed_at__gte=lower, completed_at__lt=upper)

        agg = in_period.aggregate(
            completed_jobs=Count('id'),
            gross_amount=_sum('gross_amount'),
            income=_sum('worker_amount'),
            bank_earned=_sum('worker_amount', filter=Q(payment_method=WorkerEarning.PaymentMethod.ONLINE)),
            cash_commission=_sum('commission_amount', filter=Q(payment_method=WorkerEarning.PaymentMethod.CASH)),
        )

        # Hoa hồng tiền mặt chưa nộp: tính trên MỌI kỳ, không chỉ tuần/tháng đang xem
        commission_owed = mine.filter(
            payment_method=WorkerEarning.PaymentMethod.CASH, settled_at__isnull=True,
        ).aggregate(total=_sum('commission_amount'))['total']

        wallet_balance = (
            Wallet.objects.filter(user=request.user).values_list('balance', flat=True).first()
            or Decimal('0')
        )

        series = _build_series(period, end, in_period.values_list('completed_at', 'worker_amount'))

        return Response({
            'message': 'Lấy thống kê thu nhập thành công.',
            'data': {
                'wallet_balance': str(wallet_balance),
                'commission_owed': str(commission_owed),
                'period': {
                    'type': period,
                    'start': start.isoformat(),
                    'end': end.isoformat(),
                    'completed_jobs': agg['completed_jobs'],
                    'gross_amount': str(agg['gross_amount']),
                    'income': str(agg['income']),
                    'bank_earned': str(agg['bank_earned']),
                    'cash_commission': str(agg['cash_commission']),
                    # > 0: app chuyển cho nhân viên, < 0: nhân viên chuyển lại app
                    'net_settlement': str(agg['bank_earned'] - agg['cash_commission']),
                },
                'series': series,
            },
        })


class WorkerEarningHistoryView(APIView):
    """GET /api/worker/earnings/history/?period=week|month"""
    permission_classes = [IsWorkerRole]

    def get(self, request, *args, **kwargs):
        period = _parse_period(request)
        start, end = _resolve_period(period)
        lower, upper = _range_bounds(start, end)

        queryset = (
            WorkerEarning.objects.filter(
                worker=request.user, completed_at__gte=lower, completed_at__lt=upper,
            )
            .select_related('booking', 'booking__service')
            .order_by('-completed_at')[:HISTORY_LIMIT]
        )
        return Response({
            'message': 'Lấy danh sách thu nhập thành công.',
            'data': WorkerEarningSerializer(queryset, many=True).data,
        })