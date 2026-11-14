"""The printed total and the due-now line (specs/bill-total-and-account-holder, part B: FR-141 - FR-146 and the parts of FR-147 - FR-149 that concern them).

There is no test contract (the user delegated the process); each test names the requirement or scenario it covers. Expected values are written out by hand
below. Fixtures are synthetic (tests/bill_engine_fixtures.py: BL-TOTAL prints the user's two lines word for word under a synthetic provider and name,
BL-TOTAL-NOW, BL-DUE-CARRIED, BL-TOTAL-DUE, MINI-DUE(k)); the files go through the real services (`run`, publish, the ledger and the transactions tools).

The user's words: "the paid line of the transaction table takes the 62 dollars when it should default take the total current charges". So the end-to-end
tests assert what the Transactions page shows as Paid for the bill: 1,667.91 (`-total_minor` of the document row), never 62.91.
"""

import itertools
import json
from types import SimpleNamespace

import pytest

import bill_engine_fixtures as bf
from home_manager.core.jobs import Work
from home_manager.documents import bill_split, charge_tables, extraction
from home_manager.documents.charge_tables import DUE_NOW, anchor_kind, due_now_of
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance import bill_tables
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, PeriodInput, TransactionsInput
from test_bill_account_holder import TOTAL_FIELDS, YOU, everyone
from test_bill_engine_record import UTIL_FIELDS, BillRun, bill_run, snapshot, started_scanned
from test_paystub_engine_record import started  # noqa: F401
from test_pdf import pdf_store  # noqa: F401
from test_reconcile_tools import add

PROVIDER = "LAKESIDE GAS & ELECTRIC"
DUE_NOW_LINE = "Current Charges due 11/01/2026"
# The model's answers for BL-TOTAL: it reads the due-now line as the amount due (62.91) and the total as the new charges, and gives the due date from the
# due-now line (SC-132 (a)). `WRONG` is the user's worst case: the model takes the due-now line for the new charges too.
FIELDS = {**TOTAL_FIELDS, "due_date": ("2026-11-01", "Current Charges due", "11/01/2026")}
WRONG = {**FIELDS, "new_charges": ("62.91", "Current Charges due", "$62.91")}
NOVEMBER = PeriodInput(start="2026-11-01", end="2026-11-30")
TOTAL_NOTE = "The bill prints Current Charges due 11/01/2026 62.91 and a total of 1667.91; the total is the amount due."


def total(pdf_store, local_model, fields=FIELDS, pages=None, rows=bf.STUB_TOTAL, name="bill.pdf"):
    return bill_run(pdf_store, local_model, pages if pages is not None else bf.total_pages(), rows, fields, classify=PROVIDER, name=name)


def paid(store, start="2026-11-01", end="2026-11-30"):
    """What the Transactions page shows as Paid for each bill row: (source, date, Paid) from the transactions tool the page loads, money out as a positive."""
    listed = FinanceTools(store).get_transactions(TransactionsInput(start=start, end=end, include_documents=True))
    return [(row["source"], row["posted_date"], -row["amount_minor"]) for row in listed["transactions"]]


def spent(store):
    rows = FinanceTools(store).get_spending(NOVEMBER)["by_currency"]
    return rows[0]["spending"]["minor"] if rows else 0


def due_now_of_record(run):
    return (run.record["details"] or {}).get("due_now")


# === FR-141: the due-now line ====================================================================================================================

@pytest.mark.parametrize("label, date", [
    ("Current Charges due 11/01/2026", "11/01/2026"), ("New Charges Due Nov 1, 2026", "Nov 1, 2026"), ("Current Charges due on 11/01/2026", "11/01/2026"),
    ("Total Amount Due payable by 2026-11-01", "2026-11-01"), ("New Charges due by 11/01/2026 ....", "11/01/2026"), ("Total Current Charges due 1 Nov 2026", "1 Nov 2026")])
def test_fr141_a_new_charges_or_amount_due_phrase_with_due_and_a_date_is_a_due_now_line(label, date):
    found = due_now_of(label)
    assert found is not None and found[0] == date and anchor_kind(label) is None


@pytest.mark.parametrize("label", [
    "Amount Due by 11/01/2026",  # FR-103's `by` + date: still the amount-due anchor.
    "Payment Due 11/01/2026", "Total Amount Due", "Total Current Charges", "Current Charges due", "Current Charges 11/01/2026", "Your charges due 11/01/2026",
    "Previous Balance due 11/01/2026", "Late Fee due 11/01/2026", "Current Charges due soon"])
def test_fr141_other_labels_are_not_due_now_lines(label):
    assert due_now_of(label) is None


def test_fr141_amount_due_by_a_date_stays_an_amount_due_anchor():
    assert anchor_kind("Amount Due by 11/01/2026") == "amount_due"
    assert anchor_kind("Payment Due 11/01/2026") == "amount_due"


def test_fr141_the_engine_finds_it_as_an_anchor_of_its_own_and_never_as_a_charge_row(pdf_store, local_model):
    run = started(pdf_store, local_model, bf.total_pages())
    reading = bill_tables.read(run.evidence).reading
    kinds = [(anchor.kind, anchor.token.text, anchor.date) for anchor in reading.anchors]
    assert kinds == [(DUE_NOW, "$62.91", "11/01/2026"), ("new_charges", "$1,667.91", None)]
    assert [row.label for table in reading.tables for row in table.rows] == ["Delivery Charges", "Supply Charges", "Taxes and Fees"]
    assert reading.unplaced == [] and reading.late_lines == []


def test_fr141_a_late_line_is_never_a_due_now_line(pdf_store, local_model):
    late = [*bf.left(560, "If paid after 11/01/2026, Current Charges due 11/15/2026"), *bf.heading(560, (bf.CHARGE, "$70.00"))]
    run = started(pdf_store, local_model, bf.total_pages(extra=late))
    reading = bill_tables.read(run.evidence).reading
    assert [anchor.kind for anchor in reading.anchors] == [DUE_NOW, "new_charges"] and len(reading.late_lines) == 1


def test_fr141_a_due_now_line_is_a_parts_own_amount_due_for_the_split_rule():  # FR-146
    line = type("Line", (), {"id": "page-1-layout-line-1", "text": "Current Charges due 11/01/2026 $62.91"})()
    assert bill_split.anchor_of(line)[0] == DUE_NOW
    assert bill_split.anchor_of(type("Line", (), {"id": "x", "text": "Amount Due $62.91"})())[0] == "amount_due"


# === SC-132 (a): the user's bill, end to end =====================================================================================================

def test_sc132_a_the_user_s_bill_counts_the_printed_total_and_the_transactions_page_shows_it_as_paid(pdf_store, local_model):
    run = total(pdf_store, local_model)
    record = run.record
    row = run.bill_row()
    assert row["total_minor"] == 166791  # The stored receipt: what the bill counts.
    assert record["due_date"] == "2026-11-01" and row["due_date"] == "2026-11-01" and row["purchase_date"] == "2026-11-01"
    assert record["amount_due_minor"] == 166791  # FR-142 (b): the printed total, not the due-now 62.91.
    assert record["total_minor"] == 166791
    assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("Delivery Charges", 118040), ("Supply Charges", 41226),
                                                                                              ("Taxes and Fees", 7525)]
    assert run.notes == [TOTAL_NOTE]
    assert record["review_status"] == "verified" and record["issues"] == []
    checks = {check["name"]: check["passes"] for check in record["checks"]}
    assert checks["lines"] is True and "carried" not in checks
    details = record["details"]
    assert details["due_now"]["minor"] == 6291
    assert details["due_now"]["date"] == "2026-11-01" and details["due_now"]["label"] == DUE_NOW_LINE
    assert details["due_now"]["locator"]["line_ids"] == [run.line("Current Charges due").id]
    assert details["new_charges"]["minor"] == 166791
    # The Transactions page: the bill's row, on its due date, with Paid 1,667.91 (and 62.91 nowhere).
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]
    assert spent(run.store) == 166791
    assert 6291 not in {amount for _, _, amount in paid(run.store)}


def test_sc132_a_the_page_rows_end_with_the_amount_due_and_the_due_now_line_below_it(pdf_store, local_model):
    run = total(pdf_store, local_model)
    summary = run.record["bill_summary"]
    assert summary["amount_due"]["minor"] == 166791 and summary["gap"] is None and summary["earlier_balance"] is None
    assert summary["due_now"]["minor"] == 6291 and summary["due_now"]["label"] == DUE_NOW_LINE and summary["due_now"]["date"] == "2026-11-01"
    assert summary["due_now"]["display"] == "62.91 USD"
    assert summary["due_now"]["line_ids"] == [run.line("Current Charges due").id]


def test_sc132_a_the_account_holder_is_still_read_and_every_line_shows_the_profile(pdf_store, local_model):
    run = total(pdf_store, local_model)
    assert run.record["details"]["account_holder"]["text"] == "Jordan A. Rivera"
    assert everyone(run.record, YOU) == {("Jordan Rivera", "account")}


def test_sc132_a_the_model_taking_the_due_now_line_for_the_new_charges_changes_nothing_on_a_text_pdf(pdf_store, local_model):
    run = total(pdf_store, local_model, fields=WRONG)
    assert (run.bill_row()["total_minor"], run.record["amount_due_minor"], run.record["due_date"]) == (166791, 166791, "2026-11-01")
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]
    assert run.record["review_status"] == "verified" and due_now_of_record(run)["minor"] == 6291


@pytest.mark.parametrize("amount", [-6291, -166791])
def test_sc132_a_a_payment_of_the_due_now_amount_or_of_the_total_is_proposed_as_the_bill_s_match(pdf_store, local_model, amount):
    run = total(pdf_store, local_model)
    ledger = Ledger(run.store)
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    [payment] = add(run.store, ledger, checking, run.doc, [("2026-10-30", "LAKESIDE GAS & ELECTRIC ACH", amount)])
    Reconciler(run.store).run()
    [link] = ledger.record("receipt", run.run["publication"]["id"])["links"]
    assert link["counterpart"]["id"] == payment


def test_fr143_a_payment_of_some_other_amount_is_not_the_bills_payment(pdf_store, local_model):
    run = total(pdf_store, local_model)
    ledger = Ledger(run.store)
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(run.store, ledger, checking, run.doc, [("2026-10-30", "LAKESIDE GAS & ELECTRIC ACH", -6290)])
    Reconciler(run.store).run()
    assert ledger.record("receipt", run.run["publication"]["id"])["links"] == []


# === SC-132 (b): the charge lines add up to the due-now amount (OD-10) =======================================================================

def test_sc132_b_lines_adding_up_to_the_due_now_amount_go_to_review_and_never_count_62_91(pdf_store, local_model):
    run = total(pdf_store, local_model, pages=bf.total_pages(rows=bf.TOTAL_NOW_ROWS), rows=bf.STUB_TOTAL_NOW)
    record = run.record
    assert record["review_status"] == "needs_review"
    assert "New charges: the lines add up to 62.91 USD, but the bill's new charges are 1,667.91 USD. A line may be missing or misread." in record["issues"]
    assert record["amount_due_minor"] == 166791
    assert run.bill_row()["total_minor"] == 166791  # What it counts once you confirm it: the printed total, never the 62.91 the lines add up to.
    assert paid(run.store) == []  # In review it is not on the Transactions page; confirmed, it counts the printed total.
    Ledger(run.store).review("receipt", run.run["publication"]["id"], "verified")
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]
    assert due_now_of_record(run)["minor"] == 6291


# === SC-132 (c), (d): the due date ===============================================================================================================

def test_sc132_c_with_no_due_date_from_the_model_the_due_now_line_gives_it_and_the_bill_counts_on_it(pdf_store, local_model):
    run = total(pdf_store, local_model, fields=TOTAL_FIELDS)  # No due_date answer.
    record = run.record
    assert record["due_date"] == "2026-11-01" and run.bill_row()["purchase_date"] == "2026-11-01"
    with run.store.connection() as db:  # The bill's evidence: the due-now line is cited, as the due date's source.
        cited = [line for found in db.execute("SELECT locator_json FROM financial_evidence_links WHERE record_type='receipt' AND record_id=?", (record["id"],))
                 for line in json.loads(found["locator_json"])["line_ids"]]
    assert run.line("Current Charges due").id in cited
    assert "Due date was not found in the document; add it with Edit details." not in record["issues"]
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]


def test_sc132_c_a_dropped_due_date_is_replaced_by_the_due_now_line(pdf_store, local_model):
    fields = {**TOTAL_FIELDS, "due_date": ("2026-11-15", "Current Charges due", "11/01/2026")}  # The cited line doesn't print 11/15: bill_dates drops it.
    run = total(pdf_store, local_model, fields=fields)
    assert run.record["due_date"] == "2026-11-01"
    assert any(issue.startswith("Due date: the cited line doesn't print 2026-11-15") for issue in run.record["issues"])


def test_sc132_d_a_printed_due_date_stands_and_the_bill_notes_the_due_now_line(pdf_store, local_model):
    due_date = bf.left(580, "Due Date 11/15/2026")
    fields = {**TOTAL_FIELDS, "due_date": ("2026-11-15", "Due Date", "11/15/2026")}
    run = total(pdf_store, local_model, fields=fields, pages=bf.total_pages(extra=due_date))
    assert run.record["due_date"] == "2026-11-15"
    assert "The bill also prints Current Charges due 11/01/2026." in run.notes
    assert paid(run.store, "2026-11-01", "2026-11-30") == [("bill", "2026-11-15", 166791)]


# === FR-142: which amount is the amount due ==================================================================================================

def test_sc137_a_previous_balance_less_payments_plus_new_charges_is_worked_out_when_no_amount_due_is_printed(pdf_store, local_model):
    fields = {**UTIL_FIELDS, "amount_due": ("62.91", "62.91", "62.91"), "new_charges": ("62.91", "62.91", "62.91")}  # The model: the due-now amount, printed.
    run = bill_run(pdf_store, local_model, bf.due_carried_pages(), bf.STUB_UTIL_WRONG, fields)
    record = run.record
    assert record["amount_due_minor"] == 12755 and record["total_minor"] == 9755
    assert "The amount due is worked out as previous balance 50.00 − payments 20.00 + new charges 97.55 = 127.55." in run.notes
    assert "The bill prints Current Charges due 11/01/2026 62.91 and a total of 127.55; the total is the amount due." in run.notes
    assert {check["name"] for check in record["checks"]} >= {"lines"} and "carried" not in {check["name"] for check in record["checks"]}
    assert record["details"]["due_now"]["minor"] == 6291 and record["details"]["new_charges"]["minor"] == 9755
    assert [issue for issue in record["issues"] if issue.startswith("Amount due")] == []


def test_sc138_a_total_amount_due_that_already_holds_the_previous_balance_is_never_added_to_again(pdf_store, local_model):
    fields = {**UTIL_FIELDS, "amount_due": ("97.55", "97.55", "97.55"), "new_charges": ("97.55", "97.55", "97.55")}  # The model: the due-now amount, printed.
    run = bill_run(pdf_store, local_model, bf.total_due_pages(), bf.STUB_UTIL_WRONG, fields)
    record = run.record
    assert record["amount_due_minor"] == 14755 and record["total_minor"] == 9755  # Not 245.10.
    assert {check["name"]: check["passes"] for check in record["checks"]}["carried"] is True
    assert record["details"]["due_now"]["minor"] == 9755  # Equal to the new charges, different from the amount due: kept and shown.
    assert record["bill_summary"]["due_now"]["minor"] == 9755 and record["bill_summary"]["amount_due"]["minor"] == 14755


def test_sc141_a_a_plain_amount_due_beside_the_total_keeps_the_amount_due_the_bill_prints(pdf_store, local_model):  # OD-2
    pages = [bf.page_of(bf.util_items(summary=[*bf.UTIL_SUMMARY[:2], ("New Charges", "97.55"), ("Amount Due", "62.91")], total_current="97.55", stub=False))]
    fields = {**UTIL_FIELDS, "amount_due": ("62.91", "62.91", "62.91"), "new_charges": ("97.55", "97.55", "97.55")}
    run = bill_run(pdf_store, local_model, pages, bf.STUB_UTIL_WRONG, fields)
    assert run.record["amount_due_minor"] == 6291 and run.record["total_minor"] == 9755 and "due_now" not in (run.record["details"] or {})


# === FR-146: a file of several bills =============================================================================================================

def test_sc142_each_bill_of_a_file_prints_a_due_now_line_as_its_own_amount_due(pdf_store, local_model):
    from test_bill_split import Bills, started_bills
    run = started_bills(pdf_store, local_model, bf.mini_due_pages(1, 2))
    run.answer([1, 2], amount_label="Current Charges due")
    run.extract()
    bills = run.bills()
    assert len(bills) == 2
    assert [(record["amount_due_minor"], record["total_minor"]) for _, _, record in bills] == [(8142, 8142), (8726, 8726)]
    assert [record["due_date"] for _, _, record in bills] == ["2026-07-20", "2026-08-20"]
    for _, _, record in bills:
        assert not [issue for issue in record["issues"] if "no amount due" in issue]
        assert record["review_status"] == "verified"
    assert isinstance(run, Bills)


# === Photographed and scanned bills (FR-145) =====================================================================================================

def scanned_total(pdf_store, local_model, transcription, fields, rows=bf.STUB_TOTAL):
    run = started_scanned(pdf_store, local_model, [*transcription, bf.FOOTER])
    run.stub_bill(rows, fields, classify=PROVIDER, single_run=True)
    run.extract()
    return run


def test_sc140_a_photographed_bill_whose_amount_due_cites_the_due_now_line_reads_the_total(pdf_store, local_model):
    run = scanned_total(pdf_store, local_model, bf.total_transcription(), FIELDS)
    record = run.record
    assert record["amount_due_minor"] == 166791 and record["total_minor"] == 166791 and record["due_date"] == "2026-11-01"
    assert record["details"]["due_now"]["minor"] == 6291 and record["details"]["due_now"]["date"] == "2026-11-01"
    assert record["details"]["account_holder"]["text"] == "Jordan A. Rivera"
    assert TOTAL_NOTE in run.notes
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]


def test_sc140_a_photographed_bill_whose_amount_due_cites_a_plain_amount_due_reads_exactly_as_before(pdf_store, local_model):
    transcription = [line for line in bf.total_transcription() if not line.startswith("Current Charges due")] + ["Amount Due $62.91"]
    fields = {**FIELDS, "amount_due": ("62.91", "Amount Due", "$62.91"), "due_date": ("2026-11-01", "Account Name", "")}
    fields.pop("due_date")
    run = scanned_total(pdf_store, local_model, transcription, fields)
    assert run.record["amount_due_minor"] == 6291 and run.record["total_minor"] == 166791 and "due_now" not in (run.record["details"] or {})


def test_sc132_the_model_s_new_charges_citing_the_due_now_line_is_dropped_on_a_photographed_bill_and_the_lines_count(pdf_store, local_model):
    run = scanned_total(pdf_store, local_model, bf.total_transcription(), WRONG)
    record = run.record
    assert record["total_minor"] == 166791 and record["amount_due_minor"] == 6291  # The lines count; FR-145 needs a `Total ...` new-charges line for the amount due.
    assert record["review_status"] == "needs_review" and "New charges: the cited line \"Current Charges due 11/01/2026\" is a due-now line, not the bill's new charges; it was left out." in run.notes
    Ledger(run.store).review("receipt", run.run["publication"]["id"], "verified")
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]


def test_sc132_a_due_now_amount_is_never_what_a_bill_counts_even_when_nothing_else_is_read(pdf_store, local_model):
    run = scanned_total(pdf_store, local_model, bf.total_transcription(), WRONG, rows={})  # The model gives no lines, and new charges 62.91 from the due-now line.
    record = run.record
    assert record["amount_due_minor"] == 6291  # The model's answer, the bill's due-now amount.
    assert run.bill_row()["total_minor"] is None and record["total_minor"] is None  # Nothing is counted: the old fallback counted 62.91.
    assert any(issue.startswith("New charges: the bill's new charges were not read, and its amount due is the due-now amount") for issue in record["issues"])
    assert record["review_status"] == "needs_review" and paid(run.store) == []


def test_sc132_a_bill_read_after_the_engine_failed_is_read_like_a_photographed_one_and_still_counts_the_total(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.total_pages())
    run.__class__ = BillRun
    monkeypatch.setattr(extraction.bill_tables, "read", lambda evidence, firsts=None: (_ for _ in ()).throw(RuntimeError("synthetic engine failure")))
    run.stub_bill(bf.STUB_TOTAL, FIELDS, classify=PROVIDER, single_run=True)
    run.extract()
    assert extraction.BILL_FAILED_NOTE in run.notes
    assert (run.record["amount_due_minor"], run.bill_row()["total_minor"]) == (166791, 166791)
    assert run.record["review_status"] == "needs_review" and paid(run.store) == []  # The failure note sends it to review; it counts once confirmed.
    Ledger(run.store).review("receipt", run.run["publication"]["id"], "verified")
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]


def test_fr143_the_publish_fallback_to_the_amount_due_never_counts_a_due_now_amount():
    class Probe(Ledger):
        def publish_receipt(self, receipt, source, status):
            return receipt

    ledger = Probe.__new__(Probe)
    record = {"provider": PROVIDER, "currency": "USD", "issues": [], "locator": {}, "items": [], "amount_due_minor": 6291,
              "details": {"due_now": {"minor": 6291}}}
    assert ledger.publish_bill(record, {}, "proposed")["total_minor"] is None
    plain = {**record, "details": {}}
    assert ledger.publish_bill(plain, {}, "proposed")["total_minor"] == 6291  # A family's old bill with only its amount due keeps its total.
    assert ledger.publish_bill({**record, "total_minor": 166791}, {}, "proposed")["total_minor"] == 166791


# === FR-147: stored bills, re-reading and corrections ========================================================================================

def read_before(run, monkeypatch, fields=TOTAL_FIELDS):
    """The reading the previous version left: the due-now line was a charge row, so the amount due was the model's 62.91."""
    run.stub_bill(bf.STUB_TOTAL, fields, classify=PROVIDER)
    with monkeypatch.context() as patch:
        patch.setattr(extraction, "EXTRACTION_VERSION", "typed-extraction-v51-bill-account-holder")
        patch.setattr(charge_tables, "due_now_of", lambda label: None)
        patch.setattr(bill_split, "due_now_of", lambda label: None)
        patch.setattr(extraction, "due_now_of", lambda label: None)
        run.extract()
    with run.store.connection() as db:
        db.execute("UPDATE receipts SET review_status='needs_review' WHERE id=?", (run.run["publication"]["id"],))
    assert run.record["amount_due_minor"] == 6291 and "due_now" not in (run.record["details"] or {})


def read_again(run, fields=TOTAL_FIELDS):
    run.stub_bill(bf.STUB_TOTAL, fields, classify=PROVIDER)
    config = ReasoningConfig(base_url=run.local_model["config"].base_url, model="synthetic-reasoning")
    run_id, reused = run.extraction.enqueue(run.doc["id"], run.parse_id, config)
    assert reused is True
    run.extraction.run(run_id, Work.detached())
    run.run = run.extraction.get(run_id)
    assert run.run["status"] == "succeeded", run.run["error"]


def test_sc143_the_version_moved_an_undecided_bill_gains_its_total_and_its_due_now_line_on_extract_again(pdf_store, local_model, monkeypatch):
    assert extraction.EXTRACTION_VERSION == "typed-extraction-v55-bill-total-sign-rule"
    run = started(pdf_store, local_model, bf.total_pages())
    run.__class__ = BillRun
    read_before(run, monkeypatch)
    assert run.bill_row()["total_minor"] == 166791  # The engine already counted the printed total; the amount due and the extra row were wrong.
    read_again(run)
    assert run.record["amount_due_minor"] == 166791 and run.bill_row()["total_minor"] == 166791
    assert run.record["details"]["due_now"]["minor"] == 6291 and run.record["due_date"] == "2026-11-01"
    assert [item["description"] for item in run.record["items"]] == ["Delivery Charges", "Supply Charges", "Taxes and Fees"]
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]


def test_sc143_a_correction_of_the_amount_due_made_before_the_re_read_wins_and_stays_in_the_history(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.total_pages())
    run.__class__ = BillRun
    read_before(run, monkeypatch)
    receipt_id, ledger = run.run["publication"]["id"], Ledger(run.store)
    ledger.correct("receipt", receipt_id, {"amount_due": "70.00"})
    read_again(run)
    assert run.record["amount_due_minor"] == 7000 and run.bill_row()["total_minor"] == 166791
    assert run.record["details"]["due_now"]["minor"] == 6291  # Still shown: 62.91 differs from the corrected 70.00.
    assert any(entry["field"] == "amount_due" for entry in ledger.record("receipt", receipt_id)["corrections"])


def test_sc143_a_confirmed_bill_is_never_rewritten(pdf_store, local_model, monkeypatch):
    run = started(pdf_store, local_model, bf.total_pages())
    run.__class__ = BillRun
    read_before(run, monkeypatch)
    receipt_id = run.run["publication"]["id"]
    Ledger(run.store).review("receipt", receipt_id, "verified")
    before = run.bill_row()
    read_again(run)
    after = run.bill_row()
    assert (after["amount_due_minor"], after["total_minor"], after["details_json"]) == (before["amount_due_minor"], before["total_minor"], before["details_json"])
    assert after["amount_due_minor"] == 6291


# === FR-148: deterministic =======================================================================================================================

def test_fr148_a_second_reading_changes_nothing_and_asks_the_model_nothing_more(pdf_store, local_model):
    run = total(pdf_store, local_model)
    first, first_notes, first_questions = snapshot(run), run.notes, run.asked()
    run.stub_bill(bf.STUB_TOTAL, FIELDS, classify=PROVIDER)
    run.extract(force=True)
    assert snapshot(run) == first and run.notes == first_notes and run.asked() == first_questions


# === FR-149: diagnose counts due-now lines and prints no label, amount or date ================================================================

def test_sc145_diagnose_counts_due_now_lines_per_page_and_prints_nothing_of_them(tmp_path):
    from test_bill_engine_generator import probe, written
    named = probe(written(tmp_path, "total.pdf", bf.total_pages()), tmp_path)
    plain = probe(written(tmp_path, "util.pdf", bf.util_pages()), tmp_path)
    assert named.returncode == 0 and plain.returncode == 0, (named.stderr[-300:], plain.stderr[-300:])
    assert "due-now lines: 1" in named.stdout and "due-now lines: 0" in plain.stdout
    for text in ("Current Charges", "62.91", "1,667.91", "11/01/2026", "LAKESIDE"):
        assert text not in named.stdout, text


# === Code review round 1 (plans/bill-total-and-account-holder/reviews.md): the cases that counted 62.91, lost a sign or passed an impossible date ===========

DUE_ROW = {"Current Charges due": ("Current Charges due", "service", "utilities", None, "62.91", None, None)}
NO_NEW_CHARGES = {name: found for name, found in FIELDS.items() if name != "new_charges"}


def test_review1_a_photographed_bill_whose_model_returns_the_due_now_summary_as_a_charge_row_counts_nothing_instead_of_62_91(pdf_store, local_model):  # Finding 1
    run = scanned_total(pdf_store, local_model, bf.total_transcription(), NO_NEW_CHARGES, rows=DUE_ROW)
    record = run.record
    assert record["items"] == [] and record["total_minor"] is None and run.bill_row()["total_minor"] is None  # The due-now line is no charge.
    assert record["review_status"] == "needs_review" and paid(run.store) == []
    assert any(note.startswith("The charge line \"Current Charges due\" cites the due-now line") and note.endswith("it was left out.") for note in run.notes)
    assert any(issue.startswith("New charges: the bill's new charges were not read, and its amount due is the due-now amount") for issue in record["issues"])


def test_review1_a_due_now_row_among_real_charge_rows_is_left_out_and_the_rows_still_add_up_to_the_printed_total(pdf_store, local_model):  # Finding 1
    run = scanned_total(pdf_store, local_model, bf.total_transcription(), FIELDS, rows={**bf.STUB_TOTAL, **DUE_ROW})
    record = run.record
    assert [item["line_total_minor"] for item in record["items"]] == [118040, 41226, 7525]
    assert (record["total_minor"], record["amount_due_minor"]) == (166791, 166791)
    assert record["review_status"] == "verified" and paid(run.store) == [("bill", "2026-11-01", 166791)]


def test_review1_an_engine_found_due_now_line_with_no_new_charges_line_still_drops_the_models_new_charges_that_cite_it(pdf_store, local_model):  # Finding 2
    pages = bf.total_pages(total_label=None)
    run = total(pdf_store, local_model, fields=WRONG, pages=pages)
    record = run.record
    assert record["total_minor"] == 166791 and run.bill_row()["total_minor"] == 166791  # The charge rows' sum, never the due-now 62.91.
    assert "New charges: the cited line \"Current Charges due 11/01/2026\" is a due-now line, not the bill's new charges; it was left out." in run.notes
    assert record["amount_due_minor"] == 6291 and record["review_status"] == "needs_review"  # The engine's due-now amount, the only amount printed: the lines disagree.
    assert any(issue.startswith("Amount due: the lines add up to 1,667.91 USD, but the amount due is 62.91 USD") for issue in record["issues"])
    Ledger(run.store).review("receipt", run.run["publication"]["id"], "verified")
    assert paid(run.store) == [("bill", "2026-11-01", 166791)]


@pytest.mark.parametrize("printed, held", [("-$62.91", -6291), ("$-62.91", -6291), ("($62.91)", -6291), ("(62.91)", -6291), ("62.91-", -6291), ("$62.91 CR", -6291),
                                           ("62.91 CR", -6291), ("$-62.91 CR", -6291), ("-62.91 CR", -6291), ("$62.91", 6291)])
def test_review1_a_photographed_due_now_credit_keeps_its_sign_and_is_no_payment_candidate(pdf_store, local_model, printed, held):  # Finding 3, round 2 R2-1: signs apply once
    transcription = [*bf.total_transcription()[:-2], f"Current Charges due 11/01/2026 {printed}", "Total Current Charges $1,667.91"]
    fields = {**FIELDS, "amount_due": ("-62.91" if held < 0 else "62.91", "Current Charges due", printed)}
    run = scanned_total(pdf_store, local_model, transcription, fields)
    assert due_now_of_record(run)["minor"] == held
    ledger = Ledger(run.store)
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    [payment] = add(run.store, ledger, checking, run.doc, [("2026-10-30", "LAKESIDE GAS & ELECTRIC ACH", -6291)])
    Reconciler(run.store).run()
    links = ledger.record("receipt", run.run["publication"]["id"])["links"]
    assert [link["counterpart"]["id"] for link in links] == ([payment] if held > 0 else [])  # A credit of 62.91 is not an outgoing 62.91.


MARKERS = ("lead", "paren", "trail", "cr")


def printed_amount(markers, dollar, code):
    """62.91 as a bill prints it with the given negative markers ("lead" minus, "paren" parentheses, "trail" minus, "cr"), the `$` before everything
    (`$-62.91`, `$(62.91)`), after the opening parenthesis (`($-62.91)`, `($62.91)`) or after the minus, right before the digits (`-$62.91`, `(-$62.91)`), and an ISO
    code before or after the number."""
    body = ("$" if dollar == "mid" else "") + ("-" if "lead" in markers else "") + ("$" if dollar == "inner" else "") + "62.91" + ("-" if "trail" in markers else "")
    body = f"({body})" if "paren" in markers else body
    body = f"${body}" if dollar == "outer" else body
    body = f"USD {body}" if code == "before" else f"{body} USD" if code == "after" else body
    return body + (" CR" if "cr" in markers else "")


def sign_cases():
    """Every combination of the four negative markers (none, each, each pair, each triple, all four) x no currency sign / `$` before / `$` after the parenthesis / `$` after the minus x
    no code / a code before / a code after, each printed form once."""
    seen, cases = set(), []
    for size in range(len(MARKERS) + 1):
        for markers in itertools.combinations(MARKERS, size):
            for dollar in ("none", "outer", "mid", "inner"):
                for code in ("none", "before", "after"):
                    printed = printed_amount(markers, dollar, code)
                    if printed not in seen:
                        seen.add(printed)
                        cases.append(pytest.param(printed, bool(markers), id=printed))
    return cases


SIGN_CASES = sign_cases()


def test_review3_the_sign_matrix_has_every_combination_once():
    assert len(SIGN_CASES) == len({case.id for case in SIGN_CASES}) > 100
    assert {case.id for case in SIGN_CASES} >= {"(-62.91)", "($-62.91)", "($62.91)", "-62.91-", "-$62.91", "$-62.91", "$-62.91 CR", "-$62.91- CR", "$(-62.91-) CR",
                                                "USD $62.91", "62.91 USD", "(-62.91) USD CR", "62.91", "$62.91", "USD 62.91"}


@pytest.mark.parametrize("printed, negative", SIGN_CASES)
def test_review3_a_due_now_amount_is_negative_when_any_negative_marker_is_printed_and_positive_with_none(printed, negative):  # R3-1, one rule, applied once
    found = extraction.due_now_line(f"{DUE_NOW_LINE} {printed}")
    assert found is not None and found["label"] == DUE_NOW_LINE and found["date"] == "11/01/2026"
    assert extraction.due_now_minor(found, "USD") == (-6291 if negative else 6291)


@pytest.mark.parametrize("printed, negative", SIGN_CASES)
def test_review3_a_signed_due_now_amount_is_stored_with_its_sign_and_never_links_an_outgoing_payment(pdf_store, local_model, printed, negative):  # R3-1, FR-141/143/145
    transcription = [*bf.total_transcription()[:-2], f"{DUE_NOW_LINE} {printed}", "Total Current Charges $1,667.91"]
    fields = {**FIELDS, "amount_due": ("-62.91" if negative else "62.91", "Current Charges due", printed)}
    run = scanned_total(pdf_store, local_model, transcription, fields)
    record = run.record
    assert (record["total_minor"], record["amount_due_minor"]) == (166791, 166791)
    assert record["issues"] == [] and record["review_status"] == "verified"
    assert due_now_of_record(run)["minor"] == (-6291 if negative else 6291)
    ledger = Ledger(run.store)
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    [payment] = add(run.store, ledger, checking, run.doc, [("2026-10-30", "LAKESIDE GAS & ELECTRIC ACH", -6291)])
    Reconciler(run.store).run()
    links = ledger.record("receipt", run.run["publication"]["id"])["links"]
    assert [link["counterpart"]["id"] for link in links] == ([] if negative else [payment])  # A credit of 62.91 is never an outgoing 62.91.


@pytest.mark.parametrize("printed", ["$62.91", "-$62.91", "$-62.91", "($62.91)", "(62.91)", "62.91-", "62.91 CR", "$62.91 CR", "-62.91 CR", "$-62.91 CR", "62.91 DR", "(-62.91)", "($-62.91)", "-62.91-", "(62.91) CR"])
def test_review3_a_text_pdf_due_now_amount_has_the_same_sign_rule(pdf_store, local_model, printed):  # R3-1: the engine path
    run = total(pdf_store, local_model, pages=bf.total_pages(due_amount=printed))
    record = run.record
    assert (record["total_minor"], record["amount_due_minor"]) == (166791, 166791)
    negative = printed not in ("$62.91", "62.91 DR")
    assert due_now_of_record(run)["minor"] == (-6291 if negative else 6291)


@pytest.mark.parametrize("printed", ["(62.91", "62.91)", "62.91 EUR", "EUR 62.91", "62.91 GBP CR", "$$62.91"])
def test_review3_an_unparseable_due_now_amount_is_left_out_with_a_review_issue_and_never_stored_positive(pdf_store, local_model, printed):  # R3-1
    transcription = [*bf.total_transcription()[:-2], f"{DUE_NOW_LINE} {printed}", "Total Current Charges $1,667.91"]
    fields = {**FIELDS, "amount_due": ("62.91", "Current Charges due", printed)}
    run = scanned_total(pdf_store, local_model, transcription, fields)
    record = run.record
    assert (record["details"] or {}).get("due_now") is None
    assert any(issue.startswith("Due now:") for issue in record["issues"]) and record["review_status"] == "needs_review"
    assert [link for link in Ledger(run.store).record("receipt", run.run["publication"]["id"])["links"]] == []


RENT_TRANSCRIPTION = ["SYNTH PROPERTY MANAGEMENT", "Resident Account ****4821", "Statement Date 10/10/2026", "Rent and Leasing Charges Due 10/01/2026",
                      "Rent 10/01/2026 - 10/31/2026 1,650.00", "Water Usage 17.91", "Previous Balance 50.00", "Payments Received PAYMENTS",
                      "Current Charges due 11/01/2026 $62.91", "Total Current Charges $1,667.91"]
RENT_ROWS = {"Rent 10/01": ("Rent", "rent", "housing", None, "1,650.00", None, None), "Water Usage": ("Water", "utility", "utilities", None, "17.91", None, None)}


@pytest.mark.parametrize("payments, due", [("20.00", 169791), ("0.00", 171791)])
def test_review1_a_photographed_rent_bill_works_the_amount_due_out_with_its_payments(pdf_store, local_model, payments, due):  # Finding 4
    transcription = [line.replace("PAYMENTS", payments) for line in RENT_TRANSCRIPTION]
    fields = {"provider": ("SYNTH PROPERTY MANAGEMENT", "SYNTH PROPERTY MANAGEMENT", "SYNTH PROPERTY MANAGEMENT"), "currency": ("USD", "Resident Account", "****4821"),
              "new_charges": ("1,667.91", "Total Current Charges", "$1,667.91"), "amount_due": ("62.91", "Current Charges due", "$62.91"),
              "previous_balance": ("50.00", "Previous Balance", "50.00"), "payments_received": (payments, "Payments Received", payments)}
    run = started_scanned(pdf_store, local_model, transcription)
    run.stub_bill(RENT_ROWS, fields, kind="rent", classify="SYNTH PROPERTY", single_run=True)
    run.extract()
    record = run.record
    assert record["amount_due_minor"] == due and record["total_minor"] == 166791
    assert f"The amount due is worked out as previous balance 50.00 − payments {payments} + new charges 1667.91 = {due / 100:.2f}." in run.notes
    assert not [issue for issue in record["issues"] if issue.startswith("Amount due:")]  # No carried-check failure.


@pytest.mark.parametrize("payments, field", [("20.001", "20.001"), ("20.00 EUR", "20.00 EUR")])
def test_review2_a_cited_payments_amount_that_is_not_valid_money_is_left_out_with_its_issue_and_extraction_still_succeeds(pdf_store, local_model, payments, field):  # R2-2
    transcription = [line.replace("PAYMENTS", payments) for line in RENT_TRANSCRIPTION]
    fields = {"provider": ("SYNTH PROPERTY MANAGEMENT", "SYNTH PROPERTY MANAGEMENT", "SYNTH PROPERTY MANAGEMENT"), "currency": ("USD", "Resident Account", "****4821"),
              "new_charges": ("1,667.91", "Total Current Charges", "$1,667.91"), "amount_due": ("62.91", "Current Charges due", "$62.91"),
              "previous_balance": ("50.00", "Previous Balance", "50.00"), "payments_received": (field, "Payments Received", payments)}
    run = started_scanned(pdf_store, local_model, transcription)
    run.stub_bill(RENT_ROWS, fields, kind="rent", classify="SYNTH PROPERTY", single_run=True)
    run.extract()
    record = run.record
    assert run.run["status"] != "failed" and run.run["publication"] is not None
    assert any(issue.startswith("Payments received:") for issue in record["issues"]) and record["review_status"] == "needs_review"
    assert record["total_minor"] == 166791 and record["amount_due_minor"] == 166791  # The new charges alone: nothing is worked out from the bad payments.
    assert not [note for note in run.notes if "worked out" in note] and (record["details"]["due_now"] or {}).get("worked") is None


def test_review1_a_due_now_date_before_the_issue_date_is_no_fallback_due_date_both_dates_are_left_out(pdf_store, local_model):  # Finding 5
    header = ("LAKESIDE GAS & ELECTRIC", "Account Name: Jordan A. Rivera", "Account Number 4455-6677-8899", "Statement Date 11/10/2026", "Billing Period 09/01/2026 - 09/30/2026")
    fields = {**TOTAL_FIELDS, "issue_date": ("2026-11-10", "Statement Date", "11/10/2026")}  # No due date from the model: the due-now line (11/01) would be it.
    run = total(pdf_store, local_model, fields=fields, pages=bf.total_pages(header=header))
    record = run.record
    assert record["issue_date"] is None and record["due_date"] is None
    assert "Due date: the issued date (2026-11-10) is after the due date; both were left out." in record["issues"]
    assert record["review_status"] == "needs_review" and (run.bill_row()["due_date"], run.bill_row()["purchase_date"]) != ("2026-11-01", "2026-11-01")
    assert due_now_of_record(run)["date"] == "2026-11-01"  # Still shown as printed.


def test_review1_a_due_now_date_after_the_issue_date_is_still_the_fallback_due_date(pdf_store, local_model):  # Finding 5, the month-first fallback unchanged
    run = total(pdf_store, local_model, fields=TOTAL_FIELDS)
    assert run.record["due_date"] == "2026-11-01" and run.record["issue_date"] == "2026-10-10" and run.record["review_status"] == "verified"


SEPARATED = [("Current Charges - due 11/01/2026", "dash"), ("Current Charges – due 11/01/2026", "en dash"), ("Current Charges — due 11/01/2026", "em dash"),
             ("Current Charges: due 11/01/2026", "colon"), ("Current Charges ..... due 11/01/2026", "dot leaders"), ("Current Charges | due 11/01/2026", "pipe"),
             ("Current Charges due - 11/01/2026", "dash before the date"), ("Current Charges – due by – 11/01/2026", "two en dashes"), ("$ Current Charges due 11/01/2026", "dollar")]


@pytest.mark.parametrize("label, what", SEPARATED)
def test_review1_a_separator_in_a_due_now_label_is_cleaned_as_fr103_cleans_it(label, what):  # Finding 6: the rule, the anchor and the split rule
    found = due_now_of(label)
    assert found is not None and found[0] == "11/01/2026", what
    assert anchor_kind(label) is None
    line = SimpleNamespace(id="page-1-layout-line-1", text=f"{label} $62.91")  # FR-146: the split rule's own recognition.
    assert bill_split.anchor_of(line) == (DUE_NOW, bill_split.anchor_of(line)[1])


@pytest.mark.parametrize("label", ["Current Charges - due 11/01/2026", "Current Charges: due 11/01/2026", "Current Charges ..... due 11/01/2026"])  # (the PDF font has no en dash)
def test_review1_the_engine_reads_a_separated_due_now_label_as_the_due_now_line_and_never_as_a_charge_row(pdf_store, local_model, label):  # Finding 6
    pages = bf.total_pages(due_label=label)
    run = started(pdf_store, local_model, pages)
    reading = bill_tables.read(run.evidence).reading
    assert [(anchor.kind, anchor.token.text) for anchor in reading.anchors] == [(DUE_NOW, "$62.91"), ("new_charges", "$1,667.91")]
    assert [row.label for table in reading.tables for row in table.rows] == ["Delivery Charges", "Supply Charges", "Taxes and Fees"] and reading.unplaced == []
    fields = {**FIELDS, "amount_due": ("62.91", "Current Charges", "$62.91"), "due_date": ("2026-11-01", "Current Charges", "11/01/2026")}
    done = total(pdf_store, local_model, fields=fields, pages=pages, name="separated.pdf")
    assert (done.record["amount_due_minor"], done.record["total_minor"], len(done.record["items"])) == (166791, 166791, 3)
    assert done.record["review_status"] == "verified" and due_now_of_record(done)["minor"] == 6291
