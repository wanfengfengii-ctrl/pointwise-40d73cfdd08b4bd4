"""Upgrade a real legacy file, then show historical, recursive and native results."""
import json
import tempfile
from pathlib import Path

from . import Warehouse, record, union
from .migration import upgrade
from .native2 import append, get_plan, register
from .samples import chain, node_schema, seed


def main():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / 'legacy.sqlite')
        legacy, ids = seed(path)
        before = {
            'events': legacy.results(ids['job']),
            'recursive': legacy.results(ids['node_job']),
            'empty': legacy.results(ids['empty_job']),
            'revisions': len(legacy.catalog.revisions()),
        }
        legacy.close()

        with Warehouse(path) as wh:
            upgrade(wh.db)
            assert wh.db.storage_version() == '2'
            migrated = {
                'events': wh.results(ids['job']),
                'recursive': wh.results(ids['node_job']),
                'empty': wh.results(ids['empty_job']),
            }
            for name in migrated:
                assert migrated[name] == before[name]

            # A single native writer batch consumed under two pinned recursive readers.
            writer = register(wh.db, 'demo-nodes', node_schema())
            batch = append(wh.db, 'demo-chain', writer, [chain()])['batch_id']
            pinned = []
            for label in ('checked', 'verified'):
                schema = node_schema(True)
                schema['fields'][-1]['default'] = label
                reader = register(wh.db, 'demo-reader', schema)
                job = wh.create_job(batch, reader)
                wh.run(job)
                pinned.append({'reader': label, 'job': job,
                               'values': wh.results(job)['values']})

            # Old-interface and native writes continue in the same target tables.
            accepted = wh.append('demo-old', ids['writer'], [
                union('A', record('A', x=11)), union('B', record('B', x=12))])
            old_job = wh.create_job(accepted['batch_id'], ids['reader'])
            wh.run(old_job)
            native_job = wh.create_job(
                append(wh.db, 'demo-native', ids['writer'],
                       [union('B', record('B', x=21))])['batch_id'], ids['reader'])
            wh.run(native_job)

            plan = get_plan(wh.db, ids['writer'], ids['reader'])
            print(json.dumps({
                'events': migrated['events'],
                'recursive': migrated['recursive'],
                'empty': migrated['empty'],
                'schema_revisions': before['revisions'],
                'fixed_recursive_defaults': pinned,
                'old_interface_write': wh.results(old_job),
                'native_continuation': wh.results(native_job),
                'plan_node_count': len(plan['nodes']),
            }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
