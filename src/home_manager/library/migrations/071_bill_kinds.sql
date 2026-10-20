-- Bill kinds (specs/bill-kinds; docs/money.md "Bills and their lines", docs/documents.md "Bill kinds").
-- Nullable, nothing backfilled: a bill gets its kind when it is read again (FR-52).
ALTER TABLE receipts ADD COLUMN bill_kind TEXT CHECK (bill_kind IS NULL OR bill_kind IN ('rent','general'));
ALTER TABLE receipt_items ADD COLUMN line_type TEXT
    CHECK (line_type IS NULL OR line_type IN ('rent','parking','pet','utility','fee','credit','other'));
PRAGMA user_version=71;
