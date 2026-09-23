CREATE TABLE organization_runs (
    id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_folder TEXT,
    error TEXT
);
CREATE INDEX organization_document ON organization_runs(document_id, blob_hash, created_at);
PRAGMA user_version=5;
