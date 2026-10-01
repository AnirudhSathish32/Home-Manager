-- Generated reports kept under <store>/Reports (docs/taxes.md, "CPA pack"): the year-end CPA pack workbook.
-- request_key is the tax year plus a fingerprint of the pack's data, so building again from unchanged data returns the
-- same file, and changed data makes a new one beside it. sha256 is checked before a file is served.

CREATE TABLE generated_reports (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('cpa_pack')),
    request_key TEXT NOT NULL UNIQUE,
    relative_path TEXT NOT NULL UNIQUE,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    tax_year INTEGER NOT NULL CHECK (tax_year BETWEEN 1990 AND 2100),
    created_at TEXT NOT NULL,
    manifest_json TEXT NOT NULL
) STRICT;
CREATE INDEX generated_reports_year ON generated_reports(kind, tax_year);

PRAGMA user_version=52;
