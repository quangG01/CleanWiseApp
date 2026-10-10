from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('worker', '0007_remove_bookingassignment_invitation_note')]
    operations = [
        migrations.RemoveConstraint(model_name='bookingassignment', name='uniq_pending_invitation_per_schedule'),
        migrations.AddConstraint(
            model_name='bookingassignment',
            constraint=models.UniqueConstraint(fields=['schedule', 'worker'], condition=models.Q(status='PENDING'), name='uniq_pending_invitation_per_worker'),
        ),
    ]
