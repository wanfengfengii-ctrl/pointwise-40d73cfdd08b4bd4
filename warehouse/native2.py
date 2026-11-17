"""Native target-store entry points: only version 2 databases are accepted."""
import json

from .db import dumps
from .errors import Conflict, NotFound, SchemaError
from .graph import compile_plan
from .schema import Schema


def _require_v2(db):
    if db.storage_version() != '2':
        raise Conflict('native store requires storage version 2')


def register(db, name, schema):
    _require_v2(db)
    if not isinstance(name, str) or not name:
        raise SchemaError('nonempty catalog name required')
    body = dumps(Schema(schema).body)
    with db.atomic() as conn:
        revision = conn.execute(
            'INSERT INTO v2_revisions(name,body) VALUES (?,?)', (name, body)).lastrowid
        conn.execute('INSERT INTO v2_heads VALUES (?,?) '
                     'ON CONFLICT(name) DO UPDATE SET revision=excluded.revision',
                     (name, revision))
    return revision


def append(db, request_id, writer_revision, values):
    _require_v2(db)
    if not isinstance(request_id, str) or not request_id:
        raise SchemaError('nonempty request id required')
    if type(writer_revision) is not int:
        raise SchemaError('writer must be an immutable revision id')
    row = db.connection.execute('SELECT body FROM v2_revisions WHERE id=?',
                                (writer_revision,)).fetchone()
    if row is None:
        raise NotFound('schema revision')
    schema = Schema(json.loads(row[0]))
    values = list(values)
    for value in values:
        schema.validate(value)
    payload = dumps(values)
    with db.atomic() as conn:
        old = conn.execute('SELECT * FROM v2_batches WHERE request_id=?',
                           (request_id,)).fetchone()
        if old is not None:
            if old['writer_revision'] != writer_revision or old['payload'] != payload:
                raise Conflict('request already bound to another batch')
            return {'batch_id': old['id'], 'receipt': old['receipt']}
        batch = conn.execute(
            'INSERT INTO v2_batches(request_id,writer_revision,payload,receipt) '
            'VALUES (?,?,?,?)', (request_id, writer_revision, payload,
                                 'pending:' + request_id)).lastrowid
        receipt = 'accepted:' + str(batch)
        conn.execute('UPDATE v2_batches SET receipt=? WHERE id=?', (receipt, batch))
    return {'batch_id': batch, 'receipt': receipt}


def get_plan(db, writer_revision, reader_revision):
    _require_v2(db)
    for revision in (writer_revision, reader_revision):
        if db.connection.execute('SELECT 1 FROM v2_revisions WHERE id=?',
                                 (revision,)).fetchone() is None:
            raise NotFound('schema revision')
    row = db.connection.execute(
        'SELECT graph FROM v2_plans WHERE writer_revision=? AND reader_revision=?',
        (writer_revision, reader_revision)).fetchone()
    if row is None:
        writer = json.loads(db.connection.execute(
            'SELECT body FROM v2_revisions WHERE id=?', (writer_revision,)).fetchone()[0])
        reader = json.loads(db.connection.execute(
            'SELECT body FROM v2_revisions WHERE id=?', (reader_revision,)).fetchone()[0])
        text = dumps(compile_plan(writer, reader))
        with db.atomic() as conn:
            conn.execute('INSERT OR IGNORE INTO v2_plans VALUES (?,?,?)',
                         (writer_revision, reader_revision, text))
            row = conn.execute(
                'SELECT graph FROM v2_plans WHERE writer_revision=? AND reader_revision=?',
                (writer_revision, reader_revision)).fetchone()
    return json.loads(row[0])
