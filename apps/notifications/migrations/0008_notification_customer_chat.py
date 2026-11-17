from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0007_notification_target"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="related_customer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="notification",
            name="type",
            field=models.CharField(
                choices=[
                    ("BOOKING", "Đặt lịch"),
                    ("PAYMENT", "Thanh toán"),
                    ("ASSIGNMENT", "Phân công"),
                    ("COMPLAINT", "Khiếu nại"),
                    ("CHAT", "Tin nhắn"),
                    ("SYSTEM", "Hệ thống"),
                ],
                default="SYSTEM",
                max_length=30,
            ),
        ),
    ]
