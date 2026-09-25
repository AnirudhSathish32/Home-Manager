-- Model provenance: runs are reusable only for the same server-reported model identity.
ALTER TABLE parse_runs ADD COLUMN model_identity TEXT;
ALTER TABLE reasoning_runs ADD COLUMN model_identity TEXT;
CREATE TABLE model_identities (
    fingerprint TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    base_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    first_seen TEXT NOT NULL
);
-- One row per model request, including failed and cancelled requests.
CREATE TABLE model_runs (
    id INTEGER PRIMARY KEY,
    task TEXT NOT NULL,
    owner_id TEXT,
    model_id TEXT NOT NULL,
    model_identity TEXT,
    base_url TEXT NOT NULL,
    prompt_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    time_to_first_token_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    prompt_eval_ms REAL,
    generation_ms REAL,
    total_ms REAL NOT NULL,
    prompt_tokens_per_second REAL,
    generation_tokens_per_second REAL,
    metrics_source TEXT NOT NULL,
    input_bytes INTEGER NOT NULL,
    output_bytes INTEGER NOT NULL,
    finish_reason TEXT,
    status TEXT NOT NULL,
    error_category TEXT
);
CREATE INDEX model_runs_owner ON model_runs(owner_id, started_at);
CREATE INDEX model_runs_started ON model_runs(started_at);
PRAGMA user_version=10;
