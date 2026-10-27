"""Opt-in real browser smoke test: RUN_BROWSER_TESTS=1, installed Edge + Playwright."""

import os
import re
import socket
import threading
import time

import pytest
import uvicorn

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
except ImportError:  # Browser tests are optional (.[browser-test]).
    PlaywrightTimeout = TimeoutError

from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits


def row_action(page, name, row_text=None):
    """Secondary row actions live in each Records row's ⋯ menu (records_v2.js rc2Menu)."""
    page.wait_for_load_state("networkidle")  # A closing dialog redraws the list; open the menu on the redrawn row.
    rows = page.locator("#rc2-table tbody tr")
    row = rows.filter(has_text=row_text) if row_text else rows.first
    item = page.get_by_role("menuitem", name=name, exact=True)
    for attempt in range(5):  # A folder change still drawing can replace the row, closing the menu just after it opens.
        trigger = row.get_by_role("button", name=re.compile(r"^More actions for "))
        if trigger.get_attribute("aria-expanded") != "true":
            trigger.click()
        try:
            item.click(timeout=2000)
            return
        except PlaywrightTimeout:
            if attempt == 4:
                raise
            page.wait_for_load_state("networkidle")


def open_document(page, row_text):
    """A document's name links to its page."""
    page.locator("#rc2-table tbody tr").filter(has_text=row_text).locator("a.rc2-name").click()
    page.wait_for_selector("#doc2-panel:not([hidden])")


def wait_for_document(app, name, seconds=15):
    """A scan copies files in the background; the list shows them once it's done."""
    for _ in range(seconds * 10):
        if any(doc["relative_path"].endswith(name) for doc in app.state.manager.store.documents()["items"]):
            return
        time.sleep(.1)
    raise AssertionError(f"{name} was never captured")


def read_all(page, port, force=False):
    """Processing › Read all documents, optionally re-reading what already has text."""
    page.goto(f"http://127.0.0.1:{port}/#/processing")
    page.locator("#pr2-read").click()
    page.locator("#pr2-force").set_checked(force)
    page.locator("#pr2-read-start").click()


def wait_for_batch(page, text, timeout):
    """The latest reading batch's status line (app.js receiptBatchText), as the poll last saw it. Polled with evaluate:
    the strict CSP blocks wait_for_function's string eval."""
    line = ""
    for _ in range(timeout // 250):
        line = page.evaluate("() => receiptBatchText(receiptBatch)")
        if text in line:
            return
        page.wait_for_timeout(250)
    raise AssertionError(f"The reading batch never said {text!r}; last: {line!r}")


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
            # Without a library a page says so (ui.js pageState) instead of showing empty tables.
            page.locator("#nav-accounts").click()
            playwright.expect(page.locator("#accounts2-state")).to_contain_text("Set up your library to see accounts.")
            playwright.expect(page.locator("#accounts2-state").get_by_role("link", name="Open Settings")).to_be_visible()
            playwright.expect(page.locator("#accounts2-body")).to_be_hidden()
            page.locator("#nav-settings").click()
            playwright.expect(page.get_by_role("tab", name="Library folder", exact=True)).to_have_attribute("aria-selected", "true")
            playwright.expect(page.locator("#limits")).to_contain_text("Capture limits")
            page.locator("#managed").fill(str(tmp_path / "managed"))
            page.locator("#save-settings").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Library folder saved")
            document.write_bytes(b"date,total\n2026-09-01,123\n")
            playwright.expect(page.locator("#app-alert")).to_be_empty()
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=scans")
            page.locator("#pr2-scan").click()
            scan_state = page.locator("#pr2-scan-state")
            playwright.expect(scan_state).to_contain_text(re.compile("completed", re.I), timeout=15000)
            document.write_bytes(b"date,total\n2026-09-01,456\n")
            playwright.expect(page.locator("#pr2-scan")).to_be_enabled(timeout=10000)
            page.locator("#pr2-scan").click()
            playwright.expect(scan_state).to_contain_text("new_version", timeout=15000)
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=all")
            row_action(page, "Versions (2)", "sample.csv")
            playwright.expect(page.locator("#versions-dialog")).to_be_visible()
            assert page.locator("#versions-content code").count() == 2
            page.locator("#close-versions").click()
            from test_receipts import make_receipt
            payload = make_receipt(month / "receipt.png", local_model["output"]["full_text"].splitlines())
            receipt_bytes = (month / "receipt.png").read_bytes()  # Filing later moves the Inbox file.
            requests = []
            page.on("request", lambda request: requests.append(request.url))
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=scans")
            page.locator("#pr2-scan").click()
            wait_for_document(app, "receipt.png")
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=all")
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#doc2-panel")).to_be_visible()
            next_step = page.locator("#doc2-next")
            playwright.expect(next_step).to_contain_text("Reading needs a local vision model.")
            next_step.get_by_role("button", name="Read document").click()
            playwright.expect(next_step.get_by_role("alert")).to_contain_text("Configure a local vision model")
            page.locator("#doc2-back").click()
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
            read_all(page, port)
            wait_for_batch(page, "completed", 30000)
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=all")
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#doc2-title")).to_have_text("receipt.png")
            playwright.expect(next_step).to_contain_text("Read, but not recorded yet")
            viewer = page.locator("#doc2-viewer")
            playwright.expect(viewer.locator(".sv-line", has_text="Returns within 14 days")).to_have_count(1)
            viewer.locator(".sv-extras > summary").click()
            playwright.expect(viewer.locator(".sv-codes")).to_contain_text(payload)
            viewer.get_by_role("button", name="Highlight code").first.click()
            assert viewer.locator(".sv-overlay .selected").count() > 0
            page.locator("#doc2-back").click()
            playwright.expect(page.locator("#rc2-panel")).to_be_visible()
            read_all(page, port)
            wait_for_batch(page, "1 reused", 10000)
            assert len(local_model["requests"]) == 1
            vision_output = local_model["output"]
            gate = threading.Event()
            gate.set()
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=all")
            open_document(page, "receipt.png")
            record_it = next_step.get_by_role("button", name="Record it")
            playwright.expect(record_it).to_be_visible()  # Recording is the one next action.
            from test_extraction import classification, identity, receipt_items, receipt_summary
            local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "coffee & lunch", "category": None, "recurrence": None, "item_categories": ["dining", "dining", "groceries"]},
                                      {"rewards": [{"kind": "offer", "description": "Free returns within 14 days", "amount": "14 days", "expires": "2026-10-06",
                                                    "link": None, "evidence": [{"line_id": "line-8", "quote": "Returns within 14 days"}]}]}]
            record_it.click()
            record = page.locator("#doc2-panel-record")
            # Every automatic check passes, so the record counts with nothing to click; only a rejection remains available.
            playwright.expect(page.locator("#doc2-record-badge")).to_contain_text("Checked automatically", timeout=15000)
            playwright.expect(record).to_contain_text("25.00 USD")
            playwright.expect(page.locator("#doc2-record-title")).to_have_text("Receipt from Local Test Cafe")
            # A receipt spanning several categories shows every one, largest share first.
            playwright.expect(record.locator(".doc2-fields .category-tag")).to_have_text(["Dining", "Groceries"])
            # Rewards and offers printed on the receipt are listed with the line they came from.
            playwright.expect(record.locator(".receipt-rewards")).to_contain_text("Free returns within 14 days")
            playwright.expect(record.locator(".receipt-rewards")).to_contain_text("14 days")
            playwright.expect(page.locator("#doc2-decision").get_by_role("button", name="Reject")).to_be_visible()
            playwright.expect(page.locator('#doc2-steps li[data-state="done"]')).to_have_count(2)
            playwright.expect(record.locator(".ledger-rows tbody tr")).to_have_count(3)
            # A date the model misread (or the document never printed) is entered in place.
            record.locator(".doc2-fields").get_by_role("button", name="Correct purchase date").click()
            form = page.locator("#doc2-decision .cc-form")
            form.get_by_label("Purchase date").fill("2026-09-23")
            form.get_by_role("button", name="Save").click()
            playwright.expect(page.locator(".toast", has_text=re.compile(r"^Saved\."))).to_be_visible()
            playwright.expect(record.locator(".doc2-fields")).to_contain_text("Sep 23, 2026")
            playwright.expect(record.locator(".doc2-fields .status-badge", has_text="Changed by")).to_have_count(1)
            if os.environ.get("INSPECTOR_SCREENSHOT"):
                page.screenshot(path=os.environ["INSPECTOR_SCREENSHOT"])
            page.locator("#doc2-back").click()
            # Recording filed it into Receipts, which lives on the Receipts & statements page, not in Documents.
            playwright.expect(page.locator("#rc2-table")).not_to_contain_text("receipt.png")
            page.locator("#nav-receipts").click()
            open_document(page, "receipt.png")
            playwright.expect(page.locator("#doc2-title")).to_have_text("Local Test Cafe - Coffee & lunch")  # Merchant - Description.
            playwright.expect(page.locator("#doc2-subtitle")).to_contain_text("Receipts · Sep 23, 2026 · receipt.png")
            page.locator("#doc2-tab-details").click()
            playwright.expect(page.locator("#doc2-panel-details")).to_contain_text("Library/")
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
            if os.environ.get("INSPECTOR_MOBILE_SCREENSHOT"):
                page.screenshot(path=os.environ["INSPECTOR_MOBILE_SCREENSHOT"])
            page.set_viewport_size({"width": 1280, "height": 1000})
            page.locator("#doc2-back").click()
            receipt_row = page.locator("#rc2-table tbody tr").filter(has_text="receipt.png")
            playwright.expect(receipt_row).to_contain_text("Sep 23, 2026")
            playwright.expect(receipt_row).to_contain_text("Local Test Cafe - Coffee & lunch")
            # The user's own description replaces the AI's everywhere; clearing it restores the AI's.
            row_action(page, "Edit description…", "receipt.png")
            page.locator("#description-input").fill("Weekend treats")
            page.locator("#description-form").get_by_role("button", name="Save").click()
            playwright.expect(receipt_row).to_contain_text("Local Test Cafe - Weekend treats")
            row_action(page, "Edit description…", "receipt.png")
            playwright.expect(page.locator("#description-input")).to_have_value("Weekend treats")
            page.locator("#description-input").fill("")
            page.locator("#description-form").get_by_role("button", name="Save").click()
            playwright.expect(receipt_row).to_contain_text("Local Test Cafe - Coffee & lunch")
            playwright.expect(receipt_row).to_contain_text("25.00 USD")
            if os.environ.get("LIBRARY_SCREENSHOT"):
                page.screenshot(path=os.environ["LIBRARY_SCREENSHOT"])
            rows = page.locator("#rc2-table tbody tr")
            page.locator("#rc2-tree [data-folder-group='Receipts']").click()  # Receipts opens; "All receipts" lists every receipt.
            page.locator("#rc2-tree [data-folder='Receipts']:not([data-category])").click()
            playwright.expect(rows).to_have_count(1)
            row_action(page, "Delete")
            playwright.expect(page.locator("#library-action-description")).to_contain_text("Preserved copies are not deleted")
            page.locator("#cancel-library-action").click()
            playwright.expect(page.locator("#rc2-table")).to_contain_text("receipt.png")
            row_action(page, "Delete")
            page.get_by_role("button", name="Delete to Trash", exact=True).click()
            playwright.expect(rows).to_have_count(0)
            page.locator("#rc2-tree [data-folder='trash']").click()
            page.get_by_role("button", name="Restore Local Test Cafe - Coffee & lunch").click()
            playwright.expect(rows).to_have_count(0)
            page.locator("#rc2-tree [data-folder='Receipts']:not([data-category])").click()
            row_action(page, "Move")
            page.locator("#move-folder").select_option("Housing")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(rows).to_have_count(0)
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=Housing")  # Housing is a Documents folder.
            playwright.expect(page.locator("#rc2-table")).to_contain_text("receipt.png")
            # Model runs show measured telemetry; running model work can be cancelled.
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=models")
            playwright.expect(page.locator("#pr2-models")).to_contain_text("synthetic-reasoning")
            playwright.expect(page.locator("#pr2-task")).to_contain_text(re.compile("transcription", re.I))
            gate.clear()
            local_model["response_gate"] = gate
            try:
                read_all(page, port, force=True)
                playwright.expect(page.locator("#activity-indicator")).to_contain_text("Text extraction for all images")
                # The Inbox watcher may be working too; cancel this batch by its label.
                page.locator("#pr2-activity li").filter(has_text="Text extraction for all images").get_by_role("button", name=re.compile("^Cancel")).click()
                playwright.expect(page.locator("#toasts")).to_contain_text("Cancellation requested")
            finally:
                gate.set()
            wait_for_batch(page, "Batch cancelled", 15000)
            playwright.expect(page.locator("#pr2-activity")).to_contain_text("Nothing running.")
            # Newly captured images are transcribed and extraction is attempted automatically. This synthetic
            # model answers only transcription, so extraction stops and the bill waits in Inbox.
            local_model["output"] = vision_output
            (month / "bill.png").write_bytes(receipt_bytes + b"synthetic different version")
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=scans")
            page.locator("#pr2-scan").click()
            playwright.expect(scan_state).to_contain_text("Text extraction: partial", timeout=30000)
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=Inbox")
            playwright.expect(page.locator("#rc2-table")).to_contain_text("bill.png", timeout=30000)
            calls = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"]]
            # Every model call is accounted for. The cancelled batch's reading may be stopped before it reaches the server.
            assert [call for call in calls if call != "document_transcription"] == [
                "Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription", "Rewards",
                "item_step",  # Automatic item identification; this model can't answer it, so that run stops without proposals.
                "Classification", "Classification"]  # The bill's attempt and its one correction request.
            assert calls.count("document_transcription") in (2, 3)
            inbox_file = app.state.manager.store.library.inbox / "inbox-statement.csv"
            inbox_file.write_text("date,amount\n2026-09-24,10.00\n")
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=scans")
            page.locator("#pr2-scan").click()
            wait_for_document(app, "inbox-statement.csv")
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=Inbox")
            playwright.expect(page.locator("#rc2-table")).to_contain_text("inbox-statement.csv")
            playwright.expect(page.locator("#nav-inbox .nav-count")).to_have_text("3")  # sample.csv, bill.png and this file.
            row_action(page, "Move", "inbox-statement.csv")
            page.locator("#move-folder").select_option("Bank_Statements")
            page.get_by_role("button", name="Move document", exact=True).click()
            playwright.expect(page.locator("#rc2-table")).not_to_contain_text("inbox-statement.csv")
            assert not inbox_file.exists()
            page.goto(f"http://127.0.0.1:{port}/#/receipts?folder=Bank_Statements")  # Bank statements live with receipts on the money side.
            page.locator("#rc2-table").get_by_role("button", name="Add missed inbox-statement.csv").click()
            playwright.expect(page.locator("#import-status")).to_contain_text("Choose the description column")
            page.locator("#import-map-description").select_option("date")  # The only text-like column in this minimal file.
            playwright.expect(page.locator("#import-status")).to_contain_text("1 rows ready")
            playwright.expect(page.locator("#import-preview")).to_contain_text("10.00 USD")
            page.locator("#import-institution").fill("First Local Bank")
            page.locator("#confirm-import").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Imported 1 new transactions")
            page.locator("#nav-accounts").click()
            playwright.expect(page.locator("#accounts2-body")).to_contain_text("First Local Bank")
            # Items is the default view: the cafe receipt item by item, with tax shared in and the tip as dining, and the
            # imported 10.00 as money in (docs/money.md "Money in and paystubs").
            page.goto(f"http://127.0.0.1:{port}/#/transactions?period=all")
            items = page.locator("#tx2-table tbody")
            playwright.expect(items.locator("tr")).to_have_count(5)
            playwright.expect(items).to_contain_text("SANDWICH")
            playwright.expect(items).to_contain_text("11.00 USD")
            # Charges lists each card or bank line once, money in included.
            page.goto(f"http://127.0.0.1:{port}/#/transactions?view=charges&period=all")
            playwright.expect(items).to_contain_text("10.00 USD")
            items.locator(".tx2-name .link-button").first.click()
            playwright.expect(page.locator("#tx-drawer")).to_be_visible()
            page.locator("#tx-drawer-category").fill("savings")
            page.get_by_role("button", name="Save category").click()
            playwright.expect(page.locator("#tx-drawer")).to_contain_text("Set by you.")
            page.locator("#close-tx-drawer").click()
            playwright.expect(items).to_contain_text(re.compile("savings", re.I))
            # The recorded cafe receipt has no matching charge, so it counts on its own.
            page.goto(f"http://127.0.0.1:{port}/#/spending?month=2026-09")
            playwright.expect(page.locator("#month2-tiles")).to_contain_text("25.00 USD")
            page.locator("#month2-budget-add").click()
            page.locator("#month2-budget-category").fill("groceries")
            page.locator("#month2-budget-amount").fill("450.00")
            page.locator("#month2-budget-form").get_by_role("button", name="Save budget").click()
            # Budgets count by item category: the sandwich (10.00 plus its 1.00 share of tax) is groceries, the lattes and tip dining.
            playwright.expect(page.locator("#month2-budgets")).to_contain_text("11.00 USD")
            playwright.expect(page.locator("#month2-budgets")).to_contain_text("450.00 USD")
            # The receipt has no matching card or bank charge: To check lists it as unmatched.
            page.locator("#nav-review").click()
            playwright.expect(page.locator("#review2-queue")).to_contain_text("Receipts with no matching charge")
            playwright.expect(page.locator("#review2-queue")).to_contain_text("Local Test Cafe")
            page.goto(f"http://127.0.0.1:{port}/#/inventory?tab=returns")
            playwright.expect(page.locator("#it2-policies-body")).to_contain_text("Walmart")
            page.keyboard.press("Control+k")
            page.keyboard.type("first local")
            page.keyboard.press("Enter")
            playwright.expect(page.locator("#se2-panel")).to_be_visible()
            playwright.expect(page.locator("#se2-results")).to_contain_text("First Local Bank")
            # Processing: pipeline lanes and one history of all work; Settings: backups; the assistant panel.
            page.locator("#nav-processing").click()
            playwright.expect(page.locator("#pr2-lanes")).to_contain_text("Reconciliation")
            playwright.expect(page.locator("#pr2-work")).to_contain_text("Inbox capture")
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
            playwright.expect(page.locator("#bills2-panel")).to_be_visible()
            # PDFs have a visual preview even before reading; switching back to an image clears it.
            from test_pdf import make_pdf
            make_pdf(month / "preview.pdf", ["Receipt first page", None])
            app.state.manager.start_inbox()
            app.state.manager.future.result(timeout=30)
            pdf_doc = next(doc for doc in app.state.manager.store.documents()["items"] if doc["relative_path"].endswith("preview.pdf"))
            page.goto(f"http://127.0.0.1:{port}/#/documents/{pdf_doc['id']}")
            pdf = viewer.locator(".sv-pdf")
            playwright.expect(pdf).to_be_visible()
            playwright.expect(pdf).to_have_attribute("src", re.compile(r"^blob:"))
            playwright.expect(viewer.get_by_role("tab", name="Image")).to_have_attribute("aria-selected", "true")
            playwright.expect(viewer.locator(".sv-img")).to_be_hidden()
            viewer.get_by_role("tab", name="Text").click()
            playwright.expect(pdf).to_be_hidden()
            viewer.get_by_role("tab", name="Image").click()
            playwright.expect(pdf).to_be_visible()
            image_doc = next(doc for doc in app.state.manager.store.documents()["items"] if doc["relative_path"].endswith("receipt.png"))
            page.goto(f"http://127.0.0.1:{port}/#/documents/{image_doc['id']}")
            playwright.expect(viewer.locator(".sv-img")).to_be_visible()
            playwright.expect(viewer.locator(".sv-pdf")).to_be_hidden()
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=all")
            row_action(page, "Delete", "preview.pdf")
            page.locator("#confirm-library-action").click()
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=trash")
            playwright.expect(page.locator("#rc2-table")).to_contain_text("preview.pdf")
            page.locator("#rc2-empty-trash").click()
            playwright.expect(page.locator("#confirm-title")).to_have_text("Permanently empty Trash?")
            page.locator("#confirm-cancel").click()
            page.locator("#rc2-empty-trash").click()
            page.locator("#confirm-accept").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("permanently deleted")
            playwright.expect(page.locator("#rc2-panel")).not_to_contain_text("preview.pdf")
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
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=folders")
            playwright.expect(page.locator("#pr2-folders")).to_contain_text("No watched folders")
            page.locator("#pr2-add-source").click()
            page.locator("#pr2-source-path").fill(str(folder))
            page.locator("#pr2-source-label").fill("Downloads")
            page.locator("#pr2-source-save").click()
            playwright.expect(page.locator("#pr2-source-dialog")).to_be_hidden()
            page.get_by_role("button", name="Scan Downloads").click()
            for _ in range(150):  # The scan copies the file into the library.
                if any(doc["relative_path"].endswith("statement.csv") for doc in app.state.manager.store.documents()["items"]):
                    break
                time.sleep(.1)
            page.goto(f"http://127.0.0.1:{port}/#/documents?folder=all")
            playwright.expect(page.locator("#rc2-table")).to_contain_text("statement.csv", timeout=15000)
            assert (folder / "statement.csv").exists()  # Copied, never moved.
            page.goto(f"http://127.0.0.1:{port}/#/processing?tab=folders")
            page.get_by_role("button", name="Stop watching Downloads").click()
            playwright.expect(page.locator("#confirm-dialog")).to_be_visible()
            page.locator("#confirm-accept").click()
            playwright.expect(page.locator("#pr2-folders")).to_contain_text("No watched folders")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                wide = page.evaluate("""() => [...document.querySelectorAll('#pr2-panel *')].filter(e => e.getBoundingClientRect().right > window.innerWidth + 1)
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
            panel = page.locator("#doc2-panel .split-panel")
            playwright.expect(panel).to_contain_text("This file holds 2 receipts", timeout=15000)
            playwright.expect(panel).to_contain_text("waits in To check")
            playwright.expect(panel.locator(".filter-chip[aria-pressed=true]")).to_contain_text("CORNER COFFEE")
            panel.get_by_role("button", name=re.compile("TOWN BAKERY")).click()
            playwright.expect(panel.locator(".filter-chip[aria-pressed=true]")).to_contain_text("TOWN BAKERY")
            panel.get_by_role("button", name="Confirm split").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Split confirmed")
            playwright.expect(panel).not_to_contain_text("waits in To check")
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
            queue = page.locator("#review2-queue")
            playwright.expect(queue).to_contain_text("2 images · receipt_p1.png", timeout=15000)
            queue.locator(".review2-entry", has_text="receipt_p").first.click()
            playwright.expect(page.locator("#review2-source .review2-chips .filter-chip")).to_have_count(2)
            page.locator("#review2-confirm").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Combined")
            playwright.expect(queue.locator(".review2-group-title", has_text="Images that look like one document")).to_have_count(0)
            manager.future.result(timeout=60)
            lead = manager.store.documents()["items"][0]
            page.goto(f"http://127.0.0.1:{port}/#/documents/{lead['id']}")
            strip = page.locator("#doc2-group")
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
