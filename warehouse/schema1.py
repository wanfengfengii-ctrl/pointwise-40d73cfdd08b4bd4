"""Offline dependency v1: implicit writer/reader resolution."""
import copy

from .errors import ResolutionError
from .schema import Schema, record, union


def compatible(writer, reader, wnode, rnode):
    wnode, rnode = writer.deref(wnode), reader.deref(rnode)
    if isinstance(wnode, dict) and isinstance(rnode, dict):
        return wnode['name'] in [rnode['name']] + rnode.get('aliases', [])
    return isinstance(wnode, str) and wnode == rnode


def resolve(writer_body, reader_body, value):
    writer, reader = Schema(writer_body), Schema(reader_body)
    writer.validate(value)
    output = [None]
    pending = [(writer.body, reader.body, value, output, 0)]
    while pending:
        wn, rn, val, target, key = pending.pop()
        wn, rn = writer.deref(wn), reader.deref(rn)
        if isinstance(wn, list):
            branch = next(b for b in wn if writer.tag(b) == val['$branch'])
            pending.append((branch, rn, val['value'], target, key))
            continue
        if isinstance(rn, list):
            branch = next((b for b in rn if compatible(writer, reader, wn, b)), None)
            if branch is None:
                raise ResolutionError('no compatible reader branch')
            wrapped = union(reader.tag(branch), None)
            target[key] = wrapped
            pending.append((wn, branch, val, wrapped, 'value'))
            continue
        if not compatible(writer, reader, wn, rn):
            raise ResolutionError('incompatible accessed types')
        if isinstance(rn, str):
            target[key] = copy.deepcopy(val)
            continue
        result = record(rn['name'])
        target[key] = result
        wfields = {f['name']: f for f in wn['fields']}
        tasks = []
        for rf in rn['fields']:
            match = next((n for n in [rf['name']] + rf.get('aliases', [])
                          if n in wfields), None)
            if match is None:
                if 'default' not in rf:
                    raise ResolutionError('missing required field: ' + rf['name'])
                result['fields'][rf['name']] = copy.deepcopy(rf['default'])
            else:
                tasks.append((wfields[match]['type'], rf['type'],
                              val['fields'][match], result['fields'], rf['name']))
        pending.extend(reversed(tasks))
    return output[0]
