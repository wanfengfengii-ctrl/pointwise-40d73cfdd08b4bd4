from warehouse import NotFound, ResolutionError, record, union
from warehouse.samples import chain, event_reader, event_schema, node_schema
from tests.support import WarehouseCase


class TestProcessing(WarehouseCase):
    def job(self, writer, reader, values, request='request'):
        w = self.wh.register('writer-' + request, writer)
        r = self.wh.register('reader-' + request, reader)
        batch = self.wh.append(request, w, values)['batch_id']
        return self.wh.create_job(batch, r)

    def test_recursive_defaults(self):
        job = self.job(node_schema(), node_schema(True), [chain()])
        self.wh.run(job)
        value = self.wh.results(job)['values'][0]
        self.assertEqual(value, record('Node', x=4, quality='raw', next=union('Node',
            record('Node', x=9, quality='raw', next=union('null', None)))))
        self.assertEqual(self.wh.jobs.runs(job)[0]['status'], 'succeeded')

    def test_accessed_missing_field(self):
        reader = event_schema()[:2]
        reader[1]['fields'].append({'name': 'required', 'type': 'long'})
        good = self.job(event_schema(), reader, [union('A', record('A', x=1))], 'good')
        self.wh.run(good)
        previous = self.wh.results(good)
        bad = self.job(event_schema(), reader, [
            union('A', record('A', x=2)), union('B', record('B', x=3))], 'bad')
        with self.assertRaises(ResolutionError):
            self.wh.run(bad)
        self.assertIsNone(self.wh.results(bad))
        self.assertEqual(self.wh.results(good), previous)
        self.assertEqual(self.count('publications'), 1)
        self.assertEqual(self.wh.jobs.runs(bad)[0]['status'], 'failed')

    def test_publication_failure_retry(self):
        job = self.job('long', 'long', [3, 5])
        first = self.wh.run(job)
        previous = self.wh.results(job)
        def interrupt():
            raise RuntimeError('commit gate')
        with self.assertRaisesRegex(RuntimeError, 'commit gate'):
            self.wh.run(job, before_commit=interrupt)
        self.assertEqual(self.wh.results(job), previous)
        failed = self.wh.jobs.runs(job)[1]
        self.assertEqual(failed['status'], 'failed')
        self.assertIsNone(self.wh.results(job, failed['id']))
        self.assertEqual(self.count('publications'), 1)
        last = self.wh.run(job)
        self.assertNotEqual(first['run_id'], last['run_id'])
        self.assertEqual(self.wh.results(job, first['run_id']), previous)
        self.assertEqual(self.wh.results(job)['values'], [3, 5])
        self.assertEqual(self.count('publications'), 2)

    def test_reordered_named_union_and_unvisited_bad_branch(self):
        job = self.job(event_schema(), event_reader(),
                       [union('A', record('A', x=7)), union('B', record('B', x=7))])
        self.wh.run(job)
        self.assertEqual([v['$branch'] for v in self.wh.results(job)['values']], ['A', 'B'])
        bad = self.job(event_schema(), event_reader(), [union('string', 'bad')], 'bad')
        with self.assertRaises(ResolutionError):
            self.wh.run(bad)

    def test_alias_and_first_compatible_branch(self):
        writer = {'type': 'record', 'name': 'Old', 'fields': [{'name': 'old', 'type': 'long'}]}
        reader = [
            {'type': 'record', 'name': 'First', 'aliases': ['Old'], 'fields': [
                {'name': 'new', 'aliases': ['old'], 'type': 'long'}]},
            {'type': 'record', 'name': 'Old', 'fields': [{'name': 'old', 'type': 'long'}]},
        ]
        job = self.job(writer, reader, [record('Old', old=6)])
        self.wh.run(job)
        self.assertEqual(self.wh.results(job)['values'],
                         [union('First', record('First', new=6))])

    def test_empty_missing_and_history(self):
        job = self.job('long', 'string', [])
        self.assertIsNone(self.wh.results(job))
        run = self.wh.run(job)
        self.assertEqual(self.wh.results(job)['values'], [])
        self.assertEqual(self.wh.results(job, run['run_id'])['receipt'], run['receipt'])
        with self.assertRaises(NotFound):
            self.wh.results(999)
        with self.assertRaises(NotFound):
            self.wh.results(job, 999)
        other = self.job('long', 'long', [], 'other')
        with self.assertRaises(NotFound):
            self.wh.results(other, run['run_id'])

    def test_default_values_are_independent(self):
        reader = {'type': 'record', 'name': 'R', 'fields': [
            {'name': 'extra', 'type': {'type': 'record', 'name': 'D', 'fields': [
                {'name': 'x', 'type': 'long'}]}, 'default': record('D', x=8)}]}
        writer = {'type': 'record', 'name': 'R', 'fields': []}
        job = self.job(writer, reader, [record('R'), record('R')])
        self.wh.run(job)
        values = self.wh.results(job)['values']
        values[0]['fields']['extra']['fields']['x'] = 99
        self.assertEqual(values[1]['fields']['extra']['fields']['x'], 8)
        self.assertEqual(self.wh.results(job)['values'][0]['fields']['extra']['fields']['x'], 8)

    def test_first_compatible_branch_does_not_fall_through_on_field_error(self):
        writer = {'type': 'record', 'name': 'R', 'fields': []}
        reader = [
            {'type': 'record', 'name': 'Needs', 'aliases': ['R'],
             'fields': [{'name': 'required', 'type': 'long'}]},
            {'type': 'record', 'name': 'R', 'fields': []},
        ]
        job = self.job(writer, reader, [record('R')])
        with self.assertRaisesRegex(ResolutionError, 'missing required field'):
            self.wh.run(job)
        self.assertIsNone(self.wh.results(job))

    def test_finite_recursive_values_hand_calculated(self):
        for depth in range(7):
            value = record('Node', x=0, next=union('null', None))
            expected = record('Node', x=0, quality='raw', next=union('null', None))
            for number in range(1, depth + 1):
                value = record('Node', x=number, next=union('Node', value))
                expected = record('Node', x=number, quality='raw', next=union('Node', expected))
            job = self.job(node_schema(), node_schema(True), [value], 'depth' + str(depth))
            self.wh.run(job)
            self.assertEqual(self.wh.results(job)['values'], [expected])
