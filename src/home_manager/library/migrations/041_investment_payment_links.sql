-- A bank or card line matched to money paid into an investment can be undone (docs/planning.md "Investments").
-- What the line was before the match made it a transfer, restored on undo; and who made the match.
ALTER TABLE investment_events ADD COLUMN transaction_previous_type TEXT;
ALTER TABLE investment_events ADD COLUMN transaction_link TEXT CHECK (transaction_link IS NULL OR transaction_link IN ('auto','user'));
-- Pairs the user said are not a match: never proposed again.
CREATE TABLE investment_payment_rejections (
    event_id INTEGER NOT NULL REFERENCES investment_events(id) ON DELETE CASCADE,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (event_id, transaction_id)
);
PRAGMA user_version=41;
