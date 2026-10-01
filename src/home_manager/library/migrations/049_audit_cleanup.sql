-- Fixes from the database audit (db_audit_report.md: INT-2, INT-9, SIM-1, SIM-2).

-- INT-2: family rows whose record was deleted by emptying Trash. Ids are reused, so these would attach to the
-- next record given the same id. Rows already attached to a newer record cannot be told apart and are kept.
DELETE FROM record_shares WHERE (record_type='receipt' AND record_id NOT IN (SELECT id FROM receipts))
                             OR (record_type='bill' AND record_id NOT IN (SELECT id FROM bills));
DELETE FROM family_assignments WHERE (record_type='receipt' AND record_id NOT IN (SELECT id FROM receipts))
                                  OR (record_type='bill' AND record_id NOT IN (SELECT id FROM bills))
                                  OR (record_type='statement' AND record_id NOT IN (SELECT id FROM statements))
                                  OR (record_type='income_record' AND record_id NOT IN (SELECT id FROM income_records));

-- INT-9: 024 seeded return policies with datetime('now') ('2026-09-30 12:00:00'); every other timestamp is
-- ISO-8601 UTC ('2026-09-30T12:00:00+00:00'), and the two formats do not compare or sort together.
UPDATE return_policies SET created_at=replace(created_at,' ','T')||'+00:00' WHERE created_at GLOB '????-??-?? ??:??:??';
UPDATE return_policies SET updated_at=replace(updated_at,' ','T')||'+00:00' WHERE updated_at GLOB '????-??-?? ??:??:??';

-- SIM-2: lookups that scanned the whole table, most of them once per row of the library page.
CREATE INDEX transaction_receipt_links_receipt ON transaction_receipt_links(receipt_id);
CREATE INDEX managed_intents_document ON managed_organization_intents(document_id, blob_hash, created_at);
CREATE INDEX reconciliation_issues_record ON reconciliation_issues(record_type, record_id);
CREATE INDEX transactions_statement ON transactions(statement_id);
CREATE INDEX extraction_runs_document ON extraction_runs(document_id, created_at);

-- SIM-1: columns nothing reads or writes.
ALTER TABLE bills DROP COLUMN bill_type;
ALTER TABLE investment_valuations DROP COLUMN vested_minor;

PRAGMA user_version=49;
