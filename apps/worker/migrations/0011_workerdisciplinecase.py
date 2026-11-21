from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('worker', '0010_backfill_monthly_favorites'),
    ]

    operations = [
        migrations.CreateModel(
            name='WorkerDisciplineCase',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('CANCEL', 'Hủy nhận việc'), ('LATE', 'Báo vắng sát giờ'), ('NO_SHOW', 'Không check-in')], max_length=12)),
                ('status', models.CharField(choices=[('PENDING', 'Chờ xác minh'), ('CONFIRMED', 'Đã xác nhận'), ('WAIVED', 'Đã miễn điểm')], default='PENDING', max_length=12)),
                ('deduction', models.PositiveSmallIntegerField()),
                ('reason', models.TextField(blank=True)),
                ('occurred_at', models.DateTimeField()),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('review_note', models.TextField(blank=True)),
                ('sanction', models.CharField(blank=True, choices=[('', 'Không xử lý hồ sơ'), ('SUSPENDED', 'Tạm khóa hồ sơ'), ('PROPOSED', 'Chờ duyệt cấm'), ('BANNED', 'Cấm hồ sơ')], default='', max_length=12)),
                ('sanction_at', models.DateTimeField(blank=True, null=True)),
                ('sanction_until', models.DateTimeField(blank=True, null=True)),
                ('sanction_note', models.TextField(blank=True)),
                ('assignment', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='discipline_case', to='worker.bookingassignment')),
                ('proposed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-occurred_at', '-pk']},
        ),
    ]
