from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.bookings.models import Booking, BookingSchedule, BookingActivity
from apps.payments.models import Payment
from apps.worker.models import BookingAssignment, WorkerAvailability

VIETNAM = ZoneInfo('Asia/Ho_Chi_Minh')


class Command(BaseCommand):
    help = 'Thêm lịch tuần mẫu trên tài khoản hiện có; không sửa đơn hoặc khung giờ đã có. Chạy lại không tạo trùng.'

    def add_arguments(self, parser):
        parser.add_argument('--week', help='Ngày bất kỳ trong tuần cần tạo, YYYY-MM-DD (mặc định tuần hiện tại).')
        parser.add_argument('--worker-id', type=int, help='ID tài khoản nhân viên; mặc định ba nhân viên ACTIVE đầu tiên.')

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        today = timezone.localdate(timezone=VIETNAM)
        if options['week']:
            try:
                today = datetime.strptime(options['week'], '%Y-%m-%d').date()
            except ValueError:
                raise CommandError('--week phải có định dạng YYYY-MM-DD.')
        monday = today - timedelta(days=today.weekday())
        workers = User.objects.filter(role='WORKER', is_active=True, worker_profile__status='ACTIVE',
                                      worker_profile__registered_service__is_active=True).select_related('worker_profile__registered_service').order_by('id')
        if options['worker_id']:
            workers = workers.filter(id=options['worker_id'])
        workers = list(workers[:3])
        customers = list(User.objects.filter(role='CUSTOMER', is_active=True).order_by('id')[:3])
        admin = User.objects.filter(role='ADMIN', is_active=True).order_by('id').first()
        if not workers or not customers or not admin:
            raise CommandError('Cần nhân viên ACTIVE có dịch vụ, khách hàng và admin trong DB.')
        created = 0
        for wi, worker in enumerate(workers):
            customer = customers[wi % len(customers)]
            address = CustomerAddress.objects.filter(customer=customer, is_active=True).first()
            if not address:
                address = CustomerAddress.objects.create(customer=customer, label='Địa chỉ test lịch tuần',
                    receiver_name=customer.get_full_name() or customer.username,
                    receiver_phone=customer.phone_number or '0900000000',
                    address_line='123 Nguyễn Huệ', ward='Bến Nghé', city='TP Hồ Chí Minh')
            service = worker.worker_profile.registered_service
            if not WorkerAvailability.objects.filter(worker=worker, is_active=True).exists():
                WorkerAvailability.objects.bulk_create([
                    WorkerAvailability(worker=worker, weekday=day, start_time=time(7), end_time=time(18))
                    for day in range(6)
                ])
            for offset in (0, 7):
                week = monday + timedelta(days=offset)
                # Include pending overlap and a midnight crossing to exercise the weekly layout.
                specs = [(0, 8, 2, 'ACCEPTED'), (1, 13, 3, 'ACCEPTED'),
                         (2, 9, 2, 'PENDING'), (2, 10, 2, 'PENDING'),
                         (4, 15, 2, 'ACCEPTED'), (6, 23, 2, 'ACCEPTED')]
                for index, (day, hour, hours, assignment_status) in enumerate(specs):
                    code = f'CW-WK-{worker.id}-{week:%y%m%d}-{index}'
                    start = datetime.combine(week + timedelta(days=day), time(hour), tzinfo=VIETNAM)
                    end = start + timedelta(hours=hours)
                    completed = end < timezone.now() and assignment_status == 'ACCEPTED'
                    schedule_status = 'COMPLETED' if completed else 'PENDING'
                    booking, new = Booking.objects.get_or_create(booking_code=code, defaults={
                        'customer': customer, 'service': service, 'address': address,
                        'service_data': {'date': start.date().isoformat(), 'start_time': f'{hour:02}:00', 'duration': f'{hours}_HOURS'},
                        'note': 'Dữ liệu mẫu kiểm thử lịch tuần nhân viên.',
                        'status': 'COMPLETED' if completed else ('ASSIGNED' if assignment_status == 'ACCEPTED' else 'PENDING'),
                        'payment_status': 'PAID', 'subtotal_amount': Decimal('300000'),
                        'total_amount': Decimal('300000'), 'price_breakdown': {'description': 'Dữ liệu mẫu lịch tuần'},
                    })
                    if not new:
                        continue
                    schedule = BookingSchedule.objects.create(booking=booking, sequence_no=1,
                        scheduled_start=start, scheduled_end=end, status=schedule_status,
                        actual_start=start if completed else None, actual_end=end if completed else None,
                        completion_note='Đã hoàn thành (dữ liệu mẫu).' if completed else None,
                        note='Buổi test lịch tuần; các buổi chờ xác nhận có thể trùng giờ.')
                    BookingAssignment.objects.create(schedule=schedule, worker=worker, assigned_by=admin,
                        status=assignment_status, responded_at=timezone.now() if assignment_status == 'ACCEPTED' else None)
                    Payment.objects.create(booking=booking, customer=customer, amount=Decimal('300000'),
                        method='BANK_TRANSFER', status='SUCCESS', transaction_code=f'DEMO-{code}', paid_at=timezone.now())
                    BookingActivity.objects.create(booking=booking, schedule=schedule, actor=admin,
                        event_type='WORKER_ASSIGNED', message='Phân công mẫu để kiểm thử lịch tuần.', metadata={'seed': 'worker_schedule_demo'})
                    created += 1
            self.stdout.write(f'worker_id={worker.id} | {worker.get_full_name() or worker.username} | username={worker.username}')
        self.stdout.write(self.style.SUCCESS(f'Created {created} demo bookings; weeks {monday} and {monday + timedelta(days=7)}.'))
