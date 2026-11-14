# apps/complaints/models.py

from django.conf import settings
from django.db import models
from apps.common.codes import generate_code

class ComplaintIssueType(models.Model):
    class Stage(models.TextChoices):
        BEFORE_SERVICE = 'BEFORE_SERVICE', 'Trước khi thực hiện'
        IN_SERVICE = 'IN_SERVICE', 'Đang thực hiện'
        AFTER_SERVICE = 'AFTER_SERVICE', 'Sau khi hoàn thành'
        ANY = 'ANY', 'Mọi thời điểm'

    class AppliesTo(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Khách hàng'
        WORKER = 'WORKER', 'Nhân viên'
        ANY = 'ANY', 'Cả hai'

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default='')
    stage = models.CharField(max_length=30, choices=Stage.choices, default=Stage.ANY)

    # Ai được chọn lý do này khi tạo khiếu nại — tránh khách thấy lý do
    # "Khách không trả tiền" (chỉ nhân viên mới hợp lý) và ngược lại.
    applies_to = models.CharField(max_length=20, choices=AppliesTo.choices, default=AppliesTo.ANY)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'complaint_issue_types'
        ordering = ['stage', 'name']

    def __str__(self):
        return self.name


class Complaint(models.Model):
    class ReporterRole(models.TextChoices):
        CUSTOMER = 'CUSTOMER', 'Khách hàng'
        WORKER = 'WORKER', 'Nhân viên'

    class Stage(models.TextChoices):
        BEFORE_SERVICE = 'BEFORE_SERVICE', 'Trước khi thực hiện'
        IN_SERVICE = 'IN_SERVICE', 'Đang thực hiện'
        AFTER_SERVICE = 'AFTER_SERVICE', 'Sau khi hoàn thành'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Chờ xử lý'
        IN_REVIEW = 'IN_REVIEW', 'Đang xem xét'
        RESOLVED = 'RESOLVED', 'Đã xử lý'
        REJECTED = 'REJECTED', 'Bị từ chối'
        CANCELLED = 'CANCELLED', 'Đã hủy'

    class Outcome(models.TextChoices):
        NONE = '', 'Không xử lý tiền'
        REFUND_CUSTOMER = 'REFUND_CUSTOMER', 'Hoàn tiền khách'
        PAY_WORKER = 'PAY_WORKER', 'Trả tiền nhân viên'
        RECOVER_WORKER_EARNING = 'RECOVER_WORKER_EARNING', 'Thu hồi tiền công nhân viên'

    class RequestedResolution(models.TextChoices):
        REDO = 'REDO', 'Làm lại miễn phí'
        REFUND = 'REFUND', 'Hoàn tiền'
        CHANGE = 'CHANGE', 'Đổi lịch hoặc nhân viên'
        SUPPORT = 'SUPPORT', 'Nhận hỗ trợ'

    code = models.CharField(max_length=30, unique=True, null=True, blank=True, editable=False)
    schedule = models.ForeignKey(
        'bookings.BookingSchedule', on_delete=models.DO_NOTHING,
        related_name='complaints', null=True, blank=True,
    )
    booking = models.ForeignKey(
        'bookings.Booking', on_delete=models.DO_NOTHING, related_name='complaints',
    )
    discipline_case = models.ForeignKey(
        'worker.WorkerDisciplineCase', on_delete=models.PROTECT, null=True, blank=True,
        related_name='appeals',
    )

    # Người GỬI khiếu nại — khách hàng hoặc nhân viên.
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='complaints_filed',
    )
    reporter_role = models.CharField(max_length=20, choices=ReporterRole.choices)

    # Nhân viên LIÊN QUAN, tách riêng khỏi `reporter` để luôn truy vấn được
    # "mọi khiếu nại dính tới nhân viên X" bất kể ai là người gửi.
    worker = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING,
        related_name='complaints_about', null=True, blank=True,
    )

    issue_type = models.ForeignKey(
        ComplaintIssueType, on_delete=models.PROTECT, related_name='complaints',
    )

    # Backend tự xác định từ Booking.status.
    stage = models.CharField(max_length=30, choices=Stage.choices)
    content = models.TextField(blank=True, default='')
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.PENDING)
    requested_resolution = models.CharField(max_length=12, choices=RequestedResolution.choices, blank=True, default='')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='assigned_complaints',
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    next_update_at = models.DateTimeField(null=True, blank=True)

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING,
        related_name='resolved_complaints', blank=True, null=True,
    )
    resolution_note = models.TextField(blank=True, null=True)
    resolved_at = models.DateTimeField(blank=True, null=True)

    # Kết quả tiền do hệ thống tính (xem resolution_service), admin không nhập.
    outcome = models.CharField(max_length=30, choices=Outcome.choices, blank=True, default='')
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)   # khách được hoàn
    customer_delta = models.DecimalField(max_digits=12, decimal_places=2, default=0)  # + cộng / - trừ ví khách
    worker_delta = models.DecimalField(max_digits=12, decimal_places=2, default=0)    # + cộng / - trừ ví nhân viên
    shortfall = models.DecimalField(max_digits=12, decimal_places=2, default=0)       # không thu hồi được, nền tảng chịu

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaints'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['worker', 'created_at'], name='complaints_worker_created_idx'),
        ]

    def save(self, *args, **kwargs):
        # Chỉ sinh mã khi tạo mới. Khiếu nại cũ được điền mã bằng migration bên dưới.
        if self._state.adding and not self.code:
            self.code = generate_code(
                'KN', lambda c: Complaint.objects.filter(code=c).exists(),
            )
        super().save(*args, **kwargs)
        
    def __str__(self):
        return f'{self.booking} - {self.issue_type.name}'


def complaint_attachment_path(instance, filename):
    return f'complaints/{instance.complaint_id}/{filename}'


class ComplaintAttachment(models.Model):
    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='attachments')
    file = models.URLField(max_length=500)
    public_id = models.CharField(max_length=255, blank=True, default='')
    file_type = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'complaint_attachments'

    def __str__(self):
        return str(self.file)


class ComplaintEvent(models.Model):
    class Kind(models.TextChoices):
        CLAIM = 'CLAIM', 'Tiếp nhận'
        ACK = 'ACK', 'Phản hồi của CSKH'
        REQUEST = 'REQUEST', 'Yêu cầu bổ sung thông tin'
        VERIFY = 'VERIFY', 'Xác minh nội bộ'
        REPLY = 'REPLY', 'Phản hồi của khách'
        OFFER = 'OFFER', 'Gửi phương án'
        ACCEPT = 'ACCEPT', 'Đồng ý phương án'
        REVISE = 'REVISE', 'Yêu cầu trao đổi thêm'
        CLOSE = 'CLOSE', 'Hoàn tất phương án'
        REJECT = 'REJECT', 'Từ chối khiếu nại'
        REOPEN = 'REOPEN', 'Yêu cầu xem xét lại'

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    message = models.TextField()
    is_public = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'pk']


class ComplaintProposal(models.Model):
    class Status(models.TextChoices):
        SENT = 'SENT', 'Chờ khách phản hồi'
        ACCEPTED = 'ACCEPTED', 'Đang thực hiện'
        DECLINED = 'DECLINED', 'Cần trao đổi thêm'
        COMPLETED = 'COMPLETED', 'Đã thực hiện'

    class ServiceAction(models.TextChoices):
        REDO = 'REDO', 'Làm lại miễn phí'
        CHANGE = 'CHANGE', 'Đổi lịch hoặc nhân viên'

    class RefundScope(models.TextChoices):
        SESSION = 'SESSION', 'Hoàn tiền buổi'
        BOOKING = 'BOOKING', 'Hoàn tiền đơn'
        PARTIAL = 'PARTIAL', 'Hoàn một phần tiền buổi'
        CASH = 'CASH', 'Đối soát tiền mặt'

    complaint = models.ForeignKey(Complaint, on_delete=models.CASCADE, related_name='proposals')
    message = models.TextField()
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.SENT)
    service_action = models.CharField(max_length=12, choices=ServiceAction.choices, blank=True)
    scheduled_start = models.DateTimeField(null=True, blank=True)
    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    fulfilled_schedule = models.ForeignKey('bookings.BookingSchedule', on_delete=models.PROTECT, null=True, blank=True)
    refund_scope = models.CharField(max_length=12, choices=RefundScope.choices, blank=True)
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    refund_transaction = models.OneToOneField('wallets.WalletTransaction', on_delete=models.PROTECT, null=True, blank=True)
    voucher = models.ForeignKey('vouchers.Voucher', on_delete=models.PROTECT, null=True, blank=True)
    issued_voucher = models.OneToOneField('vouchers.UserVoucher', on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        constraints = [
            models.UniqueConstraint(
                fields=['complaint'],
                condition=models.Q(status__in=['SENT', 'ACCEPTED']),
                name='complaint_one_active_proposal',
            ),
        ]
