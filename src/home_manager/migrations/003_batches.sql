CREATE TABLE receipt_batches (
    id TEXT PRIMARY KEY,
    source_root TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    skipped INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE receipt_batch_items (
    batch_id TEXT NOT NULL REFERENCES receipt_batches(id),
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    run_id TEXT NOT NULL REFERENCES parse_runs(id),
    reused INTEGER NOT NULL,
    PRIMARY KEY(batch_id, document_id)
);
PRAGMA user_version = 3;
