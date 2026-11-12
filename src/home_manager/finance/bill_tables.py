"""What a bill's printed columns mean (specs/pdf-table-engine-bills FR-105, FR-106, FR-110's rate rule, FR-124; plan P1, P2, P4).

`read` takes a saved PDF reading, finds its charge tables with `documents/charge_tables`, decides each table's column roles from the printed numbers
alone, moves a table with no charge column among the other tables, and hands Record the tables in the shape the pay stub adapter makes. It is pure and
deterministic like the engine: no store, model, network, clock or randomness. Money stays exact `Decimal` (the engine's tokens) until `printed_rate`
or Record turns it into minor units.

Roles, in the spec's order (FR-105). (a) Quantity and rate: a pair of columns whose product is a third column on every row printing all three, by the
product rule `document_checks.product` uses. (b) Sums: the column whose signed amounts (FR-106) add up to the bill's new charges (printed, else worked
out by FR-118, else the amount due), or whose printed subtotals each equal the rows they cover (phase 3 FR-91's coverage rule). (c) Headings break a tie
and are the only guide when nothing else decides. (d) One amount column is the charge. Two columns that both add up and no heading separates are guessed:
the right-most is the charge and a `Guess` says so (FR-124, a note and never a review reason). Every other column is `other` and never money.

The rate rule (`printed_rate`, FR-110, D21, D25) turns a printed rate into minor units: a rate whose value is a whole number of minor units is exact and
keeps no text, any other is rounded half up and keeps the printed text. `for_lines` keeps what lies in one part of a file, as `paystub_tables.for_lines`
does for a pay stub. A table may run on over the pages of several bills of one file: a section title never reaches a row of another bill (FR-102, FR-106),
and the sum rule is judged on each bill's own rows and anchors (FR-105 b), the bills being where `documents/bill_split` starts them. What Record says beyond the cells (the FR-117 and FR-112 guesses, summary values, notes for unplaced lines) is built where Record reads
a part, from the kinds named here.
"""

from bisect import bisect_right
from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
import re
from types import SimpleNamespace

from ..core.money import EXPONENTS
from ..documents import bill_split, charge_tables
from ..documents.charge_tables import CREDIT_SECTION, ChargeTotal
from ..documents.layout_context import evidence_lines, native_page
from ..documents.table_engine import value_of
from .document_checks import decimal
from .paystub_tables import PageMap, adapt_header, cell_of, evidence_index, multiplies, page_number, spans_of

CHARGE_COLUMN = "charge_column"
UNCLASSIFIED_ROW = "unclassified_row"
AMOUNT_DUE = "amount_due"
SPLIT_CHANGED = "split_changed"
GUESS_KINDS = (CHARGE_COLUMN, UNCLASSIFIED_ROW, AMOUNT_DUE, SPLIT_CHANGED)  # FR-124: each adds to `guesses` by kind in the eval.
ROLES = ("charge", "quantity", "unit_price", "other")

# FR-105 (c): headings only break ties and guide where the numbers decide nothing. Whole words, case-insensitive.
CHARGE_HEADS = re.compile(r"\b(?:charges?|amount|current|this\s+bill|this\s+period|total)\b", re.IGNORECASE)
OTHER_HEADS = re.compile(r"\b(?:last\s+year|previous|prior|usage|rate|kwh|meter|reading|days)\b", re.IGNORECASE)


# --- Contracts (plan P2) -------------------------------------------------------------------------------------------------

@dataclass
class Roles:
    table_id: str
    roles: dict[str, str]  # Column id to charge, quantity, unit_price or other.
    decided_by: str  # product, sum, subtotals, heading, single or guess.


@dataclass
class Guess:
    kind: str  # charge_column, unclassified_row, amount_due or split_changed (`GUESS_KINDS`)
    page: int
    table_id: str | None  # The charge table the guess concerns, None for a guess about the bill.
    text: str  # The note shown with the record.


@dataclass
class PrintedRate:
    minor: int
    text: str | None  # The printed text, only when the value is not a whole number of minor units (D25).


@dataclass
class BillTables:
    reading: charge_tables.BillReading  # `tables` holds the charge tables only; a table with no charge column is in `other_tables`.
    roles: list[Roles]  # One per charge table, in the same order.
    adapted: list = field(default_factory=list)  # `reading.tables` in Record's table shape (P4), on the pages Record can read; roles by cell index.
    guesses: list[Guess] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # The guesses' texts, in order.
    engine_pages: set[int] = field(default_factory=set)  # Pages holding an adapted charge table: Record takes its cells there.
    line_pages: set[int] = field(default_factory=set)  # Pages that have evidence lines.
    lines_of: dict[str, str] = field(default_factory=dict)  # A layout line id to the evidence line id that holds its words.
    pages: set[int] = field(default_factory=set)  # Pages holding a charge table.


# --- The rate rule (FR-110, D21, D25) ------------------------------------------------------------------------------------

def printed_rate(text, currency):
    """A printed rate as minor units. When its value is a whole number of minor units (`0.12`, `0.1200`, `13.00` in USD) it is exact and keeps no text. Else
    (`0.1430`) it is rounded half up to the minor unit and keeps the printed text. Never raises a precision issue; raises ValueError for a word that is no
    number."""
    value = decimal(text)
    if value is None:
        raise ValueError(f"not a printed rate: {text!r}")
    scaled = value.scaleb(EXPONENTS[currency])
    if scaled == scaled.to_integral_value():
        return PrintedRate(int(scaled), None)
    return PrintedRate(int(scaled.quantize(Decimal(1), ROUND_HALF_UP)), text)


# --- Money off (FR-106) --------------------------------------------------------------------------------------------------

def signed(token, section):
    """A charge token's amount with its sign: minus, parentheses, a trailing minus and `CR` make it negative; so does an unsigned amount under a credits,
    discounts or adjustments section. An explicit `+` or `DR` is a charge wherever it is printed (FR-106). None for an unreadable amount."""
    magnitude, marker, _ = token.value
    if magnitude is None:
        return None
    if marker in ("minus", "credit") or (marker is None and section and CREDIT_SECTION.search(section)):
        return -magnitude
    return magnitude


def charge_column(roles):
    return next((column for column, role in roles.roles.items() if role == "charge"), None)


def money_off(row, roles):
    """Whether a row is money off (FR-106): its charge is printed with a minus, parentheses, a trailing minus or `CR`, or is unsigned under a section
    titled credits, discounts or adjustments."""
    token = row.amounts.get(charge_column(roles))
    if token is None or token.kind != "amount" or token.value[0] is None:
        return False
    return signed(token, row.section) < 0


# --- Roles (FR-105) ------------------------------------------------------------------------------------------------------

def number_text(row, column):
    """The printed number of a cell (`500` of `500 kWh`), None when the row prints none there or it is no number."""
    if column in row.usage:
        return row.usage[column][0].split()[0]
    token = row.amounts.get(column)
    if token is not None and (token.kind == "integer" or token.kind == "amount" and token.value[0] is not None):
        return token.text
    return None


def places_of(table, column):
    """The most decimal places printed in a column's rows (a rate prints more than a quantity)."""
    return max((len(text.partition(".")[2]) for row in table.rows if (text := number_text(row, column)) is not None), default=0)


def holds(row, first, second, third):
    """first × second = third on a row printing all three, by the product rule (`document_checks.product`)."""
    texts = [number_text(row, column) for column in (first, second)]
    token = row.amounts.get(third)
    if None in texts or token is None or token.kind != "amount" or token.value[0] is None:
        return None
    result = SimpleNamespace(text=token.text, value=(abs(token.value[0]), None, token.value[2]))
    return multiplies(SimpleNamespace(text=texts[0]), SimpleNamespace(text=texts[1]), result)


def product_roles(table):
    """(a): the (quantity, unit price, charge) column ids where quantity × unit price = charge on every row printing all three, and on at least one. The
    quantity is the usage or integer column, else the one printing fewer decimal places (the left one when equal). Of several triples, the one judged on
    most rows, then the right-most charge."""
    kinds = {column.id: column.kind for column in table.columns}
    order = {column.id: number for number, column in enumerate(table.columns)}
    found = []
    for third in kinds:
        if kinds[third] != "amount":
            continue
        others = [column for column in kinds if column != third]
        for position, first in enumerate(others):
            for second in others[position + 1:]:
                verdicts = [holds(row, first, second, third) for row in table.rows]
                judged = [verdict for verdict in verdicts if verdict is not None]
                if judged and all(judged):
                    found.append((len(judged), order[third], first, second, third))
    if not found:
        return None
    _, _, first, second, third = max(found, key=lambda entry: (entry[0], entry[1]))
    if (kinds[first] == "amount") != (kinds[second] == "amount"):
        quantity, rate = (second, first) if kinds[first] == "amount" else (first, second)
    elif places_of(table, second) < places_of(table, first):
        quantity, rate = second, first
    else:
        quantity, rate = first, second
    return quantity, rate, third


def covered(entries, position):
    """The two row sets a printed total at `position` of the table's rows and totals may cover (phase 3 FR-91): the rows since the previous total, and the
    rows since the previous total or the title of the section it ends (one set when the table has no sections after the previous total)."""
    wide, narrow = [], None
    for earlier in reversed(entries[:position]):
        if isinstance(earlier, ChargeTotal):
            break
        if narrow is None and wide and earlier.section != wide[-1].section:
            narrow = list(wide)
        wide.append(earlier)
    return wide, wide if narrow is None else narrow


def subtotals_hold(table, column):
    """Whether the column has a printed total and every printed total value in it equals the rows it covers (either coverage)."""
    entries = sorted([*table.rows, *table.totals], key=lambda entry: entry.row)
    verdicts = []
    for position, entry in enumerate(entries):
        if not isinstance(entry, ChargeTotal) or column not in entry.values or entry.values[column].value[0] is None:
            continue
        rows = [row for row in covered(entries, position)[0] if column in row.amounts]
        if not rows:
            continue
        sums = [sum((signed(row.amounts[column], row.section) or 0 for row in group if column in row.amounts), Decimal(0)) for group in covered(entries, position)]
        verdicts.append(value_of(entry.values[column]) in sums)
    return bool(verdicts) and all(verdicts)


def targets_of(anchors):
    """What the charge column should add up to (FR-105 b): every new-charges value among the bill's anchors, whatever page of the bill prints it (FR-103); else,
    with a previous balance and payments there, the amount due less the previous balance plus the payments (FR-118); else every amount-due value."""
    here = [anchor for anchor in anchors if anchor.token.value[0] is not None]
    values = lambda kind: [value_of(anchor.token) for anchor in here if anchor.kind == kind]  # noqa: E731
    if values("new_charges"):
        return values("new_charges")
    due, previous, payments = values("amount_due"), values("previous_balance"), values("payments")
    if due and previous and payments:
        return [value - previous[0] + abs(payments[0]) for value in due]
    return due


def adds_up(table, column, anchors, cuts):
    """Whether a column's signed amounts add up to a target (FR-105 b), judged per bill when the table runs on over several bills of the file: each bill's
    rows of this table in the column against the targets printed anywhere in that bill's lines, on whichever pages it has (FR-103)."""
    verdicts = []
    for bill in sorted({cuts.bill_of_row(row) for row in table.rows}):
        values = [signed(row.amounts[column], row.section) for row in table.rows if column in row.amounts and cuts.bill_of_row(row) == bill]
        if None in values:
            return False
        if values:
            verdicts.append(sum(values) in targets_of([anchor for anchor in anchors if cuts.bill_of(anchor.line_id, anchor.page) == bill]))
    return bool(verdicts) and all(verdicts)


def head_of(column):
    """What a column's heading words say (FR-105 c): charge, other, or None when it says neither or both."""
    text = " ".join(column.labels)
    named = [bool(CHARGE_HEADS.search(text)), bool(OTHER_HEADS.search(text))]
    return "charge" if named == [True, False] else "other" if named == [False, True] else None


def guess_for(table, text):
    return Guess(CHARGE_COLUMN, table.pages[0], table.id, f"Page {table.pages[0]}: {text}")


def decide(table, anchors, cuts):
    """The roles of one charge table (FR-105 in order) and its guesses; None when no column of it is a charge (then it is another table). `cuts` is the
    first line of each bill of the file (`Cuts`): the sum rule is judged per bill."""
    columns = [column.id for column in table.columns]
    amount = [column.id for column in table.columns if column.kind == "amount"]
    if not amount:
        return None
    found = product_roles(table)
    if found:
        quantity, rate, charge = found
        roles = {column: "quantity" if column == quantity else "unit_price" if column == rate else "charge" if column == charge else "other" for column in columns}
        return Roles(table.id, roles, "product"), []
    roles, guesses = {column: "other" for column in columns}, []

    def decided(charge, by):
        roles[charge] = "charge"
        return Roles(table.id, roles, by), guesses

    if len(amount) == 1:
        return decided(amount[0], "sum" if adds_up(table, amount[0], anchors, cuts) else "single")
    by_sum = [column for column in amount if adds_up(table, column, anchors, cuts)]
    holding = [column for column in amount if column in by_sum or subtotals_hold(table, column)]
    if len(holding) == 1:
        return decided(holding[0], "sum" if holding[0] in by_sum else "subtotals")
    heads = {column.id: head_of(column) for column in table.columns}
    candidates = holding or amount
    named = [column for column in candidates if heads[column] != "other"]
    charge = [column for column in named if heads[column] == "charge"]
    if len(charge) == 1 or not charge and len(named) == 1:
        return decided((charge or named)[0], "heading")
    if not holding and not named:
        return None  # Every heading says the columns are something else and no number says otherwise: another table (FR-104).
    right = max(charge or named or candidates, key=columns.index)
    guesses.append(guess_for(table, "two printed columns add up to the bill's charges; the right-most was taken as the charge." if holding
                             else "the printed columns could not be told apart; the right-most was taken as the charge."))
    return decided(right, "guess")


# --- The adapter (plan P4) -----------------------------------------------------------------------------------------------

def adapt_row(table, entry, total, columns, mapping, roles):
    """One engine row or total as Record's row: cell 0 is the label, then one cell per column in column order, blank when the row prints nothing there."""
    identity = f"{table.id}-row-{entry.row}"
    printed = entry.values if total else entry.amounts
    usage = {} if total else entry.usage
    held = {word_id for token in printed.values() for word_id in token.word_ids} | {word_id for _, words in usage.values() for word_id in words}
    held |= {word_id for token in ([] if total else entry.stray) for word_id in token.word_ids}
    label_words = [word_id for word_id in entry.word_ids if word_id not in held]
    ordered = [*label_words, *[word_id for word_id in entry.word_ids if word_id not in label_words]]
    line_ids = mapping.lines(ordered) or list(entry.line_ids if not total else [entry.line_id])
    line_id = line_ids[0] if line_ids else ""
    shown = mapping.cites(label_words)
    cells = [cell_of(f"{identity}-cell-0", mapping.line_of.get(label_words[0], line_id) if label_words else line_id, entry.label, label_words, mapping,
                     mapping.lines(label_words), shown if len(shown) > 1 else None, native=True)]
    for number, column in enumerate(columns, 1):
        if column.id in usage:
            quote, words = usage[column.id]
        else:
            token = printed.get(column.id)
            quote, words = (token.text, token.word_ids) if token else ("", [])
        cells.append(cell_of(f"{identity}-cell-{number}", mapping.line_of.get(words[0], line_id) if words else line_id, quote, words, mapping,
                             mapping.lines(words), native=True))
    title = None if total else entry.title
    return SimpleNamespace(id=identity, line_id=line_id, line_ids=line_ids, cells=cells, total=total, label=entry.label, section=None if total else entry.section,
                           title_line_id=mapping.line_of.get(title.word_ids[0]) if title and title.word_ids else None, title_phone=bool(title and title.phone),
                           page=entry.page, money_off=False if total else money_off(entry, roles))


def adapt(tables, roles, evidence):
    """The charge tables in Record's table shape (plan P4): `SimpleNamespace(id, page, pages, source="bill_engine", header_rows, rows, roles, spans)`. Each
    row is `(id "<table>-row-<r>", line_id, line_ids, cells, total, label, section, title_line_id, title_phone, page, money_off)` and a total is a row with
    `total` set. A row's line ids are the evidence lines (what the model is shown) that hold its words, the label's first (a wrapped label lists both);
    `roles` maps a cell index to its role. Only rows on pages Record reads as native text are kept."""
    maps = {page.number: PageMap(page) for page in evidence.pages if page.method == "embedded_text" and page.layout is not None and native_page(page)}
    made = []
    for table, found in zip(tables, roles):
        entries = sorted([*((row, False) for row in table.rows), *((total, True) for total in table.totals)], key=lambda entry: entry[0].row)
        rows = [adapt_row(table, entry, total, table.columns, maps[entry.page], found) for entry, total in entries if entry.page in maps]
        if not rows:
            continue
        first = next((row.line_id for row in rows if row.line_id), "")
        mapping = maps[table.pages[0]] if table.pages[0] in maps else maps[rows[0].page]
        made.append(SimpleNamespace(id=table.id, page=rows[0].page, pages=sorted({row.page for row in rows}), source="bill_engine",
                                    header_rows=[adapt_header(table, table.columns, mapping, first)], rows=rows, spans=spans_of(rows, maps),
                                    roles={number: found.roles[column.id] for number, column in enumerate(table.columns, 1)}))
    return made


# --- Bills of one file (FR-128) ------------------------------------------------------------------------------------------

def anchors_by_line(anchors, lines_of):
    """{evidence line id holding an anchor's label: [(kind, value), ...]}: the engine's anchors as the split rule reads them (bill_split.bill_parts)."""
    found = {}
    for anchor in anchors:
        found.setdefault(lines_of.get(anchor.line_id, anchor.line_id), []).append((anchor.kind, anchor.token.value[0]))
    return found


@dataclass
class Cuts:
    """Where the bills of the file start (FR-128, FR-130): the position of each bill's first line among the file's non-blank evidence lines. The user's own
    split (which may cut inside a page) when there is one, else the rule's, which cuts between pages. Every decision that belongs to one bill (a section
    title's reach, the sum rule's rows and anchors, money off) asks `bill_of`."""
    firsts: list[int]
    where: dict[str, int]  # An evidence line id to its position.
    lines_of: dict[str, str]  # A layout line id to the evidence line id that holds its words.
    page_first: dict[int, int]  # A page to the position of its first line.

    def bill_of(self, line_id, page):
        """The index of the bill a layout (or evidence) line is in; a line that holds no evidence line counts as its page's first."""
        position = self.where.get(self.lines_of.get(line_id, line_id))
        if position is None:
            position = self.page_first.get(page, 0)
        return max(bisect_right(self.firsts, position) - 1, 0)

    def bill_of_row(self, row):
        return self.bill_of(row.line_ids[0] if row.line_ids else "", row.page)


def cuts_of(evidence, anchors, lines_of, firsts=None):
    """The `Cuts` of a file: at `firsts` (the evidence line ids that start the bills of the user's split), else at the pages the split rule starts bills
    on ([the first page] for one bill, or when the rule raises: the caller words that, FR-129 d)."""
    lines = [line for line in evidence_lines(evidence) if line.text.strip()]
    where = {line.id: position for position, line in enumerate(lines)}
    page_first = {}
    for position, line in enumerate(lines):
        page_first.setdefault(bill_split.page_of(line), position)
    if firsts is not None:
        starts = {where[line_id] for line_id in firsts if line_id in where}
    else:
        try:
            found = bill_split.bill_parts(lines, anchors_by_line(anchors, lines_of))
            starts = {first for first, last in found.parts if last > first}
        except Exception:
            starts = set()
    return Cuts(sorted({0, *starts}), where, lines_of, page_first)


def own_sections(table, cuts):
    """The table with each row's section kept only when its title is printed in the row's own bill: a bill's last title (`Account Credits`) does not
    carry into the next bill's rows (FR-102, FR-106), whether the bills start on a new page or inside one."""
    rows = [row if row.title is None or cuts.bill_of(row.title.line_id, row.title.page) == cuts.bill_of_row(row) else replace(row, section=None, title=None)
            for row in table.rows]
    return replace(table, rows=rows)


# --- Entry point ---------------------------------------------------------------------------------------------------------

def read(evidence, firsts=None):
    """Read a saved PDF reading (`PDFResult`) into charge tables, their column roles and Record's adapted tables. `firsts`: the evidence line ids that start
    the bills of the user's own split, which then replaces the rule's boundaries for every decision made per bill (FR-130, FR-131); the PDF is read once."""
    reading = charge_tables.read(evidence)
    lines_of, line_pages = evidence_index(evidence)
    cuts = cuts_of(evidence, reading.anchors, lines_of, firsts)
    reading = replace(reading, tables=[own_sections(table, cuts) for table in reading.tables])
    decided = [(table, decide(table, reading.anchors, cuts)) for table in reading.tables]
    tables = [table for table, found in decided if found]
    moved = [table for table, found in decided if not found]
    roles = [found[0] for _, found in decided if found]
    guesses = [guess for _, found in decided if found for guess in found[1]]
    pages = {page for table in tables for page in table.pages}
    reading = replace(reading, tables=tables, other_tables=[*reading.other_tables, *moved],
                      unplaced=[line for line in reading.unplaced if line.page in pages],
                      pages_without_tables=sorted(set(reading.pages_without_tables) | ({page for table in moved for page in table.pages} - pages)))
    found = BillTables(reading, roles, guesses=guesses, notes=[guess.text for guess in guesses], pages=pages)
    found.adapted = adapt(tables, roles, evidence)
    found.engine_pages = {row.page for table in found.adapted for row in table.rows}
    found.lines_of, found.line_pages = lines_of, line_pages
    return found


def for_lines(bills, line_ids):
    """What lies in one part of a file (plan P4): the rows and totals whose evidence line is in `line_ids`, and the anchors, late lines, unplaced lines,
    other tables and guesses (with the notes they carry) of those lines, and the pages without a table among the part's pages. A table a user split cuts
    gives each part its own rows (SC-128 step 8)."""
    ids = set(line_ids)
    mine = lambda *layout: any(bills.lines_of.get(line, line) in ids for line in layout)  # noqa: E731
    adapted = [replace_rows(table, [row for row in table.rows if row.line_id in ids]) for table in bills.adapted]
    adapted = [table for table in adapted if table.rows]
    kept = {row.id for table in adapted for row in table.rows}
    owners = {table.id for table in adapted}
    pairs = [(table, roles) for table, roles in zip(bills.reading.tables, bills.roles) if table.id in owners]
    tables = [replace(table, rows=[row for row in table.rows if f"{table.id}-row-{row.row}" in kept],
                      totals=[total for total in table.totals if f"{table.id}-row-{total.row}" in kept]) for table, _ in pairs]
    pages = {page for page in (page_number(line_id) for line_id in ids) if page is not None}
    reading = bills.reading
    others = [table for table in reading.other_tables if any(mine(*row.line_ids) for row in table.rows)]
    guesses = [guess for guess in bills.guesses if guess.table_id is None or guess.table_id in owners]
    engine_pages = {row.page for table in adapted for row in table.rows}
    part = replace(reading, tables=tables, other_tables=others, anchors=[anchor for anchor in reading.anchors if mine(anchor.line_id)],
                   late_lines=[line for line in reading.late_lines if mine(line)], unplaced=[line for line in reading.unplaced if mine(line.line_id)],
                   pages_without_tables=[page for page in sorted(reading.pages_without_tables) if page in pages],
                   line_pages={line: page for line, page in reading.line_pages.items() if mine(line)})
    return replace(bills, reading=part, roles=[roles for _, roles in pairs], adapted=adapted, guesses=guesses, notes=[guess.text for guess in guesses],
                   engine_pages=engine_pages, pages=engine_pages)


def split_anchors(bills):
    """The engine's summary anchors for the split rule (FR-128, plan P8.1), so a part whose `Amount Due` label and amount are on separate layout lines
    still prints its amount due (bill_split.bill_parts)."""
    return anchors_by_line(bills.reading.anchors, bills.lines_of)


def replace_rows(table, rows):
    return SimpleNamespace(**{**vars(table), "rows": rows})
