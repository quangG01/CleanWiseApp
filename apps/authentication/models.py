from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.crypto import constant_time_compare, salted_hmac
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


class PasswordResetOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_otps')
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(blank=True, null=True)
    used_at = models.DateTimeField(blank=True, null=True)
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'password_reset_otps'
        ordering = ['-created_at']

    @staticmethod
    def make_code_hash(code):
        return salted_hmac('authentication.password_reset_otp', code).hexdigest()

    def check_code(self, code):
        return constant_time_compare(self.code_hash, self.make_code_hash(code))

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at

    @property
    def is_used(self):
        return self.used_at is not None

    @property
    def is_verified(self):
        return self.verified_at is not None

    def mark_verified(self):
        self.verified_at = timezone.now()
        self.save(update_fields=['verified_at'])

    def mark_used(self):
        self.used_at = timezone.now()
        self.save(update_fields=['used_at'])


class WorkerProfile(models.Model):
    class Gender(models.TextChoices):
        MALE = 'MALE', 'Nam'
        FEMALE = 'FEMALE', 'Nữ'
        OTHER = 'OTHER', 'Khác'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Đang hoàn thiện hồ sơ'
        PENDING = 'PENDING', 'Chờ duyệt'
        ACTIVE = 'ACTIVE', 'Đang hoạt động'
        REJECTED = 'REJECTED', 'Bị từ chối'
        SUSPENDED = 'SUSPENDED', 'Tạm khóa'

    user = models.OneToOneField(User, on_delete=models.DO_NOTHING, related_name='worker_profile')
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    full_name = models.CharField(max_length=150, blank=True, null=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, blank=True, null=True)
    birth_date = models.DateField(blank=True, null=True)
    bio = models.TextField(blank=True, null=True)
    experience_years = models.IntegerField(default=0)
    identity_number = models.CharField(max_length=30, unique=True, blank=True, null=True)
    identity_issued_date = models.DateField(blank=True, null=True)
    identity_issued_place = models.CharField(max_length=255, blank=True, null=True)
    avatar = models.CharField(max_length=255, blank=True, null=True)
    province = models.CharField(max_length=100, blank=True, null=True)
    ward = models.CharField(max_length=100, blank=True, null=True)
    address_line = models.TextField(blank=True, null=True)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    certificate_number = models.CharField(max_length=100, blank=True, null=True)
    certificate_expiry_date = models.DateField(blank=True, null=True)
    bank_code = models.CharField(max_length=50, blank=True, null=True)
    bank_account_number_encrypted = models.TextField(blank=True, null=True)
    bank_account_last4 = models.CharField(max_length=4, blank=True, null=True)
    bank_account_holder = models.CharField(max_length=150, blank=True, null=True)
    terms_accepted_at = models.DateTimeField(blank=True, null=True)
    submitted_at = models.DateTimeField(blank=True, null=True)
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
