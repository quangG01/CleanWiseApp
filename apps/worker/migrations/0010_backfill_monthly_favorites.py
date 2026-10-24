from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone


def backfill(apps, schema_editor):
    Link = apps.get_model('worker', 'CustomerFavoriteWorker')
    Entry = apps.get_model('worker', 'WorkerFavoriteMonthlyEntry')
    database = schema_editor.connection.alias
    pending = []
    for link in Link.objects.using(database).order_by().values('customer_id', 'worker_id', 'created_at').iterator(chunk_size=1000):
        month = timezone.localtime(link['created_at'], ZoneInfo('Asia/Ho_Chi_Minh')).date().replace(day=1)
        pending.append(Entry(customer_id=link['customer_id'], worker_id=link['worker_id'], month=month,
                             first_favorited_at=link['created_at'], source='BACKFILL'))
        if len(pending) == 1000:
            Entry.objects.using(database).bulk_create(pending, ignore_conflicts=True, batch_size=1000)
            pending = []
    if pending:
        Entry.objects.using(database).bulk_create(pending, ignore_conflicts=True, batch_size=1000)


class Migration(migrations.Migration):
    dependencies = [('worker', '0009_workerfavoritemonthlyentry')]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
