-- Investments (docs/investments.md). What an investment is (its kind) is data, not a CHECK: a new kind is a row here.
-- The page and the forecast branch only on section, tax treatment and value model, never on the kind itself.
CREATE TABLE investment_kinds (
    key TEXT PRIMARY KEY CHECK (key GLOB '[a-z0-9]*' AND key NOT GLOB '*[^a-z0-9_]*'),
    label TEXT NOT NULL,
    section TEXT NOT NULL CHECK (section IN ('retirement','health','cash','fixed_income','market','education','other')),
    tax_treatment TEXT NOT NULL CHECK (tax_treatment IN ('taxable','tax_deferred','tax_free','hsa')),
    -- market: the last reported value; accrual: principal and a rate to maturity; cash: a balance earning a yearly rate.
    value_model TEXT NOT NULL CHECK (value_model IN ('market','accrual','cash')),
    has_maturity INTEGER NOT NULL DEFAULT 0 CHECK (has_maturity IN (0,1)),
    -- Yearly growth used by the forecast when the account sets none. Basis points: 250 is 2.5%.
    default_rate_bp INTEGER NOT NULL DEFAULT 0 CHECK (default_rate_bp BETWEEN -10000 AND 10000),
    position INTEGER NOT NULL
);
INSERT INTO investment_kinds(key,label,section,tax_treatment,value_model,has_maturity,position) VALUES
    ('401k','401(k)','retirement','tax_deferred','market',0,10),
    ('403b','403(b)','retirement','tax_deferred','market',0,20),
    ('457b','457(b)','retirement','tax_deferred','market',0,30),
    ('ira','Traditional IRA','retirement','tax_deferred','market',0,40),
    ('roth_ira','Roth IRA','retirement','tax_free','market',0,50),
    ('pension','Pension','retirement','tax_deferred','market',0,60),
    ('retirement','Retirement account','retirement','tax_deferred','market',0,70),
    ('hsa','HSA','health','hsa','market',0,80),
    ('hysa','High-yield savings','cash','taxable','cash',0,90),
    ('money_market','Money market','cash','taxable','cash',0,100),
    ('cd','Certificate of deposit','fixed_income','taxable','accrual',1,110),
    ('treasury','Treasuries','fixed_income','taxable','accrual',1,120),
    ('i_bond','I bonds','fixed_income','taxable','accrual',1,130),
    ('bonds','Bonds','fixed_income','taxable','market',0,140),
    ('brokerage','Brokerage','market','taxable','market',0,150),
    ('crypto','Crypto','market','taxable','market',0,160),
    ('education_529','529 education','education','tax_free','market',0,170),
    ('other','Other investment','other','taxable','market',0,999);

-- The container: one row per account at an institution.
CREATE TABLE investment_accounts (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL REFERENCES investment_kinds(key),
    name TEXT NOT NULL,
    institution TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    -- institution|last four or account name|currency, from statements; NULL for accounts the user adds.
    account_key TEXT UNIQUE,
    tax_treatment TEXT CHECK (tax_treatment IS NULL OR tax_treatment IN ('taxable','tax_deferred','tax_free','hsa')),
    -- Yearly growth or interest; NULL uses the kind's default.
    annual_rate_bp INTEGER CHECK (annual_rate_bp IS NULL OR annual_rate_bp BETWEEN -10000 AND 10000),
    -- A savings account also in the ledger, so its cash is counted once (docs/investments.md, phase 2).
    ledger_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    source TEXT NOT NULL CHECK (source IN ('manual','statement')),
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Positions in an account: funds, stocks, a CD, a Treasury bill. Terms are empty where they don't apply.
CREATE TABLE holdings (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    instrument_class TEXT NOT NULL CHECK (instrument_class GLOB '[a-z]*' AND instrument_class NOT GLOB '*[^a-z_]*'),
    name TEXT NOT NULL,
    identifier TEXT,  -- Ticker or CUSIP.
    holding_key TEXT NOT NULL,
    rate_bp INTEGER CHECK (rate_bp IS NULL OR rate_bp BETWEEN -10000 AND 10000),
    issue_date TEXT,
    maturity_date TEXT,
    principal_minor INTEGER CHECK (principal_minor IS NULL OR (typeof(principal_minor) = 'integer' AND principal_minor >= 0)),
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (account_id, holding_key)
);

-- Values over time. Never overwritten: a newer statement adds a row. A row without a holding is the whole account.
CREATE TABLE investment_valuations (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    holding_id INTEGER REFERENCES holdings(id) ON DELETE CASCADE,
    as_of TEXT NOT NULL,
    value_minor INTEGER NOT NULL CHECK (typeof(value_minor) = 'integer' AND value_minor >= 0),
    quantity TEXT,
    price_minor INTEGER,
    cost_basis_minor INTEGER,
    vested_minor INTEGER,
    source TEXT NOT NULL CHECK (source IN ('manual','statement')),
    document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL,
    blob_hash TEXT REFERENCES blobs(hash),
    extraction_run_id TEXT,
    validation_json TEXT NOT NULL DEFAULT '[]',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    legacy_asset_id INTEGER,  -- The assets row this came from before 036, for older extraction results.
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX investment_valuations_point ON investment_valuations(account_id, coalesce(holding_id, 0), as_of);
CREATE INDEX investment_valuations_review ON investment_valuations(review_status);

-- Money in and out and what it earned: contributions, dividends, interest, trades, maturities. Append-only;
-- a correction is a new event that names the one it reverses.
CREATE TABLE investment_events (
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
    reverses_event_id INTEGER REFERENCES investment_events(id),
    note TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL
);
CREATE INDEX investment_events_account ON investment_events(account_id, event_date);

-- Investment rows of assets move here, each with its one value; assets keeps homes, cars, other assets and loans.
INSERT INTO investment_accounts(id,kind,name,institution,currency,account_key,annual_rate_bp,source,archived_at,created_at,updated_at)
    SELECT id, CASE kind WHEN 'retirement' THEN 'retirement' WHEN 'bond' THEN 'bonds' ELSE 'brokerage' END, name, '', currency,
           -- Keys lose their old kind prefix, unless two old kinds held the same account (then the full key stays unique).
           CASE WHEN account_key IS NULL THEN NULL
                WHEN (SELECT count(*) FROM assets other WHERE other.kind IN ('investment','retirement','bond')
                      AND substr(other.account_key, instr(other.account_key, '|') + 1) = substr(assets.account_key, instr(assets.account_key, '|') + 1)) > 1
                THEN account_key
                ELSE substr(account_key, instr(account_key, '|') + 1) END,
           NULLIF(annual_rate_bp, 0), source, archived_at, created_at, updated_at
    FROM assets WHERE kind IN ('investment','retirement','bond');
INSERT INTO investment_valuations(account_id,as_of,value_minor,source,document_id,blob_hash,extraction_run_id,validation_json,review_status,
                                  legacy_asset_id,created_at,updated_at)
    SELECT id, as_of, value_minor, source, document_id, blob_hash, extraction_run_id, validation_json, review_status, id, created_at, updated_at
    FROM assets WHERE kind IN ('investment','retirement','bond');
DELETE FROM assets WHERE kind IN ('investment','retirement','bond');
PRAGMA user_version=36;
