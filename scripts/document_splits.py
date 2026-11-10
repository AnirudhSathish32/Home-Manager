"""The documents merged under one Inbox name, and what the upgrade split (specs/inbox-document-identity FR-09).

The report itself comes with the diagnostic; this holds the one query that decides what is merged in.
"""

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
