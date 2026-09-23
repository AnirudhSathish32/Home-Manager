"""SQLite inventory and crash-recoverable immutable capture publication."""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import uuid
from .folders import FOLDERS, HIERARCHY, validate_folder

from .paths import DirectoryLock, PathError, path_key, safe_path


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
                if version not in (0, 1, 2, 3, 4, 5):
                    raise PathError("Unsupported inventory schema version.")
                if version == 1:
                    # SQLite backup includes WAL content; do not copy the live DB file.
                    backup = safe_path(root / "inventory.before-v2.sqlite3")
                    if not backup.exists():
                        with sqlite3.connect(backup) as target:
                            db.backup(target)
                if version in (1, 2):
                    backup = safe_path(root / "inventory.before-v3.sqlite3")
                    if not backup.exists():
                        with sqlite3.connect(backup) as target:
                            db.backup(target)
                migrations = Path(__file__).parent / "migrations"
                if version in (1, 2, 3):
                    backup = safe_path(root / "inventory.before-v4.sqlite3")
                    if not backup.exists():
                        with sqlite3.connect(backup) as target:
                            db.backup(target)
                if version in (1, 2, 3, 4):
                    backup = safe_path(root / "inventory.before-v5.sqlite3")
                    if not backup.exists():
                        with sqlite3.connect(backup) as target:
                            db.backup(target)
                for number, filename in ((1, "001_inventory.sql"), (2, "002_receipts.sql"), (3, "003_batches.sql"), (4, "004_library.sql"), (5, "005_organization.sql")):
                    if version < number:
                        db.executescript("BEGIN IMMEDIATE;\n" + (migrations / filename).read_text() + "\nCOMMIT;")
            self.recover()
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
            db.execute("UPDATE jobs SET organization_status='interrupted', organization_message='Organization was interrupted. Use Parse and organize to retry.' WHERE organization_status IN ('queued','running')")
        # Only generated, unreferenced staging files; never touch user input.
        for temp in self.work.glob("*.part"):
            if len(temp.stem) == 32 and all(c in "0123456789abcdef" for c in temp.stem) and temp.stem not in pending:
                safe_path(temp).unlink()

    def mark_missing(self, job: str, source: Path, year=None, month=None):
        clauses, params = ["source_root=?", "last_job<>?", "source_status<>'missing'"], [path_key(source), job]
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
        return ("WITH library AS (SELECT o.*,b.size,"
                "(SELECT count(*) FROM versions v WHERE v.occurrence_id=o.id) AS version_count,"
                "(SELECT json_extract(p.result_json,'$.title') FROM parse_runs p WHERE p.blob_hash=o.current_hash "
                "AND p.status IN ('succeeded','partial') AND json_extract(p.result_json,'$.title') IS NOT NULL "
                "ORDER BY p.created_at DESC LIMIT 1) AS title,"
                "coalesce((SELECT f.folder FROM document_folders f WHERE f.document_id=o.id AND f.blob_hash=o.current_hash),"
                "(SELECT r.result_folder FROM organization_runs r WHERE r.document_id=o.id AND r.blob_hash=o.current_hash "
                "AND r.status='succeeded' ORDER BY r.created_at DESC LIMIT 1),"
                "(SELECT json_extract(p.result_json,'$.folder') FROM parse_runs p WHERE p.blob_hash=o.current_hash "
                "AND p.status IN ('succeeded','partial') AND json_extract(p.result_json,'$.folder') IS NOT NULL "
                "ORDER BY p.created_at DESC LIMIT 1),'Unfiled') AS folder,"
                "(SELECT p.status FROM parse_runs p WHERE p.blob_hash=o.current_hash ORDER BY p.created_at DESC LIMIT 1) AS parse_status "
                "FROM occurrences o JOIN blobs b ON b.hash=o.current_hash) ")

    def documents(self, source: Path, offset=0, limit=100, folder="all"):
        clause = "source_root=? AND deleted_at IS NULL"
        params = [path_key(source)]
        if folder == "trash":
            clause = "source_root=? AND deleted_at IS NOT NULL"
        elif folder in ["Unfiled", *FOLDERS]:
            clause += " AND folder=?"
            params.append(folder)
        elif folder in HIERARCHY:
            clause += " AND folder LIKE ?"
            params.append(folder + "/%")
        elif folder != "all":
            raise ValueError("Unknown library folder.")
        with self.connection() as db:
            total = db.execute(self.library_query() + "SELECT count(*) FROM library WHERE " + clause, params).fetchone()[0]
            rows = db.execute(self.library_query() + "SELECT * FROM library WHERE " + clause + " ORDER BY relative_path LIMIT ? OFFSET ?", [*params, limit, offset])
            return {"total": total, "items": [dict(row) for row in rows]}

    def folders(self, source):
        with self.connection() as db:
            rows = db.execute(self.library_query() + "SELECT folder,deleted_at IS NOT NULL AS trashed,count(*) AS count FROM library WHERE source_root=? GROUP BY folder,trashed", (path_key(source),)).fetchall()
        counts = {folder: 0 for folder in ["all", "trash", "Unfiled", *HIERARCHY, *FOLDERS]}
        for row in rows:
            if row["trashed"]:
                counts["trash"] += row["count"]
            else:
                counts["all"] += row["count"]
                counts[row["folder"]] = counts.get(row["folder"], 0) + row["count"]
                parent = row["folder"].split("/")[0]
                if parent in HIERARCHY:
                    counts[parent] += row["count"]
        return {"hierarchy": HIERARCHY, "counts": counts}

    def library_action(self, source, document_id, expected_hash, action, folder=None):
        if action == "move":
            validate_folder(folder)
        if action not in ("move", "trash", "restore"):
            raise ValueError("Unknown library action.")
        with self.connection() as db:
            doc = db.execute("SELECT * FROM occurrences WHERE id=? AND source_root=?", (document_id, path_key(source))).fetchone()
            if doc is None:
                raise ValueError("Document not found in the selected source library.")
            if doc["current_hash"] != expected_hash:
                raise RuntimeError("Document version changed. Refresh and confirm the action again.")
            if action == "move":
                if doc["deleted_at"]:
                    raise ValueError("Restore the document before moving it.")
                db.execute("INSERT INTO document_folders VALUES(?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET blob_hash=excluded.blob_hash,folder=excluded.folder,updated_at=excluded.updated_at", (document_id, expected_hash, folder, now()))
            else:
                db.execute("UPDATE occurrences SET deleted_at=? WHERE id=?", (now() if action == "trash" else None, document_id))
            db.execute("INSERT INTO library_events(document_id,blob_hash,action,detail,created_at) VALUES(?,?,?,?,?)", (document_id, expected_hash, action, folder or "", now()))

    def organization_state(self, job, status, message, batch=None):
        with self.connection() as db:
            db.execute("UPDATE jobs SET organization_status=?,organization_message=?,organization_batch_id=? WHERE id=?", (status, message, batch, job))

    def versions(self, occurrence: int):
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT v.*,b.size FROM versions v JOIN blobs b ON b.hash=v.hash "
                                                  "WHERE occurrence_id=? ORDER BY v.id DESC", (occurrence,))]

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
