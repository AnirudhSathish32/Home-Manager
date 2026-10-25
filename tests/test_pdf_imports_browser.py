"""PDF transaction imports in the browser (specs/account-import-pdf/test-contract.md): synthetic PDFs and data only."""
import json
import os
from urllib.parse import quote

import httpx
import pytest

import pdf_import_fixtures as fx
from test_pdf import make_pdf
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
SPENDING = "spending.net?start=2026-08-01&end=2026-08-31"


def import_pdf(manager, base, token, name, pages, **body):
    """Put a synthetic PDF in the Inbox, capture and read it, and import it into a new checking account through the real routes."""
    make_pdf(manager.store.library.inbox / name, pages)
    manager.start_inbox()
    manager.future.result(timeout=30)
    [doc] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name)]
    with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}) as client:
        account = client.post("/api/finance/accounts", json={"institution": "FIRST LOCAL BANK", "account_type": "checking", "currency": "USD", "last_four": "4821"})
        assert account.status_code == 201, account.text
        request = {"expected_hash": doc["current_hash"], "account_id": account.json()["id"], **body}
        preview = client.post(f"/api/documents/{doc['id']}/transaction-import/preview", json=request)
        assert preview.status_code == 200, preview.text
        done = client.post(f"/api/documents/{doc['id']}/transaction-imports", json={**request, "reading_id": preview.json()["reading_id"]})
        assert done.status_code == 201, done.text
        trace = client.get("/api/traces/" + quote(SPENDING, safe=""))
        assert trace.status_code == 200, trace.text
    return doc, trace.json()


def locators(manager):
    with manager.store.connection() as db:
        return [json.loads(row[0]) for row in db.execute("SELECT locator_json FROM financial_evidence_links WHERE record_type='transaction' ORDER BY id")]


def open_breakdown(page, base, token):
    page.goto(f"{base}/#token={token}")
    page.wait_for_selector("#today-panel:not([hidden])")
    page.evaluate("ref => openBreakdown(ref)", SPENDING)
    page.wait_for_selector("#breakdown-body .input-row")


@browser_test
def test_sc22_the_source_badge_names_the_page_and_the_page_it_continued_from_and_links_to_the_cited_lines(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "pdf-source-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, trace = import_pdf(manager, base, token, "K.pdf", fx.k_pages())
        # The trace carries only the light provenance: the badge gets the page from /api/provenance.
        assert all(set(item["provenance"]) == {"kind", "record"} for item in trace["inputs"])
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        open_breakdown(page, base, token)
        rows = page.locator("#breakdown-body .input-row")
        # k6 is on page 2 of K, in the table that continues page 1's: the badge says so, and its link opens the page with its lines.
        fee = rows.filter(has_text="MONTHLY SERVICE FEE")
        expect(fee.locator(".status-badge")).to_have_text("Imported · K.pdf page 2 · continued from page 1")
        link = fee.get_by_role("link", name="Open source")
        lines = [line for locator in locators(manager) if locator["page"] == 2 and locator["row"] == 2 for line in locator["line_ids"]]
        assert lines and all(line.startswith("page-2-layout-line-") for line in lines)
        expect(link).to_have_attribute("href", f"#/documents/{doc['id']}?lines={','.join(lines)}")
        # k1 is on page 1 and is not continued from anywhere.
        coffee = rows.filter(has_text="COFFEE SHOP").first
        expect(coffee.locator(".status-badge")).to_have_text("Imported · K.pdf page 1")
        assert not failures
        link.click()
        page.wait_for_url(f"**/#/documents/{doc['id']}?lines=*")
        # The page-2 preview opens with the row's words lit (its lines: the row's text and the balance beside it).
        viewer = page.locator("#doc2-viewer")
        expect(viewer.locator(".sv-page select")).to_have_value("2", timeout=15000)
        expect(viewer.locator(".sv-overlay polygon.selected").first).to_be_attached(timeout=15000)
        lit = viewer.locator(".sv-overlay polygon.selected title").all_text_contents()
        assert {"MONTHLY", "SERVICE", "FEE", "5.00"} <= set(lit), lit
        assert not failures
        browser.close()


@browser_test
def test_sc22_a_below_table_row_links_to_its_lines_and_a_csv_badge_is_unchanged(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "pdf-source-v-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, _ = import_pdf(manager, base, token, "v.pdf", fx.v_pages(), date_format="MM/DD/YYYY")
        [native, below] = locators(manager)
        assert "cell_ids" in native and "cell_ids" not in below and below["word_ids"] and below["row"] == 5
        # A CSV row of the same account: its badge and links stay as they were.
        (manager.store.library.inbox / "bank.csv").write_bytes(b"Date,Description,Amount\n2026-08-10,CSV COFFEE,-4.50\n")
        manager.start_inbox()
        manager.future.result(timeout=30)
        [csv] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith("bank.csv")]
        with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}) as client:
            done = client.post(f"/api/documents/{csv['id']}/transaction-imports", json={
                "expected_hash": csv["current_hash"], "account_id": 1, "mapping": {"date": "Date", "description": "Description", "amount": "Amount"}})
            assert done.status_code == 201, done.text
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        open_breakdown(page, base, token)
        rows = page.locator("#breakdown-body .input-row")
        expect(rows).to_have_count(3)
        csv_row = rows.filter(has_text="CSV COFFEE")
        expect(csv_row.locator(".status-badge")).to_have_text("Imported")
        expect(csv_row.get_by_role("link")).to_have_count(0)
        pdf_rows = rows.filter(has_not_text="CSV COFFEE")
        expect(pdf_rows.locator(".status-badge")).to_have_text(["Imported · v.pdf page 1", "Imported · v.pdf page 1"])
        hrefs = [pdf_rows.nth(index).get_by_role("link", name="Open source").get_attribute("href") for index in range(2)]
        assert sorted(hrefs) == sorted([f"#/documents/{doc['id']}?lines={','.join(native['cell_ids'])}", f"#/documents/{doc['id']}?lines={','.join(below['line_ids'])}"])
        # The CSV row keeps its row-form text where the server gives one (the badge is unchanged for it).
        assert page.evaluate("""() => provenanceBadge({kind: "imported", import: {file: "export.csv", row: 14}}).textContent""") == "Imported · export.csv row 14"
        assert not failures
        browser.close()


def put(manager, files):
    """Put synthetic files in the Inbox and capture them (a native PDF is read on the way in; a scan is not, with no model)."""
    for name, content in files:
        path = manager.store.library.inbox / name
        if isinstance(content, list):
            make_pdf(path, content)
        else:
            path.write_bytes(content)
    manager.start_inbox()
    manager.future.result(timeout=600)


def shop_pages(number):
    return [fx.page([fx.HEADING5, ("08/03/2026", f"SHOP NUMBER {number}", "4.50", "", "1,000.00")], above=fx.K_TEXT, number=1, total=1)]


@browser_test
def test_sc19_the_import_picker_lists_pdfs_with_a_transactions_table_beside_csv_files(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "pdf-picker-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        put(manager, [(f"shop-{number:03d}.pdf", shop_pages(number)) for number in range(250)])  # Added before the CSV.
        put(manager, [("Kc.csv", fx.kc_csv()), ("unread.pdf", fx.m_pages()),
                      ("plain.pdf", [{"items": [fx.footer("A letter about the garden fence, kept with the house papers for later", 700)]}])])
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        picker = page.locator("#money2-import")
        rows = picker.locator("#money2-import-list > li")

        def check_list():
            expect(picker).to_be_visible()
            expect(picker).to_contain_text("PDF")
            expect(rows.filter(has_text="Kc.csv")).to_have_count(1, timeout=30000)  # Not hidden behind 250 PDFs.
            expect(rows).to_have_count(251)
            expect(rows.filter(has_text="Kc.csv").locator(".status-badge")).to_have_text("CSV")
            expect(rows.filter(has_text="shop-000.pdf").locator(".status-badge")).to_have_text("PDF")
            expect(rows.filter(has_text="shop-249.pdf").locator(".status-badge")).to_have_text("PDF")
            expect(rows.filter(has_text="unread.pdf")).to_have_count(0)
            expect(rows.filter(has_text="plain.pdf")).to_have_count(0)
            expect(rows.locator(".status-badge", has_text="PDF")).to_have_count(250)

        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        page.locator("#tx2-import").click()
        check_list()
        page.locator("#money2-import-close").click()
        expect(picker).to_be_hidden()
        page.goto(f"{base}/#/accounts")
        page.locator("#accounts2-import").click()
        check_list()
        page.locator("#money2-import-close").click()
        # The per-account button: with no account yet, the empty state offers it.
        expect(page.locator("#accounts2-groups").get_by_role("button", name="Import an export")).to_be_visible()
        page.locator("#accounts2-groups").get_by_role("button", name="Import an export").click()
        check_list()
        # A PDF opens the import dialog like a CSV does.
        picker.get_by_role("button", name="Import shop-007.pdf").click()
        expect(page.locator("#import-dialog")).to_be_visible()
        assert not failures


@browser_test
def test_sc19_an_empty_library_names_pdf_csv_and_xlsx_in_the_picker(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "pdf-picker-empty"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        page.locator("#tx2-import").click()
        expect(page.locator("#money2-import-list")).to_contain_text("No bank or card exports waiting")
        for kind in ("PDF", "CSV", "XLSX"):
            expect(page.locator("#money2-import-list")).to_contain_text(kind)
