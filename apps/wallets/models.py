from django.conf import settings
from django.db import models


class Wallet(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='wallet',
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallets'
        constraints = [
            models.CheckConstraint(condition=models.Q(balance__gte=0), name='wallets_balance_check'),
        ]

    def __str__(self):
        return f'Wallet - {self.user}'


class WalletTransaction(models.Model):
    class Type(models.TextChoices):
        PAYMENT = 'PAYMENT', 'Thanh toán dịch vụ'
        REFUND = 'REFUND', 'Hoàn tiền'
        WITHDRAW = 'WITHDRAW', 'Rút tiền'
        ADJUSTMENT = 'ADJUSTMENT', 'Điều chỉnh'
        EARNING = 'EARNING', 'Thu nhập từ đơn'  # MỚI: tiền nhân viên nhận khi hoàn thành buổi (đơn online)

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Đang xử lý'
        SUCCESS = 'SUCCESS', 'Thành công'
        FAILED = 'FAILED', 'Thất bại'

    wallet = models.ForeignKey(Wallet, on_delete=models.DO_NOTHING, related_name='transactions')
    type = models.CharField(max_length=20, choices=Type.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUCCESS)

    booking = models.ForeignKey(
        'bookings.Booking',
        on_delete=models.DO_NOTHING,
        related_name='wallet_transactions',
        blank=True,
        null=True,
    )
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'wallet_transactions'
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name='wallet_tx_amount_check')]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.wallet} - {self.type} - {self.amount}'


class WorkerEarning(models.Model):
    """
    Sổ cái thu nhập của nhân viên: mỗi buổi làm hoàn thành = 1 dòng.

    - ONLINE: khách đã trả trước cho app -> app giữ tiền, cộng worker_amount
      (đã trừ hoa hồng) vào ví nhân viên.
    - CASH: nhân viên đã thu tiền mặt của khách -> không đụng ví, chỉ ghi
      commission_amount là khoản nhân viên phải nộp lại app (settled_at
      null = chưa nộp).

    Lưu commission_rate theo từng dòng để sau này đổi tỷ lệ không làm sai
    số liệu cũ.
    """

    class PaymentMethod(models.TextChoices):
        CASH = 'CASH', 'Tiền mặt'
        ONLINE = 'ONLINE', 'Thanh toán online'

    worker = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.DO_NOTHING, related_name='worker_earnings')
    # OneToOne = mỗi buổi chỉ được ghi thu nhập 1 lần (check-out trùng không cộng 2 lần)
    schedule = models.OneToOneField(
        'bookings.BookingSchedule', on_delete=models.DO_NOTHING, related_name='worker_earning',
    )
    booking = models.ForeignKey('bookings.Booking', on_delete=models.DO_NOTHING, related_name='worker_earnings')
    payment_method = models.CharField(max_length=20, choices=PaymentMethod.choices)

    gross_amount = models.DecimalField(max_digits=12, decimal_places=2)
    commission_rate = models.DecimalField(max_digits=5, decimal_places=4)
    commission_amount = models.DecimalField(max_digits=12, decimal_places=2)
    worker_amount = models.DecimalField(max_digits=12, decimal_places=2)

    completed_at = models.DateTimeField()
    settled_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'worker_earnings'
        constraints = [
            models.CheckConstraint(condition=models.Q(gross_amount__gte=0), name='worker_earnings_gross_check'),
            models.CheckConstraint(
                condition=models.Q(gross_amount=models.F('worker_amount') + models.F('commission_amount')),
                name='worker_earnings_split_check',
            ),
        ]
        indexes = [
            models.Index(fields=['worker', 'completed_at'], name='we_worker_completed_idx'),
            models.Index(fields=['worker', 'payment_method', 'settled_at'], name='we_worker_settle_idx'),
        ]
        ordering = ['-completed_at']

    def __str__(self):
        return f'{self.worker} - {self.booking} - {self.payment_method} - {self.worker_amount}'