-- Family corrections (docs/family.md "Family corrections"): a change made in the family ledger to a member's record
-- travels to the member as a delivery and applies there as a record_corrections row with the family as its actor.
--
-- In the family's own library a row is 'sent': pending until the member's next copy says what happened to it. In a
-- member's library a row is 'received': applied, a conflict (the member changed the field since, so Review asks), or
-- rejected by the member. key is the delivery's, so each correction applies once. correction_id is the member's
-- record_corrections row it made.
CREATE TABLE family_corrections (
    key TEXT PRIMARY KEY CHECK (length(key) = 32),
    direction TEXT NOT NULL CHECK (direction IN ('sent','received')),
    member_id TEXT NOT NULL,
    record_type TEXT NOT NULL CHECK (record_type IN ('transaction','receipt','bill','income_record','statement')),
    record_id INTEGER NOT NULL,
    field TEXT NOT NULL,
    value TEXT,
    previous TEXT,
    actor TEXT,
    correction_id INTEGER,
    status TEXT NOT NULL CHECK (status IN ('pending','applied','conflict','rejected')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;
CREATE INDEX family_corrections_record ON family_corrections(direction, member_id, record_type, record_id, field);

-- A conflicting family correction is a Review question (issue_type 'family_correction'), answered "Keep mine" or
-- "Use family's".
CREATE TABLE "reconciliation_issues_new" (
    id INTEGER PRIMARY KEY,
    issue_type TEXT NOT NULL,
    record_type TEXT NOT NULL,
    record_id INTEGER NOT NULL,
    detail_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open','resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL, resolution TEXT
    CHECK (resolution IS NULL OR resolution IN ('linked','left_unmatched','kept_mine','took_family')),
    UNIQUE(issue_type, record_type, record_id)
) STRICT;
INSERT INTO "reconciliation_issues_new"("id","issue_type","record_type","record_id","detail_json","status","created_at","updated_at","resolution")
    SELECT "id","issue_type","record_type","record_id","detail_json","status","created_at","updated_at","resolution" FROM "reconciliation_issues";
DROP TABLE "reconciliation_issues";
ALTER TABLE "reconciliation_issues_new" RENAME TO "reconciliation_issues";
CREATE INDEX reconciliation_issues_record ON reconciliation_issues(record_type, record_id);

PRAGMA user_version=62;
