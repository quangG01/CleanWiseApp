from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0003_backfill_pair_conversations'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='chatconversation',
            name='booking',
        ),
        migrations.AddConstraint(
            model_name='chatconversation',
            constraint=models.UniqueConstraint(fields=('customer', 'worker'), name='chat_conversation_pair_unique'),
        ),
        migrations.AddConstraint(
            model_name='chatconversation',
            constraint=models.CheckConstraint(condition=~models.Q(customer=models.F('worker')), name='chat_conversation_distinct_users'),
        ),
        migrations.AddConstraint(
            model_name='chatmessage',
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(message_type='SYSTEM', sender__isnull=True, recipient__isnull=False, related_assignment__isnull=False)
                    | models.Q(message_type__in=['TEXT', 'IMAGE', 'FILE'], sender__isnull=False, recipient__isnull=True, related_assignment__isnull=True)
                ),
                name='chat_message_actor_check',
            ),
        ),
        migrations.AddConstraint(
            model_name='chatmessage',
            constraint=models.UniqueConstraint(
                fields=('related_assignment', 'recipient'),
                condition=models.Q(message_type='SYSTEM'),
                name='chat_system_assignment_recipient_unique',
            ),
        ),
    ]
