from django.db import migrations


def repair_legacy_complaints_schema(apps, schema_editor):
    ComplaintIssueType = apps.get_model('complaints', 'ComplaintIssueType')
    table_name = 'complaints'
    connection = schema_editor.connection

    with connection.cursor() as cursor:
        columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

        legacy_type, _ = ComplaintIssueType.objects.get_or_create(
            code='LEGACY_OTHER',
            defaults={
                'name': 'Vấn đề khác',
                'description': 'Loại mặc định cho dữ liệu khiếu nại từ schema cũ.',
                'stage': 'ANY',
                'is_active': True,
            },
        )

        if 'issue_type_id' not in columns:
            cursor.execute(
                'ALTER TABLE complaints ADD COLUMN issue_type_id bigint NULL'
            )
            cursor.execute(
                'UPDATE complaints SET issue_type_id = %s WHERE issue_type_id IS NULL',
                [legacy_type.pk],
            )
            cursor.execute(
                'ALTER TABLE complaints ALTER COLUMN issue_type_id SET NOT NULL'
            )
            cursor.execute(
                'ALTER TABLE complaints ADD CONSTRAINT complaints_issue_type_fk '
                'FOREIGN KEY (issue_type_id) REFERENCES complaint_issue_types(id) '
                'DEFERRABLE INITIALLY DEFERRED'
            )
            cursor.execute(
                'CREATE INDEX complaints_issue_type_id_idx ON complaints (issue_type_id)'
            )

        if 'stage' not in columns:
            cursor.execute(
                "ALTER TABLE complaints ADD COLUMN stage varchar(30) NULL"
            )
            cursor.execute(
                "UPDATE complaints SET stage = 'AFTER_SERVICE' WHERE stage IS NULL"
            )
            cursor.execute(
                'ALTER TABLE complaints ALTER COLUMN stage SET NOT NULL'
            )

        if 'reason' in columns:
            cursor.execute(
                "UPDATE complaints SET content = CASE "
                "WHEN content IS NULL OR content = '' THEN reason "
                "ELSE content || E'\\nLý do cũ: ' || reason END "
                "WHERE reason IS NOT NULL AND reason <> ''"
            )
            cursor.execute('ALTER TABLE complaints DROP COLUMN reason')


class Migration(migrations.Migration):
    dependencies = [
        ('complaints', '0003_ensure_complaint_issue_types_table'),
    ]

    operations = [
        migrations.RunPython(
            repair_legacy_complaints_schema,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
