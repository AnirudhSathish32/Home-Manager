"""Import account transactions from PDF documents (specs/account-import-pdf/test-contract.md).

This file holds the P-check tests: they read each synthetic fixture with the real reader and assert the shape the
contract says it has (methods per page, where the transactions heading is, which pages have no native transactions
table, the page issues), before any scenario step. A failure here is a fixture or reader problem, never a reason to
change an expected value (contract "Fixture preconditions"). Expected values come from tests/pdf_import_fixtures.py.
"""

import pytest

from home_manager.core.jobs import Work
from home_manager.documents.receipt_service import ReceiptService
import pdf_import_fixtures as fx
from test_pdf import capture, make_pdf, pdf_store  # noqa: F401


def read(tmp_path, pages, **options):
    result = fx.read_pdf(tmp_path, pages, **options)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)  # No model: every page is native.
    for number in range(1, len(pages) + 1):
        assert fx.nonspace(result.pages[number - 1].layout.raw_text) >= fx.MINIMUM_FOOTER
    return result


def assert_only_unresolved_columns(result, numbers):
    """The only layout issue a page may carry is `unresolved_columns` (FR-09 as amended)."""
    for number in numbers:
        assert set(fx.layout(result, number).issues) <= {"unresolved_columns"}, number
        assert set(fx.page_issue_codes(result, number)) <= {"pdf_layout_review"}, number


def assert_clean(result, numbers):
    for number in numbers:
        assert fx.layout(result, number).issues == [] and fx.page_issue_codes(result, number) == [], number


def assert_footers_words_only(result, numbers):
    """Each native page ends in a footer of at least 40 non-space characters, made of words only (contract fixture rule)."""
    for number in numbers:
        text = fx.footer_text(result, number)
        assert fx.nonspace(text) >= fx.MINIMUM_FOOTER and not any(char.isdigit() for char in text), (number, text)


def as_cells(values):
    """{column index: text} for the non-blank printed cells of a row."""
    return {index: value for index, value in enumerate(values) if value}


def assert_heading_is_one_visual_row(result, number, names):
    """The transactions heading is exactly one visual row, with one text per heading cell and a box for each."""
    rows = fx.heading_rows(result, number)
    assert len(rows) == 1
    heading = fx.texts(result, number, rows[0])
    assert [text for text, _, _ in heading] == list(names)
    assert all(left < right for _, left, right in heading)
    assert [left for _, left, _ in heading] == sorted(left for _, left, _ in heading)
    return heading


def assert_row_cells(result, number, heading, expected):
    """The page's candidate rows (plan "Rows": a date-like word in the Date span and an amount-like word in an amount span)
    are exactly `expected`, each cell inside the column span of its heading: a list of {column: text}. No word straddles
    two spans."""
    rows = fx.candidate_rows(result, number, heading)
    assert len(rows) == len(expected)
    for row, cells in zip(rows, expected):
        found, straddling = fx.printed_cells(result, number, heading, row)
        assert (found, straddling) == (cells, []), (number, found, straddling)


def k_expected(number):
    return [as_cells(row[2:7]) for row in fx.K_ROWS if row[1] == number]


# --- K ---------------------------------------------------------------------------------------------------------------

def test_pcheck_k_pages_read_natively_with_the_heading_as_one_visual_row_and_no_native_table(tmp_path):
    result = read(tmp_path, fx.k_pages())
    assert_only_unresolved_columns(result, (1, 2, 3))
    assert_footers_words_only(result, (1, 2, 3))
    # k1-k3 print no deposit, so the reader builds no native table on page 1; pages 2 and 3 never had headings.
    assert all(fx.native_grids(result, number) == [] for number in (1, 2, 3))
    assert all(fx.native_transactions_tables(result, number) == [] for number in (1, 2, 3))
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    assert [fx.row_texts(result, 1)[i] for i in range(4)] == [[line] for line in fx.K_TEXT]
    assert fx.heading_rows(result, 2) == [] and fx.heading_rows(result, 3) == []
    for number in (1, 2, 3):
        assert_row_cells(result, number, heading, k_expected(number))
    assert len(fx.data_rows(result, 2)) == 3 and len(fx.data_rows(result, 3)) == 3
    # The Balance column is a column of its own, and no balance equals an amount, so a balance used as one would show.
    amounts = {value for row in fx.K_ROWS for value in row[4:6] if value}
    assert amounts.isdisjoint(row[6] for row in fx.K_ROWS)
    assert sum(row[7] for row in fx.K_ROWS if row[7] < 0) == -fx.K_OUT_MINOR
    assert sum(row[7] for row in fx.K_ROWS if row[7] > 0) == fx.K_IN_MINOR
    assert fx.K_OPENING_MINOR - fx.K_OUT_MINOR + fx.K_IN_MINOR == fx.K_CLOSING_MINOR


def test_pcheck_k_text_prints_the_account_number_only_on_page_one(tmp_path):
    result = read(tmp_path, fx.k_pages())
    text = [" ".join(row) for row in fx.row_texts(result, 1)]
    assert "Account ending in 4821" in text and f"Account number {fx.K_ACCOUNT_NUMBER}" in text
    assert not any("4821" in " ".join(row) for number in (2, 3) for row in fx.row_texts(result, number))


def test_pcheck_k2_prints_both_last_fours_and_k0_prints_neither(tmp_path):
    (tmp_path / "k2").mkdir()
    k2 = read(tmp_path / "k2", fx.k2_pages())
    assert_only_unresolved_columns(k2, (1, 2, 3))
    printed = [" ".join(row) for row in fx.row_texts(k2, 1)]
    assert "Payment to card XXXX7700" in printed and "Account ending in 4821" in printed
    assert_heading_is_one_visual_row(k2, 1, fx.HEADING5)
    (tmp_path / "k0").mkdir()
    k0 = read(tmp_path / "k0", fx.k0_pages())
    assert_only_unresolved_columns(k0, (1, 2, 3))
    printed = " ".join(" ".join(row) for number in (1, 2, 3) for row in fx.row_texts(k0, number))
    assert "4821" not in printed and fx.K_ACCOUNT_NUMBER not in printed and "7700" not in printed
    heading = assert_heading_is_one_visual_row(k0, 1, fx.HEADING5)
    assert_row_cells(k0, 1, heading, k_expected(1))


def test_pcheck_keur_prints_a_euro_code_on_every_amount_and_a_currency_line(tmp_path):
    result = read(tmp_path, fx.keur_pages())
    assert_only_unresolved_columns(result, (1, 2, 3))
    assert "Currency: EUR" in [" ".join(row) for row in fx.row_texts(result, 1)]
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    expected = lambda number: [{index: (f"{value} EUR" if index >= 2 else value) for index, value in cells.items()} for cells in k_expected(number)]
    for number in (1, 2, 3):
        assert_row_cells(result, number, heading, expected(number))


def test_pcheck_k18a_prints_a_euro_code_only_on_k3_and_no_currency_line(tmp_path):
    result = read(tmp_path, fx.k18a_pages())
    assert_only_unresolved_columns(result, (1, 2, 3))
    assert not any("Currency" in " ".join(row) for row in fx.row_texts(result, 1))
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    page_one = k_expected(1)
    page_one[2] = {index: (f"{value} EUR" if index >= 2 else value) for index, value in page_one[2].items()}
    assert_row_cells(result, 1, heading, page_one)
    for number in (2, 3):
        assert_row_cells(result, number, heading, k_expected(number))


# --- R ---------------------------------------------------------------------------------------------------------------

def test_pcheck_r_page_one_has_a_native_table_and_page_two_has_none(tmp_path):
    result = read(tmp_path, fx.r_pages())
    assert_clean(result, (1,))
    assert_only_unresolved_columns(result, (2,))
    assert_footers_words_only(result, (1, 2))
    assert fx.native_transactions_tables(result, 1) == [[list(fx.HEADING3), *[[r[2], r[3], r[4]] for r in fx.R_ROWS if r[1] == 1]]]
    assert fx.native_grids(result, 2) == [] and fx.heading_rows(result, 2) == []
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING3)
    assert_row_cells(result, 1, heading, [as_cells(r[2:5]) for r in fx.R_ROWS if r[1] == 1])
    assert_row_cells(result, 2, heading, [as_cells(r[2:5]) for r in fx.R_ROWS if r[1] == 2])
    assert [" ".join(row) for row in fx.row_texts(result, 1)[:2]] == ["SYNTH CARD SERVICES", "Card number XXXX7700"]
    assert sum(r[5] for r in fx.R_ROWS if r[5] < 0) == fx.R_TOTALS_C[0] and sum(r[5] for r in fx.R_ROWS if r[5] > 0) == fx.R_TOTALS_C[1]
    assert sum(r[6] for r in fx.R_ROWS if r[6] < 0) == fx.R_TOTALS_A[0] and sum(r[6] for r in fx.R_ROWS if r[6] > 0) == fx.R_TOTALS_A[1]


# --- X and its variants ----------------------------------------------------------------------------------------------

def x_rows(*ids, only_withdrawals=False):
    return [as_cells(cells) for cells in fx.x_cells(*ids, only_withdrawals=only_withdrawals)]


def test_pcheck_x_native_page_one_and_three_and_headerless_page_two(tmp_path):
    result = read(tmp_path, fx.x_pages())
    assert_clean(result, (1, 3))
    assert_only_unresolved_columns(result, (2,))
    assert_footers_words_only(result, (1, 2, 3))
    assert fx.native_grids(result, 1) == [[list(row) for row in fx.X_SUMMARY],
                                         [list(fx.HEADING5), *[list(cells) for cells in fx.x_cells("A1", "A2")]]]
    assert fx.native_transactions_tables(result, 1) == [fx.native_grids(result, 1)[1]]
    assert fx.native_grids(result, 2) == [] and fx.heading_rows(result, 2) == []
    assert fx.native_grids(result, 3) == [[list(row) for row in fx.X_FEES]] and fx.native_transactions_tables(result, 3) == []
    assert fx.data_rows(result, 3) == []  # No line on page 3 has a date.
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    assert_row_cells(result, 1, heading, x_rows("A1", "A2"))
    assert_row_cells(result, 2, heading, x_rows("B1", "B2"))
    assert fx.X_TOTALS == (-1100, 2200)


def test_pcheck_x_7a_page_three_is_a_headerless_payment_schedule(tmp_path):
    result = read(tmp_path, fx.x_pages("7a"))
    assert_clean(result, (1,))
    assert_only_unresolved_columns(result, (2, 3))
    assert fx.native_grids(result, 3) == [] and fx.heading_rows(result, 3) == []
    assert fx.row_texts(result, 3)[0] == ["Payment schedule"]
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    assert_row_cells(result, 3, heading, [as_cells(cells) for cells in fx.X_SCHEDULE_ROWS])
    assert all(cells[2] == "25.00" for cells in fx.X_SCHEDULE_ROWS)  # Both are withdrawals: -50.00 in all.


def test_pcheck_x_7b_page_two_has_its_own_headings_and_page_three_is_headerless(tmp_path):
    result = read(tmp_path, fx.x_pages("7b"))
    assert_clean(result, (1, 2))
    assert_only_unresolved_columns(result, (3,))
    assert fx.native_transactions_tables(result, 2) == [[list(fx.HEADING5), *[list(cells) for cells in fx.x_cells("B1", "B2")]]]
    assert fx.native_grids(result, 3) == [] and fx.heading_rows(result, 3) == []
    heading = assert_heading_is_one_visual_row(result, 2, fx.HEADING5)
    assert_row_cells(result, 3, heading, [as_cells(cells) for cells in fx.X_7B_ROWS])


def test_pcheck_x_7c_a_page_one_that_prints_only_withdrawals_has_no_native_transactions_table(tmp_path):
    result = read(tmp_path, fx.x_pages("7c"))
    assert_only_unresolved_columns(result, (1, 2))
    assert fx.native_transactions_tables(result, 1) == []  # The reader builds no table for a column blank on every row.
    assert fx.native_grids(result, 1) == [[list(row) for row in fx.X_SUMMARY]]
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    assert_row_cells(result, 1, heading, x_rows("A1", "A2", only_withdrawals=True))
    assert_row_cells(result, 2, heading, x_rows("B1", "B2"))
    assert fx.X_7C_TOTALS == (-3100, 200)


def test_pcheck_x_7d_b2_amount_straddles_the_withdrawals_deposits_boundary(tmp_path):
    result = read(tmp_path, fx.x_pages("7d"))
    assert_only_unresolved_columns(result, (2,))
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    b1, b2 = fx.data_rows(result, 2)
    assert fx.printed_cells(result, 2, heading, b1) == (as_cells(fx.x_cells("B1")[0]), [])
    found, straddling = fx.printed_cells(result, 2, heading, b2)
    assert straddling == ["2.00"] and 1 not in straddling
    # Its horizontal centre is on the midpoint between the two headings (within a point), so it crosses by half its width.
    midpoint = (heading[2][2] + heading[3][1]) / 2
    [word] = [word for word in b2 if word.text == "2.00"]
    left, _, right, _ = fx.word_box(fx.layout(result, 2), word)
    assert abs((left + right) / 2 - midpoint) < 1.0 and right - left > 10


def test_pcheck_x_7e_b1_description_puts_an_amount_like_word_in_the_withdrawals_span(tmp_path):
    result = read(tmp_path, fx.x_pages("7e"))
    assert_only_unresolved_columns(result, (2,))
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    b1, b2 = fx.data_rows(result, 2)
    found, straddling = fx.printed_cells(result, 2, heading, b1)
    assert straddling == []
    assert found == {0: "09/03/2026", 1: "B1 REF", 2: "12345 1.00", 4: "1,009.00"}  # Two amount-like words in one span.
    assert fx.printed_cells(result, 2, heading, b2) == (as_cells(fx.x_cells("B2")[0]), [])


# --- F, Fn, M --------------------------------------------------------------------------------------------------------

def test_pcheck_f_page_two_is_flagged_by_a_real_image_trigger_and_page_one_is_clean(tmp_path):
    result = read(tmp_path, fx.f_pages())
    assert_clean(result, (1,))
    assert fx.native_grids(result, 1) == [[list(fx.HEADING3), *[[r[2], r[3], r[4]] for r in fx.F_ROWS if r[1] == 1]]]
    assert fx.native_grids(result, 2) == [] and fx.heading_rows(result, 2) == []
    # The reader raises possible_image_content and a pdf_layout_review page issue; nothing is injected into the reading.
    assert set(fx.layout(result, 2).issues) == {"possible_image_content", "unresolved_columns"}
    assert fx.page_issue_codes(result, 2) == ["pdf_layout_review"]
    [issue] = [issue for issue in result.issues if issue.message.startswith("Page 2 ")]
    assert issue.message.startswith("Page 2 PDF layout needs review: possible_image_content")
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING3)
    assert_row_cells(result, 2, heading, [as_cells(r[2:5]) for r in fx.F_ROWS if r[1] == 2])
    assert_footers_words_only(result, (1, 2))


def test_pcheck_fn_native_table_with_a_page_of_footer_has_only_unresolved_columns(tmp_path):
    result = read(tmp_path, fx.fn_pages())
    assert fx.layout(result, 1).issues == ["unresolved_columns"]
    assert fx.native_transactions_tables(result, 1) == [[list(fx.HEADING5), *[list(cells) for cells in fx.x_cells("A1", "A2")]]]
    assert fx.footer_text(result, 1) == "FIRST LOCAL BANK - Page 1 of 3"
    assert_heading_is_one_visual_row(result, 1, fx.HEADING5)


def test_pcheck_m_page_methods_are_embedded_then_vision_and_the_scan_is_read_once(pdf_store, local_model):
    source, store = pdf_store
    make_pdf(source / "m.pdf", fx.m_pages())
    doc = capture(source, store)
    local_model["output"] = {"full_text": "SCANNED PAGE TWO\n08/04/2026 SCANNED CAFE 7.00"}
    service = ReceiptService(store)
    run_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(run_id, Work("inference", "transcription", "PDF", sink=store.record_model_run))
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    assert [page["method"] for page in run["result"]["pages"]] == ["embedded_text", "vision_model"]
    assert len(local_model["requests"]) == 1  # Only the scanned page reached the model, while reading.
    assert "SCANNED CAFE" in " ".join(line["text"] for line in run["result"]["pages"][1]["lines"])
    assert run["result"]["pages"][1]["layout"] is None or not run["result"]["pages"][1]["layout"]["tables"]
    # Page 1 is K's page 1: its heading is one visual row of its saved words.
    from home_manager.documents.pdf_reader import read_result
    result = read_result(run["result"])
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    assert_row_cells(result, 1, heading, k_expected(1))


# --- SC-05 patterns, SC-24 dates, SC-16 and SC-25 geometry -----------------------------------------------------------

@pytest.mark.parametrize("line", fx.PATTERN_MATCHES + fx.PATTERN_MISSES)
def test_pcheck_sc05_pattern_line_is_one_visual_row_above_a_native_two_row_table(tmp_path, line):
    result = read(tmp_path, fx.pattern_page(line))
    assert_clean(result, (1,))
    assert fx.row_texts(result, 1)[0] == [line]  # Bullets and the ellipsis are one glyph each (WinAnsi).
    assert fx.native_transactions_tables(result, 1) == [[list(fx.HEADING3), ["08/03/2026", "ALPHA", "1.00"], ["08/04/2026", "BETA", "2.00"]]]


@pytest.mark.parametrize("name, rows", [("D-ny", fx.D_NY), ("D-bad", fx.D_BAD), ("D-full", fx.D_FULL), ("D-amb", fx.D_AMB), ("D-2y", fx.D_2Y)])
def test_pcheck_sc24_date_fixtures_are_native_three_column_tables(tmp_path, name, rows):
    result = read(tmp_path, fx.one_page(rows))
    assert_clean(result, (1,))
    assert_footers_words_only(result, (1,))
    assert fx.native_transactions_tables(result, 1) == [[list(fx.HEADING3), *[list(row) for row in rows]]], name


@pytest.mark.parametrize("count", [3, 4])
def test_pcheck_sc16_row_limit_fixtures_are_native_tables_with_three_and_four_rows(tmp_path, count):
    rows = [(f"08/0{index}/2026", f"ROW{index}", f"{index}.00") for index in range(1, count + 1)]
    result = read(tmp_path, fx.one_page(rows))
    assert_clean(result, (1,))
    assert fx.native_transactions_tables(result, 1) == [[list(fx.HEADING3), *[list(row) for row in rows]]]


def test_pcheck_sc16_long_cell_reads_as_one_native_cell_without_a_layout_review(tmp_path):
    result = read(tmp_path, fx.long_cell_pages())
    assert_clean(result, (1,))
    [grid] = fx.native_transactions_tables(result, 1)
    assert [row[1] for row in grid[1:]] == [fx.long_cell_text(), "SHORT"]
    assert [row[2] for row in grid[1:]] == ["1.00", "2.00"] and [row[0] for row in grid[1:]] == ["08/01/2026", "08/02/2026"]
    assert len(grid[1][1]) == fx.LONG_CELL_CHARACTERS
    [table] = fx.layout(result, 1).tables
    long_cell = next(cell for cell in table.cells if cell.row == 1 and cell.column == 1)
    assert len(long_cell.word_ids) == 2  # Two words of 1,000 characters (PDFWord is capped there).
    assert fx.layout(result, 1).issues == []
    assert_heading_is_one_visual_row(result, 1, fx.HEADING3)


def v_cells(*ids):
    """V's printed cells as {column: text}: a blank cell (v3's description) prints nothing."""
    return [as_cells(row[1:6]) for row in fx.V_ROWS if row[0] in ids]


def test_pcheck_sc25_v_native_table_is_the_heading_v1_and_v2_and_v3_to_v5_are_one_visual_row_each_below_it(tmp_path):
    """Plan "SL-01 details" Gate, V (P13). v3 prints no description, and the reader's table needs a label on every row,
    so its native table is the heading, v1 and v2 only. v3 to v5 stay loose lines, and the import's below-table rows
    read them from the saved words."""
    result = read(tmp_path, fx.v_pages())
    # The reader's native table is the heading, v1 and v2, and the page's only layout issue is unresolved_columns.
    assert fx.native_transactions_tables(result, 1) == [[list(fx.HEADING5), *[list(row[1:6]) for row in fx.V_ROWS[:2]]]]
    assert len(fx.native_grids(result, 1)) == 1
    assert fx.layout(result, 1).issues == ["unresolved_columns"]
    assert fx.page_issue_codes(result, 1) == ["pdf_layout_review"]
    # Its heading is one visual row, and equals the table's row 0 (the import takes the columns from there).
    heading = assert_heading_is_one_visual_row(result, 1, fx.HEADING5)
    assert [text for text, _, _ in heading] == fx.native_grids(result, 1)[0][0]
    # v3, v4 and v5 are each one visual row below the table's last row, then the footer: nothing else is down there.
    below = fx.below_table_rows(result, 1)
    assert len(below) == 4 and fx.footer_text(result, 1) == " ".join(word.text for word in below[-1])
    assert fx.candidate_rows(result, 1, heading, below) == below[:3] == fx.data_rows(result, 1)[2:]
    # Each maps to the heading's column spans with no straddling word. v3 has no description, v4's amount is 1.2.3.
    for row, cells in zip(below[:3], v_cells("v3", "v4", "v5")):
        assert fx.printed_cells(result, 1, heading, row) == (cells, []), cells
    assert v_cells("v3")[0] == {0: "08/03/2026", 2: "1.00", 4: "989.00"}
    assert v_cells("v4")[0][2] == "1.2.3" and v_cells("v5")[0][1] == fx.V_LONG_DESCRIPTION and len(fx.V_LONG_DESCRIPTION) == 480
    # v5's 480-character description is one text, inside the Description span.
    [description] = [(text, left, right) for text, left, right in fx.texts(result, 1, below[2]) if text == fx.V_LONG_DESCRIPTION]
    span = fx.spans(heading)[1]
    assert span[0] <= description[1] and description[2] <= span[1]
    # No glyph is outside the page, no text overlaps, and nothing is rotated.
    assert not set(fx.layout(result, 1).issues) & {"glyph_outside_page", "overlapping_text", "unsupported_text_rotation"}


# --- The helpers themselves ------------------------------------------------------------------------------------------

def test_pcheck_visual_rows_and_heading_texts_equal_every_native_table_in_the_fixtures(tmp_path):
    """The plan's re-implementation of the reader's row and text grouping (visual rows, heading texts) must agree with
    the reader's own tables on every native table of the fixtures. The one difference is the Fee summary heading, where
    the reader also splits at the column of the amounts below it, so `Fee summary` and `Count` sit within 1.5 font
    sizes: a non-transactions table, whose heading text is never used."""
    cases = {"x": fx.x_pages(), "r": fx.r_pages(), "f": fx.f_pages(), "fn": fx.fn_pages(), "long": fx.long_cell_pages(),
             "d": fx.one_page(fx.D_NY), "x7b": fx.x_pages("7b"), "v": fx.v_pages()}
    for name, pages in cases.items():
        directory = tmp_path / name
        directory.mkdir()
        result = read(directory, pages)
        for number in range(1, len(pages) + 1):
            rows = fx.row_texts(result, number)
            for grid in fx.native_grids(result, number):
                for cells in grid:
                    printed = [cell for cell in cells if cell]
                    if printed == ["Fee summary", "Count", "Total"]:
                        printed = ["Fee summary Count", "Total"]
                    assert printed in rows, (name, number, printed)
