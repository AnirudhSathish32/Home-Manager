"""Parity harness for redesigned screens (docs/ui.md "Migration"), on synthetic data only.

Every figure a v2 screen shows must carry a trace ref, equal its trace's result, reconcile, and match a value the old
screen showed. Each Phase 2 session adds its (route, v1 route) pair to MIGRATED."""
from contextlib import contextmanager
from datetime import date
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
from home_manager.library.scanner import ScanLimits
from test_reconcile_tools import add
from test_taxes_browser import seed_tax_year

# (route, v1 route) for each screen moved to its redesign; the v2 route opens with the flag on, the v1 one with it off.
# Taxes works out this year's return, so it runs only while Engine 1 covers this year (test_taxes_browser.this_year_covered).
MIGRATED = [pytest.param("taxes", "taxes", marks=pytest.mark.skipif(date.today().year not in YEARS, reason="Engine 1 doesn't cover this year")),
            pytest.param("home", "home")]
# Figures a v2 screen shows that the old one never did (by ref prefix): checked against their trace only.
NEW_ON_V2 = {"home": ("worth.today", "budget.remaining", "budget.projected")}

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
        inbox_scan(manager.store, {"spending.csv": b"Date,Description,Amount\n"})
        doc = manager.store.documents()["items"][0]
        account = manager.ledger.create_account("Household checking", "checking", "USD")
        month = date.today().isoformat()[:7]
        ids = add(manager.store, manager.ledger, account, doc, [(month + "-01", "Groceries", -12500),
                  (month + "-01", "Cafe", -2400), (month + "-01", "PAYROLL", 300000)])
        with manager.store.connection() as db:
            db.execute("UPDATE transactions SET category='groceries' WHERE id=?", (ids[0],))
            db.execute("UPDATE transactions SET category='dining' WHERE id=?", (ids[1],))
        manager.ledger.set_budget("groceries", "USD", "100.00")
        seed_tax_year(manager, manager.store, manager.ledger)  # This year's taxes, for the Taxes screen.
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


def v1_amounts(page):
    """The server display text of every amount an old screen shows, and the screen's text, for "matches the old screen"
    (old screens write some amounts inside sentences, such as Tax Zen's)."""
    titles = set(page.locator(".amount[title]").evaluate_all("nodes => nodes.map(node => node.title)"))
    return titles, page.locator("[data-page]:not([hidden])").inner_text()


def shown_before(display, old):
    """Whether the old screen showed this amount: as an amount, or in its text. A tax figure shows unsigned on both (its
    label gives the direction), so its magnitude counts."""
    titles, text = old
    return any(value in titles or value in text for value in (display, display.removeprefix("-")))


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
        playwright.expect(page.locator("#home-panel")).to_be_visible()
        assert mount_dashboard_figures(page) >= 2
        assert len(check_figures(page, base, "parity-test")) >= 2
        # A16: the harness fails when a figure shows something other than its trace.
        mount_dashboard_figures(page, wrong="999,999.99 USD")
        with pytest.raises(AssertionError):
            check_figures(page, base, "parity-test")
        assert not failures, failures
        browser.close()


@browser_test
@pytest.mark.parametrize("route,v1_route", MIGRATED)
def test_migrated_screen_matches_its_traces_and_the_old_screen(tmp_path, route, v1_route):
    playwright = pytest.importorskip("playwright.sync_api")
    with seeded_server(tmp_path, "parity-test") as base, playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        headers = {"Authorization": "Bearer parity-test"}
        assert page.request.put(f"{base}/api/ui-screens", data={"routes": []}, headers=headers).ok
        page.goto(f"{base}/#token=parity-test")
        open_route(page, v1_route)
        page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)  # Slow pages (the tax engine) load first.
        old = v1_amounts(page)
        assert page.request.put(f"{base}/api/ui-screens", data={"routes": [route]}, headers=headers).ok
        page.reload()
        open_route(page, route)
        playwright.expect(page.locator('[data-page][data-ui="v2"]:not([hidden])')).to_be_visible()
        page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)
        page.wait_for_selector('[data-page][data-ui="v2"]:not([hidden]) [data-figure-ref]')
        shown = check_figures(page, base, "parity-test")
        missing = [display for ref, display in shown if not ref.startswith(NEW_ON_V2.get(route, ())) and not shown_before(display, old)]
        assert not missing, missing
        assert not failures, failures
        browser.close()
