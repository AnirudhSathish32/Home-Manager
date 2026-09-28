-- Classifier + type-specific extraction runs. result_json holds validated, normalized
-- values with evidence; publication_json names the canonical record it produced.
CREATE TABLE extraction_runs (
    id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL,
    document_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    publication_json TEXT,
    error TEXT
);
CREATE INDEX extraction_source ON extraction_runs(parse_run_id, created_at);
PRAGMA user_version=12;
