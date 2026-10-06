-- Returned items (docs/household.md "Returned items"): a line on a return receipt closes the household lot it bought,
-- as a proposal the user confirms. inventory_lots and lot_events gain 'returned'; SQLite can't change a CHECK, so both
-- are rebuilt (STRICT, as in 050).
CREATE TABLE "inventory_lots_new" (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    position INTEGER,
    units TEXT,
    cost_minor INTEGER CHECK (cost_minor IS NULL OR typeof(cost_minor) = 'integer'),
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    bought_on TEXT,
    status TEXT NOT NULL CHECK (status IN ('in_stock','finished','thrown_out','returned')),
    closed_on TEXT,
    closed_precision_days INTEGER NOT NULL DEFAULT 0,
    next_check_on TEXT,
    check_interval_days INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, opened_on TEXT,
    UNIQUE(receipt_id, position)
) STRICT;
INSERT INTO "inventory_lots_new"("id","product_id","receipt_id","position","units","cost_minor","currency","bought_on","status","closed_on","closed_precision_days","next_check_on","check_interval_days","created_at","updated_at","opened_on")
    SELECT "id","product_id","receipt_id","position","units","cost_minor","currency","bought_on","status","closed_on","closed_precision_days","next_check_on","check_interval_days","created_at","updated_at","opened_on" FROM "inventory_lots";
DROP TABLE "inventory_lots";
ALTER TABLE "inventory_lots_new" RENAME TO "inventory_lots";
CREATE INDEX inventory_lots_check ON inventory_lots(status, next_check_on);
CREATE INDEX inventory_lots_product ON inventory_lots(product_id, status, bought_on);

CREATE TABLE "lot_events_new" (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES inventory_lots(id) ON DELETE CASCADE,
    event TEXT NOT NULL CHECK (event IN ('created','still_have','finished','thrown_out','reopened','opened','returned','undone')),
    effective_on TEXT NOT NULL,
    precision_days INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL CHECK (source IN ('approval','manual','checkin','checkin_text')),
    previous_json TEXT,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "lot_events_new"("id","lot_id","event","effective_on","precision_days","source","previous_json","created_at")
    SELECT "id","lot_id","event","effective_on","precision_days","source","previous_json","created_at" FROM "lot_events";
DROP TABLE "lot_events";
ALTER TABLE "lot_events_new" RENAME TO "lot_events";
CREATE INDEX lot_events_lot ON lot_events(lot_id, id);

-- One proposal per returned receipt line: the in-stock lots it may have closed (lot_ids_json), and the user's answer.
-- lot_id is the lot they confirmed.
CREATE TABLE lot_returns (
    receipt_item_id INTEGER PRIMARY KEY REFERENCES receipt_items(id) ON DELETE CASCADE,
    lot_ids_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected')),
    lot_id INTEGER REFERENCES inventory_lots(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
PRAGMA user_version=63;
