CREATE TABLE v2_revisions(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, body TEXT NOT NULL);
CREATE TABLE v2_heads(
 name TEXT PRIMARY KEY, revision INTEGER NOT NULL REFERENCES v2_revisions(id));
CREATE TABLE v2_batches(
 id INTEGER PRIMARY KEY, request_id TEXT UNIQUE NOT NULL,
 writer_revision INTEGER NOT NULL REFERENCES v2_revisions(id),
 payload TEXT NOT NULL, receipt TEXT NOT NULL);
CREATE TABLE v2_jobs(
 id INTEGER PRIMARY KEY, batch_id INTEGER NOT NULL REFERENCES v2_batches(id),
 reader_revision INTEGER NOT NULL REFERENCES v2_revisions(id));
CREATE TABLE v2_runs(
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES v2_jobs(id),
 status TEXT NOT NULL CHECK(status IN ('running','succeeded','failed')), error TEXT);
CREATE TABLE v2_publications(
 run_id INTEGER PRIMARY KEY REFERENCES v2_runs(id),
 payload TEXT NOT NULL, receipt TEXT UNIQUE NOT NULL);
CREATE TABLE v2_plans(
 writer_revision INTEGER NOT NULL REFERENCES v2_revisions(id),
 reader_revision INTEGER NOT NULL REFERENCES v2_revisions(id),
 graph TEXT NOT NULL,
 PRIMARY KEY(writer_revision,reader_revision));
