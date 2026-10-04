"""Opt-in browser test for searching document text (docs/documents.md "Searching document text"): RUN_BROWSER_TESTS=1, Edge + Playwright."""

import json
import os
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn

from home_manager.app.api import create_app
from home_manager.library import text_index
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store, now
from test_managed_library import scan
from test_text_index import LEASE, pdf_lines


def saved_lease(root):
    """A library holding one PDF whose saved reading is a two-page synthetic lease."""
    store = Store(root)
    try:
        (store.library.inbox / "lease.pdf").write_bytes(b"synthetic lease")
        scan(store)
        doc = store.documents()["items"][0]
        lines = pdf_lines(LEASE)
        pages = [{"number": number, "method": "embedded_text", "lines": [line for line in lines if line["id"].startswith(f"page-{number}-")]}
                 for number in (1, 2)]
        result = {"parser_version": "pdf-pages-v1", "input_hash": doc["current_hash"], "transcription_method": "pdf_pages",
                  "pages": pages, "issues": [], "lines": lines}
        with store.connection() as db:
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at,result_json) "
                       "VALUES(?,?,'pdf-pages-v1',?,'succeeded',?,?,?)",
                       ("f" * 32, doc["current_hash"], json.dumps({"clockwise_rotation": 0}), now(), now(), json.dumps(result)))
        text_index.index_quietly(store, "f" * 32)
    finally:
        store.close()


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_search_shows_words_from_the_text_and_opens_the_document_at_them(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    saved_lease(tmp_path / "managed")
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
        request = urllib.request.Request(f"http://127.0.0.1:{port}/api/settings", method="PUT",
                                         data=json.dumps({"managed_directory": str(tmp_path / "managed")}).encode(),
                                         headers={"Authorization": "Bearer browser-test-token", "Content-Type": "application/json"})
        urllib.request.urlopen(request, timeout=10).close()
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 768})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=browser-test-token")
            page.goto(f"http://127.0.0.1:{port}/#/search?q=early%20termination")
            snippet = page.locator("#search-results .search-snippet").first
            playwright.expect(snippet).to_contain_text("TERMINATION")
            assert snippet.locator("mark").count() >= 1
            # The Documents list shows the same match under the name.
            page.goto(f"http://127.0.0.1:{port}/#/documents?q=renewal")
            playwright.expect(page.locator("#documents .search-snippet")).to_contain_text("Renewal")
            page.goto(f"http://127.0.0.1:{port}/#/search?q=early%20termination")
            page.locator("#search-results a[href*='lines=']").first.click()
            playwright.expect(page.locator("#document-page")).to_be_visible()
            selected = "() => { const f = document.getElementById('receipt-text'); return f.value.slice(f.selectionStart, f.selectionEnd); }"
            playwright.expect(page.locator("#receipt-text")).to_be_visible()
            for _ in range(50):
                if page.evaluate(selected):
                    break
                time.sleep(.1)
            assert page.evaluate(selected) == "EARLY TERMINATION"
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                page.goto(f"http://127.0.0.1:{port}/#/search?q=deposit")
                playwright.expect(page.locator("#search-results .search-snippet").first).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert failures == []
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
