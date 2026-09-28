-- Rewards, perks and offers printed on a receipt or encoded in its QR codes: points or cash earned or redeemed,
-- balances, member savings, future-visit offers and survey invitations. Each is cited; amount and link are as printed.
CREATE TABLE receipt_rewards (
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
);
PRAGMA user_version=33;
