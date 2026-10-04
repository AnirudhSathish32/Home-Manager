"""Donation checks and bundles (docs/evals.md).

A person checks an extracted record field by field against its original, then exports the checked documents as one
zip for the person collecting them for the private eval corpus. A check is an evaluation label: it never changes the
ledger, review status, corrections or filing. Nothing is sent anywhere; the person hands over the zip themselves.
"""

from datetime import datetime, timezone
import json
import os
import re
import shutil
import uuid
import zipfile

from ..core.answers import ANSWERS_FORMAT, CRITICAL, LABELS, ROWS, Answers, check_value, empty_answers, kind_of
from ..core.formats import extension
from ..core.jobs import Work
from ..core.money import MoneyError, format_minor, to_minor
from ..core.paths import safe_path, write_atomic
from ..library.storage import digest_file, now
from .grouping import Groups
from .receipt_service import ReceiptService

BUNDLE_FORMAT = "home-manager-donation/1"
RECORD_DOCUMENT_TYPES = {"receipt": ("receipt",), "statement": ("bank_statement", "credit_card_statement"), "income_record": ("paystub",)}
RECORD_TABLES = {"receipt": "receipts", "statement": "statements", "income_record": "income_records"}
SOURCE_KINDS = ("phone_photo", "scan", "native_pdf", "image_pdf")
ORIGINAL_EXTENSIONS = {".png": "png", ".jpg": "jpg", ".jpeg": "jpg", ".pdf": "pdf"}
DONOR = re.compile(r"[a-z0-9-]{1,16}")
MAX_BOXES, MAX_BUNDLE_CASES = 50, 200
WORKER_SECONDS = 120


def utc_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Donations:
    def __init__(self, store, receipts: ReceiptService, ledger):
        self.store, self.receipts, self.ledger = store, receipts, ledger
        self.root = safe_path(store.root / "Donations")

    # Which records can be checked ------------------------------------------------

    def candidates(self, limit=200):
        """Extracted receipts, statements and pay stubs with their check, newest first."""
        rows = []
        with self.store.connection() as db:
            for record_type, table in RECORD_TABLES.items():
                date_column = {"receipt": "purchase_date", "statement": "period_end", "income_record": "pay_date"}[record_type]
                for row in db.execute(f"SELECT r.id,r.document_id,r.blob_hash,{date_column} AS document_date,o.relative_path,c.id AS check_id,"
                                      f"c.status AS check_status FROM {table} r JOIN occurrences o ON o.id=r.document_id "
                                      "LEFT JOIN donation_checks c ON c.record_type=? AND c.record_id=r.id AND c.blob_hash=r.blob_hash "
                                      "WHERE r.extraction_run_id IS NOT NULL AND o.deleted_at IS NULL"
                                      + (" AND r.segment=0" if record_type == "receipt" else "") + " ORDER BY r.id DESC LIMIT ?",
                                      (record_type, limit)):
                    if extension(row["relative_path"]) in ORIGINAL_EXTENSIONS:
                        rows.append({**dict(row), "record_type": record_type, "name": row["relative_path"].rsplit("/", 1)[-1]})
        rows.sort(key=lambda row: row["document_date"] or "", reverse=True)
        return rows[:limit]

    def proposal(self, record_type, record_id):
        """(record row, extraction run, normalized proposal) for a record that can be donated, else ValueError."""
        if record_type not in RECORD_TABLES:
            raise ValueError("Only receipts, statements and pay stubs can be donated.")
        with self.store.connection() as db:
            row = db.execute(f"SELECT * FROM {RECORD_TABLES[record_type]} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            row = dict(row)
            if not row.get("extraction_run_id"):
                raise ValueError("Only records read from a document can be donated; imported rows have no document to check.")
            run = db.execute("SELECT * FROM extraction_runs WHERE id=?", (row["extraction_run_id"],)).fetchone()
            document = db.execute("SELECT * FROM occurrences WHERE id=?", (row["document_id"],)).fetchone()
        if run is None or run["status"] != "succeeded" or not run["result_json"]:
            raise ValueError("This record's reading is no longer available. Extract the document again first.")
        if document is None or document["deleted_at"]:
            raise ValueError("Restore the document from Trash before donating it.")
        if extension(document["relative_path"]) not in ORIGINAL_EXTENSIONS:
            raise ValueError("Only PNG, JPEG and PDF documents can be donated.")
        if Groups(self.store).of(row["document_id"], ("confirmed",)):
            raise ValueError("Documents combined from several images can't be donated yet.")
        result = json.loads(run["result_json"])
        if result.get("segments") or row.get("segment"):
            raise ValueError("A file holding several receipts can't be donated yet.")
        normalized = result.get("normalized") or {}
        if normalized.get("document_type") not in RECORD_DOCUMENT_TYPES[record_type]:
            raise ValueError("This record's reading is not a receipt, statement or pay stub.")
        return row, dict(run), dict(document), normalized

    # Checks ----------------------------------------------------------------------

    def start(self, record_type, record_id):
        """The check for this record, created with the model's proposal and the record's current corrections."""
        row, run, document, normalized = self.proposal(record_type, record_id)
        with self.store.connection() as db:
            existing = db.execute("SELECT id FROM donation_checks WHERE record_type=? AND record_id=? AND blob_hash=?",
                                  (record_type, record_id, row["blob_hash"])).fetchone()
        if existing:
            return self.get(existing["id"])
        kind = normalized["document_type"]
        prefill = dict(normalized)
        current = self.ledger.record(record_type, record_id)
        # Corrections the person already made in the app (merchant, date, employer) are the starting values.
        overlay = {"receipt": {"merchant": "merchant", "purchase_date": "purchase_date"},
                   "income_record": {"payer_or_employer": "merchant", "pay_date": "pay_date"}}.get(record_type, {})
        for field, column in overlay.items():
            if current.get(column):
                prefill[field] = current[column]
        answers = empty_answers(kind, prefill)
        parse = self.receipts.get(run["parse_run_id"])
        is_pdf = extension(document["relative_path"]) == ".pdf"
        pages = (parse["result"] or {}).get("pages") or []
        source_kind = (("native_pdf" if pages and all(page.get("method") == "embedded_text" for page in pages) else "image_pdf") if is_pdf
                       else "phone_photo" if (parse["result"] or {}).get("exif_orientation") is not None else "scan")
        options = json.loads(run["config_json"])
        with self.store.connection() as db:
            cursor = db.execute("INSERT INTO donation_checks(document_id,blob_hash,record_type,record_id,document_type,extraction_run_id,extraction_version,"
                                "proposal_json,answers_json,source_kind,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'draft',?,?)",
                                (row["document_id"], row["blob_hash"], record_type, record_id, kind, run["id"], run["prompt_version"],
                                 json.dumps({"normalized": self.project(kind, normalized), "home_currency": options.get("home_currency")}),
                                 answers.model_dump_json(), source_kind, now(), now()))
            check_id = cursor.lastrowid
        try:
            self.prepare_pages(check_id, row["blob_hash"], parse, is_pdf)
        except Exception:
            self.delete(check_id)
            raise
        return self.get(check_id)

    @staticmethod
    def project(kind, record):
        """Only the checked fields and row columns of a normalized record: no quotes, locators or notes."""
        key, columns = ROWS[kind]
        fields = {}
        for name in CRITICAL[kind]:
            try:
                fields[name] = check_value(name, record.get(name))
            except ValueError:
                fields[name] = None
        rows = []
        for row in record.get(key) or []:
            clean = {}
            for name in columns:
                try:
                    clean[name] = check_value(name, row.get(name))
                except ValueError:
                    clean[name] = None
            rows.append(clean)
        return {"document_type": kind, "fields": fields, "rows": rows}

    def folder(self, check_id):
        return safe_path(self.root / "checks" / str(int(check_id)))

    def prepare_pages(self, check_id, blob_hash, parse, is_pdf):
        folder = self.folder(check_id)
        if folder.exists():
            shutil.rmtree(folder)
        (folder / "pages").mkdir(parents=True)
        if is_pdf:
            source = self.store.blob_path(blob_hash)
            if digest_file(source) != blob_hash:
                raise ValueError("The preserved document failed its integrity check.")
        else:
            source = self.receipts.preview(parse["id"])  # The image as it was read: oriented and rotated.
        self.child(source, folder / "pages", "pages-pdf" if is_pdf else "pages-image")

    @staticmethod
    def child(source, folder, mode):
        env = {key: value for key, value in os.environ.items() if key.upper() in ("SYSTEMROOT", "WINDIR", "PATH", "COMSPEC")}
        env.update({"TEMP": str(folder), "TMP": str(folder)})
        ReceiptService.child("home_manager.documents.donation_worker", source, folder, mode, env, Work.detached(), WORKER_SECONDS)

    def row(self, check_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM donation_checks WHERE id=?", (check_id,)).fetchone()
        if row is None:
            raise ValueError("Donation check not found.")
        return dict(row)

    def get(self, check_id):
        """A check for display: each field with its proposal, value and state, and its rows; money also as display text."""
        row = self.row(check_id)
        answers = Answers.model_validate_json(row["answers_json"])
        proposal = json.loads(row["proposal_json"])["normalized"]
        currency = self.currency(answers, proposal)
        kind = row["document_type"]

        def shown(name, value):
            if value is None:
                return ""
            return format_minor(value, currency) if kind_of(name) == "money" and currency else str(value)

        _, columns = ROWS[kind]
        return {"id": row["id"], "document_id": row["document_id"], "record_type": row["record_type"], "record_id": row["record_id"],
                "document_type": kind, "status": row["status"], "source_kind": row["source_kind"], "currency": currency,
                "redactions": json.loads(row["redactions_json"]), "pages": len(list((self.folder(row["id"]) / "pages").glob("page-*.png"))),
                "fields": [{"name": name, "label": LABELS[name], "kind": kind_of(name), "value": answer.value, "display": shown(name, answer.value),
                            "input": self.input_text(name, answer.value, currency), "state": answer.state,
                            "proposed": shown(name, proposal["fields"].get(name))}
                           for name, answer in answers.fields.items()],
                "columns": [{"name": name, "label": LABELS[name], "kind": kind_of(name)} for name in columns],
                "rows": [{name: {"value": item[name], "display": shown(name, item[name]), "input": self.input_text(name, item[name], currency)}
                          for name in columns} for item in answers.rows or []],
                "proposed_rows": len(proposal["rows"]), "rows_state": answers.rows_state, "rows_complete": answers.rows_complete,
                "updated_at": row["updated_at"]}

    @staticmethod
    def currency(answers, proposal):
        value = answers.fields["currency"].value or proposal["fields"].get("currency")
        return value if isinstance(value, str) else None

    @staticmethod
    def input_text(name, value, currency):
        """What an edit box starts with: money as plain decimal text such as -12.30."""
        if value is None:
            return ""
        if kind_of(name) == "money" and currency:
            return format_minor(value, currency).rsplit(" ", 1)[0].replace(",", "")
        return str(value)

    def save(self, check_id, fields, rows=None, rows_state=None, rows_complete=None, source_kind=None, redactions=None, finish=False):
        """Save typed answers. fields: {name: {"text": what the person typed, "state": correct|fixed|unchecked}}; rows: [{column: text}].
        Money is typed as text and converted exactly; finish marks the check ready to donate."""
        row = self.row(check_id)
        kind = row["document_type"]
        answers = Answers.model_validate_json(row["answers_json"])
        proposal = json.loads(row["proposal_json"])["normalized"]
        unknown = set(fields) - set(CRITICAL[kind])
        if unknown:
            raise ValueError("Unknown fields for this document: " + ", ".join(sorted(unknown)) + ".")
        typed_currency = fields.get("currency", {}).get("text")
        currency = (typed_currency or "").strip().upper() or self.currency(answers, proposal)
        updated = answers.model_dump()
        for name, change in fields.items():
            state = change.get("state", "unchecked")
            if state not in ("correct", "fixed", "unchecked"):
                raise ValueError("A field's state must be correct, fixed or unchecked.")
            updated["fields"][name] = {"value": self.parse(name, change.get("text"), currency), "state": state}
        if rows is not None:
            _, columns = ROWS[kind]
            parsed = []
            for index, item in enumerate(rows, 1):
                if set(item) != set(columns):
                    raise ValueError(f"Row {index} must have exactly these columns: " + ", ".join(columns) + ".")
                try:
                    parsed.append({name: self.parse(name, item[name], currency) for name in columns})
                except ValueError as exc:
                    raise ValueError(f"Row {index}: {exc}") from None
            updated["rows"] = parsed
        if rows_state is not None:
            updated["rows_state"] = rows_state
        if rows_complete is not None or rows_state is not None:
            updated["rows_complete"] = rows_complete
        checked = Answers.model_validate(updated)
        if finish and not checked.checked_fields() and checked.rows_state == "unchecked":
            raise ValueError("Mark at least one field correct or fixed before finishing the check.")
        if source_kind is not None and source_kind not in SOURCE_KINDS:
            raise ValueError("Choose phone photo, scan, PDF with text or scanned PDF.")
        boxes = self.boxes(redactions, check_id) if redactions is not None else json.loads(row["redactions_json"])
        status = "checked" if finish else row["status"]
        with self.store.connection() as db:
            db.execute("UPDATE donation_checks SET answers_json=?,source_kind=?,redactions_json=?,status=?,updated_at=? WHERE id=?",
                       (checked.model_dump_json(), source_kind or row["source_kind"], json.dumps(boxes), status, now(), check_id))
        return self.get(check_id)

    def reopen(self, check_id):
        self.row(check_id)
        with self.store.connection() as db:
            db.execute("UPDATE donation_checks SET status='draft',updated_at=? WHERE id=?", (now(), check_id))
        return self.get(check_id)

    @staticmethod
    def parse(name, text, currency):
        """A typed value as stored: None when blank (the document does not print it), money in exact minor units."""
        if text is None or (isinstance(text, str) and not text.strip()):
            return None
        if not isinstance(text, str):
            raise ValueError(f"{LABELS.get(name, name)}: type the value as text.")
        text = text.strip()
        if kind_of(name) == "money":
            if not currency:
                raise ValueError("Set the currency before typing amounts.")
            try:
                return to_minor(text, currency)
            except MoneyError as exc:
                raise ValueError(f"{LABELS.get(name, name)}: {exc}") from None
        if kind_of(name) == "currency":
            text = text.upper()
        return check_value(name, text)

    def boxes(self, redactions, check_id):
        pages = len(list((self.folder(check_id) / "pages").glob("page-*.png")))
        if not isinstance(redactions, list) or len(redactions) > MAX_BOXES:
            raise ValueError(f"Use at most {MAX_BOXES} redaction boxes.")
        boxes = []
        for box in redactions:
            try:
                page, x, y, w, h = int(box["page"]), float(box["x"]), float(box["y"]), float(box["w"]), float(box["h"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("Each redaction box needs a page and a position.") from None
            if not 1 <= page <= pages or not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 - x + 1e-9 and 0 < h <= 1 - y + 1e-9):
                raise ValueError("A redaction box lies outside its page.")
            boxes.append({"page": page, "x": round(x, 5), "y": round(y, 5), "w": round(w, 5), "h": round(h, 5)})
        return boxes

    def page(self, check_id, number):
        self.row(check_id)
        path = safe_path(self.folder(check_id) / "pages" / f"page-{int(number)}.png")
        if not path.is_file():
            raise ValueError("No such page.")
        return path

    def delete(self, check_id):
        with self.store.connection() as db:
            db.execute("DELETE FROM donation_checks WHERE id=?", (check_id,))
        folder = self.folder(check_id)
        if folder.exists():
            shutil.rmtree(folder)

    def checks(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT id,document_id,record_type,record_id,document_type,status,source_kind,updated_at "
                                                    "FROM donation_checks ORDER BY updated_at DESC")]

    # Bundles ---------------------------------------------------------------------

    def export(self, check_ids, donor=None):
        """One zip of finished checks: each original (or its redacted copy), its answers and the model's proposal."""
        if not check_ids or len(check_ids) > MAX_BUNDLE_CASES:
            raise ValueError(f"Choose 1 to {MAX_BUNDLE_CASES} checked documents to donate.")
        if donor is not None and not DONOR.fullmatch(donor):
            raise ValueError("The donor ID uses lowercase letters, digits and dashes, at most 16 characters.")
        rows = [self.row(check_id) for check_id in dict.fromkeys(check_ids)]
        if any(row["status"] != "checked" for row in rows):
            raise ValueError("Finish checking every chosen document before donating it.")
        bundle_id = uuid.uuid4().hex
        exports = safe_path(self.root / "exports")
        exports.mkdir(parents=True, exist_ok=True)
        path = safe_path(exports / f"donation-{bundle_id[:12]}.zip")
        cases = []
        try:
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
                for row in rows:
                    case_id = uuid.uuid4().hex[:16]
                    data, suffix, redacted = self.original(row)
                    proposal = json.loads(row["proposal_json"])
                    bundle.writestr(f"cases/{case_id}/original.{suffix}", data)
                    bundle.writestr(f"cases/{case_id}/answers.json", row["answers_json"])
                    bundle.writestr(f"cases/{case_id}/proposal.json", json.dumps(proposal["normalized"], indent=2))
                    cases.append({"case_id": case_id, "document_type": row["document_type"], "source_kind": row["source_kind"],
                                  "redacted": redacted, "pages": len(list((self.folder(row["id"]) / "pages").glob("page-*.png"))),
                                  "original": f"cases/{case_id}/original.{suffix}", "extraction_version": row["extraction_version"],
                                  "home_currency": proposal.get("home_currency"), "answers_format": ANSWERS_FORMAT})
                manifest = {"format": BUNDLE_FORMAT, "bundle_id": bundle_id, "donor": donor, "created_at": utc_stamp(), "cases": cases}
                bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return {"bundle_id": bundle_id, "name": path.name, "cases": len(cases), "bytes": path.stat().st_size}

    def original(self, row):
        """(bytes, extension, redacted): the preserved original, or a copy with the boxes blacked out."""
        boxes = json.loads(row["redactions_json"])
        with self.store.connection() as db:
            document = db.execute("SELECT relative_path FROM occurrences WHERE id=?", (row["document_id"],)).fetchone()
        if not boxes:
            source = self.store.blob_path(row["blob_hash"])
            if digest_file(source) != row["blob_hash"]:
                raise ValueError("A preserved document failed its integrity check; it was not donated.")
            return source.read_bytes(), ORIGINAL_EXTENSIONS[extension(document["relative_path"])], False
        folder = self.folder(row["id"]) / "pages"
        write_atomic(folder / "boxes.json", json.dumps(boxes))
        for name in ("redacted.png", "redacted.pdf"):
            (folder / name).unlink(missing_ok=True)
        self.child(folder / "boxes.json", folder, "redact")
        for name, suffix in (("redacted.png", "png"), ("redacted.pdf", "pdf")):
            if (folder / name).is_file():
                return (folder / name).read_bytes(), suffix, True
        raise ValueError("The redacted copy could not be made.")

    def bundle_file(self, name):
        if not re.fullmatch(r"donation-[0-9a-f]{12}\.zip", name or ""):
            raise ValueError("Unknown donation file.")
        path = safe_path(self.root / "exports" / name)
        if not path.is_file():
            raise ValueError("Unknown donation file.")
        return path
