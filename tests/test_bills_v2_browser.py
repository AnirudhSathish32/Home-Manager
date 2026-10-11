"""Bills & subscriptions v2 in the browser (bills_v2.js; docs/ui.md "Pages"): synthetic data only, behind the
ui_v2_screens flag."""
import os
import re

import pytest

from conftest import inbox_scan
from home_manager.finance.reconcile import Reconciler
from test_reconcile_tools import add
from test_taxes_v2_browser import served
from test_today_v2_browser import months_back, seed
from test_ui_parity import check_figures

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def turn_on(page, base, token):
    assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["bills"]}, headers={"Authorization": f"Bearer {token}"}).ok


def seed_bills(manager):
    """Today v2's confirmed monthly water bill (40.00), and two payments found from three monthly charges, left proposed."""
    seed(manager)
    store, ledger = manager.store, manager.ledger
    inbox_scan(store, {"recurring.csv": b"Date,Description,Amount\n"})
    doc = next(doc for doc in store.documents()["items"] if doc["relative_path"].endswith("recurring.csv"))
    account = ledger.create_account("Bills checking", "checking", "USD")
    add(store, ledger, account, doc, [(months_back(back).isoformat()[:8] + "09", "HARBOR INSURANCE", -10000) for back in (1, 2, 3)]
        + [(months_back(back).isoformat()[:8] + "14", "GYM CLUB", -3000) for back in (1, 2, 3)], status="verified")
    Reconciler(store).run()


@browser_test
def test_bills_v2_totals_decisions_and_kinds(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bills-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed_bills(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/bills")
        panel = page.locator("#bills2-panel")
        expect(panel).to_be_visible()
        expect(page.locator("#bills-panel")).to_be_hidden()
        expect(panel.locator("h1")).to_have_text("Bills & subscriptions")
        expect(page.locator("#nav-bills")).to_contain_text("Bills & subscriptions")
        page.wait_for_load_state("networkidle")

        # The tiles are the server's recurring totals; every figure on the page reconciles with its trace.
        tiles = page.locator("#bills2-tiles .figure-tile")
        expect(tiles).to_have_count(1)
        expect(tiles.nth(0)).to_contain_text("Bills a month")
        expect(tiles.nth(0)).to_contain_text("40.00 USD")
        check_figures(page, base, token)
        tiles.nth(0).locator(".figure-button").click()
        expect(page.locator("#breakdown")).to_contain_text("CITY WATER")
        page.keyboard.press("Escape")

        # Decision in view: the first Confirm at 1366×768.
        decide = page.locator("#bills2-decide")
        expect(decide.locator(".bills2-decide-row")).to_have_count(2)
        page.evaluate("window.scrollTo(0, 0)")
        box = decide.get_by_role("button", name=re.compile(r"^Confirm ")).first.bounding_box()
        assert box and box["y"] + box["height"] <= 768, box

        # Confirm one as a subscription: it leaves To decide and joins the tiles.
        harbor = decide.locator(".bills2-decide-row", has_text="HARBOR INSURANCE")
        harbor.get_by_label(re.compile(r"HARBOR INSURANCE.* counts as")).select_option("subscription")
        harbor.get_by_role("button", name=re.compile(r"^Confirm HARBOR")).click()
        expect(decide.locator(".bills2-decide-row")).to_have_count(1)
        expect(tiles).to_have_count(3)
        expect(tiles.nth(1)).to_contain_text("Subscriptions a month")
        expect(tiles.nth(1)).to_contain_text("100.00 USD")
        expect(tiles.nth(2)).to_contain_text("1,200.00 USD")

        # Not recurring removes the other; To decide goes once it's empty.
        decide.get_by_role("button", name=re.compile(r"GYM CLUB.* is not recurring")).click()
        expect(decide).to_be_hidden()
        expect(page.locator("#bills2-all")).not_to_contain_text("GYM CLUB")

        # Bill ↔ subscription moves the total between tiles.
        page.locator("#bills2-all").get_by_label(re.compile(r"CITY WATER.* counts as")).select_option("subscription")
        expect(tiles).to_have_count(2)
        expect(tiles.nth(0)).to_contain_text("140.00 USD")

        # Mark as ended asks first.
        page.locator("#bills2-all").get_by_role("button", name=re.compile(r"CITY WATER.* actions")).click()
        page.get_by_role("menuitem", name="Mark as ended…").click()
        expect(page.locator("#confirm-dialog")).to_be_visible()
        expect(page.locator("#confirm-title")).to_contain_text("ended")
        page.locator("#confirm-cancel").click()
        expect(page.locator("#bills2-all")).to_contain_text("CITY WATER")

        # The All / Bills / Subscriptions tabs filter, kept in the URL.
        page.locator("#bills2-show-bills").click()
        expect(page).to_have_url(re.compile(r"show=bills"))
        expect(page.locator("#bills2-all")).to_contain_text("No bills here")
        page.locator("#bills2-show-subscriptions").click()
        expect(page.locator("#bills2-all-table tbody tr")).to_have_count(2)

        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()


@browser_test
def test_bills_v2_shows_loading_and_a_retryable_error(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bills-v2-state"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        expect(page.locator("#home-panel")).to_be_visible()
        page.locator("#nav-bills").click()
        expect(page.locator("#bills2-empty")).to_contain_text("No recurring payments yet")
        expect(page.locator("#bills2-tiles")).to_be_hidden()
        page.route("**/api/finance/tools/get_upcoming_bills", lambda route: route.abort())
        page.locator("#nav-home").click()
        page.locator("#nav-bills").click()
        state = page.locator("#bills2-state")
        alert = state.get_by_role("alert")
        expect(alert).to_contain_text("Couldn't load bills.")
        expect(page.locator("#bills2-body")).to_be_hidden()
        expect(page.locator('.toast[data-tone="error"]')).to_have_count(0)
        page.unroute("**/api/finance/tools/get_upcoming_bills")
        alert.get_by_role("button", name="Retry").click()
        expect(state).to_be_empty()
        expect(page.locator("#bills2-body")).to_be_visible()
        expect(page.locator("#bills2-title")).to_be_focused()
        assert not failures, failures
        browser.close()
