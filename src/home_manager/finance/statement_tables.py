"""Bank and card statements from the table engine's tables (specs/pdf-table-engine FR-09 – FR-17, plan P7 – P9).

`documents/table_engine.py` finds tables, columns and rows by alignment and knows no money. This module decides what the columns mean
and what the rows are: which column is the running balance, money in, money out or one signed amount (by the balance chain, the printed
summary, or at last the heading words and the statement type), the statement period, the date order and year, schedules and pending
rows, the notes and review issues, and the rows in the shape `ExtractionService.normalize` reads. It is pure and deterministic: no
model, no network, and no store except in `prior_order`, which reads saved statements through the connection it is given. Money is
exact: printed `Decimal`s go through `core/money.to_minor` and are compared in integer minor units; a float never decides a role or sign.

Roles are found by enumeration: every assignment of balance, signed, in, out or other to the amount columns is evaluated, and the
tiers of plan P7 keep the strongest evidence that holds (chain, summary, most chain links, headings, type default). Where candidates in
the strongest tier still differ on any row's signed amount, the roles are undecided and nothing is guessed.
"""

import copy
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from itertools import product
import json
import logging
import re
from types import SimpleNamespace

from ..core.logs import log_failure
from ..core.money import SYMBOLS, MoneyError, to_minor
from ..documents import table_engine
from ..documents.pdf_reader import PDF_VERSIONS, read_result
from ..documents.table_engine import EngineTable, Unplaced
from .statement_dates import NO_LAYOUT_NOTE, PERIOD_SLACK, Rebuild, duplicates, placed, read_period

log = logging.getLogger(__name__)

DATE_ORDERS = ("MM/DD/YYYY", "DD/MM/YYYY")
ROLES = ("balance", "signed", "in", "out", "other")  # The fixed enumeration order (plan P7.1).
MAX_COLUMNS = 6
OUT_DEFAULT, IN_DEFAULT = "positive_is_outflow", "negative_is_outflow"  # The statement type's default sign (statement-accounts FR-18).
PRIOR_STATEMENTS = 10

CHAIN_BREAK = "Page {page} row {row}: the balance {balance} doesn't follow from the row above"
UNPLACED = 'Page {page}: a printed line wasn\'t placed in any column, so it wasn\'t recorded: "{text}"'
PENDING = 'Page {page}: a pending row isn\'t recorded until it posts: "{text}"'
TWO_ACCOUNTS = ("This PDF may hold more than one account: the table on page {first} and the table on page {second} don't continue each "
                "other's balances. Both tables' rows were recorded.")
CARRIED = "Page {page} row {row}: no date is printed; it takes {date} from the row above"
NO_TABLE = "Page {page}: no table was found in the printed columns, so its rows are the reading's; check them."
ORDER_UNKNOWN = "Page {page} rows: the date order (month/day or day/month) can't be told from the printed dates."
TOO_FEW = ("Page {page}: the signs of these rows come from the column headings or the statement type, because there are too few rows and "
           "no printed summary to check them.")
ROLES_UNKNOWN = "Page {page}: which amount columns are money in, money out or the balance can't be told, so its rows weren't recorded."
ROLES_DIFFER = ("Page {page}: more than one reading of the amount columns fits the printed balances, so the signs of these rows are "
                "taken from the column headings or the statement type; check them.")
BOTH = "Both a debit and a credit are printed."
MORE_THAN_ONE_ROW = "More than one amount is printed for this row."

CODE = re.compile(r"\b[A-Z]{3}\b")  # A printed currency code (CR and DR are two letters).
PENDING_TITLE = re.compile(r"pending", re.IGNORECASE)
IN_TITLE = re.compile(r"payment|credit|refund|return|deposit|addition", re.IGNORECASE)
OUT_TITLE = re.compile(r"purchase|charge|fee|interest|advance|withdrawal|debit", re.IGNORECASE)
OUT_LABEL = re.compile(r"withdraw|debit|paid out|subtraction|money out", re.IGNORECASE)
IN_LABEL = re.compile(r"deposit|credit|paid in|addition|money in", re.IGNORECASE)
OTHER_LABEL = re.compile(r"\bforeign\b|\brate\b|\bexchange\b|\bfx\b", re.IGNORECASE)
LEAVES_THE_AMOUNT = (table_engine.JOINED_AMOUNT, table_engine.MORE_THAN_ONE.split("{")[0], table_engine.TEXT_IN_AMOUNT.split("{")[0])


# --- Results -----------------------------------------------------------------------------------------------------------------

@dataclass
class StatementReading:
    """What a statement's printed columns give (plan P2). `rows` are in the shape `ExtractionService.normalize` reads; `tables` are the
    engine's tables as this layer classed them (a schedule is its own table of kind `schedule`; pending rows are in `unplaced`)."""
    rows: list[dict] = field(default_factory=list)  # {posted_date, transaction_date, description, currency, amount_minor, locator}
    issues: list[str] = field(default_factory=list)  # Review reasons.
    notes: list[str] = field(default_factory=list)  # Record notes, not review reasons.
    dropped: int = 0  # Rejected rows, unplaced and pending lines, rows whose date order or roles couldn't be told.
    pages: set[int] = field(default_factory=set)  # Pages holding a transactions table's rows (recorded or not): the pages Record gives the engine's rows.
    opening_minor: int | None = None  # The printed opening (previous) balance: the first such anchor in reading order.
    closing_minor: int | None = None  # The printed closing (new) balance: the last such anchor.
    period: tuple[str, str] | None = None  # The printed period as ISO dates (the caller's fallback period is not reported here).
    order: str | None = None  # MM/DD/YYYY or DD/MM/YYYY, however decided; None when no date needs it or it can't be told.
    decided: dict = field(default_factory=dict)  # {order, year, signs}: how each was decided (None: not decided); signs per table id.
    roles: dict = field(default_factory=dict)  # table id -> column id -> balance, signed, in, out or other.
    available: bool = True  # False: a page has no saved layout (statement-accounts FR-23); `notes` holds NO_LAYOUT_NOTE.
    tables: list[EngineTable] = field(default_factory=list)
    unplaced: list[Unplaced] = field(default_factory=list)  # reason no_column (engine) or pending (R4).
    summary_anchors: list = field(default_factory=list)

    def as_rebuild(self) -> Rebuild:
        return Rebuild(self.available, self.pages, self.rows, self.issues, self.notes, self.dropped, self.opening_minor, self.closing_minor, self.period)


# --- Small helpers -----------------------------------------------------------------------------------------------------------

def minor_of(value, currency):
    """An exact printed `Decimal` magnitude in minor units, or None when it has more precision than the currency allows."""
    try:
        return to_minor(f"{abs(value):f}", currency)
    except MoneyError:
        return None


def signed_minor(value, currency):
    minor = minor_of(value, currency)
    return None if minor is None else -minor if value < 0 else minor


def shape_of(token):
    """A date token as `statement_dates.placed` takes it: (kind, first, second, four-digit year, two-digit year)."""
    first, second, year, form = token.value
    full = year if year is not None and year > 99 else None
    short = year if year is not None and year <= 99 else None
    return ("slash", first, second, full, short) if form == "slash" else ("iso", second, first, full, short)


def label_role(labels):
    """What a column's heading words say it is: balance, out, in, signed (`amount`), other (foreign amounts and rates), else None."""
    text = " ".join(labels).lower()
    if not text:
        return None
    if OTHER_LABEL.search(text):
        return "other"
    if "balance" in text:
        return "balance"
    out, money_in = OUT_LABEL.search(text), IN_LABEL.search(text)
    if out and not money_in:
        return "out"
    if money_in and not out:
        return "in"
    return None if out or money_in else "signed" if "amount" in text else None


def title_direction(title):
    """A section title's direction for FR-12: in (payments, credits, refunds), out (purchases, charges, fees, interest, advances), else None."""
    if not title:
        return None
    money_in, out = IN_TITLE.search(title), OUT_TITLE.search(title)
    return "in" if money_in and not out else "out" if out and not money_in else None


def convention_sign(convention, marker, magnitude):
    """A signed amount under a convention. CR and DR are explicit. Otherwise a minus (or parentheses, or a trailing minus) flips the
    convention's reading of an unmarked amount: bank (negative is money out) reads an unmarked positive as in and a minus as out; card
    (positive is money out) reads an unmarked positive as out and a minus as in (statement-accounts FR-18, as the old reader did)."""
    if marker == "credit":
        return magnitude
    if marker == "debit":
        return -magnitude
    return magnitude if (convention == IN_DEFAULT) != (marker == "minus") else -magnitude


def money_text(row_cells, positions):
    return next((row_cells[position].printed for position in positions if position in row_cells), "")


# --- One transactions table's roles (plan P7) --------------------------------------------------------------------------------

@dataclass
class Cell:
    token: object
    magnitude: Decimal | None  # None: unreadable.
    marker: str | None
    code: str | None
    minor: int | None  # The magnitude in minor units; None: unreadable, or more precision than the currency allows.

    @property
    def printed(self):
        return self.token.text


@dataclass
class Candidate:
    """One role assignment (and, for a signed column, one way of reading its signs) evaluated over a table's rows."""
    roles: tuple
    mode: str | None
    order: int  # Enumeration position (the tie-break that never changes money).
    kinds: list = field(default_factory=list)  # Per row: row, anchor, or neutral (a dated line with no amount).
    amounts: list = field(default_factory=list)  # Per row: the signed minor amount of an accepted row, else None.
    reasons: list = field(default_factory=list)  # Per row: why it is rejected, else None.
    balances: list = field(default_factory=list)  # Per row: the printed running balance in minor units, else None.
    unresolved: bool = False  # A row's sign couldn't be read: no marker, no section and no default.
    links: int = 0
    holds: int = 0
    first_break: tuple | None = None  # (row index, printed balance in minor units or None)
    implied_open: int | None = None
    implied_close: int | None = None
    printed: bool = False  # The summary's opening and closing are printed and the statement has one transactions table.
    summary_holds: bool = False
    others: int = 0
    conflicts: int = 0
    labelled: bool = False
    unsupported: bool = False  # A balance column nothing supports: no holding chain link and no heading that says balance (FX's foreign amount).

    @property
    def accepted(self):
        return [index for index, amount in enumerate(self.amounts) if amount is not None]

    @property
    def chain_decided(self):
        return self.links >= 2 and self.holds == self.links

    @property
    def usable(self):
        return not self.unresolved and bool(self.accepted)


class Sheet:
    """A transactions table's cells, and the evaluation of one role assignment over them."""

    def __init__(self, reader, table):
        self.reader, self.table = reader, table
        self.rows = list(table.rows)
        self.columns = [column for column in table.columns if column.kind == "amount"]
        index = {column.id: position for position, column in enumerate(self.columns)}
        self.index = index
        self.cells = [{index[column_id]: self.cell(token) for column_id, token in row.amounts.items() if column_id in index} for row in self.rows]
        self.labels = [label_role(column.labels) for column in self.columns]
        self.direction = {}  # id(row) -> in, out or None: its section's direction. A title that says neither (a page heading) does not end the one before it.
        current, last = None, None
        for row in self.rows:
            if row.section != last:
                current, last = title_direction(row.section) or current, row.section
            self.direction[id(row)] = current
        self.anchor_of = {}  # Row position -> the table's anchor for that balance line.
        for position, row in enumerate(self.rows):
            if row.candidate and row.line_ids:
                self.anchor_of[position] = next((anchor for anchor in table.anchors if anchor.line_id == row.line_ids[0]), None)

    def cell(self, token):
        magnitude, marker, code = token.value
        return Cell(token, magnitude, marker, code, None if magnitude is None else minor_of(magnitude, self.reader.currency))

    def problem(self, cell):
        """Why a cell in a money column can't be read (plan P3): unreadable, more precision than the currency allows, another currency."""
        if cell.magnitude is None or cell.minor is None:
            return table_engine.CANT_READ.format(text=cell.printed)
        reader = self.reader
        if reader.currency_given:
            symbol = next((char for char in cell.printed if char in SYMBOLS), None)
            printed = CODE.search(cell.printed)
            if (printed and printed.group() != reader.currency) or (symbol and reader.currency not in SYMBOLS[symbol]):
                return table_engine.NOT_IN_CURRENCY.format(text=cell.printed, currency=reader.currency)
        return None

    def signed(self, cell, row, mode, default):
        """A signed-column cell's signed amount in minor units, or None when its sign can't be read (FR-12)."""
        if mode == "bank":
            return convention_sign(IN_DEFAULT, cell.marker, cell.minor)
        if mode == "card":
            return convention_sign(OUT_DEFAULT, cell.marker, cell.minor)
        if cell.marker == "credit":
            return cell.minor
        if cell.marker == "debit":
            return -cell.minor
        if cell.marker != "minus":  # A minus is read against the default; any other amount may take its section's direction.
            direction = self.direction.get(id(row))
            if direction:
                return cell.minor if direction == "in" else -cell.minor
        return None if default is None else convention_sign(default, cell.marker, cell.minor)

    def evaluate(self, roles, mode, default, order):
        rows = self.rows
        found = Candidate(roles, mode, order, ["row"] * len(rows), [None] * len(rows), [None] * len(rows), [None] * len(rows))
        balance_at = roles.index("balance") if "balance" in roles else None
        money = [(position, role) for position, role in enumerate(roles) if role in ("in", "out", "signed")]
        clashes = 0
        chain = [None] * len(rows)  # What a row adds to the chain: its signed amount, "break" (it cannot be read), or None (not a transaction).
        for index, row in enumerate(rows):
            cells = self.cells[index]
            if row.candidate and balance_at is not None and set(cells) == {balance_at}:
                found.kinds[index] = "anchor"
                continue
            if row.reject == table_engine.NO_AMOUNT:
                found.kinds[index], found.reasons[index] = "neutral", row.reject
                continue
            if row.reject and row.reject.startswith(LEAVES_THE_AMOUNT):
                found.reasons[index], chain[index] = row.reject, "break"
                continue
            present = [(position, role) for position, role in money if position in cells]
            problems = [self.problem(cells[position]) for position, _ in present]
            if balance_at in cells:
                problems.append(self.problem(cells[balance_at]))
            problem = next((text for text in problems if text), None)
            value, reason = None, row.reject
            if problem:
                reason, chain[index] = reason or problem, "break"
            elif not present:
                reason, chain[index] = reason or table_engine.NO_AMOUNT, "break"
            elif any(role == "in" for _, role in present) and any(role == "out" for _, role in present):
                reason, chain[index] = reason or BOTH, "break"
            elif len(present) > 1:
                reason, chain[index] = reason or MORE_THAN_ONE_ROW, "break"
            else:
                position, role = present[0]
                cell = cells[position]
                if role == "signed":
                    value = self.signed(cell, row, mode, default)
                    found.unresolved = found.unresolved or value is None
                else:
                    value = -cell.minor if (role == "out") != (cell.marker == "minus") else cell.minor
                    clashes += (role == "out" and cell.marker == "credit") or (role == "in" and cell.marker == "debit")  # CR in a money-out column.
            if balance_at in cells and cells[balance_at].minor is not None:
                found.balances[index] = -cells[balance_at].minor if cells[balance_at].marker == "minus" else cells[balance_at].minor
            if value is not None:
                chain[index] = value
            found.reasons[index] = reason
            if reason is None and value is not None:
                found.amounts[index] = value
        self.run_chain(found, chain, balance_at)
        self.run_summary(found)
        found.others = roles.count("other")
        found.unsupported = balance_at is not None and found.holds == 0 and self.labels[balance_at] != "balance"
        found.conflicts = clashes + sum(1 for label, role in zip(self.labels, roles) if label is not None and label != role)
        found.labelled = any(self.labels) and all(label == role if label else role == "other" for label, role in zip(self.labels, roles))
        return found

    def run_chain(self, found, chain, balance_at):
        """FR-10: consecutive printed balances, each the one before plus the signed amounts of the rows between, in minor units (a card's
        balance is what is owed, so charges add to it). A row whose amount can't be read breaks the chain there. The chain starts from the
        table's opening anchor, else from the first printed balance."""
        if balance_at is None:
            return
        direction = -1 if self.reader.card else 1
        previous, accrued, total = None, 0, 0
        for index in range(len(self.rows)):
            kind = found.kinds[index]
            if kind == "anchor":
                anchor = self.anchor_of.get(index)
                if anchor is not None and anchor.kind == "opening" and previous is None and found.implied_open is None:
                    previous, accrued = signed_minor(anchor.value, self.reader.currency), 0
                    found.implied_open = previous
                continue
            if kind == "neutral":
                continue
            amount, balance = chain[index], found.balances[index]
            if amount is None or amount == "break":
                if previous is not None:
                    found.links += 1
                    found.first_break = found.first_break or (index, balance)
                previous, accrued = None, 0
                continue
            total += amount
            accrued += amount
            if balance is not None:
                if previous is not None:
                    found.links += 1
                    if previous + direction * accrued == balance:
                        found.holds += 1
                    else:
                        found.first_break = found.first_break or (index, balance)
                elif found.implied_open is None:
                    found.implied_open = balance - direction * total
                previous, accrued = balance, 0
        if previous is not None:
            found.implied_close = previous + direction * accrued

    def run_summary(self, found):
        """FR-11: opening + in − out = closing (bank), previous − credits + charges = new (card), from the printed anchors, and every
        printed column total. Only a statement with one transactions table can say its summary is about this table."""
        reader = self.reader
        if not reader.single:
            return
        own = [anchor for position, anchor in self.anchor_of.items() if anchor is not None and found.kinds[position] == "anchor"]
        anchors = sorted([*reader.summary_anchors, *own], key=reader.reading_order)
        opening = next((anchor for anchor in anchors if anchor.kind == "opening"), None)
        closing = next((anchor for anchor in reversed(anchors) if anchor.kind == "closing"), None)
        if opening is None or closing is None:
            return
        first, last = signed_minor(opening.value, reader.currency), signed_minor(closing.value, reader.currency)
        if first is None or last is None:
            return
        found.printed = True
        net = sum(amount for amount in found.amounts if amount is not None)
        bank, card = first + net == last, first - net == last
        holds = card if reader.card else bank if reader.statement_type == "bank" else bank or card
        for total in self.table.totals:
            position = self.index.get(total.column_id)
            if position is None or found.roles[position] not in ("in", "out"):
                continue
            printed = minor_of(total.value, reader.currency)
            summed = sum(self.cells[index][position].minor for index in found.accepted if position in self.cells[index])
            holds = holds and printed == summed
        found.summary_holds = holds


@dataclass
class Decision:
    tier: str | None = None  # chain, summary, chain_most, labels, default; None: not decided.
    candidate: Candidate | None = None
    differing: bool = False  # The strongest tier had candidates that disagree on the money, so a weaker reading was used (or none).


# --- The reader --------------------------------------------------------------------------------------------------------------

class Reader:
    def __init__(self, result, *, statement_type=None, currency="USD", fallback_period=None, choices=None, prior_order=None):
        self.statement_type = "bank" if statement_type == "bank" else "card" if statement_type in ("card", "credit_card") else None
        self.card = self.statement_type == "card"
        self.currency_given = currency is not None
        self.currency = (currency or "USD").upper()
        self.fallback = fallback_period
        self.choices = choices or {}
        self.prior = prior_order
        self.default = OUT_DEFAULT if self.card else IN_DEFAULT if self.statement_type == "bank" else None
        self.lines = {page.number: {line.id: (position, line.text) for position, line in enumerate(page.layout.lines)}
                      for page in result.pages if page.method == "embedded_text" and page.layout is not None}
        self.engine = table_engine.read(result, amounts=False)
        self.tables = copy.deepcopy(self.engine.tables)
        self.summary_anchors = copy.deepcopy(self.engine.summary_anchors)
        self.unplaced = copy.deepcopy(self.engine.unplaced)
        self.pending = []
        self.issues, self.notes, self.recorded, self.kept_anchors = [], [], [], []
        self.dropped, self.order_pages, self.years = 0, set(), set()
        self.carry = {}  # id(row) -> the row whose date a dateless row takes (OD-1).
        self.period = self.effective = None  # The printed period; the one dates are placed and checked against (printed, else the fallback).
        self.order = self.order_source = None
        self.single = False

    # --- Reading order and text ----------------------------------------------------------------------------------------------

    def reading_order(self, anchor):
        return anchor.page, self.lines[anchor.page].get(anchor.line_id, (0, ""))[0]

    def line_text(self, page, line_ids):
        return " ".join(self.lines[page].get(line_id, (0, ""))[1] for line_id in line_ids)

    def transactions(self):
        return [table for table in self.tables if table.kind == "transactions"]

    @staticmethod
    def plain(table):
        return [row for row in table.rows if not row.candidate]

    # --- Pending rows (R4) ---------------------------------------------------------------------------------------------------

    def split_pending(self):
        for table in self.transactions():
            kept = []
            for row in table.rows:
                if not row.candidate and row.section and PENDING_TITLE.search(row.section):
                    self.pending.append(Unplaced(row.page, row.line_ids[0] if row.line_ids else "", self.line_text(row.page, row.line_ids), "pending"))
                else:
                    kept.append(row)
            table.rows = kept

    # --- Period (plan P8, FR-14) ---------------------------------------------------------------------------------------------

    def slash_tokens(self):
        return [token for table in self.transactions() for row in self.plain(table) for token in row.dates if token.value[3] == "slash"]

    @staticmethod
    def day_order(tokens):
        """The order a day over 12 decides: DD/MM for a first part over 12, MM/DD for a second; None for neither (or for both, which is wrong)."""
        first, second = any(token.value[0] > 12 for token in tokens), any(token.value[1] > 12 for token in tokens)
        return None if first == second else "DD/MM/YYYY" if first else "MM/DD/YYYY"

    def find_period(self):
        """The first line outside every table with exactly two dated years and no amount, the first not after the second, read in its own
        order: a day over 12 in it, else the rows' (D6); a line whose order can't be told is not used."""
        rows_order = self.day_order(self.slash_tokens())
        for _, _, first, second in self.engine.period_lines:
            slash = [token for token in (first, second) if token.value[3] == "slash"]
            if slash:
                if any(token.value[0] > 12 for token in slash) and any(token.value[1] > 12 for token in slash):
                    continue
                order = self.day_order(slash) or rows_order
                if order is None:
                    continue
            else:
                order = DATE_ORDERS[0]
            start, end = self.place(first, order, None, None)[0], self.place(second, order, None, None)[0]
            if start and end and start <= end:
                self.period = (date.fromisoformat(start), date.fromisoformat(end))
                break
        self.effective = self.period
        if self.period is None and self.fallback:
            start, end = read_period(self.fallback[0]), read_period(self.fallback[1])
            if start and end:
                self.effective = (start, end)

    def span(self):
        """The dates a printed date with no four-digit year is placed in: the period, else the year the user chose."""
        if self.effective:
            return self.effective
        year = self.choices.get("year")
        return (date(year, 1, 1), date(year, 12, 31)) if year else (None, None)

    @staticmethod
    def place(token, order, start, end):
        return placed(shape_of(token), order, start, end)

    def iso(self, token, order):
        start, end = self.span()
        return self.place(token, order, start, end)[0]

    # --- Date order, schedules (plan P8, FR-09, FR-14, OD-2) -----------------------------------------------------------------

    def schedule_runs(self, order):
        """FR-09: a table, or a run of at least two consecutive rows that starts at a page's top or after a section title and continues
        the table, whose every row is dated outside the period ± 7 days. Needs a period (D6). [(table, rows, the whole table)]."""
        if self.effective is None:
            return []
        start, end = self.effective
        found = []
        for table in self.transactions():
            by_key = {(row.page, row.row): row for row in table.rows}
            rows = self.plain(table)
            outside = []
            for row in rows:
                source = by_key.get(row.carried_from) if row.carried_from else None
                isos = [self.iso(token, order) for token in (row.dates or (source.dates if source else []))]
                outside.append(bool(isos) and all(iso and not start - PERIOD_SLACK <= date.fromisoformat(iso) <= end + PERIOD_SLACK for iso in isos))
            if rows and all(outside):
                found.append((table, rows, True))
                continue
            index = 0
            while index < len(rows):
                if not outside[index]:
                    index += 1
                    continue
                stop = index
                while stop < len(rows) and outside[stop]:
                    stop += 1
                if stop - index >= 2 and index > 0 and (rows[index].page != rows[index - 1].page or rows[index].section != rows[index - 1].section):
                    found.append((table, rows[index:stop], False))
                index = stop
        return found

    def fits(self, order):
        """Whether every date of the transactions tables (schedules aside) falls within the period ± 7 days under `order` and each table's
        rows are in non-decreasing order, by their first date or by their last."""
        start, end = self.effective
        left_out = {id(row) for _, rows, whole in self.schedule_runs(order) if not whole for row in rows}  # A whole table outside the period is no evidence for an order.
        for table in self.transactions():
            first, last = [], []
            for row in self.plain(table):
                if id(row) in left_out or not row.dates:
                    continue
                isos = [self.iso(token, order) for token in row.dates]
                if not all(isos) or not all(start - PERIOD_SLACK <= date.fromisoformat(iso) <= end + PERIOD_SLACK for iso in isos):
                    return False
                first.append(isos[0])
                last.append(isos[-1])
            if first != sorted(first) and last != sorted(last):
                return False
        return True

    def decide_order(self, prior=True):
        """The order of the printed slash dates: a day over 12; else the only one that fits the period and the printed order; else the
        order last decided for the account (OD-2); else the user's choice; else undecided (and no row with such a date is recorded)."""
        tokens = self.slash_tokens()
        if not tokens:
            return None, None
        first, second = any(token.value[0] > 12 for token in tokens), any(token.value[1] > 12 for token in tokens)
        if first and second:
            return None, None
        if first or second:
            return ("DD/MM/YYYY" if first else "MM/DD/YYYY"), "day_over_12"
        if self.effective:
            fitting = [order for order in DATE_ORDERS if self.fits(order)]
            if len(fitting) == 1:
                return fitting[0], "period"
        if prior and self.prior is not None:
            found = self.prior()
            if found in DATE_ORDERS:
                return found, "prior"
        if self.choices.get("date_format") in DATE_ORDERS:
            return self.choices["date_format"], "choice"
        return None, None

    def prepare(self, prior=True):
        """Pending rows, the period and the date order: all the order decision of another statement of the account needs (OD-2)."""
        self.split_pending()
        self.find_period()
        self.order, self.order_source = self.decide_order(prior)

    def split_schedules(self):
        added = []
        for table, rows, whole in self.schedule_runs(self.order):
            if whole:
                table.kind = "schedule"
                continue
            chosen = {id(row) for row in rows}
            table.rows = [row for row in table.rows if id(row) not in chosen]
            number = 1 + sum(1 for _, other in added if other.continues == table.id)
            added.append((table, EngineTable(f"{table.id}-schedule-{number}", sorted({row.page for row in rows}), table.columns, rows, "schedule", table.id)))
        for table, schedule in added:
            self.tables.insert(max(self.tables.index(other) for other in [table, *[t for t in self.tables if t.continues == table.id]]) + 1, schedule)

    # --- Roles (plan P7) -----------------------------------------------------------------------------------------------------

    @staticmethod
    def assignments(count):
        for roles in product(ROLES, repeat=count):
            signed = roles.count("signed")
            if roles.count("balance") > 1 or signed > 1 or (signed and ("in" in roles or "out" in roles)) or not (signed or "in" in roles or "out" in roles):
                continue
            yield roles

    def decide(self, sheet):
        if not sheet.columns or len(sheet.columns) > MAX_COLUMNS:
            return Decision()
        candidates = []
        for roles in self.assignments(len(sheet.columns)):
            for mode in (("row", "bank", "card") if "signed" in roles else (None,)):
                candidates.append(sheet.evaluate(roles, mode, self.default, len(candidates)))
        usable = [candidate for candidate in candidates if candidate.usable]
        differing = False
        for tier, pool in (("chain", [c for c in usable if c.chain_decided]), ("summary", [c for c in usable if c.summary_holds]),
                           ("chain_most", self.most_links(usable))):
            if pool:
                chosen = self.resolve(pool)
                if chosen is not None:
                    return Decision(tier, chosen)
                differing = True
                break
        # Headings, then the type default (P7.5 c, d): a signed column's signs come from each row's own marker, its section, then the default,
        # which the user's sign choice replaces (account-import-pdf FR-07).
        default = self.choices.get("sign") or self.default
        labelled = [again for again in (sheet.evaluate(c.roles, "row", default, c.order) if "signed" in c.roles else c
                                        for c in candidates if c.labelled and c.mode in (None, "row")) if again.usable]
        if labelled:
            chosen = self.resolve(labelled)
            if chosen is not None:
                return Decision("labels", chosen, differing)
        if len(sheet.columns) == 1 and sheet.labels[0] in (None, "signed"):
            single = sheet.evaluate(("signed",), "row", default, 0)
            if single.usable:
                return Decision("default", single, differing)
        return Decision(differing=differing)

    @staticmethod
    def most_links(usable):
        """P7.5 b′: the candidates with the most holding chain links, when that is at least 2 and more than any candidate of another role set."""
        best = {}
        for candidate in usable:
            if candidate.links >= 2:
                best[candidate.roles] = max(best.get(candidate.roles, 0), candidate.holds)
        if not best:
            return []
        roles = max(best, key=lambda key: (best[key], -min(c.order for c in usable if c.roles == key)))
        others = [holds for key, holds in best.items() if key != roles]
        if best[roles] < 2 or (others and max(others) >= best[roles]):
            return []
        return [c for c in usable if c.roles == roles and c.holds == best[roles] and c.links >= 2]

    @staticmethod
    def resolve(pool):
        """The candidate a pool agrees on: every one gives every row the same signed amount; else the ones with the fewest `other` columns
        do; else the ones whose headings agree best do. None when the survivors still differ (the roles are undecided)."""
        for group in (pool, [c for c in pool if c.others == min(c.others for c in pool)]):
            if len({tuple(c.amounts) for c in group}) == 1:
                return min(group, key=lambda c: (c.unsupported, c.others, c.conflicts, c.order))
        fewest = min(c.conflicts for c in pool if c.others == min(d.others for d in pool))
        group = [c for c in pool if c.others == min(d.others for d in pool) and c.conflicts == fewest]
        if len({tuple(c.amounts) for c in group}) > 1:
            # A chain that skips a column's rows (balances printed only beside the other column's rows) holds under readings of that column
            # that differ on money; a printed summary that adds up under only some of them settles it.
            held = [c for c in group if c.summary_holds]
            group = held if held and len({tuple(c.amounts) for c in held}) == 1 else group
        return min(group, key=lambda c: (c.unsupported, c.order)) if len({tuple(c.amounts) for c in group}) == 1 else None

    # --- Rows ----------------------------------------------------------------------------------------------------------------

    def settle(self, sheet, candidate):
        """Classes the balance lines (an anchor when its amount sits in the balance column, else a row) and numbers the rows of each page
        1-based among the table's transaction rows."""
        table = sheet.table
        by_key = {(row.page, row.row): row for row in sheet.rows}
        counters = {}
        for position, row in enumerate(sheet.rows):
            if row.candidate and candidate.kinds[position] != "anchor":
                table.anchors = [anchor for anchor in table.anchors if not (row.line_ids and anchor.line_id == row.line_ids[0])]
                row.candidate = None
            elif row.candidate:
                self.kept_anchors.append(sheet.anchor_of[position])
        for row in sheet.rows:
            if row.carried_from:
                self.carry[id(row)] = by_key.get(row.carried_from)
        for position, row in enumerate(sheet.rows):
            if candidate.kinds[position] != "anchor":
                counters[row.page] = counters.get(row.page, 0) + 1
                row.row = counters[row.page]
        for row in sheet.rows:
            source = self.carry.get(id(row))
            row.carried_from = (source.page, source.row) if source else row.carried_from

    def written(self, token, order, row):
        """A printed date's ISO date, or why not; the order is needed for a numeric date."""
        if token.value[3] == "slash" and order is None:
            return None, None
        start, end = self.span()
        iso, reason = self.place(token, order, start, end)
        full = token.value[2] is not None and token.value[2] > 99
        self.years.add("printed" if full else "none" if iso is None else "period" if self.effective else "choice")
        return iso, reason

    def record(self, sheet, candidate):
        table = sheet.table
        dated = [column for column in table.columns if column.kind == "date"]
        balance_at = candidate.roles.index("balance") if "balance" in candidate.roles else None
        for position, row in enumerate(sheet.rows):
            if candidate.kinds[position] == "anchor":
                continue
            where = f"Page {row.page} row {row.row}"
            reason = candidate.reasons[position]
            if reason:
                row.reject = reason
                self.issues.append(f"{where}: {reason}")
                self.dropped += 1
                continue
            source = self.carry.get(id(row))
            tokens = row.dates or (source.dates if source else [])
            isos, failed = [], None
            for token in tokens:
                iso, why = self.written(token, self.order, row)
                if iso is None and why is None:
                    self.order_pages.add(row.page)
                    failed = failed or "order"
                elif iso is None:
                    failed = failed or why.format(date=token.text)
                    self.issues.append(f"{where}: {why.format(date=token.text)}")
                isos.append(iso)
            if failed:
                row.reject = None if failed == "order" else failed
                self.dropped += 1
                continue
            transaction, posted = (isos[0], isos[1]) if len(dated) > 1 and len(isos) > 1 else (None, isos[-1] if isos else None)
            if posted is None:
                self.dropped += 1
                continue
            if not row.dates and source:
                shown = posted if tokens[0].value[3] != "slash" else (f"{posted[8:]}/{posted[5:7]}/{posted[:4]}" if self.order == "DD/MM/YYYY"
                                                                      else f"{posted[5:7]}/{posted[8:]}/{posted[:4]}")
                self.notes.append(CARRIED.format(page=row.page, row=row.row, date=shown))
            cells = sheet.cells[position]
            money = [at for at, role in enumerate(candidate.roles) if role in ("in", "out", "signed")]
            transaction_row = {"posted_date": posted, "transaction_date": transaction, "description": row.description, "currency": self.currency,
                               "amount_minor": candidate.amounts[position],
                               "locator": {"rebuilt": True, "page": row.page, "table_id": table.id, "row": row.row,
                                           "balance_minor": candidate.balances[position] if balance_at is not None else None,
                                           "line_ids": row.line_ids, "word_ids": row.word_ids, "cell_ids": row.cell_ids,
                                           "quotes": [self.lines[row.page].get(line_id, (0, ""))[1] for line_id in row.line_ids]}}
            self.recorded.append((SimpleNamespace(page=row.page, table_id=table.id, amount_minor=candidate.amounts[position],
                                                  description=row.description, amount=money_text(cells, money), row=row.row), posted, transaction_row))

    def unreadable(self, sheet, decision):
        """No role assignment could be told: the table's rows are not recorded and the page says so (plan P7.5)."""
        rows = [row for row in sheet.rows if not row.candidate]
        for row in rows:
            if row.reject:
                self.issues.append(f"Page {row.page} row {row.row}: {row.reject}")
        self.dropped += len(rows)
        for page in sorted({row.page for row in rows}):
            self.issues.append(ROLES_UNKNOWN.format(page=page))

    def outcome(self, sheet, decision):
        """FR-15: the first row where the balance chain breaks, and FR-13's reason when only headings or the type decided the signs."""
        candidate, table = decision.candidate, sheet.table
        if candidate.first_break is not None and "balance" in candidate.roles:
            position, balance = candidate.first_break
            row = sheet.rows[position]
            cell = sheet.cells[position].get(candidate.roles.index("balance"))
            if cell is not None and balance is not None and not candidate.reasons[position]:
                self.issues.append(CHAIN_BREAK.format(page=row.page, row=row.row, balance=cell.printed))
        if decision.tier in ("labels", "default"):
            page = next((row.page for row in sheet.rows if not row.candidate), table.pages[0])
            self.issues.append((ROLES_DIFFER if decision.differing else TOO_FEW).format(page=page))

    def joins(self, chains):
        """FR-17: two chains that each hold but don't join are one issue; both tables' rows were recorded."""
        for (first, one), (second, two) in zip(chains, chains[1:]):
            if one.implied_close != two.implied_open:
                self.issues.append(TWO_ACCOUNTS.format(first=first.pages[0], second=second.pages[0]))
                return

    def pages(self):
        """The pages holding a transactions table's rows, recorded or not (pending rows count, schedules don't): Record gives these pages to the engine."""
        return {row.page for table in self.transactions() for row in self.plain(table)} | {line.page for line in self.pending}

    def balances(self):
        anchors = sorted([*self.summary_anchors, *self.kept_anchors], key=self.reading_order)
        opening = next((anchor for anchor in anchors if anchor.kind == "opening"), None)
        closing = next((anchor for anchor in reversed(anchors) if anchor.kind == "closing"), None)
        return (signed_minor(opening.value, self.currency) if opening else None, signed_minor(closing.value, self.currency) if closing else None)

    # --- The statement -------------------------------------------------------------------------------------------------------

    def run(self):
        self.prepare()
        self.split_schedules()
        tables = self.transactions()
        self.single = len(tables) == 1
        roles, signs, chains = {}, {}, []
        for table in tables:
            sheet = Sheet(self, table)
            decision = self.decide(sheet)
            signs[table.id] = decision.tier
            candidate = decision.candidate
            if candidate is None:
                roles[table.id] = {}
                self.unreadable(sheet, decision)
                continue
            roles[table.id] = {column.id: role for column, role in zip(sheet.columns, candidate.roles)}
            self.settle(sheet, candidate)
            self.record(sheet, candidate)
            self.outcome(sheet, decision)
            if decision.tier == "chain" and candidate.implied_open is not None and candidate.implied_close is not None:
                chains.append((table, candidate))
        self.joins(chains)
        self.issues += [ORDER_UNKNOWN.format(page=page) for page in sorted(self.order_pages)]
        self.dropped += len(self.unplaced) + len(self.pending)
        self.issues += [UNPLACED.format(page=line.page, text=line.text) for line in self.unplaced]
        self.issues += [PENDING.format(page=line.page, text=line.text) for line in self.pending]
        self.issues += duplicates([(row, posted) for row, posted, _ in self.recorded])
        opening, closing = self.balances()
        self.notes = [NO_TABLE.format(page=page) for page in self.engine.pages_without_tables] + self.notes
        year = None if "none" in self.years else "period" if "period" in self.years else "choice" if "choice" in self.years else "printed" if self.years else None
        return StatementReading([transaction for _, _, transaction in self.recorded], self.issues, self.notes, self.dropped, self.pages(),
                                opening, closing, tuple(day.isoformat() for day in self.period) if self.period else None, self.order,
                                {"order": self.order_source, "year": year, "signs": signs}, roles, True, self.tables, self.unplaced + self.pending,
                                self.summary_anchors)


# --- Entry points ------------------------------------------------------------------------------------------------------------

def laid_out(result):
    """False when an `embedded_text` page has no saved layout (FR-23): the reading was made before layouts existed."""
    return all(page.layout is not None for page in result.pages if page.method == "embedded_text")


def engine_pages(result) -> set[int]:
    """The pages the engine reads rows from, whatever the currency or the choices; empty when the reading has no layout."""
    return Reader(result).run().pages if laid_out(result) else set()


def read(result, *, statement_type=None, currency="USD", fallback_period=None, choices=None, prior_order=None) -> StatementReading:
    """The rows, issues and notes of a bank or card statement, from its printed columns (plan P1, P2).

    `statement_type` is `credit_card` (or `card`), `bank`, or None (no type default). `currency` is the statement's ISO code.
    `fallback_period` is the model's (start, end) as ISO dates, used only when no period is printed. `choices` are the user's, applied
    only where the printed columns can't decide: `year`, `date_format` (MM/DD/YYYY or DD/MM/YYYY) and `sign` (positive_is_outflow or
    negative_is_outflow). `prior_order` is called with no arguments when the date order can't be told, and gives an order or None (OD-2).
    """
    if not laid_out(result):
        return StatementReading(notes=[NO_LAYOUT_NOTE], available=False)
    return Reader(result, statement_type=statement_type, currency=currency, fallback_period=fallback_period, choices=choices,
                  prior_order=prior_order).run()


def decided_order(result):
    """The date order the printed dates of a reading decide on their own (a day over 12, or the printed period), else None: the order
    decision without OD-2's step, so it never recurses."""
    if not laid_out(result):
        return None
    reader = Reader(result)
    reader.prepare(prior=False)
    return reader.order


def prior_order(db, last_four, document_id):
    """OD-2: the date order last decided for the account with this last four. The statements of such accounts from other documents whose
    reading is a PDF, newest period end first, at most ten; for each, the order its own printed dates decide. None when none decides."""
    if not last_four:
        return None
    rows = db.execute("SELECT p.result_json FROM statements s JOIN accounts a ON a.id=s.account_id JOIN extraction_runs e ON e.id=s.extraction_run_id "
                      "JOIN parse_runs p ON p.id=e.parse_run_id WHERE a.account_last_four=? AND s.document_id<>? AND p.status IN ('succeeded','partial') AND p.result_json IS NOT NULL "
                      f"AND p.parser_version IN ({','.join('?' * len(PDF_VERSIONS))}) ORDER BY s.period_end DESC, s.id DESC LIMIT ?",
                      (last_four, document_id, *PDF_VERSIONS, PRIOR_STATEMENTS)).fetchall()
    for row in rows:
        try:
            found = decided_order(read_result(json.loads(row[0])))
        except Exception as exc:  # One bad saved reading must not stop the others.
            log_failure(log, "prior date order", exc)
            continue
        if found:
            return found
    return None
