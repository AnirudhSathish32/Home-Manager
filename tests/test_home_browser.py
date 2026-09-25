"""Dashboard behavior and responsive charts, using synthetic household data only."""
from datetime import date
import os
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.api import create_app
from home_manager.scanner import Scanner, ScanLimits
from test_reconcile_tools import add


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_home_charts_drilldown_and_mobile(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    source = tmp_path / "source"
    (source / "2026" / "09").mkdir(parents=True)
    (source / "2026" / "09" / "spending.csv").write_text("Date,Description,Amount\n")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "dashboard-test", port, ScanLimits(stability_seconds=0))
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
        manager.configure(str(source), str(tmp_path / "managed"))
        Scanner(manager.store, ScanLimits(stability_seconds=0)).run(manager.store.create_job(source), source)
        doc = manager.store.documents(source)["items"][0]
        account = manager.ledger.create_account("Household checking", "checking", "USD")
        month = date.today().isoformat()[:7]
        ids = add(manager.store, manager.ledger, account, doc, [(month + "-01", "Groceries", -12500),
                  (month + "-01", "Cafe", -2400), (month + "-01", "PAYROLL", 300000)])
        with manager.store.connection() as db:
            db.execute("UPDATE transactions SET category='groceries' WHERE id=?", (ids[0],))
            db.execute("UPDATE transactions SET category='dining' WHERE id=?", (ids[1],))
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=dashboard-test")
            playwright.expect(page.locator("#home-panel")).to_be_visible()
            playwright.expect(page.locator("#home-content .home-metric").first).to_contain_text("149.00 USD")
            playwright.expect(page.locator(".home-trend")).to_be_visible()
            playwright.expect(page.locator(".home-donut")).to_be_visible()
            page.get_by_role("button", name="12 months", exact=True).click()
            playwright.expect(page.get_by_role("button", name="12 months", exact=True)).to_have_attribute("aria-pressed", "true")
            page.locator(".home-legend").get_by_role("link", name="groceries", exact=True).click()
            playwright.expect(page.locator("#finance-transactions tr")).to_have_count(1)
            playwright.expect(page.locator("#finance-transactions")).to_contain_text("Groceries")
            playwright.expect(page.locator("#finance-filter-note")).to_contain_text("groceries")
            page.locator("#nav-home").click()
            playwright.expect(page.locator(".home-donut")).to_be_visible()
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 1100})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
                playwright.expect(page.locator(".home-donut")).to_be_visible()
            if os.environ.get("HOME_SCREENSHOT"):
                path = Path(os.environ["HOME_SCREENSHOT"])
                path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path), full_page=True)
            page.route("**/api/dashboard?*", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"Test unavailable"}'))
            page.locator("#home-refresh").click()
            playwright.expect(page.locator("#home-error")).to_contain_text("Could not load your dashboard")
            page.unroute("**/api/dashboard?*")
            page.get_by_role("button", name="Retry", exact=True).click()
            playwright.expect(page.locator(".home-donut")).to_be_visible()
            assert not failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
