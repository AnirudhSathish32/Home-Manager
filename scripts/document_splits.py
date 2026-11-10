"""Counts of the documents merged under one Inbox name, and of those the upgrade split (specs/inbox-document-identity FR-09).

Usage:  python scripts/document_splits.py "<path to inventory.sqlite3>"

Opens the file read-only, copies it into memory with SQLite's backup API, closes the file and counts on the copy; nothing is written.
Prints four lines of counts and fixed words, no file name, path, merchant, hash, amount or date, so the output can be pasted as it is.
The user runs it on their own library; it is explained in docs/development.md "Database checks".
"""
from pathlib import Path
import sqlite3
import sys

# A version of an Inbox document was merged in when the version before it was filed out of the Inbox before this one was captured
# (docs/documents.md "The managed library"). This lists every version from the first merged-in one on: the versions that belong to a
# document of their own. The step library/migrations/080_split_merged_documents.sql repeats the part before the last SELECT, since a
# migration can't import; tests/test_document_split.py holds the two together.
MERGED_IN = """
WITH ordered AS (
    SELECT v.occurrence_id, v.id AS version_id, v.hash, v.captured_at,
           LAG(v.hash) OVER (PARTITION BY v.occurrence_id ORDER BY v.captured_at, v.id) AS previous_hash
    FROM versions v JOIN occurrences o ON o.id = v.occurrence_id
    WHERE o.source_kind = 'inbox'
), marked AS (
    SELECT ordered.*, EXISTS (SELECT 1 FROM managed_organization_events e
                              WHERE e.document_id = ordered.occurrence_id AND e.blob_hash = ordered.previous_hash
                                AND substr(e.source_path, 1, 6) = 'Inbox/' AND substr(e.target_path, 1, 6) <> 'Inbox/'
                                AND e.created_at < ordered.captured_at) AS merged
    FROM ordered
), cut AS (
    SELECT marked.*, SUM(merged) OVER (PARTITION BY occurrence_id ORDER BY captured_at, version_id) AS run FROM marked
)
SELECT * FROM cut WHERE run > 0
"""

# Version k stayed a version although its predecessor was filed: the predecessor has a Library copy outside the Inbox but no filing
# event at all (a blocked or never-finished move), so MERGED_IN can't tell. These are the versions the report counts as incomplete.
HISTORY_INCOMPLETE = """
WITH ordered AS (
    SELECT v.occurrence_id, v.id AS version_id,
           LAG(v.hash) OVER (PARTITION BY v.occurrence_id ORDER BY v.captured_at, v.id) AS previous_hash
    FROM versions v JOIN occurrences o ON o.id = v.occurrence_id
    WHERE o.source_kind = 'inbox'
)
SELECT count(*) FROM ordered
WHERE previous_hash IS NOT NULL
  AND EXISTS (SELECT 1 FROM managed_files f WHERE f.document_id = ordered.occurrence_id AND f.blob_hash = ordered.previous_hash
              AND substr(f.relative_path, 1, 6) <> 'Inbox/')
  AND NOT EXISTS (SELECT 1 FROM managed_organization_events e
                  WHERE e.document_id = ordered.occurrence_id AND e.blob_hash = ordered.previous_hash)
"""


def plural(count):
    return f"{count} document" if count == 1 else f"{count} documents"


def report(db):
    """The four lines, in order, for a database already in memory."""
    x = db.execute
    would = x(f"SELECT count(DISTINCT occurrence_id), count(*) FROM ({MERGED_IN})").fetchone()
    has_splits = x("SELECT 1 FROM sqlite_schema WHERE type='table' AND name='document_splits'").fetchone()
    if has_splits:
        split, moved = x("SELECT count(DISTINCT from_document_id), coalesce(sum(versions), 0) FROM document_splits").fetchone()
    else:
        split, moved = 0, would[1]
    incomplete = x(HISTORY_INCOMPLETE).fetchone()[0]
    return [f"would split: {plural(would[0])}", f"split: {plural(split)}", f"versions moved: {moved}", f"left as a version, history incomplete: {incomplete}"]


if __name__ == "__main__":
    path = Path(sys.argv[1]).resolve()
    source = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=15)
    memory = sqlite3.connect(":memory:")
    source.backup(memory)
    source.close()
    print("\n".join(report(memory)))
