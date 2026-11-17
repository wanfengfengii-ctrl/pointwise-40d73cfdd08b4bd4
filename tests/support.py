import unittest

from warehouse import Warehouse


class WarehouseCase(unittest.TestCase):
    def setUp(self):
        self.wh = Warehouse()
        self.addCleanup(self.wh.close)

    def count(self, table):
        allowed = {'batches', 'schema_revisions', 'jobs', 'runs', 'publications'}
        if table not in allowed:
            raise ValueError(table)
        return self.wh.db.connection.execute('SELECT count(*) FROM ' + table).fetchone()[0]
