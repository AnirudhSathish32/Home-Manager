"""Canonical ledger writes: accounts, merchants, de-duplicated transactions, evidence and review.

Only validated, normalized values reach this module. It never parses model text and
never performs floating-point arithmetic.
"""

from collections import Counter
from datetime import date
import hashlib
import json
import re
import unicodedata
import uuid

from .formats import TABLES, extension
from pydantic import Field, field_validator

from .money import currency_code, format_minor, money, to_minor
from .receipt_schema import StrictModel
from .storage import now
from .tabular import MAX_BYTES, MappingError, parse_transactions, preview

REVIEW_STATES = ("proposed", "needs_review", "verified", "rejected")
PAYMENT_STATES = ("unknown", "unpaid", "paid")
ACCOUNT_TYPES = ("checking", "savings", "credit_card", "brokerage", "loan", "other")
RECORD_TABLES = {"statement": "statements", "transaction": "transactions", "receipt": "receipts",
                 "bill": "bills", "income_record": "income_records"}
# Excluded from spending: moving money between the household's own accounts.
NON_SPENDING = ("transfer", "payment")
SPENDING = ("purchase", "fee", "interest", "withdrawal")
# Rows that count toward totals: deterministic imports unless rejected; model-extracted
# rows only after the user verifies them. Everything else is reported as pending review.
COUNTABLE = "t.review_status<>'rejected' AND (t.origin<>'extraction' OR t.review_status='verified')"
# Summary columns per record type: one compact "what, when, how much, where from" shape.
# Each query selects id, date, name, amount_minor, currency, review_status, account, document_id.
SUMMARY_QUERIES = {
    "transaction": "SELECT t.id,t.posted_date AS date,coalesce(m.canonical_name,t.description_raw) AS name,t.description_raw AS description,"
                   "t.amount_minor,t.currency,t.transaction_type,t.review_status,a.display_name AS account,t.source_document_id AS document_id "
                   "FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN merchants m ON m.id=t.merchant_id WHERE t.id IN ({ids})",
    "receipt": "SELECT r.id,r.purchase_date AS date,m.canonical_name AS name,r.total_minor AS amount_minor,r.currency,r.review_status,"
               "NULL AS account,r.document_id FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id WHERE r.id IN ({ids})",
    "statement": "SELECT s.id,s.period_end AS date,a.institution AS name,coalesce(s.closing_balance_minor,s.statement_balance_minor) AS amount_minor,"
                 "s.currency,s.review_status,a.display_name AS account,s.document_id FROM statements s JOIN accounts a ON a.id=s.account_id WHERE s.id IN ({ids})",
    "bill": "SELECT b.id,coalesce(b.due_date,b.issue_date) AS date,m.canonical_name AS name,b.amount_due_minor AS amount_minor,b.currency,"
            "b.review_status,a.display_name AS account,b.document_id FROM bills b LEFT JOIN merchants m ON m.id=b.provider_merchant_id "
            "LEFT JOIN accounts a ON a.id=b.account_id WHERE b.id IN ({ids})",
    "income_record": "SELECT i.id,i.pay_date AS date,m.canonical_name AS name,i.net_pay_minor AS amount_minor,i.currency,i.review_status,"
                     "NULL AS account,i.document_id FROM income_records i LEFT JOIN merchants m ON m.id=i.payer_merchant_id WHERE i.id IN ({ids})",
}
SUMMARY_CHUNK = 500  # Bound on bound parameters per query.
# Fields the user may correct: record type -> field -> (column, kind, label used in validation issues).
CORRECTABLE = {
    "receipt": {"purchase_date": ("purchase_date", "date", "Purchase date"), "merchant": ("merchant_id", "name", "Merchant"),
                "location": ("location", "text", "Location")},
    "bill": {"issue_date": ("issue_date", "date", "Issue date"), "due_date": ("due_date", "date", "Due date"),
             "provider": ("provider_merchant_id", "name", "Provider")},
    "income_record": {"pay_date": ("pay_date", "date", "Pay date"), "payer": ("payer_merchant_id", "name", "Payer or employer")},
}
PENDING = "t.origin='extraction' AND t.review_status IN ('proposed','needs_review')"

TRANSFER = re.compile(r"\b(TRANSFER|XFER|TRNSFR)\b")
CARD_PAYMENT = re.compile(r"\b(PAYMENT|AUTOPAY|AUTO PAY|AUTOMATIC PAYMENT|PMT|THANK YOU)\b")
REFUND = re.compile(r"\b(REFUND|RETURN|REVERSAL|CREDIT ADJ)\b")
STORE_NOISE = re.compile(r"#\s*\d+|\b\d+\b|[^\w\s&]")
LEGAL_SUFFIX = re.compile(r"\b(INC|LLC|LTD|CO|CORP|CORPORATION|COMPANY)\b")


def normalize_name(name) -> str:
    """Stable merchant key: case, punctuation, store numbers and legal suffixes removed."""
    text = unicodedata.normalize("NFKC", name or "").upper()
    text = LEGAL_SUFFIX.sub(" ", STORE_NOISE.sub(" ", text))
    return " ".join(text.split())


def category_name(value) -> str:
    """Categories are compared as lower-case words with single spaces."""
    name = " ".join((value or "").split()).lower()
    if not name or len(name) > 60:
        raise ValueError("Enter a category of 1 to 60 characters.")
    if name == "uncategorized":
        raise ValueError("'uncategorized' means no category; choose another name.")
    return name


def name_tokens(name) -> set[str]:
    return {token for token in normalize_name(name).split() if len(token) > 2}


def classify_transaction(description, amount_minor, account_type):
    """Deterministic type from sign, account type and unambiguous keywords; reviewable later."""
    text = normalize_name(description) + " " + (description or "").upper()
    if TRANSFER.search(text):
        return "transfer"
    if CARD_PAYMENT.search(text) and (account_type == "credit_card" and amount_minor > 0 or "CARD" in text or "CRD" in text):
        return "payment"
    if re.search(r"\bINTEREST\b", text):
        return "interest"
    if re.search(r"\bFEE\b", text) and amount_minor < 0:
        return "fee"
    if amount_minor > 0:
        return "refund" if REFUND.search(text) or account_type == "credit_card" else "deposit"
    if re.search(r"\b(ATM|CASH WITHDRAWAL|WITHDRAWAL)\b", text):
        return "withdrawal"
    return "purchase" if amount_minor < 0 else "other"


def fingerprints(account_id, rows):
    """Source-independent identity: equal entries in one source keep distinct ordinals."""
    seen = Counter()
    for row in rows:
        key = (row["posted_date"], row["amount_minor"], row["currency"])
        yield hashlib.sha256(f"v1|{account_id}|{key[0]}|{key[1]}|{key[2]}|{seen[key]}".encode()).hexdigest()
        seen[key] += 1


class HouseholdConfig(StrictModel):
    """User-chosen defaults. home_currency reads bare symbols such as $ when nothing contradicts it.
    checkin_weekday is the day of the weekly household check-in: Monday 0 … Sunday 6."""
    home_currency: str | None = None
    checkin_weekday: int = Field(default=6, ge=0, le=6)
    auto_identify_items: bool = True  # Run item identification on each newly recorded receipt.

    @field_validator("home_currency")
    @classmethod
    def known(cls, value):
        return currency_code(value) if value else None


class Ledger:
    def __init__(self, store):
        self.store = store

    # Reference data -----------------------------------------------------------

    def merchant(self, db, name):
        key = normalize_name(name)
        if not key:
            return None
        db.execute("INSERT OR IGNORE INTO merchants(canonical_name,normalized_name,created_at,updated_at) VALUES(?,?,?,?)",
                   (" ".join(name.split())[:120], key, now(), now()))
        return db.execute("SELECT id FROM merchants WHERE normalized_name=?", (key,)).fetchone()[0]

    def create_account(self, institution, account_type, currency, display_name=None, last_four=None):
        with self.store.connection() as db:
            return self.account_in(db, institution, account_type, currency, display_name, last_four)

    def account_in(self, db, institution, account_type, currency, display_name=None, last_four=None):
        """Find or create an account inside the caller's transaction."""
        institution = " ".join((institution or "").split())[:120]
        if not institution:
            raise ValueError("Enter the account's institution.")
        if account_type not in ACCOUNT_TYPES:
            raise ValueError("Choose a supported account type.")
        if last_four is not None and not re.fullmatch(r"\d{4}", last_four):
            raise ValueError("Only the last four digits of an account number may be stored.")
        currency = currency_code(currency)
        existing = self.find_account(db, institution, (account_type,), last_four)
        if existing:
            if existing["currency"] != currency:
                raise ValueError("This account already exists with a different currency.")
            return existing
        cursor = db.execute("INSERT INTO accounts(institution,account_type,display_name,account_last_four,currency,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                            (institution, account_type, (display_name or f"{institution} {account_type.replace('_', ' ')}{' ' + last_four if last_four else ''}")[:160],
                             last_four, currency, now(), now()))
        return dict(db.execute("SELECT * FROM accounts WHERE id=?", (cursor.lastrowid,)).fetchone())

    def find_account(self, db, institution, account_types, last_four):
        row = db.execute(f"SELECT * FROM accounts WHERE institution=? AND account_type IN ({','.join('?' * len(account_types))}) "
                         "AND coalesce(account_last_four,'')=? ORDER BY id LIMIT 1",
                         (" ".join((institution or "").split())[:120], *account_types, last_four or "")).fetchone()
        return dict(row) if row else None

    def account(self, account_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            raise ValueError("Account not found.")
        return dict(row)

    def accounts(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM accounts ORDER BY institution, account_type, account_last_four")]

    # Evidence -----------------------------------------------------------------

    def add_evidence(self, db, record_type, record_id, source, locator):
        """source: document_id, blob_hash, parse_run_id and a source_key naming the run or import."""
        db.execute("INSERT OR IGNORE INTO financial_evidence_links(record_type,record_id,document_id,blob_hash,parse_run_id,source_key,locator_json,created_at) "
                   "VALUES(?,?,?,?,?,?,?,?)", (record_type, record_id, source["document_id"], source["blob_hash"],
                                               source.get("parse_run_id"), source["source_key"], json.dumps(locator), now()))

    def evidence(self, record_type, record_id):
        with self.store.connection() as db:
            rows = db.execute("SELECT e.*,o.relative_path FROM financial_evidence_links e JOIN occurrences o ON o.id=e.document_id "
                              "WHERE e.record_type=? AND e.record_id=? ORDER BY e.id", (record_type, record_id))
            return [{**dict(row), "locator": json.loads(row["locator_json"])} for row in rows]

    # Transactions -------------------------------------------------------------

    def insert_transactions(self, db, account, rows, origin, source, statement_id=None, review_status="proposed"):
        """Insert or de-duplicate rows, returning (inserted_ids, duplicate_ids). Evidence is always linked."""
        inserted, duplicates = [], []
        for row, fingerprint in zip(rows, fingerprints(account["id"], rows)):
            if row["currency"] != account["currency"]:
                raise ValueError("Transaction currency differs from its account currency; foreign-currency rows need review.")
            kind = row.get("transaction_type") or classify_transaction(row["description"], row["amount_minor"], account["account_type"])
            cursor = db.execute(
                "INSERT OR IGNORE INTO transactions(account_id,statement_id,source_document_id,posted_date,transaction_date,description_raw,"
                "amount_minor,currency,transaction_type,origin,review_status,review_source,source_fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account["id"], statement_id, source["document_id"], row["posted_date"], row.get("transaction_date"),
                 row["description"][:500], row["amount_minor"], row["currency"], kind, origin, review_status,
                 "automatic" if review_status == "verified" else None, fingerprint, now(), now()))
            if cursor.rowcount:
                record = cursor.lastrowid
                inserted.append(record)
            else:
                record = db.execute("SELECT id FROM transactions WHERE account_id=? AND source_fingerprint=?", (account["id"], fingerprint)).fetchone()[0]
                duplicates.append(record)
                if statement_id:
                    db.execute("UPDATE transactions SET statement_id=coalesce(statement_id,?),updated_at=? WHERE id=?", (statement_id, now(), record))
            self.add_evidence(db, "transaction", record, source, row["locator"])
        self.apply_rules(db, inserted)
        return inserted, duplicates

    # Publication of validated extraction ----------------------------------------
    # Each publication is one SQLite transaction. A record the user already verified or
    # rejected is never overwritten by a later extraction; unreviewed ones are replaced.

    def _upsert(self, db, table, source, columns):
        """Write an extraction's record unless the user has decided it; automatic acceptance can be redone."""
        existing = db.execute(f"SELECT id,review_status,review_source FROM {table} WHERE blob_hash=?", (source["blob_hash"],)).fetchone()
        if existing and existing["review_status"] in ("verified", "rejected") and existing["review_source"] == "user":
            return existing["id"], False
        columns = {**columns, "review_source": "automatic" if columns["review_status"] == "verified" else None,
                   "document_id": source["document_id"], "extraction_run_id": source["run_id"], "updated_at": now()}
        if existing:
            db.execute(f"UPDATE {table} SET {','.join(f'{name}=?' for name in columns)} WHERE id=?", (*columns.values(), existing["id"]))
            return existing["id"], True
        columns.update(blob_hash=source["blob_hash"], created_at=now())
        cursor = db.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values()))
        return cursor.lastrowid, True

    def _published(self, record_type, record_id, written, **extra):
        return {"record_type": record_type, "id": record_id, "status": "published" if written else "kept_reviewed", **extra}

    def publish_receipt(self, record, source, status):
        with self.store.connection() as db:
            receipt_id, written = self._upsert(db, "receipts", source, {
                "merchant_id": self.merchant(db, record["merchant"]) if record["merchant"] else None,
                "purchase_date": record["purchase_date"], "subtotal_minor": record["subtotal_minor"], "tax_minor": record["tax_minor"],
                "tip_minor": record["tip_minor"], "total_minor": record["total_minor"], "currency": record["currency"],
                "description": record.get("description"), "location": record.get("location"), "review_status": status, "validation_json": json.dumps(record["issues"]),
                "return_days_printed": record.get("return_days_printed"), "return_policy_quote": record.get("return_policy_quote")})
            if written:
                stale = [row[0] for row in db.execute("SELECT id FROM receipt_items WHERE receipt_id=?", (receipt_id,))]
                db.executemany("DELETE FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=?", [(item,) for item in stale])
                db.execute("DELETE FROM receipt_items WHERE receipt_id=?", (receipt_id,))
                self.add_evidence(db, "receipt", receipt_id, source, record["locator"])
                self.apply_corrections(db, "receipt", receipt_id)
                for position, item in enumerate(record["items"], 1):
                    item_id = db.execute("INSERT INTO receipt_items(receipt_id,position,description,product_code,quantity,unit_price_minor,line_total_minor,discount_minor,review_status) "
                                         "VALUES(?,?,?,?,?,?,?,?,?)", (receipt_id, position, item["description"], item["product_code"], item["quantity"],
                                                                         item["unit_price_minor"], item["line_total_minor"], item["discount_minor"], status)).lastrowid
                    self.add_evidence(db, "receipt_item", item_id, source, item["locator"])
        return self._published("receipt", receipt_id, written, items=len(record["items"]))

    def publish_asset(self, record, source):
        """An investment or loan statement's value as the forecast asset for its account (docs/items-assets-search.md §6).
        One row per account: a newer statement updates it and returns it to proposed; an older one changes nothing."""
        kind, institution = record["asset_kind"], " ".join(record["institution"].split())
        label = record.get("account_name") or ("Loan" if kind == "loan" else "Retirement account" if kind == "retirement" else "Investment account")
        identity = record.get("last_four") or normalize_name(record.get("account_name")) or "-"
        key = f"{kind}|{normalize_name(institution)}|{identity}|{record['currency']}"
        name = f"{institution} {label}{' ' + record['last_four'] if record.get('last_four') else ''}"[:80]
        values = {"value_minor": record["value_minor"], "as_of": record["period_end"], "blob_hash": source["blob_hash"], "document_id": source["document_id"],
                  "extraction_run_id": source["run_id"], "validation_json": json.dumps(record["issues"]), "updated_at": now()}
        if kind == "loan":
            values.update({"monthly_payment_minor": record.get("monthly_payment_minor")} if record.get("monthly_payment_minor") is not None else {})
            values.update({"annual_rate_bp": record["annual_rate_bp"]} if record.get("annual_rate_bp") is not None else {})
        with self.store.connection() as db:
            existing = db.execute("SELECT * FROM assets WHERE account_key=?", (key,)).fetchone()
            if existing:
                if existing["as_of"] > record["period_end"]:
                    return {"record_type": "asset", "id": existing["id"], "status": "kept_newer"}
                # Re-extracting the statement the user already decided on changes nothing.
                if existing["blob_hash"] == source["blob_hash"] and existing["as_of"] == record["period_end"] and existing["review_status"] in ("verified", "rejected"):
                    return {"record_type": "asset", "id": existing["id"], "status": "kept_reviewed"}
                db.execute(f"UPDATE assets SET {','.join(f'{column}=?' for column in values)},review_status='proposed' WHERE id=?", (*values.values(), existing["id"]))
                return {"record_type": "asset", "id": existing["id"], "status": "published"}
            columns = {**values, "name": name, "kind": kind, "currency": record["currency"], "source": "statement", "account_key": key,
                       "review_status": "proposed", "created_at": now()}
            columns.setdefault("annual_rate_bp", 0)
            asset_id = db.execute(f"INSERT INTO assets({','.join(columns)}) VALUES({','.join('?' * len(columns))})", tuple(columns.values())).lastrowid
        return {"record_type": "asset", "id": asset_id, "status": "published"}

    def publish_statement(self, record, source, status):
        card = record["statement_type"] == "credit_card"
        with self.store.connection() as db:
            account = self.find_account(db, record["institution"], ("credit_card",) if card else ("checking", "savings", "other"), record["last_four"])
            account = account or self.account_in(db, record["institution"], "credit_card" if card else "checking", record["currency"], last_four=record["last_four"])
            if account["currency"] != record["currency"]:
                raise ValueError("The statement currency differs from its account's currency; nothing was published.")
            statement_id, written = self._upsert(db, "statements", source, {
                "account_id": account["id"], "statement_type": record["statement_type"], "period_start": record["period_start"],
                "period_end": record["period_end"], "issue_date": None, "due_date": record.get("due_date"),
                "opening_balance_minor": record.get("opening_balance_minor"), "closing_balance_minor": record.get("closing_balance_minor"),
                "statement_balance_minor": record.get("statement_balance_minor"), "minimum_payment_minor": record.get("minimum_payment_minor"),
                "summary_json": json.dumps(record["summary"]), "currency": record["currency"], "review_status": status,
                "validation_json": json.dumps(record["issues"])})
            if not written:
                return self._published("statement", statement_id, False, account_id=account["id"])
            self.add_evidence(db, "statement", statement_id, source, record["locator"])
            # Rows from an earlier extraction the user has not decided (unreviewed or accepted automatically) that no other source supports.
            stale = [row[0] for row in db.execute(
                "SELECT t.id FROM transactions t WHERE t.statement_id=? AND t.origin='extraction' "
                "AND (t.review_status IN ('proposed','needs_review') OR t.review_source='automatic') "
                "AND NOT EXISTS(SELECT 1 FROM financial_evidence_links e WHERE e.record_type='transaction' AND e.record_id=t.id AND e.source_key NOT LIKE 'extraction:%')",
                (statement_id,))]
            for transaction in stale:
                db.execute("DELETE FROM financial_evidence_links WHERE record_type='transaction' AND record_id=?", (transaction,))
                db.execute("DELETE FROM transactions WHERE id=?", (transaction,))
            inserted, duplicates = self.insert_transactions(db, account, record["transactions"], "extraction", source, statement_id, status)
        return self._published("statement", statement_id, True, account_id=account["id"], inserted=len(inserted), duplicates=len(duplicates))

    def publish_bill(self, record, source, status):
        with self.store.connection() as db:
            bill_id, written = self._upsert(db, "bills", source, {
                "provider_merchant_id": self.merchant(db, record["provider"]) if record["provider"] else None,
                "issue_date": record["issue_date"], "due_date": record["due_date"], "period_start": record["period_start"],
                "period_end": record["period_end"], "amount_due_minor": record["amount_due_minor"], "currency": record["currency"],
                "review_status": status, "validation_json": json.dumps(record["issues"])})
            if written:
                self.add_evidence(db, "bill", bill_id, source, record["locator"])
                self.apply_corrections(db, "bill", bill_id)
        return self._published("bill", bill_id, written)

    def publish_income(self, record, source, status):
        with self.store.connection() as db:
            income_id, written = self._upsert(db, "income_records", source, {
                "payer_merchant_id": self.merchant(db, record["payer_or_employer"]) if record["payer_or_employer"] else None,
                "pay_date": record["pay_date"], "period_start": record["period_start"], "period_end": record["period_end"],
                "gross_pay_minor": record["gross_pay_minor"], "net_pay_minor": record["net_pay_minor"], "taxes_minor": record["taxes_minor"],
                "deductions_minor": record["deductions_minor"], "currency": record["currency"], "review_status": status,
                "validation_json": json.dumps(record["issues"])})
            if written:
                self.add_evidence(db, "income_record", income_id, source, record["locator"])
                self.apply_corrections(db, "income_record", income_id)
        return self._published("income_record", income_id, written)

    # Deterministic CSV/XLSX import ---------------------------------------------

    def table_rows(self, document_id, digest, currency, mapping):
        """Parse the preserved, hash-verified bytes; never the Inbox or Library file."""
        document, version = self.store.document_version(document_id, digest)
        if document["deleted_at"]:
            raise ValueError("Restore the document from Trash before importing it.")
        suffix = extension(document["relative_path"])
        if suffix not in TABLES:
            raise ValueError("Transaction import supports CSV and XLSX documents.")
        blob = self.store.blob_path(version["hash"])
        if blob.stat().st_size > MAX_BYTES:
            raise ValueError("The file exceeds the 32 MiB transaction import limit.")
        data = blob.read_bytes()
        if hashlib.sha256(data).hexdigest() != version["hash"]:
            raise ValueError("Preserved evidence failed its integrity check. Nothing was imported.")
        return version, parse_transactions(data, suffix, currency, mapping)

    def preview_import(self, document_id, currency, mapping=None, digest=None):
        try:
            _, (rows, used, issues, counts) = self.table_rows(document_id, digest, currency, mapping)
        except MappingError as exc:  # Readable file; the user must choose a column or date order.
            return {"error": str(exc), "mapping": exc.mapping, "issues": [], "rows": [], "totals": None,
                    "counts": {"parsed": 0, "rejected": 0, "blank": 0, "columns": exc.columns}}
        return {"error": None, "mapping": used, "issues": issues[:200], "counts": counts, **preview(rows, currency_code(currency))}

    def import_transactions(self, document_id, account_id, mapping=None, digest=None):
        account = self.account(account_id)
        version, (rows, used, issues, counts) = self.table_rows(document_id, digest, account["currency"], mapping)
        import_id = uuid.uuid4().hex
        source = {"document_id": document_id, "blob_hash": version["hash"], "source_key": "import:" + import_id}
        with self.store.connection() as db:
            inserted, duplicates = self.insert_transactions(db, account, rows, "import", source)
            db.execute("INSERT INTO transaction_imports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (import_id, document_id, version["hash"], account["id"], json.dumps(used), counts["parsed"], len(inserted),
                        len(duplicates), counts["rejected"], json.dumps(issues[:200]), now()))
        return {"import_id": import_id, "account_id": account["id"], "inserted": len(inserted), "duplicates": len(duplicates),
                "rejected": counts["rejected"], "issues": issues[:200], "mapping": used}

    # Review -------------------------------------------------------------------

    def review(self, record_type, record_id, status, note=""):
        """User review is the only path to 'verified'. Every change is recorded."""
        if record_type not in RECORD_TABLES:
            raise ValueError("Unknown financial record type.")
        if status not in ("verified", "rejected", "needs_review"):
            raise ValueError("Choose verify, reject or needs review.")
        table = RECORD_TABLES[record_type]
        with self.store.connection() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            db.execute(f"UPDATE {table} SET review_status=?,review_source='user',updated_at=? WHERE id=?", (status, now(), record_id))
            if record_type == "receipt":
                db.execute("UPDATE receipt_items SET review_status=? WHERE receipt_id=?", (status, record_id))
            if record_type == "statement" and status in ("verified", "rejected"):
                # A statement's extracted rows share its decision; rows the user reviewed individually keep theirs.
                db.execute("UPDATE transactions SET review_status=?,review_source='user',updated_at=? WHERE statement_id=? AND origin='extraction' "
                           "AND (review_status IN ('proposed','needs_review') OR review_source='automatic')", (status, now(), record_id))
            # The warnings a user counts a record despite stay on the record (undo restores them) and in its history.
            flagged = json.loads(row["validation_json"]) if "validation_json" in row.keys() else []
            if status == "verified" and flagged and not note:
                note = "Counted despite: " + " ".join(flagged)
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES(?,?,?,?,?,?)",
                       (record_type, record_id, row["review_status"], status, note[:1000], now()))
        return {"record_type": record_type, "id": record_id, "review_status": status}

    def record(self, record_type, record_id):
        """One canonical record with its rows, evidence and review history."""
        if record_type not in RECORD_TABLES:
            raise ValueError("Unknown financial record type.")
        with self.store.connection() as db:
            row = db.execute(f"SELECT * FROM {RECORD_TABLES[record_type]} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            value = dict(row)
            if "validation_json" in value:
                value["issues"] = json.loads(value.pop("validation_json"))
            if record_type == "receipt":
                value["items"] = [dict(item) for item in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY position", (record_id,))]
            if record_type == "statement":
                value["transactions"] = [dict(item) for item in db.execute("SELECT * FROM transactions WHERE statement_id=? ORDER BY posted_date,id", (record_id,))]
            for key in ("merchant_id", "provider_merchant_id", "payer_merchant_id"):
                if value.get(key):
                    value["merchant"] = db.execute("SELECT canonical_name FROM merchants WHERE id=?", (value[key],)).fetchone()[0]
            if value.get("account_id"):
                value["account"] = db.execute("SELECT display_name FROM accounts WHERE id=?", (value["account_id"],)).fetchone()[0]
            if record_type in ("transaction", "receipt"):
                value["links"] = self.links(db, record_type, record_id)
            if record_type in CORRECTABLE:
                value["corrections"] = self.corrections(db, record_type, record_id)
        # Source lines per row, so every item or transaction can be found in the transcription.
        for key, kind in (("items", "receipt_item"), ("transactions", "transaction")):
            for row in value.get(key, [])[:500]:
                row["line_ids"] = [line for evidence in self.evidence(kind, row["id"]) for line in evidence["locator"].get("line_ids", [])]
        # Exact display strings: the browser never does money arithmetic.
        for row in [value, *value.get("items", []), *value.get("transactions", [])]:
            row["display"] = {key: format_minor(amount, value["currency"]) for key, amount in row.items()
                              if key.endswith("_minor") and isinstance(amount, int)}
        value["evidence"] = self.evidence(record_type, record_id)
        value["review_history"] = self.review_history(record_type, record_id)
        return value

    def set_category(self, transaction_id, category):
        """The user's own category for one transaction. Clearing it hands the row back to the user's rules."""
        category = category_name(category) if category else None
        with self.store.connection() as db:
            if db.execute("UPDATE transactions SET category=?,category_source=?,category_rule_id=NULL,updated_at=? WHERE id=?",
                          (category, "user" if category else None, now(), transaction_id)).rowcount == 0:
                raise ValueError("Transaction not found.")
            if category is None:
                self.apply_rules(db, [transaction_id])
            row = db.execute("SELECT category,category_source FROM transactions WHERE id=?", (transaction_id,)).fetchone()
        return {"id": transaction_id, "category": row["category"], "category_source": row["category_source"]}

    # Category rules -------------------------------------------------------------
    # Rules are the user's own decisions written once: "anything from COSTCO is groceries".
    # A category set by hand on a transaction always wins over every rule.

    def rules(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT r.*,a.display_name AS account,(SELECT count(*) FROM transactions t WHERE t.category_rule_id=r.id) AS transactions "
                              "FROM category_rules r LEFT JOIN accounts a ON a.id=r.account_id ORDER BY r.category,r.pattern").fetchall()
        return [dict(row) for row in rows]

    def _rule_values(self, db, pattern, category, account_id):
        key = normalize_name(pattern)
        if not key:
            raise ValueError("Enter merchant or description words the rule should match, such as COSTCO.")
        if account_id is not None and db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
            raise ValueError("Account not found.")
        return key, category_name(category), account_id

    def add_rule(self, pattern, category, account_id=None):
        with self.store.connection() as db:
            values = self._rule_values(db, pattern, category, account_id)
            if db.execute("SELECT 1 FROM category_rules WHERE pattern=? AND coalesce(account_id,0)=coalesce(?,0)", (values[0], account_id)).fetchone():
                raise ValueError("A rule for these words already exists. Change that rule instead.")
            rule_id = db.execute("INSERT INTO category_rules(pattern,category,account_id,created_at,updated_at) VALUES(?,?,?,?,?)",
                                 (*values, now(), now())).lastrowid
            changed = self.apply_rules(db)
        return {**self.rule(rule_id), "changed": changed}

    def update_rule(self, rule_id, pattern, category, account_id=None):
        with self.store.connection() as db:
            values = self._rule_values(db, pattern, category, account_id)
            if db.execute("SELECT 1 FROM category_rules WHERE pattern=? AND coalesce(account_id,0)=coalesce(?,0) AND id<>?", (values[0], account_id, rule_id)).fetchone():
                raise ValueError("Another rule already uses these words.")
            if db.execute("UPDATE category_rules SET pattern=?,category=?,account_id=?,updated_at=? WHERE id=?", (*values, now(), rule_id)).rowcount == 0:
                raise ValueError("Rule not found.")
            changed = self.apply_rules(db)
        return {**self.rule(rule_id), "changed": changed}

    def delete_rule(self, rule_id):
        """Remove a rule. Its transactions go to the next matching rule, or back to uncategorized."""
        with self.store.connection() as db:
            if db.execute("DELETE FROM category_rules WHERE id=?", (rule_id,)).rowcount == 0:
                raise ValueError("Rule not found.")
            changed = self.apply_rules(db)
        return {"id": rule_id, "deleted": True, "changed": changed}

    def rule(self, rule_id):
        found = [rule for rule in self.rules() if rule["id"] == rule_id]
        if not found:
            raise ValueError("Rule not found.")
        return found[0]

    def apply_rules(self, db, transaction_ids=None):
        """Give every rule-managed or uncategorized transaction its best rule's category. Returns rows changed.
        The most specific rule wins: the most pattern words, then the newest."""
        rules = sorted(((set(row["pattern"].split()), row) for row in db.execute("SELECT * FROM category_rules")),
                       key=lambda item: (len(item[0]), item[1]["id"]), reverse=True)
        clause, params = "(t.category_source IS NULL OR t.category_source='rule')", []
        if transaction_ids is not None:
            ids = sorted(set(transaction_ids))
            if not ids:
                return 0
            clause += f" AND t.id IN ({','.join('?' * len(ids))})"
            params = ids
        changed = 0
        for row in db.execute("SELECT t.id,t.account_id,t.description_raw,t.category,t.category_rule_id,m.canonical_name FROM transactions t "
                              f"LEFT JOIN merchants m ON m.id=t.merchant_id WHERE {clause}", params).fetchall():
            words = set(normalize_name(f"{row['description_raw']} {row['canonical_name'] or ''}").split())
            match = next((rule for pattern, rule in rules if pattern <= words and rule["account_id"] in (None, row["account_id"])), None)
            target = (match["category"], "rule", match["id"]) if match else (None, None, None)
            if (row["category"], row["category_rule_id"]) != (target[0], target[2]):
                db.execute("UPDATE transactions SET category=?,category_source=?,category_rule_id=?,updated_at=? WHERE id=?", (*target, now(), row["id"]))
                changed += 1
        return changed

    # Budgets ------------------------------------------------------------------

    def budgets(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM budgets ORDER BY currency,category").fetchall()
        return [{**dict(row), "amount": money(row["amount_minor"], row["currency"])} for row in rows]

    def set_budget(self, category, currency, amount):
        """A monthly budget for one category and currency; setting it again changes the amount."""
        category, currency = category_name(category), currency_code(currency)
        amount_minor = to_minor(amount, currency)
        if amount_minor <= 0:
            raise ValueError("A budget must be more than zero.")
        with self.store.connection() as db:
            db.execute("INSERT INTO budgets(category,currency,amount_minor,created_at,updated_at) VALUES(?,?,?,?,?) "
                       "ON CONFLICT(category,currency) DO UPDATE SET amount_minor=excluded.amount_minor,updated_at=excluded.updated_at",
                       (category, currency, amount_minor, now(), now()))
            row = db.execute("SELECT * FROM budgets WHERE category=? AND currency=?", (category, currency)).fetchone()
        return {**dict(row), "amount": money(row["amount_minor"], row["currency"])}

    def delete_budget(self, budget_id):
        with self.store.connection() as db:
            if db.execute("DELETE FROM budgets WHERE id=?", (budget_id,)).rowcount == 0:
                raise ValueError("Budget not found.")
        return {"id": budget_id, "deleted": True}

    def review_history(self, record_type, record_id):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM review_events WHERE record_type=? AND record_id=? ORDER BY id", (record_type, record_id))]


    # Summaries and links ------------------------------------------------------

    def summaries(self, db, record_type, ids):
        """Compact display summaries keyed by record ID, fetched in bounded batches."""
        ids, found = sorted(set(ids)), {}
        for start in range(0, len(ids), SUMMARY_CHUNK):
            chunk = ids[start:start + SUMMARY_CHUNK]
            query = SUMMARY_QUERIES[record_type].format(ids=",".join("?" * len(chunk)))
            for row in db.execute(query, chunk):
                found[row["id"]] = row
        documents = {row["id"]: row["relative_path"] for row in self._documents(db, [row["document_id"] for row in found.values() if row["document_id"]])}
        return {key: {**dict(row), "record_type": record_type,
                      "amount": money(row["amount_minor"], row["currency"]) if row["amount_minor"] is not None else None,
                      "document_path": documents.get(row["document_id"])} for key, row in found.items()}

    @staticmethod
    def _documents(db, ids):
        ids = sorted(set(ids))
        for start in range(0, len(ids), SUMMARY_CHUNK):
            chunk = ids[start:start + SUMMARY_CHUNK]
            yield from db.execute(f"SELECT id,relative_path FROM occurrences WHERE id IN ({','.join('?' * len(chunk))})", chunk)

    def links(self, db, record_type, record_id):
        """Reconciliation links touching one transaction or receipt, each with its counterpart's summary."""
        rows = []
        if record_type == "transaction":
            rows += [(dict(row), "receipt", row["receipt_id"]) for row in db.execute(
                "SELECT 'receipt' AS kind,* FROM transaction_receipt_links WHERE transaction_id=? AND review_status<>'rejected'", (record_id,))]
            rows += [(dict(row), "transaction", row["to_transaction_id"] if row["from_transaction_id"] == record_id else row["from_transaction_id"])
                     for row in db.execute("SELECT link_type AS kind,* FROM transaction_links WHERE ? IN (from_transaction_id,to_transaction_id) "
                                           "AND review_status<>'rejected'", (record_id,))]
        elif record_type == "receipt":
            rows += [(dict(row), "transaction", row["transaction_id"]) for row in db.execute(
                "SELECT 'receipt' AS kind,* FROM transaction_receipt_links WHERE receipt_id=? AND review_status<>'rejected'", (record_id,))]
        counterparts = {kind: self.summaries(db, kind, [other for _, row_kind, other in rows if row_kind == kind]) for kind in ("receipt", "transaction")}
        return [{"kind": link["kind"], "id": link["id"], "review_status": link["review_status"], "match_score": link["match_score"],
                 "match_signals": link["match_method"].split("+"), "counterpart": counterparts[kind].get(other)} for link, kind, other in rows]

    # Bill payment -------------------------------------------------------------

    def set_bill_payment(self, bill_id, status, transaction_id=None, note=""):
        """The user's payment state for a bill, optionally naming the paying transaction. Audited like reviews."""
        if status not in PAYMENT_STATES:
            raise ValueError("Choose paid, unpaid or unknown.")
        if transaction_id is not None and status != "paid":
            raise ValueError("Only a paid bill can name the transaction that paid it.")
        with self.store.connection() as db:
            bill = db.execute("SELECT id,currency,payment_status FROM bills WHERE id=?", (bill_id,)).fetchone()
            if bill is None:
                raise ValueError("Bill not found.")
            if transaction_id is not None:
                payment = db.execute("SELECT currency,amount_minor,review_status FROM transactions WHERE id=?", (transaction_id,)).fetchone()
                if payment is None:
                    raise ValueError("Transaction not found.")
                if payment["currency"] != bill["currency"] or payment["amount_minor"] >= 0 or payment["review_status"] == "rejected":
                    raise ValueError("The paying transaction must be money out, in the bill's currency, and not rejected.")
            db.execute("UPDATE bills SET payment_status=?,payment_transaction_id=?,updated_at=? WHERE id=?", (status, transaction_id, now(), bill_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('bill_payment',?,?,?,?,?)",
                       (bill_id, bill["payment_status"], status, (f"Paid by transaction {transaction_id}. " if transaction_id else "") + note[:900], now()))
        return {"id": bill_id, "payment_status": status, "payment_transaction_id": transaction_id}


    # User corrections ---------------------------------------------------------

    def _correction_value(self, db, kind, field, text):
        """Validate one entered value; returns (column value, stored text)."""
        if text is None:
            return None, None
        text = " ".join(str(text).split())
        if kind == "date":
            try:
                if len(text) != 10:
                    raise ValueError
                date.fromisoformat(text)
            except ValueError:
                raise ValueError(f"Enter the {field.replace('_', ' ')} as a full date (YYYY-MM-DD).") from None
            return text, text
        if kind == "text":
            if len(text) > 60:
                raise ValueError(f"Keep the {field.replace('_', ' ')} to 60 characters or fewer.")
            return text or None, text or None
        if not text or len(text) > 120:
            raise ValueError("Enter a business name of up to 120 characters.")
        merchant = self.merchant(db, text)
        if merchant is None:
            raise ValueError("Enter a business name with letters or digits.")
        return merchant, text

    def correct(self, record_type, record_id, changes):
        """Set fields the document did not print or the model misread. Kept with the model's value in history;
        the record's review state is unchanged, and issues about the corrected fields are resolved."""
        fields = CORRECTABLE.get(record_type)
        if not fields:
            raise ValueError("This kind of record cannot be corrected here.")
        unknown = set(changes) - set(fields)
        if not changes or unknown:
            raise ValueError("Choose fields this record allows: " + ", ".join(field.replace("_", " ") for field in fields) + ".")
        table = RECORD_TABLES[record_type]
        with self.store.connection() as db:
            row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            issues = json.loads(row["validation_json"])
            for field, text in changes.items():
                column, kind, label = fields[field]
                value, stored = self._correction_value(db, kind, field, text)
                previous = self._merchant_name(db, row[column]) if kind == "name" else row[column]
                resolved = [issue for issue in issues if issue.startswith(label)]
                issues = [issue for issue in issues if not issue.startswith(label)]
                db.execute(f"UPDATE {table} SET {column}=?,updated_at=? WHERE id=?", (value, now(), record_id))
                correction = db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,created_at) VALUES(?,?,?,?,?,?,?)",
                                        (record_type, record_id, field, stored, previous, json.dumps(resolved), now())).lastrowid
            db.execute(f"UPDATE {table} SET validation_json=? WHERE id=?", (json.dumps(issues), record_id))
            if not issues and row["review_status"] == "needs_review" and row["review_source"] != "user":
                db.execute(f"UPDATE {table} SET review_status='verified',review_source='automatic' WHERE id=?", (record_id,))
                db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES(?,?,'needs_review','verified',?,?)",
                           (record_type, record_id, "Every automatic check passes after your correction.", now()))
            self.add_evidence(db, record_type, record_id, {"document_id": row["document_id"], "blob_hash": row["blob_hash"],
                                                           "source_key": f"user:correction:{correction}"}, {"entered_by_user": sorted(changes)})
        return self.record(record_type, record_id)

    def apply_corrections(self, db, record_type, record_id):
        """Re-apply the latest correction of each field after an extraction rewrote the model's values."""
        fields, table = CORRECTABLE[record_type], RECORD_TABLES[record_type]
        latest = db.execute("SELECT field,value FROM record_corrections c WHERE record_type=? AND record_id=? "
                            "AND id=(SELECT max(id) FROM record_corrections WHERE record_type=c.record_type AND record_id=c.record_id AND field=c.field)",
                            (record_type, record_id)).fetchall()
        if not latest:
            return
        issues = json.loads(db.execute(f"SELECT validation_json FROM {table} WHERE id=?", (record_id,)).fetchone()[0])
        for field, text in latest:
            column, kind, label = fields[field]
            value, _ = self._correction_value(db, kind, field, text)
            db.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (value, record_id))
            issues = [issue for issue in issues if not issue.startswith(label)]
        db.execute(f"UPDATE {table} SET validation_json=? WHERE id=?", (json.dumps(issues), record_id))

    @staticmethod
    def corrections(db, record_type, record_id):
        return [dict(row) for row in db.execute("SELECT field,value,previous,created_at FROM record_corrections WHERE record_type=? AND record_id=? ORDER BY id",
                                                (record_type, record_id))]

    @staticmethod
    def _merchant_name(db, merchant_id):
        row = db.execute("SELECT canonical_name FROM merchants WHERE id=?", (merchant_id,)).fetchone() if merchant_id else None
        return row[0] if row else None
