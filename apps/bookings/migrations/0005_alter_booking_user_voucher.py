from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('bookings', '0004_booking_delivery_address'),
        ('vouchers', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='user_voucher',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.DO_NOTHING,
                related_name='bookings',
                to='vouchers.uservoucher',
            ),
        ),
    ]
