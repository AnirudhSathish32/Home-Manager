"""The pay stub follow-up that makes one path for text PDFs (specs/pdf-table-engine-paystubs-cleanup).

SL-03: SC-91, the layouts the generator avoided (FR-92 a, b, d, e, f), hand-built: the literals are written in each test, and the expected values follow from
them by the spec's rules, not from what the code produced.

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
