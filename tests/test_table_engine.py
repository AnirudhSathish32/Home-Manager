"""The table engine, engine level (specs/pdf-table-engine/test-contract.md), slice SL-01: P-checks, tokens, columns and rows.

`pcheck_*` say each synthetic fixture has the shape the contract intends when the real reader reads it; `sc21_*` is the token table;
`rows_*` are the engine's rows for the fixtures (dates as printed tokens, descriptions, amount tokens per column, the columns found);
`sc14_*` is determinism with the network blocked and the model stub running. Expected values are the contract's, written out by
hand in tests/table_engine_fixtures.py. A failed P-check is a fixture or reader problem, never a reason to change an expected value.
No store and no model: every test reads a saved reading of a synthetic PDF.
"""

import ast
from dataclasses import asdict
from decimal import Decimal
import json
from pathlib import Path
import socket
from statistics import median

import pytest

from home_manager.documents import table_engine
from home_manager.documents.table_engine import PageView, read, read_tokens
from home_manager.finance import pdf_import
import pdf_import_fixtures as fx
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


@pytest.mark.xfail(strict=True, reason="Escalated in handoff SL-01: NB's column B holds one row (n1) and has no heading, so plan P4's two-row rule (FR-04) "
                                       "forms no column for it; the contract's NB expects it.")
def test_rows_nb_finds_two_amount_columns_without_headings(tmp_path):
    result, table = one_table(tmp_path, "NB")
    assert_columns(result, table, ["date", "text", "amount", "amount"], edges=(380, 460), aligns=["right"] * 2, labels=[[], []])
    assert_rows(table, tf.NB_ENGINE)


def test_rows_nb_column_a_alone_is_found_and_n1s_amount_forms_no_column(tmp_path):
    """What P4 does with NB today (see the xfail above): column A has two rows; n1's lone amount in B is no column and n1 is not a row."""
    result, table = one_table(tmp_path, "NB")
    assert [column.kind for column in table.columns] == ["date", "text", "amount"]
    assert [row[0] for row in printed_rows(table)] == [["11/05/2026"], ["11/18/2026"]]


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
