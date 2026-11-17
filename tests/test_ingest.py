from warehouse import Conflict, NotFound, SchemaError, record, union
from warehouse.samples import event_schema
from tests.support import WarehouseCase


class TestIngest(WarehouseCase):
    def test_named_union_identity(self):
        revision = self.wh.register('source', event_schema())
        values = [union('A', record('A', x=11)), union('B', record('B', x=11))]
        accepted = self.wh.append('one', revision, values)
        self.assertEqual(self.wh.archive.get(accepted['batch_id'])['values'], values)
        values[0]['value']['fields']['x'] = 90
        self.assertEqual(self.wh.archive.get(accepted['batch_id'])['values'][0]['value']['fields']['x'], 11)

    def test_undefined_name_preserves_head(self):
        revision = self.wh.register('source', 'long')
        with self.assertRaises(SchemaError):
            self.wh.register('source', {'type': 'record', 'name': 'R',
                                       'fields': [{'name': 'x', 'type': 'Unknown'}]})
        self.assertEqual(self.wh.catalog.revision('source'), revision)
        self.assertEqual(self.count('schema_revisions'), 1)

    def test_request_replay(self):
        revision = self.wh.register('source', 'long')
        first = self.wh.append('once', revision, [0, 1, 1])
        self.assertEqual(self.wh.append('once', revision, iter([0, 1, 1])), first)
        with self.assertRaises(Conflict):
            self.wh.append('once', revision, [1, 0, 1])
        newer = self.wh.register('source', 'long')
        with self.assertRaises(Conflict):
            self.wh.append('once', newer, [0, 1, 1])
        self.assertEqual(self.count('batches'), 1)

    def test_late_bad_value_rejects_batch(self):
        revision = self.wh.register('source', event_schema())
        good = union('A', record('A', x=1))
        with self.assertRaises(SchemaError):
            self.wh.append('retry', revision, [good, union('B', record('A', x=2))])
        self.assertEqual(self.count('batches'), 0)
        self.wh.append('retry', revision, [good])
        self.assertEqual(self.count('batches'), 1)

    def test_invalid_defaults_and_ambiguous_fields(self):
        self.wh.register('source', 'long')
        invalid = [
            {'type': 'record', 'name': 'R', 'fields': [
                {'name': 'x', 'type': 'long', 'default': None}]},
            {'type': 'record', 'name': 'R', 'fields': [
                {'name': 'x', 'type': 'long'}, {'name': 'x', 'type': 'string'}]},
            {'type': 'record', 'name': 'R', 'fields': [
                {'name': 'a', 'type': 'long', 'aliases': ['old']},
                {'name': 'b', 'type': 'long', 'aliases': ['old']}]},
            ['long', 'long'],
        ]
        for schema in invalid:
            with self.subTest(schema=schema), self.assertRaises(SchemaError):
                self.wh.register('source', schema)
        self.assertEqual(self.count('schema_revisions'), 1)

    def test_long_and_absence_errors(self):
        revision = self.wh.register('source', 'long')
        for value in (True, 2**63, -(2**63)-1, '2', None):
            with self.subTest(value=value), self.assertRaises(SchemaError):
                self.wh.append('bad', revision, [value])
        with self.assertRaises(NotFound):
            self.wh.create_job(999, 'source')
        with self.assertRaises(NotFound):
            self.wh.create_job(self.wh.append('ok', revision, [])['batch_id'], 'absent')
        self.assertEqual(self.count('jobs'), 0)
