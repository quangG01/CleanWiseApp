"""Fixtures for the three admin worker tabs, isolated from existing test accounts."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile
from apps.bookings.booking_service import create_booking
from apps.bookings.models import Booking
from apps.services.models import Service
from apps.wallets.models import Wallet
from apps.worker.assignment_service import list_available_workers_for_schedule
from apps.worker.models import Area, BookingAssignment, CustomerFavoriteWorker, WorkerWorkingArea


class Command(BaseCommand):
    help = 'Seed six future orders for suitable/favorite/requested worker tabs without sending invitations.'

    def add_arguments(self, parser):
        parser.add_argument('--area-id', type=int, required=True)
        parser.add_argument('--batch', default=timezone.localdate().strftime('%Y%m%d'))

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEBUG or settings.SETTINGS_MODULE not in ('core.settings.dev', 'core.settings.invitation_preview'):
            raise CommandError('Only DEBUG development/preview settings are supported.')
        batch = options['batch']
        if not batch or not batch.isascii() or not batch.isalnum() or len(batch) > 10:
            raise CommandError('Batch must contain 1–10 ASCII letters or digits.')
        service = Service.objects.filter(code='HOME_CLEANING_HOURLY', is_active=True).first()
        area = Area.objects.filter(id=options['area_id'], is_active=True).first()
        if not service or not area:
            raise CommandError('Active hourly cleaning service and area are required.')
        User = get_user_model()

        def account(username, phone, role, name):
            email = f'{username}@cleanwise.test'
            user, created = User.objects.get_or_create(username=username, defaults={
                'email': email, 'phone_number': phone, 'role': role, 'first_name': name,
                'is_active': True,
            })
            if (user.email, user.phone_number, user.role) != (email, phone, role):
                raise CommandError(f'Unexpected existing account: {username}')
            if created:
                user.set_password('Tabs@Test123')
                user.save(update_fields=['password'])
            return user

        customer = account('tabs_test_customer', '0999000300', 'CUSTOMER', 'Khách test ba tab')
        Wallet.objects.get_or_create(user=customer, defaults={'balance': 0})
        address, _ = CustomerAddress.objects.get_or_create(customer=customer, label='Test ba tab nhân viên', defaults={
            'receiver_name': customer.get_full_name(), 'receiver_phone': customer.phone_number,
            'address_line': '02 Đường Mẫu — test ba tab nhân viên', 'city': area.city,
            'ward': area.name, 'province_code': area.province_code or '', 'ward_code': area.ward_code or '',
            'is_active': True, 'is_default': True,
        })
        cases = [
            ('Mai Test — Phù hợp', None),
            ('Anh Test — Trùng lịch', 'Trùng lịch'),
            ('Hà Test — Thiếu số dư', 'Không đủ số dư'),
            ('Lan Test — Ngoài khu vực', 'Ngoài khu vực'),
            ('Nam Test — Khác dịch vụ', 'Không phù hợp dịch vụ'),
            ('Linh Test — Chưa duyệt', 'Hồ sơ chưa được duyệt'),
            ('Bảo Test — Phù hợp', None),
        ]
        other_service, _ = Service.objects.get_or_create(code='TABS_TEST_OTHER_SERVICE', defaults={
            'section_code': 'TABS_TEST_OTHER', 'name': 'Dịch vụ khác — fixture ba tab',
            'description': 'Chỉ phục vụ hồ sơ test, không mở bán.', 'is_active': False,
            'form_schema': {'fields': []}, 'pricing_config': {},
        })
        workers = []
        for index, (name, reason) in enumerate(cases, start=1):
            worker = account(f'tabs_test_worker_{index:02d}', f'099900030{index}', 'WORKER', name)
            profile_data = {
                'status': 'PENDING' if index == 6 else 'ACTIVE',
                'registered_service': other_service if index == 5 else service,
                'bio': f'[TEST BA TAB] {reason or "Có thể nhận ca"}.',
                'experience_years': 3, 'average_rating': Decimal('4.80'), 'total_completed_jobs': 35,
            }
            if not WorkerProfile.objects.filter(user=worker).exists():
                # Fixture inserts bypass review notifications to real administrators.
                WorkerProfile.objects.bulk_create([WorkerProfile(user=worker, **profile_data)])
            if index != 4:
                WorkerWorkingArea.objects.get_or_create(worker=worker, area=area)
            Wallet.objects.get_or_create(user=worker, defaults={'balance': 0 if index == 3 else Decimal('2000000')})
            if index <= 6:
                CustomerFavoriteWorker.objects.get_or_create(customer=customer, worker=worker)
            workers.append(worker)

        def order(code, day, note):
            booking = Booking.objects.filter(booking_code=code).first()
            if booking and booking.customer_id != customer.id:
                raise CommandError(f'Booking code collision: {code}')
            created = booking is None
            if created:
                booking = create_booking(customer=customer, service_id=service.id, address_id=address.id,
                    service_data={'date': day.isoformat(), 'start_time': '08:00', 'duration': '2_HOURS', 'additional_services': []},
                    payment_method='CASH', note=f'[TEST BA TAB] {note}')
                booking.booking_code = code
                booking.save(update_fields=['booking_code'])
            return booking, created

        output = []
        for index, (name, reason) in enumerate(cases[:6], start=1):
            day = timezone.localdate() + timedelta(days=index + 1)
            booking, created = order(f'CW-TABS-{batch}-{index:02d}', day,
                f'Khách yêu cầu {name}. Yêu cầu ưu tiên cũ đã hết hạn để admin mở popup phân công.')
            schedule = booking.schedules.get()
            if created:
                # Model a historical customer selection after its priority window expired.
                # This deliberately avoids creating notifications or live invitations.
                schedule.preferred_worker = workers[index - 1]
                schedule.preferred_worker_expires_at = timezone.now() - timedelta(minutes=1)
                schedule.save(update_fields=['preferred_worker', 'preferred_worker_expires_at'])
            if index == 2:
                conflict, conflict_created = order(f'CW-TABS-{batch}-BUSY', timezone.localdate(schedule.scheduled_start),
                    'Ca đã nhận để mô phỏng trùng lịch với đơn -02. Không dùng để gửi lời mời.')
                if conflict_created:
                    assignment = BookingAssignment(schedule=conflict.schedules.get(), worker=workers[1],
                        status='ACCEPTED', responded_at=timezone.now(), response_note='Fixture ca trùng lịch')
                    assignment._skip_assignment_notify = True
                    assignment.save()
                    conflict.status = Booking.Status.ASSIGNED
                    conflict.save(update_fields=['status'])
            if created:
                requested = list_available_workers_for_schedule(schedule_id=schedule.id, group='requested')
                if len(requested) != 1 or requested[0].unavailable_reasons != ([reason] if reason else []):
                    raise CommandError(f'Unexpected eligibility for {booking.booking_code}; rolled back.')
            output.append(f'{booking.booking_code} | id={booking.id} | schedule={schedule.id} | {reason or "Có thể nhận ca"}')
        for line in output:
            self.stdout.write(line)
        self.stdout.write('Customer: 0999000300; workers: 0999000301–0999000307; new account password: Tabs@Test123')
        self.stdout.write('No invitations/notifications sent. Existing passwords, balances and order states preserved on repeat.')
