from django.db import migrations, models
import django.db.models.deletion


def add_issue_type(apps, schema_editor):
    apps.get_model('complaints', 'ComplaintIssueType').objects.get_or_create(
        code='WORKER_DISCIPLINE',
        defaults={'name': 'Xem xét điểm tín nhiệm', 'stage': 'ANY', 'applies_to': 'WORKER'},
    )


class Migration(migrations.Migration):
    dependencies = [
        ('complaints', '0011_merge_recovery_and_attachments'),
        ('worker', '0011_workerdisciplinecase'),
    ]

    operations = [
        migrations.AddField(
            model_name='complaint', name='discipline_case',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='appeals', to='worker.workerdisciplinecase'),
        ),
        migrations.RunPython(add_issue_type, migrations.RunPython.noop),
    ]
