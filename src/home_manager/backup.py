"""Backups to a separate destination and verified restores into a new library (spec section 19).

A backup is a folder holding a consistent SQLite snapshot (the backup API, never a copy of
the live WAL database), the immutable originals (hash-verified while copied), the managed
Library files, the image previews that readings refer to, and manifest.json listing every
file with its size and SHA-256. The folder appears under its final name only once complete.

A restore verifies the whole backup first, then builds a new managed library in an empty
folder. It never replaces or modifies the active library; the user switches to the restored
one in Settings.
"""

import hashlib
from importlib import metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import uuid

from .jobs import Work
from .paths import PathError, path_key, safe_path, write_atomic
from .storage import MIGRATIONS, now

FORMAT = "home-manager-backup-v1"
MANIFEST = "manifest.json"
DATABASE = "inventory.sqlite3"
STORE_MARKER = "home-manager-store-v1\n"
CHUNK = 1024 * 1024
# Top-level folders a manifest may name; anything else is rejected before a byte is copied.
FILE_ROOTS = ("originals", "Library", "extracted")


def app_version():
    try:
        return metadata.version("home-manager")
    except metadata.PackageNotFoundError:
        return "unknown"


def copy_verified(source: Path, target: Path, expected=None):
    """Stream a file, hashing as it goes; fsync the copy. Returns (size, sha256) or raises on mismatch."""
    digest, size = hashlib.sha256(), 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(safe_path(source), "rb") as reader, open(safe_path(target), "xb") as writer:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
            writer.write(chunk)
            size += len(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    if expected is not None and digest.hexdigest() != expected:
        raise ValueError(f"{source.name} failed its integrity check; the backup was stopped.")
    return size, digest.hexdigest()


def file_digest(path: Path):
    with open(safe_path(path), "rb") as stream:
        return path.stat().st_size, hashlib.file_digest(stream, "sha256").hexdigest()


def manifest_path(relative: str) -> PurePosixPath:
    """Confine a manifest entry to the backup's own layout: no absolute paths, drives or '..'."""
    path = PurePosixPath(relative)
    if (path.is_absolute() or "\\" in relative or ":" in relative or any(part in ("", ".", "..") for part in path.parts)
            or (path.parts[0] not in FILE_ROOTS and relative != DATABASE)):
        raise PathError("The backup manifest names a file outside the backup layout.")
    return path


class BackupService:
    def __init__(self, store):
        self.store = store

    def recover(self):
        with self.store.connection() as db:
            db.execute("UPDATE backups SET status='interrupted',finished_at=?,error='Home Manager stopped during the backup.' WHERE status='running'", (now(),))

    def history(self, limit=20):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM backups ORDER BY started_at DESC LIMIT ?", (limit,))]

    def begin(self, destination: Path):
        backup_id = uuid.uuid4().hex
        with self.store.connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            db.execute("INSERT INTO backups(id,destination,status,started_at,schema_version) VALUES(?,?,'running',?,?)",
                       (backup_id, str(destination), now(), version))
        return backup_id

    def run(self, backup_id, destination: Path, work=None):
        work = work or Work.detached()
        final = safe_path(destination / f"home-manager-backup-{now()[:19].replace(':', '')}-{backup_id[:8]}")
        staging = safe_path(final.with_name(final.name + ".partial"))
        try:
            staging.mkdir()
            manifest = self.write(staging, backup_id, work)
            data = json.dumps(manifest, indent=2, sort_keys=True).encode()
            write_atomic(staging / MANIFEST, data)
            os.replace(staging, final)
            self.finish(backup_id, "succeeded", files=len(manifest["files"]), total=sum(item["size"] for item in manifest["files"]),
                        manifest=hashlib.sha256(data).hexdigest(), destination=final)
        except BaseException as exc:
            # Only the staging folder this run created is removed; nothing else in the destination is touched.
            if staging.exists() and staging.parent == destination and staging.name.endswith(".partial"):
                shutil.rmtree(staging, ignore_errors=True)
            cancelled = work.cancelled
            self.finish(backup_id, "cancelled" if cancelled else "failed",
                        error="Cancelled by the user." if cancelled else (str(exc) if isinstance(exc, (ValueError, OSError)) else type(exc).__name__))
            if not cancelled:
                raise

    def finish(self, backup_id, status, files=None, total=None, manifest=None, destination=None, error=None):
        with self.store.connection() as db:
            db.execute("UPDATE backups SET status=?,finished_at=?,file_count=?,total_bytes=?,manifest_sha256=?,error=?,destination=coalesce(?,destination) WHERE id=?",
                       (status, now(), files, total, manifest, error, str(destination) if destination else None, backup_id))

    def write(self, staging: Path, backup_id, work):
        files, issues = [], []

        def add(relative, size, digest, kind):
            files.append({"path": relative, "size": size, "sha256": digest, "kind": kind})

        # 1. Database snapshot and Library files together, with filing held still so they agree.
        library = self.store.library
        with library.lock:
            target = sqlite3.connect(staging / DATABASE)
            try:
                with self.store.connection() as db:
                    db.backup(target)  # Includes committed WAL content; the live file is never copied.
                version = target.execute("PRAGMA user_version").fetchone()[0]
                managed = [row[0] for row in target.execute("SELECT relative_path FROM managed_files ORDER BY relative_path")]
                blobs = target.execute("SELECT hash FROM blobs ORDER BY hash").fetchall()
                previews = target.execute("SELECT id,preview_hash FROM parse_runs WHERE preview_hash IS NOT NULL ORDER BY id").fetchall()
            finally:
                target.close()
            for relative in managed:
                work.check()
                source = library.path(relative)
                if not source.exists():
                    issues.append(f"Library file {relative} was missing; its preserved original is included.")
                    continue
                add(f"Library/{relative}", *copy_verified(source, staging / "Library" / relative), "library")
        add(DATABASE, *file_digest(staging / DATABASE), "database")
        # 2. Immutable originals named by the snapshot, verified against their content address.
        for (digest,) in blobs:
            work.check()
            relative = f"originals/{digest[:2]}/{digest}.blob"
            add(relative, *copy_verified(self.store.blob_path(digest), staging / relative, digest), "original")
        # 3. Image previews that readings refer to; a damaged one is reported, not copied.
        for run_id, preview_hash in previews:
            work.check()
            relative = f"extracted/{run_id}/preview.png"
            try:
                add(relative, *copy_verified(safe_path(self.store.root / relative), staging / relative, preview_hash), "preview")
            except (ValueError, OSError):
                (staging / relative).unlink(missing_ok=True)
                issues.append(f"Preview for reading {run_id} is missing or damaged and was not included; read the document again after restoring.")
        return {"format": FORMAT, "backup_id": backup_id, "created_at": now(), "app_version": app_version(), "schema_version": version,
                "inbox_key": path_key(library.inbox), "files": files, "issues": issues}


def verify_backup(folder: Path):
    """Check a backup completely without changing it. Returns (manifest or None, problems)."""
    folder = safe_path(folder)
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, ["This folder has no readable backup manifest. Choose the backup folder itself (home-manager-backup-…)."]
    if manifest.get("format") != FORMAT:
        return None, ["This backup was made in an unsupported format."]
    problems = []
    if not isinstance(manifest.get("schema_version"), int) or manifest["schema_version"] > MIGRATIONS[-1][0]:
        problems.append("This backup comes from a newer Home Manager version. Update Home Manager before restoring it.")
    for entry in manifest.get("files", []):
        try:
            path = folder.joinpath(*manifest_path(entry["path"]).parts)
            size, digest = file_digest(path)
        except PathError as exc:
            return None, [str(exc)]
        except OSError:
            problems.append(f"{entry['path']} is missing.")
            continue
        if size != entry["size"] or digest != entry["sha256"]:
            problems.append(f"{entry['path']} does not match the manifest.")
    if not problems:
        database = sqlite3.connect(f"{(folder / DATABASE).as_uri()}?mode=ro", uri=True)
        try:
            if database.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                problems.append("The backed-up database failed SQLite's integrity check.")
            elif database.execute("PRAGMA user_version").fetchone()[0] != manifest["schema_version"]:
                problems.append("The backed-up database version differs from the manifest.")
        finally:
            database.close()
    return manifest, problems


def restore_backup(folder: Path, target: Path, work=None):
    """Build a new managed library from a verified backup. The target must be empty or not yet exist."""
    work = work or Work.detached()
    manifest, problems = verify_backup(folder)
    if manifest is None or problems:
        raise ValueError("The backup did not verify: " + " ".join(problems))
    target = safe_path(target)
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise PathError("Restore into a new or empty folder; the active library is never overwritten.")
    target.mkdir(parents=True, exist_ok=True)
    for entry in manifest["files"]:
        work.check()
        relative = manifest_path(entry["path"])
        copy_verified(folder.joinpath(*relative.parts), target.joinpath(*relative.parts), entry["sha256"])
    # Documents captured through Inbox are keyed by the Inbox's absolute path; point them at the new one.
    new_inbox = path_key(target / "Library" / "Inbox")
    with sqlite3.connect(target / DATABASE) as db:
        for table in ("occurrences", "jobs", "receipt_batches", "capture_intents"):
            db.execute(f"UPDATE {table} SET source_root=? WHERE source_root=?", (new_inbox, manifest["inbox_key"]))
    db.close()
    # The store marker comes last: an interrupted restore leaves a folder Home Manager refuses to open.
    write_atomic(target / ".home-manager-store", STORE_MARKER)
    return {"restored_to": str(target), "files": len(manifest["files"]), "schema_version": manifest["schema_version"],
            "backup_created_at": manifest["created_at"], "issues": manifest.get("issues", [])}
