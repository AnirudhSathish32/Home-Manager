-- Receipt categories: transport joined travel; utilities are part of housing.
UPDATE receipts SET category='travel' WHERE category='transport';
UPDATE record_corrections SET value='travel' WHERE record_type='receipt' AND field='category' AND value='transport';
-- How often the model read a receipt's payment recurs (a bill paid on a schedule), or NULL for a one-off purchase.
ALTER TABLE receipts ADD COLUMN recurrence TEXT CHECK (recurrence IS NULL OR recurrence IN ('weekly','monthly','quarterly','semiannual','annual'));
-- Recurring bills: one payment can propose one. Adds a six-monthly frequency, the spending category the bill
-- counts under, its latest matched payment, and the receipt it was proposed from. SQLite cannot widen a CHECK in place.
CREATE TABLE recurring_obligations_new (
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
    updated_at TEXT NOT NULL,
    UNIQUE(merchant_id, account_id, currency, frequency)
);
INSERT INTO recurring_obligations_new(id,merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,next_due_date,status,
                                      confidence_source,created_at,updated_at)
    SELECT id,merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,next_due_date,status,confidence_source,created_at,updated_at
    FROM recurring_obligations;
DROP TABLE recurring_obligations;
ALTER TABLE recurring_obligations_new RENAME TO recurring_obligations;
PRAGMA user_version=28;
