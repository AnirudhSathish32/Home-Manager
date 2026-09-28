-- Receipts count as spending on their own until a card or bank line replaces them.
-- Each receipt has a category from a fixed list, suggested by the model; the user's choice is a correction.
ALTER TABLE receipts ADD COLUMN category TEXT;
-- A newly recorded statement's lines wait, uncounted and unmatched, until the user reconciles receipts against them.
-- Statements recorded before this change were already reconciled automatically.
ALTER TABLE statements ADD COLUMN reconciliation TEXT NOT NULL DEFAULT 'reconciled' CHECK (reconciliation IN ('awaiting','reconciled'));
PRAGMA user_version=26;
