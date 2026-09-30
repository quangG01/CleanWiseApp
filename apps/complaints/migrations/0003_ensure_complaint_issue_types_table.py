from django.db import migrations


def ensure_complaint_issue_types_table(apps, schema_editor):
    """Khôi phục bảng bị thiếu ở các database đã fake/applied migration 0001."""
    model = apps.get_model('complaints', 'ComplaintIssueType')
    existing_tables = schema_editor.connection.introspection.table_names()
    if model._meta.db_table not in existing_tables:
        schema_editor.create_model(model)


class Migration(migrations.Migration):
    dependencies = [
        ('complaints', '0002_complaint_schedule_and_more'),
    ]

    operations = [
        migrations.RunPython(
            ensure_complaint_issue_types_table,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
