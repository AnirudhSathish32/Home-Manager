"""The browser steps of the pay stub table engine (specs/pdf-table-engine-paystubs/test-contract.md): SC-71 (the document page's Tables tab shows what the
engine read, its guess beside its table, no outside resource), SC-54 step 4 (a wrapped label's source lights both lines' words) and SC-61 b1's guess
note shown under the pay stub's fields, and SC-74 step 2 (the split panel of a file of several stubs). Opt-in (RUN_BROWSER_TESTS=1), synthetic data only, following tests/test_table_engine_browser.py: each stub is
captured, read and extracted in the served library through the real services with the local model stub (`STUB-PS-SWAPPED`).
"""
import os

import pytest

from home_manager.documents.receipt_service import ReceiptService
import paystub_engine_fixtures as pf
from test_paystub_engine_record import B1_SUMMARY, PS_CLASSES, Run
from test_paystub_split import THREE, Stubs, mini_file
from test_pdf import make_pdf
from test_statement_accounts_browser import open_page
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
B1_CLASSES = [("Regular", "earnings", "regular_pay", "Regular"), ("Relocation Bonus", "earnings", "bonus", "Relocation Bonus")]


def record_stub(manager, local_model, pages, name, classes=PS_CLASSES, summary=None):
    """The stub captured and read by the real reader in the served library, then extracted and recorded with the swapped-amount model double."""
    make_pdf(manager.store.library.inbox / name, pages)
    manager.start_inbox()
    manager.future.result(timeout=30)
    [doc] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name)]
    with manager.store.connection() as db:
        parse_id = db.execute("SELECT id FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') ORDER BY created_at DESC LIMIT 1",
                              (doc["current_hash"],)).fetchone()[0]
    run = Run(manager.store, ReceiptService(manager.store), local_model, parse_id, doc)
    run.stub(classes, summary)
    run.extract()
    return doc, run


def watch(page, base):
    """Page errors, Content Security Policy violations and every request that isn't to the app itself."""
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.on("console", lambda message: failures.append(message.text) if "Content Security Policy" in message.text else None)
    page.on("request", lambda request: failures.append(f"outside request: {request.url}")
            if not request.url.startswith((base, "blob:", "data:")) else None)
    return failures


def open_tables(page, expect):
    page.locator("#doc2-viewer").get_by_role("tab", name="Tables").click()
    panel = page.locator("#doc2-viewer .sv-tables")
    expect(panel).to_be_visible()
    return panel


@browser_test
def test_sc71_the_tables_tab_shows_the_engines_table_roles_cells_and_guess(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "paystub-engine-sc71"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        ps_doc, ps = record_stub(manager, local_model, pf.ps_pages(), "ps.pdf")
        b1_doc, b1 = record_stub(manager, local_model, pf.b1_pages(), "b1.pdf", B1_CLASSES, B1_SUMMARY)
        browser, page, _ = open_page(driver, base, token, f"documents/{ps_doc['id']}")
        failures = watch(page, base)  # Watching from a reload, so the page's own loads count.
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#doc2-panel-record")).to_contain_text("SYNTH PAYROLL CO", timeout=15000)
        # Step 1: one table, from the engine, with its columns' roles and the ten printed rows.
        panel = open_tables(page, expect)
        expect(panel.locator("table.sv-table")).to_have_count(1)
        table = panel.locator("table.sv-table")
        expect(table.locator("caption")).to_have_text("Page 1 · Table 1 · Read from the printed columns")
        assert table.locator("thead th .sv-role").all_text_contents() == ["Hours", "Rate", "This period", "Year to date"]
        assert table.locator("thead th[data-role]").evaluate_all("nodes => nodes.map(node => node.dataset.role)") == ["hours", "rate", "current", "ytd"]
        expect(table.locator("tbody tr")).to_have_count(10)
        assert table.locator("tbody tr.muted").evaluate_all("rows => rows.map(row => row.firstElementChild.textContent)") == [
            "Gross Pay", "Total Taxes", "Total Pre-Tax Deductions", "Net Pay"]
        assert table.locator("tbody tr").evaluate_all("rows => rows.map(row => row.firstElementChild.textContent)") == [row[0] for row in pf.PS_ROWS]
        # Step 4 (amounts): every figure shown is the server's text from the run's saved result.
        served_quotes = [cell["quote"] for row in ps.run["result"]["pay_tables"][0]["rows"] for cell in row["cells"] if cell["quote"]]
        shown = table.locator("tbody td").evaluate_all("cells => cells.map(cell => cell.textContent).filter(text => text)")
        assert [text for text in shown if text != "Source"] == served_quotes
        # Step 2: choosing 2,500.00 lights that word on page 1.
        table.get_by_role("button", name="Show 2,500.00 on PDF page 1").click()
        viewer = page.locator("#doc2-viewer")
        expect(viewer.locator(".sv-overlay polygon.selected")).to_have_count(1, timeout=15000)
        assert viewer.locator(".sv-overlay polygon.selected title").all_text_contents() == ["2,500.00"]
        expect(viewer.locator(".sv-page select")).to_have_count(1)
        # Step 3: the guess about B1's columns is shown beside its table, in the note's words.
        page.goto(f"{base}/#/documents/{b1_doc['id']}")
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#doc2-panel-record")).to_contain_text("SYNTH PAYROLL CO", timeout=15000)
        panel = open_tables(page, expect)
        [guess] = b1.run["result"]["pay_tables"][0]["guesses"]
        assert "left column" in guess
        expect(panel.locator(".sv-guesses li")).to_have_text([guess])
        # SC-61 b1: the same note shows under the pay stub's fields.
        expect(page.locator("#doc2-panel-record .doc2-notes")).to_contain_text(guess)
        assert failures == [], failures
        browser.close()


@browser_test
def test_sc54_step_4_a_wrapped_labels_source_lights_both_lines(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "paystub-engine-sc54"
    classes = [("Federal Income Tax Withholding", *rest) if description == "Federal Income Tax" else (description, *rest)
               for description, *rest in [(c[0], c[1], c[2], "Federal Income" if c[0] == "Federal Income Tax" else c[3]) for c in PS_CLASSES]]
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, run = record_stub(manager, local_model, pf.ps_wrap_pages(), "wrap.pdf", classes)
        wanted = [run.line("Federal Income").id, run.line("Tax Withholding").id]
        printed = sorted(word for line in run.lines if line.id in wanted for word in line.text.split() if word != "|")  # Evidence lines join a row's cells with " | ".
        assert printed == sorted(["Federal", "Income", "Tax", "Withholding", "295.63", "3,698.75"])
        browser, page, failures = open_page(driver, base, token, f"documents/{doc['id']}")
        record = page.locator("#doc2-panel-record")
        expect(record).to_contain_text("Federal Income Tax Withholding", timeout=15000)
        row = record.locator("tr[data-lines]", has_text="Federal Income Tax Withholding")
        assert row.get_attribute("data-lines").split() == wanted
        row.get_by_role("button", name="Find this row in the transcription").click()
        viewer = page.locator("#doc2-viewer")
        expect(viewer.locator(".sv-overlay polygon.selected").first).to_be_attached(timeout=15000)
        assert sorted(viewer.locator(".sv-overlay polygon.selected title").all_text_contents()) == printed
        # The line's this-period value lights its own word (FR-66).
        row.get_by_role("button", name="Find Federal Income Tax Withholding this period on the PDF").click()
        expect(viewer.locator(".sv-overlay polygon.selected")).to_have_count(1, timeout=15000)
        assert viewer.locator(".sv-overlay polygon.selected title").all_text_contents() == ["295.63"]
        assert not failures, failures
        browser.close()


@browser_test
def test_sc74_step_2_the_split_panel_names_the_pay_stubs_and_warns_of_no_review(tmp_path, local_model):
    """The document page of a three-stub file (SC-72 a): "This file holds 3 pay stubs", a chip per stub with employer, pay date and net pay, Confirm
    split, Merge with next and Split here, and no warning that the stubs wait in To check (FR-82)."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "paystub-split-sc74"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        name = "three.pdf"
        make_pdf(manager.store.library.inbox / name, mini_file(*THREE))
        manager.start_inbox()
        manager.future.result(timeout=30)
        [doc] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name)]
        with manager.store.connection() as db:
            parse_id = db.execute("SELECT id FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') ORDER BY created_at DESC LIMIT 1",
                                  (doc["current_hash"],)).fetchone()[0]
        run = Stubs(manager.store, ReceiptService(manager.store), local_model, parse_id, doc)
        run.answer(THREE)
        run.extract()
        browser, page, _ = open_page(driver, base, token, f"documents/{doc['id']}")
        failures = watch(page, base)
        page.reload()
        page.wait_for_load_state("networkidle")
        panel = page.locator("#doc2-panel-record .split-panel")
        expect(panel.get_by_role("heading", name="This file holds 3 pay stubs")).to_be_visible(timeout=15000)
        chips = panel.locator(".filter-chip")
        expect(chips).to_have_count(3)
        for chip, (date, _) in zip(chips.all(), THREE):
            expect(chip).to_contain_text("SYNTH PAYROLL CO")
            expect(chip).to_contain_text("1,800.00 USD")
            assert date[:4] in chip.inner_text()
        for label in ("Confirm split", "Merge with next"):
            expect(panel.get_by_role("button", name=label)).to_be_visible()
        expect(panel.get_by_role("button", name="Split here")).to_be_visible()
        expect(panel).not_to_contain_text("To check")
        expect(panel).not_to_contain_text("receipt")
        assert failures == [], failures
        browser.close()
