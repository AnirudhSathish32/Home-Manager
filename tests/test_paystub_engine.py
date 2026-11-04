"""The pay table engine, engine level (specs/pdf-table-engine-paystubs/test-contract.md), slice SL-01: P-checks, then rows and labels, columns,
headings, side-by-side blocks, section titles and wrapped labels, totals lines, table extent (net pay, a new heading, a stub start line,
continuation across pages), tables set aside from the pay table (deposit, leave), the summary box and unplaced lines. Roles, guesses and which
table is a pay table are SL-02's.

`pcheck_*` say each synthetic fixture has the shape the contract intends when the real reader reads it; the others compare the engine's tables
with the facts written out by hand in tests/paystub_engine_fixtures.py. A failed P-check is a fixture or reader problem, never a reason to change an
expected value. No store and no model: every test reads a saved reading of a synthetic PDF.
"""

import ast
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import socket
from statistics import median

import pytest

from home_manager.documents import pay_tables
from home_manager.documents.table_engine import PageView
import paystub_engine_fixtures as pf
import pdf_import_fixtures as fx


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """C-net: nothing connects to a non-loopback address."""
    def loopback(address):
        host = address[0] if isinstance(address, tuple) else address
        return not isinstance(host, str) or host in ("localhost", "::1") or host.startswith("127.") or host.startswith("/")

    def guard(original):
        def connect(self, address, *args):
            if not loopback(address):
                raise OSError(f"C-net: a connection to {address} was blocked")
            return original(self, address, *args)
        return connect

    real_create = socket.create_connection

    def create(address, *args, **kwargs):
        if not loopback(address):
            raise OSError(f"C-net: a connection to {address} was blocked")
        return real_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guard(socket.socket.connect_ex))
    monkeypatch.setattr(socket, "create_connection", create)


def reading_of(tmp_path, name):
    """The fixture, read by the real reader with no model: every page is native text."""
    pages = pf.FIXTURES[name]()
    result = fx.read_pdf(tmp_path, pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
    return result


def engine_of(tmp_path, name):
    return pay_tables.read(reading_of(tmp_path, name))


def printed(table):
    """A table as the contract writes it: its heading lines, each amount column's heading words, its rows and its totals, with the printed amount
    text in each column ("" where the row prints none)."""
    columns = [column.id for column in table.columns]
    texts = lambda amounts: [amounts[column].text if column in amounts else "" for column in columns]  # noqa: E731
    return (table.headings, [column.labels for column in table.columns], [(row.label, row.section, texts(row.amounts)) for row in table.rows],
            [(total.label, total.kind, texts(total.values)) for total in table.totals])


def without_sections(table):
    headings, labels, rows, totals = table
    return headings, labels, [(label, None, texts) for label, _, texts in rows], totals


def serialized(value):
    return json.dumps(asdict(value), sort_keys=True, default=str)  # Decimal is the only value json can't write.


# === P-checks: the shape of each fixture ====================================================================================

@pytest.mark.parametrize("name", list(pf.FIXTURES))
def test_pcheck_every_page_is_native_text_and_the_reader_states_only_the_expected_layout_issues(tmp_path, name):
    result = reading_of(tmp_path, name)
    for number, page in enumerate(result.pages, 1):
        assert fx.nonspace(page.layout.raw_text) >= fx.MINIMUM_FOOTER
        assert set(page.layout.issues) <= {"unresolved_columns"}, f"page {number}: {page.layout.issues}"


def test_pcheck_ps_nh_carries_unresolved_columns_because_it_prints_no_heading(tmp_path):
    result = reading_of(tmp_path, "PS-NH")
    assert set(result.pages[0].layout.issues) == {"unresolved_columns"}
    assert fx.native_transactions_tables(result, 1) == []


def column_texts(rows, first):
    return [[row[index] for row in rows] for index in range(first, first + 4)]


def assert_right_edges(result, number, edges, columns, rows=None):
    """Each amount column's saved word boxes agree on their right edge within 0.5 pt, and it is the edge the contract states. `rows` limits the
    check to the page's visual rows from the first to before the second (a text can be printed in two places on one page)."""
    layout = fx.layout(result, number)
    scale = fx.scale(layout)
    view = PageView(layout)
    for edge, texts in zip(edges, columns):
        wanted = {text for text in texts if text}
        # A text can repeat in another column of the same rows (a leave balance equals another row's accrual), so take the words near this edge.
        words = [word for word in layout.words if word.text in wanted and (rows is None or rows[0] <= view.row_of[word.id] < rows[1])
                 and abs(fx.word_box(layout, word)[2] / scale - edge) <= 3]
        assert len(words) == sum(1 for text in texts if text), (edge, wanted)
        rights = [fx.word_box(layout, word)[2] / scale for word in words]
        assert max(rights) - min(rights) <= 0.5
        assert abs(median(rights) - edge) <= 0.5


PS_COLUMNS = column_texts(pf.PS_ROWS, 1)


@pytest.mark.parametrize("name, number, edges, columns, rows", [
    ("PS", 1, pf.PS_EDGES, PS_COLUMNS, None),
    ("PS-2L", 1, pf.PS_EDGES, PS_COLUMNS, None),
    ("PS-WRAP", 1, pf.PS_EDGES, PS_COLUMNS, None),
    ("PS-SEC", 1, pf.PS_EDGES, PS_COLUMNS, None),
    ("PS-OTHER", 1, (430,), [[row[1] for row in pf.DEPOSIT_ROWS]], (18, 20)),
    ("PS-OTHER", 1, pf.PS_EDGES[:3], [[row[index] for row in pf.LEAVE_ROWS] for index in (1, 2, 3)], (21, 23)),
    ("PS-YTDH", 1, pf.YTDH_EDGES, [["80.00", "4.00"], ["31.25", "46.8750"], [row[3] for row in pf.PS_ROWS], ["1,040.00", "24.00"],
                                   [row[4] for row in pf.PS_ROWS]], None),
    ("PS-EMP", 1, pf.EMP_EDGES, [*PS_COLUMNS, ["80.63"]], None),
    ("SBS", 1, (200, 270, 460, 530), [[row[1] for row in pf.SBS_ROWS], [row[2] for row in pf.SBS_ROWS], [row[4] for row in pf.SBS_ROWS],
                                      [row[5] for row in pf.SBS_ROWS]], None),
    ("B1", 1, (430, 520), [["2,500.00", "2,500.00", "2,500.00"], ["5,000.00", "5,000.00", "5,000.00"]], None),
    ("B2", 1, (430, 520), [[row[1] for row in pf.B2_ROWS], [row[2] for row in pf.B2_ROWS]], None),
    ("SB", 1, pf.BOX_EDGES, [[pf.BOX_CURRENT[i], pf.BOX_YTD[i]] for i in range(4)], (6, 8)),
    ("PS-CONT", 2, (430, 520), [[row[3] for row in pf.PS_ROWS[6:]], [row[4] for row in pf.PS_ROWS[6:]]], None),
    ("PS-CONT-NH", 2, (436, 526), [[row[3] for row in pf.PS_ROWS[6:]], [row[4] for row in pf.PS_ROWS[6:]]], None),
])
def test_pcheck_right_aligned_amounts_share_a_right_edge_within_half_a_point(tmp_path, name, number, edges, columns, rows):
    assert_right_edges(reading_of(tmp_path, name), number, edges, columns, rows)


def test_pcheck_stk_prints_its_second_table_at_edges_400_and_500(tmp_path):
    result = reading_of(tmp_path, "STK")
    assert_right_edges(result, 1, (400, 500), [[row[3] for row in pf.PS_ROWS[3:]], [row[4] for row in pf.PS_ROWS[3:]]], (10, 99))


def test_pcheck_ps_wrap_prints_the_second_label_line_on_its_own_visual_line_without_an_amount(tmp_path):
    result = reading_of(tmp_path, "PS-WRAP")
    view = PageView(fx.layout(result, 1))
    texts = [" ".join(word.text for word in row) for row in view.rows]
    at = next(index for index, text in enumerate(texts) if text.startswith("Federal Income 295.63"))
    assert texts[at + 1] == "Tax Withholding" and texts[at + 2].startswith("Social Security")


def test_pcheck_sbs_prints_the_right_block_labels_at_x_300(tmp_path):
    result = reading_of(tmp_path, "SBS")
    layout = fx.layout(result, 1)
    scale = fx.scale(layout)
    for label in ("Federal", "Social", "Medicare", "Total", "401K"):
        lefts = [fx.word_box(layout, word)[0] / scale for word in layout.words if word.text == label]
        assert lefts and all(abs(left - 300) <= 1.5 for left in lefts)  # A glyph's left side bearing (F: 0.86 pt) sits inside the stated x.


def test_pcheck_ps_other_prints_its_other_tables_below_net_pay_in_the_pay_tables_columns(tmp_path):
    result = reading_of(tmp_path, "PS-OTHER")
    view = PageView(fx.layout(result, 1))
    texts = [" ".join(word.text for word in row) for row in view.rows]
    assert texts[texts.index("Net Pay 2,051.89 25,672.69") + 1:-1] == [
        "Direct Deposit", "Account Amount", "Checking 1234 1,551.89", "Savings 5678 500.00", "Leave Accrued Used Balance",
        "Vacation 40.00 8.00 32.00", "Sick 24.00 0.00 24.00"]


# === Rows, labels, columns and headings (FR-50 - FR-52) =====================================================================

def test_rows_ps_gives_one_pay_table_with_four_amount_columns_six_rows_and_four_totals(tmp_path):
    """SC-50 step 2 (the roles are SL-02's)."""
    reading = engine_of(tmp_path, "PS")
    [table] = reading.tables
    assert printed(table) == pf.PS_ENGINE
    assert table.id == "page-1-pay-1" and table.pages == [1] and table.block is None and table.partner is None
    assert reading.boxes == [] and reading.other_tables == [] and reading.unplaced == [] and reading.pages_without_tables == []


def test_rows_columns_are_right_aligned_in_order_and_zoned_without_gaps_or_overlap(tmp_path):
    [table] = engine_of(tmp_path, "PS").tables
    assert [column.align for column in table.columns] == ["right"] * 4
    assert [column.id for column in table.columns] == [f"page-1-pay-1-column-{n}" for n in (1, 2, 3, 4)]
    edges = [column.edge for column in table.columns]
    assert edges == sorted(edges)
    for left, right in zip(table.columns, table.columns[1:]):
        assert left.zone[1] == right.zone[0]
    assert table.label_column[1] == table.columns[0].zone[0]
    assert all(column.zone[0] < column.edge < column.zone[1] for column in table.columns)


def test_rows_amount_tokens_are_exact_decimals_and_a_rate_keeps_its_four_decimals(tmp_path):
    [table] = engine_of(tmp_path, "PS").tables
    overtime = next(row for row in table.rows if row.label == "Overtime")
    values = [overtime.amounts[column.id].value[0] for column in table.columns]
    assert values == [Decimal("4.00"), Decimal("46.8750"), Decimal("187.50"), Decimal("1125.00")]
    assert [token.kind for token in overtime.amounts.values()] == ["amount"] * 4


def test_rows_a_row_holds_its_own_words_and_lines(tmp_path):
    result = reading_of(tmp_path, "PS")
    [table] = pay_tables.read(result).tables
    layout = fx.layout(result, 1)
    words = {word.id: word.text for word in layout.words}
    regular = table.rows[0]
    assert [words[word_id] for word_id in regular.word_ids] == ["Regular", "80.00", "31.25", "2,500.00", "32,500.00"]
    assert len(regular.line_ids) == 1 and regular.line_ids[0] in {line.id for line in layout.lines}


def test_rows_two_line_headings_label_the_columns_top_to_bottom(tmp_path):
    """SC-51 step 1: the Current column's labels are This, Period."""
    [table] = engine_of(tmp_path, "PS-2L").tables
    assert printed(table) == pf.PS_2L_ENGINE
    assert table.columns[2].labels == ["This", "Period"] and table.columns[3].labels == ["Year to", "Date"]


def test_rows_no_heading_gives_the_same_rows_and_columns_with_no_labels(tmp_path):
    """SC-55 (FR-50): PS-NH has PS's rows and totals; Current is printed at 520 and YTD at 430, so the columns are in that order."""
    [table] = engine_of(tmp_path, "PS-NH").tables
    assert without_sections(printed(table)) == pf.PS_NH_ENGINE
    assert [row.label for row in table.rows] == [row[0] for row in pf.PS_ROWS_ENGINE]
    [headed] = engine_of(tmp_path, "PS").tables
    assert [row.label for row in table.rows] == [row.label for row in headed.rows]
    assert [total.label for total in table.totals] == [total.label for total in headed.totals]


def test_rows_ytd_hours_and_an_employer_column_are_columns_of_the_table(tmp_path):
    """SC-57 engine step (the roles are SL-02's): five amount columns, the Employer value only on row 8."""
    [table] = engine_of(tmp_path, "PS-YTDH").tables
    assert printed(table) == pf.PS_YTDH_ENGINE
    [table] = engine_of(tmp_path, "PS-EMP").tables
    assert printed(table) == pf.PS_EMP_ENGINE


def test_rows_labels_keep_their_digits_and_a_bare_integer_is_no_amount(tmp_path):
    """SC-58 step 1 (FR-51)."""
    [table] = engine_of(tmp_path, "PS-DIGITS").tables
    assert printed(table) == (["Description Hours Rate Current YTD"], [["Hours"], ["Rate"], ["Current"], ["YTD"]], pf.PS_DIGITS_ROWS, pf.PS_DIGITS_TOTALS)
    digits = {row.label: row for row in table.rows if row.label in ("PRE-TAX 401K", "SECTION 125")}
    assert set(digits) == {"PRE-TAX 401K", "SECTION 125"}
    assert {label: len(row.amounts) for label, row in digits.items()} == {"PRE-TAX 401K": 2, "SECTION 125": 2}
    section = digits["SECTION 125"]
    assert [token.value[0] for token in section.amounts.values()] == [Decimal("85.00"), Decimal("1105.00")]
    assert [token.text for token in section.amounts.values()] == ["85.00", "1,105.00"]


def test_rows_a_row_printed_in_one_column_keeps_the_other_cell_blank(tmp_path):
    """SC-69 / B1: a bonus printed only under YTD, a row only under Current."""
    [table] = engine_of(tmp_path, "PS-BONUS").tables
    bonus = next(row for row in table.rows if row.label == "Relocation Bonus")
    assert [column.labels for column in table.columns if column.id in bonus.amounts] == [["YTD"]]
    assert [token.text for token in bonus.amounts.values()] == ["5,000.00"]
    [table] = engine_of(tmp_path, "B1").tables
    assert printed(table)[2:] == (pf.B1_ENGINE[2], pf.B1_ENGINE[3])
    [table] = engine_of(tmp_path, "B2").tables
    assert printed(table)[2:] == (pf.B2_ENGINE[2], pf.B2_ENGINE[3])


def test_rows_b1_and_b2_are_one_table_each_because_their_columns_print_together_on_the_totals(tmp_path):
    for name in ("B1", "B2"):
        sub = tmp_path / name
        sub.mkdir()
        reading = engine_of(sub, name)
        assert len(reading.tables) == 1 and len(reading.tables[0].columns) == 2


def test_rows_swapped_heading_words_label_the_columns_they_are_printed_over(tmp_path):
    """SC-61 a: the headings are the engine's facts; whether the numbers overrule them is SL-02's."""
    [table] = engine_of(tmp_path, "PS-SWAPHEAD").tables
    assert [column.labels for column in table.columns] == [["Hours"], ["Rate"], ["YTD"], ["Current"]]
    assert [token.text for token in table.rows[0].amounts.values()] == ["80.00", "31.25", "2,500.00", "32,500.00"]


def test_rows_misprinted_totals_are_still_totals_with_their_printed_values(tmp_path):
    """SC-62: the engine copies what is printed; the checks are Record's."""
    [table] = engine_of(tmp_path, "PS-BADTOTAL").tables
    taxes = next(total for total in table.totals if total.kind == "taxes")
    assert [token.text for token in taxes.values.values()] == ["510.23", "6,271.06"]
    [table] = engine_of(tmp_path, "PS-BADNET").tables
    net = next(total for total in table.totals if total.kind == "net")
    assert [token.text for token in net.values.values()] == ["2,061.89", "25,672.69"]


def test_rows_each_page_of_a_file_of_stubs_has_its_own_table(tmp_path):
    """SC-72 (a) engine step: three stubs on three pages are three tables, each ending at its net pay."""
    reading = engine_of(tmp_path, "MINI-3")
    assert [table.id for table in reading.tables] == ["page-1-pay-1", "page-2-pay-1", "page-3-pay-1"]
    assert [printed(table) for table in reading.tables] == [pf.MINI_ENGINE(n) for n in (11, 12, 13)]


def test_rows_a_stub_with_no_year_to_date_column_has_one_amount_column(tmp_path):
    """MINI-C (SC-73): one column, found from its heading label."""
    [table] = engine_of(tmp_path, "MINI-C").tables
    assert printed(table) == pf.MINI_C_ENGINE


def test_rows_a_row_with_an_amount_in_no_column_keeps_its_placed_amounts_and_lists_the_stray_one(tmp_path):
    [table] = engine_of(tmp_path, "PS-STRAY").tables
    [row] = [row for row in table.rows if row.label == "401K"]
    assert [token.text for token in row.amounts.values()] == ["134.38", "1,681.25"]
    assert [token.text for token in row.stray] == ["9.99"]
    assert [token.text for other in table.rows if other is not row for token in other.stray] == []
    assert engine_of(tmp_path, "PS-STRAY").unplaced == []  # The line is a row; its stray amount is on the row.


@pytest.mark.parametrize("name", list(pf.FIXTURES))
def test_rows_reading_twice_gives_equal_results(tmp_path, name):
    result = reading_of(tmp_path, name)
    assert serialized(pay_tables.read(result)) == serialized(pay_tables.read(result))


def test_rows_the_module_imports_no_finance_store_or_model_code():
    tree = ast.parse((Path(pay_tables.__file__)).read_text(encoding="utf-8"))
    modules = [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module] \
        + [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert sorted(set(modules)) == ["dataclasses", "itertools", "re", "statistics", "table_engine"]


# === Side-by-side blocks (FR-53) ===========================================================================================

def test_blocks_sbs_gives_two_tables_on_the_same_lines_each_with_only_its_own_words(tmp_path):
    """SC-52 step 1."""
    result = reading_of(tmp_path, "SBS")
    reading = pay_tables.read(result)
    left, right = reading.tables
    assert printed(left) == pf.SBS_LEFT and printed(right) == pf.SBS_RIGHT
    assert (left.block, right.block) == ("left", "right") and (left.partner, right.partner) == (right.id, left.id)
    assert (left.id, right.id) == ("page-1-pay-1", "page-1-pay-2")
    layout = fx.layout(result, 1)
    scale = fx.scale(layout)
    middle = {word.id: (fx.word_box(layout, word)[0] + fx.word_box(layout, word)[2]) / 2 / scale for word in layout.words}
    for table, side in ((left, lambda x: x < 290), (right, lambda x: x >= 290)):
        for entry in (*table.rows, *table.totals):
            assert all(side(middle[word_id]) for word_id in entry.word_ids), entry.label
    view = PageView(layout)
    visual = lambda table: {view.row_of[word_id] for entry in (*table.rows, *table.totals) for word_id in entry.word_ids}  # noqa: E731
    assert visual(left) & visual(right)  # The two tables are read from the same printed (visual) lines.
    assert reading.unplaced == []


def test_blocks_a_single_table_page_has_no_block_or_partner(tmp_path):
    for name in ("PS", "STK", "PS-OTHER"):
        sub = tmp_path / name
        sub.mkdir()
        assert all(table.block is None and table.partner is None for table in engine_of(sub, name).tables)


# === Sections and wrapped labels (FR-54) ===================================================================================

def test_sections_stk_gives_two_tables_and_the_titles_are_no_rows(tmp_path):
    """SC-53 engine step: the second table has its own columns (400, 500), no heading, and the section titles Statutory and Voluntary."""
    reading = engine_of(tmp_path, "STK")
    first, second = reading.tables
    assert printed(first) == pf.STK_FIRST and printed(second) == pf.STK_SECOND
    assert (first.id, second.id) == ("page-1-pay-1", "page-1-pay-2")
    labels = [row.label for table in reading.tables for row in (*table.rows, *table.totals)]
    assert "Statutory" not in labels and "Voluntary" not in labels
    assert second.headings == [] and [column.labels for column in second.columns] == [[], []]
    assert reading.unplaced == []


def test_sections_titles_label_the_rows_below_them_and_do_not_end_the_table(tmp_path):
    """PS-SEC: Earnings, Taxes and Pre-tax over rows that continue one table."""
    reading = engine_of(tmp_path, "PS-SEC")
    [table] = reading.tables
    assert printed(table) == (pf.PS_ENGINE[0], pf.PS_ENGINE[1], pf.PS_SEC_ROWS, pf.PS_TOTALS_ENGINE)
    assert {row.label for row in table.rows}.isdisjoint({"Earnings", "Taxes", "Pre-tax"})


def test_sections_a_wrapped_label_joins_its_row_with_its_line_and_words(tmp_path):
    """SC-54 engine step: one row `Federal Income Tax Withholding`; its lines are the two printed lines in order."""
    result = reading_of(tmp_path, "PS-WRAP")
    [table] = pay_tables.read(result).tables
    assert printed(table) == (pf.PS_ENGINE[0], pf.PS_ENGINE[1], [(label, None, texts) for label, _, texts in pf.PS_WRAP_ROWS], pf.PS_TOTALS_ENGINE)
    layout = fx.layout(result, 1)
    words = {word.id: word.text for word in layout.words}
    federal = next(row for row in table.rows if row.label == "Federal Income Tax Withholding")
    assert [words[word_id] for word_id in federal.word_ids] == ["Federal", "Income", "295.63", "3,698.75", "Tax", "Withholding"]
    assert len(federal.line_ids) == 2
    texts = {line.id: line.text for line in layout.lines}
    assert [texts[line_id] for line_id in federal.line_ids][0].startswith("Federal Income") and texts[federal.line_ids[1]] == "Tax Withholding"
    assert sum(len(row.line_ids) for row in table.rows if row is not federal) == len(table.rows) - 1


# === Totals lines (FR-55) ==================================================================================================

def test_totals_gross_pay_is_a_total_in_both_amount_columns_and_no_row(tmp_path):
    """SC-51 step 2."""
    [table] = engine_of(tmp_path, "PS-2L").tables
    gross = next(total for total in table.totals if total.label == "Gross Pay")
    assert gross.kind == "gross" and [token.text for token in gross.values.values()] == ["2,687.50", "33,625.00"]
    assert len(gross.values) == 2 and [column.labels for column in table.columns if column.id in gross.values] == [["This", "Period"], ["Year to", "Date"]]
    assert "Gross Pay" not in [row.label for row in table.rows]


def test_totals_kinds_come_from_the_printed_words(tmp_path):
    [table] = engine_of(tmp_path, "PS").tables
    assert [(total.label, total.kind) for total in table.totals] == [("Gross Pay", "gross"), ("Total Taxes", "taxes"),
                                                                      ("Total Pre-Tax Deductions", "deductions"), ("Net Pay", "net")]
    assert [total.row for total in table.totals] == [3, 7, 9, 10] and [row.row for row in table.rows] == [1, 2, 4, 5, 6, 8]


@pytest.mark.parametrize("label, kind", [
    ("Gross Pay", "gross"), ("Total Earnings", "earnings"), ("Total Earnings (A)", "earnings"), ("Total Gross", "gross"), ("Total Gross Pay", "gross"),
    ("Total Taxes", "taxes"), ("Total Tax", "taxes"), ("Total Deductions", "deductions"), ("Total Pre-Tax Deductions", "deductions"),
    ("Total Employee Deductions (B)", "deductions"), ("Net Pay", "net"), ("Net Payment (A-B)", "net"), ("net pay", "net"),
    ("Total Employer Contributions", "employer"), ("Regular", None), ("Net Pay Adjustment", None), ("Taxes", None), ("Federal Income Tax", None)])
def test_totals_label_words(label, kind):
    assert pay_tables.total_kind(label) == kind


# === Tables set aside from the pay table (FR-56 engine step) ===============================================================

def test_other_tables_deposit_and_leave_are_tables_of_their_own_not_rows_of_the_pay_table(tmp_path):
    """SC-56 engine step: each starts at its own heading and holds only its own rows; the pay table's rows are PS's. Which are pay tables is SL-02's."""
    reading = engine_of(tmp_path, "PS-OTHER")
    pay, deposit, leave = reading.tables
    assert printed(pay) == pf.PS_ENGINE and printed(deposit) == pf.DEPOSIT_ENGINE and printed(leave) == pf.LEAVE_ENGINE
    assert deposit.lead == "Direct Deposit"
    assert [table.id for table in reading.tables] == ["page-1-pay-1", "page-1-pay-2", "page-1-pay-3"]
    assert reading.unplaced == [] and reading.pages_without_tables == []
    pay_labels = {row.label for row in pay.rows}
    assert pay_labels.isdisjoint({"Checking 1234", "Savings 5678", "Vacation", "Sick"})


def test_other_tables_a_table_ends_after_its_net_pay_and_at_a_heading_of_other_words(tmp_path):
    """The pay table of PS-OTHER ends at Net Pay even though the next rows share its columns."""
    pay = engine_of(tmp_path, "PS-OTHER").tables[0]
    assert pay.totals[-1].kind == "net" and len(pay.rows) == 6 and len(pay.totals) == 4


def test_other_tables_only_the_summary_box_and_tables_are_found_on_a_page_with_a_box(tmp_path):
    for name, box in (("SB", pf.SB_BOX), ("SB-SHUF", pf.SB_SHUF_BOX), ("SB-NOHEAD", pf.SB_NOHEAD_BOX)):
        sub = tmp_path / name
        sub.mkdir()
        reading = engine_of(sub, name)
        assert [printed(table) for table in reading.tables] == [pf.SB_TABLE[:2] + (pf.SB_TABLE[2], [])]
        [found] = reading.boxes
        assert (found.id, found.page) == ("page-1-box-1", 1)
        assert [column.labels for column in found.columns] == box[0]
        assert [(row.label, [row.amounts[column.id].text for column in found.columns]) for row in found.rows] == box[1]
        assert reading.unplaced == []


# === Rows of a box are no pay lines (FR-75, found here) ====================================================================

def test_rows_the_summary_box_rows_are_not_table_rows_and_a_table_of_hours_and_rates_is_not_a_box(tmp_path):
    [table] = engine_of(tmp_path, "SB").tables
    assert "Current" not in [row.label for row in table.rows] and "YTD" not in [row.label for row in table.rows]
    for name in ("PS", "PS-BONUS", "PS-EMP", "PS-YTDH", "SBS", "STK", "MINI-3"):
        sub = tmp_path / name
        sub.mkdir()
        assert engine_of(sub, name).boxes == []


def test_rows_box_columns_line_up_for_two_rows_whether_or_not_a_heading_is_printed(tmp_path):
    for name in ("SB", "SB-NOHEAD"):
        sub = tmp_path / name
        sub.mkdir()
        [box] = engine_of(sub, name).boxes
        assert len(box.columns) == 4 and [column.align for column in box.columns] == ["right"] * 4
        assert [column.edge for column in box.columns] == sorted(column.edge for column in box.columns)


# === Unplaced lines (FR-56) ================================================================================================

def test_unplaced_a_label_and_amount_in_no_column_is_listed_and_is_no_row(tmp_path):
    """SC-60 step 1: one unplaced line on page 1 with that text."""
    result = reading_of(tmp_path, "PS-SEC-MEMO")
    reading = pay_tables.read(result)
    [line] = reading.unplaced
    assert (line.page, line.text) == (1, "Bonus advance memo 75.00")
    assert line.line_id in {item.id for item in fx.layout(result, 1).lines}
    [table] = reading.tables
    assert printed(table) == (pf.PS_ENGINE[0], pf.PS_ENGINE[1], pf.PS_SEC_ROWS, pf.PS_TOTALS_ENGINE)
    assert "Bonus advance memo" not in [entry.label for entry in (*table.rows, *table.totals)]


@pytest.mark.parametrize("name", [name for name in pf.FIXTURES if name != "PS-SEC-MEMO"])
def test_unplaced_no_other_fixture_has_an_unplaced_line(tmp_path, name):
    assert engine_of(tmp_path, name).unplaced == []


def test_unplaced_a_page_with_no_table_is_reported_and_lists_nothing(tmp_path):
    """SC-59 engine step: page 2's prose line (an amount inside a sentence) is neither a row nor an unplaced line."""
    reading = engine_of(tmp_path, "PS-PROSE")
    assert reading.pages_without_tables == [2] and reading.unplaced == []
    assert len(reading.tables) == 1 and reading.tables[0].pages == [1]


def test_unplaced_pages_with_a_table_are_not_reported_as_without_one(tmp_path):
    for name in ("PS", "SBS", "MINI-3", "PS-CONT"):
        sub = tmp_path / name
        sub.mkdir()
        assert engine_of(sub, name).pages_without_tables == []


# === Table extent: continuation, stub starts (P3.6) ========================================================================

@pytest.mark.parametrize("name", ["PS-CONT", "PS-CONT-NH"])
def test_continuation_a_later_page_with_the_same_columns_continues_the_table_with_or_without_a_heading_and_at_an_offset(tmp_path, name):
    """PS-CONT repeats the heading on page 2; PS-CONT-NH prints no heading and draws page 2 six points to the right."""
    reading = engine_of(tmp_path, name)
    [table] = reading.tables
    assert table.pages == [1, 2]
    assert printed(table) == pf.PS_CONT_ENGINE
    assert [entry.page for entry in (*table.rows, *table.totals)].count(2) == 4
    assert sorted(entry.row for entry in (*table.rows, *table.totals)) == list(range(1, 11))
    assert reading.pages_without_tables == [] and reading.unplaced == []


def test_continuation_the_second_page_cells_are_in_the_first_pages_columns_at_their_own_positions(tmp_path):
    [table] = engine_of(tmp_path, "PS-CONT-NH").tables
    net = table.totals[-1]
    assert net.page == 2 and [token.text for token in net.values.values()] == ["2,051.89", "25,672.69"]
    assert list(net.values) == [table.columns[2].id, table.columns[3].id]
    first, last = table.rows[0].amounts[table.columns[2].id], net.values[table.columns[2].id]
    assert abs((last.box[2] - first.box[2]) - 12) <= 1  # The second page is drawn 6 pt right: 12 preview units at the reader's scale of 2.


def test_continuation_a_stub_start_line_ends_the_table_so_two_stubs_never_share_one(tmp_path):
    """The second stub's pay date line cuts the first stub's table, though the stubs print no net pay and share their columns and heading words."""
    reading = engine_of(tmp_path, "STUBCUT")
    assert [printed(table) for table in reading.tables] == pf.STUBCUT_TABLES
    assert [table.id for table in reading.tables] == ["page-1-pay-1", "page-1-pay-2"]


def test_continuation_without_the_stub_start_rule_the_two_stubs_would_share_a_table(tmp_path, monkeypatch):
    """Control for the test above: it is the pay date line that separates them."""
    monkeypatch.setattr(pay_tables, "starts_stub", lambda line: False)
    reading = engine_of(tmp_path, "STUBCUT")
    assert len(reading.tables) == 1 and len(reading.tables[0].rows) == 4
