-- Document forms (specs/document-forms): receipt kinds and the printed details of receipts, pay stubs and statements.
-- Every column is nullable and nothing is backfilled: a record keeps its data until it is read again (FR-13).
ALTER TABLE receipts ADD COLUMN receipt_kind TEXT CHECK (receipt_kind IN ('fuel','dining','grocery','general'));
ALTER TABLE receipts ADD COLUMN details_json TEXT;
ALTER TABLE receipts ADD COLUMN pending_details_json TEXT;
ALTER TABLE receipts ADD COLUMN printed_total_minor INTEGER CHECK (printed_total_minor IS NULL OR typeof(printed_total_minor) = 'integer');
ALTER TABLE receipt_items ADD COLUMN details_json TEXT;
ALTER TABLE income_records ADD COLUMN details_json TEXT;
ALTER TABLE income_lines ADD COLUMN details_json TEXT;
ALTER TABLE statements ADD COLUMN details_json TEXT;
PRAGMA user_version=70;
