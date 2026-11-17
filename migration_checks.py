"""Public migration compatibility checks; no migration or graph compiler."""
import importlib
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

from warehouse import Conflict, ResolutionError, Warehouse, record, union
from warehouse import schema1, schema2
from warehouse.samples import chain, event_schema, node_schema, seed

OLD = ("schema_revisions", "schema_heads", "batches", "jobs", "runs", "publications")


def rows(db, names):
    return {name: [tuple(row) for row in db.connection.execute(
        "SELECT * FROM " + name + " ORDER BY 1")] for name in names}


@contextmanager
def target_only(db):
    jobs = importlib.import_module("warehouse.jobs")
    saved = []
    def forbidden(*args, **kwargs):
        raise AssertionError("schema1 used after upgrade")
    for module, name in ((schema1, "resolve"), (schema1, "compatible"), (jobs, "resolve")):
        if hasattr(module, name):
            saved.append((module, name, getattr(module, name)))
            setattr(module, name, forbidden)
    def authorize(action, table, column, database, origin):
        if action in (sqlite3.SQLITE_READ, sqlite3.SQLITE_INSERT,
                      sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE) and table in OLD:
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    db.connection.set_authorizer(authorize)
    try:
        yield
    finally:
        db.connection.set_authorizer(None)
        for module, name, value in saved:
            setattr(module, name, value)


class MigrationChecks(unittest.TestCase):
    def exercise(self, wh, ids):
        migration = importlib.import_module("warehouse.migration")
        native = importlib.import_module("warehouse.native2")
        audit = rows(wh.db, OLD)
        required_pairs = {tuple(r) for r in wh.db.connection.execute(
            "SELECT DISTINCT b.writer_revision,j.reader_revision FROM jobs j "
            "JOIN batches b ON b.id=j.batch_id")}
        old = wh.results(ids["job"])
        recursive = wh.results(ids["node_job"])
        histories = {j: wh.jobs.runs(j) for j in (
            ids["job"], ids["node_job"], ids["failed_job"], ids["pending_job"])}
        self.assertIsNone(migration.upgrade(wh.db))
        self.assertEqual(wh.db.connection.execute(
            "SELECT value FROM metadata WHERE key='storage_version'").fetchone()[0], "2")
        self.assertEqual(rows(wh.db, OLD), audit)
        plans = wh.db.connection.execute(
            "SELECT writer_revision,reader_revision,graph FROM v2_plans").fetchall()
        self.assertTrue(required_pairs <= {(r[0], r[1]) for r in plans})
        for row in plans:
            schema2.load_graph(row[2])
        for source, target in zip(OLD, ("v2_revisions", "v2_heads", "v2_batches",
                                       "v2_jobs", "v2_runs", "v2_publications")):
            self.assertEqual(rows(wh.db, (target,))[target], audit[source])
        target_tables = [r[0] for r in wh.db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'v2_%'")]
        before = rows(wh.db, target_tables)
        def must_not_run():
            raise AssertionError("repeat upgrade called commit hook")
        migration.upgrade(wh.db, before_commit=must_not_run)
        self.assertEqual(rows(wh.db, target_tables), before)

        with target_only(wh.db):
            self.assertEqual(wh.results(ids["job"]), old)
            self.assertEqual(wh.results(ids["node_job"]), recursive)
            for job, history in histories.items():
                self.assertEqual(wh.jobs.runs(job), history)
            self.assertIsNone(wh.results(ids["pending_job"]))
            self.assertIsNone(wh.results(ids["failed_job"]))
            self.assertEqual(wh.results(ids["empty_job"])["values"], [])
            wh.run(ids["job"])
            self.assertEqual(wh.results(ids["job"])["values"], old["values"])
            self.assertEqual(wh.results(ids["job"])["reader_revision"], ids["reader"])

            batch = wh.archive.get(ids["batch"])
            self.assertEqual(native.append(wh.db, batch["request_id"],
                batch["writer_revision"], batch["values"]),
                {"batch_id": batch["batch_id"], "receipt": batch["receipt"]})
            with self.assertRaises(Conflict):
                native.append(wh.db, batch["request_id"], ids["writer"], [])

            for request, append, values in (
                ("old-new", wh.append, [union("A", record("A", x=19)),
                                       union("B", record("B", x=-4))]),
                ("native-new", lambda *a: native.append(wh.db, *a),
                 [union("B", record("B", x=99)), union("B", record("B", x=99))])):
                accepted = append(request, ids["writer"], values)
                job = wh.create_job(accepted["batch_id"], ids["reader"])
                wh.run(job)
                self.assertEqual(wh.results(job)["values"], values)

            plan = native.get_plan(wh.db, ids["writer"], ids["reader"])
            stored = wh.db.connection.execute(
                "SELECT graph FROM v2_plans WHERE writer_revision=? AND reader_revision=?",
                (ids["writer"], ids["reader"])).fetchone()
            self.assertIsNotNone(stored)
            self.assertEqual(schema2.load_graph(stored[0]), plan)
            restored = schema2.load_graph(schema2.dump_graph(plan))
            fresh = union("A", record("A", x=47))
            self.assertEqual(schema2.execute(restored, fresh), fresh)
            with self.assertRaises(ResolutionError):
                schema2.execute(restored, union("string", "actual bad branch"))
            plan["nodes"].clear()
            self.assertTrue(native.get_plan(wh.db, ids["writer"], ids["reader"])["nodes"])

            nw = wh.register("new-nodes", node_schema())
            nb = native.append(wh.db, "new-chain", nw, [chain()])["batch_id"]
            pinned = []
            for label in ("checked", "verified"):
                reader = node_schema(True)
                reader["fields"][-1]["default"] = label
                rr = native.register(wh.db, "pinned-reader", reader)
                self.assertEqual(wh.catalog.revision("pinned-reader"), rr)
                pinned.append((wh.create_job(nb, rr), label))
            native.register(wh.db, "pinned-reader", "string")
            for job, label in reversed(pinned * 2):
                wh.run(job)
                value = wh.results(job)["values"][0]["fields"]
                self.assertEqual(value["quality"], label)
                self.assertEqual(value["next"]["value"]["fields"]["quality"], label)

            first = [{"type": "record", "name": "Needs", "aliases": ["A"],
                      "fields": [{"name": "z", "type": "long"}]}, event_schema()[0]]
            rr = wh.register("first-only", first)
            ab = wh.append("first-only", ids["writer"],
                           [union("A", record("A", x=1))])["batch_id"]
            bad = wh.create_job(ab, rr)
            previous = wh.results(ids["job"])
            with self.assertRaisesRegex(ResolutionError, "missing required field: z"):
                wh.run(bad)
            self.assertIsNone(wh.results(bad))
            self.assertEqual(wh.jobs.runs(bad)[-1]["status"], "failed")
            self.assertEqual(wh.results(ids["job"]), previous)

            def gate():
                raise RuntimeError("publication gate")
            with self.assertRaisesRegex(RuntimeError, "publication gate"):
                wh.run(ids["job"], before_commit=gate)
            self.assertEqual(wh.results(ids["job"]), previous)
            wh.run(ids["job"])
            self.assertEqual(wh.results(ids["job"])["values"], old["values"])
        self.assertEqual(rows(wh.db, OLD), audit)

    def test_real_upgrade_and_joint_consumption(self):
        wh, ids = seed()
        self.addCleanup(wh.close)
        self.exercise(wh, ids)

    def test_file_rollback_retry_and_reopen(self):
        migration = importlib.import_module("warehouse.migration")
        native = importlib.import_module("warehouse.native2")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "archive.sqlite")
            wh, ids = seed(path)
            try:
                audit = rows(wh.db, OLD)
                tables = [r[0] for r in wh.db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
                def fail():
                    raise RuntimeError("migration gate")
                with self.assertRaisesRegex(RuntimeError, "migration gate"):
                    migration.upgrade(wh.db, before_commit=fail)
                self.assertEqual(rows(wh.db, OLD), audit)
                self.assertEqual(wh.db.connection.execute(
                    "SELECT value FROM metadata WHERE key='storage_version'").fetchone()[0], "1")
                self.assertEqual([r[0] for r in wh.db.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")], tables)
            finally:
                wh.close()
            with Warehouse(path) as wh:
                self.assertEqual(rows(wh.db, OLD), audit)
                wh.run(ids["job"])
                self.exercise(wh, ids)
            with Warehouse(path) as wh, target_only(wh.db):
                self.assertEqual(wh.results(ids["job"])["values"],
                    [union("A", record("A", x=7)), union("B", record("B", x=8))])
                wh.run(ids["job"])
                b = native.append(wh.db, "after-reopen", ids["writer"],
                    [union("B", record("B", x=123))])["batch_id"]
                job = wh.create_job(b, ids["reader"])
                wh.run(job)
                self.assertEqual(wh.results(job)["values"],
                    [union("B", record("B", x=123))])


if __name__ == "__main__":
    unittest.main()
