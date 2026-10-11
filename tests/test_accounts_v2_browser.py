"""Accounts v2 in the browser (accounts_v2.js, money_v2.js; docs/ui.md "Pages"): synthetic data only, behind the
ui_v2_screens flag."""
from datetime import date
import os

import pytest

from conftest import inbox_scan
from test_family_browser import spend
from test_taxes_v2_browser import served
from test_today_v2_browser import seed
from test_ui_parity import check_figures

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def turn_on(page, base, token):
    assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["accounts"]}, headers={"Authorization": f"Bearer {token}"}).ok


@browser_test
def test_accounts_v2_balances_their_age_and_import(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "accounts-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed(manager)  # Household checking with a statement balance 40 days old.
        month = date.today().isoformat()[:7]
        inbox_scan(manager.store, {"bank-export.csv": f"Date,Description,Amount\n{month}-01,BAKERY ROW,-6.40\n{month}-01,TOY SHOP,-12.00\n".encode()})
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/accounts")
        panel = page.locator("#accounts2-panel")
        expect(panel).to_be_visible()
        expect(page.locator("#accounts-panel")).to_be_hidden()
        page.wait_for_load_state("networkidle")

        row = page.locator(".accounts2-row", has_text="Household checking")
        expect(row).to_contain_text("Statement balance")
        expect(row).to_contain_text("8,412.30")
        expect(row.locator(".status-badge")).to_have_text("Over 35 days old")
        expect(row.locator(".status-badge")).to_have_attribute("data-tone", "warning")
        check_figures(page, base, token)
        row.locator(".figure-button").click()
        expect(page.locator("#breakdown")).to_be_visible()
        page.keyboard.press("Escape")
        expect(row.get_by_role("link", name="Transactions for Household checking")).to_have_attribute("href", "#/transactions?account=1&period=all")

        # Import: the picker, then the import dialog; the account's coverage takes the new rows.
        coverage = row.locator(".accounts2-coverage")
        before = coverage.inner_text()
        page.locator("#accounts2-import").click()
        page.locator("#money2-import").get_by_role("button", name="Import bank-export.csv").click()
        expect(page.locator("#import-dialog")).to_be_visible()
        expect(page.locator("#confirm-import")).to_be_enabled(timeout=15000)
        page.locator("#confirm-import").click()
        expect(page.locator("#import-dialog")).to_be_hidden()
        expect(coverage).not_to_have_text(before)

        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()


@browser_test
def test_accounts_v2_without_a_library_and_in_the_family_view(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "accounts-v2-family"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        # No library yet: the page says so, with the way to set one up. (The flag needs a profile, so it's set after.)
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/accounts")
        expect(page.locator("#accounts-state")).to_contain_text("Set up your library to see accounts")

        month = date.today().isoformat()[:7]
        manager.configure(str(tmp_path / "alex"))
        manager.rename_profile(manager.profile["id"], "Alex")
        spend(manager, "alex", [(month + "-01", "Groceries", -12500)])
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
        turn_on(page, base, token)
        page.goto(f"{base}/#/home")
        page.reload()
        page.goto(f"{base}/#/accounts")
        expect(page.locator("#accounts2-panel")).to_be_visible()
        expect(page.locator("#accounts2-groups")).to_contain_text("Jo", timeout=15000)
        expect(page.locator("#accounts2-groups")).to_contain_text("Alex")
        expect(page.locator("#accounts2-import")).to_be_hidden()
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()
