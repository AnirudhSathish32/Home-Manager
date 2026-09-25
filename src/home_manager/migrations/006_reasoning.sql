CREATE TABLE reasoning_runs (
    id TEXT PRIMARY KEY,
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
CREATE INDEX reasoning_source ON reasoning_runs(parse_run_id, created_at);
PRAGMA user_version=6;
