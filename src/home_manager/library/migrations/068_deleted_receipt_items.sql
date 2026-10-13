-- A user's removed line must stay removed if an unreviewed receipt is read again.
-- The ordinal distinguishes repeated lines with the same description.
CREATE TABLE deleted_receipt_items (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    description TEXT NOT NULL,
    description_key TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    actor TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(receipt_id, description_key, ordinal)
) STRICT;
CREATE INDEX deleted_receipt_items_receipt ON deleted_receipt_items(receipt_id);
PRAGMA user_version=68;
