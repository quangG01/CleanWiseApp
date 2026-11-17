from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("complaints", "0013_complaint_workflow"),
        ("notifications", "0008_notification_customer_chat"),
    ]

    operations = [
        migrations.AddField(
            model_name="notification",
            name="related_complaint",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to="complaints.complaint",
            ),
        ),
    ]
