"""Configuration, independent work queues, and persistent scan ownership.

Capture (filesystem) and inference (GPU/model, concurrency 1) run on separate
queues. Library and database actions run on the request thread and never wait
for model generation; organization is serialized by the managed library itself.
"""

from concurrent.futures import Future, ThreadPoolExecutor
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import uuid

from ..core.formats import SUPPORTED, extension
from ..core.jobs import QUEUES, Cancelled, Work
from ..core.logs import log_failure
from ..core.money import currency_code, money
from ..core.paths import DirectoryLock, PathError, safe_path, separate_folder, validate_managed, write_atomic
from ..documents.extraction import ExtractionService
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
from ..finance.tools import FinanceTools
from ..household.resolver import ItemResolver
from ..household.tax_figures import TaxFigureService
from ..household.tax_tables import TaxTables, TaxTableService
from ..household.warranty import WarrantyService
from ..library import text_index
from ..library.backup import BackupService, restore_backup
from ..library.organization import OrganizationService
from ..library.scanner import ScanLimits, Scanner
from ..library.share import export_share, open_share
from ..library.storage import MigrationError, Store, now
from ..models import residency
from ..models.laya_runtime import LayaRuntime
from ..models.model_client import check_connection, is_remote, set_token
from ..models.vision import ROLE_ALIASES, ModelComputer, VisionConfig
from .family_sync import FAMILY_MARKER, FamilyFolder, changed_since, publish, read_deliveries, read_invite, sync_folder, write_delivery, write_invite
from .profiles import Profiles, public

# Settings attribute -> (file name, model). Invalid saved settings fall back to
# defaults, which disable that model; no unvalidated endpoint is ever used.
# Capture-queue work that the user may cancel; scans themselves are not interruptible.
CANCELLABLE_CAPTURE = ("backup", "restore")
MODEL_SETTINGS = {"vision": ("vision.json", VisionConfig), "reasoning_config": ("reasoning.json", ReasoningConfig),
                  "reviewer_config": ("reviewer.json", ReviewerConfig)}
# This PC's server or a family GPU computer. The token has its own file and is never returned by the API.
MODEL_COMPUTER, GPU_TOKEN = "model_computer.json", "gpu_token.txt"
log = logging.getLogger(__name__)
# Before profiles, financial preferences were one file for the computer; the first profile inherits it.
LEGACY_HOUSEHOLD = "household.json"
FAMILY_READ_ONLY = "The family view is read-only. Switch to a member's profile to change records."
PUBLISH_EVERY_SECONDS = 600  # A member's changed library is published to the family at most this often.
FAMILY_TICKS = 20  # Inbox-monitor ticks (3 s each) between family checks.


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
        self.tax_tables = self.tax_figures = None
        self.restores = {}  # Restore outcomes for this process; a restore may run with no library open.
        self.shares = {}  # Share exports for this process.
        # A shared library opened for this process only: never saved to settings, deleted when it ends.
        self.session = self.session_opening = None
        self.sessions = safe_path(self.control / "sessions")
        if self.sessions.exists():
            shutil.rmtree(self.sessions)  # Temporary copies left by a session the app did not end.
        # Model settings as saved; self.vision, self.reasoning_config and self.reviewer_config are what runs
        # (the same, or pointed at the family GPU computer by apply_model_computer).
        self.model_settings = {attribute: self.load_setting(name, model) for attribute, (name, model) in MODEL_SETTINGS.items()}
        self.model_computer = self.load_setting(MODEL_COMPUTER, ModelComputer)
        self.apply_model_computer()
        # Profiles: each person's own library, or a family view over its members (app/profiles.py).
        self.profiles = Profiles(self.control)
        self.profile = None  # The active profile record.
        self.family = None  # The open FamilyFolder while a family profile is active.
        self.family_ticks = 0
        self.household = HouseholdConfig()
        self.startup_error = None
        self.limits = limits or ScanLimits()
        self.stop_monitor = threading.Event()
        self.inbox_seen = self.inbox_candidate = None
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

    # Settings ----------------------------------------------------------------

    def settings(self):
        activity = self.activity() if self.store else []
        progress = next((item["progress"] for item in activity if item["queue"] == "inference" and item["progress"]), None)
        return {"profile": public(self.profile) if self.profile else None, "profiles": [public(item) for item in self.profiles.all()],
                "family": self.family.summary() if self.family else None,
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
                "model_computer": self.model_computer_state(),
                "household": self.household.model_dump(), "laya": self.laya.status(),
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
                family = FamilyFolder(Path(profile["folder"]))
                try:
                    self.open_library(validate_managed(str(family.root / "library"), self.control), persist=False)
                except BaseException:
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
                    return public(self.profiles.add(family.data["name"], "family", folder))
                finally:
                    family.close()
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
            return public(self.profiles.remove(profile_id))

    def close_library(self):
        """Close the open library, leaving no store (a family profile holds none). Called under self.mutex with no work running."""
        with self.mutex:
            if self.store:
                self.store.close()
            self.store = self.receipts = self.batches = self.reasoning = self.organization = None
            self.extractions = self.ledger = self.reconciler = self.tools = self.backups = self.assistant = self.items = self.checkins = self.warranties = None
            self.tax_tables = self.tax_figures = None
            self.inbox_seen = self.inbox_candidate = None

    def leave_family(self):
        with self.mutex:
            if self.family:
                self.family.close()
                self.family = None

    # Families -----------------------------------------------------------------

    def family_for(self, profile_id):
        """The family folder of a family profile: the open one, or opened for this call (the caller closes it)."""
        profile = self.profiles.get(profile_id)
        if profile["kind"] != "family":
            raise ValueError("That profile is not a family.")
        if self.family and self.profile and self.profile["id"] == profile_id:
            return self.family, False
        return FamilyFolder(Path(profile["folder"])), True

    def create_family(self, name, folder_value, sync_value, members=(), my_profile=None):
        """A family profile with its members. Nothing switches; open the family from the profile menu."""
        with self.mutex:
            folder = validate_managed(folder_value, self.control)
            if self.profiles.by_folder(folder):
                raise PathError("Another profile already uses that folder.")
            sync = sync_folder(sync_value)
            family = FamilyFolder.create(folder, name, sync)
            try:
                for member in members:
                    family.add_member(member, "remote")
                profile = self.profiles.add(family.data["name"], "family", folder)
                if my_profile:
                    self.link_local(family, family.add_member(self.profiles.get(my_profile)["name"], "local", my_profile)["member_id"], my_profile)
            finally:
                family.close()
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
        member.update(source="local", profile_id=profile_id, signature=None)
        family.save()
        # The key and sync folder let this profile import what the family sends it when the family can't open its library.
        self.profiles.update(profile_id, family={"family_id": family.data["family_id"], "family_name": family.data["name"],
                                                 "member_id": member_id, "local": True, "key": family.data["key"], "sync": family.data["sync"]})
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
        """An encrypted invite for a member's own computer. It carries the family key; the passphrase travels separately."""
        with self.mutex:
            destination = separate_folder(destination_value, self.control, (self.store.root,) if self.store else ())
            family, temporary = self.family_for(family_id)
            try:
                member = family.member(member_id)
                path = write_invite(family.data, member, destination, passphrase)
                if member["source"] != "remote":
                    member.update(source="remote", profile_id=None, signature=None)
                    family.save()
                return {"path": str(path)}
            finally:
                if temporary:
                    family.close()

    def join_family(self, invite_value, passphrase, sync_value=None):
        """Link the active individual profile to a family from its invite, then publish a first copy."""
        with self.mutex:
            if self.session:
                raise RuntimeError("End the shared-library session before joining a family.")
            if not self.store or not self.profile or self.profile["kind"] != "individual":
                raise ValueError("Open your own profile before joining a family.")
            from ..core.paths import local_absolute
            invite = read_invite(local_absolute(invite_value), passphrase)
            sync = sync_folder(sync_value or invite.get("sync_hint"))
            link = {"family_id": invite["family_id"], "family_name": str(invite.get("family_name") or "Family")[:60], "member_id": invite["member_id"],
                    "key": invite["key"], "sync": str(sync), "publishing": True, "published_at": None, "publish_error": None, "local": False}
            self.profile = self.profiles.update(self.profile["id"], family=link)
            self.start_family_publish()
            return public(self.profile)

    def leave_joined_family(self):
        with self.mutex:
            if not self.profile or not self.profile.get("family"):
                raise ValueError("This profile is not in a family.")
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
        with self.mutex:
            link = (self.profile or {}).get("family")
            if self.session or not self.store or not link or link.get("local"):
                raise ValueError("This profile does not publish to a family.")
            profile_id, store, name = self.profile["id"], self.store, self.profile["name"]

            def run(work):
                try:
                    published = publish(store, link, name)
                    update = {"published_at": published, "publish_error": None}
                except (ValueError, OSError) as exc:
                    update = {"publish_error": str(exc) if isinstance(exc, ValueError) else "The sync folder could not be written."}
                with self.mutex:
                    current = self.profiles.get(profile_id)
                    if current.get("family"):
                        profile = self.profiles.update(profile_id, family={**current["family"], **update})
                        if self.profile and self.profile["id"] == profile_id:
                            self.profile = profile

            self.future = self.submit("capture", "family_publish", "Sharing your totals with your family", run)
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
        """Every minute: a family view picks up new member copies; a member imports what the family sent them, and publishes a
        changed library at most every ten minutes."""
        with self.mutex:
            if self.session or self.busy("capture"):
                return
            if self.family:
                self.start_family_refresh()
                return
            link = (self.profile or {}).get("family")
            if self.store and link and link.get("key") and link.get("sync") and read_deliveries(link):
                self.start_family_import()
                return
            if not self.store or not link or link.get("local") or not link.get("publishing", True):
                return
            last = link.get("published_at")
            if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < PUBLISH_EVERY_SECONDS:
                return
            if changed_since(self.store, last):
                self.start_family_publish()

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
        encrypted file in their folder in the sync folder. Then refresh the family view."""
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
                        applied = False  # Locked or unavailable: it waits in the sync folder for their profile instead.
                if not applied:
                    write_delivery(family.data["family_id"], family.data["key"], family.data["sync"], member_id, delivery,
                                   document if action == "record" else None)
                results[member_id] = "delivered" if action == "record" else "retracted"
            routing.mark_delivered(record_type, record_id, results)
        folders_now = {item["id"]: item["folder"] for item in self.profiles.all() if item["kind"] == "individual"}
        family.refresh(folders_now, work)

    def start_family_import(self):
        """Import what the family sent this profile: records it routed here or shared with this person."""
        from ..finance.family_routing import apply_delivery
        from ..finance.reconcile import Reconciler
        with self.mutex:
            link, store = self.profile["family"], self.store

            def run(work):
                imported = 0
                for path, delivery, document in read_deliveries(link):
                    work.check()
                    try:
                        apply_delivery(store, delivery, document)
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
            log.info("library opened")
            self.inbox_seen = self.inbox_candidate = None
            self.receipts, self.reasoning, self.batches = receipts, reasoning, batches
            self.extractions, self.ledger = extractions, extractions.ledger
            self.reconciler, self.tools = Reconciler(store), FinanceTools(store)
            self.backups, self.assistant = BackupService(store), AssistantService(store, self.tools)
            self.organization, self.items, self.checkins = OrganizationService(store), ItemResolver(store), CheckinService(store)
            self.warranties = WarrantyService(store, self.items.web)
            self.tax_tables = TaxTableService(store, self.items.web)
            self.tax_figures = TaxFigureService(store, self.items.web)  # Its runs share tax_table_runs, recovered with the tables'.
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
        """Point every model task at this PC's server, or at the family GPU computer under role names
        (the GPU computer's owner chooses the actual models)."""
        computer = self.model_computer
        family = computer.provider == "family_gpu"
        residency.configure(computer.manage_model_loading)
        if computer.gpu_host_url:
            set_token(computer.gpu_host_url, self.gpu_token() if family else None)
        for attribute, saved in self.model_settings.items():
            if family and getattr(saved, "provider", "chat") == "chat":
                saved = saved.model_copy(update={"base_url": computer.gpu_host_url, "model": ROLE_ALIASES[attribute]})
            setattr(self, attribute, saved)

    def configure_model(self, attribute, config):
        if is_remote(config):
            raise ValueError("Enter this computer's model server here (http://127.0.0.1:PORT/v1). "
                             "To use a family member's GPU, choose it under Model computer.")
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
        """Read-only check that the family GPU computer answers and serves this app's roles."""
        return {"vision": check_connection(self.vision), "reasoning": check_connection(self.reasoning_config)}

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
        except Exception as exc:
            log_failure(log, "inbox processing", exc, job=job)
            self.store.organization_state(job, "failed", "Automatic text extraction failed. Captures are safe; use Extract text from all images to retry.")

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
            # The independent check runs on every extraction whenever Laya is installed.
            run_id, created = self.extractions.enqueue(document_id, parse_run_id, self.reasoning_config, force, self.household.home_currency,
                                                       self.laya.installed())
            self.future = self.submit("inference", "extraction", "Ledger extraction",
                                      self.extract_and_file if created else self.file_extraction, document_id, run_id)
            return {"run_id": run_id, "reused": not created}

    def extract_and_file(self, document_id, run_id, work):
        self.extractions.run(run_id, work)
        run = self.extractions.get(run_id)
        publication = run["publication"] or {}
        if publication.get("status") == "published" or ((run["result"] or {}).get("payment_terms") or {}).get("proposed"):
            self.reconciler.run("extraction")
        self.file_extraction(document_id, run_id, work)
        if publication.get("record_type") == "receipt" and publication.get("status") == "published":
            self.identify_items(publication["id"], work)
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
        state = record.get("work_state")
        tables = self.tax_tables.tables.for_year(year, ["US", *([state] if state else [])], self.household.filing_status) if year else {}
        record["withholding"] = paystub.explain(record, record["lines"], tables, self.household.filing_status)
        for part in record["withholding"]["jurisdictions"]:
            if part.get("buckets") and any(bucket["income_minor"] for bucket in part["buckets"]):
                part["chart_svg"] = tax_buckets_svg(f"{part['name']} income tax buckets, {year}", part["buckets"], record["currency"],
                                                    record["withholding"]["paychecks"])
        return record

    def start_tax_figures_lookup(self, year, filing_status=None):
        with self.mutex:
            self.require("inference", "Model work is running. Wait for it or cancel it before looking up tax figures.")
            run_id = self.tax_figures.enqueue_figures(year, filing_status or self.household.filing_status, self.reasoning_config)
            self.future = self.submit("inference", "tax_figure_lookup", "Looking up tax figures", self.tax_figures.run, run_id, self.reasoning_config)
            return {"run_id": run_id}

    def tax_year(self, year):
        """This profile's return for a year (finance/tax_year.py, finance/tax_return.py): what the records give, what you typed,
        the figures and tables it needs, and the estimate."""
        from ..finance import tax_year
        status = self.household.filing_status
        gathered = tax_year.gather(self.store, year, self.household)
        inputs = tax_year.TaxYears(self.store).inputs(year)
        tables_for = lambda codes: self.tax_tables.tables.for_year(year, codes, status)
        return self.tax_view(year, status, self.household, gathered, inputs, tables_for, self.tax_figures.figures.effective(year, status))

    def family_tax(self, year):
        """Every return in the family (finance/tax_family.py): each one's records gathered from its members' shared copies,
        estimated, with its Tax Zen. People on no return yet are listed so a return can be made for them."""
        from ..finance import tax_family, tax_year
        from ..finance.ledger import HouseholdConfig
        from ..household.tax_figures import TaxFigures
        units = tax_family.TaxUnits(self.store).list()
        with self.family.mutex:
            members = self.family_members()
            names = {member["member_id"]: member["name"] for member, _ in members}
            stores = {member["member_id"]: store for member, store in members}
            tables_any = self.scenario_tables(members)
            returns = []
            for unit in units:
                status = unit["filing_status"]
                household = HouseholdConfig(filing_status=status)
                parts = [(names.get(member, "Member"), tax_year.gather(stores[member], year, household)) for member in unit["members"] if member in stores]
                gathered = tax_family.combine(parts)
                inputs = tax_year.TaxYears(self.store).inputs(year, f"unit-{unit['id']}")
                figures = TaxFigures(self.store).effective(year, status)
                for store in stores.values():  # Figures a member confirmed or typed count when the family has none of its own.
                    member_figures = TaxFigures(store).effective(year, status)
                    for key, value in member_figures["values"].items():
                        if key not in figures["values"]:
                            figures["values"][key], figures["sources"][key] = value, member_figures["sources"][key]
                            figures["display"][key] = member_figures["display"][key]
                figures["missing"] = [key for key in figures["labels"] if key not in figures["values"]]
                view = self.tax_view(year, status, household, gathered, inputs, lambda codes, status=status: tables_any(year, codes, status), figures)
                returns.append({**unit, "member_names": [names.get(member, "Member") for member in unit["members"]], "view": view})
        placed = {member for unit in units for member in unit["members"]}
        return {"year": year, "returns": returns, "members": [{"member_id": key, "name": name, "on_a_return": key in placed} for key, name in names.items()],
                "zen": bool(returns) and all(item["view"]["zen"].get("zen") for item in returns)}

    def add_tax_unit(self, name, members, filing_status):
        from ..finance.tax_family import TaxUnits
        with self.family.mutex:
            known = {member["member_id"]: member["name"] for member, _ in self.family_members()}
        return TaxUnits(self.store).add(name, members, filing_status, known)

    def tax_view(self, year, status, household, gathered, inputs, tables_for, figures):
        """One return's page: gathered records, typed values, the merged input, its tables and figures, the estimate and Tax Zen."""
        from ..core.money import format_minor
        from ..finance import tax_return, tax_year, tax_zen
        merged = tax_year.merge(year, status, household, gathered, inputs)
        codes = ["US", *([merged.state] if merged.state else [])]
        tables = tables_for(codes)
        estimate = tax_return.estimate(merged, tables.get("US"), figures["values"], tables.get(merged.state) if merged.state else None)
        # Tax Zen (finance/tax_zen.py): the W-4 entries, or advance tax, that bring it to $0.
        federal = tables.get("US") if tables.get("US", {}).get("status") == "verified" else None
        zen = tax_zen.advise(estimate, gathered["jobs"], federal, tax_year.w4s(inputs), gathered["estimated_payments"]["federal_estimated"], year,
                             choose=inputs.get("zen_job"), prior=tax_year.prior_year(inputs))
        money_view = lambda values: {key: format_minor(amount, "USD") for key, amount in values.items() if isinstance(amount, int) and not isinstance(amount, bool)}
        gathered["display"] = money_view(gathered["values"])
        for job in gathered["jobs"]:
            job["display"] = money_view(job["values"])
            job["per_check_display"] = money_view(job["per_check"])
        for business in gathered["businesses"]:
            business["display"] = money_view(business)
        return {"year": year, "filing_status": status, "filing_status_name": paystub.STATUS_NAMES[status], "gathered": gathered, "inputs": inputs,
                "input": merged.model_dump(), "figures": figures, "return": estimate, "zen": zen,
                "tables": {code: (tables[code]["status"] if code in tables else "missing") for code in codes}}

    def paycheck(self, value):
        """A planned paycheck, gross to net (finance/paycheck.py), with a bucket chart per income tax."""
        from ..finance import tax_zen
        from ..finance.ledger import HouseholdConfig
        tables = self.tax_tables.tables.for_year(value.year, ["US", *([value.work_state] if value.work_state else [])], value.filing_status)
        result = paycheck.calculate(value, tables)
        # At tax time: this paycheck alone for a full year, and the W-4 entry that brings its return to $0 (finance/tax_zen.py).
        empty = {"values": {}, "sources": {}, "jobs": [], "businesses": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
        result["tax_time"] = tax_zen.plan_tax_zen([("This paycheck", result, value, True)], empty, HouseholdConfig(filing_status=value.filing_status),
                                                  value.filing_status, value.year, lambda codes: tables, self.tax_figures.figures.effective(value.year, value.filing_status)["values"])
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
            for value in chosen:
                value = value.model_copy(update={"forecast": value.forecast.model_copy(update={"years": years})})
                result = scenarios.run(value, self.scenario_base(value), tables_for, birth_year=self.household.birth_year)
                result["tax_zen"] = self.plan_tax_zen(value, tables_for)
                runs.append((value.name, result))
        return scenarios.compare(runs)

    def plan_tax_zen(self, value, tables_for):
        """Tax Zen in this year for a plan (finance/tax_zen.py): a full year at the pay it ends with. "Now" is this year's return."""
        from ..finance import tax_year, tax_zen
        from ..household.tax_figures import TaxFigures
        if self.family or value.basis == "family":
            return {"ready": False, "note": "Tax Zen for the family is on the Taxes page, one return at a time."}
        year, status = datetime.now().year, self.household.filing_status
        if not value.paychecks:
            if value.name != "Now" or value.basis != "profile":
                return {"ready": False, "note": "No planned paychecks."}
            view = self.tax_year(year)
            zen = view["zen"]
            return {"ready": zen.get("ready", False), "year": year, "zen": zen.get("zen"), "result_minor": zen.get("result_minor"),
                    "display": zen.get("display", {}), "job": zen.get("job", {}).get("name"), "w4": zen.get("job", {}).get("rest"),
                    "notes": ["This year's return from your records, with the paychecks left."], "note": zen.get("note")}
        # The pay the plan ends with: its paychecks with no last month (or the latest ones).
        final = [plan for plan in value.paychecks if plan.to_month is None] or [max(value.paychecks, key=lambda plan: plan.to_month or "")]
        paychecks = [(plan.label, paycheck.calculate(plan.paycheck, tables_for(plan.paycheck.year, ["US", *([plan.paycheck.work_state] if plan.paycheck.work_state else [])],
                                                                                 plan.paycheck.filing_status)), plan.paycheck, plan.mode == "replace_pay")
                     for plan in final if plan.mode == "replace_pay" or status == "married_joint"]
        gathered = tax_year.gather(self.store, year, self.household) if value.basis == "profile" else {
            "values": {}, "sources": {}, "jobs": [], "businesses": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
        figures = TaxFigures(self.store).effective(year, status)["values"]
        return tax_zen.plan_tax_zen(paychecks, gathered, self.household, status, year, lambda codes: tables_for(year, codes, status), figures)

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
        kind, merchant, dated, name = self.extractions.filing_identity(run)
        try:
            self.store.library.file_classified(document_id, self.receipts.get(run["parse_run_id"])["blob_hash"], kind, merchant, dated,
                                               "Filed from cited classification and extraction.", name)
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
        if self.session:
            shutil.rmtree(self.sessions / self.session["id"], ignore_errors=True)
        self.lock.close()
