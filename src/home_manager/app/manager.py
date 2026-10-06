"""Configuration, independent work queues, and persistent scan ownership.

Capture (filesystem) and inference (GPU/model, concurrency 1) run on separate
queues. Library and database actions run on the request thread and never wait
for model generation; organization is serialized by the managed library itself.
"""

from concurrent.futures import Future, ThreadPoolExecutor
import contextlib
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import uuid

from ..core import actor
from ..core.formats import SUPPORTED, extension
from ..core.jobs import QUEUES, Cancelled, Work
from ..core.logs import log_failure
from ..core.money import currency_code, money
from ..core.paths import DirectoryLock, PathError, safe_path, separate_folder, validate_managed, write_atomic
from ..core.trace import ref
from ..documents.extraction import ExtractionService
from ..documents.grouping import Groups
from ..documents.reasoning import ReasoningConfig, ReasoningService
from ..documents.receipt_batch import ReceiptBatches
from ..documents.receipt_service import ReceiptService
from ..documents.reviewer import ReviewerConfig, review
from ..finance import paycheck, paystub, plan_tracking, scenarios
from ..finance.assistant import AssistantService
from ..finance.charts import tax_buckets_svg
from ..finance.checkin import CheckinService
from ..finance.item_categories import ItemCategorizer
from ..finance.ledger import HouseholdConfig
from ..finance.reconcile import Reconciler
from ..finance.recurring_scan import RecurringScan
from ..finance.tax_engine import ENGINES as TAX_ENGINES
from ..finance.tax_engine import readiness as tax_engine_readiness
from ..finance.tools import FinanceTools
from ..household.resolver import ItemResolver
from ..household.tax_tables import TaxTables, TaxTableService
from ..household.warranty import WarrantyService
from ..library import text_index
from ..library.backup import BackupService, restore_backup
from ..library.organization import OrganizationService
from ..library.scanner import ScanLimits, Scanner
from ..library.share import export_share, open_share
from ..library.storage import MigrationError, Store, now
from ..models import residency
from ..models.decisions import DecisionConfig, check_decision_model
from ..models.model_client import check_connection, is_remote, set_token
from ..models.vision import ROLE_ALIASES, ModelComputer, VisionConfig
from ..models.web_lookup import https_get
from .family_client import HubError, list_deliveries, pending_copy, pull_deliveries, push_documents, seal_pending, upload_pending
from .family_hub import PORT as HUB_PORT
from .family_hub import Hub
from .family_sync import FAMILY_MARKER, FamilyFolder, changed_since, read_deliveries, read_invite, write_delivery, write_invite
from .profiles import Profiles, public

# Settings attribute -> (file name, model). Invalid saved settings fall back to
# defaults, which disable that model; no unvalidated endpoint is ever used.
# Capture-queue work that the user may cancel; scans themselves are not interruptible.
CANCELLABLE_CAPTURE = ("backup", "restore")
MODEL_SETTINGS = {"vision": ("vision.json", VisionConfig), "reasoning_config": ("reasoning.json", ReasoningConfig),
                  "reviewer_config": ("reviewer.json", ReviewerConfig), "decision_config": ("decision.json", DecisionConfig)}
# This PC's server or a shared GPU computer. The token has its own file and is never returned by the API.
MODEL_COMPUTER, GPU_TOKEN = "model_computer.json", "gpu_token.txt"
log = logging.getLogger(__name__)
# Before profiles, financial preferences were one file for the computer; the first profile inherits it.
LEGACY_HOUSEHOLD = "household.json"
FAMILY_READ_ONLY = "The family view is read-only. Switch to a member's profile to change records."
PUBLISH_EVERY_SECONDS = 600  # A member's changed library is published to the family at most this often.
FAMILY_TICKS = 20  # Inbox-monitor ticks (3 s each) between family checks.
HUB_BACKOFF_SECONDS = (60, 1800)  # While the family computer can't be reached: first wait, doubling up to the last.
SOURCE_TICKS = 10  # Inbox-monitor ticks between looks at watched folders, which can be large.


def default_control_dir() -> Path:
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HomeManager"
    return Path.home() / ".local" / "share" / "home-manager"


def apply_family_delivery(store, delivery, document):
    """One delivery from the family: a family correction (finance/family_corrections.py), or a routed record
    (finance/family_routing.py)."""
    if delivery.get("type") == "correction":
        from ..finance.family_corrections import apply_correction
        return apply_correction(store, delivery)
    from ..finance.family_routing import apply_delivery
    return apply_delivery(store, delivery, document)


def _settle(source, target):
    if source.exception() is not None:
        target.set_exception(source.exception())
    else:
        target.set_result(source.result())


class Manager:
    def __init__(self, control: Path, limits: ScanLimits | None = None, hub_port=HUB_PORT, hub_loopback=False):
        self.control = safe_path(control)
        self.lock = DirectoryLock(self.control)
        self.settings_file = safe_path(self.control / "settings.json")
        self.mutex = threading.RLock()
        self.tax_refresh = threading.Lock()  # Held while this year's return is worked out again for Home (tax_attention).
        self.tax_checked: dict = {}  # (library, year): the newest record time the return was last worked out again for.
        self.executors = {queue: ThreadPoolExecutor(max_workers=1, thread_name_prefix=queue) for queue in QUEUES}
        self.pending = {queue: [] for queue in QUEUES}  # (future, work) not yet finished
        self.future = None  # Completion of the most recently started operation, including follow-ups.
        self.store = self.receipts = self.batches = self.reasoning = self.organization = None
        self.extractions = self.ledger = self.reconciler = self.tools = self.backups = self.assistant = self.items = self.checkins = self.warranties = None
        self.tax_tables = None
        self.rate_fetch = https_get  # The ECB download; tests replace it.
        self.price_fetch = https_get  # Crypto prices (finance/prices.py); tests replace it.
        self.restores = {}  # Restore outcomes for this process; a restore may run with no library open.
        self.shares = {}  # Share exports for this process.
        # A shared library opened for this process only: never saved to settings, deleted when it ends.
        self.session = self.session_opening = None
        self.sessions = safe_path(self.control / "sessions")
        if self.sessions.exists():
            shutil.rmtree(self.sessions)  # Temporary copies left by a session the app did not end.
        # Model settings as saved; self.vision, self.reasoning_config, self.reviewer_config and self.decision_config are what runs
        # (the same, or pointed at the shared GPU computer by apply_model_computer).
        self.model_settings = {attribute: self.load_setting(name, model) for attribute, (name, model) in MODEL_SETTINGS.items()}
        self.model_computer = self.load_setting(MODEL_COMPUTER, ModelComputer)
        self.apply_model_computer()
        # Profiles: each person's own library, or a family view over its members (app/profiles.py).
        self.profiles = Profiles(self.control)
        self.profile = None  # The active profile record.
        self.family = None  # The open FamilyFolder while a family profile is active.
        self.family_ticks = 0
        # The family hub (app/family_hub.py): listens while this computer holds a family folder, whichever profile is open.
        # hub_loopback is for tests only. hub_retry is this member's backoff while the family computer can't be reached.
        self.hub = Hub(hub_port, hub_loopback)
        self.hub_retry = {"profile": None, "failures": 0, "next": 0.0}
        self.household = HouseholdConfig()
        self.startup_error = None
        self.limits = limits or ScanLimits()
        self.stop_monitor = threading.Event()
        self.inbox_seen = self.inbox_candidate = None
        # Per watched folder, like inbox_seen and inbox_candidate; a folder not yet scanned by this process is rescanned once.
        self.source_seen: dict[tuple[str, int], tuple] = {}
        self.source_candidate: dict[tuple[str, int], tuple] = {}
        self.source_ticks = 0
        self.refresh_hub()  # Before a family view opens, so it shares the hub's open folder.
        try:
            active = self.profiles.active() or self.migrate_settings()
            if active:
                self.activate(active, persist=False)
        except MigrationError as exc:
            self.startup_error = str(exc)  # Written for the user: which step stopped, and where the pre-upgrade copy is.
        except sqlite3.Error as exc:
            log_failure(log, "open library", exc)
            self.startup_error = "The library database could not be opened. Keep the library folder unchanged; details are in the Home Manager log."
        except (ValueError, KeyError, OSError) as exc:
            log_failure(log, "open saved directories", exc)
            self.startup_error = "Saved directories could not be opened. Check their availability or select valid directories."
        self.monitor = threading.Thread(target=self.watch_inbox, name="inbox-monitor", daemon=True)
        self.monitor.start()

    # Work queues -------------------------------------------------------------

    def submit(self, queue, kind, label, fn, *args):
        """Run fn(*args, work) on a queue. The work record is visible and cancellable until done."""
        work = Work(queue, kind, label, sink=self.store.record_model_run if self.store else None)

        def run():
            work.status, work.started_at = "running", now()
            log.info("work started kind=%s queue=%s work=%s", kind, queue, work.id)
            try:
                fn(*args, work)
                work.status = "cancelled" if work.cancelled else "finished"
                log.info("work %s kind=%s work=%s", work.status, kind, work.id)
            except BaseException as exc:
                work.status = "failed"
                if isinstance(exc, Cancelled):
                    log.info("work cancelled kind=%s work=%s", kind, work.id)
                else:
                    log_failure(log, "work", exc, kind=kind, work=work.id)
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
            if self.family:
                raise RuntimeError(FAMILY_READ_ONLY)
            raise PathError("Choose a library folder first.")
        if queue is not False and self.busy(queue):
            raise RuntimeError(message)
        return self.store

    # Inbox monitor -----------------------------------------------------------

    def watch_inbox(self):
        while not self.stop_monitor.wait(3):
            self.check_inbox()
            self.source_ticks += 1
            if self.source_ticks >= SOURCE_TICKS:
                self.source_ticks = 0
                self.check_sources()
            self.family_ticks += 1
            if self.family_ticks >= FAMILY_TICKS:
                self.family_ticks = 0
                try:
                    self.check_family()
                except (ValueError, OSError, RuntimeError):
                    pass  # Reported on the member's status line; the next check tries again.

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

    def source_snapshot(self, source):
        """(relative path, size, mtime) of each supported file in a watched folder, bounded like a scan."""
        root, snapshot, folders = safe_path(Path(source["path"])), [], [Path(source["path"])]
        while folders and len(snapshot) < self.limits.max_entries:
            with os.scandir(folders.pop()) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        if source["recursive"]:
                            folders.append(Path(entry.path))
                    elif entry.is_file(follow_symlinks=False) and extension(Path(entry.name)) in SUPPORTED:
                        info = entry.stat(follow_symlinks=False)
                        snapshot.append((Path(entry.path).relative_to(root).as_posix(), info.st_size, info.st_mtime_ns))
        return tuple(sorted(snapshot))

    def check_sources(self):
        """Scan a watched folder when its files changed and then held still for one more look, and rescan each one
        every rescan_hours (and once after the app starts) so a missed change is still found. One scan per call."""
        with self.mutex:
            if not self.store or self.busy("capture"):
                return
            stale = (datetime.now(timezone.utc) - timedelta(hours=self.household.rescan_hours)).isoformat()
            for source in self.store.sources():
                if not source["enabled"]:
                    continue
                key = (str(self.store.root), source["id"])
                try:
                    snapshot = self.source_snapshot(source)
                except (OSError, ValueError):
                    continue  # Unplugged or locked for now; the scan reports it when it runs.
                due = key not in self.source_seen or not source["last_scan_at"] or source["last_scan_at"] < stale
                if snapshot != self.source_candidate.get(key) and not due:
                    self.source_candidate[key] = snapshot
                    continue  # Two matching observations before scheduling capture.
                self.source_candidate[key] = snapshot
                if due or snapshot != self.source_seen.get(key):
                    try:
                        self.start_source(source["id"])
                        self.source_seen[key] = snapshot
                    except (OSError, ValueError, RuntimeError):
                        pass  # Tried again on the next look.
                    return

    # Settings ----------------------------------------------------------------

    def people(self):
        """Who can be chosen in the who's-here picker (core/actor.py): the profile's owner, the spouse named on their
        latest return, and in a family every member; nobody before a profile is set up."""
        from ..finance.tax_year import TaxYears
        found = [self.profile["name"]] if self.profile else []
        if found and self.store:
            found += TaxYears(self.store).spouse_names()
        if self.family:
            found += [member["name"] for member in self.family.summary()["members"] if member.get("name")]
        return list(dict.fromkeys(found))

    def settings(self):
        activity = self.activity() if self.store else []
        progress = next((item["progress"] for item in activity if item["queue"] == "inference" and item["progress"]), None)
        return {"profile": public(self.profile) if self.profile else None, "profiles": [public(item) for item in self.profiles.all()],
                "people": self.people(),
                "family": self.family.summary() if self.family else None,
                "hub_status": self.hub.status(),  # Where the family hub listens, or why it can't (app/family_hub.py).
                "managed_directory": str(self.session["home"] if self.session else self.store.root) if self.store else "",
                "session": {key: value for key, value in self.session.items() if key != "home"} if self.session else None,
                "session_opening": self.session_opening,
                "inbox_directory": str(self.store.library.inbox) if self.store else "",
                "configured": self.store is not None, "busy": self.busy(),
                "capture_busy": self.busy("capture"), "inference_busy": self.busy("inference"),
                "activity": activity, "startup_error": self.startup_error, "model_progress": progress,
                "vision": self.model_settings["vision"].model_dump(),
                "reasoning": self.model_settings["reasoning_config"].model_dump(),
                "reviewer": self.model_settings["reviewer_config"].model_dump(),
                "decision": self.model_settings["decision_config"].model_dump(),
                "model_computer": self.model_computer_state(),
                "household": self.household.model_dump(),
                "tax_engine": tax_engine_readiness(self.household.tax_engine),  # Whether the return can be worked out here (finance/tax_engine.py).
                "tax_engines": [tax_engine_readiness(slot) for slot in TAX_ENGINES],  # Each slot, for the second-opinion setting.
                "receipt_batch": self.batches.latest() if self.batches else None,
                "max_file_mib": self.limits.max_file_bytes // (1024 * 1024),
                "max_store_gib": self.limits.max_store_bytes // (1024 ** 3)}

    def configure(self, managed_value, persist=True):
        """Choose the active individual profile's library folder. A folder another profile uses switches to that profile;
        with no individual profile active, a new one is made for the folder."""
        with self.mutex:
            if self.session:
                raise RuntimeError("End the shared-library session before changing the library folder.")
            if self.busy():
                raise RuntimeError("Wait for active scans and model work before changing the library folder.")
            managed = validate_managed(managed_value, self.control)
            self.open_library(managed, persist)
            if not persist:
                return self.settings()
            profile = self.profiles.by_folder(managed)
            if profile is None and self.profile and self.profile["kind"] == "individual" and not self.family:
                profile = self.profiles.update(self.profile["id"], folder=str(managed))
            elif profile is None:
                profile = self.profiles.add("My profile", "individual", managed)
            self.leave_family()
            self.use_profile(profile, persist=True)
            return self.settings()

    # Profiles -----------------------------------------------------------------

    def migrate_settings(self):
        """First start with profiles: the library in settings.json becomes the first profile, with the computer's preferences."""
        if not self.settings_file.exists():
            return None
        config = json.loads(self.settings_file.read_text(encoding="utf-8"))  # Older files also name a source folder; it is ignored.
        managed = validate_managed(config["managed_directory"], self.control)
        profile = self.profiles.by_folder(managed) or self.profiles.add("My profile", "individual", managed)
        legacy = safe_path(self.control / LEGACY_HOUSEHOLD)
        if legacy.exists():
            try:
                self.profiles.save_household(profile["id"], HouseholdConfig.model_validate_json(legacy.read_bytes()))
            except (ValueError, OSError):
                pass
        self.profiles.set_active(profile["id"])
        return profile

    def use_profile(self, profile, persist):
        self.profile = profile
        self.household = self.profiles.household(profile["id"])
        if persist:
            self.profiles.set_active(profile["id"])

    def activate(self, profile, persist):
        """Open a profile: its library, or its family folder. Called under self.mutex with no work running."""
        log.info("activating profile kind=%s", profile["kind"])
        with self.mutex:
            if profile["kind"] == "family":
                # The family's own library is its inbox: documents uploaded to the family, each then routed to a person or
                # shared (finance/family_routing.py). Family totals still come only from members' copies.
                held = self.hub.folder(profile["folder"])
                family = held or FamilyFolder(Path(profile["folder"]))
                try:
                    self.open_library(validate_managed(str(family.root / "library"), self.control), persist=False)
                except BaseException:
                    if not held:
                        family.close()
                    raise
                self.leave_family()
                self.family = family
            else:
                self.open_library(validate_managed(profile["folder"], self.control), persist)
                self.leave_family()
            self.use_profile(profile, persist)
            if self.family:
                self.start_family_refresh()
            self.start_rate_refresh()
            return self.settings()

    def switch_profile(self, profile_id):
        with self.mutex:
            if self.session:
                raise RuntimeError("End the shared-library session before switching profiles.")
            if self.busy():
                raise RuntimeError("Wait for active scans and model work before switching profiles.")
            return self.activate(self.profiles.get(profile_id), persist=True)

    def create_profile(self, name, folder_value):
        """A new individual profile with its own library folder. The library is created when the profile is first opened."""
        with self.mutex:
            folder = validate_managed(folder_value, self.control)
            if (folder / FAMILY_MARKER).is_file():  # A family folder removed from this computer's list comes back as the family.
                family = FamilyFolder(folder)
                try:
                    added = public(self.profiles.add(family.data["name"], "family", folder))
                finally:
                    family.close()
                self.refresh_hub()
                return added
            if folder.exists() and any(folder.iterdir()) and not (folder / ".home-manager-store").exists():
                raise PathError("Choose an empty folder or an existing Home Manager library for the new profile.")
            return public(self.profiles.add(name, "individual", folder))

    def rename_profile(self, profile_id, name):
        with self.mutex:
            from .profiles import clean_name
            profile = self.profiles.update(profile_id, name=clean_name(name))
            if self.profile and self.profile["id"] == profile_id:
                self.profile = profile
            return public(profile)

    def remove_profile(self, profile_id):
        """Forget a profile on this computer. Its folder, library and records stay on disk."""
        with self.mutex:
            removed = public(self.profiles.remove(profile_id))
            self.refresh_hub()
            return removed

    def close_library(self):
        """Close the open library, leaving no store (a family profile holds none). Called under self.mutex with no work running."""
        with self.mutex:
            if self.store:
                self.store.close()
            self.store = self.receipts = self.batches = self.reasoning = self.organization = None
            self.extractions = self.ledger = self.reconciler = self.tools = self.backups = self.assistant = self.items = self.checkins = self.warranties = None
            self.tax_tables = None
            self.inbox_seen = self.inbox_candidate = None

    def leave_family(self):
        with self.mutex:
            if self.family:
                if self.hub.folder(self.family.root) is not self.family:
                    self.family.close()
                self.family = None

    # Families -----------------------------------------------------------------

    def refresh_hub(self):
        """Hold every family folder on this computer open for the hub and listen, or record why the hub can't listen
        (no family, no Tailscale) and let the folders go. Called at start, when families change and every family check."""
        with self.mutex:
            roots = [profile["folder"] for profile in self.profiles.all() if profile["kind"] == "family"]
            self.hub.hold(roots, self.family)
            if not self.hub.start()["listening"]:
                self.hub.hold([], self.family)  # Nothing to serve: other code may open the folders itself.
            return self.hub.status()

    def family_for(self, profile_id):
        """The family folder of a family profile: the open one (the family view's or the hub's), or opened for this call
        (the caller closes it)."""
        profile = self.profiles.get(profile_id)
        if profile["kind"] != "family":
            raise ValueError("That profile is not a family.")
        if self.family and self.profile and self.profile["id"] == profile_id:
            return self.family, False
        held = self.hub.folder(profile["folder"])
        if held:
            return held, False
        return FamilyFolder(Path(profile["folder"])), True

    def create_family(self, name, folder_value, members=(), my_profile=None):
        """A family profile with its members. Nothing switches; open the family from the profile menu."""
        with self.mutex:
            folder = validate_managed(folder_value, self.control)
            if self.profiles.by_folder(folder):
                raise PathError("Another profile already uses that folder.")
            family = FamilyFolder.create(folder, name)
            try:
                for member in members:
                    family.add_member(member, "remote")
                profile = self.profiles.add(family.data["name"], "family", folder)
                if my_profile:
                    self.link_local(family, family.add_member(self.profiles.get(my_profile)["name"], "local", my_profile)["member_id"], my_profile)
            finally:
                family.close()
            self.refresh_hub()
            return public(profile)

    def add_family_member(self, family_id, name):
        with self.mutex:
            family, temporary = self.family_for(family_id)
            try:
                return family.add_member(name, "remote")
            finally:
                if temporary:
                    family.close()

    def remove_family_member(self, family_id, member_id):
        with self.mutex:
            if self.busy("capture"):
                raise RuntimeError("Wait for the family to finish updating.")
            family, temporary = self.family_for(family_id)
            try:
                member = family.remove_member(member_id)
                if member.get("profile_id"):
                    try:
                        self.profiles.update(member["profile_id"], family=None)
                    except ValueError:
                        pass
                return family.summary()
            finally:
                if temporary:
                    family.close()

    def link_local(self, family, member_id, profile_id):
        """A member whose profile is on this computer: the family copies their library directly, nothing is published."""
        profile = self.profiles.get(profile_id)
        if profile["kind"] != "individual":
            raise ValueError("Only a person's own profile can be a family member.")
        if profile.get("family") and profile["family"]["family_id"] != family.data["family_id"]:
            raise ValueError(f"{profile['name']} already belongs to another family.")
        member = family.member(member_id)
        member.update(source="local", profile_id=profile_id, signature=None, token_sha256=None)
        family.save()
        # The key and family folder let this profile import what the family left for it when the family couldn't open its library.
        self.profiles.update(profile_id, family={"family_id": family.data["family_id"], "family_name": family.data["name"],
                                                 "member_id": member_id, "local": True, "key": family.data["key"], "folder": str(family.root)})
        if self.profile and self.profile["id"] == profile_id:
            self.profile = self.profiles.get(profile_id)

    def set_up_local_member(self, family_id, member_id, profile_id=None, folder_value=None, name=None):
        """Put a member on this computer: link an existing profile, or create one with its own library folder."""
        with self.mutex:
            family, temporary = self.family_for(family_id)
            try:
                if not profile_id:
                    if not folder_value:
                        raise ValueError("Choose the member's existing profile or a folder for a new one.")
                    profile_id = self.create_profile(name or family.member(member_id)["name"], folder_value)["id"]
                if any(item.get("profile_id") == profile_id and item["member_id"] != member_id for item in family.data["members"]):
                    raise ValueError("That profile is already a member of this family.")
                self.link_local(family, member_id, profile_id)
                return family.summary()
            finally:
                if temporary:
                    family.close()

    def invite_member(self, family_id, member_id, destination_value, passphrase):
        """An encrypted invite for a member's own computer. It carries the family key, the hub's Tailscale address and a new
        token for this member (their previous invite stops working); the passphrase travels separately."""
        with self.mutex:
            destination = separate_folder(destination_value, self.control, (self.store.root,) if self.store else ())
            hub = self.refresh_hub()
            if not hub["listening"]:
                raise ValueError(f"Members' computers can't reach this one yet. {hub['reason']}")
            family, temporary = self.family_for(family_id)
            try:
                member = family.member(member_id)
                if member["source"] != "remote":
                    member.update(source="remote", profile_id=None, signature=None)
                    family.save()
                path = write_invite(family.data, member, destination, passphrase, hub["address"], family.new_token(member_id))
                return {"path": str(path)}
            finally:
                if temporary:
                    family.close()

    def join_family(self, invite_value, passphrase):
        """Link the active individual profile to a family from its invite, then send a first copy."""
        with self.mutex:
            if self.session:
                raise RuntimeError("End the shared-library session before joining a family.")
            if not self.store or not self.profile or self.profile["kind"] != "individual":
                raise ValueError("Open your own profile before joining a family.")
            from ..core.paths import local_absolute
            invite = read_invite(local_absolute(invite_value), passphrase)
            link = {"family_id": invite["family_id"], "family_name": str(invite.get("family_name") or "Family")[:60], "member_id": invite["member_id"],
                    "key": invite["key"], "hub": invite["hub"], "token": invite["token"], "seq": 0, "publishing": True, "published_at": None,
                    "last_sync": None, "hub_state": "waiting", "hub_error": None, "local": False}
            pending_copy(self.control, link).unlink(missing_ok=True)  # A copy left from an earlier membership.
            self.profile = self.profiles.update(self.profile["id"], family=link)
            self.hub_retry = {"profile": self.profile["id"], "failures": 0, "next": 0.0}
            self.start_family_publish()
            return public(self.profile)

    def leave_joined_family(self):
        with self.mutex:
            if not self.profile or not self.profile.get("family"):
                raise ValueError("This profile is not in a family.")
            link = self.profile["family"]
            if not link.get("local"):
                pending_copy(self.control, link).unlink(missing_ok=True)  # An unsent copy never goes now.
            self.profile = self.profiles.update(self.profile["id"], family=None)
            return public(self.profile)

    def set_publishing(self, enabled):
        with self.mutex:
            link = (self.profile or {}).get("family")
            if not link or link.get("local"):
                raise ValueError("This profile does not publish to a family.")
            self.profile = self.profiles.update(self.profile["id"], family={**link, "publishing": bool(enabled)})
            return public(self.profile)

    def start_family_publish(self):
        """Share now: seal a fresh copy and send it, after taking in what the family sent."""
        with self.mutex:
            link = (self.profile or {}).get("family")
            if self.session or not self.store or not link or link.get("local"):
                raise ValueError("This profile does not publish to a family.")
            if not link.get("hub"):
                raise ValueError("Re-join your family: ask the family computer for a new invite.")
            self.hub_retry["next"] = 0.0
            return self.start_family_sync(reseal=True)

    def update_link(self, profile_id, update):
        """Merge changes into a profile's family link (if it still has one)."""
        with self.mutex:
            current = self.profiles.get(profile_id)
            if current.get("family"):
                profile = self.profiles.update(profile_id, family={**current["family"], **update})
                if self.profile and self.profile["id"] == profile_id:
                    self.profile = profile
                return profile["family"]
            return None

    def hub_result(self, profile_id, error=None):
        """Record how the last contact with the family computer went, and when to try again."""
        retry = self.hub_retry if self.hub_retry["profile"] == profile_id else {"profile": profile_id, "failures": 0, "next": 0.0}
        if error is None:
            retry.update(failures=0, next=0.0)
            update = {"hub_state": "ok", "hub_error": None, "last_sync": now()}
        else:
            retry["failures"] += 1
            first, longest = HUB_BACKOFF_SECONDS
            retry["next"] = time.monotonic() + min(first * 2 ** (retry["failures"] - 1), longest)
            update = {"hub_state": error.state, "hub_error": str(error)}
        self.hub_retry = retry
        self.update_link(profile_id, update)

    def start_family_sync(self, reseal=False):
        """Take in what the family sent (from the hub), then send this library's copy: a fresh one when reseal, otherwise one
        still waiting. Called under self.mutex."""
        link, store, control = self.profile["family"], self.store, self.control
        profile_id, name, born = self.profile["id"], self.profile["name"], self.household.birth_year

        def seal(current):
            try:
                return self.update_link(profile_id, seal_pending(store, control, current, name, born)) or current
            except (ValueError, OSError) as exc:
                log_failure(log, "family copy", exc)
                raise HubError("waiting", "Your copy couldn't be prepared. Details are in the Home Manager log.") from None

        def run(work):
            current = link
            try:
                unreachable = None
                try:  # First, so the copy includes what the family sent.
                    if pull_deliveries(store, current, lambda delivery, document: apply_family_delivery(store, delivery, document), work=work):
                        Reconciler(store).run("import")  # Records arriving from outside, like an import.
                except HubError as exc:
                    unreachable = exc
                if reseal:
                    current = seal(current)  # Sealed even while the hub can't be reached: it waits in the outbox.
                if unreachable:
                    raise unreachable
                try:
                    sent = upload_pending(control, current)
                except HubError as exc:
                    if exc.last_seq is None:
                        raise
                    # The family already has a copy numbered this high (this profile re-joined): number a fresh one above it.
                    current = seal(self.update_link(profile_id, {"seq": exc.last_seq}) or current)
                    sent = upload_pending(control, current)
                # Then the documents the copy's records cite, so originals open in the family view. documents_due keeps
                # this for the next sync if it is cut short.
                if sent or current.get("documents_due"):
                    current = self.update_link(profile_id, {"documents_due": True}) or current
                    push_documents(store, current, work)
                    self.update_link(profile_id, {"documents_due": False})
            except HubError as exc:
                self.hub_result(profile_id, exc)
                return
            self.hub_result(profile_id)

        self.future = self.submit("capture", "family_sync", "Syncing with your family", run)
        return {"started": True}

    def start_family_refresh(self):
        with self.mutex:
            if not self.family:
                raise ValueError("Open a family profile first.")
            family = self.family
            folders = {item["id"]: item["folder"] for item in self.profiles.all() if item["kind"] == "individual"}
            self.future = self.submit("capture", "family_refresh", "Updating the family view", lambda work: family.refresh(folders, work))
            return {"started": True}

    def check_family(self):
        """Every minute: the hub starts listening if it couldn't before (Tailscale started since); a family view picks up its
        members on this computer; a member on this computer imports what the family left for them; a member elsewhere asks the
        hub for deliveries and sends a changed copy at most every ten minutes, backing off while the hub can't be reached."""
        if not self.hub.status()["listening"]:
            self.refresh_hub()
        with self.mutex:
            if self.session or self.busy("capture"):
                return
            if self.family:
                self.start_family_refresh()
                return
            link = (self.profile or {}).get("family")
            if not self.store or not link:
                return
            if link.get("local"):
                root = self.local_family_root(link)
                if root and read_deliveries(root, link):
                    self.start_family_import()
                return
            profile_id = self.profile["id"]
            waiting = self.hub_retry["profile"] == profile_id and time.monotonic() < self.hub_retry["next"]
            if not link.get("hub") or waiting:
                return
            last = link.get("published_at")
            due = link.get("publishing", True) and (not last or (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds()
                                                     >= PUBLISH_EVERY_SECONDS) and changed_since(self.store, last)
            unsent = link.get("publishing", True) and (pending_copy(self.control, link).is_file() or bool(link.get("documents_due")))
        try:
            keys = list_deliveries(link)  # Outside the lock: the family computer may be slow to answer.
        except HubError as exc:
            self.hub_result(profile_id, exc)
            return
        self.hub_result(profile_id)
        with self.mutex:
            if (keys or due or unsent) and self.profile and self.profile["id"] == profile_id and not self.busy("capture"):
                self.start_family_sync(reseal=due)

    def local_family_root(self, link):
        """The family folder of a member on this computer: from the link, or (for links made before the hub) the family
        profile with this family's id."""
        if link.get("folder"):
            return Path(link["folder"])
        for profile in self.profiles.all():
            if profile["kind"] != "family":
                continue
            try:
                if json.loads((safe_path(Path(profile["folder"])) / "family.json").read_text(encoding="utf-8"))["family_id"] == link["family_id"]:
                    return Path(profile["folder"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return None

    # Family inbox: routing and delivery (finance/family_routing.py) ------------------------------

    def family_people(self):
        return [{"member_id": member["member_id"], "name": member["name"]} for member in self.family.data["members"]]

    def family_routing(self, include_delivered=False):
        """Records in the family's own library with who each is for: suggestions for new ones, the rest as confirmed."""
        from ..finance.family_routing import FamilyRouting, member_facts
        with self.mutex:
            if not self.family or not self.store:
                raise ValueError("Open a family profile first.")
            store = self.store
            with self.family.mutex:
                facts = member_facts(self.family_members())
            routing = FamilyRouting(store)
            routing.refresh(facts)
            return {"people": self.family_people(), "records": routing.list(include_delivered)}

    def assign_family_record(self, record_type, record_id, mode, members):
        """Confirm who a record is for, then deliver it to each person."""
        from ..finance.family_routing import FamilyRouting
        with self.mutex:
            if not self.family or not self.store:
                raise ValueError("Open a family profile first.")
            routing = FamilyRouting(self.store)
            assignment = routing.assign(record_type, record_id, mode, members, [person["member_id"] for person in self.family_people()])
            _, plan = routing.deliveries(record_type, record_id)
            currency = routing.payload(record_type, record_id)[0]["currency"]
            names = {person["member_id"]: person["name"] for person in self.family_people()}
            shares = [{"member_id": member, "name": names[member], "share": money(share, currency) if share is not None else None}
                      for member, action, share in plan if action == "record"]
            self.start_family_delivery()
            return {**assignment, "shares": shares}

    def start_family_delivery(self):
        """Deliver every confirmed assignment: straight into the library of a person on this computer, otherwise as an
        encrypted file in the family's outbox, which their computer pulls from the hub. Then refresh the family view."""
        with self.mutex:
            family, store = self.family, self.store
            folders = {item["id"]: item["folder"] for item in self.profiles.all() if item["kind"] == "individual"}
            self.future = self.submit("capture", "family_delivery", "Sending records to the family", lambda work: self.deliver(family, store, folders, work))
            return {"started": True}

    def deliver(self, family, store, folders, work):
        from ..finance.family_routing import FamilyRouting, apply_delivery
        from ..finance.reconcile import Reconciler
        routing, names = FamilyRouting(store), {member["member_id"]: member for member in family.data["members"]}
        for record_type, record_id in routing.pending():
            work.check()
            assignment, plan = routing.deliveries(record_type, record_id)
            record, document_name, document = routing.payload(record_type, record_id)
            people = [names[member]["name"] for member, action, _ in plan if action == "record" and member in names]
            results = {}
            for member_id, action, share in plan:
                member = names.get(member_id)
                if member is None:
                    continue
                delivery = {"key": assignment["family_record_key"], "action": action, "record_type": record_type, "name": document_name,
                            "blob_hash": hashlib.sha256(document).hexdigest(), "share": share, "people": people,
                            "record": record if action == "record" else None}
                applied = False
                folder = folders.get(member.get("profile_id")) if member["source"] == "local" else None
                if folder:
                    try:  # A person on this computer: their library is closed while the family is open, so apply it now.
                        target = Store(Path(folder))
                        try:
                            apply_delivery(target, delivery, document if action == "record" else None)
                            Reconciler(target).run("import")  # Records arriving from outside, like an import.
                        finally:
                            target.close()
                        applied = True
                    except (ValueError, OSError):
                        applied = False  # Locked or unavailable: it waits in the family's outbox for their profile instead.
                if not applied:
                    write_delivery(family.root, family.data["family_id"], family.data["key"], member_id, delivery,
                                   document if action == "record" else None)
                results[member_id] = "delivered" if action == "record" else "retracted"
            routing.mark_delivered(record_type, record_id, results)
        folders_now = {item["id"]: item["folder"] for item in self.profiles.all() if item["kind"] == "individual"}
        family.refresh(folders_now, work)

    def start_family_import(self):
        """Import what the family left in its folder for this profile, a member on this computer: records it routed here or
        shared with this person while this profile's library was open."""
        from ..finance.reconcile import Reconciler
        with self.mutex:
            link, store = self.profile["family"], self.store
            root = self.local_family_root(link)

            def run(work):
                imported = 0
                for path, delivery, document in read_deliveries(root, link) if root else []:
                    work.check()
                    try:
                        apply_family_delivery(store, delivery, document)
                        imported += 1
                    except (ValueError, OSError):
                        continue  # Left in place; the next check tries again.
                    path.unlink(missing_ok=True)
                if imported:
                    Reconciler(store).run("import")

            self.future = self.submit("capture", "family_import", "Adding records from your family", run)
            return {"started": True}

    def family_members(self):
        """(member, read-only store) for each member with data, in family order. Call with self.family.mutex held."""
        from ..finance.family import MemberStore
        return [(member, MemberStore(path)) for member, path in self.family.views()]

    def family_dashboard(self, month, months, currency):
        from ..finance.family import family_dashboard
        family = self.family
        waiting = len(self.family_routing()["records"]) if self.store else 0  # Uploads to the family not yet sent to anyone.
        with family.mutex:
            members = self.family_members()
            if not members:
                return {"family_empty": True, "family": family.summary(), "routing_waiting": waiting}
            return {**family_dashboard(members, month, months, currency, self.household.home_currency), "family": family.summary(),
                    "routing_waiting": waiting}

    def family_finance_tool(self, name, arguments=None):
        """The family ledger: a finance tool across members' copies (finance/family.py family_tool), with the fields of
        each row a correction is still waiting on."""
        from ..finance.family import family_tool
        family = self.family
        if not family:
            raise ValueError("Open a family profile first.")
        with family.mutex:
            return family_tool(self.family_members(), name, arguments, family.pending_corrections())

    def family_record(self, member_id, record_type, record_id):
        from ..finance.family import family_record
        family = self.family
        if not family:
            raise ValueError("Open a family profile first.")
        with family.mutex:
            return family_record(self.family_members(), member_id, record_type, record_id, family.pending_corrections())

    def correct_family_record(self, member_id, record_type, record_id, changes):
        """A change made in the family ledger to a member's record (finance/family_corrections.py). Each field is checked
        with a person's own correction's rules against the family's view of the record, kept as a 'sent' row, and sent:
        straight into the library of a member on this computer whose profile isn't open, otherwise as a delivery their
        computer pulls from the hub. The family view shows it at once, tagged until the member's copy answers."""
        from ..finance.family import MemberStore
        from ..finance.family_corrections import apply_correction, checked_value, current_text, same
        with self.mutex:
            family, store = self.family, self.store
            if not family or not store:
                raise ValueError("Open a family profile first.")
            member = family.member(member_id)
            view = family.view_dir / f"{member_id}.sqlite3"
            if not view.exists():
                raise ValueError(f"{member['name']}'s records haven't reached the family computer yet.")
            if not changes:
                raise ValueError("Choose a field to change.")
            who = actor.current() or family.data["name"]
            sends = []
            with family.mutex, MemberStore(view).connection() as db:
                for field, value in changes.items():
                    previous = current_text(db, record_type, record_id, field)
                    checked = checked_value(db, record_type, record_id, field, value)
                    if not same(record_type, field, previous, checked):
                        sends.append({"type": "correction", "key": uuid.uuid4().hex, "member_id": member_id, "record_type": record_type,
                                      "record_id": record_id, "field": field, "value": checked, "previous": previous, "actor": who})
            if not sends:
                raise ValueError("That's what the record already says.")
            folder = next((item["folder"] for item in self.profiles.all() if item["id"] == member.get("profile_id")), None) \
                if member["source"] == "local" else None
            with store.connection() as db:
                for item in sends:
                    db.execute("INSERT INTO family_corrections(key,direction,member_id,record_type,record_id,field,value,previous,actor,status,created_at,updated_at) "
                               "VALUES(?,'sent',?,?,?,?,?,?,?,'pending',?,?)",
                               (item["key"], member_id, record_type, record_id, item["field"], item["value"], item["previous"], who, now(), now()))
            for item in sends:
                applied = None
                if folder:  # A person on this computer: their library is closed while the family is open, so apply it now.
                    try:
                        target = Store(Path(folder))
                        try:
                            applied = apply_correction(target, item)
                        finally:
                            target.close()
                    except (ValueError, OSError):
                        applied = None  # Locked or unavailable: it waits in the family's outbox instead.
                if applied:
                    family.acknowledge(member_id, {item["key"]: applied})
                else:
                    write_delivery(family.root, family.data["family_id"], family.data["key"], member_id, item)
            if folder:
                family.refresh({item["id"]: item["folder"] for item in self.profiles.all() if item["kind"] == "individual"})
            with family.mutex:
                family.rebuild_views()
            return self.family_record(member_id, record_type, record_id)

    def reject_family_correction(self, key):
        """The member undoes a correction the family made to their record (finance/family_corrections.py)."""
        from ..finance.family_corrections import reject_correction
        with self.mutex:
            store = self.require(False)
        return reject_correction(store, key)

    def resolve_issue(self, issue_id, transaction_id=None, family_choice=None):
        """Answer a Review question: a family correction that conflicts ("Keep mine" or "Use family's"), or an ambiguous match."""
        from ..finance.family_corrections import resolve_conflict
        with self.mutex:
            store = self.require(False)
        with store.connection() as db:
            row = db.execute("SELECT issue_type FROM reconciliation_issues WHERE id=?", (issue_id,)).fetchone()
        if row and row["issue_type"] == "family_correction":
            if family_choice not in ("mine", "family"):
                raise ValueError("Choose Keep mine or Use family's.")
            return resolve_conflict(store, issue_id, family_choice == "family")
        return self.reconciler.resolve_issue(issue_id, transaction_id)

    def family_original(self, member_id, document_id, blob_hash=None, media=lambda relative_path: None):
        """A member's preserved document, for the family view: (media(relative path), chunks); media may refuse the file
        type before anything is opened. It opens while the member's app is stopped: a member on this computer is read from
        their library folder, any other from the documents their computer sent (stored encrypted, decrypted as it streams)."""
        from ..finance.family import MemberStore
        from ..library.storage import digest_file
        with self.mutex:
            family = self.family
            if not family:
                raise ValueError("Open a family profile first.")
            member = family.member(member_id)
            view = family.view_dir / f"{member_id}.sqlite3"
            if not view.exists():
                raise ValueError(f"{member['name']}'s records haven't reached the family computer yet.")
            document, version = MemberStore(view).document_version(document_id, blob_hash)
            digest, media_type = version["hash"], media(document["relative_path"])
            folder = next((item["folder"] for item in self.profiles.all() if item["id"] == member.get("profile_id")), None) \
                if member["source"] == "local" else None
        local = safe_path(Path(folder) / "originals" / digest[:2] / (digest + ".blob")) if folder else None
        if local is not None and local.is_file():
            if digest_file(local) != digest:
                raise RuntimeError("Preserved document failed its integrity check.")

            def from_library():
                with open(local, "rb") as source:
                    while chunk := source.read(1024 * 1024):
                        yield chunk
            return media_type, from_library()
        raw, reader = family.open_blob(digest)

        def from_family():
            try:
                while chunk := reader.read(1024 * 1024):
                    yield chunk
            finally:
                raw.close()
        return media_type, from_family()

    def family_net_worth(self, currency=None):
        from ..finance.family import family_net_worth
        family = self.family
        with family.mutex:
            members = self.family_members()
            return family_net_worth(members, currency or self.household.home_currency) if members else None

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
                    extractions = ExtractionService(store, receipts)
                    for service in (receipts, reasoning, batches, extractions):
                        service.recover()
                if persist:
                    write_atomic(self.settings_file, json.dumps({"managed_directory": str(managed)}))
            except BaseException:
                if store is not previous:
                    store.close()
                raise
            self.store, self.startup_error = store, None
            log.info("library opened")
            self.inbox_seen = self.inbox_candidate = None
            self.receipts, self.reasoning, self.batches = receipts, reasoning, batches
            self.extractions, self.ledger = extractions, extractions.ledger
            self.reconciler, self.tools = Reconciler(store), FinanceTools(store)
            self.tools.tax_status = self.tax_zen_status  # The assistant's get_tax_zen_status (finance/tools.py).
            self.backups, self.assistant = BackupService(store), AssistantService(store, self.tools)
            self.organization, self.items, self.checkins = OrganizationService(store), ItemResolver(store), CheckinService(store)
            self.warranties = WarrantyService(store, self.items.web)
            self.tax_tables = TaxTableService(store, self.items.web)
            for service in (self.organization, self.reconciler, self.backups, self.assistant, self.items, self.checkins, self.warranties,
                            self.tax_tables):
                service.recover()
            if previous and previous is not store:
                previous.close()
            with store.connection() as db:
                unindexed = bool(text_index.pending(db))
            if unindexed:  # Readings saved before the text index existed, or under older passage rules.
                self.submit("capture", "text_index", "Indexing document text for search", lambda work: text_index.backfill(store, work))
            return self.settings()

    def load_setting(self, name, model):
        # Invalid saved settings fall back to defaults; no unvalidated endpoint is ever used.
        path = safe_path(self.control / name)
        try:
            return model.model_validate_json(path.read_bytes()) if path.exists() else model()
        except (ValueError, OSError):
            return model()

    def gpu_token(self):
        path = safe_path(self.control / GPU_TOKEN)
        try:
            return path.read_text(encoding="utf-8").strip() if path.exists() else ""
        except OSError:
            return ""

    def apply_model_computer(self):
        """Point every model task at this PC's server, or at the shared GPU computer under role names
        (the GPU computer's owner chooses the actual models)."""
        computer = self.model_computer
        family = computer.provider == "family_gpu"
        residency.configure(computer.manage_model_loading)
        if computer.gpu_host_url:
            set_token(computer.gpu_host_url, self.gpu_token() if family else None)
        for attribute, saved in self.model_settings.items():
            # A /v1/systemone decision server is not LM Studio, so it stays on this PC.
            if family and getattr(saved, "provider", "chat") in ("chat", "lmstudio"):
                saved = saved.model_copy(update={"base_url": computer.gpu_host_url, "model": ROLE_ALIASES[attribute]})
            setattr(self, attribute, saved)

    def configure_model(self, attribute, config):
        if is_remote(config):
            raise ValueError("Enter this computer's model server here (http://127.0.0.1:PORT/v1). "
                             "To use a shared GPU, choose it under Model computer.")
        with self.mutex:
            if self.busy("inference"):
                raise RuntimeError("Wait for model work to finish, or cancel it, before changing model settings.")
            write_atomic(safe_path(self.control / MODEL_SETTINGS[attribute][0]), config.model_dump_json())
            self.model_settings[attribute] = config
            self.apply_model_computer()
            return config.model_dump()

    def configure_model_computer(self, computer, token=None):
        """Save where model calls run. A new token replaces the saved one; None keeps it."""
        with self.mutex:
            if self.busy("inference"):
                raise RuntimeError("Wait for model work to finish, or cancel it, before changing model settings.")
            if token:
                write_atomic(safe_path(self.control / GPU_TOKEN), token)
            if computer.provider == "family_gpu" and not self.gpu_token():
                raise ValueError("Paste the token the GPU computer's owner gave you.")
            if self.model_computer.gpu_host_url and self.model_computer.gpu_host_url != computer.gpu_host_url:
                set_token(self.model_computer.gpu_host_url, None)
            write_atomic(safe_path(self.control / MODEL_COMPUTER), computer.model_dump_json())
            self.model_computer = computer
            self.apply_model_computer()
            return self.model_computer_state()

    def model_computer_state(self):
        return {**self.model_computer.model_dump(), "token_set": bool(self.gpu_token()),
                "loading_hint": residency.hint() if self.model_computer.provider == "local" else None}

    def test_model_computer(self):
        """Read-only check that the shared GPU computer answers and serves this app's roles."""
        checks = {"vision": check_connection(self.vision), "reasoning": check_connection(self.reasoning_config)}
        if self.decision_config.provider == "lmstudio":
            checks["decision"] = check_connection(self.decision_config)
        return checks

    def test_decision_model(self, config):
        """Settings test for a decision model: reachable, listed, and answering with option probabilities."""
        return check_decision_model(config)

    def configure_decision(self, config):
        return self.configure_model("decision_config", config)

    def configure_vision(self, config):
        return self.configure_model("vision", config)

    def configure_reasoning(self, config):
        return self.configure_model("reasoning_config", config)

    def configure_reviewer(self, config):
        return self.configure_model("reviewer_config", config)

    def configure_household(self, config):
        with self.mutex:  # Not a model setting: never waits for model work. Each profile keeps its own.
            if not self.profile:
                raise PathError("Choose a library folder first.")
            self.profiles.save_household(self.profile["id"], config)
            self.household = config
            return config.model_dump()

    # Capture and its model follow-up ------------------------------------------

    def start_inbox(self):
        with self.mutex:
            store = self.require("capture", "Wait for the current scan before scanning Inbox.")
            job = store.create_job()
            self.future = self.pipeline(job)
            return job

    def sources(self):
        with self.mutex:
            return self.require(False).sources()

    def add_source(self, path_value, label="", recursive=True):
        """Watch a folder outside the library (Downloads, a scanner or phone-sync folder). It is scanned soon after."""
        with self.mutex:
            if self.session:
                raise RuntimeError("You are viewing a shared library. End the session to watch folders for your own library.")
            store = self.require(False)
            path = separate_folder(path_value, self.control, (store.root,))
            if not path.is_dir():
                raise PathError("Choose an existing folder to watch.")
            return store.add_source(path, label, recursive)

    def update_source(self, source_id, **changes):
        with self.mutex:
            return self.require(False).update_source(source_id, **changes)

    def remove_source(self, source_id):
        with self.mutex:
            self.require(False).remove_source(source_id)

    def start_source(self, source_id):
        """Scan one watched folder: new and changed files are copied into the library; the folder is never changed."""
        with self.mutex:
            store = self.require("capture", "Wait for the current scan before scanning a watched folder.")
            source = store.source(source_id)
            job = store.create_job(Path(source["path"]))
            store.source_scanned(source_id, job)
            self.future = self.pipeline(job, source)
            return job

    def pipeline(self, job, source=None):
        """Capture on the capture queue, then transcription on the inference queue."""
        done, follow = Future(), {}

        def capture(work):
            if self.capture(job, source):
                follow["future"] = self.submit("inference", "transcription", "Text extraction for newly captured documents", self.process_scan, job)

        def settle(outer):
            inner = follow.get("future")
            if outer.exception() is not None or inner is None:
                _settle(outer, done)
            else:
                inner.add_done_callback(lambda future: _settle(future, done))

        label = "Inbox capture" if source is None else "Watched folder capture: " + (source["label"] or Path(source["path"]).name)
        self.submit("capture", "capture", label, capture).add_done_callback(settle)
        return done

    def capture(self, job, source=None):
        if source is None:
            Scanner(self.store, self.limits).run(job)
        else:
            Scanner(self.store, self.limits).run(job, Path(source["path"]), bool(source["recursive"]))
        if self.store.job(job)["status"] not in ("completed", "partial"):
            self.store.organization_state(job, "not_started", "Capture did not complete. Preserved copies remain available.")
            return False
        try:  # Images that look like pages of one document: suggested in Review, never combined on their own.
            Groups(self.store).suggest(job)
        except (ValueError, OSError, sqlite3.Error) as exc:
            log_failure(log, "group suggestions", exc, job=job)
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
            failures = self.extract_batch(batch, work)
            state = "partial" if failures else self.batches.get(batch)["status"]
            self.store.organization_state(job, state, "Processing finished. Cited classification and extraction determine filing; unresolved documents remain available for review.", batch)
        except Cancelled:
            self.store.organization_state(job, "cancelled", "Model processing was cancelled. Captures and completed results are safe; use Extract text from all images to resume.")
        except Exception as exc:
            log_failure(log, "inbox processing", exc, job=job)
            self.store.organization_state(job, "failed", "Automatic text extraction failed. Captures are safe; use Extract text from all images to retry.")

    def extract_batch(self, batch, work, force=False):
        """Record each document a reading batch read, when a reasoning model is set. Returns how many failed.
        force: record again even from an unchanged reading (after its images were combined or separated)."""
        failures = 0
        if not self.reasoning_config.model:
            return failures
        with self.store.connection() as db:
            items = list(db.execute("SELECT document_id,run_id FROM receipt_batch_items WHERE batch_id=?", (batch,)))
        for item in items:
            work.check()
            if self.receipts.get(item["run_id"])["status"] not in ("succeeded", "partial"):
                continue
            try:
                extraction, created = self.extractions.enqueue(item["document_id"], item["run_id"], self.reasoning_config, force,
                                                               home_currency=self.household.home_currency, decision=self.decision_config)
                (self.extract_and_file if created else self.file_extraction)(item["document_id"], extraction, work)
                if self.extractions.get(extraction)["status"] != "succeeded":
                    failures += 1
            except (ValueError, OSError, RuntimeError):
                failures += 1
        work.check()
        return failures

    # Several images as one document ----------------------------------------------

    def suggested_groups(self):
        with self.mutex:
            return Groups(self.require(False)).proposed()

    def document_group(self, document_id):
        with self.mutex:
            return Groups(self.require(False)).of(document_id)

    def combine_documents(self, document_ids):
        """Make these images one document, pages in the order given, and read it."""
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before combining images.")
            group_id = Groups(self.store).create(list(document_ids))
            return self.read_group(group_id)

    def change_group(self, group_id, status=None, document_ids=None):
        """Confirm a suggestion, separate a combined document (dismissed) or put its pages in a new order; each reads again."""
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before changing a combined document.")
            groups = Groups(self.store)
            before = groups.get(group_id)["status"]
            group = groups.reorder(group_id, document_ids) if document_ids else groups.set_status(group_id, status)
            if group["status"] == "dismissed" and before == "proposed":
                return group  # A suggestion said no to: nothing was read as one.
            return self.read_group(group_id)

    def read_group(self, group_id):
        """Read and record what a group change affects. A combined document: its first page reads all pages, and the
        later pages' own receipts stop counting. Separated images: each is read and recorded on its own again."""
        group = Groups(self.store).get(group_id)
        documents = [page["document_id"] for page in group["pages"]]
        if group["status"] == "confirmed":
            for page in group["pages"][1:]:
                self.ledger.retire_segments(page["current_hash"], [], "This image is now a page of a combined document; it is recorded there.")
            documents = documents[:1]
        batch = self.batches.enqueue(self.vision, document_ids=documents)

        def run(work):
            self.batches.run(batch, work)
            work.check()
            self.extract_batch(batch, work, force=True)
        label = "Reading a combined document" if group["status"] == "confirmed" else "Reading separated images"
        self.future = self.submit("inference", "transcription", label, run)
        return {**group, "batch_id": batch}

    # Library and model operations ----------------------------------------------

    def library_action(self, document_id, expected_hash, action, folder=None):
        # Holds the mutex (not a queue) so directories cannot switch mid-move; model work continues.
        with self.mutex:
            self.require(False).library_action(document_id, expected_hash, action, folder)
            return {"status": action}

    def empty_trash(self):
        from ..library.trash import empty
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
            # The independent check runs on every extraction whenever a decision model is chosen.
            run_id, created = self.extractions.enqueue(document_id, parse_run_id, self.reasoning_config, force, self.household.home_currency,
                                                       self.decision_config)
            self.future = self.submit("inference", "extraction", "Ledger extraction",
                                      self.extract_and_file if created else self.file_extraction, document_id, run_id)
            return {"run_id": run_id, "reused": not created}

    # Several receipts in one file ------------------------------------------------

    def split(self, document_id):
        with self.mutex:
            self.require(False)
            return self.extractions.split(document_id)

    def confirm_split(self, document_id):
        with self.mutex:
            self.require(False)
            return self.extractions.confirm_split(document_id)

    def set_split(self, document_id, starts):
        """Split the file where the user says each receipt starts, then record it again with that split."""
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before changing how this file is split.")
            parse_run_id = self.extractions.set_split(document_id, starts)
            return self.start_extraction(document_id, parse_run_id, force=True)

    def extract_and_file(self, document_id, run_id, work):
        self.extractions.run(run_id, work)
        run = self.extractions.get(run_id)
        publication = run["publication"] or {}
        if publication.get("status") == "published" or ((run["result"] or {}).get("payment_terms") or {}).get("proposed"):
            self.reconciler.run("extraction")
        self.file_extraction(document_id, run_id, work)
        # A file holding several receipts published one per segment; each has its own items.
        for published in publication.get("segments") or [publication]:
            if published.get("record_type") == "receipt" and published.get("status") == "published":
                self.identify_items(published["id"], work)
        if publication.get("record_type") == "statement" and publication.get("status") == "published":
            self.scan_payees(work)
        if publication.get("record_type") == "income_record" and publication.get("status") == "published":
            self.look_up_tax_tables(publication["id"], work)

    def look_up_tax_tables(self, income_id, work):
        """After a pay stub is recorded: look up the federal and state tables for its tax year when there are none yet.
        Runs in the same model job; each table waits for the user in Review. Never fails the extraction."""
        record = self.ledger.record("income_record", income_id)
        if not record.get("pay_date"):
            return
        for jurisdiction in self.tax_tables.tables.needed(int(record["pay_date"][:4]), record.get("work_state"), self.household.filing_status):
            try:
                run_id = self.tax_tables.enqueue(jurisdiction, int(record["pay_date"][:4]), self.household.filing_status, self.reasoning_config)
            except ValueError:
                return  # No web search key or model: the pay stub page says the table is missing.
            work.check()
            self.tax_tables.run(run_id, self.reasoning_config, work)

    def start_tax_table_lookup(self, jurisdiction, year, filing_status=None):
        """filing_status: the paycheck planner can plan for another status than the household's."""
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before looking up a tax table.")
            run_id = self.tax_tables.enqueue(jurisdiction, year, filing_status or self.household.filing_status, self.reasoning_config)
            self.future = self.submit("inference", "tax_table_lookup", "Looking up a tax table", self.tax_tables.run, run_id, self.reasoning_config)
            return {"run_id": run_id}

    def paystub(self, income_id):
        """A pay stub record with how its taxes were figured (finance/paystub.py) and a bucket chart per jurisdiction."""
        record = self.ledger.record("income_record", income_id)
        year = int(record["pay_date"][:4]) if record.get("pay_date") else None
        record["withholding"] = self.paystub_taxes(record)
        for part in [*record["withholding"]["jurisdictions"], *record["withholding"]["fica"]]:  # Each estimate's breakdown (finance/tax_traces.py).
            if part.get("estimate_minor") is not None:
                part["trace"] = ref("paystub.tax", income_id=income_id, part=part.get("jurisdiction") or part["category"])
        for part in record["withholding"]["jurisdictions"]:
            if part.get("buckets") and any(bucket["income_minor"] for bucket in part["buckets"]):
                part["chart_svg"] = tax_buckets_svg(f"{part['name']} income tax buckets, {year}", part["buckets"], record["currency"],
                                                    record["withholding"]["paychecks"])
        return record

    def paystub_taxes(self, record, recorder=None, only=None):
        """How a pay stub's taxes are figured, from its year's tables (paystub.explain); a live recorder gets one part's
        estimate (finance/tax_traces.py)."""
        from ..core.trace import NULL
        year = int(record["pay_date"][:4]) if record.get("pay_date") else None
        state = record.get("work_state")
        tables = self.tax_tables.tables.for_year(year, ["US", *([state] if state else [])], self.household.filing_status) if year else {}
        return paystub.explain(record, record["lines"], tables, self.household.filing_status, recorder or NULL, only)

    def tax_year(self, year, today=None, seen=False):
        """This profile's return for a year (finance/tax_year.py, finance/tax_engine.py): what the records give, what you typed,
        the tables it needs, and the estimate. today: the date it's worked out as of (tests pin it); seen: the Taxes page
        is showing it."""
        from ..finance import tax_year
        today = today or date.today()
        status = self.household.filing_status
        gathered = tax_year.gather(self.store, year, self.household, today)
        inputs = tax_year.TaxYears(self.store).inputs(year)
        tables_for = lambda codes: self.tax_tables.tables.for_year(year, codes, status)
        return self.tax_view(year, status, self.household, gathered, inputs, tables_for, today=today, seen=seen)

    def gathered_tax_year(self, year):
        """What the records give for a year, before anything typed: kept beside each typed change (tax_input_changes)."""
        from ..finance import tax_year
        return tax_year.gather(self.store, year, self.household)

    def tax_attention(self, today=None, wait=False):
        """For Home (docs/taxes.md "Design"): this year's Tax Zen when it got worse since the Taxes page
        last showed it, else None. When a pay stub, tax form, tag or typed value is newer than the last evaluation, the
        return is worked out again in the background, so Home shows any change on its next load. wait: work it out
        first (tests)."""
        from ..finance.tax_zen import TaxZenEvaluations
        today = today or date.today()
        store = self.store
        with store.connection() as db:
            last = db.execute("SELECT max(created_at) FROM tax_zen_evaluations WHERE year=? AND unit='me'", (today.year,)).fetchone()[0]
            newest = db.execute("SELECT max(stamp) FROM (SELECT max(updated_at) AS stamp FROM income_records WHERE review_status='verified' "
                                "UNION ALL SELECT max(updated_at) FROM tax_forms WHERE review_status='verified' UNION ALL SELECT max(updated_at) FROM tax_tags "
                                "UNION ALL SELECT max(updated_at) FROM tax_years)").fetchone()[0]
        checked = max(filter(None, (last, self.tax_checked.get((str(store.root), today.year)))), default=None)
        if newest and (checked is None or newest > checked) and self.tax_refresh.acquire(blocking=False):
            def refresh():
                try:
                    self.tax_year(today.year, today)
                    self.tax_checked[(str(store.root), today.year)] = newest  # Unchanged advice adds no row; don't work it out again.
                except Exception as exc:  # Home still loads; the Taxes page shows the problem when opened.
                    log_failure(log, "tax zen refresh for Home", exc, year=today.year)
                finally:
                    self.tax_refresh.release()
            if wait:
                refresh()
            else:
                threading.Thread(target=refresh, name="tax-zen-refresh", daemon=True).start()
        return TaxZenEvaluations(store).attention(today.year)

    def tax_zen_status(self, year):
        """Tax Zen for the assistant (docs/taxes.md "Design"): the deterministic result, small, for
        the model to explain. Every figure is the engines' own."""
        view = self.tax_year(year)
        zen, result = view["zen"], view["return"]
        found = {"year": year, "status": zen.get("status"), "status_text": zen.get("status_text"), "reason": zen.get("reason") or zen.get("note"),
                 "engine": result.get("engine"), "notes": result.get("notes", [])[:3] + zen.get("notes", [])[:3]}
        if result.get("result_minor") is not None:
            found["year_end"] = {"refund" if result["result_minor"] > 0 else "owed": result["result"]["display"]}
            found["total_tax"] = next((line["display"] for line in result["lines"] if line["key"] == "total_tax"), None)
            found["paid_and_credited"] = next((line["display"] for line in result["lines"] if line["key"] == "total_payments"), None)
        if zen.get("range"):  # §23: where the year likely ends, and how sure.
            found["likely_range"] = {"low": zen["range"]["display"]["low_minor"], "high": zen["range"]["display"]["high_minor"],
                                     "confidence": zen["range"]["confidence"]}
        if zen.get("changed"):
            found["changed_since_last_time"] = zen["changed"]["texts"]
        if zen.get("cushion"):
            found["cushion"] = zen["cushion"]["text"]
        if zen.get("ready"):
            safe = zen["safe_harbor"]
            found["aim"] = {"strategy": zen["policy"]["strategy"], "year_end": zen["display"]["target_minor"], "refund": zen["target_minor"] > 0}
            found["safe_harbor"] = {"satisfied": safe["satisfied"], "risk": safe["risk"], "required_payment": zen["display"]["required_minor"],
                                    "basis": safe["required_basis"], "underpaid_quarters": safe["underpaid_quarters"]}
            job = zen.get("job")
            if job and not zen["zen"]:
                rest, extra = job["rest"], job.get("extra")
                found["w4"] = {"job": job["name"], "paychecks_left": job["paychecks_left"],
                               "step_4c_extra_per_paycheck": extra["display"]["per_check_minor"] if extra else None,
                               "step_4a_or_4b": {"field": rest.get("field"), "amount": rest.get("display", {}).get("amount"), "year_end": rest.get("display", {}).get("year_end_minor")},
                               "checked": rest.get("checked"), "unchanged_since": (job.get("steady") or {}).get("since")}
        return found

    # Exchange rates and the CPA pack (docs/money.md "Currency conversion", docs/taxes.md) ----------------------

    def rates(self, store=None):
        from ..finance.fx import EcbRates
        return EcbRates(store or self.store, self.rate_fetch, self.household.fetch_exchange_rates)

    def foreign_money(self, store=None):
        """True when any transaction or receipt is in a currency other than USD: only then are rates needed."""
        with (store or self.store).connection() as db:
            return db.execute("SELECT 1 FROM transactions WHERE currency<>'USD' UNION ALL SELECT 1 FROM receipts WHERE currency<>'USD' LIMIT 1").fetchone() is not None

    def rate_status(self):
        with self.mutex:
            store = self.require(False)
            return {**self.rates(store).status(), "needed": self.foreign_money(store)}

    def refresh_rates(self):
        """Download the ECB history now (the user's Refresh rates). The only outbound call for rates."""
        with self.mutex:
            store = self.require(False)
        self.rates(store).refresh()
        return self.rate_status()

    def start_rate_refresh(self):
        """At startup: refresh in the background when rates are on, foreign amounts exist and the cache is a day old; and crypto
        prices when they are on, coins are held and none were fetched today. Failures only leave values older, so they are logged,
        never raised."""
        store = self.store
        if not store:
            return
        if self.household.fetch_crypto_prices and self.prices(store).due():
            def prices(work):
                from ..finance.prices import PriceError
                try:
                    self.prices(store).refresh()
                except PriceError as exc:
                    log_failure(log, "crypto prices", exc)
            self.submit("capture", "crypto_prices", "Fetching crypto prices", prices)
        if not self.household.fetch_exchange_rates or not self.foreign_money(store) or not self.rates(store).due():
            return

        def run(work):
            from ..finance.fx import FxError
            try:
                self.rates(store).refresh()
            except FxError as exc:
                log_failure(log, "exchange rates", exc)
        self.submit("capture", "exchange_rates", "Downloading exchange rates", run)

    def prices(self, store=None):
        from ..finance.prices import CryptoPrices
        return CryptoPrices(store or self.store, self.price_fetch, self.household.fetch_crypto_prices)

    def price_status(self):
        with self.mutex:
            store = self.require(False)
            return self.prices(store).status()

    def refresh_prices(self):
        """Fetch crypto prices now (the user's Refresh prices). The only outbound call for prices."""
        with self.mutex:
            store = self.require(False)
        return self.prices(store).refresh()

    def build_cpa_pack(self, year):
        """The year-end CPA pack (finance/cpa_pack.py), from one snapshot of this profile's records."""
        from ..finance import tax_year
        from ..finance.cpa_pack import CpaPacks
        with self.mutex:
            store = self.require(False)
            if self.family:
                raise ValueError("Open a person's profile to build their CPA pack; the family view has no records of its own.")
            status = self.household.filing_status
            household = self.household
            tables_for = lambda codes: self.tax_tables.tables.for_year(year, codes, status)

        def tax_for(snap):
            return self.tax_view(year, status, household, tax_year.gather(snap, year, household), tax_year.TaxYears(snap).inputs(year), tables_for)
        return CpaPacks(store).build(year, tax_for)

    def cpa_packs(self, year=None):
        from ..finance.cpa_pack import CpaPacks
        with self.mutex:
            return CpaPacks(self.require(False)).list(year)

    def cpa_pack_file(self, pack_id):
        from ..finance.cpa_pack import CpaPacks
        with self.mutex:
            return CpaPacks(self.require(False)).path(pack_id)

    def donations(self):
        """Donation checks and bundles (documents/donations.py): evaluation labels only, never ledger changes.
        Not in a shared library: only the library's owner can donate their documents."""
        from ..documents.donations import Donations
        with self.mutex:
            if self.session:
                raise RuntimeError("You are viewing a shared library. Only its owner can donate its documents.")
            self.require(False)
            return Donations(self.store, self.receipts, self.ledger)

    def family_tax(self, year, today=None, seen=False):
        """Every return in the family (finance/tax_family.py): each one's records gathered from its members' shared copies,
        estimated, with its Tax Zen. People on no return yet are listed so a return can be made for them."""
        from ..finance import tax_family, tax_year
        from ..finance.ledger import HouseholdConfig
        today = today or date.today()
        units = tax_family.TaxUnits(self.store).list()
        with self.family.mutex:
            members = self.family_members()
            names = {member["member_id"]: member["name"] for member, _ in members}
            stores = {member["member_id"]: store for member, store in members}
            # Each member's birth year (their Settings): from their published copy, or their profile on this computer.
            born = {member["member_id"]: member.get("birth_year") or (self.profiles.household(member["profile_id"]).birth_year if member.get("profile_id") else None)
                    for member, _ in members}
            tables_any = self.scenario_tables(members)
            returns = []
            for unit in units:
                status = unit["filing_status"]
                present = [member for member in unit["members"] if member in stores]
                household = HouseholdConfig(filing_status=status, birth_year=born.get(present[0]) if present else None)
                parts = [(names.get(member, "Member"), tax_year.gather(stores[member], year, household, today)) for member in present]
                gathered = tax_family.combine(parts)
                inputs = tax_year.TaxYears(self.store).inputs(year, f"unit-{unit['id']}")
                if not inputs.get("people") and len(present) > 1:  # The spouse's birth year, unless typed.
                    inputs = {**inputs, "people": [{"name": names.get(present[1], "Spouse"), "birth_year": born.get(present[1])}]}
                view = self.tax_view(year, status, household, gathered, inputs, lambda codes, status=status: tables_any(year, codes, status),
                                     f"unit-{unit['id']}", today, seen)
                returns.append({**unit, "member_names": [names.get(member, "Member") for member in unit["members"]], "view": view})
        placed = {member for unit in units for member in unit["members"]}
        return {"year": year, "returns": returns, "members": [{"member_id": key, "name": name, "on_a_return": key in placed} for key, name in names.items()],
                "zen": bool(returns) and all(item["view"]["zen"].get("zen") for item in returns)}

    def add_tax_unit(self, name, members, filing_status):
        from ..finance.tax_family import TaxUnits
        with self.family.mutex:
            known = {member["member_id"]: member["name"] for member, _ in self.family_members()}
        return TaxUnits(self.store).add(name, members, filing_status, known)

    def tax_view(self, year, status, household, gathered, inputs, tables_for, unit="me", today=None, seen=False):
        """One return's page: gathered records, typed values, the merged input, its tables, the estimate and Tax Zen.
        unit: 'me', or the family's 'unit-<id>'. today: the date Tax Zen counts paychecks and due dates from. seen: the
        Taxes page is showing it, so Home stops pointing at it (tax_zen.TaxZenEvaluations)."""
        from ..core.money import format_minor
        from ..finance import tax_engine, tax_year, tax_zen
        from ..finance.tax_return import TIPPED_OCCUPATIONS
        merged = tax_year.merge(year, status, household, gathered, inputs)
        codes = ["US", *([merged.state] if merged.state else [])]
        tables = tables_for(codes)
        # The return, by the chosen engine slot (finance/tax_engine.py), kept in tax_calculations; its own output stays off the page.
        chosen = tax_engine.slot_of(self.household.tax_engine)
        estimate = tax_engine.calculate(chosen, merged, tables)
        records = tax_engine.TaxCalculations(self.store)
        calculation_id = records.record(unit, merged, estimate)
        ready = [slot for slot in tax_engine.others(chosen) if tax_engine.readiness(slot)["ready"]]
        if estimate.get("result_minor") is None and estimate.get("unsupported") and not estimate.get("needs"):
            # The chosen engine doesn't cover this return: another that does works it out, and the page says which.
            for slot in ready:
                other = tax_engine.calculate(slot, merged, tables)
                if other.get("result_minor") is not None:
                    calculation_id = records.record(unit, merged, other)
                    other["notes"] = [f"{estimate['engine']['label']} doesn't cover this return, so {other['engine']['label']} worked it out.",
                                      *estimate.get("notes", []), *other.get("notes", [])]
                    chosen, estimate, ready = slot, other, [item for item in ready if item != slot]
                    break
        if self.household.tax_engine_compare and ready and estimate.get("result_minor") is not None:  # Another engine too, and where they differ.
            other = tax_engine.calculate(ready[0], merged, tables)
            records.record(unit, merged, other)
            estimate["comparison"] = tax_engine.compare(estimate, other)
            other.pop("raw", None)
        estimate.pop("raw", None)
        # Last year's tax and AGI for the safe harbor: typed, or last year's return as worked out here.
        prior = tax_year.prior_year(inputs) or records.prior(year - 1, unit)
        # Tax Zen (finance/tax_zen.py): the W-4 entries, or advance tax, that bring it to $0.
        federal = tables.get("US") if tables.get("US", {}).get("status") == "verified" else None
        # A W-4 answer is checked by working the return out again with that job's withholding raised or lowered (§46).
        positions = {job["key"]: index for index, job in enumerate(gathered["jobs"])}

        def recheck(job_key, more):
            if job_key not in positions:
                return None
            jobs = list(merged.jobs)
            jobs[positions[job_key]] = jobs[positions[job_key]].model_copy(update={"federal_withheld": jobs[positions[job_key]].federal_withheld + more})
            return tax_engine.calculate(chosen, merged.model_copy(update={"jobs": jobs}), tables).get("result_minor")
        # The likely range (§23): the return again with the projected pay, interest and dividends moved down and up.
        outcomes = None
        if estimate.get("result_minor") is not None:
            lower, higher, confidence = tax_year.likely_range(merged, gathered, inputs)
            ends = [tax_engine.calculate(chosen, item, tables).get("result_minor") for item in (lower, higher)]
            if None not in ends:
                ends.append(estimate["result_minor"])
                outcomes = {"low_minor": min(ends), "high_minor": max(ends), "confidence": confidence}
        # Steady advice (§25): the last evaluation, and what changed since (§43).
        evaluations = tax_zen.TaxZenEvaluations(self.store)
        previous = evaluations.latest(year, unit)
        facts = tax_zen.assumptions(merged, gathered)
        changed = tax_zen.changes(previous["assumptions"] if previous else None, facts)
        zen = tax_zen.advise(estimate, gathered["jobs"], federal, tax_year.w4s(inputs), gathered["estimated_payments"]["federal_estimated"], year, today,
                             choose=inputs.get("zen_job"), prior=prior, policy=tax_zen.policy_of(inputs), recheck=recheck,
                             outcomes=outcomes, previous=previous, changed=changed)
        if zen.get("status") in tax_zen.RANK:
            evaluations.record(year, unit, zen, calculation_id, facts, "; ".join(changed["texts"]) or None)
        if seen:
            evaluations.seen(year, unit)
        money_view = lambda values: {key: format_minor(amount, "USD") for key, amount in values.items() if isinstance(amount, int) and not isinstance(amount, bool)}
        gathered["display"] = money_view(gathered["values"])
        for job in gathered["jobs"]:
            job["display"] = money_view(job["values"])
            job["per_check_display"] = money_view(job["per_check"])
        for business in gathered["businesses"]:
            business["display"] = money_view(business)
        return {"year": year, "filing_status": status, "filing_status_name": paystub.STATUS_NAMES[status], "gathered": gathered, "inputs": inputs,
                "input": merged.model_dump(), "typed_over": tax_year.typed_over(gathered, inputs), "return": estimate, "zen": zen, "prior_year": prior and {key: prior[key] for key in ("tax_minor", "agi_minor", "source") if key in prior},
                "tipped_occupations": TIPPED_OCCUPATIONS,
                "tables": {code: (tables[code]["status"] if code in tables else "missing") for code in codes}}

    def paycheck_tables(self, value):
        return self.tax_tables.tables.for_year(value.year, ["US", *([value.work_state] if value.work_state else [])], value.filing_status)

    def paycheck_tax_time(self, value, result, tables):
        """At tax time: this paycheck alone for a full year, and the W-4 entry that brings its return to $0 (finance/tax_zen.py)."""
        from ..finance import tax_zen
        from ..finance.ledger import HouseholdConfig
        empty = {"values": {}, "sources": {}, "jobs": [], "businesses": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
        return tax_zen.plan_tax_zen([("This paycheck", result, value, True)], empty, HouseholdConfig(filing_status=value.filing_status),
                                    value.filing_status, value.year, lambda codes: tables, self.household.tax_engine)

    def paycheck(self, value):
        """A planned paycheck, gross to net (finance/paycheck.py), with a bucket chart per income tax."""
        tables = self.paycheck_tables(value)
        result = paycheck.calculate(value, tables)
        result["tax_time"] = self.paycheck_tax_time(value, result, tables)
        # Each figure's breakdown re-runs this paycheck from its input (finance/tax_traces.py).
        shown = value.model_dump_json(exclude_defaults=True)
        result["traces"] = {"net_per_check": ref("paycheck.net", input=shown), "net_monthly": ref("paycheck.net", input=shown, per="month")}
        for group in result["groups"]:
            for line in group["lines"] if group["group"] == "tax" else []:
                line["trace"] = ref("paycheck.line", input=shown, category=line["category"])
        if result["tax_time"].get("result_minor") is not None:
            result["tax_time"]["trace"] = ref("taxzen.paycheck", input=shown)
        for part in result["jurisdictions"]:
            if part.get("buckets") and any(bucket["income_minor"] for bucket in part["buckets"]):
                part["chart_svg"] = tax_buckets_svg(f"{part['name']} income tax buckets, {value.year}", part["buckets"], result["currency"],
                                                    result["paychecks"])
        return result

    # What If scenarios (finance/scenarios.py) ----------------------------------------

    def scenarios_view(self):
        """Saved scenarios, the bases this profile can plan from, and the investment accounts a paycheck can pay into."""
        from ..finance.investments import Investments
        accounts = [] if self.family else [{"id": asset["account_id"], "name": asset["name"], "kind_label": asset["kind_label"], "tax_treatment": asset["tax_treatment"]}
                                           for asset in Investments(self.store).forecast_assets()]
        return {"scenarios": scenarios.Scenarios(self.store).list(), "family": bool(self.family), "accounts": accounts,
                "bases": ["family", "blank"] if self.family else ["profile", "blank"]}

    def scenario_tables(self, members=None):
        """tables_for(year, jurisdictions, status): this library's tax tables, and in the family view also each member's; a
        confirmed table wins over a proposed one. Call with the family's mutex held."""
        stores = [self.store] + ([store for _, store in (members or self.family_members())] if self.family else [])

        def tables_for(year, jurisdictions, filing_status):
            found = {}
            for store in stores:
                for code, row in TaxTables(store).for_year(year, jurisdictions, filing_status).items():
                    if code not in found or (found[code]["status"] != "verified" and row["status"] == "verified"):
                        found[code] = row
            return found
        return tables_for

    def scenario_base(self, value):
        from ..finance.forecast import Assets, baseline
        history, currency = value.forecast.history_months, value.forecast.currency
        if value.basis == "blank":
            chosen = currency_code(currency or self.household.home_currency or "USD")
            return scenarios.empty_baseline(chosen, history, scenarios.starting_cash(value, chosen))
        if value.basis == "family":
            if not self.family:
                raise ValueError("Open the family profile to plan from the family's records.")
            return scenarios.family_baseline(self.family_members(), history, currency or self.household.home_currency)
        if self.family:
            raise ValueError("In the family view, plan from the family's records or a blank slate.")
        return baseline(FinanceTools(self.store), Assets(self.store), history, currency)

    def compare_scenarios(self, ids, draft, include_now, years):
        """Now (this profile's or the family's forecast with the Forecast page's defaults) and each chosen plan, all over the
        same years."""
        from ..finance.forecast import ForecastInput
        saved = scenarios.Scenarios(self.store)
        with (self.family.mutex if self.family else contextlib.nullcontext()):
            tables_for = self.scenario_tables()
            chosen = ([scenarios.ScenarioInput(name="Now", basis="family" if self.family else "profile", forecast=ForecastInput(years=years))]
                      if include_now else [])
            chosen += [saved.input(scenario_id) for scenario_id in ids] + ([draft] if draft else [])
            runs = []
            today = date.today()
            for value in chosen:
                value = value.model_copy(update={"forecast": value.forecast.model_copy(update={"years": years})})
                result = scenarios.run(value, self.scenario_base(value), tables_for, today, birth_year=self.household.birth_year)
                result["tax_zen"] = self.plan_tax_zen(value, tables_for, today)
                if result["tax_zen"].get("result_minor") is not None:  # Its breakdown (finance/tax_traces.py).
                    result["tax_zen"]["trace"] = ref("tax.result", year=today.year) if not value.paychecks else \
                        scenarios.scenario_ref("taxzen.plan", value, today)
                runs.append((value.name, result))
        return scenarios.compare(runs)

    def plan_tax_zen(self, value, tables_for, today=None):
        """Tax Zen in this year for a plan (finance/tax_zen.py): a full year at the pay it ends with. "Now" is this year's return."""
        from ..finance import tax_year, tax_zen
        if self.family or value.basis == "family":
            return {"ready": False, "note": "Tax Zen for the family is on the Taxes page, one return at a time."}
        today = today or date.today()
        year, status = today.year, self.household.filing_status
        if not value.paychecks:
            if value.name != "Now" or value.basis != "profile":
                return {"ready": False, "note": "No planned paychecks."}
            view = self.tax_year(year, today)
            zen = view["zen"]
            return {"ready": zen.get("ready", False), "year": year, "zen": zen.get("zen"), "result_minor": zen.get("result_minor"),
                    "display": zen.get("display", {}), "job": zen.get("job", {}).get("name"), "w4": zen.get("job", {}).get("rest"),
                    "notes": ["This year's return from your records, with the paychecks left."], "note": zen.get("note")}
        # The pay the plan ends with: its paychecks with no last month (or the latest ones).
        final = [plan for plan in value.paychecks if plan.to_month is None] or [max(value.paychecks, key=lambda plan: plan.to_month or "")]
        paychecks = [(plan.label, paycheck.calculate(plan.paycheck, tables_for(plan.paycheck.year, ["US", *([plan.paycheck.work_state] if plan.paycheck.work_state else [])],
                                                                                 plan.paycheck.filing_status)), plan.paycheck, plan.mode == "replace_pay")
                     for plan in final if plan.mode == "replace_pay" or status == "married_joint"]
        gathered = tax_year.gather(self.store, year, self.household, today) if value.basis == "profile" else {
            "values": {}, "sources": {}, "jobs": [], "businesses": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
        return tax_zen.plan_tax_zen(paychecks, gathered, self.household, status, year, lambda codes: tables_for(year, codes, status), self.household.tax_engine)

    def plan_currency(self, value):
        return currency_code(value.forecast.currency or self.household.home_currency or "USD")

    def personal_plan(self, scenario_id):
        """Budgets and pay stubs belong to one person's profile, so a plan is put to use there, not in the family view."""
        if self.family:
            raise ValueError("Budgets and pay stubs belong to each person's profile. Open a person's profile to follow a plan.")
        return scenarios.Scenarios(self.store).input(scenario_id)

    def plan_budgets(self, scenario_id, month):
        value = self.personal_plan(scenario_id)
        return plan_tracking.budget_changes(value, month, self.plan_currency(value), self.ledger.budgets())

    def adopt_plan(self, scenario_id, month):
        value = self.personal_plan(scenario_id)
        return plan_tracking.adopt(self.store, self.ledger, scenario_id, month, self.plan_currency(value))

    def stop_plan(self, scenario_id):
        self.personal_plan(scenario_id)
        return plan_tracking.stop_tracking(self.store, scenario_id)

    def plan_vs_actual(self, scenario_id):
        value = self.personal_plan(scenario_id)
        return plan_tracking.plan_vs_actual(self.store, FinanceTools(self.store), scenarios.Scenarios(self.store).get(scenario_id),
                                            self.scenario_tables(), self.plan_currency(value))

    def paycheck_from_stub(self, income_id):
        """A planner input that starts from a recorded pay stub."""
        record = self.ledger.record("income_record", income_id)
        value = paycheck.from_stub(record, record["lines"], self.household.filing_status)
        return {**value, "year": value["year"] or datetime.now().year}

    def scan_payees(self, work):
        """After a statement is recorded: ask the model which new payees are recurring bills (finance/recurring_scan.py).
        Runs in the same model job; every result is a proposal in Review. Never fails the extraction."""
        try:
            if RecurringScan(self.store).run(self.reasoning_config, work)["recurring"]:
                self.reconciler.run("extraction")
        except ValueError:
            pass  # The model could not be reached; the next statement or the Bills page button asks again.

    def start_recurring_scan(self):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before looking for recurring bills.")
            if not self.reasoning_config.model:
                raise ValueError("Configure a local reasoning model in Settings first.")
            self.future = self.submit("inference", "recurring_scan", "Looking for recurring bills", self.run_recurring_scan)
            return {"started": True}

    def run_recurring_scan(self, work):
        if RecurringScan(self.store).run(self.reasoning_config, work)["recurring"]:
            self.reconciler.run("manual")

    def start_item_categories(self):
        """Categorise the items of receipts recorded before items had categories (finance/item_categories.py)."""
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before categorising receipt items.")
            if not self.reasoning_config.model:
                raise ValueError("Configure a local reasoning model in Settings first.")
            pending = len(ItemCategorizer(self.store).pending())
            if pending:
                self.future = self.submit("inference", "item_categories", "Categorising receipt items",
                                          lambda work: ItemCategorizer(self.store).run(self.reasoning_config, work))
            return {"started": bool(pending), "receipts": pending}

    def identify_items(self, receipt_id, work):
        """Automatic item identification after a receipt is recorded (docs/household.md "Identifying receipt lines").
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
        kind, merchant, dated, name = self.extractions.filing_identity(run)
        try:
            self.store.library.file_classified(document_id, self.receipts.get(run["parse_run_id"])["blob_hash"], kind, merchant, dated,
                                               "Filed from cited classification and extraction.", name)
        except (ValueError, OSError, RuntimeError):
            pass  # Filing intents retain their error; the extraction remains available.

    def reason_and_file(self, document_id, run_id, work):
        self.reasoning.run(run_id, work)
        run = self.reasoning.get(run_id)
        if run["status"] == "succeeded" and self.reviewer_config.enabled_with(self.decision_config):
            with self.store.connection() as db:
                db.execute("INSERT OR REPLACE INTO analysis_reviews VALUES(?,?,'running',NULL,NULL)", (run_id, self.reviewer_config.model_dump_json()))
            status, result, error = "failed", None, "Independent review failed. Analysis remains unreviewed."
            try:
                with work.attribute("review", run_id, "financial-review-v1"):
                    result = json.dumps(review(self.reviewer_config, run["result"], self.receipts.get(run["parse_run_id"])["result"], work, self.decision_config))
                status, error = "succeeded", None
            except Cancelled as exc:
                status, error = "cancelled", str(exc)
            except Exception as exc:  # Recorded as a failed review; the analysis stays unreviewed.
                log_failure(log, "independent review", exc, run=run_id)
            with self.store.connection() as db:
                db.execute("UPDATE analysis_reviews SET status=?,result_json=?,error=? WHERE reasoning_run_id=?", (status, result, error, run_id))
        self.file_saved_analysis(document_id, run_id, work)

    def file_saved_analysis(self, document_id, run_id, work=None):
        try:
            self.store.library.file_analysis(document_id, self.reasoning.get(run_id))
        except (ValueError, OSError, RuntimeError):
            pass  # Filing intents retain their error; valid financial analysis remains available.

    def add_manual_transaction(self, value):
        """A payment entered by hand, then a reconciliation pass: a line already here for it replaces it at once."""
        with self.mutex:
            self.require(False)
        record = self.ledger.add_manual_transaction(value.account_id, value.date, value.description, value.amount, value.direction, value.category)
        return {"record": record, "reconciliation": self.reconciler.run("manual")}

    def correct_record(self, record_type, record_id, changes, reason=None):
        """A user correction, then a reconciliation pass: dates and merchants decide matches and spending months."""
        with self.mutex:
            self.require(False)
        if record_type == "transaction":
            record = self.ledger.correct_transaction(record_id, changes, reason)
        else:
            record = self.ledger.correct(record_type, record_id, changes, reason)
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
            from ..library.share import check_passphrase
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
            from ..core.paths import local_absolute
            from ..library.share import check_passphrase
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
        self.leave_family()
        self.hub.stop()
        if self.session:
            shutil.rmtree(self.sessions / self.session["id"], ignore_errors=True)
        self.lock.close()
