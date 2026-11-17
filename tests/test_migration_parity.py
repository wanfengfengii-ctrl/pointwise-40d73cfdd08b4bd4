"""Independent compatibility oracle: schema1 resolution vs. compiled graphs.

Every case resolves the same writer/reader pair twice: once through the
untouched legacy ``schema1.resolve`` and once by executing the persisted-shape
action graph with the untouched ``schema2`` port.  Nothing here uses a
database, so it proves the graph representation is self-contained.
"""
import unittest

from warehouse import ResolutionError, record, union
from warehouse import schema1, schema2
from warehouse.graph import compile_plan
from warehouse.samples import chain, event_reader, event_schema, node_schema


def both(writer, reader, value):
    expected = schema1.resolve(writer, reader, value)
    program = schema2.load_graph(schema2.dump_graph(compile_plan(writer, reader)))
    return expected, schema2.execute(program, value)


def outcome(call):
    try:
        return ('ok', call())
    except ResolutionError as error:
        return ('error', str(error))


class TestGraphParity(unittest.TestCase):
    def assert_same(self, writer, reader, value):
        legacy = outcome(lambda: schema1.resolve(writer, reader, value))
        program = schema2.load_graph(schema2.dump_graph(compile_plan(writer, reader)))
        graph = outcome(lambda: schema2.execute(program, value))
        self.assertEqual(graph, legacy)
        return legacy

    def test_reordered_named_union_keeps_identity(self):
        for value in (union('A', record('A', x=7)), union('B', record('B', x=7))):
            kind, expected = both(event_schema(), event_reader(), value)
            self.assertEqual(kind['$branch'], value['$branch'])
            self.assertEqual(kind, expected)

    def test_unvisited_branch_fails_only_when_accessed(self):
        good, bad = union('A', record('A', x=1)), union('string', 'late')
        self.assert_same(event_schema(), event_reader(), good)
        self.assertEqual(self.assert_same(event_schema(), event_reader(), bad),
                         ('error', 'no compatible reader branch'))

    def test_recursive_defaults_each_layer(self):
        for label in ('raw', 'checked', 'verified'):
            reader = node_schema(True)
            reader['fields'][-1]['default'] = label
            _, out = both(node_schema(), reader, chain())
            self.assertEqual(out['fields']['quality'], label)
            self.assertEqual(out['fields']['next']['value']['fields']['quality'], label)

    def test_recursive_identity_without_defaults(self):
        expected, out = both(node_schema(), node_schema(), chain())
        self.assertEqual(out, expected)
        self.assertNotIn('quality', out['fields'])

    def test_aliases_are_directional(self):
        old = {'type': 'record', 'name': 'Old', 'fields': [{'name': 'old', 'type': 'long'}]}
        renamed = {'type': 'record', 'name': 'New', 'aliases': ['Old'],
                   'fields': [{'name': 'new', 'aliases': ['old'], 'type': 'long'}]}
        _, out = both(old, renamed, record('Old', old=5))
        self.assertEqual(out, record('New', new=5))
        self.assertEqual(self.assert_same(renamed, old, record('New', new=5)),
                         ('error', 'incompatible accessed types'))

    def test_record_alias_does_not_match_writer_alias(self):
        writer = {'type': 'record', 'name': 'W', 'aliases': ['R'], 'fields': []}
        reader = {'type': 'record', 'name': 'R', 'fields': []}
        self.assertEqual(self.assert_same(writer, reader, record('W')),
                         ('error', 'incompatible accessed types'))

    def test_first_compatible_branch_wins_and_does_not_fall_through(self):
        writer = {'type': 'record', 'name': 'R', 'fields': []}
        reader = [
            {'type': 'record', 'name': 'Needs', 'aliases': ['R'],
             'fields': [{'name': 'required', 'type': 'long'}]},
            {'type': 'record', 'name': 'R', 'fields': []},
        ]
        self.assertEqual(self.assert_same(writer, reader, record('R')),
                         ('error', 'missing required field: required'))

    def test_field_alias_order_prefers_literal_name(self):
        writer = {'type': 'record', 'name': 'R', 'fields': [
            {'name': 'a', 'type': 'long'}, {'name': 'b', 'type': 'long'}]}
        reader = {'type': 'record', 'name': 'R', 'fields': [
            {'name': 'a', 'aliases': ['b'], 'type': 'long'}]}
        _, out = both(writer, reader, record('R', a=1, b=2))
        self.assertEqual(out, record('R', a=1))

    def test_reader_union_selects_by_name_not_position(self):
        writer = [{'type': 'record', 'name': 'A', 'fields': [{'name': 'x', 'type': 'long'}]},
                  {'type': 'record', 'name': 'B', 'fields': [{'name': 'x', 'type': 'long'}]}]
        reader = [writer[1], writer[0]]
        for tag in ('A', 'B'):
            _, out = both(writer, reader, union(tag, record(tag, x=3)))
            self.assertEqual(out['$branch'], tag)
            self.assertEqual(out['value']['$type'], tag)

    def test_default_values_are_independent_at_every_path(self):
        writer = {'type': 'record', 'name': 'R', 'fields': []}
        reader = {'type': 'record', 'name': 'R', 'fields': [
            {'name': 'extra', 'type': {'type': 'record', 'name': 'D', 'fields': [
                {'name': 'x', 'type': 'long'}]}, 'default': record('D', x=8)}]}
        _, first = both(writer, reader, record('R'))
        _, second = both(writer, reader, record('R'))
        first['fields']['extra']['fields']['x'] = 99
        self.assertEqual(second['fields']['extra']['fields']['x'], 8)

    def test_primitive_mismatch_and_missing_field_messages(self):
        self.assertEqual(self.assert_same('long', 'string', 1),
                         ('error', 'incompatible accessed types'))
        self.assertEqual(self.assert_same('long', {'type': 'record', 'name': 'R',
                                                   'fields': [{'name': 'x', 'type': 'long'}]}, 1),
                         ('error', 'incompatible accessed types'))

    def test_deep_finite_recursion_hand_calculated(self):
        for depth in range(6):
            value = record('Node', x=0, next=union('null', None))
            expected = record('Node', x=0, quality='raw', next=union('null', None))
            for number in range(1, depth + 1):
                value = record('Node', x=number, next=union('Node', value))
                expected = record('Node', x=number, quality='raw',
                                  next=union('Node', expected))
            _, out = both(node_schema(), node_schema(True), value)
            self.assertEqual(out, expected)

    def test_empty_value_list_never_touches_graph(self):
        program = schema2.load_graph(schema2.dump_graph(compile_plan('long', 'string')))
        self.assertEqual([schema2.execute(program, v) for v in []], [])

    def test_writer_union_inside_reader_union(self):
        writer = [{'type': 'record', 'name': 'A', 'fields': []},
                  {'type': 'record', 'name': 'B', 'fields': []}, 'null']
        reader = ['null', {'type': 'record', 'name': 'B', 'fields': []},
                  {'type': 'record', 'name': 'A', 'fields': []}]
        for value in (union('A', record('A')), union('B', record('B')),
                      union('null', None)):
            _, out = both(writer, reader, value)
            self.assertEqual(out['$branch'], value['$branch'])

    def test_compiled_graph_is_independent_of_database_and_mutability(self):
        writer, reader = event_schema(), event_reader()
        first = compile_plan(writer, reader)
        second = compile_plan(writer, reader)
        self.assertEqual(first, second)
        text = schema2.dump_graph(first)
        fresh = union('A', record('A', x=47))
        self.assertEqual(schema2.execute(schema2.load_graph(text), fresh), fresh)
        fresh['value']['fields']['x'] = 1
        self.assertEqual(schema2.execute(schema2.load_graph(text),
                                         union('A', record('A', x=47))),
                         union('A', record('A', x=47)))


if __name__ == '__main__':
    unittest.main()
