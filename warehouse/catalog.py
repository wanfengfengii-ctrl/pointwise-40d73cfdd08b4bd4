import json

from .db import dumps
from .errors import NotFound, SchemaError
from .schema import Schema
from .storage import store_for


class Catalog:
    def __init__(self, db):
        self.db = db

    def register(self, name, schema):
        if not isinstance(name, str) or not name:
            raise SchemaError('nonempty catalog name required')
        body = dumps(Schema(schema).body)
        store = store_for(self.db)
        with self.db.atomic() as conn:
            revision = conn.execute(
                'INSERT INTO ' + store.revisions + '(name,body) VALUES (?,?)',
                (name, body)).lastrowid
            conn.execute(
                'INSERT INTO ' + store.heads + ' VALUES (?,?) '
                'ON CONFLICT(name) DO UPDATE SET revision=excluded.revision',
                (name, revision))
        return revision

    def revision(self, name_or_revision):
        conn = self.db.connection
        store = store_for(self.db)
        if type(name_or_revision) is int:
            row = conn.execute('SELECT id FROM ' + store.revisions + ' WHERE id=?',
                               (name_or_revision,)).fetchone()
        elif isinstance(name_or_revision, str):
            row = conn.execute('SELECT revision FROM ' + store.heads + ' WHERE name=?',
                               (name_or_revision,)).fetchone()
        else:
            row = None
        if row is None:
            raise NotFound('schema revision')
        return row[0]

    def get(self, name_or_revision):
        revision = self.revision(name_or_revision)
        store = store_for(self.db)
        row = self.db.connection.execute(
            'SELECT name,body FROM ' + store.revisions + ' WHERE id=?', (revision,)).fetchone()
        return {'revision': revision, 'name': row['name'], 'schema': json.loads(row['body'])}

    def revisions(self):
        store = store_for(self.db)
        return [self.get(row[0]) for row in self.db.connection.execute(
            'SELECT id FROM ' + store.revisions + ' ORDER BY id')]
