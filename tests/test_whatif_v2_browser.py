"""What If v2 in the browser (whatif_v2.js; design-system/home-manager/pages/wealth.md): synthetic data and synthetic tax
tables only."""
from datetime import date
import os

import pytest

from conftest import assert_tiles_fit_beside_ask, documents_by_name, inbox_scan
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
    page.goto(f"{base}/#token={token}")
    page.wait_for_selector("[data-page]:not([hidden])")
    return failures


def unfold(page):
    page.evaluate("document.querySelectorAll('#wi2-panel details').forEach(section => { section.open = true; })")


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
        # A million or more shrinks the headline figure to fit beside Ask.
        assert_tiles_fit_beside_ask(page, "#wi2-paycheck-result .plan-headline", widths=(1180,))
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


@browser_test
def test_whatif_v2_planner_gross_to_net(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "whatif-v2-planner"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        tables(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = open_v2(page, base, token)
        page.goto(f"{base}/#/whatif?tab=planner")
        result = page.locator("#wi2-paycheck-result")
        expect(result).to_contain_text("Enter a salary")
        page.locator("#wi2-plan-year").fill("2026")
        page.locator("#wi2-plan-state").select_option("GA")
        page.locator("#wi2-plan-pay").fill("104000")
        unfold(page)  # The planner's and the plan's sections start folded.
        for category, kind, value in (("retirement_pretax", "percent", "6"), ("health", "amount", "100"), ("dental", "amount", "10"), ("vision", "amount", "5")):
            page.locator("#wi2-add-plan-pre_tax").click()
            row = page.locator("#wi2-plan-pre_tax .plan-line").last
            row.locator("[data-key=category]").select_option(category)
            row.locator("[data-key=kind]").select_option(kind)
            row.locator("[data-key=value]").fill(value)
        page.locator("#wi2-add-plan-post_tax").click()
        page.locator("#wi2-plan-post_tax .plan-line").last.locator("[data-key=category]").select_option("life_insurance")
        page.locator("#wi2-plan-post_tax .plan-line").last.locator("[data-key=value]").fill("2.50")
        page.locator("#wi2-plan-match").fill("100")
        page.locator("#wi2-plan-match-limit").fill("4")
        # The same paycheck as tests/test_paycheck.py: every line from gross to net, per paycheck and per year.
        expect(result.locator(".plan-figure")).to_contain_text("2,706.71")
        for text in ("401(k)", "lowers income-tax wages only", "Wages for Social Security and Medicare", "479.36", "159.23", "240.87", "56.33",
                     "FICA (Social Security + Medicare)", "70,374.46", "401(k) match", "160.00", "Georgia income tax", "the 2026 standard deduction"):
            expect(result).to_contain_text(text)
        # W-4 Step 2 checked: the half-size schedule, 668.01 a paycheck.
        page.locator("#wi2-plan-fed-step2").check()
        expect(result).to_contain_text("668.01")
        page.locator("#wi2-plan-fed-step2").uncheck()
        expect(result).to_contain_text("479.36")
        # A December bonus rides with paycheck 24, withheld at 22% (2,068.00 on 9,400 after the 401(k)).
        page.locator("#wi2-add-plan-bonus").click()
        page.locator("#wi2-plan-bonuses [data-key=amount]").fill("10000")
        page.locator("#wi2-plan-state-supplemental").fill("5.19")
        expect(result).to_contain_text("Bonus (December)")
        expect(result).to_contain_text("Paychecks through the year")
        expect(result).to_contain_text("paid with paycheck 24")
        page.locator("#wi2-plan-bonuses .quiet").click()
        expect(result).not_to_contain_text("paid with paycheck 24")
        # A deduction you type replaces the table's, and the table's shows as the hint.
        expect(page.locator("#wi2-plan-fed-deduction")).to_have_attribute("placeholder", "Table: 15,000.00 USD")
        page.locator("#wi2-plan-fed-deduction").fill("20000")
        expect(result).to_contain_text("the deduction you entered (the table's is 15,000.00 USD)")
        # A state with no table can be worked out with a flat rate.
        page.locator("#wi2-plan-state").select_option("CO")
        expect(result).to_contain_text("hasn't been looked up yet")
        page.locator("#wi2-plan-state-rate").fill("4.4")
        expect(result).to_contain_text("160.38")
        no_overflow(page)
        assert not failures, failures
        browser.close()


@browser_test
def test_whatif_v2_builds_saves_and_reopens_a_plan(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "whatif-v2-build"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        tables(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = open_v2(page, base, token)
        page.goto(f"{base}/#/whatif")
        expect(page.locator("#wi2-scenario-paychecks")).to_contain_text("No paychecks in this plan yet")
        # Tom's steady paycheck, worked out in the planner and added to a new plan.
        page.locator("#wi2-tab-planner").click()
        unfold(page)  # The planner's and the plan's sections start folded.
        page.locator("#wi2-plan-year").fill("2026")
        page.locator("#wi2-plan-state").select_option("GA")
        page.locator("#wi2-plan-pay").fill("104000")
        page.locator("#wi2-add-plan-pre_tax").click()
        row = page.locator("#wi2-plan-pre_tax .plan-line").last
        row.locator("[data-key=kind]").select_option("percent")
        row.locator("[data-key=value]").fill("6")
        page.locator("#wi2-plan-match").fill("100")
        page.locator("#wi2-plan-match-limit").fill("4")
        expect(page.locator("#wi2-paycheck-result .plan-figure")).to_be_visible()
        page.locator("#wi2-paycheck-to-plan").click()
        expect(page.locator("#wi2-paycheck-to-plan")).to_contain_text("Update “Paycheck 1” in the plan")
        page.locator("#wi2-tab-plan").click()
        unfold(page)  # The planner's and the plan's sections start folded.
        page.locator("#wi2-plan-0-label").fill("Tom")
        page.locator("#wi2-plan-0-from_month").fill("2026-11")
        page.locator("#wi2-scenario-name").fill("Tom moves")
        page.locator("#wi2-scenario-basis").select_option("blank")
        page.locator("#wi2-scenario-cash").fill("5000")
        page.locator("#wi2-add-scenario-amount").click()
        page.locator("#wi2-scenario-amounts input[data-key=category]").fill("rent")
        page.locator("#wi2-scenario-amounts input[data-key=monthly_amount]").fill("2100")
        page.locator("#wi2-scenario-amounts input[data-key=from_month]").fill("2026-11")
        page.locator("#wi2-add-scenario-one-off").click()
        page.locator("#wi2-scenario-one-offs input[data-key=month]").fill("2026-11")
        page.locator("#wi2-scenario-one-offs input[data-key=amount]").fill("-3000")
        page.locator("#wi2-scenario-one-offs input[data-key=label]").fill("Movers")
        # Retiring in the plan's fifth year: fixed withdrawals from the plan's 401(k).
        page.locator("#wi2-scenario-retire").check()
        page.locator("#wi2-scenario-retire-month").fill(f"{date.today().year + 4}-01")
        page.locator("#wi2-scenario-retire-mode").select_option("fixed")
        page.locator("#wi2-scenario-retire-amount").fill("500")
        # Tried before saving, beside Now; the full comparison shows each run's details.
        page.locator("#wi2-scenario-try").click()
        against = page.locator("#wi2-against-body")
        expect(against).to_contain_text("Net worth, end of")
        against.get_by_role("button", name="See the full comparison").click()
        result = page.locator("#wi2-compare-result")
        expect(result.locator("svg.forecast-chart")).to_be_visible()
        result.get_by_text("Tom moves: details").click()
        expect(result.locator(".compare-run").last).to_contain_text("From investments")
        expect(result).to_contain_text("Tom: 2,")
        expect(result).to_contain_text("From 2026-11, rent is set to 2,100.00 USD a month")
        page.locator("#wi2-tab-plan").click()
        page.locator("#wi2-scenario-save").click()
        expect(page.locator("#wi2-scenario-select")).to_have_value("1")
        assert "plan=1" in page.url
        # Saved: it comes back after a reload, and can be compared from the list.
        page.reload()
        expect(page.locator("#wi2-scenario-name")).to_have_value("Tom moves")
        expect(page.locator("#wi2-scenario-retire-amount")).to_have_value("500")
        expect(page.locator("#wi2-scenario-paychecks")).to_contain_text("· Georgia · 1 pre-tax, 0 post-tax lines")
        # Opening the plan's paycheck in the planner brings every field back, the match included.
        page.locator("#wi2-tab-planner").click()
        unfold(page)
        page.locator("#wi2-plan-match").fill("")
        page.locator("#wi2-tab-plan").click()
        page.locator("#wi2-scenario-paychecks").get_by_role("button", name="Open in planner").click()
        expect(page.locator("#wi2-tab-planner")).to_have_attribute("aria-selected", "true")
        expect(page.locator("#wi2-plan-match")).to_have_value("100")
        expect(page.locator("#wi2-plan-match-limit")).to_have_value("4")
        page.locator("#wi2-tab-compare").click()
        expect(page.locator("#wi2-compare-now")).to_be_checked()
        expect(page.locator("#wi2-compare-1")).to_be_checked()
        page.locator("#wi2-compare-run").click()
        expect(result.locator("svg.forecast-chart")).to_contain_text("Tom moves")
        no_overflow(page)
        assert not failures, failures
        browser.close()
