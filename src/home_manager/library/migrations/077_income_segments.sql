-- Several pay stubs in one file (docs/documents.md, "Several pay stubs in one file"). A file's pay stubs are numbered by
-- segment, 0 for the first, as receipts are (054); a file with one pay stub has only segment 0, so every existing pay
-- stub keeps its id, its values and its meaning. income_records was unique by file; it is now unique by file and segment.
-- income_records has no index or trigger besides its unique constraint (read from sqlite_master when this was written);
-- income_lines and transaction_income_links point at its ids, which do not change.

CREATE TABLE "income_records_new" (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    segment INTEGER NOT NULL DEFAULT 0 CHECK (segment BETWEEN 0 AND 199),
    extraction_run_id TEXT,
    payer_merchant_id INTEGER REFERENCES merchants(id),
    pay_date TEXT,
    period_start TEXT,
    period_end TEXT,
    gross_pay_minor INTEGER CHECK (gross_pay_minor IS NULL OR typeof(gross_pay_minor) = 'integer'),
    net_pay_minor INTEGER CHECK (net_pay_minor IS NULL OR typeof(net_pay_minor) = 'integer'),
    taxes_minor INTEGER CHECK (taxes_minor IS NULL OR typeof(taxes_minor) = 'integer'),
    deductions_minor INTEGER CHECK (deductions_minor IS NULL OR typeof(deductions_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic')),
    gross_pay_ytd_minor INTEGER,
    net_pay_ytd_minor INTEGER,
    work_state TEXT,
    pay_frequency INTEGER CHECK (pay_frequency IS NULL OR pay_frequency IN (12, 24, 26, 52)),
    details_json TEXT,
    UNIQUE (blob_hash, segment)
) STRICT;
INSERT INTO "income_records_new"("id","document_id","blob_hash","segment","extraction_run_id","payer_merchant_id","pay_date","period_start","period_end","gross_pay_minor","net_pay_minor","taxes_minor","deductions_minor","currency","review_status","validation_json","created_at","updated_at","review_source","gross_pay_ytd_minor","net_pay_ytd_minor","work_state","pay_frequency","details_json")
    SELECT "id","document_id","blob_hash",0,"extraction_run_id","payer_merchant_id","pay_date","period_start","period_end","gross_pay_minor","net_pay_minor","taxes_minor","deductions_minor","currency","review_status","validation_json","created_at","updated_at","review_source","gross_pay_ytd_minor","net_pay_ytd_minor","work_state","pay_frequency","details_json" FROM "income_records";
DROP TABLE "income_records";
ALTER TABLE "income_records_new" RENAME TO "income_records";

PRAGMA user_version=77;
