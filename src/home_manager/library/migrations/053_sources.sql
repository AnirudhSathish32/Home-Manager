-- Watched folders outside Library/Inbox (docs/documents.md, "Watched folders"). A scan copies each new or changed file into
-- the library and never moves, renames or deletes the original. path_key is the folder's normalized path, the same value
-- its captures carry in occurrences.source_root.

CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    path_key TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    recursive INTEGER NOT NULL DEFAULT 1 CHECK (recursive IN (0, 1)),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    last_scan_at TEXT,
    last_job TEXT REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
) STRICT;

-- Documents found to be the same: identical bytes at two paths (same_bytes, recorded at capture), or two documents
-- whose records a person matched as one purchase or payment (same_record). Links never merge or delete anything.
-- The pair is stored lower id first, so each pair appears once.
CREATE TABLE occurrence_links (
    id INTEGER PRIMARY KEY,
    occurrence_id INTEGER NOT NULL REFERENCES occurrences(id) ON DELETE CASCADE,
    other_occurrence_id INTEGER NOT NULL REFERENCES occurrences(id) ON DELETE CASCADE,
    reason TEXT NOT NULL CHECK (reason IN ('same_bytes','same_record')),
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    CHECK (occurrence_id < other_occurrence_id),
    UNIQUE (occurrence_id, other_occurrence_id, reason)
) STRICT;
CREATE INDEX occurrence_links_other ON occurrence_links(other_occurrence_id);

-- Identical bytes already captured at two paths get their link now.
INSERT OR IGNORE INTO occurrence_links(occurrence_id,other_occurrence_id,reason,status,created_at)
    SELECT a.id, b.id, 'same_bytes', 'verified', strftime('%Y-%m-%dT%H:%M:%SZ','now')
    FROM occurrences a JOIN occurrences b ON b.current_hash=a.current_hash AND b.id>a.id;

PRAGMA user_version=53;
