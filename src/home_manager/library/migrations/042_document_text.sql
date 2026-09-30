-- Full-text index over saved transcriptions (docs/document-search.md). Rebuildable: library/text_index.py
-- fills it from parse_runs.result_json, so nothing here is the only copy of any text.
-- A passage is a few consecutive lines of one page, with the line IDs that locate it in the transcription.
CREATE TABLE document_passages (
    id INTEGER PRIMARY KEY,
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    ordinal INTEGER NOT NULL,
    line_ids TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (parse_run_id, ordinal)
);
CREATE VIRTUAL TABLE document_passages_fts USING fts5(
    text, content='document_passages', content_rowid='id', tokenize='unicode61 remove_diacritics 2', prefix='2 3'
);
CREATE TRIGGER document_passages_ai AFTER INSERT ON document_passages BEGIN
    INSERT INTO document_passages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER document_passages_ad AFTER DELETE ON document_passages BEGIN
    INSERT INTO document_passages_fts(document_passages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
-- Which readings are indexed, and by which passage rules; a changed version is indexed again.
CREATE TABLE document_index_state (
    parse_run_id TEXT PRIMARY KEY REFERENCES parse_runs(id),
    index_version INTEGER NOT NULL,
    passages INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
);
PRAGMA user_version=42;
