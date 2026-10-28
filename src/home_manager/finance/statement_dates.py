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
