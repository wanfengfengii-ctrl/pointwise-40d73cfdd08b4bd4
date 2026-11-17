"""Row-level access to the legacy schema1 tables and the target v2 tables.

The warehouse objects choose a store from the database's current storage
version at call time, so a live object starts using the target tables as soon
as an upgrade commits and a reopened object never sees the legacy ones.
"""


class V1Store:
    version = '1'
    revisions = 'schema_revisions'
    heads = 'schema_heads'
    batches = 'batches'
    jobs = 'jobs'
    runs = 'runs'
    publications = 'publications'

    def __init__(self, db):
        self.db = db


class V2Store(V1Store):
    version = '2'
    revisions = 'v2_revisions'
    heads = 'v2_heads'
    batches = 'v2_batches'
    jobs = 'v2_jobs'
    runs = 'v2_runs'
    publications = 'v2_publications'

    def plan(self, writer_revision, reader_revision):
        """Persisted action graph for a revision pair, compiled lazily."""
        from .native2 import get_plan
        return get_plan(self.db, writer_revision, reader_revision)


def store_for(db):
    return V2Store(db) if db.storage_version() == '2' else V1Store(db)
