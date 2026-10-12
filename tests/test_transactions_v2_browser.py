"""Transactions v2 in the browser (transactions_v2.js, money_v2.js; docs/ui.md "Pages"): synthetic data only."""
from datetime import date
import os
import re

import pytest

from conftest import inbox_scan
from test_family_browser import spend
from test_taxes_v2_browser import served
from test_today_v2_browser import seed

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def seed_transactions(manager):
    """Today v2's month (groceries, a cafe, a paycheck, a water bill) and a bank export waiting in the inbox."""
    seed(manager)
    month = date.today().isoformat()[:7]
    inbox_scan(manager.store, {"bank-export.csv": f"Date,Description,Amount\n{month}-01,BAKERY ROW,-6.40\n{month}-01,TOY SHOP,-12.00\n".encode()})


@browser_test
def test_transactions_v2_filters_categorises_adds_and_imports(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "tx-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed_transactions(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        panel = page.locator("#tx2-panel")
        expect(panel).to_be_visible()
        expect(page.locator("#transactions-panel")).to_be_hidden()
        page.wait_for_load_state("networkidle")
        expect(page.locator('#tx2-periods [data-period="last_90"]')).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#tx2-table thead")).to_contain_text("Item")

        # Period chips write the URL and the summary.
        page.locator('#tx2-periods [data-period="this_month"]').click()
        expect(page).to_have_url(re.compile(r"period=this_month"))
        first = date.today().replace(day=1)
        expect(page.locator("#tx2-summary")).to_contain_text(f"{first.strftime('%b')} 1, {first.year}")
        expect(page.locator("#tx2-table")).not_to_contain_text("CITY WATER")  # Last month's.

        # Items ↔ Charges.
        page.locator("#tx2-view-charges").click()
        expect(page).to_have_url(re.compile(r"view=charges"))
        expect(page.locator("#tx2-view-charges")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#tx2-table thead")).to_contain_text("Description")
        expect(page.locator("#tx2-type")).to_be_enabled()

        # A row's category reloads v2's table, not v1's.
        cafe = page.locator("#tx2-table tbody tr", has_text="Cafe")
        cafe.get_by_role("combobox").select_option("groceries")
        expect(page.locator(".toast").last).to_contain_text("Groceries")
        expect(page.locator("#tx2-table tbody tr", has_text="Cafe").get_by_role("combobox")).to_have_value("groceries")
        expect(page.locator("#tx-rows tr")).to_have_count(0)

        # The drawer opens from the row and its Save reloads v2.
        page.locator("#tx2-table tbody tr", has_text="Cafe").get_by_role("button", name="Cafe").click()
        expect(page.locator("#tx-drawer")).to_be_visible()
        expect(page.locator("#tx2-table tbody tr[aria-selected=true]")).to_contain_text("Cafe")
        page.locator("#tx-drawer-category").fill("dining")
        page.locator("#tx-drawer").get_by_role("button", name="Save category").click()
        expect(page.locator("#tx2-table tbody tr", has_text="Cafe").get_by_role("combobox")).to_have_value("dining")
        # The decision is the shared Confirm/Reject (trace.js confirmCorrect); Confirm can be undone from its toast,
        # which sits inside the modal drawer so it stays clickable.
        drawer = page.locator("#tx-drawer")
        expect(drawer.locator(".drawer-status")).to_contain_text("Counted in your totals.")  # An import counts unless rejected.
        drawer.get_by_role("button", name="Confirm", exact=True).click()
        expect(drawer.get_by_role("button", name="Undo verification")).to_be_visible()
        drawer.locator(".toast", has_text="Confirmed.").get_by_role("button", name="Undo").click()
        expect(drawer.get_by_role("button", name="Confirm", exact=True)).to_be_visible()
        expect(drawer.locator(".toast", has_text="Undone.")).to_be_visible()
        # The drawer's big amount stays inside the drawer on a phone.
        page.set_viewport_size({"width": 390, "height": 900})
        assert page.evaluate("""() => { const a = document.querySelector('#tx-drawer-body .drawer-amount').getBoundingClientRect(),
          b = document.getElementById('tx-drawer-body').getBoundingClientRect(); return a.left >= b.left - 0.5 && a.right <= b.right + 0.5; }""")
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.locator("#close-tx-drawer").click()
        expect(page.locator("body > #toasts")).to_have_count(1)
        expect(page.locator("#tx2-table tbody tr[aria-selected=true]")).to_have_count(0)

        # Add a payment: a missing amount is a field error; a good one appears, marked new, as Entered.
        page.locator("#tx2-add").click()
        expect(page.locator("#money2-add")).to_be_visible()
        expect(page.locator("#money2-add-account")).to_be_focused()
        page.locator("#money2-add-description").fill("Farmers market")
        page.locator("#money2-add-save").click()
        expect(page.locator("#money2-add-amount-error")).not_to_be_empty()
        expect(page.locator(".toast[data-tone=error]")).to_have_count(0)
        page.locator("#money2-add-amount").fill("23.00")
        page.locator("#money2-add-category").fill("groceries")
        page.locator("#money2-add-save").click()
        expect(page.locator("#money2-add")).to_be_hidden()
        added = page.locator("#tx2-table tbody tr.tx2-new")
        expect(added).to_contain_text("Farmers market")
        expect(added).to_contain_text("Entered")

        # Import: the picker lists the waiting export, opens the import dialog, and the rows arrive.
        page.locator("#tx2-import").click()
        expect(page.locator("#money2-import")).to_be_visible()
        page.locator("#money2-import").get_by_role("button", name="Import bank-export.csv").click()
        expect(page.locator("#import-dialog")).to_be_visible()
        expect(page.locator("#confirm-import")).to_be_enabled(timeout=15000)
        page.locator("#confirm-import").click()
        expect(page.locator("#import-dialog")).to_be_hidden()
        expect(page.locator("#tx2-table")).to_contain_text("BAKERY ROW")

        # A Home-style deep link filters v2.
        start, end = first.isoformat(), date.today().isoformat()
        page.goto(f"{base}/#/transactions?category=groceries&metric=categories&start={start}&end={end}")
        expect(page.locator("#tx2-summary")).to_contain_text("Groceries")
        expect(page.locator("#tx2-table tbody")).to_contain_text("Groceries")
        expect(page.locator("#tx2-table tbody")).not_to_contain_text("PAYROLL")

        # Stacked rows at 390: no sideways scroll, and the name keeps a usable width.
        page.goto(f"{base}/#/transactions?view=charges")
        page.set_viewport_size({"width": 390, "height": 900})
        name = page.locator("#tx2-table tbody tr").first.locator(".tx2-name")
        expect(name).to_be_visible()
        box = name.bounding_box()
        assert box and box["width"] >= 120, box
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()


@browser_test
def test_transactions_v2_family_view_shows_owners_and_no_add(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "tx-v2-family"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
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
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions?view=charges")
        expect(page.locator("#tx2-panel")).to_be_visible()
        expect(page.locator("#tx2-table tbody")).to_contain_text("Books", timeout=15000)
        expect(page.locator("#tx2-table thead .owner-col")).to_be_visible()
        expect(page.locator("#tx2-table tbody")).to_contain_text("Jo")
        expect(page.locator("#tx2-add")).to_be_hidden()
        expect(page.locator("#tx2-import")).to_be_hidden()
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()
