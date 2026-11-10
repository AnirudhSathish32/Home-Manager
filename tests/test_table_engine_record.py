"""Record through the table engine (specs/pdf-table-engine/test-contract.md), Record side: SC-01 – SC-07, SC-08 step 3, SC-09 – SC-11, SC-13 (Extract
again), SC-14, SC-16, SC-17, SC-19 step 1, SC-23 – SC-25.

Each scenario goes through the real `ExtractionService`: the fixture is captured, read by the real PDF reader (no vision model), and recorded with
the `local_model` stub answering by `json_schema.name` (Classification, the statement summary and Transactions), as tests/test_statement_rebuild.py
does. Expected values are the contract's tables, held as literals in tests/table_engine_fixtures.py. PDF import steps (SC-08 step 2, SC-12, SC-16's
preview, SC-19 step 2, J1) are SL-06's and live under names ending `_import` or `journey_j1`.

Deviations from the contract's stubs (the stub can only cite what the fixture prints): a summary value the fixture doesn't print (K3's opening and
closing, CC's, ND's, ONE's) is `missing`; WF-summary-off cites two extra lines the variant prints below the footer (`Average collected 1,100.00`,
`Available now 2,213.45`), because the reading's amounts must be printed in the lines they cite.
"""

import json
import logging
import re
import time

import pytest

from home_manager.documents import extraction
from home_manager.documents.pdf_reader import read_result
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance import pdf_import, statement_tables
import pdf_import_fixtures as fx
import statement_account_fixtures as sf
import table_engine_fixtures as tf
from test_pdf import pdf_store  # noqa: F401
from test_pdf_imports import candidates, env, opened  # noqa: F401  (the API environment of PDF import)
from test_statement_rebuild import Recorded, s_replies
from test_table_engine import no_network  # noqa: F401  C-net: autouse, nothing here connects to a non-loopback address.

ARITHMETIC = "Statement arithmetic does not reconcile"
ROW_REVIEW = re.compile(r"^Page \d+ row \d+|wasn't placed in any column|a pending row|doesn't follow from the row above|can't be told|"
                        r"may hold more than one account|weren't recorded")
REBUILD_FAILED = extraction.REBUILD_FAILED


# --- Summary stubs (the contract's table) ---------------------------------------------------------------------------------------------

def spec(kind, name, ref, period, opening, closing):
    """kind: bank or card. ref: (digits, the line that prints them). period: (start, end, line, start as printed, end as printed) or None.
    opening, closing: (value as printed, the line that prints it) or None when the fixture prints none."""
    return {"kind": kind, "name": name, "ref": ref, "period": period, "opening": opening, "closing": closing}


def period(start, end, line="Statement period"):
    def printed(iso):
        year, month, day = iso.split("-")
        return f"{month}/{day}/{year}"
    return (start, end, line, printed(start), printed(end))


SPECS = {
    "WF": spec("bank", "SYNTH WF STYLE BANK", ("9988", "Account number"), period("2026-10-01", "2026-10-31"),
               ("1,000.00", "Beginning balance"), ("2,113.45", "Ending balance")),
    "DM": spec("bank", "SYNTH DAYFIRST BANK", ("4417", "Account No"), ("2026-10-01", "2026-10-31", "Statement From", "01/10/2026", "31/10/2026"),
               ("10,000.00", "Opening Balance"), ("33,754.10", "Closing Balance")),
    "WR": spec("bank", "SYNTH WRAP BANK", ("2208", "Account number"), period("2026-11-01", "2026-11-30"), ("500.00", "Beginning balance"), ("2,007.66", "Ending balance")),
    "OD": spec("bank", "SYNTH DAILY BANK", ("6630", "Account number"), period("2026-12-01", "2026-12-31"), ("200.00", "Beginning balance"), ("437.85", "Ending balance")),
    "ONE": spec("bank", "SYNTH ONE BANK", ("6611", "Account number"), period("2026-09-01", "2026-09-30"), None, None),
    "CS": spec("card", "SYNTH REWARDS CARD", ("5512", "Card number"), period("2026-10-05", "2026-11-04"), ("1,250.00", "Previous Balance"), ("481.62", "New Balance")),
    "NB": spec("bank", "SYNTH PLAIN BANK", ("4040", "Account number"), period("2026-11-01", "2026-11-30"), ("100.00", "Beginning balance"), ("674.80", "Ending balance")),
    "NB-plain": spec("bank", "SYNTH PLAIN BANK", ("4040", "Account number"), period("2026-11-01", "2026-11-30"), None, None),
    "K3": spec("bank", "FIRST LOCAL BANK", ("4821", "Account number"), period("2026-08-01", "2026-08-31"), None, None),
    "B": spec("bank", "SYNTH CHECKING BANK", ("5521", "Account number"), period("2026-08-01", "2026-08-31"), ("1,000.00", "Beginning balance"), ("2,950.00", "Ending balance")),
    "PR": spec("bank", "SYNTH CHECKING BANK", ("5521", "Account number"), period("2026-08-01", "2026-08-31"), ("1,000.00", "Beginning balance"), ("2,947.50", "Ending balance")),
    "CC": spec("bank", "SYNTH COMBINED BANK", ("3311", "CHECKING ACCOUNT"), period("2026-09-01", "2026-09-30"), None, None),
    "ND": spec("bank", "SYNTH NODATE BANK", ("7788", "Account number"), None, None, None),
    "ND-prior": spec("bank", "SYNTH NODATE BANK", ("7788", "Account number"), period("2026-02-01", "2026-02-28"), ("100.00", "Beginning balance"), ("104.00", "Ending balance")),
    "FX": spec("card", "SYNTH TRAVEL CARD", ("7001", "Card number"), period("2026-10-01", "2026-10-31"), ("0.00", "Previous Balance"), ("210.00", "New Balance")),
    "PD": spec("card", "SYNTH PENDING CARD", ("7002", "Card number"), period("2026-10-01", "2026-10-31"), ("100.00", "Previous Balance"), ("145.00", "New Balance")),
    "TD": spec("card", "SYNTH POSTING CARD", ("7003", "Card number"), period("2026-09-20", "2026-10-19"), ("0.00", "Previous Balance"), ("439.25", "New Balance")),
}
SPECS["WF-bare"] = SPECS["WF-flag"] = SPECS["WF"]
SPECS["BRK"] = SPECS["DM"]
SPECS["WR-split"] = SPECS["WR"]
SPECS["BL"] = SPECS["UP"] = SPECS["B"]
SPECS["TD-bare"] = SPECS["TD"]
SPECS["WF-summary-off"] = {**SPECS["WF"], "opening": ("1,100.00", "Average collected"), "closing": ("2,213.45", "Available now")}


def printed_line(lines, needle):
    """The first line (id, text) that contains the needle, ignoring case: the fixtures print `Beginning balance` and `Beginning Balance`."""
    found = [pair for pair in lines if needle.lower() in sf.spaced(pair[1]).lower()]
    assert found, f"{needle!r} is printed on no line"
    return found[0]


def cited(lines, value, needle, quote=None):
    return {"value": value, "status": "proposed", "evidence": [{"line_id": printed_line(lines, needle)[0], "quote": quote or value}]}


def summary_from(chosen):
    """The `BankStatementSummary` or `CreditCardStatementSummary` reply for a spec, each value citing its printed line."""
    def make(lines):
        card = chosen["kind"] == "card"
        found = {"issuer" if card else "institution": cited(lines, chosen["name"], chosen["name"]),
                 "account_reference": cited(lines, *chosen["ref"][:1], chosen["ref"][1], quote=chosen["ref"][0])}
        if chosen["period"]:
            start, end, line, start_text, end_text = chosen["period"]
            found["period_start"], found["period_end"] = cited(lines, start, line, start_text), cited(lines, end, line, end_text)
        for key, field in (("opening", "previous_balance" if card else "opening_balance"), ("closing", "statement_balance" if card else "closing_balance")):
            if chosen[key]:
                found[field] = cited(lines, chosen[key][0], chosen[key][1])
        return sf.fill("credit_card_statement" if card else "bank_statement", found)
    return make


def summary_of(name):
    return summary_from(SPECS[name])


def replies(name, rows=None, answers=None):
    """Classification, the summary and `Transactions` for a fixture (a name in SPECS, or a spec). `rows` is a function of the lines giving the first
    Transactions answer's rows (empty by default: on engine pages the model's rows decide nothing); `answers` replaces the whole Transactions list."""
    chosen = SPECS[name] if isinstance(name, str) else name
    card = chosen["kind"] == "card"

    def make(lines):
        kind = "credit_card_statement" if card else "bank_statement"
        issuer = cited(lines, chosen["name"], chosen["name"])
        first = {"transactions": rows(lines) if rows else []}
        return {"Classification": [{"document_type": kind, "evidence": issuer["evidence"], "issuer": issuer, "document_date": sf.MISSING}],
                "CreditCardStatementSummary" if card else "BankStatementSummary": [summary_from(chosen)(lines)],
                "Transactions": answers(lines) if answers else [first] + [{"transactions": []}] * 6}
    return make


def row_stub(lines, date, description, amount, direction, needle):
    return {"posted_date": date, "transaction_date": None, "description": description, "amount": amount, "direction": direction,
            "evidence": [{"line_id": printed_line(lines, needle)[0], "quote": printed_line(lines, needle)[1]}]}


# --- Reading and recording a fixture ---------------------------------------------------------------------------------------------------

def recorded_fixture(env_, model, name, pages=None, file=None):
    """The fixture captured and read by the real reader, ready for Record (the model is the `local_model` stub)."""
    pages = pages if pages is not None else tf.FIXTURES[name]()
    doc = env_.add(f"{file or name}.pdf", pages)
    service = ReceiptService(env_.store)
    parse_id = env_.reading(doc)
    result = read_result(service.get(parse_id)["result"])
    assert [page.method for page in result.pages] == ["embedded_text"] * len(pages)
    return Recorded(env_.store, service, doc, parse_id, sf.reading_lines(result), model), result


def record(env_, model, name, pages=None, rows=None, answers=None, file=None):
    """Record the fixture; returns (recorded, record)."""
    recorded, _ = recorded_fixture(env_, model, name, pages, file)
    return recorded, recorded.run(replies(name, rows, answers))


def collapse(text):
    return " ".join(text.split())


def rows_of(recorded):
    return [(posted, amount, collapse(text)) for posted, amount, text in recorded.transactions()]


def exact(recorded, expected):
    """C-exact: the statement's transactions, in printed order, are the fixture's expected (posted_date, amount_minor, description), no extra row."""
    assert rows_of(recorded) == [(posted, amount, collapse(text)) for posted, amount, text in expected]


def reconciles(recorded, record_):
    """C-reconciles: no arithmetic issue, no failing summary figure; with an opening and a closing printed, the arithmetic check ran and held."""
    assert not any(ARITHMETIC in issue for issue in record_["issues"]), record_["issues"]
    assert all(check.get("passes", True) for check in record_.get("checks", []))


def checked(recorded):
    assert recorded.extraction["result"]["normalized"]["cross_checks"] >= 1


def no_row_review(record_):
    """C-no-row-review: no unplaced line, chain break, rejected row, pending row or 'can't be told' issue."""
    assert [issue for issue in record_["issues"] if ROW_REVIEW.search(issue)] == []


def money(env_):
    """C-money: every transaction's amount is an integer, in USD."""
    assert env_.sql("SELECT count(*) FROM transactions WHERE typeof(amount_minor)<>'integer' OR currency<>'USD'")[0][0] == 0


def expected_wf():
    return [(row[6], row[7], row[2]) for row in tf.WF_ROWS]


def same_wf(got, want):
    """G8: where a check number goes is open; the description holds the printed words, and it is never an amount."""
    return got[0] == want[0] and got[1] == want[1] and want[2] in got[2] and got[2].replace(want[2], "").strip() in ("", "1201", "1202")


def exact_wf(recorded):
    got = rows_of(recorded)
    assert len(got) == 7 and all(same_wf(one, other) for one, other in zip(got, expected_wf())), got
    assert not {120100, 120200, 300000, 276545, 156545, 111345, 211345} & {amount for _, amount, _ in got}


def expected_dm():
    return [(row[5], row[6], row[1]) for row in tf.DM_ROWS]


def shown(env_, record_):
    response = env_.client.get(f"/api/finance/records/statement/{record_['id']}")
    assert response.status_code == 200, response.text
    return response.json()


# --- SC-01: the Wells Fargo-style statement ---------------------------------------------------------------------------------------------

def test_the_extraction_version_names_the_table_engine():
    assert extraction.EXTRACTION_VERSION != "typed-extraction-v32-table-engine"  # Bumped since (receipt-tax-codes): a v32 reading is read again.


def test_sc01_wf_records_every_row_from_the_printed_columns_and_shows_the_printed_balances(env, local_model):
    def wrong(lines):  # A model's row that matches no engine row (FR-18).
        return [row_stub(lines, "2026-10-02", "PAYROLL SYNTH CO", "3,000.00", "credit", "10/2 PAYROLL SYNTH CO")]
    recorded, result = recorded_fixture(env, local_model, "WF")
    assert [page.layout.issues for page in result.pages] == [["unresolved_columns"]]  # P-check: one embedded_text page (the old header rules build no table).
    before = env.files()
    record_ = recorded.run(replies("WF", wrong))
    exact_wf(recorded)
    reconciles(recorded, record_)
    checked(recorded)
    no_row_review(record_)
    money(env)
    assert len([note for note in recorded.notes() if "printed columns don't have" in note]) == 1  # The wrong stub row is one record note (statement-accounts FR-20).
    assert not any(note.startswith("The printed ") for note in recorded.notes())  # The model's balances agree with the printed ones.
    assert env.files() == before  # C-docs
    # The two dated balance lines are summary anchors: no unplaced line, no issue quoting them.
    assert not any("Beginning balance" in issue or "Ending balance" in issue for issue in record_["issues"])
    page = shown(env, record_)
    assert (page["opening_balance_minor"], page["closing_balance_minor"]) == (100000, 211345)
    assert [row[0] for row in env.sql("SELECT review_status FROM statements")] in (["proposed"], ["needs_review"])


def test_sc01_wf_summary_off_the_record_still_shows_the_printed_balances_and_notes_the_differences(env, local_model):
    pages = tf.wf_pages()
    pages[0]["items"] = [*pages[0]["items"], (40, 500, "Average collected 1,100.00"), (40, 488, "Available now 2,213.45")]
    recorded, _ = recorded_fixture(env, local_model, "WF-summary-off", pages)
    record_ = recorded.run(replies("WF-summary-off"))
    exact_wf(recorded)
    page = shown(env, record_)
    assert (page["opening_balance_minor"], page["closing_balance_minor"]) == (100000, 211345)
    notes = [note for note in recorded.notes() if note.startswith("The printed ")]
    assert len(notes) == 2 and "1,000.00" in notes[0] and "1,100.00" in notes[0] and "2,113.45" in notes[1] and "2,213.45" in notes[1]
    assert "opening" in notes[0] and "closing" in notes[1]
    assert not any(ARITHMETIC in issue for issue in record_["issues"])


def test_sc01_wf_flag_reads_the_same_rows_and_the_statement_needs_review_naming_the_page(env, local_model):
    recorded, record_ = record(env, local_model, "WF-flag")
    exact_wf(recorded)
    assert record_["review_status"] == "needs_review"
    assert any(issue.startswith("Page 1 PDF layout needs review: ") for issue in record_["issues"])
    money(env)


# --- SC-02: the DD/MM/YYYY statement ------------------------------------------------------------------------------------------------------

def test_sc02_dm_reads_every_date_day_first_and_reconciles(env, local_model):
    recorded, result = recorded_fixture(env, local_model, "DM")
    assert len(fx.visual_rows(result, 1)) >= 20  # P-check
    record_ = recorded.run(replies("DM"))
    exact(recorded, expected_dm())
    dates = {posted for posted, _, _ in rows_of(recorded)}
    assert not dates & {"2026-01-10", "2026-02-10", "2026-03-10", "2026-05-10", "2026-06-10", "2026-08-10", "2026-12-10"}
    reconciles(recorded, record_)
    checked(recorded)
    no_row_review(record_)
    money(env)


# --- SC-03: wrapped descriptions and their source -----------------------------------------------------------------------------------------

def expected_wr():
    return [(row[8], row[7], row[6]) for row in tf.WR_ROWS]


def provenance(env_, recorded, description):
    """(the stored locator, the provenance API's answer) of the transaction with this description."""
    [(txn,)] = env_.sql("SELECT id FROM transactions WHERE statement_id=? AND description_raw=?", recorded.record["id"], description)
    [(locator,)] = env_.sql("SELECT locator_json FROM financial_evidence_links WHERE record_type='transaction' AND record_id=? ORDER BY id DESC LIMIT 1", txn)
    response = env_.client.get(f"/api/provenance/transaction/{txn}")
    assert response.status_code == 200, response.text
    return json.loads(locator), response.json()["provenance"]


def test_sc03_wrapped_rows_keep_their_whole_description_and_cite_every_line(env, local_model):
    recorded, result = recorded_fixture(env, local_model, "WR")
    printed = [line.text for line in result.pages[0].layout.lines]
    assert "SAVINGS ACCOUNT ENDING ALPHA" in printed and "HARDWARE SUPPLY STORE" in printed and "SPRINGFIELD US" in printed  # P-check: each its own visual line.
    record_ = recorded.run(replies("WR"))
    # 1. C-exact(WR).
    exact(recorded, expected_wr())
    reconciles(recorded, record_)
    checked(recorded)
    assert not any("No date is printed" in issue for issue in record_["issues"])
    layout = result.pages[0].layout
    texts = {line.id: line.text for line in layout.lines}
    words = {word.id: word.text for word in layout.words}
    # 2. r6 cites its three lines, in printed order, every word of them, and one quote per line.
    locator, found = provenance(env, recorded, "CARD PURCHASE SYNTH HARDWARE SUPPLY STORE SPRINGFIELD US")
    assert locator["rebuilt"] is True and locator["page"] == 1 and len(locator["line_ids"]) == 3
    assert [texts[line] for line in locator["line_ids"]] == [
        "11/20/2026 CARD PURCHASE SYNTH 129.99 1,757.66", "HARDWARE SUPPLY STORE", "SPRINGFIELD US"]
    assert sorted(words[word] for word in locator["word_ids"]) == sorted(
        ["11/20/2026", "CARD", "PURCHASE", "SYNTH", "129.99", "1,757.66", "HARDWARE", "SUPPLY", "STORE", "SPRINGFIELD", "US"])
    assert locator["quotes"] == [texts[line] for line in locator["line_ids"]] and len(locator["quotes"]) == 3
    assert found["kind"] == "extracted" and found["document"]["lines"] == locator["line_ids"] and found["document"]["page"] == 1
    assert found["document"]["id"] == recorded.doc["id"]
    # 3. The same for r5, two lines.
    locator, found = provenance(env, recorded, "ONLINE TRANSFER TO SYNTH SAVINGS ACCOUNT ENDING ALPHA")
    assert [texts[line] for line in locator["line_ids"]] == ["11/14/2026 ONLINE TRANSFER TO SYNTH 300.00 1,887.65", "SAVINGS ACCOUNT ENDING ALPHA"]
    assert {"SAVINGS", "ACCOUNT", "ENDING", "ALPHA", "300.00", "1,887.65"} <= {words[word] for word in locator["word_ids"]}
    assert len(locator["quotes"]) == 2 and found["document"]["lines"] == locator["line_ids"]


def test_sc03_wr_split_joins_the_date_line_to_the_amount_line_and_lists_the_memo_line_as_a_rejected_row(env, local_model):
    recorded, result = recorded_fixture(env, local_model, "WR-split")
    record_ = recorded.run(replies("WR-split"))
    exact(recorded, expected_wr())
    texts = {line.id: line.text for line in result.pages[0].layout.lines}
    locator, _ = provenance(env, recorded, "DEPOSIT SYNTH MOBILE CHECK")
    assert [texts[line] for line in locator["line_ids"]] == ["11/25/2026 DEPOSIT SYNTH", "MOBILE CHECK 250.00 2,007.66"]
    [issue] = [issue for issue in record_["issues"] if issue.startswith("Page 1 row ")]
    assert issue.startswith("Page 1 row 8: ") and len(issue) > len("Page 1 row 8: ")  # Page 1, the memo line's row (the eighth), and a reason.
    assert record_["review_status"] == "needs_review"
    assert "2026-11-27" not in {posted for posted, _, _ in rows_of(recorded)}


# --- SC-04: one date per day --------------------------------------------------------------------------------------------------------------

def test_sc04_od_dateless_rows_take_the_date_above_with_one_note_each_and_no_review_reason(env, local_model):
    recorded, result = recorded_fixture(env, local_model, "OD")
    assert len([line for line in result.pages[0].layout.lines if re.match(r"^12/\d\d ", line.text)]) == 3  # P-check: three rows print a date.
    record_ = recorded.run(replies("OD"))
    exact(recorded, [(row[5], row[6], row[1]) for row in tf.OD_ROWS])
    assert [posted for posted, _, _ in rows_of(recorded)] == ["2026-12-03", "2026-12-03", "2026-12-05", "2026-12-05", "2026-12-05", "2026-12-09"]
    notes = [note for note in recorded.notes() if note.startswith("Page ")]  # Besides the currency note every fixture's `$` footer gives.
    assert len(notes) == 3
    for note, number, carried in zip(notes, (2, 4, 5), ("12/03/2026", "12/05/2026", "12/05/2026")):
        assert note.startswith(f"Page 1 row {number}: no date is printed; it takes ") and carried in note
    reconciles(recorded, record_)
    checked(recorded)
    no_row_review(record_)
    assert not any("No date is printed" in issue for issue in record_["issues"])


# --- SC-05: no headings, columns in another order ------------------------------------------------------------------------------------------

def test_sc05_wf_bare_finds_the_roles_by_the_balance_chain(env, local_model):
    recorded, result = recorded_fixture(env, local_model, "WF-bare")
    printed = " ".join(line.text for line in result.pages[0].layout.lines)
    assert not any(word in printed for word in ("Description", "balance ", "Date Number")) or "Beginning balance" in printed  # P-check: no heading word below the lines above.
    reading = statement_tables.read(result, statement_type="bank", currency="USD")
    [table_roles] = reading.roles.values()
    assert list(table_roles.values())[-3:] == ["balance", "out", "in"]  # 330 is the balance, 410 money out, 490 money in.
    record_ = recorded.run(replies("WF-bare"))
    exact_wf(recorded)
    reconciles(recorded, record_)
    checked(recorded)


# --- SC-06: a broken chain, and too few rows ----------------------------------------------------------------------------------------------------

def test_sc06_a_brk_the_chain_break_names_row_14_and_the_row_is_recorded_as_printed(env, local_model):
    recorded, record_ = record(env, local_model, "BRK")
    want = expected_dm()
    want[13] = (tf.BRK_EXPECTED[0], tf.BRK_EXPECTED[1], want[13][2])
    exact(recorded, want)
    chain = [issue for issue in record_["issues"] if "doesn't follow from the row above" in issue]
    assert chain == ["Page 1 row 14: the balance 31,165.10 doesn't follow from the row above"]
    assert record_["review_status"] == "needs_review"


def test_sc06_b_one_row_takes_its_sign_from_the_heading_and_says_why_it_needs_review(env, local_model):
    recorded, record_ = record(env, local_model, "ONE")
    exact(recorded, [(tf.ONE_ROW[3], tf.ONE_ROW[4], tf.ONE_ROW[1])])
    assert record_["review_status"] == "needs_review"
    [reason] = [issue for issue in record_["issues"] if issue.startswith("Page 1:") and "too few rows" in issue]
    assert "signs" in reason


# --- SC-07: signs from the summary and from sections --------------------------------------------------------------------------------------------

def test_sc07_cs_card_signs_come_from_the_sections_and_the_card_check_holds(env, local_model):
    recorded, record_ = record(env, local_model, "CS")
    exact(recorded, [(row[4], row[5], row[2]) for row in tf.CS_ROWS])
    assert [amount > 0 for _, amount, _ in rows_of(recorded)] == [True, True, False, False, False, False]
    reconciles(recorded, record_)
    checked(recorded)
    no_row_review(record_)


def test_a_card_statement_that_prints_only_its_closing_date_places_its_year_less_rows_before_it(env, local_model, monkeypatch):
    """No period is printed, only the closing date, and the rows print month and day: the reading's closing date places them
    (docs/documents.md "Statement rows from the printed columns"). Without a start date every row waited for a year and the
    statement had no rows at all."""
    monkeypatch.setattr(tf, "CS_ABOVE", (*tf.CS_ABOVE[:4], "Closing Date 11/04/2026"))
    chosen = {**SPECS["CS"], "period": None}
    base = replies(chosen)

    def make(lines):
        answer = base(lines)
        answer["CreditCardStatementSummary"][0]["period_end"] = cited(lines, "2026-11-04", "Closing Date", "11/04/2026")
        return answer
    recorded, record_ = recorded_fixture(env, local_model, "CS")
    record_ = recorded.run(make)
    exact(recorded, [(row[4], row[5], row[2]) for row in tf.CS_ROWS])
    reconciles(recorded, record_)


def test_a_card_period_printed_with_two_digit_years_places_the_rows_without_the_reading(env, local_model, monkeypatch):
    """`Opening/Closing Date 10/05/26 - 11/04/26` is the printed period, though its years have two digits: the rows' month and day
    are placed in it even when the reading gives no period (docs/documents.md "Statement rows from the printed columns")."""
    monkeypatch.setattr(tf, "CS_ABOVE", (*tf.CS_ABOVE[:4], "Opening/Closing Date 10/05/26 - 11/04/26"))
    recorded, _ = recorded_fixture(env, local_model, "CS")
    record_ = recorded.run(replies({**SPECS["CS"], "period": None}))
    exact(recorded, [(row[4], row[5], row[2]) for row in tf.CS_ROWS])
    reconciles(recorded, record_)


def test_a_cards_interest_rate_lines_under_its_charges_are_no_rows_and_no_review_reason(env, local_model):
    """The interest charge calculation printed under the charges, each line an APR, an expiry date or `-`, and `- 0 -` for its
    balance and interest: lines printing only zero amounts are no rows, and one note says so instead of a review reason per line
    (docs/documents.md "Statement rows from the printed columns")."""
    pages = tf.cs_pages()
    items = [item for item in pages[0]["items"] if item[1] > 520]  # The rows; the footer is printed again below the rate lines.
    for y, cells in ((500, [(40, "Purchases"), (180, "19.99% (v)"), (260, "11/04/26"), (420, "- 0 -", True)]),
                     (480, [(40, "Cash Advances"), (180, "29.99% (v)"), (260, "-"), (420, "- 0 -", True)])):
        items += tf.row_items(y, cells)
    pages = [{**pages[0], "items": [*items, tf.words_footer("SYNTH REWARDS CARD", 460)]}]
    recorded, record_ = record(env, local_model, "CS", pages=pages)
    exact(recorded, [(row[4], row[5], row[2]) for row in tf.CS_ROWS])
    reconciles(recorded, record_)
    no_row_review(record_)
    assert "Page 1: 2 lines printing only zero amounts (an interest-rate table, say) were not recorded." in recorded.notes()


def test_a_due_date_the_reading_gives_as_printed_with_a_two_digit_year_is_recorded(env, local_model, monkeypatch):
    """`Payment Due Date: 11/23/26` given back as printed: a day over 12 says which part is the month, and a two-digit year is
    20YY, so it is 2026-11-23 (docs/documents.md "Pay stub and statement fields"). A date either order could read stays unrecorded."""
    monkeypatch.setattr(tf, "CS_ABOVE", (*tf.CS_ABOVE, "Payment Due Date: 11/23/26", "Late fee after 12/05/26"))
    for printed, expected in (("11/23/26", "2026-11-23"), ("12/05/26", None)):
        base = replies("CS")

        def make(lines, printed=printed, base=base):
            answer = base(lines)
            needle = "Payment Due Date" if printed == "11/23/26" else "Late fee after"
            answer["CreditCardStatementSummary"][0]["due_date"] = cited(lines, printed, needle, printed)
            return answer
        recorded, _ = recorded_fixture(env, local_model, "CS", file=f"CS-due-{expected}")
        record_ = recorded.run(make)
        assert record_["due_date"] == expected, printed


def test_sc07_nb_the_summary_decides_which_column_is_money_out(env, local_model):
    recorded, record_ = record(env, local_model, "NB")
    exact(recorded, [(row[4], row[5], row[1]) for row in tf.NB_ROWS])
    assert [amount < 0 for _, amount, _ in rows_of(recorded)] == [False, True, True, False]  # A is money out (n2, n3), B money in (n1, n4).
    reconciles(recorded, record_)
    checked(recorded)


def test_sc07_nb_without_its_summary_lines_the_statement_needs_review(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "NB-plain", tf.nb_pages(summary=False))
    record_ = recorded.run(replies("NB-plain"))
    assert record_["review_status"] == "needs_review"


# --- SC-08: one table across three pages (Record) --------------------------------------------------------------------------------------------

def test_sc08_k3_record_reads_all_nine_rows_across_three_pages(env, local_model):
    pages = tf.k3_pages()  # K's footers print no `$`, so Record couldn't read the amounts as USD (the contract's conventions give every native page one).
    pages = [{**page, "items": [(x, y, text.replace(", kept", ", amounts shown in $, kept"), *rest) for x, y, text, *rest in page["items"]]} for page in pages]
    recorded, result = recorded_fixture(env, local_model, "K3", pages)
    assert fx.layout(result, 3).words[0].bbox != fx.layout(result, 2).words[0].bbox  # P-check: page 3 is drawn to the right.
    record_ = recorded.run(replies("K3"))
    exact(recorded, [(posted, row[7], row[3]) for posted, row in zip(fx.K_POSTED, fx.K_ROWS)])
    reconciles(recorded, record_)
    no_row_review(record_)
    money(env)


# --- SC-09: balance lines, totals and other tables ----------------------------------------------------------------------------------------------

def test_sc09_bl_balance_lines_totals_the_daily_and_fee_tables_and_the_schedule_give_no_rows(env, local_model):
    recorded, record_ = record(env, local_model, "BL")
    exact(recorded, [("2026-08-03", -70000, "RENT SYNTH"), ("2026-08-15", 250000, "PAYROLL SYNTH"), ("2026-08-20", 15000, "REFUND SYNTH SHOP")])
    assert len(rows_of(recorded)) == 3
    assert not {100000, 295000, 265000, 30000, 280000, 0, -12500} & {amount for _, amount, _ in rows_of(recorded)}
    assert not {"2026-09-15", "2026-10-15"} & {posted for posted, _, _ in rows_of(recorded)}
    reconciles(recorded, record_)
    no_row_review(record_)
    page = shown(env, record_)
    assert (page["opening_balance_minor"], page["closing_balance_minor"]) == (100000, 295000)


# --- SC-10: a printed line that fits no column ----------------------------------------------------------------------------------------------------

def test_sc10_up_the_courtesy_line_is_an_unplaced_line_and_a_review_reason(env, local_model):
    recorded, record_ = record(env, local_model, "UP")
    exact(recorded, [("2026-08-03", -70000, "RENT SYNTH"), ("2026-08-15", 250000, "PAYROLL SYNTH"), ("2026-08-20", 15000, "REFUND SYNTH SHOP")])
    assert 3500 not in {amount for _, amount, _ in rows_of(recorded)}
    assert record_["review_status"] == "needs_review"
    [issue] = [issue for issue in record_["issues"] if "wasn't placed in any column" in issue]
    assert issue.startswith("Page 1: ") and "08/12/2026 SYNTH COURTESY CREDIT 35.00" in issue


# --- SC-11: a page with no table ----------------------------------------------------------------------------------------------------------------

def fee_answers(lines):
    fee = [row_stub(lines, "2026-08-28", "PAPER STATEMENT FEE", "2.50", "debit", "A paper statement fee of 2.50")]
    return [{"transactions": fee}, {"transactions": []}]


def test_sc11_pr_page_two_keeps_the_models_row_and_carries_the_no_table_note(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "PR")
    record_ = recorded.run(replies("PR", answers=fee_answers))
    exact(recorded, [("2026-08-03", -70000, "RENT SYNTH"), ("2026-08-15", 250000, "PAYROLL SYNTH"), ("2026-08-20", 15000, "REFUND SYNTH SHOP"),
                     ("2026-08-28", -250, "PAPER STATEMENT FEE")])
    notes = recorded.notes()
    assert "Page 2: no table was found in the printed columns, so its rows are the reading's; check them." in notes
    assert not any(note.startswith("Page 1: no table") for note in notes) and sum("no table was found" in note for note in notes) == 1
    reconciles(recorded, record_)
    checked(recorded)


def test_sc11_pr_page_two_is_asked_about_again_with_its_own_lines_only(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "PR")
    before = len(local_model["requests"])
    recorded.run(replies("PR", answers=fee_answers))
    asked = [request for request in local_model["requests"][before:] if request["response_format"]["json_schema"]["name"] == "Transactions"]
    assert len(asked) == 2
    second = json.dumps(asked[1]["messages"])
    assert "Interest of 0.42" in second and "RENT SYNTH" not in second


# --- SC-13: Extract again on an old-path library -------------------------------------------------------------------------------------------------

def old_path_statement(doc, rows, last_four="4417"):
    """DM as the old path published it: bank statement SYNTH DAYFIRST BANK ...4417 with these rows (the smallest direct path: `Ledger.publish_statement`)."""
    return {"statement_type": "bank", "institution": "SYNTH DAYFIRST BANK", "last_four": last_four, "currency": "USD", "period_start": "2026-10-01",
            "period_end": "2026-10-31", "opening_balance_minor": 1000000, "closing_balance_minor": 3375410, "summary": {}, "issues": [],
            "locator": {"line_ids": ["page-1-line-1"]},
            "transactions": [{"posted_date": posted, "description": text, "amount_minor": amount, "currency": "USD", "locator": {"line_ids": ["page-1-line-2"]}}
                             for posted, amount, text in rows]}


def month_first_rows():
    """DM rows 1-8 with month-first dates, as the old path read them."""
    dates = ["2026-01-10", "2026-02-10", "2026-03-10", "2026-05-10", "2026-06-10", "2026-08-10", "2026-10-10", "2026-12-10"]
    return [(posted, row[6], row[1]) for posted, row in zip(dates, tf.DM_ROWS)]


def test_sc13_extract_again_rebuilds_the_undecided_statement_and_keeps_the_one_you_confirmed(env, local_model):
    y, _ = recorded_fixture(env, local_model, "DM", file="y")
    z_pages = tf.dm_pages()
    z_pages[0]["items"] = [(x, yy, "SYNTH DAYFIRST BANK statement page one of one, amounts shown in $ kept again" if text.startswith("SYNTH DAYFIRST BANK statement") else text)
                           for x, yy, text, *rest in z_pages[0]["items"] for rest in [()]]
    z, _ = recorded_fixture(env, local_model, "DM", z_pages, file="z")
    assert y.doc["current_hash"] != z.doc["current_hash"]
    ledger = env.manager.ledger
    old_y = ledger.publish_statement(old_path_statement(y.doc, month_first_rows()), {"document_id": y.doc["id"], "blob_hash": y.doc["current_hash"],
                                                                                    "source_key": "extraction:old", "run_id": "old"}, "needs_review")
    # Z sits in its own account (…4418): in one account the ledger drops a row already held by another statement (same date, amount and text), and Y's
    # row 7 (2026-10-10 INTEREST CREDIT) is printed the same by both readings.
    old_z = ledger.publish_statement(old_path_statement(z.doc, month_first_rows(), "4418"), {"document_id": z.doc["id"], "blob_hash": z.doc["current_hash"],
                                                                                    "source_key": "extraction:old", "run_id": "old"}, "needs_review")
    response = env.client.post(f"/api/finance/records/statement/{old_z['id']}/review", json={"status": "verified"})
    assert response.status_code == 200, response.text
    before = env.sql("SELECT * FROM statements WHERE id=?", old_z["id"]), env.sql("SELECT * FROM transactions WHERE statement_id=? ORDER BY id", old_z["id"])
    # Z: kept as you reviewed it.
    z.run(replies("DM"), force=True)
    assert z.extraction["publication"]["status"] == "kept_reviewed"
    assert (env.sql("SELECT * FROM statements WHERE id=?", old_z["id"]), env.sql("SELECT * FROM transactions WHERE statement_id=? ORDER BY id", old_z["id"])) == before
    assert len(before[1]) == 8
    # Y: rebuilt from the printed columns, no month-first date left.
    record_ = y.run(replies("DM"), force=True)
    assert record_["id"] == old_y["id"]
    # Row 7 (2026-10-10) is printed the same by both readings, so it keeps its id and now sits first; the rows are compared in date order (DM prints them so).
    assert sorted(rows_of(y)) == sorted((posted, amount, collapse(text)) for posted, amount, text in expected_dm()) and len(rows_of(y)) == 20
    assert not {posted for posted, _, _ in rows_of(y)} & {"2026-01-10", "2026-02-10", "2026-03-10", "2026-05-10", "2026-06-10", "2026-08-10", "2026-12-10"}


def dm_z_pages():
    """Z is DM with its footer text changed so the hashes differ."""
    pages = tf.dm_pages()
    pages[0]["items"] = [(x, y, "SYNTH DAYFIRST BANK statement page one of one, amounts shown in $ kept again" if text.startswith("SYNTH DAYFIRST BANK statement") else text)
                         for x, y, text, *rest in pages[0]["items"]]
    return pages


def reopened(recorded, env_, model):
    """The same Record handle after a restart: the store of the reopened library, the saved reading's lines."""
    service = ReceiptService(env_.store)
    parse_id = recorded.parse_id
    return Recorded(env_.store, service, {"id": recorded.doc["id"]}, parse_id, sf.reading_lines(read_result(service.get(parse_id)["result"])), model)


def snapshot(env_):
    return (env_.sql("SELECT * FROM statements ORDER BY id"), env_.sql("SELECT * FROM transactions ORDER BY id"))


def journey_j1_state(env_, model):
    """DM captured and read twice (Y and Z, one account …4417), published with the old path's month-first rows, Z confirmed, both index rows
    at the version before this feature (the contract's Doubles: `Ledger.publish_statement`, then `POST …/review`, then direct SQL)."""
    y, _ = recorded_fixture(env_, model, "DM", file="y")
    z, _ = recorded_fixture(env_, model, "DM", dm_z_pages(), file="z")
    assert y.doc["current_hash"] != z.doc["current_hash"]
    ledger = env_.manager.ledger
    # Z is published first: in one account the ledger leaves a row the account already holds out of the statement published after it, so Z keeps
    # its 8 rows and Y, offered the same 8, holds none until Extract again.
    old_z = ledger.publish_statement(old_path_statement(z.doc, month_first_rows()), {"document_id": z.doc["id"], "blob_hash": z.doc["current_hash"],
                                                                                    "source_key": "extraction:old", "run_id": "old"}, "needs_review")
    old_y = ledger.publish_statement(old_path_statement(y.doc, month_first_rows()), {"document_id": y.doc["id"], "blob_hash": y.doc["current_hash"],
                                                                                    "source_key": "extraction:old", "run_id": "old"}, "needs_review")
    response = env_.client.post(f"/api/finance/records/statement/{old_z['id']}/review", json={"status": "verified"})
    assert response.status_code == 200, response.text
    with env_.store.connection() as db:
        db.execute("UPDATE pdf_import_index SET analyzer_version = 2")
    return y, z, old_y, old_z


def wait_for_the_index(env_):
    for _ in range(600):  # The backfill runs on the capture queue, started by opening the library.
        if not env_.manager.busy():
            return
        time.sleep(.05)
    raise AssertionError("the index job did not finish")


def test_journey_j1_an_upgraded_library_is_indexed_again_and_extract_again_rebuilds_only_the_statement_you_did_not_confirm(tmp_path, local_model):
    """SC-13 + SC-22 (J1), as amended 2026-10-31: Y and Z are in ONE account. The ledger leaves a row the account already holds out of a statement as a
    duplicate, and DM's row 7 (2026-10-10 INTEREST CREDIT) reads the same both ways, so after Extract again Y holds 19 rows, and Z (confirmed) still
    holds its 8. Starting the app changes no statement or transaction."""
    with opened(tmp_path) as first:
        y, z, old_y, old_z = journey_j1_state(first, local_model)
        fingerprints = first.sql("SELECT parse_run_id,created_at FROM pdf_import_index ORDER BY parse_run_id")
        assert len(first.sql("SELECT id FROM transactions WHERE statement_id=?", old_z["id"])) == 8
        before = snapshot(first)
        migrations = first.sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        with first.store.connection() as db:
            waiting = pdf_import.pending(db)
        assert sorted(waiting) == sorted([first.reading(y.doc), first.reading(z.doc)])  # Checkpoint 1: both readings wait for the index ...
        assert candidates(first)["indexing"] is True  # ... and the picker says so.
    with opened(tmp_path, configure=False) as second:  # Start the app.
        wait_for_the_index(second)
        assert snapshot(second) == before  # No transaction or statement changed.
        rows = second.sql("SELECT parse_run_id,analyzer_version FROM pdf_import_index ORDER BY parse_run_id")  # Checkpoint 2.
        assert len(rows) == 2 and all(version == pdf_import.ANALYZER_VERSION > 2 for _, version in rows)
        assert candidates(second)["indexing"] is False
        indexed = second.sql("SELECT parse_run_id,created_at FROM pdf_import_index ORDER BY parse_run_id")
    with opened(tmp_path, configure=False) as third:  # Start-up again does not index again.
        wait_for_the_index(third)
        with third.store.connection() as db:
            assert pdf_import.pending(db) == []
        assert third.sql("SELECT parse_run_id,created_at FROM pdf_import_index ORDER BY parse_run_id") == indexed != fingerprints
        z_again, y_again = reopened(z, third, local_model), reopened(y, third, local_model)
        held = third.sql("SELECT * FROM transactions WHERE statement_id=? ORDER BY id", old_z["id"])
        statement = third.sql("SELECT * FROM statements WHERE id=?", old_z["id"])
        # Checkpoint 3: Extract again on Z keeps the statement you confirmed, and its 8 rows.
        z_again.run(replies("DM"), force=True)
        assert z_again.extraction["publication"]["status"] == "kept_reviewed"
        assert third.sql("SELECT * FROM transactions WHERE statement_id=? ORDER BY id", old_z["id"]) == held and len(held) == 8
        assert third.sql("SELECT * FROM statements WHERE id=?", old_z["id"]) == statement
        # Checkpoint 4: Extract again on Y gives DM's 20 rows except the one Z holds, with no month-first date left.
        record_ = y_again.run(replies("DM"), force=True)
        assert record_["id"] == old_y["id"]
        want = [(posted, amount, collapse(text)) for posted, amount, text in expected_dm() if (posted, text) != ("2026-10-10", "INTEREST CREDIT")]
        assert len(want) == 19 and rows_of(y_again) == want
        month_first = {"2026-01-10", "2026-02-10", "2026-03-10", "2026-05-10", "2026-06-10", "2026-08-10", "2026-12-10"}
        assert not {posted for posted, _, _ in rows_of(y_again)} & month_first
        assert len(third.sql("SELECT id FROM transactions WHERE statement_id=?", old_z["id"])) == 8  # Z unchanged.
        assert third.sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") == migrations  # No schema change.
        money(third)


# --- SC-14: determinism ---------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["WF", "WR"])
def test_sc14_extract_again_gives_identical_transactions_and_locators(env, local_model, name):
    recorded, _ = recorded_fixture(env, local_model, name)
    recorded.run(replies(name))

    def snapshot():
        rows = env.sql("SELECT id,posted_date,amount_minor,description_raw FROM transactions ORDER BY id")
        locators = {}
        for txn, locator in env.sql("SELECT record_id,locator_json FROM financial_evidence_links WHERE record_type='transaction'"):
            locators.setdefault(txn, set()).add(locator)
        return rows, locators
    first = snapshot()
    asked = len(local_model["requests"])
    recorded.run(replies(name), force=True)
    assert snapshot() == first
    assert all(len(locators) == 1 for locators in first[1].values()) and len(first[0]) == 7
    assert sorted({request["response_format"]["json_schema"]["name"] for request in local_model["requests"][asked:]}) == [
        "BankStatementSummary", "Classification", "Transactions"]  # Only the stubbed reasoning calls; the engine asks for nothing.


# --- SC-16: dates whose order can't be told --------------------------------------------------------------------------------------------------------

def prior_pages(last_four="7788"):
    pages = tf.nd_prior_pages()
    pages[0]["items"] = [(x, y, text.replace("0000007788", f"00000077{last_four[2:]}")) for x, y, text, *rest in pages[0]["items"]]
    return pages


def test_sc16_a_nd_records_nothing_and_says_once_per_page_that_the_order_cant_be_told(env, local_model):
    recorded, record_ = record(env, local_model, "ND")
    assert recorded.transactions() == []
    issues = [issue for issue in record_["issues"] if "can't be told" in issue]
    assert len(issues) == 2 and issues[0].startswith("Page 1 ") and issues[1].startswith("Page 2 ")
    assert record_["review_status"] == "needs_review"


def test_sc16_a2_a_page_the_engine_records_nothing_from_keeps_the_readings_rows_for_review(env, local_model):
    # User report: a card statement whose printed columns gave no rows recorded none at all, listing every row as a note.
    def rows(lines):
        return [row_stub(lines, "2026-03-04", "ALPHA", "10.00", "credit", "ALPHA"), row_stub(lines, "2026-04-06", "CHARLIE", "1.00", "credit", "CHARLIE")]
    recorded, record_ = record(env, local_model, "ND", rows=rows)
    assert [(posted, amount) for posted, amount, _ in rows_of(recorded)] == [("2026-03-04", 1000), ("2026-04-06", 100)]
    assert record_["review_status"] == "needs_review" and any("can't be told" in issue for issue in record_["issues"])
    assert any("the reading's rows were recorded there" in note for note in recorded.notes())
    assert not any("printed columns don't have" in note for note in recorded.notes())


def test_sc16_b_nd_follows_the_order_of_an_earlier_statement_of_the_same_account(env, local_model):
    prior, record_prior = record(env, local_model, "ND-prior", file="prior")
    assert [(posted, amount) for posted, amount, _ in rows_of(prior)] == [("2026-02-15", 300), ("2026-02-16", 100)]
    assert not any("can't be told" in issue for issue in record_prior["issues"])
    recorded, record_ = record(env, local_model, "ND", file="nd")
    assert [(posted, amount) for posted, amount, _ in rows_of(recorded)] == tf.ND_EXPECTED_DAY_FIRST
    assert not any("can't be told" in issue for issue in record_["issues"])


def test_sc16_c_another_last_four_leaves_nd_as_in_a(env, local_model):
    SPECS["ND-prior-7799"] = {**SPECS["ND-prior"], "ref": ("7799", "Account number")}
    try:
        prior, _ = recorded_fixture(env, local_model, "ND-prior", prior_pages("7799"), file="prior")
        prior.run(replies("ND-prior-7799"))
    finally:
        del SPECS["ND-prior-7799"]
    recorded, record_ = record(env, local_model, "ND", file="nd")
    assert recorded.transactions() == [] and len([issue for issue in record_["issues"] if "can't be told" in issue]) == 2


def test_sc16_prior_order_on_a_real_migrated_library_reads_the_newest_other_statement_of_the_account(env, local_model):
    """OD-2 on the real schema (carried from SL-03): `statement_tables.prior_order` finds the order the account's other statements decide."""
    prior, _ = record(env, local_model, "ND-prior", file="prior")
    nd, _ = recorded_fixture(env, local_model, "ND", file="nd")
    with env.store.connection() as db:
        assert statement_tables.prior_order(db, "7788", nd.doc["id"]) == "DD/MM/YYYY"
        assert statement_tables.prior_order(db, "7788", prior.doc["id"]) is None  # Its own document is not "earlier".
        assert statement_tables.prior_order(db, "7799", nd.doc["id"]) is None
        assert statement_tables.prior_order(db, None, nd.doc["id"]) is None


# --- SC-17: two accounts in one PDF ---------------------------------------------------------------------------------------------------------------

def test_sc17_cc_both_tables_are_recorded_with_one_two_accounts_issue(env, local_model):
    recorded, record_ = record(env, local_model, "CC")
    exact(recorded, [(row[5], row[6], row[2]) for row in tf.CC_ROWS])
    assert [amount for _, amount, _ in rows_of(recorded)] == [-10000, 25000, -5000, 100000, -20000, 215]
    [issue] = [issue for issue in record_["issues"] if "This PDF may hold more than one account" in issue]
    assert "page 1" in issue and "page 2" in issue
    assert not any("doesn't follow from the row above" in issue for issue in record_["issues"])
    assert record_["review_status"] == "needs_review"


# --- SC-19: the engine fails (Record) -----------------------------------------------------------------------------------------------------------------

def test_sc19_an_engine_fault_falls_back_to_the_models_rows_with_one_note_and_logs_no_document_text(env, local_model, monkeypatch, caplog):
    """Step 1 of SC-19, on fixture S (WF's native table has unresolved columns, so the old path would leave every model row out): the engine's
    entry points raise, the fallback is taken on every page, and the statement holds the stub's six rows, each amount from the native table cell it
    cites, as `test_sc18_p8_a_rebuild_that_fails_in_read...` asserts."""
    def raising(*args, **options):
        raise RuntimeError("injected engine fault")
    recorded, _ = recorded_fixture(env, local_model, "S", sf.s_pages())  # Captured (and indexed) before the fault, so the one logged failure is Record's.
    monkeypatch.setattr(statement_tables, "engine_pages", raising)
    monkeypatch.setattr(statement_tables, "read", raising)
    with caplog.at_level(logging.DEBUG):
        record_ = recorded.run(s_replies())
    assert [amount for _, amount, _ in recorded.transactions()] == [36, 2, -38, 150000, -50000, 2]
    assert record_["review_status"] == "needs_review"
    assert (record_["issues"] + recorded.notes()).count(REBUILD_FAILED) == 1
    assert env.sql("SELECT count(*) FROM financial_evidence_links WHERE locator_json LIKE '%\"rebuilt\": true%'")[0][0] == 0
    failures = [entry for entry in caplog.records if "failed" in entry.getMessage() and "RuntimeError" in entry.getMessage()]
    assert failures and len({entry.getMessage().split(" failed")[0] for entry in failures}) == 1  # The same failure, logged where it was caught.
    logged = " ".join(entry.getMessage() for entry in caplog.records)
    assert not any(text in logged for text in (*sf.S_DESCRIPTIONS, "SYNTH ACCTVERIFY", "PAYROLL SYNTH", "TRANSFER TO CHECKING", "1,500.00", "500.00", "000009000123456", "3456"))


# --- PDF import (SL-06): SC-08 step 2, SC-12, SC-16's preview, SC-19 step 2 ----------------------------------------------------------------------

def account_for(env_, name):
    """An account matching the fixture's summary stub (SC-12 step 1): its institution, kind (a card, a savings account for DM, else checking) and last four, in USD."""
    chosen = SPECS[name]
    kind = "credit_card" if chosen["kind"] == "card" else "savings" if name in ("DM", "BRK") else "checking"
    response = env_.client.post("/api/finance/accounts", json={"institution": chosen["name"], "account_type": kind, "currency": "USD", "last_four": chosen["ref"][0]})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def with_dollar_footers(pages):
    """K's footers print no `$`, so Record couldn't read the amounts as USD (the contract's conventions give every native page one)."""
    return [{**page, "items": [(x, y, text.replace(", kept", ", amounts shown in $, kept"), *rest) for x, y, text, *rest in page["items"]]} for page in pages]


def counts_of(env_):
    return [env_.sql(f"SELECT count(*) FROM {table}")[0][0] for table in ("transactions", "transaction_imports", "accounts")]


def preview_of(env_, doc, account_id, **choices):
    response = env_.preview(doc, account_id=account_id, **choices)
    assert response.status_code == 200, response.text
    return response.json()


def test_sc08_k3_pdf_import_previews_the_nine_rows_with_page_three_linked_to_page_one_import(env, local_model):
    pages = with_dollar_footers(tf.k3_pages())
    recorded, _ = recorded_fixture(env, local_model, "K3", pages)
    account_id = account_for(env, "K3")
    before = counts_of(env)
    preview = preview_of(env, recorded.doc, account_id)
    assert counts_of(env) == before  # A preview writes nothing.
    assert [(row["posted_date"], row["amount_minor"]) for row in preview["rows"]] == [(posted, row[7]) for posted, row in zip(fx.K_POSTED, fx.K_ROWS)]
    assert [row["description"] for row in preview["rows"]] == [row[3] for row in fx.K_ROWS]
    assert not [row for row in preview["rows"] if row["rejected"]] and preview["counts"]["rejected"] == 0 and preview["counts"].get("unplaced", 0) == 0
    assert not [issue for issue in preview["issues"] if issue["code"] in ("unplaced_line", "rejected_row")]
    keys = [row["key"] for row in preview["rows"]]
    assert len(set(keys)) == 9  # Unique across pages.
    first = next(table for table in preview["tables"] if table["kind"] != "continuation" and table["page"] == 1 and table["selectable"])
    third = [row for row in preview["rows"] if row["page"] == 3]
    assert len(third) == 3 and all(row["continued_from"] == 1 for row in third)
    assert [table["linked_to"] for table in preview["tables"] if table["page"] == 3] == [first["id"]]
    assert preview["required"] == [] and preview["blocked"] is None


SC12 = ["WF", "WF-bare", "DM", "WR", "OD", "CS", "NB", "K3", "BL", "UP", "CC", "FX", "PD", "TD"]


@pytest.mark.parametrize("name", SC12)
def test_sc12_the_preview_agrees_with_record_import(env, local_model, name):
    """SC-12: for each fixture in a fresh library, an account matching the summary stub, a preview with no choices (nothing is required: the engine
    reads the printed period, the date order and the signs), then Record of the same reading. The preview's parsed, ticked rows in printed order
    equal the recorded transactions; UP's and PD's unplaced lines are listed with page and text and are not importable."""
    pages = with_dollar_footers(tf.FIXTURES[name]()) if name == "K3" else None
    recorded, _ = recorded_fixture(env, local_model, name, pages)
    blob = env.store.blob_path(recorded.doc["current_hash"])
    original = blob.read_bytes()
    account_id = account_for(env, name)
    before = counts_of(env)
    preview = preview_of(env, recorded.doc, account_id)
    assert counts_of(env) == before and blob.read_bytes() == original  # The preview writes nothing and leaves the original alone (C-docs).
    assert preview["required"] == [], preview["required"]  # No year, date-order or sign choice.
    chosen = SPECS[name]["period"]
    years = {int(chosen[0][:4]), int(chosen[1][:4])} if chosen else set()
    ticked = [row for row in preview["rows"] if row["ticked"] and not row["rejected"]]
    if years:
        assert {int(row["posted_date"][:4]) for row in ticked} <= years  # The printed period's year, for rows that print none.
    record_ = recorded.run(replies(name))
    assert blob.read_bytes() == original
    assert [(row["posted_date"], row["amount_minor"], collapse(row["description"])) for row in ticked] == rows_of(recorded), name
    assert ticked and len(ticked) == len(rows_of(recorded)) and not [row for row in preview["rows"] if row["rejected"]]
    unplaced = [issue for issue in preview["issues"] if issue["code"] == "unplaced_line"]
    in_record = [issue for issue in record_["issues"] if "wasn't placed in any column" in issue or "a pending row" in issue]
    assert [issue["message"] for issue in unplaced] == in_record, name  # Page and line text, as Record lists them.
    assert all(issue["page"] and "\"" in issue["message"] for issue in unplaced)
    assert preview["counts"].get("unplaced", 0) == len(unplaced) == {"UP": 1, "PD": 2}.get(name, 0)
    for issue in unplaced:  # Not rows, so not importable.
        quoted = issue["message"].split('"')[1]
        assert not [row for row in preview["rows"] if row["description"] and row["description"] in quoted]
    assert preview["counts"]["seen"] == len(preview["rows"]) + len(unplaced)  # The identity counts them (G13).


def test_sc16_nd_the_date_order_is_a_required_choice_in_the_preview_import(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "ND")
    account_id = account_for(env, "ND")
    before = counts_of(env)
    preview = preview_of(env, recorded.doc, account_id)
    assert preview["required"] == ["date_format"] and counts_of(env) == before
    chosen = preview_of(env, recorded.doc, account_id, date_format="DD/MM/YYYY")
    assert chosen["required"] == [] and [row["posted_date"] for row in chosen["rows"]] == [posted for posted, _ in tf.ND_EXPECTED_DAY_FIRST]


def test_sc19_an_engine_fault_is_refused_with_a_4xx_and_nothing_written_import(env, local_model, monkeypatch, caplog):
    """Step 2 of SC-19, on fixture S: the engine's entry point raises; the preview is a 4xx refusal with the message of G12, nothing is written, and the
    response holds no traceback; the log carries the exception and no fixture text."""
    recorded, _ = recorded_fixture(env, local_model, "S", sf.s_pages())
    account_id = env.client.post("/api/finance/accounts", json={"institution": "SYNTH BANK", "account_type": "savings", "currency": "USD", "last_four": "3456"}).json()["id"]
    before = counts_of(env)

    def raising(*args, **options):
        raise RuntimeError("injected engine fault")
    monkeypatch.setattr(statement_tables, "engine_pages", raising)
    monkeypatch.setattr(statement_tables, "read", raising)
    with caplog.at_level(logging.DEBUG):
        response = env.preview(recorded.doc, account_id=account_id)
    assert 400 <= response.status_code < 500, response.text
    assert "couldn't be read from its printed columns" in response.text and "Traceback" not in response.text and "injected engine fault" not in response.text
    assert counts_of(env) == before
    imported = env.run(recorded.doc, account_id=account_id, reading_id=env.reading(recorded.doc))
    assert 400 <= imported.status_code < 500 and counts_of(env) == before
    logged = " ".join(entry.getMessage() for entry in caplog.records)
    assert "RuntimeError" in logged and not any(text in logged for text in (*sf.S_DESCRIPTIONS, "SYNTH ACCTVERIFY", "000009000123456"))


# --- SC-23 – SC-25: card risks ---------------------------------------------------------------------------------------------------------------------

def test_sc23_fx_the_foreign_amount_and_rate_are_never_the_charge(env, local_model):
    recorded, record_ = record(env, local_model, "FX")
    exact(recorded, [(row[5], row[6], row[1]) for row in tf.FX_ROWS])
    assert not {9217, 3850, 10850, 12987} & {abs(amount) for _, amount, _ in rows_of(recorded)}
    reconciles(recorded, record_)
    checked(recorded)


def test_sc24_pd_pending_rows_are_not_recorded_and_each_is_a_review_reason(env, local_model):
    recorded, record_ = record(env, local_model, "PD")
    exact(recorded, [(row[4], row[5], row[2]) for row in tf.PD_ROWS[:2]])
    pending = [issue for issue in record_["issues"] if "a pending row" in issue]
    assert len(pending) == 2 and all(issue.startswith("Page 1: ") for issue in pending)
    assert "10/30 SYNTH HOTEL 200.00" in pending[0] and "10/31 SYNTH TAXI 12.50" in pending[1]
    assert record_["review_status"] == "needs_review"
    reconciles(recorded, record_)


@pytest.mark.parametrize("name", ["TD", "TD-bare"])
def test_sc25_two_date_columns_are_the_transaction_date_and_the_posted_date(env, local_model, name):
    recorded, record_ = record(env, local_model, name)
    exact(recorded, [(row[5], row[6], row[2]) for row in tf.TD_ROWS])
    dates = env.sql("SELECT transaction_date,posted_date FROM transactions WHERE statement_id=? ORDER BY id", recorded.record["id"])
    assert dates == [(row[4], row[5]) for row in tf.TD_ROWS]
    reconciles(recorded, record_)
    checked(recorded)


# --- SL-08: the code review's findings (plans/pdf-table-engine/progress.yaml SL-08) ---------------------------------------------------

def test_sl08_f3_brks_chain_break_is_in_the_preview_and_the_saved_import_import(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "BRK")
    account_id = account_for(env, "BRK")
    preview = preview_of(env, recorded.doc, account_id)
    [row] = [row for row in preview["rows"] if (row["posted_date"], row["amount_minor"]) == tf.BRK_EXPECTED]
    [issue] = [issue for issue in preview["issues"] if issue["code"] == "balance_chain_break"]
    assert (issue["page"], issue["row"]) == (1, row["row"])
    assert issue["message"].startswith(f"Page 1 row {row['row']}: the balance ") and issue["message"].endswith(" doesn't follow from the row above")
    env.ok_import(recorded.doc, reading=preview["reading_id"], account_id=account_id)
    [(saved,)] = env.sql("SELECT issues_json FROM transaction_imports")
    assert issue["message"] in json.dumps(json.loads(saved))


def test_sl08_f3_ccs_two_accounts_issue_is_in_the_preview_import(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "CC")
    preview = preview_of(env, recorded.doc, account_for(env, "CC"))
    assert [issue["message"] for issue in preview["issues"] if issue["code"] == "two_accounts"] == [statement_tables.TWO_ACCOUNTS.format(first=1, second=2)]


def test_sl08_f6_the_printed_period_is_the_records_when_the_reading_gives_none(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "WF")
    record_ = recorded.run(replies({**SPECS["WF"], "period": None}))
    exact_wf(recorded)
    assert env.sql("SELECT period_start, period_end FROM statements") == [("2026-10-01", "2026-10-31")]
    assert not any(note.startswith("The printed statement period") for note in recorded.notes())
    assert not any("period" in issue.lower() for issue in record_["issues"]), record_["issues"]


def test_sl08_f6_the_printed_period_wins_over_the_readings_with_a_note(env, local_model):
    recorded, _ = recorded_fixture(env, local_model, "WF")
    wrong = {**SPECS["WF"], "period": ("2026-09-01", "2026-09-30", "Statement period", "10/01/2026", "10/31/2026")}
    record_ = recorded.run(replies(wrong))
    exact_wf(recorded)
    assert env.sql("SELECT period_start, period_end FROM statements") == [("2026-10-01", "2026-10-31")]
    assert [note for note in recorded.notes() if note.startswith("The printed statement period")] == [
        "The printed statement period 2026-10-01 to 2026-10-31 was recorded; the reading gave 2026-09-01 to 2026-09-30."]
    assert not any("outside the statement period" in issue for issue in record_["issues"]), record_["issues"]
