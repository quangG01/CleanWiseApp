import django.db.models.deletion
from django.db import migrations, models


def backfill_review_assignments(apps, schema_editor):
    Review = apps.get_model('reviews', 'Review')
    BookingAssignment = apps.get_model('worker', 'BookingAssignment')

    for review in Review.objects.all().iterator():
        assignments = BookingAssignment.objects.filter(
            schedule__booking_id=review.booking_id,
            status='ACCEPTED',
        )
        if review.worker_id:
            assignments = assignments.filter(worker_id=review.worker_id)

        assignment_ids = list(assignments.values_list('id', flat=True)[:2])
        if len(assignment_ids) != 1:
            raise RuntimeError(
                'Không thể tự động chuyển review '
                f'{review.pk} sang BookingAssignment: tìm thấy '
                f'{len(assignment_ids)} assignment ACCEPTED phù hợp.'
            )

        review.assignment_id = assignment_ids[0]
        review.save(update_fields=['assignment'])


class Migration(migrations.Migration):

    dependencies = [
        ('reviews', '0001_initial'),
        ('worker', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='review',
            name='assignment',
            field=models.OneToOneField(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='review',
                to='worker.bookingassignment',
            ),
        ),
        migrations.RunPython(
            backfill_review_assignments,
            migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name='review',
            name='booking',
        ),
        migrations.RemoveField(
            model_name='review',
            name='customer',
        ),
        migrations.RemoveField(
            model_name='review',
            name='worker',
        ),
        migrations.AlterField(
            model_name='review',
            name='assignment',
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='review',
                to='worker.bookingassignment',
            ),
        ),
    ]
