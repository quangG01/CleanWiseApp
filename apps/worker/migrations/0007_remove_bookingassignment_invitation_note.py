from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('worker', '0006_assignment_invitations')]
    operations = [
        migrations.RemoveField(model_name='bookingassignment', name='invitation_note'),
    ]
