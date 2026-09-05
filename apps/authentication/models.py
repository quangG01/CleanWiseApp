from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Quản trị viên'
        CUSTOMER = 'CUSTOMER', 'Khách hàng'
        WORKER = 'WORKER', 'Nhân viên vệ sinh'

    role = models.CharField(
        max_length=20, 
        choices=Role.choices, 
        default=Role.CUSTOMER
    )
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, unique=True, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'users'

    def __str__(self):
        return f"{self.username} ({self.role})"


class CustomerProfile(models.Model):
    class Gender(models.TextChoices):
        MALE = 'MALE', 'Nam'
        FEMALE = 'FEMALE', 'Nữ'
        OTHER = 'OTHER', 'Khác'

    user = models.OneToOneField(User, on_delete=models.DO_NOTHING, related_name='customer_profile')
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    avatar = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_profiles'

    def __str__(self):
        return f"Hồ sơ khách hàng: {self.user}"


class WorkerProfile(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ duyệt'
        ACTIVE = 'ACTIVE', 'Đang hoạt động'
        REJECTED = 'REJECTED', 'Bị từ chối'
        SUSPENDED = 'SUSPENDED', 'Tạm khóa'

    user = models.OneToOneField(User, on_delete=models.DO_NOTHING, related_name='worker_profile')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    bio = models.TextField(blank=True, null=True)
    experience_years = models.IntegerField(default=0)
    identity_number = models.CharField(max_length=30, unique=True, blank=True, null=True)
    avatar = models.CharField(max_length=255, blank=True, null=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.DO_NOTHING,
        related_name='approved_worker_profiles',
        blank=True,
        null=True
    )
    approved_at = models.DateTimeField(blank=True, null=True)
    rejection_reason = models.TextField(blank=True, null=True)
    average_rating = models.DecimalField(max_digits=3, decimal_places=2, default=0)
    total_completed_jobs = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'worker_profiles'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(experience_years__gte=0),
                name='worker_profiles_experience_years_check'
            ),
            models.CheckConstraint(
                condition=models.Q(average_rating__gte=0) & models.Q(average_rating__lte=5),
                name='worker_profiles_average_rating_check'
            ),
            models.CheckConstraint(
                condition=models.Q(total_completed_jobs__gte=0),
                name='worker_profiles_total_completed_jobs_check'
            ),
        ]

    def __str__(self):
        return f"Hồ sơ nhân viên: {self.user}"


class WorkerVerificationDocument(models.Model):
    class DocumentType(models.TextChoices):
        IDENTITY_FRONT = 'IDENTITY_FRONT', 'CCCD/CMND mặt trước'
        IDENTITY_BACK = 'IDENTITY_BACK', 'CCCD/CMND mặt sau'
        CERTIFICATE = 'CERTIFICATE', 'Chứng chỉ'
        BACKGROUND_CHECK = 'BACKGROUND_CHECK', 'Xác minh lý lịch'
        OTHER = 'OTHER', 'Khác'

    class FileType(models.TextChoices):
        IMAGE = 'IMAGE', 'Hình ảnh'
        PDF = 'PDF', 'PDF'
        OTHER = 'OTHER', 'Khác'

    worker = models.ForeignKey(User, on_delete=models.DO_NOTHING, related_name='verification_documents')
    document_type = models.CharField(max_length=30, choices=DocumentType.choices, default=DocumentType.OTHER)
    file = models.CharField(max_length=255)
    file_type = models.CharField(max_length=30, choices=FileType.choices, default=FileType.OTHER)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'worker_verification_documents'

    def __str__(self):
        return f"{self.worker} - {self.document_type}"
