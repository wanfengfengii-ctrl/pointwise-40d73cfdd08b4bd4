from .errors import NotFound
from .schema1 import resolve


class Jobs:
    def __init__(self, db, catalog, archive, publications):
        self.db, self.catalog = db, catalog
        self.archive, self.publications = archive, publications

    def create_job(self, batch_id, reader_name_or_revision):
        self.archive.get(batch_id)
        revision = self.catalog.revision(reader_name_or_revision)
        with self.db.atomic() as conn:
            return conn.execute('INSERT INTO jobs(batch_id,reader_revision) VALUES (?,?)',
                                (batch_id, revision)).lastrowid

    def get(self, job_id):
        row = self.db.connection.execute('SELECT * FROM jobs WHERE id=?',
                                         (job_id,)).fetchone()
        if row is None:
            raise NotFound('job')
        return dict(row)

    def runs(self, job_id):
        self.get(job_id)
        return [dict(row) for row in self.db.connection.execute(
            'SELECT * FROM runs WHERE job_id=? ORDER BY id', (job_id,))]

    def run(self, job_id, before_commit=None):
        job = self.get(job_id)
        batch = self.archive.get(job['batch_id'])
        writer = self.catalog.get(batch['writer_revision'])['schema']
        reader = self.catalog.get(job['reader_revision'])['schema']
        with self.db.atomic() as conn:
            run_id = conn.execute(
                "INSERT INTO runs(job_id,status) VALUES (?,'running')", (job_id,)).lastrowid
        try:
            values = [resolve(writer, reader, value) for value in batch['values']]
            receipt = self.publications.publish(run_id, values, before_commit)
        except BaseException as error:
            with self.db.atomic() as conn:
                conn.execute("UPDATE runs SET status='failed',error=? WHERE id=?",
                             (type(error).__name__ + ': ' + str(error), run_id))
            raise
        return {'run_id': run_id, 'receipt': receipt}
