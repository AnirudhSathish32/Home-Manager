"""Dates and the rebuilt-statement shape shared by the statement readers (specs/statement-accounts FR-19, FR-29; pdf-table-engine P1).

`Rebuild` is what `ExtractionService.normalize` reads from a statement reading. `read_period` and `placed` turn a printed date and the
printed period into an ISO date, `duplicates` finds the same row printed in two tables. They live here so the engine's statement layer
(`statement_tables`) and the old reader (`statement_rows`) share them without importing each other or `pdf_import`.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

PERIOD_SLACK = timedelta(days=7)  # The tolerance `ExtractionService.normalize` gives a row's date against the printed period.
NO_LAYOUT_NOTE = "Read this document again to take its rows from the printed columns."


@dataclass
class Rebuild:
    available: bool  # False: no layout (FR-23). The caller adds its own issue when the rebuild fails (P8).
    pages: set[int] = field(default_factory=set)  # Rebuilt pages: at least one row in the selected tables, recorded or not.
    rows: list[dict] = field(default_factory=list)  # Transactions in normalize's shape, in printed order, recorded rows only.
    issues: list[str] = field(default_factory=list)  # Review reasons: rejected rows, missing years, duplicates, second headings.
    notes: list[str] = field(default_factory=list)  # Record notes, not review reasons.
    dropped: int = 0  # Rows of the rebuilt pages that were rejected or left out (FR-25's arithmetic check needs to know).
    opening_minor: int | None = None  # The printed opening (previous) balance, when the reader found one (the engine does; the old reader doesn't).
    closing_minor: int | None = None  # The printed closing (new) balance.
    period: tuple | None = None  # The printed statement period as ISO dates (start, end), when the reader found one.
    order: str | None = None  # The date order the rows were read in (MM/DD/YYYY or DD/MM/YYYY), when one was decided.


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


DUPLICATE = ("The same row is printed twice: {posted} {description} {amount} on page {first_page} (row {first_row}) and page {second_page} "
             "(row {second_row}). Both were recorded; check whether it is one payment.")


def duplicate_pairs(recorded):
    """FR-29: each pair of recorded rows with the same date, amount and description on different pages or tables, as (first, second,
    posted) in the order the rows were recorded. Rows are grouped by that key and then by page and table, and only rows of different
    groups are paired, so the work is the pairs found, not every pair of rows."""
    groups = {}
    for position, (row, posted) in enumerate(recorded):
        key = (posted, row.amount_minor, " ".join(row.description.split()).casefold())
        groups.setdefault(key, {}).setdefault((row.page, row.table_id), []).append(position)
    pairs = []
    for places in groups.values():
        lists = list(places.values())
        for at, one in enumerate(lists):
            for other in lists[at + 1:]:
                pairs += [(min(a, b), max(a, b)) for a in one for b in other]
    return [(recorded[a][0], recorded[b][0], recorded[a][1]) for a, b in sorted(pairs)]


def duplicates(recorded):
    """FR-29: one issue per pair of `duplicate_pairs`."""
    return [DUPLICATE.format(posted=posted, description=first.description, amount=first.amount, first_page=first.page, first_row=first.row,
                             second_page=second.page, second_row=second.row) for first, second, posted in duplicate_pairs(recorded)]
