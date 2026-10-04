-- Investments phase 5 (docs/planning.md "Investments"): tax lots and 1099/5498 forms.
-- Lots bought through a confirmation, or listed as buys on a statement, come from their activity when read; this table keeps
-- only lots the user enters (shares bought before the documents here begin). Sales are matched to lots first in, first out.
CREATE TABLE tax_lots (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    holding_id INTEGER NOT NULL REFERENCES holdings(id) ON DELETE CASCADE,
    acquired_date TEXT NOT NULL,
    quantity TEXT NOT NULL,  -- Exact decimal text, as shares are printed: 12.345.
    cost_minor INTEGER NOT NULL CHECK (typeof(cost_minor) = 'integer' AND cost_minor >= 0),
    created_at TEXT NOT NULL
);
CREATE INDEX tax_lots_holding ON tax_lots(holding_id, acquired_date);

-- A 1099 or 5498 from a bank, brokerage or plan (a consolidated 1099 holds several forms), for one tax year.
CREATE TABLE tax_forms (
    id INTEGER PRIMARY KEY,
    account_id INTEGER REFERENCES investment_accounts(id) ON DELETE SET NULL,  -- NULL when no account here matches it.
    institution TEXT NOT NULL,
    last_four TEXT,
    tax_year INTEGER NOT NULL CHECK (tax_year BETWEEN 1990 AND 2100),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL,
    blob_hash TEXT NOT NULL UNIQUE REFERENCES blobs(hash),
    extraction_run_id TEXT,
    validation_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE tax_form_boxes (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES tax_forms(id) ON DELETE CASCADE,
    form TEXT NOT NULL CHECK (form IN ('1099-INT','1099-DIV','1099-B','1099-R','1099-SA','5498','5498-SA')),
    box TEXT NOT NULL,  -- As printed, lower case: 1, 1a, 2b.
    label TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    locator_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX tax_form_boxes_form ON tax_form_boxes(form_id);
PRAGMA user_version=40;
