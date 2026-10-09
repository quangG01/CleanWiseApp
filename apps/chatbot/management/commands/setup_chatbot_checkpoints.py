from django.core.management.base import BaseCommand, CommandError

from apps.chatbot.agent.checkpoint import CHECKPOINT_SCHEMA, checkpoint_connection


class Command(BaseCommand):
    help = 'Initialize LangGraph PostgreSQL checkpoint tables in a dedicated schema.'

    def handle(self, *args, **options):
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import sql

        try:
            with checkpoint_connection() as conn:
                conn.execute('SELECT pg_advisory_lock(742031)')
                try:
                    conn.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(CHECKPOINT_SCHEMA)))
                    PostgresSaver(conn).setup()
                finally:
                    conn.execute('SELECT pg_advisory_unlock(742031)')
        except Exception as exc:
            # Do not echo connection strings/passwords from provider/driver errors.
            raise CommandError(f'Checkpoint setup failed ({type(exc).__name__}). Check PostgreSQL permissions/connectivity.') from exc
        self.stdout.write(self.style.SUCCESS('LangGraph checkpoint tables are ready in ' + CHECKPOINT_SCHEMA))
