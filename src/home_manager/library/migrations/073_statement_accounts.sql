-- Statement accounts (specs/statement-accounts FR-01, FR-08): an account Record creates waits for the user's Confirm.
-- origin says who made the account: 'user' (Accounts, the import dialog, PDF import, a hand-made account: confirmed at once),
-- 'record' (Record created it for a statement: it waits until a confirming action reaches it) or 'family' (a family delivery
-- created it: the family already confirmed the record). Whether a 'record' account is confirmed is not stored: finance/ledger.py
-- CONFIRMED derives it from its import records, a statement you reviewed, or a statement reconciled. No stored decision is rewritten.
-- Foreign keys are off while this script runs, so every delete below is explicit and the runner's reference check guards it.
ALTER TABLE accounts ADD COLUMN origin TEXT NOT NULL DEFAULT 'user' CHECK (origin IN ('user','record','family'));

-- sort: what follows decides which existing accounts wait for Confirm and removes the empty ones. It only ever moves an account
-- 'user' -> 'record' -> 'family' or deletes an empty one, so running it again changes nothing (tests/test_statement_accounts.py sc07).

-- An account that holds a statement or extracted rows, or that an extraction run published a statement into, was made by Record.
-- One that was created by hand and never published into keeps 'user' (confirmed).
UPDATE accounts SET origin='record'
 WHERE origin='user' AND (
       EXISTS(SELECT 1 FROM statements s WHERE s.account_id=accounts.id)
    OR EXISTS(SELECT 1 FROM transactions t WHERE t.account_id=accounts.id AND t.origin='extraction')
    OR EXISTS(SELECT 1 FROM extraction_runs r WHERE json_valid(r.publication_json)
              AND json_extract(r.publication_json,'$.record_type')='statement'
              AND json_extract(r.publication_json,'$.account_id')=accounts.id));

-- A statement a family delivery published: the family confirmed it, so its account is confirmed.
UPDATE accounts SET origin='family'
 WHERE origin='record' AND EXISTS(
       SELECT 1 FROM statements s JOIN financial_evidence_links e ON e.record_type='statement' AND e.record_id=s.id
        WHERE s.account_id=accounts.id AND e.source_key LIKE 'family:%');

-- A Record account with no statement, no transaction and no import record is what a re-read left behind: remove it.
DROP TABLE IF EXISTS temp.removed_accounts;
CREATE TEMP TABLE removed_accounts AS
SELECT a.id FROM accounts a
 WHERE a.origin='record'
   AND NOT EXISTS(SELECT 1 FROM statements s WHERE s.account_id=a.id)
   AND NOT EXISTS(SELECT 1 FROM transactions t WHERE t.account_id=a.id)
   AND NOT EXISTS(SELECT 1 FROM transaction_imports i WHERE i.account_id=a.id);
DELETE FROM category_rules WHERE account_id IN (SELECT id FROM removed_accounts);
DELETE FROM tax_rules WHERE account_id IN (SELECT id FROM removed_accounts);
UPDATE recurring_obligations SET account_id=NULL WHERE account_id IN (SELECT id FROM removed_accounts);
UPDATE investment_accounts SET ledger_account_id=NULL WHERE ledger_account_id IN (SELECT id FROM removed_accounts);
DELETE FROM accounts WHERE id IN (SELECT id FROM removed_accounts);
DROP TABLE temp.removed_accounts;
PRAGMA user_version=73;
