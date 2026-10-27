"""Record's rows from the printed columns (specs/statement-accounts/test-contract.md), module level.

This file holds SL-01's checks: the P-checks that say each synthetic fixture has the shape the contract intends when the real
reader reads it (`pcheck_*`), the rows `finance/statement_rows.rebuild` gives for each fixture (`rows_*`), FR-30's change to
`pdf_import.visual_row` (`sc27`, `sc28`, `fr30_edge`) and the stubs. Expected values are the contract's, written out in
tests/statement_account_fixtures.py by hand. A failed P-check is a fixture or reader problem, never a reason to change an
expected value.
"""

import json

from home_manager.core.jobs import Work
from home_manager.documents.extraction import ExtractionService
from home_manager.documents.layout_context import native_page
from home_manager.documents.pdf_reader import read_result
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance import pdf_import, statement_rows
from home_manager.finance.ledger import Ledger
from home_manager.finance.statement_rows import NO_LAYOUT_NOTE, rebuild, rebuilt_pages
import pdf_import_fixtures as fx
import statement_account_fixtures as sf
from test_pdf import capture, make_pdf, pdf_store  # noqa: F401
from test_pdf_imports import env, no_network, opened  # noqa: F401  (the autouse C-net guard, and the API environment of PDF import)

SEPTEMBER = ("2026-09-01", "2026-09-30")
NO_AMOUNT = "The amount is printed against the description, so it can't be told apart from it."


def read(tmp_path, pages):
    """The fixture, read by the real reader with no model: every page is native text."""
    result = fx.read_pdf(tmp_path, pages)
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
    for number in range(1, len(pages) + 1):
        assert fx.nonspace(result.pages[number - 1].layout.raw_text) >= fx.MINIMUM_FOOTER
    return result


def rows_of(built):
    return [(row["posted_date"], row["amount_minor"], row["description"]) for row in built.rows]


def bank(result, period=SEPTEMBER):
    return rebuild(result, statement_type="bank", period_start=period[0], period_end=period[1], currency="USD")


def expected_s():
    return list(zip(sf.S_POSTED, sf.S_AMOUNTS, sf.S_DESCRIPTIONS))


def analysis(result, sign="negative_is_outflow", **choices):
    return pdf_import.analyze(result, currency="USD", sign=sign, **choices)


def box_of(result, text, occurrence=-1):
    """A word's box in preview units, from the saved layout (the last occurrence by default)."""
    layout = fx.layout(result, 1)
    return [fx.word_box(layout, word) for word in layout.words if word.text == text][occurrence]


def heading_titles(result):
    """For every table that has a heading: (page, table kind, whether the visual row directly above the heading names a balance)."""
    found = []
    for entry in statement_rows.Reading(result).entries:
        if entry.spec is not None and entry.table.kind != "continuation":
            view = statement_rows.PageView(fx.layout(result, entry.table.page))
            heading = statement_rows.heading_row(view, entry.top)
            found.append((entry.table.page, entry.table.kind, statement_rows.title_names_balance(view, heading)))
    return found


def last_row_of_page(result, number=1):
    """The visual row of the page's last t1-like row: the one holding `12.34`."""
    view = pdf_import.PageView(fx.layout(result, number))
    return next(index for index, row in enumerate(view.rows) if any(word.text == "12.34" for word in row)), view


# === P-checks: the shape of each fixture ====================================================================================

def test_pcheck_s_is_one_native_page_with_a_native_table_and_no_layout_issue(tmp_path):
    result = read(tmp_path, sf.s_pages())
    assert fx.layout(result, 1).issues == [] and fx.page_issue_codes(result, 1) == []
    assert native_page(result.pages[0]) is True
    assert fx.native_transactions_tables(result, 1) == [[list(sf.HEADING4), *[[date, description, amount, balance] for _, date, description, amount, balance, _ in sf.S_ROWS]]]
    assert [text for text, _, _ in fx.texts(result, 1, fx.heading_rows(result, 1)[0])] == list(sf.HEADING4)


def test_pcheck_s_flag_raises_overlapping_text_and_unsupported_text_rotation_and_is_not_native(tmp_path):
    result = read(tmp_path, sf.s_flag_pages())
    assert {"overlapping_text", "unsupported_text_rotation"} <= set(fx.layout(result, 1).issues)
    assert native_page(result.pages[0]) is False and fx.layout(result, 1).tables == []
    assert "pdf_layout_review" in fx.page_issue_codes(result, 1)
    view = pdf_import.PageView(fx.layout(result, 1))
    assert sum(1 for index in range(len(view.rows)) if pdf_import.is_heading([text for text, _, _ in view.texts(index)])) == 1  # One heading: S's.


def test_pcheck_s_flag_s_and_s2_print_the_contracts_lines_with_the_period_last_and_s2_a_different_last_four(tmp_path):
    for name, pages, account in (("s", sf.s_pages(), "000009000123456"), ("s2", sf.s2_pages(), "000009000127890")):
        directory = tmp_path / name
        directory.mkdir()
        result = read(directory, pages)
        printed = [line.text for line in fx.layout(result, 1).lines]
        assert sorted(printed[:6]) == sorted(["SYNTH BANK", "SYNTH SAVINGS", f"Account Number {account}", "Beginning Balance 0.00", "Ending Balance 1,000.00",
                                              "Statement period 09/01/2026 through 09/30/2026"])  # The contract's lines, none added or removed.
        assert printed[5].startswith("Statement period")


def test_pcheck_title_lines_name_no_balance_except_ds_daily_table(tmp_path):
    cases = {"s": sf.s_pages(), "sflag": sf.s_flag_pages(), "s2": sf.s2_pages(), "w": sf.w_pages(), "c": sf.c_pages(), "c0": sf.c0_pages(),
             "t": sf.t_pages(), "x": sf.x_pages(), "q": sf.q_pages()}
    for name, pages in cases.items():
        directory = tmp_path / name
        directory.mkdir()
        titles = heading_titles(read(directory, pages))
        assert titles and not [title for title in titles if title[2]], (name, titles)
    for name, pages in (("d", sf.d_pages()), ("dflag", sf.d_pages(True))):
        directory = tmp_path / name
        directory.mkdir()
        titles = heading_titles(read(directory, pages))
        assert [title[2] for title in titles] == [False], (name, titles)  # S's table is kept; the daily table's title is in pcheck_d.


def test_pcheck_t_t1s_amount_is_joined_to_its_description_wholly_in_the_amount_span_and_its_only_amount(tmp_path):
    result = read(tmp_path, sf.t_pages())
    assert {"overlapping_text", "unsupported_text_rotation"} <= set(fx.layout(result, 1).issues)
    index, view = last_row_of_page(result)
    assert [text for text, _, _ in view.texts(index)] == ["09/22", "SYNTH LONG DESCRIPTION 12.34"]  # In one PageView.texts run.
    heading = pdf_import.make_spec(view.texts(next(i for i in range(len(view.rows)) if pdf_import.is_heading([t for t, _, _ in view.texts(i)]))))
    amount = heading.columns["amount"]
    box = view.box[next(word.id for word in view.rows[index] if word.text == "12.34")]
    assert heading.spans[amount][0] <= box[0] and box[2] <= heading.spans[amount][1]  # Wholly inside the Amount span, no tolerance.
    centred = [word.text for word in view.rows[index] if pdf_import.AMOUNT_WORD.fullmatch(word.text)
               and any(heading.spans[column][0] <= (view.box[word.id][0] + view.box[word.id][2]) / 2 < heading.spans[column][1]
                       for column in (amount,))]
    assert centred == ["12.34"]  # The only amount-shaped word centred in an amount column.
    first = view.box[view.rows[index][1].id]
    assert pdf_import.place(heading.spans, first)[0] == heading.columns["description"]  # SYNTH is placed in the Description column.
    assert (first[0] + first[2]) / 2 < heading.spans[amount][0]


def test_pcheck_t_edge_amount_starts_left_of_the_midpoint_by_less_than_20_percent_but_is_centred_in_the_amount_span(tmp_path):
    result = read(tmp_path, sf.t_pages(edge=True))
    index, view = last_row_of_page(result)
    heading = pdf_import.make_spec(view.texts(next(i for i in range(len(view.rows)) if pdf_import.is_heading([t for t, _, _ in view.texts(i)]))))
    amount, description = heading.columns["amount"], heading.columns["description"]
    word = next(word for word in view.rows[index] if word.text == "12.34")
    box = view.box[word.id]
    midpoint = heading.spans[amount][0]
    assert box[0] < midpoint and midpoint - box[0] < (box[2] - box[0]) * 0.2  # Starts left of the midpoint, by less than 20% of its width,
    assert midpoint <= (box[0] + box[2]) / 2 < heading.spans[amount][1]  # its centre stays in the Amount span,
    previous = view.box[view.rows[index][-2].id]
    assert box[0] - previous[2] <= view.size * 1.5  # the gap to DESCRIPTION is under 1.5 font sizes,
    assert pdf_import.place(heading.spans, box) == (amount, True)  # and today's `place` says it fits, through the 20% allowance.
    assert pdf_import.place(heading.spans, view.box[view.rows[index][1].id])[0] == description
    assert not heading.spans[amount][0] <= box[0]  # So it is not wholly inside the Amount span: FR-30 (a) fails.


def test_pcheck_d_the_daily_table_is_its_own_heading_under_a_title_that_names_a_balance(tmp_path):
    for name, pages in (("d", sf.d_pages()), ("dflag", sf.d_pages(True))):
        directory = tmp_path / name
        directory.mkdir()
        result = read(directory, pages)
        view = pdf_import.PageView(fx.layout(result, 1))
        headings = [index for index in range(len(view.rows)) if pdf_import.is_heading([text for text, _, _ in view.texts(index)])]
        assert len(headings) == 2 and [text for text, _, _ in view.texts(headings[1])] == ["Date", "Amount"]
        assert [text for text, _, _ in view.texts(headings[1] - 1)] == ["DAILY ENDING BALANCE"]
        assert statement_rows.cut_at(view, headings[0] + 1) == (headings[1] - 1, True)  # The section cut is the title, a balance section.
        assert (name == "dflag") == ("overlapping_text" in fx.layout(result, 1).issues)


def test_pcheck_q_has_two_tables_one_on_each_page_and_the_same_line_in_both(tmp_path):
    result = read(tmp_path, sf.q_pages())
    reading = statement_rows.Reading(result)
    assert [(entry.table.page, entry.table.kind) for entry in reading.entries if entry.spec] == [(1, "transactions"), (2, "rebuilt")]
    [first] = fx.native_transactions_tables(result, 1)
    assert first == [list(sf.HEADING3), list(sf.Q_CHECK)]
    assert fx.texts(result, 1, fx.visual_rows(result, 1)[2])[0][0] == "CHECKS PAID"


def test_pcheck_x_the_rows_sit_as_the_contract_places_them(tmp_path):
    result = read(tmp_path, sf.x_pages())
    view = pdf_import.PageView(fx.layout(result, 1))
    heading = next(i for i in range(len(view.rows)) if pdf_import.is_heading([t for t, _, _ in view.texts(i)]))
    spec = pdf_import.make_spec(view.texts(heading))
    amount = spec.columns["amount"]
    by_text = {row[1].text: row for row in view.rows}
    straddle = view.box[next(word.id for word in by_text["STRADDLE"] if word.text == "100.00")]
    assert pdf_import.touches(spec.spans[amount], straddle) and pdf_import.place(spec.spans, straddle)[1] is False  # x2 crosses the Amount/Balance midpoint.
    x3 = {word.text: view.box[word.id] for word in by_text["X3"]}
    assert all(spec.spans[amount][0] <= (x3[text][0] + x3[text][2]) / 2 < spec.spans[amount][1] for text in ("REF", "55.55", "5.00"))  # REF 55.55 beside 5.00.
    assert any(text.startswith("REF 55.55") for text, _, _ in view.texts(view.row_of[by_text["X3"][0].id]))  # REF and 55.55 are one run.
    got = analysis(result)
    assert [(row.rejected is None) for row in got.rows] == [True, False, False, False, False, False]


def test_pcheck_m_page_one_is_s_native_and_page_two_is_read_once_by_the_vision_stub(pdf_store, local_model):  # noqa: F811
    source, store = pdf_store
    make_pdf(source / "m.pdf", sf.m_pages())
    doc = capture(source, store)
    local_model["output"] = {"full_text": "SCANNED PAGE\n09/27 SCANNED CAFE 7.00"}
    service = ReceiptService(store)
    run_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(run_id, Work("inference", "transcription", "PDF", sink=store.record_model_run))
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    assert [page["method"] for page in run["result"]["pages"]] == ["embedded_text", "vision_model"]
    assert len(local_model["requests"]) == 1
    result = read_result(run["result"])
    requests = len(local_model["requests"])
    built = bank(result)
    assert rows_of(built) == expected_s() and built.pages == {1}  # No rebuilt row cites page 2.
    assert len(local_model["requests"]) == requests  # The rebuild makes no model call.


# === Rows from the printed columns ==========================================================================================

def test_rows_s_native_table_gives_s1_to_s5_with_the_year_from_the_period(tmp_path):
    built = bank(read(tmp_path, sf.s_pages()))
    assert built.available and built.pages == {1} and built.issues == [] and built.notes == [] and built.dropped == 0
    assert rows_of(built) == expected_s()
    assert [row["currency"] for row in built.rows] == ["USD"] * 5 and all(isinstance(row["amount_minor"], int) for row in built.rows)
    assert all(row["transaction_date"] is None and row["locator"]["rebuilt"] for row in built.rows)


def test_rows_s_flag_has_no_native_table_and_still_gives_s1_to_s5_and_no_balance_value(tmp_path):
    built = bank(read(tmp_path, sf.s_flag_pages()))
    assert rows_of(built) == expected_s() and built.issues == [] and built.dropped == 0
    assert not {38, 0} & {row["amount_minor"] for row in built.rows}  # No row holds s2's balance (0.38) or s3's (0.00).


def test_rows_locators_hold_the_line_word_and_cell_ids_and_one_quote_per_line(tmp_path):
    result = read(tmp_path, sf.s_pages())
    built = bank(result)
    lines = {line.id: line.text for line in fx.layout(result, 1).lines}
    for row in built.rows:
        locator = row["locator"]
        assert locator["page"] == 1 and locator["line_ids"] and len(locator["quotes"]) == len(locator["line_ids"])
        assert locator["quotes"] == [lines.get(line_id, "") for line_id in locator["line_ids"]]
        assert locator["cell_ids"] and set(locator["cell_ids"]) <= {cell.id for table in fx.layout(result, 1).tables for cell in table.cells}
    again = tmp_path / "flag"
    again.mkdir()
    result = read(again, sf.s_flag_pages())
    built = bank(result)
    words = {word.id: word.text for word in fx.layout(result, 1).words}
    for row, expected in zip(built.rows, sf.S_ROWS):
        locator = row["locator"]
        assert locator["word_ids"] and locator["cell_ids"] == [] and locator["table_id"] == "page-1-import-table-1"
        assert expected[1] in [words[word_id] for word_id in locator["word_ids"]]


def test_rows_w_withdrawals_and_deposits_keep_their_own_sign_and_no_balance_is_recorded(tmp_path):
    result = read(tmp_path, sf.w_pages())
    built = rebuild(result, statement_type="bank", period_start="2026-08-01", period_end="2026-08-31", currency="USD")
    assert [row["amount_minor"] for row in built.rows] == sf.W_AMOUNTS == [-120000, 250000, 15000]
    assert [row["posted_date"] for row in built.rows] == ["2026-08-03", "2026-08-15", "2026-08-20"] and built.issues == []
    assert rows_of(rebuild(result, statement_type="credit_card", period_start="2026-08-01", period_end="2026-08-31", currency="USD"))[0][1] == -120000  # Debit and Credit columns ignore the sign.


def test_rows_w_prime_and_w_second_prime_move_every_date_by_one_and_two_months(tmp_path):
    for shift, month, end in ((1, "09", "2026-09-30"), (2, "10", "2026-10-31")):
        directory = tmp_path / month
        directory.mkdir()
        built = rebuild(read(directory, sf.w_pages(shift)), statement_type="bank", period_start=f"2026-{month}-01", period_end=end, currency="USD")
        assert [row["posted_date"] for row in built.rows] == [f"2026-{month}-03", f"2026-{month}-15", f"2026-{month}-20"]
        assert [row["amount_minor"] for row in built.rows] == sf.W_AMOUNTS and built.issues == []


def test_rows_c_card_charges_are_money_out_and_the_year_crosses_the_year_end(tmp_path):
    built = rebuild(read(tmp_path, sf.c_pages()), statement_type="credit_card", period_start="2025-12-15", period_end="2026-01-14", currency="USD")
    assert [(row["posted_date"], row["amount_minor"]) for row in built.rows] == [(row[4], row[5]) for row in sf.C_ROWS]
    assert [row["amount_minor"] for row in built.rows] == [-1999, 25000, -3820] and built.issues == []


def test_rows_c0_without_a_period_records_nothing_and_lists_every_row_with_page_row_and_the_missing_year(tmp_path):
    built = rebuild(read(tmp_path, sf.c0_pages()), statement_type="credit_card", period_start=None, period_end=None, currency="USD")
    assert built.rows == [] and built.pages == {1} and built.dropped == 3
    for number, row in enumerate(sf.C_ROWS, 1):
        assert built.issues[number - 1] == f"Page 1 row {number}: no year is printed and the statement period wasn't read, so the date {row[1]} can't be placed."


def test_rows_a_printed_year_that_disagrees_with_the_period_and_an_impossible_date_are_rejected(tmp_path):
    cells = [("09/02/26", "PLACED", "1.00", ""), ("09/03/25", "WRONGYEAR", "2.00", ""), ("02/29/26", "NOTREAL", "3.00", "")]
    result = read(tmp_path, [sf.page(sf.X_ABOVE, cells, sf.COLUMNS4, sf.HEADING4, "SYNTH BANK")])
    built = bank(result)
    assert [(row["posted_date"], row["amount_minor"]) for row in built.rows] == [("2026-09-02", 100)]
    assert len(built.issues) == 2 and 'disagrees with the statement period' in built.issues[0] and "is not a real date" in built.issues[1]
    assert built.issues[0].startswith("Page 1 row ") and '"09/03/25"' in built.issues[0]


def test_rows_the_date_order_is_the_one_a_day_over_12_decides_else_the_one_that_fits_the_period_else_none(tmp_path):
    def run(name, dates, period):
        directory = tmp_path / name
        directory.mkdir()
        cells = [(date, f"ROW{number}", "1.00", "") for number, date in enumerate(dates)]
        return bank(read(directory, [sf.page(sf.X_ABOVE, cells, sf.COLUMNS4, sf.HEADING4, "SYNTH BANK")]), period)
    assert [row["posted_date"] for row in run("day", ["13/03/2026", "03/04/2026"], ("2026-03-01", "2026-04-30")).rows] == ["2026-03-13", "2026-04-03"]
    assert [row["posted_date"] for row in run("fits", ["03/10/2026", "03/11/2026"], ("2026-03-01", "2026-03-31")).rows] == ["2026-03-10", "2026-03-11"]
    both = run("both", ["03/04/2026", "03/05/2026"], ("2026-03-01", "2026-04-30"))
    assert both.rows == [] and both.issues == ["Page 1 rows: the date order (month/day or day/month) can't be told from the printed dates."]
    assert both.dropped == 2


def test_rows_x_records_only_x1_and_lists_x2_to_x6_with_pdf_imports_reasons(tmp_path):
    result = read(tmp_path, sf.x_pages())
    built = bank(result)
    assert rows_of(built) == [("2026-09-02", 1000, "GOOD")]
    assert len(built.issues) == 5 and built.dropped == 5
    assert all(issue.startswith(f"Page 1 row {number}: ") for number, issue in zip(range(1, 6), built.issues))
    reasons = [issue.split(": ", 1)[1] for issue in built.issues]
    assert reasons[0] == sf.X_REJECTED["x2"] and reasons[1] == sf.X_REJECTED["x3"] and reasons[2] == sf.X_REJECTED["x4"]
    assert "can't be read" in reasons[3] and reasons[4] == 'The amount "4.00 EUR" is not in USD.'
    assert reasons == [row.rejected for row in analysis(result).rows[1:]]  # In PDF import's own words.


def test_rows_q_records_both_check_rows_and_lists_one_duplicate_issue_naming_both_pages(tmp_path):
    built = bank(read(tmp_path, sf.q_pages()))
    assert built.pages == {1, 2} and len(built.rows) == 4
    assert [row["locator"]["page"] for row in built.rows if row["description"] == "CHECK 1001"] == [1, 2]
    assert built.issues == ["The same row is printed twice: 2026-09-10 CHECK 1001 -75.00 on page 1 (row 1) and page 2 (row 1). Both were recorded; check whether it is one payment."]


def test_rows_d_a_daily_balance_table_is_never_transactions_native_and_flagged(tmp_path):
    for name, pages in (("d", sf.d_pages()), ("dflag", sf.d_pages(True))):
        directory = tmp_path / name
        directory.mkdir()
        built = bank(read(directory, pages))
        assert rows_of(built) == expected_s() and built.issues == [] and built.notes == [] and built.pages == {1}, name


def test_rows_d_by_itself_on_page_two_starts_no_continuation_and_gives_no_rows(tmp_path):
    second = {"items": [(40, 740, "SYNTH BANK daily"), (40, 700, "DAILY ENDING BALANCE"), *fx.table_items([("Date", "Amount"), *sf.DAILY], 680, (40, 380)),
                        sf.words_footer("SYNTH BANK daily", 580)]}
    result = read(tmp_path, [*sf.s_pages(), second])
    built = bank(result)
    assert rows_of(built) == expected_s() and built.pages == {1} and built.issues == []


def test_rows_a_balance_row_under_the_heading_does_not_cut_the_table(tmp_path):
    """A row that only contains `balance` (a BALANCE TRANSFER description, a Beginning Balance line) never cuts a table (plan pass 3)."""
    extra = [("09/26", "BALANCE TRANSFER FEE", "-2.00", ""), ("09/27", "Beginning Balance carried", "-3.00", "")]
    built = bank(read(tmp_path, sf.s_pages(flagged=True, extra_rows=extra)))
    assert [row[2] for row in rows_of(built)][-2:] == ["BALANCE TRANSFER FEE", "Beginning Balance carried"]
    assert [row[1] for row in rows_of(built)] == [*sf.S_AMOUNTS, -200, -300] and built.issues == []


def test_rows_a_second_transactions_heading_on_a_rebuilt_page_is_listed(tmp_path):
    second = [(40, 300, "Date"), (110, 300, "Description"), (380, 300, "Amount"), (40, 280, "10/01"), (110, 280, "LATE ROW"), (380, 280, "9.00")]
    built = bank(read(tmp_path, sf.s_pages(flagged=True, extra=second)))
    assert rows_of(built) == expected_s()
    assert built.issues == ["Page 1: rows after a second transactions heading on this page weren't read; check them against the statement."]


def test_rows_a_balance_title_above_a_transactions_shaped_table_leaves_the_page_to_the_model_with_a_note(tmp_path):
    above = (*sf.S_ABOVE[:5], "Daily Ending Balance")
    built = bank(read(tmp_path, sf.s_pages(above=above)))
    assert built.rows == [] and built.pages == set()
    assert built.notes == ['Page 1: the line above the table headed "Date | Description | Amount | Balance" names a balance, so its rows were taken '
                           "from the reading, not the printed columns; check them."]


def test_rows_a_reading_without_a_layout_is_not_available_and_says_to_read_again(tmp_path):
    result = read(tmp_path, sf.s_pages())
    result.pages[0].layout = None
    built = bank(result)
    assert (built.available, built.rows, built.pages, built.notes) == (False, [], set(), [NO_LAYOUT_NOTE])
    assert rebuilt_pages(result) == set()


def test_rows_are_deterministic_and_the_pages_do_not_depend_on_the_currency_or_the_sign(tmp_path):
    result = read(tmp_path, sf.s_flag_pages())
    first, second = bank(result), bank(result)
    assert first == second
    assert rebuilt_pages(result) == {1}
    eur = rebuild(result, statement_type="bank", period_start=SEPTEMBER[0], period_end=SEPTEMBER[1], currency="EUR")
    assert eur.pages == {1} and [row["currency"] for row in eur.rows] == ["EUR"] * 5
    card = rebuild(result, statement_type="credit_card", period_start=SEPTEMBER[0], period_end=SEPTEMBER[1], currency="USD")
    assert card.pages == {1} and [row["amount_minor"] for row in card.rows] == [-amount for amount in sf.S_AMOUNTS]  # The sign is only the direction.


def test_rows_the_same_row_twice_in_one_table_is_two_rows_and_no_duplicate_issue(tmp_path):
    cells = [("09/02/2026", "SAME", "1.00", ""), ("09/02/2026", "SAME", "1.00", "")]
    built = bank(read(tmp_path, [sf.page(sf.X_ABOVE, cells, sf.COLUMNS4, sf.HEADING4, "SYNTH BANK")]))
    assert len(built.rows) == 2 and built.issues == []  # Same table: ordinals keep them apart, as on the statement.


# === FR-30: a number that continues the description (SC-27, SC-28, G5) ======================================================

def test_fr30_the_analyzer_version_is_two_so_every_reading_is_indexed_again():
    assert pdf_import.ANALYZER_VERSION == 2


def test_sc27_s_flag_s1_to_s3_keep_1234567890_in_the_description_and_none_is_rejected(tmp_path):
    result = read(tmp_path, sf.s_flag_pages())
    got = analysis(result)
    assert [(row.description, row.amount, row.amount_minor, row.rejected) for row in got.rows] == [
        (description, amount, minor, None) for _, _, description, amount, _, minor in sf.S_ROWS]
    built = bank(result)
    assert [row["description"] for row in built.rows][:3] == sf.S_DESCRIPTIONS[:3] and [row["amount_minor"] for row in built.rows] == sf.S_AMOUNTS


def test_sc27_without_fr30_those_rows_are_rejected_so_the_change_is_what_lets_them_through(tmp_path, monkeypatch):
    result = read(tmp_path, sf.s_flag_pages())
    monkeypatch.setattr(pdf_import, "joined_amounts", lambda *args: [])
    got = analysis(result)
    assert [row.rejected for row in got.rows[:3]] == ["The amount doesn't fit a column."] * 3 and got.rows[3].rejected is None


def test_sc27_x3_is_still_rejected_and_a_number_printed_apart_is_not_joined(tmp_path):
    """X's x3 prints `REF 55.55` in the Amount span beside `5.00` (the run starts in the Amount span); 7-e is in test_pdf_imports.
    `REF` ends before the Amount heading begins, so it is description text (docs/documents.md "Statement rows from the printed
    columns"); `55.55` is still an amount."""
    got = analysis(read(tmp_path, sf.x_pages()))
    [x3] = [row for row in got.rows if row.description == "X3 REF"]
    assert x3.rejected == "More than one amount sits in the Amount column." and x3.amount_minor is None


def test_sc27_pdf_import_previews_the_same_five_rows_by_account_id(env):
    a = env.account("B")
    doc = env.add("s-flag.pdf", sf.s_flag_pages())
    preview = env.ok_preview(doc, account_id=a, year=2026)
    assert [(row["description"], row["amount_minor"], row["status"]) for row in preview["rows"]] == [
        (description, minor, "new") for description, minor in zip(sf.S_DESCRIPTIONS, sf.S_AMOUNTS)]
    assert all(row["rejected"] is None for row in preview["rows"])


def test_sc28_t_t1_stays_an_amount_because_it_is_joined_but_wholly_in_the_amount_span_and_alone(tmp_path):
    result = read(tmp_path, sf.t_pages())
    got = analysis(result)
    assert len(got.rows) == 6 and all(row.rejected is None for row in got.rows)
    t1 = got.rows[5]
    assert (t1.date, t1.description, t1.amount, t1.amount_minor) == ("09/22", "SYNTH LONG DESCRIPTION", "12.34", 1234)
    assert [row.amount_minor for row in got.rows[:5]] == sf.S_AMOUNTS and [row.description for row in got.rows[:5]] == sf.S_DESCRIPTIONS
    built = bank(result)
    assert rows_of(built) == [*expected_s(), (sf.T1_POSTED, 1234, "SYNTH LONG DESCRIPTION")] and built.issues == []
    assert all("12.34" not in row["description"] for row in built.rows)


def test_sc28_pdf_import_previews_the_same_six_rows_with_t1s_amount_cell_and_no_number_in_its_description(env):
    a = env.account("B")
    doc = env.add("t.pdf", sf.t_pages())
    preview = env.ok_preview(doc, account_id=a, year=2026)
    assert len(preview["rows"]) == 6 and all(row["rejected"] is None for row in preview["rows"])
    t1 = preview["rows"][5]
    assert (t1["description"], t1["amount_minor"], t1["posted_date"]) == ("SYNTH LONG DESCRIPTION", 1234, sf.T1_POSTED)
    assert [row["amount_minor"] for row in preview["rows"][:5]] == sf.S_AMOUNTS


def test_fr30_edge_a_joined_only_amount_that_crosses_the_columns_edge_is_rejected_with_a_reason_never_dropped(tmp_path):
    result = read(tmp_path, sf.t_pages(edge=True))
    got = analysis(result)
    t1 = got.rows[5]
    assert t1.rejected == NO_AMOUNT and t1.amount_minor is None and not t1.ticked
    assert [row.amount_minor for row in got.rows[:5]] == sf.S_AMOUNTS and all(row.rejected is None for row in got.rows[:5])
    assert ("rejected_row", 1, 5) in [(issue.code, issue.page, issue.row) for issue in got.issues]
    built = bank(result)
    assert rows_of(built) == expected_s() and built.dropped == 1
    assert built.issues == [f"Page 1 row 5: {NO_AMOUNT}"]


def test_fr30_a_joined_amount_in_a_native_table_page_is_not_touched(tmp_path):
    """Native tables are untouched, because the reader built their cells: S (not flagged) reads the same rows as S-flag."""
    native, flagged = tmp_path / "native", tmp_path / "flagged"
    native.mkdir()
    flagged.mkdir()
    assert rows_of(bank(read(native, sf.s_pages()))) == rows_of(bank(read(flagged, sf.s_flag_pages())))


# === The stubs ===============================================================================================================

def test_stubs_s_bad_lists_the_wrong_rows_and_cites_real_lines_of_the_reading(tmp_path):
    for name, pages in (("s", sf.s_pages()), ("flag", sf.s_flag_pages()), ("t", sf.t_pages())):
        directory = tmp_path / name
        directory.mkdir()
        result = read(directory, pages)
        lines = sf.reading_lines(result)
        rows = sf.s_bad_rows(lines)
        assert [(row["amount"], row["direction"]) for row in rows] == [
            ("0.36", "credit"), ("0.38", "credit"), ("0.38", "debit"), ("1,500.00", "credit"), ("500.00", "debit"), ("0.38", "credit")], name
        assert rows[5]["description"] == "SYNTH ACCTVERIFY" and rows[5]["evidence"] == rows[1]["evidence"]  # The extra row cites s2's line.
        known = dict(lines)
        assert all(known[item["line_id"]] == item["quote"] for row in rows for item in row["evidence"])
        assert len(sf.s_bad_rows(lines, only=("s1", "s2", "s3", "s5", "extra"))) == 5  # The stub with s4 removed.
        assert all("12.34" not in repr(row) for row in rows)  # t1 is never listed.


def test_stubs_the_summaries_cite_the_printed_lines_and_s2_changes_only_the_reference(tmp_path):
    first, second = tmp_path / "s", tmp_path / "s2"
    first.mkdir()
    second.mkdir()
    for directory, pages, make, reference in ((first, sf.s_pages(), sf.s_summary, "3456"), (second, sf.s2_pages(), sf.s2_summary, "7890")):
        lines = sf.reading_lines(read(directory, pages))
        summary = make(lines)
        known = dict(lines)
        assert summary["account_reference"]["value"] == reference and summary["currency"]["status"] == "missing"
        assert (summary["period_start"]["value"], summary["period_end"]["value"], summary["opening_balance"]["value"], summary["closing_balance"]["value"]) == (
            "2026-09-01", "2026-09-30", "0.00", "1,000.00")
        assert summary["account_type"]["value"] == "savings" and "SYNTH SAVINGS" in summary["account_type"]["evidence"][0]["quote"]
        for item in summary.values():
            for cite in item["evidence"]:
                assert cite["quote"] in known[cite["line_id"]]
        assert reference in summary["account_reference"]["evidence"][0]["quote"]


# === Record: the rows through ExtractionService ==============================================================================

LAYOUT_ISSUES = {"overlapping_text", "unsupported_text_rotation"}


class Recorded:
    """One Record of a fixture: the store, the extraction run, its statement's record and the lines the model was shown."""

    def __init__(self, store, service, doc, parse_id, lines, model):
        self.store, self.service, self.doc, self.parse_id, self.lines, self.model = store, service, doc, parse_id, lines, model

    def run(self, replies, force=False):
        """Record with these `by_schema` replies (a function of the lines is called with them)."""
        self.model["by_schema"] = replies(self.lines) if callable(replies) else replies
        config = ReasoningConfig(base_url=self.model["config"].base_url, model="synthetic-reasoning")
        run_id, _ = ExtractionService(self.store, self.service).enqueue(self.doc["id"], self.parse_id, config, force=force, home_currency="USD")
        ExtractionService(self.store, self.service).run(run_id, Work.detached())
        self.extraction = ExtractionService(self.store, self.service).get(run_id)
        assert self.extraction["status"] == "succeeded", self.extraction["error"]
        self.record = Ledger(self.store).record("statement", self.extraction["publication"]["id"])
        return self.record

    def transactions(self):
        with self.store.connection() as db:
            return [(row["posted_date"], row["amount_minor"], row["description_raw"]) for row in db.execute(
                "SELECT posted_date,amount_minor,description_raw FROM transactions WHERE statement_id=? ORDER BY id", (self.record["id"],))]

    def notes(self):
        """The record's notes, read from the API's record shape (the statement's details), not from the run's result."""
        return (self.record.get("details") or {}).get("notes", [])


def stored(pdf_store, local_model, pages, scanned=None):
    """The fixture captured, read by the real reader (a None page by the vision stub), ready for Record."""
    inbox, store = pdf_store
    make_pdf(inbox / "statement.pdf", pages)
    doc = capture(inbox, store)
    if scanned:
        local_model["output"] = {"full_text": scanned}
    service = ReceiptService(store)
    parse_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(parse_id, Work.detached())
    parsed = service.get(parse_id)
    assert parsed["status"] == "succeeded", parsed["error"]
    result = read_result(parsed["result"])
    assert len(local_model["requests"]) == (1 if scanned else 0)  # Only the scanned page reached the vision model.
    return Recorded(store, service, doc, parse_id, sf.reading_lines(result), local_model), result


def bank_replies(summary, rows, kind="bank_statement", end="2026-09-30", **extra):
    def make(lines):
        key = "CreditCardStatementSummary" if kind == "credit_card_statement" else "BankStatementSummary"
        return {"Classification": [sf.classified(lines, kind, end)], key: [summary(lines)], "Transactions": [{"transactions": rows(lines)}], **extra}
    return make


def s_replies(rows=sf.s_bad_rows, summary=sf.s_summary):
    return bank_replies(summary, rows)


def s_bad_without_s4(lines):
    return sf.s_bad_rows(lines, only=("s1", "s2", "s3", "s5", "extra"))


def quoting(note, *texts):
    return all(text in note for text in texts)


def test_sc13_the_users_case_records_the_printed_columns_and_notes_the_two_rows_the_columns_dont_have(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.s_flag_pages())
    page = result.pages[0]  # P-check
    assert page.method == "embedded_text" and native_page(page) is False and LAYOUT_ISSUES <= set(page.layout.issues)
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    assert not any(amount in (38, 0) for _, amount, _ in recorded.transactions())  # Neither balance is recorded as an amount.
    notes = recorded.notes()
    assert len([note for note in notes if note.startswith("The reading listed a row the printed columns don't have")]) == 2
    assert all(quoting(note, "page 1", "2026-09-18", "0.38", "money in", "It wasn't recorded.") for note in notes if "printed columns don't have" in note)
    assert any("SYNTH ACCTVERIFY PPD ID 1234567890" in note for note in notes) and any("SYNTH ACCTVERIFY 0.38" in note for note in notes)
    assert not any("printed columns don't have" in issue for issue in record["issues"])  # Notes, not review reasons (Q5).
    assert record["review_status"] == "needs_review"
    assert any(issue.startswith("Page 1 PDF layout needs review: ") for issue in record["issues"])  # FR-22
    with recorded.store.connection() as db:
        assert db.execute("SELECT count(*) FROM transactions WHERE typeof(amount_minor)<>'integer' OR currency<>'USD'").fetchone()[0] == 0  # C-money


def test_sc14_debit_credit_columns_and_the_models_balance_amounts_change_nothing(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.w_pages())
    recorded.run(bank_replies(sf.w_summary, sf.w_rows, end="2026-08-31"))
    assert [(amount, description) for _, amount, description in recorded.transactions()] == [
        (minor, row[2]) for minor, row in zip(sf.W_AMOUNTS, sf.W_ROWS)]
    assert [amount for _, amount, _ in recorded.transactions()] == [-120000, 250000, 15000]
    assert not any(amount in (-20000, 230000, 245000) for _, amount, _ in recorded.transactions())  # No balance value is recorded.


def test_sc14_a_card_statements_charges_print_positive_and_record_as_money_out(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.c_pages())
    recorded.run(bank_replies(sf.c_summary, lambda lines: [], kind="credit_card_statement", end="2026-01-14"))
    assert [(posted, amount) for posted, amount, _ in recorded.transactions()] == [(row[4], row[5]) for row in sf.C_ROWS]
    assert [amount for _, amount, _ in recorded.transactions()] == [-1999, 25000, -3820]


def test_sc15_the_year_comes_from_the_printed_period(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.c_pages())
    record = recorded.run(bank_replies(sf.c_summary, lambda lines: [], kind="credit_card_statement", end="2026-01-14"))
    assert [posted for posted, _, _ in recorded.transactions()] == ["2025-12-20", "2026-01-03", "2026-01-05"]
    assert record["review_status"] == "proposed", record["issues"]  # 300.00 − (−19.99 + 250.00 − 38.20) = 108.19; FR-04: a new account waits


def test_sc15_with_no_printed_period_no_row_is_recorded_and_each_is_an_issue_naming_the_missing_year(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.c0_pages())
    record = recorded.run(bank_replies(lambda lines: sf.c_summary(lines, period=False), lambda lines: [], kind="credit_card_statement", end=None))
    assert recorded.transactions() == [] and record["review_status"] == "needs_review"
    for number in (1, 2, 3):
        [issue] = [issue for issue in record["issues"] if issue.startswith(f"Page 1 row {number}: ")]
        assert "no year is printed" in issue and "period" in issue
    assert not any(issue.startswith("Statement arithmetic") for issue in record["issues"])  # Rows were left out, so the sum says nothing.


def test_sc15_s_rows_without_a_year_are_2026_09(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())
    recorded.run(s_replies())
    assert [posted for posted, _, _ in recorded.transactions()] == sf.S_POSTED


def test_sc16_the_model_cannot_change_rebuilt_rows_and_the_status_follows_the_other_checks(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.s_pages())
    assert native_page(result.pages[0]) is True  # S is not flagged: the page is native for the model too.
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    notes = [note for note in recorded.notes() if "printed columns don't have" in note]
    assert len(notes) == 2 and all(quoting(note, "page 1", "2026-09-18", "0.38", "money in") for note in notes)
    assert record["issues"] == [] and record["review_status"] == "proposed"  # FR-04: it reconciles, and the new account waits for Confirm; the notes are not reasons for review.


def test_sc16_a_rebuilt_row_the_model_did_not_list_is_still_recorded(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())
    recorded.run(bank_replies(sf.s_summary, s_bad_without_s4))
    assert recorded.transactions() == expected_s()


def test_sc17_rejected_rows_are_issues_with_their_page_row_and_reason(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.x_pages())
    got = analysis(result)
    record = recorded.run(bank_replies(sf.x_summary, lambda lines: [], end="2026-09-30"))
    assert recorded.transactions() == [("2026-09-02", 1000, "GOOD")]
    assert record["review_status"] == "needs_review"
    by_row = {int(issue.split()[3].rstrip(":")): issue for issue in record["issues"] if issue.startswith("Page 1 row ")}
    assert sorted(by_row) == [1, 2, 3, 4, 5]
    for number, reason in zip(range(1, 6), [row.rejected for row in got.rows[1:]]):
        assert by_row[number] == f"Page 1 row {number}: {reason}" and reason
    assert "doesn't fit a column" in by_row[1] and "More than one amount" in by_row[2] and "not a real date" in by_row[3]
    assert "can't be read" in by_row[4] and "not in USD" in by_row[5]


def test_sc18_a_scanned_page_keeps_the_models_row_while_page_one_comes_from_the_rebuild(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.m_pages(), scanned="SCANNED PAGE\n09/27 SCANNED CAFE 7.00")
    assert [page.method for page in result.pages] == ["embedded_text", "vision_model"]
    scanned = [(line_id, text) for line_id, text in recorded.lines if line_id.startswith("page-2-")]

    def rows(lines):
        cafe = next(pair for pair in lines if "SCANNED CAFE" in pair[1])
        return [*sf.s_bad_rows(lines), sf.stub_row(lines, "2026-09-27", "SCANNED CAFE", "7.00", "debit", cafe[1])]
    record = recorded.run(bank_replies(sf.s_summary, rows))
    assert scanned and recorded.transactions() == [*expected_s(), ("2026-09-27", -700, "SCANNED CAFE")]
    with recorded.store.connection() as db:
        links = [json.loads(row[0]) for row in db.execute(
            "SELECT locator_json FROM financial_evidence_links WHERE record_type='transaction' ORDER BY record_id")]
    assert [bool(link.get("rebuilt")) for link in links] == [True] * 5 + [False]  # No rebuilt row cites page 2.
    assert all(link["line_ids"][0].startswith("page-1-") for link in links[:5]) and links[5]["line_ids"][0].startswith("page-2-")
    assert not any("aren't in the transactions" in issue for issue in record["issues"])  # Page 1 is not asked about again.


def without_layout(recorded):
    """S's saved reading with every page's layout set to None, as an old reading (test_pdf_imports does the same)."""
    with recorded.store.connection() as db:
        saved = json.loads(db.execute("SELECT result_json FROM parse_runs WHERE id=?", (recorded.parse_id,)).fetchone()[0])
        for page in saved["pages"]:
            page["layout"] = None
        db.execute("UPDATE parse_runs SET result_json=? WHERE id=?", (json.dumps(saved), recorded.parse_id))
    recorded.lines = sf.reading_lines(read_result(saved))


def test_sc18_a_reading_without_layout_records_the_models_rows_as_today_with_the_note(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())
    without_layout(recorded)
    record = recorded.run(s_replies())
    assert [(posted, amount) for posted, amount, _ in recorded.transactions()] == [
        ("2026-09-18", 36), ("2026-09-18", 38), ("2026-09-18", -38), ("2026-09-20", 150000), ("2026-09-25", -50000), ("2026-09-18", 38)]
    assert NO_LAYOUT_NOTE in recorded.notes() and NO_LAYOUT_NOTE not in record["issues"]
    assert not any("printed columns don't have" in note for note in recorded.notes())


def test_sc19_a_rebuilt_rows_provenance_names_its_file_page_lines_and_words(env, local_model):
    recorded, result = stored((env.store.library.inbox, env.store), local_model, sf.s_pages())
    recorded.run(s_replies())
    ids = [row[0] for row in env.sql("SELECT id FROM transactions WHERE statement_id=? ORDER BY id", recorded.record["id"])]
    locators = {txn: json.loads(locator) for txn, locator in env.sql("SELECT record_id,locator_json FROM financial_evidence_links WHERE record_type='transaction'")}
    s2 = ids[1]
    response = env.client.get(f"/api/provenance/transaction/{s2}")
    assert response.status_code == 200, response.text
    found = response.json()["provenance"]
    locator = locators[s2]
    layout = fx.layout(result, 1)
    assert locator["rebuilt"] is True and locator["page"] == 1 and locator["line_ids"]
    # S is a native table: s2 cites the cells of its table row, and the line that holds its words (not a bare row number).
    assert not locator["word_ids"] and locator["cell_ids"] and all(cell.startswith("page-1-layout-table-1-row-") for cell in locator["cell_ids"])
    assert [line.text for line in layout.lines if line.id in locator["line_ids"]] == [f"09/18 {sf.S_DESCRIPTIONS[1]} 0.02 0.38"]
    assert found["kind"] == "extracted"
    assert found["document"] == {"id": recorded.doc["id"], "page": 1, "lines": locator["line_ids"], "cells": locator["cell_ids"],
                                 "quote": f"09/18 {sf.S_DESCRIPTIONS[1]} 0.02 0.38"}
    assert env.sql("SELECT relative_path FROM occurrences WHERE id=?", found["document"]["id"])[0][0].endswith("statement.pdf")


def test_sc19_a_rebuilt_row_below_a_native_table_cites_its_words(env, local_model):
    recorded, result = stored((env.store.library.inbox, env.store), local_model, sf.s_flag_pages())
    recorded.run(s_replies())
    [(txn, raw)] = env.sql("SELECT record_id,locator_json FROM financial_evidence_links WHERE record_type='transaction' AND record_id IN "
                           "(SELECT id FROM transactions WHERE statement_id=? ORDER BY id LIMIT 1 OFFSET 1)", recorded.record["id"])
    locator = json.loads(raw)
    assert locator["rebuilt"] is True and locator["word_ids"] and not locator["cell_ids"]
    found = env.client.get(f"/api/provenance/transaction/{txn}").json()["provenance"]
    assert found["document"]["page"] == 1 and found["document"]["lines"] == locator["line_ids"] and found["document"]["cells"] == locator["word_ids"]
    words = {word.id for word in fx.layout(result, 1).words}
    assert set(found["document"]["cells"]) <= words and found["document"]["id"] == recorded.doc["id"]


def test_sc20_s_reconciles_and_extracting_again_gives_identical_rows_and_ids(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())
    record = recorded.run(s_replies())
    assert not any("Statement arithmetic does not reconcile" in issue for issue in record["issues"]) and recorded.extraction["result"]["normalized"]["cross_checks"] >= 1

    def snapshot():
        with recorded.store.connection() as db:
            return [tuple(row) for row in db.execute("SELECT id,posted_date,amount_minor,description_raw,source_fingerprint FROM transactions ORDER BY id")]
    first = snapshot()
    recorded.run(s_replies(), force=True)
    assert snapshot() == first and [row[2] for row in first] == sf.S_AMOUNTS


def test_sc20_a_statement_you_confirmed_is_untouched_by_extracting_again(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())
    record = recorded.run(s_replies())
    Ledger(recorded.store).review("statement", record["id"], "verified")
    with recorded.store.connection() as db:
        before = [tuple(row) for row in db.execute("SELECT * FROM transactions ORDER BY id")], [tuple(row) for row in db.execute("SELECT * FROM statements")]
    recorded.run(s_replies(rows=s_bad_without_s4), force=True)
    assert recorded.extraction["publication"]["status"] == "kept_reviewed"
    with recorded.store.connection() as db:
        assert ([tuple(row) for row in db.execute("SELECT * FROM transactions ORDER BY id")], [tuple(row) for row in db.execute("SELECT * FROM statements")]) == before


def test_sc20_the_rebuild_makes_no_request_of_its_own(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())
    before = len(local_model["requests"])
    recorded.run(s_replies())
    asked = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"][before:]]
    assert sorted(set(asked)) == ["BankStatementSummary", "Classification", "Transactions"]  # Only the stubbed reasoning calls; no vision request.
    assert all(request["messages"][1]["content"] is not None for request in local_model["requests"][before:])
    assert not any("image_url" in json.dumps(request["messages"]) for request in local_model["requests"][before:])


def test_sc21_a_daily_balance_table_is_never_transactions(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.d_pages())
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    assert sum(1 for posted, amount, _ in recorded.transactions() if (posted, amount) == ("2026-09-20", 150000)) == 1
    assert not any(row[2] == 0 or row[2] == 100000 for row in recorded.transactions())
    assert [issue for issue in record["issues"] if "PDF layout needs review" not in issue] == []  # The reader's own note on the daily rows only.


def test_sc21_the_daily_table_on_page_two_by_itself_starts_no_continuation(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.d2_pages())
    assert rebuilt_pages(result) == {1}
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    # Page 2 has no rebuilt rows, so it keeps today's reading (FR-23): the reader's page note and the missed-row note name its lines.
    assert [issue for issue in record["issues"] if not issue.startswith("Page 2 PDF layout") and "aren't in the transactions" not in issue] == []


def test_sc21_d_flag_records_only_s1_to_s5_and_no_issue_names_a_daily_row(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.d_pages(flagged=True))
    assert native_page(result.pages[0]) is False
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    assert not any("DAILY" in issue or "1,500.00" in issue for issue in record["issues"] if "layout" not in issue)


def test_sc23_the_same_row_in_two_sections_is_recorded_twice_and_noted_in_review(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.q_pages())
    record = recorded.run(bank_replies(sf.q_summary, lambda lines: []))
    checks = [row for row in recorded.transactions() if row[2] == "CHECK 1001"]
    assert len(checks) == 2 and [amount for _, amount, _ in checks] == [-7500, -7500]
    with recorded.store.connection() as db:
        assert [row[0] for row in db.execute("SELECT count(*) FROM transactions WHERE description_raw='CHECK 1001' GROUP BY source_fingerprint")] == [1, 1]
    [issue] = [issue for issue in record["issues"] if issue.startswith("The same row is printed twice")]
    assert "page 1" in issue and "page 2" in issue and record["review_status"] == "needs_review"


def test_sc27_record_reads_s_flag_with_the_description_numbers_and_rejects_none(pdf_store, local_model):
    recorded, _ = stored(pdf_store, local_model, sf.s_flag_pages())
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    assert [description for _, _, description in recorded.transactions()][:3] == [
        "SYNTH ACCTVERIFY PPD ID 1234567890", "SYNTH ACCTVERIFY PPD ID 1234567890", "SYNTH ACCTVERIFY WEB ID 1234567890"]
    assert not any("doesn't fit a column" in issue or "printed against the description" in issue for issue in record["issues"])


def test_sc28_t1_is_recorded_though_the_model_did_not_list_it_and_no_issue_names_it(pdf_store, local_model):
    recorded, result = stored(pdf_store, local_model, sf.t_pages())
    assert native_page(result.pages[0]) is False
    record = recorded.run(s_replies())
    assert recorded.transactions() == [*expected_s(), (sf.T1_POSTED, 1234, "SYNTH LONG DESCRIPTION")]
    named = [issue for issue in [*record["issues"], *recorded.notes()] if "LONG DESCRIPTION" in issue or "Page 1 row 6" in issue or "09/22" in issue]
    assert named == []  # T isn't balanced, so the arithmetic issue is expected (it names the sum, not the row).
    assert all("1234567890" in description for _, _, description in recorded.transactions()[:3])


REBUILD_FAILED = "The rows couldn't be rebuilt from the printed columns, so the reading's rows were used; check them."


def test_sc18_p8_a_rebuild_that_fails_in_read_falls_back_to_the_models_rows_on_every_page_with_one_issue(pdf_store, local_model, monkeypatch):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())

    def broken(result):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(statement_rows, "rebuilt_pages", broken)
    record = recorded.run(s_replies())
    assert [issue for issue in record["issues"] if issue == REBUILD_FAILED] == [REBUILD_FAILED]
    # As today: the model's six rows, each amount taken from the native table's cell it cites (the misread s2 and the extra row become 0.02).
    assert [amount for _, amount, _ in recorded.transactions()] == [36, 2, -38, 150000, -50000, 2]
    assert record["review_status"] == "needs_review"


def test_sc18_p8_a_rebuild_that_fails_in_publish_is_one_issue_and_the_models_rows_stand(pdf_store, local_model, monkeypatch):
    recorded, _ = stored(pdf_store, local_model, sf.s_pages())

    def broken(*args, **options):
        raise pdf_import.PDFImportError("synthetic limit")
    monkeypatch.setattr(statement_rows, "rebuild", broken)
    record = recorded.run(s_replies())
    assert record["issues"].count(REBUILD_FAILED) == 1 and len(recorded.transactions()) == 6


def test_sc17_a_rejected_row_turns_the_arithmetic_check_off_rather_than_reporting_a_false_mismatch(pdf_store, local_model):
    """FR-25: the sum is checked only when no row was left out. T-edge's t1 is rejected, so its statement isn't summed."""
    recorded, _ = stored(pdf_store, local_model, sf.t_pages(edge=True))
    record = recorded.run(s_replies())
    assert recorded.transactions() == expected_s()
    assert not any("Statement arithmetic" in issue for issue in record["issues"])
    assert f"Page 1 row 5: {NO_AMOUNT}" in record["issues"]


# === A description printed in pieces (the user's bank statement) ============================================================

PIECES_ROWS = [  # (date, description's first piece, its second piece and where it starts, amount, balance)
    ("09/18", "SYNTH ACCTVERIFY", (230, "PPD ID: SYNTHID01"), "0.36", "0.36"),
    ("09/18", "SYNTH ACCTVERIFY", (230, "PPD ID: SYNTHID01"), "0.02", "0.38"),
    ("09/18", "SYNTH ACCTVERIFY XY12", (260, "Web ID: SYNTHID01"), "-0.38", "0.00"),
]


def pieces_pages(flagged=False):
    """Date | Description | Amount | Balance with the amounts right-aligned under headings far to the right. Each description's
    second piece reaches past the midpoint between the Description and Amount headings (282 pt), but ends before Amount (433
    pt). Beginning and Ending Balance rows print only a balance. `flagged` adds S-flag's overlapping and turned words."""
    items = [(38, 700, "Date"), (80, 700, "Description"), (433, 700, "Amount"), (501, 700, "Balance"),
             (80, 680, "Beginning Balance"), (515, 680, "0.00")]
    for index, (date, first, (x, second), amount, balance) in enumerate(PIECES_ROWS):
        y = 660 - 20 * index
        items += [(38, y, date), (80, y, first), (x, y, second), (468 - 5 * len(amount), y, amount), (535 - 5 * len(balance), y, balance)]
    items += [(80, 600, "Ending Balance"), (515, 600, "0.00"), sf.words_footer("SYNTH BANK", 580)]
    return [{"items": items + (sf.flag_items() if flagged else [])}]


PIECES_EXPECTED = [("2026-09-18", 36, "SYNTH ACCTVERIFY PPD ID: SYNTHID01"), ("2026-09-18", 2, "SYNTH ACCTVERIFY PPD ID: SYNTHID01"),
                   ("2026-09-18", -38, "SYNTH ACCTVERIFY XY12 Web ID: SYNTHID01")]


def test_a_description_printed_in_pieces_is_one_cell_of_the_native_table(tmp_path):
    """The reader allowed one piece of text per cell, so it refused the table and showed only a support table."""
    result = read(tmp_path, pieces_pages())
    assert native_page(result.pages[0])
    assert fx.native_transactions_tables(result, 1) == [[["Date", "Description", "Amount", "Balance"], ["", "Beginning Balance", "", "0.00"],
                                                          *[[date, f"{first} {second}", amount, balance] for date, first, (_, second), amount, balance in PIECES_ROWS],
                                                          ["", "Ending Balance", "", "0.00"]]]
    assert rows_of(bank(result)) == PIECES_EXPECTED


def test_a_description_printed_in_pieces_is_description_text_in_a_rebuilt_row(tmp_path):
    """On a flagged page Record rebuilds from the words: the second piece's end fell in the Amount column's span, and each row
    was rejected as text in the Amount column."""
    result = read(tmp_path, pieces_pages(flagged=True))
    assert not native_page(result.pages[0])
    built = bank(result)
    assert rows_of(built) == PIECES_EXPECTED
    assert not [issue for issue in built.issues if "not an amount" in issue]
