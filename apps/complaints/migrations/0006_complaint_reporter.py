# apps/complaints/migrations/0006_complaint_reporter.py

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def backfill_reporter_role_and_worker(apps, schema_editor):
    """
    reporter_role của dữ liệu cũ đã tự động là 'CUSTOMER' (default của
    AddField bên dưới). Hàm này chỉ còn việc suy `worker` từ assignment
    ACCEPTED của schedule, cho complaint cũ nào có gắn schedule.
    """
    Complaint = apps.get_model('complaints', 'Complaint')
    BookingAssignment = apps.get_model('worker', 'BookingAssignment')

    for complaint in Complaint.objects.filter(schedule__isnull=False, worker__isnull=True):
        assignment = BookingAssignment.objects.filter(
            schedule_id=complaint.schedule_id, status='ACCEPTED',
        ).first()
        if assignment:
            complaint.worker_id = assignment.worker_id
            complaint.save(update_fields=['worker'])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('complaints', '0005_complaint_refund_amount'),
        ('worker', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='complaintissuetype',
            name='applies_to',
            field=models.CharField(
                choices=[('CUSTOMER', 'Khách hàng'), ('WORKER', 'Nhân viên'), ('ANY', 'Cả hai')],
                default='ANY',
                max_length=20,
            ),
        ),
        # RenameField (không phải Remove+Add) để GIỮ NGUYÊN dữ liệu cột
        # customer cũ, chỉ đổi tên cột trong DB sang reporter.
        migrations.RenameField(
            model_name='complaint',
            old_name='customer',
            new_name='reporter',
        ),
        migrations.AlterField(
            model_name='complaint',
            name='reporter',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='complaints_filed',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        # reporter_role: thêm với default tạm 'CUSTOMER' luôn (không cần
        # bước RunPython riêng cho field này) vì 100% dữ liệu cũ là khách.
        migrations.AddField(
            model_name='complaint',
            name='reporter_role',
            field=models.CharField(
                choices=[('CUSTOMER', 'Khách hàng'), ('WORKER', 'Nhân viên')],
                default='CUSTOMER',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='complaint',
            name='worker',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='complaints_about',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddIndex(
            model_name='complaint',
            index=models.Index(fields=['worker', 'created_at'], name='complaints_worker_created_idx'),
        ),
        migrations.RunPython(backfill_reporter_role_and_worker, noop_reverse),
    ]