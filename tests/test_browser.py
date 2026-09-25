"""Opt-in real browser smoke test: RUN_BROWSER_TESTS=1, installed Edge + Playwright."""

import os
import re
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.api import create_app
from home_manager.scanner import ScanLimits


def row_action(page, name, row_text=None):
    """Secondary row actions live in each row's "More actions" menu."""
    rows = page.locator("#documents tr")
    row = rows.filter(has_text=row_text) if row_text else rows.first
    row.get_by_role("button", name="More actions").click()
    row.get_by_role("menuitem", name=name, exact=True).click()


def open_document(page, row_text):
    """A document's name links to its inspector page."""
    page.locator("#documents tr").filter(has_text=row_text).locator("a.doc-link").click()


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_real_browser_configures_scans_and_inspects_versions(tmp_path, local_model):
    local_model["output"]["full_text"] += "\nLATTE 1 @ 5.00 5.00\nLATTE 1 @ 5.00 5.00\nSANDWICH 1 @ 10.00 10.00"
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
            playwright.expect(page.locator("#app-alert")).to_contain_text("Choose where Home Manager keeps its library")
            page.locator("#nav-settings").click()
            playwright.expect(page.get_by_role("tab", name="Library & sources", exact=True)).to_have_attribute("aria-selected", "true")
            playwright.expect(page.locator("#limits")).to_contain_text("Capture limits")
            page.locator("#source").fill(str(source))
            page.locator("#managed").fill(str(tmp_path / "managed"))
            page.locator("#save-settings").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Directories saved")
            playwright.expect(page.locator("#app-alert")).to_be_empty()
            page.locator("#nav-processing").click()
            page.locator("#scan").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("completed", timeout=15000)
            playwright.expect(page.locator("#documents")).to_contain_text("sample.csv")
            document.write_bytes(b"date,total\n2026-09-01,456\n")
            playwright.expect(page.locator("#scan")).to_be_enabled(timeout=10000)
            page.locator("#scan").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("new_version", timeout=15000)
            page.locator("#nav-documents").click()
            playwright.expect(page.locator("#documents tr").filter(has_text="sample.csv")).to_contain_text("Versions (2)")
            row_action(page, "Versions (2)", "sample.csv")
            playwright.expect(page.locator("#versions-dialog")).to_be_visible()
            assert page.locator("#versions-content code").count() == 2
            page.locator("#close-versions").click()
            from test_receipts import make_receipt
            payload = make_receipt(month / "receipt.png", local_model["output"]["full_text"].splitlines())
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.locator("#nav-processing").click()
            page.locator("#scan").click()
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png", timeout=15000)
            page.locator("#nav-documents").click()
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#document-page")).to_be_visible()
            playwright.expect(page.locator("#record-empty")).to_contain_text("hasn't read this document yet")
            page.locator("#parse-receipt").click()
            playwright.expect(page.locator("#receipt-status")).to_contain_text("Configure a local vision model")
            page.locator("#close-receipt").click()
            page.locator("#nav-settings").click()
            page.get_by_role("tab", name="Local models", exact=True).click()
            page.locator("#vision-url").fill(local_model["config"].base_url)
            page.locator("#vision-model").fill(local_model["config"].model)
            page.locator("#save-vision").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Local model settings saved")
            page.locator("#reasoning-url").fill(local_model["config"].base_url)
            page.locator("#reasoning-model").fill("synthetic-reasoning")
            page.locator("#save-reasoning").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Reasoning settings saved")
            page.locator("#nav-processing").click()
            page.locator("#parse-all-receipts").click()
            playwright.expect(page.locator("#receipt-batch-status")).to_contain_text("completed", timeout=30000)
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png")
            page.locator("#nav-documents").click()
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#receipt-title")).to_have_text("receipt.png")
            playwright.expect(page.locator("#record-empty")).to_contain_text("Read, but not recorded yet")
            playwright.expect(page.locator("#receipt-text")).to_have_value(re.compile("Returns within 14 days"))
            playwright.expect(page.locator("#receipt-codes")).to_contain_text(payload)
            page.locator(".source-extras > summary").click()
            page.get_by_role("button", name="Highlight code").first.click()
            assert page.locator("#receipt-overlay .selected").count() > 0
            page.locator("#close-receipt").click()
            playwright.expect(page.locator("#library-panel")).to_be_visible()
            page.locator("#nav-processing").click()
            page.locator("#parse-all-receipts").click()
            playwright.expect(page.locator("#receipt-batch-status")).to_contain_text("1 reused", timeout=10000)
            assert len(local_model["requests"]) == 1
            vision_output = local_model["output"]
            gate = threading.Event()
            gate.set()
            page.locator("#nav-documents").click()
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#extract-ledger")).to_be_visible()  # Ledger extraction is the primary action.
            assert page.locator("#analyze-finances").count() == 0 and page.locator("#audit-tab").count() == 0  # No audit step remains.
            from test_extraction import classification, identity, receipt_items, receipt_summary
            local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "coffee & lunch"}]
            page.locator("#extract-ledger").click()
            playwright.expect(page.locator("#extraction-state")).to_have_text("Done", timeout=15000)
            playwright.expect(page.locator("#extraction-result")).to_contain_text("25.00 USD")
            # Every automatic check passes, so the record counts with nothing to click; only a rejection remains available.
            playwright.expect(page.locator("#extraction-result .status-badge")).to_have_text("Checked automatically")
            playwright.expect(page.locator("#extraction-result").get_by_role("button", name="Count it anyway")).to_have_count(0)
            playwright.expect(page.locator("#extraction-result").get_by_role("button", name="Not right? Reject")).to_be_visible()
            playwright.expect(page.locator("#receipt-title")).to_have_text("receipt.png")  # Set once on open; loading never renames it.
            playwright.expect(page.locator("#extraction-result .ledger-record-heading")).to_contain_text("Local Test Cafe - Coffee & lunch")
            playwright.expect(page.locator("#document-state")).to_have_text("Recorded")
            playwright.expect(page.locator("#extraction-result .ledger-rows tbody tr")).to_have_count(3)
            # A date the model misread (or the document never printed) and a missing location are entered in place.
            page.locator("#extraction-result").get_by_role("button", name="Edit details").click()
            page.locator("#correct-purchase_date").fill("2026-09-23")
            page.locator("#correct-location").fill("Downtown")
            page.locator("#extraction-result").get_by_role("button", name="Save").click()
            playwright.expect(page.locator("#extraction-result .receipt-summary")).to_contain_text("Sep 23, 2026")
            playwright.expect(page.locator("#extraction-result .receipt-summary")).to_contain_text("Entered by you")
            playwright.expect(page.locator("#extraction-result .ledger-record-heading")).to_contain_text("Local Test Cafe - Downtown - Coffee & lunch")
            if os.environ.get("INSPECTOR_SCREENSHOT"):
                page.screenshot(path=os.environ["INSPECTOR_SCREENSHOT"])
            # A recorded row finds its own line in the transcription.
            page.locator("#extraction-result .ledger-rows").get_by_role("button", name="Find this row in the transcription").nth(1).click()
            playwright.expect(page.locator("#source-text-tab")).to_have_attribute("aria-selected", "true")
            assert page.locator("#receipt-text").evaluate("el => el.value.slice(0, el.selectionStart).split('\\n').length") == 10
            page.locator("#close-receipt").click()
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#receipt-title")).to_have_text("Local Test Cafe - Downtown - Coffee & lunch")  # Merchant - Location - Description.
            playwright.expect(page.locator("#receipt-subtitle")).to_contain_text("Receipts · Sep 23, 2026 · receipt.png")
            page.locator("#details-tab").click()
            playwright.expect(page.locator("#document-details")).to_contain_text("Library/")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
            if os.environ.get("INSPECTOR_MOBILE_SCREENSHOT"):
                page.screenshot(path=os.environ["INSPECTOR_MOBILE_SCREENSHOT"])
            page.set_viewport_size({"width": 1280, "height": 1000})
            page.locator("#close-receipt").click()
            receipt_row = page.locator("#documents tr").filter(has_text="receipt.png")
            playwright.expect(receipt_row).to_contain_text("Recorded")
            playwright.expect(receipt_row).to_contain_text("Sep 23, 2026")
            playwright.expect(receipt_row).to_contain_text("Local Test Cafe - Downtown - Coffee & lunch")
            # The user's own description replaces the AI's everywhere; clearing it restores the AI's.
            row_action(page, "Edit description…", "receipt.png")
            page.locator("#description-input").fill("Weekend treats")
            page.locator("#description-form").get_by_role("button", name="Save").click()
            playwright.expect(receipt_row).to_contain_text("Local Test Cafe - Downtown - Weekend treats")
            row_action(page, "Edit description…", "receipt.png")
            playwright.expect(page.locator("#description-input")).to_have_value("Weekend treats")
            page.locator("#description-input").fill("")
            page.locator("#description-form").get_by_role("button", name="Save").click()
            playwright.expect(receipt_row).to_contain_text("Local Test Cafe - Downtown - Coffee & lunch")
            playwright.expect(receipt_row).to_contain_text("25.00 USD")
            if os.environ.get("LIBRARY_SCREENSHOT"):
                page.locator("#documents tr").filter(has_text="sample.csv").get_by_role("button", name="More actions").click()
                page.screenshot(path=os.environ["LIBRARY_SCREENSHOT"])
            row_action(page, "Move", "receipt.png")
            page.locator("#move-folder").select_option("Receipts")
            page.get_by_role("button", name="Move document", exact=True).click()
            page.locator('.folder-link[data-folder="Receipts"]').click()
            playwright.expect(page.locator("#document-count")).to_have_text("1 document")
            row_action(page, "Delete")
            playwright.expect(page.locator("#library-action-description")).to_contain_text("Source files and preserved copies are not deleted")
            page.locator("#cancel-library-action").click()
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png")
            row_action(page, "Delete")
            page.get_by_role("button", name="Delete to Trash", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator('.folder-link[data-folder="trash"]').click()
            page.get_by_role("button", name="Restore", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator('.folder-link[data-folder="Receipts"]').click()
            row_action(page, "Move")
            page.locator("#move-folder").select_option("Bills")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator('.folder-link[data-folder="Bills"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("receipt.png")
            # Model history shows measured telemetry; running model work can be cancelled.
            page.locator("#nav-processing").click()
            playwright.expect(page.locator("#model-history")).to_contain_text("reasoning")
            playwright.expect(page.locator("#model-history")).to_contain_text("transcription")
            gate.clear()
            local_model["response_gate"] = gate
            try:
                page.locator("#force-receipts").check()
                page.locator("#parse-all-receipts").click()
                playwright.expect(page.locator("#activity-indicator")).to_contain_text("Text extraction for all images")
                page.locator("#nav-processing").click()
                page.locator("#activity").get_by_role("button", name="Cancel").click()
                playwright.expect(page.locator("#toasts")).to_contain_text("Cancellation requested")
            finally:
                gate.set()
            playwright.expect(page.locator("#receipt-batch-status")).to_contain_text("Batch cancelled", timeout=15000)
            playwright.expect(page.locator("#activity")).to_contain_text("No active scans or model work")
            page.locator("#force-receipts").uncheck()
            # Newly scanned images are transcribed automatically and remain Unfiled.
            local_model["output"] = vision_output
            (month / "bill.png").write_bytes((month / "receipt.png").read_bytes() + b"synthetic different version")
            page.locator("#nav-processing").click()
            page.locator("#scan").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("Text extraction: completed", timeout=30000)
            page.locator("#nav-documents").click()
            page.locator('.folder-link[data-folder="Unfiled"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("bill.png", timeout=30000)
            calls = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"]]
            # Every model call is accounted for. The cancelled batch's reading may be stopped before it reaches the server.
            assert [call for call in calls if call != "document_transcription"] == [
                "Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription"]
            assert calls.count("document_transcription") in (2, 3)
            page.locator("#nav-documents").click()
            playwright.expect(page.locator("#document-count")).to_have_text("2 documents")
            inbox_file = app.state.manager.store.library.inbox / "inbox-statement.csv"
            inbox_file.write_text("date,amount\n2026-09-24,10.00\n")
            page.locator("#nav-processing").click()
            page.locator("#scan-inbox").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("completed", timeout=15000)
            page.locator("#nav-documents").click()
            page.locator('.folder-link[data-folder="Inbox"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("inbox-statement.csv")
            playwright.expect(page.locator("#documents")).to_contain_text("Library/Inbox/")
            playwright.expect(page.locator("#nav-inbox .nav-count")).to_have_text("1")
            row_action(page, "Move")
            page.locator("#move-folder").select_option("Bank_Statements")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            assert not inbox_file.exists()
            page.locator('.folder-link[data-folder="Bank_Statements"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("Library/Bank_Statements/")
            page.get_by_role("button", name="Import transactions", exact=True).click()
            playwright.expect(page.locator("#import-status")).to_contain_text("Choose the description column")
            page.locator("#import-map-description").select_option("date")  # The only text-like column in this minimal file.
            playwright.expect(page.locator("#import-status")).to_contain_text("1 rows ready")
            playwright.expect(page.locator("#import-preview")).to_contain_text("10.00 USD")
            page.locator("#import-institution").fill("First Local Bank")
            page.locator("#confirm-import").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Imported 1 new transactions")
            page.locator("#nav-finances").click()
            page.locator("#finance-month").fill("2026-09")
            page.locator("#finance-month").dispatch_event("change")
            playwright.expect(page.locator("#finance-accounts")).to_contain_text("First Local Bank")
            playwright.expect(page.locator("#finance-transactions")).to_contain_text("10.00 USD")
            playwright.expect(page.locator("#finance-queue")).to_contain_text("Nothing needs review")
            playwright.expect(page.locator("#finance-spending")).to_contain_text("No counted spending")
            # The receipt has no matching card or bank charge: listed as unmatched, not counted in spending.
            playwright.expect(page.locator("#finance-unmatched")).to_contain_text("25.00 USD")
            playwright.expect(page.locator("#finance-unmatched")).to_contain_text("No matching card or bank charge yet.")
            # PDFs have a visual preview even before reading; switching back to an image clears it.
            from test_pdf import make_pdf
            make_pdf(month / "preview.pdf", ["Receipt first page", None])
            app.state.manager.start()
            app.state.manager.future.result(timeout=30)
            pdf_doc = next(doc for doc in app.state.manager.store.documents(source)["items"] if doc["relative_path"].endswith("preview.pdf"))
            page.goto(f"http://127.0.0.1:{port}/#/documents/{pdf_doc['id']}")
            playwright.expect(page.locator("#receipt-pdf")).to_be_visible()
            playwright.expect(page.locator("#receipt-pdf")).to_have_attribute("src", re.compile(r"^blob:"))
            playwright.expect(page.locator("#source-image-tab")).to_have_attribute("aria-selected", "true")
            playwright.expect(page.locator("#receipt-image")).to_be_hidden()
            page.locator("#source-text-tab").click()
            playwright.expect(page.locator("#receipt-pdf")).to_be_hidden()
            page.locator("#source-image-tab").click()
            playwright.expect(page.locator("#receipt-pdf")).to_be_visible()
            image_doc = next(doc for doc in app.state.manager.store.documents(source)["items"] if doc["relative_path"].endswith("receipt.png"))
            page.goto(f"http://127.0.0.1:{port}/#/documents/{image_doc['id']}")
            playwright.expect(page.locator("#receipt-image")).to_be_visible()
            playwright.expect(page.locator("#receipt-pdf")).to_be_hidden()
            page.locator("#nav-documents").click()
            page.locator('.folder-link[data-folder="all"]').click()
            row_action(page, "Delete", "preview.pdf")
            page.locator("#confirm-library-action").click()
            page.locator('.folder-link[data-folder="trash"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("preview.pdf")
            page.locator("#document-search").fill("nothing-matches-this")
            page.locator("#empty-trash").click()
            playwright.expect(page.locator("#library-action-description")).to_contain_text("cannot be undone")
            page.locator("#cancel-library-action").click()
            page.locator("#empty-trash").click()
            page.locator("#confirm-library-action").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("1 documents permanently deleted")
            page.locator("#document-search").fill("")
            playwright.expect(page.locator("#documents")).not_to_contain_text("preview.pdf")
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
