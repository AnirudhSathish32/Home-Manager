"""Family folders, invites and member snapshots.

A family view never opens a member's live library for writing. Each member's computer publishes an
encrypted copy of its database (no documents) to a sync folder both computers can see; the family
computer imports it. Members on the same computer are copied straight from their library folder.

Family folder (on the computer that shows the family view):
  .home-manager-family        marker
  family.json                 family id, name, key, sync folder, members and their import state
  members/<member>.sqlite3    the last imported copy of each member's database
  view/<member>.sqlite3       those copies with family adjustments: a joint account counted once,
                              transfers between members left out of spending and income
Sync folder (any folder both computers see, e.g. OneDrive): <sync>/<family_id>/<member_id>.hmfamily

Snapshots are encrypted with the family's random 32-byte key (library/share.py, AES-256-GCM); invites
carry that key and are encrypted with a passphrase the family owner chooses.
"""

from datetime import date, datetime
import io
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import threading
import uuid

from ..core.jobs import Work
from ..core.logs import log_failure
from ..core.money import money
from ..core.paths import DirectoryLock, PathError, safe_path, write_atomic
from ..library.share import DecryptingReader, EncryptingWriter, ShareError, check_passphrase
from ..library.storage import MIGRATIONS, MigrationError, apply_migrations, now
from .profiles import clean_name, decode_key, encode_key

log = logging.getLogger(__name__)

FAMILY_MARKER = ".home-manager-family"
MARKER_TEXT = "home-manager-family-v1\n"
SNAPSHOT_MAGIC, INVITE_MAGIC, DELIVERY_MAGIC = b"HMFAMLY1", b"HMINVIT1", b"HMDELIV1"
SNAPSHOT_EXTENSION, INVITE_EXTENSION, DELIVERY_EXTENSION = ".hmfamily", ".hminvite", ".hmdelivery"
MAX_HEADER, MAX_SNAPSHOT, MAX_INVITE = 65536, 4 * 1024 ** 3, 65536
MAX_MEMBERS = 20
# Words banks print on money moved between people rather than spent.
TRANSFER_WORDS = re.compile(r"\b(transfer|xfer|zelle|venmo|paypal|cash ?app|apple cash|wire|p2p|interac)\b", re.IGNORECASE)
TRANSFER_DAYS = 3


def sync_folder(value) -> Path:
    """The folder both computers see. Only encrypted files are written there, so network and cloud folders are fine."""
    path = Path(str(value or "")).expanduser()
    if not path.is_absolute():
        raise PathError("Choose the sync folder by its full path.")
    path = safe_path(path)
    if not path.is_dir():
        raise PathError("Choose an existing sync folder.")
    return path


def _name_part(value):
    return re.sub(r"[^A-Za-z0-9 _-]", "", value).strip()[:40] or "member"


# Encrypted payloads -------------------------------------------------------------------

def _seal(path: Path, header: dict, body=None, *, key=None, passphrase=None, magic):
    """Write header JSON, a newline and body (a file path, or bytes) encrypted, through a .partial file renamed into place."""
    partial = safe_path(path.with_name(path.name + ".partial"))
    try:
        with open(partial, "wb") as raw:
            sink = EncryptingWriter(raw, passphrase, key=key, magic=magic)
            sink.write(json.dumps(header).encode() + b"\n")
            if isinstance(body, bytes):
                sink.write(body)
            elif body is not None:
                with open(body, "rb") as source:
                    while chunk := source.read(1024 * 1024):
                        sink.write(chunk)
            sink.finish()
            raw.flush()
            os.fsync(raw.fileno())
        os.replace(partial, path)
    finally:
        partial.unlink(missing_ok=True)
    return path


def _open(path: Path, *, key=None, passphrase=None, magic, noun):
    raw = open(path, "rb")
    try:
        reader = io.BufferedReader(DecryptingReader(raw, passphrase, key=key, magic=magic, noun=noun))
        line = reader.readline(MAX_HEADER + 1)
        if not line.endswith(b"\n"):
            raise ShareError(f"The {noun} file is damaged or incomplete.")
        return raw, reader, json.loads(line)
    except BaseException:
        raw.close()
        raise


# Invites ----------------------------------------------------------------------------

def write_invite(family, member, destination: Path, passphrase):
    check_passphrase(passphrase)
    if not destination.is_dir():
        raise PathError("Choose an existing folder for the invite file.")
    payload = {"kind": "home-manager-family-invite", "family_id": family["family_id"], "family_name": family["name"],
               "member_id": member["member_id"], "member_name": member["name"], "key": family["key"], "sync_hint": family["sync"],
               "created_at": now()}
    target = safe_path(destination / f"{_name_part(family['name'])} - {_name_part(member['name'])}{INVITE_EXTENSION}")
    return _seal(target, payload, passphrase=passphrase, magic=INVITE_MAGIC)


def read_invite(path: Path, passphrase):
    check_passphrase(passphrase)
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > MAX_INVITE:
        raise PathError("Choose the .hminvite file itself.")
    raw, reader, invite = _open(path, passphrase=passphrase, magic=INVITE_MAGIC, noun="invite")
    try:
        reader.read()  # Authenticates the final chunk.
    finally:
        raw.close()
    if invite.get("kind") != "home-manager-family-invite" or not all(isinstance(invite.get(key), str) for key in ("family_id", "member_id", "key")):
        raise ShareError("This invite is not one Home Manager can use.")
    decode_key(invite["key"])
    return invite


# Family inbox deliveries (finance/family_routing.py) ----------------------------------------
# A record the family confirmed travels to each person as <sync>/<family>/to-<member>/<key>.hmdelivery: the record, the
# person's part when shared and the document itself, encrypted with the family key. A newer file for the same key
# (a reassignment, or a retraction) replaces an older one that was not imported yet.

def delivery_folder(sync, family_id, member_id):
    return safe_path(sync_folder(sync) / family_id / f"to-{member_id}")


def write_delivery(family_id, key, sync, member_id, delivery, document=None):
    folder = delivery_folder(sync, family_id, member_id)
    folder.mkdir(parents=True, exist_ok=True)
    header = {"kind": "home-manager-family-delivery", "family_id": family_id, "member_id": member_id, "created_at": now(), **delivery}
    return _seal(safe_path(folder / (delivery["key"] + DELIVERY_EXTENSION)), header, document, key=decode_key(key), magic=DELIVERY_MAGIC)


def read_deliveries(link):
    """[(path, delivery, document bytes or None)] waiting for this member, oldest first. Files that fail to open are skipped
    (another computer may still be writing them); a file for another family or member is refused."""
    try:
        folder = delivery_folder(link["sync"], link["family_id"], link["member_id"])
    except PathError:
        return []
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*" + DELIVERY_EXTENSION), key=lambda item: item.stat().st_mtime_ns):
        if path.stat().st_size > MAX_SNAPSHOT:
            continue
        try:
            raw, reader, header = _open(path, key=decode_key(link["key"]), magic=DELIVERY_MAGIC, noun="family")
            try:
                document = reader.read() or None
            finally:
                raw.close()
        except (ValueError, OSError):
            continue
        if header.get("kind") != "home-manager-family-delivery" or header.get("family_id") != link["family_id"] \
                or header.get("member_id") != link["member_id"] or path.stem != header.get("key"):
            continue
        found.append((path, header, document))
    return found


# Member side: publishing ----------------------------------------------------------------

def copy_database(source: Path, target: Path):
    """A consistent copy of a live library database, read only, with no write-ahead log beside it."""
    src = sqlite3.connect(safe_path(source).as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()


def publish(store, link, member_name):
    """Write <sync>/<family>/<member>.hmfamily from this library's database. Returns the publish time."""
    sync = sync_folder(link["sync"])
    folder = safe_path(sync / link["family_id"])
    folder.mkdir(exist_ok=True)
    staging = safe_path(store.work / f"family-{uuid.uuid4().hex}.sqlite3")
    published_at = now()
    try:
        copy_database(store.db_path, staging)
        db = sqlite3.connect(staging)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()
        header = {"kind": "home-manager-family-snapshot", "family_id": link["family_id"], "member_id": link["member_id"],
                  "member_name": member_name, "published_at": published_at, "schema_version": version}
        _seal(safe_path(folder / (link["member_id"] + SNAPSHOT_EXTENSION)), header, staging, key=decode_key(link["key"]), magic=SNAPSHOT_MAGIC)
    finally:
        staging.unlink(missing_ok=True)
    return published_at


def changed_since(store, published_at):
    """Whether the library database was written after the last publish (file times of the database and its log)."""
    if not published_at:
        return True
    latest = max((path.stat().st_mtime for path in (store.db_path, store.db_path.with_name(store.db_path.name + "-wal")) if path.exists()), default=0)
    return latest > datetime.fromisoformat(published_at).timestamp()


# Family side ------------------------------------------------------------------------

def prepare_copy(path: Path, name):
    """Bring an imported copy to this app's schema. A copy from a newer app version is refused, never guessed at."""
    db = sqlite3.connect(path, isolation_level=None)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version > MIGRATIONS[-1][0]:
            raise ValueError(f"{name}'s data comes from a newer Home Manager. Update Home Manager on this computer to include it.")
        if version < 1:
            raise ValueError(f"{name}'s copy is not a Home Manager library.")
        apply_migrations(db, version)
        db.execute("PRAGMA journal_mode=DELETE")
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise ValueError(f"{name}'s copy failed its integrity check.")
    finally:
        db.close()


class FamilyFolder:
    def __init__(self, root: Path):
        self.root = safe_path(root)
        marker = safe_path(self.root / FAMILY_MARKER)
        if not marker.is_file() or marker.read_text(encoding="utf-8") != MARKER_TEXT:
            raise PathError("That folder is not a Home Manager family folder.")
        self.lock = DirectoryLock(self.root)
        try:
            self.file = safe_path(self.root / "family.json")
            self.members_dir = safe_path(self.root / "members")
            self.view_dir = safe_path(self.root / "view")
            self.members_dir.mkdir(exist_ok=True)
            self.view_dir.mkdir(exist_ok=True)
            self.mutex = threading.RLock()
            self.data = json.loads(self.file.read_text(encoding="utf-8"))
            decode_key(self.data["key"])
        except BaseException:
            self.lock.close()
            raise

    @classmethod
    def create(cls, root: Path, name, sync: Path):
        root = safe_path(root)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise PathError("Choose a new or empty folder for the family.")
        root.mkdir(parents=True, exist_ok=True)
        data = {"family_id": uuid.uuid4().hex, "name": clean_name(name, "Family"), "key": encode_key(secrets.token_bytes(32)),
                "sync": str(sync), "created_at": now(), "members": [], "adjustments": {"joint_accounts": [], "transfers": []}}
        write_atomic(root / "family.json", json.dumps(data, indent=2))
        (root / FAMILY_MARKER).write_text(MARKER_TEXT, encoding="utf-8")
        return cls(root)

    def close(self):
        self.lock.close()

    def save(self):
        with self.mutex:
            write_atomic(self.file, json.dumps(self.data, indent=2))

    @property
    def key(self):
        return decode_key(self.data["key"])

    def member(self, member_id):
        for member in self.data["members"]:
            if member["member_id"] == member_id:
                return member
        raise ValueError("Family member not found.")

    def add_member(self, name, source, profile_id=None):
        with self.mutex:
            if len(self.data["members"]) >= MAX_MEMBERS:
                raise ValueError(f"A family can have at most {MAX_MEMBERS} members.")
            if profile_id and any(member.get("profile_id") == profile_id for member in self.data["members"]):
                raise ValueError("That profile is already a member of this family.")
            member = {"member_id": uuid.uuid4().hex[:12], "name": clean_name(name, "Member"), "source": source, "profile_id": profile_id,
                      "added_at": now(), "as_of": None, "imported_at": None, "status": "waiting", "error": None, "signature": None}
            self.data["members"].append(member)
            self.save()
            return member

    def remove_member(self, member_id):
        with self.mutex:
            member = self.member(member_id)
            self.data["members"].remove(member)
            self.save()
            for folder in (self.members_dir, self.view_dir):
                (folder / f"{member_id}.sqlite3").unlink(missing_ok=True)
            self.rebuild_views()
            return member

    def summary(self):
        with self.mutex:
            return {"family_id": self.data["family_id"], "name": self.data["name"], "sync": self.data["sync"], "folder": str(self.root),
                    "members": [{key: member.get(key) for key in ("member_id", "name", "source", "profile_id", "as_of", "imported_at", "status", "error")}
                                for member in self.data["members"]],
                    "adjustments": self.data.get("adjustments") or {"joint_accounts": [], "transfers": []}}

    # Importing ----------------------------------------------------------------------

    def refresh(self, local_folders, work=None):
        """Import every member whose data changed. local_folders maps profile id -> library folder for members on this computer."""
        work = work or Work.detached()
        changed = False
        for member in list(self.data["members"]):
            work.check()
            try:
                if member["source"] == "local":
                    changed |= self._import_local(member, local_folders.get(member.get("profile_id")))
                else:
                    changed |= self._import_snapshot(member)
            except (ValueError, OSError, sqlite3.Error, MigrationError) as exc:
                log_failure(log, "family import", exc, member=member.get("member_id"))
                member.update(status="failed", error=str(exc) if isinstance(exc, ValueError) else "The member's copy could not be read.")
                changed = True
        with self.mutex:
            if changed:
                self.rebuild_views()
            self.save()
        return self.summary()

    def _install(self, member, staged: Path, as_of, signature):
        prepare_copy(staged, member["name"])
        os.replace(staged, self.members_dir / f"{member['member_id']}.sqlite3")
        member.update(as_of=as_of, imported_at=now(), status="current", error=None, signature=signature)
        return True

    def _import_local(self, member, folder):
        if not folder:
            member.update(status="failed", error="This member's profile is no longer on this computer.")
            return True
        database = safe_path(Path(folder) / "inventory.sqlite3")
        if not database.is_file():
            member.update(status="waiting", error=None)
            return False
        signature = [[path.stat().st_size, path.stat().st_mtime_ns] for path in (database, database.with_name(database.name + "-wal")) if path.exists()]
        if signature == member.get("signature") and (self.members_dir / f"{member['member_id']}.sqlite3").exists():
            return False
        staged = safe_path(self.members_dir / f"{member['member_id']}.importing")
        try:
            copy_database(database, staged)
            return self._install(member, staged, now(), signature)
        finally:
            staged.unlink(missing_ok=True)

    def _import_snapshot(self, member):
        source = safe_path(Path(self.data["sync"]) / self.data["family_id"] / (member["member_id"] + SNAPSHOT_EXTENSION))
        if not source.is_file():
            if member["status"] != "current":
                member.update(status="waiting", error=None)
            return False
        info = source.stat()
        signature = [info.st_size, info.st_mtime_ns]
        if signature == member.get("signature") and (self.members_dir / f"{member['member_id']}.sqlite3").exists():
            return False
        if info.st_size > MAX_SNAPSHOT:
            raise ValueError(f"{member['name']}'s copy is larger than Home Manager accepts.")
        staged = safe_path(self.members_dir / f"{member['member_id']}.importing")
        raw, reader, header = _open(source, key=self.key, magic=SNAPSHOT_MAGIC, noun="family")
        try:
            if header.get("family_id") != self.data["family_id"] or header.get("member_id") != member["member_id"]:
                raise ValueError(f"The copy for {member['name']} belongs to a different family or member.")
            total = 0
            with open(staged, "wb") as target:
                while chunk := reader.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_SNAPSHOT:
                        raise ValueError(f"{member['name']}'s copy is larger than Home Manager accepts.")
                    target.write(chunk)
            raw.close()
            return self._install(member, staged, header.get("published_at"), signature)
        finally:
            raw.close()
            staged.unlink(missing_ok=True)

    # Family adjustments -----------------------------------------------------------------

    def rebuild_views(self):
        """Fresh adjusted copies of every imported member. Only the family's own copies are changed."""
        with self.mutex:
            for stale in self.view_dir.glob("*.sqlite3"):
                stale.unlink()
            present = [member for member in self.data["members"] if (self.members_dir / f"{member['member_id']}.sqlite3").exists()]
            for member in present:
                shutil.copyfile(self.members_dir / f"{member['member_id']}.sqlite3", self.view_dir / f"{member['member_id']}.sqlite3")
            connections = {member["member_id"]: sqlite3.connect(self.view_dir / f"{member['member_id']}.sqlite3") for member in present}
            try:
                names = {member["member_id"]: member["name"] for member in present}
                joint = self._joint_accounts(present, connections, names)
                transfers = self._transfers(present, connections, names)
                for db in connections.values():
                    db.commit()
            finally:
                for db in connections.values():
                    db.close()
            self.data["adjustments"] = {"joint_accounts": joint, "transfers": transfers[:50], "transfer_count": len(transfers)}

    @staticmethod
    def _joint_accounts(present, connections, names):
        """An account two members both recorded (same institution, type and last four digits) counts once: for the member
        listed first. The others' copies leave its transactions, statements and the receipts matched to them out."""
        owners, joint = {}, {}
        for member in present:
            db = connections[member["member_id"]]
            for account_id, institution, kind, last_four, display in db.execute(
                    "SELECT id,institution,account_type,account_last_four,display_name FROM accounts WHERE account_last_four IS NOT NULL"):
                key = (" ".join(institution.lower().split()), kind, last_four)
                if key not in owners:
                    owners[key] = member["member_id"]
                    continue
                if owners[key] == member["member_id"]:
                    continue
                # A receipt the family shared stays: it is this person's own part, not a copy of the owner's.
                db.execute("UPDATE receipts SET review_status='rejected' WHERE id IN (SELECT l.receipt_id FROM transaction_receipt_links l "
                           "JOIN transactions t ON t.id=l.transaction_id WHERE t.account_id=? AND l.review_status<>'rejected') "
                           "AND id NOT IN (SELECT record_id FROM record_shares WHERE record_type='receipt')", (account_id,))
                db.execute("UPDATE transactions SET review_status='rejected' WHERE account_id=?", (account_id,))
                db.execute("UPDATE statements SET review_status='rejected' WHERE account_id=?", (account_id,))
                entry = joint.setdefault(key, {"account": display, "institution": institution, "last_four": last_four,
                                               "counted_for": names[owners[key]], "also_recorded_by": []})
                entry["also_recorded_by"].append(names[member["member_id"]])
        return list(joint.values())

    @staticmethod
    def _transfers(present, connections, names):
        """Money one member sent another: the same amount leaving one member's account and arriving in another's
        within three days, where either line reads like a transfer or names the other member. Both become transfers."""
        outgoing, incoming = [], []
        for member in present:
            for row in connections[member["member_id"]].execute(
                    "SELECT id,posted_date,amount_minor,currency,description_raw FROM transactions WHERE review_status<>'rejected' "
                    "AND transaction_type NOT IN ('transfer','payment') AND amount_minor<>0"):
                item = {"member": member["member_id"], "id": row[0], "date": row[1], "amount": row[2], "currency": row[3], "text": row[4] or ""}
                (outgoing if row[2] < 0 else incoming).append(item)
        by_amount = {}
        for item in incoming:
            by_amount.setdefault((item["currency"], item["amount"]), []).append(item)
        first_names = {member_id: name.split()[0].lower() for member_id, name in names.items()}
        pairs, used = [], set()
        for sent in sorted(outgoing, key=lambda item: (item["date"], item["id"])):
            best = None
            for received in by_amount.get((sent["currency"], -sent["amount"]), []):
                if received["member"] == sent["member"] or (received["member"], received["id"]) in used:
                    continue
                gap = abs((date.fromisoformat(received["date"]) - date.fromisoformat(sent["date"])).days)
                if gap > TRANSFER_DAYS:
                    continue
                text = f"{sent['text']} {received['text']}"
                named = (re.search(rf"\b{re.escape(first_names[received['member']])}\b", sent["text"], re.IGNORECASE)
                         or re.search(rf"\b{re.escape(first_names[sent['member']])}\b", received["text"], re.IGNORECASE))
                if not (TRANSFER_WORDS.search(text) or named):
                    continue
                if best is None or gap < best[0]:
                    best = (gap, received)
            if best:
                received = best[1]
                used.add((received["member"], received["id"]))
                for item in (sent, received):
                    connections[item["member"]].execute("UPDATE transactions SET transaction_type='transfer' WHERE id=?", (item["id"],))
                pairs.append({"from": names[sent["member"]], "to": names[received["member"]], "date": sent["date"],
                              "amount": money(-sent["amount"], sent["currency"])})
        return pairs

    def views(self):
        """(member, path) for each member with an imported copy, in family order."""
        with self.mutex:
            return [(member, self.view_dir / f"{member['member_id']}.sqlite3") for member in self.data["members"]
                    if (self.view_dir / f"{member['member_id']}.sqlite3").exists()]
