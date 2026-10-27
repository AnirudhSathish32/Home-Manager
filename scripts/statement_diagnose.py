"""What the reader, the Tables tab and Record's rebuild make of one statement PDF, without printing its text.

Usage:  python scripts/statement_diagnose.py "<path to a statement PDF>" [year]

The rebuild places year-less dates in the statement's period; the script uses the whole of `year` (default this year).

Reads the PDF with this checkout's reader (documents/pdf_reader.py `worker` and `complete_pdf`, no vision model) into a
temporary folder that is deleted at the end, then runs Record's rebuild (finance/statement_rows.py `rebuild`) on it.
Prints only flags, counts, column roles (date, description, amount, balance), shapes of cells (date, amount, words(n),
blank) and positions as a percentage of the page. Review messages are printed with quotes, dates and amounts replaced by "…".
"""
from pathlib import Path
from datetime import date
import json
import re
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from home_manager.documents.layout_context import native_page, viewer_context  # noqa: E402
from home_manager.documents.pdf_reader import complete_pdf, read_result, worker  # noqa: E402
from home_manager.finance import statement_rows  # noqa: E402
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


source = Path(sys.argv[1]).resolve()
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

year = int(sys.argv[2]) if len(sys.argv) > 2 else date.today().year
print(f"\n=== Record's rebuild (bank statement, period {year}) ===")
reading = statement_rows.Reading(result)
for entry in reading.entries:
    table = entry.table
    print(f"  {table.kind} table on page {table.page}: {table.row_count} rows, roles: {entry.spec.roles if entry.spec else None}, "
          f"read by Record: {table.id in reading.ids}{'   (excluded: balance title or heading)' if table.id in reading.excluded else ''}")
if not reading.entries:
    print("  no tables found")
built = statement_rows.rebuild(result, statement_type="bank", period_start=f"{year}-01-01", period_end=f"{year}-12-31", currency="USD")
print(f"available: {built.available}   rebuilt pages: {sorted(built.pages)}   rows recorded: {len(built.rows)}   rows dropped: {built.dropped}")
for issue in built.issues:
    print("  review:", masked(issue))
for note in built.notes:
    print("  note:", masked(note))
