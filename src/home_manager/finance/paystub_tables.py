"""What the pay stub's printed columns mean (specs/pdf-table-engine-paystubs FR-56 – FR-59, FR-74, FR-75; plan P3.8, P5, P6).

`read` takes a saved PDF reading, finds its pay tables with `documents/pay_tables`, tells pay tables from other tables (deposit, leave), decides
each pay table's column roles from the printed numbers alone, reads the summary box, and writes down every guess. It is pure and deterministic like
the engine: no store, model, network, clock or randomness. Money stays exact `Decimal` (the engine's tokens); no float decides a role.

Roles, in the spec's order (FR-57). (a) Hours × rate: a pair of columns whose product is a third column on every row printing all three, by the
product rule `hours_rate` uses (document-forms FR-21). (b) Pay columns: a column whose section totals each equal the rows they cover. (c) Of two
pay columns, this period is the one that is never larger. (d) Headings break ties and are the only guide when nothing else decides. (e) One pay
column with no heading is this period. The numbers win over contradicting headings (FR-58, a guess record), and two columns the numbers can't tell
apart are guessed (FR-59, a guess record). The summary box (FR-75) is told from its sums. Every guess is a `Guess` with the note shown with the
record (D6: a note, never a review reason); `PaystubTables.notes` lists their texts.

The adapter (plan P4) hands Record the pay tables in the shape `anchor_paystub` already reads: `adapt` turns each engine table into rows and
cells whose line ids are the evidence lines the model is shown (`layout_context.project_page`), and `for_lines` keeps what lies in one part of a
file. Both are as pure as the rest. Not here (SL-04 and later): the summary box in Record, unclassified rows, section-total mismatch notes,
unplaced notes, the viewer data and splitting.
"""

from dataclasses import dataclass, field, replace
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations
import re
from types import SimpleNamespace

from ..core.money import EXPONENTS
from ..documents import pay_tables
from ..documents.layout_context import native_page, project_page
from ..documents.table_engine import value_of
from .document_checks import product

HEADINGS_OVERRULED = "headings_overruled"
COLUMNS_GUESSED = "columns_guessed"
GROUP_GUESSED = "group_guessed"
BOX_COLUMNS_GUESSED = "box_columns_guessed"
SPLIT_CHANGED = "split_changed"
SECTION_TOTALS = ("gross", "earnings", "taxes", "deductions")  # Net pay is not a section total (FR-57 b).
# The column words of documents/extraction.py COLUMN_WORDS (copied: extraction imports this module).
COLUMN_WORDS = re.compile(r"\b(?:(?P<current>current|this\s+(?:pay\s+)?period)|(?P<ytd>ytd|year[ -]?to[ -]?date)|(?P<hours>hours?|hrs)|(?P<rate>rate))\b",
                          re.IGNORECASE)
BOX_NAMES = (("net", re.compile(r"\bnet\b", re.IGNORECASE)), ("gross", re.compile(r"\bgross\b", re.IGNORECASE)),
             ("deductions", re.compile(r"\bdeductions?\b", re.IGNORECASE)), ("taxes", re.compile(r"\btax(?:es)?\b", re.IGNORECASE)))


# --- Contracts (plan P2) -------------------------------------------------------------------------------------------------

@dataclass
class Roles:
    table_id: str
    roles: dict[str, str]  # Column id to current, ytd, hours, rate or other.
    decided_by: str  # numbers, headings or guess.


@dataclass
class Guess:
    kind: str  # headings_overruled, columns_guessed, group_guessed, box_columns_guessed or split_changed
    page: int
    table_id: str | None  # The pay table (or the summary box) the guess concerns.
    text: str  # The note shown with the record.


@dataclass
class BoxRead:
    """A summary box read (FR-75): what each column is, which row is this period, and the four totals of each."""
    id: str
    page: int
    columns: dict[str, str]  # Column id to gross, taxes, deductions, net or other.
    rows: dict[str, pay_tables.PayRow]  # current and ytd.
    current: dict[str, pay_tables.Token]  # gross, taxes, deductions, net: the tokens printed on the this-period row.
    ytd: dict[str, pay_tables.Token]
    decided_by: str  # numbers or guess.


@dataclass
class PaystubTables:
    tables: list[pay_tables.PayTable]  # The pay tables (SL-03's adapter turns them into Record's table shape).
    other_tables: list[pay_tables.PayTable]  # Deposit, leave and other tables set aside: their rows are no pay lines (FR-56).
    roles: list[Roles]  # One per pay table, in the same order.
    box: dict | None  # {current: {gross, taxes, deductions, net: Token}, ytd: {...}} of the first summary box, else None.
    boxes: list[BoxRead]
    notes: list[str]  # The guesses' texts, in order.
    guesses: list[Guess]
    unplaced: list[pay_tables.Unplaced]
    pages: set[int]  # Pages holding an engine pay table or summary box.
    pages_without_tables: list[int]
    viewer: list[dict] = field(default_factory=list)  # Filled with the tables tab's data by a later slice.
    adapted: list = field(default_factory=list)  # `tables` in Record's shape (P4), on the pages Record can read; roles by cell index.
    engine_pages: set[int] = field(default_factory=set)  # Pages holding an adapted pay table: Record takes its cells there.
    lines_of: dict[str, str] = field(default_factory=dict)  # A layout line id to the evidence line id that holds its words.
    line_pages: set[int] = field(default_factory=set)  # Pages that have evidence lines.
    fallback_pages: set[int] = field(default_factory=set)  # Pages with a pay table whose columns all ended other: Record doesn't trust the engine there.


# --- Headings and numbers ------------------------------------------------------------------------------------------------

def heading_role(text):
    """The role a column's heading words name: current, ytd, hours, rate, or None. Words naming two things (YTD Hours) name none."""
    named = {match.lastgroup for match in COLUMN_WORDS.finditer(text)}
    if len(named) == 1:
        return named.pop()
    return None


def minor(value, currency):
    return int((value * Decimal(10) ** EXPONENTS[currency]).quantize(Decimal(1), ROUND_HALF_UP))


def multiplies(first, second, third):
    """first × second equals third by the hours × rate rule (`document_checks.product`: rounded half up, within one minor unit)."""
    currency = third.value[2] or "USD"
    if currency not in EXPONENTS:
        return False
    result = product(first.text, second.text, minor(value_of(third), currency), currency, "")
    return result is not None and result[2]


def places(table, column):
    """The most decimal places printed in a column's rows (a rate prints more than hours)."""
    return max((-row.amounts[column].value[0].as_tuple().exponent for row in table.rows if column in row.amounts), default=0)


def product_columns(table):
    """(a): the (a, b, p) column triples where a × b = p on every row printing all three, and on at least one."""
    ids = [column.id for column in table.columns]
    found = []
    for first, second in combinations(ids, 2):
        for third in ids:
            if third in (first, second):
                continue
            rows = [row for row in table.rows if {first, second, third} <= row.amounts.keys()]
            if rows and all(multiplies(row.amounts[first], row.amounts[second], row.amounts[third]) for row in rows):
                found.append((first, second, third))
    return found


def hours_and_rate(table, triple, head):
    """(hours, rate) of a matching pair: the rate is the column printing more decimal places, else the one headed Rate, else the right one."""
    first, second, _ = triple
    one, two = places(table, first), places(table, second)
    if one != two:
        rate = first if one > two else second
    elif head[first] == "rate" or head[second] == "hours":
        rate = first
    elif head[second] == "rate" or head[first] == "hours":
        rate = second
    else:
        rate = second  # Hours are printed before the rate.
    return (first if rate == second else second), rate


def products(table, head):
    """(a) as (products, hours of each product, rate), or None when the pairs don't settle it: one pair, or two that share the rate column."""
    triples = product_columns(table)
    if len(triples) == 1:
        hours, rate = hours_and_rate(table, triples[0], head)
        return [triples[0][2]], {triples[0][2]: hours}, rate
    if len(triples) == 2 and triples[0][2] != triples[1][2]:
        shared = set(triples[0][:2]) & set(triples[1][:2])
        if len(shared) == 1:
            [rate] = shared
            by_product = {third: next(column for column in (first, second) if column != rate) for first, second, third in triples}
            return sorted(by_product, key=[column.id for column in table.columns].index), by_product, rate
    return None


def pay_columns(table):
    """(b): the columns with at least one section total, each of which equals the sum of the rows it covers (since the previous total or the
    start of the section)."""
    entries = sorted([*table.rows, *table.totals], key=lambda entry: entry.row)
    verdicts = {}
    for position, entry in enumerate(entries):
        if not isinstance(entry, pay_tables.PayTotal) or entry.kind not in SECTION_TOTALS:
            continue
        covered = []
        for earlier in reversed(entries[:position]):
            if isinstance(earlier, pay_tables.PayTotal) or (covered and earlier.section != covered[-1].section):
                break
            covered.append(earlier)
        for column, token in entry.values.items():
            total = sum((value_of(row.amounts[column]) for row in covered if column in row.amounts), Decimal(0))
            verdicts.setdefault(column, []).append(total == value_of(token))
    return {column for column, verdict in verdicts.items() if all(verdict)}


def smaller_on(table, first, second):
    """(votes for first, votes for second, voting rows): rows printing both, neither negative; the smaller column of a row gets its vote."""
    votes, voters = [0, 0], 0
    for row in table.rows:
        if first in row.amounts and second in row.amounts:
            one, two = value_of(row.amounts[first]), value_of(row.amounts[second])
            if one < 0 or two < 0:
                continue
            voters += 1
            if one < two:
                votes[0] += 1
            elif two < one:
                votes[1] += 1
    return votes[0], votes[1], voters


def by_heading(first, second, head):
    """Which of two columns the headings make this period, or None when they don't say."""
    one = head[first] == "current" or head[second] == "ytd"
    two = head[second] == "current" or head[first] == "ytd"
    return first if one and not two else second if two and not one else None


def order(table, first, second, head):
    """(c): (this period, year to date, decided by, basis) of two pay columns, `first` being the left one. The basis is set only for a guess:
    "left" (no basis at all) or "more" (the column smaller on more rows)."""
    one, two, voters = smaller_on(table, first, second)
    if one and not two:
        return first, second, "numbers", None
    if two and not one:
        return second, first, "numbers", None
    chosen = by_heading(first, second, head)
    if chosen is not None:
        return chosen, (second if chosen == first else first), "headings", None
    if voters and not one and not two:
        return first, second, "numbers", None  # Every voting row is equal: either column gives the right values (a first paycheck).
    if one == two:
        return first, second, "guess", "left"
    return (first, second, "guess", "more") if one > two else (second, first, "guess", "more")


def later_year(table, current, others):
    """The one of several other pay columns that is never smaller than this period's, else None."""
    found = [other for other in others if smaller_on(table, current, other)[1] == 0 and smaller_on(table, current, other)[0] > 0]
    return found[0] if len(found) == 1 else None


def heading_roles(table, head, taken):
    """(d): per role, the one column whose heading names it (this period, year to date, hours or rate), among the columns not already taken."""
    named = {}
    for column in table.columns:
        if column.id not in taken and head[column.id] is not None:
            named.setdefault(head[column.id], []).append(column.id)
    return {role: columns[0] for role, columns in named.items() if len(columns) == 1}


# --- The role pass (plan P5) -------------------------------------------------------------------------------------------

def side(table, column):
    return "left" if column == table.columns[0].id else "right"


def guess_text(page, table, current, basis):
    if basis == "left":
        return f"Page {page}: the {side(table, current)} column was taken as this period; the printed amounts didn't tell the two columns apart."
    return (f"Page {page}: the {side(table, current)} column was taken as this period, because it was the smaller one on more lines; "
            "the printed amounts didn't tell the two columns apart.")


def overruled_text(page, current, ytd, label, head):
    wrong_current = head[current] == "ytd"
    wrong_ytd = ytd is not None and head[ytd] == "current"
    if wrong_current and wrong_ytd:
        return (f'Page {page}: the column headed "{label[current]}" was taken as this period and the one headed "{label[ytd]}" as year to date, '
                "because the printed amounts say so.")
    if wrong_current:
        return f'Page {page}: the column headed "{label[current]}" was taken as this period, because the printed amounts say so.'
    return f'Page {page}: the column headed "{label[ytd]}" was taken as year to date, because the printed amounts say so.'


def decide(table):
    """(roles, guesses, found) of one table. `found` says the numbers found a pay column ((a) or (b)) or the headings name this period or year to
    date: the table is a pay table (P3.8)."""
    ids = [column.id for column in table.columns]
    label = {column.id: " ".join(column.labels) for column in table.columns}
    head = {column: heading_role(text) for column, text in label.items()}
    page = table.pages[0]
    roles, guesses = dict.fromkeys(ids, "other"), []
    found_products = products(table, head)
    pay = pay_columns(table)
    found = bool(found_products) or bool(pay) or any(role in ("current", "ytd") for role in head.values())
    payable = [column for column in ids if column in pay]
    current = ytd = None
    decided_by, basis = "numbers", None
    if found_products:
        made, hours, rate = found_products
        if len(made) == 1:
            current = made[0]
            others = [column for column in payable if column != current]
            ytd = others[0] if len(others) == 1 else later_year(table, current, others) if others else None
        else:
            current, ytd, decided_by, basis = order(table, made[0], made[1], head)
        roles[rate], roles[hours[current]] = "rate", "hours"
        taken = {rate, hours[current], current, ytd, *made}
    elif len(payable) == 2:
        current, ytd, decided_by, basis = order(table, *payable, head)
        taken = set(payable)
    elif len(payable) == 1:
        if head[payable[0]] == "ytd":
            ytd, decided_by = payable[0], "headings"
        else:
            current, decided_by = payable[0], "headings" if head[payable[0]] == "current" else "numbers"
        taken = set(payable)
    else:
        decided_by, taken = "headings", set()  # The headings are the only guide (d).
    named = heading_roles(table, head, taken | set(payable))
    if not found_products:
        for role in ("hours", "rate"):
            if role in named:
                roles[named[role]] = role
    if current is None and "current" in named and not found_products:
        current = named["current"]
    if ytd is None and "ytd" in named:
        ytd = named["ytd"]
    if current is not None:
        roles[current] = "current"
    if ytd is not None:
        roles[ytd] = "ytd"
    if basis is not None:
        decided_by = "guess"
        guesses.append(Guess(COLUMNS_GUESSED, page, table.id, guess_text(page, table, current, basis)))
    elif decided_by == "numbers" and current is not None and (head[current] == "ytd" or (ytd is not None and head[ytd] == "current")):
        guesses.append(Guess(HEADINGS_OVERRULED, page, table.id, overruled_text(page, current, ytd, label, head)))
    return Roles(table.id, roles, decided_by), guesses, found


# --- The summary box (plan P6) -----------------------------------------------------------------------------------------

def box_name(text):
    return next((name for name, pattern in BOX_NAMES if pattern.search(text)), None)


def this_period_row(box):
    """The box's this-period row: the one smaller in gross; equal, the one whose label names it; else the upper one."""
    first, second = box.rows
    gross = max(first.amounts, key=lambda column: value_of(first.amounts[column]))
    one, two = value_of(first.amounts[gross]), value_of(second.amounts[gross])
    if one != two:
        return (first, second) if one < two else (second, first)
    named = [heading_role(row.label) for row in (first, second)]
    later_first = named[0] == "ytd" or named[1] == "current"
    earlier_first = named[0] == "current" or named[1] == "ytd"
    return (second, first) if later_first and not earlier_first else (first, second)


def taxes_and_deductions(rest, heads):
    """(taxes, deductions, named): the two remaining columns told apart by the heading words, else left is taxes (FR-75)."""
    taxes = [column for column in rest if heads[column] == "taxes"]
    deductions = [column for column in rest if heads[column] == "deductions"]
    if len(taxes) == 1 and len(deductions) <= 1:
        return taxes[0], next(column for column in rest if column != taxes[0]), True
    if len(deductions) == 1 and not taxes:
        return next(column for column in rest if column != deductions[0]), deductions[0], True
    return rest[0], rest[1], False


def read_box(box):
    """(BoxRead, guesses) of a summary box, or (None, []) when no three columns add up to the gross column on both rows."""
    now, later = this_period_row(box)
    ids = [column.id for column in box.columns]
    heads = {column.id: box_name(" ".join(column.labels)) for column in box.columns}
    gross = max(now.amounts, key=lambda column: value_of(now.amounts[column]))
    trios = [trio for trio in combinations([column for column in ids if column in now.amounts and column != gross], 3)
             if all(sum(value_of(row.amounts[column]) for column in trio) == value_of(row.amounts[gross]) for row in (now, later))]
    if not trios:
        return None, []
    trio = max(trios, key=lambda found: sum(heads[column] in ("taxes", "deductions", "net") for column in found))
    net = max(trio, key=lambda column: value_of(now.amounts[column]))
    taxes, deductions, named = taxes_and_deductions([column for column in trio if column != net], heads)
    columns = {column: "other" for column in ids} | {gross: "gross", taxes: "taxes", deductions: "deductions", net: "net"}
    guesses = []
    if not named:
        guesses.append(Guess(BOX_COLUMNS_GUESSED, box.page, box.id, f"Page {box.page}: in the summary box, the left of the two columns was taken as "
                             "taxes and the other as deductions, because no heading named them."))
    if any(name in ("gross", "net") and columns[column] != name for column, name in heads.items()):
        guesses.append(Guess(BOX_COLUMNS_GUESSED, box.page, box.id, f"Page {box.page}: in the summary box, a heading named a column differently "
                             "from what its amounts add up to, so the columns were taken from the amounts."))
    names = {name: column for column, name in columns.items() if name != "other"}
    return BoxRead(box.id, box.page, columns, {"current": now, "ytd": later}, {name: now.amounts[column] for name, column in names.items()},
                   {name: later.amounts[column] for name, column in names.items()}, "guess" if guesses else "numbers"), guesses


# --- The adapter (plan P4) -----------------------------------------------------------------------------------------------

PAGE_ID = re.compile(r"page-(\d+)-")


def page_number(line_id):
    found = PAGE_ID.match(line_id or "")
    return int(found.group(1)) if found else None


class PageMap:
    """Where a native page's words are in the evidence the model is shown: a word is in a projected table's row (and cell), else in a layout line."""

    def __init__(self, page):
        lines, tables = project_page(page)
        self.text = {line.id: line.text for line in lines}
        self.order = [line.id for line in lines]
        self.line_of, self.cell_of, self.layout_of, self.native_rows = {}, {}, {}, set()
        for table in tables:
            for row in [*table.header_rows, *table.rows]:
                self.native_rows.add(row.line_id)
                for cell in row.cells:
                    for word_id in cell.word_ids:
                        self.line_of[word_id], self.cell_of[word_id] = row.line_id, cell
        for line in page.layout.lines:
            for word_id in line.word_ids:
                self.layout_of[word_id] = line.id
                if line.id in self.text:
                    self.line_of.setdefault(word_id, line.id)
        self.words = {word.id: word.text for word in page.layout.words}

    def lines(self, word_ids):
        return list(dict.fromkeys(self.line_of[word_id] for word_id in word_ids if word_id in self.line_of))

    def layout_lines(self, word_ids):
        return list(dict.fromkeys(self.layout_of[word_id] for word_id in word_ids if word_id in self.layout_of))

    def cites(self, word_ids):
        """(evidence line id, the words of word_ids printed in it) per line, in order: what a label or heading of several lines cites."""
        found = {}
        for word_id in word_ids:
            if word_id in self.line_of:
                found.setdefault(self.line_of[word_id], []).append(self.words.get(word_id, ""))
        return [(line, " ".join(words)) for line, words in found.items()]

    def native_cell(self, word_ids, line_ids):
        """The projected cell id when the words are all one cell of the one projected table row the printed row is (FR-66), else None."""
        cells = {self.cell_of[word_id].id for word_id in word_ids if word_id in self.cell_of}
        mapped = all(word_id in self.cell_of for word_id in word_ids)
        return next(iter(cells)) if word_ids and mapped and len(cells) == 1 and len(line_ids) == 1 and line_ids[0] in self.native_rows else None


def cell_of(identity, line_id, quote, word_ids, mapping, line_ids=(), cites=None, native=False):
    return SimpleNamespace(id=(mapping.native_cell(word_ids, list(line_ids)) if native else None) or identity, line_id=line_id, quote=quote,
                           word_ids=list(word_ids), source_line_ids=mapping.layout_lines(word_ids), cites=cites)


def adapt_row(table, row, kind, columns, mapping):
    """One engine row or total as Record's row: cell 0 is the label, then one cell per amount column in column order (P4)."""
    identity = f"{table.id}-row-{row.row}"
    printed = row.values if kind else row.amounts
    amounts = {word_id for token in printed.values() for word_id in token.word_ids}
    stray = {word_id for token in getattr(row, "stray", []) for word_id in token.word_ids}
    label_words = [word_id for word_id in row.word_ids if word_id not in amounts | stray]
    ordered = [*label_words, *[word_id for word_id in row.word_ids if word_id not in label_words]]
    line_ids = mapping.lines(ordered) or list(getattr(row, "line_ids", None) or [row.line_id])
    line_id = line_ids[0] if line_ids else ""
    shown = mapping.cites(label_words)
    label = cell_of(f"{identity}-cell-0", mapping.line_of.get(label_words[0], line_id) if label_words else line_id, row.label, label_words, mapping,
                    mapping.lines(label_words), shown if len(shown) > 1 else None, native=True)
    cells = [label]
    for number, column in enumerate(columns, 1):
        token = printed.get(column.id)
        words = token.word_ids if token else []
        cells.append(cell_of(f"{identity}-cell-{number}", mapping.line_of.get(words[0], line_id) if words else line_id, token.text if token else "", words,
                             mapping, mapping.lines(words), native=True))
    return SimpleNamespace(id=identity, line_id=line_id, line_ids=line_ids, cells=cells, total=kind is not None, kind=kind, label=row.label,
                           section=getattr(row, "section", None), page=row.page)


def adapt_header(table, columns, mapping, first):
    identity = f"{table.id}-row-0"
    label = cell_of(f"{identity}-cell-0", first, "", [], mapping)
    cells = [label]
    for number, column in enumerate(columns, 1):
        words = [word_id for group in column.label_words for word_id in group]
        shown = [(mapping.line_of.get(group[0]), text) for group, text in zip(column.label_words, column.labels) if group]
        shown = [(line, text) for line, text in shown if line]
        cells.append(cell_of(f"{identity}-cell-{number}", shown[0][0] if shown else first, " ".join(column.labels), words, mapping, cites=shown or None))
    return SimpleNamespace(id=identity, line_id=first, cells=cells)


def adapt(pay, evidence):
    """The pay tables in Record's table shape (plan P4): `SimpleNamespace(id, page, source="pay_engine", header_rows, rows, roles)`. Each row is
    `(id "<table>-row-<r>", line_id, line_ids, cells, total)`, cells `(id, line_id, quote, word_ids, source_line_ids)`: cell 0 is the label, then one per
    amount column (a blank quote when empty). Totals are rows too, flagged `total` with their `kind`. A row's line ids are the evidence lines (what the
    model is shown) that hold its words; `roles` maps a cell index to its role. Only rows on pages Record reads as native text are kept."""
    maps = {page.number: PageMap(page) for page in evidence.pages if page.method == "embedded_text" and page.layout is not None and native_page(page)}
    distrusted = untrusted_pages(pay)
    for number in distrusted:
        maps.pop(number, None)
    made = []
    for table, roles in zip(pay.tables, pay.roles):
        entries = sorted([*((row, None) for row in table.rows), *((total, total.kind) for total in table.totals)], key=lambda entry: entry[0].row)
        rows = [adapt_row(table, row, kind, table.columns, maps[row.page]) for row, kind in entries if row.page in maps]
        if not rows:
            continue
        first = next((row.line_id for row in rows if row.line_id), "")
        mapping = maps[table.pages[0]] if table.pages[0] in maps else maps[rows[0].page]
        made.append(SimpleNamespace(id=table.id, page=rows[0].page, pages=sorted({row.page for row in rows}), source="pay_engine",
                                    header_rows=[adapt_header(table, table.columns, mapping, first)], rows=rows, spans=spans_of(rows, maps),
                                    roles={number: roles.roles[column.id] for number, column in enumerate(table.columns, 1)}))
    return made


def untrusted_pages(pay):
    """Pages with a pay table none of whose columns is this period, year to date, hours or rate (a side-by-side partner whose headings and totals
    decided nothing): the engine's rows there would carry no money, so Record keeps the printed table's cells on such a page and says so (FR-64)."""
    return {page for table, roles in zip(pay.tables, pay.roles) if set(roles.roles.values()) <= {"other"} for page in table.pages}


def spans_of(rows, maps):
    """The evidence lines from a table's first row to its last on each page: its section titles and blank lines are inside it, as a printed table's
    rows are, so the model is asked about them together (extraction.paystub_chunks)."""
    spans = set()
    for page in sorted({row.page for row in rows}):
        order = maps[page].order
        positions = [order.index(line_id) for row in rows if row.page == page for line_id in row.line_ids if line_id in order]
        spans |= set(order[min(positions):max(positions) + 1]) if positions else set()
    return spans


def evidence_index(evidence):
    """(layout line id to its evidence line id, the pages that have evidence lines) for the native pages of a reading."""
    lines_of, pages = {}, set()
    for page in evidence.pages:
        if page.method == "embedded_text" and page.layout is not None and native_page(page):
            mapping = PageMap(page)
            pages |= {page.number for line_id in mapping.text}
            for line in page.layout.lines:
                found = mapping.line_of.get(line.word_ids[0])
                if found:
                    lines_of[line.id] = found
        else:
            pages |= {number for number in (page_number(line.id) for line in page.lines) if number is not None}
    return lines_of, pages


def for_lines(pay, line_ids):
    """What lies in one part of a file (plan P7.1): the rows and totals whose evidence line is in `line_ids`, the boxes, unplaced lines, other tables
    and guesses (and the notes they carry) of those lines, and the pages without a table among the part's pages."""
    ids = set(line_ids)
    mine = lambda *layout: any(pay.lines_of.get(line, line) in ids for line in layout)  # noqa: E731
    adapted = [replace_rows(table, [row for row in table.rows if row.line_id in ids]) for table in pay.adapted]
    adapted = [table for table in adapted if table.rows]
    kept = {table.id for table in adapted}
    pairs = [(table, roles) for table, roles in zip(pay.tables, pay.roles) if table.id in kept]
    boxes = [box for box in pay.boxes if mine(*(line for row in box.rows.values() for line in row.line_ids))]
    unplaced = [line for line in pay.unplaced if mine(line.line_id)]
    pages = {page for page in (page_number(line_id) for line_id in ids) if page is not None}
    owners = kept | {box.id for box in boxes}
    guesses = [guess for guess in pay.guesses if guess.table_id is None or guess.table_id in owners]
    others = [table for table in pay.other_tables if any(mine(*row.line_ids) for row in table.rows)]
    engine_pages = {row.page for table in adapted for row in table.rows}
    return replace(pay, tables=[table for table, _ in pairs], roles=[roles for _, roles in pairs], other_tables=others, boxes=boxes,
                   box=({"current": boxes[0].current, "ytd": boxes[0].ytd} if boxes else None), notes=[guess.text for guess in guesses], guesses=guesses,
                   unplaced=unplaced, pages=engine_pages | {box.page for box in boxes}, pages_without_tables=[page for page in sorted({*pay.pages_without_tables, *pay.fallback_pages}) if page in pages],
                   adapted=adapted, engine_pages=engine_pages)


def replace_rows(table, rows):
    return SimpleNamespace(**{**vars(table), "rows": rows})


# --- Entry point ------------------------------------------------------------------------------------------------------

def read(evidence):
    """Read a saved PDF reading (`PDFResult`) into pay tables, their column roles, the summary box and the guesses."""
    reading = pay_tables.read(evidence)
    decided = {table.id: decide(table) for table in reading.tables}
    pay = {table_id for table_id, (_, _, found) in decided.items() if found}
    pay |= {table.partner for table in reading.tables if table.id in pay and table.partner}
    tables = [table for table in reading.tables if table.id in pay]
    others = [table for table in reading.tables if table.id not in pay]
    roles = [decided[table.id][0] for table in tables]
    guesses = [guess for table in tables for guess in decided[table.id][1]]
    boxes = []
    for found in reading.boxes:
        box, made = read_box(found)
        if box is not None:
            boxes.append(box)
            guesses += made
    pages = {page for table in tables for page in table.pages} | {box.page for box in boxes}
    without = sorted(set(reading.pages_without_tables) | ({page for table in others for page in table.pages} - pages))
    found = PaystubTables(tables, others, roles, ({"current": boxes[0].current, "ytd": boxes[0].ytd} if boxes else None), boxes,
                          [guess.text for guess in guesses], guesses, [line for line in reading.unplaced if line.page in pages], pages, without)
    found.fallback_pages = untrusted_pages(found)
    found.adapted = adapt(found, evidence)
    found.engine_pages = {row.page for table in found.adapted for row in table.rows}
    found.lines_of, found.line_pages = evidence_index(evidence)
    return found
