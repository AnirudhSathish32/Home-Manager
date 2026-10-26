"""Accounts v2 in the browser (accounts_v2.js, money_v2.js; docs/ui.md "Pages"): synthetic data only."""
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
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/accounts")
        panel = page.locator("#accounts2-panel")
        expect(panel).to_be_visible()
        expect(page.locator("[data-page='accounts']")).to_have_count(1)  # One section per page.
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
        # No library yet: the page says so, with the way to set one up.
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/accounts")
        expect(page.locator("#accounts2-state")).to_contain_text("Set up your library to see accounts")
        expect(page.locator("#accounts2-body")).to_be_hidden()

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


@browser_test
def test_accounts_v2_renames_an_account_and_settles_an_institution_clash(tmp_path):
    """Rename edits the name in place; Save puts focus back on Rename. The institution is offered only while another
    account of the same type and last four has it in another case; a refusal shows beside the fields, and Escape puts the
    row back and returns focus to Rename."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "accounts-v2-rename"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed(manager)
        [household] = [account for account in manager.ledger.accounts() if account["display_name"] == "Household checking"]
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/accounts")
        # 1. No clash: only the name is offered.
        page.get_by_role("button", name="Rename Household checking").click()
        form = page.get_by_role("form", name="Rename Household checking")
        expect(form.get_by_label("Name")).to_be_focused()
        expect(form.get_by_label("Institution")).to_have_count(0)
        form.get_by_label("Name").fill("Everyday checking")
        form.get_by_label("Name").press("Enter")
        expect(page.locator(".accounts2-row", has_text="Everyday checking")).to_contain_text(household["institution"])
        expect(page.get_by_role("button", name="Rename Everyday checking")).to_be_focused()
        assert manager.ledger.account(household["id"])["institution"] == household["institution"]
        # 2. An account saved before institutions matched whatever their case: the same institution in capitals.
        with manager.store.connection() as db:
            db.execute("INSERT INTO accounts(institution,account_type,display_name,account_last_four,currency,created_at,updated_at) VALUES(?,?,?,?,?,'t','t')",
                       (household["institution"].upper(), household["account_type"], "Old copy", household["account_last_four"], household["currency"]))
        page.reload()
        rename = page.get_by_role("button", name="Rename Old copy")
        rename.click()
        form = page.get_by_role("form", name="Rename Old copy")
        institution = form.get_by_label("Institution")
        expect(institution).to_be_focused()
        expect(form).to_contain_text("statements can't tell them apart")
        institution.fill(household["institution"].lower())
        form.get_by_role("button", name="Save").click()
        expect(form.get_by_role("alert")).to_contain_text('"Everyday checking" already has this institution and last four.')
        expect(institution).to_be_focused()
        page.keyboard.press("Escape")
        expect(form).to_have_count(0)
        expect(rename).to_be_focused()
        rename.click()
        form.get_by_label("Institution").fill("Synth Credit Union")
        form.get_by_label("Name").fill("Credit union checking")
        form.get_by_role("button", name="Save").click()
        expect(page.locator(".accounts2-row", has_text="Credit union checking")).to_contain_text("Synth Credit Union")
        expect(page.get_by_role("button", name="Rename Credit union checking")).to_be_focused()
        # 3. The clash is settled: neither account offers its institution any more.
        page.get_by_role("button", name="Rename Credit union checking").click()
        expect(page.get_by_role("form", name="Rename Credit union checking").get_by_label("Institution")).to_have_count(0)
        page.set_viewport_size({"width": 390, "height": 900})
        assert page.evaluate(NO_OVERFLOW)
        assert failures == []
        browser.close()
