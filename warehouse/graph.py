"""Compile a schema1-style writer/reader revision pair into a schema2 action graph.

The compiler is a pure, offline transformation.  It reads the shared schema
grammar (``warehouse.schema``) only to interpret record identity, aliases and
field layouts; it never imports ``warehouse.schema1`` and never executes a
stored value.  Named identity drives every branch: writer union branches are
selected by ``$branch`` tag through ``switch``, reader unions are lowered to
their first statically compatible named branch, and reader field aliases point
at the matched writer field.  Recursion becomes shared action-node references.
"""
from .schema import Schema


class _Compiler:
    def __init__(self, writer_body, reader_body):
        self.writer = Schema(writer_body)
        self.reader = Schema(reader_body)
        self.nodes = {}
        self.entries = {}
        self.counter = 0

    def build(self):
        root = self.action(self.writer.body, self.reader.body)
        return {'root': root, 'nodes': self.nodes}

    def _ident(self):
        ident = 'a%d' % self.counter
        self.counter += 1
        return ident

    def _add(self, op, **props):
        ident = self._ident()
        node = {'op': op}
        node.update(props)
        self.nodes[ident] = node
        return ident

    def _fail(self, message):
        return self._add('fail', message=message)

    def action(self, wnode, rnode):
        wn, rn = self.writer.deref(wnode), self.reader.deref(rnode)
        key = (id(wn), id(rn))
        if key in self.entries:
            # Shared reference: recursive graphs stay finite and reusable.
            return self.entries[key]
        ident = self._ident()
        self.entries[key] = ident
        self.nodes[ident] = None  # reserved for the recursive reference
        self.nodes[ident] = self._make(wn, rn)
        return ident

    def compatible(self, wnode, rnode):
        wn, rn = self.writer.deref(wnode), self.reader.deref(rnode)
        if isinstance(wn, dict) and isinstance(rn, dict):
            return wn['name'] in [rn['name']] + rn.get('aliases', [])
        return isinstance(wn, str) and wn == rn

    def _make(self, wn, rn):
        if isinstance(wn, list):
            # Writer union: dispatch on the actual named branch, never an index.
            cases = {}
            for branch in wn:
                tag = self.writer.tag(branch)
                inner = self.action(branch, rn)
                cases[tag] = self._add('unwrap', next=inner)
            otherwise = self._fail('unknown union branch')
            return {'op': 'switch', 'axis': '$branch',
                    'cases': cases, 'otherwise': otherwise}

        if isinstance(rn, list):
            # Reader union: the first compatible named branch, fixed at compile time.
            branch = next((b for b in rn if self.compatible(wn, b)), None)
            if branch is None:
                return {'op': 'fail', 'message': 'no compatible reader branch'}
            inner = self.action(wn, branch)
            return {'op': 'union', 'tag': self.reader.tag(branch), 'next': inner}

        if not self.compatible(wn, rn):
            return {'op': 'fail', 'message': 'incompatible accessed types'}

        if isinstance(rn, str):
            return {'op': 'copy'}

        # Both sides are records with compatible identity: project reader fields.
        wfields = {field['name']: field for field in wn['fields']}
        plan = []
        for field in rn['fields']:
            match = next((name for name in [field['name']] + field.get('aliases', [])
                          if name in wfields), None)
            if match is None and 'default' not in field:
                # schema1 raises this before descending into any sibling field.
                return {'op': 'fail',
                        'message': 'missing required field: ' + field['name']}
            plan.append((field, match))
        fields = []
        for field, match in plan:
            if match is None:
                child = self._add('const', value=field['default'])
            else:
                inner = self.action(wfields[match]['type'], field['type'])
                child = self._add('get', field=match, next=inner)
            fields.append([field['name'], child])
        return {'op': 'record', 'name': rn['name'], 'fields': fields}


def compile_plan(writer_body, reader_body):
    """Return a complete, validated JSON action graph for one revision pair."""
    from .schema2 import validate_graph
    return validate_graph(_Compiler(writer_body, reader_body).build())
