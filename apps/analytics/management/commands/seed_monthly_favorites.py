"""Deterministic, additive demo data isolated to reserved sample accounts."""
import calendar
from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.services.models import Service
from apps.wallets.models import WorkerEarning
from apps.worker.models import BookingAssignment, CustomerFavoriteWorker, WorkerFavoriteMonthlyEntry
from apps.analytics.report_service import ZONE


class Command(BaseCommand):
    help = 'Sinh dữ liệu yêu thích theo tháng cho tài khoản mẫu riêng; chạy lại không tạo trùng. Chỉ DEBUG.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Ngày neo YYYY-MM-DD, mặc định hôm nay theo giờ Việt Nam.')
        parser.add_argument('--months', type=int, default=12)

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Chỉ sinh dữ liệu mẫu khi DEBUG=True.')
        today = timezone.localdate(timezone=ZONE)
        try:
            anchor = datetime.strptime(options['date'], '%Y-%m-%d').date() if options['date'] else today
        except ValueError as exc:
            raise CommandError('--date phải có dạng YYYY-MM-DD.') from exc
        if anchor > today or not 2000 <= anchor.year <= 2100:
            raise CommandError('Ngày neo phải nằm trong năm 2000–2100 và không ở tương lai.')
        months = options['months']
        if not 1 <= months <= 24:
            raise CommandError('--months phải từ 1 đến 24.')

        User = get_user_model()

        def account(username, role, name):
            user, created = User.objects.get_or_create(username=username, defaults={
                'email': f'{username}@cleanwise.test', 'role': role, 'first_name': name, 'last_name': '',
            })
            if user.role != role or user.email != f'{username}@cleanwise.test':
                raise CommandError(f'Tài khoản {username} đã tồn tại với thông tin khác; dừng để tránh sửa dữ liệu thật.')
            if created:
                user.set_unusable_password()
                user.save(update_fields=['password'])
            return user

        names = ['Nguyễn Thị Mai', 'Trần Minh Anh', 'Lê Ngọc Hân', 'Phạm Thu Hà',
                 'Võ Thanh Tâm', 'Đặng Hoài An', 'Bùi Thị Lan', 'Đỗ Quang Huy']
        workers = [account(f'cw_fav_demo_worker_{index + 1:02}', 'WORKER', name) for index, name in enumerate(names)]
        customers = [account(f'cw_fav_demo_customer_{index + 1:02}', 'CUSTOMER', f'Khách mẫu {index + 1:02}') for index in range(32)]
        service, _ = Service.objects.get_or_create(code='CW_FAVORITE_DEMO', defaults={
            'section_code': 'HOME_CLEANING', 'name': 'Dọn dẹp nhà · Mẫu yêu thích', 'description': 'Dịch vụ mẫu cho thống kê yêu thích.',
            'form_schema': {}, 'pricing_config': {},
        })
        for worker in workers:
            # A draft profile is created first, then activated without approval signals/push.
            profile, created = WorkerProfile.objects.get_or_create(user=worker, defaults={'status': 'DRAFT'})
            if created:
                WorkerProfile.objects.filter(pk=profile.pk).update(status='ACTIVE', registered_service=service)
        existing_entries = set(WorkerFavoriteMonthlyEntry.objects.filter(worker__in=workers, customer__in=customers).values_list('customer_id', 'worker_id', 'month'))
        existing_links = set(CustomerFavoriteWorker.objects.filter(worker__in=workers, customer__in=customers).values_list('customer_id', 'worker_id'))
        entries, links, pairs = [], [], {}
        for offset in range(months - 1, -1, -1):
            ordinal = anchor.year * 12 + anchor.month - 1 - offset
            year, zero_month = divmod(ordinal, 12)
            month = anchor.replace(year=year, month=zero_month + 1, day=1)
            for index, worker in enumerate(workers):
                # Each month has a different leader and volume; no random or future dates.
                volume = max(2, min(30, 6 + (months - offset) // 2 + ((index * 5 + month.month * 3) % 17)))
                for ci in range(volume):
                    customer_index = (ci + index * 3 + month.month) % len(customers)
                    customer = customers[customer_index]
                    max_day = anchor.day if offset == 0 else calendar.monthrange(year, month.month)[1]
                    day = 1 + ((ci * 3 + index) % max_day)
                    occurred = min(datetime.combine(month.replace(day=day), time(10), tzinfo=ZONE), timezone.now())
                    key = (customer.pk, worker.pk, month)
                    if key not in existing_entries:
                        entries.append(WorkerFavoriteMonthlyEntry(customer=customer, worker=worker, month=month, first_favorited_at=occurred, source='DEMO'))
                        existing_entries.add(key)
                    code = f'CW-FAV-DEMO-{index + 1:02}-{customer_index + 1:02}'
                    pairs.setdefault(code, (customer, worker, occurred - timedelta(days=1, hours=3)))
                    if offset == 0 and (customer.pk, worker.pk) not in existing_links:
                        links.append((CustomerFavoriteWorker(customer=customer, worker=worker), occurred))
                        existing_links.add((customer.pk, worker.pk))
        WorkerFavoriteMonthlyEntry.objects.bulk_create(entries, batch_size=500)
        CustomerFavoriteWorker.objects.bulk_create([link for link, _ in links], batch_size=500)
        for link, occurred in links:
            link.created_at = occurred
        CustomerFavoriteWorker.objects.bulk_update([link for link, _ in links], ['created_at'], batch_size=500)

        # Seed eligibility with bulk inserts: no status signals, notifications or wallet mutations.
        existing_codes = set(Booking.objects.filter(booking_code__in=pairs).values_list('booking_code', flat=True))
        addresses, new_bookings = {}, []
        for code, (customer, worker, start) in pairs.items():
            if code in existing_codes:
                continue
            if customer.pk not in addresses:
                addresses[customer.pk], _ = CustomerAddress.objects.get_or_create(customer=customer, address_line='Địa chỉ mẫu thống kê yêu thích', defaults={
                    'receiver_name': customer.first_name, 'receiver_phone': '0900000000', 'city': 'TP Hồ Chí Minh',
                })
            new_bookings.append(Booking(booking_code=code, customer=customer, service=service, address=addresses[customer.pk], service_data={},
                note='Dữ liệu mẫu yêu thích; buổi 0đ, không phát sinh giao dịch hoặc thay đổi số dư ví.',
                status='COMPLETED', payment_status='PAID', total_amount=0))
        Booking.objects.bulk_create(new_bookings, batch_size=500)
        schedules = []
        for booking in new_bookings:
            customer, worker, start = pairs[booking.booking_code]
            booking.created_at = start
            schedules.append(BookingSchedule(booking=booking, sequence_no=1, status='COMPLETED',
                scheduled_start=start, scheduled_end=start + timedelta(hours=2), actual_start=start, actual_end=start + timedelta(hours=2)))
        Booking.objects.bulk_update(new_bookings, ['created_at'], batch_size=500)
        BookingSchedule.objects.bulk_create(schedules, batch_size=500)
        assignments, earnings = [], []
        for schedule in schedules:
            _, worker, start = pairs[schedule.booking.booking_code]
            assignments.append(BookingAssignment(schedule=schedule, worker=worker, status='ACCEPTED', responded_at=start))
            earnings.append(WorkerEarning(worker=worker, schedule=schedule, booking=schedule.booking,
                payment_method='ONLINE', gross_amount=0, commission_amount=0, worker_amount=0,
                commission_rate='0.10', completed_at=start + timedelta(hours=2)))
        BookingAssignment.objects.bulk_create(assignments, batch_size=500)
        WorkerEarning.objects.bulk_create(earnings, batch_size=500)
        self.stdout.write(self.style.SUCCESS(
            f'anchor={anchor}; months={months}; workers=8; customers=32; created_entries={len(entries)}; '
            f'created_current_favorites={len(links)}; created_demo_sessions={len(new_bookings)}.'))
        self.stdout.write('Prefix cw_fav_demo_ / CW-FAV-DEMO-. Existing users, favorites, orders and wallet balances unchanged.')
