"""Deterministic financial tools (spec section 11) over the canonical ledger.

SQL integer sums and Decimal do all arithmetic; nothing here calls a model. Results
carry provenance (record IDs, source documents) and explicit coverage, and never
invent values: a missing balance is reported as unavailable, not estimated. Amounts
are per currency; no conversion is performed. Model-extracted rows count only once
verified and are otherwise reported separately as pending review.
"""

from collections import defaultdict
from contextlib import contextmanager
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.money import currency_code, money, to_minor
from ..household.analysis import ANOMALY_TOOLS, ITEM_TOOLS, ItemAnalysisTools
from ..household.items import ItemLedger
from .ledger import (COUNTABLE, PENDING, RECEIPT_SPLIT_CATEGORY, RECEIPT_SPLIT_SPENT, RECEIPT_SPLITS, SPENDING, SPLIT_CATEGORY, SPLIT_SPENT,
                     STANDALONE_RECEIPT, TRANSACTION_SPLITS, Ledger, in_categories, name_tokens, normalize_name)
from .reconcile import RECEIPT_POSTING_DAYS, shift

SPENDING_TYPES = ",".join(f"'{kind}'" for kind in SPENDING)
TRANSACTION_TYPES = ("purchase", "refund", "payment", "transfer", "deposit", "fee", "interest", "withdrawal", "other")
# Which rows a transaction query includes: counted totals, extracted rows awaiting review, or rejected rows.
STATUS_FILTERS = {"counted": COUNTABLE, "pending": PENDING, "rejected": "t.review_status='rejected'"}
TRANSACTION_SORTS = {"date_desc": "t.posted_date DESC,t.id DESC", "date_asc": "t.posted_date,t.id",
                     "amount_desc": "t.amount_minor DESC,t.id DESC", "amount_asc": "t.amount_minor,t.id",
                     "description": "normalized_name(t.description_raw),t.id"}
HAS_RECEIPT = "EXISTS(SELECT 1 FROM transaction_receipt_links l WHERE l.transaction_id=t.id AND l.review_status<>'rejected')"
# A receipt with no link to a charge that the user has not rejected.
UNLINKED_RECEIPT = "r.review_status<>'rejected' AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l WHERE l.receipt_id=r.id AND l.review_status<>'rejected')"
MAX_SERIES_MONTHS = 36
# A spending-items row: one receipt item, a tip or other amount no item carries, or a whole charge or receipt.
ROW_KIND = "CASE WHEN s.id IS NULL THEN 'charge' WHEN s.receipt_item_id IS NULL THEN 'extra' ELSE 'item' END"
RECEIPT_NOTE = ("Spending counts card and bank lines plus approved receipts that no line has replaced yet (from_receipts, receipts). "
                "When a statement line matches a receipt, the line counts instead, never both.")
PENDING_NOTE = "pending_review holds extracted lines awaiting review and statement lines waiting for you to reconcile their statement; they are not counted yet."


def iso(value):
    date.fromisoformat(value)
    if len(value) != 10:
        raise ValueError("Use YYYY-MM-DD dates.")
    return value


def month_index(value):
    year, month = map(int, value.split("-"))
    if not 1 <= month <= 12:
        raise ValueError("Use YYYY-MM months.")
    return year * 12 + month - 1


def month_label(index):
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def last_day(index):
    """ISO date of the last day of the month at this month index."""
    year, month = divmod(index + 1, 12)
    return (date(year, month + 1, 1) - timedelta(days=1)).isoformat()


def percent_change(before, after):
    """Exact percentage to one decimal place, or None when there is nothing to compare against."""
    return None if before == 0 else str((Decimal(after - before) * 100 / Decimal(before)).quantize(Decimal("0.1"), ROUND_HALF_EVEN))


class ToolInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PeriodInput(ToolInput):
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    account_id: int | None = None

    @model_validator(mode="after")
    def ordered(self):
        if iso(self.start) > iso(self.end):
            raise ValueError("The period start must not be after its end.")
        return self


class CompareInput(ToolInput):
    first: PeriodInput
    second: PeriodInput


class SeriesInput(ToolInput):
    start_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    end_month: str = Field(pattern=r"^\d{4}-\d{2}$")
    account_id: int | None = None

    @model_validator(mode="after")
    def bounded(self):
        months = month_index(self.end_month) - month_index(self.start_month) + 1
        if months < 1:
            raise ValueError("The first month must not be after the last.")
        if months > MAX_SERIES_MONTHS:
            raise ValueError(f"Choose at most {MAX_SERIES_MONTHS} months.")
        return self


class TransactionsInput(ToolInput):
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    account_id: int | None = None
    query: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, min_length=1, max_length=60, description="A category name, or 'uncategorized'.")
    transaction_types: list[Literal[*TRANSACTION_TYPES]] | None = Field(default=None, min_length=1, max_length=len(TRANSACTION_TYPES))
    statuses: list[Literal[*STATUS_FILTERS]] | None = Field(default=None, min_length=1, max_length=len(STATUS_FILTERS),
                                                           description="Defaults to counted rows, plus pending ones when include_pending is true.")
    include_pending: bool = False
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    categories: list[str] | None = Field(default=None, min_length=1, max_length=500)
    metric: Literal["spending", "inflow", "cashflow", "categories"] | None = None
    has_receipt: bool | None = None
    sort: Literal[*TRANSACTION_SORTS] = "date_desc"
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=200, ge=1, le=1000)


class SpendingItemsInput(ToolInput):
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    account_id: int | None = None
    category: str | None = Field(default=None, min_length=1, max_length=60, description="A category name, or 'uncategorized'.")
    categories: list[str] | None = Field(default=None, min_length=1, max_length=500)
    query: str | None = Field(default=None, max_length=200, description="Words in the merchant, charge description or item name.")
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=200, ge=1, le=1000)


class AccountInput(ToolInput):
    account_id: int


class RecordInput(ToolInput):
    record_id: int


class AsOfInput(ToolInput):
    as_of: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    days: int = Field(default=30, ge=1, le=366)


class ReceiptSearchInput(ToolInput):
    merchant: str | None = Field(default=None, max_length=200)
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    amount: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, pattern=r"^[A-Za-z]{3}$")


class EmptyInput(ToolInput):
    pass


class BudgetInput(ToolInput):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")
    as_of: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$", description="The day pace is measured at; defaults to today.")


class InventoryInput(ToolInput):
    query: str | None = Field(default=None, max_length=100, description="Product name, brand or category words; omit for everything in stock.")
    include_closed: bool = Field(default=False, description="Also list items marked finished or thrown out.")


def scope_of(start, end, account_id):
    """SQL predicate and parameters for a posted-date period, optionally one account."""
    scope, params = "t.posted_date BETWEEN ? AND ?", [start, end]
    if account_id is not None:
        scope, params = scope + " AND t.account_id=?", [*params, account_id]
    return scope, params


def totals_view(currency, bucket):
    """from_receipts is the part of spending that only receipts show so far; the rest is card and bank lines."""
    return {"currency": currency, "spending": money(bucket["spending"], currency), "refunds": money(bucket["refunds"], currency),
            "net_spending": money(bucket["spending"] - bucket["refunds"], currency), "transactions": bucket["transactions"],
            "from_receipts": money(bucket["from_receipts"], currency), "receipts": bucket["receipts"]}


class FinanceTools(ItemAnalysisTools):
    def __init__(self, store):
        self.store, self.ledger = store, Ledger(store)

    @contextmanager
    def connection(self):
        # The merchant-key normalizer is the same function the ledger uses to write keys.
        with self.store.connection() as db:
            db.create_function("normalized_name", 1, normalize_name, deterministic=True)
            yield db

    def query(self, sql, params=()):
        with self.connection() as db:
            return [dict(row) for row in db.execute(sql, params)]

    # Accounts -----------------------------------------------------------------

    def get_accounts(self, _=None):
        accounts = []
        for account in self.ledger.accounts():
            coverage = self.query(f"SELECT min(t.posted_date) AS first,max(t.posted_date) AS last,count(*) AS transactions FROM transactions t WHERE t.account_id=? AND {COUNTABLE}",
                                  (account["id"],))[0]
            accounts.append({**account, "coverage": coverage, "balance": self.get_account_balance(AccountInput(account_id=account["id"]))["balance"]})
        return {"accounts": accounts}

    def get_account_balance(self, value):
        account = self.ledger.account(value.account_id)
        rows = self.query("SELECT id,period_end,closing_balance_minor,statement_balance_minor,review_status FROM statements WHERE account_id=? "
                          "AND review_status<>'rejected' AND period_end IS NOT NULL ORDER BY period_end DESC LIMIT 1", (account["id"],))
        if not rows or (rows[0]["closing_balance_minor"] is None and rows[0]["statement_balance_minor"] is None):
            return {"account_id": account["id"], "balance": None,
                    "note": "No statement balance is available. A current balance is not calculated from partial transaction history."}
        row = rows[0]
        amount = row["closing_balance_minor"] if row["closing_balance_minor"] is not None else row["statement_balance_minor"]
        return {"account_id": account["id"], "balance": {**money(amount, account["currency"]), "as_of": row["period_end"],
                "days_old": (date.today() - date.fromisoformat(row["period_end"])).days, "statement_id": row["id"], "review_status": row["review_status"],
                "meaning": "amount owed" if account["account_type"] == "credit_card" else "account balance"},
                "note": "Statement balance as of its period end, not a live balance."}

    # Transactions ---------------------------------------------------------------

    def get_transactions(self, value):
        statuses = value.statuses or (["counted", "pending"] if value.include_pending else ["counted"])
        clauses = ["(" + " OR ".join(f"({STATUS_FILTERS[status]})" for status in statuses) + ")"]
        params = []
        for column, operator, item in (("t.posted_date", ">=", value.start), ("t.posted_date", "<=", value.end), ("t.account_id", "=", value.account_id)):
            if item is not None:
                clauses.append(f"{column}{operator}?")
                params.append(item)
        if value.category:
            clauses.append(in_categories(1))
            params += [" ".join(value.category.split()).lower()] * 2
        if value.currency:
            clauses.append("t.currency=?")
            params.append(currency_code(value.currency))
        if value.categories:
            clauses.append(in_categories(len(value.categories)))
            params += value.categories * 2
        if value.metric:
            spending = f"t.transaction_type IN ({SPENDING_TYPES},'refund')"
            inflow = "(t.amount_minor>0 AND t.transaction_type IN ('deposit','interest','other'))"
            clauses.append({"spending": spending, "inflow": inflow, "cashflow": f"({spending} OR {inflow})",
                            "categories": f"t.transaction_type IN ({SPENDING_TYPES})"}[value.metric])
        if value.transaction_types:
            clauses.append(f"t.transaction_type IN ({','.join('?' * len(value.transaction_types))})")
            params += value.transaction_types
        if value.has_receipt is not None:
            clauses.append(HAS_RECEIPT if value.has_receipt else f"NOT {HAS_RECEIPT}")
        # Every query word must appear in the description or the merchant's name, compared as merchant keys.
        for token in normalize_name(value.query).split() if value.query else []:
            clauses.append("instr(' '||normalized_name(t.description_raw||' '||coalesce(m.canonical_name,''))||' ',?)>0")
            params.append(f" {token} ")
        tables = "FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN merchants m ON m.id=t.merchant_id "
        where = "WHERE " + " AND ".join(clauses)
        # The matched receipt (confirmed or proposed, the earliest if several), with the document to open for it.
        receipt = ("LEFT JOIN transaction_receipt_links l ON l.id=(SELECT min(k.id) FROM transaction_receipt_links k WHERE k.transaction_id=t.id "
                   "AND k.review_status<>'rejected') LEFT JOIN receipts r ON r.id=l.receipt_id ")
        with self.connection() as db:
            total = db.execute("SELECT count(*) " + tables + where, params).fetchone()[0]
            rows = [dict(row) for row in db.execute(
                "SELECT t.*,a.display_name AS account,m.canonical_name AS merchant,l.receipt_id,l.review_status AS receipt_link_status,"
                "r.document_id AS receipt_document_id " + tables + receipt + where
                + f" ORDER BY {TRANSACTION_SORTS[value.sort]} LIMIT ? OFFSET ?", [*params, value.limit, value.offset])]
        return {"transactions": [{**row, "amount": money(row["amount_minor"], row["currency"]),
                                  "counted": row["review_status"] != "rejected" and (row["origin"] != "extraction" or row["review_status"] == "verified")}
                                 for row in rows],
                "total_matching": total, "offset": value.offset, "limit": value.limit}

    # Spending -----------------------------------------------------------------

    def _totals(self, start, end, account_id, by_month=False):
        """Counted spending and refunds keyed by (month or None, currency). Spending includes receipts no card or
        bank line has replaced yet (also reported as from_receipts), unless one account is asked for."""
        scope, params = scope_of(start, end, account_id)
        month = "substr(t.posted_date,1,7)" if by_month else "NULL"
        totals = defaultdict(lambda: {"spending": 0, "refunds": 0, "transactions": 0, "from_receipts": 0, "receipts": 0})
        for row in self.query(f"SELECT {month} AS month,t.currency,t.transaction_type='refund' AS refund,sum(t.amount_minor) AS total,count(*) AS count "
                              f"FROM transactions t WHERE {COUNTABLE} AND {scope} AND t.transaction_type IN ({SPENDING_TYPES},'refund') GROUP BY 1,2,3", params):
            bucket = totals[(row["month"], row["currency"])]
            if row["refund"]:
                bucket["refunds"] += row["total"]
            else:
                bucket["spending"] -= row["total"]
            bucket["transactions"] += row["count"]
        if account_id is None:
            month = "substr(r.purchase_date,1,7)" if by_month else "NULL"
            for row in self.query(f"SELECT {month} AS month,r.currency,sum(r.total_minor) AS total,count(*) AS count FROM receipts r "
                                  f"WHERE {STANDALONE_RECEIPT} AND r.purchase_date BETWEEN ? AND ? GROUP BY 1,2", (start, end)):
                bucket = totals[(row["month"], row["currency"])]
                bucket["spending"] += row["total"]
                bucket["from_receipts"] += row["total"]
                bucket["receipts"] += row["count"]
        return totals

    def _pending(self, scope, params, by_month=False):
        month = "substr(t.posted_date,1,7)" if by_month else "NULL"
        return self.query(f"SELECT {month} AS month,t.currency,-sum(t.amount_minor) AS total,count(*) AS count FROM transactions t WHERE {PENDING} AND {scope} "
                          f"AND t.transaction_type IN ({SPENDING_TYPES}) GROUP BY 1,2", params)

    def _coverage(self, scope, params, account_id=None):
        return self.query(f"SELECT a.id AS account_id,a.display_name,min(t.posted_date) AS first,max(t.posted_date) AS last,count(t.id) AS transactions "
                          f"FROM accounts a LEFT JOIN transactions t ON t.account_id=a.id AND {COUNTABLE} AND {scope} "
                          + ("WHERE a.id=? " if account_id is not None else "") + "GROUP BY a.id ORDER BY a.id",
                          [*params, account_id] if account_id is not None else params)

    def _net_by_currency(self, start, end, account_id):
        return {currency: bucket["spending"] - bucket["refunds"] for (_, currency), bucket in self._totals(start, end, account_id).items()}

    def get_spending(self, value):
        scope, params = scope_of(value.start, value.end, value.account_id)
        totals = self._totals(value.start, value.end, value.account_id)
        excluded = self.query(f"SELECT count(*) AS count FROM transactions t WHERE {COUNTABLE} AND {scope} AND t.transaction_type IN ('transfer','payment')", params)[0]["count"]
        return {"period": {"start": value.start, "end": value.end},
                "by_currency": [totals_view(currency, bucket) for (_, currency), bucket in sorted(totals.items())],
                "pending_review": [{"currency": row["currency"], "amount": money(row["total"], row["currency"]), "transactions": row["count"]}
                                   for row in self._pending(scope, params)],
                "excluded_transfers_and_card_payments": excluded, "coverage": self._coverage(scope, params, value.account_id),
                "notes": [RECEIPT_NOTE if value.account_id is None else "Totals cover only this account's imported or verified transactions.",
                          PENDING_NOTE, "Each currency is totalled separately; no conversion was applied."]}

    def spending_series(self, value):
        """Monthly counted spending per currency, in one grouped query. Months without data are listed empty."""
        first, last = month_index(value.start_month), month_index(value.end_month)
        months = [month_label(index) for index in range(first, last + 1)]
        scope, params = scope_of(months[0] + "-01", last_day(last), value.account_id)
        totals, pending = self._totals(months[0] + "-01", last_day(last), value.account_id, by_month=True), defaultdict(list)
        for row in self._pending(scope, params, by_month=True):
            pending[row["month"]].append({"currency": row["currency"], "amount": money(row["total"], row["currency"]), "transactions": row["count"]})
        return {"months": [{"month": key, "by_currency": [totals_view(currency, bucket) for (item, currency), bucket in sorted(totals.items()) if item == key],
                            "pending_review": pending[key]} for key in months],
                "coverage": self._coverage(scope, params, value.account_id),
                "notes": [RECEIPT_NOTE if value.account_id is None else "Each month counts only this account's imported or verified transactions.",
                          "Months with no rows have no totals.", "Each currency is totalled separately; no conversion was applied."]}

    def _category_totals(self, start, end, account_id):
        """(currency, category) -> (spending, count), with receipts no line has replaced unless one account is asked for.
        A charge or receipt with categorised items is divided by item category (finance/splits.py); count is the
        number of charges and receipts with spending in the category."""
        scope, params = scope_of(start, end, account_id)
        totals = defaultdict(lambda: [0, 0])
        rows = self.query(f"SELECT t.currency,{SPLIT_CATEGORY} AS category,sum({SPLIT_SPENT}) AS total,count(DISTINCT t.id) AS count "
                          f"FROM transactions t {TRANSACTION_SPLITS} WHERE {COUNTABLE} AND {scope} AND t.transaction_type IN ({SPENDING_TYPES}) GROUP BY 1,2", params)
        if account_id is None:
            rows += self.query(f"SELECT r.currency,{RECEIPT_SPLIT_CATEGORY} AS category,sum({RECEIPT_SPLIT_SPENT}) AS total,count(DISTINCT r.id) AS count "
                               f"FROM receipts r {RECEIPT_SPLITS} WHERE {STANDALONE_RECEIPT} AND r.purchase_date BETWEEN ? AND ? GROUP BY 1,2", (start, end))
        for row in rows:
            totals[(row["currency"], row["category"])][0] += row["total"]
            totals[(row["currency"], row["category"])][1] += row["count"]
        return {key: tuple(value) for key, value in totals.items()}

    def get_spending_by_category(self, value):
        scope, params = scope_of(value.start, value.end, value.account_id)
        categories = sorted(self._category_totals(value.start, value.end, value.account_id).items(), key=lambda item: (item[0][0], -item[1][0]))
        merchants = defaultdict(lambda: [0, 0])
        rows = self.query(f"SELECT t.currency,coalesce(m.canonical_name,t.description_raw) AS name,t.amount_minor FROM transactions t "
                          f"LEFT JOIN merchants m ON m.id=t.merchant_id WHERE {COUNTABLE} AND {scope} AND t.transaction_type IN ({SPENDING_TYPES})", params)
        if value.account_id is None:
            rows += self.query(f"SELECT r.currency,coalesce(m.canonical_name,'UNKNOWN') AS name,-r.total_minor AS amount_minor FROM receipts r "
                               f"LEFT JOIN merchants m ON m.id=r.merchant_id WHERE {STANDALONE_RECEIPT} AND r.purchase_date BETWEEN ? AND ?", (value.start, value.end))
        for row in rows:
            key = (row["currency"], " ".join(normalize_name(row["name"]).split()[:3]) or "UNKNOWN")
            merchants[key][0] -= row["amount_minor"]
            merchants[key][1] += 1
        top = sorted(merchants.items(), key=lambda item: -item[1][0])[:20]
        return {"period": {"start": value.start, "end": value.end},
                "categories": [{"currency": currency, "category": category, "spending": money(total, currency), "transactions": count}
                               for (currency, category), (total, count) in categories],
                "top_merchants": [{"currency": currency, "merchant": name, "spending": money(total, currency), "transactions": count}
                                  for (currency, name), (total, count) in top]}

    def get_spending_items(self, value):
        """Counted spending one item per row, like a statement that lists what was bought: each charge's or receipt's
        items with their share of what was paid, or the charge itself when no itemised receipt is matched to it.
        status: reconciled (a statement line and a receipt agree), statement (a line with no receipt) or receipt
        (a receipt no line has replaced yet)."""
        dated, params = [], []
        for bound, operator in ((value.start, ">="), (value.end, "<=")):
            if bound is not None:
                dated.append(operator)
                params.append(bound)
        charge_scope = "".join(f" AND t.posted_date{operator}?" for operator in dated)
        receipt_scope = "".join(f" AND r.purchase_date{operator}?" for operator in dated)
        if value.account_id is not None:
            charge_scope += " AND t.account_id=?"
        linked = "(SELECT l.receipt_id FROM transaction_receipt_links l WHERE l.transaction_id=t.id AND l.review_status<>'rejected' ORDER BY l.id LIMIT 1)"
        rows = (f"SELECT 'transaction' AS source,t.id AS transaction_id,{linked} AS receipt_id,t.posted_date AS date,"
                f"coalesce(m.canonical_name,t.description_raw) AS merchant,t.description_raw AS description,{ROW_KIND} AS kind,i.position,i.description AS item,"
                f"i.line_total_minor,i.discount_minor,i.category_source AS item_category_source,{SPLIT_CATEGORY} AS category,{SPLIT_SPENT} AS amount_minor,"
                f"t.currency,a.display_name AS account,t.category_source,CASE WHEN {linked} IS NOT NULL THEN 'reconciled' ELSE 'statement' END AS status,"
                f"(SELECT document_id FROM receipts WHERE id={linked}) AS receipt_document_id "
                f"FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN merchants m ON m.id=t.merchant_id {TRANSACTION_SPLITS} "
                f"LEFT JOIN receipt_items i ON i.id=s.receipt_item_id WHERE {COUNTABLE} AND t.transaction_type IN ({SPENDING_TYPES}){charge_scope}")
        params = [*params, *([value.account_id] if value.account_id is not None else [])]
        if value.account_id is None:
            rows += (f" UNION ALL SELECT 'receipt',NULL,r.id,r.purchase_date,coalesce(m.canonical_name,'Unknown merchant'),r.description,{ROW_KIND},i.position,i.description,"
                     f"i.line_total_minor,i.discount_minor,i.category_source,{RECEIPT_SPLIT_CATEGORY},{RECEIPT_SPLIT_SPENT},r.currency,NULL,NULL,'receipt',r.document_id "
                     f"FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id {RECEIPT_SPLITS} LEFT JOIN receipt_items i ON i.id=s.receipt_item_id "
                     f"WHERE {STANDALONE_RECEIPT}{receipt_scope}")
            params += params[:len(dated)]
        clauses, filters = [], []
        if value.category:
            clauses.append("category=?")
            filters.append(" ".join(value.category.split()).lower())
        if value.categories:
            clauses.append(f"category IN ({','.join('?' * len(value.categories))})")
            filters += value.categories
        for token in normalize_name(value.query).split() if value.query else []:
            clauses.append("instr(' '||normalized_name(merchant||' '||coalesce(description,'')||' '||coalesce(item,''))||' ',?)>0")
            filters.append(f" {token} ")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.connection() as db:
            total = db.execute(f"SELECT count(*) FROM ({rows}){where}", [*params, *filters]).fetchone()[0]
            found = [dict(row) for row in db.execute(
                f"SELECT * FROM ({rows}){where} ORDER BY date DESC,source,transaction_id DESC,receipt_id DESC,position IS NULL,position "
                "LIMIT ? OFFSET ?", [*params, *filters, value.limit, value.offset])]
        for row in found:
            row["amount"] = money(row["amount_minor"], row["currency"])
            row["line_total"] = money(row["line_total_minor"], row["currency"]) if row["line_total_minor"] is not None else None
        return {"items": found, "total_matching": total, "offset": value.offset, "limit": value.limit,
                "notes": ["amount is the item's share of what was paid, including its part of tax and receipt-wide discounts; "
                          "rows for one charge or receipt add up to it exactly.",
                          "kind: item (one receipt item), extra (a tip or an amount no item carries) or charge (a whole charge or receipt without items).",
                          RECEIPT_NOTE]}

    def compare_periods(self, value):
        first, second = (self._net_by_currency(period.start, period.end, period.account_id) for period in (value.first, value.second))
        comparisons = []
        for currency in sorted(set(first) | set(second)):
            before, after = first.get(currency, 0), second.get(currency, 0)
            comparisons.append({"currency": currency, "first": money(before, currency), "second": money(after, currency),
                                "change": money(after - before, currency), "percent_change": percent_change(before, after)})
        return {"first": value.first.model_dump(), "second": value.second.model_dump(), "by_currency": comparisons,
                "notes": ["percent_change is null when the first period has no spending."]}

    def compare_categories(self, value):
        """Per-category spending in two periods, with the exact change between them."""
        first, second = (self._category_totals(period.start, period.end, period.account_id) for period in (value.first, value.second))
        rows = []
        for currency, category in sorted(set(first) | set(second), key=lambda key: (key[0], -second.get(key, (0, 0))[0], key[1])):
            before, after = first.get((currency, category), (0, 0))[0], second.get((currency, category), (0, 0))[0]
            rows.append({"currency": currency, "category": category, "first": money(before, currency), "second": money(after, currency),
                         "change": money(after - before, currency), "percent_change": percent_change(before, after)})
        return {"first": value.first.model_dump(), "second": value.second.model_dump(), "categories": rows,
                "notes": ["percent_change is null when the category had no spending in the first period."]}

    def get_budgets(self, value):
        """Each monthly budget against the month's counted category spending, with the pace so far.
        Integer arithmetic only: 'ahead_of_pace' means spent/budget exceeds elapsed days/days in the month."""
        index = month_index(value.month)
        start, end = month_label(index) + "-01", last_day(index)
        today = date.fromisoformat(iso(value.as_of)) if value.as_of else date.today()
        days = int(end[8:])
        elapsed = days if today.isoformat() > end else 0 if today.isoformat() < start else today.day
        spent = self._category_totals(start, end, None)
        # Confirmed recurring bills due this month and not yet paid in it: spending the category will still see.
        due = defaultdict(lambda: [0, []])
        for bill in self.query("SELECT o.*,m.canonical_name AS merchant FROM recurring_obligations o JOIN merchants m ON m.id=o.merchant_id "
                               "WHERE o.status='verified' AND o.next_due_date BETWEEN ? AND ? AND (o.last_paid_date IS NULL OR o.last_paid_date<?)",
                               (start, end, start)):
            key = (bill["currency"], bill["category"] or "bills")
            due[key][0] += bill["expected_amount_minor"]
            due[key][1].append(bill["merchant"])
        rows = []
        for budget in self.ledger.budgets():
            amount, currency = budget["amount_minor"], budget["currency"]
            used, count = spent.get((currency, budget["category"]), (0, 0))
            still_due, payees = due.get((currency, budget["category"]), (0, []))
            if used > amount:
                status = "over"
            elif elapsed == 0:
                status = "not_started"
            elif elapsed == days:
                status = "within"
            else:
                status = "ahead_of_pace" if used * days > amount * elapsed else "on_track"
            rows.append({"id": budget["id"], "category": budget["category"], "currency": currency, "budget": money(amount, currency),
                         "spent": money(used, currency), "remaining": money(amount - used, currency), "transactions": count,
                         "percent_used": str((Decimal(used) * 100 / Decimal(amount)).quantize(Decimal("0.1"), ROUND_HALF_EVEN)), "status": status,
                         "recurring_due": money(still_due, currency), "recurring_payees": payees,
                         "projected": money(used + still_due, currency)})
        budgeted = {(row["currency"], row["category"]) for row in rows}
        unbudgeted = defaultdict(lambda: [0, 0])
        for (currency, category), (total, count) in spent.items():
            if (currency, category) not in budgeted:
                unbudgeted[currency][0] += total
                unbudgeted[currency][1] += count
        return {"month": value.month, "period": {"start": start, "end": end}, "days": days, "elapsed_days": elapsed, "budgets": rows,
                "unbudgeted": [{"currency": currency, "spent": money(total, currency), "transactions": count}
                               for currency, (total, count) in sorted(unbudgeted.items())],
                "notes": ["Spent is the month's counted spending in the category before refunds, the same figure as By category.",
                          "recurring_due is what confirmed recurring bills in the category still expect this month; projected is spent plus that.",
                          "Extracted transactions awaiting review are not counted until verified."]}

    def get_categories(self, _=None):
        """Every category in use by transactions, receipt items, budgets or rules, with its transaction count."""
        rows = self.query("SELECT category,sum(n) AS transactions FROM (SELECT t.category,count(*) AS n FROM transactions t WHERE t.category IS NOT NULL "
                          "GROUP BY 1 UNION ALL SELECT category,0 FROM category_splits WHERE category<>'uncategorized' UNION ALL SELECT category,0 FROM budgets "
                          "UNION ALL SELECT category,0 FROM category_rules) GROUP BY 1 ORDER BY 1")
        return {"categories": rows}

    def calculate_cashflow(self, value):
        scope, params = scope_of(value.start, value.end, value.account_id)
        outflow = {currency: bucket["spending"] - bucket["refunds"] for (_, currency), bucket in self._totals(value.start, value.end, value.account_id).items()}
        inflow = {row["currency"]: row["total"] for row in self.query(
            f"SELECT t.currency,sum(t.amount_minor) AS total FROM transactions t WHERE {COUNTABLE} AND {scope} "
            "AND t.amount_minor>0 AND t.transaction_type IN ('deposit','interest','other') GROUP BY t.currency", params)}
        excluded = self.query(f"SELECT count(*) AS count FROM transactions t WHERE {COUNTABLE} AND {scope} AND t.transaction_type IN ('transfer','payment')", params)[0]["count"]
        result = [{"currency": currency, "inflow": money(inflow.get(currency, 0), currency), "outflow": money(outflow.get(currency, 0), currency),
                   "net": money(inflow.get(currency, 0) - outflow.get(currency, 0), currency)} for currency in sorted(set(inflow) | set(outflow))]
        return {"period": {"start": value.start, "end": value.end}, "by_currency": result,
                "excluded_transfers_and_card_payments": excluded, "coverage": self._coverage(scope, params, value.account_id)}

    # Obligations, bills, receipts and refunds -------------------------------------

    def get_recurring_obligations(self, _=None):
        rows = self.query("SELECT r.*,m.canonical_name AS merchant FROM recurring_obligations r JOIN merchants m ON m.id=r.merchant_id "
                          "WHERE r.status IN ('proposed','verified') ORDER BY r.next_due_date")
        return {"obligations": [{**row, "expected_amount": money(row["expected_amount_minor"], row["currency"])} for row in rows],
                "notes": ["Proposed from a steady cadence of payments, one bill payment, a statement payee the local model read as a service, "
                          "or payment terms in a contract (source_document_id, evidence); each is a proposal until verified."]}

    def get_upcoming_bills(self, value):
        """Confirmed recurring bills by next due date. Each matched payment moves a bill's next due date on,
        so a due date already past means no payment has been found since."""
        until = shift(value.as_of, value.days)
        bills = self.query("SELECT o.id,o.merchant_id,o.account_id,o.category,o.frequency,o.currency,o.expected_amount_minor,o.last_paid_date,"
                           "o.next_due_date AS due_date,m.canonical_name AS provider FROM recurring_obligations o JOIN merchants m ON m.id=o.merchant_id "
                           "WHERE o.status='verified' AND o.next_due_date IS NOT NULL AND o.next_due_date<=? ORDER BY o.next_due_date,m.canonical_name", (until,))
        return {"as_of": value.as_of, "until": until,
                "bills": [{**bill, "amount_due": money(bill["expected_amount_minor"], bill["currency"]),
                           "payment_state": "due" if bill["due_date"] >= value.as_of else "overdue"} for bill in bills],
                "notes": ["Confirmed recurring bills only; proposed ones wait in Review.",
                          "Overdue means no matching payment has been imported since the due date. The amount is the average of the last three payments."]}

    def find_receipt(self, value):
        clauses, params = ["r.review_status<>'rejected'"], []
        for clause, item in (("r.purchase_date>=?", value.start), ("r.purchase_date<=?", value.end)):
            if item:
                clauses.append(clause)
                params.append(item)
        if value.amount is not None:
            if not value.currency:
                raise ValueError("Give the currency with an amount; it is never assumed.")
            clauses.append("r.total_minor=? AND r.currency=?")
            params += [abs(to_minor(value.amount, value.currency)), currency_code(value.currency)]
        rows = self.query("SELECT r.*,m.canonical_name AS merchant,(SELECT l.transaction_id FROM transaction_receipt_links l WHERE l.receipt_id=r.id "
                          "AND l.review_status<>'rejected' LIMIT 1) AS transaction_id FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id WHERE "
                          + " AND ".join(clauses) + " ORDER BY r.purchase_date DESC", params)
        if value.merchant:
            wanted = name_tokens(value.merchant)
            rows = [row for row in rows if row["merchant"] and wanted & name_tokens(row["merchant"])]
        return {"receipts": [{**row, "total": money(row["total_minor"], row["currency"]) if row["total_minor"] is not None else None,
                              "evidence": self.ledger.evidence("receipt", row["id"])} for row in rows[:100]]}

    def find_purchase(self, value):
        return self.get_transactions(value)

    def get_statement(self, value):
        return self.ledger.record("statement", value.record_id)

    def match_receipt_to_transaction(self, value):
        receipt = self.ledger.record("receipt", value.record_id)
        links = self.query("SELECT * FROM transaction_receipt_links WHERE receipt_id=?", (value.record_id,))
        candidates = []
        if receipt["total_minor"] is not None and receipt["purchase_date"]:
            candidates = self.query(f"SELECT t.* FROM transactions t WHERE t.review_status<>'rejected' AND t.currency=? AND t.amount_minor=? "
                                    f"AND coalesce(t.transaction_date,t.posted_date) BETWEEN ? AND ?",
                                    (receipt["currency"], -receipt["total_minor"], receipt["purchase_date"], shift(receipt["purchase_date"], RECEIPT_POSTING_DAYS)))
        return {"receipt_id": value.record_id, "links": links,
                "candidates": [{**row, "amount": money(row["amount_minor"], row["currency"]),
                                "merchant_overlap": bool(receipt.get("merchant") and name_tokens(receipt["merchant"]) & name_tokens(row["description_raw"]))}
                               for row in candidates]}

    def get_refunds(self, _=None):
        credits = self.query("SELECT t.*,l.id AS link_id,l.from_transaction_id AS purchase_id,l.review_status AS link_status FROM transactions t "
                             "LEFT JOIN transaction_links l ON l.link_type='refund' AND l.to_transaction_id=t.id AND l.review_status<>'rejected' "
                             f"WHERE t.transaction_type='refund' AND {COUNTABLE} ORDER BY t.posted_date DESC")
        evidence = self.query("SELECT r.*,m.canonical_name AS merchant,(SELECT l.transaction_id FROM transaction_receipt_links l WHERE l.receipt_id=r.id "
                              "AND l.review_status<>'rejected' LIMIT 1) AS credit_transaction_id FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id "
                              "WHERE r.total_minor<0 AND r.review_status<>'rejected'")
        return {"posted_credits": [{**row, "amount": money(row["amount_minor"], row["currency"])} for row in credits],
                "refund_evidence": [{**row, "amount": money(-row["total_minor"], row["currency"]),
                                     "settlement": "posted_credit_found" if row["credit_transaction_id"] else "evidence_only_not_settled"} for row in evidence],
                "notes": ["Refund documents do not count as settled until a matching posted credit is linked."]}

    def get_unmatched_receipts(self, value):
        """Receipts in the period that no card or bank transaction matches yet. Approved ones count as spending
        on their own (from_receipts) until a matching line replaces them."""
        with self.connection() as db:
            dated = db.execute(f"SELECT r.id,(SELECT i.id FROM reconciliation_issues i WHERE i.issue_type='ambiguous_receipt_match' AND i.record_type='receipt' "
                               f"AND i.record_id=r.id AND i.status='open') AS issue_id FROM receipts r WHERE {UNLINKED_RECEIPT} "
                               "AND r.purchase_date BETWEEN ? AND ? ORDER BY r.purchase_date DESC,r.id", (value.start, value.end)).fetchall()
            undated = [row[0] for row in db.execute(f"SELECT r.id FROM receipts r WHERE {UNLINKED_RECEIPT} AND r.purchase_date IS NULL ORDER BY r.id")]
            totals = db.execute(f"SELECT r.currency,sum(r.total_minor) AS total,count(*) AS count FROM receipts r WHERE {UNLINKED_RECEIPT} "
                                "AND r.purchase_date BETWEEN ? AND ? AND r.total_minor IS NOT NULL GROUP BY r.currency ORDER BY r.currency",
                                (value.start, value.end)).fetchall()
            summaries = self.ledger.summaries(db, "receipt", [row["id"] for row in dated] + undated)
        return {"period": {"start": value.start, "end": value.end},
                "receipts": [{**summaries[row["id"]], "issue_id": row["issue_id"],
                              "reason": "several_possible_charges" if row["issue_id"] else "no_matching_charge"} for row in dated],
                "undated": [summaries[receipt_id] for receipt_id in undated],
                "by_currency": [{"currency": row["currency"], "total": money(row["total"], row["currency"]), "receipts": row["count"]} for row in totals],
                "notes": ["Approved unmatched receipts count as spending on their own; when a card or bank line matches one, the line counts instead.",
                          "Receipts without a purchase date cannot be placed in a period and are listed separately."]}

    # Review queue -------------------------------------------------------------------

    def get_inventory(self, value):
        """Household items from approved receipt lines: in stock unless closed ones are asked for."""
        lots = ItemLedger(self.store).inventory(value.query, value.include_closed, 100)
        return {"items": [{"lot_id": lot["id"], "product": lot["name"], "brand": lot["brand"], "size": lot["size_text"], "category": lot["category"],
                           "status": lot["status"], "bought_on": lot["bought_on"], "closed_on": lot["closed_on"], "units": lot["units"]} for lot in lots],
                "notes": ["Only items from receipt lines the user approved are listed."]}

    def review_queue(self, _=None):
        """Everything awaiting a decision, each item carrying display summaries of the records involved."""
        with self.connection() as db:
            records = []
            for record_type, table, label in (("statement", "statements", "period_end"), ("receipt", "receipts", "purchase_date"),
                                              ("bill", "bills", "due_date"), ("income_record", "income_records", "pay_date")):
                rows = db.execute(f"SELECT id,review_status,validation_json,{label} AS date,currency FROM {table} WHERE review_status IN ('proposed','needs_review') ORDER BY id").fetchall()
                summaries = self.ledger.summaries(db, record_type, [row["id"] for row in rows])
                records += [{"record_type": record_type, "id": row["id"], "review_status": row["review_status"], "date": row["date"],
                             "issues": json.loads(row["validation_json"]), "summary": summaries.get(row["id"])} for row in rows]
            links = [dict(row) for row in db.execute(
                "SELECT 'receipt' AS kind,l.id,l.match_score,l.match_method,l.transaction_id AS from_id,l.receipt_id AS to_id FROM transaction_receipt_links l "
                "WHERE l.review_status='proposed' UNION ALL SELECT l.link_type,l.id,l.match_score,l.match_method,l.from_transaction_id,l.to_transaction_id "
                "FROM transaction_links l WHERE l.review_status='proposed'")]
            issues = [{**dict(row), "detail": json.loads(row["detail_json"])} for row in db.execute("SELECT * FROM reconciliation_issues WHERE status='open' ORDER BY id")]
            # One batched lookup per record type for everything the links and issues mention.
            wanted = {"transaction": [link["from_id"] for link in links] + [link["to_id"] for link in links if link["kind"] != "receipt"]
                      + [candidate for issue in issues for candidate in issue["detail"]["candidate_transaction_ids"]]
                      + [issue["record_id"] for issue in issues if issue["record_type"] == "transaction"],
                      "receipt": [link["to_id"] for link in links if link["kind"] == "receipt"]
                      + [issue["record_id"] for issue in issues if issue["record_type"] == "receipt"]}
            summaries = {kind: self.ledger.summaries(db, kind, ids) for kind, ids in wanted.items()}
        for link in links:
            link["match_signals"] = link["match_method"].split("+")
            link["from"] = summaries["transaction"].get(link["from_id"])
            link["to"] = summaries["receipt" if link["kind"] == "receipt" else "transaction"].get(link["to_id"])
        for issue in issues:
            del issue["detail_json"]
            issue["record"] = summaries.get(issue["record_type"], {}).get(issue["record_id"])
            issue["candidates"] = [summaries["transaction"][candidate] for candidate in issue["detail"]["candidate_transaction_ids"] if candidate in summaries["transaction"]]
        return {"records": records, "links": links, "issues": issues}


# Typed registry: tool name -> (input model, method name). Tools only read the ledger.
TOOLS = {"get_accounts": (EmptyInput, "get_accounts"), "get_account_balance": (AccountInput, "get_account_balance"),
         "get_transactions": (TransactionsInput, "get_transactions"), "get_spending": (PeriodInput, "get_spending"),
         "spending_series": (SeriesInput, "spending_series"),
         "get_spending_by_category": (PeriodInput, "get_spending_by_category"), "get_spending_items": (SpendingItemsInput, "get_spending_items"),
         "compare_periods": (CompareInput, "compare_periods"),
         "compare_categories": (CompareInput, "compare_categories"),
         "calculate_cashflow": (PeriodInput, "calculate_cashflow"), "get_recurring_obligations": (EmptyInput, "get_recurring_obligations"),
         "get_upcoming_bills": (AsOfInput, "get_upcoming_bills"), "find_receipt": (ReceiptSearchInput, "find_receipt"),
         "get_unmatched_receipts": (PeriodInput, "get_unmatched_receipts"),
         "find_purchase": (TransactionsInput, "find_purchase"), "get_statement": (RecordInput, "get_statement"),
         "match_receipt_to_transaction": (RecordInput, "match_receipt_to_transaction"), "get_refunds": (EmptyInput, "get_refunds"),
         "review_queue": (EmptyInput, "review_queue"), "get_inventory": (InventoryInput, "get_inventory"),
         "get_budgets": (BudgetInput, "get_budgets"), "get_categories": (EmptyInput, "get_categories"), **ITEM_TOOLS, **ANOMALY_TOOLS}
ToolName = Literal[*TOOLS]
# Assistant routing (docs/items-assets-search.md §4): item questions see the item tools and spending basics;
# every other question sees the finance tools. A smaller list keeps a small model's prompt short.
ITEM_ROUTE = frozenset({*ITEM_TOOLS, "get_inventory", "get_spending", "get_spending_by_category", "get_transactions", "find_receipt"})
FINANCE_ROUTE = frozenset(name for name in TOOLS if name not in ITEM_TOOLS)


def call_tool(tools, name, arguments):
    model, method = TOOLS[name]
    return getattr(tools, method)(model.model_validate(arguments or {}))
