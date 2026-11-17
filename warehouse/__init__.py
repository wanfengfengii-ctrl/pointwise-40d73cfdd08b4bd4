from .archive import Archive
from .catalog import Catalog
from .db import Database
from .jobs import Jobs
from .publication import Publications
from .schema import record, union
from .errors import Conflict, NotFound, ResolutionError, SchemaError, WarehouseError


class Warehouse:
    def __init__(self, path=':memory:'):
        self.db = Database(path)
        self.catalog = Catalog(self.db)
        self.archive = Archive(self.db, self.catalog)
        self.publications = Publications(self.db)
        self.jobs = Jobs(self.db, self.catalog, self.archive, self.publications)

    def register(self, name, schema):
        return self.catalog.register(name, schema)

    def append(self, request_id, writer_revision, values):
        return self.archive.append(request_id, writer_revision, values)

    def create_job(self, batch_id, reader_name_or_revision):
        return self.jobs.create_job(batch_id, reader_name_or_revision)

    def run(self, job_id, before_commit=None):
        return self.jobs.run(job_id, before_commit)

    def results(self, job_id, run_id=None):
        return self.publications.results(job_id, run_id)

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
