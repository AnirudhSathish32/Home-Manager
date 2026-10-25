"""Import account transactions from PDF documents (specs/account-import-pdf/test-contract.md).

The P-check tests read each synthetic fixture with the real reader and assert the shape the contract says it has (methods
per page, where the transactions heading is, which pages have no native transactions table, the page issues), before any
scenario step. A failure there is a fixture or reader problem, never a reason to change an expected value (contract
"Fixture preconditions"). The analyzer tests (`test_analyzer_*`) run `finance/pdf_import.analyze` on real readings of the same
fixtures: they are the analyzer-level checkpoints of SC-05, SC-07, SC-08, SC-09, SC-16, SC-18, SC-24 and SC-25, and the
import steps of those scenarios are tested with the ledger. Expected values come from tests/pdf_import_fixtures.py.
"""

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import socket

from fastapi.testclient import TestClient
import pytest

from home_manager.app.api import create_app
from home_manager.core.jobs import Work
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance import pdf_import
from home_manager.finance.ledger import COUNTABLE
from home_manager.finance.tools import FinanceTools, PeriodInput
from home_manager.library.scanner import ScanLimits
from home_manager.models.vision import VisionConfig
import pdf_import_fixtures as fx
from test_pdf import capture, make_pdf, pdf_store  # noqa: F401


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """C-net: nothing connects to a non-loopback address (the TestClient transport is in-process and opens no socket)."""
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


# --- The analyzer on real readings (SL-02) ---------------------------------------------------------------------------------

def analyze(tmp_path, pages, **choices):
    """Read the fixture with the real reader and analyze it. USD unless the test says otherwise."""
    return pdf_import.analyze(read(tmp_path, pages), **{"currency": "USD", **choices})


def totals(analysis):
    """Money out and in of the ticked, parsed rows, in minor units."""
    minors = [row.amount_minor for row in analysis.rows if row.ticked and row.amount_minor is not None]
    return sum(minor for minor in minors if minor < 0), sum(minor for minor in minors if minor > 0)


def printed(row):
    return row.description, row.date, row.amount


def test_analyzer_j1_k_rows_are_rebuilt_on_page_one_and_linked_across_pages(tmp_path):
    """J1 step 3 at analyzer level: K's page 1 is a rebuilt table (no native table), pages 2 and 3 continue it."""
    analysis = analyze(tmp_path, fx.k_pages())
    assert [(row.page, row.date, row.description, row.amount, row.posted_date, row.amount_minor) for row in analysis.rows] == \
        [(r[1], r[2], r[3], r[4] or r[5], posted, r[7]) for r, posted in zip(fx.K_ROWS, fx.K_POSTED)]
    assert [(table.kind, table.linked_to, table.row_count, table.selected, table.selectable) for table in analysis.tables] == [
        ("rebuilt", None, 3, True, True), ("continuation", "page-1-import-table-1", 3, True, False), ("continuation", "page-1-import-table-1", 3, True, False)]
    assert [table.id for table in analysis.tables] == ["page-1-import-table-1", "page-2-import-continuation", "page-3-import-continuation"]
    assert [row.labels for row in analysis.rows] == [[]] * 3 + [["continued from page 1"]] * 6  # k4, page 2's first row, included.
    assert all(row.ticked and row.rejected is None and row.currency == "USD" for row in analysis.rows)
    assert analysis.issues == [] and analysis.required == [] and analysis.blocked is None  # unresolved_columns alone is not listed.
    assert analysis.counts == dict(seen=9, parsed=9, rejected=0, left_out=0, pages_without_rows=0)
    assert analysis.mapping == {"date": "Date", "description": "Description", "debit": "Withdrawals", "credit": "Deposits"}  # No Balance.
    assert analysis.last_fours == {"4821": 1} and analysis.document_currency is None
    assert totals(analysis) == (-fx.K_OUT_MINOR, fx.K_IN_MINOR)
    # Rebuilt and continuation rows cite words and lines, never native cells; row numbers count from 0 on each page (SC-22).
    assert all(row.word_ids and row.line_ids and not row.cell_ids for row in analysis.rows)
    assert [row.key for row in analysis.rows[3:6]] == ["page-2-import-continuation:0", "page-2-import-continuation:1", "page-2-import-continuation:2"]
    assert [row.continued_from for row in analysis.rows] == [None] * 3 + [1] * 6
    assert analysis.tables[0].rows == [row.key for row in analysis.rows[:3]]


def test_analyzer_is_deterministic_and_selection_follows_the_transactions_table(tmp_path):
    result = read(tmp_path, fx.k_pages())
    assert pdf_import.analyze(result, currency="USD") == pdf_import.analyze(result, currency="USD", tables=["page-1-import-table-1"])
    none = pdf_import.analyze(result, currency="USD", tables=[])
    assert none.rows == [] and none.counts["seen"] == 0 and not any(table.selected for table in none.tables)
    assert [table.row_count for table in none.tables] == [3, 3, 3]  # The preview still shows what an unticked table holds.
    with pytest.raises(pdf_import.PDFImportError, match="not in this reading"):
        pdf_import.analyze(result, currency="USD", tables=["page-9-import-table-1"])


def test_analyzer_k2_prints_two_last_fours_and_k0_none(tmp_path):
    (tmp_path / "k2").mkdir()
    assert analyze(tmp_path / "k2", fx.k2_pages()).last_fours == {"4821": 1, "7700": 1}
    (tmp_path / "k0").mkdir()
    k0 = analyze(tmp_path / "k0", fx.k0_pages())
    assert k0.last_fours == {} and len(k0.rows) == 9  # The account number line alone gives no last four.


@pytest.mark.parametrize("line", fx.PATTERN_MATCHES + fx.PATTERN_MISSES)
def test_analyzer_sc05_last_four_patterns(tmp_path, line):
    analysis = analyze(tmp_path, fx.pattern_page(line))
    assert analysis.last_fours == ({"4821": 1} if line in fx.PATTERN_MATCHES else {})


def test_analyzer_sc02_r_year_is_required_and_the_card_sign_follows_the_account_type(tmp_path):
    result = read(tmp_path, fx.r_pages())
    before = pdf_import.analyze(result, currency="USD", account_type="credit_card")
    assert before.required == ["year"] and before.sign_default == "positive_is_outflow" == before.sign
    assert [row.date for row in before.rows] == [r[2] for r in fx.R_ROWS] and all(row.posted_date is None for row in before.rows)
    assert [row.amount_minor for row in before.rows] == [r[5] for r in fx.R_ROWS] and totals(before) == fx.R_TOTALS_C
    assert before.last_fours == {"7700": 1}
    after = pdf_import.analyze(result, currency="USD", account_type="credit_card", year=2025)
    assert after.required == [] and [row.posted_date for row in after.rows] == fx.R_POSTED_2025
    assert not any(row.posted_date.startswith("2026") for row in after.rows)
    # Page 1's table is native (its rows keep the reader's row numbers); page 2 continues it.
    assert [(table.kind, table.linked_to) for table in after.tables] == [("transactions", None), ("continuation", after.tables[0].id)]
    assert [row.key for row in after.rows] == [f"{after.tables[0].id}:{n}" for n in (1, 2, 3)] + ["page-2-import-continuation:0", "page-2-import-continuation:1"]
    assert all(row.cell_ids and row.line_ids and not row.word_ids for row in after.rows[:3])
    assert all(row.word_ids and not row.cell_ids for row in after.rows[3:])


@pytest.mark.parametrize("account_type, default, column, expected", [
    ("credit_card", "positive_is_outflow", 5, fx.R_TOTALS_C), ("checking", "negative_is_outflow", 6, fx.R_TOTALS_A),
    ("savings", "negative_is_outflow", 6, fx.R_TOTALS_A), ("loan", None, None, None), ("other", None, None, None), ("brokerage", None, None, None), (None, None, None, None)])
def test_analyzer_sc03_the_sign_default_follows_the_account_type(tmp_path, account_type, default, column, expected):
    result = read(tmp_path, fx.r_pages())
    analysis = pdf_import.analyze(result, currency="USD", account_type=account_type, year=2025)
    assert analysis.sign_default == default and analysis.sign == default
    if default is None:
        assert analysis.required == ["sign"] and all(row.amount_minor is None and row.rejected is None for row in analysis.rows)
        chosen = pdf_import.analyze(result, currency="USD", account_type=account_type, year=2025, sign="positive_is_outflow")
        assert analysis.rows[0].amount_minor is None and chosen.required == [] and [row.amount_minor for row in chosen.rows] == [r[5] for r in fx.R_ROWS]
    else:
        assert analysis.required == [] and [row.amount_minor for row in analysis.rows] == [r[column] for r in fx.R_ROWS] and totals(analysis) == expected
    # A choice beats the default: checking with positive_is_outflow gives the card column, and the reverse.
    flipped = pdf_import.analyze(result, currency="USD", account_type="checking", year=2025, sign="positive_is_outflow")
    assert [row.amount_minor for row in flipped.rows] == [r[5] for r in fx.R_ROWS] and totals(flipped) == fx.R_TOTALS_C


def test_analyzer_sc03_debit_credit_tables_need_no_sign(tmp_path):
    assert analyze(tmp_path, fx.k_pages()).required == []  # K has Withdrawals and Deposits columns and no account type.


# --- SC-07: cross-page linking, rebuilt rows and pages without a transactions table -----------------------------------------

X_CHOICES = dict(date_format="MM/DD/YYYY", account_type="checking")  # Fixture rule: X's dates are ambiguous (no value above 12).


def test_analyzer_sc07_x_summary_and_fee_summary_are_listed_and_page_three_is_reported(tmp_path):
    analysis = analyze(tmp_path, fx.x_pages(), **X_CHOICES)
    assert [(table.page, table.kind, table.selected, table.selectable) for table in analysis.tables] == [
        (1, "other", False, False), (1, "transactions", True, True), (2, "continuation", True, False), (3, "other", False, False)]
    assert [table.headings for table in analysis.tables if table.kind == "other"] == [["Summary", "Amount"], ["Fee summary", "Count", "Total"]]
    assert analysis.tables[2].linked_to == analysis.tables[1].id
    assert [(row.page, row.description, row.amount_minor) for row in analysis.rows] == [(r[1], r[3], r[7]) for r in fx.X_ROWS]
    assert [row.labels for row in analysis.rows] == [[], [], ["continued from page 1"], ["continued from page 1"]]  # B1, page 2's first line, too.
    assert [(issue.page, issue.message) for issue in analysis.issues] == [(3, "Page 3: no transactions table found")]
    assert totals(analysis) == fx.X_TOTALS
    # FR-10: every page is a row source or in the issue list, and the identity holds (footer lines are not rows).
    assert analysis.counts == dict(seen=4, parsed=4, rejected=0, left_out=0, pages_without_rows=1)
    assert {row.page for row in analysis.rows} | {issue.page for issue in analysis.issues} == {1, 2, 3}
    assert analysis.counts["parsed"] + analysis.counts["rejected"] == analysis.counts["seen"]
    # Without the date order chosen, the day/month order is required (nothing is above 12).
    assert pdf_import.analyze(read(tmp_path, fx.x_pages()), currency="USD", account_type="checking").required == ["date_format"]


def test_analyzer_sc07_7a_a_payment_schedule_page_is_counted(tmp_path):
    analysis = analyze(tmp_path, fx.x_pages("7a"), **X_CHOICES)
    schedule = analysis.rows[4:]
    assert [(row.page, row.date, row.description, row.amount_minor, row.labels) for row in schedule] == [
        (3, "10/01/2026", "Scheduled payment", -2500, ["continued from page 1"]), (3, "11/01/2026", "Scheduled payment", -2500, ["continued from page 1"])]
    assert [row.posted_date for row in schedule] == ["2026-10-01", "2026-11-01"] and all(row.ticked for row in schedule)
    assert totals(analysis) == (fx.X_TOTALS[0] - 5000, fx.X_TOTALS[1]) and analysis.issues == []  # The title line has no date: not a row.


def test_analyzer_sc07_7b_a_new_transactions_table_ends_the_chain(tmp_path):
    analysis = analyze(tmp_path, fx.x_pages("7b"), **X_CHOICES)
    assert [(table.page, table.kind, table.linked_to) for table in analysis.tables if table.kind != "other"] == [
        (1, "transactions", None), (2, "transactions", None), (3, "continuation", analysis.tables[-2].id)]
    assert [row.labels for row in analysis.rows] == [[]] * 4 + [["continued from page 2"]] * 2
    assert [(row.description, row.amount_minor) for row in analysis.rows[4:]] == [("C1", -300), ("C2", 400)]


def test_analyzer_sc07_7c_a_column_blank_on_every_row_is_rebuilt_from_the_words(tmp_path):
    analysis = analyze(tmp_path, fx.x_pages("7c"), **X_CHOICES)
    assert [(table.page, table.kind, table.selected) for table in analysis.tables] == [(1, "other", False), (1, "rebuilt", True), (2, "continuation", True), (3, "other", False)]
    assert [(row.description, row.amount_minor) for row in analysis.rows] == [("A1", -1000), ("A2", -2000), ("B1", -100), ("B2", 200)]
    assert totals(analysis) == fx.X_7C_TOTALS and [issue.message for issue in analysis.issues] == ["Page 3: no transactions table found"]


def test_analyzer_sc07_7d_an_amount_straddling_two_columns_rejects_its_row(tmp_path):
    analysis = analyze(tmp_path, fx.x_pages("7d"), **X_CHOICES)
    b1, b2 = analysis.rows[2:]
    assert b1.rejected is None and b1.amount_minor == -100
    assert b2.rejected == "The amount doesn't fit a column." and b2.amount_minor is None and not b2.ticked and b2.page == 2
    assert (b2.date, b2.description, b2.amount) == ("09/04/2026", "B2", "2.00")  # Still shown as printed.
    assert analysis.counts == dict(seen=4, parsed=3, rejected=1, left_out=0, pages_without_rows=1)
    assert ("rejected_row", 2, 1) in [(issue.code, issue.page, issue.row) for issue in analysis.issues]


def test_analyzer_sc07_7e_two_amounts_in_one_amount_column_reject_the_row(tmp_path):
    analysis = analyze(tmp_path, fx.x_pages("7e"), **X_CHOICES)
    b1, b2 = analysis.rows[2:]
    assert b1.rejected == "More than one amount sits in the Withdrawals column." and b1.page == 2 and b1.amount_minor is None
    assert b1.description == "B1 REF" and b1.amount == "12345 1.00"  # Nothing is joined or guessed.
    assert b2.rejected is None and b2.amount_minor == 200 and analysis.counts["rejected"] == 1


def test_analyzer_sc07_a_summary_below_a_transactions_table_is_listed_and_nothing_is_absorbed(tmp_path):
    """Plan "Native tables" (pass-6 MAJOR-2): a Summary printed below a native transactions table shares no baseline with any
    below-table candidate row, so it stays listed as `not a transactions table`."""
    result = read(tmp_path, fx.summary_below_pages())
    assert len(fx.native_transactions_tables(result, 1)) == 1 and len(fx.native_grids(result, 1)) == 2  # P-check: the reader built both.
    analysis = pdf_import.analyze(result, currency="USD", **X_CHOICES)
    assert [(table.kind, table.headings) for table in analysis.tables] == [
        ("transactions", ["Date", "Description", "Withdrawals", "Deposits", "Balance"]), ("other", ["Summary", "Amount"])]
    assert [row.description for row in analysis.rows] == ["A1", "A2"] and analysis.issues == []


def test_analyzer_sc07_a_second_heading_below_a_native_table_is_reported_and_its_rows_are_not_read(tmp_path):
    """Plan "Rows below a native table": the visual rows after a second transactions heading are reported, not guessed. The
    blank-description row before the heading is a below-table row (row 3, rejected)."""
    result = read(tmp_path, fx.second_heading_pages())
    assert len(fx.native_transactions_tables(result, 1)) == 1 and len(fx.heading_rows(result, 1)) == 2  # P-check: the second heading is a visual row.
    analysis = pdf_import.analyze(result, currency="USD", **X_CHOICES)
    assert [(row.row, row.description, row.rejected) for row in analysis.rows] == [(1, "A1", None), (2, "A2", None), (3, "", "The description is blank.")]
    assert "C2" not in [row.description for row in analysis.rows] and "C3" not in [row.description for row in analysis.rows]
    assert [issue.message for issue in analysis.issues if issue.code == "second_heading"] == ["Page 1: rows after a second transactions heading on this page were not read."]


# --- SC-08: flagged pages ----------------------------------------------------------------------------------------------------

def test_analyzer_sc08_rows_from_a_flagged_page_start_unticked(tmp_path):
    analysis = analyze(tmp_path, fx.f_pages(), **X_CHOICES)
    assert [row.ticked for row in analysis.rows] == [True, True] + [False] * 4
    flagged = analysis.rows[2:]
    assert all(len(row.labels) == 2 and row.labels[0] == "continued from page 1" and row.labels[1].startswith("Page 2 PDF layout needs review: possible_image_content") for row in flagged)
    assert [row.posted_date for row in flagged] == ["2026-07-03", "2026-07-04", "2026-07-05", "2026-07-06"]
    assert [row.amount_minor for row in flagged] == [100, 200, 300, 400]  # Parsed, with the checking default.
    assert totals(analysis) == (0, 3000)  # Only the ticked rows count: F1 and F2.
    assert analysis.counts == dict(seen=6, parsed=6, rejected=0, left_out=4, pages_without_rows=0)
    [issue] = analysis.issues
    assert (issue.page, issue.code) == (2, "pdf_layout_review") and issue.message == flagged[0].labels[1]


def test_analyzer_sc08_8a_a_page_footer_alone_does_not_flag_a_native_page(tmp_path):
    analysis = analyze(tmp_path, fx.fn_pages(), **X_CHOICES)
    assert [row.ticked for row in analysis.rows] == [True, True] and all(row.labels == [] for row in analysis.rows) and analysis.issues == []
    assert analysis.counts["left_out"] == 0


# --- SC-09: a scanned page --------------------------------------------------------------------------------------------------

def read_with_scan(pdf_store, local_model, name, pages):
    source, store = pdf_store
    make_pdf(source / name, pages)
    doc = capture(source, store)
    local_model["output"] = {"full_text": "SCANNED PAGE TWO\n08/04/2026 SCANNED CAFE 7.00"}
    service = ReceiptService(store)
    run_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(run_id, Work("inference", "transcription", "PDF", sink=store.record_model_run))
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    from home_manager.documents.pdf_reader import read_result
    return read_result(run["result"])


def test_analyzer_sc09_a_scanned_page_is_reported_and_contributes_no_row(pdf_store, local_model):
    result = read_with_scan(pdf_store, local_model, "m.pdf", fx.m_pages())
    requests = len(local_model["requests"])
    analysis = pdf_import.analyze(result, currency="USD", **X_CHOICES)
    assert [row.description for row in analysis.rows] == ["COFFEE SHOP", "COFFEE SHOP", "GROCERY MART"] and {row.page for row in analysis.rows} == {1}
    assert [(issue.page, issue.code, issue.message) for issue in analysis.issues] == [
        (2, "scanned_page", "Page 2 is a scanned page; no rows imported. Use Record for scanned statements.")]
    assert "SCANNED CAFE" not in repr(analysis.rows) and analysis.counts["pages_without_rows"] == 1
    assert len(local_model["requests"]) == requests  # Analyzing makes no model call.


def test_analyzer_sc09_9a_an_all_scanned_pdf_has_no_rows_and_the_message(pdf_store, local_model):
    result = read_with_scan(pdf_store, local_model, "scan.pdf", [None])
    analysis = pdf_import.analyze(result, currency="USD")
    assert analysis.rows == [] and analysis.tables == [] and analysis.counts == dict(seen=0, parsed=0, rejected=0, left_out=0, pages_without_rows=1)
    assert [issue.message for issue in analysis.issues] == ["Page 1 is a scanned page; no rows imported. Use Record for scanned statements."]


def test_analyzer_a_reading_saved_before_layout_existed_is_blocked(tmp_path):
    result = fx.synthetic_result([[("08/15/2026", "ROW", "1.00")]])
    result.pages[0].layout = None
    analysis = pdf_import.analyze(result, currency="USD")
    assert analysis.rows == [] and analysis.blocked == pdf_import.NO_LAYOUT
    assert analysis.blocked == "This PDF was read before transaction import existed. Read this document again to import its transactions."


# --- SC-18: currency ---------------------------------------------------------------------------------------------------------

def test_analyzer_sc18_a_document_in_another_currency_blocks_the_import(tmp_path):
    result = read(tmp_path, fx.keur_pages())
    analysis = pdf_import.analyze(result, currency="USD")
    assert analysis.document_currency == "EUR" and "EUR" in analysis.blocked and "USD" in analysis.blocked
    assert analysis.issues[0].code == "document_currency_mismatch"
    assert analysis.counts["rejected"] == 9 and all("is not in USD" in row.rejected for row in analysis.rows)  # Each row says so, too.
    euros = pdf_import.analyze(result, currency="EUR")
    assert euros.blocked is None and euros.document_currency == "EUR" and [row.amount_minor for row in euros.rows] == [r[7] for r in fx.K_ROWS]


def test_analyzer_sc18_18a_one_row_printing_another_currency_is_rejected_alone(tmp_path):
    analysis = analyze(tmp_path, fx.k18a_pages())
    assert analysis.document_currency is None and analysis.blocked is None
    [rejected] = [row for row in analysis.rows if row.rejected]
    assert rejected.description == "GROCERY MART" and rejected.amount == "45.10 EUR" and rejected.rejected == 'The amount "45.10 EUR" is not in USD.'
    assert analysis.counts == dict(seen=9, parsed=8, rejected=1, left_out=0, pages_without_rows=0)


# --- SC-24: exact dates ------------------------------------------------------------------------------------------------------

def test_analyzer_sc24_d_ny_new_year_rows_advance_the_year(tmp_path):
    result = read(tmp_path, fx.one_page(fx.D_NY))
    blocked = pdf_import.analyze(result, currency="USD", account_type="checking")
    assert blocked.required == ["year"] and all(row.posted_date is None for row in blocked.rows)
    chosen = pdf_import.analyze(result, currency="USD", account_type="checking", year=2025)
    assert chosen.required == [] and [row.posted_date for row in chosen.rows] == ["2025-08-03", "2025-12-30", "2026-01-02"]


def test_analyzer_sc24_d_bad_an_impossible_date_rejects_its_row_naming_it(tmp_path):
    analysis = analyze(tmp_path, fx.one_page(fx.D_BAD), account_type="checking")
    p, q = analysis.rows
    assert (p.posted_date, p.rejected) == ("2026-02-27", None)
    assert q.posted_date is None and q.rejected == 'The date "02/30/2026" is not a real date.'


def test_analyzer_sc24_d_full_four_digit_years_need_no_year(tmp_path):
    result = read(tmp_path, fx.one_page(fx.D_FULL))
    assert pdf_import.analyze(result, currency="USD", account_type="checking").required == ["date_format"]  # P10: no value above 12.
    chosen = pdf_import.analyze(result, currency="USD", account_type="checking", date_format="MM/DD/YYYY")
    assert chosen.required == [] and [row.posted_date for row in chosen.rows] == ["2026-08-03", "2026-08-04"]


def test_analyzer_sc24_d_amb_the_day_month_order_is_a_required_choice(tmp_path):
    result = read(tmp_path, fx.one_page(fx.D_AMB))
    assert pdf_import.analyze(result, currency="USD", account_type="checking").required == ["date_format"]
    day_first = pdf_import.analyze(result, currency="USD", account_type="checking", date_format="DD/MM/YYYY")
    month_first = pdf_import.analyze(result, currency="USD", account_type="checking", date_format="MM/DD/YYYY")
    assert [row.posted_date for row in day_first.rows] == ["2026-08-03", "2026-09-04"]
    assert [row.posted_date for row in month_first.rows] == ["2026-03-08", "2026-04-09"]


def test_analyzer_sc24_d_2y_two_digit_years_are_blocked_until_a_year_is_chosen(tmp_path):
    result = read(tmp_path, fx.one_page(fx.D_2Y))
    assert pdf_import.analyze(result, currency="USD", account_type="checking").required == ["year", "date_format"]
    chosen = pdf_import.analyze(result, currency="USD", account_type="checking", date_format="MM/DD/YYYY", year=2026)
    assert chosen.required == [] and [row.posted_date for row in chosen.rows] == ["2026-08-03", "2026-08-04"]
    # Plan P1: a printed YY that disagrees with the computed year rejects the row (G4, not asserted by the contract).
    wrong = pdf_import.analyze(result, currency="USD", account_type="checking", date_format="MM/DD/YYYY", year=2025)
    assert all(row.rejected and "26" in row.rejected for row in wrong.rows)


# --- SC-25: rejected rows are listed with page, row and reason ----------------------------------------------------------------

def test_analyzer_sc25_v_three_rows_are_rejected_with_page_row_and_reason(tmp_path):
    analysis = analyze(tmp_path, fx.v_pages(), date_format="MM/DD/YYYY", account_type="checking")
    # v1 and v2 are the native table's rows 1 and 2; v3 to v5 are below-table rows numbered 3 to 5 (plan P13).
    assert [(row.key, row.row, row.page) for row in analysis.rows] == [(f"page-1-layout-table-1:{n}", n, 1) for n in range(1, 6)]
    assert [len(analysis.tables)] == [1] and analysis.tables[0].kind == "transactions" and analysis.tables[0].row_count == 5
    v1, v2, v3, v4, v5 = analysis.rows
    assert (v1.amount_minor, v1.rejected) == (-1000, None)
    assert v2.rejected == "Both a debit and a credit are printed." and v2.amount_minor is None
    assert v3.rejected == "The description is blank." and v3.description == "" and v3.date == "08/03/2026"
    assert v4.rejected == 'The amount "1.2.3" can\'t be read.' and v4.amount == "1.2.3"
    assert (v5.amount_minor, v5.rejected) == (-200, None) and v5.description == fx.V_LONG_DESCRIPTION  # Stored exactly as printed.
    assert analysis.counts == dict(seen=5, parsed=2, rejected=3, left_out=0, pages_without_rows=0)  # 2 + 0 + 3 + 0 = 5.
    assert [(issue.page, issue.row) for issue in analysis.issues] == [(1, 2), (1, 3), (1, 4)]
    # Native rows cite cells; below-table rows cite words and lines, with no cells.
    assert all(row.cell_ids and row.line_ids and not row.word_ids for row in (v1, v2))
    assert all(row.word_ids and row.line_ids and not row.cell_ids for row in (v3, v4, v5))
    assert not {row.amount_minor for row in analysis.rows} & {-98900, -99000, -98700}  # No Balance value is an amount.
    assert analysis.issues[-1].code == "rejected_row" and not [issue for issue in analysis.issues if issue.code == "second_heading"]


# --- SC-16: limits -----------------------------------------------------------------------------------------------------------

def big_rows(count):
    rows = [("08/15/2026", f"ROW {n}", "1.00") for n in range(count)]
    return [rows[start:start + 499] for start in range(0, count, 499)]  # A native table holds at most 500 rows, its heading included.


def test_analyzer_sc16_20001_rows_are_refused_and_20000_are_accepted():
    with pytest.raises(pdf_import.PDFImportError, match="exceeds 20,000 data rows"):
        pdf_import.analyze(fx.synthetic_result(big_rows(20_001)), currency="USD", account_type="checking")
    analysis = pdf_import.analyze(fx.synthetic_result(big_rows(20_000)), currency="USD", account_type="checking")
    assert analysis.counts["seen"] == 20_000 and analysis.counts["rejected"] == 0 and len(analysis.rows) == 20_000


def test_analyzer_sc16_the_row_limit_is_a_module_constant_the_api_test_can_lower(tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_import, "MAX_ROWS", 3)
    with pytest.raises(pdf_import.PDFImportError, match="exceeds 3 data rows"):
        analyze(tmp_path, fx.one_page([(f"08/0{n}/2026", f"ROW{n}", f"{n}.00") for n in range(1, 5)]), account_type="checking")
    (tmp_path / "three").mkdir()
    assert analyze(tmp_path / "three", fx.one_page([(f"08/0{n}/2026", f"ROW{n}", f"{n}.00") for n in range(1, 4)]), account_type="checking").counts["seen"] == 3


def test_analyzer_sc16_a_cell_over_2000_characters_refuses_the_whole_import(tmp_path):
    with pytest.raises(pdf_import.PDFImportError, match=r"2,000-character"):
        analyze(tmp_path, fx.long_cell_pages(), account_type="checking")


def test_analyzer_sc16_250_rejected_rows_list_200_issues_and_count_all_250():
    rows = [("08/15/2026", f"ROW {n}", "1.2.3") for n in range(250)]
    analysis = pdf_import.analyze(fx.synthetic_result([rows]), currency="USD", account_type="checking")
    assert len(analysis.issues) == 200 and analysis.counts["rejected"] == 250 and analysis.counts["seen"] == 250 and len(analysis.rows) == 250


def test_analyzer_visual_rows_and_heading_texts_equal_every_native_table_in_the_fixtures(tmp_path):
    """The analyzer's own re-implementation of the reader's row and text grouping (plan "Heading texts"): on every native table
    of the fixtures, a visual row equals the table's row, and the heading texts equal its header cells. It must also agree with
    the fixture helpers that SL-01 pinned, on every page."""
    cases = {"x": fx.x_pages(), "r": fx.r_pages(), "f": fx.f_pages(), "fn": fx.fn_pages(), "long": fx.long_cell_pages(), "d": fx.one_page(fx.D_NY),
             "x7b": fx.x_pages("7b"), "v": fx.v_pages(), "k": fx.k_pages()}
    for name, pages in cases.items():
        directory = tmp_path / name
        directory.mkdir()
        result = read(directory, pages)
        for number in range(1, len(pages) + 1):
            view = pdf_import.PageView(fx.layout(result, number))
            rows = [[text for text, _, _ in view.texts(index)] for index in range(len(view.rows))]
            assert rows == fx.row_texts(result, number), (name, number)
            assert [[word.id for word in row] for row in view.rows] == [[word.id for word in row] for row in fx.visual_rows(result, number)], (name, number)
            for grid in fx.native_grids(result, number):
                for cells in grid:
                    printed = [cell for cell in cells if cell]
                    if printed == ["Fee summary", "Count", "Total"]:
                        printed = ["Fee summary Count", "Total"]  # The reader also splits this heading at the amounts below it.
                    assert printed in rows, (name, number, printed)


# === Preview and import through the API (SL-03) ===========================================================================
# Each test starts a fresh library under tmp_path, puts synthetic PDFs in its Inbox, reads them with the real reader and no
# model, and drives the real routes. Final state is read from SQLite directly, never from the responses alone.

CONTRACT_TABLES = ("accounts", "transactions", "statements", "financial_evidence_links", "transaction_imports", "review_events")
ACCOUNTS = {"A": ("FIRST LOCAL BANK", "checking", "USD", "4821"), "C": ("SYNTH CARD SERVICES", "credit_card", "USD", "7700"),
            "B": ("OTHER BANK", "savings", "USD", "1111"), "L": ("SYNTH LENDER", "loan", "USD", "3333"), "E": ("EURO BANK", "checking", "EUR", "4821")}
INTEGRITY = "Preserved evidence failed its integrity check. Nothing was imported."
IMPORT_ID = re.compile(r"import:[0-9a-f]{32}")


class Env:
    def __init__(self, app, client):
        self.app, self.client = app, client
        self.names = {}

    @property
    def manager(self):
        return self.app.state.manager

    @property
    def store(self):
        return self.manager.store

    def add(self, name, pages, read=True, config=None, **options):
        """Put a synthetic PDF in the Inbox, capture it and (by default) read it with the real reader; returns the library row."""
        before = {doc["id"] for doc in self.store.documents()["items"]}
        if isinstance(pages, bytes):
            (self.store.library.inbox / name).write_bytes(pages)
        else:
            make_pdf(self.store.library.inbox / name, pages, **options)
        self.manager.start_inbox()
        self.manager.future.result(timeout=30)
        [doc] = [doc for doc in self.store.documents()["items"] if doc["id"] not in before]
        self.names[doc["id"]] = name
        # Capture already reads a native PDF (no model); the reader runs again here only for a model's page or when none was saved.
        if read and (config or not self.sql("SELECT 1 FROM parse_runs WHERE blob_hash=? AND status='succeeded'", doc["current_hash"])):
            self.read(doc, config)
        return doc

    def reading(self, doc):
        return self.sql("SELECT id FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') ORDER BY created_at DESC LIMIT 1", doc["current_hash"])[0][0]

    def read(self, doc, config=None, rotation=0):
        service = ReceiptService(self.store)
        run_id, _ = service.enqueue(doc["id"], vision=config or VisionConfig(), force=True)
        service.run(run_id, Work("inference", "transcription", "PDF", sink=self.store.record_model_run))
        run = service.get(run_id)
        assert run["status"] == "succeeded", run["error"]
        return run_id

    def account(self, key):
        institution, kind, currency, last_four = ACCOUNTS[key]
        response = self.client.post("/api/finance/accounts", json={"institution": institution, "account_type": kind, "currency": currency, "last_four": last_four})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def fresh(self, doc):
        return self.client.get(f"/api/documents/{doc['id']}").json()

    def preview(self, doc, **body):
        return self.client.post(f"/api/documents/{doc['id']}/transaction-import/preview", json={"expected_hash": doc["current_hash"], **body})

    def run(self, doc, **body):
        return self.client.post(f"/api/documents/{doc['id']}/transaction-imports", json={"expected_hash": doc["current_hash"], **body})

    def ok_preview(self, doc, **body):
        response = self.preview(doc, **body)
        assert response.status_code == 200, response.text
        return response.json()

    def ok_import(self, doc, reading=None, **body):
        """Import with the reading id of a preview of the same choices, as the dialog does."""
        reading = reading or self.ok_preview(doc, **{key: value for key, value in body.items() if key != "account_type"})["reading_id"]
        response = self.run(doc, reading_id=reading, **body)
        assert response.status_code == 201, response.text
        return response.json()

    def sql(self, query, *args):
        with self.store.connection() as db:
            return [tuple(row) for row in db.execute(query, args)]

    def counts(self):
        return {table: self.sql(f"SELECT count(*) FROM {table}")[0][0] for table in CONTRACT_TABLES}

    def files(self):
        """C-evidence: the sha256 of every preserved blob and every file in a saved reading folder."""
        found = {}
        for folder in (self.store.originals, self.store.root / "extracted"):
            for path in sorted(Path(folder).rglob("*")):
                if path.is_file():
                    found[str(path.relative_to(self.store.root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return found

    def state(self):
        return self.counts(), self.files()

    def refused(self, response, message):
        """C-refusal: a 4xx that names the problem (and so the next step)."""
        assert 400 <= response.status_code < 500 and message in str(response.json()["detail"]), (response.status_code, response.text)


@contextmanager
def opened(tmp_path, configure=True):
    """A library under tmp_path behind the real API. Opening it again after it closed is a restart of the Manager on the same folders."""
    app = create_app(tmp_path / "control", "pdf-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.headers.update({"Authorization": "Bearer pdf-token"})
        if configure:
            client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        yield Env(app, client)


@pytest.fixture
def env(tmp_path):
    with opened(tmp_path) as opened_env:
        yield opened_env


def minor(rows, field="amount_minor"):
    return [row[field] for row in rows]


def record_source(doc, key="extraction:test"):
    return {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": "test"}


def statement_of(rows):
    """S-K as the ledger publishes it: a bank statement for FIRST LOCAL BANK ...4821 with the table-K lines."""
    s_k = fx.S_K
    return {"statement_type": s_k["statement_type"], "institution": s_k["institution"], "last_four": s_k["last_four"], "currency": s_k["currency"],
            "period_start": s_k["period_start"], "period_end": s_k["period_end"], "opening_balance_minor": s_k["opening_balance_minor"],
            "closing_balance_minor": s_k["closing_balance_minor"], "summary": {}, "issues": [], "locator": {"line_ids": ["page-1-line-1"]},
            "transactions": [{"posted_date": posted, "description": description, "amount_minor": amount, "currency": "USD", "locator": {"line_ids": ["page-1-line-2"]}}
                             for posted, amount, description in rows]}


def concealed(env_):
    """C-ids: the printed account number, in full or in part, is stored in no ledger column (FR-30)."""
    tables = ("accounts", "transactions", "statements", "transaction_imports", "financial_evidence_links", "review_events")
    dump = " ".join(str(value) for table in tables for row in env_.sql(f"SELECT * FROM {table}") for value in row)
    assert fx.K_ACCOUNT_NUMBER not in dump
    text = " ".join(str(value) for query in ("SELECT description_raw FROM transactions", "SELECT * FROM accounts", "SELECT mapping_json,issues_json FROM transaction_imports")
                    for row in env_.sql(query) for value in row)
    assert not [window for window in (fx.K_ACCOUNT_NUMBER[start:start + 5] for start in range(len(fx.K_ACCOUNT_NUMBER) - 4)) if window in text]
    assert all(last is None or re.fullmatch(r"\d{4}", last) for (last,) in env_.sql("SELECT account_last_four FROM accounts"))


def ledger_rows(env_, account_id):
    return env_.sql("SELECT posted_date,amount_minor,typeof(amount_minor),origin,currency,description_raw FROM transactions WHERE account_id=? ORDER BY id", account_id)


def counted(env_, account_id=None):
    return env_.sql(f"SELECT count(*) FROM transactions t WHERE {COUNTABLE}" + (" AND t.account_id=?" if account_id else ""), *([account_id] if account_id else []))[0][0]


# --- J1 (SC-01, SC-12, SC-13, SC-14): import, restart, import again, a rejected row, another account, Record later ----------

def spending(env_, start="2026-08-01", end="2026-08-31"):
    """(net spending, refunds) in USD minor units, as the Spending view counts them."""
    [usd] = [row for row in FinanceTools(env_.store).get_spending(PeriodInput(start=start, end=end))["by_currency"] if row["currency"] == "USD"]
    return usd["net_spending"]["minor"], usd["refunds"]["minor"]


# By hand, net of refunds: purchases k1 450, k2 450, k3 4,510 and k8 8,240, fee k6 500, less interest k9 0.12 and the refund k7 19.99 (k5 is a transfer).
K_SPENDING = (12139, 1999)
K_SPENDING_WITHOUT_K8 = (3899, 1999)


def all_rows(env_, account_id):
    return env_.sql("SELECT id,posted_date,amount_minor,origin,review_status,review_source,category,statement_id,replaced_by,description_raw "
                    "FROM transactions WHERE account_id=? ORDER BY id", account_id)


def test_sc01_journey_j1_import_restart_import_again_reject_other_account_record_later(tmp_path):
    """One stateful journey. Step 9's Record uses the allowed fallback of the contract's doubles: `publish_statement(S-K, ..., "proposed")`."""
    with opened(tmp_path) as env:
        a, c, b = env.account("A"), env.account("C"), env.account("B")
        doc = env.add("K.pdf", fx.k_pages())
        kept = doc["current_hash"]
        # 1. The Inbox copy is overwritten without a scan: the preserved blob and its reading are what every step uses (FR-02).
        (env.store.library.inbox / "K.pdf").write_bytes(b"different bytes, never scanned")
        assert env.fresh(doc)["current_hash"] == kept
        # 2. K is listed as ready for the ledger, and is still a document (FR-01).
        listed = env.client.get("/api/documents", params={"status": "ready_for_ledger"}).json()["items"]
        assert [item["id"] for item in listed] == [doc["id"]] and listed[0]["relative_path"].endswith(".pdf")
        # 3. Preview with no account.
        before = env.state()
        preview = env.ok_preview(doc)
        assert env.state() == before  # C-unchanged and C-evidence.
        tables = [table for table in preview["tables"] if table["kind"] != "other"]
        assert [(table["page"], table["kind"], table["selected"]) for table in tables] == [(1, "rebuilt", True), (2, "continuation", True), (3, "continuation", True)]
        assert [table["linked_to"] for table in tables] == [None, tables[0]["id"], tables[0]["id"]] and [table["selectable"] for table in tables] == [True, False, False]
        assert preview["account_match"] == {"account_id": a, "last_four": "4821", "page": 1, "text": "Matched …4821 printed on page 1"}
        rows = preview["rows"]
        assert [(row["page"], row["date"], row["description"]) for row in rows] == [(r[1], r[2], r[3]) for r in fx.K_ROWS]
        assert [row["amount"] for row in rows] == [r[4] or r[5] for r in fx.K_ROWS] and minor(rows) == [r[7] for r in fx.K_ROWS]
        assert [row["posted_date"] for row in rows] == fx.K_POSTED
        assert {row["status"] for row in rows} == {"new"} and all(row["ticked"] for row in rows) and not any(row["rejected"] for row in rows)
        assert [row["labels"] for row in rows] == [[]] * 3 + [["continued from page 1"]] * 6
        assert (preview["totals"]["outflow_minor"], preview["totals"]["inflow_minor"]) == (-fx.K_OUT_MINOR, fx.K_IN_MINOR)
        assert (preview["totals"]["outflow"], preview["totals"]["inflow"]) == ("-641.50 USD", "2,020.11 USD")
        assert preview["issues"] == [] and preview["required"] == [] and preview["blocked"] is None
        assert -99000 not in minor(rows) and all(r[6].replace(",", "").replace(".", "") not in {str(abs(v)) for v in minor(rows)} for r in fx.K_ROWS)  # Balance is never an amount.
        # 4. Import into A with the preview's reading id.
        result = env.ok_import(doc, reading=preview["reading_id"], account_id=a)
        assert (result["inserted"], result["duplicates"], result["rejected"], result["left_out"]) == (9, 0, 0, 0) and result["account_name"] == "FIRST LOCAL BANK checking 4821"
        assert "reconciliation" in result and re.fullmatch(r"[0-9a-f]{32}", result["import_id"])
        stored = ledger_rows(env, a)
        assert [(row[0], row[1]) for row in stored] == list(zip(fx.K_POSTED, [r[7] for r in fx.K_ROWS]))
        assert {row[2:5] for row in stored} == {("integer", "import", "USD")} and counted(env, a) == 9
        [(mapping_json, parsed, inserted, duplicates, rejected, issues_json, created)] = env.sql(
            "SELECT mapping_json,parsed,inserted,duplicates,rejected,issues_json,created_at FROM transaction_imports")
        record = json.loads(mapping_json)
        assert (parsed, inserted, duplicates, rejected, json.loads(issues_json)) == (9, 9, 0, 0, []) and created
        assert (record["kind"], record["reading_id"], record["year"], record["sign"], record["left_out"]) == ("pdf", preview["reading_id"], None, None, 0)
        assert record["mapping"] == {"date": "Date", "description": "Description", "debit": "Withdrawals", "credit": "Deposits"}  # No Balance.
        assert [(table["page"], table["linked_to"]) for table in record["tables"]] == [(1, None), (2, tables[0]["id"]), (3, tables[0]["id"])]
        assert len(record["ticked"]) == 9 and record["unticked"] == []
        links = env.sql("SELECT source_key,locator_json,blob_hash,parse_run_id FROM financial_evidence_links WHERE record_type='transaction' ORDER BY id")
        assert len(links) == 9 and all(IMPORT_ID.fullmatch(link[0]) and link[2] == kept and link[3] == preview["reading_id"] for link in links)
        for link, row in zip(links, rows):
            locator = json.loads(link[1])
            assert (locator["document_id"], locator["blob_hash"], locator["reading_id"], locator["page"], locator["table_id"], locator["row"]) == (
                doc["id"], kept, preview["reading_id"], row["page"], row["table_id"], row["row"])
            assert locator["word_ids"] and locator["line_ids"] and ("continued_from" in locator) == (row["page"] > 1)
        concealed(env)
        assert env.files() == before[1]  # The blob and the saved reading are byte-identical after the import (C-evidence).
        assert env.sql("SELECT count(*) FROM accounts")[0][0] == 3 and c
        after_four = (env.counts(), env.files(), all_rows(env, a), env.sql("SELECT * FROM financial_evidence_links ORDER BY id"),
                      env.sql("SELECT id,mapping_json,created_at FROM transaction_imports"))
    # J1-a: the Manager closes and opens again on the same folders. Nothing from step 4 is lost or doubled, and every later step runs on the new one.
    with opened(tmp_path, configure=False) as env:
        assert (env.counts(), env.files(), all_rows(env, a), env.sql("SELECT * FROM financial_evidence_links ORDER BY id"),
                env.sql("SELECT id,mapping_json,created_at FROM transaction_imports")) == after_four
        assert env.fresh(doc)["current_hash"] == kept
        # 5. Spending counts the imported rows; Record is still the next step; a second preview shows every row as already recorded (FR-18, FR-12).
        assert spending(env) == K_SPENDING
        assert env.fresh(doc)["ledger_status"] == "imported"
        ready = env.client.get("/api/documents", params={"status": "ready_for_ledger"}).json()["items"]
        assert [item["id"] for item in ready] == [doc["id"]]  # Plan P5: an imported PDF stays ready to record.
        again = env.ok_preview(doc, account_id=a)
        assert {row["status_text"] for row in again["rows"]} == {"Already recorded from import K.pdf"} and again["counts"]["new"] == 0 and again["counts"]["already_recorded"] == 9
        assert again["totals"]["outflow_minor"] == 0 and again["totals"]["inflow_minor"] == 0
        # 6. (J1-a repeats this step after the restart.) Import K into A again with the same choices.
        result = env.ok_import(doc, reading=again["reading_id"], account_id=a)
        assert (result["inserted"], result["duplicates"], result["rejected"]) == (0, 9, 0) and result["duplicate_sources"] == {"Already recorded from import K.pdf": 9}
        assert len(env.sql("SELECT id FROM transaction_imports")) == 2 and len(ledger_rows(env, a)) == 9
        assert all_rows(env, a) == after_four[2]
        links = env.sql("SELECT record_id,source_key FROM financial_evidence_links WHERE record_type='transaction'")
        assert len(links) == 18 and all(len({key for record, key in links if record == row[0]}) == 2 for row in after_four[2])
        assert spending(env) == K_SPENDING
        # 7. Reject k8 through the transaction review action: it is reported "rejected earlier", the others are duplicates, nothing is inserted.
        [(k8,)] = env.sql("SELECT id FROM transactions WHERE account_id=? AND description_raw='UTILITY CO'", a)
        assert env.client.post(f"/api/finance/records/transaction/{k8}/review", json={"status": "rejected"}).status_code == 200
        third = env.ok_preview(doc, account_id=a)
        assert [row["status"] for row in third["rows"]].count("rejected_earlier") == 1 and third["counts"]["new"] == 0
        assert [row["status_text"] for row in third["rows"] if row["description"] == "UTILITY CO"] == ["rejected earlier"]
        result = env.ok_import(doc, reading=third["reading_id"], account_id=a)
        assert (result["inserted"], result["duplicates"], result["rejected_earlier"]) == (0, 9, 1) and result["duplicate_sources"] == {"Already recorded from import K.pdf": 8, "rejected earlier": 1}
        assert env.sql("SELECT review_status FROM transactions WHERE id=?", k8) == [("rejected",)] and counted(env, a) == 8
        assert spending(env) == K_SPENDING_WITHOUT_K8
        # 8. Import K into B, which no last four matched, so the request names it. A's rows and their review state are unchanged.
        a_rows = all_rows(env, a)
        into_b = env.ok_import(doc, account_id=b)
        assert (into_b["inserted"], into_b["duplicates"], into_b["account_id"], into_b["account_name"]) == (9, 0, b, "OTHER BANK savings 1111")
        assert all_rows(env, a) == a_rows and [row[1] for row in ledger_rows(env, b)] == [r[7] for r in fx.K_ROWS] and len(env.sql("SELECT id FROM transaction_imports")) == 4
        b_rows = all_rows(env, b)
        # 9. Record K into A with the Record double S-K: its statement awaits reconciliation and the rows keep their origin and review state.
        lines = list(zip(fx.K_POSTED, [r[7] for r in fx.K_ROWS], [r[3] for r in fx.K_ROWS]))
        published = env.manager.ledger.publish_statement(statement_of(lines), record_source(doc), "proposed")
        assert published["account_id"] == a and (published["inserted"], published["duplicates"]) == (0, 9)
        assert env.sql("SELECT account_id,reconciliation FROM statements") == [(a, "awaiting")]
        statement = published["id"]
        rows_now = all_rows(env, a)
        assert [row[0] for row in rows_now] == [row[0] for row in a_rows] and {row[7] for row in rows_now} == {statement}
        assert [row[1:7] + row[8:] for row in rows_now] == [row[1:7] + row[8:] for row in a_rows]  # Only statement_id changed.
        assert {row[3] for row in rows_now} == {"import"} and counted(env, a) == 8 and [row[4] for row in rows_now if row[0] == k8] == ["rejected"]
        assert all_rows(env, b) == b_rows  # B's rows are untouched: their account differs, so their fingerprints do.
        # 10. The statement is read again: the same 9 rows, each keeping its import evidence.
        env.manager.ledger.publish_statement(statement_of(lines), record_source(doc, "extraction:test-again"), "proposed")
        assert [row[0] for row in all_rows(env, a)] == [row[0] for row in a_rows]
        for row in a_rows:
            assert env.sql("SELECT count(*) FROM financial_evidence_links WHERE record_type='transaction' AND record_id=? AND source_key LIKE 'import:%'", row[0]) == [(3,)]  # Steps 4, 6 and 7.
        # Final state.
        assert env.counts()["transactions"] == 18 and env.counts()["transaction_imports"] == 4 and env.counts()["statements"] == 1 and env.counts()["accounts"] == 3
        assert env.sql("SELECT account_id,count(*),min(origin),max(origin) FROM transactions GROUP BY account_id ORDER BY account_id") == [(a, 9, "import", "import"), (b, 9, "import", "import")]
        assert counted(env) == 17 and counted(env, a) == 8 and counted(env, b) == 9
        assert env.sql("SELECT count(*) FROM transactions WHERE typeof(amount_minor)<>'integer'") == [(0,)]
        concealed(env)
        assert {path: digest for path, digest in env.files().items()} == before[1]


def test_sc02_dates_printed_without_a_year_need_the_year_and_card_amounts_flip(env):
    c = env.account("C")
    doc = env.add("r.pdf", fx.r_pages())
    preview = env.ok_preview(doc, account_id=c)
    assert [row["date"] for row in preview["rows"]] == [r[2] for r in fx.R_ROWS]  # As printed.
    assert preview["required"] == ["year"] and "Choose the year" in preview["required_messages"][0]
    assert (preview["sign_default"], preview["sign"]) == ("positive_is_outflow", "positive_is_outflow")
    assert minor(preview["rows"]) == [r[5] for r in fx.R_ROWS]
    assert (preview["totals"]["outflow_minor"], preview["totals"]["inflow_minor"]) == fx.R_TOTALS_C
    assert (preview["totals"]["outflow"], preview["totals"]["inflow"]) == ("-112.94 USD", "269.99 USD")
    before = env.state()
    env.refused(env.run(doc, account_id=c, reading_id=preview["reading_id"]), "Choose the year")
    assert env.state() == before
    preview = env.ok_preview(doc, account_id=c, year=2025)
    assert preview["required"] == []
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=c, year=2025)
    assert result["inserted"] == 5
    stored = ledger_rows(env, c)
    assert [(row[0], row[1]) for row in stored] == list(zip(fx.R_POSTED_2025, [r[5] for r in fx.R_ROWS]))
    assert not [row for row in stored if row[0].startswith("2026")] and {row[2:5] for row in stored} == {("integer", "import", "USD")} and counted(env, c) == 5
    [(mapping_json,)] = env.sql("SELECT mapping_json FROM transaction_imports")
    assert (json.loads(mapping_json)["year"], json.loads(mapping_json)["sign"]) == (2025, "positive_is_outflow") and env.counts()["transaction_imports"] == 1


def test_sc03_the_sign_default_follows_the_chosen_account(env):
    a, c, l = env.account("A"), env.account("C"), env.account("L")
    other = env.client.post("/api/finance/accounts", json={"institution": "ELSEWHERE", "account_type": "other", "currency": "USD"}).json()["id"]
    savings = env.account("B")
    doc = env.add("r.pdf", fx.r_pages())
    pick = lambda **body: env.ok_preview(doc, year=2025, **body)
    card = pick(account_id=c)
    assert (card["sign_default"], card["required"], minor(card["rows"])) == ("positive_is_outflow", [], [r[5] for r in fx.R_ROWS])
    assert (card["totals"]["outflow_minor"], card["totals"]["inflow_minor"]) == fx.R_TOTALS_C
    checking = pick(account_id=a)
    assert (checking["sign_default"], checking["sign"]) == ("negative_is_outflow", "negative_is_outflow")
    assert minor(checking["rows"]) == [r[6] for r in fx.R_ROWS]
    assert (checking["totals"]["outflow_minor"], checking["totals"]["inflow_minor"]) == fx.R_TOTALS_A
    flipped = pick(account_id=a, sign="positive_is_outflow")
    assert minor(flipped["rows"]) == [r[5] for r in fx.R_ROWS] and flipped["sign_default"] == "negative_is_outflow"
    loan = pick(account_id=l)
    assert (loan["sign_default"], loan["required"], loan["sign"]) == (None, ["sign"], None)
    # Variant 3-a: a savings account behaves as checking; an `other` account as the loan.
    assert pick(account_id=savings)["sign_default"] == "negative_is_outflow" and pick(account_id=other)["required"] == ["sign"]
    before = env.state()
    env.refused(env.run(doc, account_id=l, year=2025, reading_id=loan["reading_id"]), "Choose whether positive amounts are money in or money out")
    assert env.state() == before
    result = env.ok_import(doc, reading=loan["reading_id"], account_id=l, year=2025, sign="positive_is_outflow")
    assert result["inserted"] == 5 and [row[1] for row in ledger_rows(env, l)] == [r[5] for r in fx.R_ROWS]
    assert env.counts()["transactions"] == 5  # Only step 4's import is written.


# --- SC-04: preview writes nothing -------------------------------------------------------------------------------------------

def test_sc04_preview_writes_nothing_and_repeats_exactly(env):
    doc = env.add("k.pdf", fx.k_pages())
    before = env.state()
    previews = [env.preview(doc) for _ in range(3)]
    assert [response.status_code for response in previews] == [200] * 3
    assert previews[0].json() == previews[1].json() == previews[2].json()
    preview = previews[0].json()
    assert [row["status"] for row in preview["rows"]] == ["new"] * 9 and len(preview["rows"]) == 9
    assert preview["account_match"] is None and preview["account_id"] is None and preview["currency"] == "USD"  # No account exists: nothing to preselect.
    assert env.state() == before and env.counts()["accounts"] == 0


# --- SC-05: account preselection ---------------------------------------------------------------------------------------------

def test_sc05_an_account_is_preselected_only_on_a_unique_same_currency_last_four(env):
    a = env.account("A")
    env.account("E")
    k = env.add("k.pdf", fx.k_pages())
    assert env.ok_preview(k)["account_match"] == {"account_id": a, "last_four": "4821", "page": 1, "text": "Matched \u20264821 printed on page 1"}  # E is EUR.
    env.account("C")
    k2 = env.add("k2.pdf", fx.k2_pages())
    assert env.ok_preview(k2)["account_match"] is None  # 4821 and 7700 each match an account in USD.
    k0 = env.add("k0.pdf", fx.k0_pages())
    assert env.ok_preview(k0)["account_match"] is None
    before = env.state()
    env.refused(env.run(k2, reading_id=env.ok_preview(k2)["reading_id"]), "Choose the account these transactions belong to.")
    assert env.state() == before


def test_sc05_every_printed_form_of_the_last_four_matches_and_two_non_forms_do_not(env):
    a = env.account("A")
    env.account("C")
    for number, line in enumerate(fx.PATTERN_MATCHES):
        doc = env.add(f"match-{number}.pdf", fx.pattern_page(line))
        match = env.ok_preview(doc)["account_match"]
        assert match and match["account_id"] == a and match["text"] == "Matched \u20264821 printed on page 1", line
    for number, line in enumerate(fx.PATTERN_MISSES):
        assert env.ok_preview(env.add(f"miss-{number}.pdf", fx.pattern_page(line)))["account_match"] is None, line


def test_sc05_a_document_in_another_currency_does_not_match_an_account_in_usd_and_reads_that_currency(env):
    env.account("A")
    doc = env.add("keur.pdf", fx.keur_pages())
    preview = env.ok_preview(doc)
    assert preview["account_match"] is None and preview["currency"] == "EUR" and preview["blocked"] is None and preview["document_currency"] == "EUR"
    assert minor(preview["rows"]) == [r[7] for r in fx.K_ROWS] and preview["totals"]["outflow"] == "-641.50 EUR"
    euro = env.account("E")
    assert env.ok_preview(doc)["account_match"]["account_id"] == euro


# --- SC-07 / SC-24 / SC-25 import steps --------------------------------------------------------------------------------------

def x_import(env_, variant):
    a = env_.account("A")
    doc = env_.add("x.pdf", fx.x_pages(variant))
    preview = env_.ok_preview(doc, account_id=a, date_format="MM/DD/YYYY")
    return a, doc, preview, preview["reading_id"]


def test_sc07_cross_page_rows_are_previewed_and_imported_with_every_page_accounted_for(env):
    a, doc, preview, reading = x_import(env, None)
    others = [table for table in preview["tables"] if table["kind"] == "other"]
    assert [(table["headings"], table["selected"], table["selectable"], table["rows"]) for table in others] == [
        (["Summary", "Amount"], False, False, []), (["Fee summary", "Count", "Total"], False, False, [])]  # "not a transactions table".
    assert [(table["page"], table["kind"], table["selected"]) for table in preview["tables"] if table["kind"] != "other"] == [
        (1, "transactions", True), (2, "continuation", True)]
    rows = preview["rows"]
    assert [(row["description"], row["amount_minor"], row["ticked"], row["labels"]) for row in rows] == [
        ("A1", -1000, True, []), ("A2", 2000, True, []), ("B1", -100, True, ["continued from page 1"]), ("B2", 200, True, ["continued from page 1"])]
    assert [issue["message"] for issue in preview["issues"]] == ["Page 3: no transactions table found"]
    assert (preview["totals"]["outflow_minor"], preview["totals"]["inflow_minor"]) == fx.X_TOTALS
    result = env.ok_import(doc, reading=reading, account_id=a, date_format="MM/DD/YYYY")
    # FR-10: imported + duplicates + rejected + left out = rows seen; each page is a row source or in the issue list.
    assert result["inserted"] + result["duplicates"] + result["rejected"] + result["left_out"] == preview["counts"]["seen"] == 4
    assert {row["page"] for row in rows} | {issue["page"] for issue in result["issues"]} == {1, 2, 3}
    assert [(row[0], row[1]) for row in ledger_rows(env, a)] == [("2026-09-01", -1000), ("2026-09-02", 2000), ("2026-09-03", -100), ("2026-09-04", 200)]


def test_sc07_7c_a_page_with_a_column_blank_on_every_row_is_rebuilt_and_imported(env):
    a, doc, preview, reading = x_import(env, "7c")
    assert [(table["page"], table["kind"]) for table in preview["tables"] if table["kind"] != "other"] == [(1, "rebuilt"), (2, "continuation")]
    assert minor(preview["rows"]) == [-1000, -2000, -100, 200]
    assert (preview["totals"]["outflow_minor"], preview["totals"]["inflow_minor"]) == fx.X_7C_TOTALS
    assert env.ok_import(doc, reading=reading, account_id=a, date_format="MM/DD/YYYY")["inserted"] == 4


def test_sc07_7d_and_7e_rows_that_do_not_fit_their_columns_are_rejected_and_the_rest_import(env):
    a, doc, preview, reading = x_import(env, "7d")
    [b2] = [row for row in preview["rows"] if row["description"] == "B2"]
    assert (b2["status"], b2["page"], b2["ticked"]) == ("rejected", 2, False) and "doesn't fit a column" in b2["rejected"]
    result = env.ok_import(doc, reading=reading, account_id=a, date_format="MM/DD/YYYY")
    assert (result["inserted"], result["rejected"]) == (3, 1) and "B2" not in [row[5] for row in ledger_rows(env, a)]


def test_sc07_7e_text_in_an_amount_column_rejects_that_row(env):
    a, doc, preview, reading = x_import(env, "7e")
    [b1] = [row for row in preview["rows"] if row["description"].startswith("B1")]
    assert b1["status"] == "rejected" and b1["page"] == 2
    result = env.ok_import(doc, reading=reading, account_id=a, date_format="MM/DD/YYYY")
    assert (result["inserted"], result["rejected"]) == (3, 1) and [row[5] for row in ledger_rows(env, a)] == ["A1", "A2", "B2"]


def test_sc07_7a_a_later_page_with_dated_amounts_is_counted_with_the_preview_totals_as_the_check(env):
    a, doc, preview, reading = x_import(env, "7a")
    assert (preview["totals"]["outflow_minor"], preview["totals"]["inflow_minor"]) == (fx.X_TOTALS[0] - 5000, fx.X_TOTALS[1])
    assert env.ok_import(doc, reading=reading, account_id=a, date_format="MM/DD/YYYY")["inserted"] == 6


def test_sc24_dates_without_a_year_are_refused_until_the_year_is_chosen_and_roll_over(env):
    a = env.account("A")
    doc = env.add("d-ny.pdf", fx.one_page(fx.D_NY))
    reading = env.ok_preview(doc, account_id=a)["reading_id"]
    assert env.ok_preview(doc, account_id=a)["required"] == ["year"]
    before = env.state()
    env.refused(env.run(doc, account_id=a, reading_id=reading), "Choose the year")
    assert env.state() == before
    env.ok_import(doc, reading=reading, account_id=a, year=2025)
    assert [row[0] for row in ledger_rows(env, a)] == ["2025-08-03", "2025-12-30", "2026-01-02"]


def test_sc24_an_impossible_date_rejects_only_its_row_and_names_the_date(env):
    a = env.account("A")
    doc = env.add("d-bad.pdf", fx.one_page(fx.D_BAD))
    preview = env.ok_preview(doc, account_id=a)
    [p, q] = preview["rows"]
    assert (p["status"], p["posted_date"]) == ("new", "2026-02-27") and q["status"] == "rejected" and "02/30/2026" in q["rejected"]
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert (result["inserted"], result["rejected"]) == (1, 1) and [row[0] for row in ledger_rows(env, a)] == ["2026-02-27"]


def test_sc24_full_dates_import_without_a_year_and_an_ambiguous_order_is_a_choice(env):
    a = env.account("A")
    full = env.add("d-full.pdf", fx.one_page(fx.D_FULL))
    assert env.ok_preview(full, account_id=a)["required"] == ["date_format"]  # No value above 12: the order is a choice, never a guess.
    preview = env.ok_preview(full, account_id=a, date_format="MM/DD/YYYY")
    assert preview["required"] == [] and env.ok_import(full, reading=preview["reading_id"], account_id=a, date_format="MM/DD/YYYY")["inserted"] == 2
    assert [row[0] for row in ledger_rows(env, a)] == ["2026-08-03", "2026-08-04"]
    a = env.account("B")  # A already holds a +1.00 on 2026-08-03.
    amb = env.add("d-amb.pdf", fx.one_page(fx.D_AMB))
    assert env.ok_preview(amb, account_id=a)["required"] == ["date_format"]
    day_first = env.ok_preview(amb, account_id=a, date_format="DD/MM/YYYY")
    assert [row["posted_date"] for row in day_first["rows"]] == ["2026-08-03", "2026-09-04"]
    month_first = env.ok_preview(amb, account_id=a, date_format="MM/DD/YYYY")
    assert [row["posted_date"] for row in month_first["rows"]] == ["2026-03-08", "2026-04-09"]
    env.ok_import(amb, reading=day_first["reading_id"], account_id=a, date_format="DD/MM/YYYY")
    assert [row[0] for row in ledger_rows(env, a)] == ["2026-08-03", "2026-09-04"]


def test_sc24_two_digit_years_are_refused_until_the_year_is_chosen(env):
    a = env.account("A")
    doc = env.add("d-2y.pdf", fx.one_page(fx.D_2Y))
    preview = env.ok_preview(doc, account_id=a, date_format="MM/DD/YYYY")
    assert preview["required"] == ["year"]
    before = env.state()
    env.refused(env.run(doc, account_id=a, date_format="MM/DD/YYYY", reading_id=preview["reading_id"]), "Choose the year")
    assert env.state() == before


def test_sc25_rejected_rows_are_listed_with_page_row_and_reason_and_never_inserted(env):
    a = env.account("A")
    doc = env.add("v.pdf", fx.v_pages())
    preview = env.ok_preview(doc, account_id=a, date_format="MM/DD/YYYY")
    v1, v2, v3, v4, v5 = preview["rows"]
    assert [(row["page"], row["row"]) for row in (v2, v3, v4)] == [(1, 2), (1, 3), (1, 4)]
    assert [row["rejected"] for row in (v2, v3, v4)] == ["Both a debit and a credit are printed.", "The description is blank.", 'The amount "1.2.3" can\'t be read.']
    assert [row["status"] for row in preview["rows"]] == ["new", "rejected", "rejected", "rejected", "new"]
    assert (preview["counts"]["new"], preview["counts"]["rejected"], preview["counts"]["seen"]) == (2, 3, 5)  # 2 + 0 + 3 + 0 = 5.
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a, date_format="MM/DD/YYYY")
    assert (result["inserted"], result["rejected"], result["duplicates"], result["left_out"]) == (2, 3, 0, 0)
    stored = ledger_rows(env, a)
    assert [(row[1], row[2]) for row in stored] == [(-1000, "integer"), (-200, "integer")]  # No Balance value is an amount.
    assert stored[1][5] == fx.V_LONG_DESCRIPTION and len(stored[1][5]) == 480  # v5 as printed, within the 500 characters kept.
    assert {issue["row"] for issue in result["issues"]} == {2, 3, 4}


# --- SC-08: a flagged page ---------------------------------------------------------------------------------------------------

def test_sc08_rows_from_a_flagged_page_start_unticked_and_the_user_chooses(env):
    a = env.account("A")
    doc = env.add("f.pdf", fx.f_pages())
    preview = env.ok_preview(doc, account_id=a, date_format="MM/DD/YYYY")
    rows = preview["rows"]
    assert [row["ticked"] for row in rows] == [True, True, False, False, False, False]
    assert all(row["labels"][-1].startswith("Page 2 PDF layout needs review") for row in rows[2:]) and rows[0]["labels"] == rows[1]["labels"] == []
    assert [(row["posted_date"], row["amount_minor"]) for row in rows[2:]] == [("2026-07-03", 100), ("2026-07-04", 200), ("2026-07-05", 300), ("2026-07-06", 400)]
    assert (preview["totals"]["inflow_minor"], preview["totals"]["outflow_minor"]) == (3000, 0) and preview["counts"]["left_out"] == 4
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a, date_format="MM/DD/YYYY", ticked=[rows[2]["key"], rows[4]["key"]])
    assert (result["inserted"], result["left_out"]) == (4, 2)
    assert [row[5] for row in ledger_rows(env, a)] == ["F1", "F2", "F3", "F5"] and counted(env, a) == 4
    [(mapping_json,)] = env.sql("SELECT mapping_json FROM transaction_imports")
    record = json.loads(mapping_json)
    assert record["unticked"] == [rows[3]["key"], rows[5]["key"]] and len(record["ticked"]) == 4 and record["left_out"] == 2


def test_sc08_8a_a_footer_with_a_digit_does_not_flag_a_native_table(env):
    a = env.account("A")
    preview = env.ok_preview(env.add("fn.pdf", fx.fn_pages()), account_id=a, date_format="MM/DD/YYYY")
    assert [row["ticked"] for row in preview["rows"]] == [True, True] and [row["labels"] for row in preview["rows"]] == [[], []] and preview["issues"] == []


def test_unticking_a_row_never_renumbers_another_rows_identity(env):
    """Plan P3: fingerprints are worked out over every parsed row, so k2 (same day and amount as k1) keeps ordinal 1."""
    a = env.account("A")
    doc = env.add("k.pdf", fx.k_pages())
    preview = env.ok_preview(doc, account_id=a)
    k1 = preview["rows"][0]["key"]
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a, unticked=[k1])
    assert (result["inserted"], result["left_out"]) == (8, 1)
    ordinal = lambda number: hashlib.sha256(f"v1|{a}|2026-08-03|-450|USD|{number}".encode()).hexdigest()
    assert [row[0] for row in env.sql("SELECT source_fingerprint FROM transactions WHERE posted_date='2026-08-03'")] == [ordinal(1)]
    after = env.ok_preview(doc, account_id=a)
    assert [row["status"] for row in after["rows"][:3]] == ["new", "already_recorded", "already_recorded"]
    assert after["rows"][1]["status_text"] == f"Already recorded from import {env.names[doc['id']]}"
    assert (after["totals"]["outflow_minor"], after["already_recorded_totals"]["inflow_minor"]) == (-450, fx.K_IN_MINOR)
    again = env.ok_import(doc, reading=after["reading_id"], account_id=a)
    assert (again["inserted"], again["duplicates"], again["duplicate_sources"]) == (1, 8, {"Already recorded from import k.pdf": 8})
    assert sorted(row[0] for row in env.sql("SELECT source_fingerprint FROM transactions WHERE posted_date='2026-08-03'")) == sorted([ordinal(0), ordinal(1)])


# --- SC-09: a scanned page ---------------------------------------------------------------------------------------------------

def test_sc09_a_scanned_page_is_reported_and_contributes_no_row(env, local_model):
    a = env.account("A")
    local_model["output"] = {"full_text": "SCANNED PAGE TWO\n08/04/2026 SCANNED CAFE 7.00"}
    doc = env.add("m.pdf", fx.m_pages(), config=local_model["config"])
    requests = len(local_model["requests"])
    assert requests == 1
    preview = env.ok_preview(doc, account_id=a, date_format="MM/DD/YYYY")  # k1-k3 print no day above 12.
    assert [row["description"] for row in preview["rows"]] == ["COFFEE SHOP", "COFFEE SHOP", "GROCERY MART"] and "SCANNED CAFE" not in json.dumps(preview["rows"])
    assert [issue["message"] for issue in preview["issues"]] == ["Page 2 is a scanned page; no rows imported. Use Record for scanned statements."]
    assert len(local_model["requests"]) == requests
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a, date_format="MM/DD/YYYY")
    assert result["inserted"] == 3 and len(local_model["requests"]) == requests
    assert {json.loads(locator)["page"] for (locator,) in env.sql("SELECT locator_json FROM financial_evidence_links WHERE record_type='transaction'")} == {1}


def test_sc09_9a_an_all_scanned_pdf_previews_no_rows_and_importing_it_writes_nothing(env, local_model):
    a = env.account("A")
    local_model["output"] = {"full_text": "SCANNED PAGE ONE\n08/04/2026 SCANNED CAFE 7.00"}
    doc = env.add("scan.pdf", [None], config=local_model["config"])
    preview = env.ok_preview(doc, account_id=a)
    assert preview["rows"] == [] and preview["tables"] == [] and [issue["message"] for issue in preview["issues"]] == [
        "Page 1 is a scanned page; no rows imported. Use Record for scanned statements."]
    before = env.state()
    env.refused(env.run(doc, account_id=a, reading_id=preview["reading_id"]), "Nothing to import: Page 1 is a scanned page")
    assert env.state() == before


# --- SC-15: documents that cannot be imported --------------------------------------------------------------------------------

def test_sc15_a_pdf_recorded_as_something_else_is_refused_and_trash_must_be_restored(env):
    a = env.account("A")
    ledger = env.manager.ledger
    copy = lambda name: env.add(f"{name}.pdf", fx.k_pages(above=(*fx.K_TEXT, f"Copy {name}")))
    receipt, bill, stub, trashed, recorded = (copy(name) for name in ("pr", "pb", "pp", "pt", "ps"))
    ledger.publish_receipt({"merchant": "Corner Shop", "purchase_date": "2026-09-10", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                            "total_minor": 299, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-0"]}, "items": []}, record_source(receipt), "proposed")
    ledger.publish_bill({"provider": "City Power", "issue_date": "2026-09-10", "due_date": "2026-09-20", "period_start": None, "period_end": None,
                         "amount_due_minor": 12000, "currency": "USD", "issues": [], "locator": {}}, record_source(bill), "proposed")
    ledger.publish_income({"payer_or_employer": "Acme Widgets", "pay_date": "2026-09-15", "period_start": None, "period_end": None, "gross_pay_minor": 320000,
                           "net_pay_minor": 250000, "taxes_minor": 50000, "deductions_minor": 20000, "currency": "USD", "issues": [], "locator": {}},
                          record_source(stub), "proposed")
    for doc, kind in ((receipt, "receipt"), (bill, "bill"), (stub, "pay stub")):
        before = env.state()
        for response in (env.preview(doc, account_id=a), env.run(doc, account_id=a, reading_id=env.reading(doc))):
            env.refused(response, f"This PDF is recorded as a {kind}.")
        assert env.state() == before
    # Pt: in Trash, refused until restored.
    env.client.post(f"/api/documents/{trashed['id']}/trash", json={"expected_hash": trashed["current_hash"], "confirmed": True})
    before = env.state()
    env.refused(env.preview(trashed, account_id=a), "Restore the document from Trash before importing it.")
    env.refused(env.run(trashed, account_id=a, reading_id="0" * 32), "Restore the document from Trash before importing it.")
    assert env.state() == before
    assert env.client.post(f"/api/documents/{trashed['id']}/restore", json={"expected_hash": trashed["current_hash"]}).status_code == 200
    assert env.ok_preview(trashed, account_id=a)["counts"]["new"] == 9
    # Ps: Recorded as a statement and reconciled: its own rows are "Already recorded from this statement".
    published = ledger.publish_statement(statement_of(list(zip(fx.K_POSTED, [r[7] for r in fx.K_ROWS], [r[3] for r in fx.K_ROWS]))), record_source(recorded), "proposed")
    assert published["inserted"] == 9 and published["account_id"] == a
    ledger.review("statement", published["id"], "verified")
    waiting = env.ok_preview(recorded, account_id=a)  # Until the user reconciles the statement its lines do not count, and the preview says so.
    assert {row["status_text"] for row in waiting["rows"]} == {"Already recorded from this statement; not counted until you reconcile it."}
    env.manager.reconciler.reconcile_statement(published["id"])  # The user releases the statement's lines.
    assert env.sql("SELECT reconciliation FROM statements") == [("reconciled",)]
    preview = env.ok_preview(recorded, account_id=a)
    assert {row["status_text"] for row in preview["rows"]} == {"Already recorded from this statement"} and preview["counts"]["new"] == 0
    result = env.ok_import(recorded, reading=preview["reading_id"], account_id=a)
    assert (result["inserted"], result["duplicates"]) == (0, 9) and env.sql("SELECT count(*) FROM transactions WHERE account_id=?", a)[0][0] == 9


# --- SC-16: limits -----------------------------------------------------------------------------------------------------------

def test_sc16_the_row_limit_and_the_cell_limit_refuse_the_whole_import(env, monkeypatch):
    a = env.account("A")
    rows = lambda count: [("08/15/2026", f"ROW {n}", "1.00") for n in range(count)]
    four = env.add("four.pdf", fx.one_page(rows(4)))
    three = env.add("three.pdf", fx.one_page(rows(3)))
    reading = env.ok_preview(four, account_id=a)["reading_id"]
    monkeypatch.setattr(pdf_import, "MAX_ROWS", 3)
    before = env.state()
    env.refused(env.preview(four, account_id=a), "exceeds 3 data rows")
    env.refused(env.run(four, account_id=a, reading_id=reading), "exceeds 3 data rows")
    assert env.state() == before
    preview = env.ok_preview(three, account_id=a)
    assert env.ok_import(three, reading=preview["reading_id"], account_id=a)["inserted"] == 3
    long = env.add("long.pdf", fx.long_cell_pages())
    before = env.state()
    env.refused(env.preview(long, account_id=a), "2,000-character")
    env.refused(env.run(long, account_id=a, reading_id=env.reading(long)), "2,000-character")
    assert env.state() == before and env.sql("SELECT count(*) FROM transactions")[0][0] == 3


# --- SC-17: integrity checks before any write --------------------------------------------------------------------------------

def previewed_k(env_):
    a = env_.account("A")
    doc = env_.add("k.pdf", fx.k_pages())
    return a, doc, env_.ok_preview(doc, account_id=a)["reading_id"]


def changed_files(before, after):
    return {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}


def test_sc17a_a_corrupted_preserved_blob_refuses_the_import(env):
    a, doc, reading = previewed_k(env)
    before = env.state()
    blob = env.store.blob_path(doc["current_hash"])
    blob.write_bytes(b"corrupt")
    env.refused(env.run(doc, account_id=a, reading_id=reading), INTEGRITY)
    env.refused(env.preview(doc, account_id=a), INTEGRITY)
    after = env.state()
    assert after[0] == before[0] and changed_files(before[1], after[1]) == {str(blob.relative_to(env.store.root))}


def test_sc17b_a_changed_saved_reading_refuses_the_import(env):
    a, doc, reading = previewed_k(env)
    before = env.state()
    saved = env.store.root / "extracted" / reading / "result.json"
    text = saved.read_text(encoding="utf-8")
    assert "45.10" in text
    saved.write_text(text.replace("45.10", "45.11", 1), encoding="utf-8")
    env.refused(env.run(doc, account_id=a, reading_id=reading), INTEGRITY)
    after = env.state()
    assert after[0] == before[0] and changed_files(before[1], after[1]) == {str(saved.relative_to(env.store.root))}


def test_sc17c_a_document_captured_again_with_new_content_refuses_the_old_hash(env):
    a, doc, reading = previewed_k(env)
    (env.store.library.inbox / "k.pdf").write_bytes(fx_bytes(env, fx.k_pages(above=(*fx.K_TEXT, "A changed copy"))))
    env.manager.start_inbox()
    env.manager.future.result(timeout=30)
    assert env.fresh(doc)["current_hash"] != doc["current_hash"]
    before = env.state()
    env.refused(env.run(doc, account_id=a, reading_id=reading), "This document changed since the preview; preview again.")
    env.refused(env.preview(doc, account_id=a), "This document changed since the preview; preview again.")
    assert env.state() == before


def fx_bytes(env_, pages):
    scratch = env_.store.root.parent / "scratch.pdf"
    make_pdf(scratch, pages)
    return scratch.read_bytes()


def test_sc17d_a_document_read_again_after_the_preview_must_be_previewed_again(env):
    a, doc, reading = previewed_k(env)
    assert env.read(doc) != reading
    before = env.state()
    env.refused(env.run(doc, account_id=a, reading_id=reading), "This document was read again since the preview; preview again.")
    assert env.state() == before
    fresh = env.ok_preview(doc, account_id=a)["reading_id"]
    assert fresh != reading and env.ok_import(doc, reading=fresh, account_id=a)["inserted"] == 9


def test_sc17e_a_fault_while_inserting_leaves_nothing_and_the_retry_imports_all(env):
    a, doc, reading = previewed_k(env)
    with env.store.connection() as db:
        db.execute("CREATE TRIGGER fault BEFORE INSERT ON transactions WHEN NEW.description_raw = 'TRANSFER TO SAVINGS' BEGIN SELECT RAISE(ABORT, 'injected fault'); END")
    try:
        before = env.state()
        quiet = TestClient(env.app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False, headers=dict(env.client.headers))
        response = quiet.post(f"/api/documents/{doc['id']}/transaction-imports", json={"expected_hash": doc["current_hash"], "account_id": a, "reading_id": reading})
        assert response.status_code >= 500 and "Traceback" not in response.text and "injected" not in response.text
        assert env.state() == before and before[0]["transactions"] == 0 and before[0]["transaction_imports"] == 0 and before[0]["financial_evidence_links"] == 0
    finally:
        with env.store.connection() as db:
            db.execute("DROP TRIGGER fault")
    assert env.ok_import(doc, reading=reading, account_id=a)["inserted"] == 9


# --- SC-18: currency ---------------------------------------------------------------------------------------------------------

def test_sc18_a_document_in_another_currency_blocks_the_import(env):
    a = env.account("A")
    doc = env.add("keur.pdf", fx.keur_pages())
    preview = env.ok_preview(doc, account_id=a)
    assert "EUR" in preview["blocked"] and "USD" in preview["blocked"] and preview["document_currency"] == "EUR"
    before = env.state()
    response = env.run(doc, account_id=a, reading_id=preview["reading_id"])
    env.refused(response, preview["blocked"])
    assert env.state() == before


def test_sc18_18a_one_row_printed_in_another_currency_is_rejected_and_the_rest_import(env):
    a = env.account("A")
    doc = env.add("k18a.pdf", fx.k18a_pages())
    preview = env.ok_preview(doc, account_id=a)
    [k3] = [row for row in preview["rows"] if row["rejected"]]
    assert k3["description"] == "GROCERY MART" and "USD" in k3["rejected"] and preview["blocked"] is None
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert (result["inserted"], result["rejected"]) == (8, 1) and "GROCERY MART" not in [row[5] for row in ledger_rows(env, a)]


# --- The request model --------------------------------------------------------------------------------------------------------

def test_the_import_request_keeps_csv_and_pdf_choices_apart(env):
    a = env.account("A")
    pdf = env.add("k.pdf", fx.k_pages())
    csv = env.add("kc.csv", fx.kc_csv(), read=False)
    env.refused(env.preview(pdf, account_id=a, mapping={"date": "Date"}), "Column mapping applies to CSV and XLSX files.")
    env.refused(env.preview(csv, account_id=a, year=2025), "apply to PDF files only")
    env.refused(env.run(csv, account_id=a, sign="negative_is_outflow"), "apply to PDF files only")
    for body in ({"year": 1800}, {"reading_id": "not-a-reading"}, {"date_format": "YYYY"}, {"sign": "both"}, {"extra": 1}):
        assert env.preview(pdf, account_id=a, **body).status_code == 422
    assert env.ok_preview(csv, account_id=a)["counts"]["parsed"] == 9  # CSV bodies are unchanged.
    env.refused(env.run(pdf, account_id=a), "Preview this document again before importing it.")
    unread = env.add("unread.pdf", fx.m_pages(), read=False)  # A scanned page needs a model, so capture could not read it.
    env.refused(env.preview(unread, account_id=a), "Read this document first.")
    assert env.counts()["transactions"] == 0


# --- SC-06: a new account is created only together with a successful import --------------------------------------------------

NEW_C = {"institution": "Bank", "account_type": "credit_card", "currency": "USD", "display_name": "Synth card", "last_four": "7700"}


def failing_insert(env_, marker, body):
    """Run `body` with a permanent BEFORE INSERT trigger on transactions (the import's connection is its own, so a TEMP trigger would not be seen)."""
    with env_.store.connection() as db:
        db.execute(f"CREATE TRIGGER fault BEFORE INSERT ON transactions WHEN NEW.description_raw = '{marker}' BEGIN SELECT RAISE(ABORT, 'injected fault'); END")
    try:
        return body()
    finally:
        with env_.store.connection() as db:
            db.execute("DROP TRIGGER fault")


def test_sc06_a_new_account_is_created_only_together_with_a_successful_import(env):
    doc = env.add("r.pdf", fx.r_pages())
    # 1. Preview with no account: nothing is preselected and the one printed last four is offered for the new account.
    preview = env.ok_preview(doc)
    assert preview["account_match"] is None and preview["new_account_last_four"] == "7700" and preview["account_id"] is None
    assert env.counts()["accounts"] == 0
    reading = env.ok_preview(doc, year=2025, new_account=NEW_C)["reading_id"]  # A new account typed in full previews without creating it.
    assert env.counts()["accounts"] == 0
    body = {"year": 2025, "reading_id": reading, "new_account": NEW_C}
    # 2. A fault on the last row: the request fails without a trace, and no account, row, evidence or import is left.
    before = env.state()
    quiet = TestClient(env.app, base_url="http://127.0.0.1:8765", raise_server_exceptions=False, headers=dict(env.client.headers))

    def fails():
        return quiet.post(f"/api/documents/{doc['id']}/transaction-imports", json={"expected_hash": doc["current_hash"], **body})
    response = failing_insert(env, "RETURN BOOKSTORE", fails)
    assert response.status_code >= 500 and "Traceback" not in response.text and "injected" not in response.text
    assert env.state() == before and before[0]["accounts"] == 0 and before[0]["transactions"] == 0 and before[0]["financial_evidence_links"] == 0
    assert before[0]["transaction_imports"] == 0
    # 3. The same request with the fault removed imports all 5 rows into the one new account, with the card column's amounts.
    response = env.run(doc, **body)
    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["inserted"], result["duplicates"], result["account_name"]) == (5, 0, "Synth card")
    [(account_id, kind, last_four, currency, name)] = env.sql("SELECT id,account_type,account_last_four,currency,display_name FROM accounts")
    assert (kind, last_four, currency, name) == ("credit_card", "7700", "USD", "Synth card") and result["account_id"] == account_id
    rows = ledger_rows(env, account_id)
    assert [(row[0], row[1], row[2], row[3]) for row in rows] == [(posted, row[5], "integer", "import") for posted, row in zip(fx.R_POSTED_2025, fx.R_ROWS)]
    assert env.counts()["transaction_imports"] == 1 and counted(env, account_id) == 5
    concealed(env)
    # 4. A last four of six digits is refused as for the account route (422), and writes nothing.
    before = env.state()
    response = env.run(doc, year=2025, reading_id=reading, new_account={**NEW_C, "last_four": "123456"})
    assert response.status_code == 422 and env.state() == before


def test_sc06_a_new_account_that_would_not_be_created_writes_nothing(env):
    """Neither or both of account_id and new_account, a CSV with a new account, a different currency for an identical account."""
    a = env.account("A")
    doc = env.add("r.pdf", fx.r_pages())
    csv = env.add("kc.csv", fx.kc_csv(), read=False)
    k = env.add("k.pdf", fx.k_pages())
    reading, k_reading = env.ok_preview(doc, year=2025)["reading_id"], env.ok_preview(k)["reading_id"]
    before = env.state()
    env.refused(env.run(doc, year=2025, reading_id=reading), "Choose the account these transactions belong to.")
    env.refused(env.run(doc, year=2025, reading_id=reading, account_id=a, new_account=NEW_C), "Choose an existing account or a new one, not both.")
    env.refused(env.run(csv, new_account=NEW_C), "apply to PDF files only")
    env.refused(env.preview(csv, currency="USD", new_account=NEW_C), "apply to PDF files only")
    env.refused(env.run(k, reading_id=k_reading, new_account={"institution": "FIRST LOCAL BANK", "account_type": "checking", "currency": "EUR", "last_four": "4821"}),
                "This account already exists with a different currency.")
    assert env.state() == before


def test_sc06_6a_two_printed_last_fours_prefill_nothing(env):
    doc = env.add("k2.pdf", fx.k2_pages())
    preview = env.ok_preview(doc)
    assert preview["new_account_last_four"] is None and preview["account_match"] is None


def test_sc06_p6_a_new_account_identical_to_an_existing_one_is_reused(env):
    """Plan P6: no second account and no constraint error; the preview and the import both see the existing account's rows."""
    a = env.account("A")
    doc = env.add("k.pdf", fx.k_pages())
    same = {"institution": "FIRST LOCAL BANK", "account_type": "checking", "currency": "USD", "last_four": "4821"}
    first = env.ok_import(doc, new_account=same)
    assert (first["inserted"], first["account_id"], first["account_name"]) == (9, a, "FIRST LOCAL BANK checking 4821") and env.counts()["accounts"] == 1
    preview = env.ok_preview(doc, new_account=same)
    assert {row["status_text"] for row in preview["rows"]} == {"Already recorded from import k.pdf"} and preview["account_id"] == a
    again = env.ok_import(doc, reading=preview["reading_id"], new_account=same)
    assert (again["inserted"], again["duplicates"], again["account_id"]) == (0, 9, a) and env.counts()["accounts"] == 1 and len(ledger_rows(env, a)) == 9


def test_sc06_a_typed_new_account_gives_the_preview_its_sign_default_and_currency(env):
    doc = env.add("r.pdf", fx.r_pages())
    as_card = env.ok_preview(doc, year=2025, new_account=NEW_C)
    as_checking = env.ok_preview(doc, year=2025, new_account={**NEW_C, "account_type": "checking"})
    assert minor(as_card["rows"]) == [row[5] for row in fx.R_ROWS] and minor(as_checking["rows"]) == [row[6] for row in fx.R_ROWS]
    assert (as_card["totals"]["outflow_minor"], as_card["totals"]["inflow_minor"]) == fx.R_TOTALS_C
    assert (as_checking["totals"]["outflow_minor"], as_checking["totals"]["inflow_minor"]) == fx.R_TOTALS_A
    assert env.counts()["accounts"] == 0


# --- SC-10 and SC-11: rows that are already in the ledger ---------------------------------------------------------------------

def snapshot(env_, account_id):
    """What a PDF import must not change about a row it finds again."""
    return env_.sql("SELECT id,origin,category,category_source,review_status,review_source,statement_id,replaced_by,merchant_id FROM transactions WHERE account_id=? ORDER BY id", account_id)


def test_sc10_a_row_already_imported_from_csv_is_a_duplicate_with_a_new_evidence_link(env):
    a = env.account("A")
    kc = env.add("Kc.csv", fx.kc_csv(), read=False)
    assert csv_import(env, kc, a)["inserted"] == 9  # The CSV dialog's behaviour (SC-26 step 3).
    doc = env.add("K.pdf", fx.k_pages())
    rows_before, spent = snapshot(env, a), spending(env)
    links_before = env.sql("SELECT count(*) FROM financial_evidence_links")[0][0]
    preview = env.ok_preview(doc, account_id=a)
    assert {row["status_text"] for row in preview["rows"]} == {"Already recorded from import Kc.csv"} and preview["counts"]["new"] == 0
    assert (preview["totals"]["outflow_minor"], preview["totals"]["inflow_minor"]) == (0, 0)
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert (result["inserted"], result["duplicates"]) == (0, 9) and result["duplicate_sources"] == {"Already recorded from import Kc.csv": 9}
    assert env.sql("SELECT count(*),min(origin),max(origin) FROM transactions") == [(9, "import", "import")] and snapshot(env, a) == rows_before
    assert env.sql("SELECT count(*) FROM financial_evidence_links WHERE blob_hash=?", doc["current_hash"]) == [(9,)]
    assert env.sql("SELECT count(*) FROM financial_evidence_links")[0][0] == links_before + 9 and spending(env) == spent == K_SPENDING


def csv_import(env_, doc, account_id):
    response = env_.run(doc, account_id=account_id)
    assert response.status_code == 201, response.text
    return response.json()


def manual_in_a(env_, account_id, posted, description, amount):
    return env_.manager.ledger.add_manual_transaction(account_id, posted, description, amount, "out")


def test_sc10_10a_a_manual_entry_is_labelled_in_the_preview_and_replaced_after_the_import(env):
    a = env.account("A")
    doc = env.add("K.pdf", fx.k_pages())
    manual_in_a(env, a, "2026-08-05", "Groceries by hand", "45.10")
    [(manual_id,)] = env.sql("SELECT id FROM transactions WHERE origin='manual'")
    assert spending(env)[0] == 4510
    preview = env.ok_preview(doc, account_id=a)
    labelled = [(row["description"], row["status"]) for row in preview["rows"] if "replaces a manual entry" in row["labels"]]
    assert labelled == [("GROCERY MART", "new")] and preview["counts"]["new"] == 9
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert result["inserted"] == 9
    [(k3,)] = env.sql("SELECT id FROM transactions WHERE account_id=? AND description_raw='GROCERY MART'", a)
    assert env.sql("SELECT review_status,replaced_by FROM transactions WHERE id=?", manual_id) == [("rejected", k3)]
    assert env.sql(f"SELECT count(*) FROM transactions t WHERE {COUNTABLE} AND t.id=?", k3) == [(1,)]
    assert spending(env) == K_SPENDING  # 45.10 counts once.
    assert env.ok_preview(doc, account_id=a)["counts"]["already_recorded"] == 9


def test_sc10_10b_two_equal_new_rows_against_one_manual_entry_label_nothing_and_replace_nothing(env):
    """k1 and k2 are both -4.50 on 08-03: replace_manual would have two candidates, so the preview claims none (plan, pass-2 MJ-1)."""
    a = env.account("A")
    doc = env.add("K.pdf", fx.k_pages())
    manual_in_a(env, a, "2026-08-03", "Coffee by hand", "4.50")
    [(manual_id,)] = env.sql("SELECT id FROM transactions WHERE origin='manual'")
    preview = env.ok_preview(doc, account_id=a)
    assert [row for row in preview["rows"] if "replaces a manual entry" in row["labels"]] == []
    env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert env.sql("SELECT review_status,replaced_by FROM transactions WHERE id=?", manual_id) == [("verified", None)]
    assert counted(env, a) == 10 and spending(env)[0] == K_SPENDING[0] + 450  # Existing counting is unchanged: nothing is dropped by a guess.


def test_sc10_existing_matching_lines_count_as_candidates_so_the_preview_labels_nothing(env):
    """Two lines already match the manual entry, so replace_manual replaced nothing; k3 would be a third, and the preview claims nothing."""
    a = env.account("A")
    doc = env.add("K.pdf", fx.k_pages())
    manual_in_a(env, a, "2026-08-05", "Groceries by hand", "45.10")
    two = env.add("two.csv", b"Date,Description,Amount\n2026-08-04,GROCERY ONE,-45.10\n2026-08-06,GROCERY TWO,-45.10\n", read=False)
    assert csv_import(env, two, a)["inserted"] == 2
    assert env.sql("SELECT review_status,replaced_by FROM transactions WHERE origin='manual'") == [("verified", None)]
    preview = env.ok_preview(doc, account_id=a)
    assert [row for row in preview["rows"] if "replaces a manual entry" in row["labels"]] == [] and preview["counts"]["new"] == 9
    env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert env.sql("SELECT review_status,replaced_by FROM transactions WHERE origin='manual'") == [("verified", None)]  # Nothing replaced, as the preview said.


def test_sc11_a_statement_recorded_and_awaiting_reconciliation_is_not_duplicated(env):
    """Record is the double of the contract's fallback: `publish_statement(S-K, ..., "proposed")`."""
    a = env.account("A")
    doc = env.add("K.pdf", fx.k_pages())
    lines = list(zip(fx.K_POSTED, [r[7] for r in fx.K_ROWS], [r[3] for r in fx.K_ROWS]))
    published = env.manager.ledger.publish_statement(statement_of(lines), record_source(doc), "proposed")
    assert published["inserted"] == 9 and published["account_id"] == a
    assert env.sql("SELECT reconciliation FROM statements") == [("awaiting",)]
    assert env.sql("SELECT count(*),min(origin),max(origin) FROM transactions") == [(9, "extraction", "extraction")] and counted(env, a) == 0
    rows_before = snapshot(env, a)
    preview = env.ok_preview(doc, account_id=a)
    assert {row["status_text"] for row in preview["rows"]} == {"Already recorded from this statement; not counted until you reconcile it."}
    result = env.ok_import(doc, reading=preview["reading_id"], account_id=a)
    assert (result["inserted"], result["duplicates"]) == (0, 9) and snapshot(env, a) == rows_before and counted(env, a) == 0
    assert env.sql("SELECT count(*),min(origin),max(origin) FROM transactions") == [(9, "extraction", "extraction")]
    assert env.counts()["transaction_imports"] == 1
    assert env.sql("SELECT count(*) FROM financial_evidence_links WHERE source_key LIKE 'import:%'") == [(9,)]


# --- SC-26: CSV/XLSX import and the PDF status filters are unchanged ---------------------------------------------------------

def listed(env_, status):
    return {Path(item["relative_path"]).name for item in env_.client.get("/api/documents", params={"status": status}).json()["items"]}


def test_sc26_status_filters_for_pdfs_and_table_files(env):
    from home_manager.core.formats import TABLES  # Imported here: the module routes by extension and must not have changed.
    assert ".pdf" not in TABLES
    a = env.account("A")
    k = env.add("K.pdf", fx.k_pages())
    kc = env.add("Kc.csv", fx.kc_csv(), read=False)
    unread = env.add("unread.pdf", fx.m_pages(), read=False)
    assert listed(env, "ready_for_ledger") == {"K.pdf", "Kc.csv"} and listed(env, "needs_text") == {"unread.pdf"}
    # A CSV import with the dialog's remembered account behaves as before: the table file leaves "ready", and a PDF imported stays.
    assert csv_import(env, kc, a)["inserted"] == 9
    assert listed(env, "ready_for_ledger") == {"K.pdf"}
    assert env.ok_import(k, account_id=a)["duplicates"] == 9
    assert listed(env, "ready_for_ledger") == {"K.pdf"} and listed(env, "needs_text") == {"unread.pdf"} and unread
    # A PDF recorded as a statement is no longer ready (as before the feature).
    lines = list(zip(fx.K_POSTED, [r[7] for r in fx.K_ROWS], [r[3] for r in fx.K_ROWS]))
    env.manager.ledger.publish_statement(statement_of(lines), record_source(k), "proposed")
    assert listed(env, "ready_for_ledger") == set()
    assert env.fresh(k)["relative_path"].endswith(".pdf")


def test_sc10_manual_candidates_counts_stored_lines_and_the_lines_an_import_would_add(env):
    from home_manager.finance.reconcile import manual_candidates
    a = env.account("A")
    manual_in_a(env, a, "2026-08-05", "Groceries by hand", "45.10")
    extra = [{"key": "x", "posted_date": "2026-08-10", "amount_minor": -4510, "currency": "USD"},  # Five days after: inside the window.
             {"key": "y", "posted_date": "2026-08-11", "amount_minor": -4510, "currency": "USD"},  # Six days: outside.
             {"key": "z", "posted_date": "2026-08-05", "amount_minor": -4500, "currency": "USD"},  # Another amount.
             {"key": "w", "posted_date": "2026-08-05", "amount_minor": -4510, "currency": "EUR"}]  # Another currency.
    with env.store.connection() as db:
        manual = db.execute("SELECT * FROM transactions WHERE origin='manual'").fetchone()
        assert manual_candidates(db, manual) == [] and [line["key"] for line in manual_candidates(db, manual, extra)] == ["x"]
