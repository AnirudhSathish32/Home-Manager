-- Assets and loans for the forecast (docs/forecast.md). A value the user types in (a car, a house)
-- is their own input and counts at once; a value read from a statement is proposed until reviewed.
CREATE TABLE assets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('investment','retirement','bond','real_estate','vehicle','other_asset','loan')),
    value_minor INTEGER NOT NULL CHECK (typeof(value_minor) = 'integer' AND value_minor >= 0),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    as_of TEXT NOT NULL,
    -- Yearly growth for assets; the yearly interest rate for loans. Basis points: 250 is 2.5%.
    annual_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK (annual_rate_bp BETWEEN -10000 AND 10000),
    monthly_payment_minor INTEGER CHECK (monthly_payment_minor IS NULL OR (typeof(monthly_payment_minor) = 'integer' AND monthly_payment_minor >= 0)),
    source TEXT NOT NULL CHECK (source IN ('manual','statement')),
    document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX assets_active ON assets(archived_at, review_status);
PRAGMA user_version=22;
