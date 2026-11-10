-- A record keeps one link to each file's reading: the newest. Every re-read added one more, so a transaction listed its
-- statement once per reading (docs/money.md "Reading a statement or receipt again"). Imports, corrections and family links stay.
DELETE FROM financial_evidence_links WHERE source_key LIKE 'extraction:%' AND id < (
    SELECT max(other.id) FROM financial_evidence_links other
    WHERE other.record_type=financial_evidence_links.record_type AND other.record_id=financial_evidence_links.record_id
      AND other.blob_hash=financial_evidence_links.blob_hash AND other.source_key LIKE 'extraction:%');
PRAGMA user_version=79;
