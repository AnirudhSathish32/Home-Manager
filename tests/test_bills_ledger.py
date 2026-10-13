"""Bills with line items, and money in on the ledger (docs/money.md "Bills and their lines", "Money in and paystubs";
docs/family.md "Who has what", "Sharing a bill by line"). Synthetic records only."""

from datetime import date, timedelta
from decimal import Decimal
import hashlib
import os
import re

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.app.family_sync import FamilyFolder
from home_manager.finance.family_routing import FamilyRouting, apply_delivery, import_request, record_payload
from home_manager.finance.forecast import Assets, baseline
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, PeriodInput, SpendingItemsInput, TransactionsInput
from home_manager.library.storage import Store
from seed_documents import seed_bill
from test_extraction import MISSING, cite, extract, transcribe, value
from test_reconcile_tools import add, source_of
from test_taxes_v2_browser import served

SEPTEMBER = PeriodInput(start="2026-09-01", end="2026-09-30")
FILES = {"export.csv": b"date,amount\n", "rent.png": b"synthetic rent bill", "phone.png": b"synthetic phone bill", "stub.png": b"synthetic pay stub"}
WHO = [{"member_id": "alex", "kind": "phone", "last_four": "1111", "label": "Alex"}, {"member_id": "blair", "kind": "phone", "last_four": "2222", "label": "Blair"},
       {"member_id": "casey", "kind": "phone", "last_four": "3333", "label": "Casey"}]


def open_books(root):
    store = Store(root)
    inbox_scan(store, FILES)
    return store, Ledger(store), documents_by_name(store)


@pytest.fixture
def books(tmp_path):
    store, ledger, docs = open_books(tmp_path / "managed")
    try:
        yield store, ledger, docs
    finally:
        store.close()


def line(description, amount, category, kind="service", holder=None):
    return {"description": description, "line_total_minor": amount, "category": category, "line_kind": kind, "line_holder": holder,
            "locator": {"line_ids": ["line-2"]}}


def bill(ledger, doc, provider, due, lines, issue=None, last_four=None, status="verified"):
    total = sum(item["line_total_minor"] for item in lines)
    return ledger.publish_bill({"provider": provider, "issue_date": issue, "due_date": due, "period_start": None, "period_end": None,
                                "amount_due_minor": total, "total_minor": total, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]},
                                "items": lines, "category": None, "recurrence": "monthly", "last_four": last_four},
                               source_of(doc, "extraction:" + doc["relative_path"]), status)["id"]


def rent_and_water(ledger, doc, status="verified"):
    return bill(ledger, doc, "Oakwood Apartments", "2026-09-28", [line("Rent", 150000, "housing"), line("Water", 4520, "utilities", "usage"),
                                                                   line("Trash", 1500, "utilities")], issue="2026-09-01", last_four="7788", status=status)


def phone_bill(ledger, doc):
    return bill(ledger, doc, "Acme Wireless", "2026-09-28", [
        line("Unlimited plan", 4000, "phone & internet", holder="Alex 555-201-1111"),
        line("Unlimited plan", 3000, "phone & internet", holder="Blair 555-202-2222"),
        line("Basic plan", 2000, "phone & internet", holder="Casey 555-203-3333"),
        line("Apple TV+", 999, "subscriptions", "subscription", holder="Alex 555-201-1111"),
        line("Taxes, surcharges and fees", 1800, "phone & internet", "tax_fee")], issue="2026-09-05")


def by_category(store):
    return {row["category"]: row["spending"]["minor"] for row in FinanceTools(store).get_spending_by_category(SEPTEMBER)["categories"]}


def spending(store):
    rows = FinanceTools(store).get_spending(SEPTEMBER)["by_currency"]
    return rows[0]["spending"]["minor"] if rows else 0


PHONE_TEXT = ["ACME WIRELESS", "Account 0000 4821", "Bill date 2026-09-05", "Due 2026-09-28", "Alex 555-201-1111 Unlimited 40.00",
              "Apple TV+ 9.99", "Taxes and fees 18.00", "Past due 12.00", "New charges 67.99", "Amount due USD 79.99"]


def test_a_bill_is_read_by_line_and_counts_its_new_charges(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, PHONE_TEXT)
    header = {"provider": value("ACME WIRELESS", 1), "account_reference": value("4821", 2, "Account 0000 4821"), "issue_date": value("2026-09-05", 3),
              "due_date": value("2026-09-28", 4), "period_start": MISSING, "period_end": MISSING, "amount_due": value("79.99", 10, "Amount due USD 79.99"),
              "new_charges": value("67.99", 9, "New charges 67.99"), "currency": value("USD", 10, "USD")}
    rows = [{"description": "Unlimited", "amount": "40.00", "category": "phone & internet", "line_kind": "service", "line_holder": "Alex 555-201-1111",
             "evidence": cite(5, PHONE_TEXT[4])},
            # A holder that isn't printed where the line is cited is left out, never guessed.
            {"description": "Apple TV+", "amount": "9.99", "category": "subscriptions", "line_kind": "subscription", "line_holder": "Alex 555-201-1111",
             "evidence": cite(6, PHONE_TEXT[5])},
            {"description": "Taxes and fees", "amount": "18.00", "category": None, "line_kind": "tax_fee", "line_holder": None, "evidence": cite(7, PHONE_TEXT[6])}]
    local_model["outputs"] = [{"document_type": "bill", "evidence": cite(1, "ACME WIRELESS"), "issuer": value("ACME WIRELESS", 1), "document_date": MISSING},
                              header, {"line_items": rows}]
    try:
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert (run["publication"]["document_kind"], run["publication"]["review_status"]) == ("bill", "verified")  # The lines reach the new charges.
        record = manager.ledger.record("receipt", run["publication"]["id"])
        # The past-due 12.00 is in the amount due, never in what counts.
        assert (record["total_minor"], record["amount_due_minor"], record["account_last_four"], record["purchase_date"]) == (6799, 7999, "4821", "2026-09-28")
        assert [(item["line_holder"], item["line_kind"], item["category"]) for item in record["items"]] == [
            ("Alex 555-201-1111", "service", "phone & internet"), (None, "subscription", "subscriptions"), (None, "tax_fee", None)]
        assert (record["category"], record["recurrence"], record["includes"]) == ("phone & internet", "monthly", ["Apple TV+"])
        # A line with no category counts under the bill's own.
        assert {row["category"]: row["amount_minor"] for row in record["splits"]} == {"phone & internet": 5800, "subscriptions": 999}
        assert manager.store.document(doc["id"])["folder"] == "Bills"
    finally:
        manager.close()


def test_a_bill_counts_by_its_lines_on_its_due_date_until_its_payment_replaces_it(books):
    store, ledger, docs = books
    rent = rent_and_water(ledger, docs["rent.png"])
    record = ledger.record("receipt", rent)
    assert (record["document_kind"], record["purchase_date"], record["total_minor"], record["includes"]) == ("bill", "2026-09-28", 156020, [])
    # Rent is housing, water and trash utilities: the bill counts on its due date by its lines.
    assert spending(store) == 156020 and by_category(store) == {"housing": 150000, "utilities": 6020}
    listed = FinanceTools(store).get_transactions(TransactionsInput(start="2026-09-01", end="2026-09-30", include_documents=True))
    assert [(row["source"], row["posted_date"], row["amount_minor"]) for row in listed["transactions"]] == [("bill", "2026-09-28", -156020)]
    assert [(row["out"]["minor"], row["in"]["minor"]) for row in listed["totals"]] == [(156020, 0)]

    checking = ledger.create_account("First Local Bank", "checking", "USD")
    # Same amount, but nothing names the provider or the bill's account: never taken for its payment.
    stranger = add(store, ledger, checking, docs["export.csv"], [("2026-09-20", "CHECK 1043", -156020)])
    Reconciler(store).run()
    assert ledger.record("receipt", rent)["links"] == []
    # Paid on the due date by a line naming the bill's account number: the line replaces the bill.
    [payment] = add(store, ledger, checking, docs["export.csv"], [("2026-09-27", "ACH PMT ACCT 7788", -156020)])
    Reconciler(store).run()
    [link] = ledger.record("receipt", rent)["links"]
    assert link["counterpart"]["id"] == payment and link["counterpart"]["id"] not in stranger
    tools = FinanceTools(store)
    totals = tools.get_spending(SEPTEMBER)["by_currency"][0]
    assert (totals["spending"]["minor"], totals["from_receipts"]["minor"]) == (156020 * 2, 0)  # The check counts on its own.
    assert by_category(store) == {"housing": 150000, "utilities": 6020, "uncategorized": 156020}  # The payment takes the bill's lines.
    listed = tools.get_transactions(TransactionsInput(start="2026-09-01", end="2026-09-30", include_documents=True))
    assert {row["source"] for row in listed["transactions"]} == {"transaction"}
    assert_ledger_healthy(store)


def test_a_bill_paid_after_its_window_is_not_matched_and_a_verified_bill_proposes_its_recurring_bill(books):
    store, ledger, docs = books
    rent = rent_and_water(ledger, docs["rent.png"])
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [("2026-10-04", "OAKWOOD APARTMENTS", -156020)])  # Due Sep 28; five days later is Oct 3.
    Reconciler(store).run()
    assert ledger.record("receipt", rent)["links"] == []
    [obligation] = FinanceTools(store).get_recurring_obligations()["obligations"]
    assert (obligation["merchant"], obligation["frequency"], obligation["source_receipt_id"], obligation["category"]) == (
        "Oakwood Apartments", "monthly", rent, "housing")


def test_a_bill_lines_type_and_person_survive_reading_it_again(books):
    store, ledger, docs = books
    rent = rent_and_water(ledger, docs["rent.png"], status="needs_review")
    ledger.correct_line(rent, 3, "line_kind", "tax_fee")
    with pytest.raises(ValueError, match="listed line types"):
        ledger.correct_line(rent, 3, "line_kind", "snacks")
    with pytest.raises(ValueError, match="someone in the family"):
        ledger.correct_line(rent, 3, "member", "stranger")
    rent_and_water(ledger, docs["rent.png"], status="needs_review")  # Read again.
    record = ledger.record("receipt", rent)
    assert record["items"][2]["line_kind"] == "tax_fee"
    [entry] = [row for row in ledger.history("receipt", rent) if row["kind"] == "correction"]
    assert (entry["label"], entry["from"], entry["to"], entry["undoable"]) == ("Type of Trash", "service", "tax_fee", True)
    assert ledger.undo_corrections("receipt", rent, [entry["id"]])["items"][2]["line_kind"] == "service"


def test_deleting_a_bill_line_updates_splits_and_survives_a_new_reading(books):
    store, ledger, docs = books
    receipt_id = rent_and_water(ledger, docs["rent.png"], status="needs_review")
    original = ledger.record("receipt", receipt_id)
    removed_id = original["items"][1]["id"]
    record = ledger.delete_item(receipt_id, 2)
    assert [item["description"] for item in record["items"]] == ["Rent", "Trash"]
    assert record["total_minor"] == original["total_minor"] == 156020
    assert sum(part["amount_minor"] for part in record["splits"]) == 156020
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM receipt_items WHERE id=?", (removed_id,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM category_splits WHERE receipt_item_id=?", (removed_id,)).fetchone()[0] == 0
    with pytest.raises(ValueError, match="not found"):
        ledger.delete_item(receipt_id, 2)
    rent_and_water(ledger, docs["rent.png"], status="needs_review")
    assert [item["description"] for item in ledger.record("receipt", receipt_id)["items"]] == ["Rent", "Trash"]
    assert_ledger_healthy(store)


def test_deleting_one_of_two_same_named_bill_lines_keeps_the_other(books):
    _, ledger, docs = books
    receipt_id = bill(ledger, docs["phone.png"], "Acme Wireless", "2026-09-28", [
        line("Unlimited plan", 4000, "phone & internet"), line("Unlimited plan", 3000, "phone & internet")], status="needs_review")
    ledger.delete_item(receipt_id, 1)
    bill(ledger, docs["phone.png"], "Acme Wireless", "2026-09-28", [
        line("Unlimited plan", 4000, "phone & internet"), line("Unlimited plan", 3000, "phone & internet")], status="needs_review")
    assert [(item["position"], item["line_total_minor"]) for item in ledger.record("receipt", receipt_id)["items"]] == [(2, 3000)]


def test_who_has_what_is_checked_and_holds_last_four_digits_only(tmp_path):
    family = FamilyFolder.create(tmp_path / "family", "The Testers")
    try:
        alex, blair = (family.add_member(name, "remote")["member_id"] for name in ("Alex", "Blair"))
        entry = {"member_id": alex, "kind": "phone", "last_four": "1111", "label": "Alex's phone"}
        for wrong, message in [({**entry, "member_id": "0" * 12}, "someone in the family"), ({**entry, "kind": "pager"}, "phone line or a card"),
                               ({**entry, "last_four": "5552011111"}, "last four digits"), ({**entry, "last_four": "11a1"}, "last four digits")]:
            with pytest.raises(ValueError, match=message):
                family.set_who_has_what([wrong])
        with pytest.raises(ValueError, match="listed twice"):
            family.set_who_has_what([entry, {**entry, "member_id": blair}])
        saved = family.set_who_has_what([entry, {"member_id": blair, "kind": "card", "last_four": "4242", "label": "Visa"}])
        assert saved == [entry, {"member_id": blair, "kind": "card", "last_four": "4242", "label": "Visa"}]
        assert family.summary()["who_has_what"] == saved
        family.remove_member(blair)
        assert family.who_has_what() == [entry]
    finally:
        family.close()


def test_a_phone_bill_is_shared_by_line_and_the_payers_charge_counts_only_their_part(tmp_path):
    inbox, ledger, docs = open_books(tmp_path / "family")
    people = {name: open_books(tmp_path / name)[0] for name in ("alex", "blair", "casey")}
    try:
        phone = phone_bill(ledger, docs["phone.png"])
        assert ledger.record("receipt", phone)["includes"] == ["Apple TV+"]
        routing = FamilyRouting(inbox)
        routing.refresh({}, WHO[:2])
        [listed] = routing.list()
        # Casey's line isn't in Who has what yet: asked once, and the lines named so far are suggested.
        assert (listed["bill"], listed["suggested"]["mode"], listed["suggested"]["ask"]) == (True, "lines", {"kind": "phone", "last_four": "3333"})
        routing.refresh({}, WHO)
        [listed] = routing.list()
        assert (listed["suggested"]["mode"], listed["suggested"]["members"]) == ("lines", ["alex", "blair", "casey"])
        assert [line["member_id"] for line in listed["lines"]] == ["alex", "blair", "casey", "alex", None]
        routing.assign("receipt", phone, "lines", [], ["alex", "blair", "casey"])
        assignment, plan = routing.deliveries("receipt", phone)
        # Each person's own lines, and the 18.00 of taxes in proportion to them: 49.99, 30.00 and 20.00 of 99.99.
        assert plan == [("alex", "record", 5899), ("blair", "record", 3540), ("casey", "record", 2360)]
        record, name, document = routing.payload("receipt", phone)
        for member, _, share in plan:
            apply_delivery(people[member], {"key": assignment["family_record_key"], "action": "record", "record_type": "receipt", "record": record,
                                            "name": name, "blob_hash": hashlib.sha256(document).hexdigest(), "share": share,
                                            "people": ["Alex", "Blair", "Casey"], "share_member": member}, document)
        assert (spending(people["alex"]), by_category(people["alex"])) == (5899, {"phone & internet": 4900, "subscriptions": 999})
        assert (spending(people["blair"]), by_category(people["blair"])) == (3540, {"phone & internet": 3540})
        assert spending(people["casey"]) == 2360
        # Alex's card pays the whole bill: the charge replaces Alex's bill and counts only Alex's part.
        card = Ledger(people["alex"]).create_account("Card Co", "credit_card", "USD")
        add(people["alex"], Ledger(people["alex"]), card, documents_by_name(people["alex"])["export.csv"], [("2026-09-25", "ACME WIRELESS AUTOPAY", -11799)])
        Reconciler(people["alex"]).run()
        totals = FinanceTools(people["alex"]).get_spending(SEPTEMBER)["by_currency"][0]
        assert (totals["spending"]["minor"], totals["from_receipts"]["minor"]) == (5899, 0)
        assert by_category(people["alex"]) == {"phone & internet": 4900, "subscriptions": 999}
        for store in people.values():
            assert_ledger_healthy(store)
    finally:
        for store in (inbox, *people.values()):
            store.close()


def test_a_person_asks_the_family_to_share_their_bill_by_line(tmp_path):
    mine, ledger, docs = open_books(tmp_path / "alex")
    inbox = Store(tmp_path / "family")
    try:
        phone = phone_bill(ledger, docs["phone.png"])
        assert ledger.record("receipt", phone)["shareable_by_line"] is True
        with mine.connection() as db:
            db.execute("INSERT INTO share_requests(receipt_id,mode,requested_at) VALUES(?,'lines','t')", (phone,))
        record, row = record_payload(mine, "receipt", phone)
        document = mine.blob_path(row["blob_hash"]).read_bytes()
        copied = import_request(inbox, "alex", phone, record, "Alex bill", document)
        assert import_request(inbox, "alex", phone, record, "Alex bill", document) is None  # Once per request.
        routing = FamilyRouting(inbox)
        routing.refresh({}, WHO)
        [listed] = routing.list()
        assert (listed["id"], listed["suggested"]["requested_by"], listed["suggested"]["mode"]) == (copied, "alex", "lines")
        # The family's answer reaches Alex's own library and settles the request.
        routing.assign("receipt", copied, "lines", [], ["alex", "blair", "casey"])
        assignment, plan = routing.deliveries("receipt", copied)
        payload, name, sent = routing.payload("receipt", copied)
        apply_delivery(mine, {"key": assignment["family_record_key"], "action": "record", "record_type": "receipt", "record": payload, "name": name,
                              "blob_hash": hashlib.sha256(sent).hexdigest(), "share": plan[0][2], "people": [], "share_member": "alex"}, sent)
        assert ledger.record("receipt", phone)["share_request"] is None and spending(mine) == 5899
    finally:
        mine.close()
        inbox.close()


def test_a_pay_stub_counts_as_money_in_until_its_deposit_replaces_it(books):
    store, ledger, docs = books
    stub = ledger.publish_income({"payer_or_employer": "Acme Widgets", "pay_date": "2026-09-15", "period_start": None, "period_end": None,
                                  "gross_pay_minor": 320000, "net_pay_minor": 250000, "taxes_minor": 50000, "deductions_minor": 20000, "currency": "USD",
                                  "issues": [], "locator": {}}, source_of(docs["stub.png"], "extraction:stub"), "verified")["id"]
    tools = FinanceTools(store)

    def money_in():
        return tools.calculate_cashflow(SEPTEMBER)["by_currency"][0]["inflow"]["minor"]
    assert money_in() == 250000
    listed = tools.get_transactions(TransactionsInput(start="2026-09-01", end="2026-09-30", include_documents=True))
    assert [(row["source"], row["income_record_id"], row["amount_minor"]) for row in listed["transactions"]] == [("paystub", stub, 250000)]
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    [deposit] = add(store, ledger, checking, docs["export.csv"], [("2026-09-16", "ACME WIDGETS PAYROLL", 250000)])
    assert money_in() == 500000  # Until reconciliation links them, both are money in.
    assert Reconciler(store).run()["income_links"] == 1
    assert money_in() == 250000  # The deposit replaced the pay stub: counted once.
    [link] = ledger.record("income_record", stub)["links"]
    assert (link["kind"], link["counterpart"]["id"], link["match_signals"]) == ("income", deposit, ["amount", "payer"])
    items = tools.get_spending_items(SpendingItemsInput(start="2026-09-01", end="2026-09-30", direction="in"))
    assert [(row["kind"], row["status"], row["income_record_id"], row["amount_minor"]) for row in items["items"]] == [("income", "reconciled", stub, 250000)]
    with store.connection() as db:  # The forecast's income is cash flow's: the paycheck once.
        assert db.execute("SELECT count(*) FROM transaction_income_links WHERE review_status<>'rejected'").fetchone()[0] == 1
    assert baseline(tools, Assets(store), 3, today=date(2026, 10, 15))["monthly_income"] == Decimal(250000) / 3
    assert_ledger_healthy(store)


def test_two_deposits_for_one_pay_stub_are_asked_about(books):
    store, ledger, docs = books
    stub = ledger.publish_income({"payer_or_employer": "Acme Widgets", "pay_date": "2026-09-15", "period_start": None, "period_end": None,
                                  "gross_pay_minor": 320000, "net_pay_minor": 250000, "taxes_minor": None, "deductions_minor": None, "currency": "USD",
                                  "issues": [], "locator": {}}, source_of(docs["stub.png"], "extraction:stub"), "verified")["id"]
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    deposits = add(store, ledger, checking, docs["export.csv"], [("2026-09-14", "DEPOSIT", 250000), ("2026-09-17", "MOBILE DEPOSIT", 250000)])
    reconciler = Reconciler(store)
    assert reconciler.run()["income_links"] == 0
    [question] = [row for row in FinanceTools(store).review_queue()["issues"] if row["issue_type"] == "ambiguous_income_match"]
    assert (question["record"]["id"], sorted(row["id"] for row in question["candidates"])) == (stub, sorted(deposits))
    reconciler.resolve_issue(question["id"], deposits[1])
    assert FinanceTools(store).calculate_cashflow(SEPTEMBER)["by_currency"][0]["inflow"]["minor"] == 500000  # The pay stub, once; the other deposit.
    assert_ledger_healthy(store)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_bills_and_pay_stubs_on_transactions_and_the_document_page(tmp_path, local_model):
    """Charges lists a bill and a pay stub with their source; Out and In filter it with totals; the bill's page edits its lines."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bills-ledger-test"
    day = (date.today() - timedelta(days=5)).isoformat()
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        phone = seed_bill(manager, local_model)
        inbox_scan(manager.store, {"stub.png": FILES["stub.png"]})
        manager.ledger.publish_income({"payer_or_employer": "Acme Widgets", "pay_date": day, "period_start": None, "period_end": None, "gross_pay_minor": 320000,
                                       "net_pay_minor": 250000, "taxes_minor": None, "deductions_minor": None, "currency": "USD", "issues": [], "locator": {}},
                                      source_of(documents_by_name(manager.store)["stub.png"], "extraction:stub"), "verified")
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions?view=charges&period=last_90")
        rows = page.locator("#tx2-table tbody tr")
        expect(rows.locator('.tx2-col-account [data-status="src_bill"]')).to_be_visible()
        expect(page.locator('#tx2-table tbody tr[data-source="paystub"]')).to_contain_text("Acme Widgets")
        expect(page.locator("#tx2-totals")).to_contain_text("2,500.00")
        page.locator('#tx2-direction [data-direction="out"]').click()
        expect(page).to_have_url(re.compile(r"direction=out"))
        expect(page.locator('#tx2-table tbody tr[data-source="paystub"]')).to_have_count(0)
        expect(page.locator('#tx2-table tbody tr[data-source="bill"]')).to_have_count(1)
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        page.goto(f"{base}/#/documents/{phone['doc_id']}")
        lines = page.locator(".bill-lines")
        expect(lines).to_be_visible()
        expect(page.locator("#doc2-record-title")).to_have_text("Bill from ACME WIRELESS")
        expect(page.locator('#doc2-record-badge [data-status="bill_doc"]')).to_be_visible()
        notes = page.locator(".table-wrap", has=lines)
        expect(notes).to_contain_text("Only the new charges count")
        expect(notes).to_contain_text("Includes: Apple TV+")
        apple = lines.get_by_role("combobox", name="Type of Apple TV+")
        apple.select_option("service")
        expect(page.locator(".table-wrap", has=page.locator(".bill-lines"))).not_to_contain_text("Includes:")  # No longer a subscription line.
        expect(page.locator(".bill-lines").get_by_role("combobox", name="Type of Apple TV+")).to_have_value("service")
        assert manager.ledger.record("receipt", phone["record_id"])["items"][1]["line_kind"] == "service"

        lines.get_by_role("button", name="Delete Apple TV+").click()
        expect(page.locator("#confirm-dialog")).to_be_visible()
        page.locator("#confirm-cancel").click()
        expect(lines).to_contain_text("Apple TV+")
        lines.get_by_role("button", name="Delete Apple TV+").click()
        page.locator("#confirm-dialog").get_by_role("button", name="Delete item").click()
        expect(page.locator(".bill-lines tbody tr")).to_have_count(2)
        assert [item["description"] for item in manager.ledger.record("receipt", phone["record_id"])["items"]] == ["Unlimited", "Taxes and fees"]

        page.goto(f"{base}/#/documents?folder=Bills")
        expect(page.locator('#rc2-table [data-status="bill_doc"]')).to_have_count(1)
        expect(page.locator("#rc2-table")).to_contain_text("Due")
        assert failures == []
        browser.close()


def test_money_out_and_in_filter_both_views_with_their_totals(books):
    store, ledger, docs = books
    rent_and_water(ledger, docs["rent.png"])
    ledger.publish_income({"payer_or_employer": "Acme Widgets", "pay_date": "2026-09-15", "period_start": None, "period_end": None,
                           "gross_pay_minor": 320000, "net_pay_minor": 250000, "taxes_minor": None, "deductions_minor": None, "currency": "USD",
                           "issues": [], "locator": {}}, source_of(docs["stub.png"], "extraction:stub"), "verified")
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-03", "GROCERY MART", -5000), ("2026-09-08", "INTEREST PAID", 125),
                                                      ("2026-09-10", "TRANSFER TO SAVINGS", -20000)])
    tools = FinanceTools(store)
    shown = lambda **filters: tools.get_transactions(TransactionsInput(start="2026-09-01", end="2026-09-30", include_documents=True, **filters))
    every = shown()
    assert [(row["source"], row["amount_minor"]) for row in every["transactions"]] == [
        ("bill", -156020), ("paystub", 250000), ("transaction", -20000), ("transaction", 125), ("transaction", -5000)]
    # Transfers are listed but neither in nor out.
    assert [(row["in"]["minor"], row["out"]["minor"], row["net"]["minor"]) for row in every["totals"]] == [(250125, 161020, 89105)]
    out = shown(direction="out")
    assert [row["source"] for row in out["transactions"]] == ["bill", "transaction", "transaction"] and out["total_matching"] == 3
    money_in = shown(direction="in")
    assert [row["amount_minor"] for row in money_in["transactions"]] == [250000, 125]
    assert [(row["in"]["minor"], row["out"]["minor"]) for row in money_in["totals"]] == [(250125, 0)]
    assert [row["amount_minor"] for row in shown(sort="amount_asc")["transactions"]] == [-156020, -20000, -5000, 125, 250000]
    # A filter only a card or bank line can meet leaves receipts, bills and pay stubs out.
    assert {row["source"] for row in shown(account_id=checking["id"])["transactions"]} == {"transaction"}
    assert {row["source"] for row in shown(category="utilities")["transactions"]} == {"bill"}
    items = tools.get_spending_items(SpendingItemsInput(start="2026-09-01", end="2026-09-30"))
    assert {(row["kind"], row["direction"]) for row in items["items"]} >= {("item", "out"), ("income", "in"), ("charge", "out")}
    assert [(row["in"]["minor"], row["out"]["minor"]) for row in items["totals"]] == [(250125, 161020)]
    outs = tools.get_spending_items(SpendingItemsInput(start="2026-09-01", end="2026-09-30", direction="out"))
    assert sorted(row["amount_minor"] for row in outs["items"]) == [1500, 4520, 5000, 150000]
