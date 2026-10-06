"""Family folders, invites and member snapshots.

A family view never opens a member's live library for writing. Each member's computer pushes an
encrypted copy of its database (no documents) to the family computer's hub over Tailscale
(app/family_hub.py, app/family_client.py). Members on the same computer are copied straight from
their library folder.

Family folder (on the computer that shows the family view):
  .home-manager-family        marker
  family.json                 family id, name, key, members (with their hub token's SHA-256, the last
                              accepted copy's seq) and their import state
  members/<member>.sqlite3    the last imported copy of each member's database
  view/<member>.sqlite3       those copies with family adjustments: a joint account counted once,
                              transfers between members left out of spending and income
  incoming/<member>.hmfamily  a copy being received by the hub
  outbox/to-<member>/<key>.hmdelivery   records the family sent this member, until they acknowledge them
  blobs/<hh>/<hash>.hmblob    the documents members' records cite, sealed with the family key (content-addressed)

Snapshots are encrypted with the family's random 32-byte key (library/share.py, AES-256-GCM); invites
carry that key, the hub's address and the member's token, and are encrypted with a passphrase the
family owner chooses.
"""

from datetime import date, datetime
import hashlib
import hmac
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
SNAPSHOT_MAGIC, INVITE_MAGIC, DELIVERY_MAGIC, BLOB_MAGIC = b"HMFAMLY1", b"HMINVIT2", b"HMDELIV1", b"HMBLOB01"
OLD_INVITE_MAGIC = b"HMINVIT1"  # Invites from before the hub: they name a sync folder, not the hub.
SNAPSHOT_EXTENSION, INVITE_EXTENSION, DELIVERY_EXTENSION, BLOB_EXTENSION = ".hmfamily", ".hminvite", ".hmdelivery", ".hmblob"
# A copy's header lists every family correction the member received (about 60 bytes each), hence its larger limit.
MAX_HEADER, MAX_SNAPSHOT, MAX_INVITE = 4 * 1024 ** 2, 4 * 1024 ** 3, 65536
MAX_BLOB = 1024 ** 3  # One document. The scanner takes files up to 256 MiB; this leaves room, and caps what a token can send.
HASH = re.compile(r"^[0-9a-f]{64}$")
MAX_MEMBERS = 20
HEX_ID = re.compile(r"^[0-9a-f]{12,32}$")  # Family ids, member ids and delivery keys.
# Words banks print on money moved between people rather than spent.
TRANSFER_WORDS = re.compile(r"\b(transfer|xfer|zelle|venmo|paypal|cash ?app|apple cash|wire|p2p|interac)\b", re.IGNORECASE)
TRANSFER_DAYS = 3


def token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CopyRefused(ValueError):
    """A member's copy the hub won't install; status is the HTTP status the hub answers with."""

    def __init__(self, status, message, **extra):
        super().__init__(message)
        self.status, self.extra = status, extra


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

def write_invite(family, member, destination: Path, passphrase, hub, token):
    """hub is the family computer's "100.x.y.z:port"; token is this member's hub token (only its hash stays here)."""
    check_passphrase(passphrase)
    if not destination.is_dir():
        raise PathError("Choose an existing folder for the invite file.")
    payload = {"kind": "home-manager-family-invite", "family_id": family["family_id"], "family_name": family["name"],
               "member_id": member["member_id"], "member_name": member["name"], "key": family["key"], "hub": hub, "token": token,
               "created_at": now()}
    target = safe_path(destination / f"{_name_part(family['name'])} - {_name_part(member['name'])}{INVITE_EXTENSION}")
    return _seal(target, payload, passphrase=passphrase, magic=INVITE_MAGIC)


def read_invite(path: Path, passphrase):
    check_passphrase(passphrase)
    path = safe_path(path)
    if not path.is_file() or path.stat().st_size > MAX_INVITE:
        raise PathError("Choose the .hminvite file itself.")
    with open(path, "rb") as raw:
        if raw.read(len(OLD_INVITE_MAGIC)) == OLD_INVITE_MAGIC:
            raise ShareError("This invite is from before the family computer shared over Tailscale. Ask the family computer for a new invite.")
    raw, reader, invite = _open(path, passphrase=passphrase, magic=INVITE_MAGIC, noun="invite")
    try:
        reader.read()  # Authenticates the final chunk.
    finally:
        raw.close()
    if invite.get("kind") != "home-manager-family-invite" or not all(isinstance(invite.get(key), str) for key in ("family_id", "member_id", "key", "hub", "token")) \
            or not HEX_ID.match(invite["family_id"]) or not HEX_ID.match(invite["member_id"]):
        raise ShareError("This invite is not one Home Manager can use.")
    decode_key(invite["key"])
    return invite


# Family inbox deliveries (finance/family_routing.py) ----------------------------------------
# A record the family confirmed travels to each person as <family>/outbox/to-<member>/<key>.hmdelivery: the record, the
# person's part when shared and the document itself, encrypted with the family key. The member pulls it from the hub and
# acknowledges it, which deletes it (a member on this computer reads the folder directly). A newer file for the same key
# (a reassignment, or a retraction) replaces an older one that was not imported yet.

def delivery_folder(family_root: Path, member_id):
    if not HEX_ID.match(member_id):
        raise ValueError("Family member not found.")
    return safe_path(Path(family_root) / "outbox" / f"to-{member_id}")


def write_delivery(family_root: Path, family_id, key, member_id, delivery, document=None):
    folder = delivery_folder(family_root, member_id)
    folder.mkdir(parents=True, exist_ok=True)
    header = {"kind": "home-manager-family-delivery", "family_id": family_id, "member_id": member_id, "created_at": now(), **delivery}
    return _seal(safe_path(folder / (delivery["key"] + DELIVERY_EXTENSION)), header, document, key=decode_key(key), magic=DELIVERY_MAGIC)


def open_delivery(path: Path, link):
    """(delivery, document bytes or None) from one sealed delivery file, or ValueError when it is damaged or meant for
    another family, member or key."""
    if path.stat().st_size > MAX_SNAPSHOT:
        raise ValueError("The delivery is larger than Home Manager accepts.")
    raw, reader, header = _open(path, key=decode_key(link["key"]), magic=DELIVERY_MAGIC, noun="family")
    try:
        document = reader.read() or None
    finally:
        raw.close()
    if header.get("kind") != "home-manager-family-delivery" or header.get("family_id") != link["family_id"] \
            or header.get("member_id") != link["member_id"] or not HEX_ID.match(str(header.get("key"))):
        raise ValueError("The delivery belongs to a different family or member.")
    return header, document


def read_deliveries(family_root: Path, link):
    """[(path, delivery, document bytes or None)] waiting in the family folder for a member on this computer, oldest first.
    Files that fail to open are skipped (the family may still be writing them); a file for another family or member is refused."""
    try:
        folder = delivery_folder(family_root, link["member_id"])
    except (PathError, ValueError):
        return []
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*" + DELIVERY_EXTENSION), key=lambda item: item.stat().st_mtime_ns):
        try:
            header, document = open_delivery(path, link)
        except (ValueError, OSError):
            continue
        if path.stem == header["key"]:
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


def seal_copy(store, link, target: Path, seq, member_name, birth_year=None):
    """Seal this library's database into target (a .hmfamily file). Returns the publish time. seq rises with every copy, so
    the hub refuses a replayed older one. The birth year (Settings) goes in the sealed header, for the family's tax returns
    (ages count on a return)."""
    staging = safe_path(store.work / f"family-{uuid.uuid4().hex}.sqlite3")
    published_at = now()
    try:
        copy_database(store.db_path, staging)
        db = sqlite3.connect(staging)
        try:
            version = db.execute("PRAGMA user_version").fetchone()[0]
        finally:
            db.close()
        # corrections: what became of each family correction received here, so the family's "Waiting" tags clear.
        header = {"kind": "home-manager-family-snapshot", "family_id": link["family_id"], "member_id": link["member_id"], "seq": seq,
                  "member_name": member_name, "published_at": published_at, "schema_version": version, "birth_year": birth_year,
                  "corrections": received_corrections(staging)}
        _seal(target, header, staging, key=decode_key(link["key"]), magic=SNAPSHOT_MAGIC)
    finally:
        staging.unlink(missing_ok=True)
    return published_at


# Tables whose rows cite a preserved document: the records themselves, and the evidence linking records to documents.
CITING_TABLES = ("financial_evidence_links", "receipts", "statements", "bills", "income_records", "assets", "tax_forms",
                 "transaction_imports", "investment_confirmations", "investment_events", "investment_valuations")


def cited_blobs(store):
    """The content hashes this library's records cite, sorted. Only these documents go to the family."""
    found = set()
    with store.connection() as db:
        for table in CITING_TABLES:
            found.update(row[0] for row in db.execute(f"SELECT DISTINCT blob_hash FROM {table} WHERE blob_hash IS NOT NULL"))
    return sorted(digest for digest in found if HASH.match(digest))


def seal_blob(store, link, digest, target: Path):
    """Seal one preserved document for the family. The header names the family, member and hash, which the hub checks."""
    header = {"kind": "home-manager-family-blob", "family_id": link["family_id"], "member_id": link["member_id"], "hash": digest}
    return _seal(target, header, store.blob_path(digest), key=decode_key(link["key"]), magic=BLOB_MAGIC)


def received_corrections(database: Path):
    """{key: status} of the family corrections a library database received (finance/family_corrections.py)."""
    db = sqlite3.connect(safe_path(database).as_uri() + "?mode=ro", uri=True, timeout=15)
    try:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='family_corrections'").fetchone():
            return {}
        return {key: status for key, status in db.execute("SELECT key,status FROM family_corrections WHERE direction='received'")}
    finally:
        db.close()


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
    def create(cls, root: Path, name):
        root = safe_path(root)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise PathError("Choose a new or empty folder for the family.")
        root.mkdir(parents=True, exist_ok=True)
        data = {"family_id": uuid.uuid4().hex, "name": clean_name(name, "Family"), "key": encode_key(secrets.token_bytes(32)),
                "created_at": now(), "members": [], "adjustments": {"joint_accounts": [], "transfers": []}}
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
            shutil.rmtree(delivery_folder(self.root, member_id), ignore_errors=True)
            self.rebuild_views()
            return member

    def summary(self):
        with self.mutex:
            return {"family_id": self.data["family_id"], "name": self.data["name"], "folder": str(self.root), "documents_bytes": self.blob_size(),
                    "members": [{key: member.get(key) for key in ("member_id", "name", "source", "profile_id", "as_of", "imported_at", "status", "error")}
                                for member in self.data["members"]],
                    "adjustments": self.data.get("adjustments") or {"joint_accounts": [], "transfers": []}}

    # Importing ----------------------------------------------------------------------

    def refresh(self, local_folders, work=None):
        """Import every member on this computer whose data changed. local_folders maps profile id -> library folder.
        Members on other computers arrive through the hub (import_copy)."""
        work = work or Work.detached()
        changed = False
        with self.mutex:  # The hub may be installing another member's copy meanwhile.
            for member in list(self.data["members"]):
                work.check()
                if member["source"] != "local":
                    continue
                try:
                    changed |= self._import_local(member, local_folders.get(member.get("profile_id")))
                except (ValueError, OSError, sqlite3.Error, MigrationError) as exc:
                    log_failure(log, "family import", exc, member=member.get("member_id"))
                    member.update(status="failed", error=str(exc) if isinstance(exc, ValueError) else "The member's copy could not be read.")
                    changed = True
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
            self.acknowledge(member["member_id"], received_corrections(staged))
            return self._install(member, staged, now(), signature)
        finally:
            staged.unlink(missing_ok=True)

    # Hub (app/family_hub.py): tokens, copies and deliveries --------------------------------

    def new_token(self, member_id):
        """A fresh hub token for a member on another computer, returned once; only its SHA-256 is kept. Their old token stops
        working, and the next copy may start again from seq 1 (a re-join starts a new sequence)."""
        token = secrets.token_urlsafe(32)
        with self.mutex:
            self.member(member_id).update(token_sha256=token_digest(token), last_seq=0)
            self.save()
        return token

    def token_member(self, member_id, token):
        """The member this token belongs to, if it is member_id's, else None. Checked against family.json as it is now (this
        process holds the folder's lock, so the data in memory is the file), so a removed member or a new invite counts at once."""
        digest = token_digest(token)
        with self.mutex:
            found = next((member for member in self.data["members"]
                          if hmac.compare_digest(str(member.get("token_sha256") or ""), digest)), None)
        return found if found is not None and found["member_id"] == member_id and found["source"] == "remote" else None

    def import_copy(self, member_id, source: Path):
        """Install a sealed copy the hub received. It must be this family's, for this member, with a seq above the last one
        accepted (a replayed copy is refused). Returns the member's new state."""
        member = self.member(member_id)
        staged = safe_path(self.members_dir / f"{member_id}-{uuid.uuid4().hex[:8]}.importing")
        raw, reader, header = _open(source, key=self.key, magic=SNAPSHOT_MAGIC, noun="family")
        try:
            if header.get("kind") != "home-manager-family-snapshot" or header.get("family_id") != self.data["family_id"] \
                    or header.get("member_id") != member_id:
                raise CopyRefused(403, "This copy belongs to a different family or member.")
            seq = header.get("seq")
            if not isinstance(seq, int) or isinstance(seq, bool) or seq <= (member.get("last_seq") or 0):
                raise CopyRefused(409, "The family computer already has this copy or a newer one.", last_seq=member.get("last_seq") or 0)
            total = 0
            with open(staged, "wb") as target:
                while chunk := reader.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_SNAPSHOT:
                        raise CopyRefused(413, f"{member['name']}'s copy is larger than Home Manager accepts.")
                    target.write(chunk)
            raw.close()
            try:
                prepare_copy(staged, member["name"])
            except (ValueError, sqlite3.Error, MigrationError) as exc:
                log_failure(log, "family import", exc, member=member_id)
                with self.mutex:
                    member.update(status="failed", error=str(exc) if isinstance(exc, ValueError) else "The member's copy could not be read.")
                    self.save()
                raise CopyRefused(422, member["error"]) from None
            born = header.get("birth_year")
            with self.mutex:
                if seq <= (member.get("last_seq") or 0):  # Another push of a newer copy finished first.
                    raise CopyRefused(409, "The family computer already has this copy or a newer one.", last_seq=member["last_seq"])
                os.replace(staged, self.members_dir / f"{member_id}.sqlite3")
                self.acknowledge(member_id, header.get("corrections"))  # Before the views: an answered correction isn't shown again.
                member.update(as_of=header.get("published_at"), imported_at=now(), status="current", error=None, last_seq=seq,
                              birth_year=born if isinstance(born, int) and not isinstance(born, bool) and 1900 <= born <= 2100 else None)
                self.rebuild_views()
                self.save()
                return {key: member.get(key) for key in ("member_id", "as_of", "imported_at", "status")}
        finally:
            raw.close()
            staged.unlink(missing_ok=True)

    def blob_file(self, digest):
        if not HASH.match(str(digest)):
            raise ValueError("Invalid content hash.")
        return safe_path(self.root / "blobs" / digest[:2] / (digest + BLOB_EXTENSION))

    def missing_blobs(self, digests):
        """The hashes this family doesn't hold yet."""
        return [digest for digest in digests if not self.blob_file(digest).is_file()]

    def store_blob(self, member_id, digest, source: Path):
        """Keep a sealed document a member sent, once its header names this family, member and hash and its decrypted
        bytes hash to it. The sealed bytes are kept as sent: encrypted at rest with the family key."""
        raw, reader, header = _open(source, key=self.key, magic=BLOB_MAGIC, noun="family")
        try:
            if header.get("kind") != "home-manager-family-blob" or header.get("family_id") != self.data["family_id"] \
                    or header.get("member_id") != member_id or header.get("hash") != digest:
                raise CopyRefused(403, "This document belongs to a different family or member.")
            hasher = hashlib.sha256()
            while chunk := reader.read(1024 * 1024):
                hasher.update(chunk)
        finally:
            raw.close()
        if hasher.hexdigest() != digest:
            raise CopyRefused(422, "The document doesn't match its hash.")
        target = self.blob_file(digest)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.mutex:
            if not target.exists():
                size = source.stat().st_size
                os.replace(source, target)
                if "documents_bytes" in self.data:
                    self.data["documents_bytes"] += size
        return {"hash": digest}

    def open_blob(self, digest):
        """(raw file, decrypting reader) for a document the family holds; the caller closes raw. ValueError if it has none."""
        path = self.blob_file(digest)
        if not path.is_file():
            raise ValueError("This document hasn't reached the family computer yet.")
        raw, reader, header = _open(path, key=self.key, magic=BLOB_MAGIC, noun="family")
        if header.get("hash") != digest:
            raw.close()
            raise ValueError("The family's copy of this document is damaged.")
        return raw, reader

    def blob_size(self):
        """Bytes of documents the family holds, counted once and then kept up to date as documents arrive."""
        with self.mutex:
            if "documents_bytes" not in self.data:
                folder = self.root / "blobs"
                self.data["documents_bytes"] = sum(path.stat().st_size for path in folder.glob("*/*" + BLOB_EXTENSION)) if folder.is_dir() else 0
            return self.data["documents_bytes"]

    # Family corrections (finance/family_corrections.py): the 'sent' rows live in the family's own library. -----------

    def _library_db(self):
        """A connection to the family's own library database, or None before it has the corrections table. The hub may
        write here while the family view has the library open; SQLite serialises the writes."""
        path = self.root / "library" / "inventory.sqlite3"
        if not path.is_file():
            return None
        db = sqlite3.connect(path, timeout=15)
        db.row_factory = sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='family_corrections'").fetchone():
            db.close()
            return None
        return db

    def pending_corrections(self):
        """The corrections sent to members that no copy has answered yet, oldest first."""
        db = self._library_db()
        if db is None:
            return []
        try:
            return [dict(row) for row in db.execute("SELECT * FROM family_corrections WHERE direction='sent' AND status='pending' ORDER BY created_at,key")]
        finally:
            db.close()

    def acknowledge(self, member_id, answers):
        """A member's copy says what became of each correction it received ({key: status}); the sent rows follow it."""
        if not isinstance(answers, dict) or not answers:
            return
        db = self._library_db()
        if db is None:
            return
        try:
            with db:
                for key, status in answers.items():
                    if HEX_ID.match(str(key)) and status in ("applied", "conflict", "rejected"):
                        db.execute("UPDATE family_corrections SET status=?,updated_at=? WHERE key=? AND direction='sent' AND member_id=? AND status<>?",
                                   (status, now(), key, member_id, status))
        finally:
            db.close()

    def deliveries(self, member_id):
        """Keys of the deliveries waiting for a member, oldest first."""
        folder = delivery_folder(self.root, member_id)
        if not folder.is_dir():
            return []
        paths = sorted(folder.glob("*" + DELIVERY_EXTENSION), key=lambda item: item.stat().st_mtime_ns)
        return [{"key": path.stem, "size": path.stat().st_size} for path in paths if HEX_ID.match(path.stem)]

    def delivery_path(self, member_id, key):
        if not HEX_ID.match(key):
            raise ValueError("No such delivery.")
        return safe_path(delivery_folder(self.root, member_id) / (key + DELIVERY_EXTENSION))

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
                self._pending_corrections(connections)
                for db in connections.values():
                    db.commit()
            finally:
                for db in connections.values():
                    db.close()
            self.data["adjustments"] = {"joint_accounts": joint, "transfers": transfers[:50], "transfer_count": len(transfers),
                                         "transfers_not_listed": max(len(transfers) - 50, 0)}

    def _pending_corrections(self, connections):
        """Show each correction the family sent and no copy has answered yet, in that member's view copy."""
        from ..finance.family_corrections import apply_to_view
        for correction in self.pending_corrections():
            db = connections.get(correction["member_id"])
            if db is None:
                continue
            db.row_factory = sqlite3.Row  # The ledger's helpers read columns by name.
            try:
                apply_to_view(db, correction["record_type"], correction["record_id"], correction["field"], correction["value"])
            except (ValueError, sqlite3.Error) as exc:
                log_failure(log, "family correction view", exc, member=correction["member_id"])
            finally:
                db.row_factory = None

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
                    "AND transaction_type NOT IN ('transfer','payment','refund') AND amount_minor<>0"):  # A store's refund is never a member's payment.
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
