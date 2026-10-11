"""Forecast v2 in the browser (forecast_v2.js; design-system/home-manager/pages/wealth.md): synthetic data only,
behind the ui_v2_screens flag."""
from datetime import date
import os

import pytest

from home_manager.finance.forecast import AssetInput, Assets
from test_taxes_v2_browser import served
from test_ui_parity import check_figures

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
# Every id in the document once: the charts' title and desc ids are keyed per chart (finance/charts.py line_chart).
UNIQUE_IDS = """(() => { const ids = [...document.querySelectorAll('[id$="-t"], [id$="-d"]')].map(node => node.id);
  return ids.length > 0 && ids.length === new Set(ids).size; })()"""


def seed(manager):
    """No balances, a car and a loan with a payment: cash goes below zero in the first month."""
    today = date.today().isoformat()
    assets = Assets(manager.store)
    assets.add(AssetInput(name="Family car", kind="vehicle", value="18000", currency="USD", as_of=today))
    assets.add(AssetInput(name="Car loan", kind="loan", value="6000", currency="USD", as_of=today, annual_rate_percent="6", monthly_payment="350.00"))


def no_overflow(page):
    for width in (390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate(NO_OVERFLOW), width
    page.set_viewport_size({"width": 1440, "height": 1000})


@browser_test
def test_forecast_v2(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "forecast-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on("dialog", lambda dialog: dialog.accept())
        assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["forecast"]}, headers={"Authorization": f"Bearer {token}"}).ok
        page.goto(f"{base}/#token={token}")
        page.locator("#nav-forecast").click()
        expect(page.locator("#fc2-panel")).to_be_visible()
        expect(page.locator("#forecast-panel")).to_be_hidden()
        page.wait_for_selector("#fc2-tiles [data-figure-ref]")

        # Tiles: end cash and net worth are traced and open their breakdown; cash below zero is a needs-you tile.
        tiles = page.locator("#fc2-tiles")
        expect(tiles).to_contain_text("Cash, end of")
        expect(tiles).to_contain_text("in today's dollars")
        below = tiles.locator(".figure-tile.attention")
        expect(below).to_contain_text("From ")
        expect(below).to_contain_text("Cash goes below zero")
        assert below.locator("svg").count() == 1  # The icon, beside the text: never color alone.
        tiles.locator('[data-figure-ref^="forecast.net_worth"]').click()
        expect(page.locator("#breakdown")).to_be_visible()
        page.keyboard.press("Escape")
        check_figures(page, base, token)

        # One chart at a time; the switch lives in the URL and the data table follows it.
        expect(page.locator("#fc2-chart svg")).to_have_count(1)
        expect(page.locator("#fc2-chart svg > title")).to_have_text("Net worth")
        expect(page.locator("#fc2-chart-desc")).to_contain_text("end of each year")
        page.locator("#fc2-chart-data summary").click()
        expect(page.locator("#fc2-chart-table table")).to_contain_text("In today's dollars")
        assert page.locator("#fc2-chart-table [data-figure-ref]").count() >= 10
        page.locator("#fc2-chart-switch [data-chart='balance_sheet']").click()
        expect(page.locator("#fc2-chart-switch [data-chart='balance_sheet']")).to_have_attribute("aria-pressed", "true")
        expect(page).to_have_url(f"{base}/#/forecast?chart=balance_sheet")
        expect(page.locator("#fc2-chart svg > title")).to_have_text("Cash, assets and loans")
        expect(page.locator("#fc2-chart-table table")).to_contain_text("Loans owed")
        # Chart title and desc ids are unique in the document.
        assert page.evaluate(UNIQUE_IDS)
        expect(page.locator("#fc2-about")).to_contain_text("About these numbers")

        # A one-off: Update writes it to the URL, and a reload rebuilds the row and the result.
        page.locator("#fc2-forecast-years").fill("5")
        page.locator("#fc2-forecast-one-offs").locator("xpath=..").locator("summary").click()
        page.locator("#fc2-add-one-off").click()
        page.locator("#fc2-forecast-one-offs input[type=month]").fill("2027-06")
        page.locator("#fc2-forecast-one-offs input[inputmode=decimal]").fill("-3000")
        page.locator("#fc2-forecast-one-offs input[maxlength='80']").fill("Trip~to Lisbon")
        page.locator("#fc2-run-top").click()
        expect(page.locator("#fc2-status")).to_have_text("Forecast updated")
        expect(page).to_have_url(f"{base}/#/forecast?years=5&oneoff=2027-06%7E-3000%7ETrip%7Eto+Lisbon&chart=balance_sheet")
        expect(page.locator("#fc2-forecast-one-offs").locator("xpath=..").locator("summary")).to_contain_text("(1)")
        page.reload()
        page.wait_for_selector("#fc2-tiles [data-figure-ref]")
        expect(page.locator("#fc2-forecast-years")).to_have_value("5")
        expect(page.locator("#fc2-forecast-one-offs input[type=month]")).to_have_value("2027-06")
        expect(page.locator("#fc2-forecast-one-offs input[maxlength='80']")).to_have_value("Trip~to Lisbon")
        expect(page.locator("#fc2-chart svg > title")).to_have_text("Cash, assets and loans")
        page.locator("#fc2-chart-data summary").click()
        expect(page.locator("#fc2-chart-table tbody tr")).to_have_count(5)
        # An invalid value is dropped and its default used.
        page.goto(f"{base}/#/forecast?years=abc&oneoff=bad")
        page.wait_for_selector("#fc2-tiles [data-figure-ref]")
        expect(page.locator("#fc2-forecast-years")).to_have_value("10")
        expect(page.locator("#fc2-forecast-one-offs .forecast-item")).to_have_count(0)

        # Retirement fields follow the checkbox and the mode.
        page.locator("#fc2-retirement summary").click()
        assert page.locator("#fc2-retire-fields").is_hidden()
        page.locator("#fc2-retire-plan").check()
        expect(page.locator("#fc2-retire-state")).to_have_text("On")
        assert page.locator("#fc2-retire-amount-field").is_hidden() and page.locator("#fc2-retire-floor").is_visible()
        page.locator("#fc2-retire-mode").select_option("fixed")
        assert page.locator("#fc2-retire-amount").is_visible()
        page.locator("#fc2-retire-plan").uncheck()

        # Assets: add one, then remove it (after confirming); both reload this screen.
        rows = page.locator("#fc2-asset-rows")
        expect(rows).to_contain_text("Car loan")
        expect(rows).to_contain_text("350.00")
        page.locator("#fc2-asset-add summary").click()
        page.locator("#fc2-asset-name").fill("Boat")
        page.locator("#fc2-asset-kind").select_option("other_asset")
        page.locator("#fc2-asset-value").fill("4000")
        page.locator("#fc2-add-asset").click()
        expect(rows).to_contain_text("Boat")
        expect(page.locator("#fc2-panel")).to_be_visible()
        rows.get_by_role("button", name="Remove Boat").click()
        page.locator("#confirm-dialog").get_by_role("button", name="Remove").click()
        expect(rows).not_to_contain_text("Boat")
        expect(page.locator("#fc2-panel")).to_be_visible()

        # Starting point, folded.
        page.locator("#fc2-start-region summary").click()
        expect(page.locator("#fc2-start")).to_contain_text("Cash in accounts")
        no_overflow(page)
        assert not failures, failures
        browser.close()


@browser_test
def test_forecast_v2_narrow_folds_assumptions(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "forecast-v2-narrow"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        seed(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 390, "height": 844})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["forecast"]}, headers={"Authorization": f"Bearer {token}"}).ok
        # With assumptions in the URL the column starts folded, its summary saying what's set.
        page.goto(f"{base}/#token={token}")
        page.wait_for_selector("[data-page]:not([hidden])")
        page.goto(f"{base}/#/forecast?years=3&inflation=3")
        page.wait_for_selector("#fc2-tiles [data-figure-ref]")
        expect(page.locator("#fc2-assumptions")).not_to_have_attribute("open", "")
        expect(page.locator("#fc2-assumptions > summary")).to_contain_text("3 years · 3% inflation · 0 changes")
        # The header button still runs it.
        page.locator("#fc2-run-top").click()
        expect(page.locator("#fc2-status")).to_have_text("Forecast updated")
        no_overflow(page)
        assert not failures, failures
        browser.close()
