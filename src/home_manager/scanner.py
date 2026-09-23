"""D1 discovery and D2 capture. No parsing, OCR, model calls or source writes."""

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import stat
import time
import uuid

from .paths import PathError, is_link, safe_path, signature, source_reader
from .storage import Store


SUPPORTED = {".csv", ".xlsx", ".png", ".jpg", ".jpeg"}


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

    def run(self, job: str, source: Path, year=None, month=None):
        self.store.job_state(job, "running")
        try:
            self._run(job, source, year, month)
        except (PathError, RuntimeError) as exc:
            self.store.job_state(job, "failed", str(exc))
        except Exception:
            # Do not log document contents or platform error paths to console.
            self.store.job_state(job, "failed", "Scan stopped unexpectedly. Completed captures are retained; check access/storage and rescan.")

    def _run(self, job: str, source: Path, year=None, month=None):
        safe_path(source)
        if not source.is_dir():
            self.store.job_state(job, "failed", "Source root is unavailable. No files marked missing.")
            return
        selected = source
        if year is not None:
            selected /= f"{year:04d}"
        if month is not None:
            selected /= f"{month:02d}"
        safe_path(selected)
        if selected.exists() and not selected.is_dir():
            self.store.job_state(job, "failed", "Selected year/month is not a directory. No files marked missing.")
            return
        candidates = []
        complete, issues, count = True, False, 0
        pending = [selected] if selected.exists() else []
        if not pending:
            self.store.event(job, str(selected.relative_to(source)), "absent_folder", "Selected folder does not exist; prior occurrences in this scope will be marked missing.")
        while pending:
            directory = pending.pop()
            try:
                safe_path(directory)
                with os.scandir(directory) as entries:
                    for entry in entries:
                        count += 1
                        if count > self.limits.max_entries:
                            raise RuntimeError("Scan entry limit reached. Select a smaller year/month scope.")
                        path = Path(entry.path)
                        relative = path.relative_to(source).as_posix()
                        try:
                            if is_link(path):
                                self.store.observe(job, source, relative, "rejected")
                                self.store.event(job, relative, "rejected", "Links and reparse points are not followed.")
                                complete, issues = False, True
                                continue
                            # Windows DirEntry.stat omits device/inode identity.
                            # Path.stat matches fstat on our later capture handle.
                            info = path.stat(follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode):
                                parts = path.relative_to(source).parts
                                valid = (len(parts) > 2 or
                                         (len(parts) == 1 and re.fullmatch(r"[1-9][0-9]{3}", parts[0])) or
                                         (len(parts) == 2 and re.fullmatch(r"0[1-9]|1[0-2]", parts[1])))
                                if valid:
                                    pending.append(path)
                                else:
                                    self.store.event(job, relative, "invalid_folder", "Expected YYYY/MM. This folder was not scanned.")
                                    issues = True
                                continue
                            # Previously captured bytes remain available but are not
                            # represented as the verified current source until capture succeeds.
                            self.store.observe(job, source, relative, "not_captured")
                            if not stat.S_ISREG(info.st_mode):
                                self.store.event(job, relative, "rejected", "Only regular files are supported.")
                                issues = True
                                continue
                            lower = path.name.lower()
                            if lower.startswith("~$") or lower.endswith((".tmp", ".part", ".crdownload", ".download")):
                                self.store.event(job, relative, "ignored", "Temporary/download/lock file.")
                                continue
                            parts = path.relative_to(source).parts
                            if len(parts) < 3:
                                self.store.event(job, relative, "invalid_folder", "Place files beneath YYYY/MM.")
                                issues = True
                                continue
                            if path.suffix.lower() not in SUPPORTED:
                                self.store.event(job, relative, "unsupported", "Capture supports CSV, XLSX, PNG, JPG and JPEG. No contents were read.")
                                issues = True
                                continue
                            if not 0 < info.st_size <= self.limits.max_file_bytes:
                                self.store.event(job, relative, "rejected", "Empty file or file exceeds the capture size limit.")
                                issues = True
                                continue
                            candidates.append((path, relative, info, int(parts[0]), int(parts[1])))
                        except (OSError, PathError):
                            self.store.observe(job, source, relative, "unavailable")
                            self.store.event(job, relative, "unavailable", "Cannot inspect this entry. Check permissions or file locks.")
                            complete, issues = False, True
            except OSError:
                relative = directory.relative_to(source).as_posix()
                self.store.event(job, relative, "unavailable", "Cannot enumerate directory. No missing-file inference for this scan.")
                complete, issues = False, True
        # One stability interval for the inventory, not one delay per document.
        if candidates:
            time.sleep(self.limits.stability_seconds)
        for path, relative, before, file_year, file_month in candidates:
            try:
                self.capture(job, source, path, relative, before, file_year, file_month)
            except (OSError, PathError) as exc:
                self.store.observe(job, source, relative, "unavailable")
                message = str(exc) if isinstance(exc, CaptureError) else "File is locked, changed, or inaccessible; or storage is unavailable. Rescan after checking it."
                self.store.event(job, relative, "deferred", message)
                issues = True
        if complete:
            self.store.mark_missing(job, source, year, month)
        self.store.job_state(job, "partial" if issues else "completed")

    def capture(self, job, source, path, relative, before, year, month):
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
                    raise CaptureError("Source path changed while being captured; rescan.")
            digest = hasher.hexdigest()
            if not self.store.blob_path(digest).exists() and self.store.used_bytes() + size > self.limits.max_store_bytes:
                raise CaptureError("Managed evidence quota reached (5 GiB by default); source left untouched.")
            self.store.prepare(capture_id, job, source, relative, year, month, digest, size, before.st_mtime_ns)
            prepared = True
            self.store.publish(capture_id)
        finally:
            if not prepared:
                temp.unlink(missing_ok=True)


class CaptureError(OSError):
    pass
