from warehouse import record
from warehouse.samples import chain, node_schema
from tests.support import WarehouseCase


class TestEvolution(WarehouseCase):
    def test_fixed_reader_revision(self):
        writer = self.wh.register('writer', node_schema())
        original = self.wh.register('reader', node_schema())
        batch = self.wh.append('chain', writer, [chain()])['batch_id']
        old = self.wh.create_job(batch, 'reader')
        revised = self.wh.register('reader', node_schema(True))
        new = self.wh.create_job(batch, 'reader')
        for job in (old, new, old, new):
            self.wh.run(job)
        self.assertEqual(self.wh.results(old)['reader_revision'], original)
        self.assertEqual(self.wh.results(new)['reader_revision'], revised)
        self.assertNotIn('quality', self.wh.results(old)['values'][0]['fields'])
        self.assertEqual(self.wh.results(new)['values'][0]['fields']['quality'], 'raw')
        self.assertEqual(self.wh.catalog.get(original)['schema'], node_schema())
        retrieved = self.wh.catalog.get(original)
        retrieved['schema']['fields'].clear()
        self.assertEqual(self.wh.catalog.get(original)['schema'], node_schema())

    def test_recursive_reader_pair_does_not_leak(self):
        writer = self.wh.register('writer', node_schema())
        batch = self.wh.append('chain', writer, [chain()])['batch_id']
        readers = []
        for label in ('checked', 'verified'):
            schema = node_schema(True)
            schema['fields'][-1]['default'] = label
            revision = self.wh.register('reader', schema)
            readers.append((self.wh.create_job(batch, revision), label))
        for job, label in reversed(readers * 2):
            self.wh.run(job)
            root = self.wh.results(job)['values'][0]['fields']
            self.assertEqual(root['quality'], label)
            self.assertEqual(root['next']['value']['fields']['quality'], label)

    def test_reader_name_alias_is_directional(self):
        from warehouse import ResolutionError
        old = {'type': 'record', 'name': 'Old', 'fields': []}
        new = {'type': 'record', 'name': 'New', 'aliases': ['Old'], 'fields': []}
        w = self.wh.register('w', new)
        r = self.wh.register('r', old)
        batch = self.wh.append('new', w, [record('New')])['batch_id']
        job = self.wh.create_job(batch, r)
        with self.assertRaises(ResolutionError):
            self.wh.run(job)
