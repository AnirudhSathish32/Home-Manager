"""Today v2 in the browser (today_v2.js; docs/ui.md "Pages"): synthetic data only, behind the ui_v2_screens flag."""
from datetime import date, timedelta
import os
import re

import pytest

from conftest import inbox_scan
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools
from test_family_browser import spend
from test_reconcile_tools import add, receipt
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def months_back(count):
    """The first day of the month `count` months before this one."""
    day = date.today().replace(day=1)
    for _ in range(count):
        day = (day - timedelta(days=1)).replace(day=1)
    return day


def seed(manager):
    """test_ui_parity's month (groceries over a 100.00 budget, a cafe, a paycheck), a 40-day-old statement balance, a
    confirmed monthly bill from three earlier payments, and a receipt waiting for review."""
    store, ledger = manager.store, manager.ledger
    inbox_scan(store, {"spending.csv": b"Date,Description,Amount\n", "statement.pdf": b"synthetic statement", "cafe.png": b"synthetic cafe receipt"})
    docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in store.documents()["items"]}
    account = ledger.create_account("Household checking", "checking", "USD")
    month = date.today().isoformat()[:7]
    ids = add(store, ledger, account, docs["spending.csv"], [(month + "-01", "Groceries", -12500), (month + "-01", "Cafe", -2400),
              (month + "-01", "PAYROLL", 300000)] + [(months_back(back).isoformat()[:8] + "03", "CITY WATER", -4000) for back in (1, 2, 3)])
    Reconciler(store).run()  # Finds the monthly water bill from its three payments.
    with store.connection() as db:
        db.execute("UPDATE transactions SET category='groceries',category_source='user' WHERE id=?", (ids[0],))
        db.execute("UPDATE transactions SET category='dining',category_source='user' WHERE id=?", (ids[1],))
        statement = docs["statement.pdf"]
        db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_end,closing_balance_minor,currency,review_status,created_at,updated_at) "
                   "VALUES(?,?,?,'bank',?,841230,'USD','verified','t','t')",
                   (account["id"], statement["id"], statement["current_hash"], (date.today() - timedelta(days=40)).isoformat()))
    ledger.set_budget("groceries", "USD", "100.00")
    water = next(row for row in FinanceTools(store).get_recurring_obligations()["obligations"] if row["merchant"].startswith("CITY WATER"))
    Reconciler(store).review_obligation(water["id"], "verified")
    receipt(ledger, docs["cafe.png"], "Corner Cafe", month + "-02", 1850)


def turn_on(page, base, token):
    assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["home"]}, headers={"Authorization": f"Bearer {token}"}).ok


@browser_test
def test_today_v2_puts_the_household_and_what_needs_you_in_view(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "today-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        panel = page.locator("#today-panel")
        expect(panel).to_be_visible()
        expect(page.locator("#home-panel")).to_be_hidden()
        expect(panel.locator("h1")).to_have_text("Today")
        expect(page.locator("#nav-home")).to_contain_text("Today")
        assert page.title().startswith("Today")

        # The four tiles, each a traced figure.
        tiles = page.locator("#today-tiles > .figure-tile")
        expect(tiles).to_have_count(4)
        page.wait_for_load_state("networkidle")  # The poll reloads Today once the seeded inbox work is done.
        expect(tiles.locator(".figure-label")).to_have_text(["Cash", "Net worth", re.compile(r"^Spent in "), "Money in"])
        expect(tiles.nth(2)).to_contain_text("149.00")
        expect(tiles.nth(0)).to_contain_text("Some balances are old")
        cash = tiles.nth(0).locator(".figure-button").first
        cash.click()
        expect(page.locator("#breakdown")).to_be_visible()
        expect(page.locator("#breakdown")).to_contain_text("over 35 days old")
        expect(page.locator("#breakdown-title")).to_be_focused()
        page.keyboard.press("Escape")
        expect(page.locator("#breakdown")).to_be_hidden()
        expect(cash).to_be_focused()

        # Needs you: the review row, and never a row with a count of 0.
        needs = page.locator("#today-needs")
        expect(needs.locator(".needs-row.attention").first).to_contain_text("to check")
        assert not re.search(r"(^|\s)0 ", needs.inner_text()), needs.inner_text()
        expect(page.locator("#today-dated")).to_contain_text("CITY WATER")
        expect(page.locator("#today-budgets")).to_contain_text("Over by 25.00 USD")

        # Decision in view: the first action at 1366×768.
        page.set_viewport_size({"width": 1366, "height": 768})
        page.evaluate("window.scrollTo(0, 0)")
        box = page.locator("#today-needs .needs-row .needs-action").first.bounding_box()
        assert box and box["y"] + box["height"] <= 768, box

        # The trend's 12 months and the month are kept in the URL.
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="12 months").click()
        expect(page.get_by_role("button", name="12 months")).to_have_attribute("aria-pressed", "true")
        assert "months=12" in page.url
        page.reload()
        expect(page.locator("#today-panel").get_by_role("button", name="12 months")).to_have_attribute("aria-pressed", "true")
        page.locator("#today-month").fill(months_back(1).isoformat()[:7])
        page.locator("#today-month").dispatch_event("change")
        expect(page).to_have_url(re.compile(r"month=\d{4}-\d{2}"))
        expect(page.locator("#today-tiles")).to_be_visible()

        # An error hides the figures; Retry recovers.
        page.route("**/api/dashboard*", lambda route: route.fulfill(status=503, body='{"detail":"Down for a moment"}', content_type="application/json"))
        page.locator("#today-refresh").click()
        expect(page.locator("#today-state")).to_contain_text("Couldn't load your household")
        expect(page.locator("#today-body")).to_be_hidden()
        page.unroute("**/api/dashboard*")
        page.locator("#today-state").get_by_role("button", name="Retry").click()
        expect(page.locator("#today-body")).to_be_visible()
        expect(page.locator("#today-tiles > .figure-tile")).to_have_count(4)

        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()


@browser_test
def test_today_v2_family_view_adds_everyone_up(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "today-v2-family"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        month = date.today().isoformat()[:7]
        manager.configure(str(tmp_path / "alex"))
        manager.rename_profile(manager.profile["id"], "Alex")
        spend(manager, "alex", [(month + "-01", "Groceries", -12500), (month + "-01", "PAYROLL", 300000)])
        alex = manager.profile["id"]
        sam = manager.create_profile("Sam", str(tmp_path / "sam"))
        manager.switch_profile(sam["id"])
        spend(manager, "sam", [(month + "-01", "Books", -2400)])
        manager.switch_profile(alex)
        family = manager.create_family("The Parks", str(tmp_path / "family"), ["Jo"], my_profile=alex)
        from home_manager.app.family_sync import FamilyFolder
        folder = FamilyFolder(tmp_path / "family")
        jo = folder.data["members"][0]["member_id"]
        folder.close()
        manager.set_up_local_member(family["id"], jo, profile_id=sam["id"])
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        inbox_scan(manager.store, {"market.png": b"family market receipt"})
        doc = manager.store.documents()["items"][0]
        manager.ledger.publish_receipt({"merchant": "Corner Market", "purchase_date": month + "-02", "subtotal_minor": None, "tax_minor": None,
                                        "tip_minor": None, "total_minor": 5001, "currency": "USD", "issues": [], "items": [], "locator": {}},
                                       {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "test", "run_id": None}, "verified")
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        expect(page.locator("#today-panel")).to_be_visible()
        tiles = page.locator("#today-tiles > .figure-tile")
        expect(tiles.nth(2)).to_contain_text("149.00", timeout=15000)  # Spent: both people's.
        expect(tiles.nth(3)).to_contain_text("3,000.00")
        expect(page.locator("#today-family-members")).to_contain_text("Alex")
        expect(page.locator("#today-family-members")).to_contain_text("Jo")
        expect(page.locator("#today-family-worth")).to_be_visible()
        expect(page.locator("#today-budgets")).to_be_hidden()
        expect(page.locator("#today-needs .needs-row.attention").first).to_contain_text("waiting for a person")
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()
