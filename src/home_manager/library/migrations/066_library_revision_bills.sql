-- Bills are kept as documents. Revision catches fast captures and filing between polls.
INSERT INTO folder_aliases(old_folder,folder) VALUES('Bills','Bills') ON CONFLICT(old_folder) DO UPDATE SET folder='Bills';
CREATE TABLE library_revision(id INTEGER PRIMARY KEY CHECK(id=1), version INTEGER NOT NULL) STRICT;
INSERT INTO library_revision VALUES(1,0);
CREATE TABLE record_corrections_new (
    id INTEGER PRIMARY KEY,
    record_type TEXT NOT NULL CHECK (record_type IN ('receipt','receipt_item','bill','income_record','transaction','statement','investment_valuation',
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
INSERT INTO record_corrections_new SELECT * FROM record_corrections;
DROP TABLE record_corrections;
ALTER TABLE record_corrections_new RENAME TO record_corrections;
CREATE INDEX record_corrections_record ON record_corrections(record_type, record_id, field, id);
CREATE TRIGGER revision_occurrences_insert AFTER INSERT ON occurrences BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_occurrences_update AFTER UPDATE ON occurrences BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_occurrences_delete AFTER DELETE ON occurrences BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_managed_files_insert AFTER INSERT ON managed_files BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_managed_files_update AFTER UPDATE ON managed_files BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_managed_files_delete AFTER DELETE ON managed_files BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_document_folders_insert AFTER INSERT ON document_folders BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_document_folders_update AFTER UPDATE ON document_folders BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_document_folders_delete AFTER DELETE ON document_folders BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_parse_runs_insert AFTER INSERT ON parse_runs BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_parse_runs_update AFTER UPDATE ON parse_runs BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_parse_runs_delete AFTER DELETE ON parse_runs BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_extraction_runs_insert AFTER INSERT ON extraction_runs BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_extraction_runs_update AFTER UPDATE ON extraction_runs BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
CREATE TRIGGER revision_extraction_runs_delete AFTER DELETE ON extraction_runs BEGIN UPDATE library_revision SET version=version+1 WHERE id=1; END;
PRAGMA user_version=66;
