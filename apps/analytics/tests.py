from datetime import datetime
from decimal import Decimal
from io import BytesIO, StringIO
from zipfile import ZipFile
from xml.etree import ElementTree

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.reviews.models import Review
from apps.services.models import Service
from apps.wallets.models import WorkerEarning
from apps.worker.models import BookingAssignment, CustomerFavoriteWorker
from apps.complaints.models import Complaint, ComplaintIssueType
from apps.bookings.models import Booking, BookingSchedule
from .report_service import Report, ReportParams, ZONE

User = get_user_model()


def at(value):
    return datetime.fromisoformat(value).replace(tzinfo=ZONE)


class AdminReportTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='report-admin', email='report-admin@test.com', role='ADMIN')
        self.customer = User.objects.create_user(username='report-customer', email='report-customer@test.com', role='CUSTOMER')
        self.workers = [User.objects.create_user(username=f'report-worker-{i}', email=f'report-worker-{i}@test.com', role='WORKER') for i in range(2)]
        for i, worker in enumerate(self.workers):
            WorkerProfile.objects.create(user=worker, status='ACTIVE' if i == 0 else 'SUSPENDED')
        self.services = [Service.objects.create(code=f'report-service-{i}', section_code='HOME_CLEANING', name=f'Dịch vụ {i}', description='', form_schema={}, pricing_config={}) for i in range(2)]
        self.address = CustomerAddress.objects.create(customer=self.customer, receiver_name='Test', receiver_phone='0900000000', address_line='123 Test', city='HCM')
        self.b1 = self.booking('ONE', 300000, 'COMPLETED', 0)
        self.b2 = self.booking('TWO', 200000, 'COMPLETED', 1)
        self.booking('CANCEL', 400000, 'CANCELLED', 0)
        self.booking('FAIL', 100000, 'FAILED', 1)
        self.old = self.booking('OLD', 500000, 'COMPLETED', 1, '2026-09-01T09:00')
        self.e1, a1 = self.earning(self.b1, 1, 150000, 0, '2026-10-05T10:00')
        self.e2, a2 = self.earning(self.b1, 2, 150000, 0, '2026-10-06T10:00')
        self.earning(self.b2, 1, 200000, 1, '2026-10-07T10:00')
        self.earning(self.old, 1, 500000, 1, '2026-10-08T10:00', cash=True)
        for assignment, rating, visible in [(a1, 4, True), (a2, 5, True)]:
            review = Review.objects.create(assignment=assignment, rating=rating, is_visible=visible)
            Review.objects.filter(pk=review.pk).update(created_at=at('2026-10-09T10:00'))
        self.params = {'period': 'custom', 'start': '2026-10-05', 'end': '2026-10-12'}
        self.client.force_authenticate(self.admin)

    def booking(self, code, amount, status, service, created='2026-10-05T09:00'):
        booking = Booking.objects.create(booking_code=f'REPORT-{code}', customer=self.customer, service=self.services[service],
            address=self.address, service_data={}, total_amount=amount, status=status)
        Booking.objects.filter(pk=booking.pk).update(created_at=at(created))
        return booking

    def earning(self, booking, sequence, amount, worker, date, cash=False):
        schedule = BookingSchedule.objects.create(booking=booking, sequence_no=sequence, status='COMPLETED',
            scheduled_start=at(date.replace('10:00', '08:00')), scheduled_end=at(date), actual_end=at(date))
        assignment = BookingAssignment.objects.create(worker=self.workers[worker], schedule=schedule, status='ACCEPTED')
        earning = WorkerEarning.objects.create(worker=self.workers[worker], schedule=schedule, booking=booking,
            gross_amount=amount, commission_amount=Decimal(amount) / 10, worker_amount=Decimal(amount) * Decimal('.9'),
            commission_rate=Decimal('.1'), payment_method='CASH' if cash else 'ONLINE', completed_at=at(date))
        return earning, assignment

    def data(self, name='overview', params=None):
        response = self.client.get(reverse(f'admin-report-{name}'), params or self.params)
        self.assertEqual(response.status_code, 200, response.data)
        return response.data['data']

    def test_summary_uses_separate_date_cohorts_and_no_fanout(self):
        summary = self.data()['summary']
        self.assertEqual(summary['total_orders'], 4)
        self.assertEqual(summary['total_order_value'], '1000000.00')
        self.assertEqual(summary['cancelled_failed_order_value'], '500000.00')
        self.assertEqual(summary['valid_order_value'], '500000.00')
        self.assertEqual(summary['cleanwise_revenue'], '100000.00')
        self.assertEqual(summary['worker_income'], '900000.00')
        self.assertEqual(summary['cash_commission_owed_in_period'], '50000.00')
        self.assertEqual(summary['active_workers_current'], 1)
        self.assertEqual(summary['completed_sessions'], 4)
        self.assertEqual(summary['missing_earning_sessions'], 0)

    def test_timeline_zero_days_and_totals_match(self):
        data = self.data()
        self.assertEqual(len(data['timeline']), 7)
        self.assertEqual(data['timeline'][-1]['cleanwise_revenue'], '0.00')
        self.assertEqual(sum(r['orders'] for r in data['timeline']), 4)
        self.assertEqual(sum(Decimal(r['cleanwise_revenue']) for r in data['timeline']), Decimal(data['summary']['cleanwise_revenue']))
        self.assertEqual(sum(Decimal(r['order_value']) for r in data['timeline']), Decimal(data['summary']['total_order_value']))

    def test_workers_distinct_orders_and_rating_sort(self):
        rows = self.data('workers')['results']
        self.assertEqual(rows[0]['worker_id'], self.workers[1].id)
        self.assertEqual(rows[0]['completed_orders'], 2)
        self.assertEqual(rows[1]['completed_orders'], 1)
        self.assertEqual(rows[1]['completed_sessions'], 2)
        self.assertEqual(rows[1]['average_rating'], 4.5)
        params = {**self.params, 'sort': 'rating'}
        self.assertEqual(self.data('workers', params)['results'][0]['worker_id'], self.workers[0].id)
        self.assertIsNone(rows[0]['average_rating'])
        Review.objects.update(is_visible=False)
        self.assertTrue(all(r['average_rating'] is None for r in self.data('workers')['results']))

    def test_services_match_summary(self):
        rows = self.data('services')['results']
        self.assertEqual(sum(r['orders'] for r in rows), 4)
        self.assertEqual(sum(r['order_share_percent'] for r in rows), 100)
        self.assertEqual(sum(Decimal(r['cleanwise_revenue']) for r in rows), Decimal('100000'))

    def test_worker_favorites_are_current_unique_customers_and_sort_before_pagination(self):
        other = User.objects.create_user(username='favorite-report', email='favorite-report@test.com', role='CUSTOMER')
        link = CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.workers[0])
        CustomerFavoriteWorker.objects.filter(pk=link.pk).update(created_at=at('2026-09-01T10:00'))
        CustomerFavoriteWorker.objects.create(customer=other, worker=self.workers[0])
        CustomerFavoriteWorker.objects.create(customer=self.customer, worker=self.workers[1])
        page = self.data('workers', {**self.params, 'sort': 'favorites', 'page_size': 1})
        self.assertEqual(page['results'][0]['worker_id'], self.workers[0].pk)
        self.assertEqual(page['results'][0]['favorite_count_current'], 2)
        self.assertTrue(page['has_next'])
        link.delete()
        rows = self.data('workers', {**self.params, 'sort': 'favorites'})['results']
        self.assertTrue(all(r['favorite_count_current'] == 1 for r in rows))

    def test_customer_complaints_counts_statuses_and_period_without_join_fanout(self):
        issue = ComplaintIssueType.objects.create(code='REPORT_ISSUE', name='Phản ánh')
        def complaint(worker, status, role='CUSTOMER', date='2026-10-05T00:00'):
            obj = Complaint.objects.create(booking=self.b1, worker=worker, reporter=self.customer if role == 'CUSTOMER' else worker,
                reporter_role=role, issue_type=issue, stage='AFTER_SERVICE', status='PENDING')
            Complaint.objects.filter(pk=obj.pk).update(created_at=at(date), status=status)
        for status in ['PENDING', 'IN_REVIEW', 'RESOLVED', 'REJECTED', 'CANCELLED']:
            complaint(self.workers[0], status)
        complaint(self.workers[0], 'PENDING', date='2026-10-12T00:00')
        complaint(self.workers[0], 'PENDING', date='2026-10-04T23:59')
        complaint(self.workers[1], 'RESOLVED')
        complaint(self.workers[1], 'PENDING', role='WORKER')
        complaint(None, 'PENDING')
        rows = self.data('workers', {**self.params, 'sort': 'complaints'})['results']
        self.assertEqual(rows[0]['worker_id'], self.workers[0].pk)
        self.assertEqual(rows[0]['complaint_count'], 4)
        self.assertEqual(rows[0]['complaint_pending_count'], 2)
        self.assertEqual(rows[0]['complaint_resolved_count'], 1)
        self.assertEqual(rows[0]['complaint_rejected_count'], 1)
        self.assertEqual(rows[0]['completed_sessions'], 2)
        self.assertEqual(rows[1]['complaint_count'], 1)
        self.assertEqual(rows[1]['favorite_count_current'], 0)

    def test_periods_week_month_quarter_leap_year(self):
        cases = [('week', '2026-10-01', '2026-09-28', '2026-10-05'),
                 ('month', '2024-02-20', '2024-02-01', '2024-03-01'),
                 ('quarter', '2026-12-31', '2026-10-01', '2027-01-01')]
        for period, date, start, end in cases:
            with self.subTest(period=period):
                parsed = ReportParams(data={'period': period, 'date': date})
                parsed.is_valid(raise_exception=True)
                report = Report(parsed.validated_data)
                self.assertEqual(report.period()['start'], start)
                self.assertEqual(report.period()['end'], end)

    def test_boundaries_use_vietnam_timezone_and_exclusive_end(self):
        self.booking('START', 1, 'PENDING', 0, '2026-10-05T00:00')
        self.booking('END', 1, 'PENDING', 0, '2026-10-12T00:00')
        self.assertEqual(self.data()['summary']['total_orders'], 5)

    def test_paginated_details_and_recent_workers(self):
        rows = self.data('revenue', {**self.params, 'page_size': 2})
        self.assertEqual(rows['count'], 4)
        self.assertEqual(len(rows['results']), 2)
        self.assertTrue(rows['has_next'])
        self.assertEqual(len(self.data('bookings')['results']), 4)
        recent = next(row for row in self.data()['recent_bookings'] if row['id'] == self.b1.id)
        self.assertEqual(len(recent['workers']), 1)

    def test_data_quality_refunds_and_missing_ledger(self):
        Booking.objects.filter(pk=self.b2.pk).update(payment_status='REFUNDED')
        BookingSchedule.objects.create(booking=self.b2, sequence_no=2, status='COMPLETED',
            scheduled_start=at('2026-10-10T08:00'), scheduled_end=at('2026-10-10T10:00'), actual_end=at('2026-10-10T10:00'))
        summary = self.data()['summary']
        self.assertEqual(summary['commission_on_refunded_bookings'], '20000.00')
        self.assertEqual(summary['missing_earning_sessions'], 1)
        self.assertEqual(summary['cleanwise_revenue'], '100000.00')

    def test_invalid_inputs_and_permissions(self):
        for params in ({'period': 'bad'}, {'period': 'custom'}, {**self.params, 'end': '2026-10-01'},
                       {'period': 'week', 'date': '2026-02-30'}, {'date': '9999-12-31'},
                       {**self.params, 'page_size': 101}, {**self.params, 'page': 0},
                       {'period': 'all', 'start': '2026-10-01'}, {**self.params, 'sort': 'bad'}):
            self.assertEqual(self.client.get(reverse('admin-report-overview'), params).status_code, 400)
        self.assertEqual(self.client.get(reverse('admin-report-revenue'), {**self.params, 'page': 99}).status_code, 400)
        for user in (self.customer, self.workers[0], None):
            self.client.force_authenticate(user)
            for endpoint in ('overview', 'workers', 'services', 'revenue', 'bookings', 'export'):
                self.assertIn(self.client.get(reverse(f'admin-report-{endpoint}'), self.params).status_code, (401, 403))

    def test_excel_valid_numeric_cells_and_literal_strings(self):
        self.workers[0].first_name = '=1+1'
        self.workers[0].save(update_fields=['first_name'])
        response = self.client.get(reverse('admin-report-export'), self.params)
        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(response.content)) as archive:
            workbook = ElementTree.fromstring(archive.read('xl/workbook.xml'))
            ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            self.assertEqual(len(workbook.findall('s:sheets/s:sheet', ns)), 5)
            summary = ElementTree.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            self.assertIn('100000.00', [v.text for v in summary.findall('.//s:v', ns)])
            for file in archive.namelist():
                if file.endswith('.xml'):
                    ElementTree.fromstring(archive.read(file))
            workers = ElementTree.fromstring(archive.read('xl/worksheets/sheet3.xml'))
            self.assertEqual(workers.findall('.//s:f', ns), [])
            self.assertIn('=1+1', archive.read('xl/worksheets/sheet3.xml').decode())

    def test_empty_period(self):
        data = self.data(params={'period': 'month', 'date': '2020-02-01'})
        self.assertEqual(data['summary']['total_orders'], 0)
        self.assertEqual(data['summary']['cleanwise_revenue'], '0.00')
        self.assertEqual(len(data['timeline']), 29)

    def test_seed_is_additive_and_idempotent(self):
        existing = self.b1.total_amount
        call_command('seed_admin_reports', stdout=StringIO())
        count = Booking.objects.filter(booking_code__startswith='CW-RPT-').count()
        earnings = WorkerEarning.objects.count()
        self.assertEqual(count, 30)
        self.assertGreater(earnings, 4)
        call_command('seed_admin_reports', stdout=StringIO())
        self.assertEqual(Booking.objects.filter(booking_code__startswith='CW-RPT-').count(), count)
        self.assertEqual(WorkerEarning.objects.count(), earnings)
        self.b1.refresh_from_db()
        self.assertEqual(self.b1.total_amount, existing)
