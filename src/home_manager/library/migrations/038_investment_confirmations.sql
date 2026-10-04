-- Investments phase 3 (docs/planning.md "Investments"): purchase confirmations (a trade, a CD or a Treasury bought), and the terms
-- a holding's value is estimated from between statements.
-- One confirmation per document: the reviewable record, as an account value is for a statement.
CREATE TABLE investment_confirmations (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL,
    blob_hash TEXT NOT NULL UNIQUE REFERENCES blobs(hash),
    extraction_run_id TEXT,
    trade_date TEXT NOT NULL,
    validation_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
-- What is paid at maturity (a Treasury bill's face value), when an I bond or CD can first be cashed without losing
-- interest, whether it renews itself, and where its terms came from.
ALTER TABLE holdings ADD COLUMN face_minor INTEGER CHECK (face_minor IS NULL OR (typeof(face_minor) = 'integer' AND face_minor >= 0));
ALTER TABLE holdings ADD COLUMN redeemable_date TEXT;
ALTER TABLE holdings ADD COLUMN rollover INTEGER NOT NULL DEFAULT 0 CHECK (rollover IN (0,1));
ALTER TABLE holdings ADD COLUMN source TEXT NOT NULL DEFAULT 'statement' CHECK (source IN ('statement','confirmation','manual'));
ALTER TABLE holdings ADD COLUMN confirmation_id INTEGER REFERENCES investment_confirmations(id) ON DELETE SET NULL;
ALTER TABLE investment_events ADD COLUMN confirmation_id INTEGER REFERENCES investment_confirmations(id) ON DELETE CASCADE;
CREATE INDEX investment_events_confirmation ON investment_events(confirmation_id);
PRAGMA user_version=38;
