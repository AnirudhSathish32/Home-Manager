"""Inventory v2 in the browser (inventory_v2.js; design-system/home-manager/pages/inventory.md): synthetic data only."""
import os

import pytest

from conftest import assert_tiles_fit_beside_ask
from seed_items import seed_items
from test_taxes_v2_browser import served
from test_ui_parity import check_figures

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def no_overflow(page):
    for width in (390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate(NO_OVERFLOW), width
    page.set_viewport_size({"width": 1440, "height": 1000})


@browser_test
def test_inventory_v2_tabs_answers_and_insights(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "inventory-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.locator("#nav-inventory").click()
        expect(page.locator("#it2-panel")).to_be_visible()
        expect(page.locator("#inventory-panel")).to_be_hidden()
        expect(page.locator("#it2-body")).to_contain_text("No items yet")

        seed_items(manager)
        page.reload()
        # Items: one table, a group row per category in proper case; each row has its menu.
        groups = page.locator("#it2-items tr.group-row th[scope='colgroup']")
        expect(groups.first).to_be_visible()
        assert {"Dairy & eggs (1)", "Home maintenance (1)", "Pantry (2)"} <= set(groups.all_inner_texts())
        drill = page.locator("#it2-items tr", has_text="Cordless Drill")
        expect(drill).to_contain_text("Returnable until")
        expect(drill.get_by_role("button", name="Actions for Cordless Drill")).to_be_visible()
        expect(page.locator("#it2-tab-checkin")).to_have_attribute("aria-label", "Check-in, 2 waiting")
        expect(page.locator("#it2-tab-returns")).to_have_attribute("aria-label", "Returns, 1 to answer")
        no_overflow(page)

        # A search from the URL lands on Items, whatever tab it names, and survives a reload.
        page.goto(f"{base}/#/inventory?tab=returns&q=kettle")
        expect(page.locator("#it2-tab-items")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#it2-search")).to_have_value("kettle")
        expect(page.locator("#it2-items tbody tr:not(.group-row)")).to_have_count(1)
        page.reload()
        expect(page.locator("#it2-search")).to_have_value("kettle")
        expect(page).to_have_url(f"{base}/#/inventory?q=kettle")

        # Check-in: an answer applies at once and can be undone from its toast.
        page.goto(f"{base}/#/inventory?tab=checkin")
        rows = page.locator("#it2-checkin-list .checkin-row")
        expect(rows).to_have_count(2)
        rows.first.get_by_role("button", name="Still have it").click()
        expect(page.locator("#it2-tab-checkin")).to_have_attribute("aria-label", "Check-in, 1 waiting")
        page.locator(".toast").get_by_role("button", name="Undo").click()
        expect(page.locator("#it2-tab-checkin")).to_have_attribute("aria-label", "Check-in, 2 waiting")
        no_overflow(page)

        # Warranties: the one ending soon says so; the header action becomes "Warranty".
        page.locator("#it2-tab-warranties").click()
        expect(page).to_have_url(f"{base}/#/inventory?tab=warranties")
        expect(page.locator("#it2-add")).to_have_text("Warranty")
        expect(page.locator("#it2-warranties-panel tr", has_text="Electric Kettle")).to_contain_text("Ends within 30 days")
        no_overflow(page)

        # Returns: add a policy in the dialog (an error beside its field first), then remove it.
        page.locator("#it2-tab-returns").click()
        expect(page.locator("#it2-closing")).to_contain_text("Cordless Drill")
        page.locator("#it2-add").click()
        expect(page.locator("#it2-policy-dialog")).to_be_visible()
        expect(page.locator("#it2-policy-merchant")).to_be_focused()
        page.locator("#it2-policy-save").click()
        expect(page.locator("#it2-policy-merchant-error")).to_have_text("Enter the store's name.")
        page.locator("#it2-policy-merchant").fill("Corner Hardware")
        page.locator("#it2-policy-days").fill("30")
        page.locator("#it2-policy-save").click()
        expect(page.locator("#it2-policy-dialog")).to_be_hidden()
        policy = page.locator("#it2-policies tr", has_text="Corner Hardware")
        expect(policy).to_contain_text("Yours")
        policy.get_by_role("button", name="Actions for the Corner Hardware policy").click()
        policy.get_by_role("menuitem", name="Remove").click()
        expect(page.locator("#confirm-cancel")).to_be_focused()
        page.locator("#confirm-accept").click()
        expect(page.locator("#it2-policies tr", has_text="Corner Hardware")).to_have_count(0)

        # Did this go back? Answering it closes the towels and clears the question.
        returned = page.locator("#it2-returned")
        expect(returned).to_contain_text("TOWEL SET")
        returned.get_by_role("button", name="Yes, Bath Towel Set went back").click()
        expect(returned).to_be_hidden()
        expect(page.locator("#it2-tab-returns")).not_to_have_attribute("aria-label", "Returns, 1 to answer")
        no_overflow(page)

        # Item insights: four traced tiles; one opens its breakdown with steps; the period lives in the URL.
        page.locator("#it2-tab-insights").click()
        tiles = page.locator("#it2-insights .figure-tile")
        expect(tiles).to_have_count(4)
        expect(page.locator("#it2-insights")).to_contain_text("Prices that went up")
        expect(page.locator("#it2-insights")).to_contain_text("smaller pack")
        check_figures(page, base, token)
        page.locator('#it2-insights [data-figure-ref^="items.spending"]').click()
        expect(page.locator("#breakdown")).to_be_visible()
        expect(page.locator("#breakdown .breakdown-steps tbody tr").first).to_be_visible()
        page.keyboard.press("Escape")
        page.locator("#it2-insights-panel [data-period='30']").click()
        expect(page).to_have_url(f"{base}/#/inventory?tab=insights&period=30")
        page.reload()
        expect(page.locator("#it2-tab-insights")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#it2-insights-panel [data-period='30']")).to_have_attribute("aria-pressed", "true")
        expect(page.locator('#it2-insights [data-figure-ref^="items.spending"]')).to_be_visible()
        no_overflow(page)
        # A million or more shrinks the row's figures to fit, with Ask open and without.
        assert_tiles_fit_beside_ask(page, ".it2-tiles")
        assert not failures, failures
        browser.close()
