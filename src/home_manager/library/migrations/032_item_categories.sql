-- Spending categories belong to receipt items, not whole receipts: one Costco receipt can hold dining,
-- shopping and groceries. receipt_items.category already exists; taxed is the printed tax flag (NULL: not shown).
ALTER TABLE receipt_items ADD COLUMN taxed INTEGER CHECK (taxed IS NULL OR taxed IN (0,1));
ALTER TABLE receipt_items ADD COLUMN category_source TEXT CHECK (category_source IS NULL OR category_source IN ('model','memory','receipt','user'));
-- A receipt's money, or the money of a charge linked to it, divided by item category (finance/splits.py).
-- Rows for one receipt (transaction_id NULL) add up to its total; rows for one charge add up to what it charged.
-- receipt_item_id is NULL for a tip, or for money no item could carry.
CREATE TABLE category_splits (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE CASCADE,
    receipt_item_id INTEGER REFERENCES receipt_items(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer')
);
CREATE INDEX category_splits_receipt ON category_splits(receipt_id, transaction_id);
CREATE INDEX category_splits_transaction ON category_splits(transaction_id);
-- The user's category for an item, remembered by seller and item text and used ahead of the model next time.
CREATE TABLE item_category_memory (
    merchant_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    category TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (merchant_key, item_key)
);
PRAGMA user_version=32;
