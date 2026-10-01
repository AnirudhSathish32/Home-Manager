"""Inbox and watched-folder discovery and capture. No parsing, OCR or model calls; source files are read, never written."""

from dataclasses import dataclass
import hashlib
import logging
import os
from pathlib import Path
import stat
import time
import uuid

from ..core.formats import SUPPORTED, extension
from ..core.logs import log_failure
from ..core.paths import PathError, is_link, safe_path, signature, source_reader
from .storage import Store

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanLimits:
    stability_seconds: float = 1.0
    max_file_bytes: int = 256 * 1024 * 1024
    max_store_bytes: int = 5 * 1024 * 1024 * 1024
    max_entries: int = 100_000


class Scanner:
    def __init__(self, store: Store, limits: ScanLimits | None = None):
        self.store = store
        self.limits = limits or ScanLimits()

    def run(self, job: str, root: Path | None = None, recursive=False):
        """Capture every supported file placed directly in Library/Inbox, or in a watched folder (root), whose
        subfolders are read too when recursive. Source files are read, never written, moved or deleted."""
        self.store.job_state(job, "running")
        try:
            self._run(job, root or self.store.library.inbox, recursive and root is not None, root is None)
        except (PathError, RuntimeError) as exc:
            self.store.job_state(job, "failed", str(exc))
        except Exception as exc:
            # Do not log document contents or platform error paths to console (log_failure keeps only the class and code frames).
            log_failure(log, "inbox scan", exc, job=job)
            self.store.job_state(job, "failed", "Scan stopped unexpectedly. Completed captures are retained; check access/storage and rescan.")

    def _run(self, job: str, inbox: Path, recursive=False, is_inbox=True):
        place = "Library/Inbox" if is_inbox else "The watched folder"
        safe_path(inbox)
        if not inbox.is_dir():
            self.store.job_state(job, "failed", f"{place} is unavailable. No files marked missing.")
            return
        candidates = []
        complete, issues, count = True, False, 0
        folders = [inbox]
        while folders:
            folder = folders.pop()
            try:
                with os.scandir(folder) as listing:
                    entries = [Path(entry.path) for entry in listing]
            except OSError:
                where = folder.relative_to(inbox).as_posix() if folder != inbox else ""
                self.store.event(job, where, "unavailable", f"Cannot list {place if folder == inbox else 'this folder'}. No missing-file inference for this scan.")
                complete, issues = False, True
                continue
            for path in entries:
                count += 1
                if count > self.limits.max_entries:
                    raise RuntimeError(f"Scan entry limit reached. Move some files out of {'Inbox' if is_inbox else 'the watched folder'} and scan again.")
                relative = path.relative_to(inbox).as_posix()
                try:
                    if is_link(path):
                        self.store.observe(job, relative, "rejected")
                        self.store.event(job, relative, "rejected", "Links and reparse points are not followed.")
                        complete, issues = False, True
                        continue
                    # Windows DirEntry.stat omits device/inode identity.
                    # Path.stat matches fstat on our later capture handle.
                    info = path.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        if recursive:
                            folders.append(path)
                        elif is_inbox:
                            self.store.event(job, relative, "invalid_folder", "Place Inbox documents directly in Library/Inbox, not subfolders.")
                            issues = True
                        continue
                    # Previously captured bytes remain available but are not
                    # represented as the verified current file until capture succeeds.
                    self.store.observe(job, relative, "not_captured")
                    if not stat.S_ISREG(info.st_mode):
                        self.store.event(job, relative, "rejected", "Only regular files are supported.")
                        issues = True
                        continue
                    lower = path.name.lower()
                    if lower.startswith("~$") or (not is_inbox and lower.startswith(".")) or lower.endswith((".tmp", ".part", ".crdownload", ".download")):
                        self.store.event(job, relative, "ignored", "Temporary/download/lock file.")
                        continue
                    if extension(path) not in SUPPORTED:
                        # A watched folder holds other files too; only the Inbox reports them as needing attention.
                        self.store.event(job, relative, "unsupported", "Capture supports " + ", ".join(sorted(SUPPORTED)) + " files. No contents were read.")
                        issues = issues or is_inbox
                        continue
                    if not 0 < info.st_size <= self.limits.max_file_bytes:
                        self.store.event(job, relative, "rejected", "Empty file or file exceeds the capture size limit.")
                        issues = True
                        continue
                    candidates.append((path, relative, info))
                except (OSError, PathError):
                    self.store.observe(job, relative, "unavailable")
                    self.store.event(job, relative, "unavailable", "Cannot inspect this entry. Check permissions or file locks.")
                    complete, issues = False, True
        # One stability interval for the inventory, not one delay per document.
        if candidates:
            time.sleep(self.limits.stability_seconds)
        for path, relative, before in candidates:
            try:
                self.capture(job, path, relative, before)
            except (OSError, PathError) as exc:
                self.store.observe(job, relative, "unavailable")
                message = str(exc) if isinstance(exc, CaptureError) else "File is locked, changed, or inaccessible; or storage is unavailable. Rescan after checking it."
                self.store.event(job, relative, "deferred", message)
                issues = True
        if complete:
            self.store.mark_missing(job)
        self.store.job_state(job, "partial" if issues else "completed")

    def capture(self, job, path, relative, before):
        safe_path(path)
        if signature(before) != signature(path.stat()):
            raise CaptureError("File changed during the stability interval; rescan when copying is finished.")
        capture_id = uuid.uuid4().hex
        temp = safe_path(self.store.work / (capture_id + ".part"))
        prepared = False
        try:
            hasher = hashlib.sha256()
            size = 0
            with source_reader(path) as reader:
                if signature(before) != signature(os.fstat(reader.fileno())):
                    raise CaptureError("File changed before capture; rescan.")
                with open(temp, "xb") as writer:
                    while chunk := reader.read(1024 * 1024):
                        size += len(chunk)
                        if size > self.limits.max_file_bytes:
                            raise CaptureError("File exceeds the capture size limit.")
                        writer.write(chunk)
                        hasher.update(chunk)
                    writer.flush()
                    os.fsync(writer.fileno())
                if size != before.st_size or signature(before) != signature(os.fstat(reader.fileno())):
                    raise CaptureError("File changed while being captured; rescan.")
                # Windows denies concurrent writers; rehash also protects other OSes.
                reader.seek(0)
                if hashlib.file_digest(reader, "sha256").hexdigest() != hasher.hexdigest():
                    raise CaptureError("File contents changed while being captured; rescan.")
                safe_path(path)
                if signature(before) != signature(path.stat()):
                    raise CaptureError("The source file changed while being captured; rescan.")
            digest = hasher.hexdigest()
            if not self.store.blob_path(digest).exists() and self.store.used_bytes() + size > self.limits.max_store_bytes:
                raise CaptureError("Managed evidence quota reached (5 GiB by default); the source file was left untouched.")
            self.store.prepare(capture_id, job, relative, digest, size, before.st_mtime_ns)
            prepared = True
            self.store.publish(capture_id)
            try:
                self.store.library.ensure_capture(relative, digest, self.store.job_root(job))
            except (ValueError, OSError, RuntimeError):
                self.store.event(job, relative, "organization_failed", "Captured evidence is safe; library organization needs attention or retry.", digest)
        finally:
            if not prepared:
                temp.unlink(missing_ok=True)


class CaptureError(OSError):
    pass
