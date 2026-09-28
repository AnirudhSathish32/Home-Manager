-- Household items (docs/household-items.md): receipt lines resolved to products, a
-- household inventory of purchase lots, and the history behind run-out dates.

-- A canonical product. Created or matched only when the user approves a resolution.
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    brand TEXT,
    size_text TEXT,
    category TEXT NOT NULL,
    consumable INTEGER NOT NULL CHECK (consumable IN (0,1)),
    barcode TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(normalized_name, brand, size_text)
);

-- Printed receipt text at one merchant -> product. Written only by approval, so it is ground truth.
CREATE TABLE item_aliases (
    id INTEGER PRIMARY KEY,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
    normalized_text TEXT NOT NULL,
    product_code TEXT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    created_at TEXT NOT NULL,
    UNIQUE(merchant_id, normalized_text)
);
CREATE INDEX item_aliases_code ON item_aliases(merchant_id, product_code);

-- A proposed product for one receipt line. Receipt lines are rewritten when an unreviewed
-- receipt is re-extracted; their pending proposals go with them.
CREATE TABLE item_resolutions (
    id INTEGER PRIMARY KEY,
    receipt_item_id INTEGER NOT NULL REFERENCES receipt_items(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id),
    name TEXT NOT NULL,
    brand TEXT,
    size_text TEXT,
    category TEXT NOT NULL,
    consumable INTEGER NOT NULL CHECK (consumable IN (0,1)),
    barcode TEXT,
    confidence TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
    method TEXT NOT NULL CHECK (method IN ('alias','history','barcode','search','user')),
    sources_json TEXT NOT NULL DEFAULT '[]',
    run_id TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    reviewed_at TEXT
);
CREATE INDEX item_resolutions_item ON item_resolutions(receipt_item_id, review_status);

-- One purchase of one product. Keyed by receipt and line position, which survive a
-- re-extraction, so approving the same line again never adds a second lot.
CREATE TABLE inventory_lots (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    position INTEGER,
    units TEXT,
    cost_minor INTEGER CHECK (cost_minor IS NULL OR typeof(cost_minor) = 'integer'),
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    bought_on TEXT,
    status TEXT NOT NULL CHECK (status IN ('in_stock','finished','thrown_out')),
    closed_on TEXT,
    closed_precision_days INTEGER NOT NULL DEFAULT 0,
    next_check_on TEXT,
    check_interval_days INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(receipt_id, position)
);
CREATE INDEX inventory_lots_product ON inventory_lots(product_id, status, bought_on);
CREATE INDEX inventory_lots_check ON inventory_lots(status, next_check_on);

-- Append-only: an undo is a new 'undone' event carrying the state it restored, never a deletion.
CREATE TABLE lot_events (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES inventory_lots(id) ON DELETE CASCADE,
    event TEXT NOT NULL CHECK (event IN ('created','still_have','finished','thrown_out','reopened','undone')),
    effective_on TEXT NOT NULL,
    precision_days INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL CHECK (source IN ('approval','manual','checkin','checkin_text')),
    previous_json TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX lot_events_lot ON lot_events(lot_id, id);

-- One item-resolution agent run over a receipt's unresolved lines.
CREATE TABLE item_resolution_runs (
    id TEXT PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    result_json TEXT,
    error TEXT,
    model_identity TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Search responses, keyed by the exact normalized query, so a repeated lookup sends nothing.
CREATE TABLE web_search_cache (
    query TEXT PRIMARY KEY,
    results_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);
PRAGMA user_version=21;
