"""App-owned library publication. External source paths are never write targets."""

from datetime import date
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import shutil
import threading
import unicodedata
import uuid

from .folders import FOLDERS, LIBRARY_FOLDERS, validate_folder
from .formats import SUPPORTED, extension as file_extension
from .paths import PathError, path_key, safe_path, signature, source_reader
from .storage import digest_file, now

TYPE_FOLDERS = {"receipt": "Receipts", "bank_statement": "Bank_Statements",
                "credit_card_statement": "Credit_Card_Statements", "bill": "Bills",
                "income": "Income", "investment_statement": "Investments", "loan_document": "Loans",
                "insurance_document": "Insurance", "housing_document": "Housing", "tax_document": "Taxes"}


def locked(method):
    """Serialize organization; capture, inference and user actions run on separate threads."""
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapper


def iso_date(value):
    """Strict YYYY-MM-DD only; other forms are ambiguous for filing."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def filename(document_id, digest, extension, folder, merchant=None, document_date=None, full_hash=False):
    """Conservative convenience labels; never include original names or account numbers."""
    validate_folder(folder)
    if not isinstance(document_id, int) or document_id < 1 or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid document identity for managed filename.")
    extension = extension.lower()
    if extension not in SUPPORTED:
        raise ValueError("Unsupported managed file extension.")
    components = []
    if document_date:
        if iso_date(document_date) is None:
            raise ValueError("Managed filenames require an unambiguous ISO date.")
        components.append(document_date)
    if merchant:
        # Digits are deliberately excluded: account numbers cannot leak through a label.
        label = "".join(char if char.isalpha() or char in " -_" else " " for char in unicodedata.normalize("NFKC", merchant))
        label = "_".join(label.split()).strip("_-")[:36]
        if label:
            components.append(label)
    components.extend(["Document" if folder == "Unfiled" else folder,
                       digest if full_hash else digest[:16], f"d{document_id}"])
    name = "__".join(components) + extension
    if len(name) > 180 or ".." in name or any(char in name for char in '/\\:'):
        raise ValueError("Managed filename exceeds safe limits.")
    return name


class ManagedLibrary:
    def __init__(self, store):
        self.store = store
        self.lock = threading.RLock()
        self.root = safe_path(store.root / "Library")
        self.root.mkdir(exist_ok=True)
        for folder in LIBRARY_FOLDERS:
            safe_path(self.root / folder).mkdir(exist_ok=True)
        self.inbox = self.root / "Inbox"

    def path(self, relative):
        parts = PurePosixPath(relative).parts
        if (not relative or "\\" in relative or ":" in relative or len(parts) != 2
                or parts[0] not in LIBRARY_FOLDERS or any(part in (".", "..") for part in parts)
                or PurePosixPath(relative).is_absolute() or "/".join(parts) != relative):
            raise PathError("Invalid managed library path.")
        target = safe_path(self.root / parts[0] / parts[1])
        if len(str(target).encode("utf-16-le")) // 2 > 240:
            raise PathError("Managed path exceeds the 240-character limit. Choose a shorter managed root.")
        return target

    def current_file(self, document_id, digest):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM managed_files WHERE document_id=? AND blob_hash=?", (document_id, digest)).fetchone()
        return dict(row) if row else None

    def ensure_capture(self, source, relative, digest):
        with self.store.connection() as db:
            row = db.execute("SELECT id FROM occurrences WHERE source_root=? AND path_key=? AND current_hash=?",
                             (path_key(source), path_key(relative), digest)).fetchone()
        if row:
            self.ensure_document(row["id"], digest)

    @locked
    def ensure_document(self, document_id, digest):
        doc, _ = self.store.document_version(document_id, digest)
        existing = self.current_file(document_id, digest)
        if existing:
            # A re-added identical Inbox file still needs to be consumed safely.
            original = self.path("Inbox/" + doc["relative_path"]) if doc["source_kind"] == "inbox" else None
            if original and existing["folder"] != "Inbox" and original.exists():
                if digest_file(original) != digest:
                    return
                self.organize(document_id, digest, existing["folder"], "Repeated Inbox capture.", source_override="Inbox/" + doc["relative_path"])
            return
        if doc["deleted_at"]:
            return
        if doc["source_kind"] == "inbox":
            relative = "Inbox/" + doc["relative_path"]
            path = self.path(relative)
            if path.exists():
                if digest_file(path) != digest:
                    raise ValueError("Inbox file changed after capture. Rescan it before organizing.")
                with self.store.connection() as db:
                    prior = db.execute("SELECT document_id,blob_hash FROM managed_files WHERE relative_path=?", (relative,)).fetchone()
                if prior and prior["blob_hash"] != digest:
                    # Inbox name was reused/edited. Materialize the old version from its
                    # immutable blob, never rename the newly captured bytes as the old version.
                    with self.store.connection() as db:
                        db.execute("UPDATE managed_organization_intents SET status='superseded',updated_at=? WHERE document_id=? AND blob_hash=? AND status IN ('pending','blocked')", (now(), prior["document_id"], prior["blob_hash"]))
                    self.organize(prior["document_id"], prior["blob_hash"], "Unfiled", "Preserved previous Inbox version.", action="archive")
                with self.store.connection() as db:
                    db.execute("INSERT INTO managed_files VALUES(?,?,?,?,?,?)", (document_id, digest, relative, "Inbox", "Awaiting classification or a manual folder choice.", now()))
                return
        with self.store.connection() as db:
            manual = db.execute("SELECT folder FROM document_folders WHERE document_id=? AND blob_hash=?", (document_id, digest)).fetchone()
            historical = db.execute(self.store.library_query() + "SELECT folder FROM library WHERE id=?", (document_id,)).fetchone()
        folder = manual["folder"] if manual else historical["folder"] if historical and historical["folder"] != "Inbox" else "Unfiled"
        self.organize(document_id, digest, folder, "Migrated folder assignment." if folder != "Unfiled" or manual else "Awaiting supported classification and identifying metadata.")

    @locked
    def organize(self, document_id, digest, folder, reason, *, action="capture", merchant=None, document_date=None, source_override=None):
        validate_folder(folder)
        doc, _ = self.store.document_version(document_id, digest)
        if doc["current_hash"] != digest and action != "archive":
            raise RuntimeError("Document version changed. Refresh before organizing.")
        if doc["deleted_at"]:
            raise ValueError("Restore the document before organizing it.")
        if digest_file(self.store.blob_path(digest)) != digest:
            raise ValueError("Preserved evidence failed its integrity check. No library file was moved.")
        existing = self.current_file(document_id, digest)
        if source_override and (doc["source_kind"] != "inbox" or source_override != "Inbox/" + doc["relative_path"]):
            raise ValueError("Only the captured Inbox file may supply an organization source.")
        source = None if action == "archive" else source_override or (existing["relative_path"] if existing else None)
        extension = file_extension(doc["relative_path"])
        name = filename(document_id, digest, extension, folder, merchant, document_date)
        target = existing["relative_path"] if source_override and existing else folder + "/" + name
        # Deterministic fallback for the short-hash collision case; never overwrite.
        if self.path(target).exists() and target != source and digest_file(self.path(target)) != digest:
            target = folder + "/" + filename(document_id, digest, extension, folder, merchant, document_date, full_hash=True)
        with self.store.connection() as db:
            pending = db.execute("SELECT id,target_path FROM managed_organization_intents WHERE document_id=? AND blob_hash=? AND status IN ('pending','blocked')", (document_id, digest)).fetchone()
            if pending:
                if pending["target_path"] != target:
                    raise RuntimeError("A previous organization needs recovery before choosing another destination.")
                intent_id = pending["id"]
            else:
                intent_id = uuid.uuid4().hex
                db.execute("INSERT INTO managed_organization_intents VALUES(?,?,?,?,?,?,?,?,'pending',?,?,NULL)",
                           (intent_id, document_id, digest, source, target, folder, reason, action, now(), now()))
        self.execute(intent_id)
        return intent_id

    @locked
    def execute(self, intent_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM managed_organization_intents WHERE id=?", (intent_id,)).fetchone()
        if not row:
            raise ValueError("Managed organization intent not found.")
        intent = dict(row)
        if intent["status"] in ("succeeded", "superseded"):
            return
        stage = safe_path(self.store.work / (intent_id + ".library-stage"))
        try:
            doc, _ = self.store.document_version(intent["document_id"], intent["blob_hash"])
            if (doc["current_hash"] != intent["blob_hash"] and intent["action"] != "archive") or doc["deleted_at"]:
                with self.store.connection() as db:
                    db.execute("UPDATE managed_organization_intents SET status='superseded',updated_at=? WHERE id=?", (now(), intent_id))
                return
            digest = intent["blob_hash"]
            blob = self.store.blob_path(digest)
            if digest_file(blob) != digest:
                raise ValueError("Preserved evidence failed its integrity check.")
            target = self.path(intent["target_path"])
            source = self.path(intent["source_path"]) if intent["source_path"] else None
            if source and source.exists() and digest_file(source) != digest:
                raise ValueError("Managed file was edited after capture. It was not overwritten or moved; preserve the edit and rescan Inbox or restore this copy before retrying.")
            if not target.exists():
                if source and source.exists() and os.name == "nt":
                    # Windows rename fails if destination exists. No replace/overwrite.
                    before = signature(source.stat())
                    with source_reader(source) as reader:
                        if hashlib.file_digest(reader, "sha256").hexdigest() != digest:
                            raise ValueError("Managed file changed before organization.")
                    safe_path(source)
                    safe_path(target)
                    if signature(source.stat()) != before:
                        raise ValueError("Managed file changed before organization.")
                    os.rename(source, target)
                else:
                    # Independent bytes: Library edits must never modify a preserved blob.
                    # A crashed publication can leave this stage hard-linked to a file
                    # later renamed by the user. Never truncate that inode on retry.
                    stage.unlink(missing_ok=True)
                    with source_reader(blob) as reader, open(stage, "xb") as writer:
                        shutil.copyfileobj(reader, writer, 1024 * 1024)
                        writer.flush()
                        os.fsync(writer.fileno())
                    if digest_file(stage) != digest:
                        raise ValueError("Managed copy failed verification.")
                    safe_path(target)
                    os.link(stage, target)  # Atomic no-clobber publication on local filesystems.
            if digest_file(target) != digest:
                raise ValueError("Managed destination contains different bytes. It was not overwritten.")
            if source and source != target and source.exists():
                # Covers POSIX publication and recovery after publication before cleanup.
                safe_path(source)
                if digest_file(source) != digest:
                    raise ValueError("Managed source changed. Both files were preserved for review.")
                source.unlink()
            self.finish(intent)
            stage.unlink(missing_ok=True)
        except (OSError, ValueError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else "Managed organization could not finish. Check file locks, permissions and disk space; preserved evidence is safe."
            with self.store.connection() as db:
                db.execute("UPDATE managed_organization_intents SET status='blocked',error=?,updated_at=? WHERE id=?", (message, now(), intent_id))
            raise ValueError(message) from exc

    def finish(self, intent):
        with self.store.connection() as db:
            db.execute("INSERT INTO managed_files VALUES(?,?,?,?,?,?) ON CONFLICT(document_id,blob_hash) DO UPDATE SET relative_path=excluded.relative_path,folder=excluded.folder,reason=excluded.reason,updated_at=excluded.updated_at",
                       (intent["document_id"], intent["blob_hash"], intent["target_path"], intent["folder"], intent["reason"], now()))
            db.execute("INSERT OR IGNORE INTO managed_organization_events(intent_id,document_id,blob_hash,source_path,target_path,action,created_at) VALUES(?,?,?,?,?,?,?)",
                       (intent["id"], intent["document_id"], intent["blob_hash"], intent["source_path"], intent["target_path"], intent["action"], now()))
            if intent["action"] == "manual":
                db.execute("INSERT INTO document_folders VALUES(?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET blob_hash=excluded.blob_hash,folder=excluded.folder,updated_at=excluded.updated_at",
                           (intent["document_id"], intent["blob_hash"], intent["folder"], now()))
                db.execute("INSERT INTO library_events(document_id,blob_hash,action,detail,created_at) VALUES(?,?,'move',?,?)", (intent["document_id"], intent["blob_hash"], intent["folder"], now()))
            db.execute("UPDATE occurrences SET source_status='organized' WHERE id=? AND current_hash=? AND source_kind='inbox'", (intent["document_id"], intent["blob_hash"]))
            db.execute("UPDATE managed_organization_intents SET status='succeeded',error=NULL,updated_at=? WHERE id=?", (now(), intent["id"]))

    @locked
    def file_classified(self, document_id, digest, document_type, merchant, dated, reason):
        """The one filing rule: a supported, evidence-cited type plus unambiguous merchant/issuer and
        ISO date files the copy; anything else goes to Unfiled. A manual choice always wins, and an
        inconclusive later result never undoes an earlier evidence-backed filing."""
        with self.store.connection() as db:
            if db.execute("SELECT 1 FROM document_folders WHERE document_id=? AND blob_hash=?", (document_id, digest)).fetchone():
                return None
        dated = iso_date(dated)
        if document_type in TYPE_FOLDERS and merchant and dated:
            return self.organize(document_id, digest, TYPE_FOLDERS[document_type], reason, action="classification",
                                 merchant=merchant, document_date=dated)
        existing = self.current_file(document_id, digest)
        if existing and existing["folder"] in FOLDERS:
            return None
        missing = [text for text, known in (("the document type is not confirmed", document_type in TYPE_FOLDERS),
                                            ("the merchant or issuer is not confirmed", bool(merchant)), ("the date is not confirmed", bool(dated))) if not known]
        return self.organize(document_id, digest, "Unfiled", f"Not filed automatically: {'; '.join(missing)}. Choose a folder manually.",
                             action="classification")

    def file_analysis(self, document_id, run):
        """Adapter for the audit-mode analysis; cited facts only."""
        if run["status"] != "succeeded" or not run["result"]:
            return None
        with self.store.connection() as db:
            source = db.execute("SELECT blob_hash,result_json FROM parse_runs WHERE id=?", (run["parse_run_id"],)).fetchone()
        lines = {line["id"]: line["text"] for line in json.loads(source["result_json"])["lines"]}
        output = run["result"]

        def cited(citations):
            return bool(citations) and all(cite["line_id"] in lines and cite["quote"].strip() and cite["quote"] in lines[cite["line_id"]] for cite in citations)

        def fact(kinds):
            if any(item["kind"] in kinds and item["status"] == "ambiguous" for item in output["facts"]):
                return None
            values = {item["value"] for item in output["facts"] if item["kind"] in kinds and item["status"] == "proposed" and item["value"] and cited(item["evidence"])}
            return values.pop() if len(values) == 1 else None

        document_type = output["document_type"]
        date_kind = {"receipt": "purchase_date", "bank_statement": "period_end", "credit_card_statement": "period_end"}.get(document_type, "issue_date")
        review = run.get("review")
        result = (review or {}).get("result") or {}
        # Advisory (Laya) reviews, including failed ones, never block filing until Laya is benchmarked.
        advisory = result.get("advisory") or json.loads((review or {}).get("config_json") or "{}").get("provider") == "laya"
        review_blocks = review and not advisory and (review["status"] != "succeeded" or not result.get("classification_supported"))
        supported = cited(output.get("classification_evidence", [])) and not review_blocks
        return self.file_classified(document_id, source["blob_hash"], document_type if supported else "unknown",
                                    fact(("merchant",)) or fact(("issuer",)), fact((date_kind,)),
                                    "Filed from evidence-linked analysis; financial values remain unreviewed.")

    @locked
    def recover(self):
        with self.store.connection() as db:
            pending = [row[0] for row in db.execute("SELECT id FROM managed_organization_intents WHERE status IN ('pending','blocked') ORDER BY created_at")]
        for intent in pending:
            try:
                self.execute(intent)
            except (ValueError, OSError):
                pass  # Durable blocked error remains visible; never guess a replacement path.
        with self.store.connection() as db:
            missing = list(db.execute("SELECT o.id,o.current_hash FROM occurrences o LEFT JOIN managed_files m ON m.document_id=o.id AND m.blob_hash=o.current_hash WHERE m.document_id IS NULL AND o.deleted_at IS NULL"))
        for doc in missing:
            try:
                self.ensure_document(doc["id"], doc["current_hash"])
            except (ValueError, OSError, RuntimeError):
                pass
