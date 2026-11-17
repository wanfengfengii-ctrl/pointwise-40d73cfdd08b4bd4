import unittest

from warehouse import ResolutionError, record, union
from warehouse import schema2


def graph():
    # A hand-authored native action graph; no schema descriptions are inputs.
    return {'root': 'cell', 'nodes': {
        'cell': {'op': 'check', 'kind': 'record', 'name': 'Cell', 'next': 'out'},
        'out': {'op': 'record', 'name': 'Packet',
                'fields': [['payload', 'payload'], ['tail', 'tail']]},
        'payload': {'op': 'get', 'field': 'payload', 'next': 'integer'},
        'integer': {'op': 'check', 'kind': 'long', 'next': 'copy'},
        'tail': {'op': 'get', 'field': 'tail', 'next': 'choose'},
        'choose': {'op': 'switch', 'axis': '$branch',
                   'cases': {'null': 'copy', 'Cell': 'wrap'}, 'otherwise': 'bad'},
        'wrap': {'op': 'union', 'tag': 'Packet', 'next': 'unwrap'},
        'unwrap': {'op': 'unwrap', 'next': 'recur'},
        'recur': {'op': 'call', 'target': 'cell'},
        'copy': {'op': 'copy'},
        'bad': {'op': 'fail', 'message': 'unsupported tag'},
    }}


class TestSchema2(unittest.TestCase):
    def test_recursive_actions_survive_serialization(self):
        program = schema2.load_graph(schema2.dump_graph(graph()))
        for number in (2, 17):
            value = record('Cell', payload=number, tail=union('Cell',
                record('Cell', payload=-1, tail=union('null', None))))
            expected = record('Packet', payload=number, tail=union('Packet',
                record('Packet', payload=-1, tail=union('null', None))))
            self.assertEqual(schema2.execute(program, value), expected)
        bad = record('Cell', payload=2, tail=union('Unknown', None))
        with self.assertRaisesRegex(ResolutionError, 'unsupported tag'):
            schema2.execute(program, bad)

    def test_composition_and_default_are_explicit(self):
        program = {'root': 'compose', 'nodes': {
            'compose': {'op': 'compose', 'first': 'intermediate', 'then': 'project'},
            'intermediate': {'op': 'record', 'name': 'Intermediate',
                             'fields': [['saved', 'copy'], ['default', 'default']]},
            'copy': {'op': 'copy'},
            'default': {'op': 'const', 'value': 'unknown'},
            'project': {'op': 'get', 'field': 'saved', 'next': 'copy'},
        }}
        value = union('A', record('A', x=4))
        out = schema2.execute(schema2.load_graph(schema2.dump_graph(program)), value)
        self.assertEqual(out, value)
        out['value']['fields']['x'] = 5
        self.assertEqual(value['value']['fields']['x'], 4)
        program['root'] = 'intermediate'
        self.assertEqual(schema2.execute(program, value)['fields']['default'], 'unknown')

    def test_branch_identity_and_lazy_failure(self):
        program = {'root': 'select', 'nodes': {
            'select': {'op': 'switch', 'axis': '$type',
                       'cases': {'A': 'a', 'B': 'b'}, 'otherwise': 'error'},
            'a': {'op': 'const', 'value': 'first'},
            'b': {'op': 'const', 'value': 'second'},
            'error': {'op': 'fail', 'message': 'wrong name'},
        }}
        self.assertEqual(schema2.execute(program, record('A', x=1)), 'first')
        self.assertEqual(schema2.execute(program, record('B', x=1)), 'second')
        with self.assertRaises(ResolutionError):
            schema2.execute(program, record('C', x=1))

    def test_graph_references_are_validated(self):
        program = graph()
        program['nodes']['recur']['target'] = 'absent'
        with self.assertRaises(ValueError):
            schema2.dump_graph(program)
        for kind, value in [('long', True), ('long', 2**63), ('null', 0),
                            ('string', None)]:
            with self.subTest(kind=kind, value=value), self.assertRaises(ResolutionError):
                schema2.execute({'root': 'check', 'nodes': {
                    'check': {'op': 'check', 'kind': kind, 'next': 'copy'},
                    'copy': {'op': 'copy'}}}, value)
