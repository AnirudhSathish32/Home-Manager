"""What If page: the paycheck planner in the browser, using synthetic tax tables only (docs/planning.md "What If")."""
from datetime import date
import os
import socket
import threading
import time

import pytest
import uvicorn

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.scenarios import ScenarioInput, Scenarios
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from test_paycheck import TOM
from test_plan_tracking import stub
from test_withholding import FEDERAL, GEORGIA, confirmed


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_paycheck_planner_gross_to_net(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "whatif-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        tables = TaxTables(manager.store)
        confirmed(tables, "US", FEDERAL)
        confirmed(tables, "GA", GEORGIA)
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=whatif-test")
            page.locator("#nav-whatif").click()
            playwright.expect(page.locator("#paycheck-result")).to_contain_text("Enter a salary")
            page.locator("#plan-year").fill("2026")
            page.locator("#plan-state").select_option("GA")
            page.locator("#plan-pay").fill("104000")
            for category, kind, value in (("retirement_pretax", "percent", "6"), ("health", "amount", "100"), ("dental", "amount", "10"), ("vision", "amount", "5")):
                page.locator("#add-plan-pre_tax").click()
                row = page.locator("#plan-pre_tax .plan-line").last
                row.locator("[data-key=category]").select_option(category)
                row.locator("[data-key=kind]").select_option(kind)
                row.locator("[data-key=value]").fill(value)
            page.locator("#add-plan-post_tax").click()
            page.locator("#plan-post_tax .plan-line").last.locator("[data-key=category]").select_option("life_insurance")
            page.locator("#plan-post_tax .plan-line").last.locator("[data-key=value]").fill("2.50")
            page.locator("#plan-match").fill("100")
            page.locator("#plan-match-limit").fill("4")
            result = page.locator("#paycheck-result")
            # The same paycheck as tests/test_paycheck.py: every line from gross to net, per paycheck and per year.
            playwright.expect(result.locator(".plan-figure")).to_contain_text("2,706.71")
            for text in ("401(k)", "lowers income-tax wages only", "Wages for Social Security and Medicare", "479.36", "159.23", "240.87", "56.33",
                         "FICA (Social Security + Medicare)", "70,374.46", "401(k) match", "160.00", "Georgia income tax", "the 2026 standard deduction"):
                playwright.expect(result).to_contain_text(text)
            # W-4 Step 2 checked: the half-size schedule, 668.01 a paycheck.
            page.locator("#plan-fed-step2").check()
            playwright.expect(result).to_contain_text("668.01")
            page.locator("#plan-fed-step2").uncheck()
            playwright.expect(result).to_contain_text("479.36")
            # A December bonus rides with paycheck 24, withheld at 22% (2,068.00 on 9,400 after the 401(k)).
            page.locator("#add-plan-bonus").click()
            page.locator("#plan-bonuses [data-key=amount]").fill("10000")
            page.locator("#plan-state-supplemental").fill("5.19")
            playwright.expect(result).to_contain_text("Bonus (December)")
            playwright.expect(result).to_contain_text("Paychecks through the year")
            playwright.expect(result).to_contain_text("paid with paycheck 24")
            page.locator("#plan-bonuses .quiet").click()
            playwright.expect(result).not_to_contain_text("paid with paycheck 24")
            # A deduction you type replaces the table's, and the table's shows as the hint.
            playwright.expect(page.locator("#plan-fed-deduction")).to_have_attribute("placeholder", "Table: 15,000.00 USD")
            page.locator("#plan-fed-deduction").fill("20000")
            playwright.expect(result).to_contain_text("the deduction you entered (the table's is 15,000.00 USD)")
            # A state with no table can be worked out with a flat rate.
            page.locator("#plan-state").select_option("CO")
            playwright.expect(result).to_contain_text("hasn't been looked up yet")
            page.locator("#plan-state-rate").fill("4.4")
            playwright.expect(result).to_contain_text("160.38")
            # The breakdown stays beside the inputs on a laptop screen, and nothing scrolls sideways on a phone.
            page.set_viewport_size({"width": 1366, "height": 768})
            box = result.bounding_box()
            assert box and box["y"] + 200 <= 768 and box["x"] > 600
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                wide = page.evaluate("[...document.querySelectorAll('#whatif-panel *')].filter(node => node.getBoundingClientRect().right > window.innerWidth + 1)"
                                     ".slice(0, 5).map(node => node.tagName + '#' + node.id + '.' + node.className)")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (width, wide)
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_a_saved_plan_compared_with_now(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "plan-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        tables = TaxTables(manager.store)
        confirmed(tables, "US", FEDERAL)
        confirmed(tables, "GA", GEORGIA)
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=plan-test")
            page.locator("#nav-whatif").click()
            playwright.expect(page.locator("#scenario-paychecks")).to_contain_text("No paychecks in this plan yet")
            # Tom's steady paycheck, worked out in the planner and added to a new plan.
            page.locator("#plan-year").fill("2026")
            page.locator("#plan-state").select_option("GA")
            page.locator("#plan-pay").fill("104000")
            page.locator("#add-plan-pre_tax").click()
            row = page.locator("#plan-pre_tax .plan-line").last
            row.locator("[data-key=kind]").select_option("percent")
            row.locator("[data-key=value]").fill("6")
            page.locator("#plan-match").fill("100")
            page.locator("#plan-match-limit").fill("4")
            playwright.expect(page.locator("#paycheck-result .plan-figure")).to_be_visible()
            page.locator("#paycheck-to-plan").click()
            playwright.expect(page.locator("#paycheck-to-plan")).to_contain_text("Update “Paycheck 1” in the plan")
            page.locator("#plan-0-label").fill("Tom")
            page.locator("#plan-0-from_month").fill("2026-11")
            page.locator("#scenario-name").fill("Tom moves")
            page.locator("#scenario-basis").select_option("blank")
            page.locator("#scenario-cash").fill("5000")
            page.locator("#add-scenario-amount").click()
            page.locator("#scenario-amounts input[data-key=category]").fill("rent")
            page.locator("#scenario-amounts input[data-key=monthly_amount]").fill("2100")
            page.locator("#scenario-amounts input[data-key=from_month]").fill("2026-11")
            page.locator("#add-scenario-one-off").click()
            page.locator("#scenario-one-offs input[data-key=month]").fill("2026-11")
            page.locator("#scenario-one-offs input[data-key=amount]").fill("-3000")
            page.locator("#scenario-one-offs input[data-key=label]").fill("Movers")
            # Retiring in the plan's fifth year: fixed withdrawals from the plan's 401(k).
            page.locator("#scenario-retire").check()
            page.locator("#scenario-retire-month").fill(f"{date.today().year + 4}-01")
            page.locator("#scenario-retire-mode").select_option("fixed")
            page.locator("#scenario-retire-amount").fill("500")
            # Tried before saving, beside Now.
            page.locator("#scenario-try").click()
            result = page.locator("#compare-result")
            playwright.expect(result.locator("svg.forecast-chart")).to_be_visible()
            playwright.expect(result).to_contain_text("Tom moves: details")
            result.get_by_text("Tom moves: details").click()
            playwright.expect(result.locator(".compare-run").last).to_contain_text("From investments")
            playwright.expect(result).to_contain_text("Tom: 2,")
            playwright.expect(result).to_contain_text("From 2026-11, rent is set to 2,100.00 USD a month")
            page.locator("#scenario-save").click()
            playwright.expect(page.locator("#scenario-select")).to_have_value("1")
            assert "plan=1" in page.url
            # Saved: it comes back after a reload, and can be compared from the list.
            page.reload()
            playwright.expect(page.locator("#scenario-name")).to_have_value("Tom moves")
            playwright.expect(page.locator("#scenario-retire-amount")).to_have_value("500")
            # Opening the plan's paycheck in the planner brings every field back, the match included.
            page.locator("#plan-match").fill("")
            page.locator("#scenario-paychecks").get_by_role("button", name="Open in planner").click()
            playwright.expect(page.locator("#plan-match")).to_have_value("100")
            playwright.expect(page.locator("#plan-match-limit")).to_have_value("4")
            playwright.expect(page.locator("#scenario-paychecks")).to_contain_text("104000 a year · Georgia")
            playwright.expect(page.locator("#compare-now")).to_be_checked()
            playwright.expect(page.locator("#compare-1")).to_be_checked()
            page.locator("#compare-run").click()
            playwright.expect(result.locator("svg.forecast-chart")).to_contain_text("Tom moves")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_following_a_plan(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "follow-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        store = manager.store
        tables = TaxTables(store)
        confirmed(tables, "US", FEDERAL)
        confirmed(tables, "GA", GEORGIA)
        month = date.today().isoformat()[:7]
        inbox_scan(store, {"stub.png": b"stub"})
        stub(store, documents_by_name(store)["stub.png"], month + "-01", 47000, 278000)
        manager.ledger.set_budget("groceries", "USD", "500")
        plan = Scenarios(store).create(ScenarioInput.model_validate({
            "name": "Tom's new job", "paychecks": [{"label": "Tom", "paycheck": TOM, "from_month": month}],
            "forecast": {"category_amounts": [{"category": "rent", "monthly_amount": "2100", "from_month": month},
                                              {"category": "groceries", "monthly_amount": "400", "from_month": month}]}}))
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=follow-test")
            page.goto(f"http://127.0.0.1:{port}/#/whatif?plan={plan['id']}")
            panel = page.locator("#track-panel")
            playwright.expect(panel).to_be_visible()
            # Before following it, the plan is already compared with the stub and this month's spending.
            actual = page.locator("#track-actual")
            playwright.expect(actual).to_contain_text("Tom: planned paycheck and pay stubs")
            for text in ("479.36", "470.00", "−9.36", "2,706.71", "2,780.00", "Within plan"):
                playwright.expect(actual).to_contain_text(text)
            page.locator("#track-preview").click()
            budgets = page.locator("#track-budgets")
            playwright.expect(budgets).to_contain_text("New budget")
            playwright.expect(budgets).to_contain_text("Changes")
            budgets.get_by_role("button", name="Set 2 budgets and follow this plan").click()
            playwright.expect(page.locator("#track-status")).to_contain_text("Followed since")
            playwright.expect(page.locator("#track-stop")).to_be_visible()
            assert {budget["category"]: budget["amount_minor"] for budget in manager.ledger.budgets()} == {"groceries": 40000, "rent": 210000}
            page.locator("#track-stop").click()
            page.locator("#confirm-accept").click()
            playwright.expect(page.locator("#track-stop")).to_be_hidden()
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
