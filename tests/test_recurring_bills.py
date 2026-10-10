"""Recurring bills proposed from a single payment, kept current by later payments, and used by forecasts and budgets."""

from datetime import date
import json
import os
import socket
import threading
import time

import pytest
import uvicorn

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance.dashboard import dashboard
from home_manager.finance.forecast import ForecastInput, forecast
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.recurring_scan import RecurringScan
from home_manager.finance.tools import AsOfInput, BudgetInput, FinanceTools, RecurringInput
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from home_manager.library.trash import empty
from test_extraction import MISSING, extract, transcribe, value
from test_reconcile_tools import add
from test_statement_assets import classified


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n", "rent.png": b"synthetic rent receipt", "power.png": b"synthetic power receipt",
                       "insurance.png": b"synthetic insurance receipt"})
    try:
        yield store, Ledger(store), Reconciler(store), documents_by_name(store)
    finally:
        store.close()


def paid(ledger, doc, merchant, day, total, category, recurrence):
    key = "extraction:" + doc["relative_path"]
    return ledger.publish_receipt({"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                   "total_minor": total, "currency": "USD", "issues": [], "items": [], "category": category, "recurrence": recurrence,
                                   "locator": {"line_ids": ["line-1"]}},
                                  {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": key}, "verified")["id"]


def bills(tools):
    return {row["merchant"]: row for row in tools.get_recurring_obligations()["obligations"]}


def test_one_receipt_proposes_a_bill_and_varying_payments_keep_it_current(books):
    store, ledger, reconciler, docs = books
    paid(ledger, docs["power.png"], "City Power", "2026-07-03", 12000, "housing", "monthly")
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [("2026-08-03", "CITY POWER UTIL", -14000), ("2026-09-03", "CITY POWER UTIL", -9000),
                                                        ("2026-09-04", "CITY POWER UTIL", -90000)])  # Far above the usual: not a bill payment.
    assert reconciler.run()["recurring"] == 1
    bill = bills(FinanceTools(store))["City Power"]
    assert (bill["status"], bill["frequency"], bill["category"], bill["confidence_source"]) == ("proposed", "monthly", "housing", "receipt_single_payment")
    # Last paid, next due and an expected amount averaging the three payments (utilities vary).
    assert (bill["last_paid_date"], bill["next_due_date"], bill["expected_amount_minor"]) == ("2026-09-03", "2026-10-03", 11667)
    assert reconciler.run()["recurring"] == 0  # Proposed once.


def test_a_categorized_charge_proposes_a_bill_the_user_confirms_or_rejects(books):
    store, ledger, reconciler, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    ledger.add_rule("GEICO", "insurance")
    ledger.add_rule("ACME LOANS", "housing")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-10", "GEICO AUTO", -30000), ("2026-09-12", "ACME LOANS", -80000),
                                                        ("2026-09-12", "BOOKSHOP", -1500)])
    assert reconciler.run()["recurring"] == 2
    found = bills(FinanceTools(store))
    assert set(found) == {"GEICO AUTO", "ACME LOANS"} and found["GEICO AUTO"]["frequency"] == "monthly"
    # How often is unknown from one charge; the user sets it when confirming.
    reconciler.review_obligation(found["GEICO AUTO"]["id"], "verified", frequency="semiannual")
    reconciler.review_obligation(found["ACME LOANS"]["id"], "rejected")
    with pytest.raises(ValueError, match="six months"):
        reconciler.review_obligation(found["GEICO AUTO"]["id"], "verified", frequency="fortnightly")
    assert reconciler.run()["recurring"] == 0  # A rejected payee is never proposed again.
    geico = bills(FinanceTools(store))["GEICO AUTO"]
    assert (geico["status"], geico["frequency"], geico["next_due_date"]) == ("verified", "semiannual", "2027-03-10")
    # Only a confirmed payment can end: a rejected one can't, and ending one twice is refused.
    with pytest.raises(ValueError, match="Only a confirmed"):
        reconciler.review_obligation(found["ACME LOANS"]["id"], "ended")
    assert reconciler.review_obligation(geico["id"], "ended")["status"] == "ended"
    with pytest.raises(ValueError, match="Only a confirmed"):
        reconciler.review_obligation(geico["id"], "ended")


def test_confirmed_bills_are_forecast_on_schedule_and_budgeted(books):
    store, ledger, reconciler, docs = books
    paid(ledger, docs["rent.png"], "Oak Street Rentals", "2026-09-01", 150000, "housing", "monthly")
    paid(ledger, docs["insurance.png"], "Harbor Insurance", "2026-09-15", 60000, "insurance", "quarterly")
    reconciler.run()
    for bill in bills(FinanceTools(store)).values():
        reconciler.review_obligation(bill["id"], "verified")
    result = forecast(store, ForecastInput(years=1, inflation_percent="0"), today=date(2026, 10, 15))
    # The September payments leave the averages; the bills fall on their due months instead: rent monthly, insurance each quarter from December.
    assert result["starting_point"]["monthly_spending"] == []
    assert [(row["month"], row["spending"]) for row in result["months"][:5]] == [
        ("2026-11", 150000), ("2026-12", 210000), ("2027-01", 150000), ("2027-02", 150000), ("2027-03", 210000)]
    assert [bill["name"] for bill in result["starting_point"]["recurring_bills"]] == ["Harbor Insurance", "Oak Street Rentals"]
    ledger.set_budget("housing", "USD", "2000.00")
    [row] = FinanceTools(store).get_budgets(BudgetInput(month="2026-10", as_of="2026-10-05"))["budgets"]
    assert (row["recurring_due"]["decimal"], row["recurring_payees"], row["projected"]["decimal"]) == ("1500.00", ["Oak Street Rentals"], "1500.00")


def test_upcoming_bills_are_confirmed_recurring_bills_by_next_due_date(books):
    store, ledger, reconciler, docs = books
    paid(ledger, docs["rent.png"], "Oak Street Rentals", "2026-09-01", 150000, "housing", "monthly")
    paid(ledger, docs["insurance.png"], "Harbor Insurance", "2026-09-15", 60000, "insurance", "monthly")
    reconciler.run()
    tools = FinanceTools(store)
    upcoming = lambda day: [(bill["provider"], bill["due_date"], bill["amount_due"]["decimal"], bill["payment_state"])
                            for bill in tools.get_upcoming_bills(AsOfInput(as_of=day))["bills"]]
    assert upcoming("2026-09-20") == []  # Proposals wait in Review.
    reconciler.review_obligation(bills(tools)["Oak Street Rentals"]["id"], "verified")
    assert upcoming("2026-09-20") == [("Oak Street Rentals", "2026-10-01", "1500.00", "due")]
    assert upcoming("2026-10-05") == [("Oak Street Rentals", "2026-10-01", "1500.00", "overdue")]  # No payment found since.
    # The Bills page's groups come from the server: overdue, within seven days, or later.
    group = lambda day: [bill["group"] for bill in tools.get_upcoming_bills(AsOfInput(as_of=day))["bills"]]
    assert (group("2026-10-05"), group("2026-09-24"), group("2026-09-23")) == (["overdue"], ["this_week"], ["later"])
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [("2026-10-03", "OAK STREET RENTALS", -150000)])
    reconciler.run()
    assert upcoming("2026-10-05") == [("Oak Street Rentals", "2026-11-03", "1500.00", "due")]
    home = dashboard(store, "2026-10", today=date(2026, 10, 5))["bills"]
    assert ([bill["provider"] for bill in home["upcoming"]], home["overdue"], home["total"]) == (["Oak Street Rentals"], [], 1)


def test_bill_or_subscription_is_suggested_and_the_users_choice_stays(books):
    store, ledger, reconciler, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    ledger.add_rule("STREAMFLIX", "subscriptions")
    ledger.add_rule("GEICO", "insurance")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-10", "GEICO AUTO", -30000), ("2026-09-11", "STREAMFLIX", -1599),
                                                        # Uncategorized, at a steady cadence: detected, and a bill until the user says otherwise.
                                                        ("2026-07-05", "GAME PASS", -1700), ("2026-08-05", "GAME PASS", -1700), ("2026-09-05", "GAME PASS", -1700)])
    reconciler.run()
    found = bills(FinanceTools(store))
    assert {name: row["kind"] for name, row in found.items()} == {"GEICO AUTO": "bill", "STREAMFLIX": "subscription", "GAME PASS": "bill"}
    # The user decides: while confirming, or at any time after.
    reconciler.review_obligation(found["GAME PASS"]["id"], "verified", kind="subscription")
    reconciler.review_obligation(found["STREAMFLIX"]["id"], "verified")
    assert reconciler.set_obligation_kind(found["STREAMFLIX"]["id"], "bill") == {"id": found["STREAMFLIX"]["id"], "kind": "bill"}
    with pytest.raises(ValueError, match="bill or subscription"):
        reconciler.set_obligation_kind(found["GEICO AUTO"]["id"], "luxury")
    reconciler.review_obligation(found["GEICO AUTO"]["id"], "rejected")
    with pytest.raises(ValueError, match="proposed or confirmed"):
        reconciler.set_obligation_kind(found["GEICO AUTO"]["id"], "subscription")
    add(store, ledger, checking, docs["export.csv"], [("2026-10-05", "GAME PASS", -1700)])
    reconciler.run()  # Re-detection never overwrites the user's choice.
    after = bills(FinanceTools(store))
    assert (after["GAME PASS"]["kind"], after["STREAMFLIX"]["kind"]) == ("subscription", "bill")
    with store.connection() as db:
        notes = [row[0] for row in db.execute("SELECT note FROM review_events WHERE record_type='recurring_obligation' ORDER BY id")]
    assert "Kind: subscription." in notes and "Kind: subscription to bill." in notes
    upcoming = FinanceTools(store).get_upcoming_bills(AsOfInput(as_of="2026-10-06", days=60))["bills"]
    assert {bill["provider"]: bill["kind"] for bill in upcoming} == {"GAME PASS": "subscription", "STREAMFLIX": "bill"}


def test_subscriptions_are_totalled_and_what_if_can_cancel_them(books):
    store, ledger, reconciler, docs = books
    paid(ledger, docs["rent.png"], "Oak Street Rentals", "2026-09-01", 150000, "housing", "monthly")
    paid(ledger, docs["power.png"], "Stream Co", "2026-09-02", 1599, "subscriptions", "monthly")
    paid(ledger, docs["insurance.png"], "Game Club", "2026-09-03", 500, "entertainment", "weekly")
    reconciler.run()
    tools = FinanceTools(store)
    for bill in bills(tools).values():
        reconciler.review_obligation(bill["id"], "verified")
    result = tools.get_recurring_obligations(RecurringInput())
    # Weekly counts 52/12 a month: 1599 + 500 * 52 / 12 = 3765.67 a month, 1599 * 12 + 500 * 52 = 451.88 a year.
    assert [(row["kind"], row["count"], row["monthly"]["decimal"], row["yearly"]["decimal"]) for row in result["totals"]] == [
        ("bill", 1, "1500.00", "18000.00"), ("subscription", 2, "37.66", "451.88")]
    only = tools.get_recurring_obligations(RecurringInput(kind="subscription"))["obligations"]
    assert sorted(row["merchant"] for row in only) == ["Game Club", "Stream Co"]
    base = forecast(store, ForecastInput(years=1, inflation_percent="0"), today=date(2026, 10, 15))
    cut = forecast(store, ForecastInput(years=1, inflation_percent="0", cut_subscriptions_from="2027-01"), today=date(2026, 10, 15))
    assert {bill["name"]: bill["kind"] for bill in cut["starting_point"]["recurring_bills"]} == {
        "Oak Street Rentals": "bill", "Stream Co": "subscription", "Game Club": "subscription"}
    before, after = [row["spending"] for row in base["months"]], [row["spending"] for row in cut["months"]]
    assert before[:2] == after[:2]  # November and December still pay them.
    assert all(old - new == 1599 + 2167 for old, new in zip(before[2:], after[2:]))  # From January, rent alone.
    assert any("2 confirmed subscriptions are cancelled" in note and "37.66" in note for note in cut["notes"])
    assert cut["assumptions"]["cut_subscriptions_from"] == "2027-01"


def test_a_confirmed_bill_outlives_the_receipt_it_came_from(books):
    store, ledger, reconciler, docs = books
    paid(ledger, docs["rent.png"], "Oak Street Rentals", "2026-09-01", 150000, "housing", "monthly")
    reconciler.run()
    bill = bills(FinanceTools(store))["Oak Street Rentals"]
    reconciler.review_obligation(bill["id"], "verified")
    store.library_action(docs["rent.png"]["id"], docs["rent.png"]["current_hash"], "trash")
    assert empty(store)["deleted"] == 1
    kept = bills(FinanceTools(store))["Oak Street Rentals"]
    assert (kept["id"], kept["status"], kept["source_receipt_id"]) == (bill["id"], "verified", None)
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_the_model_marks_statement_payees_as_recurring_once(books, local_model):
    store, ledger, reconciler, docs = books
    paid(ledger, docs["power.png"], "City Power", "2026-09-03", 12000, "housing", "monthly")
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [("2026-08-12", "VERIZON WIRELESS", -8500), ("2026-09-12", "VERIZON WIRELESS", -9100),
                                                        ("2026-09-14", "CORNER BAKERY", -1200), ("2026-09-20", "CITY POWER UTIL", -12500)])
    reconciler.run()
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    # Most-charged payee first; City Power already has a bill, so it is not asked about. Answers for unknown ids are ignored.
    local_model["outputs"] = [{"payees": [{"payee_id": 0, "recurrence": "monthly", "category": "housing"},
                                          {"payee_id": 1, "recurrence": None, "category": "dining"},
                                          {"payee_id": 7, "recurrence": "annual", "category": None}]}]
    assert RecurringScan(store).run(config) == {"asked": 2, "recurring": 1}
    sent = json.loads(local_model["requests"][-1]["messages"][1]["content"])["payees"]
    assert [payee["payee"] for payee in sent] == ["VERIZON WIRELESS", "CORNER BAKERY"]
    assert sent[0]["charges"] == ["2026-09-12 91.00 USD", "2026-08-12 85.00 USD"]
    assert reconciler.run()["recurring"] == 1
    found = bills(FinanceTools(store))
    assert set(found) == {"City Power", "VERIZON WIRELESS"}
    phone = found["VERIZON WIRELESS"]
    assert (phone["status"], phone["confidence_source"], phone["frequency"], phone["category"]) == ("proposed", "statement_model", "monthly", "housing")
    assert (phone["last_paid_date"], phone["next_due_date"], phone["expected_amount_minor"]) == ("2026-09-12", "2026-10-12", 8800)
    # Each payee is asked once, the one-off answer included.
    requests = len(local_model["requests"])
    assert RecurringScan(store).run(config) == {"asked": 0, "recurring": 0} and len(local_model["requests"]) == requests
    assert reconciler.run()["recurring"] == 0


LEASE = ["OAK STREET RENTALS", "Residential Lease Agreement", "Lease start 2026-10-01", "Monthly rent $1,500.00 due on the 1st",
         "Security deposit $1,500.00", "Currency USD"]


def lease_term(amount="1,500.00", quote=LEASE[3]):
    return {"payee": value("Oak Street Rentals", 1, LEASE[0]), "amount": value(amount, 4, quote), "currency": value("USD", 6, LEASE[5]),
            "frequency": "monthly", "first_due_date": value("2026-10-01", 3, LEASE[2]), "category": "housing"}


def test_a_lease_proposes_its_rent_as_a_recurring_bill(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, LEASE)
    try:
        # The first answer cites an amount that isn't printed; the corrected one is used.
        local_model["outputs"] = [classified("housing_document", LEASE), {"terms": [lease_term("1,600.00")]}, {"terms": [lease_term(), lease_term()]}]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert run["publication"] is None and len(run["result"]["payment_terms"]["proposed"]) == 1
        rent = bills(manager.tools)["Oak Street Rentals"]
        assert (rent["status"], rent["confidence_source"], rent["expected_amount_minor"], rent["currency"], rent["frequency"], rent["category"]) == (
            "proposed", "contract_terms", 150000, "USD", "monthly", "housing")
        assert rent["source_document_id"] == doc["id"] and rent["evidence"] == LEASE[3]
        # The first due date rolls forward to the next one on or after today, on the same day of the month.
        assert rent["next_due_date"] >= date.today().isoformat() and rent["next_due_date"].endswith("-01")
        # Extracting again proposes nothing new: the payee already has a bill.
        local_model["outputs"] = [classified("housing_document", LEASE), {"terms": [lease_term()]}]
        again = extract(manager, doc, parse_id, force=True)
        assert again["result"]["payment_terms"]["proposed"] == [] and len(bills(manager.tools)) == 1
    finally:
        manager.close()


def test_unreadable_terms_never_fail_the_document(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, LEASE)
    try:
        term = lease_term()
        term["amount"] = MISSING
        broken = {"terms": [lease_term("9.99")]}
        local_model["outputs"] = [classified("insurance_document", LEASE), broken, broken]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded" and run["result"]["payment_terms"]["proposed"] == []
        assert "could not be read" in run["result"]["payment_terms"]["notes"][0]
        local_model["outputs"] = [classified("insurance_document", LEASE), {"terms": [term]}]
        run = extract(manager, doc, parse_id, force=True)
        assert run["result"]["payment_terms"]["proposed"] == [] and "payee or amount" in run["result"]["payment_terms"]["notes"][0]
        assert bills(manager.tools) == {}
    finally:
        manager.close()


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_confirms_a_proposed_bill_with_its_frequency(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "bills-browser", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        inbox_scan(manager.store, {"insurance.png": b"synthetic insurance receipt"})
        paid(manager.ledger, documents_by_name(manager.store)["insurance.png"], "Harbor Insurance", "2026-09-15", 60000, "insurance", "monthly")
        manager.reconciler.run()
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=bills-browser")
            page.locator("#nav-review").click()
            detail = page.locator("#review-detail")
            playwright.expect(detail).to_contain_text("A receipt was read as a payment for a service billed on a schedule")
            detail.get_by_label("How often").select_option("semiannual")
            playwright.expect(detail.get_by_label("Counts as")).to_have_value("bill")  # Insurance is suggested as a bill.
            detail.get_by_label("Counts as").select_option("subscription")
            detail.get_by_role("button", name="Confirm recurring (V)").click()
            playwright.expect(page.locator(".toast").last).to_contain_text("Confirmed as a subscription")
            playwright.expect(detail).to_contain_text("Nothing needs your review")
            page.locator("#nav-bills").click()
            playwright.expect(page.locator("#recurring-rows")).to_contain_text("6 months")
            playwright.expect(page.locator("#recurring-rows")).to_contain_text("Mar 15, 2027")
            playwright.expect(page.locator("#recurring-scan")).to_be_visible()
            playwright.expect(page.locator("#bill-groups")).not_to_be_empty()  # The bill, or the empty state while it is months away.
            # Every six months: 600.00 / 6 = 100.00 a month, 1,200.00 a year.
            summary = page.locator("#subscription-summary")
            playwright.expect(summary).to_contain_text("Harbor Insurance")
            playwright.expect(summary).to_contain_text("1 subscription: about 100.00 USD a month, 1,200.00 USD a year")
            # Changed back later on the Bills page.
            page.get_by_label("Harbor Insurance counts as").select_option("bill")
            playwright.expect(summary).to_contain_text("No confirmed subscriptions")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert not failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_bills_shows_loading_and_a_retryable_error(tmp_path):
    """ui.js pageState: a slow load says so after 300 ms; a failed one shows the error with Retry, and no toast."""
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "bills-state", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        app.state.manager.configure(str(tmp_path / "managed"))
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=bills-state")
            playwright.expect(page.locator("#home-panel")).to_be_visible()
            # A slow response (delayed in the page): nothing for 300 ms, then the loading line, then the bills.
            page.evaluate("""() => { const original = window.fetch;
              window.fetch = (url, options) => String(url).includes("get_upcoming_bills")
                ? new Promise(resolve => setTimeout(resolve, 1500)).then(() => { window.fetch = original; return original(url, options); })
                : original(url, options); }""")
            page.locator("#nav-bills").click()
            state = page.locator("#bills-state")
            playwright.expect(state.get_by_role("status")).to_contain_text("Loading bills")
            playwright.expect(page.locator("#bills-panel")).to_have_attribute("aria-busy", "true")
            playwright.expect(state).to_be_empty()
            playwright.expect(page.locator("#bill-groups")).to_contain_text("No confirmed recurring payments due soon")
            assert page.locator("#bills-panel").get_attribute("aria-busy") is None
            # A failed request: the alert, its details and Retry; the panels are hidden and no toast repeats it.
            page.route("**/api/finance/tools/get_upcoming_bills", lambda route: route.abort())
            page.locator("#nav-home").click()
            page.locator("#nav-bills").click()
            alert = state.get_by_role("alert")
            playwright.expect(alert).to_contain_text("Couldn't load bills.")
            playwright.expect(alert.locator("summary")).to_have_text("Technical details")
            playwright.expect(page.locator("#bill-groups")).to_be_hidden()
            playwright.expect(page.locator('.toast[data-tone="error"]')).to_have_count(0)
            page.unroute("**/api/finance/tools/get_upcoming_bills")
            alert.get_by_role("button", name="Retry").click()
            playwright.expect(state).to_be_empty()
            playwright.expect(page.locator("#bill-groups")).to_be_visible()
            # Focus waited on the state host while it loaded, then moved to the page heading once the host emptied.
            playwright.expect(page.locator("#bills-title")).to_be_focused()
            assert not failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
