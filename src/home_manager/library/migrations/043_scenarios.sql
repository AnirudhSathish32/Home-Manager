-- What If scenarios (docs/planning.md "What If"): a named plan (planned paychecks, set category amounts, one-offs, forecast
-- assumptions) run through the forecast beside "Now". Inputs only; results are always worked out again.
CREATE TABLE scenarios (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    basis TEXT NOT NULL CHECK (basis IN ('profile','family','blank')),
    inputs_json TEXT NOT NULL,
    adopted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=43;
