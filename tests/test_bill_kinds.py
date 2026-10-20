"""Bill kinds (specs/bill-kinds FR-40 – FR-58): a rent form beside the general bill form. Synthetic bills only."""

from contextlib import contextmanager
from datetime import date
import json
from types import SimpleNamespace

import pytest

from bill_kinds_fixtures import (
    AMOUNT_LINE,
    RENT,
    RENT_LINE,
    WATER_LINE,
    general_replies,
    rent_plain,
    rent_replies,
    rent_row,
    water_row,
    with_line,
)
from document_forms_fixtures import uncited
from home_manager.documents.extraction import EXTRACTION_VERSION, HEADERS, bill_kind, date_printed, printed_dates
from home_manager.finance.ledger import HouseholdConfig
from home_manager.finance.tools import BudgetInput, FinanceTools, PeriodInput
from test_bills_ledger import PHONE_TEXT, bill, line, open_books
from test_extraction import MISSING, cite, extract, transcribe, value
from test_reconcile_tools import source_of

V30 = "typed-extraction-v30-pre-tax-deductions"
OCTOBER = PeriodInput(start="2026-10-01", end="2026-10-31")


@contextmanager
def read_bill(tmp_path, local_model, lines, replies):
    """Transcribe lines and read them with replies keyed by schema name, home currency USD (the bill prints only $).
    Yields (manager, run, record, row): row is the bill's database row, for the final-state checks."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        manager.configure_household(HouseholdConfig(auto_identify_items=False, home_currency="USD"))
        local_model["requests"].clear()
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert "image_url" not in json.dumps(local_model["requests"])  # C-calls: no image is sent.
        with manager.store.connection() as db:
            row = dict(db.execute("SELECT * FROM receipts WHERE id=?", (run["publication"]["id"],)).fetchone())
        yield manager, run, manager.ledger.record("receipt", row["id"]), row
    finally:
        manager.close()


def asked(local_model):
    return [request["response_format"]["json_schema"]["name"] for request in local_model["requests"]]


def request_for(local_model, name):
    return next(request for request in local_model["requests"] if request["response_format"]["json_schema"]["name"] == name)


def stored_lines(manager, receipt_id):
    """Each line as stored: (description, line_total_minor, line_type, line_kind, category, details)."""
    with manager.store.connection() as db:
        return [(row[0], row[1], row[2], row[3], row[4], json.loads(row[5]) if row[5] else None) for row in db.execute(
            "SELECT description,line_total_minor,line_type,line_kind,category,details_json FROM receipt_items WHERE receipt_id=? ORDER BY position",
            (receipt_id,))]


def bill_details(row):
    return json.loads(row["details_json"])[row["bill_kind"]] if row["details_json"] else None


def printed_as(day, text):
    """An independent C-date check: the day is written in text as 10/01/2026, 10/1/2026, Oct 1, 2026 or 2026-10-01."""
    forms = {day.isoformat(), f"{day.month:02d}/{day.day:02d}/{day.year}", f"{day.month}/{day.day}/{day.year}",
             f"{day.strftime('%b')} {day.day}, {day.year}"}
    return any(form in text for form in forms)


def assert_published_bill(manager, lines, receipt_id):
    """The shared final-state oracle (contract "Shared checks"): C-cite, C-date and C-money on what a bill stored."""
    with manager.store.connection() as db:
        row = db.execute("SELECT typeof(total_minor),typeof(amount_due_minor),details_json,bill_kind FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        assert {row[0], row[1]} <= {"integer", "null"}  # C-money
        assert {item[0] for item in db.execute("SELECT typeof(line_total_minor) FROM receipt_items WHERE receipt_id=?", (receipt_id,))} <= {"integer", "null"}
        usage = [item[0] for item in db.execute("SELECT json_type(details_json,'$.usage.text') FROM receipt_items WHERE receipt_id=? "
                                                "AND json_extract(details_json,'$.usage') IS NOT NULL", (receipt_id,))]
        assert set(usage) <= {"text"}  # Usage is its printed text, never a number.
        details = json.loads(row[2])[row[3]] if row[2] else {}
        for name, detail in details.items():
            if isinstance(detail, dict) and "locator" in detail:
                assert db.execute(f"SELECT json_type(details_json,'$.{row[3]}.{name}.minor') FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0] == "integer"
    for _, _, _, _, _, item in stored_lines(manager, receipt_id):
        for name, detail in (item or {}).items():
            texts = [lines[int(id.split("-")[1]) - 1] for id in detail["locator"]["line_ids"]]
            assert uncited(detail, lines) == [], name  # C-cite
            if name == "period":
                for side in ("start", "end"):
                    if detail["how"] == "printed":  # C-date: printed in its line, or marked as worked out.
                        assert any(printed_as(date.fromisoformat(detail[side]), text) for text in texts), (side, detail)
                    else:
                        assert detail["how"] in ("whole_month", "year_from_due")
            if name == "usage":
                assert any(detail["text"] in text for text in texts)


def phone_outputs():
    """The PHONE bill's classification, summary and lines, in the order a general bill asks them."""
    header = {"provider": value("ACME WIRELESS", 1), "account_reference": value("4821", 2, "Account 0000 4821"), "issue_date": value("2026-09-05", 3),
              "due_date": value("2026-09-28", 4), "period_start": MISSING, "period_end": MISSING, "amount_due": value("79.99", 10, "Amount due USD 79.99"),
              "new_charges": value("67.99", 9, "New charges 67.99"), "currency": value("USD", 10, "USD")}
    rows = [{"description": "Unlimited", "amount": "40.00", "category": "phone & internet", "line_kind": "service", "line_holder": "Alex 555-201-1111",
             "evidence": cite(5, PHONE_TEXT[4])},
            {"description": "Apple TV+", "amount": "9.99", "category": "subscriptions", "line_kind": "subscription", "line_holder": None,
             "evidence": cite(6, PHONE_TEXT[5])},
            {"description": "Taxes and fees", "amount": "18.00", "category": None, "line_kind": "tax_fee", "line_holder": None, "evidence": cite(7, PHONE_TEXT[6])}]
    return [{"document_type": "bill", "evidence": cite(1, "ACME WIRELESS"), "issuer": value("ACME WIRELESS", 1), "document_date": MISSING},
            header, {"line_items": rows}]


def test_version_ledger_stores_a_bills_kind_details_and_line_types(tmp_path):
    """SL-01 plumbing: a bill record carrying a kind, details and line types is stored and read back by kind; one without
    a kind keeps every new column empty (FR-52)."""
    store, ledger, docs = open_books(tmp_path / "managed")
    try:
        period = {"period": {"start": "2026-10-01", "end": "2026-10-31", "how": "printed", "locator": {"line_ids": ["line-2"]}}}
        lines = [{**line("Rent", 145000, "housing"), "line_type": "rent", "details": period},
                 {**line("Water", 3842, "utilities", "usage"), "line_type": "utility"}]
        record = {"provider": "Synth Property", "issue_date": None, "due_date": "2026-10-01", "period_start": None, "period_end": None,
                  "amount_due_minor": 148842, "total_minor": 148842, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]},
                  "items": lines, "category": None, "recurrence": "monthly", "bill_kind": "rent",
                  "details": {"previous_balance": {"minor": 0, "locator": {"line_ids": ["line-1"]}}, "notes": []}}
        rent = ledger.publish_bill(record, source_of(docs["rent.png"], "extraction:rent.png"), "needs_review")["id"]
        with store.connection() as db:
            row = db.execute("SELECT bill_kind,receipt_kind,details_json FROM receipts WHERE id=?", (rent,)).fetchone()
            assert (row["bill_kind"], row["receipt_kind"]) == ("rent", None)
            assert json.loads(row["details_json"])["rent"]["previous_balance"]["minor"] == 0
            assert [tuple(item) for item in db.execute("SELECT line_type,line_kind FROM receipt_items WHERE receipt_id=? ORDER BY position", (rent,))] == [
                ("rent", "service"), ("utility", "usage")]
        shown = ledger.record("receipt", rent)
        assert shown["bill_kind"] == "rent" and shown["details"]["previous_balance"]["minor"] == 0
        assert shown["items"][0]["details"]["period"]["start"] == "2026-10-01" and shown["items"][1]["line_type"] == "utility"

        phone = bill(ledger, docs["phone.png"], "Acme Wireless", "2026-09-28", [line("Unlimited plan", 4000, "phone & internet")])
        with store.connection() as db:
            row = db.execute("SELECT bill_kind,receipt_kind,details_json FROM receipts WHERE id=?", (phone,)).fetchone()
            assert tuple(row) == (None, None, None)
            assert tuple(db.execute("SELECT line_type,details_json FROM receipt_items WHERE receipt_id=?", (phone,)).fetchone()) == (None, None)
    finally:
        store.close()


def test_version_changed_and_a_bill_read_under_v30_is_read_again(tmp_path, local_model):
    """SC-49 step 2 (FR-52): the version changed, so a parse with only a v30 run gets a new run."""
    assert EXTRACTION_VERSION != V30
    manager, doc, parse_id = transcribe(tmp_path, local_model, PHONE_TEXT)
    try:
        local_model["outputs"] = phone_outputs()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        with manager.store.connection() as db:
            db.execute("UPDATE extraction_runs SET prompt_version=? WHERE id=?", (V30, run["id"]))
        local_model["outputs"] = phone_outputs()
        started = manager.start_extraction(doc["id"], parse_id)
        manager.future.result(timeout=30)
        assert started["reused"] is False and started["run_id"] != run["id"]
        again = manager.extractions.get(started["run_id"])
        assert (again["status"], again["prompt_version"]) == ("succeeded", EXTRACTION_VERSION)
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1  # The same bill, read again.
    finally:
        manager.close()


# Printed dates (plan "Date checks"): unit tests --------------------------------------------------------------------

def quotes(*texts):
    return [SimpleNamespace(line_id="line-1", quote=text) for text in texts]


@pytest.mark.parametrize("text", ["Due Date 10/01/2026", "Due 10/1/2026", "Due Oct 1, 2026", "Due October 1 2026", "Due 1 Oct 2026",
                                  "Due Oct. 1st, 2026", "Due 2026-10-01"])
def test_dates_every_printed_form_of_a_date_is_found(text):
    assert date_printed("2026-10-01", quotes(text)) == ("2026-10-01", "printed")


def test_dates_numeric_dates_give_both_readings_and_never_match_inside_another_date():
    found = printed_dates("Rent 10/01/2026 - 10/31/2026")
    assert (date(2026, 10, 1), "numeric") in found and (date(2026, 1, 10), "numeric") in found
    assert (date(2026, 10, 31), "numeric") in found
    assert not [entry for entry in found if entry[1] in ("month", "yearless")]  # 01/2026 and 10/01 are inside full dates.
    assert printed_dates("Rent for October 2026") == [((2026, 10), "month")]
    assert printed_dates("Billed 10/2026") == [((2026, 10), "month")]
    assert printed_dates("Rent 10/1 - 10/31") == [((10, 1), "yearless"), ((10, 31), "yearless")]
    assert printed_dates("Rent 10/01/26") == []  # Two-digit years are not a form (plan P5).


def test_dates_a_date_not_printed_in_its_quote_is_not_kept():
    assert date_printed("2026-10-02", quotes("Due Date ...... 10/01/2026")) == (None, None)
    assert date_printed("2026-10-01", quotes("Rent for October 2026")) == (None, None)  # A month alone is not a full date.
    assert date_printed("not a date", quotes("10/01/2026")) == (None, None)
    assert date_printed("2026-10-01", quotes("Rent 10/1 - 10/31")) == (None, None)  # No due date: no year for a yearless date.


def test_dates_a_yearless_date_takes_its_year_from_the_due_date_within_a_month_either_side():
    assert date_printed("2026-10-01", quotes("Rent 10/1 - 10/31"), "2026-10-01") == ("2026-10-01", "year_from_due")
    assert date_printed("2026-11-30", quotes("Rent 11/1 - 11/30"), "2026-10-01") == ("2026-11-30", "year_from_due")
    assert date_printed("2026-12-15", quotes("Gas 12/15 - 1/14"), date(2027, 1, 5)) == ("2026-12-15", "year_from_due")  # December/January wrap.
    assert date_printed("2027-12-15", quotes("Gas 12/15 - 1/14"), date(2027, 1, 5)) == (None, None)  # The year that doesn't put it there.
    assert date_printed("2026-05-15", quotes("Water Usage 5/15 - 6/14"), "2026-10-01") == (None, None)  # Too far from the due month.


# SC-38 and its variants: a rent bill is read with the rent form ---------------------------------------------------

def test_sc38_a_rent_bill_is_read_with_the_rent_form(tmp_path, local_model):
    with read_bill(tmp_path / "general", local_model, RENT, general_replies(kind=None)):
        general_calls = len(local_model["requests"])
    with read_bill(tmp_path / "rent", local_model, RENT, rent_replies()) as (manager, run, record, row):
        # Step 2: one rent-form request and no general one; the same number of calls as a general bill (C-calls).
        names = asked(local_model)
        assert names == ["Classification", "BillRentSummary", "RentBillLines"] and len(names) == general_calls
        summary = request_for(local_model, "BillRentSummary")
        properties = summary["response_format"]["json_schema"]["schema"]["properties"]
        assert {"previous_balance", "payments_received", "monthly_rent"} <= set(properties)
        assert not {"volume", "fuel_amount", "gratuity", "tenders", "savings_total"} & set(properties)
        instruction = summary["messages"][0]["content"]
        assert all(f"{name}: the printed" in instruction for name in ("previous_balance", "payments_received", "monthly_rent"))
        lines_request = request_for(local_model, "RentBillLines")
        line_schema = json.dumps(lines_request["response_format"]["json_schema"]["schema"])
        assert all(word in line_schema for word in ('"rent_type"', '"utility"', '"parking"', '"period_start"', '"period_end"', '"usage"'))
        assert "never a warning, a term or a fee that may apply later" in lines_request["messages"][0]["content"]  # FR-58
        # Step 3: the kind and its citation on line 3, kept in the run's saved classification (C-cite).
        assert (row["document_kind"], row["bill_kind"], row["receipt_kind"]) == ("bill", "rent", None)
        evidence = run["result"]["classification"]["bill_kind_evidence"]
        assert evidence == cite(3, RENT[2]) and all(entry["quote"] in RENT[2] for entry in evidence)
        # Final state.
        assert (row["due_date"], row["issue_date"], row["period_start"], row["period_end"], row["recurrence"]) == (
            "2026-10-01", None, "2026-10-01", "2026-10-31", "monthly")
        assert bill_details(row) == {}  # Previous balance, payments and monthly rent are missing, not 0.
        assert stored_lines(manager, row["id"]) == [
            ("Rent", 145000, "rent", "service", "housing",
             {"period": {"start": "2026-10-01", "end": "2026-10-31", "how": "printed", "locator": {"line_ids": ["line-4"], "quotes": [RENT[3]]}}}),
            ("Water Usage", 3842, "utility", "usage", "utilities",
             {"period": {"start": "2026-08-15", "end": "2026-09-14", "how": "printed", "locator": {"line_ids": ["line-5"], "quotes": [RENT[4]]}},
              "usage": {"text": "3,200 GAL", "locator": {"line_ids": ["line-5"], "quotes": [RENT[4]]}}})]
        assert (row["total_minor"], row["amount_due_minor"], row["account_last_four"]) == (148842, 148842, "4821")
        assert run["result"]["normalized"]["cross_checks"] >= 1
        assert (record["review_status"], record["review_source"], record["issues"]) == ("verified", "automatic", [])
        assert record["category"] == "housing"
        assert_published_bill(manager, RENT, row["id"])


def test_sc38_a_a_line_period_or_usage_not_printed_in_its_citation_is_left_out_with_a_note(tmp_path, local_model):
    """38a: the water line's period cited on the rent line, then its usage: each is dropped with a note naming the line,
    and the bill still counts automatically (a line date is a note only, FR-48)."""
    wrong_period = cite(RENT_LINE, RENT[3]) + cite(WATER_LINE, "$38.42")
    replies = rent_replies(rows=[rent_row(), water_row(evidence=wrong_period, usage=None)])
    with read_bill(tmp_path / "period", local_model, RENT, replies) as (manager, _run, record, row):
        water = stored_lines(manager, row["id"])[1]
        assert (water[0], water[1], water[2], water[5]) == ("Water Usage", 3842, "utility", None)
        assert bill_details(row)["notes"] == ["Water Usage: its period isn't printed in its line; it was left out."]
        assert record["review_status"] == "verified" and record["issues"] == []
        assert_published_bill(manager, RENT, row["id"])
    replies = rent_replies(rows=[rent_row(), water_row(evidence=wrong_period, period=None)])
    with read_bill(tmp_path / "usage", local_model, RENT, replies) as (manager, _run, record, row):
        assert stored_lines(manager, row["id"])[1][5] is None
        assert bill_details(row)["notes"] == ["Water Usage: its usage isn't printed in its line; it was left out."]
        assert record["review_status"] == "verified"


def test_sc38_b_a_water_line_folded_into_rent_is_never_stored(tmp_path, local_model):
    """38b: one rent line of 1,488.42 citing line 4 fails the amount check twice; the bill is read again with the general
    form, published general with the note and in review, and no line of 1,488.42 is ever stored."""
    folded = {"line_items": [rent_row(amount="1,488.42")]}
    replies = {**rent_replies(), "RentBillLines": [folded, folded], **{name: reply for name, reply in general_replies().items() if name != "Classification"}}
    with read_bill(tmp_path, local_model, RENT, replies) as (manager, _run, record, row):
        assert asked(local_model) == ["Classification", "BillRentSummary", "RentBillLines", "RentBillLines", "BillSummary", "BillLines"]
        assert row["bill_kind"] == "general" and record["review_status"] == "needs_review"
        assert any(issue.startswith("Read as a general bill: Extraction failed validation: line_items.0: the amount is not printed")
                   for issue in record["issues"]), record["issues"]
        assert [(entry[0], entry[1], entry[2]) for entry in stored_lines(manager, row["id"])] == [("Rent", 145000, None), ("Water Usage", 3842, None)]
        assert 148842 not in [entry[1] for entry in stored_lines(manager, row["id"])]


def test_sc38_c_a_rent_form_that_fails_twice_is_read_as_a_general_bill(tmp_path, local_model):
    """38c (spec "Errors"): the rent summary's amount due isn't printed where cited, twice; the bill is never lost."""
    replies = rent_replies(amount_due=value("1,588.42", AMOUNT_LINE, RENT[6]))
    replies["BillRentSummary"] *= 2
    replies.update({name: reply for name, reply in general_replies().items() if name != "Classification"})
    with read_bill(tmp_path, local_model, RENT, replies) as (manager, _run, record, row):
        assert asked(local_model) == ["Classification", "BillRentSummary", "BillRentSummary", "BillSummary", "BillLines"]
        assert row["bill_kind"] == "general" and row["amount_due_minor"] == 148842 and record["review_status"] == "needs_review"
        notes = [issue for issue in record["issues"] if issue.startswith("Read as a general bill: ")]
        assert notes == ["Read as a general bill: Extraction failed validation: amount_due: the amount is not printed in its cited evidence."]


def test_sc38_d_a_rent_bill_with_no_rent_line(tmp_path, local_model):
    """38d (spec "Errors"): read as rent, no period from lines, and the note "No rent line was read"."""
    with read_bill(tmp_path, local_model, RENT, rent_replies(rows=[water_row()])) as (manager, _run, _record, row):
        assert row["bill_kind"] == "rent"
        assert [entry[0] for entry in stored_lines(manager, row["id"])] == ["Water Usage"]
        assert bill_details(row)["notes"] == ["No rent line was read."]


# SC-43: each rent line's category comes from its type ---------------------------------------------------------------

def test_sc43_each_line_counts_under_its_types_category(tmp_path, local_model):
    rows = [rent_row(category=None), water_row(category=None)]
    with read_bill(tmp_path, local_model, RENT, rent_replies(rows=rows)) as (manager, _run, record, row):
        # Step 1: Rent housing, Water utilities, the bill's own category housing (most of its money), no note about categories.
        assert [(entry[0], entry[4]) for entry in stored_lines(manager, row["id"])] == [("Rent", "housing"), ("Water Usage", "utilities")]
        assert row["category"] == "housing" and bill_details(row) == {}
        # Step 2: it is already verified.
        assert (record["review_status"], record["review_source"]) == ("verified", "automatic")
        # Step 3: October spending by category.
        tools = FinanceTools(manager.store)
        spent = {entry["category"]: entry["spending"]["minor"] for entry in tools.get_spending_by_category(OCTOBER)["categories"]}
        assert (spent.get("housing"), spent.get("utilities")) == (145000, 3842)
        # Step 4: a utilities budget's spent includes the water line.
        manager.ledger.set_budget("utilities", "USD", "100.00")
        budgets = {entry["category"]: entry for entry in tools.get_budgets(BudgetInput(month="2026-10", as_of="2026-10-31"))["budgets"]}
        assert budgets["utilities"]["spent"]["minor"] == 3842
        assert_published_bill(manager, RENT, row["id"])


@pytest.mark.parametrize("rows,expected", [
    ([rent_row(), water_row(category="housing")], [("Rent", "housing"), ("Water Usage", "utilities")]),   # 43a
    ([rent_row(category="utilities"), water_row()], [("Rent", "housing"), ("Water Usage", "utilities")]),  # 43b
], ids=["water_answered_housing", "rent_answered_utilities"])
def test_sc43_variants_the_type_decides_a_disagreeing_category(tmp_path, local_model, rows, expected):
    with read_bill(tmp_path, local_model, RENT, rent_replies(rows=rows)) as (manager, _run, record, row):
        assert [(entry[0], entry[4]) for entry in stored_lines(manager, row["id"])] == expected
        assert bill_details(row) == {} and record["review_status"] == "verified"  # No note when the type overrides.


# SC-43b: a bare water line is still a utility line -----------------------------------------------------------------

def test_sc43b_a_bare_water_line_is_a_utility_line(tmp_path, local_model):
    lines = rent_plain()
    rows = [rent_row(lines=lines), water_row(lines, description="Water", period=None, usage=None)]
    with read_bill(tmp_path, local_model, lines, rent_replies(lines, rows=rows)) as (manager, _run, record, row):
        assert stored_lines(manager, row["id"])[1] == ("Water", 3842, "utility", "usage", "utilities", None)
        assert bill_details(row) == {}  # No note: what the line doesn't print stays empty.
        assert (record["review_status"], record["review_source"]) == ("verified", "automatic")
        assert_published_bill(manager, lines, row["id"])


@pytest.mark.parametrize("word", ["Water", "Sewer", "Trash", "Gas", "Electric"])
def test_sc43b_1_a_utility_line_answered_other_is_a_utility(tmp_path, local_model, word):
    lines = with_line(RENT, WATER_LINE, f"{word} $38.42")
    rows = [rent_row(lines=lines), water_row(lines, description=word, rent_type="other", category=None, period=None, usage=None)]
    with read_bill(tmp_path, local_model, lines, rent_replies(lines, rows=rows)) as (manager, _run, record, row):
        assert stored_lines(manager, row["id"])[1][:5] == (word, 3842, "utility", "usage", "utilities")
        assert record["review_status"] == "verified"


# SC-44: an unusable kind proposal is a general bill -----------------------------------------------------------------

@pytest.mark.parametrize("kind,evidence,note", [
    ("rent", [], "Bill kind: rent was not used: no line was cited for it. It was read as a general bill."),
    ("rent", [{"line_id": "line-3", "quote": "Rent and Lease Due"}],
     "Bill kind: rent was not used: a citation is not an exact quote of an existing line. It was read as a general bill."),  # 44a
    ("utility", cite(5, RENT[4]), "Bill kind: utility was not used: it is not one of rent or general. It was read as a general bill."),  # 44b
], ids=["uncited", "miscited", "unlisted"])
def test_sc44_an_unusable_kind_is_read_as_a_general_bill_with_a_note(tmp_path, local_model, kind, evidence, note):
    with read_bill(tmp_path, local_model, RENT, general_replies(kind=kind, kind_evidence=evidence)) as (_manager, _run, record, row):
        assert asked(local_model) == ["Classification", "BillSummary", "BillLines"]  # The general form, no rent form.
        assert row["bill_kind"] == "general" and record["review_status"] == "needs_review"
        assert [issue for issue in record["issues"] if issue.startswith("Bill kind:")] == [note]


def test_sc44_c_a_null_kind_is_general_with_no_note(tmp_path, local_model):
    with read_bill(tmp_path, local_model, RENT, general_replies(kind=None)) as (_manager, _run, record, row):
        assert row["bill_kind"] == "general" and json.loads(row["details_json"]) == {"general": {}}
        assert (record["review_status"], record["issues"]) == ("verified", [])  # Only the rest of the bill decides.


def test_sc44_d_an_invoice_answered_rent_is_stored_general(tmp_path, local_model):
    text = ["EXAMPLE REPAIRS", "Invoice INV-104", "Bill to Alex Example", "Issued 2026-09-10", "Due 2026-09-28", "USD", "Parts 100.00",
            "Invoice total 100.00", "Balance due 100.00"]
    header = {name: MISSING for name in HEADERS["bill"]}
    header.update(provider=value("EXAMPLE REPAIRS", 1), invoice_marker=value("Invoice", 2, "Invoice"), invoice_number=value("INV-104", 2, "INV-104"),
                  issue_date=value("2026-09-10", 4, "2026-09-10"), due_date=value("2026-09-28", 5, "2026-09-28"), currency=value("USD", 6),
                  invoice_total=value("100.00", 8, "100.00"), balance_due=value("100.00", 9, "100.00"), amount_due=value("100.00", 9, "100.00"))
    replies = {"Classification": [{"document_type": "bill", "evidence": cite(2, text[1]), "issuer": value("EXAMPLE REPAIRS", 1), "document_date": MISSING,
                                   "bill_kind": "rent", "bill_kind_evidence": cite(2, text[1])}],
               "BillRentSummary": [header],
               "RentBillLines": [{"line_items": [rent_row("Parts", "100.00", 7, text, rent_type="rent", category=None, period=None)]}]}
    with read_bill(tmp_path, local_model, text, replies) as (manager, _run, record, row):
        assert row["bill_kind"] == "general" and json.loads(row["invoice_json"])["number"] == "INV-104"
        assert stored_lines(manager, row["id"]) == [("Parts", 10000, None, "service", None, None)]  # No rent type or rent category.
        assert record["review_status"] == "verified" and record["recurrence"] is None


def test_sc44_bill_kind_rules_on_hand_built_classifications():
    from home_manager.documents.extraction import Classification
    base = {"document_type": "bill", "evidence": cite(1, RENT[0]), "issuer": value(RENT[0], 1), "document_date": MISSING}
    lines = [SimpleNamespace(id=f"line-{number}", text=text) for number, text in enumerate(RENT, 1)]
    notes = []
    assert bill_kind(Classification.model_validate({**base, "bill_kind": "rent", "bill_kind_evidence": cite(3, "Rent and Leasing")}), lines, notes) == "rent"
    assert bill_kind(Classification.model_validate({**base, "bill_kind": "general"}), lines, notes) == "general"
    assert bill_kind(Classification.model_validate(base), lines, notes) == "general" and notes == []
    assert bill_kind(Classification.model_validate(base), lines, notes, requested="rent") == "rent"  # A kind change wins.
    assert bill_kind(Classification.model_validate({**base, "bill_kind": "Rent Bill!"}), lines, notes) == "general"
    assert notes == ["Bill kind: an unlisted kind was not used: it is not one of rent or general. It was read as a general bill."]


# SC-50 (PHONE part): a phone bill is read general, its lines unchanged -------------------------------------------------

def test_sc50_a_phone_bill_is_read_general_with_its_lines_unchanged(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, PHONE_TEXT)
    try:
        local_model["outputs"] = phone_outputs()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        record = manager.ledger.record("receipt", run["publication"]["id"])
        with manager.store.connection() as db:
            row = db.execute("SELECT bill_kind,details_json FROM receipts WHERE id=?", (record["id"],)).fetchone()
        assert (row["bill_kind"], json.loads(row["details_json"])) == ("general", {"general": {}})
        assert (record["review_status"], record["review_source"], record["total_minor"], record["amount_due_minor"]) == ("verified", "automatic", 6799, 7999)
        assert [(item["line_holder"], item["line_kind"], item["line_type"], item["category"]) for item in record["items"]] == [
            ("Alex 555-201-1111", "service", None, "phone & internet"), (None, "subscription", None, "subscriptions"), (None, "tax_fee", None, None)]
        assert {entry["category"]: entry["amount_minor"] for entry in record["splits"]} == {"phone & internet": 5800, "subscriptions": 999}
    finally:
        manager.close()
