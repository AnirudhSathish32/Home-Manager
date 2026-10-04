-- Tax Zen evaluations (docs/taxes.md "Tax Zen", "Design"): what Tax Zen said for a
-- return and why, kept so advice stays steady and a change can be explained. A row is added only when the status, the
-- W-4 answer or the return's inputs changed since the last one for that year and filing unit ('me' or 'unit-<id>');
-- rows are never rewritten, except seen_at, set when the Taxes page shows the return.
-- calculation_id: the return it was worked from (tax_calculations); policy_json: the aim; low/high: the likely range
-- from the projected values; w4_json: the W-4 answer (job, field, amount, per-paycheck withholding); assumptions_json:
-- the figures it rested on (each field's value and kind, each job's pay per paycheck and paychecks left, the sources),
-- compared next time to say what changed; trigger: that change, in words.

CREATE TABLE tax_zen_evaluations (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    unit TEXT NOT NULL,
    calculation_id INTEGER REFERENCES tax_calculations(id),
    policy_json TEXT NOT NULL,
    status TEXT NOT NULL,
    result_minor INTEGER,
    low_minor INTEGER,
    high_minor INTEGER,
    confidence TEXT,
    w4_json TEXT,
    assumptions_json TEXT NOT NULL,
    inputs_hash TEXT NOT NULL,
    trigger TEXT,
    created_at TEXT NOT NULL,
    seen_at TEXT
) STRICT;
CREATE INDEX tax_zen_evaluations_year ON tax_zen_evaluations(year, unit, id);

PRAGMA user_version=60;
