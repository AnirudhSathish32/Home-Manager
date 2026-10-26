"""Canonical ledger writes: accounts, merchants, de-duplicated transactions, evidence and review.

Only validated, normalized values reach this module. It never parses model text and
never performs floating-point arithmetic.
"""

from collections import Counter
from dataclasses import asdict
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
from typing import Literal
import unicodedata
import uuid

from pydantic import Field, field_validator, model_validator

from ..core import actor
from ..core.categories import LINE_KINDS, RECEIPT_CATEGORIES, RENT_LINE_KINDS, RENT_LINE_TYPES, receipt_category
from ..core.formats import TABLES, extension
from ..core.money import currency_code, format_minor, money, to_minor
from ..core.paths import safe_path
from ..core.trace import NULL
from ..documents.pdf_layout import PDF_EVIDENCE_BYTES
from ..documents.pdf_reader import PDFResult, read_result
from ..documents.receipt_schema import StrictModel
from ..library.storage import digest_file, now
from . import document_checks, paystub, pdf_import, splits
from .tabular import MAX_BYTES, MappingError, parse_transactions, preview

PDF_INTEGRITY = "Preserved evidence failed its integrity check. Nothing was imported."
PDF_ONLY = "Year, date order, sign, ticks and table choices apply to PDF files only."
# What must still be chosen before a PDF import (pdf_import.Analysis.required), as the refusal and the dialog say it.
REQUIRED = {"year": "Choose the year: these dates print no year, or only two digits.",
            "date_format": "Choose the date order: day first or month first.",
            "sign": "Choose whether positive amounts are money in or money out for this account."}
REVIEW_STATES = ("proposed", "needs_review", "verified", "rejected")
ACCOUNT_TYPES = ("checking", "savings", "credit_card", "brokerage", "loan", "other")
ACCOUNT_ORIGINS = ("user", "record", "family")
US_STATES = frozenset("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())
# A bill is a receipt with document_kind 'bill' (docs/money.md "Bills and their lines"), not a record type of its own.
RECORD_TABLES = {"statement": "statements", "transaction": "transactions", "receipt": "receipts", "income_record": "income_records"}
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


def confirmed(alias="a"):
    """The SQL test for an account the user has confirmed (docs/money.md "New statements wait for you"), for the accounts
    row named `alias`. Derived, not stored, so it can't drift from review history: an account Record created (origin 'record')
    waits until an import reached it, a statement in it was confirmed by the user, or one was reconciled. Undo of a Confirm
    sets the statement back to needs_review, which unconfirms the account again unless something else confirms it."""
    return (f"({alias}.origin<>'record' OR EXISTS(SELECT 1 FROM transaction_imports i WHERE i.account_id={alias}.id) "
            f"OR EXISTS(SELECT 1 FROM statements s WHERE s.account_id={alias}.id AND "
            "(s.review_status='verified' AND s.review_source='user' OR s.reconciliation='reconciled')))")


CONFIRMED = confirmed("a")
# A receipt counts on its own until a card or bank line that is not rejected replaces it: a sale as spending, a
# return (a negative total) as a refund, the same way (docs/money.md "Returns").
STANDALONE_RECEIPT = ("r.review_status='verified' AND r.total_minor<>0 AND r.purchase_date IS NOT NULL AND NOT EXISTS("
                      "SELECT 1 FROM transaction_receipt_links l JOIN transactions lt ON lt.id=l.transaction_id "
                      "WHERE l.receipt_id=r.id AND l.review_status<>'rejected' AND lt.review_status<>'rejected')")
# A verified pay stub counts as net pay on its pay date until the bank deposit that paid it is linked, the same way a
# receipt counts until its charge does (docs/money.md "Money in and paystubs").
STANDALONE_INCOME = ("i.review_status='verified' AND i.net_pay_minor>0 AND i.pay_date IS NOT NULL AND NOT EXISTS("
                     "SELECT 1 FROM transaction_income_links l JOIN transactions lt ON lt.id=l.transaction_id "
                     "WHERE l.income_record_id=i.id AND l.review_status<>'rejected' AND lt.review_status<>'rejected')")
# A transaction's category: its own (set by the user or a rule), else its matched receipt's; a refund with neither takes
# the category of the purchase it refunds (docs/money.md "Returns").
TRANSACTION_CATEGORY = ("coalesce(t.category,(SELECT r.category FROM transaction_receipt_links l JOIN receipts r ON r.id=l.receipt_id "
                        "WHERE l.transaction_id=t.id AND l.review_status<>'rejected' AND r.category IS NOT NULL ORDER BY l.id LIMIT 1),"
                        "(SELECT coalesce(pt.category,(SELECT pr.category FROM transaction_receipt_links pl JOIN receipts pr ON pr.id=pl.receipt_id "
                        "WHERE pl.transaction_id=pt.id AND pl.review_status<>'rejected' AND pr.category IS NOT NULL ORDER BY pl.id LIMIT 1)) "
                        "FROM transaction_links pk JOIN transactions pt ON pt.id=pk.from_transaction_id WHERE t.transaction_type='refund' "
                        "AND pk.link_type='refund' AND pk.to_transaction_id=t.id AND pk.review_status<>'rejected' ORDER BY pk.id LIMIT 1),'uncategorized')")
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
# Worked on magnitudes, then signed, so SQLite (which truncates) and charge_share (which floors) agree on a refund's share.
CHARGE_SHARE = ("(SELECT CASE WHEN -t.amount_minor=x.total_minor THEN x.share_minor ELSE (abs(t.amount_minor*x.share_minor)+abs(x.total_minor)/2)/abs(x.total_minor)"
                "*(CASE WHEN (-t.amount_minor*x.share_minor<0)=(x.total_minor<0) THEN 1 ELSE -1 END) END "
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
    total, otherwise the same fraction of the charge, its size rounded half up. The same rule as CHARGE_SHARE; a refund's
    amounts are negative."""
    if charged == total:
        return share
    sign = 1 if (charged * share < 0) == (total < 0) else -1
    return sign * ((abs(charged * share) + abs(total) // 2) // abs(total))


def receipt_direction(row):
    """'return' for a receipt that gives money back (a negative total), otherwise 'sale'."""
    return "return" if (row["total_minor"] or 0) < 0 else "sale"


def sale_label(total, lines):
    """The tag a receipt shows: Exchange when it has lines both bought and returned, Return when it gives money back,
    otherwise None."""
    lines = [line for line in lines if line]
    if any(line < 0 for line in lines) and any(line > 0 for line in lines):
        return "Exchange"
    return "Return" if (total or 0) < 0 or (lines and all(line < 0 for line in lines)) else None


SALE_LABEL_SQL = ("CASE WHEN EXISTS(SELECT 1 FROM receipt_items i WHERE i.receipt_id=r.id AND i.line_total_minor<0) "
                  "AND EXISTS(SELECT 1 FROM receipt_items i WHERE i.receipt_id=r.id AND i.line_total_minor>0) THEN 'Exchange' "
                  "WHEN r.total_minor<0 THEN 'Return' END")


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
               f"NULL AS account,r.document_id,{SALE_LABEL_SQL} AS sale_label,r.document_kind,r.due_date FROM receipts r "
               "LEFT JOIN merchants m ON m.id=r.merchant_id WHERE r.id IN ({ids})",
    "statement": "SELECT s.id,s.period_end AS date,a.institution AS name,coalesce(s.closing_balance_minor,s.statement_balance_minor) AS amount_minor,"
                 "s.currency,s.review_status,a.display_name AS account,s.document_id FROM statements s JOIN accounts a ON a.id=s.account_id WHERE s.id IN ({ids})",
    "income_record": "SELECT i.id,i.pay_date AS date,m.canonical_name AS name,i.net_pay_minor AS amount_minor,i.currency,i.review_status,"
                     "NULL AS account,i.document_id FROM income_records i LEFT JOIN merchants m ON m.id=i.payer_merchant_id WHERE i.id IN ({ids})",
}
SUMMARY_CHUNK = 500  # Bound on bound parameters per query.
# Fields the user may correct: record type -> field -> (column, kind, label used in validation issues).
CORRECTABLE = {
    "receipt": {"purchase_date": ("purchase_date", "date", "Purchase date"), "merchant": ("merchant_id", "name", "Merchant"),
                **{field: (field + "_minor", "receipt_money", field.capitalize()) for field in ("subtotal", "tax", "tip", "total")},
                "location": ("location", "text", "Location"), "category": ("category", "category", "Category"),
                # sale or return: the signs of the receipt's amounts (docs/money.md "Returns").
                "direction": ("total_minor", "sale_type", "Sale or return"),
                "document_kind": ("document_kind", "document_kind", "Record as"),
                # A bill's own (BILL_FIELDS); its due date is also the date it counts on (purchase_date).
                "issue_date": ("issue_date", "date", "Issue date"), "due_date": ("due_date", "date", "Due date"),
                "period_start": ("period_start", "date", "Period start"), "period_end": ("period_end", "date", "Period end"),
                "amount_due": ("amount_due_minor", "money", "Amount due")},
    "income_record": {"pay_date": ("pay_date", "date", "Pay date"), "payer": ("payer_merchant_id", "name", "Payer or employer"),
                      "period_start": ("period_start", "date", "Period start"), "period_end": ("period_end", "date", "Period end"),
                      "pay_frequency": ("pay_frequency", "pay_frequency", "Pay frequency"),
                      "work_state": ("work_state", "work_state", "Work state"),
                      "gross_pay": ("gross_pay_minor", "money", "Gross pay"), "net_pay": ("net_pay_minor", "money", "Net pay"),
                      "gross_pay_ytd": ("gross_pay_ytd_minor", "money", "Gross pay year to date"),
                      "net_pay_ytd": ("net_pay_ytd_minor", "money", "Net pay year to date"),
                      "taxes": ("taxes_minor", "money", "Taxes this period"),
                      "deductions": ("deductions_minor", "money", "Pre-tax deductions this period")},
    "statement": {"period_start": ("period_start", "date", "Period start"), "period_end": ("period_end", "date", "Period end"),
                  "issue_date": ("issue_date", "date", "Issue date"), "due_date": ("due_date", "date", "Due date"),
                  "opening_balance": ("opening_balance_minor", "money", "Opening balance"),
                  "closing_balance": ("closing_balance_minor", "money", "Closing balance"),
                  "statement_balance": ("statement_balance_minor", "money", "Statement balance"),
                  "minimum_payment": ("minimum_payment_minor", "money", "Minimum payment")},
}
# Which receipt fields a bill shows, and what it calls them: a bill has no tip or store location, and counts its new
# charges (total), not past-due balances (docs/money.md "Bills and their lines").
BILL_FIELDS = ("issue_date", "due_date", "period_start", "period_end", "amount_due")
# A bank statement prints no card balance, minimum payment or due date, and a card statement keeps its previous and new
# balances in its summary, not as an opening and closing balance: neither is offered for correction on the other type.
OTHER_STATEMENT_FIELDS = {"bank": ("statement_balance", "minimum_payment", "due_date"), "credit_card": ("opening_balance", "closing_balance")}
BILL_SHOWN = {"document_kind": "Record as", "merchant": "Provider", "issue_date": "Issue date", "due_date": "Due date", "period_start": "Period start",
              "period_end": "Period end", "total": "New charges", "amount_due": "Amount due", "category": "Category"}
# A bill line's own corrections, kept by printed position like an item's price ("line_kind:3", "member:3"): field -> column.
# A rent bill's line has a rent type ("line_type:3", specs/bill-kinds FR-45), which also sets its mapped line_kind.
LINE_FIELDS = {"line_kind": "line_kind", "line_type": "line_type", "member": "member_id"}
TRANSACTION_TYPES = ("purchase", "refund", "payment", "transfer", "deposit", "fee", "interest", "withdrawal", "other")
# A transaction's fields a person may correct when the import or the reading got them wrong (docs/money.md "Corrections"):
# field -> (column, kind). The amount is entered positive, and its direction is a field of its own.
TRANSACTION_CORRECTABLE = {"posted_date": ("posted_date", "date"), "amount": ("amount_minor", "amount"), "direction": ("amount_minor", "direction"),
                           "merchant": ("merchant_id", "name"), "transaction_type": ("transaction_type", "type")}
# What a transaction's fields are called in its history and Correct form; category is set on its own (set_category).
TRANSACTION_LABELS = {"posted_date": "Date", "amount": "Amount", "direction": "Money in or out", "merchant": "Merchant",
                      "transaction_type": "Type", "category": "Category"}
# The review note when a correction clears a record's last issue; with no actor, the history shows it as automatic.
AUTO_VERIFIED_NOTE = "Every automatic check passes after your correction."
UNDO_REASON = "Undid a change"
# A receipt's printed details a person may correct, as "detail:<name>" (docs/money.md "Corrections"): name -> (kind, label).
# A tender's amount is "detail:tenders.<n>.amount", n counted from 1.
DETAIL_CORRECTABLE = {"volume": ("decimal_text", "Fuel volume"), "price_per_unit": ("decimal_text", "Fuel price per unit"),
                      "pump_number": ("decimal_text", "Pump number"), "fuel_amount": ("money", "Fuel amount"), "gratuity": ("money", "Gratuity"),
                      "party_size": ("decimal_text", "Party size"), "savings_total": ("money", "Savings total")}
TENDER_LABELS = {"gift_card": "Gift card", "ebt": "EBT", "card": "Card", "cash": "Cash", "other": "Payment"}
# What decides a receipt's amount paid after gift cards (refresh_paid): corrections to these fields, or any detail.
PAID_FIELDS = ("total", "direction", "document_kind", "receipt_kind")
# The notes refresh_paid owns: each run removes them all and adds back only the current ones.
PAID_ISSUES = ("Gift card on a return", "Gift card deductions exceed", "Amount paid (")


def kind_column(row):
    """The column holding a receipts row's kind: bill_kind for a bill, receipt_kind otherwise (specs/bill-kinds P1).
    Its details are details_json[<that kind>]."""
    return "bill_kind" if row["document_kind"] == "bill" else "receipt_kind"


UNITS_SHOWN = {"gallon": "gal", "litre": "L"}


def shown_details(found, currency):
    """Printed details with the text the page shows for each value (the browser does no money formatting): an
    amount's display, or a number's text with its unit ("10.312 gal", "56.00 hrs")."""
    if isinstance(found, list):
        return [shown_details(entry, currency) for entry in found]
    if not isinstance(found, dict):
        return found
    shown = {key: shown_details(entry, currency) for key, entry in found.items()}
    price = shown.get("price_per_unit")
    if isinstance(price, dict) and price.get("unit"):  # A price per gallon or litre: "3.459/gal".
        price["display"] = f"{price['text']}/{UNITS_SHOWN.get(price['unit'], price['unit'])}"
    if "locator" in found and isinstance(found.get("minor"), int):
        shown["display"] = format_minor(found["minor"], currency)
    elif "locator" in found and found.get("text") is not None:
        unit = found.get("unit")
        shown["display"] = f"{found['text']} {UNITS_SHOWN.get(unit, unit)}" if unit else found["text"]
    return shown


def field_labels(record_type, bill=False):
    """What a record type's correctable fields are called (a bill's as BILL_SHOWN names them)."""
    if record_type == "transaction":
        return TRANSACTION_LABELS
    labels = {field: label for field, (_, _, label) in CORRECTABLE.get(record_type, {}).items()}
    return {**labels, **BILL_SHOWN} if bill else labels


def fields_for(record_type, row):
    """The correctable fields of one record: a bill's (BILL_SHOWN), a receipt's without the bill-only ones, or a statement's
    without the other statement type's (OTHER_STATEMENT_FIELDS)."""
    fields = CORRECTABLE.get(record_type, {})
    if record_type == "statement":
        return {field: value for field, value in fields.items() if field not in OTHER_STATEMENT_FIELDS.get(row["statement_type"], ())}
    if record_type != "receipt":
        return fields
    if row["document_kind"] == "bill":
        return {field: (column, kind, BILL_SHOWN[field]) for field, (column, kind, _) in fields.items() if field in BILL_SHOWN}
    return {field: value for field, value in fields.items() if field not in BILL_FIELDS}
PENDING = f"(t.origin='extraction' AND t.review_status IN ('proposed','needs_review') OR t.review_status<>'rejected' AND {HELD})"
# Transactions reconciliation may match: not rejected, and not waiting on their statement.
MATCHABLE = f"t.review_status<>'rejected' AND NOT ({HELD})"

TRANSFER = re.compile(r"\b(TRANSFER|XFER|TRNSFR)\b")
CARD_PAYMENT = re.compile(r"\b(PAYMENT|AUTOPAY|AUTO PAY|AUTOMATIC PAYMENT|PMT|THANK YOU)\b")
REFUND = re.compile(r"\b(REFUND|RETURN|REVERSAL|CREDIT ADJ)\b")
# A receipt line saying money goes back to the customer (docs/money.md "Returns"); a return policy line never does.
RETURN_WORDS = re.compile(r"\b(REFUNDS?|REFUNDED|RETURNS?|RETURNED|REVERSAL|CREDIT ADJ|MERCHANDISE CREDIT|STORE CREDIT|EXCHANGE|CREDIT TO)\b")
RETURN_POLICY = re.compile(r"\b(POLICY|POLICIES|WITHIN|DAYS?|RECEIPT REQUIRED)\b")


def says_return(text):
    """Whether printed text marks a refund or return, not a return policy."""
    text = (text or "").upper()
    return bool(RETURN_WORDS.search(text)) and not RETURN_POLICY.search(text)
STORE_NOISE = re.compile(r"#\s*\d+|\b\d+\b|[^\w\s&]")
LEGAL_SUFFIX = re.compile(r"\b(INC|LLC|LTD|CO|CORP|CORPORATION|COMPANY)\b")


def clean_reason(text):
    """A correction's optional reason: one line of up to 500 characters, or None."""
    text = " ".join((text or "").split())
    if len(text) > 500:
        raise ValueError("Keep the reason under 500 characters.")
    return text or None


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


identities = fingerprints  # insert_transactions has a parameter of the same name.


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
    tax_engine: Literal["engine_1"] = "engine_1"  # The engine slot that works out the year's return (finance/tax_engine.py).
    tax_engine_compare: bool = True  # Also work it out with another engine that can run here (Engine 2), and show where they differ.

    @model_validator(mode="before")
    @classmethod
    def retired_keys(cls, value):
        # ui_v2_screens chose redesigned screens while both UIs shipped; every screen is redesigned now.
        if isinstance(value, dict) and "ui_v2_screens" in value:
            value = {key: item for key, item in value.items() if key != "ui_v2_screens"}
        return value

    @field_validator("tax_engine", mode="before")
    @classmethod
    def engine_slot(cls, value):
        # Engine names saved before the numbered slots: their work is done by Engine 1 now.
        return {"builtin": "engine_1", "opentax": "engine_1"}.get(value, value)

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


STATEMENT_TYPES = (("credit_card",), ("checking", "savings", "other"))


def default_account_name(institution, account_type, last_four):
    """The name an account gets unless one is given. It leaves out the type when the institution already ends with it
    ("Household checking", not "Household checking checking"); migration 065 renamed older rows the same way."""
    kind = account_type.replace("_", " ")
    default = institution if institution.lower() == kind or institution.lower().endswith(" " + kind) else f"{institution} {kind}"
    return f"{default}{' ' + last_four if last_four else ''}"[:160]


# The account type a bank statement's printed type word gives its account (document forms FR-25); other or none: checking.
PRINTED_ACCOUNT_TYPES = {"checking": "checking", "savings": "savings", "money_market": "savings"}


def statement_types(account_type):
    """The account types one statement searches together (publish_statement): a card statement the cards, a bank statement
    checking, savings and other. Any other type only itself."""
    return next((group for group in STATEMENT_TYPES if account_type in group), (account_type,))


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

    def account_in(self, db, institution, account_type, currency, display_name=None, last_four=None, origin="user"):
        """Find or create an account inside the caller's transaction. origin says who makes it: 'user' (confirmed at once),
        'record' (a statement Record read: it waits for Confirm) or 'family' (a family delivery). Adding by hand an account
        that waits for Confirm confirms it: an existing 'record' account found with origin 'user' takes that origin."""
        if origin not in ACCOUNT_ORIGINS:
            raise ValueError("Unknown account origin.")
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
            if origin == "user" and existing["origin"] == "record":
                db.execute("UPDATE accounts SET origin='user',updated_at=? WHERE id=?", (now(), existing["id"]))
                existing = dict(db.execute("SELECT * FROM accounts WHERE id=?", (existing["id"],)).fetchone())
            return existing
        cursor = db.execute("INSERT INTO accounts(institution,account_type,display_name,account_last_four,currency,origin,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                            (institution, account_type, display_name[:160] if display_name else default_account_name(institution, account_type, last_four),
                             last_four, currency, origin, now(), now()))
        return dict(db.execute("SELECT * FROM accounts WHERE id=?", (cursor.lastrowid,)).fetchone())

    def retype_account(self, db, account, account_type):
        """A checking account a later statement prints as savings (or the other way): the printed type wins, and a name
        still the default follows it; a name the user gave is kept. No account of that type has the same identity
        (publish_statement looks for one first)."""
        name = account["display_name"]
        if name == default_account_name(account["institution"], account["account_type"], account["account_last_four"]):
            name = default_account_name(account["institution"], account_type, account["account_last_four"])
        db.execute("UPDATE accounts SET account_type=?,display_name=?,updated_at=? WHERE id=?", (account_type, name, now(), account["id"]))
        return dict(db.execute("SELECT * FROM accounts WHERE id=?", (account["id"],)).fetchone())

    def find_account(self, db, institution, account_types, last_four):
        """The institution matches whatever its case: a statement prints "FIRST LOCAL BANK" for the account the user named
        "First Local Bank". An exact match wins. Accounts saved before that may differ only by case; when the institution
        matches several of them and none exactly, none is guessed: ValueError (docs/money.md "New statements wait for you")."""
        institution = " ".join((institution or "").split())[:120]
        rows = db.execute(f"SELECT * FROM accounts WHERE institution=? COLLATE NOCASE AND account_type IN ({','.join('?' * len(account_types))}) "
                          "AND coalesce(account_last_four,'')=? ORDER BY institution=? DESC, id",
                          (institution, *account_types, last_four or "", institution)).fetchall()
        if len(rows) > 1 and rows[0]["institution"] != institution:
            names = ", ".join(f'"{row["display_name"]}"' for row in rows)
            raise ValueError(f'"{institution}" matches {len(rows)} accounts whose institutions differ only in case ({names}), '
                             "so none was chosen. Rename all but one of them on Accounts, then try again.")
        return dict(rows[0]) if rows else None

    def case_twin(self, db, account, institution):
        """Another account a statement could take for this one under `institution`: same institution whatever its case, same
        last four (NULL-aware), and a type the same statement searches (statement_types). Its row, or None."""
        types = statement_types(account["account_type"])
        return db.execute(f"SELECT * FROM accounts WHERE id<>? AND institution=? COLLATE NOCASE AND account_type IN ({','.join('?' * len(types))}) "
                          "AND coalesce(account_last_four,'')=coalesce(?,'') ORDER BY id LIMIT 1",
                          (account["id"], institution, *types, account["account_last_four"])).fetchone()

    def institution_clash(self, db, account):
        """Whether another account has this account's institution in another case where a statement would look for both: the
        clash find_account refuses to guess. Only then may the institution be changed (see rename_account)."""
        return self.case_twin(db, account, account["institution"]) is not None

    def rename_account(self, account_id, institution, display_name):
        """Change an account's name, and its institution only to settle a clash (institution_clash). Statements and family
        sync find an account by its institution, type and last four, so changing it otherwise would make the next Record
        of its statement create a second account. The new institution may not be one a statement would also find another
        account under, whatever its case (docs/money.md "New statements wait for you")."""
        institution, display_name = " ".join((institution or "").split())[:120], " ".join((display_name or "").split())[:160]
        if not institution:
            raise ValueError("Enter the account's institution.")
        if not display_name:
            raise ValueError("Enter a name for the account.")
        with self.store.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            account = self.account(account_id, db)
            if institution != account["institution"]:
                if not self.institution_clash(db, account):
                    raise ValueError("Statements find this account by its institution, so it stays as it is. Only the name can be changed.")
                clash = self.case_twin(db, account, institution)
                if clash:
                    raise ValueError(f'"{clash["display_name"]}" already has this institution and last four. Choose a different institution.')
            db.execute("UPDATE accounts SET institution=?,display_name=?,updated_at=? WHERE id=?", (institution, display_name, now(), account_id))
            return self.account(account_id, db)

    def account(self, account_id, db=None):
        """The account row; on `db` when given, so it is read inside the caller's transaction."""
        if db is None:
            with self.store.connection() as db:
                return self.account(account_id, db)
        row = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None:
            raise ValueError("Account not found.")
        return dict(row)

    def accounts(self):
        """The accounts the user has confirmed. One filter here keeps an account that waits for Confirm off every list built from
        it: Accounts, Today, Forecast, the pickers and the assistant's get_accounts (docs/money.md "New statements wait for you")."""
        with self.store.connection() as db:
            return [dict(row) for row in db.execute(f"SELECT a.* FROM accounts a WHERE {CONFIRMED} ORDER BY a.institution, a.account_type, a.account_last_four")]

    def waiting_accounts(self):
        """The accounts that wait for Confirm, each with its newest statement that isn't rejected (the document to open and
        confirm), else None. Kept out of accounts(), so nothing counts them."""
        with self.store.connection() as db:
            return [dict(row) for row in db.execute(
                "SELECT a.*,s.id AS statement_id,s.document_id AS statement_document_id FROM accounts a LEFT JOIN statements s ON s.id="
                "(SELECT max(x.id) FROM statements x WHERE x.account_id=a.id AND x.review_status<>'rejected') "
                f"WHERE NOT {CONFIRMED} ORDER BY a.institution, a.account_type, a.account_last_four, a.id")]

    def account_confirmed(self, db, account_id):
        return db.execute(f"SELECT 1 FROM accounts a WHERE a.id=? AND {CONFIRMED}", (account_id,)).fetchone() is not None

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

    def insert_transactions(self, db, account, rows, origin, source, statement_id=None, review_status="proposed", refresh=(), fingerprints=None):
        """Insert or de-duplicate rows, returning (inserted_ids, duplicate_ids). Evidence is always linked.
        A duplicate whose id is in refresh takes this reading's description, dates, type and review state.
        fingerprints: the rows' identities when the caller worked them out over a larger set (a PDF import ticks rows, but
        unticking one must not renumber another); by default they are worked out over `rows`."""
        inserted, duplicates = [], []
        for row, fingerprint in zip(rows, identities(account["id"], rows) if fingerprints is None else fingerprints):
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

    def add_manual_transaction(self, account_id, posted_date, description, amount, direction, category=None):
        """A payment entered by hand (docs/money.md): it counts at once, with the person who entered it, and the
        statement or import line for the same payment replaces it when it arrives (reconcile.replace_manual).
        amount: positive text in the account's currency; direction: "out" (money leaves) or "in"."""
        if direction not in ("out", "in"):
            raise ValueError("Choose money out or money in.")
        try:
            day = date.fromisoformat(posted_date).isoformat()
        except (TypeError, ValueError):
            raise ValueError("Enter the date as YYYY-MM-DD.") from None
        text = " ".join((description or "").split())
        if not text or len(text) > 200:
            raise ValueError("Describe the payment in up to 200 characters.")
        with self.store.connection() as db:
            account = db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
            if account is None:
                raise ValueError("Account not found.")
            if not self.account_confirmed(db, account_id):  # The pickers don't offer it; only a crafted request gets here.
                raise ValueError("This account waits for you to confirm its statement.")
            minor = to_minor(amount, account["currency"])
            if minor <= 0:
                raise ValueError("Enter an amount above zero; choose money out or in separately.")
            signed = -minor if direction == "out" else minor
            kind = classify_transaction(text, signed, account["account_type"])
            transaction_id = db.execute(
                "INSERT INTO transactions(account_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,review_source,"
                "source_fingerprint,actor,created_at,updated_at) VALUES(?,?,?,?,?,?,'manual','verified','user',?,?,?,?)",
                (account_id, day, text, signed, account["currency"], kind, f"manual:{uuid.uuid4().hex}", actor.current(), now(), now())).lastrowid
            db.execute("UPDATE transactions SET merchant_id=? WHERE id=?", (self.merchant(db, text), transaction_id))
            if category:
                db.execute("UPDATE transactions SET category=?,category_source='user' WHERE id=?", (category_name(category), transaction_id))
            else:
                self.apply_rules(db, [transaction_id])
        return self.record("transaction", transaction_id)

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
            # A bill's kind is in bill_kind, a receipt's in receipt_kind (kind_column); the other stays empty.
            column = kind_column({"document_kind": record.get("document_kind", "receipt")})
            kind = record.get(column)
            before = db.execute(f"SELECT {column} FROM receipts WHERE blob_hash=? AND segment=?", (source["blob_hash"], source.get("segment", 0))).fetchone()
            receipt_id, written = self._upsert(db, "receipts", source, {
                # The kind it was read with and that kind's details, beside any other kind's (docs/documents.md "Receipt kinds").
                # The printed total is written as the total; refresh_paid then counts what was paid after gift cards.
                "receipt_kind": kind if column == "receipt_kind" else None, "bill_kind": kind if column == "bill_kind" else None,
                "details_json": self.merged_details(db, source, kind, record.get("details")), "printed_total_minor": None,
                "pending_details_json": None,
                "merchant_id": self.merchant(db, record["merchant"]) if record["merchant"] else None,
                "purchase_date": record["purchase_date"], "subtotal_minor": record["subtotal_minor"], "tax_minor": record["tax_minor"],
                "tip_minor": record["tip_minor"], "total_minor": record["total_minor"], "currency": record["currency"],
                "description": record.get("description"), "location": record.get("location"), "category": record.get("category"),
                "recurrence": record.get("recurrence"), "payment_last_four": record.get("payment_last_four"),
                "review_status": status, "validation_json": json.dumps(record["issues"]),
                "return_days_printed": record.get("return_days_printed"), "return_policy_quote": record.get("return_policy_quote"),
                "document_kind": record.get("document_kind", "receipt"), "issue_date": record.get("issue_date"), "due_date": record.get("due_date"),
                "period_start": record.get("period_start"), "period_end": record.get("period_end"),
                "amount_due_minor": record.get("amount_due_minor"), "account_last_four": record.get("account_last_four"),
                "invoice_json": json.dumps(record["invoice"]) if record.get("invoice") else None})
            kept = 0
            if source.get("kind_change") and kind:
                # The user's kind change (docs/documents.md "Receipt kinds"), recorded with the reading it asked for.
                db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,actor,created_at) "
                           f"VALUES('receipt',?,'{column}',?,?,'[]',?,?)", (receipt_id, kind, before[column] if before else None,
                                                                             actor.current(), now()))
                if not written:  # Reviewed: amounts, items and review state stay; the kind's details wait for Apply details.
                    db.execute(f"UPDATE receipts SET {column}=?,pending_details_json=?,updated_at=? WHERE id=?",
                               (kind, json.dumps({"kind": kind, "details": record.get("details") or {}, "run_id": source["run_id"], "proposed_at": now()}),
                                now(), receipt_id))
            if written:
                self.add_evidence(db, "receipt", receipt_id, source, record["locator"])
                kept = self._replace_items(db, receipt_id, record, source, status)
                if kept:
                    issues = [*record["issues"], f"This reading no longer finds {kept} item{'s' if kept > 1 else ''} you worked on; "
                              "they were kept at the end of the list. Check them against the receipt."]
                    db.execute("UPDATE receipts SET review_status='needs_review',review_source=NULL,validation_json=? WHERE id=?", (json.dumps(issues), receipt_id))
                # After the items: a sale-or-return correction signs them as well as the totals.
                self.apply_corrections(db, "receipt", receipt_id)
                self.refresh_paid(db, receipt_id)
                db.execute("DELETE FROM receipt_rewards WHERE receipt_id=?", (receipt_id,))
                db.executemany("INSERT INTO receipt_rewards(receipt_id,position,kind,description,amount_text,expires_on,link,locator_json,created_at,updated_at) "
                               "VALUES(?,?,?,?,?,?,?,?,?,?)",
                               [(receipt_id, position, reward["kind"], reward["description"], reward["amount"], reward["expires"], reward["link"],
                                 json.dumps(reward["locator"]), now(), now()) for position, reward in enumerate(record.get("rewards", []), 1)])
                self.refresh_splits(db, receipt_id)
        return self._published("receipt", receipt_id, written, items=len(record["items"]), kept=kept)

    @staticmethod
    def merged_details(db, source, kind, details):
        """A receipt's details by kind: this reading replaces only the entry for the kind it read, so an earlier kind's
        details come back with an undo of a kind change. None for a record not read with kinds (a bill read before bill kinds).
        kind is the receipt kind or, for a bill, the bill kind (kind_column)."""
        if kind is None:
            return None
        row = db.execute("SELECT details_json FROM receipts WHERE blob_hash=? AND segment=?", (source["blob_hash"], source.get("segment", 0))).fetchone()
        found = json.loads(row["details_json"]) if row and row["details_json"] else {}
        return json.dumps({**found, kind: details or {}})

    def chosen_kind(self, blob_hash, segment, field="receipt_kind"):
        """The kind the user last chose for the receipt or bill at this file part, or None (none chosen, or undone back
        to none). field: the kind correction that fits the reading, receipt_kind or bill_kind (kind_column)."""
        if field not in ("receipt_kind", "bill_kind"):
            raise ValueError("Unknown kind field.")
        with self.store.connection() as db:
            row = db.execute("SELECT c.value FROM record_corrections c JOIN receipts r ON r.id=c.record_id WHERE c.record_type='receipt' "
                             "AND c.field=? AND r.blob_hash=? AND r.segment=? ORDER BY c.id DESC LIMIT 1", (field, blob_hash, segment)).fetchone()
        return row[0] if row and row[0] else None

    def apply_details(self, receipt_id):
        """Apply details (FR-12): the details read for a reviewed receipt's new kind become current, as a correction with
        Undo. Amounts and the review state don't change, even with a gift card (decision D-P4)."""
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            pending = json.loads(row["pending_details_json"] or "null")
            if not pending:
                raise ValueError("There are no details waiting to be applied.")
            everything = json.loads(row["details_json"] or "{}")
            previous = everything.get(pending["kind"])
            everything[pending["kind"]] = pending["details"]
            db.execute("UPDATE receipts SET details_json=?,pending_details_json=NULL,updated_at=? WHERE id=?", (json.dumps(everything), now(), receipt_id))
            correction = db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,actor,created_at) "
                                    "VALUES('receipt',?,'receipt_details',?,?,'[]',?,?)",
                                    (receipt_id, pending["kind"], json.dumps(previous) if previous is not None else None, actor.current(), now())).lastrowid
        return {**self.record("receipt", receipt_id), "correction_ids": [correction]}

    def _undo_kind(self, db, receipt_id, row):
        """Undo a kind change or an Apply details (undo_corrections). A kind change puts the earlier kind back, so its
        details are current again, and drops any proposal for the undone kind; undoing Apply details puts them back to
        wait. Each is recorded, so later readings see the undone choice. A bill put back to a kind other than rent loses
        its lines' rent types; each line keeps its line_kind (specs/bill-kinds FR-42)."""
        receipt = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        if row["field"] in ("receipt_kind", "bill_kind"):
            column = row["field"]
            db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,reason,actor,created_at) "
                       f"VALUES('receipt',?,'{column}',?,?,'[]',?,?,?)", (receipt_id, row["previous"], row["value"], UNDO_REASON, actor.current(), now()))
            db.execute(f"UPDATE receipts SET {column}=?,pending_details_json=NULL,updated_at=? WHERE id=?", (row["previous"], now(), receipt_id))
            if column == "bill_kind" and row["previous"] != "rent":
                db.execute("UPDATE receipt_items SET line_type=NULL,updated_at=? WHERE receipt_id=? AND line_type IS NOT NULL", (now(), receipt_id))
            return
        if row["value"] is None:
            raise ValueError("Those details were already put back to wait; apply them again instead.")
        everything = json.loads(receipt["details_json"] or "{}")
        applied = everything.get(row["value"])
        if row["previous"] is None:
            everything.pop(row["value"], None)
        else:
            everything[row["value"]] = json.loads(row["previous"])
        pending = {"kind": row["value"], "details": applied or {}, "run_id": None, "proposed_at": now()}
        db.execute("UPDATE receipts SET details_json=?,pending_details_json=?,updated_at=? WHERE id=?",
                   (json.dumps(everything), json.dumps(pending), now(), receipt_id))
        db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,reason,actor,created_at) "
                   "VALUES('receipt',?,'receipt_details',NULL,?,'[]',?,?,?)", (receipt_id, row["value"], UNDO_REASON, actor.current(), now()))

    @staticmethod
    def current_details(row):
        """A receipt's or bill's details for the kind it is read as now ({} when it has none)."""
        kind = row[kind_column(row)]
        if not row["details_json"] or not kind:
            return {}
        return json.loads(row["details_json"]).get(kind) or {}

    def refresh_paid(self, db, receipt_id):
        """What a receipt counts after gift cards (docs/money.md "Gift cards"; spec D15): the printed total less its gift-card
        tenders, kept in total_minor, with the printed total in printed_total_minor as a magnitude. Idempotent; it never
        sets a receipt verified. Rules, first match: a gift card on a return isn't handled (the signed printed total counts,
        with a note); deductions above the total count the printed total, with a note; a gift card counts the amount paid;
        otherwise the printed total counts as today. A linked charge that no longer equals the amount paid gets a note."""
        row = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        if row is None:
            return
        stored = json.loads(row["validation_json"])
        issues = [issue for issue in stored if not issue.startswith(PAID_ISSUES)]
        printed = row["printed_total_minor"] if row["printed_total_minor"] is not None else (abs(row["total_minor"]) if row["total_minor"] is not None else None)
        gift = sum(abs(tender["minor"]) for tender in self.current_details(row).get("tenders", [])
                   if tender.get("tender_type") == "gift_card" and tender.get("minor") is not None)
        sign = -1 if self.effective_receipt_direction(db, row) == "return" else 1
        total, kept = row["total_minor"], None
        if row["document_kind"] == "bill" or printed is None or (not gift and row["printed_total_minor"] is None):
            if row["document_kind"] == "bill" and row["printed_total_minor"] is not None:  # Recorded as a bill: it counts its total once more.
                total = sign * printed
        elif gift and sign == -1:
            total = -printed
            issues.append("Gift card on a return isn't handled; check the amount.")
        elif gift > printed:
            total = printed
            issues.append("Gift card deductions exceed the total; the printed total is counted until you correct it.")
        elif gift:
            total, kept = document_checks.amount_paid(printed, [gift], None, row["currency"])[0], printed
            charged = db.execute("SELECT -t.amount_minor FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id WHERE l.receipt_id=? "
                                 "AND l.review_status<>'rejected' AND t.review_status<>'rejected' ORDER BY l.id LIMIT 1", (receipt_id,)).fetchone()
            if charged and charged[0] != total:
                issues.append(f"Amount paid ({money(total, row['currency'])['decimal']}) no longer equals the linked charge "
                              f"({money(charged[0], row['currency'])['decimal']}).")
        else:
            total = sign * printed
        added = [issue for issue in issues if issue.startswith(PAID_ISSUES) and issue not in stored]
        review = ("needs_review", None) if added and row["review_source"] != "user" else (row["review_status"], row["review_source"])
        db.execute("UPDATE receipts SET total_minor=?,printed_total_minor=?,validation_json=?,review_status=?,review_source=?,updated_at=? WHERE id=?",
                   (total, kept, json.dumps(issues), *review, now(), receipt_id))
        if total != row["total_minor"]:
            self.refresh_splits(db, receipt_id)

    def detail_fields(self, row):
        """A receipt's current details a person may correct: {"detail:<path>": (kind, label)}."""
        details = self.current_details(row) if row["document_kind"] != "bill" else {}
        fields = {f"detail:{name}": entry for name, entry in DETAIL_CORRECTABLE.items() if name in details}
        tenders = details.get("tenders", [])
        for number, tender in enumerate(tenders, 1):
            label = TENDER_LABELS.get(tender.get("tender_type"), "Payment")
            same = [entry for entry in tenders if entry.get("tender_type") == tender.get("tender_type")]
            fields[f"detail:tenders.{number}.amount"] = ("money", f"{label} amount" + (f" {same.index(tender) + 1}" if len(same) > 1 else ""))
        return fields

    @staticmethod
    def detail_entry(details, field):
        """(the dict holding a detail's value, value key) for "detail:<name>" or "detail:tenders.<n>.amount"; None when
        the current details don't have it."""
        parts = field.removeprefix("detail:").split(".")
        if len(parts) == 1 and isinstance(details.get(parts[0]), dict):
            return details[parts[0]], "minor" if DETAIL_CORRECTABLE.get(parts[0], ("",))[0] == "money" else "text"
        if len(parts) == 3 and parts[0] == "tenders" and parts[1].isdigit() and parts[2] == "amount":
            tenders = details.get("tenders", [])
            if 1 <= int(parts[1]) <= len(tenders):
                return tenders[int(parts[1]) - 1], "minor"
        return None

    def _set_detail(self, db, receipt_id, field, text, currency):
        """Write one corrected detail into the receipt's current details; returns its text before. A detail the reading
        no longer has is refused."""
        row = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        details = self.current_details(row)
        found = self.detail_entry(details, field)
        if found is None:
            raise ValueError("This detail is no longer in the reading.")
        entry, key = found
        previous = (money(abs(entry[key]), currency)["decimal"] if entry.get(key) is not None else None) if key == "minor" else entry.get("text")
        if key == "minor":
            amount = abs(to_minor(text, currency)) if text is not None else None
            entry["minor"] = -amount if amount is not None and field == "detail:savings_total" else amount  # Savings are money off.
        else:
            if text is not None:
                try:
                    if not Decimal(str(text).strip().replace(",", "")).is_finite():
                        raise InvalidOperation
                except InvalidOperation:
                    raise ValueError("Enter a number as printed, such as 10.312.") from None
            entry["text"] = str(text).strip() if text is not None else None
        entry["status"] = "proposed" if entry.get(key) is not None else "missing"
        everything = json.loads(row["details_json"])
        everything[row[kind_column(row)]] = details
        db.execute("UPDATE receipts SET details_json=?,updated_at=? WHERE id=?", (json.dumps(everything), now(), receipt_id))
        return previous

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
        removed = {(row["description_key"], row["ordinal"]) for row in db.execute(
            "SELECT description_key,ordinal FROM deleted_receipt_items WHERE receipt_id=?", (receipt_id,))}
        seen_descriptions = Counter()
        incoming = []
        for position, item in enumerate(record["items"], 1):
            key = normalize_name(item["description"])
            ordinal = seen_descriptions[key]
            seen_descriptions[key] += 1
            if (key, ordinal) not in removed:
                incoming.append((position, item))
        by_key = dict(zip(self.item_keys(earlier), earlier))
        matched = {}  # new position -> earlier item
        for (position, _), key in zip(incoming, self.item_keys([item for _, item in incoming])):
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
        for position, item in incoming:
            category, category_source = remembered.get(normalize_name(item["description"])), "memory"
            if category is None:
                category, category_source = receipt_category(item.get("category")), "model"
            taxed = None if item.get("taxed") is None else int(item["taxed"])
            values = (item["description"], item.get("product_code"), item.get("quantity"), item.get("unit_price_minor"), item["line_total_minor"],
                      item.get("discount_minor"), taxed, item.get("line_holder"), item.get("line_kind"), item.get("line_type"),
                      json.dumps(item["details"]) if item.get("details") else None)
            # Whose line it is: as the family sent it, else the person's own choice from before, else nobody yet.
            member, member_source = item.get("member_id"), item.get("member_source") or ("configured" if item.get("member_id") else None)
            if position in matched:
                item_id, earlier_item = matched[position]["id"], matched[position]
                if earlier_item["category_source"] == "user":  # The user's own category outlives any reading.
                    category, category_source = earlier_item["category"], "user"
                if member is None and earlier_item["member_source"] == "user":
                    member, member_source = earlier_item["member_id"], "user"
                db.execute("UPDATE receipt_items SET description=?,product_code=?,quantity=?,unit_price_minor=?,line_total_minor=?,discount_minor=?,taxed=?,"
                           "line_holder=?,line_kind=?,line_type=?,details_json=?,category=?,category_source=?,member_id=?,member_source=?,review_status=?,updated_at=? WHERE id=?",
                           (*values, category, category_source if category else None, member, member_source, status, now(), item_id))
                db.execute("DELETE FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=?", (item_id,))
            else:
                item_id = db.execute("INSERT INTO receipt_items(receipt_id,position,description,product_code,quantity,unit_price_minor,line_total_minor,discount_minor,"
                                     "taxed,line_holder,line_kind,line_type,details_json,category,category_source,member_id,member_source,review_status,"
                                     "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                     (receipt_id, position, *values, category, category_source if category else None, member, member_source,
                                      status, now(), now())).lastrowid
            self.add_evidence(db, "receipt_item", item_id, source, item["locator"])
        return len(kept)

    def delete_item(self, receipt_id, position):
        """Remove one line and its dependent item data, remembering it across later readings."""
        with self.store.connection() as db:
            item = db.execute("SELECT i.* FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id "
                              "WHERE i.receipt_id=? AND i.position=? AND r.review_status<>'rejected'", (receipt_id, position)).fetchone()
            if item is None:
                raise ValueError("Receipt item not found.")
            key = normalize_name(item["description"])
            # Match by normalized description, including earlier removals, so repeated lines keep distinct ordinals.
            before = sum(normalize_name(row[0]) == key for row in db.execute(
                "SELECT description FROM receipt_items WHERE receipt_id=? AND position<?", (receipt_id, position)))
            before += db.execute("SELECT count(*) FROM deleted_receipt_items WHERE receipt_id=? AND position<? AND description_key=?",
                                 (receipt_id, position, key)).fetchone()[0]
            db.execute("INSERT INTO deleted_receipt_items(receipt_id,position,description,description_key,ordinal,actor,created_at) "
                       "VALUES(?,?,?,?,?,?,?)", (receipt_id, position, item["description"], key, before, actor.current(), now()))
            db.execute("DELETE FROM record_corrections WHERE record_type='receipt_item' AND record_id=? AND field IN (?,?,?,?)",
                       (receipt_id, f"price:{position}", f"line_kind:{position}", f"line_type:{position}", f"member:{position}"))
            db.execute("DELETE FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=?", (item["id"],))
            # Keep a product already added to the household, but detach it from this removed line.
            db.execute("UPDATE inventory_lots SET position=NULL,updated_at=? WHERE receipt_id=? AND position=?", (now(), receipt_id, position))
            db.execute("DELETE FROM receipt_items WHERE id=?", (item["id"],))
            self.refresh_splits(db, receipt_id)
        return self.record("receipt", receipt_id)

    @staticmethod
    def item_worked_on(db, receipt_id, item):
        """Whether the user categorised, identified or tagged a receipt line, said whose it is, or keeps it in the household (a lot)."""
        return item["category_source"] == "user" or item.get("member_source") == "user" or db.execute(
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
        found = self.split_inputs(db, receipt_id)
        if found is None:
            return
        receipt, items, charges, shared = found
        for transaction_id, target, currency in charges:
            shares = self.shares(receipt, items, target, currency, shared)
            db.executemany("INSERT INTO category_splits(receipt_id,transaction_id,receipt_item_id,category,amount_minor) VALUES(?,?,?,?,?)",
                           [(receipt_id, transaction_id, None if index is None else items[index]["id"], category, amount) for index, category, amount in shares])

    @staticmethod
    def split_inputs(db, receipt_id):
        """(receipt, items, [(transaction id or None, target, currency)], shared part) for dividing a receipt by item
        category, or None when it has no total or no items."""
        receipt = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        items = [dict(row) for row in db.execute("SELECT id,description,line_total_minor,discount_minor,taxed,category,member_id FROM receipt_items "
                                                 "WHERE receipt_id=? AND review_status<>'rejected' ORDER BY position", (receipt_id,))]
        if receipt is None or receipt["total_minor"] is None or not items:
            return None
        charges = [(None, receipt["total_minor"], receipt["currency"])] + [(row["id"], -row["amount_minor"], row["currency"]) for row in db.execute(
            "SELECT t.id,t.amount_minor,t.currency FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id "
            "WHERE l.receipt_id=? AND l.review_status<>'rejected'", (receipt_id,))]
        shared = db.execute("SELECT share_minor,total_minor,member_id FROM record_shares WHERE record_type='receipt' AND record_id=?", (receipt_id,)).fetchone()
        return receipt, items, charges, shared

    @staticmethod
    def shares(receipt, items, target, currency, shared, recorder=NULL):
        """One charge's (or the receipt's own) division by item category, summing to target. A live recorder gets the
        last pass: the one whose rounding gives the stored shares (finance/traces.py split)."""
        args = (items, receipt["subtotal_minor"], receipt["tax_minor"], receipt["tip_minor"])
        last = lambda final: recorder if final else NULL
        printed = receipt["printed_total_minor"] if "printed_total_minor" in receipt.keys() else None
        if currency == receipt["currency"] and printed is not None:
            # Paid partly by gift card: divided as printed, then resized to the amount paid, each category keeping its proportion.
            shares = splits.scale(splits.allocate(*args, printed, receipt["category"]), target, last(not shared), items, currency)
        elif currency == receipt["currency"]:
            shares = splits.allocate(*args, target, receipt["category"], last(not shared), currency)
        else:  # A card charge in another currency: share the receipt in its own currency, then resize to the charge.
            shares = splits.scale(splits.allocate(*args, receipt["total_minor"], receipt["category"]), target, last(not shared), items, currency)
        if shared and shared["member_id"]:  # Shared by line: this person's own lines and their part of the rest (docs/family.md).
            shares = splits.scale(splits.by_line(shares, items, shared["member_id"]), charge_share(target, shared["share_minor"], shared["total_minor"]),
                                  recorder, items, currency)
        elif shared:  # Each category keeps its proportion of this person's part.
            shares = splits.scale(shares, charge_share(target, shared["share_minor"], shared["total_minor"]), recorder, items, currency)
        return shares

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
            db.execute("UPDATE receipt_items SET category=?,category_source='user',updated_at=? WHERE id=?", (category, now(), item["id"]))
            db.execute("INSERT INTO item_category_memory(merchant_key,item_key,category,updated_at) VALUES(?,?,?,?) "
                       "ON CONFLICT(merchant_key,item_key) DO UPDATE SET category=excluded.category,updated_at=excluded.updated_at",
                       (normalize_name(item["merchant"]), normalize_name(item["description"]), category, now()))
            self.refresh_splits(db, receipt_id)
        return {"receipt_id": receipt_id, "position": position, "category": category, "category_source": "user"}

    def publish_asset(self, record, source):
        """A loan statement's balance as the forecast loan for its account (docs/planning.md "Assets and loans"); investment
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

    def publish_statement(self, record, source, status, origin="user"):
        """origin: who makes the account if the statement needs a new one (account_in)."""
        card = record["statement_type"] == "credit_card"
        # A bank statement's account is the type it prints (savings for "Chase Savings"), checking when none is printed.
        printed = None if card else PRINTED_ACCOUNT_TYPES.get(((record.get("details") or {}).get("account_type") or {}).get("text"))
        kind = "credit_card" if card else printed or "checking"
        with self.store.connection() as db:
            account = (printed and self.find_account(db, record["institution"], (printed,), record["last_four"])
                       or self.find_account(db, record["institution"], statement_types(kind), record["last_four"]))
            account = account or self.account_in(db, record["institution"], kind, record["currency"], last_four=record["last_four"], origin=origin)
            if printed and account["account_type"] in PRINTED_ACCOUNT_TYPES.values() and account["account_type"] != printed:
                account = self.retype_account(db, account, printed)
            if account["currency"] != record["currency"]:
                raise ValueError("The statement currency differs from its account's currency; nothing was published.")
            statement_id, written = self._upsert(db, "statements", source, {
                "account_id": account["id"], "statement_type": record["statement_type"], "period_start": record["period_start"],
                "period_end": record["period_end"], "issue_date": None, "due_date": record.get("due_date"),
                "opening_balance_minor": record.get("opening_balance_minor"), "closing_balance_minor": record.get("closing_balance_minor"),
                "statement_balance_minor": record.get("statement_balance_minor"), "minimum_payment_minor": record.get("minimum_payment_minor"),
                "summary_json": json.dumps(record["summary"]), "currency": record["currency"], "review_status": status,
                "validation_json": json.dumps(record["issues"]), "reconciliation": "awaiting",
                # Printed summary details, shown and checked only: what counts doesn't change (FR-29). The printed account type
                # picks the account above (docs/documents.md "Pay stub and statement fields").
                "details_json": json.dumps(record["details"]) if record.get("details") else None})
            if not written:
                return self._published("statement", statement_id, False, account_id=account["id"])
            self.add_evidence(db, "statement", statement_id, source, record["locator"])
            self.apply_corrections(db, "statement", statement_id)
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
            self.reapply_transaction_corrections(db, refresh)
            if kept:
                issues = [*record["issues"], f"This reading no longer finds {len(kept)} transaction{'s' if len(kept) > 1 else ''} you worked on; "
                          "they were kept. Check them against the statement."]
                db.execute("UPDATE statements SET review_status='needs_review',review_source=NULL,validation_json=? WHERE id=?", (json.dumps(issues), statement_id))
        return self._published("statement", statement_id, True, account_id=account["id"], inserted=len(inserted), duplicates=len(duplicates), kept=len(kept))

    @staticmethod
    def user_worked_on(db, transaction_id):
        """Whether the user categorised, corrected, tagged or matched a transaction (a machine proposal does not count)."""
        return db.execute(
            "SELECT EXISTS(SELECT 1 FROM transactions WHERE id=:t AND category_source='user') "
            "OR EXISTS(SELECT 1 FROM record_corrections WHERE record_type='transaction' AND record_id=:t) "
            "OR EXISTS(SELECT 1 FROM transaction_receipt_links WHERE transaction_id=:t AND review_status='verified') "
            "OR EXISTS(SELECT 1 FROM transaction_links WHERE :t IN (from_transaction_id,to_transaction_id) AND review_status='verified') "
            "OR EXISTS(SELECT 1 FROM transaction_income_links WHERE transaction_id=:t AND review_status='verified') "
            "OR EXISTS(SELECT 1 FROM tax_tags WHERE transaction_id=:t AND (source='user' OR review_status='verified')) "
            "OR EXISTS(SELECT 1 FROM investment_events WHERE transaction_id=:t AND transaction_link='user')",
            {"t": transaction_id}).fetchone()[0] == 1

    @staticmethod
    def remove_transaction(db, transaction_id):
        """Delete a transaction no reading supports, with the machine-made rows that point at it. Tags, splits and
        payment rejections go by cascade; the typed-ID rows are removed here, as emptying Trash does."""
        db.execute("DELETE FROM transaction_receipt_links WHERE transaction_id=?", (transaction_id,))
        db.execute("DELETE FROM transaction_income_links WHERE transaction_id=?", (transaction_id,))
        db.execute("DELETE FROM transaction_links WHERE ? IN (from_transaction_id,to_transaction_id)", (transaction_id,))
        for table in ("financial_evidence_links", "reconciliation_issues", "review_events"):
            db.execute(f"DELETE FROM {table} WHERE record_type='transaction' AND record_id=?", (transaction_id,))
        db.execute("DELETE FROM transactions WHERE id=?", (transaction_id,))

    def publish_bill(self, record, source, status):
        """A bill as a receipt (docs/money.md "Bills and their lines"): it counts its new charges (total_minor) on its due
        date, by its lines' categories, until the payment that paid it replaces it. A bill sent by a family before bills had
        lines carries only its amount due, which is then its total."""
        items = [{"description": line["description"], "line_total_minor": line["line_total_minor"], "category": line.get("category"),
                  "line_kind": line.get("line_kind"), "line_type": line.get("line_type"), "line_holder": line.get("line_holder"),
                  "member_id": line.get("member_id"), "member_source": line.get("member_source"), "quantity": line.get("quantity"),
                  "unit_price_minor": line.get("unit_price_minor"), "details": line.get("details"),
                  "locator": line.get("locator") or {}} for line in record.get("items", [])]
        total = record.get("total_minor", record.get("amount_due_minor"))
        # The bill's own category, for lines that have none: the category most of its money is in.
        spent: dict = {}
        for item in items:
            if receipt_category(item["category"]) and item["line_total_minor"]:
                spent[item["category"]] = spent.get(item["category"], 0) + item["line_total_minor"]
        category = record.get("category") or (max(sorted(spent), key=lambda name: spent[name]) if spent else None)
        receipt = {"merchant": record["provider"], "purchase_date": record.get("due_date") or record.get("issue_date"), "subtotal_minor": None,
                   "tax_minor": None, "tip_minor": None, "total_minor": total, "currency": record["currency"], "issues": record["issues"],
                   "locator": record["locator"], "items": items, "category": category, "recurrence": record.get("recurrence"),
                   "document_kind": "bill", "issue_date": record.get("issue_date"), "due_date": record.get("due_date"),
                   "period_start": record.get("period_start"), "period_end": record.get("period_end"),
                   "amount_due_minor": record.get("amount_due_minor"), "account_last_four": record.get("last_four") or record.get("account_last_four"),
                   "invoice": record.get("invoice"),
                   # Its kind and that kind's printed details (docs/documents.md "Bill kinds"); None for a bill read without kinds.
                   "bill_kind": record.get("bill_kind"), "details": record.get("details")}
        return {**self.publish_receipt(receipt, source, status), "document_kind": "bill"}

    def publish_income(self, record, source, status):
        with self.store.connection() as db:
            income_id, written = self._upsert(db, "income_records", source, {
                "payer_merchant_id": self.merchant(db, record["payer_or_employer"]) if record["payer_or_employer"] else None,
                "pay_date": record["pay_date"], "period_start": record["period_start"], "period_end": record["period_end"],
                "gross_pay_minor": record["gross_pay_minor"], "net_pay_minor": record["net_pay_minor"], "taxes_minor": record["taxes_minor"],
                "deductions_minor": record["deductions_minor"], "currency": record["currency"], "review_status": status,
                "gross_pay_ytd_minor": record.get("gross_pay_ytd_minor"), "net_pay_ytd_minor": record.get("net_pay_ytd_minor"),
                "work_state": record.get("work_state"), "pay_frequency": record.get("pay_frequency"),
                "validation_json": json.dumps(record["issues"]),
                # Printed labels and guard results (docs/documents.md "Pay stub and statement fields"), null when there are none.
                "details_json": json.dumps(record["details"]) if record.get("details") else None})
            if written:
                self.add_evidence(db, "income_record", income_id, source, record["locator"])
                self.apply_corrections(db, "income_record", income_id)
                db.execute("DELETE FROM income_lines WHERE income_record_id=?", (income_id,))
                db.executemany("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,ytd_minor,locator_json,"
                               "details_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               [(income_id, position, line["description"], line["line_group"], line["category"], line["current_minor"],
                                 line["ytd_minor"], json.dumps(line["locator"]), json.dumps(line["details"]) if line.get("details") else None, now(), now())
                                for position, line in enumerate(record.get("lines", []), 1)])
                self.apply_income_line_corrections(db, income_id)
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

    def preview_import(self, document_id, currency, mapping=None, digest=None, pdf=None):
        if self.is_pdf(document_id):
            return self.preview_pdf_import(document_id, digest, mapping=mapping, currency=currency, **(pdf or {}))
        if pdf:
            raise ValueError(PDF_ONLY)
        try:
            _, (rows, used, issues, counts) = self.table_rows(document_id, digest, currency, mapping)
        except MappingError as exc:  # Readable file; the user must choose a column or date order.
            return {"error": str(exc), "mapping": exc.mapping, "issues": [], "rows": [], "totals": None,
                    "counts": {"parsed": 0, "rejected": 0, "blank": 0, "columns": exc.columns}}
        return {"error": None, "mapping": used, "issues": issues[:200], "counts": counts, **preview(rows, currency_code(currency))}

    def import_transactions(self, document_id, account_id, mapping=None, digest=None, pdf=None):
        if self.is_pdf(document_id):
            choices = {name: value for name, value in (pdf or {}).items() if name != "account_type"}  # The account's own type is used.
            return self.import_pdf_transactions(document_id, digest, account_id=account_id, mapping=mapping, **choices)
        if pdf:
            raise ValueError(PDF_ONLY)
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

    # Deterministic PDF import ---------------------------------------------------
    # The rows come from the PDF's saved reading (finance/pdf_import.py, docs/documents.md "PDFs"). Neither the preview nor
    # the import opens the PDF beyond hashing it, and neither calls a model.

    def is_pdf(self, document_id):
        with self.store.connection() as db:
            row = db.execute("SELECT relative_path FROM occurrences WHERE id=?", (document_id,)).fetchone()
        return row is not None and extension(row["relative_path"]) == ".pdf"

    def pdf_reading(self, db, document_id, digest, reading_id=None):
        """(document, version, run, PDFResult) for the document's current content and its current reading, after every
        check that the reading still describes the preserved bytes (FR-22). Raises ValueError, naming the next step."""
        document = db.execute("SELECT * FROM occurrences WHERE id=?", (document_id,)).fetchone()
        if document is None:
            raise ValueError("Document not found.")
        selected = digest or document["current_hash"]
        version = db.execute("SELECT * FROM versions WHERE occurrence_id=? AND hash=?", (document_id, selected)).fetchone()
        if version is None:
            raise ValueError("This content version does not belong to the document.")
        if document["deleted_at"]:
            raise ValueError("Restore the document from Trash before importing it.")
        if selected != document["current_hash"]:  # document_version accepts any earlier version, so it can't tell (plan P8).
            raise ValueError("This document changed since the preview; preview again.")
        try:
            intact = digest_file(self.store.blob_path(version["hash"])) == version["hash"]
        except OSError:
            intact = False
        if not intact:
            raise ValueError(PDF_INTEGRITY)
        # The reading the library shows as this document's text (library/storage.py text_run_id).
        run = db.execute("SELECT * FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') AND parser_version<>'receipt-ocr-v1' "
                         "ORDER BY created_at DESC LIMIT 1", (version["hash"],)).fetchone()
        if run is None:
            raise ValueError("Read this document first.")
        if reading_id is not None and reading_id != run["id"]:
            raise ValueError("This document was read again since the preview; preview again.")
        saved = safe_path(self.store.root / "extracted" / run["id"] / "result.json") if re.fullmatch(r"[a-f0-9]{32}", run["id"]) else None
        try:
            if saved is None or not run["result_json"] or saved.stat().st_size > PDF_EVIDENCE_BYTES:
                raise ValueError(PDF_INTEGRITY)
            # Both copies are read the same way, so the comparison is of what the reading holds, not of how it was written.
            stored, written = read_result(json.loads(run["result_json"])), read_result(json.loads(saved.read_bytes()))
        except (OSError, ValueError) as exc:  # pydantic's ValidationError and JSON errors are ValueErrors.
            raise ValueError(PDF_INTEGRITY) from exc
        if not isinstance(stored, PDFResult):
            raise ValueError(pdf_import.NO_LAYOUT)
        if stored.model_dump() != written.model_dump() or stored.input_hash != version["hash"]:
            raise ValueError(PDF_INTEGRITY)
        return dict(document), dict(version), dict(run), stored

    def pdf_refusal(self, db, blob_hash):
        """What a PDF is already recorded as, which Record decided and an import must not contradict (FR-19), or None."""
        kinds = (("SELECT CASE WHEN EXISTS(SELECT 1 FROM receipts WHERE blob_hash=? AND review_status<>'rejected' AND document_kind='bill') THEN 'bill' "
                  "WHEN EXISTS(SELECT 1 FROM receipts WHERE blob_hash=? AND review_status<>'rejected') THEN 'receipt' END"),
                 "SELECT CASE WHEN EXISTS(SELECT 1 FROM income_records WHERE blob_hash=? AND review_status<>'rejected') THEN 'pay stub' END",
                 "SELECT CASE WHEN EXISTS(SELECT 1 FROM tax_forms WHERE blob_hash=? AND review_status<>'rejected') THEN 'tax form' END",
                 "SELECT CASE WHEN EXISTS(SELECT 1 FROM investment_valuations WHERE blob_hash=? AND review_status<>'rejected') THEN 'investment statement' END")
        for query in kinds:
            kind = db.execute(query, (blob_hash,) * query.count("?")).fetchone()[0]
            if kind:
                return f"This PDF is recorded as a {kind}."
        return None

    def account_match(self, db, last_fours, document_currency, home_currency=None):
        """The one active account in the document's currency whose last four the document prints, or None (FR-13).
        last_fours: each distinct NNNN found, with the page of its first occurrence."""
        currency = document_currency or home_currency or "USD"
        found = [dict(row) for row in db.execute(f"SELECT a.* FROM accounts a WHERE a.active=1 AND a.currency=? AND {CONFIRMED} ORDER BY a.id", (currency,))
                 if row["account_last_four"] in last_fours]
        if len(found) != 1:
            return None
        four = found[0]["account_last_four"]
        return {"account_id": found[0]["id"], "last_four": four, "page": last_fours[four], "text": f"Matched …{four} printed on page {last_fours[four]}"}

    def row_status(self, db, account, fingerprints, blob_hash):
        """Per row, in order: New, rejected earlier, or already recorded, with where from (FR-16, FR-17). Reads only.
        A fingerprint never matches a manual entry (manual rows store manual:<uuid>)."""
        found = {}
        for start in range(0, len(fingerprints), 500):
            chunk = fingerprints[start:start + 500]
            for row in db.execute(f"SELECT t.id,t.source_fingerprint,t.review_status,{COUNTABLE} AS counted FROM transactions t "
                                  f"WHERE t.account_id=? AND t.source_fingerprint IN ({','.join('?' * len(chunk))})", (account["id"], *chunk)):
                found[row["source_fingerprint"]] = dict(row)
        sources = {}
        for start in range(0, len(found), 500):
            chunk = [row["id"] for row in list(found.values())[start:start + 500]]
            for link in db.execute("SELECT e.record_id,e.source_key,e.blob_hash,o.relative_path FROM financial_evidence_links e JOIN occurrences o ON o.id=e.document_id "
                                   f"WHERE e.record_type='transaction' AND e.record_id IN ({','.join('?' * len(chunk))}) ORDER BY e.id DESC", chunk):
                sources[link["record_id"]] = link  # Descending, so the earliest link wins.
        statuses = []
        for fingerprint in fingerprints:
            row = found.get(fingerprint)
            if row is None:
                statuses.append({"status": "new", "text": "New"})
            elif row["review_status"] == "rejected":
                statuses.append({"status": "rejected_earlier", "text": "rejected earlier"})
            else:
                link = sources.get(row["id"])
                name = link["relative_path"].replace("\\", "/").rsplit("/", 1)[-1] if link else "an earlier import"
                kind = "statement" if link and link["source_key"].startswith("extraction:") else "import"
                text = "Already recorded from this statement" if kind == "statement" and link["blob_hash"] == blob_hash else f"Already recorded from {kind} {name}"
                statuses.append({"status": "already_recorded", "text": text + ("" if row["counted"] else "; not counted until you reconcile it.")})
        return statuses

    def replacing_manual(self, db, account, lines):
        """The keys of the New lines that the reconciliation pass after the import would use to replace a manual entry (FR-17):
        a line is its entry's only candidate, by replace_manual's own rule, counting the lines this import would add. Reads only."""
        from .reconcile import manual_candidates  # reconcile.py imports this module.
        keys = set()
        for manual in db.execute("SELECT * FROM transactions WHERE origin='manual' AND account_id=? AND review_status<>'rejected' AND replaced_by IS NULL", (account["id"],)).fetchall():
            candidates = manual_candidates(db, manual, lines)
            if len(candidates) == 1 and isinstance(candidates[0], dict):
                keys.add(candidates[0]["key"])
        return keys

    def pdf_state(self, db, document_id, digest, *, reading_id=None, account_id=None, account=None, account_type=None, currency=None, home_currency=None,
                  mapping=None, tables=None, year=None, date_format=None, sign=None, ticked=None, unticked=None):
        """Everything the preview and the import share: the reading, the account in force, the analysis and the ticks. Reads only.
        account: the account row itself, for an import that has just created it inside this transaction (account_id can't see it)."""
        if mapping is not None:
            raise ValueError("Column mapping applies to CSV and XLSX files.")
        document, version, run, result = self.pdf_reading(db, document_id, digest, reading_id)
        refusal = self.pdf_refusal(db, version["hash"])
        if refusal:
            raise ValueError(refusal)
        choices = dict(tables=tables, year=year, date_format=date_format or "auto", sign=sign)
        currency = currency_code(currency) if currency else None
        account = account or (self.account(account_id, db) if account_id else None)
        match = None
        if account is None:  # A first look finds the last fours and the document's currency, which choose the account and so the sign.
            first = pdf_import.analyze(result, account_type=account_type, currency=currency or "USD", **choices)
            match = self.account_match(db, first.last_fours, first.document_currency, home_currency)
            if match and account_type is None and currency in (None, db.execute("SELECT currency FROM accounts WHERE id=?", (match["account_id"],)).fetchone()[0]):
                account = self.account(match["account_id"], db)
            else:
                currency = currency or first.document_currency or home_currency or "USD"
        analysis = pdf_import.analyze(result, account_type=account["account_type"] if account else account_type,
                                      currency=account["currency"] if account else currency, **choices)
        if match is None:
            match = self.account_match(db, analysis.last_fours, analysis.document_currency, home_currency)
        rows = {row.key: row for row in analysis.rows}
        if set(ticked or ()) & set(unticked or ()):
            raise ValueError("A row cannot be both ticked and unticked.")
        ticks = {key: row.ticked for key, row in rows.items()}
        for key in ticked or ():
            if key in rows and not rows[key].rejected:
                ticks[key] = True
        for key in unticked or ():
            if key in rows:
                ticks[key] = False
        # Identity is worked out over every parsed row in document order, so unticking one never renumbers another (plan P3).
        parsed = [row for row in analysis.rows if not row.rejected]
        fingerprints = []
        if account and not analysis.required:
            fingerprints = list(identities(account["id"], [{"posted_date": row.posted_date, "amount_minor": row.amount_minor, "currency": row.currency} for row in parsed]))
        return {"document": document, "version": version, "run": run, "account": account, "match": match, "analysis": analysis,
                "ticks": ticks, "parsed": parsed, "fingerprints": fingerprints, "currency": account["currency"] if account else currency, "choices": choices}

    def preview_pdf_import(self, document_id, digest, *, mapping=None, account_id=None, new_account=None, account_type=None, currency=None, home_currency=None,
                           reading_id=None, tables=None, year=None, date_format=None, sign=None, ticked=None, unticked=None):
        """What importing the PDF would do, writing nothing (FR-05). With no account and no currency the currency is the
        document's, else the household's, else USD, and every row is New unless exactly one account matches (FR-13).
        new_account (a possibly typed one): an account it would find is the account in force, as at import (plan P6); otherwise its type
        and currency give the sign default and the currency checks, and every row is New."""
        with self.store.connection() as db:
            account = None
            if new_account and account_id is None:
                account = self.find_account(db, new_account["institution"], (new_account["account_type"],), new_account.get("last_four"))
                if account and account["currency"] != currency_code(new_account["currency"]):
                    account = None  # The import refuses this one; the preview still shows the rows.
                if account is None:
                    account_type, currency = account_type or new_account["account_type"], currency or new_account["currency"]
            state = self.pdf_state(db, document_id, digest, reading_id=reading_id, account_id=account_id, account=account, account_type=account_type,
                                   currency=currency, home_currency=home_currency, mapping=mapping, tables=tables, year=year, date_format=date_format,
                                   sign=sign, ticked=ticked, unticked=unticked)
            analysis, account, ticks, currency = state["analysis"], state["account"], state["ticks"], state["currency"]
            statuses, replacing = {}, set()
            if state["fingerprints"]:
                for row, status in zip(state["parsed"], self.row_status(db, account, state["fingerprints"], state["version"]["hash"])):
                    statuses[row.key] = status
                replacing = self.replacing_manual(db, account, [{"key": row.key, "posted_date": row.posted_date, "amount_minor": row.amount_minor, "currency": row.currency}
                                                                 for row in state["parsed"] if ticks[row.key] and statuses[row.key]["status"] == "new"])
        totals = {"new": [0, 0], "recorded": [0, 0]}
        rows, counts = [], {"new": 0, "already_recorded": 0, "rejected_earlier": 0}
        for row in analysis.rows:
            status = {"status": "rejected", "text": "Rejected: " + row.rejected} if row.rejected else statuses.get(row.key, {"status": "new", "text": "New"})
            ticked_now = ticks[row.key]
            if ticked_now and not row.rejected:
                counts[status["status"]] += 1
                if row.amount_minor is not None:
                    bucket = totals["new" if status["status"] == "new" else "recorded"]
                    bucket[row.amount_minor > 0] += row.amount_minor
            rows.append({"key": row.key, "page": row.page, "table_id": row.table_id, "row": row.row, "date": row.date, "description": row.description,
                         "amount": row.amount, "posted_date": row.posted_date, "amount_minor": row.amount_minor, "currency": row.currency,
                         "display_amount": format_minor(row.amount_minor, currency) if row.amount_minor is not None else None,
                         "ticked": ticked_now, "labels": row.labels + (["replaces a manual entry"] if row.key in replacing else []), "rejected": row.rejected, "status": status["status"], "status_text": status["text"],
                         "continued_from": row.continued_from, "cell_ids": row.cell_ids, "line_ids": row.line_ids, "word_ids": row.word_ids})

        def money(bucket):
            return {"outflow": format_minor(bucket[0], currency), "inflow": format_minor(bucket[1], currency), "outflow_minor": bucket[0], "inflow_minor": bucket[1]}
        left_out = sum(1 for row in state["parsed"] if not ticks[row.key])
        return {"kind": "pdf", "reading_id": state["run"]["id"], "currency": currency, "account_id": account["id"] if account else None,
                "tables": [asdict(table) for table in analysis.tables], "rows": rows, "issues": [asdict(issue) for issue in analysis.issues],
                "counts": {**analysis.counts, "left_out": left_out, **counts}, "required": analysis.required,
                "required_messages": [REQUIRED[item] for item in analysis.required], "blocked": analysis.blocked,
                "totals": money(totals["new"]), "already_recorded_totals": money(totals["recorded"]), "account_match": state["match"],
                "new_account_last_four": next(iter(analysis.last_fours)) if len(analysis.last_fours) == 1 else None,
                "sign_default": analysis.sign_default, "sign": analysis.sign, "signed": analysis.signed, "mapping": analysis.mapping, "document_currency": analysis.document_currency}

    def import_pdf_transactions(self, document_id, digest, *, account_id=None, new_account=None, mapping=None, reading_id=None, tables=None, year=None,
                                date_format=None, sign=None, ticked=None, unticked=None):
        """Import the ticked rows of the PDF into an account, as one transaction: every check is made again inside it (FR-22, FR-23).
        new_account (institution, account_type, currency, display_name, last_four) is found or created in that same transaction (FR-14,
        plan P6), so a refusal or a failure leaves no account behind."""
        if account_id is None and new_account is None:
            raise ValueError("Choose the account these transactions belong to.")
        if account_id is not None and new_account is not None:
            raise ValueError("Choose an existing account or a new one, not both.")
        if reading_id is None:
            raise ValueError("Preview this document again before importing it.")
        import_id = uuid.uuid4().hex
        with self.store.connection() as db:
            # The write lock is taken before the checks, so a reading published meanwhile waits for this import (FR-22).
            db.execute("BEGIN IMMEDIATE")
            account = self.account_in(db, new_account["institution"], new_account["account_type"], new_account["currency"], new_account.get("display_name"),
                                      new_account.get("last_four")) if new_account else None
            state = self.pdf_state(db, document_id, digest, reading_id=reading_id, account_id=account_id, account=account, mapping=mapping, tables=tables, year=year,
                                   date_format=date_format, sign=sign, ticked=ticked, unticked=unticked)
            analysis, account, ticks, version = state["analysis"], state["account"], state["ticks"], state["version"]
            if analysis.blocked:
                raise ValueError(analysis.blocked)
            if analysis.required:
                raise ValueError(" ".join(REQUIRED[item] for item in analysis.required))
            chosen = [(row, fingerprint) for row, fingerprint in zip(state["parsed"], state["fingerprints"]) if ticks[row.key]]
            if not chosen:
                reason = "every row was rejected or left out" if analysis.rows else (analysis.issues[0].message if analysis.issues else "no transactions table was found")
                raise ValueError(f"Nothing to import: {reason}")
            known = {fingerprint: status for (_, fingerprint), status in zip(chosen, self.row_status(db, account, [item[1] for item in chosen], version["hash"]))}
            source = {"document_id": document_id, "blob_hash": version["hash"], "parse_run_id": reading_id, "source_key": "import:" + import_id}
            lines = []
            for row, _ in chosen:
                locator = {"document_id": document_id, "blob_hash": version["hash"], "reading_id": reading_id, "page": row.page, "table_id": row.table_id,
                           "row": row.row, **({"cell_ids": row.cell_ids} if row.cell_ids else {"word_ids": row.word_ids}), "line_ids": row.line_ids}
                if row.continued_from is not None:
                    locator["continued_from"] = row.continued_from
                lines.append({"posted_date": row.posted_date, "description": row.description, "amount_minor": row.amount_minor, "currency": row.currency,
                              "locator": locator})
            inserted, duplicates = self.insert_transactions(db, account, lines, "import", source, fingerprints=[fingerprint for _, fingerprint in chosen])
            sources = {}
            for status in known.values():
                if status["status"] != "new":
                    sources[status["text"]] = sources.get(status["text"], 0) + 1
            rejected_earlier = sum(1 for status in known.values() if status["status"] == "rejected_earlier")
            left_out = sum(1 for row in state["parsed"] if not ticks[row.key])
            used_sign = analysis.sign if analysis.signed else None
            selected = [table for table in analysis.tables if table.selected]
            record = {"kind": "pdf", "reading_id": reading_id, "tables": [{"id": table.id, "page": table.page, "linked_to": table.linked_to} for table in selected],
                      "mapping": analysis.mapping, "mappings": {table.id: table.columns for table in selected if table.linked_to is None}, "year": year, "date_format": date_format or "auto", "sign": used_sign,
                      "ticked": [row.key for row in state["parsed"] if ticks[row.key]], "unticked": [row.key for row in state["parsed"] if not ticks[row.key]], "left_out": left_out}
            issues = [asdict(issue) for issue in analysis.issues]
            db.execute("INSERT INTO transaction_imports VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (import_id, document_id, version["hash"], account["id"], json.dumps(record), analysis.counts["parsed"], len(inserted),
                        len(duplicates), analysis.counts["rejected"], json.dumps(issues), now()))
        return {"import_id": import_id, "account_id": account["id"], "account_name": account["display_name"], "inserted": len(inserted),
                "duplicates": len(duplicates), "rejected": analysis.counts["rejected"], "left_out": left_out, "rejected_earlier": rejected_earlier,
                "pages_without_rows": analysis.counts["pages_without_rows"], "issues": issues, "duplicate_sources": sources}

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
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at,actor) VALUES(?,?,?,?,?,?,?)",
                       (record_type, record_id, row["review_status"], status, note[:1000], now(), actor.current()))
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
            if "details_json" in value:  # Printed details (docs/documents.md "Typed extraction"): a receipt's for the kind it is read as now.
                stored = json.loads(value.pop("details_json") or "null")
                found = (stored or {}).get(row[kind_column(row)]) if record_type == "receipt" and stored is not None else stored
                value["details"] = shown_details(found, row["currency"])
            if "pending_details_json" in value:
                pending = json.loads(value.pop("pending_details_json") or "null")
                value["pending_details"] = {**pending, "details": shown_details(pending["details"], row["currency"])} if pending else None
            if record_type == "receipt":
                value["invoice"] = json.loads(value.pop("invoice_json") or "null")
                value["items"] = [dict(item) for item in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY position", (record_id,))]
                for item in value["items"]:
                    item["details"] = shown_details(json.loads(item.pop("details_json") or "null"), row["currency"])
                # Each item's share of what was paid (its price with its part of tax and discounts), and the totals by category.
                shares = dict(db.execute("SELECT receipt_item_id,amount_minor FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL "
                                         "AND receipt_item_id IS NOT NULL", (record_id,)).fetchall())
                bill = row["document_kind"] == "bill"
                for item in value["items"]:
                    item["share_minor"] = shares.get(item["id"])
                    item["correctable"] = [{"field": "price", "label": "Price", "kind": "receipt_money",
                                            "value": money(abs(item["line_total_minor"]), row["currency"])["decimal"] if item["line_total_minor"] is not None else None}]
                    if bill:  # A bill's lines: what each is and whose (docs/money.md "Bills and their lines").
                        # A rent bill's line takes a rent type (specs/bill-kinds FR-45), which sets its line kind.
                        kind = ({"field": "line_type", "label": "Type", "kind": "choice", "value": item["line_type"], "options": list(RENT_LINE_TYPES)}
                                if row["bill_kind"] == "rent" else
                                {"field": "line_kind", "label": "Type", "kind": "choice", "value": item["line_kind"], "options": list(LINE_KINDS)})
                        item["correctable"] += [kind, {"field": "member_id", "label": "Person", "kind": "member", "value": item["member_id"]}]
                if bill:
                    # Subscription lines inside a bill aren't recurring payments of their own; the Bills page lists them under it.
                    value["includes"] = [item["description"] for item in value["items"] if item["line_kind"] == "subscription" and item["review_status"] != "rejected"]
                    share = db.execute("SELECT share_minor,total_minor,people_json,member_id FROM record_shares WHERE record_type='receipt' AND record_id=?",
                                       (record_id,)).fetchone()
                    value["share"] = {**dict(share), "people": json.loads(share["people_json"])} if share else None
                    value["share_request"] = (dict(db.execute("SELECT mode,requested_at FROM share_requests WHERE receipt_id=?", (record_id,)).fetchone() or {})
                                              or None)
                    holders = {item["line_holder"] for item in value["items"] if item["line_holder"]}
                    # Lines for more than one person: the family can share it by line (docs/family.md "Sharing a bill by line").
                    value["shareable_by_line"] = len(holders) > 1 or len({item["member_id"] for item in value["items"] if item["member_id"]}) > 1
                value["unmatched_minor"] = db.execute("SELECT sum(amount_minor) FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL "
                                                      "AND receipt_item_id IS NULL", (record_id,)).fetchone()[0]
                printed_total = row["printed_total_minor"] if row["printed_total_minor"] is not None else row["total_minor"]  # Before gift cards.
                value["totals_mismatch"] = (row["subtotal_minor"] is not None and printed_total is not None
                                             and abs(row["subtotal_minor"] + (row["tax_minor"] or 0) + (row["tip_minor"] or 0) - printed_total) > 1)
                value["splits"] = [dict(split) for split in db.execute(
                    "SELECT category,sum(amount_minor) AS amount_minor FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL "
                    "GROUP BY 1 ORDER BY 2 DESC,1", (record_id,))]
                value["rewards"] = []
                for reward in db.execute("SELECT * FROM receipt_rewards WHERE receipt_id=? ORDER BY position", (record_id,)):
                    reward = dict(reward)
                    reward["line_ids"] = json.loads(reward.pop("locator_json")).get("line_ids", [])
                    value["rewards"].append(reward)
                # Sale or return, as a correction sets it, and the tag the page shows (docs/money.md "Returns").
                value["direction"] = self.effective_receipt_direction(db, row)
                value["sale_label"] = sale_label(row["total_minor"], [item["line_total_minor"] for item in value["items"]])
                # Printed total, gift cards and what was paid, worked out here ("Total 8.55 · Gift card −5.00 · Paid 3.55").
                printed = row["printed_total_minor"] if row["printed_total_minor"] is not None else (abs(row["total_minor"]) if row["total_minor"] is not None else None)
                sign = -1 if value["direction"] == "return" else 1
                value["printed_total"] = money(sign * printed, row["currency"]) if printed is not None else None
                value["amount_paid"] = money(row["total_minor"], row["currency"]) if row["total_minor"] is not None else None
                value["tenders"] = [{**tender, "label": TENDER_LABELS.get(tender.get("tender_type"), "Payment"),
                                     "amount": money(tender["minor"], row["currency"]) if tender.get("minor") is not None else None}
                                    for tender in self.current_details(row).get("tenders", [])]
                value["reconciled"] = db.execute("SELECT 1 FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id WHERE l.receipt_id=? "
                                                 "AND l.review_status<>'rejected' AND t.review_status<>'rejected'", (record_id,)).fetchone() is not None
            if record_type == "transaction":
                value["splits"] = [dict(split) for split in db.execute(
                    f"SELECT s.category,sum(s.amount_minor) AS amount_minor FROM transactions t JOIN category_splits s ON {CHARGE_SPLITS} "
                    "WHERE t.id=? GROUP BY 1 ORDER BY 2 DESC,1", (record_id,))]
            if record_type == "statement":
                value["transactions"] = [dict(item) for item in db.execute("SELECT * FROM transactions WHERE statement_id=? ORDER BY posted_date,id", (record_id,))]
                value["account_confirmed"] = self.account_confirmed(db, row["account_id"])
            if record_type == "income_record":
                value["lines"] = []
                for line in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY position", (record_id,)):
                    line = dict(line)
                    line["details"] = shown_details(json.loads(line.pop("details_json") or "null"), row["currency"])
                    source = json.loads(line.pop("locator_json"))
                    line["line_ids"] = source.get("line_ids", [])
                    line["cell_evidence"] = source.get("cells", {})
                    line["correctable"] = [{"field": field, "label": label, "kind": "money",
                                            "value": money(line[column], row["currency"])["decimal"] if line[column] is not None else None}
                                           for field, label, column in (("current", "This period", "current_minor"),
                                                                        ("ytd", "Year to date", "ytd_minor"))]
                    value["lines"].append(line)
            for key in ("merchant_id", "provider_merchant_id", "payer_merchant_id"):
                if value.get(key):
                    value["merchant"] = db.execute("SELECT canonical_name FROM merchants WHERE id=?", (value[key],)).fetchone()[0]
            if value.get("account_id"):
                value["account"] = db.execute("SELECT display_name FROM accounts WHERE id=?", (value["account_id"],)).fetchone()[0]
            if record_type in ("transaction", "receipt", "income_record"):
                value["links"] = self.links(db, record_type, record_id)
            # What the Correct form offers, with the text a correction takes (docs/money.md "Corrections").
            value["correctable"] = self.correctable(db, record_type, row)
            for line in value.get("transactions", [])[:500]:
                line["correctable"] = self.correctable(db, "transaction", line)
            if record_type in CORRECTABLE or record_type == "transaction":
                value["corrections"] = self.corrections(db, record_type, record_id)
                # Changes the family made to this record, each of which this person can reject (finance/family_corrections.py).
                value["family_corrections"] = [dict(row) for row in db.execute(
                    "SELECT key,field,value,previous,actor,status,created_at FROM family_corrections WHERE direction='received' AND record_type=? "
                    "AND record_id=? ORDER BY created_at", (record_type, record_id))]
            # The document's own arithmetic checks, worked out here with the functions their traces run (FR-19).
            from .document_traces import checks
            value["checks"] = checks(db, record_type, row)
            if record_type == "receipt":
                # "Total 8.55 · Gift card −5.00 · Paid 3.55" (FR-09): Paid is the amount-paid check's figure. counted: whether
                # what the receipt counts is that amount (a receipt reviewed before its gift card was read counts its total).
                paid = next((check for check in value["checks"] if check["name"] == "paid"), None)
                gifts = sum(abs(tender["minor"]) for tender in self.current_details(row).get("tenders", [])
                            if tender.get("tender_type") == "gift_card" and tender.get("minor"))
                value["paid_summary"] = {"total": value.get("printed_total"), "gift_cards": money(-gifts, row["currency"]), "paid": paid["figure"],
                                         "counted": row["total_minor"] == paid["figure"]["minor"]} if paid else None
                value["bill_summary"] = self.bill_summary(db, row, value["items"], value["checks"], value.get("issues") or [])
        # Source lines per row, so every item or transaction can be found in the transcription.
        for key, kind in (("items", "receipt_item"), ("transactions", "transaction")):
            for row in value.get(key, [])[:500]:
                evidence = self.evidence(kind, row["id"])
                row["line_ids"] = [line for entry in evidence for line in entry["locator"].get("line_ids", [])]
                row["cell_evidence"] = {name: cell for entry in evidence for name, cell in entry["locator"].get("cells", {}).items()}
        # Exact display strings: the browser never does money arithmetic.
        for row in [value, *([value["invoice"]] if value.get("invoice") else []), *value.get("items", []), *value.get("transactions", []), *value.get("lines", []), *value.get("splits", [])]:
            row["display"] = {key: format_minor(amount, value["currency"]) for key, amount in row.items()
                              if key.endswith("_minor") and isinstance(amount, int)}
        if record_type == "income_record":  # Gross to net, grouped with subtotals (finance/paystub.py).
            value["breakdown"] = paystub.with_display(paystub.breakdown(value, value["lines"]), value["currency"])
            # Taxes and deductions the stub doesn't print as totals are shown from the breakdown's subtotals; the record keeps
            # them empty, so a correction or a reading that finds a printed total still wins.
            subtotals = {group["group"]: group["current_minor"] for group in value["breakdown"]["groups"]}
            value["worked_out"] = []
            for field, groups in (("taxes_minor", ("tax",)), ("deductions_minor", ("pre_tax",))):
                present = [subtotals[group] for group in groups if group in subtotals]
                if value[field] is None and present and None not in present:
                    value["display"][field] = format_minor(sum(present), value["currency"])
                    value["worked_out"].append(field)
            # Shown only, never stored: everything taken from gross pay (taxes and all deductions).
            for field, groups in (("total_deductions_minor", ("tax", "pre_tax", "post_tax")),):
                present = [subtotals[group] for group in groups if group in subtotals]
                if present and None not in present:
                    value["display"][field] = format_minor(sum(present), value["currency"])
                    value["worked_out"].append(field)
        value["evidence"] = self.evidence(record_type, record_id)
        value["review_history"] = self.review_history(record_type, record_id)
        return value

    def set_category(self, transaction_id, category):
        """The user's own category for one transaction. Clearing it hands the row back to the user's rules."""
        category = category_name(category) if category else None
        with self.store.connection() as db:
            before = db.execute("SELECT category FROM transactions WHERE id=?", (transaction_id,)).fetchone()
            if before is None:
                raise ValueError("Transaction not found.")
            db.execute("UPDATE transactions SET category=?,category_source=?,category_rule_id=NULL,updated_at=? WHERE id=?",
                       (category, "user" if category else None, now(), transaction_id))
            if category is None:
                self.apply_rules(db, [transaction_id])
            row = db.execute("SELECT category,category_source FROM transactions WHERE id=?", (transaction_id,)).fetchone()
            if row["category"] != before["category"]:  # Kept with who changed it (provenance "override").
                db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,actor,created_at) VALUES('transaction',?,'category',?,?,?,?)",
                           (transaction_id, row["category"], before["category"], actor.current(), now()))
        return {"id": transaction_id, "category": row["category"], "category_source": row["category_source"]}

    def correct_transaction(self, transaction_id, changes, reason=None):
        """Set a transaction's date, amount, direction, merchant or type when the import or the reading got it wrong. Kept
        with the value it replaced, the person and an optional reason (record_corrections), and applied again when its
        statement is read again (reapply_transaction_corrections). The review state is unchanged."""
        unknown = set(changes) - set(TRANSACTION_CORRECTABLE)
        if not changes or unknown:
            raise ValueError("Choose fields a transaction allows: " + ", ".join(field.replace("_", " ") for field in TRANSACTION_CORRECTABLE) + ".")
        with self.store.connection() as db:
            ids = self._apply_transaction_correction(db, transaction_id, changes, reason)
        return {**self.record("transaction", transaction_id), "correction_ids": ids}

    def _apply_transaction_correction(self, db, transaction_id, changes, reason):
        """Write a transaction's corrected fields and their history rows; returns the rows' ids."""
        if db.execute("SELECT 1 FROM transactions WHERE id=?", (transaction_id,)).fetchone() is None:
            raise ValueError("Transaction not found.")
        ids = []
        for field, text in changes.items():
            row = db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
            if row["replaced_by"] is not None:
                raise ValueError("Its statement or import line replaced this entry; correct that line instead.")
            value, stored = self._transaction_value(db, row, field, text)
            db.execute(f"UPDATE transactions SET {TRANSACTION_CORRECTABLE[field][0]}=?,updated_at=? WHERE id=?", (value, now(), transaction_id))
            ids.append(db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,reason,actor,created_at) VALUES('transaction',?,?,?,?,?,?,?)",
                                  (transaction_id, field, stored, self._transaction_text(db, row, field), clean_reason(reason), actor.current(), now())).lastrowid)
        return ids

    def _transaction_value(self, db, row, field, text):
        """(column value, stored text) for one corrected transaction field, keeping what the other fields say."""
        kind = TRANSACTION_CORRECTABLE[field][1]
        text = " ".join(str(text or "").split())
        if kind == "amount":
            minor = to_minor(text, row["currency"])
            if minor <= 0:
                raise ValueError("Enter the amount as a positive number; its direction is corrected separately.")
            return (-minor if row["amount_minor"] < 0 else minor), money(minor, row["currency"])["decimal"]
        if kind == "direction":
            if text not in ("out", "in"):
                raise ValueError("Choose money out or money in.")
            return (-abs(row["amount_minor"]) if text == "out" else abs(row["amount_minor"])), text
        if kind == "type":
            if text not in TRANSACTION_TYPES:
                raise ValueError("Choose a type: " + ", ".join(TRANSACTION_TYPES) + ".")
            return text, text
        return self._correction_value(db, kind, field, text, currency=row["currency"])

    def _transaction_text(self, db, row, field):
        """A transaction field as it read before a correction."""
        if field == "amount":
            return money(abs(row["amount_minor"]), row["currency"])["decimal"]
        if field == "direction":
            return "out" if row["amount_minor"] < 0 else "in"
        if field == "merchant":
            return self._merchant_name(db, row["merchant_id"]) or row["description_raw"]
        return row[TRANSACTION_CORRECTABLE[field][0]]

    def reapply_transaction_corrections(self, db, transaction_ids):
        """A re-read statement rewrites its lines' text and type: put back what a person corrected, in the order corrected."""
        for transaction_id in transaction_ids:
            for field, text in db.execute("SELECT field,value FROM record_corrections WHERE record_type='transaction' AND record_id=? AND field<>'category' "
                                          "ORDER BY id", (transaction_id,)).fetchall():
                row = db.execute("SELECT * FROM transactions WHERE id=?", (transaction_id,)).fetchone()
                value, _ = self._transaction_value(db, row, field, text)
                db.execute(f"UPDATE transactions SET {TRANSACTION_CORRECTABLE[field][0]}=? WHERE id=?", (value, transaction_id))

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
            before = db.execute("SELECT amount_minor FROM budgets WHERE category=? AND currency=?", (category, currency)).fetchone()
            db.execute("INSERT INTO budgets(category,currency,amount_minor,created_at,updated_at) VALUES(?,?,?,?,?) "
                       "ON CONFLICT(category,currency) DO UPDATE SET amount_minor=excluded.amount_minor,updated_at=excluded.updated_at",
                       (category, currency, amount_minor, now(), now()))
            row = db.execute("SELECT * FROM budgets WHERE category=? AND currency=?", (category, currency)).fetchone()
            if before is None or before[0] != amount_minor:
                self.budget_change(db, row["id"], category, currency, before[0] if before else None, amount_minor)
        return {**dict(row), "amount": money(row["amount_minor"], row["currency"])}

    def delete_budget(self, budget_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM budgets WHERE id=?", (budget_id,)).fetchone()
            if row is None:
                raise ValueError("Budget not found.")
            db.execute("DELETE FROM budgets WHERE id=?", (budget_id,))
            self.budget_change(db, budget_id, row["category"], row["currency"], row["amount_minor"], None)
        return {"id": budget_id, "deleted": True}

    @staticmethod
    def budget_change(db, budget_id, category, currency, previous, amount):
        """A budget's history (budget_changes): from what to what (None: not set), who, when."""
        db.execute("INSERT INTO budget_changes(budget_id,category,currency,previous_minor,amount_minor,actor,created_at) VALUES(?,?,?,?,?,?,?)",
                   (budget_id, category, currency, previous, amount, actor.current(), now()))

    def budget_history(self, category, currency):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM budget_changes WHERE category=? AND currency=? ORDER BY id DESC", (category_name(category), currency_code(currency)))
            return [{**dict(row), **{key: money(row[f"{key}_minor"], row["currency"]) if row[f"{key}_minor"] is not None else None
                                     for key in ("previous", "amount")}} for row in rows]

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
            rows += [(dict(row), "income_record", row["income_record_id"]) for row in db.execute(
                "SELECT 'income' AS kind,* FROM transaction_income_links WHERE transaction_id=? AND review_status<>'rejected'", (record_id,))]
        elif record_type == "receipt":
            rows += [(dict(row), "transaction", row["transaction_id"]) for row in db.execute(
                "SELECT 'receipt' AS kind,* FROM transaction_receipt_links WHERE receipt_id=? AND review_status<>'rejected'", (record_id,))]
        elif record_type == "income_record":  # The deposit that paid a pay stub (docs/money.md "Money in and paystubs").
            rows += [(dict(row), "transaction", row["transaction_id"]) for row in db.execute(
                "SELECT 'income' AS kind,* FROM transaction_income_links WHERE income_record_id=? AND review_status<>'rejected'", (record_id,))]
        counterparts = {kind: self.summaries(db, kind, [other for _, row_kind, other in rows if row_kind == kind])
                        for kind in ("receipt", "transaction", "income_record")}
        return [{"kind": link["kind"], "id": link["id"], "review_status": link["review_status"], "match_score": link["match_score"],
                 "match_signals": link["match_method"].split("+"), "counterpart": counterparts[kind].get(other)} for link, kind, other in rows]

    # User corrections ---------------------------------------------------------

    def _correction_value(self, db, kind, field, text, stored=False, currency=None):
        """Validate one entered value; returns (column value, stored text). stored re-applies a saved correction,
        which may name a category retired since (LEGACY_CATEGORIES) until the re-sort replaces it. A money value is in
        the record's currency, stored as its exact decimal text."""
        if kind == "document_kind":
            value = str(text or "").strip().lower()
            if value not in ("receipt", "bill"):
                raise ValueError("Choose purchase or bill.")
            return value, value
        if text is None:
            return None, None
        text = " ".join(str(text).split())
        if kind == "sale_type":
            if text.lower() not in ("sale", "return"):
                raise ValueError("Choose sale or return.")
            return text.lower(), text.lower()
        if kind in ("money", "receipt_money"):
            minor = to_minor(text, currency)
            if kind == "receipt_money" and minor < 0:
                raise ValueError("Enter a positive amount; sale or return sets its direction.")
            return minor, money(minor, currency)["decimal"]
        if kind == "pay_frequency":
            if text not in ("12", "24", "26", "52"):
                raise ValueError("Choose monthly, twice a month, every two weeks or weekly.")
            return int(text), text
        if kind == "work_state":
            state = text.upper()
            if state not in US_STATES:
                raise ValueError("Enter a two-letter US state code.")
            return state, state
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

    def correct(self, record_type, record_id, changes, reason=None):
        """Set fields the document did not print or the model misread. Kept with the model's value in history, with the
        person (core/actor.py) and an optional reason; the record's review state is unchanged, and issues about the
        corrected fields are resolved."""
        if not CORRECTABLE.get(record_type):
            raise ValueError("This kind of record cannot be corrected here.")
        with self.store.connection() as db:
            row = db.execute(f"SELECT * FROM {RECORD_TABLES[record_type]} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            fields = fields_for(record_type, row)
            details = self.detail_fields(row) if record_type == "receipt" else {}
            if not changes or set(changes) - set(fields) - set(details):
                raise ValueError("Choose fields this record allows: " + ", ".join(field.replace("_", " ") for field in fields) + ".")
            ids = self._apply_correction(db, record_type, record_id, changes, reason)
            if record_type == "receipt" and any(field in PAID_FIELDS or field.startswith("detail:") for field in changes):
                self.refresh_paid(db, record_id)  # Its notes are in place before the automatic check below.
            table = RECORD_TABLES[record_type]
            row = db.execute(f"SELECT validation_json,review_status,review_source FROM {table} WHERE id=?", (record_id,)).fetchone()
            if not json.loads(row["validation_json"]) and row["review_status"] == "needs_review" and row["review_source"] != "user":
                db.execute(f"UPDATE {table} SET review_status='verified',review_source='automatic' WHERE id=?", (record_id,))
                db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES(?,?,'needs_review','verified',?,?)",
                           (record_type, record_id, AUTO_VERIFIED_NOTE, now()))
        # The new history rows, so the change can be undone (undo_corrections).
        return {**self.record(record_type, record_id), "correction_ids": ids}

    def _apply_correction(self, db, record_type, record_id, changes, reason):
        """Write a record's corrected fields and their history rows; returns the rows' ids. Issues about the corrected
        fields are resolved; the review state is left to the caller."""
        table = RECORD_TABLES[record_type]
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        if row is None:
            raise ValueError("Financial record not found.")
        fields = fields_for(record_type, row)
        details = self.detail_fields(row) if record_type == "receipt" else {}
        issues, ids = json.loads(row["validation_json"]), []
        for field, text in sorted(changes.items(), key=lambda pair: pair[0] == "direction"):
            if field.startswith("detail:"):  # A printed detail (docs/money.md "Corrections"), kept as its text.
                kind, label = details.get(field) or ("money" if field.endswith(".amount") else "decimal_text", self.detail_label(field))
                text = " ".join(str(text).split()) if text is not None else None
                previous = self._set_detail(db, record_id, field, text, row["currency"])
                stored = money(abs(to_minor(text, row["currency"])), row["currency"])["decimal"] if text is not None and kind == "money" else text
                resolved = [issue for issue in issues if issue.startswith(label)]
                issues = [issue for issue in issues if not issue.startswith(label)]
                ids.append(db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,reason,actor,created_at) "
                                      "VALUES(?,?,?,?,?,?,?,?,?)", (record_type, record_id, field, stored, previous, json.dumps(resolved),
                                                                    clean_reason(reason), actor.current(), now())).lastrowid)
                continue
            column, kind, label = fields[field]
            value, stored = self._correction_value(db, kind, field, text, currency=row["currency"])
            current = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if kind == "receipt_money" and value is not None:
                value *= -1 if self.effective_receipt_direction(db, current) == "return" else 1
            previous = self._field_text(db, current, kind, column)
            resolved = [issue for issue in issues if issue.startswith(label)]
            issues = [issue for issue in issues if not issue.startswith(label)]
            if kind == "sale_type":
                self.set_receipt_direction(db, record_id, value)
            elif record_type == "receipt" and field == "total" and current["printed_total_minor"] is not None:
                # The printed total of a receipt paid partly by gift card; refresh_paid works out what was paid from it.
                db.execute("UPDATE receipts SET printed_total_minor=?,total_minor=CASE WHEN ? IS NULL THEN NULL ELSE total_minor END,updated_at=? WHERE id=?",
                           (abs(value) if value is not None else None, value, now(), record_id))
            else:
                db.execute(f"UPDATE {table} SET {column}=?,updated_at=? WHERE id=?", (value, now(), record_id))
            ids.append(db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,reason,actor,created_at) "
                                  "VALUES(?,?,?,?,?,?,?,?,?)", (record_type, record_id, field, stored, previous, json.dumps(resolved),
                                                                clean_reason(reason), actor.current(), now())).lastrowid)
        db.execute(f"UPDATE {table} SET validation_json=? WHERE id=?", (json.dumps(issues), record_id))
        if record_type == "receipt" and receipt_category(changes.get("category")):
            # The whole receipt's category is a shortcut for every item the user has not categorised one by one.
            db.execute("UPDATE receipt_items SET category=?,category_source='receipt' WHERE receipt_id=? AND coalesce(category_source,'')<>'user'",
                       (receipt_category(changes["category"]), record_id))
        if record_type == "receipt":
            self.bill_counts_on_due_date(db, record_id)
            self.refresh_splits(db, record_id)
        self.add_evidence(db, record_type, record_id, {"document_id": row["document_id"], "blob_hash": row["blob_hash"],
                                                       "source_key": f"user:correction:{ids[-1]}"}, {"entered_by_user": sorted(changes)})
        return ids

    def bill_summary(self, db, row, items, checks, issues):
        """A kinded bill's rows under its lines (docs/money.md "Bills and their lines"; specs/bill-kinds FR-50): the printed previous balance and payments, then
        what's left between those rows and the amount due, then the amount due. The left-over is the Earlier balance
        when nothing carried is printed and the lines add up to the printed new charges; otherwise it is Not accounted
        for, with the failing check's reason. None for invoices and bills read before kinds (plan P7)."""
        if row["document_kind"] != "bill" or not row["bill_kind"] or row["invoice_json"]:
            return None
        from .document_traces import provenance, reading
        currency, details = row["currency"], self.current_details(row)
        shown = lambda minor: money(minor, currency)  # noqa: E731
        carried = []
        for name, label, sign in (("previous_balance", "Previous balance", 1), ("payments_received", "Payment received", -1)):
            detail = details.get(name) or {}
            if detail.get("minor") is not None:
                carried.append({"label": label, **shown(sign * abs(detail["minor"]) if sign < 0 else detail["minor"]), "field": f"detail:{name}",
                                "line_ids": (detail.get("locator") or {}).get("line_ids", [])})
        due = row["amount_due_minor"]
        source = provenance(db, "receipt", row, "amount_due", result=reading(db, row))
        summary = {"carried": carried, "earlier_balance": None, "gap": None,
                   "amount_due": {**(shown(due) if due is not None else {"minor": None, "display": None}), "line_ids": source.get("line_ids", [])}}
        amounts = [item["line_total_minor"] for item in items if item["review_status"] != "rejected"]
        if due is None or any(amount is None for amount in amounts):
            return summary
        remainder = due - sum(amounts) - sum(item["minor"] for item in carried)
        if not remainder:
            return summary
        lines = next((check for check in checks if check["name"] == "lines"), None)
        new = (details.get("new_charges") or {}).get("minor")
        if not carried and new is not None and lines and lines["passes"]:
            summary["earlier_balance"] = shown(remainder)
            return summary
        failed = [check["name"] for check in checks if not check["passes"]]
        prefixes = (("Amount due: previous balance",) if "carried" in failed else ()) + ("Amount due: the lines", "New charges: the lines", "Amount due:")
        reason = next((issue for prefix in prefixes for issue in issues if issue.startswith(prefix)),
                      f"The rows above add up to {format_minor(due - remainder, currency)}, but the amount due is {format_minor(due, currency)}.")
        summary["gap"] = {**shown(remainder), "reason": reason}
        return summary

    @staticmethod
    def bill_counts_on_due_date(db, receipt_id):
        """A bill counts on its due date (its issue date when none is printed): purchase_date follows them."""
        db.execute("UPDATE receipts SET purchase_date=coalesce(due_date,issue_date,purchase_date) WHERE id=? AND document_kind='bill'", (receipt_id,))

    def _field_text(self, db, row, kind, column):
        """A correctable field as a correction enters it: the merchant's name, a money decimal, sale or return, or the value."""
        if kind == "name":
            return self._merchant_name(db, row[column])
        if kind in ("money", "receipt_money"):
            value = row[column]
            if column == "total_minor" and "printed_total_minor" in row.keys() and row["printed_total_minor"] is not None:
                value = row["printed_total_minor"]  # The printed total, not what was paid after gift cards.
            return money(abs(value) if kind == "receipt_money" else value, row["currency"])["decimal"] if value is not None else None
        if kind == "sale_type":
            return self.effective_receipt_direction(db, row)
        return row[column]

    def correctable(self, db, record_type, row):
        """The fields a person may correct on one record, each with the text a correction takes (docs/money.md
        "Corrections"): [{field, label, kind, value, shown_as, options?}]. shown_as is the record row the field corrects."""
        if record_type == "transaction":
            fields = [(field, TRANSACTION_LABELS[field], kind, self._transaction_text(db, row, field)) for field, (_, kind) in TRANSACTION_CORRECTABLE.items()]
        else:
            fields = [(field, label, kind, self._field_text(db, row, kind, column)) for field, (column, kind, label) in fields_for(record_type, row).items()]
        options = {"category": RECEIPT_CATEGORIES, "sale_type": ("sale", "return"), "direction": ("out", "in"),
                   "type": TRANSACTION_TYPES, "pay_frequency": ("", "52", "26", "24", "12"), "document_kind": ("receipt", "bill")}
        found = []
        for field, label, kind, value in fields:
            if kind == "pay_frequency" and value is not None:
                value = str(value)
            item = {"field": field, "label": label, "kind": kind, "value": value, "shown_as": "merchant" if field in ("provider", "payer") else field}
            if kind in options:
                item["options"] = list(options[kind])
            found.append(item)
        if record_type == "receipt":
            details = self.current_details(row)
            for field, (kind, label) in self.detail_fields(row).items():
                entry, key = self.detail_entry(details, field)
                shown = (money(abs(entry[key]), row["currency"])["decimal"] if entry.get(key) is not None else None) if key == "minor" else entry.get("text")
                found.append({"field": field, "label": label, "kind": kind, "value": shown, "shown_as": field})
        return found

    @staticmethod
    def detail_label(field):
        """What a detail correction is called once its detail is gone from the reading (its history still shows it)."""
        name = field.removeprefix("detail:")
        if name in DETAIL_CORRECTABLE:
            return DETAIL_CORRECTABLE[name][1]
        return "Payment amount" if name.startswith("tenders.") else name.replace("_", " ").capitalize()

    @staticmethod
    def detail_kind(field):
        """How a detail correction's value is shown: money (an amount) or its printed text."""
        name = field.removeprefix("detail:")
        return "money" if name.endswith(".amount") or DETAIL_CORRECTABLE.get(name, ("",))[0] == "money" else "text"

    def reapply_detail(self, db, receipt_id, field, text, currency):
        """A saved detail correction written again after a reading; False when the reading no longer has that detail."""
        row = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        if self.detail_entry(self.current_details(row), field) is None:
            return False
        self._set_detail(db, receipt_id, field, text, currency)
        return True

    def history(self, record_type, record_id):
        """A record's changes, newest first (docs/money.md "Corrections"): corrections (a statement's rows' too), review
        decisions and corrections received from the family. A correction is undoable while it is its field's latest."""
        if record_type not in RECORD_TABLES:
            raise ValueError("Unknown financial record type.")
        with self.store.connection() as db:
            row = db.execute(f"SELECT * FROM {RECORD_TABLES[record_type]} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            currency = row["currency"]
            targets = [(record_type, record_id, None)]
            if record_type == "receipt":
                targets.append(("receipt_item", record_id, None))
            if record_type == "statement":
                for line in db.execute("SELECT t.id,t.posted_date,coalesce(m.canonical_name,t.description_raw) AS name FROM transactions t "
                                       "LEFT JOIN merchants m ON m.id=t.merchant_id WHERE t.statement_id=? ORDER BY t.posted_date,t.id", (record_id,)):
                    targets.append(("transaction", line["id"], {"type": "transaction", "id": line["id"], "label": f"{line['name']} · {line['posted_date']}"}))
            entries = []
            bill = record_type == "receipt" and row["document_kind"] == "bill"
            income_labels = {}
            if record_type == "income_record":
                for line, key in self.income_line_keys(db, record_id):
                    income_labels.update({f"income_line:{key}:current": f"This period: {line['description']}",
                                          f"income_line:{key}:ytd": f"Year to date: {line['description']}"})
            detail_labels = ({field: label for field, (_, label) in self.detail_fields(row).items()} | {"receipt_kind": "Receipt kind", "bill_kind": "Bill kind", "receipt_details": "Receipt details"}
                             if record_type == "receipt" else {})
            for kind, target, shown_row in targets:
                labels = field_labels(kind, bill=bill and kind == "receipt") | (income_labels if kind == "income_record" else {}) | (
                    detail_labels if kind == "receipt" else {})
                if kind == "receipt_item":
                    labels = {f"{field}:{item['position']}": f"{what} {item['description'] or 'item ' + str(item['position'])}"
                              for item in db.execute("SELECT position,description FROM receipt_items WHERE receipt_id=?", (target,))
                              for field, what in (("price", "Price of"), ("line_kind", "Type of"), ("line_type", "Type of"), ("member", "Person for"))}
                kinds = ({field: value_kind for field, (_, value_kind) in TRANSACTION_CORRECTABLE.items()} | {"category": "category"} if kind == "transaction"
                         else {field: value_kind for field, (_, value_kind, _) in CORRECTABLE.get(kind, {}).items()})
                latest = dict(db.execute("SELECT field,max(id) FROM record_corrections WHERE record_type=? AND record_id=? GROUP BY field", (kind, target)).fetchall())
                for item in db.execute("SELECT * FROM record_corrections WHERE record_type=? AND record_id=?", (kind, target)):
                    value_kind = ("money" if item["field"].startswith("price:") else "text") if kind == "receipt_item" else (
                        "money" if kind == "income_record" and item["field"].startswith("income_line:") else
                        self.detail_kind(item["field"]) if item["field"].startswith("detail:") else kinds.get(item["field"], "text"))
                    shown = (lambda text: format_minor(to_minor(text, currency), currency) if text is not None else None) if value_kind in ("money", "amount", "receipt_money") else (lambda text: text)
                    entries.append({"kind": "correction", "id": item["id"], "at": item["created_at"], "who": item["actor"] or "Home Manager",
                                    "field": item["field"], "label": labels.get(item["field"], "Item price" if kind == "receipt_item" else
                                                                       self.detail_label(item["field"]) if item["field"].startswith("detail:") else
                                                                       item["field"].replace("_", " ").capitalize()),
                                    "value_kind": value_kind, "from": shown(item["previous"]), "to": shown(item["value"]), "reason": item["reason"],
                                    "resolved_issues": json.loads(item["resolved_issues_json"]),
                                    "undoable": latest.get(item["field"]) == item["id"] and (kind != "transaction" or item["field"] in TRANSACTION_CORRECTABLE),
                                    "row": shown_row, "_order": (item["created_at"], 1, item["id"])})
            for event in db.execute("SELECT * FROM review_events WHERE record_type=? AND record_id=?", (record_type, record_id)):
                automatic = event["note"] == AUTO_VERIFIED_NOTE and not event["actor"]
                entries.append({"kind": "review", "id": event["id"], "at": event["created_at"],
                                "who": event["actor"] or ("Automatic check" if automatic else "Home Manager"), "automatic": automatic,
                                "from_status": event["previous_status"], "to_status": event["new_status"], "note": event["note"],
                                "_order": (event["created_at"], 0, event["id"])})
            for number, item in enumerate(db.execute("SELECT * FROM family_corrections WHERE direction='received' AND record_type=? AND record_id=? ORDER BY created_at",
                                                     (record_type, record_id))):
                entries.append({"kind": "family", "at": item["created_at"], "who": item["actor"] or "The family", "field": item["field"],
                                "label": field_labels(record_type, bill=bill).get(item["field"], item["field"].replace("_", " ").capitalize()),
                                "from": item["previous"], "to": item["value"], "status": item["status"], "_order": (item["created_at"], 2, number)})
        entries.sort(key=lambda entry: entry.pop("_order"), reverse=True)
        return entries

    def undo_corrections(self, record_type, record_id, ids):
        """Put back what corrections replaced (each the latest of its field), with the issues they resolved. A record the
        correction verified automatically, and nobody has decided since, goes back to needing review."""
        if record_type not in RECORD_TABLES:
            raise ValueError("Unknown financial record type.")
        if not ids:
            raise ValueError("Choose the changes to undo.")
        with self.store.connection() as db:
            if db.execute(f"SELECT 1 FROM {RECORD_TABLES[record_type]} WHERE id=?", (record_id,)).fetchone() is None:
                raise ValueError("Financial record not found.")
            rows = [db.execute("SELECT * FROM record_corrections WHERE id=?", (correction_id,)).fetchone() for correction_id in ids]
            for row in rows:
                owned = row is not None and ((row["record_type"], row["record_id"]) == (record_type, record_id) or (
                    record_type == "receipt" and row["record_type"] == "receipt_item" and row["record_id"] == record_id) or (
                    record_type == "statement" and row["record_type"] == "transaction"
                    and db.execute("SELECT 1 FROM transactions WHERE id=? AND statement_id=?", (row["record_id"], record_id)).fetchone()))
                if not owned:
                    raise ValueError("That change isn't part of this record.")
                later = db.execute("SELECT 1 FROM record_corrections WHERE record_type=? AND record_id=? AND field=? AND id>?",
                                   (row["record_type"], row["record_id"], row["field"], row["id"])).fetchone()
                if later:
                    raise ValueError("It was changed again since; correct it instead.")
                if row["record_type"] == "transaction" and row["field"] not in TRANSACTION_CORRECTABLE:
                    raise ValueError("Change a transaction's category on the transaction instead.")
            for row in sorted(rows, key=lambda item: -item["id"]):
                if row["record_type"] == "income_record" and row["field"].startswith("income_line:"):
                    self._correct_income_line(db, record_id, row["field"], row["previous"], UNDO_REASON)
                    issues = json.loads(db.execute("SELECT validation_json FROM income_records WHERE id=?", (record_id,)).fetchone()[0])
                    issues += [issue for issue in json.loads(row["resolved_issues_json"]) if issue not in issues]
                    db.execute("UPDATE income_records SET validation_json=? WHERE id=?", (json.dumps(issues), record_id))
                    continue
                if row["record_type"] == "receipt_item":
                    name, position = row["field"].split(":")
                    if name in LINE_FIELDS:
                        db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,reason,actor,created_at) "
                                   "VALUES('receipt_item',?,?,?,?,?,?,?)", (record_id, row["field"], row["previous"], row["value"], UNDO_REASON,
                                                                           actor.current(), now()))
                        self._set_line(db, record_id, int(position), name, row["previous"])
                    else:
                        self._correct_item(db, record_id, int(position), row["previous"], UNDO_REASON, signed=True)
                    continue
                if row["record_type"] == "transaction":
                    self._apply_transaction_correction(db, row["record_id"], {row["field"]: row["previous"]}, UNDO_REASON)
                    continue
                if row["record_type"] == "receipt" and row["field"] in ("receipt_kind", "bill_kind", "receipt_details"):
                    self._undo_kind(db, record_id, row)
                    continue
                self._apply_correction(db, row["record_type"], row["record_id"], {row["field"]: row["previous"]}, UNDO_REASON)
                table = RECORD_TABLES[row["record_type"]]
                issues = json.loads(db.execute(f"SELECT validation_json FROM {table} WHERE id=?", (row["record_id"],)).fetchone()[0])
                issues += [issue for issue in json.loads(row["resolved_issues_json"]) if issue not in issues]
                db.execute(f"UPDATE {table} SET validation_json=? WHERE id=?", (json.dumps(issues), row["record_id"]))
            table = RECORD_TABLES[record_type]
            record = db.execute(f"SELECT review_status,review_source FROM {table} WHERE id=?", (record_id,)).fetchone()
            event = db.execute("SELECT note,actor,created_at FROM review_events WHERE record_type=? AND record_id=? ORDER BY id DESC LIMIT 1",
                               (record_type, record_id)).fetchone()
            first = min(row["created_at"] for row in rows)
            if (record["review_status"], record["review_source"]) == ("verified", "automatic") and event and event["note"] == AUTO_VERIFIED_NOTE \
                    and not event["actor"] and event["created_at"] >= first:
                db.execute(f"UPDATE {table} SET review_status='needs_review',updated_at=? WHERE id=?", (now(), record_id))
                db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at,actor) VALUES(?,?,'verified','needs_review',?,?,?)",
                           (record_type, record_id, "Undid a correction", now(), actor.current()))
            if record_type == "receipt" and any(row["field"] in PAID_FIELDS or row["field"].startswith("detail:") for row in rows):
                self.refresh_paid(db, record_id)  # Last, after the restored notes and the revert above.
        return self.record(record_type, record_id)

    def apply_corrections(self, db, record_type, record_id):
        """Re-apply the latest correction of each field after an extraction rewrote the model's values."""
        if record_type == "receipt":
            rent = db.execute("SELECT bill_kind FROM receipts WHERE id=?", (record_id,)).fetchone()[0] == "rent"
            found = db.execute("SELECT field,value FROM record_corrections c WHERE record_type='receipt_item' AND record_id=? "
                               "AND id=(SELECT max(id) FROM record_corrections WHERE record_type=c.record_type AND record_id=c.record_id AND field=c.field)",
                               (record_id,)).fetchall()
            # A rent type first (only on a bill read as rent), then a line kind, so a person's line kind wins over the
            # rent type's mapping (specs/bill-kinds plan "Replaying line corrections on a re-read").
            for item in sorted(found, key=lambda row: not row["field"].startswith("line_type:")):
                name, position = item["field"].split(":")
                if name == "line_type" and not rent:
                    continue
                if name in LINE_FIELDS:  # A bill line's type or person, as the person set it.
                    self._set_line(db, record_id, int(position), name, item["value"])
                    continue
                currency = db.execute("SELECT currency FROM receipts WHERE id=?", (record_id,)).fetchone()[0]
                price = to_minor(item["value"], currency) if item["value"] is not None else None
                db.execute("UPDATE receipt_items SET line_total_minor=? WHERE receipt_id=? AND position=?", (price, record_id, int(position)))
        table = RECORD_TABLES[record_type]
        fields = fields_for(record_type, db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone())
        latest = db.execute("SELECT field,value FROM record_corrections c WHERE record_type=? AND record_id=? "
                            "AND id=(SELECT max(id) FROM record_corrections WHERE record_type=c.record_type AND record_id=c.record_id AND field=c.field)",
                            (record_type, record_id)).fetchall()
        if not latest:
            return
        stored_json, currency = db.execute(f"SELECT validation_json,currency FROM {table} WHERE id=?", (record_id,)).fetchone()
        issues = json.loads(stored_json)
        for field, text in sorted(latest, key=lambda pair: (pair[0] != "document_kind", pair[0] == "direction")):
            if field.startswith("detail:"):
                if record_type == "receipt" and self.reapply_detail(db, record_id, field, text, currency):
                    issues = [issue for issue in issues if not issue.startswith(self.detail_label(field))]
                continue
            if field == "document_kind":
                value, _ = self._correction_value(db, "document_kind", field, text)
                db.execute("UPDATE receipts SET document_kind=? WHERE id=?", (value, record_id))
                fields = fields_for(record_type, db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone())
            if field not in fields:  # A field this kind of record no longer shows (a receipt read again as a bill).
                continue
            column, kind, label = fields[field]
            value, _ = self._correction_value(db, kind, field, text, stored=True, currency=currency)
            if kind == "receipt_money" and value is not None:
                current = db.execute("SELECT * FROM receipts WHERE id=?", (record_id,)).fetchone()
                value *= -1 if self.effective_receipt_direction(db, current) == "return" else 1
            if kind == "sale_type":
                self.set_receipt_direction(db, record_id, value)
            else:
                db.execute(f"UPDATE {table} SET {column}=? WHERE id=?", (value, record_id))
            issues = [issue for issue in issues if not issue.startswith(label)]
        db.execute(f"UPDATE {table} SET validation_json=? WHERE id=?", (json.dumps(issues), record_id))
        if record_type == "receipt":
            self.bill_counts_on_due_date(db, record_id)

    @staticmethod
    def income_line_keys(db, income_id):
        """Match a pay line by its group, description and occurrence across readings of the same stub."""
        seen = Counter()
        found = []
        for line in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY position", (income_id,)):
            name = (line["line_group"], normalize_name(line["description"]))
            ordinal = seen[name]
            seen[name] += 1
            key = hashlib.sha256(f"{name[0]}\0{name[1]}\0{ordinal}".encode()).hexdigest()[:24]
            found.append((line, key))
        return found

    def _correct_income_line(self, db, income_id, field, text, reason):
        _, key, name = field.split(":")
        if name not in ("current", "ytd"):
            raise ValueError("Choose this period or year to date.")
        matched = next((line for line, candidate in self.income_line_keys(db, income_id) if candidate == key), None)
        if matched is None:
            raise ValueError("This pay line is no longer in the reading.")
        currency = db.execute("SELECT currency FROM income_records WHERE id=?", (income_id,)).fetchone()[0]
        column = "current_minor" if name == "current" else "ytd_minor"
        value, stored = self._correction_value(db, "money", name, text, currency=currency)
        previous = money(matched[column], currency)["decimal"] if matched[column] is not None else None
        db.execute(f"UPDATE income_lines SET {column}=?,updated_at=? WHERE id=?", (value, now(), matched["id"]))
        # Notes about this line's amount clear as for other fields; undo puts them back (FR-23).
        issues = json.loads(db.execute("SELECT validation_json FROM income_records WHERE id=?", (income_id,)).fetchone()[0])
        label = self.income_line_label(matched, name)
        resolved = [issue for issue in issues if issue.startswith(label)]
        db.execute("UPDATE income_records SET validation_json=?,updated_at=? WHERE id=?",
                   (json.dumps([issue for issue in issues if not issue.startswith(label)]), now(), income_id))
        return db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,reason,actor,created_at) "
                          "VALUES('income_record',?,?,?,?,?,?,?,?)",
                          (income_id, field, stored, previous, json.dumps(resolved), clean_reason(reason), actor.current(), now())).lastrowid

    @staticmethod
    def income_line_label(line, name):
        """What a pay line's amount is called in its notes and history: "This period: Regular" or "Year to date: Regular"."""
        return f"{'This period' if name == 'current' else 'Year to date'}: {line['description']}"

    def correct_income_line(self, income_id, position, changes, reason=None):
        if not changes or set(changes) - {"current", "ytd"}:
            raise ValueError("Choose this period or year to date.")
        with self.store.connection() as db:
            line = next(((row, key) for row, key in self.income_line_keys(db, income_id) if row["position"] == position), None)
            if line is None:
                raise ValueError("Pay line not found.")
            ids = [self._correct_income_line(db, income_id, f"income_line:{line[1]}:{name}", text, reason)
                   for name, text in changes.items()]
        return {**self.record("income_record", income_id), "correction_ids": ids}

    def apply_income_line_corrections(self, db, income_id):
        """Re-apply each pay line's latest correction after a reading; a corrected line's notes stay cleared."""
        keys = {key: line for line, key in self.income_line_keys(db, income_id)}
        currency, stored_json = db.execute("SELECT currency,validation_json FROM income_records WHERE id=?", (income_id,)).fetchone()
        issues = json.loads(stored_json)
        latest = db.execute("SELECT field,value FROM record_corrections c WHERE record_type='income_record' AND record_id=? "
                            "AND field LIKE 'income_line:%' AND id=(SELECT max(id) FROM record_corrections "
                            "WHERE record_type=c.record_type AND record_id=c.record_id AND field=c.field)", (income_id,)).fetchall()
        for field, text in latest:
            _, key, name = field.split(":")
            if key in keys and name in ("current", "ytd"):
                column = "current_minor" if name == "current" else "ytd_minor"
                value = to_minor(text, currency) if text is not None else None
                db.execute(f"UPDATE income_lines SET {column}=?,updated_at=? WHERE id=?", (value, now(), keys[key]["id"]))
                label = self.income_line_label(keys[key], name)
                issues = [issue for issue in issues if not issue.startswith(label)]
        if latest:
            db.execute("UPDATE income_records SET validation_json=? WHERE id=?", (json.dumps(issues), income_id))

    def correct_item(self, receipt_id, position, price, reason=None):
        """Keep an item price correction by printed position across re-readings (docs/money.md)."""
        with self.store.connection() as db:
            correction_id = self._correct_item(db, receipt_id, position, price, reason)
        return {"record": self.record("receipt", receipt_id), "correction_ids": [correction_id]}

    def correct_line(self, receipt_id, position, field, value, reason=None, members=None):
        """A bill line's type (line_kind) or whose it is (member: a family member's id, or None for nobody), kept by printed
        position across re-readings like a price (docs/money.md "Bills and their lines"). members: the ids a person may be
        given, when the family is known here; otherwise any id the line already had or none. A rent bill's line takes a
        rent type (line_type, which also sets its line_kind); its line_kind is refused once it has a rent type
        (specs/bill-kinds FR-45)."""
        if field not in LINE_FIELDS:
            raise ValueError("Choose the line's type or person.")
        value = " ".join(str(value).split()) or None if value is not None else None
        if field == "line_kind" and value not in (None, *LINE_KINDS):
            raise ValueError("Choose one of the listed line types.")
        if field == "line_type" and value not in (None, *RENT_LINE_TYPES):
            raise ValueError("Choose one of the rent bill's line types.")
        with self.store.connection() as db:
            row = db.execute("SELECT i.*,r.bill_kind FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id WHERE i.receipt_id=? AND i.position=? "
                             "AND r.document_kind='bill'", (receipt_id, position)).fetchone()
            if row is None:
                raise ValueError("Bill line not found.")
            if field == "line_type" and row["bill_kind"] != "rent":
                raise ValueError("Only a rent bill's lines have a rent type.")
            if field == "line_kind" and row["bill_kind"] == "rent" and row["line_type"] is not None:
                raise ValueError("Choose one of the rent bill's line types.")
            if field == "member" and value is not None and value not in (members or ()) and value != row["member_id"]:
                raise ValueError("Choose someone in the family.")
            correction_id = db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,reason,actor,created_at) "
                                       "VALUES('receipt_item',?,?,?,?,?,?,?)", (receipt_id, f"{field}:{position}", value, row[LINE_FIELDS[field]],
                                                                               clean_reason(reason), actor.current(), now())).lastrowid
            self._set_line(db, receipt_id, position, field, value)
        return {"record": self.record("receipt", receipt_id), "correction_ids": [correction_id]}

    def _set_line(self, db, receipt_id, position, field, value):
        if field == "member":
            db.execute("UPDATE receipt_items SET member_id=?,member_source=CASE WHEN ? IS NULL THEN NULL ELSE 'user' END,updated_at=? "
                       "WHERE receipt_id=? AND position=?", (value, value, now(), receipt_id, position))
        elif field == "line_type":  # A rent type and the line kind it is stored with; cleared, the line keeps its line kind.
            db.execute("UPDATE receipt_items SET line_type=?,line_kind=coalesce(?,line_kind),updated_at=? WHERE receipt_id=? AND position=?",
                       (value, RENT_LINE_KINDS.get(value) if value else None, now(), receipt_id, position))
        else:
            db.execute("UPDATE receipt_items SET line_kind=?,updated_at=? WHERE receipt_id=? AND position=?", (value, now(), receipt_id, position))
        self.refresh_splits(db, receipt_id)

    @staticmethod
    def effective_receipt_direction(db, row):
        """An explicit direction also survives a missing or zero total."""
        saved = db.execute("SELECT value FROM record_corrections WHERE record_type='receipt' AND record_id=? AND field='direction' ORDER BY id DESC LIMIT 1",
                           (row["id"],)).fetchone()
        if saved and saved[0] in ("sale", "return"):
            return saved[0]
        for field in ("total_minor", "subtotal_minor", "tax_minor", "tip_minor"):
            if row[field]:
                return "return" if row[field] < 0 else "sale"
        return "sale"

    def _correct_item(self, db, receipt_id, position, price, reason, signed=False):
        row = db.execute("SELECT i.*,r.currency,r.total_minor FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id "
                         "WHERE i.receipt_id=? AND i.position=?", (receipt_id, position)).fetchone()
        if row is None:
            raise ValueError("Receipt item not found.")
        value, _ = self._correction_value(db, "money" if signed else "receipt_money", "price", price, currency=row["currency"])
        if value is not None:
            value = abs(value)  # Undo restores the price, keeping any later sale/return direction change.
            receipt = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
            negative = row["line_total_minor"] < 0 if row["line_total_minor"] else self.effective_receipt_direction(db, receipt) == "return"
            value *= -1 if negative else 1
        decimal = lambda amount: money(amount, row["currency"])["decimal"] if amount is not None else None
        correction_id = db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,reason,actor,created_at) "
                                   "VALUES('receipt_item',?,?,?,?,?,?,?)", (receipt_id, f"price:{position}", decimal(value), decimal(row["line_total_minor"]),
                                                                           clean_reason(reason), actor.current(), now())).lastrowid
        db.execute("UPDATE receipt_items SET line_total_minor=?,updated_at=? WHERE receipt_id=? AND position=?", (value, now(), receipt_id, position))
        self.refresh_splits(db, receipt_id)
        return correction_id

    @staticmethod
    def set_receipt_direction(db, receipt_id, direction):
        """Make a receipt a sale (amounts positive) or a return (negative), with its family share. An exchange's lines
        (some bought, some returned) keep their signs; a receipt whose lines all agree flips them too."""
        sign = -1 if direction == "return" else 1
        db.execute("UPDATE receipts SET subtotal_minor=?*abs(subtotal_minor),tax_minor=?*abs(tax_minor),tip_minor=?*abs(tip_minor),"
                   "total_minor=?*abs(total_minor),updated_at=? WHERE id=?", (sign, sign, sign, sign, now(), receipt_id))
        signs = {row[0] for row in db.execute("SELECT DISTINCT line_total_minor<0 FROM receipt_items WHERE receipt_id=? AND line_total_minor<>0",
                                              (receipt_id,))}
        if len(signs) <= 1:
            db.execute("UPDATE receipt_items SET line_total_minor=?*abs(line_total_minor),updated_at=? WHERE receipt_id=?", (sign, now(), receipt_id))
        db.execute("UPDATE record_shares SET share_minor=?*abs(share_minor),total_minor=?*abs(total_minor) WHERE record_type='receipt' AND record_id=?",
                   (sign, sign, receipt_id))

    @staticmethod
    def corrections(db, record_type, record_id):
        return [dict(row) for row in db.execute("SELECT field,value,previous,reason,actor,created_at FROM record_corrections WHERE record_type=? AND record_id=? ORDER BY id",
                                                (record_type, record_id))]

    @staticmethod
    def _merchant_name(db, merchant_id):
        row = db.execute("SELECT canonical_name FROM merchants WHERE id=?", (merchant_id,)).fetchone() if merchant_id else None
        return row[0] if row else None
