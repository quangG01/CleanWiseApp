from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.booking_service import create_booking
from apps.bookings.models import Booking
from apps.services.models import Service
from apps.wallets.models import Wallet
from apps.worker.assignment_service import list_available_workers_for_schedule
from apps.worker.models import Area, CustomerFavoriteWorker, WorkerWorkingArea

TEST_PASSWORD = 'Cards@Test123'


class Command(BaseCommand):
    help = 'Create a separate customer, two workers and five future invitation test orders in a development database.'

    def add_arguments(self, parser):
        parser.add_argument('--service-code', default='HOME_CLEANING_HOURLY')
        parser.add_argument('--area-id', type=int)
        parser.add_argument('--batch', default=timezone.localdate().strftime('%Y%m%d'))

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or settings.SETTINGS_MODULE not in ('core.settings.dev', 'core.settings.invitation_preview'):
            raise CommandError('This command only supports DEBUG development/preview settings.')
        batch = options['batch']
        if not batch.isascii() or not batch.isalnum() or len(batch) > 12:
            raise CommandError('Batch must contain 1–12 ASCII letters or digits.')
        service = Service.objects.filter(code=options['service_code'], is_active=True).first()
        if not service:
            raise CommandError('Active test service not found.')
        areas = Area.objects.filter(is_active=True)
        if options['area_id']:
            area = areas.filter(pk=options['area_id']).first()
        else:
            area = areas.filter(workers__worker__worker_profile__status='ACTIVE',
                                workers__worker__worker_profile__registered_service__section_code=service.section_code).annotate(
                candidate_count=Count('workers')).order_by('-candidate_count', 'id').first()
        if not area:
            raise CommandError('No active area found. Supply --area-id.')

        User = get_user_model()

        def test_user(username, phone, role, first_name, last_name):
            email = f'{username}@cleanwise.test'
            user, created = User.objects.get_or_create(username=username, defaults={
                'email': email, 'phone_number': phone, 'role': role,
                'first_name': first_name, 'last_name': last_name, 'is_active': True,
            })
            if not created and (user.email != email or user.phone_number != phone or user.role != role):
                raise CommandError(f'{username} is not the expected test account; no changes made.')
            if created:
                user.set_password(TEST_PASSWORD)
                user.save(update_fields=['password'])
            return user

        customer = test_user('card_test_customer', '0999000100', 'CUSTOMER', 'Khách test', 'Phân công')
        Wallet.objects.get_or_create(user=customer, defaults={'balance': Decimal('0')})
        address, _ = CustomerAddress.objects.get_or_create(customer=customer, label='Địa chỉ test phân công', defaults={
            'receiver_name': customer.get_full_name(), 'receiver_phone': customer.phone_number,
            'address_line': '01 Đường Mẫu — dữ liệu test', 'city': area.city,
            'ward': area.name if area.name != area.city else '',
            'province_code': area.province_code or '', 'ward_code': area.ward_code or '',
            'is_default': True, 'is_active': True,
        })
        test_workers = []
        for index, (first_name, last_name) in enumerate([('Nguyễn Thị', 'Mai Test'), ('Trần Minh', 'Anh Test')], start=1):
            worker = test_user(f'card_test_worker_{index:02d}', f'099900020{index}', 'WORKER', first_name, last_name)
            WorkerProfile.objects.get_or_create(user=worker, defaults={
                'status': 'ACTIVE', 'registered_service': service,
                'bio': 'Hồ sơ minh họa để kiểm tra popup phân công và phản hồi lời mời.',
                'experience_years': 2 + index, 'average_rating': Decimal('4.90') if index == 1 else Decimal('4.80'),
                'total_completed_jobs': 120 + index * 30,
            })
            WorkerWorkingArea.objects.get_or_create(worker=worker, area=area)
            Wallet.objects.get_or_create(user=worker, defaults={'balance': Decimal('2000000')})
            CustomerFavoriteWorker.objects.get_or_create(customer=customer, worker=worker)
            test_workers.append(worker)

        cases = [
            ('Gửi lời mời hàng loạt', '2_HOURS'),
            ('Nhân viên nhận việc trước', '2_HOURS'),
            ('Nhân viên từ chối lời mời', '3_HOURS'),
            ('Admin thu hồi lời mời', '2_HOURS'),
            ('Tìm kiếm và chọn nhân viên yêu thích', '3_HOURS'),
        ]
        for index, (case, duration) in enumerate(cases, start=1):
            code = f'CW-CARDS-{batch}-{index:02d}'
            booking = Booking.objects.filter(booking_code=code).first()
            if booking and booking.customer_id != customer.id:
                raise CommandError(f'Booking code collision: {code}')
            if not booking:
                service_data = {
                    'date': (timezone.localdate() + timedelta(days=index + 1)).isoformat(),
                    'start_time': '08:00', 'duration': duration, 'additional_services': [],
                }
                booking = create_booking(customer=customer, service_id=service.id, address_id=address.id,
                                         service_data=service_data, payment_method='CASH', note=f'[TEST THẺ NHÂN VIÊN] {case}')
                # Give fixture orders recognizable stable codes. No external bank reference is used for CASH.
                booking.booking_code = code
                booking.save(update_fields=['booking_code'])
            schedule = booking.schedules.first()
            candidates = list_available_workers_for_schedule(schedule_id=schedule.id) if schedule.status == 'PENDING' and schedule.scheduled_start > timezone.now() else []
            if not candidates and not schedule.assignments.filter(status='ACCEPTED').exists():
                raise CommandError(f'No eligible workers for {code}; seed rolled back.')
            self.stdout.write(f'{code} | booking_id={booking.id} | schedule_id={schedule.id} | eligible_workers={len(candidates)}')

        self.stdout.write(f'Customer: {customer.username} / {customer.phone_number}')
        self.stdout.write('Workers: ' + ', '.join(f'{worker.username} / {worker.phone_number}' for worker in test_workers))
        self.stdout.write(f'New test account password: {TEST_PASSWORD}')
        self.stdout.write('No invitations sent. Existing test passwords and booking states are preserved on repeat runs.')
