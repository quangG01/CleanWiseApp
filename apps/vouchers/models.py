from django.conf import settings
from django.db import models


class Voucher(models.Model):
    class DiscountType(models.TextChoices):
        PERCENT = 'PERCENT', 'Phần trăm'
        FIXED = 'FIXED', 'Số tiền cố định'

    class DistributionType(models.TextChoices):
        PUBLIC = 'PUBLIC', 'Công khai'
        CODE_ONLY = 'CODE_ONLY', 'Chỉ nhận bằng mã'
        ASSIGNED = 'ASSIGNED', 'Được cấp riêng'

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True)
    distribution_type = models.CharField(max_length=20, choices=DistributionType.choices, default=DistributionType.CODE_ONLY)
    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)
    max_discount_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    min_order_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    issuance_limit = models.IntegerField(blank=True, null=True)
    issued_count = models.IntegerField(default=0)
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'vouchers'
        constraints = [
            models.CheckConstraint(condition=models.Q(discount_value__gt=0), name='vouchers_discount_value_check'),
            models.CheckConstraint(condition=models.Q(min_order_amount__gte=0), name='vouchers_min_order_amount_check'),
            models.CheckConstraint(condition=models.Q(issued_count__gte=0), name='vouchers_issued_count_check'),
            models.CheckConstraint(condition=models.Q(issuance_limit__isnull=True) | models.Q(issuance_limit__gt=0), name='vouchers_issuance_limit_check'),
            models.CheckConstraint(condition=models.Q(issuance_limit__isnull=True) | models.Q(issued_count__lte=models.F('issuance_limit')), name='vouchers_issued_within_limit_check'),
            models.CheckConstraint(condition=models.Q(discount_type='FIXED') | models.Q(discount_value__lte=100), name='vouchers_percent_value_check'),
            models.CheckConstraint(condition=models.Q(max_discount_amount__isnull=True) | models.Q(max_discount_amount__gt=0), name='vouchers_max_discount_amount_check'),
            models.CheckConstraint(condition=models.Q(discount_type='PERCENT') | models.Q(max_discount_amount__isnull=True), name='vouchers_fixed_max_discount_null_check'),
            models.CheckConstraint(condition=models.Q(start_at__lt=models.F('end_at')), name='vouchers_time_check'),
        ]

    def __str__(self):
        return self.code


class UserVoucher(models.Model):
    class Source(models.TextChoices):
        ADMIN = 'ADMIN', 'Quản trị viên cấp'
        CODE = 'CODE', 'Nhận bằng mã'
        PUBLIC = 'PUBLIC', 'Tự nhận công khai'
        CAMPAIGN = 'CAMPAIGN', 'Chiến dịch tự động'

    class Status(models.TextChoices):
        AVAILABLE = 'AVAILABLE', 'Có thể sử dụng'
        RESERVED = 'RESERVED', 'Đang được giữ'
        USED = 'USED', 'Đã sử dụng'
        REVOKED = 'REVOKED', 'Đã thu hồi'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='user_vouchers')
    voucher = models.ForeignKey(Voucher, on_delete=models.DO_NOTHING, related_name='user_vouchers')
    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    assigned_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='assigned_user_vouchers', blank=True, null=True)
    reserved_at = models.DateTimeField(blank=True, null=True)
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_vouchers'
        constraints = [models.UniqueConstraint(fields=['user', 'voucher'], name='user_vouchers_user_voucher_unique')]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.voucher}"
