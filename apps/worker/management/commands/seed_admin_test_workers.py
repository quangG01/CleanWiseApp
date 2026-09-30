from datetime import time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import WorkerProfile
from apps.services.models import Service
from apps.wallets.models import Wallet
from apps.worker.models import Area, WorkerAvailability, WorkerWorkingArea


WORKERS = [
    ('Nguyễn', 'Minh Anh', 'FEMALE'),
    ('Trần', 'Quốc Bảo', 'MALE'),
    ('Lê', 'Thùy Dương', 'FEMALE'),
    ('Phạm', 'Hoàng Nam', 'MALE'),
    ('Võ', 'Ngọc Hà', 'FEMALE'),
    ('Đặng', 'Tuấn Kiệt', 'MALE'),
    ('Bùi', 'Thanh Trúc', 'FEMALE'),
    ('Đỗ', 'Gia Huy', 'MALE'),
    ('Huỳnh', 'Kim Oanh', 'FEMALE'),
    ('Phan', 'Đức Long', 'MALE'),
]


class Command(BaseCommand):
    help = 'Tạo 10 nhân viên ACTIVE dùng để kiểm thử phân công từ trang admin.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        admin = User.objects.filter(role='ADMIN', is_active=True).order_by('id').first()
        service = Service.objects.filter(
            is_active=True,
            section_code='HOME_CLEANING',
        ).order_by('id').first()
        if not admin or not service:
            raise CommandError('Can co admin va dich vu HOME_CLEANING dang hoat dong.')

        area, _ = Area.objects.get_or_create(
            city='TP Hồ Chí Minh',
            name='TP Hồ Chí Minh',
            defaults={'is_active': True},
        )
        if not area.is_active:
            area.is_active = True
            area.save(update_fields=['is_active', 'updated_at'])

        created_count = 0
        updated_count = 0
        shared_password_hash = make_password('CleanWise@Test123')
        for index, (last_name, first_name, gender) in enumerate(WORKERS, start=1):
            username = f'admin_test_worker_{index:02d}'
            email = f'{username}@cleanwise.test'
            phone = f'09870000{index:02d}'
            worker, created = User.objects.get_or_create(
                username=username,
                defaults={
                    'email': email,
                    'phone_number': phone,
                    'first_name': first_name,
                    'last_name': last_name,
                    'gender': gender,
                    'role': 'WORKER',
                    'is_active': True,
                },
            )
            worker.email = email
            worker.phone_number = phone
            worker.first_name = first_name
            worker.last_name = last_name
            worker.gender = gender
            worker.role = 'WORKER'
            worker.is_active = True
            worker.password = shared_password_hash
            worker.save()

            profile = WorkerProfile.objects.filter(user=worker).first()
            if profile is None:
                # Tạo ở DRAFT để seed không phát thông báo duyệt hồ sơ qua Celery.
                profile = WorkerProfile.objects.create(
                    user=worker,
                    status=WorkerProfile.Status.DRAFT,
                    identity_number=f'CWTEST{index:06d}',
                )
            WorkerProfile.objects.filter(pk=profile.pk).update(
                status=WorkerProfile.Status.ACTIVE,
                bio='Nhân viên mẫu dùng để kiểm thử chức năng phân công admin.',
                experience_years=(index % 5) + 1,
                registered_service=service,
                approved_by=admin,
                approved_at=timezone.now(),
                average_rating=Decimal('4.50') + Decimal(index % 5) / Decimal('10'),
                total_completed_jobs=index * 7,
                rejection_reason=None,
                rejected_fields={},
            )

            WorkerWorkingArea.objects.get_or_create(worker=worker, area=area)
            Wallet.objects.update_or_create(
                user=worker,
                defaults={'balance': Decimal('2000000')},
            )
            for weekday in range(7):
                WorkerAvailability.objects.update_or_create(
                    worker=worker,
                    weekday=weekday,
                    start_time=time(0, 0),
                    defaults={'end_time': time(23, 59), 'is_active': True},
                )

            created_count += int(created)
            updated_count += int(not created)

        self.stdout.write(self.style.SUCCESS(
            f'Created {created_count}, updated {updated_count} admin test workers.'
        ))
        self.stdout.write('Usernames: admin_test_worker_01 ... admin_test_worker_10')
        self.stdout.write('Password: CleanWise@Test123')
        self.stdout.write(f'Service section: {service.section_code}; area_id: {area.id}')
