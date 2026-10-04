-- Donation checks (docs/evals.md): a person marks each critical field of an extracted record, and
-- for a statement or pay stub its rows, as correct or fixed against the original, so the document can be donated with
-- answers someone actually checked. A check is an evaluation label only: it never changes the ledger, review status or
-- filing. proposal_json is the model's normalized result before any check; answers_json holds the checked answers
-- (library/donation.py). One check per extracted record of one content version.

CREATE TABLE donation_checks (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','statement','income_record')),
    record_id INTEGER NOT NULL,
    document_type TEXT NOT NULL CHECK (document_type IN ('receipt','bank_statement','credit_card_statement','paystub')),
    extraction_run_id TEXT NOT NULL,
    extraction_version TEXT NOT NULL,
    proposal_json TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('phone_photo','scan','native_pdf','image_pdf')),
    -- Boxes to black out before export, as fractions of each page: [{"page": 1, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.05}].
    redactions_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL CHECK (status IN ('draft','checked')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (record_type, record_id, blob_hash)
) STRICT;
CREATE INDEX donation_checks_document ON donation_checks(document_id);

PRAGMA user_version=57;
