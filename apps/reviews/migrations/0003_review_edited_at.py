from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('reviews', '0002_review_assignment')]

    operations = [
        migrations.AddField(
            model_name='review', name='edited_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
