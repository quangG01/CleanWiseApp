from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("addresses", "0001_initial"),
        ("services", "0002_alter_service_is_active"),
        ("vouchers", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Booking",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("booking_code", models.CharField(max_length=30, unique=True)),
                ("service_data", models.JSONField()),
                ("note", models.TextField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Chờ xử lý / Chờ nhận việc"),
                            ("ASSIGNED", "Đã có nhân viên nhận"),
                            ("IN_PROGRESS", "Đang thực hiện"),
                            ("COMPLETED", "Hoàn thành toàn bộ"),
                            ("CANCELLED", "Đã hủy"),
                            ("FAILED", "Thất bại"),
                        ],
                        default="PENDING",
                        max_length=30,
                    ),
                ),
                (
                    "payment_status",
                    models.CharField(
                        choices=[
                            ("UNPAID", "Chưa thanh toán"),
                            ("PAID", "Đã thanh toán"),
                            ("REFUNDED", "Đã hoàn tiền"),
                        ],
                        default="UNPAID",
                        max_length=30,
                    ),
                ),
                ("price_breakdown", models.JSONField(blank=True, null=True)),
                (
                    "subtotal_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=12, null=True
                    ),
                ),
                (
                    "discount_amount",
                    models.DecimalField(decimal_places=2, default=0, max_digits=12),
                ),
                (
                    "total_amount",
                    models.DecimalField(
                        blank=True, decimal_places=2, max_digits=12, null=True
                    ),
                ),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_reason", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "address",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="bookings",
                        to="addresses.customeraddress",
                    ),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="cancelled_bookings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "customer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="bookings",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "service",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="bookings",
                        to="services.service",
                    ),
                ),
                (
                    "user_voucher",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="booking",
                        to="vouchers.uservoucher",
                    ),
                ),
            ],
            options={
                "db_table": "bookings",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="BookingSchedule",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("sequence_no", models.IntegerField()),
                ("scheduled_start", models.DateTimeField()),
                ("scheduled_end", models.DateTimeField()),
                ("actual_start", models.DateTimeField(blank=True, null=True)),
                ("actual_end", models.DateTimeField(blank=True, null=True)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("PENDING", "Chờ thực hiện"),
                            ("IN_PROGRESS", "Đang làm buổi này"),
                            ("COMPLETED", "Đã xong buổi này"),
                            ("CANCELLED", "Hủy buổi này"),
                            ("MISSED", "Bỏ lỡ buổi này"),
                        ],
                        default="PENDING",
                        max_length=20,
                    ),
                ),
                ("note", models.TextField(blank=True, null=True)),
                ("cancelled_at", models.DateTimeField(blank=True, null=True)),
                ("cancel_reason", models.TextField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "booking",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="schedules",
                        to="bookings.booking",
                    ),
                ),
                (
                    "cancelled_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="cancelled_booking_schedules",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "booking_schedules",
                "ordering": ["scheduled_start"],
            },
        ),
        migrations.CreateModel(
            name="BookingScheduleImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "image_type",
                    models.CharField(
                        choices=[
                            ("BEFORE", "Trước khi làm"),
                            ("AFTER", "Sau khi làm"),
                            ("ISSUE", "Vấn đề phát sinh"),
                            ("OTHER", "Khác"),
                        ],
                        default="OTHER",
                        max_length=20,
                    ),
                ),
                ("image", models.CharField(max_length=255)),
                ("note", models.TextField(blank=True, null=True)),
                ("sort_order", models.IntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "schedule",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="images",
                        to="bookings.bookingschedule",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.DO_NOTHING,
                        related_name="uploaded_schedule_images",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "db_table": "booking_schedule_images",
                "ordering": ["schedule_id", "sort_order", "created_at", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("subtotal_amount__isnull", True),
                    ("subtotal_amount__gte", 0),
                    _connector="OR",
                ),
                name="bookings_subtotal_amount_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.CheckConstraint(
                condition=models.Q(("discount_amount__gte", 0)),
                name="bookings_discount_amount_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="booking",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("total_amount__isnull", True),
                    ("total_amount__gte", 0),
                    _connector="OR",
                ),
                name="bookings_total_amount_check",
            ),
        ),
        migrations.AddIndex(
            model_name="bookingschedule",
            index=models.Index(
                fields=["scheduled_start"], name="bs_scheduled_start_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="bookingschedule",
            index=models.Index(
                fields=["status", "scheduled_start"], name="bs_status_start_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingschedule",
            constraint=models.UniqueConstraint(
                fields=("booking", "sequence_no"),
                name="booking_schedules_booking_sequence_unique",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("sequence_no__gt", 0)),
                name="booking_schedules_sequence_no_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(("scheduled_start__lt", models.F("scheduled_end"))),
                name="booking_schedules_scheduled_time_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingschedule",
            constraint=models.CheckConstraint(
                condition=models.Q(
                    ("actual_end__isnull", True),
                    ("actual_start__isnull", True),
                    ("actual_start__lte", models.F("actual_end")),
                    _connector="OR",
                ),
                name="booking_schedules_actual_time_check",
            ),
        ),
        migrations.AddConstraint(
            model_name="bookingscheduleimage",
            constraint=models.CheckConstraint(
                condition=models.Q(("sort_order__gte", 0)),
                name="booking_schedule_images_sort_order_check",
            ),
        ),
    ]