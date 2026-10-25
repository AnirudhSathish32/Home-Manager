-- PDF import index (specs/account-import-pdf): per reading, how many transactions tables it has and which last fours and currency it prints.
-- Derived data, rebuilt from the saved reading by finance/pdf_import.py; it holds no money and no row data. Nothing is backfilled here:
-- the app indexes older readings in the background at the next start.
CREATE TABLE pdf_import_index (
    parse_run_id TEXT PRIMARY KEY REFERENCES parse_runs(id) ON DELETE CASCADE,
    analyzer_version INTEGER NOT NULL,
    transactions_tables INTEGER NOT NULL,
    last_fours_json TEXT NOT NULL,
    document_currency TEXT,
    error TEXT,
    created_at TEXT NOT NULL
) STRICT;
PRAGMA user_version=71;
