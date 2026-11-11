"""Import the provided issue-type dump by code, preserving existing references."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / '.env')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings.dev')
import django

django.setup()
from django.db import connection, transaction

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('source', type=Path)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()

columns = ['id', 'code', 'name', 'description', 'stage', 'is_active',
           'created_at', 'updated_at', 'applies_to']
quoted = ', '.join('"' + column + '"' for column in columns)
literal = r"(?:[0-9]+|true|false|'(?:''|[^'])*')"
pattern = re.compile(
    r'insert into "complaint_issue_types" \(' + re.escape(quoted)
    + r'\) overriding system value values \('
    + literal + (r',\s*' + literal) * 8 + r'\);', re.IGNORECASE)
source = args.source.read_text(encoding='utf-8-sig')
statements = []
position = 0
while position < len(source):
    if source[position].isspace():
        position += 1
        continue
    match = pattern.match(source, position)
    if not match:
        raise ValueError('Unexpected SQL at character ' + str(position))
    statements.append(match.group())
    position = match.end()
if not statements:
    raise ValueError('No issue types in source')

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '10s'")
        cursor.execute('LOCK TABLE complaint_issue_types IN SHARE ROW EXCLUSIVE MODE')
        cursor.execute('CREATE TEMP TABLE import_issue_types ON COMMIT DROP AS '
                       'SELECT * FROM complaint_issue_types WITH NO DATA')
        for statement in statements:
            cursor.execute(statement.replace('"complaint_issue_types"', '"import_issue_types"', 1))
        cursor.execute('SELECT COUNT(*), COUNT(DISTINCT code) FROM import_issue_types')
        count, unique_count = cursor.fetchone()
        if count != unique_count:
            raise ValueError('Duplicate source codes')
        cursor.execute("SELECT COUNT(*) FROM import_issue_types WHERE stage NOT IN "
                       "('BEFORE_SERVICE','IN_SERVICE','AFTER_SERVICE','ANY') OR "
                       "applies_to NOT IN ('CUSTOMER','WORKER','ANY')")
        if cursor.fetchone()[0]:
            raise ValueError('Invalid stage or applies_to')
        cursor.execute('SELECT COUNT(*) FROM import_issue_types s JOIN '
                       'complaint_issue_types t USING (code)')
        existing = cursor.fetchone()[0]
        print(f'Source: {count}; existing codes: {existing}; new: {count - existing}')
        if not args.apply:
            transaction.set_rollback(True)
        else:
            cursor.execute('SELECT * FROM complaint_issue_types ORDER BY id')
            names = [col[0] for col in cursor.description]
            backup = [dict(zip(names, row)) for row in cursor.fetchall()]
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup_path = ROOT / 'exports' / f'complaint_issue_types_before_{stamp}.json'
            backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=2,
                                              default=str), encoding='utf-8')
            print('Backup:', backup_path)
            cursor.execute("SELECT pg_get_serial_sequence('complaint_issue_types', 'id')")
            sequence = cursor.fetchone()[0]
            if not sequence:
                raise ValueError('Missing ID sequence')
            # Never move the sequence backwards or reuse an existing ID.
            cursor.execute('SELECT MAX(id) FROM complaint_issue_types')
            max_id = cursor.fetchone()[0] or 0
            cursor.execute('SELECT nextval(%s::regclass)', [sequence])
            next_id = cursor.fetchone()[0]
            cursor.execute('SELECT setval(%s::regclass, %s, true)',
                           [sequence, max(next_id, max_id)])
            fields = ', '.join(columns[1:])
            updates = ', '.join(f'{field} = EXCLUDED.{field}' for field in columns[2:])
            cursor.execute(f'INSERT INTO complaint_issue_types ({fields}) '
                           f'SELECT {fields} FROM import_issue_types ORDER BY id '
                           f'ON CONFLICT (code) DO UPDATE SET {updates}')
            print('Imported:', cursor.rowcount)
            matches = ' AND '.join(f't.{field} IS NOT DISTINCT FROM s.{field}'
                                   for field in columns[1:])
            cursor.execute('SELECT COUNT(*) FROM import_issue_types s JOIN '
                           f'complaint_issue_types t ON {matches}')
            if cursor.fetchone()[0] != count:
                raise ValueError('Imported data differs from source; rollback')
            cursor.execute('SELECT applies_to, is_active, COUNT(*) FROM '
                           'complaint_issue_types GROUP BY applies_to, is_active '
                           'ORDER BY applies_to, is_active')
            print('Verified groups:', cursor.fetchall())
if args.apply:
    print('Committed successfully')
