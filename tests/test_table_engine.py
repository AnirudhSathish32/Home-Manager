"""The table engine, engine level (specs/pdf-table-engine/test-contract.md), slices SL-01 - SL-03: P-checks, tokens, columns and rows,
then tables across pages, line classes (balance candidates, totals, summary anchors), unplaced lines and rejected rows (sc08 - sc10),
then the statement layer (`stmt_*`: roles, signs, period, date order, schedules, notes and issues; SC-01 - SC-07, SC-16, SC-17, SC-23 - SC-25).

`pcheck_*` say each synthetic fixture has the shape the contract intends when the real reader reads it; `sc21_*` is the token table;
`rows_*` are the engine's rows for the fixtures (dates as printed tokens, descriptions, amount tokens per column, the columns found);
`sc14_*` is determinism with the network blocked and the model stub running. Expected values are the contract's, written out by
hand in tests/table_engine_fixtures.py. A failed P-check is a fixture or reader problem, never a reason to change an expected value.
No store and no model: every test reads a saved reading of a synthetic PDF.
"""

import ast
from collections import Counter
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import re
import socket
import sqlite3
from statistics import median

import pytest

from home_manager.documents import table_engine
from home_manager.documents.table_engine import PageView, read, read_tokens
from home_manager.finance import pdf_import, statement_dates, statement_rows
from home_manager.finance import statement_tables as stt
import pdf_import_fixtures as fx
import statement_account_fixtures as sf
import table_engine_fixtures as tf


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
    pages = tf.FIXTURES[name]()
    result = fx.read_pdf(tmp_path, pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
    return result


def amount_columns(table):
    return [column for column in table.columns if column.kind == "amount"]


def printed_rows(table):
    """Per row: the printed date texts, the description and the printed amount text in each amount column, left to right."""
    columns = [column.id for column in amount_columns(table)]
    return [([date.text for date in row.dates], row.description, [row.amounts[column].text if column in row.amounts else "" for column in columns])
            for row in table.rows]


def serialized(value):
    return json.dumps(asdict(value), sort_keys=True, default=str)  # Decimal is the only value json can't write.


def scale_of(result, number=1):
    return fx.scale(fx.layout(result, number))


def words_with(result, number, texts):
    return [word for word in fx.layout(result, number).words if word.text in texts]


# === P-checks: the shape of each fixture ====================================================================================

@pytest.mark.parametrize("name", list(tf.FIXTURES))
def test_pcheck_every_page_is_native_text_and_the_reader_states_only_the_expected_layout_issues(tmp_path, name):
    result = reading_of(tmp_path, name)
    for number, page in enumerate(result.pages, 1):
        assert fx.nonspace(page.layout.raw_text) >= fx.MINIMUM_FOOTER
        issues = set(page.layout.issues)
        if name == "WF-flag":
            assert {"overlapping_text", "unsupported_text_rotation"} <= issues
        else:
            assert issues <= {"unresolved_columns"}, f"page {number}: {issues}"  # No table the old header rules know: the reader says so.


def test_pcheck_wf_prints_its_heading_on_two_visual_lines_and_the_old_header_rules_build_no_transactions_table(tmp_path):
    result = reading_of(tmp_path, "WF")
    assert fx.native_transactions_tables(result, 1) == []
    view = PageView(fx.layout(result, 1))
    rows = {text: view.row_of[word.id] for word in view.layout.words for text in ("Deposits/", "Additions") if word.text == text}
    assert rows["Additions"] - rows["Deposits/"] == 1
    below = [word for word in view.layout.words if view.row_of[word.id] >= 6]  # The six lines above come first.
    assert {view.row_of[word.id] for word in below if word.text in ("Check", "Ending", "daily")} == {rows["Deposits/"]}
    assert {view.row_of[word.id] for word in below if word.text in ("Date", "Number", "Description", "Subtractions", "balance")} == {rows["Additions"]}


def test_pcheck_wf_bare_prints_no_heading_word_below_its_lines_above(tmp_path):
    result = reading_of(tmp_path, "WF-bare")
    view = PageView(fx.layout(result, 1))
    below = [word.text for index in range(6, len(view.rows)) for word in view.rows[index]]
    assert not {"Date", "Number", "Description", "Check", "Additions", "Subtractions", "Deposits/", "Withdrawals/", "balance", "daily"} & set(below)
    assert len(view.rows) == 6 + 7 + 1  # The six lines above, seven rows and the footer.


def test_pcheck_dm_has_twenty_visual_lines_with_a_date_at_x_40(tmp_path):
    result = reading_of(tmp_path, "DM")
    layout = fx.layout(result, 1)
    scale = fx.scale(layout)
    view = PageView(layout)
    dated = [word for word in layout.words if word.text in {row[0] for row in tf.DM_ROWS} and view.row_of[word.id] >= 6]  # Below the six lines above.
    assert len(dated) == 20 and len({view.row_of[word.id] for word in dated}) == 20
    assert all(abs(fx.word_box(layout, word)[0] / scale - 40) <= 1.5 for word in dated)


def test_pcheck_wr_saves_each_continuation_line_as_its_own_visual_line(tmp_path):
    result = reading_of(tmp_path, "WR")
    layout = fx.layout(result, 1)
    printed = [text for row in tf.WR_ROWS for text in row[2]]
    assert len(printed) == 4
    for text in printed:
        assert [line.text for line in layout.lines].count(text) == 1


def test_pcheck_k3_draws_page_3_six_points_to_the_right_of_pages_1_and_2(tmp_path):
    result = reading_of(tmp_path, "K3")
    scale = scale_of(result)
    first_date = lambda number: min(fx.word_box(fx.layout(result, number), word)[0] for word in fx.layout(result, number).words if word.text.count("/") == 2)  # noqa: E731
    assert abs(first_date(1) - first_date(2)) < 0.5 * scale
    assert abs((first_date(3) - first_date(1)) / scale - 6) <= 0.5


def test_pcheck_k3_repeats_page_2s_heading(tmp_path):
    result = reading_of(tmp_path, "K3")
    heads = [page for page in (1, 2, 3) if any(word.text == "Withdrawals" for word in fx.layout(result, page).words)]
    assert heads == [1, 2]


@pytest.mark.parametrize("name, number, edges, texts", [
    ("WF", 1, tf.WF_EDGES, [[row[3] for row in tf.WF_ROWS], [row[4] for row in tf.WF_ROWS], [row[5] for row in tf.WF_ROWS]]),
    ("WF-bare", 1, tf.WF_BARE_EDGES, [[row[5] for row in tf.WF_ROWS], [row[4] for row in tf.WF_ROWS], [row[3] for row in tf.WF_ROWS]]),
    ("DM", 1, tf.DM_EDGES, [[row[2] for row in tf.DM_ROWS], [row[3] for row in tf.DM_ROWS], [row[4] for row in tf.DM_ROWS]]),
    ("CS", 1, (420,), [[row[3] for row in tf.CS_ROWS]]),
    ("TD", 1, (420,), [[row[3] for row in tf.TD_ROWS]]),
    ("NB", 1, (380,), [[row[2] for row in tf.NB_ROWS]]),
])
def test_pcheck_right_aligned_amounts_share_a_right_edge_within_half_a_point(tmp_path, name, number, edges, texts):
    result = reading_of(tmp_path, name)
    layout = fx.layout(result, number)
    scale = fx.scale(layout)
    for edge, column in zip(edges, texts):
        view = PageView(layout)
        printed = [word for word in layout.words if word.text in {text for text in column if text} and view.row_of[word.id] >= 5]  # Below the lines above.
        assert printed
        rights = [fx.word_box(layout, word)[2] / scale for word in printed]
        assert max(rights) - min(rights) <= 0.5
        assert abs(median(rights) - edge) <= 0.5


def test_pcheck_od_leaves_the_date_cell_of_rows_two_four_and_five_empty(tmp_path):
    result = reading_of(tmp_path, "OD")
    view = PageView(fx.layout(result, 1))
    dated = [index for index, row in enumerate(view.rows) if row[0].text.count("/") == 1]
    first = dated[0]
    assert [index - first for index in dated] == [0, 2, 5]
    assert [row[0].text for row in (view.rows[first + 1], view.rows[first + 3], view.rows[first + 4])] == ["BAKERY", "GROCERY", "PHARMACY"]


def test_pcheck_wr_split_prints_the_date_line_without_an_amount_and_the_memo_line_below_r7(tmp_path):
    result = reading_of(tmp_path, "WR-split")
    view = PageView(fx.layout(result, 1))
    texts = [" ".join(word.text for word in row) for row in view.rows]
    at = texts.index("11/25/2026 DEPOSIT SYNTH")
    assert texts[at + 1].startswith("MOBILE CHECK") and "250.00" in texts[at + 1] and "2,007.66" in texts[at + 1]
    assert texts[at + 2] == tf.WR_MEMO


def test_pcheck_up_prints_the_courtesy_amount_right_of_every_column(tmp_path):
    result = reading_of(tmp_path, "UP")
    layout = fx.layout(result, 1)
    scale = fx.scale(layout)
    word = next(word for word in layout.words if word.text == "35.00")
    assert abs(fx.word_box(layout, word)[0] / scale - tf.UP_X) <= 0.5
    assert max(fx.word_box(layout, other)[2] for other in layout.words if other.text in {row[4] for row in tf.B_ROWS}) < fx.word_box(layout, word)[0]


def test_pcheck_pr_page_2_is_prose_and_bl_page_2_is_a_schedule(tmp_path):
    (tmp_path / "pr").mkdir()
    (tmp_path / "bl").mkdir()
    prose = reading_of(tmp_path / "pr", "PR")
    assert prose.pages[1].layout.tables == []
    schedule = reading_of(tmp_path / "bl", "BL")
    assert [word.text for word in schedule.pages[1].layout.words if word.text.count("/") == 2] == ["09/15/2026", "10/15/2026"]


# === SC-21: tokens ==========================================================================================================

DATES = [  # (printed words of one run, expected (first, second, year, form))
    (["9/1"], (9, 1, None, "slash")), (["09/01"], (9, 1, None, "slash")), (["9/1/26"], (9, 1, 26, "slash")),
    (["09/01/2026"], (9, 1, 2026, "slash")), (["01/09/2026"], (1, 9, 2026, "slash")), (["09-01-2026"], (9, 1, 2026, "slash")),
    (["09.01.2026"], (9, 1, 2026, "slash")), (["2026-09-01"], (1, 9, 2026, "iso")),
    (["01", "Oct", "2026"], (1, 10, 2026, "month_name")), (["1-Oct-26"], (1, 10, 26, "month_name")), (["Oct", "1"], (1, 10, None, "month_name")),
    (["Oct", "01,", "2026"], (1, 10, 2026, "month_name")),
]
AMOUNTS = [  # (printed words, magnitude in minor units, marker, code)
    (["0.36"], 36, None, None), (["1,234.56"], 123456, None, None), (["$1,234.56"], 123456, None, "USD"), (["USD", "1,234.56"], 123456, None, "USD"),
    (["1,234.56", "USD"], 123456, None, "USD"), (["-12.00"], 1200, "minus", None), (["+12.00"], 1200, "plus", None), (["12.00-"], 1200, "minus", None),
    (["(12.00)"], 1200, "minus", None), (["12.00", "CR"], 1200, "credit", None), (["12.00", "DR"], 1200, "debit", None),
]
TEXTS = [["13/45"], ["1/2/3/4"], ["2026-13-01"], ["PPD", "ID", "1234567890"], ["SYNTH", "LONG", "DESCRIPTION12.34"]]


@pytest.mark.parametrize("words, expected", DATES, ids=[" ".join(words) for words, _ in DATES])
def test_sc21_a_printed_date_is_one_date_token(words, expected):
    tokens = read_tokens(words)
    assert [token.kind for token in tokens] == ["date"] and tokens[0].value == expected
    assert tokens[0].word_ids == [f"word-{index}" for index in range(len(words))]


@pytest.mark.parametrize("words, minor, marker, code", AMOUNTS, ids=[" ".join(words) for words, *_ in AMOUNTS])
def test_sc21_a_printed_amount_is_one_amount_token_with_its_magnitude_marker_and_code(words, minor, marker, code):
    tokens = read_tokens(words)
    assert [token.kind for token in tokens] == ["amount"]
    magnitude, found_marker, found_code = tokens[0].value
    assert isinstance(magnitude, Decimal) and magnitude * 100 == minor and (found_marker, found_code) == (marker, code)


@pytest.mark.parametrize("words", TEXTS, ids=[" ".join(words) for words in TEXTS])
def test_sc21_what_is_no_date_or_amount_stays_text(words):
    assert not [token for token in read_tokens(words) if token.kind in ("date", "amount")]


@pytest.mark.parametrize("word", ["1.234,56", "1.2.3"])
def test_sc21_a_decimal_comma_or_malformed_number_is_never_read_as_an_amount(word):
    (token,) = read_tokens([word])
    assert token.kind != "date" and not (token.kind == "amount" and token.value[0] is not None)  # An unreadable amount (G18), not a value.


def test_sc21_a_plain_integer_is_an_integer_token_until_an_amount_zone_claims_it():
    assert [(token.kind, token.value) for token in read_tokens(["1201", "12345"])] == [("integer", 1201), ("integer", 12345)]


# === Columns and rows =======================================================================================================

def one_table(tmp_path, name):
    result = reading_of(tmp_path, name)
    reading = read(result)
    assert reading.pages_without_tables == []
    assert len(reading.tables) == 1 and reading.tables[0].id == "page-1-table-1" and reading.tables[0].kind == "transactions"
    return result, reading.tables[0]


def assert_columns(result, table, kinds, edges=None, aligns=None, labels=None):
    assert [column.kind for column in table.columns] == kinds
    amounts = amount_columns(table)
    scale = scale_of(result)
    if edges:
        assert [round(column.edge / scale) for column in amounts] == list(edges)
        assert all(abs(column.edge / scale - edge) <= 0.5 for column, edge in zip(amounts, edges))
    if aligns:
        assert [column.align for column in amounts] == aligns
    if labels is not None:
        assert [column.labels for column in amounts] == labels
    zones = [column.zone for column in table.columns]
    assert all(left < right for left, right in zones) and all(a[1] == b[0] for a, b in zip(zones, zones[1:]))  # Zones tile the page left to right.


def assert_rows(table, expected, checks=None):
    rows = printed_rows(table)
    assert len(rows) == len(expected)
    for number, (row, want) in enumerate(zip(rows, expected), 1):
        if checks:
            assert checks(row, want), (number, row, want)
        else:
            assert row == want, number
    assert [row.row for row in table.rows] == list(range(1, len(expected) + 1))
    assert [row.page for row in table.rows] == [1] * len(expected)


def wf_description(row, want):
    """G8: where a check number goes is open; it is never an amount, and the description holds the printed words."""
    return row[0] == want[0] and want[1] in row[1] and row[1].replace(want[1], "").strip() in ("", "1201", "1202") and row[2] == want[2]


def test_rows_wf_two_line_heading_gives_date_description_and_three_amount_columns(tmp_path):
    result, table = one_table(tmp_path, "WF")
    assert_columns(result, table, ["date", "text", "amount", "amount", "amount"], edges=tf.WF_EDGES, aligns=["right"] * 3, labels=tf.WF_LABELS)
    assert table.columns[0].labels == ["Date"] and table.columns[1].labels == ["Check", "Number", "Description"]
    assert table.headings == ["Check Deposits/ Withdrawals/ Ending daily", "Date Number Description Additions Subtractions balance"]
    assert_rows(table, tf.WF_ENGINE, checks=lambda row, want: wf_description(row, want))
    for row, check in zip(table.rows, tf.WF_CHECKS):
        assert all(token.text != check or not check for token in row.amounts.values())  # A check number is never an amount.
        assert row.reject is None and row.carried_from is None and len(row.line_ids) == 1


def test_rows_wf_check_rows_hold_check_in_the_description_and_no_check_number_amount(tmp_path):
    _, table = one_table(tmp_path, "WF")
    checks = [row for row, number in zip(table.rows, tf.WF_CHECKS) if number]
    assert len(checks) == 2 and all("CHECK" in row.description for row in checks)
    assert [list(row.amounts.values())[0].text for row in checks] == ["150.00", "500.00"]


def test_rows_wf_bare_finds_the_same_rows_without_headings_and_with_the_columns_in_another_order(tmp_path):
    result, table = one_table(tmp_path, "WF-bare")
    assert_columns(result, table, ["date", "text", "amount", "amount", "amount"], edges=tf.WF_BARE_EDGES, aligns=["right"] * 3, labels=[[], [], []])
    assert table.headings == []
    assert_rows(table, tf.WF_BARE_ENGINE, checks=lambda row, want: row[0] == want[0] and want[1] in row[1] and row[2] == want[2])


def test_rows_wf_flag_reads_the_same_rows_on_a_flagged_page(tmp_path):
    _, table = one_table(tmp_path, "WF-flag")
    assert_rows(table, tf.WF_ENGINE, checks=lambda row, want: row[0] == want[0] and want[1] in row[1] and row[2] == want[2])


def test_rows_dm_gives_twenty_rows_with_the_dates_as_printed(tmp_path):
    result, table = one_table(tmp_path, "DM")
    assert_columns(result, table, ["date", "text", "amount", "amount", "amount"], edges=tf.DM_EDGES, aligns=["right"] * 3,
                   labels=[["Withdrawal Amt."], ["Deposit Amt."], ["Closing Balance"]])
    assert_rows(table, tf.DM_ENGINE)
    assert all(row.dates[0].value[3] == "slash" for row in table.rows)  # The order is not decided here: 01/10/2026 stays (1, 10, 2026).
    assert table.rows[0].dates[0].value == (1, 10, 2026, "slash") and table.rows[7].dates[0].value == (12, 10, 2026, "slash")


def test_rows_wr_joins_wrapped_description_lines_and_cites_every_line(tmp_path):
    result, table = one_table(tmp_path, "WR")
    assert_columns(result, table, ["date", "text", "amount", "amount", "amount"], aligns=["left"] * 3, labels=[["Withdrawals"], ["Deposits"], ["Balance"]])
    assert_rows(table, tf.WR_ENGINE)
    assert [len(row.line_ids) for row in table.rows] == tf.WR_LINES
    assert [len(row.word_ids) for row in table.rows][4] > [len(row.word_ids) for row in table.rows][3]
    assert all(row.reject is None and row.carried_from is None for row in table.rows)


def test_rows_od_gives_each_dateless_row_the_date_of_the_row_above_by_reference(tmp_path):
    result, table = one_table(tmp_path, "OD")
    assert_columns(result, table, ["date", "text", "amount", "amount", "amount"], aligns=["left"] * 3, labels=[["Withdrawals"], ["Deposits"], ["Balance"]])
    assert_rows(table, tf.OD_ENGINE)
    assert [row.carried_from for row in table.rows] == [None, (1, 1), None, (1, 3), (1, 3), None]
    assert [bool(row.dates) for row in table.rows] == [not row[7] for row in tf.OD_ROWS]
    assert all(row.reject is None for row in table.rows)


def test_rows_one_forms_its_columns_from_the_heading_alone(tmp_path):
    result, table = one_table(tmp_path, "ONE")
    assert_columns(result, table, ["date", "text", "amount"], aligns=["left"], labels=[["Withdrawals"]])
    assert_rows(table, tf.ONE_ENGINE)


def test_rows_nb_finds_two_amount_columns_without_headings(tmp_path):
    result, table = one_table(tmp_path, "NB")
    assert_columns(result, table, ["date", "text", "amount", "amount"], edges=(380, 460), aligns=["right"] * 2, labels=[[], []])
    assert_rows(table, tf.NB_ENGINE)


def test_rows_td_reads_two_date_columns_as_printed(tmp_path):
    result, table = one_table(tmp_path, "TD")
    assert_columns(result, table, ["date", "date", "text", "amount"], edges=(420,), aligns=["right"])
    assert_rows(table, tf.TD_ENGINE)
    assert [len(row.dates) for row in table.rows] == [2, 2, 2]
    assert [date.value for date in table.rows[0].dates] == [(9, 28, None, "slash"), (10, 1, None, "slash")]


def test_rows_td_bare_reads_the_same_two_date_columns_without_a_heading(tmp_path):
    result, table = one_table(tmp_path, "TD-bare")
    assert_columns(result, table, ["date", "date", "text", "amount"], edges=(420,), aligns=["right"], labels=[[]])
    assert_rows(table, tf.TD_ENGINE)


def test_rows_cs_reads_one_amount_column_and_leaves_the_signs_to_the_statement_layer(tmp_path):
    result, table = one_table(tmp_path, "CS")
    assert_columns(result, table, ["date", "text", "amount"], edges=(420,), aligns=["right"], labels=[["Amount"]])
    assert_rows(table, tf.CS_ENGINE)
    assert all(next(iter(row.amounts.values())).value[1] is None for row in table.rows)  # All unsigned, as printed.


def test_rows_fx_keeps_the_foreign_amount_and_rate_as_amount_tokens_in_their_own_columns(tmp_path):
    result, table = one_table(tmp_path, "FX")
    assert_columns(result, table, ["date", "text", "amount", "amount", "amount"], labels=[["Foreign amount"], ["Rate"], ["Amount"]])
    assert_rows(table, tf.FX_ENGINE)
    assert table.rows[0].amounts[amount_columns(table)[1].id].value[0] == Decimal("1.0850")  # The statement layer, not the engine, calls it `other` (R3).


def test_rows_a_page_with_no_dated_amount_lines_has_no_table(tmp_path):
    result = reading_of(tmp_path, "PR")
    reading = read(result)
    assert [table.id for table in reading.tables] == ["page-1-table-1"] and reading.pages_without_tables == [2]


def test_rows_pdf_import_re_exports_the_page_view_under_the_same_name():
    assert pdf_import.PageView is table_engine.PageView


def test_rows_the_engine_imports_nothing_from_finance():
    imported = [node.module or "" for node in ast.walk(ast.parse(Path(table_engine.__file__).read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom)]
    assert imported and not [module for module in imported if "finance" in module]


# === SC-14: determinism and no model calls ==================================================================================

@pytest.mark.parametrize("name", list(tf.FIXTURES))
def test_sc14_the_engine_run_twice_gives_byte_identical_output_with_no_model_call(tmp_path, local_model, name):
    result = reading_of(tmp_path, name)
    calls = len(local_model["requests"])
    first, second = read(result), read(result)
    assert serialized(first) == serialized(second)
    assert first.tables or first.pages_without_tables  # Something was said about every fixture.
    assert len(local_model["requests"]) == calls == 0


def test_sc14_a_reading_loaded_again_from_the_same_bytes_gives_the_same_output(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert serialized(read(reading_of(tmp_path / "a", "WR"))) == serialized(read(reading_of(tmp_path / "b", "WR")))


# === SL-02: tables across pages, line classes, unplaced lines and rejected rows =============================================

def read_pages(tmp_path, pages):
    """Any fixture's pages, read by the real reader with no model: every page is native text."""
    result = fx.read_pdf(tmp_path, pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
    return result


def sub(tmp_path, name):
    (tmp_path / name).mkdir()
    return tmp_path / name


DATE_WORD = re.compile(r"\d{1,2}/\d{1,2}(?:/\d{2,4})?")
AMOUNT_WORD = re.compile(r"-?\d[\d,]*\.\d{2}")


def dated_amount_lines(result, pages):
    """(page, visual row) of every printed line with a date word and an amount word, counted from the printed words and not from the engine."""
    found = set()
    for number in pages:
        for index, row in enumerate(fx.visual_rows(result, number)):
            words = [word.text for word in row]
            if any(DATE_WORD.fullmatch(word) for word in words) and any(AMOUNT_WORD.fullmatch(word) for word in words):
                found.add((number, index))
    return found


def accounted(result, reading):
    """(page, visual row) -> what accounts for the line: a row, a rejected row, an anchor, a total, another table's row or an unplaced line."""
    views = {number: PageView(page.layout) for number, page in enumerate(result.pages, 1)}
    found = {}

    def put(page, index, kind):
        assert found.setdefault((page, index), kind) == kind, (page, index, kind, found[(page, index)])

    def of_line(page, line_id):
        line = next(line for line in result.pages[page - 1].layout.lines if line.id == line_id)
        return views[page].row_of[line.word_ids[0]]

    for table in reading.tables:
        for row in table.rows:
            if row.candidate:
                continue  # Counted once, as the table's anchor.
            for index in {views[row.page].row_of[word_id] for word_id in row.word_ids}:
                put(row.page, index, "rejected" if row.reject else "row" if table.kind == "transactions" else "other")
        for anchor in table.anchors:
            put(anchor.page, of_line(anchor.page, anchor.line_id), "anchor")
        for total in table.totals:
            put(total.page, of_line(total.page, total.line_id), "total")
    for anchor in reading.summary_anchors:
        put(anchor.page, of_line(anchor.page, anchor.line_id), "anchor")
    for line in reading.unplaced:
        put(line.page, of_line(line.page, line.line_id), "unplaced")
    return found


def identity(result, reading):
    """How the date-and-amount lines on the table pages are accounted for (FR-08); every one must be."""
    lines = dated_amount_lines(result, sorted({page for table in reading.tables for page in table.pages}))
    found = accounted(result, reading)
    assert lines <= set(found), sorted(lines - set(found))
    return Counter(found[key] for key in lines)


# Hand counts from the contract's fixtures (each row of an expected table whose line holds a date and an amount; BL and UP and WF are the
# contract's own numbers). In SL-02 the schedule's two lines on BL's page 2 are rows of the table they continue: SL-03 moves them to
# "other" once the period is known, which makes the contract's 5 other-table rows.
IDENTITY = {
    "WF": {"row": 7, "anchor": 2}, "WF-bare": {"row": 7, "anchor": 2}, "WF-flag": {"row": 7, "anchor": 2}, "DM": {"row": 20}, "BRK": {"row": 20},
    "WR": {"row": 7}, "WR-split": {"row": 6}, "WR-above": {"row": 7}, "OD": {"row": 3}, "ONE": {"row": 1}, "CS": {"row": 6}, "NB": {"row": 4}, "K3": {"row": 9},
    "B": {"row": 3}, "BL": {"row": 5, "anchor": 2, "other": 3}, "UP": {"row": 3, "unplaced": 1}, "PR": {"row": 3}, "CC": {"row": 6}, "ND": {"row": 4},
    "ND-prior": {"row": 2}, "FX": {"row": 3}, "PD": {"row": 4}, "TD": {"row": 3}, "TD-bare": {"row": 3}, "OR": {"row": 4}, "CS-split": {"row": 5},
}


def test_sc10_every_fixture_has_hand_counts():
    assert set(IDENTITY) == set(tf.FIXTURES)


@pytest.mark.parametrize("name", list(IDENTITY))
def test_sc10_the_fr08_identity_holds_for_every_fixture_every_date_and_amount_line_is_accounted_for_once(tmp_path, name):
    result = reading_of(tmp_path, name)
    assert identity(result, read(result)) == Counter(IDENTITY[name])


def test_sc10_up_lists_the_courtesy_line_as_its_one_unplaced_line_quoting_its_text(tmp_path):
    result = reading_of(tmp_path, "UP")
    reading = read(result)
    (line,) = reading.unplaced
    assert (line.page, line.text, line.reason) == (1, "08/12/2026 SYNTH COURTESY CREDIT 35.00", "no_column")
    assert line.line_id in {layout_line.id for layout_line in result.pages[0].layout.lines}
    (table,) = reading.tables
    assert [row.description for row in table.rows] == [row[1] for row in tf.B_ROWS] and not any("35.00" in row.description for row in table.rows)
    assert all(token.text != "35.00" for row in table.rows for token in row.amounts.values())
    assert identity(result, reading) == Counter(row=3, unplaced=1) and sum(identity(result, reading).values()) == 4


def test_sc10_b_without_a_stray_line_has_no_unplaced_line(tmp_path):
    reading = read(reading_of(tmp_path, "B"))
    assert reading.unplaced == [] and [row.reject for row in reading.tables[0].rows] == [None] * 3


# --- SC-08: one table across three pages ------------------------------------------------------------------------------------

def test_sc08_k3_is_one_transactions_table_whose_rows_cite_pages_1_2_and_3(tmp_path):
    result = reading_of(tmp_path, "K3")
    reading = read(result)
    (table,) = reading.tables
    assert (table.id, table.kind, table.pages) == ("page-1-table-1", "transactions", [1, 2, 3])
    assert reading.pages_without_tables == [] and reading.unplaced == []
    assert [row.page for row in table.rows] == [1, 1, 1, 2, 2, 2, 3, 3, 3] and [row.row for row in table.rows] == [1, 2, 3] * 3
    assert {row.table_id for row in table.rows} == {table.id} and all(row.reject is None and row.carried_from is None for row in table.rows)
    assert printed_rows(table) == [([row[2]], row[3], [row[4], row[5], row[6]]) for row in fx.K_ROWS]  # Withdrawals, Deposits, Balance; page 2's heading is no row.
    assert [column.labels for column in amount_columns(table)] == [["Withdrawals"], ["Deposits"], ["Balance"]]
    assert table.headings == ["Date Description Withdrawals Deposits Balance"]
    scale = scale_of(result)
    assert abs((table.rows[6].dates[0].box[0] - table.rows[0].dates[0].box[0]) / scale - 6) <= 0.5  # Page 3 sits 6 pt to the right.


def test_sc08_k3_page_3_has_no_heading_and_its_utility_row_reads_its_withdrawal_in_the_column_page_1_found(tmp_path):
    result = reading_of(tmp_path, "K3")
    table = read(result).tables[0]
    withdrawals, deposits, balance = amount_columns(table)
    assert [list(row.amounts) for row in table.rows[6:]] == [[deposits.id, balance.id], [withdrawals.id, balance.id], [deposits.id, balance.id]]
    assert table.rows[7].description == "UTILITY CO"  # 82.40 is an amount, not description text.


def test_sc08_a_page_with_a_different_heading_starts_its_own_table_cc(tmp_path):
    reading = read(reading_of(tmp_path, "CC"))
    assert [(table.id, table.pages, len(table.rows)) for table in reading.tables] == [("page-1-table-1", [1], 3), ("page-2-table-1", [2], 3)]
    assert [len(amount_columns(table)) for table in reading.tables] == [3, 2]  # Withdrawals, Deposits, Balance; Amount, Balance.


def test_sc08_a_second_page_with_the_same_columns_and_no_heading_continues_nd(tmp_path):
    (table,) = read(reading_of(tmp_path, "ND")).tables
    assert table.pages == [1, 2] and [row.page for row in table.rows] == [1, 1, 2, 2]


# --- SC-09: balance lines, totals and other tables ------------------------------------------------------------------------------

def test_sc09_bl_balance_lines_are_candidates_totals_are_checks_and_the_daily_lines_a_balance_table(tmp_path):
    result = reading_of(tmp_path, "BL")
    reading = read(result)
    main, daily = reading.tables
    assert (main.id, main.kind, main.pages) == ("page-1-table-1", "transactions", [1, 2])
    assert (daily.id, daily.kind, daily.pages) == ("page-1-table-2", "balance", [1])
    candidates = [row for row in main.rows if row.candidate]
    assert [(row.row, row.candidate, row.description) for row in candidates] == [(1, "opening", "Beginning Balance"), (5, "closing", "Ending Balance")]
    assert [(a.page, a.kind, a.value, a.inside_table, a.dated) for a in main.anchors] == [
        (1, "opening", Decimal("1000.00"), True, True), (1, "closing", Decimal("2950.00"), True, True)]
    assert [a.line_id for a in main.anchors] == [row.line_ids[0] for row in candidates]
    withdrawals, deposits, _ = amount_columns(main)
    assert [(total.page, total.column_id, total.value) for total in main.totals] == [(1, withdrawals.id, Decimal("700.00")), (1, deposits.id, Decimal("2650.00"))]
    plain = [row for row in main.rows if not row.candidate]
    assert [(row.page, row.description) for row in plain] == [(1, row[1]) for row in tf.B_ROWS] + [(2, "SCHEDULED PAYMENT")] * 2  # SL-03 decides the schedule.
    assert [row.section for row in plain[3:]] == ["Payment schedule"] * 2
    assert printed_rows(daily) == [([date], "", [amount]) for date, amount in tf.BL_DAILY] and not any(row.description for row in daily.rows)
    assert all(row.reject is None for table in reading.tables for row in table.rows)
    assert reading.summary_anchors == [] and reading.unplaced == []
    assert not [row for table in reading.tables for row in table.rows if "fee" in row.description.lower()]  # The fee lines are no table's rows.
    assert identity(result, reading) == Counter(row=5, anchor=2, other=3)


def test_sc09_wf_dated_balance_lines_above_the_table_are_summary_anchors_not_unplaced_lines(tmp_path):
    reading = read(reading_of(tmp_path, "WF"))
    assert [(a.page, a.kind, a.value, a.inside_table, a.dated) for a in reading.summary_anchors] == [
        (1, "opening", Decimal("1000.00"), False, True), (1, "closing", Decimal("2113.45"), False, True)]
    assert reading.unplaced == [] and reading.tables[0].anchors == [] and not any(row.candidate for row in reading.tables[0].rows)


SUMMARY = {  # The contract's summary stubs: the printed opening (previous) and closing (new) balance lines above each table.
    "DM": ("10000.00", "33754.10"), "WR": ("500.00", "2007.66"), "OD": ("200.00", "437.85"), "CS": ("1250.00", "481.62"), "NB": ("100.00", "674.80"),
    "B": ("1000.00", "2950.00"), "PR": ("1000.00", "2947.50"), "FX": ("0.00", "210.00"), "PD": ("100.00", "145.00"),
    "TD": ("0.00", "439.25"), "ND-prior": ("100.00", "104.00"), "OR": ("100.00", "149.00"), "WF-bare": ("1000.00", "2113.45"), "WF-flag": ("1000.00", "2113.45"),
}


@pytest.mark.parametrize("name", list(SUMMARY))
def test_sc09_balance_lines_outside_every_table_are_summary_anchors_with_their_printed_values(tmp_path, name):
    reading = read(reading_of(tmp_path, name))
    assert [(a.kind, a.value) for a in reading.summary_anchors] == [("opening", Decimal(SUMMARY[name][0])), ("closing", Decimal(SUMMARY[name][1]))]
    assert all(not a.inside_table for a in reading.summary_anchors) and reading.unplaced == []


@pytest.mark.parametrize("name", ["K3", "ONE", "CC", "ND"])
def test_sc09_a_fixture_without_balance_lines_has_no_summary_anchor(tmp_path, name):
    assert read(reading_of(tmp_path, name)).summary_anchors == []


def test_sc09_a_balance_line_with_a_minus_sign_is_a_negative_anchor(tmp_path):
    items = tf.lines_above(("SYNTH MINUS BANK", "Beginning balance -25.00", "Ending balance (10.00)", "Statement period 08/01/2026 to 08/31/2026"))
    rows, y = tf.b_rows(680, tf.B_ROWS[:2])
    result = read_pages(tmp_path, [tf.native("SYNTH CHECKING BANK", items + tf.row_items(700, list(zip((40, 110, 330, 400, 470), tf.HEADING5))) + rows, y)])
    assert [(a.kind, a.value) for a in read(result).summary_anchors] == [("opening", Decimal("-25.00")), ("closing", Decimal("-10.00"))]


def test_rows_native_tables_no_engine_row_cites_are_listed_as_other(tmp_path):
    """Account-import-pdf SC-07's X: a summary table on page 1 and a fee table on page 3 are native tables the engine's rows don't cover."""
    result = read_pages(tmp_path, fx.x_pages())
    reading = read(result)
    named = [fx.layout(result, number).tables[index].id for number in (1, 3) for index, grid in enumerate(fx.native_grids(result, number))
             if grid[0][0] in ("Summary", "Fee summary")]
    assert len(named) == 2 and reading.other_native_tables == named
    (table,) = reading.tables
    assert (table.pages, [row.page for row in table.rows]) == ([1, 2], [1, 1, 2, 2]) and reading.pages_without_tables == [3]  # Page 2 has no heading.


# --- SC-03 (engine): a date line over its amount line; a dated line with no amount is rejected -------------------------------------

def test_rows_wr_split_cites_two_lines_in_one_row_and_the_memo_line_is_a_rejected_row_with_a_reason(tmp_path):
    result, table = one_table(tmp_path, "WR-split")
    assert printed_rows(table)[:6] == tf.WR_ENGINE[:6] and len(table.rows) == 8
    r7, memo = table.rows[6:]
    assert (r7.description, len(r7.line_ids), r7.reject) == ("DEPOSIT SYNTH MOBILE CHECK", 2, None)
    assert [token.text for token in r7.amounts.values()] == ["250.00", "2,007.66"] and [date.text for date in r7.dates] == ["11/25/2026"]
    assert (memo.page, memo.row, memo.description, len(memo.line_ids), memo.reject) == (1, 8, "SYNTH MEMO NOTICE", 1, "No amount is printed.")
    assert [date.text for date in memo.dates] == ["11/27/2026"] and memo.amounts == {}
    assert [row.reject for row in table.rows[:7]] == [None] * 7 and read(result).unplaced == []


# --- SC-15 / FR-16: statement-accounts X, T and T-edge ------------------------------------------------------------------------------

def test_rows_x_x1_is_a_row_x2_is_an_unplaced_line_and_x3_to_x6_are_rejected_with_pdf_imports_reasons(tmp_path):
    result = read_pages(tmp_path, sf.x_pages())
    reading = read(result, currency="USD")
    (table,) = reading.tables
    assert [(row.description, row.reject) for row in table.rows] == [
        ("GOOD", None), ("X3 REF", sf.X_REJECTED["x3"]), ("BADDATE", sf.X_REJECTED["x4"]), ("BADAMT", 'The amount "1.2.3" can\'t be read.'),
        ("EURO", 'The amount "4.00 EUR" is not in USD.')]
    assert [(line.page, line.text, line.reason) for line in reading.unplaced] == [(1, "09/03/2026 STRADDLE 100.00", "no_column")]  # x2: the amount straddles.
    assert [row.row for row in table.rows] == [1, 2, 3, 4, 5]
    assert table.rows[2].dates == [] and table.rows[2].carried_from is None  # x4's date is no date; it is not given the date above.
    assert identity(result, reading) == Counter(row=1, rejected=3, unplaced=1)  # x5's `1.2.3` is no amount word to the count, so five lines hold both.


def test_rows_x_the_reasons_are_the_old_readers_words(tmp_path):
    """FR-16: the same words as pdf_import's, row by row (x3 - x6)."""
    result = read_pages(tmp_path, sf.x_pages())
    legacy = pdf_import.analyze(result, currency="USD")
    assert [row.rejected for row in legacy.rows[2:]] == [row.reject for row in read(result, currency="USD").tables[0].rows[1:]]


def test_rows_x_a_foreign_code_is_kept_on_the_amount_token_when_no_currency_is_given(tmp_path):
    result = read_pages(tmp_path, sf.x_pages())
    euro = read(result).tables[0].rows[-1]
    assert euro.reject is None and next(iter(euro.amounts.values())).value == (Decimal("4.00"), None, "EUR")


def test_rows_t_t1s_amount_is_wholly_in_the_amount_zone_so_it_stays_an_amount(tmp_path):
    result = read_pages(tmp_path, sf.t_pages())
    reading = read(result)
    (table,) = reading.tables
    assert [row.description for row in table.rows] == [*sf.S_DESCRIPTIONS, "SYNTH LONG DESCRIPTION"] and all(row.reject is None for row in table.rows)
    amount = amount_columns(table)[0]
    assert [row.amounts[amount.id].text for row in table.rows] == [row[3] for row in sf.S_ROWS] + ["12.34"] and reading.unplaced == []


def test_rows_t_edge_t1_is_a_rejected_row_with_todays_reason_never_dropped(tmp_path):
    result = read_pages(tmp_path, sf.t_pages(edge=True))
    reading = read(result)
    (table,) = reading.tables
    t1 = table.rows[5]
    assert (t1.reject, t1.amounts, t1.description) == ("The amount is printed against the description, so it can't be told apart from it.", {}, "SYNTH LONG DESCRIPTION 12.34")
    assert [row.description for row in table.rows[:5]] == sf.S_DESCRIPTIONS and all(row.reject is None for row in table.rows[:5]) and reading.unplaced == []


def test_rows_a_blank_description_in_a_transactions_table_is_a_rejected_row(tmp_path):
    rows, y = tf.b_rows(680, [(row[0], "" if number == 1 else row[1], *row[2:]) for number, row in enumerate(tf.B_ROWS)])
    items = tf.lines_above(tf.B_ABOVE) + tf.row_items(700, list(zip((40, 110, 330, 400, 470), tf.HEADING5))) + rows
    table = read(read_pages(tmp_path, [tf.native("SYNTH CHECKING BANK", items, y)])).tables[0]
    assert [row.reject for row in table.rows] == [None, "The description is blank.", None]


def test_rows_text_that_is_not_an_amount_in_an_amount_column_is_a_rejected_row_with_todays_reason(tmp_path):
    rows, y = tf.b_rows(680)
    items = tf.lines_above(tf.B_ABOVE) + tf.row_items(700, list(zip((40, 110, 330, 400, 470), tf.HEADING5))) + rows + [(400, 680, "HOLD")]
    table = read(read_pages(tmp_path, [tf.native("SYNTH CHECKING BANK", items, y)])).tables[0]
    assert [row.reject for row in table.rows] == ["Text that is not an amount sits in the Deposits column.", None, None]


# --- Section titles (plan P4, P6) ---------------------------------------------------------------------------------------------

def test_section_titles_cs_rows_carry_payments_and_credits_then_purchases(tmp_path):
    _, table = one_table(tmp_path, "CS")
    assert [row.section for row in table.rows] == tf.CS_SECTIONS == ["Payments and Credits"] * 2 + ["Purchases"] * 4


def test_section_titles_pd_rows_carry_purchases_then_pending_transactions(tmp_path):
    _, table = one_table(tmp_path, "PD")
    assert [row.section for row in table.rows] == [row[0] for row in tf.PD_ROWS] == ["Purchases"] * 2 + ["Pending transactions"] * 2


def test_section_titles_a_table_with_no_title_has_no_section(tmp_path):
    assert {row.section for row in one_table(tmp_path, "WF")[1].rows} == {None}


def test_section_titles_carry_onto_the_continuation_page_until_another_title(tmp_path):
    reading = read(reading_of(tmp_path, "CS-split"))
    (table,) = reading.tables
    assert table.pages == [1, 2] and [row.section for row in table.rows] == tf.CSP_SECTIONS
    assert printed_rows(table) == tf.CSP_ENGINE and [row.page for row in table.rows] == [1, 1, 1, 2, 2]


@pytest.mark.parametrize("name", ["CS", "PD"])
def test_section_titles_a_footer_never_becomes_a_title(tmp_path, name):
    plain = read(reading_of(sub(tmp_path, "plain"), name)).tables[0]
    pages = tf.FIXTURES[name]()
    pages[0]["items"] += [(40, 120, "Pending transactions are shown on the next statement"), (40, 100, "Total fees this period")]
    result = read_pages(sub(tmp_path, "footer"), pages)
    reading = read(result)
    (table,) = reading.tables
    assert [row.section for row in table.rows] == [row.section for row in plain.rows] and printed_rows(table) == printed_rows(plain)
    assert reading.unplaced == [] and len(reading.tables) == 1 and not any("Pending" in row.description for row in table.rows[:2])


# --- One-row continuation page (plan P4) -----------------------------------------------------------------------------------------

def test_one_row_continuation_page_two_with_one_row_and_no_heading_continues_page_ones_table(tmp_path):
    result = reading_of(tmp_path, "OR")
    reading = read(result)
    (table,) = reading.tables
    assert (table.id, table.kind, table.pages) == ("page-1-table-1", "transactions", [1, 2]) and reading.pages_without_tables == []
    assert printed_rows(table) == tf.OR_ENGINE and [row.page for row in table.rows] == [1, 1, 1, 2] and [row.row for row in table.rows] == [1, 2, 3, 1]
    assert all(row.reject is None for row in table.rows) and reading.unplaced == []
    scale = scale_of(result)
    assert abs((table.rows[3].dates[0].box[0] - table.rows[0].dates[0].box[0]) / scale - tf.OR_SHIFT) <= 0.5


def test_one_row_continuation_that_page_alone_forms_no_columns(tmp_path):
    alone = read(read_pages(tmp_path, [tf.or_pages()[1]]))
    assert alone.tables == [] and alone.pages_without_tables == [1]


# --- Descriptions above their amounts (plan P5.7) -----------------------------------------------------------------------------------

def test_description_above_wr_above_reads_the_same_rows_as_wr_with_every_line_cited(tmp_path):
    result, table = one_table(tmp_path, "WR-above")
    assert_rows(table, tf.WR_ENGINE)
    assert [len(row.line_ids) for row in table.rows] == [lines + 1 for lines in tf.WR_LINES]  # Its description lines and its date line: WR's lines, plus the date line apart.
    assert all(row.reject is None and row.carried_from is None for row in table.rows)
    assert [column.labels for column in amount_columns(table)] == [["Withdrawals"], ["Deposits"], ["Balance"]]  # The heading is still found above the first description.
    view = PageView(fx.layout(result, 1))
    for number, row in enumerate(table.rows):
        visual = sorted({view.row_of[word_id] for word_id in row.word_ids})
        assert visual == list(range(visual[0], visual[0] + len(tf.WR_ROWS[number][2]) + 2))  # The description lines, then the date line, one after another.
        assert view.row_of[next(word.id for word in view.layout.words if word.id in row.word_ids and word.text == tf.WR_ROWS[number][0])] == visual[-1]


def test_description_above_is_not_used_when_the_first_date_line_has_the_heading_above_it(tmp_path):
    _, table = one_table(tmp_path, "WR")
    assert [len(row.line_ids) for row in table.rows] == tf.WR_LINES  # WR: its wrapped lines still join the row above.


# === SL-03: the statement layer (finance/statement_tables.py) =============================================================
# Expected values are the contract's, held in tests/table_engine_fixtures.py (WF_ROWS, DM_ROWS, ...). The engine reads each fixture's
# saved reading with no store and no model; a stub `prior_order` stands for OD-2's lookup.

CARDS = {"CS", "CS-split", "FX", "PD", "TD", "TD-bare"}
ONE_TABLE = "page-1-table-1"


def statement(tmp_path, name, pages=None, **options):
    result = read_pages(tmp_path, pages) if pages is not None else reading_of(tmp_path, name)
    return result, stt.read(result, statement_type="credit_card" if name in CARDS else "bank", currency="USD", **options)


def squashed(text):
    return " ".join(text.split())


def recorded(reading):
    return [(row["posted_date"], row["amount_minor"], squashed(row["description"])) for row in reading.rows]


def role_list(reading, table_id=ONE_TABLE):
    return list(reading.roles[table_id].values())


# --- SC-01 / SC-05: roles by the chain, with and without headings ----------------------------------------------------------------

@pytest.mark.parametrize("name, roles, balances", [
    ("WF", ["in", "out", "balance"], [300000, None, 276545, 156545, None, 111345, 211345]),
    ("WF-bare", ["balance", "out", "in"], [300000, None, 276545, 156545, None, 111345, 211345])])
def test_stmt_sc01_sc05_wf_roles_are_found_by_the_chain_with_or_without_headings(tmp_path, name, roles, balances):
    _, reading = statement(tmp_path, name)
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[6], row[7]) for row in tf.WF_ROWS]
    assert [text for _, _, text in recorded(reading)][0] == "PAYROLL SYNTH CO" and all("CHECK" in recorded(reading)[index][2] for index in (1, 5))
    assert role_list(reading) == roles and reading.decided == {"order": "day_over_12", "year": "period", "signs": {ONE_TABLE: "chain"}}
    assert (reading.opening_minor, reading.closing_minor, reading.period) == (100000, 211345, ("2026-10-01", "2026-10-31"))
    assert (reading.issues, reading.notes, reading.dropped, reading.pages) == ([], [], 0, {1})
    assert [row["amount_minor"] for row in reading.rows if row["amount_minor"] in (120100, 120200, -120100, -120200, *[abs(b) for b in balances if b])] == []
    assert [row["locator"]["balance_minor"] for row in reading.rows] == balances  # The printed balance rides on the row's locator.
    assert all(row["transaction_date"] is None and row["currency"] == "USD" for row in reading.rows)


def test_stmt_sc01_the_dated_summary_lines_are_the_statements_opening_and_closing_and_nothing_is_unplaced(tmp_path):
    result, reading = statement(tmp_path, "WF")
    (table,) = [table for table in reading.tables if table.kind == "transactions"]
    assert len(table.rows) == 2 + 5 and len(reading.summary_anchors) == 2 and reading.unplaced == []  # 7 rows + 2 anchors = 9 date-and-amount lines.
    assert [(anchor.kind, anchor.value) for anchor in reading.summary_anchors] == [("opening", Decimal("1000.00")), ("closing", Decimal("2113.45"))]


def test_stmt_sc01_wf_flag_reads_the_same_rows(tmp_path):
    _, plain = statement(tmp_path, "WF")
    flagged_dir = tmp_path / "flag"
    flagged_dir.mkdir()
    _, flagged = statement(flagged_dir, "WF-flag")
    assert recorded(flagged) == recorded(plain)


# --- SC-02 / SC-06 a: day-first dates, and one broken link ------------------------------------------------------------------------

def test_stmt_sc02_dm_reads_day_first_because_a_day_is_over_12(tmp_path):
    _, reading = statement(tmp_path, "DM")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[5], row[6]) for row in tf.DM_ROWS]
    assert reading.order == "DD/MM/YYYY" and reading.decided["order"] == "day_over_12" and reading.decided["year"] == "printed"
    assert not {posted for posted, _, _ in recorded(reading)} & {"2026-01-10", "2026-02-10", "2026-03-10", "2026-05-10", "2026-06-10", "2026-08-10", "2026-12-10"}
    assert (reading.issues, reading.dropped) == ([], 0) and role_list(reading) == ["out", "in", "balance"]
    assert (reading.opening_minor, reading.closing_minor) == (1000000, 3375410)


def test_stmt_sc06_a_brk_one_chain_issue_names_row_14_and_its_recorded_value_is_79700(tmp_path):
    _, reading = statement(tmp_path, "BRK")
    expected = [(row[5], row[6]) for row in tf.DM_ROWS]
    expected[tf.BRK_ROW] = tf.BRK_EXPECTED
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == expected
    assert reading.issues == ["Page 1 row 14: the balance 31,165.10 doesn't follow from the row above"]
    assert reading.decided["signs"] == {ONE_TABLE: "chain_most"} and role_list(reading) == ["out", "in", "balance"]  # Tier b': the most holding links.


# --- SC-03 / SC-04: wrapped rows, carried dates --------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["WR", "WR-above"])
def test_stmt_sc03_wr_descriptions_are_whole(tmp_path, name):
    _, reading = statement(tmp_path, name)
    assert recorded(reading) == [(row[8], row[7], row[6]) for row in tf.WR_ROWS]
    assert (reading.issues, reading.notes, reading.dropped) == ([], [], 0)
    assert [len(row["locator"]["line_ids"]) for row in reading.rows][4:] == [2 + (name == "WR-above"), 3 + (name == "WR-above"), 2 + (name == "WR-above")]


def test_stmt_sc03_wr_split_records_r1_to_r7_and_lists_the_memo_line_as_a_rejected_row(tmp_path):
    _, reading = statement(tmp_path, "WR-split")
    assert recorded(reading) == [(row[8], row[7], row[6]) for row in tf.WR_ROWS]
    assert len(reading.rows[6]["locator"]["line_ids"]) == 2
    assert reading.issues == ["Page 1 row 8: No amount is printed."] and reading.dropped == 1 and "2026-11-27" not in {row["posted_date"] for row in reading.rows}


def test_stmt_sc04_od_carried_dates_come_with_three_notes_and_no_review_reason(tmp_path):
    _, reading = statement(tmp_path, "OD")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[5], row[6]) for row in tf.OD_ROWS]
    assert reading.decided["order"] == "period" and reading.order == "MM/DD/YYYY"  # Every day is <= 12; day-first falls outside December.
    assert reading.issues == [] and reading.dropped == 0
    assert len(reading.notes) == 3
    for note, (row, date) in zip(reading.notes, [(2, "12/03/2026"), (4, "12/05/2026"), (5, "12/05/2026")]):
        assert note == f"Page 1 row {row}: no date is printed; it takes {date} from the row above"
    assert [row["locator"]["row"] for row in reading.rows] == [1, 2, 3, 4, 5, 6]


# --- SC-06 b: one row, no summary -------------------------------------------------------------------------------------------------

def test_stmt_sc06_b_one_row_takes_its_sign_from_the_heading_and_says_why_it_needs_review(tmp_path):
    _, reading = statement(tmp_path, "ONE")
    assert recorded(reading) == [("2026-09-15", -2500, "SYNTH SERVICE FEE")] and reading.decided["signs"] == {ONE_TABLE: "labels"}
    assert reading.issues == ["Page 1: the signs of these rows come from the column headings or the statement type, because there are too few rows "
                              "and no printed summary to check them."]
    assert (reading.opening_minor, reading.closing_minor) == (None, None) and reading.period == ("2026-09-01", "2026-09-30")


# --- SC-07: signs from the summary and from sections --------------------------------------------------------------------------------

def test_stmt_sc07_cs_signs_come_from_the_sections_and_the_card_check_holds(tmp_path):
    _, reading = statement(tmp_path, "CS")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[4], row[5]) for row in tf.CS_ROWS]
    assert reading.decided["signs"] == {ONE_TABLE: "summary"} and role_list(reading) == ["signed"] and reading.issues == []
    assert (reading.opening_minor, reading.closing_minor) == (125000, 48162)  # Previous 1,250.00, new 481.62.


def test_stmt_sc07_cs_split_sections_carry_onto_the_next_page_and_no_summary_says_why(tmp_path):
    _, reading = statement(tmp_path, "CS-split")
    assert [amount for _, amount, _ in recorded(reading)] == [50000, -12040, -5218, -1599, -300]  # Payments in; purchases and fees out.
    assert len(reading.issues) == 1 and reading.issues[0].startswith("Page 1: the signs of these rows come from the column headings")


def test_stmt_sc07_nb_the_summary_decides_which_column_is_money_out(tmp_path):
    _, reading = statement(tmp_path, "NB")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[4], row[5]) for row in tf.NB_ROWS]
    assert role_list(reading) == ["out", "in"] and reading.decided["signs"] == {ONE_TABLE: "summary"} and reading.issues == []


def test_stmt_sc07_nb_without_its_summary_lines_nothing_is_decided_by_chain_or_summary_and_no_row_is_guessed(tmp_path):
    _, reading = statement(tmp_path, "NB", pages=tf.nb_pages(summary=False))
    assert reading.decided["signs"][ONE_TABLE] not in ("chain", "summary") and reading.rows == [] and reading.issues and reading.dropped == 4
    assert reading.roles[ONE_TABLE] == {}


# --- SC-08 / SC-09 / SC-10: pages, balance lines, schedules, unplaced lines ------------------------------------------------------------

def test_stmt_sc08_k3_is_one_table_whose_rows_cite_three_pages(tmp_path):
    result, reading = statement(tmp_path, "K3")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == list(zip(fx.K_POSTED, [row[7] for row in fx.K_ROWS]))
    assert [amount for _, amount, _ in recorded(reading)] == [-450, -450, -4510, 200000, -50000, -500, 1999, -8240, 12]
    assert [row["locator"]["page"] for row in reading.rows] == [1, 1, 1, 2, 2, 2, 3, 3, 3] and reading.pages == {1, 2, 3}
    assert [table.pages for table in reading.tables] == [[1, 2, 3]] and reading.issues == [] and reading.unplaced == []
    assert {row["locator"]["table_id"] for row in reading.rows} == {ONE_TABLE}


def test_stmt_sc09_bl_the_balance_lines_are_anchors_the_daily_lines_a_balance_table_and_the_schedule_other_rows(tmp_path):
    _, reading = statement(tmp_path, "BL")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [("2026-08-03", -70000), ("2026-08-15", 250000), ("2026-08-20", 15000)]
    assert (reading.opening_minor, reading.closing_minor) == (100000, 295000) and reading.issues == [] and reading.dropped == 0
    kinds = {table.id: table.kind for table in reading.tables}
    assert sorted(kinds.values()) == ["balance", "schedule", "transactions"]
    transactions = next(table for table in reading.tables if table.kind == "transactions")
    assert [(anchor.kind, anchor.value) for anchor in transactions.anchors] == [("opening", Decimal("1000.00")), ("closing", Decimal("2950.00"))]
    assert [total.value for total in transactions.totals] == [Decimal("700.00"), Decimal("2650.00")]
    schedule = next(table for table in reading.tables if table.kind == "schedule")
    daily = next(table for table in reading.tables if table.kind == "balance")
    other_rows = len(schedule.rows) + len(daily.rows)
    plain = [row for row in transactions.rows if not row.candidate]
    assert (len(plain), len(transactions.anchors), other_rows, len(reading.unplaced)) == (3, 2, 5, 0)  # FR-08: 3 rows + 0 rejected + 2 anchors + 5 other + 0 unplaced = 10.
    assert [token.text for row in schedule.rows for token in row.dates] == ["09/15/2026", "10/15/2026"] and reading.pages == {1}
    assert not {row["posted_date"] for row in reading.rows} & {"2026-09-15", "2026-10-15"}


def test_stmt_sc09_without_a_printed_period_nothing_is_a_schedule(tmp_path, monkeypatch):
    """FR-09 as settled in D6: with no period the dates decide nothing (account-import-pdf 7-a unchanged)."""
    monkeypatch.setattr(tf, "B_ABOVE", (*tf.B_ABOVE[:4], "Account statement for August"))
    _, reading = statement(tmp_path, "BL")
    assert reading.period is None and sorted(table.kind for table in reading.tables) == ["balance", "transactions"]
    assert [(posted, amount) for posted, amount, _ in recorded(reading)][3:] == [("2026-09-15", -12500), ("2026-10-15", -12500)]  # Rows, as before the schedule rule.


def test_stmt_sc10_up_the_courtesy_line_is_one_unplaced_issue_and_not_a_row(tmp_path):
    _, reading = statement(tmp_path, "UP")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [("2026-08-03", -70000), ("2026-08-15", 250000), ("2026-08-20", 15000)]
    assert reading.issues == ['Page 1: a printed line wasn\'t placed in any column, so it wasn\'t recorded: "08/12/2026 SYNTH COURTESY CREDIT 35.00"']
    assert reading.dropped == 1 and [line.reason for line in reading.unplaced] == ["no_column"] and 3500 not in {row["amount_minor"] for row in reading.rows}


def test_stmt_sc11_a_page_with_no_table_gets_its_note_and_is_not_an_engine_page(tmp_path):
    _, reading = statement(tmp_path, "PR")
    assert reading.notes == ["Page 2: no table was found in the printed columns, so its rows are the reading's; check them."] and reading.pages == {1}


# --- FR-16: rejections that need the roles ------------------------------------------------------------------------------------------

def test_stmt_fr16_a_row_with_both_a_debit_and_a_credit_is_rejected(tmp_path):
    both = tf.b_pages(extra=[[(40, "08/25/2026"), (110, "BOTH SYNTH"), (330, "5.00"), (400, "5.00")]])
    _, reading = statement(tmp_path, "B", pages=both)
    assert [amount for _, amount, _ in recorded(reading)] == [-70000, 250000, 15000]
    assert reading.issues == ["Page 1 row 4: Both a debit and a credit are printed."] and reading.dropped == 1


def test_stmt_fr16_too_much_precision_rejects_a_row_only_in_a_money_column(tmp_path):
    extra = tf.b_pages(extra=[[(40, "08/25/2026"), (110, "PRECISE SYNTH"), (330, "5.001")]])
    _, reading = statement(tmp_path, "B", pages=extra)
    assert [amount for _, amount, _ in recorded(reading)] == [-70000, 250000, 15000] and reading.issues == ['Page 1 row 4: The amount "5.001" can\'t be read.']


def test_stmt_fr16_x_rejections_and_the_unplaced_line_are_listed_with_todays_reasons(tmp_path):
    result = read_pages(tmp_path, sf.x_pages())
    reading = stt.read(result, statement_type="bank", currency="USD")
    assert recorded(reading) == [("2026-09-02", 1000, "GOOD")]
    assert reading.issues[:4] == ["Page 1 row 2: More than one amount sits in the Amount column.", 'Page 1 row 3: The date "02/30/2026" is not a real date.',
                                  'Page 1 row 4: The amount "1.2.3" can\'t be read.', 'Page 1 row 5: The amount "4.00 EUR" is not in USD.']
    assert reading.issues[-1] == 'Page 1: a printed line wasn\'t placed in any column, so it wasn\'t recorded: "09/03/2026 STRADDLE 100.00"'
    assert reading.dropped == 5


# --- SC-17: two chains that don't join ---------------------------------------------------------------------------------------------

def test_stmt_sc17_cc_two_tables_are_both_recorded_with_one_two_accounts_issue_and_no_chain_issue(tmp_path):
    _, reading = statement(tmp_path, "CC")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[5], row[6]) for row in tf.CC_ROWS]
    assert reading.issues == ["This PDF may hold more than one account: the table on page 1 and the table on page 2 don't continue each other's "
                              "balances. Both tables' rows were recorded."]
    assert reading.decided["signs"] == {"page-1-table-1": "chain", "page-2-table-1": "chain"}
    assert [role_list(reading, "page-1-table-1"), role_list(reading, "page-2-table-1")] == [["out", "in", "balance"], ["signed", "balance"]]


def test_stmt_sc17_one_table_that_continues_its_own_balances_raises_no_two_accounts_issue(tmp_path):
    _, reading = statement(tmp_path, "K3")
    assert not any("more than one account" in issue for issue in reading.issues)


# --- SC-16: dates whose order can't be told, and OD-2 --------------------------------------------------------------------------------

def test_stmt_sc16_a_nd_records_nothing_and_says_so_once_per_page(tmp_path):
    _, reading = statement(tmp_path, "ND")
    assert reading.rows == [] and reading.order is None and reading.dropped == 4
    assert reading.issues == ["Page 1 rows: the date order (month/day or day/month) can't be told from the printed dates.",
                              "Page 2 rows: the date order (month/day or day/month) can't be told from the printed dates."]


def test_stmt_sc16_b_nd_follows_the_order_prior_order_gives_for_the_account(tmp_path):
    calls = []
    _, reading = statement(tmp_path, "ND", prior_order=lambda: calls.append(1) or "DD/MM/YYYY")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == tf.ND_EXPECTED_DAY_FIRST
    assert reading.issues == [] and reading.decided["order"] == "prior" and reading.order == "DD/MM/YYYY" and len(calls) == 1


def test_stmt_sc16_c_a_prior_order_that_finds_nothing_leaves_nd_undecided(tmp_path):
    _, reading = statement(tmp_path, "ND", prior_order=lambda: None)
    assert reading.rows == [] and len(reading.issues) == 2


def test_stmt_sc16_a_printed_day_over_12_or_the_period_never_asks_prior_order(tmp_path):
    def forbidden():
        raise AssertionError("prior_order was asked although the printed dates decide")
    for name in ("DM", "WF", "OD"):
        sub_dir = tmp_path / name
        sub_dir.mkdir()
        statement(sub_dir, name, prior_order=forbidden)


def test_stmt_sc16_the_user_choice_decides_only_where_the_printed_dates_cannot(tmp_path):
    _, chosen = statement(tmp_path, "ND", choices={"date_format": "DD/MM/YYYY"})
    assert [(posted, amount) for posted, amount, _ in recorded(chosen)] == tf.ND_EXPECTED_DAY_FIRST and chosen.decided["order"] == "choice"
    other = tmp_path / "dm"
    other.mkdir()
    _, dm = statement(other, "DM", choices={"date_format": "MM/DD/YYYY"})
    assert dm.order == "DD/MM/YYYY"


def test_stmt_sc16_the_order_decision_without_od2_reads_nd_prior_day_first_and_nd_not_at_all(tmp_path):
    prior = read_pages(tmp_path, tf.nd_prior_pages())
    other = tmp_path / "nd"
    other.mkdir()
    ambiguous = read_pages(other, tf.nd_pages())
    assert (stt.decided_order(prior), stt.decided_order(ambiguous)) == ("DD/MM/YYYY", None)


def _prior_database(tmp_path, rows):
    """The tables prior_order reads, with the columns the library schema gives them (migrations/050_strict_tables.sql), loose-typed."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("CREATE TABLE accounts (id INTEGER PRIMARY KEY, account_last_four TEXT);"
                     "CREATE TABLE parse_runs (id TEXT PRIMARY KEY, parser_version TEXT, status TEXT, result_json TEXT);"
                     "CREATE TABLE extraction_runs (id TEXT PRIMARY KEY, parse_run_id TEXT);"
                     "CREATE TABLE statements (id INTEGER PRIMARY KEY, account_id INTEGER, document_id INTEGER, extraction_run_id TEXT, period_end TEXT);")
    for number, (last_four, document, period_end, pages, version, status) in enumerate(rows, 1):
        folder = tmp_path / f"prior-{number}"
        folder.mkdir()
        read_pages(folder, pages)
        db.execute("INSERT INTO accounts VALUES (?,?)", (number, last_four))
        db.execute("INSERT INTO parse_runs VALUES (?,?,?,?)", (f"p{number}", version, status, (folder / "result.json").read_text(encoding="utf-8")))
        db.execute("INSERT INTO extraction_runs VALUES (?,?)", (f"e{number}", f"p{number}"))
        db.execute("INSERT INTO statements VALUES (?,?,?,?,?)", (number, number, document, f"e{number}", period_end))
    return db


def test_stmt_sc16_prior_order_reads_the_newest_other_statement_of_the_account_that_decides(tmp_path):
    from home_manager.documents.pdf_reader import PDF_VERSION
    db = _prior_database(tmp_path, [("7788", 11, "2026-02-28", tf.nd_prior_pages(), PDF_VERSION, "succeeded"),
                                    ("7788", 12, "2026-03-31", tf.nd_pages(), PDF_VERSION, "succeeded"),  # Newer, but its dates decide nothing.
                                    ("7799", 13, "2026-04-30", tf.nd_prior_pages(), PDF_VERSION, "succeeded")])
    assert stt.prior_order(db, "7788", 99) == "DD/MM/YYYY"
    assert stt.prior_order(db, "7788", 11) is None  # Its own document is never its own prior; the other ND decides nothing.
    assert stt.prior_order(db, "7799", 99) == "DD/MM/YYYY" and stt.prior_order(db, "0000", 99) is None and stt.prior_order(db, None, 99) is None


def test_stmt_sc16_prior_order_ignores_readings_that_are_not_pdf_pages_or_failed(tmp_path):
    db = _prior_database(tmp_path, [("7788", 11, "2026-02-28", tf.nd_prior_pages(), "receipt-ocr-v1", "succeeded"),
                                    ("7788", 12, "2026-03-31", tf.nd_prior_pages(), "pdf-pages-v1", "failed")])
    assert stt.prior_order(db, "7788", 99) is None


# --- R3, R4, R5: foreign amounts, pending rows, two dates ----------------------------------------------------------------------------

def test_stmt_sc23_fx_the_foreign_amount_and_rate_columns_are_other_and_never_money(tmp_path):
    _, reading = statement(tmp_path, "FX")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[5], row[6]) for row in tf.FX_ROWS]
    assert role_list(reading) == ["other", "other", "signed"] and reading.issues == [] and reading.decided["signs"] == {ONE_TABLE: "summary"}
    assert not {9217, 3850, 10850, 12987, -9217, -3850} & {row["amount_minor"] for row in reading.rows}


def test_stmt_sc23_fx_a_rate_that_cannot_be_read_does_not_reject_the_row(tmp_path, monkeypatch):
    rows = [(*row[:3], "1.2.3" if row[3] else "", *row[4:]) for row in tf.FX_ROWS]
    monkeypatch.setattr(tf, "FX_ROWS", rows)
    _, reading = statement(tmp_path, "FX")
    assert [amount for _, amount, _ in recorded(reading)] == [-10000, -5000, -6000] and reading.issues == []


def test_stmt_sc24_pd_pending_rows_are_not_recorded_and_each_is_one_issue(tmp_path):
    _, reading = statement(tmp_path, "PD")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [("2026-10-05", -3000), ("2026-10-18", -1500)]
    assert reading.issues == ['Page 1: a pending row isn\'t recorded until it posts: "10/30 SYNTH HOTEL 200.00"',
                              'Page 1: a pending row isn\'t recorded until it posts: "10/31 SYNTH TAXI 12.50"']
    assert [line.reason for line in reading.unplaced] == ["pending", "pending"] and reading.dropped == 2 and reading.decided["signs"] == {ONE_TABLE: "summary"}
    assert reading.pages == {1}


@pytest.mark.parametrize("name", ["TD", "TD-bare"])
def test_stmt_sc25_two_date_columns_are_the_transaction_date_and_the_posted_date(tmp_path, name):
    _, reading = statement(tmp_path, name)
    assert [(row["transaction_date"], row["posted_date"], row["amount_minor"]) for row in reading.rows] == [(row[4], row[5], row[6]) for row in tf.TD_ROWS]
    assert reading.issues == [] and reading.decided["signs"] == {ONE_TABLE: "summary"}


# --- The shapes Record and PDF import will read ---------------------------------------------------------------------------------------

def test_stmt_as_rebuild_is_the_old_rebuild_shape_plus_opening_closing_and_period(tmp_path):
    _, reading = statement(tmp_path, "WF")
    rebuild = reading.as_rebuild()
    assert isinstance(rebuild, statement_dates.Rebuild) and rebuild.available and rebuild.pages == {1} and rebuild.dropped == 0
    assert (rebuild.opening_minor, rebuild.closing_minor, rebuild.period) == (100000, 211345, ("2026-10-01", "2026-10-31"))
    assert rebuild.rows == reading.rows and set(rebuild.rows[0]) == {"posted_date", "transaction_date", "description", "currency", "amount_minor", "locator"}
    locator = rebuild.rows[1]["locator"]
    assert set(locator) == {"rebuilt", "page", "table_id", "row", "balance_minor", "line_ids", "word_ids", "cell_ids", "quotes"}
    assert (locator["rebuilt"], locator["page"], locator["table_id"], locator["row"], locator["balance_minor"]) == (True, 1, ONE_TABLE, 2, None)
    assert len(locator["quotes"]) == len(locator["line_ids"]) == 1 and "CHECK" in locator["quotes"][0] and isinstance(locator["cell_ids"], list)


def test_stmt_a_reading_without_a_layout_is_unavailable_with_the_old_note(tmp_path):
    result = reading_of(tmp_path, "WF")
    result.pages[0].layout = None
    reading = stt.read(result, statement_type="bank", currency="USD")
    assert reading.available is False and reading.notes == [statement_dates.NO_LAYOUT_NOTE] and reading.rows == [] and stt.engine_pages(result) == set()


@pytest.mark.parametrize("name, pages", [("WF", {1}), ("BL", {1}), ("PR", {1}), ("K3", {1, 2, 3}), ("PD", {1}), ("CC", {1, 2})])
def test_stmt_engine_pages_are_the_pages_holding_a_transactions_tables_rows(tmp_path, name, pages):
    result = reading_of(tmp_path, name)
    assert stt.engine_pages(result) == pages


def test_stmt_the_moved_helpers_are_the_same_objects_statement_rows_exports_and_statement_dates_imports_no_pdf_import():
    for name in ("Rebuild", "read_period", "placed", "duplicates", "PERIOD_SLACK"):
        assert getattr(statement_rows, name) is getattr(statement_dates, name)
    tree = ast.parse(Path(statement_dates.__file__).read_text(encoding="utf-8"))
    imported = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {alias.name for node in ast.walk(tree)
                                                                                                      if isinstance(node, ast.Import) for alias in node.names}
    assert not any("pdf_import" in name or "statement_rows" in name or "statement_tables" in name for name in imported)
    rebuild = statement_dates.Rebuild(True)
    assert (rebuild.opening_minor, rebuild.closing_minor, rebuild.period) == (None, None, None)


def test_stmt_sc14_the_statement_reading_is_the_same_twice_for_every_fixture(tmp_path):
    for name in tf.FIXTURES:
        folder = tmp_path / name
        folder.mkdir()
        result = reading_of(folder, name)
        kind = "credit_card" if name in CARDS else "bank"
        first, second = (stt.read(result, statement_type=kind, currency="USD") for _ in range(2))
        assert serialized(first) == serialized(second), name
        assert json.dumps(first.rows, sort_keys=True) == json.dumps(second.rows, sort_keys=True)


def test_stmt_engine_tables_are_not_changed_by_the_statement_layer(tmp_path):
    """The statement layer works on copies: the engine's own reading of the same document is byte-identical before and after."""
    result = reading_of(tmp_path, "BL")
    before = serialized(read(result))
    stt.read(result, statement_type="bank", currency="USD")
    assert serialized(read(result)) == before


# --- FR-12 markers, FR-14 period fallbacks and years ---------------------------------------------------------------------------------

@pytest.mark.parametrize("marked", [("1,000.00 CR", "45.00 CR"), ("-1,000.00", "-45.00"), ("(1,000.00)", "(45.00)")])
def test_stmt_fr12_a_rows_own_marker_marks_a_credit_on_a_card(tmp_path, monkeypatch, marked):
    rows = [(*row[:3], marked[number], *row[4:]) if number < 2 else row for number, row in enumerate(tf.CS_ROWS)]
    monkeypatch.setattr(tf, "CS_ROWS", rows)
    _, reading = statement(tmp_path, "CS")
    assert [(posted, amount) for posted, amount, _ in recorded(reading)] == [(row[4], row[5]) for row in tf.CS_ROWS]  # The contract's CS values.
    assert reading.issues == [] and reading.decided["signs"] == {ONE_TABLE: "summary"}


def test_stmt_fr14_the_models_period_is_used_only_when_none_is_printed(tmp_path, monkeypatch):
    monkeypatch.setattr(tf, "WF_ABOVE", tf.WF_ABOVE[:-1])
    _, none = statement(tmp_path, "WF")
    assert none.rows == [] and none.period is None and len(none.issues) == 7 and all("no year is printed and the statement period wasn't read" in issue for issue in none.issues)
    other = tmp_path / "fallback"
    other.mkdir()
    _, fallback = statement(other, "WF", fallback_period=("2026-10-01", "2026-10-31"))
    assert [(posted, amount) for posted, amount, _ in recorded(fallback)] == [(row[6], row[7]) for row in tf.WF_ROWS]
    assert fallback.period is None and fallback.decided["year"] == "period"  # The printed period is what is reported; the fallback only places dates.
    chosen = tmp_path / "choice"
    chosen.mkdir()
    _, choice = statement(chosen, "WF", choices={"year": 2026})
    assert [(posted, amount) for posted, amount, _ in recorded(choice)] == [(row[6], row[7]) for row in tf.WF_ROWS] and choice.decided["year"] == "choice"


def test_stmt_fr14_a_printed_period_wins_over_the_models(tmp_path):
    _, reading = statement(tmp_path, "WF", fallback_period=("2025-01-01", "2025-01-31"))
    assert reading.period == ("2026-10-01", "2026-10-31") and recorded(reading)[0][0] == "2026-10-02"
