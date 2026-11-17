import json

from .db import dumps
from .errors import Conflict, NotFound
from .storage import store_for


class Publications:
    def __init__(self, db):
        self.db = db

    def publish(self, run_id, values, before_commit=None):
        payload = dumps(values)
        store = store_for(self.db)
        with self.db.atomic() as conn:
            row = conn.execute('SELECT status FROM ' + store.runs + ' WHERE id=?',
                               (run_id,)).fetchone()
            if row is None:
                raise NotFound('run')
            if row['status'] != 'running':
                raise Conflict('run is terminal')
            receipt = 'published:' + str(run_id)
            conn.execute('INSERT INTO ' + store.publications + ' VALUES (?,?,?)',
                         (run_id, payload, receipt))
            conn.execute('UPDATE ' + store.runs + " SET status='succeeded' WHERE id=?",
                         (run_id,))
            if before_commit is not None:
                before_commit()
        return receipt

    def results(self, job_id, run_id=None):
        conn = self.db.connection
        store = store_for(self.db)
        if conn.execute('SELECT 1 FROM ' + store.jobs + ' WHERE id=?',
                        (job_id,)).fetchone() is None:
            raise NotFound('job')
        if run_id is None:
            row = conn.execute(
                'SELECT p.* FROM ' + store.publications + ' p JOIN ' + store.runs +
                ' r ON r.id=p.run_id WHERE r.job_id=? ORDER BY p.run_id DESC LIMIT 1',
                (job_id,)).fetchone()
            if row is None:
                return None
        else:
            run = conn.execute('SELECT job_id FROM ' + store.runs + ' WHERE id=?',
                               (run_id,)).fetchone()
            if run is None or run['job_id'] != job_id:
                raise NotFound('run for job')
            row = conn.execute('SELECT * FROM ' + store.publications + ' WHERE run_id=?',
                               (run_id,)).fetchone()
            if row is None:
                return None
        lineage = conn.execute(
            'SELECT j.batch_id,j.reader_revision,b.writer_revision FROM ' + store.jobs +
            ' j JOIN ' + store.batches + ' b ON b.id=j.batch_id WHERE j.id=?',
            (job_id,)).fetchone()
        return {'job_id': job_id, 'run_id': row['run_id'],
                'batch_id': lineage['batch_id'],
                'writer_revision': lineage['writer_revision'],
                'reader_revision': lineage['reader_revision'],
                'values': json.loads(row['payload']), 'receipt': row['receipt']}
