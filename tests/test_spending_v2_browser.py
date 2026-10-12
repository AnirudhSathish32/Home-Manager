"""This month v2 in the browser (month_v2.js; docs/ui.md "Pages"): synthetic data only."""
from datetime import date
import os
import re

import pytest

from conftest import assert_tiles_fit_beside_ask, inbox_scan
from test_family_browser import spend
from test_reconcile_tools import add
from test_taxes_v2_browser import served
from test_today_v2_browser import months_back, seed

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


def seed_month(manager):
    """Today v2's month (groceries 125.00 over a 100.00 budget, a cafe, a paycheck) and groceries the month before."""
    seed(manager)
    inbox_scan(manager.store, {"before.csv": b"Date,Description,Amount\n"})
    doc = next(doc for doc in manager.store.documents()["items"] if doc["relative_path"].endswith("before.csv"))
    account = manager.ledger.create_account("Second checking", "checking", "USD")
    ids = add(manager.store, manager.ledger, account, doc, [(months_back(1).isoformat()[:8] + "12", "Groceries", -8000)], status="verified")
    with manager.store.connection() as db:
        db.execute("UPDATE transactions SET category='groceries',category_source='user' WHERE id=?", (ids[0],))


@browser_test
def test_this_month_v2_shows_the_month_its_budgets_and_rules(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "month-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed_month(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/spending")
        panel = page.locator("#month2-panel")
        expect(panel).to_be_visible()
        expect(page.locator("[data-page='spending']")).to_have_count(1)  # One section per page.
        expect(panel.locator("h1")).to_have_text("This month")
        expect(page.locator("#nav-spending")).to_contain_text("This month")
        assert page.title().startswith("This month")
        page.wait_for_load_state("networkidle")  # The poll reloads the page once the seeded inbox work is done.

        # The tiles: net spending and last month's are traced figures; the second is labelled with the other month.
        tiles = page.locator("#month2-tiles > .figure-tile")
        expect(tiles).to_have_count(4)
        previous = MONTHS[months_back(1).month - 1]
        expect(tiles.locator(".figure-label")).to_have_text(["Net spending", previous, "Refunded", "Budgets"])
        expect(tiles.nth(0)).to_contain_text("149.00")
        expect(tiles.nth(1)).to_contain_text("120.00")  # Groceries 80.00 and the 40.00 water bill.
        expect(tiles.nth(3)).to_contain_text("1 over")
        net = tiles.nth(0).locator("> .figure-button")
        net.click()
        expect(page.locator("#breakdown")).to_be_visible()
        page.keyboard.press("Escape")
        expect(net).to_be_focused()
        # Under it, the traced difference from last month (spending.net_change): an arrow and words, never red.
        more = tiles.nth(0).locator(".figure-sub", has_text="more than")
        expect(more).to_contain_text(f"29.00 USD more than {previous}")
        expect(more.locator(".month2-arrow")).to_have_count(1)
        expect(more.locator('[data-figure-ref^="spending.net_change?"]')).to_have_count(1)
        # The Refunded tile, a change cell and a top merchant are traced figures too.
        expect(tiles.nth(2).locator('> [data-figure-ref^="spending.refunds?"]')).to_have_count(1)
        expect(page.locator('#month2-categories .month2-change [data-figure-ref^="spending.change?"]').first).to_be_visible()
        expect(page.locator('#month2-merchants [data-figure-ref^="spending.merchant?"]').first).to_be_visible()

        # By category: names through categoryLabel, the comparison month beside this one, and the change as text.
        categories = page.locator("#month2-categories")
        groceries = categories.locator("tbody tr", has_text="Groceries")
        expect(groceries).to_contain_text("125.00")
        expect(groceries).to_contain_text("80.00")
        expect(groceries.locator(".month2-change")).to_contain_text("45.00")
        expect(groceries.locator(".meter")).to_have_count(1)
        expect(categories).not_to_contain_text("groceries")

        # Over budget is amber, never red.
        budgets = page.locator("#month2-budgets")
        expect(budgets.locator(".status-badge", has_text="Over budget")).to_have_attribute("data-tone", "warning")
        expect(budgets.locator('[data-tone="danger"]')).to_have_count(0)
        expect(budgets).to_contain_text("Over by 25.00 USD")

        # Add a budget: a bad amount is a field error, not a toast; a good one saves.
        page.locator("#month2-budget-add").click()
        expect(page.locator("#month2-budget-form")).to_be_visible()
        expect(page.locator("#month2-budget-category")).to_be_focused()
        page.locator("#month2-budget-category").fill("dining")
        page.locator("#month2-budget-amount").fill("lots")
        page.locator("#month2-budget-form").get_by_role("button", name="Save budget").click()
        expect(page.locator("#month2-budget-error")).not_to_be_empty()
        expect(page.locator(".toast")).to_have_count(0)
        page.locator("#month2-budget-amount").fill("50.00")
        page.locator("#month2-budget-form").get_by_role("button", name="Save budget").click()
        expect(budgets.locator(".month2-budget", has_text="Dining")).to_be_visible()
        expect(page.locator("#month2-budget-form")).to_be_hidden()

        # Prev and next move the month in the URL; next stops at this month.
        expect(page.locator("#month2-next")).to_be_disabled()
        page.locator("#month2-prev").click()
        expect(page).to_have_url(re.compile(rf"month={months_back(1).isoformat()[:7]}"))
        expect(tiles.nth(0)).to_contain_text("120.00")
        page.locator("#month2-next").click()
        expect(page).not_to_have_url(re.compile(r"month="))

        # Same month last year relabels the comparison tile.
        page.locator("#month2-compare").select_option("last_year")
        expect(page).to_have_url(re.compile(r"compare=last_year"))
        last_year = date.today().replace(day=1)
        expect(tiles.nth(1).locator(".figure-label")).to_have_text(f"{MONTHS[last_year.month - 1]} {last_year.year - 1}")

        # Category rules open from the URL; add one, then delete it.
        page.goto(f"{base}/#/spending?rules=1")
        rules = page.locator("#month2-rules")
        expect(rules).to_have_attribute("open", "")
        page.locator("#month2-rule-pattern").fill("CAFE")
        page.locator("#month2-rule-category").fill("dining")
        page.locator("#month2-rule-form").get_by_role("button", name="Add rule").click()
        expect(rules.locator("tbody")).to_contain_text("CAFE")
        expect(rules.locator("summary")).to_have_text("Category rules (1)")
        rules.get_by_role("button", name="Delete the rule CAFE").click()
        page.locator("#confirm-accept").click()
        expect(rules.locator("summary")).to_have_text("Category rules (0)")
        rules.locator("summary").click()
        expect(page).not_to_have_url(re.compile(r"rules=1"))

        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        # A million or more shrinks the row's figures to fit, with Ask open and without.
        assert_tiles_fit_beside_ask(page, "#month2-tiles")
        assert not failures, failures
        browser.close()


@browser_test
def test_this_month_v2_family_view_has_no_budgets_or_rules(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "month-v2-family"
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
        page.goto(f"{base}/#/spending")
        expect(page.locator("#month2-panel")).to_be_visible()
        tiles = page.locator("#month2-tiles > .figure-tile")
        expect(tiles).to_have_count(3)
        expect(tiles.nth(0)).to_contain_text("149.00", timeout=15000)  # Both people's spending.
        expect(page.locator("#month2-budgets")).to_be_hidden()
        expect(page.locator("#month2-rules")).to_be_hidden()
        for width in (390, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()
