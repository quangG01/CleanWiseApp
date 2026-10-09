"""Shared report calculations. Orders use created_at; earned commission uses completed_at."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Avg, Count, Min, Prefetch, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncWeek
from django.utils import timezone
from rest_framework import serializers

from apps.reviews.models import Review
from apps.services.models import Service
from apps.wallets.models import WorkerEarning
from apps.worker.models import BookingAssignment, CustomerFavoriteWorker
from apps.complaints.models import Complaint
from apps.bookings.models import Booking, BookingSchedule

ZONE = ZoneInfo('Asia/Ho_Chi_Minh')
User = get_user_model()


class ReportParams(serializers.Serializer):
    period = serializers.ChoiceField(choices=['all', 'week', 'month', 'quarter', 'custom'], default='all')
    date = serializers.DateField(required=False)
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    group_by = serializers.ChoiceField(choices=['auto', 'day', 'week', 'month'], default='auto')
    sort = serializers.ChoiceField(choices=['orders', 'sessions', 'rating', 'commission', 'favorites', 'complaints'], default='orders')
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)

    def validate(self, attrs):
        for field in ('date', 'start', 'end'):
            if field in attrs and not 1900 <= attrs[field].year <= 2100:
                raise serializers.ValidationError({field: 'Ngày báo cáo phải nằm trong năm 1900–2100.'})
        if attrs['period'] == 'custom':
            if 'start' not in attrs or 'end' not in attrs:
                raise serializers.ValidationError('Kỳ custom cần start và end (end không bao gồm).')
            if not 0 < (attrs['end'] - attrs['start']).days <= 3660:
                raise serializers.ValidationError('Khoảng ngày phải từ 1 đến 3660 ngày.')
        elif 'start' in attrs or 'end' in attrs:
            raise serializers.ValidationError('Chỉ truyền start/end khi period=custom.')
        return attrs


def money(value):
    return format(value or Decimal('0'), '.2f')


def next_month(date):
    return date.replace(year=date.year + (date.month == 12), month=date.month % 12 + 1, day=1)


class Report:
    def __init__(self, params):
        self.params = params
        today = timezone.localdate(timezone=ZONE)
        date = params.get('date', today)
        period = params['period']
        if period == 'custom':
            start, end = params['start'], params['end']
        elif period == 'week':
            start = date - timedelta(days=date.weekday())
            end = start + timedelta(days=7)
        elif period == 'month':
            start = date.replace(day=1)
            end = next_month(start)
        elif period == 'quarter':
            start = date.replace(month=(date.month - 1) // 3 * 3 + 1, day=1)
            end = next_month(next_month(next_month(start)))
        else:
            dates = [Booking.objects.aggregate(value=Min('created_at'))['value'],
                     WorkerEarning.objects.aggregate(value=Min('completed_at'))['value'],
                     Review.objects.aggregate(value=Min('created_at'))['value'],
                     Complaint.objects.aggregate(value=Min('created_at'))['value']]
            start = min([timezone.localtime(d, ZONE).date() for d in dates if d] + [today])
            end = today + timedelta(days=1)
        self.start, self.end = start, end
        self.lower = datetime.combine(start, time.min, tzinfo=ZONE)
        self.upper = datetime.combine(end, time.min, tzinfo=ZONE)
        days = (end - start).days
        group = params['group_by']
        self.group = ('day' if days <= 31 else 'week' if days <= 180 else 'month') if group == 'auto' else group
        if self.group == 'day' and days > 366:
            raise serializers.ValidationError({'group_by': 'Khoảng trên 366 ngày cần nhóm theo week hoặc month.'})
        if self.group == 'week' and days > 3660:
            raise serializers.ValidationError({'group_by': 'Khoảng trên 10 năm cần nhóm theo month.'})
        self.orders = self.between(Booking.objects.all(), 'created_at')
        self.earnings = self.between(WorkerEarning.objects.all(), 'completed_at')
        self.completed = self.between(BookingSchedule.objects.filter(status='COMPLETED'), 'actual_end')
        self.reviews = self.between(Review.objects.filter(is_visible=True), 'created_at')

    def between(self, queryset, field):
        return queryset.filter(**{f'{field}__gte': self.lower, f'{field}__lt': self.upper})

    def period(self):
        return {'type': self.params['period'], 'start': self.start.isoformat(), 'end': self.end.isoformat(),
                'end_exclusive': True, 'timezone': str(ZONE), 'group_by': self.group,
                'orders_date_field': 'created_at', 'revenue_date_field': 'completed_at',
                'reviews_date_field': 'created_at', 'complaints_date_field': 'created_at',
                'favorites_basis': 'current_saved_customers',
                'complaints_basis': 'customer_reports_excluding_cancelled',
                'revenue_basis': 'recorded_commission_before_refund_adjustments'}

    def summary(self):
        orders = self.orders.aggregate(total=Count('id'), amount=Sum('total_amount'),
            excluded=Sum('total_amount', filter=Q(status__in=['CANCELLED', 'FAILED'])))
        earnings = self.earnings.aggregate(gross=Sum('gross_amount'), commission=Sum('commission_amount'),
            income=Sum('worker_amount'), owed=Sum('commission_amount', filter=Q(payment_method='CASH', settled_at__isnull=True)),
            refund_review=Sum('commission_amount', filter=Q(booking__payment_status='REFUNDED')))
        statuses = {s: 0 for s, _ in Booking.Status.choices}
        statuses.update({r['status']: r['count'] for r in self.orders.values('status').annotate(count=Count('id'))})
        outstanding = WorkerEarning.objects.filter(payment_method='CASH', settled_at__isnull=True).aggregate(value=Sum('commission_amount'))['value']
        missing = self.completed.filter(worker_earning__isnull=True).count()
        today = timezone.localdate(timezone=ZONE)
        today_lower = datetime.combine(today, time.min, tzinfo=ZONE)
        today_upper = today_lower + timedelta(days=1)
        return {
            'total_orders': orders['total'], 'total_order_value': money(orders['amount']),
            'cancelled_failed_order_value': money(orders['excluded']),
            'valid_order_value': money((orders['amount'] or 0) - (orders['excluded'] or 0)),
            'order_statuses': statuses,
            'processing_orders': sum(statuses[s] for s in ('PENDING', 'ASSIGNED', 'IN_PROGRESS')),
            'completed_sessions': self.completed.count(), 'completed_service_value': money(earnings['gross']),
            'cleanwise_revenue': money(earnings['commission']), 'worker_income': money(earnings['income']),
            'cash_commission_owed_in_period': money(earnings['owed']),
            'cash_commission_owed_current': money(outstanding),
            'active_workers_current': User.objects.filter(role='WORKER', is_active=True, worker_profile__status='ACTIVE').count(),
            'orders_today': Booking.objects.filter(created_at__gte=today_lower, created_at__lt=today_upper).count(),
            'missing_earning_sessions': missing,
            'completed_sessions_missing_actual_end': BookingSchedule.objects.filter(status='COMPLETED', actual_end__isnull=True).count(),
            'commission_on_refunded_bookings': money(earnings['refund_review']),
        }

    def bucket(self, date):
        if self.group == 'week':
            return date - timedelta(days=date.weekday())
        if self.group == 'month':
            return date.replace(day=1)
        return date

    def timeline(self):
        truncate = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth}[self.group]
        order_rows = self.orders.order_by().annotate(bucket=truncate('created_at', tzinfo=ZONE)).values('bucket').annotate(count=Count('id'), value=Sum('total_amount'))
        earning_rows = self.earnings.order_by().annotate(bucket=truncate('completed_at', tzinfo=ZONE)).values('bucket').annotate(commission=Sum('commission_amount'), gross=Sum('gross_amount'))
        orders = {timezone.localtime(r['bucket'], ZONE).date(): r for r in order_rows}
        earnings = {timezone.localtime(r['bucket'], ZONE).date(): r for r in earning_rows}
        result, cursor = [], self.bucket(self.start)
        while cursor < self.end:
            nxt = next_month(cursor) if self.group == 'month' else cursor + timedelta(days=7 if self.group == 'week' else 1)
            o, e = orders.get(cursor, {}), earnings.get(cursor, {})
            result.append({'start': max(cursor, self.start).isoformat(), 'end': min(nxt, self.end).isoformat(),
                'orders': o.get('count', 0), 'order_value': money(o.get('value')),
                'cleanwise_revenue': money(e.get('commission')), 'completed_service_value': money(e.get('gross'))})
            cursor = nxt
        return result

    def workers(self):
        jobs = {r['assignments__worker_id']: r for r in self.completed.filter(assignments__status='ACCEPTED').order_by().values('assignments__worker_id').annotate(
            completed_orders=Count('booking_id', distinct=True), completed_sessions=Count('id', distinct=True))}
        earnings = {r['worker_id']: r for r in self.earnings.order_by().values('worker_id').annotate(commission=Sum('commission_amount'), income=Sum('worker_amount'))}
        ratings = {r['assignment__worker_id']: r for r in self.reviews.order_by().values('assignment__worker_id').annotate(rating=Avg('rating'), count=Count('id'))}
        favorites = dict(CustomerFavoriteWorker.objects.filter(customer__role='CUSTOMER').order_by().values('worker_id').annotate(
            count=Count('customer_id', distinct=True)).values_list('worker_id', 'count'))
        complaints = {r['worker_id']: r for r in self.between(
            Complaint.objects.filter(reporter_role='CUSTOMER', worker__isnull=False).exclude(status='CANCELLED'),
            'created_at').order_by().values('worker_id').annotate(
                total=Count('id'),
                pending=Count('id', filter=Q(status__in=['PENDING', 'IN_REVIEW'])),
                resolved=Count('id', filter=Q(status='RESOLVED')),
                rejected=Count('id', filter=Q(status='REJECTED')))}
        result = []
        for worker in User.objects.filter(role='WORKER').select_related('worker_profile').order_by('id'):
            job, earned, rating = jobs.get(worker.id, {}), earnings.get(worker.id, {}), ratings.get(worker.id, {})
            profile = getattr(worker, 'worker_profile', None)
            complaint = complaints.get(worker.id, {})
            result.append({'worker_id': worker.id, 'name': worker.get_full_name() or worker.username, 'username': worker.username,
                'active_current': worker.is_active and bool(profile and profile.status == 'ACTIVE'),
                'profile_status': profile.status if profile else None,
                'completed_orders': job.get('completed_orders', 0), 'completed_sessions': job.get('completed_sessions', 0),
                'average_rating': round(rating['rating'], 2) if rating else None, 'review_count': rating.get('count', 0),
                'favorite_count_current': favorites.get(worker.id, 0),
                'complaint_count': complaint.get('total', 0),
                'complaint_pending_count': complaint.get('pending', 0),
                'complaint_resolved_count': complaint.get('resolved', 0),
                'complaint_rejected_count': complaint.get('rejected', 0),
                'cleanwise_revenue': money(earned.get('commission')), 'worker_income': money(earned.get('income'))})
        sort = self.params['sort']
        primary = {'orders': lambda r: r['completed_orders'], 'sessions': lambda r: r['completed_sessions'],
                   'rating': lambda r: r['average_rating'] if r['average_rating'] is not None else -1,
                   'commission': lambda r: Decimal(r['cleanwise_revenue']),
                   'favorites': lambda r: r['favorite_count_current'],
                   'complaints': lambda r: r['complaint_count']}[sort]
        result.sort(key=lambda r: (-primary(r), -r['completed_sessions'], -r['review_count'], r['worker_id']))
        for rank, row in enumerate(result, 1):
            row['rank'] = rank
        return result

    def services(self):
        orders = {r['service_id']: r for r in self.orders.order_by().values('service_id').annotate(count=Count('id'), amount=Sum('total_amount'),
            cancelled=Count('id', filter=Q(status='CANCELLED')), failed=Count('id', filter=Q(status='FAILED')))}
        earned = {r['booking__service_id']: r for r in self.earnings.order_by().values('booking__service_id').annotate(commission=Sum('commission_amount'), gross=Sum('gross_amount'))}
        completed = {r['booking__service_id']: r['count'] for r in self.completed.order_by().values('booking__service_id').annotate(count=Count('id'))}
        total = sum(r['count'] for r in orders.values())
        result = []
        for service in Service.objects.order_by('id'):
            o, e = orders.get(service.id, {}), earned.get(service.id, {})
            result.append({'service_id': service.id, 'code': service.code, 'name': service.name, 'active_current': service.is_active,
                'orders': o.get('count', 0), 'order_share_percent': round(o.get('count', 0) * 100 / total, 2) if total else 0,
                'cancelled_orders': o.get('cancelled', 0), 'failed_orders': o.get('failed', 0),
                'completed_sessions': completed.get(service.id, 0), 'order_value': money(o.get('amount')),
                'completed_service_value': money(e.get('gross')), 'cleanwise_revenue': money(e.get('commission'))})
        return sorted(result, key=lambda r: (-r['orders'], r['service_id']))

    def revenue_queryset(self):
        return self.earnings.select_related('booking__service', 'worker', 'schedule').order_by('-completed_at', '-id')

    @staticmethod
    def revenue_row(earning):
        return {'id': earning.id, 'booking_id': earning.booking_id, 'booking_code': earning.booking.booking_code,
            'schedule_id': earning.schedule_id, 'sequence_no': earning.schedule.sequence_no,
            'worker_id': earning.worker_id, 'worker_name': earning.worker.get_full_name() or earning.worker.username,
            'service_id': earning.booking.service_id, 'service_name': earning.booking.service.name,
            'completed_at': earning.completed_at.isoformat(), 'payment_method': earning.payment_method,
            'gross_amount': money(earning.gross_amount), 'commission_rate': str(earning.commission_rate),
            'commission_amount': money(earning.commission_amount), 'worker_amount': money(earning.worker_amount),
            'settled_at': earning.settled_at.isoformat() if earning.settled_at else None,
            'cash_commission_owed': earning.payment_method == 'CASH' and earning.settled_at is None,
            'booking_payment_status': earning.booking.payment_status}

    def booking_queryset(self):
        return self.orders.select_related('customer', 'service').prefetch_related(Prefetch('schedules__assignments',
            queryset=BookingAssignment.objects.filter(status='ACCEPTED').select_related('worker'))).order_by('-created_at', '-id')

    @staticmethod
    def booking_row(booking):
        workers = {}
        for schedule in booking.schedules.all():
            for assignment in schedule.assignments.all():
                workers[assignment.worker_id] = {'id': assignment.worker_id, 'name': assignment.worker.get_full_name() or assignment.worker.username}
        return {'id': booking.id, 'booking_code': booking.booking_code, 'created_at': booking.created_at.isoformat(),
            'customer_name': booking.customer.get_full_name() or booking.customer.username,
            'service_id': booking.service_id, 'service_name': booking.service.name,
            'status': booking.status, 'status_label': booking.get_status_display(),
            'payment_status': booking.payment_status, 'total_amount': money(booking.total_amount), 'workers': list(workers.values())}
