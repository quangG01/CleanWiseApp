from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('notifications', '0005_notification_related_worker')]
    operations = [migrations.AddField(
        model_name='notification', name='navigation_source',
        field=models.CharField(max_length=20, default='mine'),
    )]
