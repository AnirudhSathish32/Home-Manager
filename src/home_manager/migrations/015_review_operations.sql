-- Review decisions, reconciliation history, backups and assistant runs
-- (docs/ui-design-plan.md §7: B6, B10, B13, B15, B16).

-- A bill's payment state set by the user may name the transaction that paid it.
ALTER TABLE bills ADD COLUMN payment_transaction_id INTEGER REFERENCES transactions(id);

-- The user's decision on an ambiguous match. 'left_unmatched' keeps later
-- reconciliation passes from reopening the same question.
ALTER TABLE reconciliation_issues ADD COLUMN resolution TEXT
    CHECK (resolution IS NULL OR resolution IN ('linked','left_unmatched'));

-- One row per reconciliation pass, with its outcome counts.
CREATE TABLE reconciliation_runs (
    id INTEGER PRIMARY KEY,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual','import','extraction','resolution')),
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
CREATE INDEX reconciliation_runs_started ON reconciliation_runs(started_at);

-- Backups written to a destination outside the managed directory.
CREATE TABLE backups (
    id TEXT PRIMARY KEY,
    destination TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','cancelled','interrupted')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    schema_version INTEGER NOT NULL,
    file_count INTEGER,
    total_bytes INTEGER,
    manifest_sha256 TEXT,
    error TEXT
);

-- Assistant questions, the read-only tool calls that answered them and the checked answer.
CREATE TABLE assistant_runs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
CREATE INDEX assistant_runs_created ON assistant_runs(created_at);
PRAGMA user_version=15;
