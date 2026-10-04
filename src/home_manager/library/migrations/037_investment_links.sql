-- Investments phase 2 (docs/planning.md "Investments"): a ledger savings account stands for at most one investment account,
-- so its balance is counted once, as an investment.
CREATE UNIQUE INDEX investment_accounts_ledger ON investment_accounts(ledger_account_id) WHERE ledger_account_id IS NOT NULL;
CREATE INDEX investment_events_source ON investment_events(account_id, blob_hash);
PRAGMA user_version=37;
