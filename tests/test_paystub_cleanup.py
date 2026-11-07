"""The pay stub follow-up that makes one path for text PDFs (specs/pdf-table-engine-paystubs-cleanup).

SL-02: SC-90 step 1, the sectioned payslip through the engine alone (FR-89 heading phrases split by column, FR-90 whole-number amounts, FR-91 totals
covering several sections), with the details-box line of m7 and the page of whole hours on several rows. Expected values are the contract's literals
and the fixture's printed numbers, not what the code produced. No store and no model: the engine is read from a saved PDF reading.
"""

from decimal import Decimal

from home_manager.documents import pay_tables
from home_manager.finance import paystub_tables
import paystub_engine_fixtures as pf
import pdf_import_fixtures as fx
from table_engine_fixtures import row_items
from test_pdf_layout import sectioned_payslip_items

BENEFITS = {"items": [(60, 700, "Other Benefit And Information"), (250, 700, "This Period"), (320, 700, "Year to Date"),
                      (60, 685, "Co Match 401K"), (265, 685, "160.00"), (330, 685, "3,360.00")]}


def sectioned(tmp_path, extra=()):
    """The sectioned payslip of test_layout_consumers (page 1) and its page-two benefits table, read by the engine."""
    items = [(30, 760, "SYNTH CONSULTING LTD"), (30, 745, "Currency USD"), *sectioned_payslip_items(), *extra]
    return paystub_tables.read(fx.read_pdf(tmp_path, [{"items": items}, BENEFITS]))


def roles_of(found, table):
    return [found.roles[found.tables.index(table)].roles[column.id] for column in table.columns]


def cell(table, label, column):
    [row] = [row for row in table.rows if row.label == label]
    return row.amounts[column.id]


# --- SC-90 step 1: the sectioned payslip through the engine ----------------------------------------------------------------

def check_the_sectioned_payslip(found):
    earnings, deductions, benefits = found.tables
    assert (earnings.block, deductions.block, earnings.partner, deductions.partner) == ("left", "right", deductions.id, earnings.id)
    # FR-89: the one-run headings give each column the words over it, and the right block's label is not the left's last column's.
    assert [column.labels for column in earnings.columns] == [["Rate"], ["Hours"], ["This Period"], ["Year To Date"]]
    assert [column.labels for column in deductions.columns] == [["This Period"], ["Year To Date"]]
    assert roles_of(found, earnings) == ["rate", "hours", "current", "ytd"]
    assert roles_of(found, deductions) == ["current", "ytd"]
    # FR-90: `80` is the Hours cell of Regular Salary (50.00 x 80 = 4,000.00) and `4,000` the Year To Date cell of Relocation Bonus.
    rate, hours, current, ytd = earnings.columns
    assert [token.text for token in earnings.rows[0].amounts.values()] == ["50.00", "80", "4,000.00", "84,000.00"]
    assert cell(earnings, "Regular Salary", hours).value == (Decimal(80), None, None) and cell(earnings, "Regular Salary", hours).kind == "amount"
    assert [(row.label, [token.text for token in row.amounts.values()]) for row in earnings.rows] == [
        ("Regular Salary", ["50.00", "80", "4,000.00", "84,000.00"]), ("Relocation Bonus", ["4,000"])]
    assert cell(earnings, "Relocation Bonus", ytd).value[0] == Decimal(4000)
    assert earnings.rows[1].amounts.keys() == {ytd.id}
    assert [(row.label, row.section) for row in deductions.rows] == [
        ("Federal Tax", "Statutory"), ("Social Security Tax", "Statutory"), ("Medicare Tax", "Statutory"), ("GA State Tax", "Statutory"),
        ("Medical HDP", "Voluntary"), ("Vision Insurance", "Voluntary"), ("Dental PPO", "Voluntary"), ("HSA Additional", "Voluntary"),
        ("401K Plan", "Voluntary")]
    # FR-91: Total Deductions (B) covers both sections this period (1,354.00) and not year to date (rows 28,314.00, printed 28,434.00).
    assert paystub_tables.pay_columns(earnings) == {current.id, ytd.id}
    assert paystub_tables.pay_columns(deductions) == {deductions.columns[0].id}
    [note] = paystub_tables.mismatches(found)
    assert "Total Deductions (B)" in note and "28,434.00" in note and "28,314.00" in note and "1,354.00" not in note
    # Page 1 is trusted, page 2's one-row table is a pay table with This Period and Year to Date, and nothing is unplaced.
    assert paystub_tables.untrusted_pages(found) == set() and found.pages == {1, 2}
    assert [column.labels for column in benefits.columns] == [["This Period"], ["Year to Date"]]
    assert roles_of(found, benefits) == ["current", "ytd"]
    assert found.unplaced == [] and found.pages_without_tables == [] and found.other_tables == []


def test_sc90_the_sectioned_payslip_is_read_by_the_engine_with_every_column_headed(tmp_path):
    check_the_sectioned_payslip(sectioned(tmp_path))


def test_sc90_a_lone_integer_on_the_details_box_line_gives_no_row(tmp_path):
    """m7: `Federal Allowances` has a `2` printed at the right edge of the deductions' This Period column (516); it is no row, no amount, no stray line."""
    two = (round(516 - 5.0, 1), 660, "2")
    found = sectioned(tmp_path, [two])
    check_the_sectioned_payslip(found)
    assert "Federal Allowances" not in [row.label for table in found.tables for row in table.rows]


# --- SC-90 step 1: whole hours on several rows ----------------------------------------------------------------------------

WHOLE_HOURS = [("Regular", "25.00", "40", "1,000.00", "13,000.00"), ("Overtime", "37.50", "4", "150.00", "600.00"),
               ("Holiday", "25.00", "8", "200.00", "400.00")]


def hours_page(rows=WHOLE_HOURS, heading=True):
    items = row_items(700, [(40, "Description"), (260, "Rate", True), (330, "Hours", True), (430, "Current", True), (520, "YTD", True)]) if heading else []
    for number, (label, rate, hours, current, ytd) in enumerate(rows):
        items += row_items(680 - 16 * number, [(40, label), (260, rate, True), (330, hours, True), (430, current, True), (520, ytd, True)])
    items += row_items(680 - 16 * len(rows), [(40, "Gross Pay"), (430, "1,350.00", True), (520, "14,000.00", True)])
    return [{"items": [*items, (40, 60, pf.FOOTER)]}]


def test_sc90_whole_hours_on_several_rows_are_one_block_and_one_table(tmp_path):
    """Hours 40, 4 and 8 line up in a column of their own under Hours: no second block, no row labelled with a number, and rate x hours = this
    period (25.00 x 40 = 1,000.00; 37.50 x 4 = 150.00; 25.00 x 8 = 200.00) decides the Rate and Hours roles."""
    found = paystub_tables.read(fx.read_pdf(tmp_path, hours_page()))

    [table] = found.tables
    assert table.block is None and table.partner is None and table.pages == [1]
    assert [row.label for row in table.rows] == ["Regular", "Overtime", "Holiday"]
    assert [[token.text for token in row.amounts.values()] for row in table.rows] == [[row[1], row[2], row[3], row[4]] for row in WHOLE_HOURS]
    assert [column.labels for column in table.columns] == [["Rate"], ["Hours"], ["Current"], ["YTD"]]
    assert [found.roles[0].roles[column.id] for column in table.columns] == ["rate", "hours", "current", "ytd"]
    assert [total.label for total in table.totals] == ["Gross Pay"] and found.unplaced == []


def test_sc90_a_whole_number_under_no_heading_on_one_row_stays_label_text(tmp_path):
    """FR-90 keeps a column of whole numbers only under a heading word or on at least two rows: here one row prints `40` and nothing is headed."""
    rows = [("Regular", "40", "1,000.00", "13,000.00"), ("Overtime", "", "150.00", "600.00")]
    items = [item for number, (label, hours, current, ytd) in enumerate(rows)
             for item in row_items(680 - 16 * number, [(40, label), (330, hours, True), (430, current, True), (520, ytd, True)])]
    reading = pay_tables.read(fx.read_pdf(tmp_path, [{"items": [*items, (40, 60, pf.FOOTER)]}]))

    [table] = reading.tables
    assert [column.labels for column in table.columns] == [[], []]
    assert [row.label for row in table.rows] == ["Regular 40", "Overtime"]
