from contextlib import contextmanager

from django.conf import settings

from ..exceptions import AgentUnavailable

CHECKPOINT_SCHEMA = 'chatbot_checkpoints'


def checkpoint_connection():
    import psycopg
    from psycopg.rows import dict_row

    db = settings.DATABASES['default']
    if db['ENGINE'] != 'django.db.backends.postgresql':
        raise AgentUnavailable('Chatbot checkpoint requires PostgreSQL.')
    options = db.get('OPTIONS', {})
    host = settings.CHATBOT_CHECKPOINT_DB_HOST or db.get('HOST') or None
    # Neon pooled connections cannot preserve the session search_path required
    # by PostgresSaver. Use its matching direct endpoint for checkpoints only.
    if host and host.endswith('.neon.tech'):
        host = host.replace('-pooler.', '.')
    allowed_options = ('sslmode', 'sslrootcert', 'sslcert', 'sslkey', 'channel_binding',
                       'keepalives', 'keepalives_idle', 'keepalives_interval', 'keepalives_count')
    params = {key: options[key] for key in allowed_options if key in options}
    params.update(dbname=db['NAME'], user=db.get('USER') or None, password=db.get('PASSWORD') or None,
                  host=host, port=db.get('PORT') or 5432,
                  connect_timeout=10, autocommit=True, prepare_threshold=0, row_factory=dict_row,
                  options=f'-c search_path={CHECKPOINT_SCHEMA} -c statement_timeout=10000')
    return psycopg.connect(**params)


@contextmanager
def open_checkpointer():
    from langgraph.checkpoint.postgres import PostgresSaver

    # setup() is an explicit deployment command, not DDL on every request.
    with checkpoint_connection() as conn:
        yield PostgresSaver(conn)
