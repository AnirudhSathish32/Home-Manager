CREATE TABLE parse_runs (
    id TEXT PRIMARY KEY,
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    parser_version TEXT NOT NULL,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT,
    result_json TEXT,
    preview_hash TEXT
);
CREATE INDEX parse_runs_blob ON parse_runs(blob_hash, created_at);
CREATE UNIQUE INDEX parse_runs_active ON parse_runs(blob_hash, parser_version, options_json)
    WHERE status IN ('queued', 'running');
PRAGMA user_version = 2;
