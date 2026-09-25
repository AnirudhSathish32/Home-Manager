"""SQLite inventory and crash-recoverable immutable capture publication."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .folders import LIBRARY_FOLDERS, validate_folder
from .money import format_minor
from .paths import DirectoryLock, PathError, path_key, safe_path

TABLE_FILE = "(lower(relative_path) LIKE '%.csv' OR lower(relative_path) LIKE '%.xlsx')"
# Work filters over the library view: what each document needs next.
WORK_FILTERS = {
    "all": "1",
    "needs_text": f"text_run_id IS NULL AND NOT {TABLE_FILE}",
    "ready_for_ledger": f"(text_run_id IS NOT NULL OR {TABLE_FILE}) AND ledger_status IS NULL",
    "needs_review": "ledger_status IN ('proposed','needs_review')",
    "failed": "(parse_status IN ('failed','interrupted') OR extraction_status IN ('failed','interrupted'))",
}
# Library orderings. "date" is the document's own date (purchase, period end, due or pay date).
DOCUMENT_SORTS = {
    "path": "relative_path",
    "name": "lower(coalesce(title,relative_path)),relative_path",
    "date": "document_date IS NULL,document_date DESC,relative_path",
    "added": "first_seen DESC,relative_path",
}
# Unified job history: every kind of durable work as (kind, id, status, started, finished, document, error).
# Readings that belong to a batch are listed through their batch, not one by one.
JOB_HISTORY = {
    "source_scan": "SELECT 'source_scan',id,status,created_at,updated_at,NULL,error FROM jobs WHERE source_root<>:inbox",
    "inbox_capture": "SELECT 'inbox_capture',id,status,created_at,updated_at,NULL,error FROM jobs WHERE source_root=:inbox",
    "text_batch": "SELECT 'text_batch',id,status,created_at,NULL,NULL,NULL FROM receipt_batches",
    "text_reading": "SELECT 'text_reading',p.id,p.status,p.created_at,p.updated_at,(SELECT o.id FROM occurrences o WHERE o.current_hash=p.blob_hash "
                    "ORDER BY o.id LIMIT 1),p.error FROM parse_runs p WHERE NOT EXISTS(SELECT 1 FROM receipt_batch_items i WHERE i.run_id=p.id)",
    "ledger_extraction": "SELECT 'ledger_extraction',id,status,created_at,updated_at,document_id,error FROM extraction_runs",
    "audit_analysis": "SELECT 'audit_analysis',r.id,r.status,r.created_at,r.updated_at,(SELECT o.id FROM occurrences o JOIN parse_runs p ON p.blob_hash=o.current_hash "
                      "WHERE p.id=r.parse_run_id ORDER BY o.id LIMIT 1),r.error FROM reasoning_runs r",
    "reconciliation": "SELECT 'reconciliation',CAST(id AS TEXT),status,started_at,finished_at,NULL,error FROM reconciliation_runs",
    "backup": "SELECT 'backup',id,status,started_at,finished_at,NULL,error FROM backups",
    "assistant": "SELECT 'assistant',id,status,created_at,updated_at,NULL,error FROM assistant_runs",
}
# Forward-only schema scripts; NNN_ prefixes match PRAGMA user_version.
MIGRATIONS = sorted((int(path.name[:3]), path) for path in (Path(__file__).parent / "migrations").glob("[0-9][0-9][0-9]_*.sql"))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_file(path: Path) -> str:
    with open(safe_path(path), "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


class Store:
    def __init__(self, root: Path):
        self.root = safe_path(root)
        marker = safe_path(root / ".home-manager-store")
        if root.exists() and any(root.iterdir()) and not marker.exists():
            raise PathError("Choose an empty managed-data folder or an existing Home Manager store.")
        if marker.exists() and marker.read_text(encoding="utf-8") != "home-manager-store-v1\n":
            raise PathError("Unrecognized managed-data store marker.")
        self.lock = DirectoryLock(root)
        try:
            marker.write_text("home-manager-store-v1\n", encoding="utf-8")
            self.work = safe_path(root / "work")
            self.originals = safe_path(root / "originals")
            self.work.mkdir(exist_ok=True)
            self.originals.mkdir(exist_ok=True)
            self.db_path = safe_path(root / "inventory.sqlite3")
            with self.connection() as db:
                db.execute("PRAGMA journal_mode=WAL")
                version = db.execute("PRAGMA user_version").fetchone()[0]
                latest = MIGRATIONS[-1][0]
                if version not in range(latest + 1):
                    raise PathError("Unsupported inventory schema version.")
                if 0 < version < latest:
                    # SQLite backup includes WAL content; never copy the live DB file.
                    backup = safe_path(root / f"inventory.before-v{latest}.sqlite3")
                    if not backup.exists():
                        target = sqlite3.connect(backup)
                        try:
                            db.backup(target)
                        finally:
                            target.close()
                for number, script in MIGRATIONS:
                    if version < number:
                        db.executescript("BEGIN IMMEDIATE;\n" + script.read_text() + "\nCOMMIT;")
            self.recover()
            from .managed_library import ManagedLibrary
            self.library = ManagedLibrary(self)
            self.library.recover()
            from .trash import cleanup
            cleanup(self)
        except BaseException:
            self.lock.close()
            raise

    @contextmanager
    def connection(self):
        safe_path(self.db_path)
        db = sqlite3.connect(self.db_path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self):
        self.lock.close()

    def blob_path(self, digest: str) -> Path:
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid content hash.")
        return safe_path(self.originals / digest[:2] / (digest + ".blob"))

    def create_job(self, source: Path, year=None, month=None) -> str:
        job = uuid.uuid4().hex
        with self.connection() as db:
            db.execute("INSERT INTO jobs(id,source_root,year,month,status,created_at,updated_at,error) VALUES (?, ?, ?, ?, 'queued', ?, ?, NULL)",
                       (job, path_key(source), year, month, now(), now()))
        return job

    def job_state(self, job: str, status: str, error=None):
        with self.connection() as db:
            db.execute("UPDATE jobs SET status=?, updated_at=?, error=? WHERE id=?",
                       (status, now(), error, job))

    def event(self, job: str, relative: str, status: str, message: str, digest=None):
        with self.connection() as db:
            db.execute("INSERT INTO events(job_id,relative_path,status,message,hash,created_at) "
                       "VALUES(?,?,?,?,?,?)", (job, relative, status, message, digest, now()))
            db.execute("UPDATE jobs SET updated_at=? WHERE id=?", (now(), job))

    def observe(self, job: str, source: Path, relative: str, status="present"):
        with self.connection() as db:
            db.execute("UPDATE occurrences SET last_seen=?,last_job=?,source_status=? "
                       "WHERE source_root=? AND path_key=?",
                       (now(), job, status, path_key(source), path_key(relative)))

    def prepare(self, capture_id: str, job: str, source: Path, relative: str,
                year: int, month: int, digest: str, size: int, mtime_ns: int):
        with self.connection() as db:
            db.execute("INSERT INTO capture_intents VALUES(?,?,?,?,?,?,?,?,?)",
                       (capture_id, job, path_key(source), relative, year, month,
                        digest, size, mtime_ns))

    def publish(self, capture_id: str) -> str:
        with self.connection() as db:
            row = db.execute("SELECT * FROM capture_intents WHERE id=?", (capture_id,)).fetchone()
        if row is None:
            raise ValueError("Capture intent not found.")
        item = dict(row)
        temp = safe_path(self.work / (capture_id + ".part"))
        final = self.blob_path(item["hash"])
        final.parent.mkdir(exist_ok=True)
        if not final.exists():
            if not temp.is_file() or temp.stat().st_size != item["size"] or digest_file(temp) != item["hash"]:
                raise OSError("Incomplete capture; rescan its source file.")
            try:
                # Atomic publication without overwriting an existing immutable blob.
                os.link(temp, final)
            except FileExistsError:
                pass
        if final.stat().st_size != item["size"] or digest_file(final) != item["hash"]:
            raise OSError("Stored evidence failed its integrity check; restore the managed store from backup.")
        stamp = now()
        with self.connection() as db:
            duplicate = db.execute("SELECT 1 FROM blobs WHERE hash=?", (item["hash"],)).fetchone()
            db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?,?)", (item["hash"], item["size"], stamp))
            previous = db.execute("SELECT o.id,o.current_hash,j.created_at AS job_created FROM occurrences o "
                                  "JOIN jobs j ON j.id=o.last_job WHERE o.source_root=? AND o.path_key=?",
                                  (item["source_root"], path_key(item["relative_path"]))).fetchone()
            if previous:
                occurrence = previous["id"]
                intent_job_date = db.execute("SELECT created_at FROM jobs WHERE id=?", (item["job_id"],)).fetchone()[0]
                if previous["job_created"] > intent_job_date:
                    # A failed old publication may recover after a newer scan.
                    # Preserve it as history without rolling the current pointer back.
                    status = "recovered_version"
                else:
                    status = "unchanged" if previous["current_hash"] == item["hash"] else "new_version"
                    db.execute("UPDATE occurrences SET current_hash=?,source_status='present',last_seen=?,"
                               "last_job=?,relative_path=? WHERE id=?",
                               (item["hash"], stamp, item["job_id"], item["relative_path"], occurrence))
            else:
                status = "duplicate" if duplicate else "captured"
                cursor = db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,folder_year,"
                                    "folder_month,current_hash,first_seen,last_seen,last_job) VALUES(?,?,?,?,?,?,?,?,?)",
                                    (item["source_root"], path_key(item["relative_path"]), item["relative_path"],
                                     item["folder_year"], item["folder_month"], item["hash"], stamp, stamp, item["job_id"]))
                occurrence = cursor.lastrowid
            db.execute("INSERT OR IGNORE INTO versions(occurrence_id,hash,captured_at,source_mtime_ns) VALUES(?,?,?,?)",
                       (occurrence, item["hash"], stamp, item["source_mtime_ns"]))
            if item["source_root"] == path_key(self.root / "Library" / "Inbox"):
                db.execute("UPDATE occurrences SET source_kind='inbox' WHERE id=?", (occurrence,))
            db.execute("INSERT INTO events(job_id,relative_path,status,message,hash,created_at) VALUES(?,?,?,?,?,?)",
                       (item["job_id"], item["relative_path"], status,
                        "Bytes preserved. Content parsing is a separate operation.", item["hash"], stamp))
            db.execute("DELETE FROM capture_intents WHERE id=?", (capture_id,))
            db.execute("UPDATE jobs SET updated_at=? WHERE id=?", (stamp, item["job_id"]))
        # A crash here leaves only an expendable internal temporary hard link.
        temp.unlink(missing_ok=True)
        return status

    def recover(self):
        with self.connection() as db:
            intents = [dict(row) for row in db.execute("SELECT * FROM capture_intents")]
        for item in intents:
            try:
                self.publish(item["id"])
            except (OSError, ValueError) as exc:
                self.event(item["job_id"], item["relative_path"], "recovery_failed", str(exc))
                # Retain failed intent and staged bytes for inspection/retry.
        with self.connection() as db:
            db.execute("UPDATE jobs SET status='interrupted',updated_at=?,error=? "
                       "WHERE status IN ('queued','running')",
                       (now(), "Previous process stopped. Preserved captures recovered where possible; run a new scan."))
            pending = {row[0] for row in db.execute("SELECT id FROM capture_intents")}
            db.execute("UPDATE jobs SET organization_status='interrupted', organization_message='Text extraction was interrupted. Use Extract text from all images to retry.' WHERE organization_status IN ('queued','running')")
        # Only generated, unreferenced staging files; never touch user input.
        for temp in self.work.glob("*.part"):
            if len(temp.stem) == 32 and all(c in "0123456789abcdef" for c in temp.stem) and temp.stem not in pending:
                safe_path(temp).unlink()

    def mark_missing(self, job: str, source: Path, year=None, month=None):
        clauses, params = ["source_root=?", "last_job<>?", "source_status NOT IN ('missing','organized')"], [path_key(source), job]
        if year is not None:
            clauses.append("folder_year=?")
            params.append(year)
        if month is not None:
            clauses.append("folder_month=?")
            params.append(month)
        with self.connection() as db:
            rows = list(db.execute("SELECT id,relative_path,current_hash FROM occurrences WHERE " + " AND ".join(clauses), params))
            for row in rows:
                db.execute("UPDATE occurrences SET source_status='missing' WHERE id=?", (row["id"],))
                db.execute("INSERT INTO events(job_id,relative_path,status,message,hash,created_at) VALUES(?,?,?,?,?,?)",
                           (job, row["relative_path"], "missing", "Not found in this scan. Preserved copies and versions retained.", row["current_hash"], now()))

    def jobs(self, limit=50):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,))]

    def job_history(self, limit=50, kinds=None):
        """Recent work of every kind, newest first, in one query."""
        kinds = kinds or list(JOB_HISTORY)
        if any(kind not in JOB_HISTORY for kind in kinds):
            raise ValueError("Unknown job kind.")
        query = " UNION ALL ".join(JOB_HISTORY[kind] for kind in kinds)
        columns = ("kind", "id", "status", "started_at", "finished_at", "document_id", "error")
        with self.connection() as db:
            rows = db.execute(f"SELECT * FROM ({query}) ORDER BY 4 DESC LIMIT :limit", {"inbox": path_key(self.library.inbox), "limit": limit})
            return [dict(zip(columns, row)) for row in rows]

    def job(self, job: str):
        with self.connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job,)).fetchone()
            if row is None:
                return None
            result = dict(row)
            result["counts"] = {r[0]: r[1] for r in db.execute("SELECT status,count(*) FROM events WHERE job_id=? GROUP BY status", (job,))}
            return result

    def events(self, job: str, offset=0, limit=100):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM events WHERE job_id=? ORDER BY id LIMIT ? OFFSET ?", (job, limit, offset))]

    def library_query(self):
        return ("WITH raw_library AS (SELECT o.*,b.size,m.relative_path AS managed_path,m.reason AS organization_reason,"
                "(SELECT i.status FROM managed_organization_intents i WHERE i.document_id=o.id AND i.blob_hash=o.current_hash ORDER BY i.created_at DESC LIMIT 1) AS managed_status,"
                "(SELECT i.error FROM managed_organization_intents i WHERE i.document_id=o.id AND i.blob_hash=o.current_hash ORDER BY i.created_at DESC LIMIT 1) AS managed_error,"
                "(SELECT count(*) FROM versions v WHERE v.occurrence_id=o.id) AS version_count,"
                # Naming parts, joined in the library view below as "Merchant - Location - Description".
                "(SELECT d.description FROM document_descriptions d WHERE d.document_id=o.id) AS user_description,"
                "(SELECT r.location FROM receipts r WHERE r.blob_hash=o.current_hash AND r.review_status<>'rejected') AS location,"
                "(SELECT r.description FROM receipts r WHERE r.blob_hash=o.current_hash AND r.review_status<>'rejected') AS model_description,"
                "coalesce((SELECT m.canonical_name FROM receipts r JOIN merchants m ON m.id=r.merchant_id WHERE r.blob_hash=o.current_hash AND r.review_status<>'rejected'),"
                "(SELECT a.institution FROM statements s JOIN accounts a ON a.id=s.account_id WHERE s.blob_hash=o.current_hash AND s.review_status<>'rejected'),"
                "(SELECT m.canonical_name FROM bills b JOIN merchants m ON m.id=b.provider_merchant_id WHERE b.blob_hash=o.current_hash AND b.review_status<>'rejected'),"
                "(SELECT m.canonical_name FROM income_records i JOIN merchants m ON m.id=i.payer_merchant_id WHERE i.blob_hash=o.current_hash AND i.review_status<>'rejected')) AS merchant,"
                "coalesce(m.folder,(SELECT f.folder FROM document_folders f WHERE f.document_id=o.id AND f.blob_hash=o.current_hash),"
                "(SELECT r.result_folder FROM organization_runs r WHERE r.document_id=o.id AND r.blob_hash=o.current_hash "
                "AND r.status='succeeded' ORDER BY r.created_at DESC LIMIT 1),"
                "(SELECT json_extract(p.result_json,'$.folder') FROM parse_runs p WHERE p.blob_hash=o.current_hash "
                "AND p.status IN ('succeeded','partial') AND json_extract(p.result_json,'$.folder') IS NOT NULL "
                "ORDER BY p.created_at DESC LIMIT 1),'Unfiled') AS stored_folder,"
                "(SELECT p.status FROM parse_runs p WHERE p.blob_hash=o.current_hash ORDER BY p.created_at DESC LIMIT 1) AS parse_status,"
                "(SELECT p.id FROM parse_runs p WHERE p.blob_hash=o.current_hash AND p.status IN ('succeeded','partial') "
                "AND p.parser_version<>'receipt-ocr-v1' ORDER BY p.created_at DESC LIMIT 1) AS text_run_id,"
                "(SELECT r.status FROM reasoning_runs r JOIN parse_runs p ON p.id=r.parse_run_id WHERE p.blob_hash=o.current_hash "
                "ORDER BY r.created_at DESC LIMIT 1) AS analysis_status,"
                "(SELECT e.status FROM extraction_runs e JOIN parse_runs p ON p.id=e.parse_run_id WHERE e.document_id=o.id "
                "AND p.blob_hash=o.current_hash ORDER BY e.created_at DESC LIMIT 1) AS extraction_status,"
                "coalesce((SELECT total_minor FROM receipts WHERE blob_hash=o.current_hash),(SELECT amount_due_minor FROM bills WHERE blob_hash=o.current_hash),"
                "(SELECT net_pay_minor FROM income_records WHERE blob_hash=o.current_hash),"
                "(SELECT coalesce(closing_balance_minor,statement_balance_minor) FROM statements WHERE blob_hash=o.current_hash)) AS ledger_amount_minor,"
                "coalesce((SELECT currency FROM receipts WHERE blob_hash=o.current_hash),(SELECT currency FROM bills WHERE blob_hash=o.current_hash),"
                "(SELECT currency FROM income_records WHERE blob_hash=o.current_hash),(SELECT currency FROM statements WHERE blob_hash=o.current_hash)) AS ledger_currency,"
                # Review state of the ledger record published from this version, or 'imported' for CSV/XLSX.
                "coalesce((SELECT review_status FROM receipts WHERE blob_hash=o.current_hash),(SELECT review_status FROM statements WHERE blob_hash=o.current_hash),"
                "(SELECT review_status FROM bills WHERE blob_hash=o.current_hash),(SELECT review_status FROM income_records WHERE blob_hash=o.current_hash),"
                "(SELECT CASE WHEN count(*)>0 THEN 'imported' END FROM transaction_imports i WHERE i.blob_hash=o.current_hash)) AS ledger_status,"
                # The document's own date from its ledger record, for display, filtering and sorting.
                "coalesce((SELECT purchase_date FROM receipts WHERE blob_hash=o.current_hash),(SELECT period_end FROM statements WHERE blob_hash=o.current_hash),"
                "(SELECT coalesce(due_date,issue_date) FROM bills WHERE blob_hash=o.current_hash),(SELECT pay_date FROM income_records WHERE blob_hash=o.current_hash)) AS document_date,"
                # Reconciliation of the record published from this version: a receipt's match to a
                # transaction, or a bill's payment state. NULL where reconciliation does not apply.
                "coalesce((SELECT CASE WHEN EXISTS(SELECT 1 FROM transaction_receipt_links l WHERE l.receipt_id=r.id AND l.review_status='verified') THEN 'matched' "
                "WHEN EXISTS(SELECT 1 FROM transaction_receipt_links l WHERE l.receipt_id=r.id AND l.review_status='proposed') THEN 'proposed' "
                "WHEN EXISTS(SELECT 1 FROM reconciliation_issues i WHERE i.record_type='receipt' AND i.record_id=r.id AND i.status='open') THEN 'ambiguous' "
                "ELSE 'unmatched' END FROM receipts r WHERE r.blob_hash=o.current_hash AND r.review_status<>'rejected'),"
                "(SELECT CASE b.payment_status WHEN 'paid' THEN 'matched' WHEN 'unpaid' THEN 'unmatched' END FROM bills b "
                "WHERE b.blob_hash=o.current_hash AND b.review_status<>'rejected')) AS reconciliation_status "
                "FROM occurrences o JOIN blobs b ON b.hash=o.current_hash LEFT JOIN managed_files m ON m.document_id=o.id AND m.blob_hash=o.current_hash), "
                # An AI description that merely restates the merchant or location (saved before extraction checked
                # for this) is left out of the title; the user's own description is always shown as written.
                "described AS (SELECT r.*,coalesce(r.user_description,CASE WHEN "
                # instr() is NULL when the merchant or location is missing, which keeps the description.
                "instr(upper(r.merchant),upper(r.model_description))>0 OR instr(upper(r.model_description),upper(r.merchant))>0 "
                "OR instr(upper(r.location),upper(r.model_description))>0 OR instr(upper(r.model_description),upper(r.location))>0 "
                "THEN NULL ELSE r.model_description END) AS shown_description FROM raw_library r), "
                "library AS (SELECT r.*,coalesce(a.folder,'Unfiled') AS folder,r.shown_description AS description,"
                "CASE WHEN r.user_description IS NOT NULL THEN 'user' WHEN r.shown_description IS NOT NULL THEN 'model' END AS description_source,"
                "nullif(substr(coalesce(' - '||r.merchant,'')||coalesce(' - '||r.location,'')||coalesce(' - '||r.shown_description,''),4),'') AS title,"
                "CASE WHEN coalesce(a.folder,'Unfiled')='Unfiled' THEN r.organization_reason END AS unfiled_reason "
                "FROM described r LEFT JOIN folder_aliases a ON a.old_folder=r.stored_folder) ")

    @staticmethod
    def display_amount(row):
        # Exact display text; the browser never formats money.
        row["ledger_amount"] = format_minor(row["ledger_amount_minor"], row["ledger_currency"]) if row["ledger_amount_minor"] is not None else None
        return row

    def documents(self, source: Path, offset=0, limit=100, folder="all", status="all", query=None, sort="path", date_from=None, date_to=None):
        if sort not in DOCUMENT_SORTS:
            raise ValueError("Unknown document sort order.")
        clause = "source_root IN (?,?) AND deleted_at IS NULL"
        params = [path_key(source), path_key(self.library.inbox)]
        if folder == "trash":
            clause = "source_root IN (?,?) AND deleted_at IS NOT NULL"
        elif folder in LIBRARY_FOLDERS:
            clause += " AND folder=?"
            params.append(folder)
        elif folder != "all":
            raise ValueError("Unknown library folder.")
        if status not in WORK_FILTERS:
            raise ValueError("Unknown document filter.")
        if status != "all":
            clause += " AND " + WORK_FILTERS[status]
        if query:
            clause += " AND (lower(coalesce(title,'')) LIKE ? ESCAPE '\\' OR lower(coalesce(merchant,'')) LIKE ? ESCAPE '\\' OR lower(relative_path) LIKE ? ESCAPE '\\')"
            pattern = "%" + query.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            params += [pattern, pattern, pattern]
        for bound, operator in ((date_from, ">="), (date_to, "<=")):
            if bound:
                clause += f" AND document_date{operator}?"
                params.append(bound)
        with self.connection() as db:
            total = db.execute(self.library_query() + "SELECT count(*) FROM library WHERE " + clause, params).fetchone()[0]
            rows = [dict(row) for row in db.execute(self.library_query() + "SELECT * FROM library WHERE " + clause + f" ORDER BY {DOCUMENT_SORTS[sort]} LIMIT ? OFFSET ?",
                                                    [*params, limit, offset])]
        return {"total": total, "items": [self.display_amount(row) for row in rows]}

    def document(self, source: Path, document_id: int):
        """One library row (including Trash), shaped like a documents() item."""
        with self.connection() as db:
            row = db.execute(self.library_query() + "SELECT * FROM library WHERE source_root IN (?,?) AND id=?",
                             (path_key(source), path_key(self.library.inbox), document_id)).fetchone()
        if row is None:
            raise ValueError("Document not found.")
        return self.display_amount(dict(row))

    def set_description(self, source: Path, document_id: int, description: str | None):
        """The user's own description (the last part of the title); None or blank returns to the model's."""
        self.document(source, document_id)  # Only documents in this library.
        text = " ".join((description or "").split())
        if len(text) > 60:
            raise ValueError("Keep the description to 60 characters or fewer.")
        with self.connection() as db:
            if text:
                db.execute("INSERT INTO document_descriptions VALUES(?,?,?) ON CONFLICT(document_id) DO UPDATE SET description=excluded.description,updated_at=excluded.updated_at",
                           (document_id, text, now()))
            else:
                db.execute("DELETE FROM document_descriptions WHERE document_id=?", (document_id,))
        return self.document(source, document_id)

    def folders(self, source):
        roots = (path_key(source), path_key(self.library.inbox))
        with self.connection() as db:
            rows = db.execute(self.library_query() + "SELECT folder,deleted_at IS NOT NULL AS trashed,count(*) AS count FROM library WHERE source_root IN (?,?) GROUP BY folder,trashed", roots).fetchall()
            work = {name: db.execute(self.library_query() + f"SELECT count(*) FROM library WHERE source_root IN (?,?) AND deleted_at IS NULL AND {condition}", roots).fetchone()[0]
                    for name, condition in WORK_FILTERS.items() if name != "all"}
        counts = {folder: 0 for folder in ["all", "trash", *LIBRARY_FOLDERS]}
        for row in rows:
            if row["trashed"]:
                counts["trash"] += row["count"]
            else:
                counts["all"] += row["count"]
                counts[row["folder"]] += row["count"]
        return {"folders": LIBRARY_FOLDERS, "counts": counts, "work": work}

    def library_action(self, source, document_id, expected_hash, action, folder=None):
        if action == "move":
            validate_folder(folder)
        if action not in ("move", "trash", "restore"):
            raise ValueError("Unknown library action.")
        with self.connection() as db:
            doc = db.execute("SELECT * FROM occurrences WHERE id=? AND source_root IN (?,?)", (document_id, path_key(source), path_key(self.library.inbox))).fetchone()
            if doc is None:
                raise ValueError("Document not found in the selected source library.")
            if doc["current_hash"] != expected_hash:
                raise RuntimeError("Document version changed. Refresh and confirm the action again.")
            if action == "move":
                if doc["deleted_at"]:
                    raise ValueError("Restore the document before moving it.")
            else:
                db.execute("UPDATE occurrences SET deleted_at=? WHERE id=?", (now() if action == "trash" else None, document_id))
            if action != "move":
                db.execute("INSERT INTO library_events(document_id,blob_hash,action,detail,created_at) VALUES(?,?,?,?,?)", (document_id, expected_hash, action, folder or "", now()))
        if action == "move":
            self.library.ensure_document(document_id, expected_hash)
            self.library.organize(document_id, expected_hash, folder, "Manually filed by the user.", action="manual")

    def organization_state(self, job, status, message, batch=None):
        with self.connection() as db:
            db.execute("UPDATE jobs SET organization_status=?,organization_message=?,organization_batch_id=? WHERE id=?", (status, message, batch, job))

    def versions(self, occurrence: int):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT v.*,b.size FROM versions v JOIN blobs b ON b.hash=v.hash "
                                                  "WHERE occurrence_id=? ORDER BY v.id DESC", (occurrence,))]

    MODEL_RUN_FIELDS = ("model_id", "base_url", "started_at", "finished_at", "time_to_first_token_ms", "prompt_tokens",
                        "completion_tokens", "prompt_eval_ms", "generation_ms", "total_ms", "prompt_tokens_per_second",
                        "generation_tokens_per_second", "metrics_source", "input_bytes", "output_bytes", "finish_reason",
                        "status", "error_category")

    def record_model_run(self, task, owner_id, prompt_version, identity, metrics):
        with self.connection() as db:
            db.execute(f"INSERT INTO model_runs(task,owner_id,prompt_version,model_identity,{','.join(self.MODEL_RUN_FIELDS)}) "
                       f"VALUES(?,?,?,?,{','.join('?' * len(self.MODEL_RUN_FIELDS))})",
                       (task, owner_id, prompt_version, identity, *(metrics[key] for key in self.MODEL_RUN_FIELDS)))

    def remember_identity(self, fingerprint, config, metadata):
        with self.connection() as db:
            db.execute("INSERT OR IGNORE INTO model_identities VALUES(?,?,?,?,?)",
                       (fingerprint, config.model, config.base_url, json.dumps(metadata, sort_keys=True), now()))

    def model_runs(self, owner_id=None, limit=50):
        query = ("SELECT r.*,i.metadata_json FROM model_runs r LEFT JOIN model_identities i ON i.fingerprint=r.model_identity"
                 + (" WHERE r.owner_id=?" if owner_id else "") + " ORDER BY r.id DESC LIMIT ?")
        with self.connection() as db:
            return [dict(row) for row in db.execute(query, (owner_id, limit) if owner_id else (limit,))]

    def used_bytes(self) -> int:
        with self.connection() as db:
            return db.execute("SELECT coalesce(sum(size),0) FROM blobs").fetchone()[0]

    def document_version(self, occurrence: int, digest: str | None = None):
        with self.connection() as db:
            document = db.execute("SELECT * FROM occurrences WHERE id=?", (occurrence,)).fetchone()
            if document is None:
                raise ValueError("Document not found.")
            selected = digest or document["current_hash"]
            version = db.execute("SELECT * FROM versions WHERE occurrence_id=? AND hash=?", (occurrence, selected)).fetchone()
            if version is None:
                raise ValueError("This content version does not belong to the document.")
            return dict(document), dict(version)
