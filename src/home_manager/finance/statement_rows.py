"""A statement PDF's transactions, rebuilt from its printed columns (specs/statement-accounts FR-16 – FR-30).

Beside `pdf_import`, because it applies that module's row rules to a saved reading. It is pure and deterministic: no store, no
model, no network and no PDF is opened. `rebuild` gives the rows of every `embedded_text` page that has a transactions table,
in the shape `ExtractionService.normalize` reads, and the review issues and record notes that go with them. A balance table
(FR-27) is never read, and a table ends where a balance title or a second heading begins on a page the reader built no table
for. A row that cannot be placed is listed as an issue, never guessed.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

from .pdf_import import BALANCE_NAMES, PageView, analyze, is_heading, make_spec, page_flags, read_shape, structure

NO_LAYOUT_NOTE = "Read this document again to take its rows from the printed columns."
BALANCE_WORDS = (*BALANCE_NAMES, "daily ending balance", "daily balance")  # FR-27: what makes a title or heading name a balance.
DATE_ORDERS = ("MM/DD/YYYY", "DD/MM/YYYY")
PERIOD_SLACK = timedelta(days=7)  # The tolerance `ExtractionService.normalize` gives a row's date against the printed period.
SECOND_HEADING = "Page {page}: rows after a second transactions heading on this page weren't read; check them against the statement."
TITLE_NOTE = ('Page {page}: the line above the table headed "{heading}" names a balance, so its rows were taken from the reading, '
              "not the printed columns; check them.")


@dataclass
class Rebuild:
    available: bool  # False: no layout (FR-23). The caller adds its own issue when the rebuild fails (P8).
    pages: set[int] = field(default_factory=set)  # Rebuilt pages: at least one row in the selected tables, recorded or not.
    rows: list[dict] = field(default_factory=list)  # Transactions in normalize's shape, in printed order, recorded rows only.
    issues: list[str] = field(default_factory=list)  # Review reasons: rejected rows, missing years, duplicates, second headings.
    notes: list[str] = field(default_factory=list)  # Record notes, not review reasons.
    dropped: int = 0  # Rows of the rebuilt pages that were rejected or left out (FR-25's arithmetic check needs to know).


def names_balance(text):
    lowered = text.lower()
    return any(name in lowered for name in BALANCE_WORDS)


def heading_row(view, top):
    """The visual row of a table's heading: the one whose baseline is nearest the table's top."""
    return min(range(len(view.row_baseline)), key=lambda index: abs(view.row_baseline[index] - top))


def row_text(view, index):
    return " ".join(word.text for word in view.rows[index])


def heading_names_balance(spec):
    """A heading text names a balance, apart from the column `assign` already took as the Balance column (P10)."""
    return any(names_balance(text) and role != "balance" for text, role in zip(spec.texts, spec.roles))


def title_names_balance(view, heading):
    return heading > 0 and names_balance(row_text(view, heading - 1))


def cut_at(view, start):
    """FR-27's section cut: the first visual row from `start` that is a balance title (it names a balance and sits directly
    above a transactions heading) or a transactions heading, with whether it is a balance section. A row that only contains
    `balance` (a BALANCE TRANSFER description, a Beginning Balance line) never cuts."""
    for index in range(start, len(view.rows)):
        below = index + 1 < len(view.rows) and is_heading([text for text, _, _ in view.texts(index + 1)])
        if names_balance(row_text(view, index)) and below:
            return index, True
        if is_heading([text for text, _, _ in view.texts(index)]):
            return index, heading_names_balance(make_spec(view.texts(index)))
    return None


class Reading:
    """The tables of a reading and which of them Record reads (FR-27)."""

    def __init__(self, result):
        issues = []
        self.entries = structure(result, page_flags(result), issues)
        self.by_id = {entry.table.id: entry for entry in self.entries}
        self.views = {page.number: PageView(page.layout) for page in result.pages if page.method == "embedded_text"}
        self.notes, self.excluded, self.own = [], set(), {}
        for entry in self.entries:
            if entry.spec is None:
                continue
            view = self.views[entry.table.page]
            if entry.table.kind == "continuation":
                continue
            heading = heading_row(view, entry.top)
            self.own.setdefault(entry.table.page, set()).add(heading)
            by_title, by_heading = title_names_balance(view, heading), heading_names_balance(entry.spec)
            if by_title or by_heading:
                self.excluded.add(entry.table.id)
            if by_title and not by_heading and "description" in entry.spec.columns and any(role in entry.spec.columns for role in ("amount", "debit", "credit")):
                self.notes.append(TITLE_NOTE.format(page=entry.table.page, heading=" | ".join(entry.spec.texts)))
        self.ids = [entry.table.id for entry in self.entries if entry.table.selectable and entry.table.id not in self.excluded]
        self.cuts = {}

    def cut(self, table):
        """A rebuilt or continuation table's section cut (`cut_at`), else None. Native tables need none: the reader ends them."""
        if table.id not in self.cuts:
            view, entry = self.views[table.page], self.by_id[table.id]
            start = heading_row(view, entry.top) + 1 if table.kind == "rebuilt" else 0 if table.kind == "continuation" else None
            self.cuts[table.id] = None if start is None else cut_at(view, start)
        return self.cuts[table.id]

    def kept(self, rows, tables):
        """The rows of the analysis that survive the cuts. A table ends at its cut, and a continuation of a cut table continues
        nothing, so its page keeps the model's reading (FR-23)."""
        by_id = {table.id: table for table in tables}
        found = []
        for row in rows:
            table = by_id[row.table_id]
            cut = self.cut(table)
            if cut and row.word_ids and self.views[table.page].row_of[row.word_ids[0]] >= cut[0]:
                continue
            if table.kind == "continuation" and self.cut(by_id[table.linked_to]):
                continue
            found.append(row)
        return found

    def second_headings(self, pages):
        """The rebuilt pages with a transactions heading that is no table's own and names no balance (step 7)."""
        found = []
        for number in sorted(pages):
            view = self.views[number]
            for index in range(len(view.rows)):
                if index in self.own.get(number, set()) or not is_heading([text for text, _, _ in view.texts(index)]):
                    continue
                if not title_names_balance(view, index) and not heading_names_balance(make_spec(view.texts(index))):
                    found.append(number)
                    break
        return found


def selected(result, currency, sign, date_format="auto"):
    reading = Reading(result)
    analysis = analyze(result, tables=reading.ids, sign=sign, currency=currency, date_format=date_format)
    return reading, analysis, reading.kept(analysis.rows, analysis.tables)


def laid_out(result):
    """False when an `embedded_text` page has no saved layout (FR-23): the reading was made before layouts existed."""
    return all(page.layout is not None for page in result.pages if page.method == "embedded_text")


def rebuilt_pages(result) -> set[int]:
    """The pages that have rebuilt rows. The pages don't depend on the currency or the sign, which only decide which rows are
    rejected (a rejected row still makes its page rebuilt)."""
    if not laid_out(result):
        return set()
    _, _, rows = selected(result, "USD", "negative_is_outflow")
    return {row.page for row in rows}


def read_period(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def placed(shape, order, start, end):
    """A printed date's ISO date, or why it can't be placed (FR-19). A four-digit year is read as printed; else the year is the
    period's start year, or across a year end the end year for a month earlier than the start month."""
    kind, first, second, full, short = shape
    month, day = (first, second) if kind == "iso" or order == "MM/DD/YYYY" else (second, first)
    year = full
    if year is None:
        if start is None or end is None:
            return None, "no year is printed and the statement period wasn't read, so the date {date} can't be placed."
        year = start.year if start.year == end.year else end.year if month < start.month else start.year
        if short is not None and year % 100 != short:
            return None, 'the printed year in "{date}" disagrees with the statement period.'
    try:
        return date(year, month, day).isoformat(), None
    except ValueError:
        return None, 'The date "{date}" is not a real date.'


def date_order(rows, start, end):
    """The printed slash dates' order: the one a day over 12 decides, else the one under which every date falls inside the
    printed period (P12). None when it can't be told."""
    shapes = [read_shape(row.date) for row in rows]
    slashed = [shape for shape in shapes if shape and shape[0] == "slash"]
    if not slashed:
        return None
    first, second = any(shape[1] > 12 for shape in slashed), any(shape[2] > 12 for shape in slashed)
    if first != second:
        return "DD/MM/YYYY" if first else "MM/DD/YYYY"
    if start is None or end is None:
        return None
    fits = []
    for order in DATE_ORDERS:
        found = [placed(shape, order, start, end)[0] for shape in slashed]
        if all(found) and all(start - PERIOD_SLACK <= date.fromisoformat(posted) <= end + PERIOD_SLACK for posted in found):
            fits.append(order)
    return fits[0] if len(fits) == 1 else None


def rebuild(result, *, statement_type, period_start, period_end, currency) -> Rebuild:
    """The rows of a bank or card statement, from the printed columns. `statement_type` is `credit_card` or `bank` (FR-18: a card
    statement's positive amounts are money out, a bank statement's negative ones). The period is an ISO date or None."""
    if not laid_out(result):
        return Rebuild(False, notes=[NO_LAYOUT_NOTE])
    sign = "positive_is_outflow" if statement_type == "credit_card" else "negative_is_outflow"
    start, end = read_period(period_start), read_period(period_end)
    reading, analysis, rows = selected(result, currency, sign)
    order = date_order(rows, start, end)
    if order:
        reading, analysis, rows = selected(result, currency, sign, order)
    issues, recorded, dropped, unplaced = [], [], 0, {}
    blocked = analysis.blocked
    for row in rows:
        where = f"Page {row.page} row {row.row}"
        if blocked:
            dropped += 1
            continue
        if row.rejected:
            issues.append(f"{where}: {row.rejected}")
            dropped += 1
            continue
        shape = read_shape(row.date)
        posted = row.posted_date
        if posted is None:
            if shape[0] == "slash" and order is None:
                unplaced[row.page] = unplaced.get(row.page, 0) + 1
                dropped += 1
                continue
            posted, reason = placed(shape, order, start, end)
            if reason:
                issues.append(f"{where}: {reason.format(date=row.date)}")
                dropped += 1
                continue
        recorded.append((row, posted))
    if blocked:
        issues.insert(0, blocked)
    for page in sorted(unplaced):
        issues.append(f"Page {page} rows: the date order (month/day or day/month) can't be told from the printed dates.")
    pages = {row.page for row in rows}
    issues += [SECOND_HEADING.format(page=page) for page in reading.second_headings(pages)]
    issues += duplicates(recorded)
    lines = {page.number: {line.id: line.text for line in page.layout.lines} for page in result.pages if page.method == "embedded_text"}
    transactions = [{"posted_date": posted, "transaction_date": None, "description": row.description, "currency": row.currency,
                     "amount_minor": row.amount_minor,
                     "locator": {"rebuilt": True, "page": row.page, "table_id": row.table_id, "row": row.row, "balance_minor": row.balance_minor,
                                 "line_ids": row.line_ids,
                                 "word_ids": row.word_ids, "cell_ids": row.cell_ids,
                                 "quotes": [lines[row.page].get(line_id, "") for line_id in row.line_ids]}}
                    for row, posted in recorded]
    return Rebuild(True, pages, transactions, issues, reading.notes, dropped)


def duplicates(recorded):
    """FR-29: one issue per pair of recorded rows with the same date, amount and description on different pages or tables."""
    issues = []
    for position, (first, posted) in enumerate(recorded):
        for second, other in recorded[position + 1:]:
            if (posted, first.amount_minor, " ".join(first.description.split()).casefold()) != (
                    other, second.amount_minor, " ".join(second.description.split()).casefold()):
                continue
            if (first.page, first.table_id) != (second.page, second.table_id):
                issues.append(f"The same row is printed twice: {posted} {first.description} {first.amount} on page {first.page} (row {first.row}) and "
                              f"page {second.page} (row {second.row}). Both were recorded; check whether it is one payment.")
    return issues
