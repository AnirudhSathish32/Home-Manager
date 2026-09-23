"""Configuration, exclusive worker lifecycle, and persistent scan ownership."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import threading

from .paths import DirectoryLock, PathError, safe_path, validate_roots
from .scanner import Scanner, ScanLimits
from .storage import Store
from .receipt_service import ReceiptService
from .receipt_batch import ReceiptBatches
from .vision import VisionConfig
from .organization import OrganizationService


def default_control_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HomeManager"
    return Path.home() / ".local" / "share" / "home-manager"


class Manager:
    def __init__(self, control: Path, limits: ScanLimits | None = None):
        self.control = safe_path(control)
        self.lock = DirectoryLock(self.control)
        self.settings_file = safe_path(self.control / "settings.json")
        self.mutex = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="document-scan")
        self.future = None
        self.store = None
        self.source = None
        self.receipts = None
        self.batches = None
        self.vision_file = safe_path(self.control / "vision.json")
        self.vision = VisionConfig()
        if self.vision_file.exists():
            try:
                self.vision = VisionConfig.model_validate_json(self.vision_file.read_bytes())
            except (ValueError, OSError):
                pass  # Invalid settings disable vision; no unvalidated endpoint is used.
        self.startup_error = None
        self.limits = limits or ScanLimits()
        if self.settings_file.exists():
            try:
                config = json.loads(self.settings_file.read_text(encoding="utf-8"))
                self.configure(config["source_directory"], config["managed_directory"], persist=False)
            except (ValueError, KeyError, OSError):
                self.startup_error = "Saved directories could not be opened. Check their availability or select valid directories."

    def busy(self):
        return self.future is not None and not self.future.done()

    def settings(self):
        return {"source_directory": str(self.source) if self.source else "",
                "managed_directory": str(self.store.root) if self.store else "",
                "configured": self.store is not None, "busy": self.busy(),
                "startup_error": self.startup_error,
                "model_progress": (self.receipts.progress or self.organization.progress) if self.receipts and self.busy() else None,
                "vision": self.vision.model_dump(),
                "receipt_batch": self.batches.latest(self.source) if self.batches else None,
                "max_file_mib": self.limits.max_file_bytes // (1024 * 1024),
                "max_store_gib": self.limits.max_store_bytes // (1024 ** 3)}

    def configure(self, source_value, managed_value, persist=True):
        with self.mutex:
            if self.busy():
                raise RuntimeError("Wait for the active scan or receipt parsing job before changing directories.")
            source, managed = validate_roots(source_value, managed_value, self.control)
            previous = self.store
            store = previous if previous and previous.root == managed else Store(managed)
            try:
                receipts = self.receipts if store is previous else ReceiptService(store)
                if store is not previous:
                    receipts.recover()
                batches = self.batches if store is previous else ReceiptBatches(store, receipts)
                if store is not previous:
                    batches.recover()
                if persist:
                    temp = safe_path(self.control / "settings.tmp")
                    with open(temp, "w", encoding="utf-8") as stream:
                        json.dump({"source_directory": str(source), "managed_directory": str(managed)}, stream)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temp, self.settings_file)
            except BaseException:
                if store is not previous:
                    store.close()
                raise
            self.store, self.source, self.startup_error = store, source, None
            self.receipts = receipts
            self.organization = OrganizationService(store, source)
            self.organization.recover()
            self.batches = batches
            if previous and previous is not store:
                previous.close()
            return self.settings()

    def start(self, year=None, month=None):
        with self.mutex:
            if self.store is None:
                raise PathError("Configure source and managed-data directories first.")
            if self.busy():
                raise RuntimeError("A scan or receipt parsing job is already running.")
            # Recheck roots at use time, including replaced/reparse components.
            validate_roots(str(self.source), str(self.store.root), self.control)
            job = self.store.create_job(self.source, year, month)
            self.store.organization_state(job, "queued", "Waiting for capture to finish.")
            self.future = self.executor.submit(self.scan_and_organize, job, year, month)
            return job

    def scan_and_organize(self, job, year, month):
        Scanner(self.store, self.limits).run(job, self.source, year, month)
        if self.store.job(job)["status"] not in ("completed", "partial"):
            self.store.organization_state(job, "not_started", "Capture did not complete. Preserved copies remain available.")
            return
        if not self.vision.model or not self.vision.organize_after_scan:
            self.store.organization_state(job, "not_configured", "Automatic organization is off or no vision model is configured. Documents remain available in Unfiled.")
            return
        try:
            self.store.organization_state(job, "running", "Reading and organizing newly captured images with the local model.")
            batch = self.batches.enqueue(self.source, self.vision, scan_job=job)
            if batch is None:
                self.store.organization_state(job, "not_needed", "No new or changed supported images. Other formats await their readers.")
                return
            self.store.organization_state(job, "running", "Model processing in progress; results appear in the library.", batch)
            self.batches.run(batch)
            state = self.batches.get(batch)["status"]
            self.store.organization_state(job, state, "Organization finished. Review model-assigned folders; failed or unsupported documents remain Unfiled.", batch)
        except Exception:
            self.store.organization_state(job, "failed", "Automatic organization failed. Captures are safe; use Parse and organize to retry.")

    def library_action(self, document_id, expected_hash, action, folder=None):
        with self.mutex:
            if not self.store:
                raise ValueError("Configure directories first.")
            if self.busy():
                raise RuntimeError("Wait for scanning or parsing to finish before changing the library.")
            self.store.library_action(self.source, document_id, expected_hash, action, folder)
            return {"status": action}

    def start_receipt(self, document_id, digest=None, rotation=0, force=False, organize=True):
        with self.mutex:
            if self.store is None:
                raise PathError("Configure directories first.")
            if self.busy():
                raise RuntimeError("Wait for the current scan or receipt parsing job to finish.")
            run_id, created = self.receipts.enqueue(document_id, digest, rotation, force, self.vision, organize)
            if created:
                self.future = self.executor.submit(self.receipts.run, run_id)
            return {"run_id": run_id, "reused": not created}

    def start_organization(self, document_id, digest):
        with self.mutex:
            if not self.store:
                raise ValueError("Configure directories first.")
            if self.busy():
                raise RuntimeError("Wait for the current operation to finish.")
            run_id = self.organization.enqueue(document_id, digest, self.vision)
            self.future = self.executor.submit(self.organization.run, run_id)
            return {"run_id": run_id}

    def configure_vision(self, config):
        with self.mutex:
            if self.busy():
                raise RuntimeError("Wait for the current operation before changing model settings.")
            temp = safe_path(self.control / "vision.tmp")
            with open(temp, "w", encoding="utf-8") as stream:
                stream.write(config.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, self.vision_file)
            self.vision = config
            return config.model_dump()

    def start_receipt_batch(self, force=False):
        with self.mutex:
            if not self.store:
                raise ValueError("Configure directories first.")
            if self.busy():
                raise RuntimeError("A scan or receipt parsing operation is already running.")
            batch = self.batches.enqueue(self.source, self.vision, force)
            self.future = self.executor.submit(self.batches.run, batch)
            return {"batch_id": batch}

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=False)
        if self.store:
            self.store.close()
        self.lock.close()
