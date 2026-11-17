"""The shared schema grammar and write-value validator; no writer/reader resolver."""
import copy
import re

from .errors import SchemaError

PRIMITIVES = frozenset(('null', 'long', 'string'))
NAME = re.compile(r'[A-Za-z_][A-Za-z0-9_.]*\Z')


def named(value):
    return isinstance(value, str) and NAME.fullmatch(value) is not None


def record(name, **fields):
    return {'$type': name, 'fields': fields}


def union(branch, value):
    return {'$branch': branch, 'value': value}


class Schema:
    def __init__(self, body):
        self.body = copy.deepcopy(body)
        self.names = {}
        self._collect(self.body)
        self._check(self.body)
        self._defaults(self.body)

    def _collect(self, node):
        if isinstance(node, list):
            for child in node:
                self._collect(child)
        elif isinstance(node, dict):
            if set(node) - {'type', 'name', 'aliases', 'fields'}:
                raise SchemaError('unknown record property')
            if node.get('type') != 'record' or not named(node.get('name')):
                raise SchemaError('expected named record')
            name = node['name']
            if name in PRIMITIVES or name in self.names:
                raise SchemaError('duplicate or reserved record name: ' + name)
            self.names[name] = node
            fields = node.get('fields')
            if not isinstance(fields, list):
                raise SchemaError('fields must be a list')
            for field in fields:
                if not isinstance(field, dict) or 'type' not in field:
                    raise SchemaError('invalid field')
                self._collect(field['type'])
        elif not isinstance(node, str):
            raise SchemaError('invalid schema node')

    @staticmethod
    def _aliases(obj):
        aliases = obj.get('aliases', [])
        if not isinstance(aliases, list) or any(not named(a) for a in aliases):
            raise SchemaError('invalid aliases')
        if len(set(aliases)) != len(aliases):
            raise SchemaError('duplicate alias')
        return aliases

    def deref(self, node):
        if isinstance(node, str) and node not in PRIMITIVES:
            try:
                return self.names[node]
            except KeyError:
                raise SchemaError('undefined name: ' + node) from None
        return node

    def tag(self, node):
        node = self.deref(node)
        return node['name'] if isinstance(node, dict) else node

    def _check(self, node):
        if isinstance(node, str):
            self.deref(node)
        elif isinstance(node, list):
            if not node or any(isinstance(b, list) for b in node):
                raise SchemaError('empty or nested union')
            tags = [self.tag(b) for b in node]
            if len(set(tags)) != len(tags):
                raise SchemaError('duplicate union branch')
            for branch in node:
                self._check(branch)
        else:
            self._aliases(node)
            claimed = set()
            for field in node['fields']:
                if set(field) - {'name', 'type', 'aliases', 'default'}:
                    raise SchemaError('unknown field property')
                name = field.get('name')
                if not named(name):
                    raise SchemaError('invalid field name')
                keys = [name] + self._aliases(field)
                if len(set(keys)) != len(keys) or claimed.intersection(keys):
                    raise SchemaError('ambiguous field name or alias')
                claimed.update(keys)
                self._check(field['type'])

    def _defaults(self, node):
        if isinstance(node, list):
            for branch in node:
                self._defaults(branch)
        elif isinstance(node, dict):
            for field in node['fields']:
                if 'default' in field:
                    self.validate(field['default'], field['type'])
                self._defaults(field['type'])

    def validate(self, value, node=None):
        # Explicit stack also validates deeply nested finite write values.
        pending = [(self.body if node is None else node, value)]
        while pending:
            typ, val = pending.pop()
            typ = self.deref(typ)
            if isinstance(typ, list):
                if not isinstance(val, dict) or set(val) != {'$branch', 'value'}:
                    raise SchemaError('union requires explicit branch')
                branches = {self.tag(b): b for b in typ}
                tag = val['$branch']
                if not isinstance(tag, str) or tag not in branches:
                    raise SchemaError('unknown union branch')
                pending.append((branches[tag], val['value']))
            elif isinstance(typ, dict):
                if (not isinstance(val, dict) or set(val) != {'$type', 'fields'}
                        or val['$type'] != typ['name']
                        or not isinstance(val['fields'], dict)):
                    raise SchemaError('record identity or shape mismatch')
                expected = {f['name'] for f in typ['fields']}
                if set(val['fields']) != expected:
                    raise SchemaError('write fields must match exactly')
                pending.extend((f['type'], val['fields'][f['name']])
                               for f in reversed(typ['fields']))
            elif typ == 'null':
                if val is not None:
                    raise SchemaError('expected null')
            elif typ == 'long':
                if type(val) is not int or not -(2**63) <= val < 2**63:
                    raise SchemaError('expected signed 64-bit integer')
            elif typ == 'string':
                if not isinstance(val, str):
                    raise SchemaError('expected string')
        return copy.deepcopy(value)
