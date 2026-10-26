"""Read a PDF's saved layout into transaction rows for the import (specs/account-import-pdf, docs/documents.md "PDFs").

`analyze` is pure and deterministic: it reads one saved reading and the user's choices, and returns tables, rows, issues
and counts. It touches no store, makes no model call and never opens the PDF. Native tables are used as the reader built
them. Where the reader built none (a page with no headings, a column blank on every row), or ended a table early (a row with
no alphabetic description), the rows are rebuilt from the saved words, grouped into visual rows by baseline with the
reader's own rule. Nothing is joined or guessed: a row that does not fit its columns is rejected with its page, row and
reason. The row limits and the account lookup live elsewhere (`ledger.py`).
"""

from dataclasses import dataclass, field
from datetime import date
import json
import logging
import math
import re
from statistics import median

from ..core.logs import log_failure
from ..core.money import MoneyError, currency_code, to_minor
from ..documents.pdf_layout import PDFTable, point, visual_box
from ..documents.pdf_reader import PDF_VERSIONS, PDFResult, read_result
from .tabular import DATE_FORMATS, HEADER_NAMES

log = logging.getLogger(__name__)

MAX_ROWS, MAX_CELL, MAX_ISSUES = 20_000, 2000, 200
# Bump when what the analyzer finds changes (tables, last fours, currency): every PDF reading is indexed again at the next start.
ANALYZER_VERSION = 2  # 2: FR-30, a number that continues the description is description text (specs/statement-accounts).
BALANCE_NAMES = ("balance", "running balance", "new balance", "ending balance")  # Never an amount (PDF import only).
ROLES = ("date", "description", "amount", "debit", "credit")
AMOUNT_ROLES = ("amount", "debit", "credit")
SIGN_DEFAULTS = {"credit_card": "positive_is_outflow", "checking": "negative_is_outflow", "savings": "negative_is_outflow"}
BLOCKING = ("reading_without_layout", "document_currency_mismatch")  # Issue codes that stop the import.
FLAG_CODES = ("pdf_layout_review", "pdf_table_ambiguous")
NO_LAYOUT = "This PDF was read before transaction import existed. Read this document again to import its transactions."

# FR-06's printed dates, and the plan's amount shape ("Rows"): digit-led digits, commas and periods, whose parse is decided later.
DATE_WORD = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2}|/\d{4})?|\d{4}-\d{2}-\d{2}")
AMOUNT_WORD = re.compile(r"[-+(]?[$€£¥]?\d[\d,.]*(?:\)|-|CR|DR|[A-Za-z]{3})?")
CODE_WORD = re.compile(r"[A-Z]{3}")
SHAPE = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?|(\d{4})-(\d{2})-(\d{2})")
CURRENCY_LINE = re.compile(r"^\s*currency\s*:\s*([A-Za-z]{3})\s*$", re.IGNORECASE | re.MULTILINE)
PRINTED_CODE = re.compile(r"(.*?)\s*([A-Za-z]{3})")
# FR-13: the printed forms of an account's last four. A mask is two or more of X, x, *, • or … (spaces and dashes may separate its parts).
LAST_FOUR = [re.compile(pattern, re.IGNORECASE if ignore else 0) for pattern, ignore in (
    (r"\bending(?:\s+in)?\s+(\d{4})(?!\d)", True),
    (r"(?<![A-Za-z0-9])[Xx*•…]{2,}(?:[ -]*[Xx*•…]+)*[ -]*(\d{4})(?!\d)", False),
    (r"(?<![*\w])\*(\d{4})(?!\d)", False),
    (r"(?:…|\.\.\.)(\d{4})(?!\d)", False))]


class PDFImportError(ValueError):
    """A limit or an unusable choice: the whole import is refused, naming the limit."""


@dataclass
class ImportIssue:
    page: int | None
    row: int | None
    code: str
    message: str


@dataclass
class ImportRow:
    key: str  # "<table_id>:<row>"
    page: int
    table_id: str
    row: int
    date: str  # As printed.
    description: str
    amount: str
    posted_date: str | None
    amount_minor: int | None
    currency: str | None
    ticked: bool
    labels: list[str]
    rejected: str | None
    cell_ids: list[str]
    line_ids: list[str]
    word_ids: list[str]
    continued_from: int | None


@dataclass
class ImportTable:
    id: str
    page: int
    kind: str  # transactions, rebuilt, continuation or other
    linked_to: str | None
    headings: list[str]
    columns: dict[str, str]  # Role to heading text.
    rows: list[str]  # Keys of its rows in Analysis.rows (empty unless selected).
    row_count: int  # Data rows seen, whether or not the table is selected.
    selected: bool
    selectable: bool


@dataclass
class Analysis:
    tables: list[ImportTable]
    rows: list[ImportRow]
    issues: list[ImportIssue]
    counts: dict[str, int]
    required: list[str]  # What must still be chosen: year, date_format, sign.
    mapping: dict[str, str]
    last_fours: dict[str, int]  # Each distinct NNNN printed, with the page of its first occurrence.
    document_currency: str | None
    sign_default: str | None
    sign: str | None  # The sign convention in force: the choice, else the account type's default.
    signed: bool = False  # A selected table has a single Amount column, so the sign applies (FR-07), whatever the first table has.

    @property
    def blocked(self):
        """The reason the import cannot go ahead whatever the user chooses, or None."""
        return next((issue.message for issue in self.issues if issue.code in BLOCKING), None)


# --- Visual rows ---------------------------------------------------------------------------------------------------------

class PageView:
    """A native page's saved words grouped into visual rows (plan "Visual rows"): a word's baseline is its first character's
    origin through page_to_preview, else the bottom of its box; a new row starts when a baseline differs by more than a quarter
    of the font size from the first word of the row. This re-implements the reader's rule, which is a closure (pdf_layout.py)."""

    def __init__(self, layout):
        self.layout = layout
        matrix = layout.page_to_preview
        glyphs = [char for char in layout.characters if char.bbox and not char.generated and char.text and not char.text.isspace()]
        self.size = max(1, median(char.font_size for char in glyphs) * math.hypot(matrix[0], matrix[1])) if glyphs else 1
        self.box = {word.id: visual_box(matrix, word.bbox) for word in layout.words}
        self.baseline = {}
        for word in layout.words:
            origin = layout.characters[word.character_indexes[0]].origin
            self.baseline[word.id] = point(matrix, *origin)[1] if origin else self.box[word.id][3]
        groups = []
        for word in sorted(layout.words, key=lambda word: (self.baseline[word.id], self.box[word.id][0])):
            if not groups or abs(self.baseline[word.id] - self.baseline[groups[-1][0].id]) > self.size * 0.25:
                groups.append([])
            groups[-1].append(word)
        self.row_baseline = [self.baseline[group[0].id] for group in groups]
        self.rows = [sorted(group, key=lambda word: self.box[word.id][0]) for group in groups]
        self.row_of = {word.id: index for index, row in enumerate(self.rows) for word in row}
        self.line_of = {word_id: line.id for line in layout.lines for word_id in line.word_ids}

    def runs(self, index):
        """A visual row's runs of words: a word closer than 1.5 font sizes to the one before it joins its run (plan "Heading texts")."""
        groups = []
        for word in self.rows[index]:
            if not groups or self.box[word.id][0] - self.box[groups[-1][-1].id][2] > self.size * 1.5:
                groups.append([])
            groups[-1].append(word)
        return groups

    def texts(self, index):
        """A visual row's texts, as (text, left, right): the text of each run and where it starts and ends."""
        return [(" ".join(word.text for word in run), self.box[run[0].id][0], self.box[run[-1].id][2]) for run in self.runs(index)]

    def lines(self, word_ids):
        return list(dict.fromkeys(self.line_of[word_id] for word_id in word_ids if word_id in self.line_of))


def is_heading(names):
    """A transactions heading has a date name and an amount, debit or credit name (matched stripped and lower-cased)."""
    names = [name.strip().lower() for name in names]
    return any(name in HEADER_NAMES["date"] for name in names) and any(name in HEADER_NAMES[role] for name in names for role in AMOUNT_ROLES)


@dataclass
class Spec:
    """A table's columns: the heading texts, the role each plays, and the horizontal span each owns. Each span runs from the
    midpoint after the previous heading to the midpoint before the next; the first and last are open to the page edges."""
    texts: list[str]
    roles: list[str | None]
    spans: list[tuple[float, float]]
    columns: dict[str, int]  # Role to index into texts.
    source: list[int]  # A native table's column for each text.


def assign(texts):
    """The role of each heading (`tabular.HEADER_NAMES`, leftmost wins). A balance heading is never an amount, debit or credit,
    and a single Amount column takes the place of Debit/Credit headings, as `tabular.detect` does."""
    roles, columns = [None] * len(texts), {}
    for index, text in enumerate(texts):
        name = text.strip().lower()
        if name in BALANCE_NAMES:
            roles[index] = "balance"
            continue
        for role in ROLES:
            if name in HEADER_NAMES[role] and role not in columns:
                columns[role] = index
                roles[index] = role
                break
    if "amount" in columns:
        for role in ("debit", "credit"):
            if role in columns:
                roles[columns.pop(role)] = None
    return roles, columns


def make_spec(items, source=()):
    infinity = float("inf")
    cuts = [(items[index][2] + items[index + 1][1]) / 2 for index in range(len(items) - 1)]
    texts = [text for text, _, _ in items]
    roles, columns = assign(texts)
    return Spec(texts, roles, list(zip([-infinity] + cuts, cuts + [infinity])), columns, list(source))


def place(spans, box):
    """The span holding a word's horizontal centre, and whether the word fits it: it straddles when its box crosses a midpoint
    by more than 20% of its own width (plan "Column positions")."""
    centre = (box[0] + box[2]) / 2
    index = next(index for index, (left, right) in enumerate(spans) if left <= centre < right)
    allowance = (box[2] - box[0]) * 0.2
    return index, spans[index][0] - allowance <= box[0] and box[2] <= spans[index][1] + allowance


def touches(span, box):
    """A word falls in a span (its centre is there) or straddles it (it crosses into it by more than 20% of its width)."""
    centre = (box[0] + box[2]) / 2
    return span[0] <= centre < span[1] or min(box[2], span[1]) - max(box[0], span[0]) > (box[2] - box[0]) * 0.2


@dataclass
class Raw:
    """One data row as printed, before dates and amounts are read."""
    row: int
    date: str = ""
    description: str = ""
    debit: str = ""
    credit: str = ""
    amount: str = ""
    cell_ids: list[str] = field(default_factory=list)
    line_ids: list[str] = field(default_factory=list)
    word_ids: list[str] = field(default_factory=list)
    reject: str | None = None
    shape: tuple | None = None


def joined_amounts(view, spec, index, amount_columns):
    """FR-30: the amount-shaped words that continue the description's printed text. A run of words whose first word is placed in
    the Description column holds description text, so each later amount-shaped word in it is joined to the description. A joined
    word stays an amount when (a) its whole box lies inside one amount column's span, with no tolerance, and (b) it is the only
    amount-shaped word of the row centred in an amount column; a Balance column is not an amount column. Returns the joined words
    that stay description text."""
    description = spec.columns.get("description")
    if description is None:
        return []
    joined = [word for run in view.runs(index) if place(spec.spans, view.box[run[0].id])[0] == description
              for word in run[1:] if AMOUNT_WORD.fullmatch(word.text)]
    centred = [word for word in view.rows[index] if AMOUNT_WORD.fullmatch(word.text)
               and any(spec.spans[column][0] <= (view.box[word.id][0] + view.box[word.id][2]) / 2 < spec.spans[column][1] for column in amount_columns)]
    return [word for word in joined if not (len(centred) == 1 and any(spec.spans[column][0] <= view.box[word.id][0] and view.box[word.id][2] <= spec.spans[column][1]
                                                                      for column in amount_columns))]


def visual_row(view, spec, index, row):
    """A visual row as a candidate row (plan "Rows"), or None when it is not one. A candidate has a date-like word in or
    straddling the date span and an amount-like word in or straddling an amount, debit or credit span (a Balance-only
    amount makes none). It is accepted when its date and amounts each sit wholly inside one span and each amount column
    holds exactly one amount (and at most the currency code after it); otherwise it is rejected with the reason. An
    amount-shaped word that continues the description's text is description text, not an amount (FR-30, `joined_amounts`)."""
    words = view.rows[index]
    date_span = spec.columns["date"]
    amount_columns = [spec.columns[role] for role in AMOUNT_ROLES if role in spec.columns]
    taken = {word.id for word in joined_amounts(view, spec, index, amount_columns)}
    dates = [word for word in words if DATE_WORD.fullmatch(word.text) and touches(spec.spans[date_span], view.box[word.id])]
    candidates = [word for word in words if AMOUNT_WORD.fullmatch(word.text) and any(touches(spec.spans[column], view.box[word.id]) for column in amount_columns)]
    amounts = [word for word in candidates if word.id not in taken]
    if not dates or not amounts and not any(word.id in taken for word in candidates):
        return None
    found, cells = {}, {}
    for word in words:
        column, fits = (spec.columns["description"], True) if word.id in taken else place(spec.spans, view.box[word.id])
        found[word.id] = (column, fits)
        cells.setdefault(column, []).append(word)
    reject = None
    if not amounts:
        reject = "The amount is printed against the description, so it can't be told apart from it."  # P18: never dropped silently.
    elif not all(found[word.id] == (date_span, True) for word in dates):
        reject = "The date doesn't fit a column."
    elif not all(found[word.id][0] in amount_columns and found[word.id][1] for word in amounts):
        reject = "The amount doesn't fit a column."
    else:
        for column in amount_columns:
            held = cells.get(column, [])
            numbers = [word for word in held if AMOUNT_WORD.fullmatch(word.text)]
            other = [word for position, word in enumerate(held) if not AMOUNT_WORD.fullmatch(word.text)
                     and not (CODE_WORD.fullmatch(word.text) and position and AMOUNT_WORD.fullmatch(held[position - 1].text))]
            if len(numbers) > 1:
                reject = f"More than one amount sits in the {spec.texts[column]} column."
            elif other:
                reject = f"Text that is not an amount sits in the {spec.texts[column]} column."
            if reject:
                break

    def text(role):
        return " ".join(word.text for word in cells.get(spec.columns[role], [])) if role in spec.columns else ""

    word_ids = [word.id for word in words]
    return Raw(row=row, date=text("date"), description=text("description"), debit=text("debit"), credit=text("credit"), amount=text("amount"),
               line_ids=view.lines(word_ids), word_ids=word_ids, reject=reject)


def native_spec(view, table):
    """A native transactions table's columns, from the words of its row-0 cells."""
    items = []
    for cell in table.cells:
        if cell.row == 0 and cell.word_ids:
            boxes = [view.box[word_id] for word_id in cell.word_ids]
            items.append((cell.column, cell.text, min(box[0] for box in boxes), max(box[2] for box in boxes)))
    items.sort(key=lambda item: item[2])
    return make_spec([(text, left, right) for _, text, left, right in items], [column for column, _, _, _ in items])


def native_rows(table: PDFTable, spec, view):
    by_cell = {(cell.row, cell.column): cell for cell in table.cells}
    raws = []
    for row in range(1, table.rows):
        cells = [by_cell[(row, column)] for column in range(table.columns) if (row, column) in by_cell]

        text = {role: by_cell[(row, spec.source[spec.columns[role]])].text if (row, spec.source[spec.columns[role]]) in by_cell else ""
                for role in ROLES if role in spec.columns}
        printed = [cell for cell in cells if cell.text]
        raws.append(Raw(row=row, date=text.get("date", ""), description=text.get("description", ""), debit=text.get("debit", ""),
                        credit=text.get("credit", ""), amount=text.get("amount", ""),
                        cell_ids=[cell.id for cell in printed], line_ids=list(dict.fromkeys(line for cell in printed for line in cell.line_ids))))
    return raws


def table_extent(view, table):
    """The baselines of a native table's first and last rows that hold words."""
    rows = {}
    for cell in table.cells:
        rows.setdefault(cell.row, []).extend(view.baseline[word_id] for word_id in cell.word_ids)
    rows = {row: baselines for row, baselines in rows.items() if baselines}
    return (min(rows[min(rows)]), max(rows[max(rows)])) if rows else (0.0, 0.0)


@dataclass
class Entry:
    table: ImportTable
    raws: list[Raw]
    spec: Spec | None
    top: float
    parent: "Entry | None" = None
    flags: list[str] = field(default_factory=list)  # The page's layout issues that flag its rows (FR-09).


# --- Structure -----------------------------------------------------------------------------------------------------------

def page_flags(result):
    flags = {}
    for issue in result.issues:
        match = re.match(r"Page (\d+) ", issue.message)
        if issue.code in FLAG_CODES and match:
            flags.setdefault(int(match.group(1)), []).append(issue)
    return flags


def structure(result, flags, issues):
    """Every table of the reading, in page order, with its rows as printed (not yet read as dates and amounts)."""
    entries, chain = [], None
    for page in result.pages:
        number = page.number
        if page.method != "embedded_text":
            issues.append(ImportIssue(number, None, "scanned_page", f"Page {number} is a scanned page; no rows imported. Use Record for scanned statements."))
            continue
        layout = page.layout
        view = PageView(layout)
        natives, others = [], []
        for table in layout.tables:
            names = [next((cell.text for cell in table.cells if cell.row == 0 and cell.column == column), "") for column in range(table.columns)]
            (natives if is_heading([name for name in names if name]) else others).append((table, names))
        natives.sort(key=lambda item: table_extent(view, item[0])[0])
        page_entries, claimed, continuation = [], set(), False
        if natives:
            for position, (table, names) in enumerate(natives):
                spec = native_spec(view, table)
                top, last = table_extent(view, table)
                next_top = table_extent(view, natives[position + 1][0])[0] if position + 1 < len(natives) else None
                raws = native_rows(table, spec, view)
                margin = view.size * 0.25
                number_below = table.rows
                for index, baseline in enumerate(view.row_baseline):
                    if baseline - last <= margin or (next_top is not None and baseline >= next_top - margin):
                        continue
                    if is_heading([text for text, _, _ in view.texts(index)]):
                        issues.append(ImportIssue(number, None, "second_heading", f"Page {number}: rows after a second transactions heading on this page were not read."))
                        break
                    raw = visual_row(view, spec, index, number_below)
                    if raw:
                        raws.append(raw)
                        claimed.add(index)
                        number_below += 1
                table_entry = ImportTable(table.id, number, "transactions", None, [text for text in names if text], {}, [], len(raws), True, True)
                page_entries.append(Entry(table_entry, raws, spec, top))
            chain = page_entries[-1]
        else:
            heading = next((index for index in range(len(view.rows)) if is_heading([text for text, _, _ in view.texts(index)])), None)
            if heading is not None:
                spec = make_spec(view.texts(heading))
                raws = []
                for index in range(heading + 1, len(view.rows)):
                    raw = visual_row(view, spec, index, len(raws))
                    if raw:
                        raws.append(raw)
                        claimed.add(index)
                claimed.add(heading)
                rebuilt = ImportTable(f"page-{number}-import-table-1", number, "rebuilt", None, list(spec.texts), {}, [], len(raws), True, True)
                page_entries.append(Entry(rebuilt, raws, spec, view.row_baseline[heading]))
                chain = page_entries[-1]
                if not raws:
                    issues.append(ImportIssue(number, None, "no_rows", f"Page {number}: no rows found under the transactions heading."))
            elif chain is not None:
                continuation = True
                raws = []
                for index in range(len(view.rows)):
                    raw = visual_row(view, chain.spec, index, len(raws))
                    if raw:
                        raws.append(raw)
                if raws:
                    table_entry = ImportTable(f"page-{number}-import-continuation", number, "continuation", chain.table.id, list(chain.table.headings), {}, [],
                                              len(raws), True, False)
                    page_entries.append(Entry(table_entry, raws, chain.spec, view.row_baseline[0], parent=chain))
            if heading is None and not page_entries:
                issues.append(ImportIssue(number, None, "no_table", f"Page {number}: no transactions table found"))
        for table, names in others:
            if any(view.row_of[word_id] in claimed for cell in table.cells for word_id in cell.word_ids):
                continue  # Absorbed into the rebuilt table, or the native table's below-table rows (plan "Native tables").
            other = ImportTable(table.id, number, "other", None, [name for name in names if name], {}, [], 0, False, False)
            page_entries.append(Entry(other, [], None, table_extent(view, table)[0]))
        page_entries.sort(key=lambda entry: entry.top)
        holds = bool(natives) or any(entry.table.kind == "rebuilt" for entry in page_entries) or continuation
        shown = [issue for issue in flags.get(number, []) if not (issue.code == "pdf_layout_review" and layout.issues == ["unresolved_columns"] and holds)]
        if shown and any(entry.raws for entry in page_entries):
            issues.append(ImportIssue(number, None, shown[0].code, shown[0].message))
            for entry in page_entries:
                entry.flags = [issue.message for issue in shown]
        entries += page_entries
    return entries


# --- Reading dates, amounts and signs ----------------------------------------------------------------------------------

def read_shape(text):
    """A printed date as (kind, first, second, year, two-digit year): kind is `iso`, or `slash` for MM/DD and DD/MM shapes."""
    match = SHAPE.fullmatch(text.strip())
    if not match:
        return None
    if match.group(4):
        return "iso", int(match.group(5)), int(match.group(6)), int(match.group(4)), None
    year = match.group(3)
    return "slash", int(match.group(1)), int(match.group(2)), int(year) if year and len(year) == 4 else None, int(year) if year and len(year) == 2 else None


def printed_code(text):
    value = text.strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1].strip()
    if value.endswith("-"):
        value = value[:-1].strip()
    match = PRINTED_CODE.fullmatch(value)
    return match.group(2).upper() if match else None


def last_fours(result):
    found = {}
    for page in result.pages:
        if page.method == "embedded_text" and page.layout:
            matches = sorted((match.start(), match.group(1)) for pattern in LAST_FOUR for match in pattern.finditer(page.layout.raw_text))
            for _, digits in matches:
                found.setdefault(digits, page.number)
    return found


def document_currency(result, raws):
    """The code on a printed `Currency: XXX` line, else the one code that every amount cell carries (FR-11), else None."""
    printed = {match.group(1).upper() for page in result.pages if page.method == "embedded_text" and page.layout for match in CURRENCY_LINE.finditer(page.layout.raw_text)}
    if printed:
        return printed.pop() if len(printed) == 1 else None
    cells = [text for raw in raws for text in (raw.amount, raw.debit, raw.credit) if text.strip()]
    codes = {printed_code(text) for text in cells}
    return codes.pop() if cells and len(codes) == 1 and None not in codes else None


def read_date(raw, order, year, state):
    """The posted date of a row, or the reason it cannot be read. `state` carries the year walk (plan "Dates"): the year starts
    at the chosen one and advances by one each time a month is lower than the previous year-less row's. Returns (date, reason)."""
    if not raw.date.strip():
        return None, "No date is printed."
    shape = raw.shape
    if shape is None:
        return None, f'The date "{raw.date}" is not one this import reads.'
    kind, first, second, full, short = shape
    if kind == "iso":
        month, day = first, second
    elif order is None:
        return None, None  # The order is a required choice.
    elif order == "YYYY-MM-DD":
        return None, f'The date "{raw.date}" cannot be read in the chosen date format.'
    else:
        month, day = (first, second) if order == "MM/DD/YYYY" else (second, first)
        try:
            date(2000, month, day)  # A leap year, so a year-less 02/29 is real until the year is known.
        except ValueError:
            return None, f'The date "{raw.date}" is not a real date.'
    if full is None and short is None and kind == "slash" or short is not None:
        if year is None:
            return None, None
        if state["previous"] is not None and month < state["previous"]:
            state["year"] += 1
        state["previous"] = month
        computed = state["year"]
        if short is not None and computed % 100 != short:
            return None, f'The printed year in "{raw.date}" disagrees with the year {computed} counted from the year you chose.'
    else:
        computed = full
    try:
        return date(computed, month, day).isoformat(), None
    except ValueError:
        return None, f'The date "{raw.date}" is not a real date.'


def read_amount(raw, spec, currency, sign):
    """The signed amount in minor units (None while the sign convention is still a choice), or the reason it cannot be read."""
    try:
        if "amount" in spec.columns:
            if not raw.amount.strip():
                return None, "No amount is printed."
            value = to_minor(raw.amount, currency)
            return (None if sign is None else -value if sign == "positive_is_outflow" else value), None
        debit, credit = raw.debit.strip(), raw.credit.strip()
        if debit and credit:
            return None, "Both a debit and a credit are printed."
        if not debit and not credit:
            return None, "No amount is printed."
        return (-abs(to_minor(debit, currency)), None) if debit else (abs(to_minor(credit, currency)), None)
    except MoneyError as error:
        text = raw.amount or raw.debit or raw.credit
        if "differs" in str(error):
            return None, f'The amount "{text}" is not in {currency}.'
        return None, f'The amount "{text}" can\'t be read.'


def printed_amount(raw):
    return raw.amount or " / ".join(text for text in (raw.debit, raw.credit) if text)


# --- Analysis ------------------------------------------------------------------------------------------------------------

def analyze(result: PDFResult, *, tables=None, year=None, date_format="auto", sign=None, account_type=None, currency) -> Analysis:
    """Read the saved `result` into an Analysis. `tables` are the ids of the transactions tables to import (None: all of them;
    a continuation follows the table it continues). `currency` is the account's. Raises PDFImportError over a limit."""
    currency = currency_code(currency)
    if date_format != "auto" and date_format not in DATE_FORMATS:
        raise PDFImportError(f"Unknown date format {date_format}.")
    if any(page.method == "embedded_text" and page.layout is None for page in result.pages):
        blocked = ImportIssue(None, None, "reading_without_layout", NO_LAYOUT)
        return Analysis([], [], [blocked], dict(seen=0, parsed=0, rejected=0, left_out=0, pages_without_rows=len(result.pages)), [], {}, {}, None,
                        SIGN_DEFAULTS.get(account_type), sign or SIGN_DEFAULTS.get(account_type))
    issues: list[ImportIssue] = []
    entries = structure(result, page_flags(result), issues)
    selectable = {entry.table.id for entry in entries if entry.table.selectable}
    known = {entry.table.id: entry.table.kind for entry in entries}
    for table_id in tables or []:
        if table_id not in known:
            raise PDFImportError(f"Table {table_id} is not in this reading; preview again.")
        if known[table_id] == "other":
            raise PDFImportError(f"Table {table_id} is not a transactions table.")
    chosen = selectable if tables is None else selectable & set(tables)
    for entry in entries:
        entry.table.selected = entry.parent.table.id in chosen if entry.parent else entry.table.id in chosen
    used = [entry for entry in entries if entry.table.selected]
    raws = [raw for entry in used for raw in entry.raws]
    if len(raws) > MAX_ROWS:
        raise PDFImportError(f"This PDF exceeds {MAX_ROWS:,} data rows, the most one import can hold.")
    for entry in used:
        for raw in entry.raws:
            if any(len(text) > MAX_CELL for text in (raw.date, raw.description, raw.debit, raw.credit, raw.amount)):
                raise PDFImportError(f"Page {entry.table.page}, row {raw.row}: a cell exceeds the {MAX_CELL:,}-character limit.")
    for entry in entries:
        if entry.parent:
            entry.table.columns = dict(entry.parent.table.columns)
        elif entry.spec:
            entry.table.columns = {role: entry.spec.texts[index] for role, index in entry.spec.columns.items()}
            if entry.table.selected:
                issues += [ImportIssue(entry.table.page, None, "unassigned_column", f'Page {entry.table.page}: the "{text}" column was not used.')
                           for text, role in zip(entry.spec.texts, entry.spec.roles) if role is None and text.strip()]

    # Dates: the order is decided once across every row, then the year walk runs in document order.
    for raw in raws:
        raw.shape = read_shape(raw.date)
    slashed = [raw.shape for raw in raws if raw.shape and raw.shape[0] == "slash"]
    order, required = None, []
    if slashed:
        if date_format != "auto":
            order = date_format
        else:
            first, second = any(shape[1] > 12 for shape in slashed), any(shape[2] > 12 for shape in slashed)
            order = "DD/MM/YYYY" if first and not second else "MM/DD/YYYY" if second and not first else None
    if any(shape and shape[0] == "slash" and shape[3] is None for shape in (raw.shape for raw in raws)) and year is None:
        required.append("year")
    if slashed and order is None:
        required.append("date_format")
    state = {"year": year, "previous": None}

    default = SIGN_DEFAULTS.get(account_type)
    used_sign = sign or default
    if used_sign is None and any(entry.spec and "amount" in entry.spec.columns for entry in used):
        required.append("sign")

    rows, parsed_issues = [], []
    for entry in used:
        table = entry.table
        for raw in entry.raws:
            posted, reason = read_date(raw, order, year, state)
            reject = raw.reject or reason
            if not reject and not raw.description.strip():
                reject = "The description is blank."
            minor, amount_reason = read_amount(raw, entry.spec, currency, used_sign)
            reject = reject or amount_reason
            labels = ([f"continued from page {entry.parent.table.page}"] if entry.parent else []) + entry.flags
            if reject:
                posted, minor = None, None
                parsed_issues.append(ImportIssue(table.page, raw.row, "rejected_row", f"Page {table.page} row {raw.row}: {reject}"))
            key = f"{table.id}:{raw.row}"
            rows.append(ImportRow(key, table.page, table.id, raw.row, raw.date, raw.description, printed_amount(raw), posted, minor, None if reject else currency,
                                  not reject and not entry.flags, labels, reject, raw.cell_ids, raw.line_ids, raw.word_ids,
                                  entry.parent.table.page if entry.parent else None))
            table.rows.append(key)
    issues += parsed_issues

    found_currency = document_currency(result, raws)
    if found_currency and found_currency != currency:
        issues.insert(0, ImportIssue(None, None, "document_currency_mismatch",
                                     f"This PDF is in {found_currency}, but the account's currency is {currency}. No conversion is done; choose an account in {found_currency}."))
    blocking = [issue for issue in issues if issue.code in BLOCKING]
    issues = blocking + sorted((issue for issue in issues if issue.code not in BLOCKING), key=lambda issue: issue.page or 0)
    rejected = sum(1 for row in rows if row.rejected)
    sourced = {row.page for row in rows}
    counts = dict(seen=len(rows), parsed=len(rows) - rejected, rejected=rejected, left_out=sum(1 for row in rows if not row.rejected and not row.ticked),
                  pages_without_rows=sum(1 for page in result.pages if page.number not in sourced))
    mapping: dict[str, str] = next((entry.table.columns for entry in used if not entry.parent), {})
    return Analysis([entry.table for entry in entries], rows, issues[:MAX_ISSUES], counts, [item for item in ("year", "date_format", "sign") if item in required],
                    mapping, last_fours(result), found_currency, default, used_sign, any("amount" in entry.table.columns for entry in used))


# --- Import index (migration 072; docs/documents.md "PDFs") -------------------------------------------------------------
# Derived and rebuildable from the saved reading, like the text index. It is read by the Import picker and the library
# listing, never by an import: an import always analyzes the reading itself.

PDF_READINGS = f"p.status IN ('succeeded','partial') AND p.parser_version IN ({','.join(repr(version) for version in PDF_VERSIONS)})"


def index_row(db, run_id):
    """Write (replace) one PDF reading's index row and return it as a dict, or None for a reading that is not a finished PDF reading.
    A row is written even when the analysis fails: no tables and the reason in `error`, so the backfill never stops on or repeats it."""
    from ..library.storage import now
    run = db.execute(f"SELECT p.result_json FROM parse_runs p WHERE p.id=? AND {PDF_READINGS}", (run_id,)).fetchone()
    if run is None:
        db.execute("DELETE FROM pdf_import_index WHERE parse_run_id=?", (run_id,))
        return None
    tables, fours, found_currency, error = 0, {}, None, None
    try:
        result = read_result(json.loads(run["result_json"])) if run["result_json"] else None
        if not isinstance(result, PDFResult):
            error = NO_LAYOUT
        else:
            analysis = analyze(result, currency="USD")  # A document in another currency is blocked for this one, but is still importable.
            if any(issue.code == "reading_without_layout" for issue in analysis.issues):
                error = NO_LAYOUT
            else:
                tables = sum(1 for table in analysis.tables if table.selectable)
                fours, found_currency = analysis.last_fours, analysis.document_currency
    except PDFImportError as exc:
        error = str(exc)
    except Exception as exc:  # A bad reading must not stop the others (the cause is in the log, not in the row).
        log_failure(log, "pdf import index", exc, run=run_id)
        error = f"The reading could not be analyzed ({type(exc).__name__})."
    row = dict(parse_run_id=run_id, analyzer_version=ANALYZER_VERSION, transactions_tables=tables, last_fours_json=json.dumps(fours),
               document_currency=found_currency, error=error, created_at=now())
    db.execute("INSERT OR REPLACE INTO pdf_import_index(parse_run_id,analyzer_version,transactions_tables,last_fours_json,document_currency,error,created_at) "
               "VALUES(:parse_run_id,:analyzer_version,:transactions_tables,:last_fours_json,:document_currency,:error,:created_at)", row)
    return row


def index_quietly(store, run_id):
    """Index a reading just saved. A failure is logged and left to the next start's backfill; it never fails the reading."""
    try:
        with store.connection() as db:
            index_row(db, run_id)
    except Exception as exc:
        log_failure(log, "pdf import index", exc, run=run_id)


def pending(db):
    """The PDF readings with no index row, or one made by an older analyzer."""
    return [row[0] for row in db.execute(f"SELECT p.id FROM parse_runs p LEFT JOIN pdf_import_index x ON x.parse_run_id=p.id "
                                         f"WHERE {PDF_READINGS} AND (x.parse_run_id IS NULL OR x.analyzer_version<>?) ORDER BY p.created_at",
                                         (ANALYZER_VERSION,))]


def backfill(store, work=None):
    """Index every PDF reading not yet indexed with the current analyzer. Returns how many."""
    with store.connection() as db:
        waiting = pending(db)
    for run_id in waiting:
        if work is not None:
            work.check()
        with store.connection() as db:
            index_row(db, run_id)
    if waiting:
        log.info("pdf import indexed readings=%s", len(waiting))
    return len(waiting)


REFUSED = re.compile(r"This PDF is recorded as an? (.+)\.")


def summaries(db, ledger, rows, home_currency=None):
    """Set `pdf_import` on each library row (a dict): null when its current reading has no index row, else
    {"tables", "match": {"account_id","last_four","page"} | null, "refused": "<kind>" | null}. Computed here so the browser copies no rule.
    `ledger` supplies the account match and what a PDF is recorded as (finance/ledger.py), so those rules stay in one place."""
    runs = sorted({row.get("text_run_id") for row in rows if row.get("text_run_id") and str(row.get("relative_path", "")).lower().endswith(".pdf")})
    index = {}
    for start in range(0, len(runs), 500):
        chunk = runs[start:start + 500]
        index.update({row["parse_run_id"]: row for row in db.execute(
            f"SELECT * FROM pdf_import_index WHERE parse_run_id IN ({','.join('?' * len(chunk))})", chunk)})
    for row in rows:
        found = index.get(row.get("text_run_id"))
        row["pdf_import"] = None
        if found is None:
            continue
        tables, match, refused = found["transactions_tables"], None, None
        if tables:
            fours = json.loads(found["last_fours_json"])
            matched = ledger.account_match(db, fours, found["document_currency"], home_currency) if fours else None
            match = {key: matched[key] for key in ("account_id", "last_four", "page")} if matched else None
            reason = ledger.pdf_refusal(db, row["current_hash"])
            parsed = REFUSED.fullmatch(reason) if reason else None
            refused = parsed.group(1) if parsed else reason
        row["pdf_import"] = {"tables": tables, "match": match, "refused": refused}
    return rows
