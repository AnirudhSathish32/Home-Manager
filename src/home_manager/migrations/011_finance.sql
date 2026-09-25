-- Canonical financial layer. Model output remains staging; these rows carry review
-- state, origin and evidence links. Money is INTEGER minor units plus an ISO currency;
-- typeof() checks reject REAL values so binary floating point can never be stored.
CREATE TABLE merchants (
    id INTEGER PRIMARY KEY,
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    institution TEXT NOT NULL,
    account_type TEXT NOT NULL CHECK (account_type IN ('checking','savings','credit_card','brokerage','loan','other')),
    display_name TEXT NOT NULL,
    account_last_four TEXT CHECK (account_last_four IS NULL OR account_last_four GLOB '[0-9][0-9][0-9][0-9]'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX accounts_identity ON accounts(institution, account_type, coalesce(account_last_four, ''));
CREATE TABLE statements (
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
);
CREATE TABLE transactions (
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
    updated_at TEXT NOT NULL,
    UNIQUE(account_id, source_fingerprint)
);
CREATE INDEX transactions_posted ON transactions(posted_date, account_id);
CREATE TABLE receipts (
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
);
CREATE TABLE receipt_items (
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
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    UNIQUE(receipt_id, position)
);
CREATE TABLE bills (
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
    bill_type TEXT NOT NULL DEFAULT 'other',
    payment_status TEXT NOT NULL DEFAULT 'unknown' CHECK (payment_status IN ('unknown','unpaid','paid')),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE income_records (
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
);
CREATE TABLE recurring_obligations (
    id INTEGER PRIMARY KEY,
    merchant_id INTEGER NOT NULL REFERENCES merchants(id),
    account_id INTEGER REFERENCES accounts(id),
    obligation_type TEXT NOT NULL,
    expected_amount_minor INTEGER NOT NULL CHECK (typeof(expected_amount_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    frequency TEXT NOT NULL CHECK (frequency IN ('weekly','monthly','quarterly','annual')),
    next_due_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected','ended')),
    confidence_source TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(merchant_id, account_id, currency, frequency)
);
-- Every canonical record points back to a document version and the run that produced it.
CREATE TABLE financial_evidence_links (
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
);
CREATE INDEX evidence_record ON financial_evidence_links(record_type, record_id);
CREATE TABLE review_events (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    previous_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
PRAGMA user_version=11;
