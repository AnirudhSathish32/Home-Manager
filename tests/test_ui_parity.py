"""Figure harness for the traced screens (docs/ui.md "Trace contract"), on synthetic data only.

Every figure a screen shows must carry a trace ref, equal its trace's result, and reconcile."""
from contextlib import contextmanager
from datetime import date, timedelta
import os
import socket
import threading
import time
from urllib.parse import quote

import pytest
import uvicorn

from conftest import inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.engines.opentax import YEARS
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools
from home_manager.library.scanner import ScanLimits
from seed_taxes import seed_tax_year
from seed_wealth import seed_investments
from test_reconcile_tools import add

# Every screen that shows traced figures. Taxes works out this year's return, so it runs only while Engine 1 covers
# this year (seed_taxes.this_year_covered). Inventory's figures are on its Item insights tab.
TRACED = [pytest.param("taxes", marks=pytest.mark.skipif(date.today().year not in YEARS, reason="Engine 1 doesn't cover this year")),
          "home", "spending", "bills", "accounts", "investments", "forecast", "inventory?tab=insights"]

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")


@contextmanager
def seeded_server(tmp_path, token):
    """The app on a free port with test_home_browser.py's synthetic month: groceries, a cafe and a paycheck."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", token, port, ScanLimits(stability_seconds=0))
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
        inbox_scan(manager.store, {"spending.csv": b"Date,Description,Amount\n", "statement.pdf": b"synthetic statement"})
        docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in manager.store.documents()["items"]}
        doc, statement = docs["spending.csv"], docs["statement.pdf"]
        account = manager.ledger.create_account("Household checking", "checking", "USD")
        month = date.today().isoformat()[:7]
        # And a monthly water bill from three earlier payments, confirmed below, for Bills.
        earlier = [date.today().replace(day=1)]
        for _ in range(3):
            earlier.append((earlier[-1] - timedelta(days=1)).replace(day=1))
        ids = add(manager.store, manager.ledger, account, doc, [(month + "-01", "Groceries", -12500),
                  (month + "-01", "Cafe", -2400), (month + "-01", "PAYROLL", 300000)]
                  + [(day.isoformat()[:8] + "03", "CITY WATER", -4000) for day in earlier[1:]])
        Reconciler(manager.store).run()
        with manager.store.connection() as db:
            db.execute("UPDATE transactions SET category='groceries',category_source='user' WHERE id=?", (ids[0],))
            db.execute("UPDATE transactions SET category='dining',category_source='user' WHERE id=?", (ids[1],))
            # A statement balance, for Accounts.
            db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_end,closing_balance_minor,currency,review_status,"
                       "created_at,updated_at) VALUES(?,?,?,'bank',?,841230,'USD','verified','t','t')",
                       (account["id"], statement["id"], statement["current_hash"], (date.today() - timedelta(days=5)).isoformat()))
        water = next(row for row in FinanceTools(manager.store).get_recurring_obligations()["obligations"] if row["merchant"].startswith("CITY WATER"))
        Reconciler(manager.store).review_obligation(water["id"], "verified")
        manager.ledger.set_budget("groceries", "USD", "100.00")
        seed_tax_year(manager, manager.store, manager.ledger)  # This year's taxes, for the Taxes screen.
        seed_investments(manager, full=False)  # A 401(k) and a CD account, for Investments (and Today's net worth).
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


# Mounts figure() (trace.js) for every traced figure in this month's dashboard into div#parity-fixture in main.
MOUNT = """async ({month, wrong}) => {
  const data = await api(`/api/dashboard?month=${month}`), found = [];
  const walk = node => {
    if (Array.isArray(node)) node.forEach(walk);
    else if (node && typeof node === "object") { if (node.trace && node.display) found.push(node); else Object.values(node).forEach(walk); }
  };
  walk(data);
  let fixture = document.getElementById("parity-fixture");
  if (!fixture) { fixture = element("div"); fixture.id = "parity-fixture"; document.querySelector("main").append(fixture); }
  const figures = wrong ? [{...found[0], display: wrong}] : found;
  fixture.replaceChildren(...figures.map(fig => {
    const tile = element("div", "", "figure-tile");
    tile.append(element("p", fig.trace, "figure-label"), figure(fig));
    return tile;
  }));
  return figures.length;
}"""


def mount_dashboard_figures(page, wrong=None):
    return page.evaluate(MOUNT, {"month": date.today().isoformat()[:7], "wrong": wrong})


def check_figures(page, base, token):
    """Every [data-figure-ref] on the page: its trace reconciles and its result is the display shown."""
    found = page.locator("[data-figure-ref]").evaluate_all("nodes => nodes.map(node => [node.dataset.figureRef, node.dataset.figureDisplay])")
    assert found, "no traced figures on the page"
    for ref, display in found:
        response = page.request.get(f"{base}/api/traces/{quote(ref, safe='')}", headers={"Authorization": f"Bearer {token}"})
        assert response.ok, (ref, response.status)
        trace = response.json()
        assert trace["reconciles"], ref
        assert trace["result"]["display"] == display, (ref, trace["result"]["display"], display)
    return found


def open_route(page, route):
    page.evaluate("route => { location.hash = '#/' + route; }", route)
    page.wait_for_selector("[data-page]:not([hidden])")
    page.wait_for_load_state("networkidle")


@browser_test
def test_harness_passes_real_figures_and_fails_a_seeded_mismatch(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with seeded_server(tmp_path, "parity-test") as base, playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token=parity-test")
        playwright.expect(page.locator("#today-panel")).to_be_visible()
        assert mount_dashboard_figures(page) >= 2
        assert len(check_figures(page, base, "parity-test")) >= 2
        # A16: the harness fails when a figure shows something other than its trace.
        mount_dashboard_figures(page, wrong="999,999.99 USD")
        with pytest.raises(AssertionError):
            check_figures(page, base, "parity-test")
        assert not failures, failures
        browser.close()


@browser_test
@pytest.mark.parametrize("route", TRACED)
def test_every_screen_reconciles(tmp_path, route):
    playwright = pytest.importorskip("playwright.sync_api")
    with seeded_server(tmp_path, "parity-test") as base, playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token=parity-test")
        open_route(page, route)
        playwright.expect(page.locator("[data-page]:not([hidden])")).to_be_visible()
        page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)  # Slow pages (the tax engine) load first.
        page.wait_for_selector("[data-page]:not([hidden]) [data-figure-ref]")
        check_figures(page, base, "parity-test")
        assert not failures, failures
        browser.close()
