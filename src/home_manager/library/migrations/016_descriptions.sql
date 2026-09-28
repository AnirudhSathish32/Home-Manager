-- Short labels for what a document is about, such as a shopping trip's contents.
-- The model proposes one per receipt; the user's own label for a document always wins.
ALTER TABLE receipts ADD COLUMN description TEXT;
CREATE TABLE document_descriptions (
    document_id INTEGER PRIMARY KEY REFERENCES occurrences(id),
    description TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=16;
