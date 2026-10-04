"""Opt-in browser test for Donate documents: checking a receipt beside its original, blacking out an area, donating."""

import json
import os
import socket
import threading
import time
import zipfile

import pytest
import uvicorn

from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_real_browser_checks_and_donates_a_receipt(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    from home_manager.documents.reasoning import ReasoningConfig
    from home_manager.finance.ledger import HouseholdConfig
    from test_donations import DESCRIBE
    from test_extraction import RECEIPT, classification, identity, receipt_items, receipt_summary
    from test_receipts import make_receipt
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "browser-test-token", port, ScanLimits(stability_seconds=0))
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
        make_receipt(manager.store.library.inbox / "cafe.png")
        local_model["output"] = {"full_text": "\n".join(RECEIPT)}
        manager.configure_vision(local_model["config"])
        manager.start_inbox()
        manager.future.result(timeout=30)
        manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
        manager.configure_household(HouseholdConfig(auto_identify_items=False))
        doc = manager.store.documents()["items"][0]
        local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), DESCRIBE, {"rewards": []}]
        manager.start_extraction(doc["id"], manager.receipts.history(doc["id"])[0]["id"])
        manager.future.result(timeout=30)
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768}, accept_downloads=True)
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=browser-test-token")
            page.locator("#nav-donate").click()
            candidates = page.locator("#donate-candidates")
            playwright.expect(candidates).to_contain_text("Receipt", timeout=15000)
            candidates.get_by_role("button", name="Check").click()
            playwright.expect(page.locator("#donate-check-title")).to_contain_text("Check this receipt")
            # Decision in view: the original, the values and Finish check together at 1366×768.
            box = page.locator("#donate-finish").bounding_box()
            assert box and box["y"] + box["height"] <= 768
            assert page.locator("#donate-image").bounding_box()["x"] < page.locator("#donate-fields").bounding_box()["x"]
            total = page.locator('#donate-fields tr[data-name="total_minor"]')
            playwright.expect(total).to_contain_text("25.00 USD")
            total.get_by_role("button", name="Correct").click()
            merchant = page.locator("#donate-field-merchant")
            merchant.fill("Local Test Cafe Inc")
            playwright.expect(page.locator('#donate-fields tr[data-name="merchant"]').get_by_role("button", name="Fixed")).to_have_attribute("aria-pressed", "true")
            page.locator("#donate-rows-complete").check()
            # Black out an area by dragging across the page.
            page.locator("#donate-redact").click()
            frame = page.locator("#donate-frame").bounding_box()
            page.mouse.move(frame["x"] + 10, frame["y"] + 10)
            page.mouse.down()
            page.mouse.move(frame["x"] + 60, frame["y"] + 40)
            page.mouse.up()
            playwright.expect(page.locator(".donate-box:not(.pending)")).to_have_count(1)
            page.locator("#donate-finish").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("ready to donate")
            playwright.expect(page.locator("#donate-checks")).to_contain_text("Ready to donate")
            page.locator("#donate-donor").fill("d07")
            with page.expect_download() as download:
                page.locator("#donate-export").click()
            saved = tmp_path / "bundle.zip"
            download.value.save_as(saved)
            with zipfile.ZipFile(saved) as bundle:
                manifest = json.loads(bundle.read("manifest.json"))
                case = manifest["cases"][0]
                answers = json.loads(bundle.read(f"cases/{case['case_id']}/answers.json"))
            assert manifest["donor"] == "d07" and case["redacted"] is True
            assert answers["fields"]["merchant"] == {"value": "Local Test Cafe Inc", "state": "fixed"}
            assert answers["fields"]["total_minor"] == {"value": 2500, "state": "correct"} and answers["rows_complete"] is True
            assert answers["fields"]["tip_minor"]["state"] == "unchecked"
            check_id = manager.donations().checks()[0]["id"]
            page.goto(f"http://127.0.0.1:{port}/#/donate/{check_id}")
            playwright.expect(page.locator("#donate-save")).to_have_text("Change answers")
            if os.environ.get("DONATE_SCREENSHOT"):
                page.screenshot(path=os.environ["DONATE_SCREENSHOT"])
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert failures == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
