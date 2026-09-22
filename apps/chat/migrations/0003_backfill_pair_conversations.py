from importlib import import_module

from django.db import migrations


backfill_chat_assignments = import_module(
    'apps.chat.migrations.0002_chatconversationassignment_alter_chatmessage_options_and_more'
).backfill_chat_assignments


class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0002_chatconversationassignment_alter_chatmessage_options_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_chat_assignments, migrations.RunPython.noop),
    ]
