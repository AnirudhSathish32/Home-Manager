-- Receipt tax codes (docs/money.md "Item categories and splits"): the code printed beside an item's price, the per-code tax
-- lines a receipt prints, and which rule a reading set up. Only adds a NULL column, a NULL column and an empty table, so no
-- existing receipt, item or split changes (specs/receipt-tax-codes FR-13).
-- tax_source: 'tax_lines' (per-code tax lines are stored), 'legend' (a code legend and no per-code amounts), 'printed' (read
-- with neither). NULL for every receipt recorded before this change, every bill, and any record published without a reading.
ALTER TABLE receipt_items ADD COLUMN tax_code TEXT;
ALTER TABLE receipts ADD COLUMN tax_source TEXT CHECK (tax_source IS NULL OR tax_source IN ('tax_lines','legend','printed'));
-- Amounts are magnitudes: the receipt's own tax carries the sign (a return flips tax_minor, never these rows).
CREATE TABLE receipt_tax_lines (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    code TEXT NOT NULL,
    rate_text TEXT,
    taxable_minor INTEGER CHECK (taxable_minor IS NULL OR typeof(taxable_minor)='integer'),
    amount_minor INTEGER CHECK (amount_minor IS NULL OR typeof(amount_minor)='integer'),
    locator_json TEXT NOT NULL,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(receipt_id, position)
) STRICT;
PRAGMA user_version=75;
