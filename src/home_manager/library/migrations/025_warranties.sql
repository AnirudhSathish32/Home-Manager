-- Warranties for durable household items (docs/warranties-assistant-processing.md §1).
CREATE TABLE warranties (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES inventory_lots(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('manufacturer','store','extended')),
    months INTEGER CHECK (months IS NULL OR months BETWEEN 1 AND 600),
    lifetime INTEGER NOT NULL DEFAULT 0 CHECK (lifetime IN (0,1)),
    starts_on TEXT NOT NULL,
    expires_on TEXT,
    source TEXT NOT NULL CHECK (source IN ('user','lookup')),
    source_title TEXT,
    source_url TEXT,
    quote TEXT,
    note TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((lifetime = 1 AND months IS NULL AND expires_on IS NULL) OR (lifetime = 0 AND months IS NOT NULL AND expires_on IS NOT NULL)),
    UNIQUE(lot_id, kind)
);

-- One warranty lookup: a short agent run with web search for one item.
CREATE TABLE warranty_runs (
    id TEXT PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES inventory_lots(id) ON DELETE CASCADE,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=25;
