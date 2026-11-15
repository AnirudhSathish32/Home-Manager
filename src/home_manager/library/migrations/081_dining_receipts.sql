-- Dining receipts (docs/money.md "Item categories and splits", docs/documents.md "Receipt kinds"). Three columns and nothing else: no row is
-- touched, so no stored total, tip or split changes at upgrade (specs/dining-receipt-indent D5).
-- one_category: 1 once every item of a dining receipt counts under the receipt's category (FR-10); 0 for every receipt already recorded.
ALTER TABLE receipts ADD COLUMN one_category INTEGER NOT NULL DEFAULT 0 CHECK (one_category IN (0, 1));
-- tip_worked_out_json: the two printed lines a tip was worked out from, and their amounts; NULL when the tip is printed or missing.
ALTER TABLE receipts ADD COLUMN tip_worked_out_json TEXT;
-- item_categories_json: the item categories and the flag a kind change replaced, so Undo gives them back (set on a kind change only).
ALTER TABLE record_corrections ADD COLUMN item_categories_json TEXT;
PRAGMA user_version=81;
