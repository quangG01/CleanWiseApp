from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('complaints', '0008_complaint_code')]

    operations = [
        migrations.AlterField(
            model_name='complaint',
            name='outcome',
            field=models.CharField(blank=True, choices=[
                ('', 'Không xử lý tiền'),
                ('REFUND_CUSTOMER', 'Hoàn tiền khách'),
                ('PAY_WORKER', 'Trả tiền nhân viên'),
                ('RECOVER_WORKER_EARNING', 'Thu hồi tiền công nhân viên'),
            ], default='', max_length=30),
        ),
    ]
