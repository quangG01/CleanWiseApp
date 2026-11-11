from datetime import date, datetime, timezone as utc
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.authentication.models import WorkerProfile
from apps.worker.models import CustomerFavoriteWorker, WorkerFavoriteMonthlyEntry
from apps.bookings.models import Booking
from apps.wallets.models import Wallet
from apps.notifications.models import Notification
from .report_service import ZONE

User = get_user_model()


class MonthlyFavoriteReportTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='fav-admin', email='fav-admin@test.com', role='ADMIN')
        self.customers = [User.objects.create_user(username=f'fav-customer-{i}', email=f'fav-customer-{i}@test.com', role='CUSTOMER') for i in range(4)]
        self.workers = [User.objects.create_user(username=f'fav-worker-{i}', email=f'fav-worker-{i}@test.com', role='WORKER') for i in range(3)]
        for i, worker in enumerate(self.workers):
            WorkerProfile.objects.create(user=worker, status='ACTIVE' if i != 1 else 'SUSPENDED')
        self.client.force_authenticate(self.admin)
        self.url = reverse('admin-report-favorite-workers')

    def entry(self, month, worker=0, customer=0, source='LIVE'):
        month = date.fromisoformat(month)
        return WorkerFavoriteMonthlyEntry.objects.create(customer=self.customers[customer], worker=self.workers[worker],
            month=month, first_favorited_at=datetime(month.year, month.month, 3, 10, tzinfo=ZONE), source=source)

    def report(self, year=2026, month=10, **extra):
        response = self.client.get(self.url, {'year': year, 'month': month, **extra})
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_monthly_totals_ranking_ties_previous_comparison_and_empty_buckets(self):
        self.entry('2026-09-01')
        self.entry('2026-10-01')
        self.entry('2026-10-01', customer=1)
        self.entry('2026-10-01', worker=1, customer=1)
        self.entry('2026-10-01', worker=1, customer=2)
        self.entry('2026-10-01', worker=2, customer=0, source='BACKFILL')
        report = self.report(limit=2)
        self.assertEqual(report['summary'], {'favorites': 5, 'customers': 3, 'workers': 3, 'legacy_entries': 1,
            'previous_month_favorites': 1, 'change': 4, 'change_percent': 400.0})
        self.assertEqual(len(report['timeline']), 12)
        self.assertEqual(report['timeline'][9]['favorites'], 5)
        self.assertEqual(report['timeline'][0]['favorites'], 0)
        self.assertEqual(sum(row['favorites'] for row in report['timeline']), 6)
        self.assertEqual([row['worker_id'] for row in report['top_workers']], [self.workers[0].pk, self.workers[1].pk])
        self.assertFalse(report['top_workers'][1]['active_current'])
        self.assertEqual(report['period']['end'], '2026-11-01')

    def test_unfavorite_does_not_erase_monthly_history(self):
        self.entry('2026-10-01')
        link = CustomerFavoriteWorker.objects.create(customer=self.customers[0], worker=self.workers[0])
        link.delete()
        self.assertEqual(self.report()['summary']['favorites'], 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.entry('2026-10-01')
        self.entry('2026-11-01')
        self.assertEqual(self.report(month=11)['summary']['favorites'], 1)

    def test_january_comparison_uses_previous_year_and_empty_data(self):
        self.entry('2025-12-01')
        report = self.report(month=1)
        self.assertEqual(report['summary']['favorites'], 0)
        self.assertEqual(report['summary']['previous_month_favorites'], 1)
        self.assertEqual(report['summary']['change_percent'], -100.0)
        self.assertEqual(report['top_workers'], [])
        self.assertIsNone(self.report(year=2027)['summary']['change_percent'])

    def test_params_defaults_follow_vietnam_month_and_invalid_values_are_rejected(self):
        with patch('django.utils.timezone.now', return_value=datetime(2026, 9, 30, 17, 0, tzinfo=utc.utc)):
            data = self.client.get(self.url).data['data']
        self.assertEqual((data['year'], data['month']), (2026, 10))
        for params in ({'month': 0}, {'month': 13}, {'year': 1999}, {'year': 2101}, {'limit': 51}, {'month': 'bad'}):
            self.assertEqual(self.client.get(self.url, params).status_code, 400)

    def test_only_admin_can_read(self):
        for user in (self.customers[0], self.workers[0], None):
            self.client.force_authenticate(user)
            self.assertIn(self.client.get(self.url).status_code, (401, 403))

    def test_backfill_uses_original_date_and_can_be_replayed(self):
        import importlib
        from types import SimpleNamespace
        from django.db import connection
        module = importlib.import_module('apps.worker.migrations.0010_backfill_monthly_favorites')
        link = CustomerFavoriteWorker.objects.create(customer=self.customers[0], worker=self.workers[0])
        original = datetime(2026, 9, 30, 17, 0, tzinfo=utc.utc)
        CustomerFavoriteWorker.objects.filter(pk=link.pk).update(created_at=original)
        for _ in range(2):
            module.backfill(apps, SimpleNamespace(connection=connection))
        entry = WorkerFavoriteMonthlyEntry.objects.get()
        self.assertEqual(entry.month, date(2026, 10, 1))
        self.assertEqual(entry.first_favorited_at, original)
        self.assertEqual(entry.source, 'BACKFILL')

    @override_settings(DEBUG=True)
    def test_seed_is_idempotent_varied_historical_and_preserves_existing_data(self):
        now = datetime(2026, 10, 23, 10, tzinfo=ZONE)
        notification_count = Notification.objects.count()
        with patch('django.utils.timezone.now', return_value=now):
            call_command('seed_monthly_favorites', date='2026-10-23', months=12, stdout=StringIO())
            entry_count = WorkerFavoriteMonthlyEntry.objects.count()
            job_count = Booking.objects.count()
            wallets = list(Wallet.objects.values())
            links = CustomerFavoriteWorker.objects.count()
            self.assertGreater(entry_count, 1000)
            self.assertEqual(User.objects.filter(username__startswith='cw_fav_demo_worker_').count(), 8)
            self.assertEqual(WorkerFavoriteMonthlyEntry.objects.values('month').distinct().count(), 12)
            self.assertFalse(WorkerFavoriteMonthlyEntry.objects.filter(first_favorited_at__gt=now).exists())
            call_command('seed_monthly_favorites', date='2026-10-23', months=12, stdout=StringIO())
        self.assertEqual(WorkerFavoriteMonthlyEntry.objects.count(), entry_count)
        self.assertEqual(Booking.objects.count(), job_count)
        self.assertEqual(CustomerFavoriteWorker.objects.count(), links)
        self.assertEqual(list(Wallet.objects.values()), wallets)
        self.assertEqual(Notification.objects.count(), notification_count)
        self.assertTrue(self.customers[0].is_active)
        self.assertGreater(len({row['favorites'] for row in self.report()['timeline']}), 1)

    def test_seed_refuses_production_and_invalid_options(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command('seed_monthly_favorites', stdout=StringIO())
        with override_settings(DEBUG=True):
            for params in ({'months': 25}, {'date': 'invalid'}, {'date': '2100-12-31'}):
                with self.assertRaises(CommandError):
                    call_command('seed_monthly_favorites', stdout=StringIO(), **params)
