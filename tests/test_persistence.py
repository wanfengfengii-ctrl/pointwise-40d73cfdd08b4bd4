import os
import tempfile
import unittest

from warehouse import Warehouse
from warehouse.samples import seed


class TestPersistence(unittest.TestCase):
    def test_complete_old_database_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'warehouse.sqlite')
            wh, ids = seed(path)
            old = wh.results(ids['job'])
            old_runs = wh.jobs.runs(ids['job'])
            revisions = wh.catalog.revisions()
            batch = wh.archive.get(ids['batch'])
            wh.close()
            with Warehouse(path) as reopened:
                self.assertEqual(reopened.catalog.revisions(), revisions)
                self.assertEqual(reopened.archive.get(ids['batch']), batch)
                self.assertEqual(reopened.results(ids['job']), old)
                self.assertEqual(reopened.jobs.runs(ids['job']), old_runs)
                self.assertEqual(reopened.db.connection.execute(
                    "SELECT value FROM metadata WHERE key='storage_version'").fetchone()[0], '1')
                replay = reopened.append(batch['request_id'], batch['writer_revision'], batch['values'])
                self.assertEqual(replay, {'batch_id': batch['batch_id'], 'receipt': batch['receipt']})
                reopened.run(ids['job'])
                self.assertEqual(reopened.results(ids['job'])['reader_revision'], ids['reader'])
                self.assertEqual(reopened.results(ids['job'])['values'], old['values'])
                self.assertEqual(reopened.results(ids['empty_job'])['values'], [])
                self.assertIsNone(reopened.results(ids['pending_job']))
                self.assertEqual(reopened.jobs.runs(ids['pending_job']), [])
                self.assertIsNone(reopened.results(ids['failed_job']))
                self.assertEqual(reopened.jobs.runs(ids['failed_job'])[0]['status'], 'failed')

    def test_publication_rollback_reopen_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'warehouse.sqlite')
            wh, ids = seed(path)
            previous = wh.results(ids['job'])
            def fail():
                raise RuntimeError('disk publication gate')
            try:
                with self.assertRaisesRegex(RuntimeError, 'disk publication gate'):
                    wh.run(ids['job'], before_commit=fail)
            finally:
                wh.close()
            with Warehouse(path) as reopened:
                self.assertEqual(reopened.results(ids['job']), previous)
                failed = reopened.jobs.runs(ids['job'])[-1]
                self.assertEqual(failed['status'], 'failed')
                self.assertIsNone(reopened.results(ids['job'], failed['id']))
                reopened.run(ids['job'])
                self.assertEqual(reopened.results(ids['job'])['values'], previous['values'])
                self.assertEqual(reopened.results(ids['job'], previous['run_id']), previous)
