-- Opened items, return windows and statement assets (docs/items-assets-search.md).

-- When a non-food lot was opened; an opened item usually can't be returned.
ALTER TABLE inventory_lots ADD COLUMN opened_on TEXT;

-- lot_events gains the 'opened' event. SQLite can't change a CHECK, so the table is rebuilt.
CREATE TABLE lot_events_new (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES inventory_lots(id) ON DELETE CASCADE,
    event TEXT NOT NULL CHECK (event IN ('created','still_have','finished','thrown_out','reopened','opened','undone')),
    effective_on TEXT NOT NULL,
    precision_days INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL CHECK (source IN ('approval','manual','checkin','checkin_text')),
    previous_json TEXT,
    created_at TEXT NOT NULL
);
INSERT INTO lot_events_new SELECT id,lot_id,event,effective_on,precision_days,source,previous_json,created_at FROM lot_events;
DROP TABLE lot_events;
ALTER TABLE lot_events_new RENAME TO lot_events;
CREATE INDEX lot_events_lot ON lot_events(lot_id, id);

-- A return policy printed on the receipt, found in its transcription when it is recorded.
-- return_days_printed 0 means the receipt says no returns.
ALTER TABLE receipts ADD COLUMN return_days_printed INTEGER CHECK (return_days_printed IS NULL OR return_days_printed BETWEEN 0 AND 730);
ALTER TABLE receipts ADD COLUMN return_policy_quote TEXT;

-- A merchant's general return policy, matched by merchant name words like category rules.
-- days NULL means no fixed limit. 'typical' rows are starting points the user can change.
CREATE TABLE return_policies (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL UNIQUE,
    merchant TEXT NOT NULL,
    days INTEGER CHECK (days IS NULL OR days BETWEEN 0 AND 730),
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL CHECK (source IN ('typical','user')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
INSERT INTO return_policies(pattern,merchant,days,note,source,created_at,updated_at) VALUES
    ('WALMART','Walmart',90,'Most items; electronics and some categories are shorter.','typical',datetime('now'),datetime('now')),
    ('TARGET','Target',90,'Most items; electronics are shorter and Target''s own brands are longer.','typical',datetime('now'),datetime('now')),
    ('COSTCO','Costco',NULL,'No fixed limit on most items; electronics and major appliances are shorter.','typical',datetime('now'),datetime('now')),
    ('HOME DEPOT','The Home Depot',90,'Most items; some categories are shorter.','typical',datetime('now'),datetime('now')),
    ('LOWE S','Lowe''s',90,'Most items; some categories are shorter.','typical',datetime('now'),datetime('now')),
    ('BEST BUY','Best Buy',15,'Standard window; membership levels may extend it.','typical',datetime('now'),datetime('now')),
    ('AMAZON','Amazon',30,'Most items sold by Amazon; third-party sellers vary.','typical',datetime('now'),datetime('now'));

-- Statement-read assets: the source record and one row per account.
ALTER TABLE assets ADD COLUMN blob_hash TEXT REFERENCES blobs(hash);
ALTER TABLE assets ADD COLUMN extraction_run_id TEXT;
ALTER TABLE assets ADD COLUMN account_key TEXT;
ALTER TABLE assets ADD COLUMN validation_json TEXT NOT NULL DEFAULT '[]';
CREATE UNIQUE INDEX assets_account ON assets(account_key) WHERE account_key IS NOT NULL;
PRAGMA user_version=24;
