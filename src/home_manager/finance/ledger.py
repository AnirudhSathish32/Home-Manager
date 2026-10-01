"""Canonical ledger writes: accounts, merchants, de-duplicated transactions, evidence and review.

Only validated, normalized values reach this module. It never parses model text and
never performs floating-point arithmetic.
"""

from collections import Counter
from datetime import date
import hashlib
import json
import re
from typing import Literal
import unicodedata
import uuid

from pydantic import Field, field_validator

from ..core.categories import receipt_category
from ..core.formats import TABLES, extension
from ..core.money import currency_code, format_minor, money, to_minor
from ..documents.receipt_schema import StrictModel
from ..library.storage import now
from . import paystub, splits
from .tabular import MAX_BYTES, MappingError, parse_transactions, preview

REVIEW_STATES = ("proposed", "needs_review", "verified", "rejected")
PAYMENT_STATES = ("unknown", "unpaid", "paid")
ACCOUNT_TYPES = ("checking", "savings", "credit_card", "brokerage", "loan", "other")
RECORD_TABLES = {"statement": "statements", "transaction": "transactions", "receipt": "receipts",
                 "bill": "bills", "income_record": "income_records"}
# Excluded from spending: moving money between the household's own accounts.
NON_SPENDING = ("transfer", "payment")
SPENDING = ("purchase", "fee", "interest", "withdrawal")
# Lines read from a recorded statement the user has not reconciled receipts against yet.
# Rows that also came from an import keep counting.
HELD = "t.origin='extraction' AND EXISTS(SELECT 1 FROM statements s WHERE s.id=t.statement_id AND s.reconciliation='awaiting')"
# Rows that count toward totals: deterministic imports unless rejected; model-extracted
# rows only after the user verifies them; statement lines once their statement is reconciled.
# Everything else is reported as pending review.
COUNTABLE = f"t.review_status<>'rejected' AND (t.origin<>'extraction' OR t.review_status='verified') AND NOT ({HELD})"
# A receipt counts on its own, as spending, until a card or bank line that is not rejected replaces it.
# Refund receipts (negative totals) stay evidence until a posted credit settles them.
STANDALONE_RECEIPT = ("r.review_status='verified' AND r.total_minor>0 AND r.purchase_date IS NOT NULL AND NOT EXISTS("
                      "SELECT 1 FROM transaction_receipt_links l JOIN transactions lt ON lt.id=l.transaction_id "
                      "WHERE l.receipt_id=r.id AND l.review_status<>'rejected' AND lt.review_status<>'rejected')")
# A transaction's category: its own (set by the user or a rule), else its matched receipt's.
TRANSACTION_CATEGORY = ("coalesce(t.category,(SELECT r.category FROM transaction_receipt_links l JOIN receipts r ON r.id=l.receipt_id "
                        "WHERE l.transaction_id=t.id AND l.review_status<>'rejected' AND r.category IS NOT NULL ORDER BY l.id LIMIT 1),'uncategorized')")
# Item categories (finance/splits.py). A charge with a matched, itemised receipt is divided by that receipt's item
# categories, unless the user chose the charge's category themselves; that choice covers the whole charge.
CHARGE_SPLITS = ("s.transaction_id=t.id AND coalesce(t.category_source,'')<>'user' AND s.receipt_id=(SELECT l.receipt_id FROM "
                 "transaction_receipt_links l WHERE l.transaction_id=t.id AND l.review_status<>'rejected' ORDER BY l.id LIMIT 1)")
HAS_SPLITS = f"EXISTS(SELECT 1 FROM category_splits s WHERE {CHARGE_SPLITS})"
# Joined to transactions t: one row per item-category share, or the charge itself when it has none.
TRANSACTION_SPLITS = f"LEFT JOIN category_splits s ON {CHARGE_SPLITS}"
SPLIT_CATEGORY = f"coalesce(s.category,{TRANSACTION_CATEGORY})"
# A receipt shared by a family (record_shares, written by a family delivery) counts only this person's part of it,
# and so does the card charge matched to it: the same fraction of what the card was charged (charge_share below).
RECEIPT_SHARE = "(SELECT x.share_minor FROM record_shares x WHERE x.record_type='receipt' AND x.record_id=r.id)"
RECEIPT_SPENT = f"coalesce({RECEIPT_SHARE},r.total_minor)"
CHARGE_SHARE = ("(SELECT CASE WHEN -t.amount_minor=x.total_minor THEN x.share_minor ELSE (-t.amount_minor*x.share_minor+x.total_minor/2)/x.total_minor END "
                "FROM transaction_receipt_links l JOIN record_shares x ON x.record_type='receipt' AND x.record_id=l.receipt_id "
                "WHERE l.transaction_id=t.id AND l.review_status<>'rejected' ORDER BY l.id LIMIT 1)")
TRANSACTION_SPENT = f"coalesce({CHARGE_SHARE},-t.amount_minor)"
SPLIT_SPENT = f"coalesce(s.amount_minor,{TRANSACTION_SPENT})"
# Joined to receipts r: one row per item-category share, or the whole receipt under its own category.
RECEIPT_SPLITS = "LEFT JOIN category_splits s ON s.receipt_id=r.id AND s.transaction_id IS NULL"
RECEIPT_SPLIT_CATEGORY = "coalesce(s.category,r.category,'uncategorized')"
RECEIPT_SPLIT_SPENT = f"coalesce(s.amount_minor,{RECEIPT_SPENT})"


def charge_share(charged, share, total):
    """The part of a charge a person carries for a shared receipt: all of their share when the charge is the receipt's
    total, otherwise the same fraction of the charge, rounded half up. The same rule as CHARGE_SHARE."""
    return share if charged == total else (charged * share + total // 2) // total


def in_categories(count):
    """SQL, taking the category list twice, true for a transaction with spending in any of count categories."""
    marks = ",".join("?" * count)
    return (f"(CASE WHEN {HAS_SPLITS} THEN EXISTS(SELECT 1 FROM category_splits s WHERE {CHARGE_SPLITS} AND s.category IN ({marks})) "
            f"ELSE {TRANSACTION_CATEGORY} IN ({marks}) END)")
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
                "location": ("location", "text", "Location"), "category": ("category", "category", "Category")},
    "bill": {"issue_date": ("issue_date", "date", "Issue date"), "due_date": ("due_date", "date", "Due date"),
             "provider": ("provider_merchant_id", "name", "Provider")},
    "income_record": {"pay_date": ("pay_date", "date", "Pay date"), "payer": ("payer_merchant_id", "name", "Payer or employer")},
}
PENDING = f"(t.origin='extraction' AND t.review_status IN ('proposed','needs_review') OR t.review_status<>'rejected' AND {HELD})"
# Transactions reconciliation may match: not rejected, and not waiting on their statement.
MATCHABLE = f"t.review_status<>'rejected' AND NOT ({HELD})"

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
    filing_status: Literal["single", "married_joint", "head_of_household"] = "single"  # For the pay stub tax estimate.
    birth_year: int | None = Field(default=None, ge=1900, le=2100)  # For required minimum distributions and retirement in the forecast.
    fetch_exchange_rates: bool = True  # Download ECB reference rates for USD totals. Off means no outbound calls for rates.
    fetch_crypto_prices: bool = False  # Fetch crypto market prices (CoinGecko) for coins held. Off means no outbound calls for prices.
    rescan_hours: int = Field(default=6, ge=1, le=168)  # Full rescan of each watched folder, catching changes the watcher missed.

    @field_validator("home_currency")
    @classmethod
    def known(cls, value):
        return currency_code(value) if value else None

    @field_validator("birth_year")
    @classmethod
    def born(cls, value):
        if value is not None and value > date.today().year:
            raise ValueError("Enter the year you were born.")
        return value


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

    def insert_transactions(self, db, account, rows, origin, source, statement_id=None, review_status="proposed", refresh=()):
        """Insert or de-duplicate rows, returning (inserted_ids, duplicate_ids). Evidence is always linked.
        A duplicate whose id is in refresh takes this reading's description, dates, type and review state."""
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
                if record in refresh:
                    db.execute("UPDATE transactions SET transaction_date=?,description_raw=?,transaction_type=?,review_status=?,review_source=?,updated_at=? WHERE id=?",
                               (row.get("transaction_date"), row["description"][:500], kind, review_status,
                                "automatic" if review_status == "verified" else None, now(), record))
            self.add_evidence(db, "transaction", record, source, row["locator"])
        self.apply_rules(db, inserted)
        from .tax_tags import TaxTags  # Tax rules and suggestions for the new lines (finance/tax_tags.py imports this module).
        TaxTags(self.store).refresh(db, inserted)
        return inserted, duplicates

    # Publication of validated extraction ----------------------------------------
    # Each publication is one SQLite transaction. A record the user already verified or
    # rejected is never overwritten by a later extraction; unreviewed ones are replaced.

    def _upsert(self, db, table, source, columns):
        """Write an extraction's record unless the user has decided it; automatic acceptance can be redone.
        A file holding several receipts keeps one per segment (source["segment"], 0 for the first)."""
        segment = source.get("segment", 0) if table == "receipts" else None
        existing = db.execute(f"SELECT id,review_status,review_source FROM {table} WHERE blob_hash=?" + (" AND segment=?" if segment is not None else ""),
                              (source["blob_hash"],) + ((segment,) if segment is not None else ())).fetchone()
        if existing and existing["review_status"] in ("verified", "rejected") and existing["review_source"] == "user":
            return existing["id"], False
        columns = {**columns, "review_source": "automatic" if columns["review_status"] == "verified" else None,
                   "document_id": source["document_id"], "extraction_run_id": source["run_id"], "updated_at": now()}
        if existing:
            db.execute(f"UPDATE {table} SET {','.join(f'{name}=?' for name in columns)} WHERE id=?", (*columns.values(), existing["id"]))
            return existing["id"], True
        columns.update(blob_hash=source["blob_hash"], created_at=now(), **({"segment": segment} if segment is not None else {}))
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
                "description": record.get("description"), "location": record.get("location"), "category": record.get("category"),
                "recurrence": record.get("recurrence"), "payment_last_four": record.get("payment_last_four"),
                "review_status": status, "validation_json": json.dumps(record["issues"]),
                "return_days_printed": record.get("return_days_printed"), "return_policy_quote": record.get("return_policy_quote")})
            kept = 0
            if written:
                self.add_evidence(db, "receipt", receipt_id, source, record["locator"])
                self.apply_corrections(db, "receipt", receipt_id)
                kept = self._replace_items(db, receipt_id, record, source, status)
                if kept:
                    issues = [*record["issues"], f"This reading no longer finds {kept} item{'s' if kept > 1 else ''} you worked on; "
                              "they were kept at the end of the list. Check them against the receipt."]
                    db.execute("UPDATE receipts SET review_status='needs_review',review_source=NULL,validation_json=? WHERE id=?", (json.dumps(issues), receipt_id))
                db.execute("DELETE FROM receipt_rewards WHERE receipt_id=?", (receipt_id,))
                db.executemany("INSERT INTO receipt_rewards(receipt_id,position,kind,description,amount_text,expires_on,link,locator_json) VALUES(?,?,?,?,?,?,?,?)",
                               [(receipt_id, position, reward["kind"], reward["description"], reward["amount"], reward["expires"], reward["link"],
                                 json.dumps(reward["locator"])) for position, reward in enumerate(record.get("rewards", []), 1)])
                self.refresh_splits(db, receipt_id)
        return self._published("receipt", receipt_id, written, items=len(record["items"]), kept=kept)

    def retire_segments(self, blob_hash, keep, note="The latest reading of this file no longer finds this receipt; check how the file was split."):
        """Receipts of a file's segments that its latest reading no longer finds (keep: the segments it found; none when
        the file became a later page of a combined document). One the user never decided stops counting (rejected
        automatically, so a later reading that finds it again restores it); one the user decided keeps their decision with a note."""
        retired = 0
        with self.store.connection() as db:
            marks = ",".join("?" * len(keep))
            for row in db.execute("SELECT id,review_source,validation_json FROM receipts WHERE blob_hash=?" + (f" AND segment NOT IN ({marks})" if keep else ""),
                                  (blob_hash, *keep)).fetchall():
                issues = [issue for issue in json.loads(row["validation_json"]) if issue != note] + [note]
                if row["review_source"] == "user":
                    db.execute("UPDATE receipts SET validation_json=?,updated_at=? WHERE id=?", (json.dumps(issues), now(), row["id"]))
                else:
                    db.execute("UPDATE receipts SET review_status='rejected',review_source='automatic',validation_json=?,updated_at=? WHERE id=?",
                               (json.dumps(issues), now(), row["id"]))
                    self.refresh_splits(db, row["id"])
                retired += 1
        return retired

    @staticmethod
    def item_keys(items):
        """Reading-independent identity of receipt lines: description and line total, with an ordinal for repeated lines."""
        seen = Counter()
        for item in items:
            key = (normalize_name(item["description"]), item["line_total_minor"])
            yield (*key, seen[key])
            seen[key] += 1

    def _replace_items(self, db, receipt_id, record, source, status):
        """Write this reading's items. An item it finds again keeps its id, so its identification, write-off tags, household
        lot and the user's category stay; it takes the new text and position. One it no longer finds is removed, unless the
        user worked on it: then it is kept after the new items. Returns how many were kept that way."""
        earlier = [dict(row) for row in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,))]
        by_key = dict(zip(self.item_keys(earlier), earlier))
        matched = {}  # new position -> earlier item
        for position, key in enumerate(self.item_keys(record["items"]), 1):
            if key in by_key:
                matched[position] = by_key.pop(key)
        kept = [item for item in by_key.values() if self.item_worked_on(db, receipt_id, item)]
        for item in by_key.values():
            if item not in kept:
                db.execute("DELETE FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=?", (item["id"],))
                db.execute("DELETE FROM receipt_items WHERE id=?", (item["id"],))
        # Lines and their lots move to their new positions in two steps, as positions are unique per receipt.
        moves = {**{item["position"]: position for position, item in matched.items()},
                 **{item["position"]: len(record["items"]) + index for index, item in enumerate(kept, 1)}}
        for table in ("receipt_items", "inventory_lots"):
            db.execute(f"UPDATE {table} SET position=-position WHERE receipt_id=? AND position>0", (receipt_id,))
            db.executemany(f"UPDATE {table} SET position=? WHERE receipt_id=? AND position=?", [(new, receipt_id, -old) for old, new in moves.items()])
        # A lot whose line had already gone (a reading before this change replaced every line) keeps its product, not a position.
        db.execute("UPDATE inventory_lots SET position=NULL WHERE receipt_id=? AND position<0", (receipt_id,))
        remembered = self.remembered_categories(db, record["merchant"])
        for position, item in enumerate(record["items"], 1):
            category, category_source = remembered.get(normalize_name(item["description"])), "memory"
            if category is None:
                category, category_source = receipt_category(item.get("category")), "model"
            taxed = None if item.get("taxed") is None else int(item["taxed"])
            values = (item["description"], item["product_code"], item["quantity"], item["unit_price_minor"], item["line_total_minor"], item["discount_minor"], taxed)
            if position in matched:
                item_id, earlier_item = matched[position]["id"], matched[position]
                if earlier_item["category_source"] == "user":  # The user's own category outlives any reading.
                    category, category_source = earlier_item["category"], "user"
                db.execute("UPDATE receipt_items SET description=?,product_code=?,quantity=?,unit_price_minor=?,line_total_minor=?,discount_minor=?,taxed=?,"
                           "category=?,category_source=?,review_status=? WHERE id=?", (*values, category, category_source if category else None, status, item_id))
                db.execute("DELETE FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=?", (item_id,))
            else:
                item_id = db.execute("INSERT INTO receipt_items(receipt_id,position,description,product_code,quantity,unit_price_minor,line_total_minor,discount_minor,"
                                     "taxed,category,category_source,review_status) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (receipt_id, position, *values, category, category_source if category else None, status)).lastrowid
            self.add_evidence(db, "receipt_item", item_id, source, item["locator"])
        return len(kept)

    @staticmethod
    def item_worked_on(db, receipt_id, item):
        """Whether the user categorised, identified or tagged a receipt line, or keeps it in the household (a lot)."""
        return item["category_source"] == "user" or db.execute(
            "SELECT EXISTS(SELECT 1 FROM item_resolutions WHERE receipt_item_id=:i AND review_status='verified') "
            "OR EXISTS(SELECT 1 FROM tax_tags WHERE receipt_item_id=:i AND (source='user' OR review_status='verified')) "
            "OR EXISTS(SELECT 1 FROM inventory_lots WHERE receipt_id=:r AND position=:p)",
            {"i": item["id"], "r": receipt_id, "p": item["position"]}).fetchone()[0] == 1

    # Item categories --------------------------------------------------------------
    # Each receipt item has its own spending category; category_splits divides the money (finance/splits.py).

    @staticmethod
    def remembered_categories(db, merchant):
        """{item key: category} the user chose before for items from this seller."""
        return dict(db.execute("SELECT item_key,category FROM item_category_memory WHERE merchant_key=?", (normalize_name(merchant),)).fetchall())

    def refresh_splits(self, db, receipt_id=None):
        """Rebuild the category shares of one receipt (or every receipt) and of each charge linked to it."""
        if receipt_id is None:
            db.execute("DELETE FROM category_splits")
            for (receipt,) in db.execute("SELECT DISTINCT receipt_id FROM receipt_items").fetchall():
                self.refresh_splits(db, receipt)
            return
        db.execute("DELETE FROM category_splits WHERE receipt_id=?", (receipt_id,))
        receipt = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        items = [dict(row) for row in db.execute("SELECT id,line_total_minor,discount_minor,taxed,category FROM receipt_items "
                                                 "WHERE receipt_id=? AND review_status<>'rejected' ORDER BY position", (receipt_id,))]
        if receipt is None or receipt["total_minor"] is None or not items:
            return
        charges = [(None, receipt["total_minor"], receipt["currency"])] + [(row["id"], -row["amount_minor"], row["currency"]) for row in db.execute(
            "SELECT t.id,t.amount_minor,t.currency FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id "
            "WHERE l.receipt_id=? AND l.review_status<>'rejected'", (receipt_id,))]
        shared = db.execute("SELECT share_minor,total_minor FROM record_shares WHERE record_type='receipt' AND record_id=?", (receipt_id,)).fetchone()
        for transaction_id, target, currency in charges:
            if currency == receipt["currency"]:
                shares = splits.allocate(items, receipt["subtotal_minor"], receipt["tax_minor"], receipt["tip_minor"], target, receipt["category"])
            else:  # A card charge in another currency: share the receipt in its own currency, then resize to the charge.
                shares = splits.scale(splits.allocate(items, receipt["subtotal_minor"], receipt["tax_minor"], receipt["tip_minor"],
                                                      receipt["total_minor"], receipt["category"]), target)
            if shared:  # Each category keeps its proportion of this person's part.
                shares = splits.scale(shares, charge_share(target, shared["share_minor"], shared["total_minor"]))
            db.executemany("INSERT INTO category_splits(receipt_id,transaction_id,receipt_item_id,category,amount_minor) VALUES(?,?,?,?,?)",
                           [(receipt_id, transaction_id, None if index is None else items[index]["id"], category, amount) for index, category, amount in shares])

    def set_item_category(self, receipt_id, position, category):
        """The user's category for one receipt item, remembered for the same item from the same seller."""
        category = receipt_category(category)
        if category is None:
            raise ValueError("Choose a category from the list.")
        with self.store.connection() as db:
            item = db.execute("SELECT i.*,m.canonical_name AS merchant FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id "
                              "LEFT JOIN merchants m ON m.id=r.merchant_id WHERE i.receipt_id=? AND i.position=?", (receipt_id, position)).fetchone()
            if item is None:
                raise ValueError("Receipt item not found.")
            db.execute("UPDATE receipt_items SET category=?,category_source='user' WHERE id=?", (category, item["id"]))
            db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,?,?) "
                       "ON CONFLICT(merchant_key,item_key) DO UPDATE SET category=excluded.category,updated_at=excluded.updated_at",
                       (normalize_name(item["merchant"]), normalize_name(item["description"]), category, now()))
            self.refresh_splits(db, receipt_id)
        return {"receipt_id": receipt_id, "position": position, "category": category, "category_source": "user"}

    def publish_asset(self, record, source):
        """A loan statement's balance as the forecast loan for its account (docs/items-assets-search.md §6); investment
        statements go to finance/investments.py. One row per account: a newer statement updates it and returns it to
        proposed; an older one changes nothing."""
        kind, institution = record["asset_kind"], " ".join(record["institution"].split())
        label = record.get("account_name") or "Loan"
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
                "validation_json": json.dumps(record["issues"]), "reconciliation": "awaiting"})
            if not written:
                return self._published("statement", statement_id, False, account_id=account["id"])
            self.add_evidence(db, "statement", statement_id, source, record["locator"])
            # Rows from an earlier extraction the user has not decided (unreviewed or accepted automatically) that no other source supports.
            # A row this reading finds again (same fingerprint) keeps its id, so its tags, links and category stay; it takes the new
            # reading's text. A row it no longer finds is removed, unless the user worked on it: then it stays and the statement waits in Review.
            found = set(fingerprints(account["id"], record["transactions"]))
            earlier = db.execute(
                "SELECT t.id,t.source_fingerprint FROM transactions t WHERE t.statement_id=? AND t.origin='extraction' "
                "AND (t.review_status IN ('proposed','needs_review') OR t.review_source='automatic') "
                "AND NOT EXISTS(SELECT 1 FROM financial_evidence_links e WHERE e.record_type='transaction' AND e.record_id=t.id AND e.source_key NOT LIKE 'extraction:%')",
                (statement_id,)).fetchall()
            refresh = {row["id"] for row in earlier if row["source_fingerprint"] in found}
            missing = [row["id"] for row in earlier if row["source_fingerprint"] not in found]
            kept = [transaction for transaction in missing if self.user_worked_on(db, transaction)]
            for transaction in refresh:  # Cited from this reading only, below.
                db.execute("DELETE FROM financial_evidence_links WHERE record_type='transaction' AND record_id=? AND blob_hash=? AND source_key LIKE 'extraction:%'",
                           (transaction, source["blob_hash"]))
            for transaction in set(missing) - set(kept):
                self.remove_transaction(db, transaction)
            inserted, duplicates = self.insert_transactions(db, account, record["transactions"], "extraction", source, statement_id, status, refresh)
            if kept:
                issues = [*record["issues"], f"This reading no longer finds {len(kept)} transaction{'s' if len(kept) > 1 else ''} you worked on; "
                          "they were kept. Check them against the statement."]
                db.execute("UPDATE statements SET review_status='needs_review',review_source=NULL,validation_json=? WHERE id=?", (json.dumps(issues), statement_id))
        return self._published("statement", statement_id, True, account_id=account["id"], inserted=len(inserted), duplicates=len(duplicates), kept=len(kept))

    @staticmethod
    def user_worked_on(db, transaction_id):
        """Whether the user categorised, tagged or matched a transaction (a machine proposal does not count)."""
        return db.execute(
            "SELECT EXISTS(SELECT 1 FROM transactions WHERE id=:t AND category_source='user') "
            "OR EXISTS(SELECT 1 FROM transaction_receipt_links WHERE transaction_id=:t AND review_status='verified') "
            "OR EXISTS(SELECT 1 FROM transaction_links WHERE :t IN (from_transaction_id,to_transaction_id) AND review_status='verified') "
            "OR EXISTS(SELECT 1 FROM bills WHERE payment_transaction_id=:t) "
            "OR EXISTS(SELECT 1 FROM tax_tags WHERE transaction_id=:t AND (source='user' OR review_status='verified')) "
            "OR EXISTS(SELECT 1 FROM investment_events WHERE transaction_id=:t AND transaction_link='user')",
            {"t": transaction_id}).fetchone()[0] == 1

    @staticmethod
    def remove_transaction(db, transaction_id):
        """Delete a transaction no reading supports, with the machine-made rows that point at it. Tags, splits and
        payment rejections go by cascade; the typed-ID rows are removed here, as emptying Trash does."""
        db.execute("DELETE FROM transaction_receipt_links WHERE transaction_id=?", (transaction_id,))
        db.execute("DELETE FROM transaction_links WHERE ? IN (from_transaction_id,to_transaction_id)", (transaction_id,))
        for table in ("financial_evidence_links", "reconciliation_issues", "review_events"):
            db.execute(f"DELETE FROM {table} WHERE record_type='transaction' AND record_id=?", (transaction_id,))
        db.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))

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
                "gross_pay_ytd_minor": record.get("gross_pay_ytd_minor"), "net_pay_ytd_minor": record.get("net_pay_ytd_minor"),
                "work_state": record.get("work_state"), "pay_frequency": record.get("pay_frequency"),
                "validation_json": json.dumps(record["issues"])})
            if written:
                self.add_evidence(db, "income_record", income_id, source, record["locator"])
                self.apply_corrections(db, "income_record", income_id)
                db.execute("DELETE FROM income_lines WHERE income_record_id=?", (income_id,))
                db.executemany("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,ytd_minor,locator_json) "
                               "VALUES(?,?,?,?,?,?,?,?)",
                               [(income_id, position, line["description"], line["line_group"], line["category"], line["current_minor"],
                                 line["ytd_minor"], json.dumps(line["locator"])) for position, line in enumerate(record.get("lines", []), 1)])
        return self._published("income_record", income_id, written, lines=len(record.get("lines", [])))

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
                # Each item's share of what was paid (its price with its part of tax and discounts), and the totals by category.
                shares = dict(db.execute("SELECT receipt_item_id,amount_minor FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL "
                                         "AND receipt_item_id IS NOT NULL", (record_id,)).fetchall())
                for item in value["items"]:
                    item["share_minor"] = shares.get(item["id"])
                value["splits"] = [dict(split) for split in db.execute(
                    "SELECT category,sum(amount_minor) AS amount_minor FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL "
                    "GROUP BY 1 ORDER BY 2 DESC,1", (record_id,))]
                value["rewards"] = []
                for reward in db.execute("SELECT * FROM receipt_rewards WHERE receipt_id=? ORDER BY position", (record_id,)):
                    reward = dict(reward)
                    reward["line_ids"] = json.loads(reward.pop("locator_json")).get("line_ids", [])
                    value["rewards"].append(reward)
                value["reconciled"] = db.execute("SELECT 1 FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id WHERE l.receipt_id=? "
                                                 "AND l.review_status<>'rejected' AND t.review_status<>'rejected'", (record_id,)).fetchone() is not None
            if record_type == "transaction":
                value["splits"] = [dict(split) for split in db.execute(
                    f"SELECT s.category,sum(s.amount_minor) AS amount_minor FROM transactions t JOIN category_splits s ON {CHARGE_SPLITS} "
                    "WHERE t.id=? GROUP BY 1 ORDER BY 2 DESC,1", (record_id,))]
            if record_type == "statement":
                value["transactions"] = [dict(item) for item in db.execute("SELECT * FROM transactions WHERE statement_id=? ORDER BY posted_date,id", (record_id,))]
            if record_type == "income_record":
                value["lines"] = []
                for line in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY position", (record_id,)):
                    line = dict(line)
                    line["line_ids"] = json.loads(line.pop("locator_json")).get("line_ids", [])
                    value["lines"].append(line)
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
        for row in [value, *value.get("items", []), *value.get("transactions", []), *value.get("lines", []), *value.get("splits", [])]:
            row["display"] = {key: format_minor(amount, value["currency"]) for key, amount in row.items()
                              if key.endswith("_minor") and isinstance(amount, int)}
        if record_type == "income_record":  # Gross to net, grouped with subtotals (finance/paystub.py).
            value["breakdown"] = paystub.with_display(paystub.breakdown(value, value["lines"]), value["currency"])
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

    def _correction_value(self, db, kind, field, text, stored=False):
        """Validate one entered value; returns (column value, stored text). stored re-applies a saved correction,
        which may name a category retired since (LEGACY_CATEGORIES) until the re-sort replaces it."""
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
        if kind == "category":
            value = receipt_category(text, legacy=stored)
            return value, value
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
            if record_type == "receipt" and receipt_category(changes.get("category")):
                # The whole receipt's category is a shortcut for every item the user has not categorised one by one.
                db.execute("UPDATE receipt_items SET category=?,category_source='receipt' WHERE receipt_id=? AND coalesce(category_source,'')<>'user'",
                           (receipt_category(changes["category"]), record_id))
            if record_type == "receipt":
                self.refresh_splits(db, record_id)
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
            value, _ = self._correction_value(db, kind, field, text, stored=True)
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
