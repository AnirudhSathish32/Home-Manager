"""Investments v2 in the browser (investments_v2.js; design-system/home-manager/pages/wealth.md): synthetic data only,
behind the ui_v2_screens flag."""
from datetime import date
import os

import pytest

from seed_wealth import seed_investments
from test_taxes_v2_browser import served
from test_ui_parity import check_figures

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def turn_on(page, base, token):
    assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["investments"]}, headers={"Authorization": f"Bearer {token}"}).ok


def no_overflow(page):
    for width in (390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate(NO_OVERFLOW), width
    page.set_viewport_size({"width": 1440, "height": 1000})


@browser_test
def test_investments_v2_list_needs_and_controls(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "investments-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        ids = seed_investments(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        page.locator("#nav-investments").click()
        expect(page.locator("#inv2-panel")).to_be_visible()
        expect(page.locator("#investments-panel")).to_be_hidden()
        page.wait_for_selector("#inv2-tiles [data-figure-ref]")

        # Tiles: the invested total is traced and opens its breakdown.
        tiles = page.locator("#inv2-tiles")
        expect(tiles).to_contain_text("Invested, USD")
        expect(tiles).to_contain_text("Coming due · 90 days")
        expect(tiles).to_contain_text("1 CD or Treasury")
        expect(tiles).to_contain_text("Required distributions")
        tiles.locator('[data-figure-ref^="investments.total"]').click()
        expect(page.locator("#breakdown")).to_be_visible()
        page.keyboard.press("Escape")
        check_figures(page, base, token)

        # Needs you: each row with one action.
        needs = page.locator("#inv2-needs")
        expect(needs).to_contain_text("1 value or purchase waits in To check")
        expect(needs).to_contain_text("I bonds over the 10,000.00 USD yearly limit (2024)")
        expect(needs).to_contain_text(f"Maya 529: a {date.today().year - 1} withdrawal isn't marked")
        expect(needs.get_by_role("link", name="Open To check")).to_have_attribute("href", "#/review")
        expect(needs.locator(".needs-row", has_text="I bonds").get_by_role("link", name="Open account")).to_have_attribute("href", f"#/investments?account={ids['ibonds']}")

        # Accounts: one table, a group row per section; a pension shows its income and isn't counted.
        groups = page.locator("#inv2-accounts tr.group-row th[scope='colgroup']")
        assert {"Retirement", "Education", "Stocks and funds"} <= set(groups.all_inner_texts())
        pension = page.locator("#inv2-accounts tr", has_text="State pension")
        expect(pension).to_contain_text("not counted in totals")
        expect(pension).to_contain_text("2,400.00")
        expect(page.locator("#inv2-taxes")).to_contain_text("Chase 1099-INT")
        expect(page.locator("#inv2-split")).to_contain_text("Tax-deferred")
        no_overflow(page)

        # The year and Show removed live in the URL and survive a reload.
        page.locator("#inv2-removed").check()
        expect(page).to_have_url(f"{base}/#/investments?removed=1")
        page.goto(f"{base}/#/investments?removed=1&year=2024")
        expect(page.locator("#inv2-taxes-title")).to_have_text("Taxes for 2024")
        page.reload()
        expect(page.locator("#inv2-removed")).to_be_checked()
        expect(page.locator("#inv2-year")).to_have_value("2024")
        expect(page).to_have_url(f"{base}/#/investments?removed=1&year=2024")

        # Add an account: a field error beside its field, then the new account opens.
        page.goto(f"{base}/#/investments")
        page.locator("#inv2-add").click()
        expect(page.locator("#inv2-add-dialog")).to_be_visible()
        expect(page.locator("#inv2-add-name")).to_be_focused()
        page.locator("#inv2-add-save").click()
        expect(page.locator("#inv2-add-name-error")).not_to_be_empty()
        page.locator("#inv2-add-name").fill("Rainy day")
        page.locator("#inv2-add-kind").select_option("hysa")
        page.locator("#inv2-add-value").fill("15000")
        page.locator("#inv2-add-save").click()
        expect(page.locator("#inv2-add-dialog")).to_be_hidden()
        expect(page.locator("#inv2-title")).to_have_text("Rainy day")
        assert "account=" in page.url
        assert not failures, failures
        browser.close()


@browser_test
def test_investments_v2_account_view(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "investments-v2-account"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        ids = seed_investments(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        turn_on(page, base, token)
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/investments")
        page.locator("#inv2-accounts").get_by_role("link", name="12-month CD", exact=True).click()
        expect(page).to_have_url(f"{base}/#/investments?account={ids['cd']}")
        expect(page.locator("#inv2-title")).to_have_text("12-month CD")
        expect(page.locator("#inv2-back")).to_be_visible()
        expect(page.locator("#inv2-account-head [data-figure-ref^='investments.value']")).to_be_visible()
        expect(page.locator("#inv2-tab-activity")).to_be_hidden()
        # Holdings: the CD's estimated value is a figure; the tab is in the URL.
        page.locator("#inv2-tab-holdings").click()
        expect(page).to_have_url(f"{base}/#/investments?account={ids['cd']}&tab=holdings")
        expect(page.locator("#inv2-holdings-panel [data-figure-ref^='investments.holding']")).to_be_visible()
        check_figures(page, base, token)
        # Record value goes to Overview and focuses the form.
        page.locator("#inv2-record").click()
        expect(page.locator("#inv2-overview-panel")).to_be_visible()
        expect(page.locator("#inv2-overview-panel form input").first).to_be_focused()
        no_overflow(page)

        # A lot added from Holdings reloads this screen, not v1.
        page.goto(f"{base}/#/investments?account={ids['brokerage']}&tab=holdings")
        holdings = page.locator("#inv2-holdings-panel")
        holdings.locator("summary", has_text="Tax lots").click()
        expect(holdings.locator("[data-figure-ref^='investments.lot_gain']")).to_be_visible()
        holdings.get_by_label("Bought").fill(f"{date.today().year - 2}-06-01")
        holdings.get_by_label("Shares").fill("5")
        holdings.get_by_label("Cost (USD)").fill("1500")
        holdings.get_by_role("button", name="Add lot").click()
        expect(holdings.locator(".investment-lots li")).to_have_count(2)
        expect(page.locator("#inv2-panel")).to_be_visible()
        expect(page.locator("#investment-detail")).to_be_empty()

        # Activity: a 529 withdrawal marked not qualified.
        page.goto(f"{base}/#/investments?account={ids['education']}&tab=activity")
        activity = page.locator("#inv2-activity-panel")
        activity.get_by_role("button", name="Not qualified").click()
        expect(activity).to_contain_text("Non-qualified withdrawal")
        expect(page).to_have_url(f"{base}/#/investments?account={ids['education']}&tab=activity")

        # Settings: Remove asks first, with Cancel focused.
        page.locator("#inv2-tab-settings").click()
        page.locator("#inv2-remove").click()
        expect(page.locator("#confirm-dialog")).to_be_visible()
        expect(page.locator("#confirm-cancel")).to_be_focused()
        page.locator("#confirm-cancel").click()
        expect(page.locator("#inv2-title")).to_have_text("Maya 529")

        # A pension has no Holdings tab and no Record value; an unknown id says so.
        page.goto(f"{base}/#/investments?account={ids['pension']}")
        expect(page.locator("#inv2-account-head")).to_contain_text("2,400.00 USD a month from")
        expect(page.locator("#inv2-tab-holdings")).to_be_hidden()
        expect(page.locator("#inv2-record")).to_be_hidden()
        no_overflow(page)
        page.goto(f"{base}/#/investments?account=9999")
        expect(page.locator("#inv2-account-head")).to_contain_text("That account isn't here")
        page.locator("#inv2-account-head").get_by_role("link", name="Back to Investments").click()
        expect(page.locator("#inv2-title")).to_have_text("Investments")
        assert not failures, failures
        browser.close()
