import json

from .db import dumps
from .errors import Conflict, NotFound, SchemaError
from .schema import Schema
from .storage import store_for


class Archive:
    def __init__(self, db, catalog):
        self.db, self.catalog = db, catalog

    def append(self, request_id, writer_revision, values):
        if not isinstance(request_id, str) or not request_id:
            raise SchemaError('nonempty request id required')
        if type(writer_revision) is not int:
            raise SchemaError('writer must be an immutable revision id')
        schema = Schema(self.catalog.get(writer_revision)['schema'])
        values = list(values)
        for value in values:
            schema.validate(value)
        payload = dumps(values)
        store = store_for(self.db)
        with self.db.atomic() as conn:
            old = conn.execute('SELECT * FROM ' + store.batches + ' WHERE request_id=?',
                               (request_id,)).fetchone()
            if old is not None:
                if old['writer_revision'] != writer_revision or old['payload'] != payload:
                    raise Conflict('request already bound to another batch')
                return {'batch_id': old['id'], 'receipt': old['receipt']}
            batch = conn.execute(
                'INSERT INTO ' + store.batches +
                '(request_id,writer_revision,payload,receipt) VALUES (?,?,?,?)',
                (request_id, writer_revision, payload, 'pending:' + request_id)
            ).lastrowid
            receipt = 'accepted:' + str(batch)
            conn.execute('UPDATE ' + store.batches + ' SET receipt=? WHERE id=?',
                         (receipt, batch))
        return {'batch_id': batch, 'receipt': receipt}

    def get(self, batch_id):
        store = store_for(self.db)
        row = self.db.connection.execute('SELECT * FROM ' + store.batches + ' WHERE id=?',
                                         (batch_id,)).fetchone()
        if row is None:
            raise NotFound('batch')
        return {'batch_id': row['id'], 'request_id': row['request_id'],
                'writer_revision': row['writer_revision'],
                'values': json.loads(row['payload']), 'receipt': row['receipt']}
