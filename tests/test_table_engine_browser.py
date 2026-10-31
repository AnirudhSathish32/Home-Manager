"""The browser step of the table engine's SC-03 (specs/pdf-table-engine/test-contract.md): a wrapped row's source lights all its lines. Opt-in
(RUN_BROWSER_TESTS=1), synthetic data only, following tests/test_statement_accounts_browser.py: WR is captured, read and Recorded in the served
library with the local model stub, then the browser opens r6's source from the document page.
"""
import json
import os

import pytest

from home_manager.documents.pdf_reader import read_result
from home_manager.documents.receipt_service import ReceiptService
import statement_account_fixtures as sf
import table_engine_fixtures as tf
from test_pdf import make_pdf
from test_statement_accounts_browser import open_page, sql
from test_statement_rebuild import Recorded
from test_table_engine_record import replies
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
R6 = "CARD PURCHASE SYNTH HARDWARE SUPPLY STORE SPRINGFIELD US"


def record_wr(manager, model, name="wr.pdf"):
    """WR captured and read by the real reader, then Recorded through the service: a statement of seven rows from the printed columns."""
    make_pdf(manager.store.library.inbox / name, tf.wr_pages())
    manager.start_inbox()
    manager.future.result(timeout=30)
    [doc] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name)]
    with manager.store.connection() as db:
        parse_id = db.execute("SELECT id FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') ORDER BY created_at DESC LIMIT 1",
                              (doc["current_hash"],)).fetchone()[0]
    service = ReceiptService(manager.store)
    result = read_result(service.get(parse_id)["result"])
    recorded = Recorded(manager.store, service, doc, parse_id, sf.reading_lines(result), model)
    recorded.run(replies("WR"))
    return doc, recorded, result


@browser_test
def test_sc03_step_4_a_wrapped_rows_source_opens_page_1_with_all_three_lines_lit(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "table-engine-sc03"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded, result = record_wr(manager, local_model)
        [(locator,)] = sql(manager, "SELECT e.locator_json FROM transactions t JOIN financial_evidence_links e ON e.record_type='transaction' AND e.record_id=t.id "
                                    "WHERE t.description_raw=?", R6)
        located = json.loads(locator)
        assert located["rebuilt"] and len(located["line_ids"]) == 3 and located["word_ids"]
        layout = result.pages[0].layout
        printed = [word.text for line in layout.lines if line.id in located["line_ids"] for word in layout.words if word.id in line.word_ids]
        assert len(printed) == 11
        browser, page, failures = open_page(driver, base, token, f"documents/{doc['id']}")
        record = page.locator("#doc2-panel-record")
        expect(record).to_contain_text("SYNTH WRAP BANK", timeout=15000)
        page.evaluate("""() => { const real = doc2.viewer.highlight; window.lit = [];
          doc2.viewer.highlight = ids => { window.lit.push(ids); return real(ids); }; }""")
        row = record.locator("tbody tr", has=page.locator("td.numeric", has_text="129.99"))
        expect(row).to_have_count(1)
        row.get_by_role("button", name="Find this row in the transcription").click()
        viewer = page.locator("#doc2-viewer")
        expect(viewer.locator(".sv-overlay polygon.selected").first).to_be_attached(timeout=15000)
        # What reaches the source viewer: the row's three lines and every word of them.
        assert page.evaluate("window.lit") == [[*located["line_ids"], *located["word_ids"]]]
        expect(viewer.locator(".sv-page select")).to_have_value("1")
        lit = viewer.locator(".sv-overlay polygon.selected title").all_text_contents()
        assert sorted(lit) == sorted(printed), lit
        assert not failures, failures
        browser.close()
