from datetime import date

from django.db.models import Count, Q
from django.utils import timezone
from rest_framework import serializers

from apps.worker.models import WorkerFavoriteMonthlyEntry
from .report_service import ZONE, next_month


class FavoriteReportParams(serializers.Serializer):
    year = serializers.IntegerField(min_value=2000, max_value=2100, required=False)
    month = serializers.IntegerField(min_value=1, max_value=12, required=False)
    limit = serializers.IntegerField(min_value=1, max_value=50, default=10)


def monthly_favorite_report(params):
    today = timezone.localdate(timezone=ZONE)
    year, month = params.get('year', today.year), params.get('month', today.month)
    selected_month = date(year, month, 1)
    previous_month = date(year - 1, 12, 1) if month == 1 else date(year, month - 1, 1)
    entries = WorkerFavoriteMonthlyEntry.objects.filter(customer__role='CUSTOMER', worker__role='WORKER')
    selected = entries.filter(month=selected_month)
    previous = entries.filter(month=previous_month).count()
    summary = selected.aggregate(favorites=Count('id'), customers=Count('customer_id', distinct=True),
                                 workers=Count('worker_id', distinct=True), legacy_entries=Count('id', filter=Q(source='BACKFILL')))
    summary['previous_month_favorites'] = previous
    summary['change'] = summary['favorites'] - previous
    summary['change_percent'] = round(summary['change'] * 100 / previous, 1) if previous else None
    rows = entries.filter(month__gte=date(year, 1, 1), month__lt=date(year + 1, 1, 1)).order_by().values('month').annotate(
        favorites=Count('id'), customers=Count('customer_id', distinct=True), workers=Count('worker_id', distinct=True))
    by_month = {row['month'].month: row for row in rows}
    timeline = [{'month': date(year, index, 1).isoformat(),
                 **{key: by_month.get(index, {}).get(key, 0) for key in ('favorites', 'customers', 'workers')}}
                for index in range(1, 13)]
    ranked = selected.order_by().values('worker_id', 'worker__first_name', 'worker__last_name',
                                        'worker__username', 'worker__is_active', 'worker__worker_profile__status').annotate(
        favorite_count=Count('customer_id', distinct=True)).order_by('-favorite_count', 'worker_id')[:params['limit']]
    workers = []
    for rank, row in enumerate(ranked, 1):
        workers.append({'rank': rank, 'worker_id': row['worker_id'],
                        'name': f"{row['worker__first_name']} {row['worker__last_name']}".strip() or row['worker__username'],
                        'username': row['worker__username'], 'favorite_count': row['favorite_count'],
                        'active_current': row['worker__is_active'] and row['worker__worker_profile__status'] == 'ACTIVE'})
    return {'year': year, 'month': month, 'timezone': str(ZONE),
            'period': {'start': selected_month.isoformat(), 'end': next_month(selected_month).isoformat(), 'end_exclusive': True},
            'basis': 'unique_customer_worker_additions_per_month', 'summary': summary,
            'timeline': timeline, 'top_workers': workers}
