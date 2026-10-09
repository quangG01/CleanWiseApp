"""Add report fixtures without modifying existing orders, balances, or transactions."""
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.models import Booking, BookingSchedule
from apps.analytics.report_service import ZONE
from apps.payments.models import Payment
from apps.reviews.models import Review
from apps.services.models import Service
from apps.wallets.earning_service import calculate_commission, calculate_gross_amount, COMMISSION_RATE
from apps.wallets.models import WorkerEarning
from apps.worker.models import BookingAssignment


class Command(BaseCommand):
    help = 'Thêm dữ liệu báo cáo trên 96 ngày, có sổ hoa hồng và đánh giá. Chạy lại không tạo trùng.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Ngày neo YYYY-MM-DD; mặc định hôm nay theo giờ Việt Nam.')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        now = timezone.now()
        anchor = timezone.localdate(timezone=ZONE)
        if options['date']:
            try:
                anchor = datetime.strptime(options['date'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--date phải có định dạng YYYY-MM-DD.')
        if anchor > timezone.localdate(timezone=ZONE):
            raise CommandError('Ngày neo không được nằm trong tương lai.')
        services = list(Service.objects.filter(is_active=True).order_by('id')[:3])
        customers = list(User.objects.filter(role='CUSTOMER', is_active=True).order_by('id')[:3])
        admin = User.objects.filter(role='ADMIN', is_active=True).first()
        if not services or not customers or not admin:
            raise CommandError('Cần dịch vụ active, khách hàng và admin trong DB.')
        created_orders = created_earnings = created_reviews = 0
        worker_ids = set()
        offsets = [0, 1, 2, 3, 6, 8, 12, 18, 25, 35, 50, 70, 95, 0, 0]
        for si, service in enumerate(services):
            workers = list(User.objects.filter(role='WORKER', is_active=True, worker_profile__status='ACTIVE',
                worker_profile__registered_service=service).order_by('id')[:2])
            if not workers:
                username = f'cw_report_worker_{service.id}'
                worker, new = User.objects.get_or_create(username=username, defaults={
                    'email': f'{username}@cleanwise.test', 'role': 'WORKER', 'is_active': True,
                    'first_name': 'Báo cáo', 'last_name': f'Nhân viên mẫu {service.id}',
                })
                if new:
                    worker.set_unusable_password()
                    worker.save(update_fields=['password'])
                if worker.role != 'WORKER':
                    raise CommandError(f'Tài khoản {username} đang có role khác WORKER.')
                profile, profile_new = WorkerProfile.objects.get_or_create(user=worker, defaults={'status': 'DRAFT'})
                # QuerySet update avoids profile-approval push notifications for test fixtures.
                if new or profile_new:
                    WorkerProfile.objects.filter(pk=profile.pk).update(status='ACTIVE', registered_service=service,
                        approved_by=admin, approved_at=now)
                elif not worker.is_active or profile.status != 'ACTIVE' or profile.registered_service_id != service.id:
                    raise CommandError(f'Tài khoản mẫu {username} đã thay đổi trạng thái/dịch vụ; không tự cập nhật lại.')
                workers = [worker]
            customer = customers[si % len(customers)]
            address = CustomerAddress.objects.filter(customer=customer, is_active=True).first()
            if not address:
                address = CustomerAddress.objects.create(customer=customer, receiver_name=customer.get_full_name() or customer.username,
                    receiver_phone=customer.phone_number or '0900000000', address_line='123 Nguyễn Huệ (dữ liệu báo cáo)', city='TP Hồ Chí Minh')
            for index, offset in enumerate(offsets):
                code = f'CW-RPT-{service.id}-{anchor:%y%m%d}-{index}'
                day = anchor - timedelta(days=offset)
                worker = workers[index % len(workers)]
                worker_ids.add(worker.id)
                sessions = 2 if index % 4 == 0 or index == 3 else 1
                unit_price = Decimal(200000 + si * 100000 + index * 10000)
                status = 'ASSIGNED' if index in (0, 3) else ('CANCELLED' if index == 5 else 'FAILED' if index == 8 else 'COMPLETED')
                first_hour = 11 if index == 14 else 8
                if offset == 0 and datetime.combine(day, time(first_hour + 2), tzinfo=ZONE) > now:
                    status = 'ASSIGNED'
                partial = index == 3
                booking, new = Booking.objects.get_or_create(booking_code=code, defaults={
                    'customer': customer, 'service': service, 'address': address, 'status': status,
                    'service_data': {'date': (day + timedelta(days=1) if offset == 0 and status == 'ASSIGNED' else day).isoformat(),
                                     'start_time': f'{first_hour:02}:00', 'duration': '2_HOURS'},
                    'note': 'Dữ liệu mẫu báo cáo; sổ thu nhập là snapshot test, không thay đổi ví.',
                    'price_breakdown': {'unit_price': str(unit_price)}, 'subtotal_amount': unit_price * sessions,
                    'total_amount': unit_price * sessions, 'payment_status': 'UNPAID' if status == 'FAILED' else 'REFUNDED' if status == 'CANCELLED' else 'PAID',
                    'cancelled_at': datetime.combine(day, time(10), tzinfo=ZONE) if status == 'CANCELLED' else None,
                })
                if not new:
                    continue
                created_at = now if offset == 0 else datetime.combine(day, time(6), tzinfo=ZONE)
                Booking.objects.filter(pk=booking.pk).update(created_at=created_at)
                cash = index % 3 == 0
                Payment.objects.create(booking=booking, customer=customer, amount=booking.total_amount,
                    method='CASH' if cash else 'BANK_TRANSFER',
                    status='REFUNDED' if status == 'CANCELLED' else 'PENDING' if status == 'FAILED' else 'SUCCESS',
                    transaction_code=f'DEMO-{code}', paid_at=created_at if status not in ('FAILED', 'CANCELLED') else None)
                for sequence in range(1, sessions + 1):
                    planned_day = day + timedelta(days=1) if offset == 0 and status == 'ASSIGNED' else day
                    start = datetime.combine(planned_day, time(first_hour + (sequence - 1) * 3), tzinfo=ZONE)
                    end = start + timedelta(hours=2)
                    done = status == 'COMPLETED' or (partial and sequence == 1)
                    schedule = BookingSchedule.objects.create(booking=booking, sequence_no=sequence,
                        scheduled_start=start, scheduled_end=end, actual_start=start if done else None, actual_end=end if done else None,
                        status='COMPLETED' if done else 'CANCELLED' if status == 'CANCELLED' else 'MISSED' if status == 'FAILED' else 'PENDING')
                    assignment = BookingAssignment.objects.create(schedule=schedule, worker=worker, assigned_by=admin,
                        status='CANCELLED' if status == 'CANCELLED' else 'ACCEPTED', responded_at=created_at)
                    if not done:
                        continue
                    gross = calculate_gross_amount(schedule, booking)
                    commission = calculate_commission(gross)
                    WorkerEarning.objects.create(worker=worker, booking=booking, schedule=schedule,
                        payment_method='CASH' if cash else 'ONLINE', gross_amount=gross,
                        commission_rate=COMMISSION_RATE, commission_amount=commission, worker_amount=gross - commission,
                        completed_at=end, settled_at=(end + timedelta(minutes=30)) if cash and index % 2 == 0 else None)
                    created_earnings += 1
                    review = Review.objects.create(assignment=assignment, rating=3 + (index + si + sequence) % 3,
                        comment='Đánh giá mẫu cho báo cáo.', is_visible=index != 6)
                    Review.objects.filter(pk=review.pk).update(created_at=end + timedelta(hours=1))
                    created_reviews += 1
                created_orders += 1
        self.stdout.write(self.style.SUCCESS(f'Created orders={created_orders}, earnings={created_earnings}, reviews={created_reviews}; anchor={anchor}.'))
        self.stdout.write(f'Worker IDs: {sorted(worker_ids)}. Booking prefix: CW-RPT-. Existing wallets and orders unchanged.')
