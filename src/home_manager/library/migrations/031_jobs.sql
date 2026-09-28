-- Income becomes Jobs: one folder per employer, each with Paystubs and Documents (docs/jobs-and-paystubs.md).
-- On startup the managed library moves files out of Library/Income into Jobs.
UPDATE folder_aliases SET folder='Jobs' WHERE folder='Income';
INSERT OR IGNORE INTO folder_aliases VALUES ('Jobs','Jobs');
INSERT INTO library_events(document_id,blob_hash,action,detail,created_at)
 SELECT document_id,blob_hash,'folder_migration','Income -> Jobs',strftime('%Y-%m-%dT%H:%M:%fZ','now') FROM document_folders WHERE folder='Income';
UPDATE document_folders SET folder='Jobs' WHERE folder='Income';
-- Employers: named from the documents, each with its own folder under Jobs. Never deleted with a document.
CREATE TABLE employers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    folder_name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    created_at TEXT NOT NULL
);
-- Which employer folder and section a document in Jobs is filed under.
CREATE TABLE job_filings (
    document_id INTEGER NOT NULL REFERENCES occurrences(id),
    blob_hash TEXT NOT NULL,
    employer_id INTEGER NOT NULL REFERENCES employers(id),
    section TEXT NOT NULL CHECK (section IN ('Paystubs','Documents')),
    label TEXT,  -- In the file name (letters only): Offer_Letter.
    title TEXT,  -- Shown in the library, as printed: Offer Letter, W-2.
    PRIMARY KEY (document_id, blob_hash)
);
-- A pay stub's printed lines: earnings, deductions, taxes and employer-paid amounts, this period and year to date.
CREATE TABLE income_lines (
    id INTEGER PRIMARY KEY,
    income_record_id INTEGER NOT NULL REFERENCES income_records(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    description TEXT NOT NULL,
    line_group TEXT NOT NULL CHECK (line_group IN ('earnings','pre_tax','tax','post_tax','employer_paid')),
    category TEXT NOT NULL,
    current_minor INTEGER CHECK (current_minor IS NULL OR typeof(current_minor) = 'integer'),
    ytd_minor INTEGER CHECK (ytd_minor IS NULL OR typeof(ytd_minor) = 'integer'),
    locator_json TEXT NOT NULL,
    UNIQUE (income_record_id, position)
);
ALTER TABLE income_records ADD COLUMN gross_pay_ytd_minor INTEGER;
ALTER TABLE income_records ADD COLUMN net_pay_ytd_minor INTEGER;
ALTER TABLE income_records ADD COLUMN work_state TEXT;
ALTER TABLE income_records ADD COLUMN pay_frequency INTEGER CHECK (pay_frequency IS NULL OR pay_frequency IN (12, 24, 26, 52));
-- Income tax tables, looked up by the local model for each new tax year and confirmed by the user before use.
-- brackets_json: [{"from_minor": 0, "rate_bp": 1000}, ...] over taxable income after the standard deduction.
CREATE TABLE tax_tables (
    id INTEGER PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN ('single','married_joint','head_of_household')),
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    standard_deduction_minor INTEGER NOT NULL,
    brackets_json TEXT NOT NULL,
    ss_rate_bp INTEGER,
    ss_wage_base_minor INTEGER,
    medicare_rate_bp INTEGER,
    additional_medicare_rate_bp INTEGER,
    additional_medicare_threshold_minor INTEGER,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected')),
    sources_json TEXT NOT NULL,
    run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX tax_tables_open ON tax_tables(jurisdiction, year, filing_status) WHERE status<>'rejected';
CREATE TABLE tax_table_runs (
    id TEXT PRIMARY KEY,
    jurisdiction TEXT NOT NULL,
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL,
    config_json TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    model_identity TEXT,
    status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','cancelled','interrupted')),
    result_json TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=31;
