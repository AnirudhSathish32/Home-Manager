"""Opt-in real browser smoke test: RUN_BROWSER_TESTS=1, installed Edge + Playwright."""

import os
import re
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits


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
    month = tmp_path / "managed" / "Library" / "Inbox"  # Created when the library folder is saved.
    document = month / "sample.csv"
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
            playwright.expect(page.get_by_role("tab", name="Library folder", exact=True)).to_have_attribute("aria-selected", "true")
            playwright.expect(page.locator("#limits")).to_contain_text("Capture limits")
            page.locator("#managed").fill(str(tmp_path / "managed"))
            page.locator("#save-settings").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Library folder saved")
            document.write_bytes(b"date,total\n2026-09-01,123\n")
            playwright.expect(page.locator("#app-alert")).to_be_empty()
            page.locator("#nav-processing").click()
            page.locator("#scan-inbox").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("completed", timeout=15000)
            playwright.expect(page.locator("#documents")).to_contain_text("sample.csv")
            document.write_bytes(b"date,total\n2026-09-01,456\n")
            playwright.expect(page.locator("#scan-inbox")).to_be_enabled(timeout=10000)
            page.locator("#scan-inbox").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("new_version", timeout=15000)
            page.locator("#nav-documents").click()
            playwright.expect(page.locator("#documents tr").filter(has_text="sample.csv")).to_contain_text("Versions (2)")
            row_action(page, "Versions (2)", "sample.csv")
            playwright.expect(page.locator("#versions-dialog")).to_be_visible()
            assert page.locator("#versions-content code").count() == 2
            page.locator("#close-versions").click()
            from test_receipts import make_receipt
            payload = make_receipt(month / "receipt.png", local_model["output"]["full_text"].splitlines())
            receipt_bytes = (month / "receipt.png").read_bytes()  # Filing later moves the Inbox file.
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.locator("#nav-processing").click()
            page.locator("#scan-inbox").click()
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
            # A decision model in LM Studio: every answer is "A" (yes, or the first document type: receipt).
            local_model["decide"] = lambda path, body: {"output": [{"type": "message", "content": [{"type": "output_text", "text": "A",
                "logprobs": [{"token": "A", "logprob": -0.05, "top_logprobs": [{"token": "A", "logprob": -0.05}, {"token": "B", "logprob": -3.0}]}]}]}]}
            page.locator("#decision-provider").select_option("lmstudio")
            page.locator("#decision-url").fill(local_model["config"].base_url)
            page.locator("#decision-model").fill("synthetic-reasoning")
            page.locator("#test-decision").click()
            playwright.expect(page.locator("#test-decision-result")).to_contain_text("answers with option probabilities")
            page.locator("#save-decision").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Decision model saved")
            page.get_by_role("tab", name="Independent checks", exact=True).click()
            playwright.expect(page.locator("#decision-status")).to_contain_text("synthetic-reasoning checks every ledger extraction")
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
            local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "coffee & lunch", "category": None, "recurrence": None, "item_categories": ["dining", "dining", "groceries"]},
                                      {"rewards": [{"kind": "offer", "description": "Free returns within 14 days", "amount": "14 days", "expires": "2026-10-06",
                                                    "link": None, "evidence": [{"line_id": "line-8", "quote": "Returns within 14 days"}]}]}]
            page.locator("#extract-ledger").click()
            playwright.expect(page.locator("#extraction-state")).to_have_text("Done", timeout=15000)
            playwright.expect(page.locator("#extraction-result")).to_contain_text("25.00 USD")
            # Every automatic check passes, so the record counts with nothing to click; only a rejection remains available.
            playwright.expect(page.locator("#extraction-result .ledger-record-heading .status-badge")).to_have_text("Checked automatically")
            # Items carry their own categories; the receipt counts on its own until a statement line matches it.
            playwright.expect(page.locator("#extraction-result .receipt-splits")).to_contain_text("Receipt only")
            # A receipt spanning several categories shows every one in its summary, largest share first.
            playwright.expect(page.locator("#extraction-result .receipt-summary .category-tag")).to_have_text(["Dining", "Groceries"])
            page.locator("#extraction-result").get_by_role("button", name="Edit details").click()
            playwright.expect(page.get_by_label("Category for all items")).to_be_visible()
            page.locator("#extraction-result").get_by_role("button", name="Cancel").click()
            # Rewards and offers printed on the receipt are listed with the line they came from.
            playwright.expect(page.locator("#extraction-result .receipt-rewards")).to_contain_text("Free returns within 14 days")
            playwright.expect(page.locator("#extraction-result .receipt-rewards")).to_contain_text("14 days")
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
            # Recording filed it into Receipts, which lives on the Receipts & statements page, not in Documents.
            playwright.expect(page.locator("#documents")).not_to_contain_text("receipt.png")
            page.locator("#nav-receipts").click()
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
            page.locator('[data-folder-group="Receipts"]').click()  # Receipts opens; "All receipts" lists every receipt.
            page.locator('.folder-link[data-folder="Receipts"]').click()
            playwright.expect(page.locator("#document-count")).to_have_text("1 document")
            row_action(page, "Delete")
            playwright.expect(page.locator("#library-action-description")).to_contain_text("Preserved copies are not deleted")
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
            page.locator("#move-folder").select_option("Housing")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(page.locator("#empty-folder")).to_be_visible()
            page.locator("#nav-documents").click()  # Housing is a Documents folder.
            page.locator('.folder-link[data-folder="Housing"]').click()
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
                # The Inbox watcher may be working too; cancel this batch by its label.
                page.locator("#activity li").filter(has_text="Text extraction for all images").get_by_role("button", name="Cancel").click()
                playwright.expect(page.locator("#toasts")).to_contain_text("Cancellation requested")
            finally:
                gate.set()
            playwright.expect(page.locator("#receipt-batch-status")).to_contain_text("Batch cancelled", timeout=15000)
            playwright.expect(page.locator("#activity")).to_contain_text("No active scans or model work")
            page.locator("#force-receipts").uncheck()
            # Newly captured images are transcribed and extraction is attempted automatically. This synthetic
            # model answers only transcription, so extraction stops and the bill waits in Inbox.
            local_model["output"] = vision_output
            (month / "bill.png").write_bytes(receipt_bytes + b"synthetic different version")
            page.locator("#nav-processing").click()
            page.locator("#scan-inbox").click()
            playwright.expect(page.locator("#scan-state")).to_contain_text("Text extraction: partial", timeout=30000)
            page.locator("#nav-documents").click()
            page.locator('.folder-link[data-folder="Inbox"]').click()
            playwright.expect(page.locator("#documents")).to_contain_text("bill.png", timeout=30000)
            calls = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"]]
            # Every model call is accounted for. The cancelled batch's reading may be stopped before it reaches the server.
            assert [call for call in calls if call != "document_transcription"] == [
                "Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription", "Rewards",
                "item_step",  # Automatic item identification; this model can't answer it, so that run stops without proposals.
                "Classification", "Classification"]  # The bill's attempt and its one correction request.
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
            playwright.expect(page.locator("#nav-inbox .nav-count")).to_have_text("3")  # sample.csv, bill.png and this file.
            row_action(page, "Move", "inbox-statement.csv")
            page.locator("#move-folder").select_option("Bank_Statements")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(page.locator("#documents")).not_to_contain_text("inbox-statement.csv")
            assert not inbox_file.exists()
            page.locator("#nav-receipts").click()  # Bank statements live with receipts on the money side.
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
            page.locator("#nav-accounts").click()
            playwright.expect(page.locator("#account-groups")).to_contain_text("First Local Bank")
            page.locator("#nav-transactions").click()
            page.locator("#tx-period").select_option("all")
            # Items is the default view: the cafe receipt item by item, with tax shared in and the tip as dining.
            playwright.expect(page.locator("#item-rows tr")).to_have_count(4)
            playwright.expect(page.locator("#item-rows")).to_contain_text("SANDWICH")
            playwright.expect(page.locator("#item-rows")).to_contain_text("11.00 USD")
            playwright.expect(page.locator("#item-rows")).to_contain_text("Receipt only")
            # Charges lists each card or bank line once, money in included.
            page.locator("#tx-view").select_option("charges")
            playwright.expect(page.locator("#tx-rows")).to_contain_text("10.00 USD")
            page.locator("#tx-rows .link-button").first.click()
            playwright.expect(page.locator("#tx-drawer")).to_be_visible()
            page.locator("#tx-drawer-category").fill("savings")
            page.get_by_role("button", name="Save category").click()
            playwright.expect(page.locator("#tx-drawer")).to_contain_text("Set by you.")
            page.locator("#close-tx-drawer").click()
            playwright.expect(page.locator("#tx-rows")).to_contain_text("savings")
            page.locator("#nav-spending").click()
            page.locator("#spend-month").fill("2026-09")
            page.locator("#spend-month").dispatch_event("change")
            # The recorded cafe receipt has no matching charge, so it counts on its own and is labelled as such.
            playwright.expect(page.locator("#spend-figures")).to_contain_text("From receipts only25.00 USD · 1 receipt")
            page.locator("#budget-category").fill("groceries")
            page.locator("#budget-amount").fill("450.00")
            page.get_by_role("button", name="Save budget").click()
            # Budgets count by item category: the sandwich (10.00 plus its 1.00 share of tax) is groceries, the lattes and tip dining.
            playwright.expect(page.locator("#budget-rows")).to_contain_text("11.00 USD of 450.00 USD")
            page.locator("#nav-review").click()
            playwright.expect(page.locator("#review-detail")).to_contain_text("Nothing needs your review")
            # The receipt has no matching card or bank charge: listed as unmatched, not counted in spending.
            playwright.expect(page.locator("#review-unmatched")).to_contain_text("25.00 USD")
            playwright.expect(page.locator("#review-unmatched")).to_contain_text("No matching card or bank charge yet.")
            page.locator("#nav-inventory").click()
            playwright.expect(page.locator("#inventory-groups")).to_contain_text("No items yet")
            playwright.expect(page.locator("#policy-rows")).to_contain_text("Walmart")
            page.keyboard.press("Control+k")
            page.keyboard.type("first local")
            page.keyboard.press("Enter")
            playwright.expect(page.locator("#search-panel")).to_be_visible()
            playwright.expect(page.locator("#search-results")).to_contain_text("First Local Bank")
            # Phase E: pipeline lanes, one history of all work, backup section; Phase F: the assistant panel.
            page.locator("#nav-processing").click()
            playwright.expect(page.locator("#pipeline-lanes")).to_contain_text("Reconciliation")
            playwright.expect(page.locator("#job-rows")).to_contain_text("Inbox capture")
            page.locator("#nav-settings").click()
            # Reached with the arrow keys, not a click, the Backup tab still loads its list.
            page.locator("#checks-tab").click()
            page.keyboard.press("ArrowRight")
            playwright.expect(page.locator("#backup-tab")).to_be_focused()
            playwright.expect(page.locator("#backup-rows")).to_contain_text("No backups yet")
            page.keyboard.press("Control+j")
            playwright.expect(page.locator("#assistant-panel")).to_be_visible()
            playwright.expect(page.locator("#assistant-question")).to_be_focused()
            page.keyboard.press("Escape")
            playwright.expect(page.locator("#assistant-panel")).to_be_hidden()
            page.goto(f"http://127.0.0.1:{port}/#/finances?section=bills")  # Old links still land on the right page.
            playwright.expect(page.locator("#bills-panel")).to_be_visible()
            # PDFs have a visual preview even before reading; switching back to an image clears it.
            from test_pdf import make_pdf
            make_pdf(month / "preview.pdf", ["Receipt first page", None])
            app.state.manager.start_inbox()
            app.state.manager.future.result(timeout=30)
            pdf_doc = next(doc for doc in app.state.manager.store.documents()["items"] if doc["relative_path"].endswith("preview.pdf"))
            page.goto(f"http://127.0.0.1:{port}/#/documents/{pdf_doc['id']}")
            playwright.expect(page.locator("#receipt-pdf")).to_be_visible()
            playwright.expect(page.locator("#receipt-pdf")).to_have_attribute("src", re.compile(r"^blob:"))
            playwright.expect(page.locator("#source-image-tab")).to_have_attribute("aria-selected", "true")
            playwright.expect(page.locator("#receipt-image")).to_be_hidden()
            page.locator("#source-text-tab").click()
            playwright.expect(page.locator("#receipt-pdf")).to_be_hidden()
            page.locator("#source-image-tab").click()
            playwright.expect(page.locator("#receipt-pdf")).to_be_visible()
            image_doc = next(doc for doc in app.state.manager.store.documents()["items"] if doc["relative_path"].endswith("receipt.png"))
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


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_real_browser_watches_a_folder(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    folder = tmp_path / "Downloads"
    folder.mkdir()
    (folder / "statement.csv").write_bytes(b"date,total\n2026-09-01,123\n")
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
        app.state.manager.configure(str(tmp_path / "managed"))
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=browser-test-token")
            page.locator("#nav-processing").click()
            playwright.expect(page.locator("#source-rows")).to_contain_text("No watched folders")
            page.locator("#source-path").fill(str(folder))
            page.locator("#source-label").fill("Downloads")
            page.locator("#add-source").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Folder added")
            row = page.locator("#source-rows tr").filter(has_text="Downloads")
            row.get_by_role("button", name="Scan now").click()
            playwright.expect(page.locator("#documents")).to_contain_text("statement.csv", timeout=15000)
            assert (folder / "statement.csv").exists()  # Copied, never moved.
            row.get_by_role("button", name="Stop watching").click()
            playwright.expect(page.locator("#confirm-dialog")).to_be_visible()
            page.locator("#confirm-accept").click()
            playwright.expect(page.locator("#source-rows")).to_contain_text("No watched folders")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                wide = page.evaluate("""() => [...document.querySelectorAll('#scan-panel *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
                    .slice(0, 8).map(e => e.tagName + '#' + e.id + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right))""")
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (width, wide)
            assert failures == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_real_browser_shows_and_confirms_a_split_file(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    from home_manager.documents.reasoning import ReasoningConfig
    from home_manager.finance.ledger import HouseholdConfig
    from test_receipt_segments import LINES, split_answers
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
        make_receipt(manager.store.library.inbox / "pile.png")
        local_model["output"] = {"full_text": "\n".join(LINES)}
        manager.configure_vision(local_model["config"])
        manager.start_inbox()
        manager.future.result(timeout=30)
        manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
        manager.configure_household(HouseholdConfig(auto_identify_items=False))
        doc = manager.store.documents()["items"][0]
        local_model["outputs"] = split_answers()
        manager.start_extraction(doc["id"], manager.receipts.history(doc["id"])[0]["id"])
        manager.future.result(timeout=30)
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=browser-test-token")
            page.goto(f"http://127.0.0.1:{port}/#/documents/{doc['id']}")
            panel = page.locator(".split-panel")
            playwright.expect(panel).to_contain_text("This file holds 2 receipts", timeout=15000)
            playwright.expect(panel).to_contain_text("waits in Review")
            playwright.expect(page.locator(".ledger-record-heading")).to_contain_text("CORNER COFFEE")
            panel.get_by_role("button", name="TOWN BAKERY").click()
            playwright.expect(page.locator(".ledger-record-heading")).to_contain_text("TOWN BAKERY")
            panel.get_by_role("button", name="Confirm split").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Split confirmed")
            playwright.expect(panel).not_to_contain_text("waits in Review")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert failures == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_real_browser_combines_suggested_images(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
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
        for name in ("receipt_p1.png", "receipt_p2.png"):
            make_receipt(manager.store.library.inbox / name, [name])
        manager.start_inbox()
        manager.future.result(timeout=30)
        manager.configure_vision(local_model["config"])
        local_model["outputs"] = [{"full_text": "SHOP\nITEM 1.00"}, {"full_text": "Total 1.00"}]
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=browser-test-token")
            page.goto(f"http://127.0.0.1:{port}/#/review")
            panel = page.locator("#group-suggestions-panel")
            playwright.expect(panel).to_contain_text("receipt_p2.png", timeout=15000)
            panel.get_by_role("button", name="Combine 2 images").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Combined")
            playwright.expect(panel).to_be_hidden()
            manager.future.result(timeout=60)
            lead = manager.store.documents()["items"][0]
            page.goto(f"http://127.0.0.1:{port}/#/documents/{lead['id']}")
            strip = page.locator("#group-pages")
            playwright.expect(strip).to_contain_text("Combined document · 2 pages", timeout=15000)
            strip.get_by_role("button", name="Page 2").click()
            playwright.expect(strip.get_by_role("button", name="Page 2")).to_have_attribute("aria-pressed", "true")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert failures == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
