from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.authentication.models import WorkerProfile, WorkerVerificationDocument
from apps.services.models import Service
from apps.worker.models import Area, WorkerWorkingArea


WORKERS = [
    ('Lê', 'Hải Yến', 'FEMALE', WorkerProfile.Status.DRAFT),
    ('Nguyễn', 'Thành Đạt', 'MALE', WorkerProfile.Status.DRAFT),
    ('Trần', 'Ngọc Mai', 'FEMALE', WorkerProfile.Status.PENDING),
    ('Phạm', 'Minh Khang', 'MALE', WorkerProfile.Status.PENDING),
    ('Võ', 'Thanh Hương', 'FEMALE', WorkerProfile.Status.PENDING),
    ('Đặng', 'Quốc Việt', 'MALE', WorkerProfile.Status.ACTIVE),
    ('Bùi', 'Khánh Linh', 'FEMALE', WorkerProfile.Status.ACTIVE),
    ('Đỗ', 'Anh Tuấn', 'MALE', WorkerProfile.Status.REJECTED),
    ('Huỳnh', 'Thu Trang', 'FEMALE', WorkerProfile.Status.REJECTED),
    ('Phan', 'Hoàng Long', 'MALE', WorkerProfile.Status.SUSPENDED),
]

DEMO_IMAGE = 'https://res.cloudinary.com/demo/image/upload/sample.jpg'


class Command(BaseCommand):
    help = 'Tạo 10 hồ sơ nhân viên ở đủ trạng thái để kiểm thử trang quản trị.'

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        admin = User.objects.filter(role=User.Role.ADMIN, is_active=True).order_by('id').first()
        service = Service.objects.filter(is_active=True).order_by('id').first()
        if not admin or not service:
            raise CommandError('Cần có ít nhất một admin và một dịch vụ đang hoạt động.')

        area, _ = Area.objects.get_or_create(
            city='TP Hồ Chí Minh',
            name='Quận 1',
            defaults={'is_active': True},
        )
        if not area.is_active:
            area.is_active = True
            area.save(update_fields=['is_active', 'updated_at'])

        password_hash = make_password('CleanWise@Test123')
        usernames = [f'admin_profile_worker_{index:02d}' for index in range(1, len(WORKERS) + 1)]
        status_counts = {status: 0 for status, _ in WorkerProfile.Status.choices}
        existing_users = {
            user.username: user
            for user in User.objects.filter(username__in=usernames)
        }
        new_users = []

        for index, (last_name, first_name, gender, _) in enumerate(WORKERS, start=1):
            username = f'admin_profile_worker_{index:02d}'
            if username not in existing_users:
                new_users.append(User(
                    username=username,
                    email=f'{username}@cleanwise.test',
                    phone_number=f'09760000{index:02d}',
                    first_name=first_name,
                    last_name=last_name,
                    gender=gender,
                    birth_date=date(1987 + index, 6, 15),
                    role=User.Role.WORKER,
                    is_active=True,
                    password=password_hash,
                ))
        User.objects.bulk_create(new_users)

        workers = list(User.objects.filter(username__in=usernames).order_by('username'))
        worker_by_username = {worker.username: worker for worker in workers}

        for index, (last_name, first_name, gender, profile_status) in enumerate(WORKERS, start=1):
            username = f'admin_profile_worker_{index:02d}'
            worker = worker_by_username[username]
            worker.email = f'{username}@cleanwise.test'
            worker.phone_number = f'09760000{index:02d}'
            worker.first_name = first_name
            worker.last_name = last_name
            worker.gender = gender
            worker.birth_date = date(1987 + index, 6, 15)
            worker.role = User.Role.WORKER
            worker.is_active = True
            worker.password = password_hash
        User.objects.bulk_update(
            workers,
            ['email', 'phone_number', 'first_name', 'last_name', 'gender', 'birth_date', 'role', 'is_active', 'password'],
        )

        existing_profile_user_ids = set(
            WorkerProfile.objects.filter(user_id__in=[worker.id for worker in workers])
            .values_list('user_id', flat=True)
        )
        WorkerProfile.objects.bulk_create([
            WorkerProfile(user=worker)
            for worker in workers
            if worker.id not in existing_profile_user_ids
        ])
        profiles = list(WorkerProfile.objects.filter(user_id__in=[worker.id for worker in workers]))
        profile_by_user_id = {profile.user_id: profile for profile in profiles}

        for index, (_, first_name, _, profile_status) in enumerate(WORKERS, start=1):
            worker = worker_by_username[f'admin_profile_worker_{index:02d}']
            profile = profile_by_user_id[worker.id]
            is_draft = profile_status == WorkerProfile.Status.DRAFT
            is_rejected = profile_status == WorkerProfile.Status.REJECTED
            is_suspended = profile_status == WorkerProfile.Status.SUSPENDED
            rejection_reason = None
            rejected_fields = {}
            if is_rejected:
                rejection_reason = 'Ảnh chân dung chưa rõ khuôn mặt và thông tin giới thiệu còn quá ngắn.'
                rejected_fields = {
                    'portrait': 'Ảnh chân dung chưa rõ khuôn mặt.',
                    'bio': 'Vui lòng mô tả kinh nghiệm chi tiết hơn.',
                }
            elif is_suspended:
                rejection_reason = 'Tạm khóa hồ sơ để xác minh phản ánh về việc nhận lịch.'

            profile.status = profile_status
            profile.bio = None if is_draft else f'{first_name} có kinh nghiệm vệ sinh nhà ở và phục vụ khách hàng.'
            profile.experience_years = 0 if is_draft else (index % 5) + 1
            profile.identity_number = None if is_draft else f'07900000{index:04d}'
            profile.avatar = None if is_draft else DEMO_IMAGE
            profile.registered_service = None if is_draft else service
            profile.approved_by = admin if profile_status == WorkerProfile.Status.ACTIVE else None
            profile.approved_at = timezone.now() if profile_status == WorkerProfile.Status.ACTIVE else None
            profile.rejection_reason = rejection_reason
            profile.rejected_fields = rejected_fields
            profile.average_rating = Decimal('4.20') + Decimal(index % 7) / Decimal('10')
            profile.total_completed_jobs = index * 4
            status_counts[profile_status] += 1

        WorkerProfile.objects.bulk_update(
            profiles,
            [
                'status', 'bio', 'experience_years', 'identity_number', 'avatar',
                'registered_service', 'approved_by', 'approved_at',
                'rejection_reason', 'rejected_fields', 'average_rating',
                'total_completed_jobs',
            ],
        )

        complete_workers = [
            worker_by_username[f'admin_profile_worker_{index:02d}']
            for index, (_, _, _, profile_status) in enumerate(WORKERS, start=1)
            if profile_status != WorkerProfile.Status.DRAFT
        ]
        WorkerWorkingArea.objects.bulk_create(
            [WorkerWorkingArea(worker=worker, area=area) for worker in complete_workers],
            ignore_conflicts=True,
        )
        WorkerVerificationDocument.objects.filter(
            worker__username__in=usernames,
            document_type__in=[
                WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
                WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
            ],
        ).delete()
        WorkerVerificationDocument.objects.bulk_create([
            WorkerVerificationDocument(
                worker=worker,
                document_type=document_type,
                file=DEMO_IMAGE,
                file_type=WorkerVerificationDocument.FileType.IMAGE,
                note='Tài liệu mẫu dùng cho kiểm thử admin.',
            )
            for worker in complete_workers
            for document_type in (
                WorkerVerificationDocument.DocumentType.IDENTITY_FRONT,
                WorkerVerificationDocument.DocumentType.IDENTITY_BACK,
            )
        ])

        summary = ', '.join(f'{status}: {count}' for status, count in status_counts.items() if count)
        self.stdout.write(self.style.SUCCESS(
            f'Created {len(new_users)}, updated {len(workers) - len(new_users)} demo workers. {summary}'
        ))
        self.stdout.write('Usernames: admin_profile_worker_01 ... admin_profile_worker_10')
        self.stdout.write('Shared password: CleanWise@Test123')
