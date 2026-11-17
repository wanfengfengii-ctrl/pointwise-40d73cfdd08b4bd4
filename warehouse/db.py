import json
import sqlite3
from contextlib import contextmanager

META_DDL = """
CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

V1_DDL = """
CREATE TABLE IF NOT EXISTS schema_revisions(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS schema_heads(
 name TEXT PRIMARY KEY, revision INTEGER NOT NULL REFERENCES schema_revisions(id));
CREATE TABLE IF NOT EXISTS batches(
 id INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
 writer_revision INTEGER NOT NULL REFERENCES schema_revisions(id),
 payload TEXT NOT NULL, receipt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(
 id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES batches(id),
 reader_revision INTEGER NOT NULL REFERENCES schema_revisions(id));
CREATE TABLE IF NOT EXISTS runs(
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id),
 status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')), error TEXT);
CREATE TABLE IF NOT EXISTS publications(
 run_id INTEGER PRIMARY KEY REFERENCES runs(id), payload TEXT NOT NULL,
 receipt TEXT UNIQUE NOT NULL);
"""


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


class Database:
    def __init__(self, path=':memory:'):
        self.connection = sqlite3.connect(path, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys=ON')
        self.connection.execute('PRAGMA busy_timeout=3000')
        self.connection.execute(META_DDL)
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='storage_version'").fetchone()
        if row is None:
            self.connection.execute(
                "INSERT INTO metadata VALUES ('storage_version','1')")
        # An upgraded database keeps only the v2 business tables in use; the
        # legacy tables are audit history and are never created or touched anew.
        if row is None or row[0] != '2':
            self.connection.executescript(V1_DDL)

    def storage_version(self):
        row = self.connection.execute(
            "SELECT value FROM metadata WHERE key='storage_version'").fetchone()
        return row[0] if row is not None else '1'

    @contextmanager
    def atomic(self):
        if self.connection.in_transaction:
            raise RuntimeError('nested transaction')
        self.connection.execute('BEGIN IMMEDIATE')
        try:
            yield self.connection
            self.connection.commit()
        except BaseException:
            self.connection.rollback()
            raise

    def close(self):
        self.connection.close()
