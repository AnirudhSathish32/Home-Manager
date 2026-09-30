-- A tax year's federal figures beyond the brackets (docs/taxes.md): capital-gains thresholds, credit amounts, caps and
-- limits. A looked-up set is quoted from official pages and waits for confirmation in Review; a typed set is the
-- user's own and counts at once, each typed figure replacing the looked-up one. Lookups reuse tax_table_runs.
CREATE TABLE tax_figure_sets (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN ('single','married_joint','head_of_household')),
    source TEXT NOT NULL CHECK (source IN ('lookup','typed')),
    figures_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('proposed','verified','rejected')),
    sources_json TEXT NOT NULL DEFAULT '[]',
    run_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX tax_figure_sets_open ON tax_figure_sets(year, filing_status, source) WHERE status<>'rejected';
-- A filing unit's inputs for a year's return estimate: what the user typed over the figures gathered from records.
CREATE TABLE tax_years (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    unit TEXT NOT NULL,
    inputs_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (year, unit)
);
PRAGMA user_version=46;
