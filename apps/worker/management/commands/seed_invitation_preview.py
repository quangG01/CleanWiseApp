from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.addresses.models import CustomerAddress
from apps.authentication.models import WorkerProfile, WorkerVerificationDocument
from apps.bookings.models import Booking, BookingSchedule
from apps.payments.models import Payment
from apps.services.models import Service
from apps.wallets.models import Wallet
from apps.worker.invitation_service import send_invitation
from apps.worker.models import Area, BookingAssignment, CustomerFavoriteWorker, WorkerWorkingArea


class Command(BaseCommand):
    help = 'Seed isolated local invitation preview accounts and bookings.'

    @transaction.atomic
    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE != 'core.settings.invitation_preview':
            raise CommandError('Chỉ chạy với --settings=core.settings.invitation_preview.')
        User = get_user_model()
        users = {}
        for role, name in [('ADMIN', 'admin'), ('CUSTOMER', 'customer'), ('WORKER', 'worker')]:
            user, created = User.objects.get_or_create(username=f'preview-{name}', defaults={
                'email': f'{name}@cleanwise.test', 'role': role,
                'first_name': 'Preview', 'last_name': name, 'phone_number': f'090000000{len(users) + 1}',
                'gender': 'FEMALE', 'birth_date': date(1995, 1, 1),
            })
            if created:
                user.set_password('Invitation@Test123')
                user.save()
            users[name] = user
        service, _ = Service.objects.get_or_create(code='INVITATION_PREVIEW', defaults={
            'name': 'Dọn nhà — xem thử lời mời', 'section_code': 'HOME_CLEANING',
            'description': 'Dịch vụ mẫu', 'is_active': True,
            'form_schema': {'fields': []}, 'pricing_config': {'base_prices': {'2_HOURS': 150000}},
        })
        worker = users['worker']
        WorkerProfile.objects.get_or_create(user=worker, defaults={
            'status': 'ACTIVE', 'registered_service': service,
            'approved_by': users['admin'], 'approved_at': timezone.now(),
            'average_rating': Decimal('4.90'), 'total_completed_jobs': 20,
            'identity_number': 'PREVIEW-WORKER', 'avatar': '/media/preview-avatar.png',
        })
        area, _ = Area.objects.get_or_create(ward_code='PREVIEW', defaults={'province_code': '79', 'name': 'Phường mẫu', 'city': 'TP.HCM'})
        WorkerWorkingArea.objects.get_or_create(worker=worker, area=area)
        for kind in ['IDENTITY_FRONT', 'IDENTITY_BACK']:
            WorkerVerificationDocument.objects.get_or_create(worker=worker, document_type=kind, defaults={'file': '/media/preview-document.png', 'file_type': 'IMAGE'})
        Wallet.objects.get_or_create(user=worker, defaults={'balance': Decimal('2000000')})
        CustomerFavoriteWorker.objects.get_or_create(customer=users['customer'], worker=worker)
        # Enough local demo candidates to exercise pagination and bulk selection.
        for index in range(2, 15):
            candidate, created = User.objects.get_or_create(username=f'preview-worker-{index}', defaults={
                'email': f'worker-{index}@cleanwise.test', 'role': 'WORKER',
                'first_name': 'Nhân viên mẫu', 'last_name': str(index),
                'phone_number': f'09000001{index:02d}',
            })
            if created:
                candidate.set_password('Invitation@Test123')
                candidate.save()
            WorkerProfile.objects.get_or_create(user=candidate, defaults={
                'status': 'ACTIVE', 'registered_service': service,
                'average_rating': Decimal('4.80'), 'total_completed_jobs': index,
            })
            WorkerWorkingArea.objects.get_or_create(worker=candidate, area=area)
            Wallet.objects.get_or_create(user=candidate, defaults={'balance': Decimal('2000000')})

        address, _ = CustomerAddress.objects.get_or_create(customer=users['customer'], address_line='01 Đường mẫu', defaults={
            'city': 'TP.HCM', 'ward': 'Phường mẫu', 'receiver_name': 'Khách mẫu', 'receiver_phone': '0900000002',
        })
        for index, state in enumerate(['OPEN', 'WAITING', 'EXPIRED'], start=1):
            booking, created = Booking.objects.get_or_create(booking_code=f'CW-INVITE-{state}', defaults={
                'customer': users['customer'], 'service': service, 'address': address,
                'service_data': {}, 'total_amount': 150000, 'subtotal_amount': 150000,
                'payment_status': 'UNPAID', 'note': f'Đơn mẫu: {state}',
            })
            if not created:
                continue
            start = timezone.now() + timedelta(days=index)
            schedule = BookingSchedule.objects.create(booking=booking, sequence_no=1, scheduled_start=start, scheduled_end=start + timedelta(hours=2))
            Payment.objects.create(booking=booking, customer=users['customer'], amount=150000, method='CASH', status='PENDING')
            if state == 'WAITING':
                send_invitation(schedule_id=schedule.id, worker_id=worker.id, admin_user=users['admin'], response_minutes=60)
            elif state == 'EXPIRED':
                BookingAssignment.objects.create(schedule=schedule, worker=worker, assigned_by=users['admin'], status='EXPIRED', expired_at=timezone.now() - timedelta(minutes=1))
        self.stdout.write('Preview accounts: admin username preview-admin / worker phone 0900000003')
        self.stdout.write('Preview password: Invitation@Test123')
