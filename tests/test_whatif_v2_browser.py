"""What If v2 in the browser (whatif_v2.js; design-system/home-manager/pages/wealth.md): synthetic data and synthetic tax
tables only, behind the ui_v2_screens flag."""
from datetime import date
import os

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.finance.scenarios import ScenarioInput, Scenarios
from home_manager.household.tax_tables import TaxTables
from seed_wealth import seed_plans
from test_paycheck import TOM
from test_plan_tracking import stub
from test_taxes_v2_browser import served
from test_ui_parity import check_figures
from test_withholding import FEDERAL, GEORGIA, confirmed

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def tables(manager):
    found = TaxTables(manager.store)
    confirmed(found, "US", FEDERAL)
    confirmed(found, "GA", GEORGIA)


def open_v2(page, base, token):
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["whatif"]}, headers={"Authorization": f"Bearer {token}"}).ok
    page.goto(f"{base}/#token={token}")
    page.wait_for_selector("[data-page]:not([hidden])")
    return failures


def no_overflow(page):
    for width in (390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate(NO_OVERFLOW), width
    page.set_viewport_size({"width": 1440, "height": 1000})


@browser_test
def test_whatif_v2_plan_compare_and_planner(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "whatif-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        tables(manager)
        plans = seed_plans(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = open_v2(page, base, token)

        # ?plan= opens the plan on the Plan tab.
        page.goto(f"{base}/#/whatif?plan={plans['plan']}")
        expect(page.locator("#wi2-panel")).to_be_visible()
        expect(page.locator("#whatif-panel")).to_be_hidden()
        expect(page.locator("#wi2-scenario-name")).to_have_value("Tom moves to Denver")
        expect(page.locator("#wi2-tab-plan")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#wi2-scenario-one-offs").locator("xpath=..").locator("summary")).to_contain_text("(1)")
        against = page.locator("#wi2-against-body")
        expect(against).to_contain_text("Try the plan to see it against now")

        # Try it: the plan against Now as figures that open their breakdown; the paycheck shows the server's take-home.
        page.locator("#wi2-scenario-try").click()
        expect(against).to_contain_text("Net worth, end of")
        expect(against).to_contain_text("Cash below zero")
        expect(against.locator("[data-figure-ref]").first).to_be_visible()
        assert against.locator("[data-figure-ref]").count() >= 2
        against.locator("[data-figure-ref]").first.click()
        expect(page.locator("#breakdown")).to_be_visible()
        page.keyboard.press("Escape")
        expect(page.locator("#wi2-scenario-paychecks")).to_contain_text("take-home")
        expect(page.locator("#wi2-scenario-paychecks")).not_to_contain_text("85000 a year")
        expect(page.locator("#wi2-scenario-paychecks [data-figure-ref^='paycheck.net']")).to_have_count(1)
        check_figures(page, base, token)

        # The full comparison is on Compare; the tab lives in the URL and survives a reload.
        against.get_by_role("button", name="See the full comparison").click()
        expect(page.locator("#wi2-tab-compare")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#wi2-compare-result svg.forecast-chart")).to_be_visible()
        expect(page).to_have_url(f"{base}/#/whatif?plan={plans['plan']}&tab=compare")
        page.reload()
        expect(page.locator("#wi2-tab-compare")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#wi2-compare-panel")).to_be_visible()
        # Nothing chosen: Compare waits. Now and the plan: the chart and each run.
        for box in page.locator("#wi2-compare-options input").all():
            box.uncheck()
        expect(page.locator("#wi2-compare-run")).to_be_disabled()
        expect(page.locator("#wi2-compare-note")).to_be_visible()
        page.locator("#wi2-compare-now").check()
        page.locator(f"#wi2-compare-{plans['plan']}").check()
        page.locator("#wi2-compare-run").click()
        result = page.locator("#wi2-compare-result")
        expect(result.locator("svg.forecast-chart")).to_contain_text("Tom moves to Denver")
        expect(result.locator(".compare-run")).to_have_count(2)
        expect(result).to_contain_text("View data table")

        # The planner works a paycheck out; its headline figure opens the paycheck.net breakdown.
        page.locator("#wi2-tab-planner").click()
        expect(page).to_have_url(f"{base}/#/whatif?plan={plans['plan']}&tab=planner")
        page.locator("#wi2-plan-year").fill("2026")
        page.locator("#wi2-plan-state").select_option("GA")
        page.locator("#wi2-plan-pay").fill("104000")
        headline = page.locator("#wi2-paycheck-result .plan-figure [data-figure-ref^='paycheck.net']")
        expect(headline).to_be_visible()
        headline.click()
        expect(page.locator("#breakdown")).to_be_visible()
        page.locator("#breakdown .breakdown-close").first.click()
        expect(page.locator("#breakdown")).to_be_hidden()
        expect(page.locator("#wi2-paycheck-result")).to_contain_text("Take-home per paycheck")
        # The result stays beside the inputs on a laptop screen.
        page.set_viewport_size({"width": 1366, "height": 768})
        page.evaluate("window.scrollTo(0, 0)")
        box = page.locator("#wi2-paycheck-result").bounding_box()
        assert box and box["y"] + 200 <= 768 and box["x"] > 600, box
        page.set_viewport_size({"width": 1440, "height": 1000})

        # Delete… asks first, with Cancel focused.
        page.locator("#wi2-scenario-delete").click()
        expect(page.locator("#confirm-dialog")).to_be_visible()
        expect(page.locator("#confirm-cancel")).to_be_focused()
        page.locator("#confirm-cancel").click()
        expect(page.locator("#wi2-scenario-name")).to_have_value("Tom moves to Denver")
        no_overflow(page)
        assert not failures, failures
        browser.close()


@browser_test
def test_whatif_v2_follow_this_plan(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "whatif-v2-follow"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        store = manager.store
        tables(manager)
        # As tests/test_whatif_browser.py test_following_a_plan: a stub this month, a groceries budget, and a plan.
        month = date.today().isoformat()[:7]
        inbox_scan(store, {"stub.png": b"stub"})
        stub(store, documents_by_name(store)["stub.png"], month + "-01", 47000, 278000)
        manager.ledger.set_budget("groceries", "USD", "500")
        plan = Scenarios(store).create(ScenarioInput.model_validate({
            "name": "Tom's new job", "paychecks": [{"label": "Tom", "paycheck": TOM, "from_month": month}],
            "forecast": {"category_amounts": [{"category": "rent", "monthly_amount": "2100", "from_month": month},
                                              {"category": "groceries", "monthly_amount": "400", "from_month": month}]}}))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = open_v2(page, base, token)
        page.goto(f"{base}/#/whatif?plan={plan['id']}&tab=follow")
        expect(page.locator("#wi2-tab-follow")).to_be_visible()
        expect(page.locator("#wi2-tab-follow")).to_have_attribute("aria-selected", "true")
        actual = page.locator("#wi2-track-actual")
        expect(actual).to_contain_text("Tom: planned paycheck and pay stubs")
        for text in ("479.36", "470.00", "2,706.71", "Within plan"):
            expect(actual).to_contain_text(text)
        # Plan against actual: traced figures that open their breakdown.
        expect(actual.locator("[data-figure-ref^='plan.actual']").first).to_be_visible()
        check_figures(page, base, token)
        page.locator("#wi2-track-preview").click()
        budgets = page.locator("#wi2-track-budgets")
        expect(budgets).to_contain_text("New budget")
        budgets.get_by_role("button", name="Set 2 budgets and follow this plan").click()
        expect(page.locator("#wi2-track-status")).to_contain_text("Followed since")
        assert {budget["category"]: budget["amount_minor"] for budget in manager.ledger.budgets()} == {"groceries": 40000, "rent": 210000}
        page.locator("#wi2-track-stop").click()
        page.locator("#confirm-accept").click()
        expect(page.locator("#wi2-track-stop")).to_be_hidden()
        # A new plan has nothing to follow: the tab goes, and the Plan tab opens.
        page.locator("#wi2-scenario-select").select_option("")
        expect(page.locator("#wi2-tab-follow")).to_be_hidden()
        expect(page.locator("#wi2-tab-plan")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#wi2-scenario-name")).to_have_value("")
        no_overflow(page)
        assert not failures, failures
        browser.close()


@browser_test
def test_whatif_v2_family_view(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "whatif-v2-family"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "alex"))
        family = manager.create_family("The Parks", str(tmp_path / "family"), ["Jo"], my_profile=manager.profile["id"])
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        plan = Scenarios(manager.store).create(ScenarioInput.model_validate({"name": "Family move", "basis": "blank", "starting_cash": "5000"}))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = open_v2(page, base, token)
        page.goto(f"{base}/#/whatif?plan={plan['id']}")
        expect(page.locator("#wi2-scenario-name")).to_have_value("Family move")
        # The family view plans from the family's records or a blank slate, and has nothing to follow.
        expect(page.locator("#wi2-scenario-basis option")).to_have_count(2)
        expect(page.locator("#wi2-tab-follow")).to_be_hidden()
        page.locator("#wi2-scenario-try").click()
        expect(page.locator("#wi2-against-body")).to_contain_text("Tax Zen for the family is on the Taxes page")
        no_overflow(page)
        assert not failures, failures
        browser.close()
