"""Record's rows from the printed columns (specs/statement-accounts/test-contract.md), module level.

This file holds SL-01's checks: the P-checks that say each synthetic fixture has the shape the contract intends when the real
reader reads it (`pcheck_*`), the rows `finance/statement_rows.rebuild` gives for each fixture (`rows_*`), FR-30's change to
`pdf_import.visual_row` (`sc27`, `sc28`, `fr30_edge`) and the stubs. Expected values are the contract's, written out in
tests/statement_account_fixtures.py by hand. A failed P-check is a fixture or reader problem, never a reason to change an
expected value.
"""

from home_manager.core.jobs import Work
from home_manager.documents.layout_context import native_page
from home_manager.documents.pdf_reader import read_result
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance import pdf_import, statement_rows
from home_manager.finance.statement_rows import NO_LAYOUT_NOTE, rebuild, rebuilt_pages
import pdf_import_fixtures as fx
import statement_account_fixtures as sf
from test_pdf import capture, make_pdf, pdf_store  # noqa: F401
from test_pdf_imports import env, no_network  # noqa: F401  (the autouse C-net guard, and the API environment of PDF import)

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
    """X's x3 prints `REF 55.55` in the Amount span beside `5.00` (the run starts in the Amount span); 7-e is in test_pdf_imports."""
    got = analysis(read(tmp_path, sf.x_pages()))
    [x3] = [row for row in got.rows if row.description == "X3"]
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
