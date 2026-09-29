"""App-owned library publication: Inbox captures filed into Library folders."""

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

from ..core.folders import FOLDERS, JOB_SECTIONS, LIBRARY_FOLDERS, RETIRED_FOLDERS, validate_folder
from ..core.formats import SUPPORTED
from ..core.formats import extension as file_extension
from ..core.paths import PathError, path_key, safe_path, signature, source_reader
from .storage import digest_file, now

# Category folders file into YYYY/MM subfolders by the document's own date. Inbox (awaiting
# classification) and Unfiled (not confidently identified) stay flat.
DATED_FOLDERS = frozenset(LIBRARY_FOLDERS) - {"Inbox", "Unfiled"}
# Retired folders are only ever a source: their files are read while being moved out.
READABLE_FOLDERS = frozenset(LIBRARY_FOLDERS) | frozenset(RETIRED_FOLDERS)
TYPE_FOLDERS = {"receipt": "Receipts", "bank_statement": "Bank_Statements",
                "credit_card_statement": "Credit_Card_Statements",
                "paystub": "Jobs", "employment_document": "Jobs", "investment_statement": "Investments",
                "investment_confirmation": "Investments", "investment_tax_form": "Taxes", "loan_document": "Loans",
                "insurance_document": "Insurance", "housing_document": "Housing", "tax_document": "Taxes"}
# Jobs types and the section of the employer's folder they file into.
JOB_TYPES = {"paystub": "Paystubs", "employment_document": "Documents"}
# Legal-form words left off an employer's folder name: "Google LLC" files under Google.
LEGAL_SUFFIXES = {"LLC", "L.L.C.", "INC", "INC.", "INCORPORATED", "CORP", "CORP.", "CORPORATION", "CO", "CO.", "COMPANY", "LTD", "LTD.",
                  "LIMITED", "LP", "LLP", "PLC", "GMBH", "PBC"}
# Recognized types that are deliberately not filed or tracked, with why.
UNTRACKED_TYPES = {"bill": "Bills aren't tracked. Move it to a folder if you want to keep it, or delete it."}


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


def clean_label(text):
    """Letters, '-' and '_' only, spaces as '_', at most 36 characters. Digits are deliberately excluded:
    account numbers cannot leak through a label."""
    label = "".join(char if char.isalpha() or char in " -_" else " " for char in unicodedata.normalize("NFKC", text or ""))
    return "_".join(label.split()).strip("_-")[:36]


ONES = ("Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen",
        "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen")
TENS = ("", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety")


def spelled(text):
    """A document name for a file name with its short numbers in words: W-2 -> W-Two. Only one- and two-digit
    numbers are spelled; longer ones (which could be account numbers) are still left out by clean_label."""
    def word(match):
        number = int(match.group(0))
        return ONES[number] if number < 20 else TENS[number // 10] + (ONES[number % 10] if number % 10 else "")
    return re.sub(r"(?<!\d)\d{1,2}(?!\d)", word, text or "")


def is_label(text):
    return bool(text) and len(text) <= 36 and text[0].isalpha() and all(char.isalpha() or char in "-_" for char in text)


def employer_folder(name):
    """An employer's folder name: its name without a trailing legal form, as a label. "Google LLC" -> Google."""
    words = (name or "").replace(",", " ").split()
    while len(words) > 1 and words[-1].upper() in LEGAL_SUFFIXES:
        words.pop()
    return clean_label(" ".join(words))


def directory(folder, document_date=None, employer=None, section=None):
    """Where a folder's files live: Receipts/2026/09 for a dated category document, Jobs/Google/Paystubs/2026/09 for a
    job document with a known employer, else the folder itself."""
    day = iso_date(document_date)
    if folder == "Jobs" and employer and section:
        folder = f"Jobs/{employer}/{section}"
    return f"{folder}/{day[:4]}/{day[5:7]}" if folder.split("/")[0] in DATED_FOLDERS and day else folder


def filename(document_id, digest, extension, folder, merchant=None, document_date=None, full_hash=False, label=None):
    """Conservative convenience labels; never include original names or account numbers. With a label
    (Paystub, Offer_Letter) it stands in for the folder name: 2026-09-15__Paystub__Google__<hash>__d<id>.pdf."""
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
    label = clean_label(label) if label else None
    if label:
        components.append(label)
    if merchant and clean_label(merchant):
        components.append(clean_label(merchant))
    if not label:
        components.append("Document" if folder == "Unfiled" else folder)
    components.extend([digest if full_hash else digest[:16], f"d{document_id}"])
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
        """Folder/name, Category/YYYY/MM/name, or Jobs/Employer/Section/YYYY/MM/name. Nothing else is a library path."""
        parts = PurePosixPath(relative).parts

        def month(year, number):
            return re.fullmatch(r"(19|20)\d{2}", year) and re.fullmatch(r"0[1-9]|1[0-2]", number)

        dated = len(parts) == 4 and parts[0] in DATED_FOLDERS | set(RETIRED_FOLDERS) and month(parts[1], parts[2])
        job = len(parts) == 6 and parts[0] == "Jobs" and is_label(parts[1]) and parts[2] in JOB_SECTIONS and month(parts[3], parts[4])
        if (not relative or "\\" in relative or ":" in relative or not (len(parts) == 2 or dated or job)
                or parts[0] not in READABLE_FOLDERS or any(part in (".", "..") for part in parts)
                or PurePosixPath(relative).is_absolute() or "/".join(parts) != relative):
            raise PathError("Invalid managed library path.")
        target = safe_path(self.root.joinpath(*parts))
        if len(str(target).encode("utf-16-le")) // 2 > 240:
            raise PathError("Managed path exceeds the 240-character limit. Choose a shorter managed root.")
        return target

    def current_file(self, document_id, digest):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM managed_files WHERE document_id=? AND blob_hash=?", (document_id, digest)).fetchone()
        return dict(row) if row else None

    def ensure_capture(self, relative, digest):
        with self.store.connection() as db:
            row = db.execute("SELECT id FROM occurrences WHERE source_root=? AND path_key=? AND current_hash=?",
                             (path_key(self.inbox), path_key(relative), digest)).fetchone()
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

    def employers(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM employers ORDER BY name COLLATE NOCASE")]

    @locked
    def employer(self, name):
        """The employer whose folder this name maps to, created with its Paystubs and Documents folders if new; None
        when the name has no usable letters."""
        folder = employer_folder(name)
        if not is_label(folder):
            return None
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM employers WHERE folder_name=?", (folder,)).fetchone()
            if row is None:
                words = (name or "").replace(",", " ").split()
                while len(words) > 1 and words[-1].upper() in LEGAL_SUFFIXES:
                    words.pop()
                db.execute("INSERT INTO employers(name,folder_name,created_at) VALUES(?,?,?)", (" ".join(words)[:100], folder, now()))
                row = db.execute("SELECT * FROM employers WHERE folder_name=?", (folder,)).fetchone()
        for section in JOB_SECTIONS:
            self.make_directory(safe_path(self.root / "Jobs" / row["folder_name"] / section))
        return dict(row)

    def job_filing(self, document_id, digest):
        with self.store.connection() as db:
            row = db.execute("SELECT f.section,f.label,f.title,e.* FROM job_filings f JOIN employers e ON e.id=f.employer_id "
                             "WHERE f.document_id=? AND f.blob_hash=?", (document_id, digest)).fetchone()
        return dict(row) if row else None

    @locked
    def organize(self, document_id, digest, folder, reason, *, action="capture", merchant=None, document_date=None, source_override=None, keep_name=False,
                 employer=None, section=None, label=None, title=None):
        """employer (an employers row), section and label place a Jobs document: Jobs/<Employer>/<Section>/YYYY/MM,
        named <date>__<label>__<Employer>; title is its printed name for the library. Without them a Jobs document
        keeps its current employer folder, if any."""
        validate_folder(folder)
        if folder == "Jobs" and employer is None and (filed := self.job_filing(document_id, digest)):
            employer, section, label, title = filed, filed["section"], filed["label"], filed["title"]
        if folder != "Jobs" or section not in JOB_SECTIONS:
            employer = section = label = title = None
        doc, _ = self.store.document_version(document_id, digest)
        if doc["current_hash"] != digest and action not in ("archive", "layout"):  # Older versions may be archived or re-foldered.
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
        # A move keeps the document's known date, so its name and its YYYY/MM folder always agree.
        document_date = document_date or (self.filing_date(document_id, digest) if folder in DATED_FOLDERS else None)
        if employer:
            merchant = employer["name"]
        name = (PurePosixPath(existing["relative_path"]).name if keep_name and existing
                else filename(document_id, digest, extension, folder, merchant, document_date, label=label))
        place = directory(folder, document_date, employer and employer["folder_name"], section)
        target = existing["relative_path"] if source_override and existing else place + "/" + name
        # Deterministic fallback for the short-hash collision case; never overwrite.
        if self.path(target).exists() and target != source and digest_file(self.path(target)) != digest:
            target = place + "/" + filename(document_id, digest, extension, folder, merchant, document_date, full_hash=True, label=label)
        with self.store.connection() as db:  # Where in Jobs the document belongs; cleared when it leaves Jobs.
            if employer:
                db.execute("INSERT INTO job_filings VALUES(?,?,?,?,?,?) ON CONFLICT(document_id,blob_hash) DO UPDATE SET "
                           "employer_id=excluded.employer_id,section=excluded.section,label=excluded.label,title=excluded.title",
                           (document_id, digest, employer["id"], section, label, title))
            else:
                db.execute("DELETE FROM job_filings WHERE document_id=? AND blob_hash=?", (document_id, digest))
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
            if (doc["current_hash"] != intent["blob_hash"] and intent["action"] not in ("archive", "layout")) or doc["deleted_at"]:
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
                self.make_directory(target.parent)
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
            if source and source != target:
                self.remove_empty(source.parent)
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

    def make_directory(self, folder):
        """Create a YYYY/MM folder beneath a category, refusing links at every level."""
        for level in reversed([folder, *folder.parents]):
            if level == self.root or self.root not in level.parents:
                continue
            safe_path(level).mkdir(exist_ok=True)

    def remove_empty(self, folder):
        """Tidy a month, then a year, folder that a move left empty. Category folders themselves stay."""
        for level in (folder, folder.parent):
            relative = level.relative_to(self.root).parts if self.root in level.parents else ()
            depths = (2, 3, 4, 5) if relative[:1] == ("Jobs",) else (2, 3)  # Jobs/<Employer>/<Section>/YYYY/MM; employer folders stay.
            if len(relative) not in depths or relative[0] not in DATED_FOLDERS | set(RETIRED_FOLDERS) or not relative[-1].isdigit():
                return
            try:
                safe_path(level).rmdir()  # Fails harmlessly unless empty, so nothing of the user's is removed.
            except OSError:
                return

    def filing_date(self, document_id, digest):
        """The document's own date: its ledger record's, else the date its filed name already carries."""
        with self.store.connection() as db:
            row = db.execute(self.store.library_query() + "SELECT document_date FROM library WHERE id=? AND current_hash=?", (document_id, digest)).fetchone()
        if row and iso_date(row["document_date"]):
            return row["document_date"]
        existing = self.current_file(document_id, digest)
        name = PurePosixPath(existing["relative_path"]).name if existing else ""
        return iso_date(name[:10])

    @locked
    def relayout(self, document_id=None):
        """Move category files into their YYYY/MM folder once their date is known. Names never change."""
        # Every version's file, so an older version's copy lands in its month too.
        query = ("SELECT m.* FROM managed_files m JOIN occurrences o ON o.id=m.document_id "
                 "WHERE o.deleted_at IS NULL AND NOT EXISTS(SELECT 1 FROM managed_organization_intents i WHERE i.document_id=m.document_id "
                 "AND i.blob_hash=m.blob_hash AND i.status IN ('pending','blocked'))")
        with self.store.connection() as db:
            rows = [dict(row) for row in db.execute(query + (" AND m.document_id=?" if document_id else ""), (document_id,) if document_id else ())]
        moved = 0
        for row in rows:
            if row["folder"] not in DATED_FOLDERS:
                continue
            job = self.job_filing(row["document_id"], row["blob_hash"]) if row["folder"] == "Jobs" else None
            place = directory(row["folder"], self.filing_date(row["document_id"], row["blob_hash"]),
                              job and job["folder_name"], job and job["section"])
            if str(PurePosixPath(row["relative_path"]).parent) == place:
                continue
            try:
                self.organize(row["document_id"], row["blob_hash"], row["folder"], row["reason"], action="layout", keep_name=True)
                moved += 1
            except (ValueError, OSError, RuntimeError):
                pass  # The blocked intent stays visible; the file is left where it is.
        return moved

    @locked
    def file_classified(self, document_id, digest, document_type, merchant, dated, reason, document_name=None):
        """The one filing rule: a supported, evidence-cited type plus unambiguous merchant/issuer and
        ISO date files the copy; anything else goes to Unfiled. A manual choice always wins, and an
        inconclusive later result never undoes an earlier evidence-backed filing. For a job document the
        merchant is the employer: its folder under Jobs is created when new, and the document files into
        its Paystubs or Documents section, named Paystub or by its printed document name (Offer Letter)."""
        with self.store.connection() as db:
            manual = db.execute("SELECT 1 FROM document_folders WHERE document_id=? AND blob_hash=?", (document_id, digest)).fetchone()
        if manual:
            self.relayout(document_id)  # The user's folder stands; a newly known date still picks its month.
            return None
        dated = iso_date(dated)
        employer = self.employer(merchant) if document_type in JOB_TYPES and merchant else None
        if document_type in JOB_TYPES and not employer:
            merchant = None  # A name with no letters can't name an employer folder.
        if document_type in TYPE_FOLDERS and merchant and dated:
            return self.organize(document_id, digest, TYPE_FOLDERS[document_type], reason, action="classification",
                                 merchant=merchant, document_date=dated, employer=employer, section=JOB_TYPES.get(document_type),
                                 label=("Paystub" if document_type == "paystub" else clean_label(spelled(document_name)) or "Document") if employer else None,
                                 title=" ".join((document_name or "").split())[:60] or None if document_type == "employment_document" else None)
        existing = self.current_file(document_id, digest)
        if existing and existing["folder"] in FOLDERS:
            return None
        if document_type in UNTRACKED_TYPES:
            return self.organize(document_id, digest, "Unfiled", UNTRACKED_TYPES[document_type], action="classification")
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
        self.retire_folders()
        self.relayout()  # Also moves files filed before the YYYY/MM layout existed.

    @locked
    def retire_folders(self):
        """Move every file out of a retired folder into its replacement: Bills into Unfiled, keeping the name;
        Income into Jobs, a pay stub into its employer's Paystubs folder with a new name."""
        marks = ",".join("?" * len(RETIRED_FOLDERS))
        with self.store.connection() as db:
            rows = [dict(row) for row in db.execute(
                f"SELECT m.*,(SELECT mm.canonical_name FROM income_records i JOIN merchants mm ON mm.id=i.payer_merchant_id "
                f"WHERE i.blob_hash=m.blob_hash AND i.review_status<>'rejected') AS payer FROM managed_files m JOIN occurrences o ON o.id=m.document_id "
                f"WHERE m.folder IN ({marks}) AND o.deleted_at IS NULL "
                "AND NOT EXISTS(SELECT 1 FROM managed_organization_intents i WHERE i.document_id=m.document_id AND i.blob_hash=m.blob_hash "
                "AND i.status IN ('pending','blocked'))", list(RETIRED_FOLDERS))]
        for row in rows:
            destination = RETIRED_FOLDERS[row["folder"]]
            employer = self.employer(row["payer"]) if destination == "Jobs" and row["payer"] else None
            reason = "The Bills folder was retired; bills aren't tracked." if row["folder"] == "Bills" else f"The {row['folder']} folder became {destination}."
            try:
                self.organize(row["document_id"], row["blob_hash"], destination, reason, action="layout", keep_name=employer is None,
                              employer=employer, section="Paystubs" if employer else None, label="Paystub" if employer else None)
            except (ValueError, OSError, RuntimeError):
                pass  # The blocked intent stays visible; the file is left where it is.
