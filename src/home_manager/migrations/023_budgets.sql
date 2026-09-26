-- Category rules and monthly budgets (docs/money-review-inventory.md), and free-text check-in runs.

-- A user-written rule: transactions whose merchant key contains every word of the pattern get the category.
CREATE TABLE category_rules (
    id INTEGER PRIMARY KEY,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    account_id INTEGER REFERENCES accounts(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX category_rules_identity ON category_rules(pattern, coalesce(account_id, 0));

-- Who set a transaction's category: the user by hand, or one of the user's rules.
-- A hand-set category is never changed by a rule.
ALTER TABLE transactions ADD COLUMN category_source TEXT CHECK (category_source IS NULL OR category_source IN ('user','rule'));
ALTER TABLE transactions ADD COLUMN category_rule_id INTEGER REFERENCES category_rules(id) ON DELETE SET NULL;
UPDATE transactions SET category_source='user' WHERE category IS NOT NULL;

-- One monthly amount per category and currency.
CREATE TABLE budgets (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    amount_minor INTEGER NOT NULL CHECK (typeof(amount_minor) = 'integer' AND amount_minor > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(category, currency)
);

-- A free-text check-in answer read by the local model into proposed lot updates, applied only on confirmation.
CREATE TABLE checkin_runs (
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
);
PRAGMA user_version=23;
