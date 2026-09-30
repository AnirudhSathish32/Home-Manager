-- Tax tags (docs/taxes.md): what a ledger item is for taxes. A business's income or expense (a Schedule C line; contract
-- work is a business too), an itemized deduction, an above-the-line adjustment, spending that earns a credit, or a tax
-- payment made ahead (estimated tax). Tags feed the year's tax estimate.
CREATE TABLE businesses (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    archived_at TEXT
);
-- The user's rules, matched like category rules: every word of the pattern in a bank line's description (and merchant).
CREATE TABLE tax_rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    line TEXT NOT NULL,
    business_id INTEGER REFERENCES businesses(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX tax_rules_pattern ON tax_rules(pattern, coalesce(account_id, 0));
-- One tag per item: a bank line, a receipt, or one line of a receipt. A rejected tag stays, so the same payee isn't
-- suggested again.
CREATE TABLE tax_tags (
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
);
CREATE INDEX tax_tags_date ON tax_tags(tax_date);
PRAGMA user_version=45;
