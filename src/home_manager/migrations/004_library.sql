ALTER TABLE occurrences ADD COLUMN deleted_at TEXT;
ALTER TABLE jobs ADD COLUMN organization_status TEXT;
ALTER TABLE jobs ADD COLUMN organization_message TEXT;
ALTER TABLE jobs ADD COLUMN organization_batch_id TEXT REFERENCES receipt_batches(id);
CREATE TABLE document_folders (
    document_id INTEGER PRIMARY KEY REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    folder TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE library_events (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
PRAGMA user_version = 4;
