-- Values the user entered on a canonical record (a date the document never printed, a merchant
-- the model missed). Every correction is kept; the latest per field applies, including after a
-- re-extraction rewrites the model's values.
CREATE TABLE record_corrections (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill','income_record')),
    record_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    previous TEXT,
    resolved_issues_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE INDEX record_corrections_record ON record_corrections(record_type, record_id, field, id);

-- A correction also triggers a reconciliation pass; SQLite cannot widen a CHECK in place.
CREATE TABLE reconciliation_runs_v17 (
    id INTEGER PRIMARY KEY,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual','import','extraction','resolution','correction')),
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    receipt_links INTEGER,
    transfers INTEGER,
    refunds INTEGER,
    recurring INTEGER,
    open_issues INTEGER,
    error TEXT
);
INSERT INTO reconciliation_runs_v17 SELECT * FROM reconciliation_runs;
DROP TABLE reconciliation_runs;
ALTER TABLE reconciliation_runs_v17 RENAME TO reconciliation_runs;
CREATE INDEX reconciliation_runs_started ON reconciliation_runs(started_at);
PRAGMA user_version=17;
