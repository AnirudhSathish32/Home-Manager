"""Ledger health: rules the money data must keep, checked over the whole database.

The code keeps these rules as it writes, but several are not enforced by the schema, and split totals, counting and
tax lots are derived rather than stored. check_ledger() recomputes each one and reports every record that breaks it.
A problem names the rule and the record by id only, never amounts, names or document text, so a report can be shared.

Severities: error (money is counted wrongly or a rule the code enforces was broken), warning (probably wrong; worth a
look), info (expected while records are incomplete, such as shares bought before the first statement).
"""

from collections import Counter
from typing import NamedTuple

from ..core.money import EXPONENTS
from .ledger import COUNTABLE, STANDALONE_RECEIPT, charge_share
from .tax_lots import account_lots, shares

SEVERITIES = ("error", "warning", "info")
RULES = {
    "split_receipt_sum": ("error", "A receipt's category shares do not add up to its total (or to this person's share of it)."),
    "split_charge_sum": ("error", "A charge's category shares do not add up to what it charged (or to this person's share of it)."),
    "split_missing": ("warning", "An itemized receipt, or a charge matched to one, has no category shares; open it and save its items again."),
    "split_stale": ("warning", "Category shares remain for a charge no longer matched to that receipt."),
    "link_multi_receipt": ("error", "A charge is matched to more than one receipt."),
    "link_multi_charge": ("warning", "A receipt is matched to more than one charge; each charge counts in full."),
    "link_currency": ("error", "A receipt is matched to a charge in another currency without the user choosing it (only a foreign receipt "
                               "and the USD card charge that paid it may be, once the user picks it)."),
    "link_amount": ("warning", "A proposed match joins a receipt and a charge of different amounts."),
    "receipt_uncounted": ("warning", "A verified receipt is matched only to charges that do not count yet, so its money is counted nowhere."),
    "currency_unknown": ("error", "A record uses a currency Home Manager does not support."),
    "statement_balance": ("warning", "A statement's opening balance plus its lines does not reach its closing balance; lines may be missing or misread."),
    "share_total": ("error", "A shared record's share was recorded against a different total, or is larger than the total."),
    "income_link_multi": ("error", "A deposit is matched to more than one pay stub, so their net pay is counted once for several."),
    "income_link_amount": ("warning", "A proposed match joins a pay stub and a deposit of different amounts."),
    "lots_uncovered": ("info", "Shares were sold that no recorded lot covers."),
    "lots_vs_holding": ("info", "A holding's open lots do not add up to the shares its latest statement shows."),
    "orphan_share": ("error", "A family share or assignment names a record that no longer exists; the next record given that id would inherit it."),
    "orphan_reference": ("warning", "Evidence, a correction, a review note or an open question names a record that no longer exists."),
}
# Tables that name a record by (record_type, record_id) instead of a foreign key, and the records they can name.
TYPED_ID_TABLES = {"record_shares": "orphan_share", "family_assignments": "orphan_share", "financial_evidence_links": "orphan_reference",
                   "record_corrections": "orphan_reference", "review_events": "orphan_reference", "reconciliation_issues": "orphan_reference"}
RECORD_TABLES = {"receipt": "receipts", "statement": "statements", "income_record": "income_records",
                 "transaction": "transactions", "receipt_item": "receipt_items"}


class Problem(NamedTuple):
    code: str
    severity: str
    record_type: str
    record_id: int | str
    detail: str


def problem(code, record_type, record_id):
    severity, detail = RULES[code]
    return Problem(code, severity, record_type, record_id, detail)


def check_ledger(db) -> list[Problem]:
    """Every rule over the whole database. db: an open connection with sqlite3.Row rows; nothing is written."""
    found: list[Problem] = []
    for check in (split_sums, split_coverage, links, income_links, uncounted_receipts, currencies, statement_balances, record_shares, lots, orphans):
        found += check(db)
    return sorted(found, key=lambda item: (SEVERITIES.index(item.severity), item.code, str(item.record_id)))


# Record type -> (SQL giving the record's link value, link key). A problem reported by a table name (orphans, unknown
# currencies) has no record to open.
LINKS = {
    "receipt": ("SELECT document_id FROM receipts WHERE id=?", "document_id"),
    "statement": ("SELECT document_id FROM statements WHERE id=?", "document_id"),
    "income_record": ("SELECT document_id FROM income_records WHERE id=?", "document_id"),
    "transaction": ("SELECT coalesce(t.source_document_id, s.document_id) FROM transactions t LEFT JOIN statements s ON s.id=t.statement_id "
                    "WHERE t.id=?", "document_id"),
    "holding": ("SELECT account_id FROM holdings WHERE id=?", "investment_account_id"),
    "investment_event": ("SELECT account_id FROM investment_events WHERE id=?", "investment_account_id"),
}


def record_links(db, problems):
    """Each problem as a dict with `link`: where the user opens the record to fix it ({document_id} or
    {investment_account_id}), or None when there is no such page (docs/operations.md "Ledger health")."""
    linked = []
    for item in problems:
        link = None
        if item.record_type in LINKS:
            sql, key = LINKS[item.record_type]
            row = db.execute(sql, (item.record_id,)).fetchone()
            if row and row[0] is not None:
                link = {key: row[0]}
        linked.append({**item._asdict(), "link": link})
    return linked


def summary(problems):
    """{"error": n, "warning": n, "info": n, "by_rule": {code: n}}."""
    severities = Counter(item.severity for item in problems)
    return {**{severity: severities[severity] for severity in SEVERITIES}, "by_rule": dict(Counter(item.code for item in problems))}


def split_sums(db):
    """Rows for a receipt add up to its total; rows for a charge add up to what it charged (ledger.refresh_splits)."""
    found = []
    shared = "LEFT JOIN record_shares h ON h.record_type='receipt' AND h.record_id=s.receipt_id"
    for row in db.execute(f"SELECT s.receipt_id,sum(s.amount_minor) AS allocated,r.total_minor AS target,h.share_minor,h.total_minor AS shared_total "
                          f"FROM category_splits s JOIN receipts r ON r.id=s.receipt_id {shared} WHERE s.transaction_id IS NULL GROUP BY s.receipt_id"):
        if row["allocated"] != expected(row["target"], row):
            found.append(problem("split_receipt_sum", "receipt", row["receipt_id"]))
    for row in db.execute(f"SELECT s.receipt_id,s.transaction_id,sum(s.amount_minor) AS allocated,-t.amount_minor AS target,h.share_minor,h.total_minor AS shared_total "
                          f"FROM category_splits s JOIN transactions t ON t.id=s.transaction_id {shared} WHERE s.transaction_id IS NOT NULL "
                          f"GROUP BY s.receipt_id,s.transaction_id"):
        if row["allocated"] != expected(row["target"], row):
            found.append(problem("split_charge_sum", "transaction", row["transaction_id"]))
    return found


def expected(target, row):
    if target is None:
        return None  # Shares with no total to divide are always wrong.
    if row["share_minor"] is None or not target:
        return target
    return charge_share(target, row["share_minor"], row["shared_total"])


def split_coverage(db):
    """Split rows exist exactly where ledger.refresh_splits writes them."""
    items = "EXISTS(SELECT 1 FROM receipt_items i WHERE i.receipt_id=r.id AND i.review_status<>'rejected')"
    found = [problem("split_missing", "receipt", row[0]) for row in db.execute(
        f"SELECT r.id FROM receipts r WHERE r.total_minor IS NOT NULL AND {items} "
        "AND NOT EXISTS(SELECT 1 FROM category_splits s WHERE s.receipt_id=r.id AND s.transaction_id IS NULL)")]
    found += [problem("split_missing", "transaction", row[0]) for row in db.execute(
        f"SELECT l.transaction_id FROM transaction_receipt_links l JOIN receipts r ON r.id=l.receipt_id WHERE l.review_status<>'rejected' "
        f"AND r.total_minor IS NOT NULL AND {items} "
        "AND NOT EXISTS(SELECT 1 FROM category_splits s WHERE s.receipt_id=r.id AND s.transaction_id=l.transaction_id)")]
    found += [problem("split_stale", "transaction", row[0]) for row in db.execute(
        "SELECT DISTINCT s.transaction_id FROM category_splits s WHERE s.transaction_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l "
        "WHERE l.receipt_id=s.receipt_id AND l.transaction_id=s.transaction_id AND l.review_status<>'rejected')")]
    return found


def links(db):
    live = "l.review_status<>'rejected'"
    found = [problem("link_multi_receipt", "transaction", row[0]) for row in db.execute(
        f"SELECT l.transaction_id FROM transaction_receipt_links l WHERE {live} GROUP BY l.transaction_id HAVING count(DISTINCT l.receipt_id)>1")]
    found += [problem("link_multi_charge", "receipt", row[0]) for row in db.execute(
        f"SELECT l.receipt_id FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id "
        f"WHERE {live} AND t.review_status<>'rejected' GROUP BY l.receipt_id HAVING count(DISTINCT l.transaction_id)>1")]
    found += [problem("link_currency", "receipt", row[0]) for row in db.execute(
        f"SELECT DISTINCT l.receipt_id FROM transaction_receipt_links l JOIN receipts r ON r.id=l.receipt_id JOIN transactions t ON t.id=l.transaction_id "
        f"WHERE {live} AND r.currency<>t.currency AND NOT (l.review_status='verified' AND t.currency='USD')")]
    # A match the user verified may differ on purpose (a tip added after printing); a proposed one should not. A bill may
    # be paid by its amount due, past-due balance included (docs/money.md "Bills and their lines").
    found += [problem("link_amount", "receipt", row[0]) for row in db.execute(
        "SELECT DISTINCT l.receipt_id FROM transaction_receipt_links l JOIN receipts r ON r.id=l.receipt_id JOIN transactions t ON t.id=l.transaction_id "
        "WHERE l.review_status='proposed' AND r.total_minor IS NOT NULL AND r.total_minor<>-t.amount_minor "
        "AND NOT (r.document_kind='bill' AND r.amount_due_minor=-t.amount_minor)")]
    return found


def income_links(db):
    """A deposit pays one pay stub, and a proposed match is for exactly its net pay (reconcile.income)."""
    live = "l.review_status<>'rejected'"
    found = [problem("income_link_multi", "transaction", row[0]) for row in db.execute(
        f"SELECT l.transaction_id FROM transaction_income_links l WHERE {live} GROUP BY l.transaction_id HAVING count(DISTINCT l.income_record_id)>1")]
    found += [problem("income_link_amount", "income_record", row[0]) for row in db.execute(
        "SELECT DISTINCT l.income_record_id FROM transaction_income_links l JOIN income_records i ON i.id=l.income_record_id "
        "JOIN transactions t ON t.id=l.transaction_id WHERE l.review_status='proposed' AND i.net_pay_minor<>t.amount_minor")]
    return found


def uncounted_receipts(db):
    """A verified receipt (a sale or a return) stops counting once matched, so its charge or credit must count instead
    (ledger.STANDALONE_RECEIPT, COUNTABLE)."""
    return [problem("receipt_uncounted", "receipt", row[0]) for row in db.execute(
        f"SELECT r.id FROM receipts r WHERE r.review_status='verified' AND r.total_minor<>0 AND r.purchase_date IS NOT NULL AND NOT ({STANDALONE_RECEIPT}) "
        f"AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l JOIN transactions t ON t.id=l.transaction_id "
        f"WHERE l.receipt_id=r.id AND l.review_status<>'rejected' AND {COUNTABLE})")]


def currencies(db):
    """Every currency column holds a supported code (core.money.EXPONENTS)."""
    found = []
    supported = ",".join("?" * len(EXPONENTS))
    for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        if not any(column[1] == "currency" for column in db.execute(f'PRAGMA table_info("{table}")')):
            continue
        found += [problem("currency_unknown", table, row[0]) for row in db.execute(
            f'SELECT rowid FROM "{table}" WHERE currency IS NOT NULL AND currency NOT IN ({supported})', tuple(EXPONENTS))]
    return found


def statement_balances(db):
    """Opening balance plus the statement's lines reaches its closing balance. Issuers print balances with either sign
    convention (a card balance owed is positive), so either direction passes."""
    found = []
    for row in db.execute("SELECT s.id,s.opening_balance_minor AS opening,s.closing_balance_minor AS closing,sum(t.amount_minor) AS moved "
                          "FROM statements s JOIN transactions t ON t.statement_id=s.id AND t.review_status<>'rejected' "
                          "WHERE s.review_status<>'rejected' AND s.opening_balance_minor IS NOT NULL AND s.closing_balance_minor IS NOT NULL GROUP BY s.id"):
        if row["closing"] not in (row["opening"] + row["moved"], row["opening"] - row["moved"]):
            found.append(problem("statement_balance", "statement", row["id"]))
    return found


def record_shares(db):
    """A person's part of a shared receipt or bill was recorded against that record's total, and is no larger than it."""
    return [problem("share_total", "receipt", row[0]) for row in db.execute(
        "SELECT h.record_id FROM record_shares h JOIN receipts x ON x.id=h.record_id WHERE h.record_type='receipt' "
        "AND (x.total_minor IS NULL OR x.total_minor<>h.total_minor OR abs(h.share_minor)>abs(h.total_minor) OR h.share_minor*h.total_minor<0)")]


def orphans(db):
    """Typed-ID rows name a record that exists. Ids are reused once deleted, so an orphan can attach itself to a new record.
    Reported by the orphan's own table and rowid; review_events also notes records of other kinds, which are not checked."""
    found = []
    for table, code in TYPED_ID_TABLES.items():
        for kind, records in RECORD_TABLES.items():
            if table == "record_corrections" and kind == "receipt_item":
                records = "receipts"  # Item price overrides use receipt id plus printed position.
            found += [problem(code, table, row[0]) for row in db.execute(
                f"SELECT rowid FROM {table} WHERE record_type=? AND record_id NOT IN (SELECT id FROM {records})", (kind,))]
    return found


def lots(db):
    """Sales each have lots to cover them, and open lots match the latest statement's share count (finance/tax_lots.py)."""
    found = []
    for (account_id,) in db.execute("SELECT id FROM investment_accounts WHERE archived_at IS NULL ORDER BY id").fetchall():
        for holding_id, result in account_lots(db, account_id).items():
            found += [problem("lots_uncovered", "investment_event", gap["sell_event_id"]) for gap in result["missing"]]
            latest = db.execute("SELECT quantity FROM investment_valuations WHERE holding_id=? AND review_status='verified' AND quantity IS NOT NULL "
                                "ORDER BY as_of DESC LIMIT 1", (holding_id,)).fetchone()
            held = shares(latest[0]) if latest else None  # None: no share count shown (or none held).
            if held is not None and held != shares(result["open_shares"]):
                found.append(problem("lots_vs_holding", "holding", holding_id))
    return found
