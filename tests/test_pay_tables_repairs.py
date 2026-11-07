"""One unit test for each of the eight repairs the pay stub layout generator found in `documents/pay_tables.py` (specs/pdf-table-engine-paystubs-cleanup,
FR-98, SC-96; the list is in docs/open-work.md).

Each test reads a small page written out by hand below, with its numbers and positions as literals, through the real reader and `pay_tables.read`, and
says what the repair does. The page is built so that without that repair the same assertion fails: the generated cases in
tests/test_paystub_engine_generator.py pin the repairs only together. No store and no model.
"""

from home_manager.documents import pay_tables
import paystub_engine_fixtures as pf
from pdf_import_fixtures import footer, read_pdf
from table_engine_fixtures import row_items

PERIOD = (430, 520)  # The right edges of the Current and YTD amounts of a one-block table.

# Rows (label, current, ytd) of a one-block table; the second set is a later part of the same table or another table.
EARNINGS = [("Regular", "2,500.00", "32,500.00"), ("Overtime", "187.50", "1,125.00"), ("Bonus", "50.00", "300.00")]
TAXES = [("Medicare", "38.97", "487.56"), ("Dental", "12.00", "144.00"), ("Vision", "4.50", "54.00")]
# Rows (earning, current, ytd, deduction, current, ytd) of a page with a left and a right block.
BLOCK_ROWS = [("Regular", "1,000.00", "5,000.00", "Dental", "30.00", "150.00"), ("Bonus", "50.00", "250.00", "Vision", "10.00", "50.00"),
              ("Overtime", "20.00", "90.00", "Parking", "5.00", "25.00")]
LATER_BLOCK_ROWS = [("Regular", "1,100.00", "6,100.00", "Dental", "30.00", "180.00"), ("Bonus", "60.00", "310.00", "Vision", "10.00", "60.00"),
                    ("Overtime", "25.00", "115.00", "Parking", "5.00", "30.00")]


def read(tmp_path, *pages):
    """The pages (positioned items, each with the contract's words-only footer) read by the real reader, then the pay tables of the reading."""
    result = read_pdf(tmp_path, [{"items": [*items, footer(pf.FOOTER, 60)]} for items in pages])
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
    return pay_tables.read(result)


def heading(y, edges=PERIOD, words=("Description", "Current", "YTD")):
    return row_items(y, [(40, words[0]), (edges[0], words[1], True), (edges[1], words[2], True)])


def rows(top, data, edges=PERIOD):
    """Rows from y = top, 16 pt apart: the label at x 40 and the two amounts right-aligned at the edges."""
    return [item for number, (label, current, ytd) in enumerate(data)
            for item in row_items(top - 16 * number, [(40, label), (edges[0], current, True), (edges[1], ytd, True)])]


def blocks(top, data):
    """A left block (Earnings, edges 200 and 270) and a right block (Deductions, edges 460 and 530) printed on the same lines: a heading at y = top
    and the rows below it."""
    items = row_items(top, [(40, "Earnings"), (200, "Current", True), (270, "YTD", True), (300, "Deductions"), (460, "Current", True), (530, "YTD", True)])
    for number, (left, current, ytd, right, other_current, other_ytd) in enumerate(data):
        items += row_items(top - 20 - 16 * number, [(40, left), (200, current, True), (270, ytd, True), (300, right), (460, other_current, True),
                                                      (530, other_ytd, True)])
    return items


def labels(table):
    return [row.label for row in table.rows]


def test_repair_summary_box_above_side_by_side_blocks(tmp_path):
    """A summary box printed across the page above a left and a right block is found on the whole page, before the page is split into blocks, so
    its two lines are the box's and not rows of the blocks' tables."""
    box = row_items(700, [(150, "Gross", True), (250, "Taxes", True), (350, "Deductions", True), (450, "Net", True)])
    box += row_items(684, [(40, "Current"), (150, "1,000.00", True), (250, "200.00", True), (350, "100.00", True), (450, "700.00", True)])
    box += row_items(668, [(40, "YTD"), (150, "5,000.00", True), (250, "1,000.00", True), (350, "500.00", True), (450, "3,500.00", True)])

    reading = read(tmp_path, box + blocks(630, BLOCK_ROWS))

    assert [[row.label for row in found.rows] for found in reading.boxes] == [["Current", "YTD"]]
    left, right = reading.tables
    assert (left.block, right.block) == ("left", "right")
    assert (left.partner, right.partner) == (right.id, left.id)
    assert labels(left) == ["Regular", "Bonus", "Overtime"]
    assert labels(right) == ["Dental", "Vision", "Parking"]


def test_repair_repeated_stub_heading_on_a_later_page(tmp_path):
    """A later page that prints the stub's pay date line again (the same date) continues the open table instead of ending it."""
    first = [(40, 780, "Pay date 2026-07-03"), *heading(700), *rows(680, EARNINGS)]
    second = [(40, 780, "Pay date 2026-07-03"), *rows(760, TAXES)]

    reading = read(tmp_path, first, second)

    (table,) = reading.tables
    assert table.pages == [1, 2]
    assert labels(table) == ["Regular", "Overtime", "Bonus", "Medicare", "Dental", "Vision"]


def test_repair_start_line_ends_an_empty_blocks_table(tmp_path):
    """A new stub's pay date line printed over the left block only (the right block's part of the line is empty) still ends the right block's open
    table: the second page's right table is a new one, not a continuation of the first page's."""
    first = [(40, 780, "Pay date 2026-07-03"), *blocks(700, BLOCK_ROWS)]
    second = [(40, 780, "Pay date 2026-07-10"), *blocks(760, LATER_BLOCK_ROWS)]

    reading = read(tmp_path, first, second)

    assert [(table.block, table.pages) for table in reading.tables] == [("left", [1]), ("right", [1]), ("left", [2]), ("right", [2])]
    assert [labels(table) for table in reading.tables] == [["Regular", "Bonus", "Overtime"], ["Dental", "Vision", "Parking"]] * 2


def test_repair_second_table_with_the_same_heading_words(tmp_path):
    """A heading printed again over other columns, with the same words as the open table's, is the heading of a second table; only a heading over the
    open table's own columns is a repeat to ignore."""
    other = (330, 400)
    garnishments = [("Garnish", "10.00", "20.00"), ("Loan", "5.00", "8.00"), ("Fee", "3.00", "4.00")]

    reading = read(tmp_path, [*heading(700), *rows(680, EARNINGS), *heading(600, other), *rows(580, garnishments, other)])

    first, second = reading.tables
    assert labels(first) == ["Regular", "Overtime", "Bonus"]
    assert labels(second) == ["Garnish", "Loan", "Fee"]
    assert second.headings == ["Description Current YTD"]
    assert [column.labels for column in second.columns] == [["Current"], ["YTD"]]


def test_repair_partner_table_beside_several_tables(tmp_path):
    """A page with a left block over a second table in the same block and a right block makes three tables; the right one is the partner of the left
    table it shares lines with, and the other left table has none."""
    account = row_items(600, [(40, "Account"), (150, "Amount", True), (240, "Balance", True)])
    account += row_items(584, [(40, "Checking"), (150, "500.00", True), (240, "1,500.00", True)])
    account += row_items(568, [(40, "Savings"), (150, "200.00", True), (240, "900.00", True)])

    reading = read(tmp_path, blocks(700, BLOCK_ROWS) + account)

    earnings, balances, deductions = reading.tables
    assert [(table.block, labels(table)) for table in reading.tables] == [
        ("left", ["Regular", "Bonus", "Overtime"]), ("left", ["Checking", "Savings"]), ("right", ["Dental", "Vision", "Parking"])]
    assert (earnings.partner, deductions.partner) == (deductions.id, earnings.id)
    assert balances.partner is None


def test_repair_two_heading_phrases_printed_close_together(tmp_path):
    """Two headings printed closer than a run gap read as one run ("This Period Year to Date"); the run is split where its words lie over different
    columns, so each column is named by its own phrase."""
    close = (450, 515)

    reading = read(tmp_path, heading(700, close, ("Description", "This Period", "Year to Date")) + rows(680, EARNINGS, close))

    (table,) = reading.tables
    assert [column.labels for column in table.columns] == [["This Period"], ["Year to Date"]]


def test_repair_text_only_line_of_several_runs(tmp_path):
    """An indented text-only line under a row that has several runs (two notes side by side) is no wrapped label: the row keeps its own."""
    note = [(60, 648, "Rate change"), (200, 648, "effective July")]

    reading = read(tmp_path, [*heading(700), *rows(680, EARNINGS[:2]), *note])

    (table,) = reading.tables
    assert labels(table) == ["Regular", "Overtime"]


def test_repair_continuation_column_at_another_alignment(tmp_path):
    """A later page prints the table's columns left-aligned (its amounts differ in width, so their left edges line up and their right edges don't)
    where the first page printed them right-aligned; the column is matched at that alignment and the table continues."""
    later = []
    for number, (label, current, ytd) in enumerate([("Medicare", "300.00", "1,200.00"), ("Dental", "1,200.00", "45.00"), ("Vision", "45.00", "7.00")]):
        later += [(40, 780 - 16 * number, label), (397, 780 - 16 * number, current), (476, 780 - 16 * number, ytd)]

    reading = read(tmp_path, [*heading(700), *rows(680, EARNINGS)], later)

    (table,) = reading.tables
    assert table.pages == [1, 2]
    assert labels(table) == ["Regular", "Overtime", "Bonus", "Medicare", "Dental", "Vision"]
