from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("bookings", "0002_alter_booking_status"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE bookings
                DROP COLUMN IF EXISTS pricing_status;
            """,
            reverse_sql="""
                ALTER TABLE bookings
                ADD COLUMN pricing_status VARCHAR(30) NOT NULL DEFAULT 'CALCULATED';
            """,
        ),
    ]
