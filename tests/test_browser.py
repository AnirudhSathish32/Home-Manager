"""Opt-in real browser smoke test: RUN_BROWSER_TESTS=1, installed Edge + Playwright."""

import os
import re
from pathlib import Path
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.api import create_app
from home_manager.scanner import ScanLimits


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_real_browser_configures_scans_and_inspects_versions(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    document = month / "sample.csv"
    document.write_bytes(b"date,total\n2026-09-01,123\n")
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
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=browser-test-token")
            page.get_by_role("button", name="Open settings").click()
            playwright.expect(page.get_by_role("tab", name="Directories", exact=True)).to_have_attribute("aria-selected", "true")
            playwright.expect(page.locator("#limits")).to_contain_text("Capture limits")
            page.locator("#source").fill(str(source))
            page.locator("#managed").fill(str(tmp_path / "managed"))
            page.locator("#save-settings").click()
            playwright.expect(page.locator("#notice")).to_contain_text("Directories saved")
            page.locator("#close-settings").click()
            page.locator("#scan-tab").click()
            page.locator("#scan").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("completed", timeout=15000)
            playwright.expect(page.locator("#documents")).to_contain_text("sample.csv")
            document.write_bytes(b"date,total\n2026-09-01,456\n")
            playwright.expect(page.locator("#scan")).to_be_enabled(timeout=10000)
            page.locator("#scan").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("new_version", timeout=15000)
            page.locator("#documents-tab").click()
            page.get_by_role("button", name="Versions (2)", exact=True).click()
            playwright.expect(page.locator("#versions-dialog")).to_be_visible()
            assert page.locator("#versions-content code").count() == 2
            page.locator("#close-versions").click()
            from test_receipts import make_receipt
            payload = make_receipt(month / "receipt.png")
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.locator("#scan-tab").click()
            page.locator("#scan").click()
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png", timeout=15000)
            page.locator("#documents-tab").click()
            page.get_by_role("button", name="Inspect document", exact=True).click()
            playwright.expect(page.locator("#receipt-dialog")).to_be_visible()
            page.locator("#parse-receipt").click()
            playwright.expect(page.locator("#receipt-text")).to_have_value(re.compile("RETURNS", re.IGNORECASE), timeout=30000)
            playwright.expect(page.locator("#receipt-fields")).to_contain_text("25.00")
            playwright.expect(page.locator("#receipt-calculation")).to_contain_text("matches")
            playwright.expect(page.locator("#receipt-codes")).to_contain_text(payload)
            assert page.locator("#receipt-codes a").count() == 0
            page.locator("#receipt-fields button").first.click()
            assert page.locator("#receipt-overlay .selected").count() > 0
            page.locator("#close-receipt").click()
            page.locator("#open-settings").click()
            page.get_by_role("tab", name="Local model", exact=True).click()
            page.locator("#vision-url").fill(local_model["config"].base_url)
            page.locator("#vision-model").fill(local_model["config"].model)
            page.locator("#save-vision").click()
            playwright.expect(page.locator("#notice")).to_contain_text("Local model settings saved")
            page.locator("#close-settings").click()
            page.locator("#parse-all-receipts").click()
            playwright.expect(page.locator("#receipt-batch-status")).to_contain_text("completed", timeout=30000)
            playwright.expect(page.locator("#documents")).to_contain_text(local_model["output"]["title"])
            playwright.expect(page.locator("#documents")).to_contain_text("2026/09/receipt.png")
            page.get_by_role("button", name="Inspect document", exact=True).click()
            playwright.expect(page.locator("#receipt-title")).to_contain_text(local_model["output"]["title"])
            playwright.expect(page.locator("#receipt-text")).to_have_value(re.compile("Returns within 14 days"))
            page.get_by_role("button", name="Find in transcription").first.click()
            assert page.locator("#receipt-text").evaluate("el => el.selectionEnd > el.selectionStart")
            page.locator("#close-receipt").click()
            page.locator("#parse-all-receipts").click()
            playwright.expect(page.locator("#receipt-batch-status")).to_contain_text("1 reused", timeout=10000)
            assert len(local_model["requests"]) == 1
            page.locator('.folder-link[data-folder="03_Purchases/Receipts"]').click()
            playwright.expect(page.locator("#document-count")).to_have_text("1 document")
            page.get_by_role("button", name="Delete", exact=True).click()
            playwright.expect(page.locator("#library-action-description")).to_contain_text("Source files and preserved copies are not deleted")
            page.locator("#cancel-library-action").click()
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png")
            page.get_by_role("button", name="Delete", exact=True).click()
            page.get_by_role("button", name="Delete to Trash", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator('.folder-link[data-folder="trash"]').click()
            page.get_by_role("button", name="Restore", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator('.folder-link[data-folder="03_Purchases/Receipts"]').click()
            page.get_by_role("button", name="Move", exact=True).click()
            page.locator("#move-folder").select_option("04_Bills/Utilities")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator('.folder-link[data-folder="04_Bills/Utilities"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png")
            # Newly scanned images are automatically read and filed without the batch button.
            (month / "bill.png").write_bytes((month / "receipt.png").read_bytes() + b"synthetic different version")
            local_model["output"]["title"] = "Neighborhood utility bill"
            local_model["output"]["folder"] = "04_Bills/Utilities"
            page.locator("#scan-tab").click()
            page.locator("#scan").click()
            playwright.expect(page.locator("#documents")).to_contain_text("Neighborhood utility bill", timeout=30000)
            assert len(local_model["requests"]) == 2
            page.locator("#documents-tab").click()
            playwright.expect(page.locator("#document-count")).to_have_text("2 documents")
            assert all(url.startswith(f"http://127.0.0.1:{port}/") or url.startswith("blob:") for url in requests)
            assert "token=" not in page.url
            assert not failures
            # Synthetic evidence only. Optional path is explicitly supplied by the test runner.
            if os.environ.get("BROWSER_SCREENSHOT"):
                page.screenshot(path=os.environ["BROWSER_SCREENSHOT"], full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        assert not thread.is_alive()
