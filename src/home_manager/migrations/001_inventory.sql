CREATE TABLE jobs (
    id TEXT PRIMARY KEY,
    source_root TEXT NOT NULL,
    year INTEGER,
    month INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT
);
CREATE TABLE blobs (
    hash TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE occurrences (
    id INTEGER PRIMARY KEY,
    source_root TEXT NOT NULL,
    path_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    folder_year INTEGER NOT NULL,
    folder_month INTEGER NOT NULL,
    current_hash TEXT NOT NULL REFERENCES blobs(hash),
    source_status TEXT NOT NULL DEFAULT 'present',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_job TEXT NOT NULL REFERENCES jobs(id),
    UNIQUE(source_root, path_key)
);
CREATE TABLE versions (
    id INTEGER PRIMARY KEY,
    occurrence_id INTEGER NOT NULL REFERENCES occurrences(id),
    hash TEXT NOT NULL REFERENCES blobs(hash),
    captured_at TEXT NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    UNIQUE(occurrence_id, hash)
);
CREATE TABLE events (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    hash TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE capture_intents (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    source_root TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    folder_year INTEGER NOT NULL,
    folder_month INTEGER NOT NULL,
    hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL
);
CREATE INDEX events_job ON events(job_id, id);
CREATE INDEX occurrences_root ON occurrences(source_root, folder_year, folder_month);
PRAGMA user_version = 1;
