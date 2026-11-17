import json

from .samples import seed


def main():
    wh, ids = seed()
    try:
        old = wh.results(ids['job'])
        wh.run(ids['job'])
        assert wh.results(ids['job'])['reader_revision'] == ids['reader']
        assert old['values'] == wh.results(ids['job'])['values']
        print(json.dumps({
            'events': wh.results(ids['job']),
            'recursive': wh.results(ids['node_job']),
            'empty': wh.results(ids['empty_job']),
            'schema_revisions': len(wh.catalog.revisions()),
        }, ensure_ascii=False, sort_keys=True))
    finally:
        wh.close()


if __name__ == '__main__':
    main()
