from django.db import migrations, models
from django.utils import timezone


def close_legacy_pending(apps, schema_editor):
    # Old pending records had no invitation lifecycle or deadline.
    Assignment = apps.get_model('worker', 'BookingAssignment')
    Assignment.objects.using(schema_editor.connection.alias).filter(status='PENDING').update(
        status='CANCELLED', responded_at=timezone.now(),
        response_note='Lời mời cũ đóng khi nâng cấp luồng nhận việc.',
    )


class Migration(migrations.Migration):
    dependencies = [('worker', '0005_remove_area_areas_city_name_unique_and_more')]
    operations = [
        migrations.AddField(model_name='bookingassignment', name='invitation_note', field=models.TextField(blank=True, default='')),
        migrations.RunPython(close_legacy_pending, migrations.RunPython.noop),
        migrations.AddConstraint(model_name='bookingassignment', constraint=models.UniqueConstraint(
            fields=['schedule'], condition=models.Q(status='PENDING'), name='uniq_pending_invitation_per_schedule',
        )),
    ]
