CREATE TABLE analysis_reviews (
    reasoning_run_id TEXT PRIMARY KEY REFERENCES reasoning_runs(id),
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT
);
PRAGMA user_version=9;
