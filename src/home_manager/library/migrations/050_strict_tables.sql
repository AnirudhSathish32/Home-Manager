-- Every ordinary table becomes STRICT, so a value of the wrong type is refused instead of stored (a '12.50' in a
-- *_minor column used to become the float 12.5). The same rebuild adds the CHECKs the database audit found missing:
-- run and job states, document source states, tax rule kinds and two booleans (docs/development.md "Database checks": INT-5 to INT-8).
-- The full-text index (document_passages_fts) is a virtual table and stays as it is; its rowids follow document_passages.ids.
-- Generated from the version 49 schema: each table is rebuilt as SQLite documents (new table, copy, drop, rename), then its
-- indexes and triggers are created again. The runner turns foreign keys off for this and checks references before committing.

-- States no current writer uses (left by older versions) become the safe terminal state, so the CHECKs below hold.
UPDATE jobs SET status='interrupted' WHERE status IS NOT NULL AND status NOT IN ('queued','running','completed','partial','failed','interrupted');
UPDATE jobs SET organization_status='interrupted' WHERE organization_status IS NOT NULL AND organization_status NOT IN ('not_started','not_needed','not_configured','queued','running','partial','completed','cancelled','failed','interrupted');
UPDATE receipt_batches SET status='interrupted' WHERE status IS NOT NULL AND status NOT IN ('queued','running','partial','completed','cancelled','interrupted');
UPDATE parse_runs SET status='interrupted' WHERE status IS NOT NULL AND status NOT IN ('queued','running','succeeded','partial','failed','cancelled','interrupted');
UPDATE reasoning_runs SET status='interrupted' WHERE status IS NOT NULL AND status NOT IN ('queued','running','succeeded','failed','cancelled','interrupted');
UPDATE extraction_runs SET status='interrupted' WHERE status IS NOT NULL AND status NOT IN ('queued','running','succeeded','failed','cancelled','interrupted');
UPDATE managed_organization_intents SET status='superseded' WHERE status IS NOT NULL AND status NOT IN ('pending','blocked','superseded','succeeded');

-- accounts
CREATE TABLE "accounts_new" (
    id INTEGER PRIMARY KEY,
    institution TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('checking','savings','credit_card','brokerage','loan','other')),
    display_name TEXT NOT NULL,
    account_last_four TEXT CHECK (account_last_four IS NULL OR account_last_four GLOB '[0-9][0-9][0-9][0-9]'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (active IN (0,1))
) STRICT;
INSERT INTO "accounts_new"("id","institution","account_type","display_name","account_last_four","currency","active","created_at","updated_at") SELECT "id","institution","account_type","display_name","account_last_four","currency","active","created_at","updated_at" FROM "accounts";
DROP TABLE "accounts";
ALTER TABLE "accounts_new" RENAME TO "accounts";
CREATE UNIQUE INDEX accounts_identity ON accounts(institution, account_type, coalesce(account_last_four, ''));

-- analysis_reviews
CREATE TABLE "analysis_reviews_new" (
    reasoning_run_id TEXT PRIMARY KEY REFERENCES reasoning_runs(id),
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_json TEXT,
    error TEXT
) STRICT;
INSERT INTO "analysis_reviews_new"("reasoning_run_id","config_json","status","result_json","error") SELECT "reasoning_run_id","config_json","status","result_json","error" FROM "analysis_reviews";
DROP TABLE "analysis_reviews";
ALTER TABLE "analysis_reviews_new" RENAME TO "analysis_reviews";

-- assets
CREATE TABLE "assets_new" (
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
, blob_hash TEXT REFERENCES blobs(hash), extraction_run_id TEXT, account_key TEXT, validation_json TEXT NOT NULL DEFAULT '[]') STRICT;
INSERT INTO "assets_new"("id","name","kind","value_minor","currency","as_of","annual_rate_bp","monthly_payment_minor","source","document_id","review_status","archived_at","created_at","updated_at","blob_hash","extraction_run_id","account_key","validation_json") SELECT "id","name","kind","value_minor","currency","as_of","annual_rate_bp","monthly_payment_minor","source","document_id","review_status","archived_at","created_at","updated_at","blob_hash","extraction_run_id","account_key","validation_json" FROM "assets";
DROP TABLE "assets";
ALTER TABLE "assets_new" RENAME TO "assets";
CREATE UNIQUE INDEX assets_account ON assets(account_key) WHERE account_key IS NOT NULL;
CREATE INDEX assets_active ON assets(archived_at, review_status);

-- assistant_runs
CREATE TABLE "assistant_runs_new" (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
) STRICT;
INSERT INTO "assistant_runs_new"("id","question","config_json","prompt_version","model_identity","status","created_at","updated_at","result_json","error") SELECT "id","question","config_json","prompt_version","model_identity","status","created_at","updated_at","result_json","error" FROM "assistant_runs";
DROP TABLE "assistant_runs";
ALTER TABLE "assistant_runs_new" RENAME TO "assistant_runs";
CREATE INDEX assistant_runs_created ON assistant_runs(created_at);

-- backups
CREATE TABLE "backups_new" (
    id TEXT PRIMARY KEY,
    destination TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed','cancelled','interrupted')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    schema_version INTEGER NOT NULL,
    file_count INTEGER,
    total_bytes INTEGER,
    manifest_sha256 TEXT,
    error TEXT
) STRICT;
INSERT INTO "backups_new"("id","destination","status","started_at","finished_at","schema_version","file_count","total_bytes","manifest_sha256","error") SELECT "id","destination","status","started_at","finished_at","schema_version","file_count","total_bytes","manifest_sha256","error" FROM "backups";
DROP TABLE "backups";
ALTER TABLE "backups_new" RENAME TO "backups";

-- bills
CREATE TABLE "bills_new" (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL UNIQUE REFERENCES blobs(hash),
    extraction_run_id TEXT,
    provider_merchant_id INTEGER REFERENCES merchants(id),
    account_id INTEGER REFERENCES accounts(id),
    issue_date TEXT,
    due_date TEXT,
    period_start TEXT,
    period_end TEXT,
    amount_due_minor INTEGER CHECK (amount_due_minor IS NULL OR typeof(amount_due_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    payment_status TEXT NOT NULL DEFAULT 'unknown' CHECK (payment_status IN ('unknown','unpaid','paid')),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, payment_transaction_id INTEGER REFERENCES transactions(id), review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic'))) STRICT;
INSERT INTO "bills_new"("id","document_id","blob_hash","extraction_run_id","provider_merchant_id","account_id","issue_date","due_date","period_start","period_end","amount_due_minor","currency","payment_status","review_status","validation_json","created_at","updated_at","payment_transaction_id","review_source") SELECT "id","document_id","blob_hash","extraction_run_id","provider_merchant_id","account_id","issue_date","due_date","period_start","period_end","amount_due_minor","currency","payment_status","review_status","validation_json","created_at","updated_at","payment_transaction_id","review_source" FROM "bills";
DROP TABLE "bills";
ALTER TABLE "bills_new" RENAME TO "bills";

-- blobs
CREATE TABLE "blobs_new" (
    hash TEXT PRIMARY KEY,
    size INTEGER NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "blobs_new"("hash","size","created_at") SELECT "hash","size","created_at" FROM "blobs";
DROP TABLE "blobs";
ALTER TABLE "blobs_new" RENAME TO "blobs";

-- budgets
CREATE TABLE "budgets_new" (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer' AND amount_minor > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, currency)
) STRICT;
INSERT INTO "budgets_new"("id","category","currency","amount_minor","created_at","updated_at") SELECT "id","category","currency","amount_minor","created_at","updated_at" FROM "budgets";
DROP TABLE "budgets";
ALTER TABLE "budgets_new" RENAME TO "budgets";

-- businesses
CREATE TABLE "businesses_new" (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
) STRICT;
INSERT INTO "businesses_new"("id","name","created_at","archived_at") SELECT "id","name","created_at","archived_at" FROM "businesses";
DROP TABLE "businesses";
ALTER TABLE "businesses_new" RENAME TO "businesses";

-- capture_intents
CREATE TABLE "capture_intents_new" (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    source_root TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    folder_year INTEGER NOT NULL,
    folder_month INTEGER NOT NULL,
    hash TEXT NOT NULL,
    size INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL
) STRICT;
INSERT INTO "capture_intents_new"("id","job_id","source_root","relative_path","folder_year","folder_month","hash","size","source_mtime_ns") SELECT "id","job_id","source_root","relative_path","folder_year","folder_month","hash","size","source_mtime_ns" FROM "capture_intents";
DROP TABLE "capture_intents";
ALTER TABLE "capture_intents_new" RENAME TO "capture_intents";

-- category_rules
CREATE TABLE "category_rules_new" (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "category_rules_new"("id","pattern","category","account_id","created_at","updated_at") SELECT "id","pattern","category","account_id","created_at","updated_at" FROM "category_rules";
DROP TABLE "category_rules";
ALTER TABLE "category_rules_new" RENAME TO "category_rules";
CREATE UNIQUE INDEX category_rules_identity ON category_rules(pattern, coalesce(account_id, 0));

-- category_splits
CREATE TABLE "category_splits_new" (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    transaction_id INTEGER REFERENCES transactions(id) ON DELETE CASCADE,
    receipt_item_id INTEGER REFERENCES receipt_items(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer')
) STRICT;
INSERT INTO "category_splits_new"("id","receipt_id","transaction_id","receipt_item_id","category","amount_minor") SELECT "id","receipt_id","transaction_id","receipt_item_id","category","amount_minor" FROM "category_splits";
DROP TABLE "category_splits";
ALTER TABLE "category_splits_new" RENAME TO "category_splits";
CREATE INDEX category_splits_receipt ON category_splits(receipt_id, transaction_id);
CREATE INDEX category_splits_transaction ON category_splits(transaction_id);

-- checkin_runs
CREATE TABLE "checkin_runs_new" (
    id TEXT PRIMARY KEY,
    answer TEXT NOT NULL,
    checkin_on TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "checkin_runs_new"("id","answer","checkin_on","config_json","prompt_version","model_identity","status","result_json","error","created_at","updated_at") SELECT "id","answer","checkin_on","config_json","prompt_version","model_identity","status","result_json","error","created_at","updated_at" FROM "checkin_runs";
DROP TABLE "checkin_runs";
ALTER TABLE "checkin_runs_new" RENAME TO "checkin_runs";

-- document_descriptions
CREATE TABLE "document_descriptions_new" (
    document_id INTEGER PRIMARY KEY REFERENCES occurrences(id),
    description TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "document_descriptions_new"("document_id","description","updated_at") SELECT "document_id","description","updated_at" FROM "document_descriptions";
DROP TABLE "document_descriptions";
ALTER TABLE "document_descriptions_new" RENAME TO "document_descriptions";

-- document_folders
CREATE TABLE "document_folders_new" (
    document_id INTEGER PRIMARY KEY REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    folder TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "document_folders_new"("document_id","blob_hash","folder","updated_at") SELECT "document_id","blob_hash","folder","updated_at" FROM "document_folders";
DROP TABLE "document_folders";
ALTER TABLE "document_folders_new" RENAME TO "document_folders";

-- document_index_state
CREATE TABLE "document_index_state_new" (
    parse_run_id TEXT PRIMARY KEY REFERENCES parse_runs(id),
    index_version INTEGER NOT NULL,
    passages INTEGER NOT NULL,
    indexed_at TEXT NOT NULL
) STRICT;
INSERT INTO "document_index_state_new"("parse_run_id","index_version","passages","indexed_at") SELECT "parse_run_id","index_version","passages","indexed_at" FROM "document_index_state";
DROP TABLE "document_index_state";
ALTER TABLE "document_index_state_new" RENAME TO "document_index_state";

-- document_passages
CREATE TABLE "document_passages_new" (
    id INTEGER PRIMARY KEY,
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    ordinal INTEGER NOT NULL,
    line_ids TEXT NOT NULL,
    text TEXT NOT NULL,
    UNIQUE (parse_run_id, ordinal)
) STRICT;
INSERT INTO "document_passages_new"("id","parse_run_id","ordinal","line_ids","text") SELECT "id","parse_run_id","ordinal","line_ids","text" FROM "document_passages";
DROP TABLE "document_passages";
ALTER TABLE "document_passages_new" RENAME TO "document_passages";
CREATE TRIGGER document_passages_ad AFTER DELETE ON document_passages BEGIN
    INSERT INTO document_passages_fts(document_passages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER document_passages_ai AFTER INSERT ON document_passages BEGIN
    INSERT INTO document_passages_fts(rowid, text) VALUES (new.id, new.text);
END;

-- employers
CREATE TABLE "employers_new" (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    folder_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "employers_new"("id","name","folder_name","created_at") SELECT "id","name","folder_name","created_at" FROM "employers";
DROP TABLE "employers";
ALTER TABLE "employers_new" RENAME TO "employers";

-- events
CREATE TABLE "events_new" (
    id INTEGER PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id),
    relative_path TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT NOT NULL,
    hash TEXT,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "events_new"("id","job_id","relative_path","status","message","hash","created_at") SELECT "id","job_id","relative_path","status","message","hash","created_at" FROM "events";
DROP TABLE "events";
ALTER TABLE "events_new" RENAME TO "events";
CREATE INDEX events_job ON events(job_id, id);

-- extraction_runs
CREATE TABLE "extraction_runs_new" (
    id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL,
    document_type TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    publication_json TEXT,
    error TEXT,
    CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted'))
) STRICT;
INSERT INTO "extraction_runs_new"("id","document_id","parse_run_id","config_json","prompt_version","model_identity","status","document_type","created_at","updated_at","result_json","publication_json","error") SELECT "id","document_id","parse_run_id","config_json","prompt_version","model_identity","status","document_type","created_at","updated_at","result_json","publication_json","error" FROM "extraction_runs";
DROP TABLE "extraction_runs";
ALTER TABLE "extraction_runs_new" RENAME TO "extraction_runs";
CREATE INDEX extraction_runs_document ON extraction_runs(document_id, created_at);
CREATE INDEX extraction_source ON extraction_runs(parse_run_id, created_at);

-- family_assignments
CREATE TABLE "family_assignments_new" (
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill','statement','income_record')),
    record_id INTEGER NOT NULL,
    family_record_key TEXT NOT NULL UNIQUE,
    mode TEXT CHECK (mode IS NULL OR mode IN ('member','shared')),
    members_json TEXT NOT NULL DEFAULT '[]',
    suggested_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('unassigned','suggested','confirmed','delivered')),
    delivered_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id)
) STRICT;
INSERT INTO "family_assignments_new"("record_type","record_id","family_record_key","mode","members_json","suggested_json","status","delivered_json","updated_at") SELECT "record_type","record_id","family_record_key","mode","members_json","suggested_json","status","delivered_json","updated_at" FROM "family_assignments";
DROP TABLE "family_assignments";
ALTER TABLE "family_assignments_new" RENAME TO "family_assignments";

-- financial_evidence_links
CREATE TABLE "financial_evidence_links_new" (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('statement','transaction','receipt','receipt_item','bill','income_record')),
    record_id INTEGER NOT NULL,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    parse_run_id TEXT REFERENCES parse_runs(id),
    source_key TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(record_type, record_id, source_key)
) STRICT;
INSERT INTO "financial_evidence_links_new"("id","record_type","record_id","document_id","blob_hash","parse_run_id","source_key","locator_json","created_at") SELECT "id","record_type","record_id","document_id","blob_hash","parse_run_id","source_key","locator_json","created_at" FROM "financial_evidence_links";
DROP TABLE "financial_evidence_links";
ALTER TABLE "financial_evidence_links_new" RENAME TO "financial_evidence_links";
CREATE INDEX evidence_record ON financial_evidence_links(record_type, record_id);

-- folder_aliases
CREATE TABLE "folder_aliases_new" (old_folder TEXT PRIMARY KEY, folder TEXT NOT NULL) STRICT;
INSERT INTO "folder_aliases_new"("old_folder","folder") SELECT "old_folder","folder" FROM "folder_aliases";
DROP TABLE "folder_aliases";
ALTER TABLE "folder_aliases_new" RENAME TO "folder_aliases";

-- holdings
CREATE TABLE "holdings_new" (
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
    updated_at TEXT NOT NULL, face_minor INTEGER CHECK (face_minor IS NULL OR (typeof(face_minor) = 'integer' AND face_minor >= 0)), redeemable_date TEXT, rollover INTEGER NOT NULL DEFAULT 0 CHECK (rollover IN (0,1)), source TEXT NOT NULL DEFAULT 'statement' CHECK (source IN ('statement','confirmation','manual')), confirmation_id INTEGER REFERENCES investment_confirmations(id) ON DELETE SET NULL,
    UNIQUE (account_id, holding_key)
) STRICT;
INSERT INTO "holdings_new"("id","account_id","instrument_class","name","identifier","holding_key","rate_bp","issue_date","maturity_date","principal_minor","archived_at","created_at","updated_at","face_minor","redeemable_date","rollover","source","confirmation_id") SELECT "id","account_id","instrument_class","name","identifier","holding_key","rate_bp","issue_date","maturity_date","principal_minor","archived_at","created_at","updated_at","face_minor","redeemable_date","rollover","source","confirmation_id" FROM "holdings";
DROP TABLE "holdings";
ALTER TABLE "holdings_new" RENAME TO "holdings";

-- income_lines
CREATE TABLE "income_lines_new" (
    id INTEGER PRIMARY KEY,
    income_record_id INTEGER NOT NULL REFERENCES income_records(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    description TEXT NOT NULL,
    line_group TEXT NOT NULL CHECK (line_group IN ('earnings','pre_tax','tax','post_tax','employer_paid')),
    category TEXT NOT NULL,
    current_minor INTEGER CHECK (current_minor IS NULL OR typeof(current_minor) = 'integer'),
    ytd_minor INTEGER CHECK (ytd_minor IS NULL OR typeof(ytd_minor) = 'integer'),
    locator_json TEXT NOT NULL,
    UNIQUE (income_record_id, position)
) STRICT;
INSERT INTO "income_lines_new"("id","income_record_id","position","description","line_group","category","current_minor","ytd_minor","locator_json") SELECT "id","income_record_id","position","description","line_group","category","current_minor","ytd_minor","locator_json" FROM "income_lines";
DROP TABLE "income_lines";
ALTER TABLE "income_lines_new" RENAME TO "income_lines";

-- income_records
CREATE TABLE "income_records_new" (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL UNIQUE REFERENCES blobs(hash),
    extraction_run_id TEXT,
    payer_merchant_id INTEGER REFERENCES merchants(id),
    pay_date TEXT,
    period_start TEXT,
    period_end TEXT,
    gross_pay_minor INTEGER CHECK (gross_pay_minor IS NULL OR typeof(gross_pay_minor) = 'integer'),
    net_pay_minor INTEGER CHECK (net_pay_minor IS NULL OR typeof(net_pay_minor) = 'integer'),
    taxes_minor INTEGER CHECK (taxes_minor IS NULL OR typeof(taxes_minor) = 'integer'),
    deductions_minor INTEGER CHECK (deductions_minor IS NULL OR typeof(deductions_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic')), gross_pay_ytd_minor INTEGER, net_pay_ytd_minor INTEGER, work_state TEXT, pay_frequency INTEGER CHECK (pay_frequency IS NULL OR pay_frequency IN (12, 24, 26, 52))) STRICT;
INSERT INTO "income_records_new"("id","document_id","blob_hash","extraction_run_id","payer_merchant_id","pay_date","period_start","period_end","gross_pay_minor","net_pay_minor","taxes_minor","deductions_minor","currency","review_status","validation_json","created_at","updated_at","review_source","gross_pay_ytd_minor","net_pay_ytd_minor","work_state","pay_frequency") SELECT "id","document_id","blob_hash","extraction_run_id","payer_merchant_id","pay_date","period_start","period_end","gross_pay_minor","net_pay_minor","taxes_minor","deductions_minor","currency","review_status","validation_json","created_at","updated_at","review_source","gross_pay_ytd_minor","net_pay_ytd_minor","work_state","pay_frequency" FROM "income_records";
DROP TABLE "income_records";
ALTER TABLE "income_records_new" RENAME TO "income_records";

-- inventory_lots
CREATE TABLE "inventory_lots_new" (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    position INTEGER,
    units TEXT,
    cost_minor INTEGER CHECK (cost_minor IS NULL OR typeof(cost_minor) = 'integer'),
    currency TEXT CHECK (currency IS NULL OR length(currency) = 3),
    bought_on TEXT,
    status TEXT NOT NULL CHECK (status IN ('in_stock','finished','thrown_out')),
    closed_on TEXT,
    closed_precision_days INTEGER NOT NULL DEFAULT 0,
    next_check_on TEXT,
    check_interval_days INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, opened_on TEXT,
    UNIQUE(receipt_id, position)
) STRICT;
INSERT INTO "inventory_lots_new"("id","product_id","receipt_id","position","units","cost_minor","currency","bought_on","status","closed_on","closed_precision_days","next_check_on","check_interval_days","created_at","updated_at","opened_on") SELECT "id","product_id","receipt_id","position","units","cost_minor","currency","bought_on","status","closed_on","closed_precision_days","next_check_on","check_interval_days","created_at","updated_at","opened_on" FROM "inventory_lots";
DROP TABLE "inventory_lots";
ALTER TABLE "inventory_lots_new" RENAME TO "inventory_lots";
CREATE INDEX inventory_lots_check ON inventory_lots(status, next_check_on);
CREATE INDEX inventory_lots_product ON inventory_lots(product_id, status, bought_on);

-- investment_accounts
CREATE TABLE "investment_accounts_new" (
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
    -- A savings account also in the ledger, so its cash is counted once (docs/planning.md "Reading statements").
    ledger_account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL,
    source TEXT NOT NULL CHECK (source IN ('manual','statement')),
    archived_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, payroll_merchant_id INTEGER REFERENCES merchants(id) ON DELETE SET NULL, payroll_link TEXT CHECK (payroll_link IS NULL OR payroll_link IN ('auto','user','none')), monthly_contribution_minor INTEGER
    CHECK (monthly_contribution_minor IS NULL OR (typeof(monthly_contribution_minor) = 'integer' AND monthly_contribution_minor >= 0))) STRICT;
INSERT INTO "investment_accounts_new"("id","kind","name","institution","currency","account_key","tax_treatment","annual_rate_bp","ledger_account_id","source","archived_at","created_at","updated_at","payroll_merchant_id","payroll_link","monthly_contribution_minor") SELECT "id","kind","name","institution","currency","account_key","tax_treatment","annual_rate_bp","ledger_account_id","source","archived_at","created_at","updated_at","payroll_merchant_id","payroll_link","monthly_contribution_minor" FROM "investment_accounts";
DROP TABLE "investment_accounts";
ALTER TABLE "investment_accounts_new" RENAME TO "investment_accounts";
CREATE UNIQUE INDEX investment_accounts_ledger ON investment_accounts(ledger_account_id) WHERE ledger_account_id IS NOT NULL;

-- investment_confirmations
CREATE TABLE "investment_confirmations_new" (
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
) STRICT;
INSERT INTO "investment_confirmations_new"("id","account_id","document_id","blob_hash","extraction_run_id","trade_date","validation_json","review_status","created_at","updated_at") SELECT "id","account_id","document_id","blob_hash","extraction_run_id","trade_date","validation_json","review_status","created_at","updated_at" FROM "investment_confirmations";
DROP TABLE "investment_confirmations";
ALTER TABLE "investment_confirmations_new" RENAME TO "investment_confirmations";

-- investment_events
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
    reverses_event_id INTEGER REFERENCES investment_events(id),
    note TEXT NOT NULL DEFAULT '',
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL
, confirmation_id INTEGER REFERENCES investment_confirmations(id) ON DELETE CASCADE, transaction_previous_type TEXT, transaction_link TEXT CHECK (transaction_link IS NULL OR transaction_link IN ('auto','user')),
    CHECK (transaction_previous_type IS NULL OR transaction_previous_type IN ('purchase','refund','payment','transfer','deposit','fee','interest','withdrawal','other'))
) STRICT;
INSERT INTO "investment_events_new"("id","account_id","holding_id","event_date","event_type","contribution_source","amount_minor","quantity","transaction_id","income_line_id","document_id","blob_hash","reverses_event_id","note","review_status","created_at","confirmation_id","transaction_previous_type","transaction_link") SELECT "id","account_id","holding_id","event_date","event_type","contribution_source","amount_minor","quantity","transaction_id","income_line_id","document_id","blob_hash","reverses_event_id","note","review_status","created_at","confirmation_id","transaction_previous_type","transaction_link" FROM "investment_events";
DROP TABLE "investment_events";
ALTER TABLE "investment_events_new" RENAME TO "investment_events";
CREATE INDEX investment_events_account ON investment_events(account_id, event_date);
CREATE INDEX investment_events_confirmation ON investment_events(confirmation_id);
CREATE INDEX investment_events_source ON investment_events(account_id, blob_hash);

-- investment_kinds
CREATE TABLE "investment_kinds_new" (
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
) STRICT;
INSERT INTO "investment_kinds_new"("key","label","section","tax_treatment","value_model","has_maturity","default_rate_bp","position") SELECT "key","label","section","tax_treatment","value_model","has_maturity","default_rate_bp","position" FROM "investment_kinds";
DROP TABLE "investment_kinds";
ALTER TABLE "investment_kinds_new" RENAME TO "investment_kinds";

-- investment_payment_rejections
CREATE TABLE "investment_payment_rejections_new" (
    event_id INTEGER NOT NULL REFERENCES investment_events(id) ON DELETE CASCADE,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, transaction_id)
) STRICT;
INSERT INTO "investment_payment_rejections_new"("event_id","transaction_id","created_at") SELECT "event_id","transaction_id","created_at" FROM "investment_payment_rejections";
DROP TABLE "investment_payment_rejections";
ALTER TABLE "investment_payment_rejections_new" RENAME TO "investment_payment_rejections";

-- investment_valuations
CREATE TABLE "investment_valuations_new" (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    holding_id INTEGER REFERENCES holdings(id) ON DELETE CASCADE,
    as_of TEXT NOT NULL,
    value_minor INTEGER NOT NULL CHECK (typeof(value_minor) = 'integer' AND value_minor >= 0),
    quantity TEXT,
    price_minor INTEGER,
    cost_basis_minor INTEGER,
    source TEXT NOT NULL CHECK (source IN ('manual','statement')),
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

-- item_aliases
CREATE TABLE "item_aliases_new" (
    id INTEGER PRIMARY KEY,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
    normalized_text TEXT NOT NULL,
    product_code TEXT,
    product_id INTEGER NOT NULL REFERENCES products(id),
    created_at TEXT NOT NULL,
    UNIQUE(merchant_id, normalized_text)
) STRICT;
INSERT INTO "item_aliases_new"("id","merchant_id","normalized_text","product_code","product_id","created_at") SELECT "id","merchant_id","normalized_text","product_code","product_id","created_at" FROM "item_aliases";
DROP TABLE "item_aliases";
ALTER TABLE "item_aliases_new" RENAME TO "item_aliases";
CREATE INDEX item_aliases_code ON item_aliases(merchant_id, product_code);

-- item_category_memory
CREATE TABLE "item_category_memory_new" (
    merchant_key TEXT NOT NULL,
    item_key TEXT NOT NULL,
    category TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (merchant_key, item_key)
) STRICT;
INSERT INTO "item_category_memory_new"("merchant_key","item_key","category","updated_at") SELECT "merchant_key","item_key","category","updated_at" FROM "item_category_memory";
DROP TABLE "item_category_memory";
ALTER TABLE "item_category_memory_new" RENAME TO "item_category_memory";

-- item_resolution_runs
CREATE TABLE "item_resolution_runs_new" (
    id TEXT PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    result_json TEXT,
    error TEXT,
    model_identity TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "item_resolution_runs_new"("id","receipt_id","config_json","prompt_version","status","result_json","error","model_identity","created_at","updated_at") SELECT "id","receipt_id","config_json","prompt_version","status","result_json","error","model_identity","created_at","updated_at" FROM "item_resolution_runs";
DROP TABLE "item_resolution_runs";
ALTER TABLE "item_resolution_runs_new" RENAME TO "item_resolution_runs";

-- item_resolutions
CREATE TABLE "item_resolutions_new" (
    id INTEGER PRIMARY KEY,
    receipt_item_id INTEGER NOT NULL REFERENCES receipt_items(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id),
    name TEXT NOT NULL,
    brand TEXT,
    size_text TEXT,
    category TEXT NOT NULL,
    consumable INTEGER NOT NULL CHECK (consumable IN (0,1)),
    barcode TEXT,
    confidence TEXT NOT NULL CHECK (confidence IN ('low','medium','high')),
    method TEXT NOT NULL CHECK (method IN ('alias','history','barcode','search','user')),
    sources_json TEXT NOT NULL DEFAULT '[]',
    run_id TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    reviewed_at TEXT
) STRICT;
INSERT INTO "item_resolutions_new"("id","receipt_item_id","product_id","name","brand","size_text","category","consumable","barcode","confidence","method","sources_json","run_id","review_status","created_at","reviewed_at") SELECT "id","receipt_item_id","product_id","name","brand","size_text","category","consumable","barcode","confidence","method","sources_json","run_id","review_status","created_at","reviewed_at" FROM "item_resolutions";
DROP TABLE "item_resolutions";
ALTER TABLE "item_resolutions_new" RENAME TO "item_resolutions";
CREATE INDEX item_resolutions_item ON item_resolutions(receipt_item_id, review_status);

-- job_filings
CREATE TABLE "job_filings_new" (
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL,
    employer_id INTEGER NOT NULL REFERENCES employers(id),
    section TEXT NOT NULL CHECK (section IN ('Paystubs','Documents')),
    label TEXT,  -- In the file name (letters only): Offer_Letter.
    title TEXT,  -- Shown in the library, as printed: Offer Letter, W-2.
    PRIMARY KEY (document_id, blob_hash)
) STRICT;
INSERT INTO "job_filings_new"("document_id","blob_hash","employer_id","section","label","title") SELECT "document_id","blob_hash","employer_id","section","label","title" FROM "job_filings";
DROP TABLE "job_filings";
ALTER TABLE "job_filings_new" RENAME TO "job_filings";

-- jobs
CREATE TABLE "jobs_new" (
    id TEXT PRIMARY KEY,
    source_root TEXT NOT NULL,
    year INTEGER,
    month INTEGER,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT
, organization_status TEXT, organization_message TEXT, organization_batch_id TEXT REFERENCES receipt_batches(id),
    CHECK (status IN ('queued','running','completed','partial','failed','interrupted')),
    CHECK (organization_status IS NULL OR organization_status IN ('not_started','not_needed','not_configured','queued','running','partial','completed','cancelled','failed','interrupted'))
) STRICT;
INSERT INTO "jobs_new"("id","source_root","year","month","status","created_at","updated_at","error","organization_status","organization_message","organization_batch_id") SELECT "id","source_root","year","month","status","created_at","updated_at","error","organization_status","organization_message","organization_batch_id" FROM "jobs";
DROP TABLE "jobs";
ALTER TABLE "jobs_new" RENAME TO "jobs";

-- library_events
CREATE TABLE "library_events_new" (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "library_events_new"("id","document_id","blob_hash","action","detail","created_at") SELECT "id","document_id","blob_hash","action","detail","created_at" FROM "library_events";
DROP TABLE "library_events";
ALTER TABLE "library_events_new" RENAME TO "library_events";

-- lot_events
CREATE TABLE "lot_events_new" (
    id INTEGER PRIMARY KEY,
    lot_id INTEGER NOT NULL REFERENCES inventory_lots(id) ON DELETE CASCADE,
    event TEXT NOT NULL CHECK (event IN ('created','still_have','finished','thrown_out','reopened','opened','undone')),
    effective_on TEXT NOT NULL,
    precision_days INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL CHECK (source IN ('approval','manual','checkin','checkin_text')),
    previous_json TEXT,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "lot_events_new"("id","lot_id","event","effective_on","precision_days","source","previous_json","created_at") SELECT "id","lot_id","event","effective_on","precision_days","source","previous_json","created_at" FROM "lot_events";
DROP TABLE "lot_events";
ALTER TABLE "lot_events_new" RENAME TO "lot_events";
CREATE INDEX lot_events_lot ON lot_events(lot_id, id);

-- managed_files
CREATE TABLE "managed_files_new" (
 document_id INTEGER NOT NULL REFERENCES occurrences(id),
 blob_hash TEXT NOT NULL REFERENCES blobs(hash),
 relative_path TEXT NOT NULL UNIQUE,
 folder TEXT NOT NULL,
 reason TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 PRIMARY KEY(document_id,blob_hash)
) STRICT;
INSERT INTO "managed_files_new"("document_id","blob_hash","relative_path","folder","reason","updated_at") SELECT "document_id","blob_hash","relative_path","folder","reason","updated_at" FROM "managed_files";
DROP TABLE "managed_files";
ALTER TABLE "managed_files_new" RENAME TO "managed_files";

-- managed_organization_events
CREATE TABLE "managed_organization_events_new" (
 id INTEGER PRIMARY KEY,
 intent_id TEXT NOT NULL UNIQUE REFERENCES managed_organization_intents(id),
 document_id INTEGER NOT NULL REFERENCES occurrences(id),
 blob_hash TEXT NOT NULL REFERENCES blobs(hash),
 source_path TEXT,
 target_path TEXT NOT NULL,
 action TEXT NOT NULL,
 created_at TEXT NOT NULL
) STRICT;
INSERT INTO "managed_organization_events_new"("id","intent_id","document_id","blob_hash","source_path","target_path","action","created_at") SELECT "id","intent_id","document_id","blob_hash","source_path","target_path","action","created_at" FROM "managed_organization_events";
DROP TABLE "managed_organization_events";
ALTER TABLE "managed_organization_events_new" RENAME TO "managed_organization_events";

-- managed_organization_intents
CREATE TABLE "managed_organization_intents_new" (
 id TEXT PRIMARY KEY,
 document_id INTEGER NOT NULL REFERENCES occurrences(id),
 blob_hash TEXT NOT NULL REFERENCES blobs(hash),
 source_path TEXT,
 target_path TEXT NOT NULL,
 folder TEXT NOT NULL,
 reason TEXT NOT NULL,
 action TEXT NOT NULL,
 status TEXT NOT NULL,
 created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL,
 error TEXT,
    CHECK (status IN ('pending','blocked','superseded','succeeded'))
) STRICT;
INSERT INTO "managed_organization_intents_new"("id","document_id","blob_hash","source_path","target_path","folder","reason","action","status","created_at","updated_at","error") SELECT "id","document_id","blob_hash","source_path","target_path","folder","reason","action","status","created_at","updated_at","error" FROM "managed_organization_intents";
DROP TABLE "managed_organization_intents";
ALTER TABLE "managed_organization_intents_new" RENAME TO "managed_organization_intents";
CREATE UNIQUE INDEX managed_active_intent ON managed_organization_intents(document_id,blob_hash)
 WHERE status IN ('pending','blocked');
CREATE INDEX managed_intents_document ON managed_organization_intents(document_id, blob_hash, created_at);

-- merchants
CREATE TABLE "merchants_new" (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "merchants_new"("id","canonical_name","normalized_name","created_at","updated_at") SELECT "id","canonical_name","normalized_name","created_at","updated_at" FROM "merchants";
DROP TABLE "merchants";
ALTER TABLE "merchants_new" RENAME TO "merchants";

-- model_identities
CREATE TABLE "model_identities_new" (
    fingerprint TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    base_url TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    first_seen TEXT NOT NULL
) STRICT;
INSERT INTO "model_identities_new"("fingerprint","model_id","base_url","metadata_json","first_seen") SELECT "fingerprint","model_id","base_url","metadata_json","first_seen" FROM "model_identities";
DROP TABLE "model_identities";
ALTER TABLE "model_identities_new" RENAME TO "model_identities";

-- model_runs
CREATE TABLE "model_runs_new" (
    id INTEGER PRIMARY KEY,
    task TEXT NOT NULL,
    owner_id TEXT,
    model_id TEXT NOT NULL,
    model_identity TEXT,
    base_url TEXT NOT NULL,
    prompt_version TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT NOT NULL,
    time_to_first_token_ms REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    prompt_eval_ms REAL,
    generation_ms REAL,
    total_ms REAL NOT NULL,
    prompt_tokens_per_second REAL,
    generation_tokens_per_second REAL,
    metrics_source TEXT NOT NULL,
    input_bytes INTEGER NOT NULL,
    output_bytes INTEGER NOT NULL,
    finish_reason TEXT,
    status TEXT NOT NULL,
    error_category TEXT
) STRICT;
INSERT INTO "model_runs_new"("id","task","owner_id","model_id","model_identity","base_url","prompt_version","started_at","finished_at","time_to_first_token_ms","prompt_tokens","completion_tokens","prompt_eval_ms","generation_ms","total_ms","prompt_tokens_per_second","generation_tokens_per_second","metrics_source","input_bytes","output_bytes","finish_reason","status","error_category") SELECT "id","task","owner_id","model_id","model_identity","base_url","prompt_version","started_at","finished_at","time_to_first_token_ms","prompt_tokens","completion_tokens","prompt_eval_ms","generation_ms","total_ms","prompt_tokens_per_second","generation_tokens_per_second","metrics_source","input_bytes","output_bytes","finish_reason","status","error_category" FROM "model_runs";
DROP TABLE "model_runs";
ALTER TABLE "model_runs_new" RENAME TO "model_runs";
CREATE INDEX model_runs_owner ON model_runs(owner_id, started_at);
CREATE INDEX model_runs_started ON model_runs(started_at);

-- occurrences
CREATE TABLE "occurrences_new" (
    id INTEGER PRIMARY KEY,
    source_root TEXT NOT NULL,
    path_key TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    folder_year INTEGER NOT NULL,
    folder_month INTEGER NOT NULL,
    current_hash TEXT NOT NULL REFERENCES blobs(hash),
    source_status TEXT NOT NULL DEFAULT 'present',
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    last_job TEXT NOT NULL REFERENCES jobs(id), deleted_at TEXT, source_kind TEXT NOT NULL DEFAULT 'external',
    UNIQUE(source_root, path_key),
    CHECK (source_status IN ('present','missing','organized','rejected','not_captured','unavailable')),
    CHECK (source_kind IN ('external','inbox'))
) STRICT;
INSERT INTO "occurrences_new"("id","source_root","path_key","relative_path","folder_year","folder_month","current_hash","source_status","first_seen","last_seen","last_job","deleted_at","source_kind") SELECT "id","source_root","path_key","relative_path","folder_year","folder_month","current_hash","source_status","first_seen","last_seen","last_job","deleted_at","source_kind" FROM "occurrences";
DROP TABLE "occurrences";
ALTER TABLE "occurrences_new" RENAME TO "occurrences";
CREATE INDEX occurrences_root ON occurrences(source_root, folder_year, folder_month);

-- organization_runs
CREATE TABLE "organization_runs_new" (
    id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    config_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_folder TEXT,
    error TEXT
) STRICT;
INSERT INTO "organization_runs_new"("id","document_id","blob_hash","parse_run_id","config_json","status","created_at","updated_at","result_folder","error") SELECT "id","document_id","blob_hash","parse_run_id","config_json","status","created_at","updated_at","result_folder","error" FROM "organization_runs";
DROP TABLE "organization_runs";
ALTER TABLE "organization_runs_new" RENAME TO "organization_runs";
CREATE INDEX organization_document ON organization_runs(document_id, blob_hash, created_at);

-- parse_runs
CREATE TABLE "parse_runs_new" (
    id TEXT PRIMARY KEY,
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    parser_version TEXT NOT NULL,
    options_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    error TEXT,
    result_json TEXT,
    preview_hash TEXT
, model_identity TEXT,
    CHECK (status IN ('queued','running','succeeded','partial','failed','cancelled','interrupted'))
) STRICT;
INSERT INTO "parse_runs_new"("id","blob_hash","parser_version","options_json","status","created_at","updated_at","error","result_json","preview_hash","model_identity") SELECT "id","blob_hash","parser_version","options_json","status","created_at","updated_at","error","result_json","preview_hash","model_identity" FROM "parse_runs";
DROP TABLE "parse_runs";
ALTER TABLE "parse_runs_new" RENAME TO "parse_runs";
CREATE UNIQUE INDEX parse_runs_active ON parse_runs(blob_hash, parser_version, options_json)
    WHERE status IN ('queued', 'running');
CREATE INDEX parse_runs_blob ON parse_runs(blob_hash, created_at);

-- payee_recurrence
CREATE TABLE "payee_recurrence_new" (
    payee_key TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    recurrence TEXT CHECK (recurrence IS NULL OR recurrence IN ('weekly','monthly','quarterly','semiannual','annual')),
    category TEXT,
    model TEXT,
    asked_at TEXT NOT NULL,
    PRIMARY KEY (payee_key, currency)
) STRICT;
INSERT INTO "payee_recurrence_new"("payee_key","currency","recurrence","category","model","asked_at") SELECT "payee_key","currency","recurrence","category","model","asked_at" FROM "payee_recurrence";
DROP TABLE "payee_recurrence";
ALTER TABLE "payee_recurrence_new" RENAME TO "payee_recurrence";

-- products
CREATE TABLE "products_new" (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    brand TEXT,
    size_text TEXT,
    category TEXT NOT NULL,
    consumable INTEGER NOT NULL CHECK (consumable IN (0,1)),
    barcode TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(normalized_name, brand, size_text)
) STRICT;
INSERT INTO "products_new"("id","name","normalized_name","brand","size_text","category","consumable","barcode","created_at","updated_at") SELECT "id","name","normalized_name","brand","size_text","category","consumable","barcode","created_at","updated_at" FROM "products";
DROP TABLE "products";
ALTER TABLE "products_new" RENAME TO "products";

-- reasoning_runs
CREATE TABLE "reasoning_runs_new" (
    id TEXT PRIMARY KEY,
    parse_run_id TEXT NOT NULL REFERENCES parse_runs(id),
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    result_json TEXT,
    error TEXT
, model_identity TEXT,
    CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted'))
) STRICT;
INSERT INTO "reasoning_runs_new"("id","parse_run_id","config_json","prompt_version","status","created_at","updated_at","result_json","error","model_identity") SELECT "id","parse_run_id","config_json","prompt_version","status","created_at","updated_at","result_json","error","model_identity" FROM "reasoning_runs";
DROP TABLE "reasoning_runs";
ALTER TABLE "reasoning_runs_new" RENAME TO "reasoning_runs";
CREATE INDEX reasoning_source ON reasoning_runs(parse_run_id, created_at);

-- receipt_batch_items
CREATE TABLE "receipt_batch_items_new" (
    batch_id TEXT NOT NULL REFERENCES receipt_batches(id),
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    run_id TEXT NOT NULL REFERENCES parse_runs(id),
    reused INTEGER NOT NULL,
    PRIMARY KEY(batch_id, document_id),
    CHECK (reused IN (0,1))
) STRICT;
INSERT INTO "receipt_batch_items_new"("batch_id","document_id","run_id","reused") SELECT "batch_id","document_id","run_id","reused" FROM "receipt_batch_items";
DROP TABLE "receipt_batch_items";
ALTER TABLE "receipt_batch_items_new" RENAME TO "receipt_batch_items";

-- receipt_batches
CREATE TABLE "receipt_batches_new" (
    id TEXT PRIMARY KEY,
    source_root TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    skipped INTEGER NOT NULL DEFAULT 0,
    CHECK (status IN ('queued','running','partial','completed','cancelled','interrupted'))
) STRICT;
INSERT INTO "receipt_batches_new"("id","source_root","status","created_at","skipped") SELECT "id","source_root","status","created_at","skipped" FROM "receipt_batches";
DROP TABLE "receipt_batches";
ALTER TABLE "receipt_batches_new" RENAME TO "receipt_batches";

-- receipt_items
CREATE TABLE "receipt_items_new" (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    description TEXT NOT NULL,
    product_code TEXT,
    quantity TEXT,
    unit_price_minor INTEGER CHECK (unit_price_minor IS NULL OR typeof(unit_price_minor) = 'integer'),
    line_total_minor INTEGER CHECK (line_total_minor IS NULL OR typeof(line_total_minor) = 'integer'),
    discount_minor INTEGER CHECK (discount_minor IS NULL OR typeof(discount_minor) = 'integer'),
    category TEXT,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')), taxed INTEGER CHECK (taxed IS NULL OR taxed IN (0,1)), category_source TEXT CHECK (category_source IS NULL OR category_source IN ('model','memory','receipt','user','legacy')),
    UNIQUE(receipt_id, position)
) STRICT;
INSERT INTO "receipt_items_new"("id","receipt_id","position","description","product_code","quantity","unit_price_minor","line_total_minor","discount_minor","category","review_status","taxed","category_source") SELECT "id","receipt_id","position","description","product_code","quantity","unit_price_minor","line_total_minor","discount_minor","category","review_status","taxed","category_source" FROM "receipt_items";
DROP TABLE "receipt_items";
ALTER TABLE "receipt_items_new" RENAME TO "receipt_items";

-- receipt_rewards
CREATE TABLE "receipt_rewards_new" (
    id INTEGER PRIMARY KEY,
    receipt_id INTEGER NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('earned','redeemed','balance','offer','survey','membership')),
    description TEXT NOT NULL,
    amount_text TEXT,
    expires_on TEXT,
    link TEXT,
    locator_json TEXT NOT NULL,
    UNIQUE(receipt_id, position)
) STRICT;
INSERT INTO "receipt_rewards_new"("id","receipt_id","position","kind","description","amount_text","expires_on","link","locator_json") SELECT "id","receipt_id","position","kind","description","amount_text","expires_on","link","locator_json" FROM "receipt_rewards";
DROP TABLE "receipt_rewards";
ALTER TABLE "receipt_rewards_new" RENAME TO "receipt_rewards";

-- receipts
CREATE TABLE "receipts_new" (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL UNIQUE REFERENCES blobs(hash),
    extraction_run_id TEXT,
    merchant_id INTEGER REFERENCES merchants(id),
    purchase_date TEXT,
    subtotal_minor INTEGER CHECK (subtotal_minor IS NULL OR typeof(subtotal_minor) = 'integer'),
    tax_minor INTEGER CHECK (tax_minor IS NULL OR typeof(tax_minor) = 'integer'),
    tip_minor INTEGER CHECK (tip_minor IS NULL OR typeof(tip_minor) = 'integer'),
    total_minor INTEGER CHECK (total_minor IS NULL OR typeof(total_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, description TEXT, review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic')), location TEXT, return_days_printed INTEGER CHECK (return_days_printed IS NULL OR return_days_printed BETWEEN 0 AND 730), return_policy_quote TEXT, category TEXT, recurrence TEXT CHECK (recurrence IS NULL OR recurrence IN ('weekly','monthly','quarterly','semiannual','annual')), payment_last_four TEXT CHECK (payment_last_four IS NULL OR payment_last_four GLOB '[0-9][0-9][0-9][0-9]')) STRICT;
INSERT INTO "receipts_new"("id","document_id","blob_hash","extraction_run_id","merchant_id","purchase_date","subtotal_minor","tax_minor","tip_minor","total_minor","currency","review_status","validation_json","created_at","updated_at","description","review_source","location","return_days_printed","return_policy_quote","category","recurrence","payment_last_four") SELECT "id","document_id","blob_hash","extraction_run_id","merchant_id","purchase_date","subtotal_minor","tax_minor","tip_minor","total_minor","currency","review_status","validation_json","created_at","updated_at","description","review_source","location","return_days_printed","return_policy_quote","category","recurrence","payment_last_four" FROM "receipts";
DROP TABLE "receipts";
ALTER TABLE "receipts_new" RENAME TO "receipts";

-- reconciliation_issues
CREATE TABLE "reconciliation_issues_new" (
    id INTEGER PRIMARY KEY,
    issue_type TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    detail_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, resolution TEXT
    CHECK (resolution IS NULL OR resolution IN ('linked','left_unmatched')),
    UNIQUE(issue_type, record_type, record_id)
) STRICT;
INSERT INTO "reconciliation_issues_new"("id","issue_type","record_type","record_id","detail_json","status","created_at","updated_at","resolution") SELECT "id","issue_type","record_type","record_id","detail_json","status","created_at","updated_at","resolution" FROM "reconciliation_issues";
DROP TABLE "reconciliation_issues";
ALTER TABLE "reconciliation_issues_new" RENAME TO "reconciliation_issues";
CREATE INDEX reconciliation_issues_record ON reconciliation_issues(record_type, record_id);

-- reconciliation_runs
CREATE TABLE "reconciliation_runs_new" (
    id INTEGER PRIMARY KEY,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual','import','extraction','resolution','correction')),
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    receipt_links INTEGER,
    transfers INTEGER,
    refunds INTEGER,
    recurring INTEGER,
    open_issues INTEGER,
    error TEXT
) STRICT;
INSERT INTO "reconciliation_runs_new"("id","trigger","status","started_at","finished_at","receipt_links","transfers","refunds","recurring","open_issues","error") SELECT "id","trigger","status","started_at","finished_at","receipt_links","transfers","refunds","recurring","open_issues","error" FROM "reconciliation_runs";
DROP TABLE "reconciliation_runs";
ALTER TABLE "reconciliation_runs_new" RENAME TO "reconciliation_runs";
CREATE INDEX reconciliation_runs_started ON reconciliation_runs(started_at);

-- record_corrections
CREATE TABLE "record_corrections_new" (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill','income_record')),
    record_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    previous TEXT,
    resolved_issues_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "record_corrections_new"("id","record_type","record_id","field","value","previous","resolved_issues_json","created_at") SELECT "id","record_type","record_id","field","value","previous","resolved_issues_json","created_at" FROM "record_corrections";
DROP TABLE "record_corrections";
ALTER TABLE "record_corrections_new" RENAME TO "record_corrections";
CREATE INDEX record_corrections_record ON record_corrections(record_type, record_id, field, id);

-- record_shares
CREATE TABLE "record_shares_new" (
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill')),
    record_id INTEGER NOT NULL,
    share_minor INTEGER NOT NULL CHECK (typeof(share_minor) = 'integer'),
    total_minor INTEGER NOT NULL CHECK (typeof(total_minor) = 'integer' AND total_minor <> 0),
    people_json TEXT NOT NULL DEFAULT '[]',
    family_record_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id)
) STRICT;
INSERT INTO "record_shares_new"("record_type","record_id","share_minor","total_minor","people_json","family_record_key","created_at") SELECT "record_type","record_id","share_minor","total_minor","people_json","family_record_key","created_at" FROM "record_shares";
DROP TABLE "record_shares";
ALTER TABLE "record_shares_new" RENAME TO "record_shares";

-- recurring_obligations
CREATE TABLE "recurring_obligations_new" (
    id INTEGER PRIMARY KEY,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
    account_id INTEGER REFERENCES accounts(id),
    obligation_type TEXT NOT NULL,
    expected_amount_minor INTEGER NOT NULL CHECK (typeof(expected_amount_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    frequency TEXT NOT NULL CHECK (frequency IN ('weekly','monthly','quarterly','semiannual','annual')),
    next_due_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected','ended')),
    confidence_source TEXT NOT NULL,
    category TEXT,
    last_paid_date TEXT,
    source_receipt_id INTEGER REFERENCES receipts(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, source_document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL, evidence TEXT, kind TEXT NOT NULL DEFAULT 'bill' CHECK (kind IN ('bill','subscription')),
    UNIQUE(merchant_id, account_id, currency, frequency)
) STRICT;
INSERT INTO "recurring_obligations_new"("id","merchant_id","account_id","obligation_type","expected_amount_minor","currency","frequency","next_due_date","status","confidence_source","category","last_paid_date","source_receipt_id","created_at","updated_at","source_document_id","evidence","kind") SELECT "id","merchant_id","account_id","obligation_type","expected_amount_minor","currency","frequency","next_due_date","status","confidence_source","category","last_paid_date","source_receipt_id","created_at","updated_at","source_document_id","evidence","kind" FROM "recurring_obligations";
DROP TABLE "recurring_obligations";
ALTER TABLE "recurring_obligations_new" RENAME TO "recurring_obligations";

-- return_policies
CREATE TABLE "return_policies_new" (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL UNIQUE,
    merchant TEXT NOT NULL,
    days INTEGER CHECK (days IS NULL OR days BETWEEN 0 AND 730),
    note TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL CHECK (source IN ('typical','user')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "return_policies_new"("id","pattern","merchant","days","note","source","created_at","updated_at") SELECT "id","pattern","merchant","days","note","source","created_at","updated_at" FROM "return_policies";
DROP TABLE "return_policies";
ALTER TABLE "return_policies_new" RENAME TO "return_policies";

-- review_events
CREATE TABLE "review_events_new" (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "review_events_new"("id","record_type","record_id","previous_status","new_status","note","created_at") SELECT "id","record_type","record_id","previous_status","new_status","note","created_at" FROM "review_events";
DROP TABLE "review_events";
ALTER TABLE "review_events_new" RENAME TO "review_events";

-- scenarios
CREATE TABLE "scenarios_new" (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    basis TEXT NOT NULL CHECK (basis IN ('profile','family','blank')),
    inputs_json TEXT NOT NULL,
    adopted_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, adopted_month TEXT) STRICT;
INSERT INTO "scenarios_new"("id","name","basis","inputs_json","adopted_at","created_at","updated_at","adopted_month") SELECT "id","name","basis","inputs_json","adopted_at","created_at","updated_at","adopted_month" FROM "scenarios";
DROP TABLE "scenarios";
ALTER TABLE "scenarios_new" RENAME TO "scenarios";

-- statements
CREATE TABLE "statements_new" (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL UNIQUE REFERENCES blobs(hash),
    extraction_run_id TEXT,
    statement_type TEXT NOT NULL CHECK (statement_type IN ('bank','credit_card')),
    period_start TEXT,
    period_end TEXT,
    issue_date TEXT,
    due_date TEXT,
    opening_balance_minor INTEGER CHECK (opening_balance_minor IS NULL OR typeof(opening_balance_minor) = 'integer'),
    closing_balance_minor INTEGER CHECK (closing_balance_minor IS NULL OR typeof(closing_balance_minor) = 'integer'),
    statement_balance_minor INTEGER CHECK (statement_balance_minor IS NULL OR typeof(statement_balance_minor) = 'integer'),
    minimum_payment_minor INTEGER CHECK (minimum_payment_minor IS NULL OR typeof(minimum_payment_minor) = 'integer'),
    summary_json TEXT NOT NULL DEFAULT '{}',
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
, review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic')), reconciliation TEXT NOT NULL DEFAULT 'reconciled' CHECK (reconciliation IN ('awaiting','reconciled'))) STRICT;
INSERT INTO "statements_new"("id","account_id","document_id","blob_hash","extraction_run_id","statement_type","period_start","period_end","issue_date","due_date","opening_balance_minor","closing_balance_minor","statement_balance_minor","minimum_payment_minor","summary_json","currency","review_status","validation_json","created_at","updated_at","review_source","reconciliation") SELECT "id","account_id","document_id","blob_hash","extraction_run_id","statement_type","period_start","period_end","issue_date","due_date","opening_balance_minor","closing_balance_minor","statement_balance_minor","minimum_payment_minor","summary_json","currency","review_status","validation_json","created_at","updated_at","review_source","reconciliation" FROM "statements";
DROP TABLE "statements";
ALTER TABLE "statements_new" RENAME TO "statements";

-- tax_figure_sets
CREATE TABLE "tax_figure_sets_new" (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN ('single','married_joint','head_of_household')),
    source TEXT NOT NULL CHECK (source IN ('lookup','typed')),
    figures_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected')),
    sources_json TEXT NOT NULL DEFAULT '[]',
    run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "tax_figure_sets_new"("id","year","filing_status","source","figures_json","status","sources_json","run_id","created_at","updated_at") SELECT "id","year","filing_status","source","figures_json","status","sources_json","run_id","created_at","updated_at" FROM "tax_figure_sets";
DROP TABLE "tax_figure_sets";
ALTER TABLE "tax_figure_sets_new" RENAME TO "tax_figure_sets";
CREATE UNIQUE INDEX tax_figure_sets_open ON tax_figure_sets(year, filing_status, source) WHERE status<>'rejected';

-- tax_form_boxes
CREATE TABLE "tax_form_boxes_new" (
    id INTEGER PRIMARY KEY,
    form_id INTEGER NOT NULL REFERENCES tax_forms(id) ON DELETE CASCADE,
    form TEXT NOT NULL CHECK (form IN ('1099-INT','1099-DIV','1099-B','1099-R','1099-SA','5498','5498-SA')),
    box TEXT NOT NULL,  -- As printed, lower case: 1, 1a, 2b.
    label TEXT NOT NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    locator_json TEXT NOT NULL DEFAULT '{}'
) STRICT;
INSERT INTO "tax_form_boxes_new"("id","form_id","form","box","label","amount_minor","locator_json") SELECT "id","form_id","form","box","label","amount_minor","locator_json" FROM "tax_form_boxes";
DROP TABLE "tax_form_boxes";
ALTER TABLE "tax_form_boxes_new" RENAME TO "tax_form_boxes";
CREATE INDEX tax_form_boxes_form ON tax_form_boxes(form_id);

-- tax_forms
CREATE TABLE "tax_forms_new" (
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
) STRICT;
INSERT INTO "tax_forms_new"("id","account_id","institution","last_four","tax_year","currency","document_id","blob_hash","extraction_run_id","validation_json","review_status","created_at","updated_at") SELECT "id","account_id","institution","last_four","tax_year","currency","document_id","blob_hash","extraction_run_id","validation_json","review_status","created_at","updated_at" FROM "tax_forms";
DROP TABLE "tax_forms";
ALTER TABLE "tax_forms_new" RENAME TO "tax_forms";

-- tax_lots
CREATE TABLE "tax_lots_new" (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES investment_accounts(id) ON DELETE CASCADE,
    holding_id INTEGER NOT NULL REFERENCES holdings(id) ON DELETE CASCADE,
    acquired_date TEXT NOT NULL,
    quantity TEXT NOT NULL,  -- Exact decimal text, as shares are printed: 12.345.
    cost_minor INTEGER NOT NULL CHECK (typeof(cost_minor) = 'integer' AND cost_minor >= 0),
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "tax_lots_new"("id","account_id","holding_id","acquired_date","quantity","cost_minor","created_at") SELECT "id","account_id","holding_id","acquired_date","quantity","cost_minor","created_at" FROM "tax_lots";
DROP TABLE "tax_lots";
ALTER TABLE "tax_lots_new" RENAME TO "tax_lots";
CREATE INDEX tax_lots_holding ON tax_lots(holding_id, acquired_date);

-- tax_rules
CREATE TABLE "tax_rules_new" (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    line TEXT NOT NULL,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK (kind IN ('business_income','business_expense','itemized','adjustment','credit_spending','tax_payment'))
) STRICT;
INSERT INTO "tax_rules_new"("id","pattern","account_id","kind","line","business_id","created_at","updated_at") SELECT "id","pattern","account_id","kind","line","business_id","created_at","updated_at" FROM "tax_rules";
DROP TABLE "tax_rules";
ALTER TABLE "tax_rules_new" RENAME TO "tax_rules";
CREATE UNIQUE INDEX tax_rules_pattern ON tax_rules(pattern, coalesce(account_id, 0));

-- tax_table_runs
CREATE TABLE "tax_table_runs_new" (
    id TEXT PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "tax_table_runs_new"("id","jurisdiction","year","filing_status","config_json","prompt_version","model_identity","status","result_json","error","created_at","updated_at") SELECT "id","jurisdiction","year","filing_status","config_json","prompt_version","model_identity","status","result_json","error","created_at","updated_at" FROM "tax_table_runs";
DROP TABLE "tax_table_runs";
ALTER TABLE "tax_table_runs_new" RENAME TO "tax_table_runs";

-- tax_tables
CREATE TABLE "tax_tables_new" (
    id INTEGER PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN ('single','married_joint','head_of_household')),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    standard_deduction_minor INTEGER NOT NULL,
    brackets_json TEXT NOT NULL,
    ss_rate_bp INTEGER,
    ss_wage_base_minor INTEGER,
    medicare_rate_bp INTEGER,
    additional_medicare_rate_bp INTEGER,
    additional_medicare_threshold_minor INTEGER,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected')),
    sources_json TEXT NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "tax_tables_new"("id","jurisdiction","year","filing_status","currency","standard_deduction_minor","brackets_json","ss_rate_bp","ss_wage_base_minor","medicare_rate_bp","additional_medicare_rate_bp","additional_medicare_threshold_minor","status","sources_json","run_id","created_at","updated_at") SELECT "id","jurisdiction","year","filing_status","currency","standard_deduction_minor","brackets_json","ss_rate_bp","ss_wage_base_minor","medicare_rate_bp","additional_medicare_rate_bp","additional_medicare_threshold_minor","status","sources_json","run_id","created_at","updated_at" FROM "tax_tables";
DROP TABLE "tax_tables";
ALTER TABLE "tax_tables_new" RENAME TO "tax_tables";
CREATE UNIQUE INDEX tax_tables_open ON tax_tables(jurisdiction, year, filing_status) WHERE status<>'rejected';

-- tax_tags
CREATE TABLE "tax_tags_new" (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER UNIQUE REFERENCES transactions(id) ON DELETE CASCADE,
    receipt_id INTEGER UNIQUE REFERENCES receipts(id) ON DELETE CASCADE,
    receipt_item_id INTEGER UNIQUE REFERENCES receipt_items(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('business_income','business_expense','itemized','adjustment','credit_spending','tax_payment')),
    line TEXT NOT NULL,
    business_id INTEGER REFERENCES businesses(id) ON DELETE SET NULL,
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer' AND amount_minor >= 0),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    tax_date TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('user','rule','suggestion')),
    rule_id INTEGER REFERENCES tax_rules(id) ON DELETE SET NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    reason TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    CHECK ((transaction_id IS NOT NULL) + (receipt_id IS NOT NULL) + (receipt_item_id IS NOT NULL) = 1)
) STRICT;
INSERT INTO "tax_tags_new"("id","transaction_id","receipt_id","receipt_item_id","kind","line","business_id","amount_minor","currency","tax_date","source","rule_id","review_status","reason","note","created_at","updated_at") SELECT "id","transaction_id","receipt_id","receipt_item_id","kind","line","business_id","amount_minor","currency","tax_date","source","rule_id","review_status","reason","note","created_at","updated_at" FROM "tax_tags";
DROP TABLE "tax_tags";
ALTER TABLE "tax_tags_new" RENAME TO "tax_tags";
CREATE INDEX tax_tags_date ON tax_tags(tax_date);

-- tax_units
CREATE TABLE "tax_units_new" (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    members_json TEXT NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN ('single','married_joint','head_of_household')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
INSERT INTO "tax_units_new"("id","name","members_json","filing_status","created_at","updated_at") SELECT "id","name","members_json","filing_status","created_at","updated_at" FROM "tax_units";
DROP TABLE "tax_units";
ALTER TABLE "tax_units_new" RENAME TO "tax_units";

-- tax_years
CREATE TABLE "tax_years_new" (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    unit TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (year, unit)
) STRICT;
INSERT INTO "tax_years_new"("id","year","unit","inputs_json","updated_at") SELECT "id","year","unit","inputs_json","updated_at" FROM "tax_years";
DROP TABLE "tax_years";
ALTER TABLE "tax_years_new" RENAME TO "tax_years";

-- transaction_imports
CREATE TABLE "transaction_imports_new" (
    id TEXT PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    mapping_json TEXT NOT NULL,
    parsed INTEGER NOT NULL,
    inserted INTEGER NOT NULL,
    duplicates INTEGER NOT NULL,
    rejected INTEGER NOT NULL,
    issues_json TEXT NOT NULL,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "transaction_imports_new"("id","document_id","blob_hash","account_id","mapping_json","parsed","inserted","duplicates","rejected","issues_json","created_at") SELECT "id","document_id","blob_hash","account_id","mapping_json","parsed","inserted","duplicates","rejected","issues_json","created_at" FROM "transaction_imports";
DROP TABLE "transaction_imports";
ALTER TABLE "transaction_imports_new" RENAME TO "transaction_imports";
CREATE INDEX transaction_imports_document ON transaction_imports(document_id, created_at);

-- transaction_links
CREATE TABLE "transaction_links_new" (
    id INTEGER PRIMARY KEY,
    link_type TEXT NOT NULL CHECK (link_type IN ('transfer','refund')),
    from_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    to_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    match_score INTEGER NOT NULL,
    match_method TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(link_type, from_transaction_id, to_transaction_id)
) STRICT;
INSERT INTO "transaction_links_new"("id","link_type","from_transaction_id","to_transaction_id","match_score","match_method","review_status","created_at","updated_at") SELECT "id","link_type","from_transaction_id","to_transaction_id","match_score","match_method","review_status","created_at","updated_at" FROM "transaction_links";
DROP TABLE "transaction_links";
ALTER TABLE "transaction_links_new" RENAME TO "transaction_links";

-- transaction_receipt_links
CREATE TABLE "transaction_receipt_links_new" (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    receipt_id INTEGER NOT NULL REFERENCES receipts(id),
    match_score INTEGER NOT NULL,
    match_method TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(transaction_id, receipt_id)
) STRICT;
INSERT INTO "transaction_receipt_links_new"("id","transaction_id","receipt_id","match_score","match_method","review_status","created_at","updated_at") SELECT "id","transaction_id","receipt_id","match_score","match_method","review_status","created_at","updated_at" FROM "transaction_receipt_links";
DROP TABLE "transaction_receipt_links";
ALTER TABLE "transaction_receipt_links_new" RENAME TO "transaction_receipt_links";
CREATE INDEX transaction_receipt_links_receipt ON transaction_receipt_links(receipt_id);

-- transactions
CREATE TABLE "transactions_new" (
    id INTEGER PRIMARY KEY,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    statement_id INTEGER REFERENCES statements(id),
    source_document_id INTEGER REFERENCES occurrences(id),
    posted_date TEXT NOT NULL CHECK (posted_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    transaction_date TEXT,
    description_raw TEXT NOT NULL,
    merchant_id INTEGER REFERENCES merchants(id),
    -- Signed from the household's perspective: negative leaves the account holder.
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    transaction_type TEXT NOT NULL CHECK (transaction_type IN ('purchase','refund','payment','transfer','deposit','fee','interest','withdrawal','other')),
    category TEXT,
    origin TEXT NOT NULL CHECK (origin IN ('import','extraction','manual')),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    source_fingerprint TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic')), category_source TEXT CHECK (category_source IS NULL OR category_source IN ('user','rule')), category_rule_id INTEGER REFERENCES category_rules(id) ON DELETE SET NULL,
    UNIQUE(account_id, source_fingerprint)
) STRICT;
INSERT INTO "transactions_new"("id","account_id","statement_id","source_document_id","posted_date","transaction_date","description_raw","merchant_id","amount_minor","currency","transaction_type","category","origin","review_status","source_fingerprint","created_at","updated_at","review_source","category_source","category_rule_id") SELECT "id","account_id","statement_id","source_document_id","posted_date","transaction_date","description_raw","merchant_id","amount_minor","currency","transaction_type","category","origin","review_status","source_fingerprint","created_at","updated_at","review_source","category_source","category_rule_id" FROM "transactions";
DROP TABLE "transactions";
ALTER TABLE "transactions_new" RENAME TO "transactions";
CREATE INDEX transactions_posted ON transactions(posted_date, account_id);
CREATE INDEX transactions_statement ON transactions(statement_id);

-- trash_cleanup
CREATE TABLE "trash_cleanup_new" (
    relative_path TEXT PRIMARY KEY,
    is_directory INTEGER NOT NULL CHECK (is_directory IN (0,1))
) STRICT;
INSERT INTO "trash_cleanup_new"("relative_path","is_directory") SELECT "relative_path","is_directory" FROM "trash_cleanup";
DROP TABLE "trash_cleanup";
ALTER TABLE "trash_cleanup_new" RENAME TO "trash_cleanup";

-- versions
CREATE TABLE "versions_new" (
    id INTEGER PRIMARY KEY,
    occurrence_id INTEGER NOT NULL REFERENCES occurrences(id),
    hash TEXT NOT NULL REFERENCES blobs(hash),
    captured_at TEXT NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    UNIQUE(occurrence_id, hash)
) STRICT;
INSERT INTO "versions_new"("id","occurrence_id","hash","captured_at","source_mtime_ns") SELECT "id","occurrence_id","hash","captured_at","source_mtime_ns" FROM "versions";
DROP TABLE "versions";
ALTER TABLE "versions_new" RENAME TO "versions";

-- warranties
CREATE TABLE "warranties_new" (
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
) STRICT;
INSERT INTO "warranties_new"("id","lot_id","kind","months","lifetime","starts_on","expires_on","source","source_title","source_url","quote","note","review_status","run_id","created_at","updated_at") SELECT "id","lot_id","kind","months","lifetime","starts_on","expires_on","source","source_title","source_url","quote","note","review_status","run_id","created_at","updated_at" FROM "warranties";
DROP TABLE "warranties";
ALTER TABLE "warranties_new" RENAME TO "warranties";

-- warranty_runs
CREATE TABLE "warranty_runs_new" (
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
) STRICT;
INSERT INTO "warranty_runs_new"("id","lot_id","config_json","prompt_version","model_identity","status","result_json","error","created_at","updated_at") SELECT "id","lot_id","config_json","prompt_version","model_identity","status","result_json","error","created_at","updated_at" FROM "warranty_runs";
DROP TABLE "warranty_runs";
ALTER TABLE "warranty_runs_new" RENAME TO "warranty_runs";

-- web_search_cache
CREATE TABLE "web_search_cache_new" (
    query TEXT PRIMARY KEY,
    results_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL
) STRICT;
INSERT INTO "web_search_cache_new"("query","results_json","fetched_at") SELECT "query","results_json","fetched_at" FROM "web_search_cache";
DROP TABLE "web_search_cache";
ALTER TABLE "web_search_cache_new" RENAME TO "web_search_cache";

PRAGMA user_version=50;
