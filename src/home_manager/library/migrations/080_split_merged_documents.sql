-- Split the documents merged under one Inbox name (docs/documents.md "The managed library"). Before capture gave a different file under
-- a filed file's name a document of its own, every download called document.pdf became the next version of the first one. A version
-- is merged in when the version before it was filed out of the Inbox before it was captured. Each run of versions from there on
-- becomes a document; the earliest run keeps the id. Every row naming the merged document and one of those versions follows it.
-- All of it is one step, so the upgrade runner's transaction, snapshot and broken-reference check make it all or nothing.
-- Stage 1 is scripts/document_splits.py MERGED_IN, repeated: a migration cannot import, and a test holds the two together.
CREATE TABLE IF NOT EXISTS document_splits (
    document_id INTEGER PRIMARY KEY REFERENCES occurrences(id),
    from_document_id INTEGER NOT NULL REFERENCES occurrences(id),
    versions INTEGER NOT NULL,
    created_at TEXT NOT NULL
) STRICT;

-- 1. Every version of every Inbox document with the run it belongs to.
CREATE TEMP TABLE split_versions AS
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
SELECT * FROM cut;

-- 2. The runs after the first: their first and last version and how many there are.
CREATE TEMP TABLE split_runs AS
SELECT r.occurrence_id, r.run, count(*) AS versions, min(r.captured_at) AS first_seen,
       (SELECT s.hash FROM split_versions s WHERE s.occurrence_id = r.occurrence_id AND s.run = r.run ORDER BY s.captured_at, s.version_id LIMIT 1) AS first_hash,
       (SELECT s.hash FROM split_versions s WHERE s.occurrence_id = r.occurrence_id AND s.run = r.run ORDER BY s.captured_at DESC, s.version_id DESC LIMIT 1) AS last_hash
FROM split_versions r WHERE r.run > 0 GROUP BY r.occurrence_id, r.run;

-- 3. A document for each of them, before any row moves, so nothing ever names a document that isn't there. The path key is a
-- placeholder that is unique and never a real path; stage 6 gives the real ones.
INSERT INTO occurrences(source_root, path_key, relative_path, current_hash, source_status, first_seen, last_seen, last_job, deleted_at, source_kind)
SELECT o.source_root, o.path_key || '|split-' || r.occurrence_id || '-' || r.run, o.relative_path, r.last_hash, 'organized', r.first_seen,
       o.last_seen, o.last_job, o.deleted_at, o.source_kind
FROM split_runs r JOIN occurrences o ON o.id = r.occurrence_id ORDER BY r.occurrence_id, r.run;

CREATE TEMP TABLE split_map AS
SELECT r.occurrence_id, r.run, n.id AS new_id
FROM split_runs r JOIN occurrences o ON o.id = r.occurrence_id
JOIN occurrences n ON n.source_root = o.source_root AND n.path_key = o.path_key || '|split-' || r.occurrence_id || '-' || r.run;

-- Every document the repair touches, with the merged document it came from. The first run is the merged document itself.
CREATE TEMP TABLE split_pieces AS
SELECT DISTINCT occurrence_id AS document_id, occurrence_id AS from_id FROM split_runs
UNION ALL SELECT new_id, occurrence_id FROM split_map;

-- 4. Rows that name a document and a version follow the version. Only versions of later runs are listed, so a document that never
-- merged is not updated at all (an update that changes nothing would still fire the library_revision triggers).
CREATE TEMP TABLE split_hashes AS
SELECT s.occurrence_id, s.hash, m.new_id AS target_id
FROM split_versions s JOIN split_map m ON m.occurrence_id = s.occurrence_id AND m.run = s.run WHERE s.run > 0;

UPDATE versions SET occurrence_id = h.target_id FROM split_hashes h WHERE versions.occurrence_id = h.occurrence_id AND versions.hash = h.hash;
UPDATE managed_files SET document_id = h.target_id FROM split_hashes h WHERE managed_files.document_id = h.occurrence_id AND managed_files.blob_hash = h.hash;
UPDATE managed_organization_intents SET document_id = h.target_id FROM split_hashes h WHERE managed_organization_intents.document_id = h.occurrence_id AND managed_organization_intents.blob_hash = h.hash;
UPDATE managed_organization_events SET document_id = h.target_id FROM split_hashes h WHERE managed_organization_events.document_id = h.occurrence_id AND managed_organization_events.blob_hash = h.hash;
UPDATE library_events SET document_id = h.target_id FROM split_hashes h WHERE library_events.document_id = h.occurrence_id AND library_events.blob_hash = h.hash;
UPDATE document_folders SET document_id = h.target_id FROM split_hashes h WHERE document_folders.document_id = h.occurrence_id AND document_folders.blob_hash = h.hash;
UPDATE document_segments SET document_id = h.target_id FROM split_hashes h WHERE document_segments.document_id = h.occurrence_id AND document_segments.blob_hash = h.hash;
UPDATE organization_runs SET document_id = h.target_id FROM split_hashes h WHERE organization_runs.document_id = h.occurrence_id AND organization_runs.blob_hash = h.hash;
UPDATE job_filings SET document_id = h.target_id FROM split_hashes h WHERE job_filings.document_id = h.occurrence_id AND job_filings.blob_hash = h.hash;
UPDATE donation_checks SET document_id = h.target_id FROM split_hashes h WHERE donation_checks.document_id = h.occurrence_id AND donation_checks.blob_hash = h.hash;
UPDATE statements SET document_id = h.target_id FROM split_hashes h WHERE statements.document_id = h.occurrence_id AND statements.blob_hash = h.hash;
UPDATE receipts SET document_id = h.target_id FROM split_hashes h WHERE receipts.document_id = h.occurrence_id AND receipts.blob_hash = h.hash;
UPDATE income_records SET document_id = h.target_id FROM split_hashes h WHERE income_records.document_id = h.occurrence_id AND income_records.blob_hash = h.hash;
UPDATE assets SET document_id = h.target_id FROM split_hashes h WHERE assets.document_id = h.occurrence_id AND assets.blob_hash = h.hash;
UPDATE tax_forms SET document_id = h.target_id FROM split_hashes h WHERE tax_forms.document_id = h.occurrence_id AND tax_forms.blob_hash = h.hash;
UPDATE investment_confirmations SET document_id = h.target_id FROM split_hashes h WHERE investment_confirmations.document_id = h.occurrence_id AND investment_confirmations.blob_hash = h.hash;
UPDATE investment_events SET document_id = h.target_id FROM split_hashes h WHERE investment_events.document_id = h.occurrence_id AND investment_events.blob_hash = h.hash;
UPDATE investment_valuations SET document_id = h.target_id FROM split_hashes h WHERE investment_valuations.document_id = h.occurrence_id AND investment_valuations.blob_hash = h.hash;
UPDATE transaction_imports SET document_id = h.target_id FROM split_hashes h WHERE transaction_imports.document_id = h.occurrence_id AND transaction_imports.blob_hash = h.hash;
UPDATE financial_evidence_links SET document_id = h.target_id FROM split_hashes h WHERE financial_evidence_links.document_id = h.occurrence_id AND financial_evidence_links.blob_hash = h.hash;

-- 5. Rows that name a document but no version follow a version named through another row, else stay with the first run.
-- A reading belongs to the version it read.
UPDATE extraction_runs SET document_id = h.target_id FROM parse_runs p JOIN split_hashes h ON h.hash = p.blob_hash
WHERE extraction_runs.parse_run_id = p.id AND extraction_runs.document_id = h.occurrence_id;
-- A batch item names a document and the reading of it.
UPDATE receipt_batch_items SET document_id = h.target_id FROM parse_runs p JOIN split_hashes h ON h.hash = p.blob_hash
WHERE receipt_batch_items.run_id = p.id AND receipt_batch_items.document_id = h.occurrence_id;

-- A transaction follows its statement, else the import its evidence names, else its first evidence. Each of those rows has moved.
CREATE TEMP TABLE split_transactions AS
SELECT t.id, t.source_document_id AS was, COALESCE(
    (SELECT s.document_id FROM statements s WHERE s.id = t.statement_id
       AND s.document_id IN (SELECT document_id FROM split_pieces WHERE from_id = t.source_document_id)),
    (SELECT i.document_id FROM financial_evidence_links e JOIN transaction_imports i ON e.source_key = 'import:' || i.id
     WHERE e.record_type = 'transaction' AND e.record_id = t.id
       AND i.document_id IN (SELECT document_id FROM split_pieces WHERE from_id = t.source_document_id) ORDER BY e.id LIMIT 1),
    (SELECT e.document_id FROM financial_evidence_links e WHERE e.record_type = 'transaction' AND e.record_id = t.id
       AND e.document_id IN (SELECT document_id FROM split_pieces WHERE from_id = t.source_document_id) ORDER BY e.id LIMIT 1)
) AS moved_to
FROM transactions t WHERE t.source_document_id IN (SELECT from_id FROM split_pieces);
UPDATE transactions SET source_document_id = (SELECT moved_to FROM split_transactions WHERE id = transactions.id)
WHERE id IN (SELECT id FROM split_transactions WHERE moved_to IS NOT NULL AND moved_to <> was);

-- An obligation follows the receipt it came from.
UPDATE recurring_obligations SET source_document_id = (SELECT r.document_id FROM receipts r WHERE r.id = recurring_obligations.source_receipt_id)
WHERE source_document_id IN (SELECT from_id FROM split_pieces) AND source_receipt_id IS NOT NULL
  AND (SELECT r.document_id FROM receipts r WHERE r.id = recurring_obligations.source_receipt_id) IN
      (SELECT document_id FROM split_pieces WHERE from_id = recurring_obligations.source_document_id)
  AND (SELECT r.document_id FROM receipts r WHERE r.id = recurring_obligations.source_receipt_id) <> source_document_id;

-- A link to the merged document goes to the piece whose versions include the other document's current file (a same_bytes link). The
-- other document may itself have been merged, so both sides are worked out from the states before this stage. A link that would name
-- one document twice is dropped. Descriptions and group pages are document-level and stay.
CREATE TEMP TABLE split_links AS
SELECT l.id, l.occurrence_id AS a, l.other_occurrence_id AS b, l.reason, l.status, l.created_at,
       CASE WHEN l.reason = 'same_bytes' AND l.occurrence_id IN (SELECT from_id FROM split_pieces) THEN COALESCE(
           (SELECT p.document_id FROM split_pieces p JOIN versions v ON v.occurrence_id = p.document_id
            WHERE p.from_id = l.occurrence_id AND v.hash = (SELECT current_hash FROM occurrences WHERE id = l.other_occurrence_id) LIMIT 1),
           l.occurrence_id) ELSE l.occurrence_id END AS new_a,
       CASE WHEN l.reason = 'same_bytes' AND l.other_occurrence_id IN (SELECT from_id FROM split_pieces) THEN COALESCE(
           (SELECT p.document_id FROM split_pieces p JOIN versions v ON v.occurrence_id = p.document_id
            WHERE p.from_id = l.other_occurrence_id AND v.hash = (SELECT current_hash FROM occurrences WHERE id = l.occurrence_id) LIMIT 1),
           l.other_occurrence_id) ELSE l.other_occurrence_id END AS new_b
FROM occurrence_links l
WHERE l.occurrence_id IN (SELECT from_id FROM split_pieces) OR l.other_occurrence_id IN (SELECT from_id FROM split_pieces);
INSERT OR IGNORE INTO occurrence_links(occurrence_id, other_occurrence_id, reason, status, created_at)
SELECT min(new_a, new_b), max(new_a, new_b), reason, status, created_at FROM split_links WHERE new_a <> new_b AND (new_a <> a OR new_b <> b) ORDER BY id;
DELETE FROM occurrence_links WHERE id IN (SELECT id FROM split_links WHERE new_a = new_b OR new_a <> a OR new_b <> b);

-- 6. The Inbox path. The stored key is never recomputed from relative_path: since capture stopped merging, a merged document may
-- already have given up the bare key to a later file. A document that still holds the bare key passes it, and its status, to the piece
-- holding its current file. Every other piece takes the key a released document has (storage.RELEASED_PATH, built from the key's base
-- so a dropped file's re-drop lookup finds it) and counts as filed.
CREATE TEMP TABLE split_keys AS
SELECT p.document_id, p.from_id, o.path_key AS stored,
       CASE WHEN instr(o.path_key, '|released-d') > 0 THEN substr(o.path_key, 1, instr(o.path_key, '|released-d') - 1) ELSE o.path_key END AS base,
       instr(o.path_key, '|released-d') = 0 AND EXISTS (SELECT 1 FROM versions v WHERE v.occurrence_id = p.document_id AND v.hash = o.current_hash) AS holder,
       o.source_status AS stored_status
FROM split_pieces p JOIN occurrences o ON o.id = p.from_id;
ALTER TABLE split_keys ADD COLUMN final_key TEXT;
ALTER TABLE split_keys ADD COLUMN final_status TEXT;
UPDATE split_keys SET final_key = CASE WHEN holder THEN stored ELSE base || '|released-d' || document_id END,
                      final_status = CASE WHEN holder THEN stored_status ELSE 'organized' END;
-- The merged document's current file is its last run's. Then the keys, in an order that never clashes: the first runs step aside,
-- the pieces that take the stored key go next, and the released keys last.
UPDATE occurrences SET current_hash = (SELECT s.hash FROM split_versions s WHERE s.occurrence_id = occurrences.id AND s.run = 0
                                       ORDER BY s.captured_at DESC, s.version_id DESC LIMIT 1)
WHERE id IN (SELECT from_id FROM split_keys);
UPDATE occurrences SET path_key = (SELECT base FROM split_keys WHERE document_id = occurrences.id) || '|split-0-' || id
WHERE id IN (SELECT from_id FROM split_keys);
UPDATE occurrences SET path_key = k.final_key, source_status = k.final_status FROM split_keys k WHERE occurrences.id = k.document_id AND k.final_key = k.stored;
UPDATE occurrences SET path_key = k.final_key, source_status = k.final_status FROM split_keys k WHERE occurrences.id = k.document_id AND k.final_key <> k.stored;

-- 7. What was split, for the diagnostic (scripts/document_splits.py). Nothing in the app reads it.
INSERT INTO document_splits(document_id, from_document_id, versions, created_at)
SELECT m.new_id, m.occurrence_id, r.versions, strftime('%Y-%m-%dT%H:%M:%f', 'now') || '+00:00'
FROM split_map m JOIN split_runs r ON r.occurrence_id = m.occurrence_id AND r.run = m.run;

-- 8.
DROP TABLE split_links;
DROP TABLE split_keys;
DROP TABLE split_transactions;
DROP TABLE split_hashes;
DROP TABLE split_pieces;
DROP TABLE split_map;
DROP TABLE split_runs;
DROP TABLE split_versions;
PRAGMA user_version=80;
