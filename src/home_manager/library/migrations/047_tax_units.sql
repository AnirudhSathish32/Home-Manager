-- The family's tax returns (docs/taxes.md): who files together. A return is one person filing single or head of
-- household, or a married couple filing jointly; the family is Tax Zen when every return is. Kept in the family's own
-- library; each return's typed values are in tax_years under unit 'unit-<id>'.
CREATE TABLE tax_units (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    members_json TEXT NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN ('single','married_joint','head_of_household')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
PRAGMA user_version=47;
