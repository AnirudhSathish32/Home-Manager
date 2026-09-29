-- Family inbox (docs/sharing.md, "Family inbox"). A document uploaded to a family is routed to one person or shared.
-- The card a receipt was paid with, when printed ("VISA ****1234"): four digits at most, used to suggest whose it is.
ALTER TABLE receipts ADD COLUMN payment_last_four TEXT CHECK (payment_last_four IS NULL OR payment_last_four GLOB '[0-9][0-9][0-9][0-9]');
-- In a person's library: the part of a shared receipt or bill this person carries. No row means all of it.
-- Written only by a family delivery, never rebuilt, so category refreshes divide the share rather than the total.
CREATE TABLE record_shares (
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill')),
    record_id INTEGER NOT NULL,
    share_minor INTEGER NOT NULL CHECK (typeof(share_minor) = 'integer'),
    total_minor INTEGER NOT NULL CHECK (typeof(total_minor) = 'integer' AND total_minor <> 0),
    people_json TEXT NOT NULL DEFAULT '[]',
    family_record_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id)
);
-- In a family's own library: who each recorded document is for, and its delivery to each person.
CREATE TABLE family_assignments (
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','bill','statement','income_record')),
    record_id INTEGER NOT NULL,
    family_record_key TEXT NOT NULL UNIQUE,
    mode TEXT CHECK (mode IS NULL OR mode IN ('member','shared')),
    members_json TEXT NOT NULL DEFAULT '[]',
    suggested_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL CHECK (status IN ('unassigned','suggested','confirmed','delivered')),
    delivered_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (record_type, record_id)
);
PRAGMA user_version=35;
