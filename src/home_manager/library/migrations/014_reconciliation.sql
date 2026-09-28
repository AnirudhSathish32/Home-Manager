-- Deterministic reconciliation. Scores are integer points from explicit rules, not
-- calibrated probabilities. Ambiguity is recorded as an issue, never resolved by guessing;
-- a link the user rejected is never proposed again.
CREATE TABLE transaction_receipt_links (
    id INTEGER PRIMARY KEY,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    receipt_id INTEGER NOT NULL REFERENCES receipts(id),
    match_score INTEGER NOT NULL,
    match_method TEXT NOT NULL,
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','verified','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(transaction_id, receipt_id)
);
CREATE TABLE transaction_links (
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
);
CREATE TABLE reconciliation_issues (
    id INTEGER PRIMARY KEY,
    issue_type TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    detail_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(issue_type, record_type, record_id)
);
PRAGMA user_version=14;
