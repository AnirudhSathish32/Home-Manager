"""Bank and card statement forms (specs/document-forms FR-25 – FR-29): printed summary details and the summary checks.
What a statement counts doesn't change (SC-24)."""

from contextlib import contextmanager
import json

import pytest

from document_forms_fixtures import (
    BANK,
    CARD,
    MISSING,
    at,
    bank_replies,
    card_replies,
    cite,
    library,
    p_table,
    record_document,
    stored_identifiers,
    uncited,
    value,
)
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
        assert record["review_status"] == "proposed", record["issues"]  # FR-04: its account is new, so it waits for Confirm; the checks pass.
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


# Account-verification deposits and their reversal, printed without a sign; the reversal also prints the running balance.
VERIFY = ["09/18 SYNTH BANK ACCTVERIFY PPD ID: SYNTHVERIFY 0.36", "09/18 SYNTH BANK ACCTVERIFY PPD ID: SYNTHVERIFY 0.38",
          "09/18 SYNTH BANK ACCTVERIFY WEB ID: SYNTHVERIFY -0.74 0.00"]


def verify_rows(lines):
    first = lines.index(VERIFY[0]) + 1
    return [{"posted_date": "2026-09-18", "transaction_date": None, "description": "SYNTH BANK ACCTVERIFY", "amount": amount,
             "direction": direction, "evidence": at(lines, first + offset)}
            for offset, (amount, direction) in enumerate((("0.36", "credit"), ("0.38", "credit"), ("0.74", "debit")))]


def test_skipped_statement_rows_are_asked_for_again_and_kept_in_printed_order(tmp_path, local_model):
    """The first answer leaves out the verification rows (statement_rows reads only signed lines); the second request, for
    those lines alone, finds them, and they sit after the rent row as printed."""
    lines = [*BANK, *VERIFY]
    replies = bank_replies(lines)
    replies["Transactions"].append({"transactions": verify_rows(lines)})
    with read_statement(tmp_path, local_model, lines, replies) as (_, _run, record):
        assert [(row["description_raw"], row["amount_minor"]) for row in record["transactions"]] == [
            ("PAYROLL SYNTH WORKS", 250000), ("RENT", -120050), ("SYNTH BANK ACCTVERIFY", 36), ("SYNTH BANK ACCTVERIFY", 38), ("SYNTH BANK ACCTVERIFY", -74)]
        assert record["review_status"] == "proposed", record["issues"]  # FR-04


def test_statement_rows_still_missing_after_the_second_request_are_a_review_note(tmp_path, local_model):
    lines = [*BANK, *VERIFY]
    replies = bank_replies(lines)
    replies["Transactions"].append({"transactions": []})
    with read_statement(tmp_path, local_model, lines, replies) as (_, _run, record):
        assert len(record["transactions"]) == 2 and record["review_status"] == "needs_review"
        assert any(issue.startswith("3 printed line(s) with a date and an amount aren't in the transactions: \"09/18 SYNTH BANK ACCTVERIFY")
                   for issue in record["issues"]), record["issues"]


def test_each_statement_type_offers_only_its_own_fields(tmp_path, local_model):
    with read_statement(tmp_path, local_model, BANK, bank_replies(BANK)) as (_, _run, record):
        bank = {item["field"] for item in record["correctable"]}
    (tmp_path / "card").mkdir()
    with read_statement(tmp_path / "card", local_model, CARD, card_replies(CARD)) as (_, _run, record):
        card = {item["field"] for item in record["correctable"]}
    assert {"opening_balance", "closing_balance"} <= bank and not {"statement_balance", "minimum_payment", "due_date"} & bank
    assert {"statement_balance", "minimum_payment", "due_date"} <= card and not {"opening_balance", "closing_balance"} & card


SAVINGS = replaced(BANK, "EVERYDAY CHECKING", "EVERYDAY SAVINGS ACCOUNT 000123456789")


def savings_replies():
    return bank_replies(SAVINGS, account_type=value(SAVINGS, "savings", "EVERYDAY SAVINGS", "EVERYDAY SAVINGS"))


def accounts(manager):
    with manager.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT account_type,display_name FROM accounts ORDER BY id")]


def test_a_savings_statement_records_into_a_savings_account(tmp_path, local_model):
    with read_statement(tmp_path, local_model, SAVINGS, savings_replies()) as (manager, _run, record):
        assert accounts(manager) == [("savings", "SYNTH BANK savings 6789")] and record["account"] == "SYNTH BANK savings 6789"


@pytest.mark.parametrize("name, renamed", [(None, "SYNTH BANK savings 6789"), ("Rainy day fund", "Rainy day fund")])
def test_a_checking_account_a_statement_prints_as_savings_becomes_savings(tmp_path, local_model, name, renamed):
    """An account recorded as checking before the printed type counted: the next Record of its statement corrects the type,
    and a default name follows it while a name the user gave stays."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, SAVINGS)
    try:
        account = manager.ledger.create_account("SYNTH BANK", "checking", "USD", display_name=name, last_four="6789")
        local_model["by_schema"] = savings_replies()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert manager.ledger.record("statement", run["publication"]["id"])["account_id"] == account["id"]
        assert accounts(manager) == [("savings", renamed)]
    finally:
        manager.close()


def test_the_printed_words_as_the_account_type_and_four_digits_from_the_middle_of_the_number(tmp_path, local_model):
    """The model answers the type with the printed words and the reference with four digits from inside the number."""
    account = "EVERYDAY SAVINGS ACCOUNT 000123456789"
    replies = bank_replies(SAVINGS, account_type=value(SAVINGS, "Everyday Savings", account, "EVERYDAY SAVINGS"),
                           account_reference=value(SAVINGS, "1234", account, account))
    with read_statement(tmp_path, local_model, SAVINGS, replies) as (manager, _run, record):
        assert stored_details(manager)["account_type"]["text"] == "savings"
        assert accounts(manager) == [("savings", "SYNTH BANK savings 6789")] and record["review_status"] == "proposed", record["issues"]  # FR-04


@pytest.mark.parametrize("amount, flagged", [("0.38", True), ("0.02", False)])
def test_a_row_that_took_its_lines_running_balance_goes_to_review(tmp_path, local_model, amount, flagged):
    lines = [*BANK, "09/18 SYNTH BANK ACCTVERIFY PPD ID: 1234567890 0.02 0.38"]
    replies = bank_replies(lines)
    replies["Transactions"][0]["transactions"].append({"posted_date": "2026-09-18", "transaction_date": None, "description": "SYNTH BANK ACCTVERIFY",
                                                       "amount": amount, "direction": "credit", "evidence": at(lines, len(lines))})
    with read_statement(tmp_path, local_model, lines, replies) as (_, _run, record):
        found = [issue for issue in record["issues"] if "usually the running balance" in issue]
        assert found == ([f"Transaction 3 (SYNTH BANK ACCTVERIFY): {amount} is the last of the amounts on its line, which is usually the running "
                          "balance, not the transaction's amount. Check its amount."] if flagged else []), record["issues"]


def test_sc22_b_no_type_word_is_other(tmp_path, local_model):
    lines = replaced(BANK, "EVERYDAY CHECKING", "ACCOUNT 000123456789")
    guessed = value(lines, "checking", "ACCOUNT 000123456789")  # Not printed as a word: never taken.
    with read_statement(tmp_path, local_model, lines, bank_replies(lines, account_type=guessed)) as (manager, _run, record):
        assert stored_details(manager)["account_type"]["text"] == "other" and record["review_status"] == "proposed"  # FR-04
        with manager.store.connection() as db:
            assert db.execute("SELECT account_type FROM accounts").fetchone()[0] == "checking"  # The account itself doesn't change.


def test_sc22_c_without_a_withdrawals_total_the_summary_check_is_skipped(tmp_path, local_model):
    lines = without(BANK, "WITHDRAWALS ")
    with read_statement(tmp_path, local_model, lines, bank_replies(lines)) as (_, run, record):
        assert record["review_status"] == "proposed" and run["result"]["normalized"]["cross_checks"] == 1  # FR-04


def test_sc23_card_statement_fields_and_summary_check(tmp_path, local_model):
    with read_statement(tmp_path, local_model, CARD, card_replies(CARD)) as (manager, run, record):
        assert record["review_status"] == "proposed", record["issues"]  # FR-04
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
        assert record["review_status"] == "proposed" and run["result"]["normalized"]["cross_checks"] == 1  # FR-04


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
        assert run["publication"]["review_status"] == "proposed"  # FR-04: a new account waits for Confirm, so its statement does too.
        manager.ledger.review("statement", run["publication"]["id"], "verified")  # Confirm, as the user does; the rows then count after reconcile.
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
