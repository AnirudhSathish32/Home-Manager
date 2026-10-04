-- Tax calculations (docs/tax-engines.md): each distinct return a tax engine worked out, so a past result can be traced
-- and reproduced (docs/tax_intelligence_architecture.md §34, §37). One row per year, filing unit ('me' or 'unit-<id>'),
-- engine, engine version and profile: the same profile worked out again by the same engine adds nothing, and a newer
-- engine adds a row beside the old one rather than rewriting it. profile_json is the tax_return.ReturnInput the engine
-- read; result_json is its answer without the engine's own output; raw_json is what's needed to re-run and check it (for
-- OpenTax: the facts, its assumptions, the corpus Merkle root and the artifact hash).

CREATE TABLE tax_calculations (
    id INTEGER PRIMARY KEY,
    year INTEGER NOT NULL,
    unit TEXT NOT NULL,
    engine TEXT NOT NULL,
    engine_version TEXT NOT NULL,
    pin_sha256 TEXT,
    profile_hash TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    raw_json TEXT,
    result_minor INTEGER,
    created_at TEXT NOT NULL,
    UNIQUE (year, unit, engine, engine_version, profile_hash)
) STRICT;
CREATE INDEX tax_calculations_year ON tax_calculations(year, unit, created_at);

PRAGMA user_version=58;
