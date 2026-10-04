-- Investment kinds made specific (docs/planning.md "Kinds made specific") and phase 5's account columns.
-- A pension is an income stream, not a balance: value model 'income'. A crypto market price adds a 'quote' value. 1099-Q
-- (529 withdrawals) and 1099-DA (digital asset sales) join the tax forms. The CHECKs that change need table rebuilds, done as
-- in 050 (new table, copy, drop, rename); the runner turns foreign keys off and checks references before committing.

-- investment_kinds: value model 'income' (a pension pays a monthly benefit; it has no balance to grow or draw).
CREATE TABLE "investment_kinds_new" (
    key TEXT PRIMARY KEY CHECK (key GLOB '[a-z0-9]*' AND key NOT GLOB '*[^a-z0-9_]*'),
    label TEXT NOT NULL,
    section TEXT NOT NULL CHECK (section IN ('retirement','health','cash','fixed_income','market','education','other')),
    tax_treatment TEXT NOT NULL CHECK (tax_treatment IN ('taxable','tax_deferred','tax_free','hsa')),
    -- market: the last reported value; accrual: principal and a rate to maturity; cash: a balance earning a yearly rate;
    -- income: a monthly benefit from a start date (pension_terms), never counted as a balance.
    value_model TEXT NOT NULL CHECK (value_model IN ('market','accrual','cash','income')),
    has_maturity INTEGER NOT NULL DEFAULT 0 CHECK (has_maturity IN (0,1)),
    -- Yearly growth used by the forecast when the account sets none. Basis points: 250 is 2.5%.
    default_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK (default_rate_bp BETWEEN -10000 AND 10000),
    position INTEGER NOT NULL
) STRICT;
INSERT INTO "investment_kinds_new"("key","label","section","tax_treatment","value_model","has_maturity","default_rate_bp","position") SELECT "key","label","section","tax_treatment","value_model","has_maturity","default_rate_bp","position" FROM "investment_kinds";
DROP TABLE "investment_kinds";
ALTER TABLE "investment_kinds_new" RENAME TO "investment_kinds";
UPDATE investment_kinds SET value_model='income' WHERE key='pension';

-- investment_valuations: source 'quote', a value worked out from a market price (finance/prices.py). Quotes never replace a
-- statement or a value you typed; a document value for the same date replaces the quote.
CREATE TABLE "investment_valuations_new" (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    holding_id INTEGER REFERENCES holdings(id) ON DELETE CASCADE,
    as_of TEXT NOT NULL,
    value_minor INTEGER NOT NULL CHECK (typeof(value_minor) = 'integer' AND value_minor >= 0),
    quantity TEXT,
    price_minor INTEGER,
    cost_basis_minor INTEGER,
    source TEXT NOT NULL CHECK (source IN ('manual','statement','quote')),
    document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL,
    blob_hash TEXT REFERENCES blobs(hash),
    extraction_run_id TEXT,
    validation_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    legacy_asset_id INTEGER,  -- The assets row this came from before 036, for older extraction results.
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "investment_valuations_new"("id","account_id","holding_id","as_of","value_minor","quantity","price_minor","cost_basis_minor","source","document_id","blob_hash","extraction_run_id","validation_json","review_status","legacy_asset_id","created_at","updated_at") SELECT "id","account_id","holding_id","as_of","value_minor","quantity","price_minor","cost_basis_minor","source","document_id","blob_hash","extraction_run_id","validation_json","review_status","legacy_asset_id","created_at","updated_at" FROM "investment_valuations";
DROP TABLE "investment_valuations";
ALTER TABLE "investment_valuations_new" RENAME TO "investment_valuations";
CREATE UNIQUE INDEX investment_valuations_point ON investment_valuations(account_id, coalesce(holding_id, 0), as_of);
CREATE INDEX investment_valuations_review ON investment_valuations(review_status);

-- tax_form_boxes: 1099-Q (529 and Coverdell withdrawals) and 1099-DA (digital asset sales).
CREATE TABLE "tax_form_boxes_new" (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES tax_forms(id) ON DELETE CASCADE,
    form TEXT NOT NULL CHECK (form IN ('1099-INT','1099-DIV','1099-B','1099-R','1099-SA','1099-Q','1099-DA','5498','5498-SA')),
    box TEXT NOT NULL,  -- As printed, lower case: 1, 1a, 2b.
    label TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    locator_json TEXT NOT NULL DEFAULT '{}'
) STRICT;
INSERT INTO "tax_form_boxes_new"("id","form_id","form","box","label","amount_minor","locator_json") SELECT "id","form_id","form","box","label","amount_minor","locator_json" FROM "tax_form_boxes";
DROP TABLE "tax_form_boxes";
ALTER TABLE "tax_form_boxes_new" RENAME TO "tax_form_boxes";
CREATE INDEX tax_form_boxes_form ON tax_form_boxes(form_id);

-- A pension's terms: what it pays a month from its start date, its yearly cost-of-living raise, what a survivor keeps, and
-- the lump sum offered instead (shown beside it, never counted in totals).
CREATE TABLE pension_terms (
    account_id INTEGER PRIMARY KEY REFERENCES investment_accounts(id) ON DELETE CASCADE,
    monthly_benefit_minor INTEGER NOT NULL CHECK (monthly_benefit_minor >= 0),
    start_date TEXT NOT NULL CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    cola_bp INTEGER NOT NULL DEFAULT 0 CHECK (cola_bp BETWEEN 0 AND 2000),
    survivor_pct INTEGER NOT NULL DEFAULT 0 CHECK (survivor_pct BETWEEN 0 AND 100),
    lump_sum_minor INTEGER CHECK (lump_sum_minor IS NULL OR lump_sum_minor >= 0),
    updated_at TEXT NOT NULL
) STRICT;

-- Market prices fetched for crypto (finance/prices.py), only when the household setting allows it. One price per source,
-- symbol, currency and day; a later fetch the same day replaces it. Prices are exact decimal text, never REAL.
CREATE TABLE price_quotes (
    source TEXT NOT NULL CHECK (source IN ('coingecko')),
    symbol TEXT NOT NULL CHECK (symbol GLOB '[A-Z0-9]*' AND length(symbol) BETWEEN 1 AND 20),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    as_of TEXT NOT NULL,
    price TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, symbol, currency, as_of)
) STRICT;

-- I bond rates as TreasuryDirect publishes them, each May 1 and November 1: the fixed rate for bonds issued in that period, and
-- the semiannual inflation rate. Basis points: 130 is 1.30%. Kept by the user (a new row each May and November); no network.
CREATE TABLE ibond_rates (
    period_start TEXT PRIMARY KEY CHECK (period_start GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-01'),
    fixed_bp INTEGER NOT NULL CHECK (fixed_bp BETWEEN 0 AND 1000),
    inflation_semiannual_bp INTEGER NOT NULL CHECK (inflation_semiannual_bp BETWEEN -1000 AND 1000)
) STRICT;
INSERT INTO ibond_rates(period_start,fixed_bp,inflation_semiannual_bp) VALUES
    ('2015-05-01',0,-80), ('2015-11-01',10,77), ('2016-05-01',10,8), ('2016-11-01',0,138), ('2017-05-01',0,98),
    ('2017-11-01',10,124), ('2018-05-01',30,111), ('2018-11-01',50,116), ('2019-05-01',50,70), ('2019-11-01',20,101),
    ('2020-05-01',0,53), ('2020-11-01',0,84), ('2021-05-01',0,177), ('2021-11-01',0,356), ('2022-05-01',0,481),
    ('2022-11-01',40,324), ('2023-05-01',90,169), ('2023-11-01',130,197), ('2024-05-01',130,148), ('2024-11-01',120,95),
    ('2025-05-01',110,143), ('2025-11-01',90,156), ('2026-05-01',90,167);

-- A 529's beneficiary (a profile's name or anyone) and the state whose plan it is.
ALTER TABLE investment_accounts ADD COLUMN beneficiary TEXT CHECK (beneficiary IS NULL OR length(beneficiary) <= 80);
ALTER TABLE investment_accounts ADD COLUMN plan_state TEXT CHECK (plan_state IS NULL OR plan_state GLOB '[A-Z][A-Z]');
-- Phase 5 (forecast): the part of the yearly return paid out as dividends or interest, and whether it is reinvested.
ALTER TABLE investment_accounts ADD COLUMN yield_bp INTEGER NOT NULL DEFAULT 0 CHECK (yield_bp BETWEEN 0 AND 10000);
ALTER TABLE investment_accounts ADD COLUMN reinvest INTEGER NOT NULL DEFAULT 1 CHECK (reinvest IN (0,1));

PRAGMA user_version=56;
