"""Configuration, independent work queues, and persistent scan ownership.

Capture (filesystem) and inference (GPU/model, concurrency 1) run on separate
queues. Library and database actions run on the request thread and never wait
for model generation; organization is serialized by the managed library itself.
"""

from concurrent.futures import Future, ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import threading
import uuid

from .assistant import AssistantService
from .checkin import CheckinService
from .warranty import WarrantyService
from .backup import BackupService, restore_backup
from .extraction import ExtractionService
from .finance import HouseholdConfig
from .laya_runtime import LayaRuntime
from .finance_tools import FinanceTools
from .formats import SUPPORTED, extension
from .item_resolver import ItemResolver
from .jobs import QUEUES, Cancelled, Work
from .model_client import check_connection
from .paths import DirectoryLock, PathError, safe_path, separate_folder, validate_managed, write_atomic
from .scanner import Scanner, ScanLimits
from .share import export_share, open_share
from .storage import Store, now
from .receipt_service import ReceiptService
from .receipt_batch import ReceiptBatches
from .vision import VisionConfig
from .organization import OrganizationService
from .reasoning import ReasoningConfig, ReasoningService
from .reconcile import Reconciler
from .reviewer import ReviewerConfig, review

# Settings attribute -> (file name, model). Invalid saved settings fall back to
# defaults, which disable that model; no unvalidated endpoint is ever used.
# Capture-queue work that the user may cancel; scans themselves are not interruptible.
CANCELLABLE_CAPTURE = ("backup", "restore")
MODEL_SETTINGS = {"vision": ("vision.json", VisionConfig), "reasoning_config": ("reasoning.json", ReasoningConfig),
                  "reviewer_config": ("reviewer.json", ReviewerConfig), "household": ("household.json", HouseholdConfig)}


def default_control_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HomeManager"
    return Path.home() / ".local" / "share" / "home-manager"


def _settle(source, target):
    if source.exception() is not None:
        target.set_exception(source.exception())
    else:
        target.set_result(source.result())


class Manager:
    def __init__(self, control: Path, limits: ScanLimits | None = None):
        self.control = safe_path(control)
        self.lock = DirectoryLock(self.control)
        self.settings_file = safe_path(self.control / "settings.json")
        # In-process Laya (advisory scoring/classification); generative models stay on loopback LM Studio.
        self.laya = LayaRuntime(self.control / "models" / "laya")
        self.mutex = threading.RLock()
        self.executors = {queue: ThreadPoolExecutor(max_workers=1, thread_name_prefix=queue) for queue in QUEUES}
        self.pending = {queue: [] for queue in QUEUES}  # (future, work) not yet finished
        self.future = None  # Completion of the most recently started operation, including follow-ups.
        self.store = self.receipts = self.batches = self.reasoning = self.organization = None
        self.extractions = self.ledger = self.reconciler = self.tools = self.backups = self.assistant = self.items = self.checkins = self.warranties = None
        self.restores = {}  # Restore outcomes for this process; a restore may run with no library open.
        self.shares = {}  # Share exports for this process.
        # A shared library opened for this process only: never saved to settings, deleted when it ends.
        self.session = self.session_opening = None
        self.sessions = safe_path(self.control / "sessions")
        if self.sessions.exists():
            shutil.rmtree(self.sessions)  # Temporary copies left by a session the app did not end.
        for attribute, (name, model) in MODEL_SETTINGS.items():
            path = safe_path(self.control / name)
            try:
                setattr(self, attribute, model.model_validate_json(path.read_bytes()) if path.exists() else model())
            except (ValueError, OSError):
                setattr(self, attribute, model())
        self.startup_error = None
        self.limits = limits or ScanLimits()
        self.stop_monitor = threading.Event()
        self.inbox_seen = self.inbox_candidate = None
        if self.settings_file.exists():
            try:
                config = json.loads(self.settings_file.read_text(encoding="utf-8"))
                self.configure(config["managed_directory"], persist=False)  # Older files also name a source folder; it is ignored.
            except (ValueError, KeyError, OSError):
                self.startup_error = "Saved directories could not be opened. Check their availability or select valid directories."
        self.monitor = threading.Thread(target=self.watch_inbox, name="inbox-monitor", daemon=True)
        self.monitor.start()

    # Work queues -------------------------------------------------------------

    def submit(self, queue, kind, label, fn, *args):
        """Run fn(*args, work) on a queue. The work record is visible and cancellable until done."""
        work = Work(queue, kind, label, sink=self.store.record_model_run if self.store else None)

        def run():
            work.status, work.started_at = "running", now()
            try:
                fn(*args, work)
                work.status = "cancelled" if work.cancelled else "finished"
            except BaseException:
                work.status = "failed"
                raise
            finally:
                work.progress = None

        with self.mutex:
            future = self.executors[queue].submit(run)
            self.pending[queue] = [item for item in self.pending[queue] if not item[0].done()] + [(future, work)]
        return future

    def busy(self, queue=None):
        with self.mutex:
            return any(not future.done() for name in ([queue] if queue else QUEUES) for future, _ in self.pending[name])

    def activity(self):
        with self.mutex:
            return [work.summary() for name in QUEUES for future, work in self.pending[name] if not future.done()]

    def cancel(self, work_id=None):
        """Cancel running and queued model work, backups and restores (or one item). Scans are not interruptible."""
        with self.mutex:
            targets = [work for queue in QUEUES for future, work in self.pending[queue] if not future.done() and work_id in (None, work.id)
                       and (queue == "inference" or work.kind in CANCELLABLE_CAPTURE)]
        if work_id and not targets:
            raise ValueError("No cancellable work with that ID. It may already have finished.")
        for work in targets:
            work.cancel()
        return {"cancelled": [work.id for work in targets]}

    def require(self, queue=None, message=""):
        """Called under self.mutex before starting work or changing shared state."""
        if self.store is None:
            raise PathError("Choose a library folder first.")
        if queue is not False and self.busy(queue):
            raise RuntimeError(message)
        return self.store

    # Inbox monitor -----------------------------------------------------------

    def watch_inbox(self):
        while not self.stop_monitor.wait(3):
            self.check_inbox()

    def check_inbox(self):
        with self.mutex:
            if not self.store or self.busy("capture"):
                return
            try:
                snapshot = []
                for index, path in enumerate(safe_path(self.store.library.inbox).iterdir()):
                    if index >= self.limits.max_entries:
                        break
                    if extension(path) in SUPPORTED and safe_path(path).is_file():
                        info = path.stat()
                        snapshot.append((path.name, info.st_size, info.st_mtime_ns))
                snapshot = tuple(sorted(snapshot))
                if snapshot != self.inbox_candidate:
                    self.inbox_candidate = snapshot
                    return  # Two matching observations before scheduling capture.
                if snapshot != self.inbox_seen:
                    self.inbox_seen = snapshot
                    if snapshot:
                        self.start_inbox()
            except (OSError, ValueError, RuntimeError):
                return

    # Settings ----------------------------------------------------------------

    def settings(self):
        activity = self.activity() if self.store else []
        progress = next((item["progress"] for item in activity if item["queue"] == "inference" and item["progress"]), None)
        return {"managed_directory": str(self.session["home"] if self.session else self.store.root) if self.store else "",
                "session": {key: value for key, value in self.session.items() if key != "home"} if self.session else None,
                "session_opening": self.session_opening,
                "inbox_directory": str(self.store.library.inbox) if self.store else "",
                "configured": self.store is not None, "busy": self.busy(),
                "capture_busy": self.busy("capture"), "inference_busy": self.busy("inference"),
                "activity": activity, "startup_error": self.startup_error, "model_progress": progress,
                "vision": self.vision.model_dump(),
                "reasoning": self.reasoning_config.model_dump(),
                "reviewer": self.reviewer_config.model_dump(),
                "household": self.household.model_dump(), "laya": self.laya.status(),
                "receipt_batch": self.batches.latest() if self.batches else None,
                "max_file_mib": self.limits.max_file_bytes // (1024 * 1024),
                "max_store_gib": self.limits.max_store_bytes // (1024 ** 3)}

    def configure(self, managed_value, persist=True):
        with self.mutex:
            if self.session:
                raise RuntimeError("End the shared-library session before changing the library folder.")
            if self.busy():
                raise RuntimeError("Wait for active scans and model work before changing the library folder.")
            return self.open_library(validate_managed(managed_value, self.control), persist)

    def open_library(self, managed, persist):
        """Switch to an already validated library folder. Called under self.mutex with no work running."""
        with self.mutex:
            previous = self.store
            if previous and previous.root == managed:
                store, receipts, reasoning, batches, extractions = previous, self.receipts, self.reasoning, self.batches, self.extractions
            else:
                store = Store(managed)
            try:
                if store is not previous:
                    receipts = ReceiptService(store)
                    reasoning = ReasoningService(store, receipts)
                    batches = ReceiptBatches(store, receipts)
                    extractions = ExtractionService(store, receipts, self.laya)
                    for service in (receipts, reasoning, batches, extractions):
                        service.recover()
                if persist:
                    write_atomic(self.settings_file, json.dumps({"managed_directory": str(managed)}))
            except BaseException:
                if store is not previous:
                    store.close()
                raise
            self.store, self.startup_error = store, None
            self.inbox_seen = self.inbox_candidate = None
            self.receipts, self.reasoning, self.batches = receipts, reasoning, batches
            self.extractions, self.ledger = extractions, extractions.ledger
            self.reconciler, self.tools = Reconciler(store), FinanceTools(store)
            self.backups, self.assistant = BackupService(store), AssistantService(store, self.tools)
            self.organization, self.items, self.checkins = OrganizationService(store), ItemResolver(store), CheckinService(store)
            self.warranties = WarrantyService(store, self.items.web)
            for service in (self.organization, self.reconciler, self.backups, self.assistant, self.items, self.checkins, self.warranties):
                service.recover()
            if previous and previous is not store:
                previous.close()
            return self.settings()

    def configure_model(self, attribute, config):
        with self.mutex:
            if self.busy("inference"):
                raise RuntimeError("Wait for model work to finish, or cancel it, before changing model settings.")
            write_atomic(safe_path(self.control / MODEL_SETTINGS[attribute][0]), config.model_dump_json())
            setattr(self, attribute, config)
            return config.model_dump()

    def configure_vision(self, config):
        return self.configure_model("vision", config)

    def configure_reasoning(self, config):
        return self.configure_model("reasoning_config", config)

    def configure_reviewer(self, config):
        return self.configure_model("reviewer_config", config)

    def configure_household(self, config):
        with self.mutex:  # Not a model setting: never waits for model work.
            write_atomic(safe_path(self.control / MODEL_SETTINGS["household"][0]), config.model_dump_json())
            self.household = config
            return config.model_dump()

    # Capture and its model follow-up ------------------------------------------

    def start_inbox(self):
        with self.mutex:
            store = self.require("capture", "Wait for the current scan before scanning Inbox.")
            job = store.create_job()
            self.future = self.pipeline(job)
            return job

    def pipeline(self, job):
        """Capture on the capture queue, then transcription on the inference queue."""
        done, follow = Future(), {}

        def capture(work):
            if self.capture(job):
                follow["future"] = self.submit("inference", "transcription", "Text extraction for newly captured documents", self.process_scan, job)

        def settle(outer):
            inner = follow.get("future")
            if outer.exception() is not None or inner is None:
                _settle(outer, done)
            else:
                inner.add_done_callback(lambda future: _settle(future, done))

        self.submit("capture", "capture", "Inbox capture", capture).add_done_callback(settle)
        return done

    def capture(self, job):
        Scanner(self.store, self.limits).run(job)
        if self.store.job(job)["status"] not in ("completed", "partial"):
            self.store.organization_state(job, "not_started", "Capture did not complete. Preserved copies remain available.")
            return False
        if not {"captured", "duplicate", "new_version"} & set(self.store.job(job)["counts"]):
            # A rescan that found nothing new (the watcher sees files still waiting in Inbox) queues no model work.
            self.store.organization_state(job, "not_needed", "Nothing new was captured.")
            return False
        if not self.vision.organize_after_scan:
            self.store.organization_state(job, "not_configured", "Automatic text extraction is off or no vision model is configured. Documents remain available in Unfiled.")
            return False
        self.store.organization_state(job, "queued", "Capture finished. Waiting for the model queue.")
        return True

    def process_scan(self, job, work):
        try:
            self.store.organization_state(job, "running", "Transcribing newly captured images with the local model.")
            batch = self.batches.enqueue(self.vision, scan_job=job)
            if batch is None:
                self.store.organization_state(job, "not_needed", "No new or changed images or PDFs. Other formats use their own readers.")
                return
            self.store.organization_state(job, "running", "Model processing in progress; results appear in the library.", batch)
            self.batches.run(batch, work)
            work.check()
            failures = 0
            if self.reasoning_config.model:
                with self.store.connection() as db:
                    items = list(db.execute("SELECT document_id,run_id FROM receipt_batch_items WHERE batch_id=?", (batch,)))
                for item in items:
                    work.check()
                    if self.receipts.get(item["run_id"])["status"] not in ("succeeded", "partial"):
                        continue
                    try:
                        extraction, created = self.extractions.enqueue(item["document_id"], item["run_id"], self.reasoning_config,
                                                                       home_currency=self.household.home_currency, laya=self.laya.installed())
                        (self.extract_and_file if created else self.file_extraction)(item["document_id"], extraction, work)
                        if self.extractions.get(extraction)["status"] != "succeeded":
                            failures += 1
                    except (ValueError, OSError, RuntimeError):
                        failures += 1
                work.check()
            state = "partial" if failures else self.batches.get(batch)["status"]
            self.store.organization_state(job, state, "Processing finished. Cited classification and extraction determine filing; unresolved documents remain available for review.", batch)
        except Cancelled:
            self.store.organization_state(job, "cancelled", "Model processing was cancelled. Captures and completed results are safe; use Extract text from all images to resume.")
        except Exception:
            self.store.organization_state(job, "failed", "Automatic text extraction failed. Captures are safe; use Extract text from all images to retry.")

    # Library and model operations ----------------------------------------------

    def library_action(self, document_id, expected_hash, action, folder=None):
        # Holds the mutex (not a queue) so directories cannot switch mid-move; model work continues.
        with self.mutex:
            self.require(False).library_action(document_id, expected_hash, action, folder)
            return {"status": action}

    def empty_trash(self):
        from .trash import empty
        with self.mutex:
            store = self.require(None, "Wait for running work to finish before emptying Trash.")
            with store.library.lock:
                return empty(store)

    def start_organization(self, document_id, digest):
        with self.mutex:
            self.require(False)
            return {"run_id": self.organization.enqueue(document_id, digest)}

    def import_transactions(self, document_id, account_id, mapping=None, digest=None):
        """Deterministic and fast; runs on the request thread, never waiting for model work."""
        with self.mutex:
            self.require(False)
        result = self.ledger.import_transactions(document_id, account_id, mapping, digest)
        return {**result, "reconciliation": self.reconciler.run("import")}

    def start_receipt(self, document_id, digest=None, rotation=0, force=False):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it first.")
            run_id, created = self.receipts.enqueue(document_id, digest, rotation, force, self.vision)
            if created:
                self.future = self.submit("inference", "transcription", "Text extraction", self.receipts.run, run_id)
            return {"run_id": run_id, "reused": not created}

    def start_receipt_batch(self, force=False, document_ids=None):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it first.")
            batch = self.batches.enqueue(self.vision, force, document_ids=document_ids)
            label = "Text extraction for all images and PDFs" if document_ids is None else f"Text extraction for {len(document_ids)} selected documents"
            self.future = self.submit("inference", "transcription", label, self.batches.run, batch)
            return {"batch_id": batch}

    def start_reasoning(self, document_id, parse_run_id, force=False):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before starting financial analysis.")
            run_id, created = self.reasoning.enqueue(document_id, parse_run_id, self.reasoning_config, force)
            self.future = self.submit("inference", "reasoning", "Financial analysis",
                                      self.reason_and_file if created else self.file_saved_analysis, document_id, run_id)
            return {"run_id": run_id, "reused": not created}

    def start_extraction(self, document_id, parse_run_id, force=False):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before extracting to the ledger.")
            # The independent check runs on every extraction whenever Laya is installed.
            run_id, created = self.extractions.enqueue(document_id, parse_run_id, self.reasoning_config, force, self.household.home_currency,
                                                       self.laya.installed())
            self.future = self.submit("inference", "extraction", "Ledger extraction",
                                      self.extract_and_file if created else self.file_extraction, document_id, run_id)
            return {"run_id": run_id, "reused": not created}

    def extract_and_file(self, document_id, run_id, work):
        self.extractions.run(run_id, work)
        publication = self.extractions.get(run_id)["publication"] or {}
        if publication.get("status") == "published":
            self.reconciler.run("extraction")
        self.file_extraction(document_id, run_id, work)
        if publication.get("record_type") == "receipt" and publication.get("status") == "published":
            self.identify_items(publication["id"], work)

    def identify_items(self, receipt_id, work):
        """Automatic item identification after a receipt is recorded (docs/warranties-assistant-processing.md §2).
        Runs in the same model job; every result is still a proposal in Review. Never fails the extraction."""
        if not self.household.auto_identify_items:
            return
        try:
            run_id = self.items.enqueue(receipt_id, self.reasoning_config)
        except ValueError:
            return  # Every line already has a proposal or a product, or the receipt has no lines.
        work.check()
        self.items.run(run_id, self.reasoning_config, work)

    def file_extraction(self, document_id, run_id, work=None):
        run = self.extractions.get(run_id)
        if run["status"] != "succeeded":
            return
        kind, merchant, dated = self.extractions.filing_identity(run)
        try:
            self.store.library.file_classified(document_id, self.receipts.get(run["parse_run_id"])["blob_hash"], kind, merchant, dated,
                                               "Filed from cited classification and extraction.")
        except (ValueError, OSError, RuntimeError):
            pass  # Filing intents retain their error; the extraction remains available.

    def reason_and_file(self, document_id, run_id, work):
        self.reasoning.run(run_id, work)
        run = self.reasoning.get(run_id)
        if run["status"] == "succeeded" and self.reviewer_config.enabled:
            with self.store.connection() as db:
                db.execute("INSERT OR REPLACE INTO analysis_reviews VALUES(?,?,'running',NULL,NULL)", (run_id, self.reviewer_config.model_dump_json()))
            status, result, error = "failed", None, "Independent review failed. Analysis remains unreviewed."
            try:
                with work.attribute("review", run_id, "financial-review-v1"):
                    result = json.dumps(review(self.reviewer_config, run["result"], self.receipts.get(run["parse_run_id"])["result"], work, self.laya))
                status, error = "succeeded", None
            except Cancelled as exc:
                status, error = "cancelled", str(exc)
            except Exception:
                pass
            with self.store.connection() as db:
                db.execute("UPDATE analysis_reviews SET status=?,result_json=?,error=? WHERE reasoning_run_id=?", (status, result, error, run_id))
        self.file_saved_analysis(document_id, run_id, work)

    def file_saved_analysis(self, document_id, run_id, work=None):
        try:
            self.store.library.file_analysis(document_id, self.reasoning.get(run_id))
        except (ValueError, OSError, RuntimeError):
            pass  # Filing intents retain their error; valid financial analysis remains available.

    def correct_record(self, record_type, record_id, changes):
        """A user correction, then a reconciliation pass: dates and merchants decide matches and spending months."""
        with self.mutex:
            self.require(False)
        record = self.ledger.correct(record_type, record_id, changes)
        return {"record": record, "reconciliation": self.reconciler.run("correction")}

    # Models, backups, restores and questions -----------------------------------------

    @staticmethod
    def test_model_connection(config):
        """Read-only check of a loopback model endpoint; independent of any queue."""
        return check_connection(config)

    def start_backup(self, destination_value):
        with self.mutex:
            if self.session:
                raise RuntimeError("You are viewing a shared library. End the session to back up your own library.")
            store = self.require("capture", "Wait for the current scan to finish before backing up.")
            destination = separate_folder(destination_value, self.control, (store.root,))
            if not destination.is_dir():
                raise PathError("Choose an existing folder for the backup.")
            backup_id = self.backups.begin(destination)
            self.future = self.submit("capture", "backup", "Backup to a separate folder", self.backups.run, backup_id, destination)
            return {"backup_id": backup_id}

    def start_restore(self, backup_value, target_value):
        """Verify a backup and rebuild it as a new library folder. The open library is never touched."""
        with self.mutex:
            if self.busy("capture"):
                raise RuntimeError("Wait for the current scan or backup to finish before restoring.")
            open_folders = (self.store.root,) if self.store else ()
            backup = separate_folder(backup_value, self.control, open_folders)
            target = separate_folder(target_value, self.control, (*open_folders, backup))
            restore_id = uuid.uuid4().hex
            record = self.restores[restore_id] = {"id": restore_id, "status": "running", "backup": str(backup), "target": str(target),
                                                  "started_at": now(), "finished_at": None, "result": None, "error": None}

            def run(work):
                try:
                    record.update(status="succeeded", result=restore_backup(backup, target, work))
                except Cancelled:
                    record.update(status="cancelled", error="Cancelled by the user. Delete the partly restored folder before using it again.")
                except (ValueError, OSError) as exc:
                    record.update(status="failed", error=str(exc))
                finally:
                    record["finished_at"] = now()

            self.future = self.submit("capture", "restore", "Restore from backup", run)
            return {"restore_id": restore_id}

    def restore(self, restore_id):
        if restore_id not in self.restores:
            raise ValueError("Restore not found. Restores are tracked until Home Manager restarts.")
        return self.restores[restore_id]

    def start_assistant(self, question, context=None):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before asking a question.")
            run_id = self.assistant.enqueue(question, self.reasoning_config, context)
            self.future = self.submit("inference", "assistant", "Answering a question", self.assistant.run, run_id, self.reasoning_config)
            return {"run_id": run_id}

    def start_item_resolution(self, receipt_id):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before identifying receipt items.")
            run_id = self.items.enqueue(receipt_id, self.reasoning_config)
            self.future = self.submit("inference", "item_resolution", "Identifying receipt items", self.items.run, run_id, self.reasoning_config)
            return {"run_id": run_id}

    def start_warranty_lookup(self, lot_id):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before looking up a warranty.")
            run_id = self.warranties.enqueue(lot_id, self.reasoning_config)
            self.future = self.submit("inference", "warranty_lookup", "Looking up a warranty", self.warranties.run, run_id, self.reasoning_config)
            return {"run_id": run_id}

    def start_checkin_text(self, answer):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it, or answer with the buttons.")
            weekday = self.household.checkin_weekday
            run_id = self.checkins.enqueue(answer, weekday, self.reasoning_config)
            self.future = self.submit("inference", "checkin_text", "Reading your check-in answer", self.checkins.run, run_id, self.reasoning_config, weekday)
            return {"run_id": run_id}

    # Sharing ------------------------------------------------------------------

    def start_share_export(self, destination_value, passphrase, label):
        """Encrypt this library into one .hmshare file. Only reads the library."""
        with self.mutex:
            if self.session:
                raise RuntimeError("You are viewing a shared library. End the session to share your own library.")
            store = self.require(None, "Wait for running work to finish before sharing.")
            destination = separate_folder(destination_value, self.control, (store.root,))
            if not destination.is_dir():
                raise PathError("Choose an existing folder for the share file.")
            from .share import check_passphrase
            check_passphrase(passphrase)
            share_id = uuid.uuid4().hex
            record = self.shares[share_id] = {"id": share_id, "status": "running", "started_at": now(), "finished_at": None, "result": None, "error": None}

            def run(work):
                try:
                    record.update(status="succeeded", result=export_share(store, destination, passphrase, label, work))
                except Cancelled:
                    record.update(status="cancelled", error="Cancelled by the user.")
                except (ValueError, OSError) as exc:
                    record.update(status="failed", error=str(exc))
                finally:
                    record["finished_at"] = now()

            self.future = self.submit("capture", "share", "Encrypting a share file", run)
            return {"share_id": share_id}

    def share(self, share_id):
        if share_id not in self.shares:
            raise ValueError("Share not found. Shares are tracked until Home Manager restarts.")
        return self.shares[share_id]

    def start_session(self, share_value, passphrase):
        """Open someone's .hmshare as a temporary library. Your own library is closed, never written."""
        with self.mutex:
            if self.session:
                raise RuntimeError("A shared library is already open. End that session first.")
            if self.store is None:
                raise PathError("Choose your own library folder first; the session returns to it when it ends.")
            if self.busy():
                raise RuntimeError("Wait for running work to finish before opening a shared library.")
            from .paths import local_absolute
            from .share import check_passphrase
            share_file = local_absolute(share_value)
            check_passphrase(passphrase)
            session_id = uuid.uuid4().hex
            target = safe_path(self.sessions / session_id / "library")
            opening = self.session_opening = {"id": session_id, "status": "running", "error": None}
            home = self.store.root

            def run(work):
                try:
                    result = open_share(share_file, passphrase, target, work)
                    with self.mutex:
                        self.open_library(target, persist=False)
                        self.session = {"id": session_id, "label": result["label"], "shared_at": result["shared_at"],
                                        "opened_at": now(), "issues": result["issues"], "home": home}
                    opening.update(status="succeeded")
                except Cancelled:
                    opening.update(status="cancelled", error="Cancelled by the user.")
                except (ValueError, OSError) as exc:
                    opening.update(status="failed", error=str(exc))
                if opening["status"] != "succeeded":
                    shutil.rmtree(self.sessions / session_id, ignore_errors=True)

            self.future = self.submit("capture", "session", "Opening a shared library", run)
            return {"session_id": session_id}

    def end_session(self):
        """Close the shared copy, delete it, and reopen your own library."""
        with self.mutex:
            if not self.session:
                raise ValueError("No shared library is open.")
            if self.busy():
                raise RuntimeError("Wait for running work to finish, or cancel it, before ending the session.")
            session = self.session
            self.open_library(session["home"], persist=False)  # Closes the shared copy.
            self.session = self.session_opening = None
            shutil.rmtree(safe_path(self.sessions / session["id"]), ignore_errors=True)
            return self.settings()

    def close(self):
        self.stop_monitor.set()
        self.monitor.join(timeout=5)
        for queue in QUEUES:  # Capture first: it may still enqueue inference follow-ups.
            self.executors[queue].shutdown(wait=True, cancel_futures=False)
        if self.store:
            self.store.close()
        if self.session:
            shutil.rmtree(self.sessions / self.session["id"], ignore_errors=True)
        self.lock.close()
