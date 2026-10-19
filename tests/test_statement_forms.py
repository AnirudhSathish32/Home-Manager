"""Bank and card statement forms (specs/document-forms FR-25 – FR-29): printed summary details and the summary checks.
What a statement counts doesn't change (SC-24)."""

from contextlib import contextmanager
import json

import pytest

from document_forms_fixtures import BANK, CARD, MISSING, bank_replies, card_replies, cite, library, p_table, record_document, stored_identifiers, uncited, value
from home_manager.documents import extraction
from home_manager.documents.extraction import DETAILS_FAILED
from home_manager.finance import traces
from home_manager.finance.tools import AccountInput, FinanceTools, PeriodInput
from test_extraction import extract, transcribe
from test_paystub_forms import p_details, p_table_replies


@contextmanager
def read_statement(tmp_path, local_model, lines, replies):
    """Transcribe lines and record them with replies; yields (manager, run, record)."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        yield manager, run, manager.ledger.record("statement", run["publication"]["id"])
    finally:
        manager.close()


def stored_details(manager):
    with manager.store.connection() as db:
        text = db.execute("SELECT details_json FROM statements").fetchone()[0]
    return json.loads(text) if text else None


def without(lines, *starts):
    return [line for line in lines if not line.startswith(starts)]


def replaced(lines, start, line):
    return [line if text.startswith(start) else text for text in lines]


def test_sc22_bank_statement_fields_and_summary_check(tmp_path, local_model):
    with read_statement(tmp_path, local_model, BANK, bank_replies(BANK)) as (manager, run, record):
        assert record["review_status"] == "verified", record["issues"]
        assert run["result"]["normalized"]["cross_checks"] == 2  # The summary check and the transaction check.
        details = stored_details(manager)
        assert details["account_type"]["text"] == "checking"
        assert [details[name]["minor"] for name in ("deposits_total", "withdrawals_total", "interest_earned", "fees_total")] == [250000, 120050, 42, 0]
        assert details["apy"]["text"] == "0.50%"
        assert all(uncited(details[name], BANK) == [] for name in ("account_type", "deposits_total", "apy"))  # C-cite
        with manager.store.connection() as db:
            assert tuple(db.execute("SELECT json_type(details_json,'$.deposits_total.minor'),json_type(details_json,'$.apy.text') FROM statements")
                         .fetchone()) == ("integer", "text")  # C-money
            assert tuple(db.execute("SELECT account_last_four,account_type FROM accounts").fetchone()) == ("6789", "checking")
            assert stored_identifiers(db, ("000123456789", "021000021")) == []  # C-ids


def summary_trace(manager, record):
    [check] = [check for check in record["checks"] if check["name"] == "summary"]
    trace = traces.trace(manager.store, check["figure"]["trace"], manager)
    assert trace["result"]["minor"] == check["figure"]["minor"]
    return trace


def test_sc22_the_bank_summary_trace(tmp_path, local_model):
    with read_statement(tmp_path, local_model, BANK, bank_replies(BANK)) as (manager, _run, record):
        trace = summary_trace(manager, record)
        assert (trace["result"]["decimal"], trace["compared_with"]["decimal"], trace["reconciles"]) == ("2299.50", "2299.50", True)
        assert [(step["label"], step["op"], step["value"]["decimal"]) for step in trace["steps"]] == [
            ("Opening balance", "+", "1000.00"), ("Deposits", "+", "2500.00"), ("Withdrawals", "−", "1200.50")]
        assert all(item["provenance"]["kind"] == "extracted" and item["provenance"]["line_ids"] for item in trace["inputs"])


def test_sc22_a_the_bank_summary_trace_on_a_mismatch(tmp_path, local_model):
    lines = replaced(BANK, "CLOSING BALANCE", "CLOSING BALANCE 2,300.50")
    with read_statement(tmp_path, local_model, lines, bank_replies(lines)) as (manager, _run, record):
        trace = summary_trace(manager, record)
        assert (trace["compared_with"]["decimal"], trace["reconciles"]) == ("2300.50", False)


def test_sc23_the_card_summary_trace(tmp_path, local_model):
    with read_statement(tmp_path, local_model, CARD, card_replies(CARD)) as (manager, _run, record):
        trace = summary_trace(manager, record)
        assert (trace["result"]["decimal"], trace["reconciles"]) == ("792.45", True)
        assert [step["value"]["decimal"] for step in trace["steps"]] == ["500.00", "500.00", "20.00", "812.45", "0.00", "0.00"]


def test_sc23_a_the_card_summary_trace_on_a_mismatch(tmp_path, local_model):
    lines = replaced(CARD, "NEW BALANCE", "NEW BALANCE 795.45")
    with read_statement(tmp_path, local_model, lines, card_replies(lines)) as (manager, _run, record):
        assert summary_trace(manager, record)["reconciles"] is False


def test_sc22_a_statement_with_no_summary_terms_has_no_summary_figure(tmp_path, local_model):
    lines = without(BANK, "WITHDRAWALS ")
    with read_statement(tmp_path, local_model, lines, bank_replies(lines)) as (manager, _run, record):
        assert record["checks"] == []
        with pytest.raises(ValueError, match="This isn't worked out for this record."):
            traces.trace(manager.store, f"statement.summary?statement_id={record['id']}", manager)


def test_sc22_a_a_mismatching_closing_balance_fails_both_checks(tmp_path, local_model):
    lines = replaced(BANK, "CLOSING BALANCE", "CLOSING BALANCE 2,300.50")
    with read_statement(tmp_path, local_model, lines, bank_replies(lines)) as (_, run, record):
        assert record["review_status"] == "needs_review" and run["result"]["normalized"]["cross_checks"] == 0
        [summary] = [issue for issue in record["issues"] if issue.startswith("Closing balance: ")]
        assert summary == ("Closing balance: opening 1,000.00 + deposits 2,500.00 − withdrawals 1,200.50 = 2,299.50 USD, "
                           "but the printed closing balance is 2,300.50 USD.")
        assert any(issue.startswith("Statement arithmetic does not reconcile") for issue in record["issues"])


def test_sc22_b_no_type_word_is_other(tmp_path, local_model):
    lines = replaced(BANK, "EVERYDAY CHECKING", "ACCOUNT 000123456789")
    guessed = value(lines, "checking", "ACCOUNT 000123456789")  # Not printed as a word: never taken.
    with read_statement(tmp_path, local_model, lines, bank_replies(lines, account_type=guessed)) as (manager, _run, record):
        assert stored_details(manager)["account_type"]["text"] == "other" and record["review_status"] == "verified"
        with manager.store.connection() as db:
            assert db.execute("SELECT account_type FROM accounts").fetchone()[0] == "checking"  # The account itself doesn't change.


def test_sc22_c_without_a_withdrawals_total_the_summary_check_is_skipped(tmp_path, local_model):
    lines = without(BANK, "WITHDRAWALS ")
    with read_statement(tmp_path, local_model, lines, bank_replies(lines)) as (_, run, record):
        assert record["review_status"] == "verified" and run["result"]["normalized"]["cross_checks"] == 1


def test_sc23_card_statement_fields_and_summary_check(tmp_path, local_model):
    with read_statement(tmp_path, local_model, CARD, card_replies(CARD)) as (manager, run, record):
        assert record["review_status"] == "verified", record["issues"]
        assert run["result"]["normalized"]["cross_checks"] == 2
        details = stored_details(manager)
        assert (details["purchase_apr"]["text"], details["cash_advance_apr"]["text"]) == ("24.99%", "29.99%")
        assert (details["credit_limit"]["minor"], details["available_credit"]["minor"]) == (500000, 420755)
        rewards = details["rewards_earned"]
        assert (rewards["text"], rewards["unit"], rewards["minor"]) == ("812", "points", None)  # Points stay text, never money.


def test_sc23_a_a_mismatching_new_balance_goes_to_review(tmp_path, local_model):
    lines = replaced(CARD, "NEW BALANCE", "NEW BALANCE 795.45")
    with read_statement(tmp_path, local_model, lines, card_replies(lines)) as (_, _run, record):
        assert record["review_status"] == "needs_review"
        assert ("Statement balance: previous 500.00 − payments 500.00 − credits 20.00 + purchases 812.45 + fees 0.00 + interest 0.00 = 792.45 USD, "
                "but the printed statement balance is 795.45 USD.") in record["issues"]


def test_sc23_b_without_a_fees_line_the_summary_check_is_skipped(tmp_path, local_model):
    lines = without(CARD, "FEES CHARGED")
    with read_statement(tmp_path, local_model, lines, card_replies(lines)) as (_, run, record):
        assert record["review_status"] == "verified" and run["result"]["normalized"]["cross_checks"] == 1


def test_sc25_statement_identifiers_are_never_stored(tmp_path, local_model):
    """The stub returns the full account number, citing the account and routing lines."""
    account = "EVERYDAY CHECKING ACCOUNT 000123456789"
    full = {"value": "000123456789", "status": "proposed", "evidence": cite(BANK, account) + cite(BANK, "ROUTING 021000021")}
    with read_statement(tmp_path, local_model, BANK, bank_replies(BANK, account_reference=full)) as (manager, _run, _record):
        with manager.store.connection() as db:
            assert stored_identifiers(db) == []
            assert db.execute("SELECT account_last_four FROM accounts").fetchone()[0] == "6789"


def test_sc26_bank_details_that_fail_twice_are_left_out(tmp_path, local_model):
    """FR-14: the new fields fail twice (a deposits total not printed in its citation); the statement and its
    transactions publish as today, with no new field and the reason."""
    invented = value(BANK, "2,600.00", "DEPOSITS 2,500.00")
    replies = bank_replies(BANK, deposits_total=invented)
    replies["BankStatementSummary"] *= 2
    with read_statement(tmp_path, local_model, BANK, replies) as (manager, _run, record):
        assert record["review_status"] == "needs_review" and DETAILS_FAILED in record["issues"]
        assert (record["closing_balance_minor"], len(record["transactions"])) == (229950, 2)
        assert stored_details(manager) is None


def september(manager):
    """September 2026 as the app counts it: money in, spending and the bank account's balance (FinanceTools, as the API)."""
    tools, period = FinanceTools(manager.store), PeriodInput(start="2026-09-01", end="2026-09-30")
    cashflow = tools.calculate_cashflow(period)["by_currency"][0]
    spending = tools.get_spending(period)["by_currency"][0]
    bank = next(account for account in manager.ledger.accounts() if account["account_type"] == "checking")
    return {"in": cashflow["inflow"]["minor"], "spent": spending["net_spending"]["minor"], "refunds": spending["refunds"]["minor"],
            "balance": tools.get_account_balance(AccountInput(account_id=bank["id"]))["balance"]["minor"]}


def read_september(tmp_path, model):
    """SC-24's library: the P-sept pay stub verified, and the SC-22 and SC-23 statements released for reconciliation."""
    manager = library(tmp_path, model)
    lines, tables = p_table(period=("2026-09-01", "2026-09-14"), pay_date="2026-09-19")
    _, _, stub = record_document(manager, model, "stub.png", lines, p_table_replies(lines, hours="80.00", rate="31.25", **p_details(lines)), tables)
    assert stub["publication"]["review_status"] == "verified"
    for name, statement, replies in (("bank.png", BANK, bank_replies(BANK)), ("card.png", CARD, card_replies(CARD))):
        _, _, run = record_document(manager, model, name, statement, replies)
        assert run["publication"]["review_status"] == "verified"
        manager.reconciler.reconcile_statement(run["publication"]["id"])
    return manager


def test_sc24_counting_is_unchanged(tmp_path, local_model, monkeypatch):
    """FR-29: worked out from the fixture rows under today's rules. Money in: the paycheck at net 1,912.34 on its own
    (the bank's PAYROLL +2,500.00 isn't its net pay, so no deposit link forms) plus that deposit. Spending: RENT 1,200.50
    and the card purchase 812.45, net of its 20.00 refund. Interest 0.42 has no transaction row, so it isn't counted.
    The balance is the bank's closing 2,299.50. The same figures with the new fields not written."""
    expected = {"in": 191234 + 250000, "spent": 120050 + 81245 - 2000, "refunds": 2000, "balance": 229950}
    manager = read_september(tmp_path / "with", local_model)
    try:
        assert september(manager) == expected
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM transaction_income_links").fetchone()[0] == 0
    finally:
        manager.close()
    monkeypatch.setattr(extraction, "statement_details", lambda *args: None)
    monkeypatch.setattr(extraction, "pay_details", lambda *args: None)
    monkeypatch.setattr(extraction, "cited_label", lambda *args: None)
    manager = read_september(tmp_path / "without", local_model)
    try:
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM statements WHERE details_json IS NOT NULL").fetchone()[0] == 0
        assert september(manager) == expected
    finally:
        manager.close()


@pytest.mark.parametrize("field", ["deposits_total", "credit_limit"])
def test_a_missing_detail_is_never_filled_in(tmp_path, local_model, field):
    """FR-04's rule for statements too: an unprinted detail stays out, never 0."""
    lines, replies = (BANK, bank_replies(BANK, deposits_total=MISSING)) if field == "deposits_total" else (CARD, card_replies(CARD, credit_limit=MISSING))
    with read_statement(tmp_path, local_model, lines, replies) as (manager, _run, _record):
        assert field not in stored_details(manager)
