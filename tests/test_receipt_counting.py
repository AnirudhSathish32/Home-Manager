"""Receipts count on their own until a statement line replaces them; new statements wait for the user to reconcile."""

import json
import os
import socket
import threading
import time

from fastapi.testclient import TestClient
import pytest
import uvicorn

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.core.categories import RECEIPT_CATEGORIES
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, PeriodInput, TransactionsInput
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store

SEPTEMBER = PeriodInput(start="2026-09-01", end="2026-09-30")
# One blank page: enough for the browser's PDF viewer to load, which is what used to add a history entry.
MINIMAL_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
               b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n")


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"statement.pdf": b"synthetic statement", "cafe.png": b"synthetic cafe receipt",
                       "grocer.png": b"synthetic grocer receipt", "diner.png": b"synthetic diner receipt"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def source_of(doc):
    key = "extraction:" + doc["relative_path"]
    return {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": key}


def receipt(ledger, doc, merchant, day, total, category=None, status="verified"):
    return ledger.publish_receipt({"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                   "total_minor": total, "currency": "USD", "issues": [], "items": [], "category": category,
                                   "locator": {"line_ids": ["line-1"]}}, source_of(doc), status)["id"]


def statement(ledger, doc, rows):
    return ledger.publish_statement({"institution": "Fidelity", "statement_type": "credit_card", "last_four": "7314", "currency": "USD",
                                     "period_start": "2026-09-01", "period_end": "2026-09-30", "statement_balance_minor": 0, "summary": {},
                                     "issues": [], "locator": {"line_ids": ["line-1"]},
                                     "transactions": [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                       "locator": {"line_ids": [f"line-{index}"]}} for index, (day, text, amount) in enumerate(rows, 2)]},
                                    source_of(doc), "verified")["id"]


def spending(tools):
    row = tools.get_spending(SEPTEMBER)["by_currency"][0]
    return row["spending"]["minor"], row["from_receipts"]["minor"], row["receipts"], row["transactions"]


def test_receipts_count_until_a_reconciled_statement_line_replaces_them(books):
    store, ledger, docs = books
    tools, reconciler = FinanceTools(store), Reconciler(store)
    receipt(ledger, docs["cafe.png"], "Cafe One", "2026-09-10", 1200, "dining")
    receipt(ledger, docs["grocer.png"], "Green Grocer", "2026-09-12", 5000, "groceries")
    receipt(ledger, docs["diner.png"], "Night Diner", "2026-09-14", 3000, status="needs_review")  # Not approved: never counts.
    assert spending(tools) == (6200, 6200, 2, 0)

    statement_id = statement(ledger, docs["statement.pdf"], [("2026-09-10", "CAFE ONE", -1200), ("2026-09-20", "BOOKSHOP", -800)])
    # Recorded but not reconciled: its lines neither count nor match, so nothing is counted twice.
    assert spending(tools) == (6200, 6200, 2, 0)
    assert reconciler.run("extraction")["receipt_links"] == 0
    assert tools.get_spending(SEPTEMBER)["pending_review"][0]["transactions"] == 2
    [waiting] = reconciler.awaiting()
    assert (waiting["id"], waiting["statement_type"], waiting["lines"], waiting["receipts"]) == (statement_id, "credit_card", 2, 3)

    result = reconciler.reconcile_statement(statement_id)
    assert (result["charges"], result["matched_receipts"], result["charges_without_receipt"], result["questions"]) == (2, 1, 1, 0)
    assert reconciler.awaiting() == []
    # The cafe line replaces its receipt; the grocer receipt still counts on its own; the bookshop line counts.
    assert spending(tools) == (1200 + 800 + 5000, 5000, 1, 2)
    # The matched line takes its receipt's category; the category totals include the grocer receipt.
    categories = {row["category"]: row["spending"]["minor"] for row in tools.get_spending_by_category(SEPTEMBER)["categories"]}
    assert categories == {"dining": 1200, "groceries": 5000, "uncategorized": 800}
    assert [row["description_raw"] for row in tools.get_transactions(TransactionsInput(category="dining"))["transactions"]] == ["CAFE ONE"]
    assert_ledger_healthy(store)


def test_a_larger_same_merchant_charge_is_asked_about_not_linked_or_double_counted(books):
    store, ledger, docs = books
    reconciler = Reconciler(store)
    receipt(ledger, docs["diner.png"], "Night Diner", "2026-09-14", 3000, "dining")  # Printed before the tip.
    statement_id = statement(ledger, docs["statement.pdf"], [("2026-09-15", "NIGHT DINER 042", -3600), ("2026-09-15", "FUEL STOP", -3500)])
    result = reconciler.reconcile_statement(statement_id)
    assert (result["matched_receipts"], result["questions"]) == (0, 1)
    with store.connection() as db:
        issue = db.execute("SELECT * FROM reconciliation_issues WHERE issue_type='ambiguous_receipt_match' AND status='open'").fetchone()
        diner = db.execute("SELECT id FROM transactions WHERE description_raw='NIGHT DINER 042'").fetchone()[0]
    assert diner in json.loads(issue["detail_json"])["candidate_transaction_ids"]
    reconciler.resolve_issue(issue["id"], diner)
    link = ledger.record("receipt", issue["record_id"])["links"][0]
    assert (link["review_status"], link["match_signals"]) == ("verified", ["near_amount", "date", "merchant", "user_choice"])
    # Linked: only the charge with the tip counts.
    assert FinanceTools(store).get_spending(SEPTEMBER)["by_currency"][0]["spending"]["minor"] == 3600 + 3500
    assert_ledger_healthy(store)


def test_receipt_category_is_a_correction_kept_through_re_extraction(books):
    store, ledger, docs = books
    receipt_id = receipt(ledger, docs["cafe.png"], "Cafe One", "2026-09-10", 1200, "clothing")
    # Utilities and rent are bills, paid by card or bank; not a receipt category. Shopping was retired for finer categories.
    for unlisted in ("coffee", "utilities", "shopping"):
        with pytest.raises(ValueError, match="listed categories"):
            ledger.correct("receipt", receipt_id, {"category": unlisted})
    assert ledger.correct("receipt", receipt_id, {"category": "Dining"})["category"] == "dining"
    receipt(ledger, docs["cafe.png"], "Cafe One", "2026-09-10", 1200, "clothing")  # Extracted again with the model's suggestion.
    assert ledger.record("receipt", receipt_id)["category"] == "dining"
    receipt(ledger, docs["grocer.png"], "Green Grocer", "2026-09-12", 5000)
    for name in ("cafe.png", "grocer.png"):  # The Receipts folder's subfolders count the documents filed there.
        store.library_action(docs[name]["id"], docs[name]["current_hash"], "move", "Receipts")
    folders = store.folders()["receipt_categories"]
    assert [row["category"] for row in folders] == [*RECEIPT_CATEGORIES, "uncategorized"] and len(RECEIPT_CATEGORIES) == 19
    assert {"furniture & decor", "household supplies", "home improvement", "pets", "kids & baby", "gifts & donations"} <= set(RECEIPT_CATEGORIES)
    assert {row["category"]: row["count"] for row in folders if row["count"]} == {"dining": 1, "uncategorized": 1}
    assert [doc["id"] for doc in store.documents(folder="Receipts", category="dining")["items"]] == [docs["cafe.png"]["id"]]
    with pytest.raises(ValueError, match="Unknown receipt category"):
        store.documents(category="coffee")


def test_statement_prompt_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "prompt-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.headers.update({"Authorization": "Bearer prompt-token"})
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        store = app.state.manager.store
        inbox_scan(store, {"statement.pdf": b"synthetic statement"})
        statement_id = statement(Ledger(store), documents_by_name(store)["statement.pdf"], [("2026-09-10", "CAFE ONE", -1200)])
        [waiting] = client.get("/api/finance/statements/awaiting-reconciliation").json()
        assert (waiting["id"], waiting["statement_type"], waiting["lines"]) == (statement_id, "credit_card", 1)
        result = client.post(f"/api/finance/statements/{statement_id}/reconcile").json()
        assert (result["charges"], result["matched_receipts"], result["charges_without_receipt"]) == (1, 0, 1)
        assert client.get("/api/finance/statements/awaiting-reconciliation").json() == []
        assert client.post("/api/finance/statements/9999/reconcile").status_code == 400
        assert client.get("/api/documents", params={"category": "coffee"}).status_code == 400
        assert [row["category"] for row in client.get("/api/folders").json()["receipt_categories"]][:2] == ["groceries", "dining"]


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_prompts_to_reconcile_and_lists_receipt_subfolders(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "prompt-browser", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    shots = os.environ.get("RECONCILE_SCREENSHOTS")
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        store, ledger = manager.store, manager.ledger
        inbox_scan(store, {"statement.pdf": MINIMAL_PDF, "cafe.png": b"synthetic cafe receipt", "grocer.png": b"synthetic grocer receipt"})
        docs = documents_by_name(store)
        receipt(ledger, docs["cafe.png"], "Cafe One", "2026-09-10", 1200, "dining")
        receipt(ledger, docs["grocer.png"], "Green Grocer", "2026-09-12", 5000, "groceries")
        for name in ("cafe.png", "grocer.png"):
            store.library_action(docs[name]["id"], docs[name]["current_hash"], "move", "Receipts")
        statement(ledger, docs["statement.pdf"], [("2026-09-10", "CAFE ONE", -1200), ("2026-09-20", "BOOKSHOP", -800)])
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=prompt-browser")
            prompt = page.locator("#reconcile-prompt")
            playwright.expect(prompt).to_contain_text("Credit card statement recorded")
            playwright.expect(prompt).to_contain_text("Begin reconciling receipts?")
            if shots:
                page.screenshot(path=os.path.join(shots, "1-prompt.png"))
            prompt.get_by_role("button", name="No", exact=True).click()
            playwright.expect(prompt).to_contain_text("waiting to be reconciled")
            prompt.get_by_role("button", name="Reconcile now").click()
            playwright.expect(prompt).to_contain_text("1 of 2 charges matched to your receipts")
            if shots:
                page.screenshot(path=os.path.join(shots, "2-result.png"))
            # Receipts live in the money store, not in Documents.
            page.locator("#nav-documents").click()
            playwright.expect(page.locator('[data-folder-group="Receipts"]')).to_have_count(0)
            page.locator("#nav-receipts").click()
            playwright.expect(page.locator("#library-title")).to_have_text("Receipts & statements")
            group = page.locator('[data-folder-group="Receipts"]')
            playwright.expect(group).to_have_attribute("aria-expanded", "false")
            playwright.expect(page.locator('.folder-link[data-category="dining"]')).to_have_count(0)
            group.click()
            playwright.expect(group).to_have_attribute("aria-expanded", "true")
            dining = page.locator('.folder-link[data-category="dining"]')
            playwright.expect(dining).to_contain_text("1")
            dining.click()
            playwright.expect(page.locator("#folder-breadcrumb")).to_have_text("Receipts › Dining")
            playwright.expect(page.locator("#documents tr")).to_have_count(1)
            if shots:
                page.screenshot(path=os.path.join(shots, "3-subfolders.png"))
            page.locator('.folder-link[data-folder="Receipts"]').click()  # "All receipts".
            playwright.expect(page.locator("#documents tr")).to_have_count(2)
            group.click()
            playwright.expect(page.locator('.folder-link[data-category="dining"]')).to_have_count(0)
            # A PDF opens in an embedded viewer. A read PDF loads the viewer twice (the document, then its reading's
            # preview); neither load may add a history entry, so one Back returns to the list.
            pdf = docs["statement.pdf"]
            page.locator("#nav-documents").click()  # The statement was never recorded, so it waits in the Inbox.
            page.locator('.folder-link[data-folder="all"]').click()
            page.evaluate(f"location.hash = '#/documents/{pdf['id']}'")
            playwright.expect(page.locator("#receipt-pdf")).to_be_visible()
            page.evaluate(f"imageForReceipt('/api/documents/{pdf['id']}/preview?blob_hash={pdf['current_hash']}', receipt)")
            page.wait_for_timeout(500)  # Let the viewer finish loading.
            page.locator("#close-receipt").click()
            playwright.expect(page.locator("#library-panel")).to_be_visible()
            # A preview that fails is said beside the image, and the rest of the page still loads (never stuck on "Loading").
            page.route("**/preview*", lambda route: route.fulfill(status=500, content_type="application/json", body='{"detail": "Synthetic preview failure."}'))
            page.evaluate(f"location.hash = '#/documents/{pdf['id']}'")
            playwright.expect(page.locator("#receipt-preview-error")).to_contain_text("Synthetic preview failure.")
            playwright.expect(page.locator("#receipt-status")).not_to_contain_text("Loading the preserved document")
            page.unroute("**/preview*")
            assert not failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
