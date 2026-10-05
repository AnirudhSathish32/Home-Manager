-- Provenance for every figure (docs/ui.md "Redesign: calculation observability"; docs/open-work.md "UI redesign" 3).
-- Who changed what, from what, and why; when child rows were written; which rule set a figure used; and the inputs a
-- figure was last shown with, so a change since can be flagged.
--
-- actor: the person chosen in the who's-here picker for the session (the X-HM-Actor header, checked against the
-- profile's people), or NULL when nobody was chosen or the change was automatic.

-- Corrections: any record a person can correct, with an optional reason and the person.
CREATE TABLE "record_corrections_new" (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill','income_record','transaction','statement','investment_valuation',
                                                     'tax_form_box','holding','budget')),
    record_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    previous TEXT,
    resolved_issues_json TEXT NOT NULL DEFAULT '[]',
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 500),
    actor TEXT,
    created_at TEXT NOT NULL
) STRICT;
INSERT INTO "record_corrections_new"("id","record_type","record_id","field","value","previous","resolved_issues_json","created_at")
    SELECT "id","record_type","record_id","field","value","previous","resolved_issues_json","created_at" FROM "record_corrections";
DROP TABLE "record_corrections";
ALTER TABLE "record_corrections_new" RENAME TO "record_corrections";
CREATE INDEX record_corrections_record ON record_corrections(record_type, record_id, field, id);

ALTER TABLE review_events ADD COLUMN actor TEXT;
ALTER TABLE family_assignments ADD COLUMN actor TEXT;
ALTER TABLE transactions ADD COLUMN actor TEXT;  -- Who entered a manual transaction.
-- A manual transaction counts at once; the imported or statement line for the same payment replaces it later
-- (finance/reconcile.py replace_manual), and this names that line.
ALTER TABLE transactions ADD COLUMN replaced_by INTEGER REFERENCES transactions(id);

-- A budget's history: every amount it was set to, removal included (amount_minor NULL).
CREATE TABLE budget_changes (
    id INTEGER PRIMARY KEY,
    budget_id INTEGER,
    category TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    previous_minor INTEGER CHECK (previous_minor IS NULL OR typeof(previous_minor) = 'integer'),
    amount_minor INTEGER CHECK (amount_minor IS NULL OR typeof(amount_minor) = 'integer'),
    actor TEXT,
    created_at TEXT NOT NULL
) STRICT;
CREATE INDEX budget_changes_budget ON budget_changes(category, currency, id);

-- Typed tax values: the value gathered from records at the time, beside what was typed over it (tax_year.merge keeps
-- no original). key is a return field ("interest") or a job's ("job:employer-3:wages"); the values are JSON.
CREATE TABLE tax_input_changes (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL CHECK (year BETWEEN 1990 AND 2100),
    unit TEXT NOT NULL DEFAULT 'me',
    key TEXT NOT NULL,
    gathered_json TEXT,
    previous_json TEXT,
    typed_json TEXT,
    reason TEXT CHECK (reason IS NULL OR length(reason) <= 500),
    actor TEXT,
    created_at TEXT NOT NULL
) STRICT;
CREATE INDEX tax_input_changes_key ON tax_input_changes(year, unit, key, id);

-- When child rows were written: their record's time for the rows already here.
ALTER TABLE receipt_items ADD COLUMN created_at TEXT;
ALTER TABLE receipt_items ADD COLUMN updated_at TEXT;
UPDATE receipt_items SET created_at=(SELECT created_at FROM receipts WHERE id=receipt_id), updated_at=(SELECT updated_at FROM receipts WHERE id=receipt_id);
ALTER TABLE receipt_rewards ADD COLUMN created_at TEXT;
ALTER TABLE receipt_rewards ADD COLUMN updated_at TEXT;
UPDATE receipt_rewards SET created_at=(SELECT created_at FROM receipts WHERE id=receipt_id), updated_at=(SELECT updated_at FROM receipts WHERE id=receipt_id);
ALTER TABLE income_lines ADD COLUMN created_at TEXT;
ALTER TABLE income_lines ADD COLUMN updated_at TEXT;
UPDATE income_lines SET created_at=(SELECT created_at FROM income_records WHERE id=income_record_id), updated_at=(SELECT updated_at FROM income_records WHERE id=income_record_id);
ALTER TABLE tax_form_boxes ADD COLUMN created_at TEXT;
ALTER TABLE tax_form_boxes ADD COLUMN updated_at TEXT;
UPDATE tax_form_boxes SET created_at=(SELECT created_at FROM tax_forms WHERE id=form_id), updated_at=(SELECT updated_at FROM tax_forms WHERE id=form_id);

-- Rule sets (finance/rules.py RULES, written here when a library opens): each constant set a figure can rest on, with its
-- version, tax year, source, the day it was checked against that source (NULL: no check recorded), when a CPA reviewed
-- it (NULL: not reviewed), and a digest of its values, so a value changed without a new version is caught.
CREATE TABLE rule_sources (
    key TEXT NOT NULL,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    tax_year INTEGER,
    source TEXT NOT NULL,
    checked_on TEXT,
    cpa_reviewed_on TEXT,
    values_sha256 TEXT NOT NULL,
    PRIMARY KEY (key, version)
) STRICT;
-- The lookup procedure a tax table came from (household/tax_tables.py TAX_TABLE_VERSION).
ALTER TABLE tax_tables ADD COLUMN rule_version TEXT;
UPDATE tax_tables SET rule_version='tax-table-lookup-v1';

-- A figure as last shown or traced: the hash of its inputs and its result, so a later look can say it changed.
CREATE TABLE figure_snapshots (
    ref TEXT PRIMARY KEY,
    inputs_hash TEXT NOT NULL,
    result_minor INTEGER CHECK (result_minor IS NULL OR typeof(result_minor) = 'integer'),
    currency TEXT,
    computed_at TEXT NOT NULL
) STRICT;

PRAGMA user_version=61;
