"""Profiles and the family view in the browser, using synthetic household data only."""
from datetime import date
import os
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn

from conftest import inbox_scan
from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits
from test_reconcile_tools import add


def spend(manager, name, rows):
    inbox_scan(manager.store, {f"{name}.csv": b"Date,Description,Amount\n"})
    doc = manager.store.documents()["items"][0]
    account = manager.ledger.create_account(f"{name} bank", "checking", "USD")
    add(manager.store, manager.ledger, account, doc, rows, status="verified")


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_profile_switch_family_view_and_settings(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "family-test", port, ScanLimits(stability_seconds=0))
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
        month = date.today().isoformat()[:7]
        manager.configure(str(tmp_path / "alex"))
        manager.rename_profile(manager.profile["id"], "Alex")
        spend(manager, "alex", [(month + "-01", "Groceries", -12500), (month + "-01", "PAYROLL", 300000)])
        alex = manager.profile["id"]
        sam = manager.create_profile("Sam", str(tmp_path / "sam"))
        manager.switch_profile(sam["id"])
        spend(manager, "sam", [(month + "-01", "Books", -2400)])
        manager.switch_profile(alex)
        (tmp_path / "sync").mkdir()
        family = manager.create_family("The Parks", str(tmp_path / "family"), str(tmp_path / "sync"), ["Jo"], my_profile=alex)
        from home_manager.app.family_sync import FamilyFolder
        folder = FamilyFolder(tmp_path / "family")
        jo = folder.data["members"][0]["member_id"]
        folder.close()
        manager.set_up_local_member(family["id"], jo, profile_id=sam["id"])
        # One receipt uploaded to the family's own inbox, waiting to be routed.
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        inbox_scan(manager.store, {"market.png": b"family market receipt"})
        doc = manager.store.documents()["items"][0]
        manager.ledger.publish_receipt({"merchant": "Corner Market", "purchase_date": month + "-02", "subtotal_minor": None, "tax_minor": None,
                                        "tip_minor": None, "total_minor": 5001, "currency": "USD", "issues": [], "items": [], "locator": {}},
                                       {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "test", "run_id": None}, "verified")
        manager.switch_profile(alex)
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=family-test")
            playwright.expect(page.locator("#home-content .home-metric").first).to_contain_text("125.00")
            playwright.expect(page.locator("#profile-select")).to_have_value(alex)
            page.locator("#profile-select").select_option(family["id"])
            playwright.expect(page.locator("#family-members")).to_contain_text("Jo", timeout=15000)
            playwright.expect(page.locator("#family-members")).to_contain_text("Alex")
            playwright.expect(page.locator("#home-content .home-metric").first).to_contain_text("149.00")
            playwright.expect(page.locator("#family-net-worth")).to_be_visible()
            playwright.expect(page.locator("#nav-transactions")).to_be_hidden()
            playwright.expect(page.locator("#home-content a[href^='#/transactions']")).to_have_count(0)
            page.goto(f"http://127.0.0.1:{port}/#/transactions")
            playwright.expect(page).to_have_url(f"http://127.0.0.1:{port}/#/home")
            playwright.expect(page.locator("#home-content")).to_contain_text("1 document uploaded to the family is waiting")
            page.get_by_role("link", name="Choose who they're for").click()
            row = page.locator("#family-routing .routing-row")
            playwright.expect(row).to_contain_text("Corner Market")
            playwright.expect(row).to_contain_text("50.01")
            for width in (390, 1366):  # The decision stays beside the record, and nothing scrolls sideways.
                page.set_viewport_size({"width": width, "height": 768})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            box = row.get_by_role("button", name="Send").bounding_box()
            assert box and box["y"] + box["height"] <= 768
            page.set_viewport_size({"width": 1440, "height": 1000})
            row.get_by_label("For").select_option("shared")
            playwright.expect(row.locator(".routing-people")).to_be_visible()
            if os.environ.get("FAMILY_SCREENSHOT"):
                page.screenshot(path=str(Path(os.environ["FAMILY_SCREENSHOT"]).with_name("family-routing.png")), full_page=True)
            row.get_by_role("button", name="Send").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Shared: Jo 25.01 USD · Alex 25.00 USD")
            playwright.expect(page.locator("#family-routing")).to_contain_text("Everything uploaded to the family has been sent")
            page.locator("#nav-home").click()
            # Once delivered, each person carries their part and the family counts the purchase once: 149.00 + 50.01.
            playwright.expect(page.locator("#home-content .home-metric").first).to_contain_text("199.01", timeout=15000)
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            page.set_viewport_size({"width": 1440, "height": 1000})
            if os.environ.get("FAMILY_SCREENSHOT"):
                path = Path(os.environ["FAMILY_SCREENSHOT"])
                path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path), full_page=True)
            page.locator("#nav-settings").click()
            page.locator("#profiles-tab").click()
            playwright.expect(page.locator("#family-section")).to_contain_text("The Parks: members")
            playwright.expect(page.locator("#family-section")).to_contain_text("This computer · Sam")
            playwright.expect(page.locator("#family-form")).to_be_hidden()
            if os.environ.get("FAMILY_SCREENSHOT"):
                page.screenshot(path=str(Path(os.environ["FAMILY_SCREENSHOT"]).with_name("family-settings.png")), full_page=True)
            page.locator("#profile-select").select_option(alex)
            playwright.expect(page.locator("#nav-transactions")).to_be_visible()
            playwright.expect(page.locator("#family-section")).to_contain_text("The Parks reads this profile directly")
            page.locator("#profile-name").fill("Robin")
            page.locator("#profile-folder").fill(str(tmp_path / "robin"))
            page.locator("#profile-add").click()
            playwright.expect(page.locator("#profile-rows")).to_contain_text("Robin")
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
