"""One-way upgrade from the legacy schema1 storage to the explicit-graph store.

The whole migration is a single SQLite transaction: schema copies, lazily
executable plans and the metadata version switch commit together.  A caller
callback runs after the target is complete but before that commit, so any
failure leaves the legacy database and its version untouched and the upgrade
can be retried.  Legacy tables are never dropped; they remain immutable audit.
"""
import json

from .db import dumps
from .errors import WarehouseError
from .graph import compile_plan

V2_DDL = """
CREATE TABLE IF NOT EXISTS v2_revisions(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_heads(
 name TEXT PRIMARY KEY, revision INTEGER NOT NULL REFERENCES v2_revisions(id));
CREATE TABLE IF NOT EXISTS v2_batches(
 id INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
 writer_revision INTEGER NOT NULL REFERENCES v2_revisions(id),
 payload TEXT NOT NULL, receipt TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_jobs(
 id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES v2_batches(id),
 reader_revision INTEGER NOT NULL REFERENCES v2_revisions(id));
CREATE TABLE IF NOT EXISTS v2_runs(
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES v2_jobs(id),
 status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')), error TEXT);
CREATE TABLE IF NOT EXISTS v2_publications(
 run_id INTEGER PRIMARY KEY REFERENCES v2_runs(id),
 payload TEXT NOT NULL, receipt TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS v2_plans(
 writer_revision INTEGER NOT NULL REFERENCES v2_revisions(id),
 reader_revision INTEGER NOT NULL REFERENCES v2_revisions(id),
 graph TEXT NOT NULL,
 PRIMARY KEY(writer_revision,reader_revision));
"""

_COPIES = (
    ('v2_revisions', 'schema_revisions'),
    ('v2_heads', 'schema_heads'),
    ('v2_batches', 'batches'),
    ('v2_jobs', 'jobs'),
    ('v2_runs', 'runs'),
    ('v2_publications', 'publications'),
)

# executescript would COMMIT first, so the target DDL is issued statement by
# statement to stay inside the single atomic switch.
V2_STATEMENTS = [statement.strip() for statement in V2_DDL.split(';')
                 if statement.strip()]

_TARGETS = [target for target, _ in _COPIES] + ['v2_plans']


def _plans(conn):
    pairs = conn.execute(
        'SELECT DISTINCT b.writer_revision,j.reader_revision FROM jobs j '
        'JOIN batches b ON b.id=j.batch_id ORDER BY 1,2').fetchall()
    bodies = {}
    for writer, reader in pairs:
        for revision in (writer, reader):
            if revision not in bodies:
                row = conn.execute('SELECT body FROM schema_revisions WHERE id=?',
                                   (revision,)).fetchone()
                if row is None:
                    raise WarehouseError('missing schema revision ' + str(revision))
                bodies[revision] = json.loads(row[0])
        graph = compile_plan(bodies[writer], bodies[reader])
        conn.execute('INSERT OR REPLACE INTO v2_plans VALUES (?,?,?)',
                     (writer, reader, dumps(graph)))


def upgrade(db, before_commit=None):
    """Migrate ``db`` in place; idempotent once the version is 2."""
    conn = db.connection
    if db.storage_version() == '2':
        return None
    with db.atomic():
        # No target table may survive a failed attempt; recreate from scratch.
        for table in reversed(_TARGETS):
            conn.execute('DROP TABLE IF EXISTS ' + table)
        for statement in V2_STATEMENTS:
            conn.execute(statement)
        for target, source in _COPIES:
            conn.execute('INSERT INTO ' + target + ' SELECT * FROM ' + source)
        _plans(conn)
        if before_commit is not None:
            before_commit()
        conn.execute("UPDATE metadata SET value='2' WHERE key='storage_version'")
    return None
