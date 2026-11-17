"""Offline dependency v2: execute explicit JSON action graphs.

This module accepts no schemas and performs no implicit schema resolution.
"""
import copy
import json

from .errors import ResolutionError
from .schema import named, record, union

OPS = {
    'copy': (), 'const': (), 'fail': (), 'check': ('next',),
    'get': ('next',), 'unwrap': ('next',), 'union': ('next',),
    'call': ('target',), 'compose': ('first', 'then'),
    'record': (), 'switch': (),
}


def validate_graph(graph):
    if not isinstance(graph, dict) or set(graph) != {'root', 'nodes'}:
        raise ValueError('graph requires root and nodes')
    nodes = graph['nodes']
    if not isinstance(nodes, dict) or not nodes or any(not isinstance(k, str) for k in nodes):
        raise ValueError('nodes must have string identifiers')
    if not isinstance(graph['root'], str) or graph['root'] not in nodes:
        raise ValueError('missing root')
    for node in nodes.values():
        if not isinstance(node, dict) or node.get('op') not in OPS:
            raise ValueError('unknown action')
        op = node['op']
        refs = [node.get(k) for k in OPS[op]]
        if op == 'const' and 'value' not in node:
            raise ValueError('constant requires value')
        if op == 'fail' and not isinstance(node.get('message'), str):
            raise ValueError('failure requires message')
        if op == 'get' and not isinstance(node.get('field'), str):
            raise ValueError('field required')
        if op == 'check':
            if node.get('kind') not in ('null', 'long', 'string', 'record', 'union'):
                raise ValueError('invalid check kind')
            if node['kind'] == 'record' and not named(node.get('name')):
                raise ValueError('record check requires name')
        if op in ('record', 'union') and not named(node.get('name' if op == 'record' else 'tag')):
            raise ValueError('name or tag required')
        if op == 'record':
            fields = node.get('fields')
            if (not isinstance(fields, list)
                    or any(not isinstance(p, list) or len(p) != 2
                           or not isinstance(p[0], str) for p in fields)):
                raise ValueError('record fields must be name/action pairs')
            if len({p[0] for p in fields}) != len(fields):
                raise ValueError('duplicate output field')
            refs.extend(p[1] for p in fields)
        if op == 'switch':
            if node.get('axis') not in ('$branch', '$type'):
                raise ValueError('invalid switch axis')
            if not isinstance(node.get('cases'), dict):
                raise ValueError('cases required')
            refs.extend(node['cases'].values())
            refs.append(node.get('otherwise'))
        if any(not isinstance(ref, str) or ref not in nodes for ref in refs):
            raise ValueError('dangling action reference')
    json.dumps(graph, allow_nan=False)
    return graph


def dump_graph(graph):
    validate_graph(graph)
    return json.dumps(graph, sort_keys=True, separators=(',', ':'), allow_nan=False)


def load_graph(text):
    return validate_graph(json.loads(text))


def execute(graph, value):
    validate_graph(graph)
    nodes = graph['nodes']
    result = [None]
    stack = [('eval', graph['root'], value, result, 0)]
    while stack:
        mode, ident, val, target, key = stack.pop()
        if mode == 'continue':
            stack.append(('eval', ident, val[0], target, key))
            continue
        node = nodes[ident]
        op = node['op']
        if op == 'copy':
            target[key] = copy.deepcopy(val)
        elif op == 'const':
            target[key] = copy.deepcopy(node['value'])
        elif op == 'fail':
            raise ResolutionError(node['message'])
        elif op == 'call':
            stack.append(('eval', node['target'], val, target, key))
        elif op == 'compose':
            cell = [None]
            stack.append(('continue', node['then'], cell, target, key))
            stack.append(('eval', node['first'], val, cell, 0))
        elif op == 'check':
            kind = node['kind']
            valid = (
                (kind == 'null' and val is None)
                or (kind == 'long' and type(val) is int and -(2**63) <= val < 2**63)
                or (kind == 'string' and isinstance(val, str))
                or (kind == 'record' and isinstance(val, dict)
                    and set(val) == {'$type', 'fields'}
                    and val['$type'] == node['name'] and isinstance(val['fields'], dict))
                or (kind == 'union' and isinstance(val, dict)
                    and set(val) == {'$branch', 'value'} and isinstance(val['$branch'], str)))
            if not valid:
                raise ResolutionError('explicit value check failed')
            stack.append(('eval', node['next'], val, target, key))
        elif op == 'get':
            if (not isinstance(val, dict) or not isinstance(val.get('fields'), dict)
                    or node['field'] not in val['fields']):
                raise ResolutionError('explicit field missing: ' + node['field'])
            stack.append(('eval', node['next'], val['fields'][node['field']], target, key))
        elif op == 'unwrap':
            if not isinstance(val, dict) or set(val) != {'$branch', 'value'}:
                raise ResolutionError('expected tagged union')
            stack.append(('eval', node['next'], val['value'], target, key))
        elif op == 'switch':
            tag = val.get(node['axis']) if isinstance(val, dict) else None
            branch = node['cases'].get(tag, node['otherwise']) if isinstance(tag, str) else node['otherwise']
            stack.append(('eval', branch, val, target, key))
        elif op == 'union':
            wrapped = union(node['tag'], None)
            target[key] = wrapped
            stack.append(('eval', node['next'], val, wrapped, 'value'))
        elif op == 'record':
            out = record(node['name'])
            target[key] = out
            for name, child in reversed(node['fields']):
                stack.append(('eval', child, val, out['fields'], name))
    return result[0]
