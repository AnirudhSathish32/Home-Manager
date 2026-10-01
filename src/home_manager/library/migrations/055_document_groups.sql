-- Several images that are one document, such as a long receipt photographed in parts (docs/document-parsing.md,
-- "Several images as one document"). The app suggests groups (proposed); the user confirms or dismisses them, or
-- combines images directly (confirmed). A confirmed group reads as one multi-page document under its first page,
-- the lead, which carries the reading and the records; the other pages are hidden from lists while it lasts.

CREATE TABLE document_groups (
    id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('proposed','confirmed','dismissed')),
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
) STRICT;

CREATE TABLE document_group_pages (
    group_id INTEGER NOT NULL REFERENCES document_groups(id) ON DELETE CASCADE,
    occurrence_id INTEGER NOT NULL REFERENCES occurrences(id) ON DELETE CASCADE,
    page_no INTEGER NOT NULL CHECK (page_no BETWEEN 1 AND 20),
    PRIMARY KEY (group_id, occurrence_id),
    UNIQUE (group_id, page_no)
) STRICT;
CREATE INDEX document_group_pages_occurrence ON document_group_pages(occurrence_id);

PRAGMA user_version=55;
