"""What the reader, the Tables tab and Record's rebuild make of one statement PDF, without printing its text.

Usage:  python scripts/statement_diagnose.py "<path to a statement PDF>" [year] [card]

The rebuild places year-less dates in the statement's period; the script uses the whole of `year` (default this year).
`card` runs the table engine as a credit-card statement (positive amounts are charges); the default is a bank statement.

Reads the PDF with this checkout's reader (documents/pdf_reader.py `worker` and `complete_pdf`, no vision model) into a
temporary folder that is deleted at the end, then runs Record's rebuild (finance/statement_rows.py `rebuild`) on it.
Prints only flags, counts, column roles (date, description, amount, balance), shapes of cells (date, amount, words(n),
blank) and positions as a percentage of the page. Review messages are printed with quotes, dates and amounts replaced by "…".

The last section is the table engine (documents/table_engine.py and finance/statement_tables.py, plan P13, OD-6): per page, each
column's edges and zone as a percentage of the page width, its kind and role, and counts of rows, rejected rows, recorded rows,
anchors, totals, other-table rows and unplaced lines; whether a period was printed, the decided date order and how it was decided,
how each table's roles were decided (chain, summary, headings or the type default), and the first chain-break row number. It prints
no heading word, description, date or amount.
"""
from datetime import date
import json
import math
from pathlib import Path
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from home_manager.documents.layout_context import native_page, viewer_context  # noqa: E402
from home_manager.documents.pdf_reader import complete_pdf, read_result, worker  # noqa: E402
from home_manager.finance import statement_rows, statement_tables  # noqa: E402
from home_manager.finance.pdf_import import PageView, assign, is_heading, native_spec  # noqa: E402
from home_manager.library.storage import digest_file  # noqa: E402

DATE = re.compile(r"\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?")
AMOUNT = re.compile(r"[-+(]?[$€£]?\d{1,3}(,\d{3})*\.\d{2}\)?-?")


def shape(text):
    text = text.strip()
    if not text:
        return "blank"
    if DATE.fullmatch(text):
        return "date"
    if AMOUNT.fullmatch(text):
        return "amount"
    return f"words({len(text.split())})"


def masked(message):
    """Quotes, dates and amounts are the document's; page and row numbers are kept."""
    message = re.sub(r'"[^"]*"', '"…"', message)
    return AMOUNT.sub("…", DATE.sub("…", message))


ARGUMENTS = sys.argv[1:]
source = Path(ARGUMENTS[0]).resolve()
with tempfile.TemporaryDirectory() as folder:
    folder = Path(folder)
    worker(str(source), folder)
    complete_pdf(folder, config=None, digest=digest_file(source))
    result = read_result(json.loads((folder / "result.json").read_text(encoding="utf-8")))

print("pages:", len(result.pages))
for page in result.pages:
    print(f"\n=== Page {page.number} === method: {page.method}")
    layout = page.layout
    if layout is None:
        print("no layout saved")
        continue
    view = PageView(layout)
    width, height = layout.preview_width, layout.preview_height
    print(f"flags: {', '.join(layout.issues) or 'none'}   text size: {view.size:.1f} px   native page: {native_page(page)}")
    print(f"native tables: {len(layout.tables)}")
    for table in layout.tables:
        spec = native_spec(view, table)
        cells = {(cell.row, cell.column): cell.text for cell in table.cells}
        print(f"  {table.id.split('-layout-')[-1]}: {table.rows} rows × {table.columns} columns, "
              f"transactions heading: {is_heading(spec.texts)}, roles: {spec.roles}")
        for row in range(1, min(table.rows, 7)):
            print(f"    row {row}: {[shape(cells.get((row, column), '')) for column in range(table.columns)]}")
    heading = next((index for index in range(len(view.rows)) if is_heading([text for text, _, _ in view.texts(index)])), None)
    if heading is None:
        print("transactions heading in the visual rows: none")
        continue
    texts = view.texts(heading)
    print(f"transactions heading: visual row {heading} of {len(view.rows)}, y {100 * view.row_baseline[heading] / height:.1f}%, "
          f"roles: {assign([text for text, _, _ in texts])[0]}")
    print("  heading columns (x %):", [f"{100 * left / width:.1f}–{100 * right / width:.1f}" for _, left, right in texts])
    for index in range(max(0, heading - 2), min(len(view.rows), heading + 9)):
        runs = [f"{shape(text)} @{100 * left / width:.0f}–{100 * right / width:.0f}" for text, left, right in view.texts(index)]
        label = "heading" if index == heading else f"{index - heading:+d}"
        print(f"  row {label:>7}: {runs}")

print("\n=== Tables tab ===")
context = viewer_context(result)
print(f"tables shown: {len(context['tables'])}" + ("" if context["tables"] else "  (the tab says no reliable table structure was found)"))

year = int(next((argument for argument in ARGUMENTS[1:] if argument.isdigit()), date.today().year))
print(f"\n=== Record's rebuild (bank statement, period {year}) ===")
reading = statement_rows.Reading(result)
for entry in reading.entries:
    table = entry.table
    print(f"  {table.kind} table on page {table.page}: {table.row_count} rows, roles: {entry.spec.roles if entry.spec else None}, "
          f"read by Record: {table.id in reading.ids}{'   (excluded: balance title or heading)' if table.id in reading.excluded else ''}")
if not reading.entries:
    print("  no tables found")
_, analysis, kept = statement_rows.selected(result, "USD", "negative_is_outflow")
kinds = {table.id: table.kind for table in analysis.tables}
print(f"rows Record takes from the printed columns: {len(kept)}")
for row in kept:
    cells = {role: shape(getattr(row, role)) for role in ("date", "description", "amount")}
    where = f"y {100 * min(PageView(result.pages[row.page - 1].layout).box[w][1] for w in row.word_ids) / result.pages[row.page - 1].layout.preview_height:.1f}%" if row.word_ids else "native cells"
    print(f"  page {row.page} {kinds[row.table_id]} row {row.row} ({where}): {cells}"
          + (f"   rejected: {masked(row.rejected)}" if row.rejected else ""))
built = statement_rows.rebuild(result, statement_type="bank", period_start=f"{year}-01-01", period_end=f"{year}-12-31", currency="USD")
print(f"available: {built.available}   rebuilt pages: {sorted(built.pages)}   rows recorded: {len(built.rows)}   rows dropped: {built.dropped}")
for issue in built.issues:
    print("  review:", masked(issue))
for note in built.notes:
    print("  note:", masked(note))


# --- The table engine (plan P13, OD-6): counts, shapes and positions only ----------------------------------------------------------

BREAK = re.compile(r"Page (\d+) row (\d+): the balance")


def percent(value, width):
    return "edge" if math.isinf(value) else f"{100 * value / width:.1f}"


def span_text(pair, width):
    return f"{percent(pair[0], width)}–{percent(pair[1], width)}"


def engine_section():
    card = "card" in ARGUMENTS[1:]
    print(f"\n=== Table engine ({'card' if card else 'bank'} statement, year {year} for year-less dates) ===")
    try:
        reading = statement_tables.read(result, statement_type="credit_card" if card else "bank", choices={"year": year})
    except Exception as exc:  # The type only: an exception's text may quote the document.
        print(f"the engine raised {type(exc).__name__}")
        return
    if not reading.available:
        print("a page has no saved layout: the engine has nothing to read")
        return
    decided = reading.decided
    print(f"period printed: {'yes' if reading.period else 'no'}   date order: {reading.order or 'undecided'} (decided by: {decided.get('order') or 'nothing'})"
          f"   opening printed: {'yes' if reading.opening_minor is not None else 'no'}   closing printed: {'yes' if reading.closing_minor is not None else 'no'}")
    print(f"rows recorded: {len(reading.rows)}   dropped: {reading.dropped}   review issues: {len(reading.issues)}   year of year-less dates decided by: {decided.get('year') or 'nothing'}")
    breaks = [(int(page), int(row)) for page, row in (match.groups() for match in map(BREAK.match, reading.issues) if match)]
    first = f"page {min(breaks)[0]} row {min(breaks)[1]}" if breaks else "none"
    print(f"first chain-break row: {first}")
    recorded = {}
    for row in reading.rows:
        recorded[row["locator"]["page"]] = recorded.get(row["locator"]["page"], 0) + 1
    for page in result.pages:
        layout = page.layout
        print(f"\n  --- Page {page.number} ---")
        if layout is None:
            print("  no layout saved")
            continue
        width = layout.preview_width
        tables = [table for table in reading.tables if page.number in table.pages]
        unplaced = [line for line in [*reading.unplaced] if line.page == page.number]
        anchors = sum(1 for table in tables for anchor in table.anchors if anchor.page == page.number) \
            + sum(1 for anchor in reading.summary_anchors if anchor.page == page.number)
        totals = sum(1 for table in tables for total in table.totals if total.page == page.number)
        on_page = [(table, [row for row in table.rows if row.page == page.number]) for table in tables]
        rows = sum(len(found) for table, found in on_page if table.kind == "transactions")
        rejected = sum(1 for table, found in on_page if table.kind == "transactions" for row in found if row.reject)
        other = sum(len(found) for table, found in on_page if table.kind != "transactions")
        print(f"  tables: {len(tables)}   rows: {rows}   rejected rows: {rejected}   recorded: {recorded.get(page.number, 0)}   anchors: {anchors}"
              f"   totals: {totals}   other-table rows: {other}   unplaced lines: {len(unplaced)}")
        for table, found in on_page:
            how = decided.get("signs", {}).get(table.id)
            print(f"  {table.id}: kind {table.kind}, pages {table.pages}, {len(found)} rows here, heading lines: {len(table.headings)}"
                  + (f", roles decided by: {how or 'nothing'}" if table.kind == "transactions" else ""))
            for column in table.columns:
                role = reading.roles.get(table.id, {}).get(column.id, "-" if column.kind != "amount" else "undecided")
                print(f"    {column.kind:<6} {column.align:<6} edge {percent(column.edge, width):>5}%  extent {span_text(column.extent, width)}%  "
                      f"zone {span_text(column.zone, width)}%  role {role}  heading words: {len(column.labels)}")
        if not tables:
            print("  no table on this page")


engine_section()
