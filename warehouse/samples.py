"""Small deterministic source data and a complete schema1 warehouse fixture."""
from . import ResolutionError, Warehouse, record, union


def event_schema():
    return [
        {'type': 'record', 'name': 'A', 'fields': [{'name': 'x', 'type': 'long'}]},
        {'type': 'record', 'name': 'B', 'fields': [{'name': 'x', 'type': 'long'}]},
        'string',
    ]


def event_reader():
    a, b, _ = event_schema()
    return [b, a]


def node_schema(extra=False):
    fields = [
        {'name': 'x', 'type': 'long'},
        {'name': 'next', 'type': ['null', 'Node']},
    ]
    if extra:
        fields.append({'name': 'quality', 'type': 'string', 'default': 'raw'})
    return {'type': 'record', 'name': 'Node', 'fields': fields}


def chain():
    return record('Node', x=4, next=union('Node',
                  record('Node', x=9, next=union('null', None))))


def seed(path=':memory:'):
    """Return an open warehouse plus IDs; path may point to an empty local file."""
    wh = Warehouse(path)
    writer = wh.register('events', event_schema())
    reader = wh.register('read-events', event_reader())
    accepted = wh.append('source-001', writer,
                         [union('A', record('A', x=7)), union('B', record('B', x=8))])
    job = wh.create_job(accepted['batch_id'], 'read-events')
    run = wh.run(job)
    wh.register('read-events', event_schema())  # Existing job remains pinned.
    nwriter = wh.register('nodes', node_schema())
    nreader = wh.register('read-nodes', node_schema(True))
    nbatch = wh.append('source-002', nwriter, [chain()])
    njob = wh.create_job(nbatch['batch_id'], nreader)
    wh.run(njob)
    empty = wh.append('source-empty', writer, [])
    empty_job = wh.create_job(empty['batch_id'], reader)
    wh.run(empty_job)
    rejected = wh.append('source-incompatible', writer, [union('string', 'late')])
    failed_job = wh.create_job(rejected['batch_id'], reader)
    try:
        wh.run(failed_job)
    except ResolutionError:
        pass
    else:
        raise AssertionError('sample incompatible value unexpectedly resolved')
    pending_job = wh.create_job(accepted['batch_id'], reader)
    return wh, {'failed_job': failed_job, 'pending_job': pending_job, 'writer': writer, 'reader': reader, 'batch': accepted['batch_id'],
                'job': job, 'run': run['run_id'], 'node_job': njob, 'empty_job': empty_job}


def main():
    import argparse
    import json
    parser = argparse.ArgumentParser(description='Create a complete schema1 sample warehouse')
    parser.add_argument('database')
    args = parser.parse_args()
    wh, ids = seed(args.database)
    try:
        print(json.dumps(ids, sort_keys=True))
    finally:
        wh.close()


if __name__ == '__main__':
    main()
