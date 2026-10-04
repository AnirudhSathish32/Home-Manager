-- Several receipts in one file (docs/documents.md, "Several receipts in one file"). A file's receipts are numbered by
-- segment, 0 for the first; a file with one receipt has only segment 0, so every existing receipt keeps its meaning.
-- document_segments records where each receipt sits in the file's text (its first and last line), and whether the user
-- confirmed the split. Segments written by the user (source user) win over the model's on later extractions.

CREATE TABLE "receipts_new" (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    segment INTEGER NOT NULL DEFAULT 0 CHECK (segment BETWEEN 0 AND 199),
    extraction_run_id TEXT,
    merchant_id INTEGER REFERENCES merchants(id),
    purchase_date TEXT,
    subtotal_minor INTEGER CHECK (subtotal_minor IS NULL OR typeof(subtotal_minor) = 'integer'),
    tax_minor INTEGER CHECK (tax_minor IS NULL OR typeof(tax_minor) = 'integer'),
    tip_minor INTEGER CHECK (tip_minor IS NULL OR typeof(tip_minor) = 'integer'),
    total_minor INTEGER CHECK (total_minor IS NULL OR typeof(total_minor) = 'integer'),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    review_status TEXT NOT NULL CHECK (review_status IN ('proposed','needs_review','verified','rejected')),
    validation_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    description TEXT,
    review_source TEXT CHECK (review_source IS NULL OR review_source IN ('user','automatic')),
    location TEXT,
    return_days_printed INTEGER CHECK (return_days_printed IS NULL OR return_days_printed BETWEEN 0 AND 730),
    return_policy_quote TEXT,
    category TEXT,
    recurrence TEXT CHECK (recurrence IS NULL OR recurrence IN ('weekly','monthly','quarterly','semiannual','annual')),
    payment_last_four TEXT CHECK (payment_last_four IS NULL OR payment_last_four GLOB '[0-9][0-9][0-9][0-9]'),
    UNIQUE (blob_hash, segment)
) STRICT;
INSERT INTO "receipts_new"("id","document_id","blob_hash","segment","extraction_run_id","merchant_id","purchase_date","subtotal_minor","tax_minor","tip_minor","total_minor","currency","review_status","validation_json","created_at","updated_at","description","review_source","location","return_days_printed","return_policy_quote","category","recurrence","payment_last_four")
    SELECT "id","document_id","blob_hash",0,"extraction_run_id","merchant_id","purchase_date","subtotal_minor","tax_minor","tip_minor","total_minor","currency","review_status","validation_json","created_at","updated_at","description","review_source","location","return_days_printed","return_policy_quote","category","recurrence","payment_last_four" FROM "receipts";
DROP TABLE "receipts";
ALTER TABLE "receipts_new" RENAME TO "receipts";

CREATE TABLE document_segments (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES occurrences(id) ON DELETE CASCADE,
    blob_hash TEXT NOT NULL REFERENCES blobs(hash),
    ordinal INTEGER NOT NULL CHECK (ordinal BETWEEN 0 AND 199),
    first_line_id TEXT NOT NULL,
    last_line_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed','confirmed')),
    source TEXT NOT NULL CHECK (source IN ('model','user')),
    extraction_run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (document_id, blob_hash, ordinal)
) STRICT;

PRAGMA user_version=54;
