ALTER TABLE occurrences ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'external';
CREATE TABLE managed_files (
 document_id INTEGER NOT NULL REFERENCES occurrences(id),
 blob_hash TEXT NOT NULL REFERENCES blobs(hash),
 relative_path TEXT NOT NULL UNIQUE,
 folder TEXT NOT NULL,
 reason TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(document_id,blob_hash)
);
CREATE TABLE managed_organization_intents (
 id TEXT PRIMARY KEY,
 document_id INTEGER NOT NULL REFERENCES occurrences(id),
 blob_hash TEXT NOT NULL REFERENCES blobs(hash),
 source_path TEXT,
 target_path TEXT NOT NULL,
 folder TEXT NOT NULL,
 reason TEXT NOT NULL,
 action TEXT NOT NULL,
 status TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 error TEXT
);
CREATE UNIQUE INDEX managed_active_intent ON managed_organization_intents(document_id,blob_hash)
 WHERE status IN ('pending','blocked');
CREATE TABLE managed_organization_events (
 id INTEGER PRIMARY KEY,
 intent_id TEXT NOT NULL UNIQUE REFERENCES managed_organization_intents(id),
 document_id INTEGER NOT NULL REFERENCES occurrences(id),
 blob_hash TEXT NOT NULL REFERENCES blobs(hash),
 source_path TEXT,
 target_path TEXT NOT NULL,
 action TEXT NOT NULL,
 created_at TEXT NOT NULL
);
PRAGMA user_version=8;
