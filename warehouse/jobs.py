from .errors import NotFound
from .schema1 import resolve
from .storage import store_for


class Jobs:
    def __init__(self, db, catalog, archive, publications):
        self.db, self.catalog = db, catalog
        self.archive, self.publications = archive, publications

    def create_job(self, batch_id, reader_name_or_revision):
        self.archive.get(batch_id)
        revision = self.catalog.revision(reader_name_or_revision)
        store = store_for(self.db)
        with self.db.atomic() as conn:
            return conn.execute(
                'INSERT INTO ' + store.jobs + '(batch_id,reader_revision) VALUES (?,?)',
                (batch_id, revision)).lastrowid

    def get(self, job_id):
        store = store_for(self.db)
        row = self.db.connection.execute('SELECT * FROM ' + store.jobs + ' WHERE id=?',
                                         (job_id,)).fetchone()
        if row is None:
            raise NotFound('job')
        return dict(row)

    def runs(self, job_id):
        self.get(job_id)
        store = store_for(self.db)
        return [dict(row) for row in self.db.connection.execute(
            'SELECT * FROM ' + store.runs + ' WHERE job_id=? ORDER BY id', (job_id,))]

    def run(self, job_id, before_commit=None):
        job = self.get(job_id)
        batch = self.archive.get(job['batch_id'])
        store = store_for(self.db)
        with self.db.atomic() as conn:
            run_id = conn.execute(
                'INSERT INTO ' + store.runs + "(job_id,status) VALUES (?,'running')",
                (job_id,)).lastrowid
        try:
            if store.version == '2':
                # The persisted graph is the only interpreter; it is materialised
                # before any value is touched so an empty batch needs no graph run.
                from .schema2 import execute
                program = store.plan(batch['writer_revision'], job['reader_revision'])
                values = [execute(program, value) for value in batch['values']]
            else:
                writer = self.catalog.get(batch['writer_revision'])['schema']
                reader = self.catalog.get(job['reader_revision'])['schema']
                values = [resolve(writer, reader, value) for value in batch['values']]
            receipt = self.publications.publish(run_id, values, before_commit)
        except BaseException as error:
            with self.db.atomic() as conn:
                conn.execute('UPDATE ' + store.runs +
                             " SET status='failed',error=? WHERE id=?",
                             (type(error).__name__ + ': ' + str(error), run_id))
            raise
        return {'run_id': run_id, 'receipt': receipt}
