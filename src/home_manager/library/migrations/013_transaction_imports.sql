-- Deterministic CSV/XLSX imports. Re-importing the same export inserts nothing new:
-- transaction fingerprints de-duplicate, and each import keeps its own evidence rows.
CREATE TABLE transaction_imports (
    id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    mapping_json TEXT NOT NULL,
    parsed INTEGER NOT NULL,
    inserted INTEGER NOT NULL,
    duplicates INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    issues_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX transaction_imports_document ON transaction_imports(document_id, created_at);
PRAGMA user_version=13;
