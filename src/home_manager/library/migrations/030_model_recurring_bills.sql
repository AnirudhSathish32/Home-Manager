-- Recurring bills the local model proposes: from a contract, lease or policy's payment terms (the document and
-- the quoted terms are kept for Review), and from statement payees it reads as ongoing services.
ALTER TABLE recurring_obligations ADD COLUMN source_document_id INTEGER REFERENCES occurrences(id) ON DELETE SET NULL;
ALTER TABLE recurring_obligations ADD COLUMN evidence TEXT;
-- One answer per statement payee, so a payee is asked once. A NULL recurrence means a one-off payee.
CREATE TABLE payee_recurrence (
    payee_key TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    recurrence TEXT CHECK (recurrence IS NULL OR recurrence IN ('weekly','monthly','quarterly','semiannual','annual')),
    category TEXT,
    model TEXT,
    asked_at TEXT NOT NULL,
    PRIMARY KEY (payee_key, currency)
);
PRAGMA user_version=30;
