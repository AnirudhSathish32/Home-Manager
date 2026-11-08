"""The pay stub follow-up that makes one path for text PDFs (specs/pdf-table-engine-paystubs-cleanup).

SL-04: SC-90 at Record level, SC-92, SC-93 and SC-97 (one path for text PDFs, FR-93 – FR-95, FR-99), and the mixed text-and-scan file (review pass 1, M3).

SL-03: SC-91, the layouts the generator avoided (FR-92 a, b, d, e, f), hand-built: the literals are written in each test, and the expected values follow from
them by the spec's rules, not from what the code produced.

SL-02: SC-90 step 1, the sectioned payslip through the engine alone (FR-89 heading phrases split by column, FR-90 whole-number amounts, FR-91 totals
covering several sections), with the details-box line of m7 and the page of whole hours on several rows. Expected values are the contract's literals
and the fixture's printed numbers, not what the code produced. No store and no model: the engine is read from a saved PDF reading.
"""

from decimal import Decimal
import json
import logging

from home_manager.core.jobs import Work
from home_manager.documents import extraction, pay_tables
from home_manager.documents.layout_context import evidence_tables
from home_manager.documents.pdf_reader import read_result
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance import paystub_tables
from home_manager.finance.ledger import Ledger
import paystub_engine_fixtures as pf
import pdf_import_fixtures as fx
from table_engine_fixtures import row_items, width
from test_paystub_engine_record import PS_CLASSES, Run, auto, expect, no_network, printed, started, swapped  # noqa: F401
from test_pdf import capture, make_pdf, pdf_store  # noqa: F401
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


# --- SC-90 (code review round 1, R1-1): rows printed in whole numbers only -----------------------------------------------------

def whole_page(rows, above=()):
    """A headed `Description Current YTD` table (columns right-aligned at 430 and 520), `above` the heading lines of a details box."""
    items = [item for number, (label, *cells) in enumerate(above) for item in row_items(740 - 16 * number, [(40, label), *[(430, cells[0], True)]])] if above else []
    items += row_items(700, [(40, "Description"), (430, "Current", True), (520, "YTD", True)])
    for number, (label, current, ytd) in enumerate(rows):
        items += row_items(680 - 16 * number, [(40, label), (430, current, True), (520, ytd, True)])
    return [{"items": [*items, (40, 60, pf.FOOTER)]}]


def check_the_whole_number_table(found, texts):
    [table] = found.tables
    assert [column.labels for column in table.columns] == [["Current"], ["YTD"]]
    assert [found.roles[0].roles[column.id] for column in table.columns] == ["current", "ytd"]
    assert [(row.label, [token.text for token in row.amounts.values()]) for row in table.rows] == [
        ("Regular", list(texts[0])), ("Bonus", list(texts[1]))]
    [total] = table.totals
    assert (total.label, total.kind, [token.text for token in total.values.values()]) == ("Gross Pay", "gross", list(texts[2]))
    assert found.unplaced == [] and found.notes == [] and paystub_tables.mismatches(found) == []  # the total holds: 100 + 20 = 120, 1300 + 260 = 1560


def test_sc90_r1_1_a_table_printed_in_whole_numbers_only_reads_three_rows_with_the_total_holding(tmp_path):
    found = paystub_tables.read(fx.read_pdf(tmp_path, whole_page([("Regular", "100", "1300"), ("Bonus", "20", "260"), ("Gross Pay", "120", "1560")])))

    check_the_whole_number_table(found, [("100", "1300"), ("20", "260"), ("120", "1560")])
    assert [row.amounts[column.id].value[0] for row in found.tables[0].rows for column in found.tables[0].columns] == [
        Decimal(100), Decimal(1300), Decimal(20), Decimal(260)]


def test_sc90_r1_1_a_whole_number_total_that_does_not_add_up_is_noted(tmp_path):
    found = paystub_tables.read(fx.read_pdf(tmp_path, whole_page([("Regular", "100", "1300"), ("Bonus", "20", "260"), ("Gross Pay", "125", "1560")])))

    [note] = paystub_tables.mismatches(found)
    assert '"Gross Pay" 125 (this period)' in note and "add up to 120" in note


def test_sc90_r1_1_a_whole_number_in_a_table_of_decimal_amounts_is_an_amount_of_its_column(tmp_path):
    found = paystub_tables.read(fx.read_pdf(tmp_path, whole_page([("Regular", "100", "1300"), ("Bonus", "20.00", "260.00"), ("Gross Pay", "120.00", "1560.00")])))

    check_the_whole_number_table(found, [("100", "1300"), ("20.00", "260.00"), ("120.00", "1560.00")])


def test_sc90_r1_1_a_details_box_above_the_whole_number_table_forms_no_row(tmp_path):
    """`Federal Allowances 2` and `Exemptions 1` print above the first heading, in the Current column's edge: no amount, no row, no stray line."""
    pages = whole_page([("Regular", "100", "1300"), ("Bonus", "20", "260"), ("Gross Pay", "120", "1560")],
                       above=[("Federal Allowances", "2"), ("Exemptions", "1")])
    result = fx.read_pdf(tmp_path, pages)
    found = paystub_tables.read(result)

    check_the_whole_number_table(found, [("100", "1300"), ("20", "260"), ("120", "1560")])
    assert "Federal Allowances" not in [row.label for table in found.tables for row in table.rows]


def test_sc90_r1_1_a_one_row_whole_number_column_under_no_heading_stays_text(tmp_path):
    items = row_items(680, [(40, "Regular"), (430, "100", True)])
    reading = pay_tables.read(fx.read_pdf(tmp_path, [{"items": [*items, (40, 60, pf.FOOTER)]}]))

    assert reading.tables == [] and reading.unplaced == []


def test_sc90_r1_1_a_column_of_integer_only_rows_with_no_heading_over_it_stays_text_though_two_rows_line_up(tmp_path):
    """Stricter than a pay line's column (R-B): `Current` is headed, the second column is not, so its two rows' numbers are no amounts and no row forms."""
    items = row_items(700, [(40, "Description"), (430, "Current", True)])
    for number, (label, current, other) in enumerate([("Regular", "100", "1300"), ("Bonus", "20", "260")]):
        items += row_items(680 - 16 * number, [(40, label), (430, current, True), (520, other, True)])
    reading = pay_tables.read(fx.read_pdf(tmp_path, [{"items": [*items, (40, 60, pf.FOOTER)]}]))

    assert reading.tables == [] and reading.unplaced == []


def test_sc90_r1_1_a_stub_printed_in_whole_numbers_records_its_lines_in_minor_units(pdf_store, local_model):
    """100 / 1300 and 20 / 260 are amounts of the Current and YTD columns: the record's lines hold 10000 / 130000 and 2000 / 26000, each citing a cell."""
    items = [*pf.page_of([*row_items(700, [(40, "Description"), (430, "Current", True), (520, "YTD", True)]),
                          *[item for number, (label, current, ytd) in enumerate([("Regular", "100", "1300"), ("Bonus", "20", "260"), ("Gross Pay", "120", "1560")])
                            for item in row_items(680 - 16 * number, [(40, label), (430, current, True), (520, ytd, True)])]])["items"]]
    run = started(pdf_store, local_model, [{"items": items}])
    run.stub(classes=[("Regular", "earnings", "regular_pay", "Regular"), ("Bonus", "earnings", "bonus", "Bonus")],
             summary={"gross_pay": ("Gross Pay", "120"), "gross_pay_ytd": ("Gross Pay", "1560")})
    run.extract()

    record = run.record
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [("Regular", 10000, 130000), ("Bonus", 2000, 26000)]
    assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"]) == (12000, 156000)
    assert all(line["cell_evidence"] for line in record["lines"])
    assert not [note for note in run.notes if "doesn't match" in note]


# --- SC-91: the layouts the generator avoided (FR-92) ------------------------------------------------------------------------------------------

def values_by_role(found, table):
    """The printed amount texts of each role's column, one per row printing it."""
    roles = found.roles[found.tables.index(table)].roles
    return {roles[column.id]: [row.amounts[column.id].text for row in table.rows if column.id in row.amounts] for column in table.columns}


def test_sc91_a_rows_all_printed_negative_with_year_to_date_left_give_this_period_on_the_right(tmp_path):
    """(a): `-600.00 / -50.00` and `-240.00 / -20.00` share a sign, so they vote by magnitude: -50.00 and -20.00 are smaller, the right column is this period,
    from numbers alone (no heading, no guess). Total Taxes -840.00 / -70.00 is the sum of each column, so the table is a pay table."""
    rows = [("Federal Income Tax", "-600.00", "-50.00"), ("State Income Tax", "-240.00", "-20.00"), ("Total Taxes", "-840.00", "-70.00")]
    items = [item for number, (label, left, right) in enumerate(rows) for item in row_items(680 - 16 * number, [(40, label), (430, left, True), (520, right, True)])]
    found = paystub_tables.read(fx.read_pdf(tmp_path, [pf.page_of(items)]))

    [table] = found.tables
    assert values_by_role(found, table) == {"ytd": ["-600.00", "-240.00"], "current": ["-50.00", "-20.00"]}
    assert found.roles[0].decided_by == "numbers" and found.guesses == [] and found.notes == []


def stacked_pages():
    """Page 1: a Current / YTD / Hours / Rate table (right edges 304, 376, 448, 520). Page 2 opens with a second table titled Taxes whose two columns sit at
    415 and 487, 33 points left of page 1's Hours and Rate columns, so they lie over them at a page offset of -33 (the generator's failing layout)."""
    head = row_items(700, [(40, "Description"), (304, "Current", True), (376, "YTD", True), (448, "Hours", True), (520, "Rate", True)])
    rows = [("Regular", "2,500.00", "32,500.00", "80.00", "31.25"), ("Overtime", "187.50", "1,125.00", "4.00", "46.8750"), ("Gross Pay", "2,687.50", "33,625.00", "", "")]
    one = [item for number, (label, *cells) in enumerate(rows) for item in row_items(680 - 16 * number, [(40, label), *zip((304, 376, 448, 520), cells, (True,) * 4)])]
    two = [(40, 740, "Taxes"), *[item for number, (label, *cells) in enumerate([("Federal Income Tax", "295.63", "3,698.75"), ("Social Security", "166.63", "2,084.75"),
                                                                              ("Total Taxes", "462.26", "5,783.50")])
                                for item in row_items(720 - 16 * number, [(40, label), *zip((415, 487), cells, (True, True))])]]
    return [pf.page_of([*head, *one]), pf.page_of(two, above=())]


def test_sc91_b_a_second_table_starting_a_page_at_other_edges_is_a_table_of_its_own(tmp_path):
    """(b): page 2's rows lie 33 points left of page 1's Hours and Rate columns (the rows' columns line up with them at one page offset, -33, which is more
    than ALIGN font sizes), so they are not page 1's table continued: a new table with its own two columns, page 1's four columns unchanged. And phase 2's
    PS-CONT (same columns, no offset, or 6 points) still continues."""
    found = pay_tables.read(fx.read_pdf(tmp_path, stacked_pages()))

    first, second = found.tables
    assert (first.pages, len(first.columns), [row.label for row in first.rows]) == ([1], 4, ["Regular", "Overtime"])
    assert (second.pages, len(second.columns), [row.label for row in second.rows]) == ([2], 2, ["Federal Income Tax", "Social Security"])
    for name in ("PS-CONT", "PS-CONT-NH"):
        (tmp_path / name).mkdir()
        [table] = pay_tables.read(fx.read_pdf(tmp_path / name, pf.FIXTURES[name]())).tables
        assert table.pages == [1, 2], name


def one_column_table(upper, lower):
    """A table of one amount column (right edge 520) under a heading of two lines, `upper` over `lower`, with two rows and their gross total."""
    items = [*row_items(700, [(520, upper, True)]), *row_items(686, [(40, "Description"), (520, lower, True)])]
    for number, (label, amount) in enumerate([("Salary", "2,500.00"), ("Commission", "300.00"), ("Gross Pay", "2,800.00")]):
        items += row_items(666 - 16 * number, [(40, label), (520, amount, True)])
    return items


def test_sc91_d_a_one_column_table_under_a_two_line_heading_reads_like_one_under_one_line(tmp_path):
    """(d): `This` over `Period` is the column's heading (this period); `Year to` over `Date` is year to date. Before, only the lower line was attached
    (`Period`, `Date`), so the column took its role from the numbers alone: this period."""
    for name, (upper, lower), role in (("this", ("This", "Period"), "current"), ("ytd", ("Year to", "Date"), "ytd")):
        (tmp_path / name).mkdir()
        found = paystub_tables.read(fx.read_pdf(tmp_path / name, [pf.page_of(one_column_table(upper, lower))]))
        [table] = found.tables
        assert [column.labels for column in table.columns] == [[upper, lower]], name
        assert values_by_role(found, table) == {role: ["2,500.00", "300.00"]}, name
        assert found.guesses == [], name


HOURS_MULTIPLE = [("Regular", "12.00", "25.00", "300.00", "3,600.00"), ("Overtime", "12.00", "37.50", "450.00", "5,400.00"), ("Gross Pay", "", "", "750.00", "9,000.00")]


def hours_multiple_pages(heading):
    """Regular prints 12.00 hours × 25.00 = 300.00 this period and 3,600.00 year to date (12 periods): 12.00 × 25.00 = 300.00 and 12.00 × 300.00 = 3,600.00,
    two products sharing the hours column. Overtime: 12.00 × 37.50 = 450.00 and 12.00 × 450.00 = 5,400.00."""
    items = row_items(700, [(40, "Description"), (260, "Hours", True), (330, "Rate", True), (430, "Current", True), (520, "YTD", True)]) if heading else []
    for number, (label, hours, rate, current, ytd) in enumerate(HOURS_MULTIPLE):
        items += row_items(680 - 16 * number, [(40, label), (260, hours, True), (330, rate, True), (430, current, True), (520, ytd, True)])
    return [pf.page_of(items)]


def test_sc91_e_hours_equal_to_the_ytd_multiple_take_this_period_as_the_product_that_is_the_other_s_factor(tmp_path):
    """(e), with headings: hours 12.00, rate 25.00, this period 300.00 (30000), year to date 3,600.00 (360000), no guess, from the headings and numbers.
    And two products sharing the rate column (phase 2 PS-YTDH) keep their SC-57 values."""
    found = paystub_tables.read(fx.read_pdf(tmp_path, hours_multiple_pages(True)))

    [table] = found.tables
    assert values_by_role(found, table) == {"hours": ["12.00", "12.00"], "rate": ["25.00", "37.50"], "current": ["300.00", "450.00"],
                                            "ytd": ["3,600.00", "5,400.00"]}
    assert found.guesses == [] and found.notes == []
    # PS-YTDH (phase 2 SC-57 a), two products sharing the rate column: Hours, Rate, Current, YTD Hours, YTD keeps YTD Hours as other.
    (tmp_path / "ytdh").mkdir()
    ytdh = paystub_tables.read(fx.read_pdf(tmp_path / "ytdh", pf.FIXTURES["PS-YTDH"]()))
    assert [ytdh.roles[0].roles[column.id] for column in ytdh.tables[0].columns] == ["hours", "rate", "current", "other", "ytd"]
    assert ytdh.roles[0].decided_by == "numbers" and ytdh.guesses == []


def test_sc91_e_without_a_heading_it_is_a_columns_guessed_note_with_the_same_values(tmp_path):
    """(e), no heading: the same roles and values, and one `columns_guessed` note (the phase 2 wording)."""
    found = paystub_tables.read(fx.read_pdf(tmp_path, hours_multiple_pages(False)))

    [table] = found.tables
    assert values_by_role(found, table) == {"hours": ["12.00", "12.00"], "rate": ["25.00", "37.50"], "current": ["300.00", "450.00"],
                                            "ytd": ["3,600.00", "5,400.00"]}
    assert [guess.kind for guess in found.guesses] == [paystub_tables.COLUMNS_GUESSED]
    assert found.notes == ["Page 1: the right column was taken as this period; the printed amounts didn't tell the two columns apart."]


# (f): the first two stubs of the generator's failing layout (seed 20261104, case 52) kept to their left blocks: one pay column, a Leave table whose columns line
# up with it by their left and centre edges, then the next stub.
def leave_rows(top):
    return [(40, top, "Leave"), (113.32, top, "Accrued"), (196.66, top, "Used"), (253.87, top, "Balance"),
            (40, top - 16, "Vacation"), (124.98, top - 16, "40.00"), (200.54, top - 16, "8.00"), (264.98, top - 16, "32.00"),
            (40, top - 32, "Sick"), (124.98, top - 32, "24.00"), (200.54, top - 32, "0.00"), (264.98, top - 32, "24.00")]


def stub_left(top, base, retro, gross, net):
    return [(40, top, "Pay date 2026-04-10"), (40, top - 12, "Pay period 2026-03-23 to 2026-04-05"), (40, top - 24, "NORTHWIND SYNTH LLC"),
            (40, top - 36, "Currency USD"), (40, top - 72, "Earnings"), (189.43, top - 72, "This Period"),
            (40, top - 92, "Base Pay"), (201.08, top - 92, base), (40, top - 108, "Retro Pay"), (209.42, top - 108, retro),
            (40, top - 124, "Total Earnings"), (201.08, top - 124, gross), (40, top - 156, "Net Pay"), (201.08, top - 156, net)]


def test_sc91_f_a_leave_table_lined_up_with_the_pay_column_is_a_table_of_its_own(tmp_path):
    """(f): two stubs on a page, each an Earnings table (Base Pay + Retro Pay = Total Earnings) and a Leave table whose columns line up with the pay
    column by their left and centre edges. Columns are formed per table, between heading lines and stub starts, so the Leave amounts don't merge with the
    pay column: each stub reads as one table with its two rows and its totals, and the Leave rows give no pay line."""
    items = [*stub_left(780, "2,662.41", "225.58", "2,888.00", "2,250.00"), *leave_rows(584), *stub_left(516, "2,527.84", "210.70", "2,738.54", "2,189.00"),
             *leave_rows(320)]
    found = paystub_tables.read(fx.read_pdf(tmp_path, [pf.page_of(items, above=())]))

    assert [[row.label for row in table.rows] for table in found.tables] == [["Base Pay", "Retro Pay"], ["Base Pay", "Retro Pay"]]
    assert [[row.amounts[table.columns[0].id].text for row in table.rows] for table in found.tables] == [["2,662.41", "225.58"], ["2,527.84", "210.70"]]
    assert [[total.label for total in table.totals] for table in found.tables] == [["Total Earnings", "Net Pay"]] * 2
    assert [[row.label for row in table.rows] for table in found.other_tables] == [["Vacation", "Sick"]] * 2


def leave_rows_one_run_heading(top, title):
    """The Leave table of `leave_rows` with its heading printed as one run ("Accrued Vacation Used Leave Balance"), under a title line of its own when `title`."""
    return [*([(40, top + 16, "Leave")] if title else []), (113.32, top, "Accrued Vacation Used Leave Balance"), *leave_rows(top)[4:]]


def test_sc91_f_a_leave_table_under_a_one_run_heading_is_a_table_of_its_own(tmp_path):
    """(f), review round 1 R1-2: the Leave heading is one run of five words, with or without a title line of its own above it, and the leave amounts line up
    with the pay column. The cut before clustering recognises it as a heading (FR-89), so Base Pay and Retro Pay keep the pay column and the leave rows are no
    pay rows."""
    for title in (False, True):
        folder = tmp_path / f"title-{title}"
        folder.mkdir()
        items = [*stub_left(780, "2,662.41", "225.58", "2,888.00", "2,250.00"), *leave_rows_one_run_heading(584, title)]
        found = paystub_tables.read(fx.read_pdf(folder, [pf.page_of(items, above=())]))

        assert [[row.label for row in table.rows] for table in found.tables] == [["Base Pay", "Retro Pay"]]
        assert [[row.amounts[found.tables[0].columns[0].id].text for row in table.rows] for table in found.tables] == [["2,662.41", "225.58"]]
        assert [[total.label for total in table.totals] for table in found.tables] == [["Total Earnings", "Net Pay"]]
        assert [[row.label for row in table.rows] for table in found.other_tables] == [["Vacation", "Sick"]]


LITERALS = [("Regular", ["2,000.00", "24,000.00"]), ("Overtime", ["150.00", "900.00"]), ("Vision", ["6.00", "6.00"]), ("Medical", ["40.00", "480.00"]),
            ("Dental", ["8.00", "96.00"])]


def stacked_stub_with_title(title, rows):
    """A stacked stub (Description / Current / YTD, amount edges 430 and 520): Regular, Overtime and Total Earnings, then a section `title` line of
    three or more words in the label column, then `rows` ((label, current, ytd) tuples)."""
    items = pf.head(700, ("Description", "Current", "YTD"), (430, 520))
    y = 680
    for row in (("Regular", "2,000.00", "24,000.00"), ("Overtime", "150.00", "900.00"), ("Total Earnings", "2,150.00", "24,900.00"), title, *rows):
        cells = [(40, row)] if isinstance(row, str) else [(40, row[0]), *[(edge, text, True) for edge, text in zip((430, 520), row[1:])]]
        items += row_items(y, cells)
        y -= 16
    return items


def test_sc91_f_r2_a_section_title_in_the_label_column_never_cuts_the_block(tmp_path):
    """(f), review round 2 (the R1-2 fix's regression): a title of three or more words in the label column ("Pre Tax Deductions") is no heading, because no
    word of it lies over the amounts of the row below. The block is not cut there, so one pay table holds the rows below the title, as it does with a
    one-word title; no row is unplaced."""
    for number, title in enumerate(("Deductions", "Pre Tax Deductions", "Before Tax Deductions Withheld")):
        for kind, rows, wanted in (("one", [("Vision", "6.00", "6.00")], ["Regular", "Overtime", "Vision"]),
                                   ("two", [("Medical", "40.00", "480.00"), ("Dental", "8.00", "96.00"), ("Total Deductions", "48.00", "576.00")],
                                    ["Regular", "Overtime", "Medical", "Dental"])):
            folder = tmp_path / f"{number}-{kind}"
            folder.mkdir()
            found = paystub_tables.read(fx.read_pdf(folder, [pf.page_of(stacked_stub_with_title(title, rows))]))

            [table] = found.tables
            roles = [found.roles[0].roles[column.id] for column in table.columns]
            assert roles == ["current", "ytd"], (title, kind)
            assert [(row.label, [row.amounts[column.id].text for column in table.columns]) for row in table.rows] == \
                [(label, texts) for label, texts in LITERALS if label in wanted], (title, kind)
            assert [row.label for row in table.rows] == wanted, (title, kind)
            assert [[total.label for total in table.totals]] == [["Total Earnings"] if kind == "one" else ["Total Earnings", "Total Deductions"]], (title, kind)
            assert found.other_tables == [] and found.unplaced == [] and found.pages_without_tables == []


def section_title_is_no_cut(found, label_rows):
    """One pay table of Current / YTD holds every row, the lone row under the section title included; nothing is unplaced."""
    [table] = found.tables
    assert [found.roles[0].roles[column.id] for column in table.columns] == ["current", "ytd"]
    assert [(row.label, [row.amounts[column.id].text for column in table.columns]) for row in table.rows] == label_rows
    assert [total.label for total in table.totals] == ["Total Earnings"]
    assert found.other_tables == [] and found.unplaced == [] and found.pages_without_tables == []


def test_sc91_f_r3_a_long_section_title_in_the_label_column_does_not_cut_the_block(tmp_path):
    """(f), review round 2 R2-1: a section title of eleven words starts at the label column and runs over both amount columns (the amounts are at 430 and
    520). It is one piece and starts at the label's left edge, so it is no heading: Regular, Overtime and Vision stay in one table with their literals."""
    title = "Before Tax Deductions For Medical Insurance, Dental, Vision And Retirement Contributions"
    found = paystub_tables.read(fx.read_pdf(tmp_path, [pf.page_of(stacked_stub_with_title(title, [("Vision", "6.00", "6.00")]))]))

    section_title_is_no_cut(found, [(label, texts) for label, texts in LITERALS if label in ("Regular", "Overtime", "Vision")])


def test_sc91_f_r3_a_centred_section_title_over_both_columns_does_not_cut_the_block(tmp_path):
    """(f), review round 2 R2-1: a shorter title centred over the two amount columns starts right of the label column, but it is one piece and no word of
    it lines up with each amount by one edge, so it is no heading either. A four-word title placed so its words do line up that way (shifted 15 from the
    centre) is the cut's known limit (docs/documents.md "Known limits"), not tested here."""
    for number, (title, shift) in enumerate((("Pre Tax Deductions", 0), ("Pre Tax Deductions", -30), ("Before Tax Deductions Withheld", -40))):
        folder = tmp_path / str(number)
        folder.mkdir()
        centre = (430 - width("6.00") + 520) / 2 + shift
        items = [(round(centre - width(text) / 2, 3) if text == title else x, y, text) for x, y, text in stacked_stub_with_title(title, [("Vision", "6.00", "6.00")])]
        found = paystub_tables.read(fx.read_pdf(folder, [pf.page_of(items)]))

        section_title_is_no_cut(found, [(label, texts) for label, texts in LITERALS if label in ("Regular", "Overtime", "Vision")])


def test_sc91_f_r3_a_leave_table_under_a_two_word_one_run_heading_is_a_table_of_its_own(tmp_path):
    """(f), review round 2 R2-2: the Leave heading is the two words "Used Balance" in one run (a heading over two leave amounts, right of the label column),
    with or without a title line "Leave" above it. The cut recognises it from its geometry, not its word count: Base Pay 2,662.41 and Retro Pay 225.58 keep
    the pay column and the leave rows are no pay rows."""
    data = [(40, 568, "Vacation"), (200.54, 568, "8.00"), (264.98, 568, "32.00"), (40, 552, "Sick"), (200.54, 552, "0.00"), (264.98, 552, "24.00")]
    for title in (False, True):
        folder = tmp_path / f"title-{title}"
        folder.mkdir()
        items = [*stub_left(780, "2,662.41", "225.58", "2,888.00", "2,250.00"), *([(40, 600, "Leave")] if title else []),
                 (196.66, 584, "Used"), (230, 584, "Balance"), *data]
        found = paystub_tables.read(fx.read_pdf(folder, [pf.page_of(items, above=())]))

        [table] = found.tables
        assert [(row.label, row.amounts[table.columns[0].id].text) for row in table.rows] == [("Base Pay", "2,662.41"), ("Retro Pay", "225.58")], title
        assert [total.label for total in table.totals] == ["Total Earnings", "Net Pay"], title
        assert [[row.label for row in other.rows] for other in found.other_tables] == [["Vacation", "Sick"]], title
        assert found.unplaced == [], title


# --- SL-04: the record of a text-PDF stub never comes from a printed table (FR-93, FR-94)----------------------------------------------------

def printed_grid_ids(run):
    """The ids of the reader's printed tables (`table_grid`, source `pdf_text`) of the run's file."""
    return {table.id for table in evidence_tables(run.evidence) if getattr(table, "source", None) == "pdf_text"}


def check_no_grid(run):
    """C-no-grid (test contract): (1) every cell the record cites is a cell of the run result's `pay_tables`, else the value is a flat line's (no cell
    reference); (2) no request after the classification carries a printed table. An engine cell may reuse a printed cell's id (phase 2 FR-66)."""
    result = run.run["result"]
    engine_cells = {cell["id"] for table in result["pay_tables"] for row in [*table["header_rows"], *table["rows"]] for cell in row["cells"]}
    cited = [reference for row in result["rows"] for reference in (row.get("cell_evidence") or {}).values() if isinstance(reference, dict)]
    cited += list((result.get("summary_cell_evidence") or {}).values())
    assert {reference["cell_id"] for reference in cited} <= engine_cells
    grid = printed_grid_ids(run)
    assert grid  # The fixture has printed tables to ignore.
    asked = [json.loads(request["messages"][1]["content"]).get("reported_tables", []) for request in run.local_model["requests"][run.before:]
             if request["response_format"]["json_schema"]["name"] != "Classification"]
    assert not [table for tables in asked for table in tables if table["table_id"] in grid]


def sectioned_run(pdf_store, local_model):
    """The record test's sectioned payslip file (page 1 and the benefits page) with the model stubs of test_layout_consumers: every row classified and
    the summary cited from the lines, so the values must come from the engine's cells."""
    run = started(pdf_store, local_model, [{"items": [(30, 760, "SYNTH CONSULTING LTD"), (30, 745, "Currency USD"), *sectioned_payslip_items()]}, BENEFITS],
                  name="sectioned.pdf")
    rows = [("Regular Salary", "earnings", "regular_pay"), ("Relocation Bonus", "earnings", "bonus"), ("Federal Tax", "tax", "federal_income_tax"),
            ("Social Security Tax", "tax", "social_security"), ("Medicare Tax", "tax", "medicare"), ("GA State Tax", "tax", "state_income_tax"),
            ("Medical HDP", "pre_tax", "health"), ("Vision Insurance", "pre_tax", "vision"), ("Dental PPO", "pre_tax", "dental"),
            ("HSA Additional", "pre_tax", "hsa"), ("401K Plan", "pre_tax", "retirement_pretax"), ("Co Match 401K", "employer_paid", "other")]
    summary = {"gross_pay": ("Regular Salary", "4,000.00"), "gross_pay_ytd": ("Regular Salary", "84,000.00"), "net_pay": ("Net Payment", "2,646.00"),
               "net_pay_ytd": ("Net Payment", "59,566.00"), "deductions": ("Total Deductions", "1,354.00")}
    cite = run.cite
    run.cite = lambda text, quote=None: cite("Pay Date" if text == "Pay date" else text, quote)  # This payslip prints its date as "Pay Date".
    run.stub(classes=[(label, group, category, label) for label, group, category in rows], summary=summary, employer="SYNTH CONSULTING LTD",
             details={"pay_date": run.value("10/09/2026", "Pay Date")})
    run.extract()
    return run


def test_sc90_the_sectioned_payslip_record_has_the_same_values_from_engine_cells_and_one_total_note(pdf_store, local_model):
    run = sectioned_run(pdf_store, local_model)
    record = run.record
    assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"], record["net_pay_minor"], record["net_pay_ytd_minor"], record["deductions_minor"]) == (
        400000, 8800000, 264600, 5956600, None)
    assert (record["display"]["deductions_minor"], record["display"]["total_deductions_minor"]) == ("358.00 USD", "1,354.00 USD")
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [
        ("Regular Salary", 400000, 8400000), ("Relocation Bonus", None, 400000), ("Federal Tax", 50000, 1050000), ("Social Security Tax", 24800, 520800),
        ("Medicare Tax", 5800, 121800), ("GA State Tax", 19000, 399000), ("Medical HDP", 9000, 189000), ("Vision Insurance", 600, 600),
        ("Dental PPO", 1200, 25200), ("HSA Additional", 5000, 105000), ("401K Plan", 20000, 420000), ("Co Match 401K", 16000, 336000)]
    assert (record["lines"][0]["details"]["hours"]["text"], record["lines"][0]["details"]["rate"]["text"]) == ("80", "50.00")
    assert not any(words in issue for issue in record["issues"]
                   for words in ("column headings", "source cell", "multiple amounts", "not accounted for", "left out", "add up"))
    check_no_grid(run)
    assert not [note for note in run.notes if note.startswith("Page 1: no pay table")]
    [doesnt_match] = [note for note in run.notes if "doesn't match" in note]
    assert "28,434.00" in doesnt_match and "28,314.00" in doesnt_match and "1,354.00" not in doesnt_match


MINI_13 = pf.mini_pages(("2026-07-03", 13))[0]["items"]
MINI_CLASSES = [("Regular", "earnings", "regular_pay", "Regular"), ("Federal Income Tax", "tax", "federal_income_tax", "Federal Income Tax")]
MINI_SUMMARY = {"gross_pay": ("Gross Pay", "2,000.00"), "gross_pay_ytd": ("Gross Pay", "26,000.00"), "net_pay": ("Net Pay", "1,800.00"),
                "net_pay_ytd": ("Net Pay", "23,400.00"), "taxes": ("Total Taxes", "200.00")}
OTHER_TABLE = [*pf.head(700, ("Item", "Code A", "Code B"), (430, 520)),
               *pf.lay(680, [("row", "Adjustment", ("50.00", "50.00")), ("row", "Other", ("10.00", "10.00"))], (430, 520)), fx.footer(pf.FOOTER, 60)]
NO_TABLE_NOTE = "Page 2: no pay table was found in the printed columns, so its amounts are the reading's; check them."


def test_sc92_a_page_whose_table_the_engine_does_not_trust_is_read_like_flat_text(pdf_store, local_model):
    run = started(pdf_store, local_model, [{"items": MINI_13}, {"items": OTHER_TABLE}])
    assert paystub_tables.read(run.evidence).pages_without_tables == [2]  # An other table: no pay table on page 2.
    assert printed_grid_ids(run)  # Page 2's printed table is there for the reader to be tempted by.
    adjustment = {"description": "Adjustment", "group": "earnings", "category": "other", "current": "50.00", "ytd": None, "evidence": run.cite("Adjustment")}
    run.stub(classes=MINI_CLASSES, summary=MINI_SUMMARY, extra_lines=[adjustment])
    run.extract()
    record = run.record
    assert [(line["description"], line["line_group"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]] == [
        ("Regular", "earnings", 200000, 2600000), ("Federal Income Tax", "tax", 20000, 260000), ("Adjustment", "earnings", 5000, None)]
    assert record["lines"][2]["cell_evidence"] in (None, {})  # The model's value, judged by the flat rules: no cell cited.
    assert NO_TABLE_NOTE in run.notes and NO_TABLE_NOTE not in record["issues"]
    assert (record["gross_pay_minor"], record["gross_pay_ytd_minor"], record["net_pay_minor"], record["net_pay_ytd_minor"]) == (200000, 2600000, 180000, 2340000)
    check_no_grid(run)


def test_sc92_m4_a_pay_table_whose_roles_all_end_other_puts_its_page_in_pages_without_tables_and_in_no_adapted_table(tmp_path, monkeypatch):
    """The untrusted case: page 2's table is found to be a pay table (a side-by-side partner, say) but none of its columns is this period, year to date,
    hours or rate. Its page is a page without a pay table and in no adapted table, so Record reads it flat."""
    real = paystub_tables.decide

    def decide(table):
        roles, guesses, found = real(table)
        if table.pages[0] != 2:
            return roles, guesses, found
        return paystub_tables.Roles(table.id, dict.fromkeys(roles.roles, "other"), "numbers"), [], True
    monkeypatch.setattr(paystub_tables, "decide", decide)
    found = paystub_tables.read(fx.read_pdf(tmp_path, [{"items": MINI_13}, {"items": OTHER_TABLE}]))
    assert paystub_tables.untrusted_pages(found) == {2} and [table.pages for table in found.tables] == [[1], [2]]
    assert found.pages_without_tables == [2] and found.pages == {1} and found.engine_pages == {1}
    assert {row.page for table in found.adapted for row in table.rows} == {1}
    part = paystub_tables.for_lines(found, set(found.lines_of.values()))
    assert part.pages_without_tables == [2] and {row.page for table in part.adapted for row in table.rows} == {1}


def summary_box_over_untrusted_pair():
    """A summary box above a page whose left table reads (This Period, YTD) and whose right table's columns (Code A, Code B) decide nothing, so its roles end
    all `other` and the page is untrusted by itself, with no monkeypatch."""
    box = row_items(740, [(150, "Gross", True), (250, "Taxes", True), (350, "Deductions", True), (450, "Net", True)])
    box += row_items(724, [(40, "Current"), (150, "1,000.00", True), (250, "200.00", True), (350, "100.00", True), (450, "700.00", True)])
    box += row_items(708, [(40, "YTD"), (150, "5,000.00", True), (250, "1,000.00", True), (350, "500.00", True), (450, "3,500.00", True)])
    heading = row_items(670, [(40, "Earnings"), (200, "Current", True), (270, "YTD", True), (300, "Deductions"), (460, "Code A", True), (530, "Code B", True)])
    data = [("Regular", "900.00", "4,500.00", "Dental", "30.00", "30.00"), ("Bonus", "100.00", "500.00", "Vision", "10.00", "10.00")]
    rows = [item for n, (label, current, ytd, right, one, two) in enumerate(data)
            for item in row_items(650 - n * 16, [(40, label), (200, current, True), (270, ytd, True), (300, right), (460, one, True), (530, two, True)])]
    return pf.page_of([*box, *heading, *rows])


def test_sc92_r1_3_an_untrusted_page_holding_a_summary_box_is_still_a_page_without_a_pay_table(tmp_path):
    """FR-93 / phase 2 FR-64 (review round 1, R1-3): the summary box keeps its page in `pages` and its cells, but the untrusted page is also listed in
    `pages_without_tables` and `untrusted`, and `for_lines` keeps both for the part holding its lines."""
    found = paystub_tables.read(fx.read_pdf(tmp_path, [summary_box_over_untrusted_pair()]))
    assert paystub_tables.untrusted_pages(found) == {1} and len(found.boxes) == 1 and found.pages == {1}
    assert found.pages_without_tables == [1] and found.untrusted == {1} and found.engine_pages == set()
    part = paystub_tables.for_lines(found, set(found.lines_of.values()))
    assert part.pages_without_tables == [1] and part.untrusted == {1} and part.pages == {1}


def test_sc92_r1_3_an_untrusted_page_holding_a_summary_box_gets_the_no_pay_table_note(pdf_store, local_model):
    """The same page through Extract: the amounts are the model's (read like flat text), so the record carries FR-64's note for page 1."""
    run = started(pdf_store, local_model, [summary_box_over_untrusted_pair()])
    summary = {"gross_pay": ("Current", "1,000.00"), "gross_pay_ytd": ("YTD", "5,000.00"), "net_pay": ("Current", "700.00"), "net_pay_ytd": ("YTD", "3,500.00")}
    extra = [{"description": label, "group": group, "category": "other", "current": current, "ytd": ytd, "evidence": run.cite(label)}
             for label, group, current, ytd in [("Regular", "earnings", "900.00", "4,500.00"), ("Bonus", "earnings", "100.00", "500.00"),
                                                ("Dental", "post_tax", "30.00", "30.00"), ("Vision", "post_tax", "10.00", "10.00")]]
    run.stub(classes=[], summary=summary, extra_lines=extra)
    run.extract()
    assert "Page 1: no pay table was found in the printed columns, so its amounts are the reading's; check them." in run.notes


def test_sc93_with_the_engine_down_a_wrongly_swapped_amount_is_nulled_by_the_flat_rules_on_every_page(pdf_store, local_model, monkeypatch, caplog):
    """FR-94: the stub is read like flat text on every page, so the paystub-columns checks judge every line (printed_columns is every line of the part)
    and a swapped pair is left out, as on a photo; no printed table's cell is cited and none is shown to the model."""
    run = started(pdf_store, local_model, pf.ps_pages())
    monkeypatch.setattr(paystub_tables, "read", lambda evidence: (_ for _ in ()).throw(RuntimeError("injected engine fault")))
    by_label = {label: (hours, rate, current, ytd) for label, hours, rate, current, ytd, kind in pf.PS_ROWS if kind == "row"}
    lines = [{"description": description, "group": group, "category": category, "evidence": run.cite(label),
              "current": by_label[label][3] if label == "Overtime" else by_label[label][2],  # Overtime's two amounts are given swapped.
              "ytd": by_label[label][2] if label == "Overtime" else by_label[label][3],
              "hours": by_label[label][0], "rate": by_label[label][1]} for description, group, category, label in PS_CLASSES]
    run.stub(summary=printed(pf.PS_ROWS))
    run.runs = lambda: [[False, [line.id for line in run.lines]]]
    run.local_model["by_schema"].update(PayLines=[{"lines": lines}], PayRowClasses=[])
    with caplog.at_level(logging.ERROR):
        run.extract()
    record = run.record
    assert extraction.PAY_FAILED_NOTE in run.notes
    by_name = {line["description"]: line for line in record["lines"]}
    assert (by_name["Overtime"]["current_minor"], by_name["Overtime"]["ytd_minor"]) == (None, None)
    assert any("Overtime" in issue and "doesn't match the printed columns" in issue for issue in record["issues"])
    assert [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"] if line["description"] != "Overtime"] == [
        (line[0], line[2], line[3]) for line in pf.EXP_PS_LINES if line[0] != "Overtime"]
    assert not [1 for line in record["lines"] if line["cell_evidence"]]
    assert not [1 for request in run.local_model["requests"][run.before:] if request["response_format"]["json_schema"]["name"] != "Classification"
                and json.loads(request["messages"][1]["content"]).get("reported_tables")]


# --- SC-97: the version ------------------------------------------------------------------------------------------------------------------

def test_sc97_the_version_changed_and_extract_again_rereads_the_undecided_stub_and_keeps_the_reviewed_one(pdf_store, local_model, monkeypatch):
    previous = "typed-extraction-v35-paystub-engine"
    assert extraction.EXTRACTION_VERSION != previous
    with monkeypatch.context() as past:
        past.setattr(extraction, "EXTRACTION_VERSION", previous)
        undecided = started(pdf_store, local_model, pf.ps_pages(), name="undecided.pdf")
        undecided.stub()
        undecided.extract()
        reviewed = started(pdf_store, local_model, pf.ps_2l_pages(), name="reviewed.pdf")
        reviewed.stub()
        reviewed.extract()
        assert undecided.run["prompt_version"] == reviewed.run["prompt_version"] == previous
        Ledger(reviewed.store).review("income_record", reviewed.run["publication"]["id"], "verified")

    def rows():
        with reviewed.store.connection() as db:
            return ([tuple(row) for row in db.execute("SELECT * FROM income_records WHERE id=?", (reviewed.run["publication"]["id"],))],
                    [tuple(row) for row in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY id", (reviewed.run["publication"]["id"],))])
    frozen = rows()
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    for run in (undecided, reviewed):
        run.stub()
        run_id, created = run.extraction.enqueue(run.doc["id"], run.parse_id, config)
        assert created  # Not reused: the version is part of the reuse key (`reused: False`).
        run.extraction.run(run_id, Work.detached())
        run.run = run.extraction.get(run_id)
        assert run.run["status"] == "succeeded" and run.run["prompt_version"] == extraction.EXTRACTION_VERSION
    expect(undecided.record)
    assert rows() == frozen  # The reviewed record's income_records and income_lines rows are unchanged.
    assert reviewed.record["review_status"] == "verified"


# --- A file mixing a text page and a scanned page (review pass 1, M3) --------------------------------------------------------------------------

def test_a_scanned_page_of_a_text_pdf_stub_keeps_its_vision_tables_beside_the_engine_page(pdf_store, local_model):
    """Page 1 is the text stub (engine cells); page 2 is a scan whose transcription has a table. The printed tables of page 1 are dropped, the vision
    table of page 2 is shown to the model and anchors its stub's values."""
    inbox, store = pdf_store
    make_pdf(inbox / "mixed.pdf", [{"items": MINI_13}, None])
    doc = capture(inbox, store)
    local_model["output"] = {"full_text": "Other earnings\nDescription | Current | YTD\nBonus | 100.00 | 500.00"}
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    assert service.get(parse_id)["status"] == "succeeded", service.get(parse_id)["error"]
    evidence = read_result(service.get(parse_id)["result"])
    assert [page.method for page in evidence.pages] == ["embedded_text", "vision_model"]
    vision = [table for table in evidence_tables(evidence) if getattr(table, "source", None) != "pdf_text"]
    assert len(vision) == 1 and len(vision[0].rows) == 1  # The scanned page's table.
    run = Run(store, service, local_model, parse_id, doc)
    run.stub(classes=MINI_CLASSES, summary=MINI_SUMMARY)
    run.local_model["by_schema"]["PayRowClasses"].append({"lines": [{"description": "Bonus", "group": "earnings", "category": "bonus", "evidence": run.cite("Bonus")}]})
    run.extract()
    shown = [table for request in run.local_model["requests"][run.before:] if request["response_format"]["json_schema"]["name"] != "Classification"
             for table in json.loads(request["messages"][1]["content"]).get("reported_tables", [])]
    assert vision[0].id in {table["table_id"] for table in shown}  # The scanned page keeps its vision table for its stub.
    assert not {table["table_id"] for table in shown} & printed_grid_ids(run)
    record = run.record
    assert ("Bonus", 10000, 50000) in [(line["description"], line["current_minor"], line["ytd_minor"]) for line in record["lines"]]
    assert [line["current_minor"] for line in record["lines"][:2]] == [200000, 20000]
