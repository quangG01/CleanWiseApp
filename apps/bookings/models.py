from django.conf import settings
from django.db import models


class Area(models.Model):
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'areas'
        constraints = [
            models.UniqueConstraint(
                fields=['city', 'name'],
                name='areas_city_name_unique',
            ),
        ]
        ordering = ['city', 'name']

    def __str__(self):
        return f"{self.name}, {self.city}"


class CustomerAddress(models.Model):
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='addresses')
    label = models.CharField(max_length=100, default='Dia chi')
    receiver_name = models.CharField(max_length=150)
    receiver_phone = models.CharField(max_length=15)
    address_line = models.TextField()
    ward = models.CharField(max_length=100, blank=True, null=True)
    city = models.CharField(max_length=100)
    latitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=7, blank=True, null=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'customer_addresses'
        ordering = ['-is_default', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['customer'],
                condition=models.Q(is_default=True, is_active=True),
                name='customer_addresses_one_active_default',
            ),
        ]

    def __str__(self):
        return f"{self.label} - {self.receiver_name}"


class WorkerWorkingArea(models.Model):
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='working_areas')
    area = models.ForeignKey(Area, on_delete=models.DO_NOTHING, related_name='workers')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'worker_working_areas'
        constraints = [
            models.UniqueConstraint(fields=['worker', 'area'], name='worker_working_areas_worker_area_unique'),
        ]

    def __str__(self):
        return f"{self.worker} - {self.area}"


class WorkerAvailability(models.Model):
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='availabilities')
    weekday = models.IntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'worker_availability'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(weekday__gte=0) & models.Q(weekday__lte=6),
                name='worker_availability_weekday_check',
            ),
            models.CheckConstraint(
                condition=models.Q(start_time__lt=models.F('end_time')),
                name='worker_availability_time_check',
            ),
        ]
        ordering = ['worker_id', 'weekday', 'start_time']

    def __str__(self):
        return f"{self.worker} - {self.weekday} {self.start_time}-{self.end_time}"


class Booking(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        WAITING_ASSIGNMENT = 'WAITING_ASSIGNMENT', 'Chờ phân công'
        ASSIGNED = 'ASSIGNED', 'Đã phân công'
        IN_PROGRESS = 'IN_PROGRESS', 'Đang thực hiện'
        COMPLETED = 'COMPLETED', 'Hoàn thành'
        CANCELLED = 'CANCELLED', 'Đã hủy'
        FAILED = 'FAILED', 'Thất bại'

    class PricingStatus(models.TextChoices):
        PENDING = 'PENDING', 'Chưa tính giá'
        CALCULATED = 'CALCULATED', 'Đã tính tự động'
        WAITING_QUOTE = 'WAITING_QUOTE', 'Chờ báo giá'
        QUOTED = 'QUOTED', 'Đã báo giá'

    class PaymentStatus(models.TextChoices):
        UNPAID = 'UNPAID', 'Chưa thanh toán'
        PARTIALLY_PAID = 'PARTIALLY_PAID', 'Thanh toán một phần'
        PAID = 'PAID', 'Đã thanh toán'
        REFUNDED = 'REFUNDED', 'Đã hoàn tiền'

    booking_code = models.CharField(max_length=30, unique=True)
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='bookings')
    service = models.ForeignKey('services.Service', on_delete=models.DO_NOTHING, related_name='bookings')
    user_voucher = models.OneToOneField(
        'UserVoucher',
        on_delete=models.DO_NOTHING,
        related_name='booking',
        blank=True,
        null=True,
    )
    service_data = models.JSONField()
    address = models.ForeignKey(CustomerAddress, on_delete=models.DO_NOTHING, related_name='bookings')
    note = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    pricing_status = models.CharField(max_length=30, choices=PricingStatus.choices)
    payment_status = models.CharField(max_length=30, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    price_breakdown = models.JSONField(blank=True, null=True)
    subtotal_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, blank=True, null=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='cancelled_bookings',
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'bookings'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(subtotal_amount__isnull=True) | models.Q(subtotal_amount__gte=0),
                name='bookings_subtotal_amount_check',
            ),
            models.CheckConstraint(condition=models.Q(discount_amount__gte=0), name='bookings_discount_amount_check'),
            models.CheckConstraint(
                condition=models.Q(total_amount__isnull=True) | models.Q(total_amount__gte=0),
                name='bookings_total_amount_check',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return self.booking_code


class BookingSchedule(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        IN_PROGRESS = 'IN_PROGRESS', 'Đang thực hiện'
        COMPLETED = 'COMPLETED', 'Hoàn thành'
        CANCELLED = 'CANCELLED', 'Đã hủy'
        MISSED = 'MISSED', 'Bỏ lỡ'

    booking = models.ForeignKey(Booking, on_delete=models.DO_NOTHING, related_name='schedules')
    sequence_no = models.IntegerField()
    scheduled_start = models.DateTimeField()
    scheduled_end = models.DateTimeField()
    actual_start = models.DateTimeField(blank=True, null=True)
    actual_end = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    note = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='cancelled_booking_schedules',
        blank=True,
        null=True,
    )
    cancelled_at = models.DateTimeField(blank=True, null=True)
    cancel_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'booking_schedules'
        constraints = [
            models.UniqueConstraint(
                fields=['booking', 'sequence_no'],
                name='booking_schedules_booking_sequence_unique',
            ),
            models.CheckConstraint(
                condition=models.Q(sequence_no__gt=0),
                name='booking_schedules_sequence_no_check',
            ),
            models.CheckConstraint(
                condition=models.Q(scheduled_start__lt=models.F('scheduled_end')),
                name='booking_schedules_scheduled_time_check',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(actual_end__isnull=True)
                    | models.Q(actual_start__isnull=True)
                    | models.Q(actual_start__lte=models.F('actual_end'))
                ),
                name='booking_schedules_actual_time_check',
            ),
        ]
        indexes = [
            models.Index(fields=['scheduled_start'], name='bs_scheduled_start_idx'),
            models.Index(fields=['status', 'scheduled_start'], name='bs_status_start_idx'),
        ]
        ordering = ['scheduled_start']

    def __str__(self):
        return f"{self.booking} - buổi {self.sequence_no}"


class BookingAssignment(models.Model):
    class AssignedMethod(models.TextChoices):
        MANUAL = 'MANUAL', 'Thủ công'
        AI = 'AI', 'AI'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ phản hồi'
        ACCEPTED = 'ACCEPTED', 'Đã nhận'
        REJECTED = 'REJECTED', 'Từ chối'
        CANCELLED = 'CANCELLED', 'Đã hủy'
        EXPIRED = 'EXPIRED', 'Đã hết hạn'

    schedule = models.ForeignKey(BookingSchedule, on_delete=models.DO_NOTHING, related_name='assignments')
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='booking_assignments',
    )
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='assigned_booking_schedules',
        blank=True,
        null=True,
    )
    assigned_method = models.CharField(
        max_length=20,
        choices=AssignedMethod.choices,
        default=AssignedMethod.MANUAL,
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    response_note = models.TextField(blank=True, null=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(blank=True, null=True)
    expired_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'booking_assignments'
        indexes = [
            models.Index(fields=['schedule', 'status'], name='ba_schedule_status_idx'),
            models.Index(fields=['worker', 'status'], name='ba_worker_status_idx'),
        ]
        ordering = ['-assigned_at']

    def __str__(self):
        return f"{self.schedule} - {self.worker}"


class BookingScheduleImage(models.Model):
    class ImageType(models.TextChoices):
        BEFORE = 'BEFORE', 'Trước khi làm'
        AFTER = 'AFTER', 'Sau khi làm'
        ISSUE = 'ISSUE', 'Vấn đề phát sinh'
        OTHER = 'OTHER', 'Khác'

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='uploaded_schedule_images',
    )
    schedule = models.ForeignKey(BookingSchedule, on_delete=models.DO_NOTHING, related_name='images')
    image_type = models.CharField(max_length=20, choices=ImageType.choices, default=ImageType.OTHER)
    image = models.CharField(max_length=255)
    note = models.TextField(blank=True, null=True)
    sort_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'booking_schedule_images'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(sort_order__gte=0),
                name='booking_schedule_images_sort_order_check',
            ),
        ]
        ordering = ['schedule_id', 'sort_order', 'created_at', 'id']

    def __str__(self):
        return f"{self.schedule} - {self.image_type}"


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
    distribution_type = models.CharField(
        max_length=20,
        choices=DistributionType.choices,
        default=DistributionType.CODE_ONLY,
    )
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
            models.CheckConstraint(
                condition=models.Q(issuance_limit__isnull=True) | models.Q(issuance_limit__gt=0),
                name='vouchers_issuance_limit_check',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(issuance_limit__isnull=True)
                    | models.Q(issued_count__lte=models.F('issuance_limit'))
                ),
                name='vouchers_issued_within_limit_check',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(discount_type='FIXED')
                    | models.Q(discount_value__lte=100)
                ),
                name='vouchers_percent_value_check',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(max_discount_amount__isnull=True)
                    | models.Q(max_discount_amount__gt=0)
                ),
                name='vouchers_max_discount_amount_check',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(discount_type='PERCENT')
                    | models.Q(max_discount_amount__isnull=True)
                ),
                name='vouchers_fixed_max_discount_null_check',
            ),
            models.CheckConstraint(
                condition=models.Q(start_at__lt=models.F('end_at')),
                name='vouchers_time_check',
            ),
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

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='user_vouchers',
    )
    voucher = models.ForeignKey(
        Voucher,
        on_delete=models.DO_NOTHING,
        related_name='user_vouchers',
    )
    source = models.CharField(max_length=20, choices=Source.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.AVAILABLE)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='assigned_user_vouchers',
        blank=True,
        null=True,
    )
    reserved_at = models.DateTimeField(blank=True, null=True)
    used_at = models.DateTimeField(blank=True, null=True)
    revoked_at = models.DateTimeField(blank=True, null=True)
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'user_vouchers'
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'voucher'],
                name='user_vouchers_user_voucher_unique',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} - {self.voucher}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = 'CASH', 'Tiền mặt'
        BANK_TRANSFER = 'BANK_TRANSFER', 'Chuyển khoản'
        MOMO = 'MOMO', 'MoMo'
        VNPAY = 'VNPAY', 'VNPay'
        CARD = 'CARD', 'Thẻ'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ thanh toán'
        SUCCESS = 'SUCCESS', 'Thành công'
        FAILED = 'FAILED', 'Thất bại'
        CANCELLED = 'CANCELLED', 'Đã hủy'
        REFUNDED = 'REFUNDED', 'Đã hoàn tiền'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='payments')
    booking = models.ForeignKey(Booking, on_delete=models.DO_NOTHING, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=30, choices=Method.choices)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    transaction_code = models.CharField(max_length=100, unique=True, blank=True, null=True)
    paid_at = models.DateTimeField(blank=True, null=True)
    failure_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'payments'
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name='payments_amount_check'),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booking} - {self.amount}"


class Review(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.DO_NOTHING, related_name='review')
    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='reviews')
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='worker_reviews',
        blank=True,
        null=True,
    )
    rating = models.IntegerField()
    comment = models.TextField(blank=True, null=True)
    admin_reply = models.TextField(blank=True, null=True)
    replied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='review_replies',
        blank=True,
        null=True,
    )
    replied_at = models.DateTimeField(blank=True, null=True)
    is_visible = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'reviews'
        constraints = [
            models.CheckConstraint(
                condition=models.Q(rating__gte=1) & models.Q(rating__lte=5),
                name='reviews_rating_check',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booking} - {self.rating}"


class ReviewImage(models.Model):
    review = models.ForeignKey(Review, on_delete=models.DO_NOTHING, related_name='images')
    image = models.CharField(max_length=255)
    caption = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'review_images'
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.review} - {self.image}"


class Complaint(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        IN_REVIEW = 'IN_REVIEW', 'Đang xem xét'
        RESOLVED = 'RESOLVED', 'Đã xử lý'
        REJECTED = 'REJECTED', 'Bị từ chối'
        CANCELLED = 'CANCELLED', 'Đã hủy'

    customer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='complaints')
    booking = models.ForeignKey(Booking, on_delete=models.DO_NOTHING, related_name='complaints')
    reason = models.CharField(max_length=150)
    content = models.TextField()
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='resolved_complaints',
        blank=True,
        null=True,
    )
    resolution_note = models.TextField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.booking} - {self.reason}"


class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.DO_NOTHING, related_name='attachments')
    file = models.CharField(max_length=255)
    file_type = models.CharField(max_length=30)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaint_attachments'

    def __str__(self):
        return self.file


class Notification(models.Model):
    class Type(models.TextChoices):
        BOOKING = 'BOOKING', 'Đặt lịch'
        PAYMENT = 'PAYMENT', 'Thanh toán'
        ASSIGNMENT = 'ASSIGNMENT', 'Phân công'
        COMPLAINT = 'COMPLAINT', 'Khiếu nại'
        SYSTEM = 'SYSTEM', 'Hệ thống'

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='notifications')
    title = models.CharField(max_length=150)
    message = models.TextField()
    type = models.CharField(max_length=30, choices=Type.choices, default=Type.SYSTEM)
    related_booking = models.ForeignKey(
        Booking,
        on_delete=models.DO_NOTHING,
        related_name='notifications',
        blank=True,
        null=True,
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ChatConversation(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Đang mở'
        CLOSED = 'CLOSED', 'Đã đóng'

    booking = models.ForeignKey(
        Booking,
        on_delete=models.DO_NOTHING,
        related_name='chat_conversations',
        blank=True,
        null=True,
    )
    customer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='customer_chat_conversations',
    )
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='worker_chat_conversations',
    )
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'chat_conversations'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.customer} - {self.worker}"


class ChatMessage(models.Model):
    class MessageType(models.TextChoices):
        TEXT = 'TEXT', 'Văn bản'
        IMAGE = 'IMAGE', 'Hình ảnh'
        FILE = 'FILE', 'Tệp'

    conversation = models.ForeignKey(
        ChatConversation,
        on_delete=models.DO_NOTHING,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name='chat_messages',
    )
    message = models.TextField()
    message_type = models.CharField(max_length=20, choices=MessageType.choices, default=MessageType.TEXT)
    attachment = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'chat_messages'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.sender}: {self.message[:40]}"
