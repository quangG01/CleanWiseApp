from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('notifications', '0004_notification_related_schedule'), ('authentication', '0004_add_worker_rejected_fields')]
    operations = [migrations.AddField(model_name='notification', name='related_worker', field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='authentication.workerprofile'))]
