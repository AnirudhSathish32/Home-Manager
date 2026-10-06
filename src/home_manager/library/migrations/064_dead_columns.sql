-- Dead columns from the 2026-09-30 audit (docs/development.md "Database checks"): written but never read. jobs.year and
-- jobs.month, and occurrences.folder_year and folder_month (folder dates left the capture model; capture_intents keeps
-- its own), drop in place once their index is gone: UNIQUE(source_root, path_key) still serves lookups by source.
-- investment_events.reverses_event_id has a REFERENCES clause, which DROP COLUMN refuses, so that table is rebuilt
-- (STRICT, as in 050) with its indexes.
DROP INDEX occurrences_root;
ALTER TABLE occurrences DROP COLUMN folder_year;
ALTER TABLE occurrences DROP COLUMN folder_month;
ALTER TABLE jobs DROP COLUMN year;
ALTER TABLE jobs DROP COLUMN month;

CREATE TABLE "investment_events_new" (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    holding_id INTEGER REFERENCES holdings(id) ON DELETE SET NULL,
    event_date TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type GLOB '[a-z]*' AND event_type NOT GLOB '*[^a-z_]*'),
    contribution_source TEXT CHECK (contribution_source IS NULL OR contribution_source IN ('employee','employer','personal')),
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    quantity TEXT,
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE SET NULL,
    income_line_id INTEGER REFERENCES income_lines(id) ON DELETE SET NULL,
    document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL,
    blob_hash TEXT REFERENCES blobs(hash),
    note TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    confirmation_id INTEGER REFERENCES investment_confirmations(id) ON DELETE CASCADE,
    transaction_previous_type TEXT,
    transaction_link TEXT CHECK (transaction_link IS NULL OR transaction_link IN ('auto','user')),
    CHECK (transaction_previous_type IS NULL OR transaction_previous_type IN ('purchase','refund','payment','transfer','deposit','fee','interest','withdrawal','other'))
) STRICT;
INSERT INTO "investment_events_new"("id","account_id","holding_id","event_date","event_type","contribution_source","amount_minor","quantity","transaction_id","income_line_id","document_id","blob_hash","note","review_status","created_at","confirmation_id","transaction_previous_type","transaction_link")
    SELECT "id","account_id","holding_id","event_date","event_type","contribution_source","amount_minor","quantity","transaction_id","income_line_id","document_id","blob_hash","note","review_status","created_at","confirmation_id","transaction_previous_type","transaction_link" FROM "investment_events";
DROP TABLE "investment_events";
ALTER TABLE "investment_events_new" RENAME TO "investment_events";
CREATE INDEX investment_events_account ON investment_events(account_id, event_date);
CREATE INDEX investment_events_confirmation ON investment_events(confirmation_id);
CREATE INDEX investment_events_source ON investment_events(account_id, blob_hash);
PRAGMA user_version=64;
