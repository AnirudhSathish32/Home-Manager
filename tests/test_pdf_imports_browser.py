"""PDF transaction imports in the browser (specs/account-import-pdf/test-contract.md): synthetic PDFs and data only."""
import json
import os
import re
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


NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
ACCOUNTS = {"A": ("FIRST LOCAL BANK", "checking", "4821"), "C": ("SYNTH CARD SERVICES", "credit_card", "7700"), "L": ("SYNTH LENDER", "loan", "3333")}
LEDGER_TABLES = ("accounts", "transactions", "financial_evidence_links", "transaction_imports", "statements")


def add_accounts(base, token, keys):
    """Create the contract's accounts (A checking …4821, C card …7700, L loan …3333) through the real route; returns their ids."""
    with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}) as client:
        ids = {}
        for key in keys:
            institution, kind, last_four = ACCOUNTS[key]
            response = client.post("/api/finance/accounts", json={"institution": institution, "account_type": kind, "currency": "USD", "last_four": last_four})
            assert response.status_code == 201, response.text
            ids[key] = response.json()["id"]
    return ids


def library_row(base, token, manager, name):
    [doc] = [item for item in manager.store.documents(limit=1000)["items"] if item["relative_path"].endswith(name)]
    with httpx.Client(base_url=base, headers={"Authorization": f"Bearer {token}"}) as client:
        return client.get(f"/api/documents/{doc['id']}").json()


def ledger_counts(manager):
    with manager.store.connection() as db:
        return {table: db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in LEDGER_TABLES}


def finished_readings(manager):
    with manager.store.connection() as db:
        return db.execute("SELECT COUNT(*) FROM parse_runs WHERE status IN ('succeeded','partial')").fetchone()[0]


@browser_test
def test_sc21_import_on_an_unread_pdf_asks_for_a_reading_and_previews_in_place(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "pdf-unread-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        # Automatic reading after capture is a setting; with it off (and no model) a native PDF waits unread.
        manager.vision = manager.vision.model_copy(update={"organize_after_scan": False})
        ids = add_accounts(base, token, "A")
        put(manager, [("Ku.pdf", fx.k_pages()), ("Kmixed.pdf", fx.m_pages())])
        assert finished_readings(manager) == 0
        before = ledger_counts(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        page.wait_for_selector("#tx2-import")
        dialog = page.locator("#import-dialog")
        # The dialog opened straight on the library row: rows no longer offer Import before recording, but the dialog still reads first.
        page.evaluate("""doc => { window.closes = 0; document.getElementById("import-dialog").addEventListener("close", () => { window.closes += 1; }); openImport(doc); }""",
                      library_row(base, token, manager, "Kmixed.pdf"))
        expect(dialog).to_be_visible()
        expect(dialog.get_by_text("Read this document first")).to_be_visible()
        read = dialog.get_by_role("button", name="Read", exact=True)
        expect(read).to_be_visible()
        expect(dialog.locator("#confirm-import")).to_be_hidden()
        assert ledger_counts(manager) == before and finished_readings(manager) == 0
        # 21-a: a scanned page needs a model; the dialog says what it says today, and nothing is written.
        read.click()
        expect(dialog.locator("#import-status")).to_contain_text("Configure a local vision model", timeout=60000)
        expect(read).to_be_enabled()
        assert ledger_counts(manager) == before and finished_readings(manager) == 0
        page.locator("#close-import").click()
        # Ku is fully native: Read, then the preview in the same dialog, without reopening it.
        page.evaluate("""doc => { window.closes = 0; openImport(doc); }""", library_row(base, token, manager, "Ku.pdf"))
        expect(dialog.get_by_text("Read this document first")).to_be_visible()
        assert ledger_counts(manager) == before
        dialog.get_by_role("button", name="Read", exact=True).click()
        rows = dialog.locator("#import-pdf-rows tr")
        expect(rows).to_have_count(9, timeout=60000)
        expect(dialog.get_by_text("Read this document first")).to_be_hidden()
        expect(dialog.locator("#import-account")).to_have_value(str(ids["A"]))
        expect(dialog.locator("#import-account-note")).to_contain_text("4821")
        expect(dialog.locator("#confirm-import")).to_be_enabled()
        assert page.evaluate("window.closes") == 0
        expect(dialog).to_be_visible()
        assert finished_readings(manager) == 1 and ledger_counts(manager) == before  # A reading exists; the ledger tables did not move.
        # Closing without importing writes nothing.
        page.locator("#close-import").click()
        expect(dialog).to_be_hidden()
        assert ledger_counts(manager) == before and ledger_counts(manager)["transactions"] == 0
        assert not failures
        browser.close()


def tab_walk(page, stop=None, limit=60):
    """What each Tab press reaches (a row or table key, else the element id), until `stop` or the limit."""
    seen = []
    for _ in range(limit):
        page.keyboard.press("Tab")
        reached = page.evaluate("document.activeElement.dataset.key || document.activeElement.id")
        seen.append(reached)
        if reached == stop:
            break
    return seen


def choose_in_dialog(page, picker_name):
    """Transactions → Import an export → a file, by keyboard only (no pointer calls)."""
    page.locator("#tx2-import").focus()
    page.keyboard.press("Enter")
    page.get_by_role("button", name=f"Import {picker_name}").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("#import-dialog[open]")


@browser_test
def test_sc23_the_pdf_dialog_works_by_keyboard_and_announces_its_summary(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)
    token = "pdf-dialog-keyboard"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        ids = add_accounts(base, token, "ACL")
        put(manager, [("K.pdf", fx.k_pages()), ("R.pdf", fx.r_pages())])
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.evaluate("id => localStorage.setItem('home-manager-import-account', String(id))", ids["C"])
        page.goto(f"{base}/#/transactions")  # The one navigation; everything after it is the keyboard.
        page.wait_for_selector("#tx2-import")
        dialog = page.locator("#import-dialog")
        status, account = dialog.locator("#import-status"), dialog.locator("#import-account")
        # 1. K opens in PDF mode, with A matched and not the remembered C.
        choose_in_dialog(page, "K.pdf")
        rows = dialog.locator("#import-pdf-rows tr")
        expect(rows).to_have_count(9)
        expect(dialog.locator("#import-table-list input[type=checkbox]")).to_have_count(1)
        expect(rows.nth(0).locator("td").first).to_have_text("1")
        expect(rows.nth(8).locator("td").first).to_have_text("3")
        row_keys = [box.get_attribute("data-key").removeprefix("row:") for box in rows.locator("input[type=checkbox]").all()]
        for hidden in ("#import-csv-map", "#import-csv-wrap", "#import-map-date", "#import-csv-sign"):
            expect(dialog.locator(hidden)).to_be_hidden()
        expect(account).to_have_value(str(ids["A"]))
        expect(dialog.locator("#import-account-note")).to_have_text("Matched …4821 printed on page 1")
        assert page.evaluate("document.getElementById('import-dialog').contains(document.activeElement)")
        assert page.evaluate(NO_OVERFLOW)
        # 2. Tab reaches every control. First with a new account typed (its fields show); then with A, where Import is enabled.
        account.focus()
        page.keyboard.press("ArrowUp")  # Choose… < New account… < A: one step up from A is New account….
        expect(dialog.locator("#import-new-account")).to_be_visible()
        expect(dialog.locator("#import-last-four")).to_have_value("4821")  # Prefilled from the one number the PDF prints.
        expect(status).to_contain_text("9 new")
        walked = tab_walk(page, limit=40)
        assert {"import-account", "import-institution", "import-type", "import-currency", "import-last-four", "preview-import"} <= set(walked), walked
        assert any(key.startswith("table:") for key in walked) and any(key.startswith("row:") for key in walked), walked
        account.focus()
        page.keyboard.press("ArrowDown")
        expect(account).to_have_value(str(ids["A"]))
        expect(dialog.locator("#import-new-account")).to_be_hidden()
        expect(status).to_contain_text("9 new")
        walked = tab_walk(page, stop="confirm-import", limit=40)
        assert walked[-1] == "confirm-import" and any(key.startswith("table:") for key in walked), walked
        assert [key for key in tab_walk(page, limit=9) if key.startswith("row:")] == [f"row:{key}" for key in row_keys], "every row tick is reachable in order"
        # A row's tick is a checkbox: Space leaves the row out, and focus stays on it while the preview redraws.
        first_tick = rows.nth(0).locator("input[type=checkbox]")
        first_tick.focus()
        page.keyboard.press("Space")
        expect(status).to_contain_text("8 new")
        expect(status).to_contain_text("1 left out")
        assert page.evaluate("document.activeElement.dataset.key") == f"row:{row_keys[0]}"
        page.keyboard.press("Space")
        expect(status).to_contain_text("9 new")
        assert page.evaluate("document.activeElement.dataset.key").startswith("row:")
        # 3. Import: the summary lands in the dialog's live region.
        assert dialog.locator("#import-status").get_attribute("aria-live") == "polite" and dialog.locator("#import-status").get_attribute("role") == "status"
        page.locator("#confirm-import").focus()
        page.keyboard.press("Enter")
        expect(status).to_contain_text("Imported 9 new transactions into FIRST LOCAL BANK")
        expect(status).to_contain_text("0 were already recorded")
        assert ledger_counts(manager)["transactions"] == 9
        assert page.evaluate("document.activeElement.id") == "close-import"
        # 4. Closing returns focus to what opened it.
        page.keyboard.press("Enter")
        expect(dialog).to_be_hidden()
        assert page.evaluate("document.activeElement.id") == "tx2-import"
        # 5. R: the card's sign default, a year to choose, and the totals that follow the account.
        choose_in_dialog(page, "R.pdf")
        expect(rows).to_have_count(5)
        expect(account).to_have_value(str(ids["C"]))  # R prints XXXX7700: matched, and the same as the remembered one.
        sign, year = dialog.locator("#import-pdf-sign"), dialog.locator("#import-year")
        expect(sign).to_have_value("positive_is_outflow")
        expect(status).to_contain_text("Choose the year")
        expect(year).to_be_visible()
        expect(dialog.locator("#confirm-import")).to_be_disabled()
        year.focus()
        page.keyboard.type("2025")
        expect(year).to_have_value("2025")
        expect(status).to_contain_text("5 new")
        expect(dialog.locator("#confirm-import")).to_be_enabled()
        expect(status).to_contain_text("New: money out -112.94 USD; money in 269.99 USD")
        assert page.evaluate(NO_OVERFLOW)
        account.focus()
        page.keyboard.press("ArrowUp")  # C → A
        expect(account).to_have_value(str(ids["A"]))
        expect(sign).to_have_value("negative_is_outflow")
        expect(status).to_contain_text("New: money out -269.99 USD; money in 112.94 USD")
        account.focus()
        page.keyboard.press("ArrowDown")
        page.keyboard.press("ArrowDown")  # A → C → L (a loan has no default sign)
        expect(account).to_have_value(str(ids["L"]))
        expect(sign).to_have_value("")
        expect(dialog.locator("#confirm-import")).to_be_disabled()
        expect(status).to_contain_text("Choose whether positive amounts")
        sign.focus()
        page.keyboard.press("ArrowDown")
        expect(sign).to_have_value("negative_is_outflow")
        expect(dialog.locator("#confirm-import")).to_be_enabled()
        # 6. Nothing failed, and nothing overflowed.
        assert page.evaluate(NO_OVERFLOW)
        assert not failures
        browser.close()


@browser_test
def test_the_dialog_creates_a_new_account_with_the_import_request_and_follows_the_table_choice(tmp_path):
    """FR-14 (UI): no account request of its own; the last four is prefilled; FR-28: a table can be left out."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)
    token = "pdf-dialog-new-account"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        put(manager, [("K.pdf", fx.k_pages())])
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures, requests = [], []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.on("request", lambda request: requests.append((request.method, request.url.split(base)[-1], request.post_data)) if request.method == "POST" else None)
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        page.wait_for_selector("#tx2-import")
        dialog = page.locator("#import-dialog")
        status, account = dialog.locator("#import-status"), dialog.locator("#import-account")
        page.locator("#tx2-import").click()
        page.get_by_role("button", name="Import K.pdf").click()
        rows = dialog.locator("#import-pdf-rows tr")
        expect(rows).to_have_count(9)
        # No saved account: nothing chosen, Import disabled, and the dialog says why.
        expect(account).to_have_value("none")
        expect(dialog.locator("#import-account-note")).to_contain_text("No saved account matches")
        expect(dialog.locator("#confirm-import")).to_be_disabled()
        # Leaving the table out leaves no rows to import.
        table = dialog.locator("#import-table-list input[type=checkbox]")
        table.uncheck()
        expect(rows).to_have_count(0)
        expect(status).to_have_text("No rows to import in the selected tables.")
        table.check()
        expect(rows).to_have_count(9)
        # A new account: last four from the PDF, institution typed; Import waits for the institution.
        account.select_option("")
        expect(dialog.locator("#import-last-four")).to_have_value("4821")
        expect(dialog.locator("#confirm-import")).to_be_disabled()
        dialog.locator("#import-institution").fill("FIRST LOCAL BANK")
        expect(dialog.locator("#confirm-import")).to_be_enabled()
        assert ledger_counts(manager)["accounts"] == 0
        dialog.locator("#confirm-import").click()
        expect(status).to_contain_text("Imported 9 new transactions into FIRST LOCAL BANK")
        accounts = [(method, url) for method, url, _ in requests if url.startswith("/api/finance/accounts")]
        assert accounts == [], "the import request creates the account; the dialog sends no request of its own"
        [(_, _, body)] = [item for item in requests if item[1].endswith("/transaction-imports")]
        sent = json.loads(body)
        assert sent["new_account"] == {"institution": "FIRST LOCAL BANK", "account_type": "checking", "currency": "USD", "last_four": "4821"} and "account_id" not in sent
        with manager.store.connection() as db:
            assert [tuple(row) for row in db.execute("SELECT account_last_four FROM accounts")] == [("4821",)]
            assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 9
        assert not failures
        browser.close()


@browser_test
def test_the_dialog_shows_flagged_rows_unticked_and_imports_the_ones_the_user_ticks(tmp_path):
    """FR-09 (UI): a flagged page's rows start unticked, labelled with the reader's reason; FR-06: the date order is a choice."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)
    token = "pdf-dialog-flagged"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        ids = add_accounts(base, token, "A")
        put(manager, [("f.pdf", fx.f_pages())])
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        page.wait_for_selector("#tx2-import")
        dialog = page.locator("#import-dialog")
        status = dialog.locator("#import-status")
        page.locator("#tx2-import").click()
        page.get_by_role("button", name="Import f.pdf").click()
        rows = dialog.locator("#import-pdf-rows tr")
        expect(rows).to_have_count(6)
        # F prints no account number, so nothing is preselected; the user chooses A.
        expect(dialog.locator("#import-account")).to_have_value("none")
        dialog.locator("#import-account").select_option(str(ids["A"]))
        # July dates print no day above 12: the order is a choice, and Import waits for it.
        expect(status).to_have_text("Choose the date order: day first or month first.")
        expect(dialog.locator("#confirm-import")).to_be_disabled()
        dialog.locator("#import-date-format").select_option("MM/DD/YYYY")
        expect(status).to_contain_text("2 new")
        expect(status).to_contain_text("4 left out")
        boxes = rows.locator("input[type=checkbox]")
        assert [box.is_checked() for box in boxes.all()] == [True, True, False, False, False, False]
        for index in (2, 3, 4, 5):
            expect(rows.nth(index)).to_contain_text("Page 2 PDF layout needs review")
        expect(rows.nth(0).locator(".import-row-label")).to_have_count(0)
        boxes.nth(2).check()
        boxes.nth(4).check()
        expect(status).to_contain_text("4 new")
        expect(status).to_contain_text("2 left out")
        dialog.locator("#confirm-import").click()
        expect(status).to_contain_text("Imported 4 new transactions into FIRST LOCAL BANK")
        expect(status).to_contain_text("2 were left out")
        with manager.store.connection() as db:
            assert [row[0] for row in db.execute("SELECT description_raw FROM transactions WHERE account_id=? ORDER BY id", (ids["A"],))] == ["F1", "F2", "F3", "F5"]
        assert not failures
        browser.close()


PRIMARY = re.compile(r"\bprimary\b")


def library_page(page, base):
    # Rows from an earlier visit stay in the DOM until the fresh load redraws the table, so wait for rows it drew.
    page.locator("#rc2-table tbody tr").evaluate_all("rows => rows.forEach(row => { row.dataset.stale = 'true'; })")
    page.goto(f"{base}/#/documents?folder=Inbox")
    page.wait_for_selector("#rc2-table tbody tr:not([data-stale])")


def row_of(page, name):
    return page.locator("#rc2-table tbody tr").filter(has_text=name)


def record_statement(manager, doc, account_id):
    """Record a read PDF as a statement with no rows (so an import still adds all of them), with the extraction run its document page reads."""
    statement = {"statement_type": "bank", "institution": "FIRST LOCAL BANK", "last_four": "4821", "currency": "USD", "period_start": "2026-08-01",
                 "period_end": "2026-08-31", "opening_balance_minor": None, "closing_balance_minor": None, "summary": {}, "issues": [],
                 "locator": {"line_ids": ["line-0"]}, "transactions": []}
    published = manager.ledger.publish_statement(statement, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:test",
                                                             "run_id": "test"}, "proposed")
    with manager.store.connection() as db:
        db.execute("INSERT INTO extraction_runs(id,document_id,parse_run_id,config_json,prompt_version,status,created_at,updated_at,publication_json) "
                   "VALUES('record-k',?,?,'{}','v','succeeded','t','t',?)",
                   (doc["id"], doc["text_run_id"], json.dumps({"record_type": "statement", "id": published["id"], "status": "published", "account_id": account_id})))


def menu_items(row):
    """Open the row's More actions menu and return its items' texts (the menu stays open)."""
    row.locator(".menu-trigger").click()
    return row.get_by_role("menuitem").all_text_contents()


@browser_test
def test_sc20_the_primary_action_follows_the_reading_the_account_match_and_what_the_pdf_is_recorded_as(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "pdf-primary-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        ids = add_accounts(base, token, "A")
        # K matches A and is recorded as a statement. Kn has K's table and no last four, and isn't recorded. Kr has K's table and is
        # recorded as a receipt. Kc is a CSV.
        put(manager, [("K.pdf", fx.k_pages()), ("Kn.pdf", fx.k0_pages()), ("Kr.pdf", fx.k_pages(above=(*fx.K_TEXT, "Copy Kr"))), ("Kc.csv", fx.kc_csv())])
        # Ku is a native PDF that nothing has read: automatic reading after capture is a setting, and it is off for this one.
        manager.vision = manager.vision.model_copy(update={"organize_after_scan": False})
        put(manager, [("Ku.pdf", fx.k_pages(above=(*fx.K_TEXT, "Copy Ku")))])
        docs = {item["relative_path"].rsplit("/", 1)[-1]: item for item in manager.store.documents(limit=1000)["items"]}
        kr = docs["Kr.pdf"]
        manager.ledger.publish_receipt({"merchant": "Corner Shop", "purchase_date": "2026-09-10", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                        "total_minor": 299, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-0"]}, "items": []},
                                       {"document_id": kr["id"], "blob_hash": kr["current_hash"], "source_key": "extraction:test", "run_id": "test"}, "proposed")
        record_statement(manager, docs["K.pdf"], ids["A"])
        assert not docs["Ku.pdf"]["text_run_id"] and docs["K.pdf"]["text_run_id"] and docs["Kn.pdf"]["text_run_id"]
        before = ledger_counts(manager)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        library_page(page, base)
        step = lambda name: row_of(page, name).locator("button.rc2-step")
        # 1. Library rows: a PDF offers Import only once it is recorded.
        expect(step("K.pdf")).to_have_text("Add missed")
        items = menu_items(row_of(page, "K.pdf"))
        assert "Record" not in items and "Add missed transactions" not in items
        page.keyboard.press("Escape")
        expect(step("Kn.pdf")).to_have_text("Record")
        items = menu_items(row_of(page, "Kn.pdf"))
        assert "Add missed transactions" not in items and "Record" not in items
        page.keyboard.press("Escape")
        expect(step("Ku.pdf")).to_have_text("Read")
        assert "Add missed transactions" not in menu_items(row_of(page, "Ku.pdf"))
        page.keyboard.press("Escape")
        expect(step("Kc.csv")).to_have_text("Add missed")
        assert "Import transactions" not in menu_items(row_of(page, "Kc.csv"))
        page.keyboard.press("Escape")
        expect(step("Kr.pdf")).to_have_count(0)
        assert not [text for text in menu_items(row_of(page, "Kr.pdf")) if text in ("Add missed transactions", "Record")]
        page.keyboard.press("Escape")
        assert ledger_counts(manager) == before
        # 2. Document pages.
        def document_page(name):
            page.goto(f"{base}/#/documents/{docs[name]['id']}")
            expect(page.locator("#doc2-steps .doc2-step").first).to_be_visible()
            return page.locator("#doc2-next")
        # On the document page Add missed transactions waits, turned off beside Record it, until the PDF is recorded.
        nxt = document_page("K.pdf")
        expect(nxt.get_by_role("button", name="Add missed transactions")).to_be_enabled()
        expect(nxt.get_by_role("button", name="Add missed transactions")).to_have_class(PRIMARY)
        expect(nxt.get_by_role("button", name="Record it")).to_have_count(0)
        nxt = document_page("Kn.pdf")
        expect(nxt.get_by_role("button", name="Record it")).to_have_class(PRIMARY)
        expect(nxt.get_by_role("button", name="Add missed transactions")).to_be_disabled()
        expect(nxt.get_by_role("button", name="Add missed transactions")).not_to_have_class(PRIMARY)
        nxt = document_page("Ku.pdf")
        expect(nxt.get_by_role("button", name="Read document")).to_have_class(PRIMARY)
        expect(nxt.get_by_role("button", name="Add missed transactions")).to_have_count(0)
        nxt = document_page("Kr.pdf")
        expect(page.locator("#doc2-steps .doc2-step").nth(1)).to_be_visible()
        expect(nxt.get_by_role("button", name="Add missed transactions")).to_have_count(0)
        assert ledger_counts(manager) == before and finished_readings(manager) == 3
        # 3. Add recorded K's missed rows into A from its row; it still offers Add missed, on the row and on its page.
        library_page(page, base)
        dialog = page.locator("#import-dialog")
        step("K.pdf").click()
        expect(dialog.locator("#import-title")).to_have_text("Add transactions the reading missed")
        expect(dialog.locator("#confirm-import")).to_have_text("Add missed transactions")
        expect(dialog.locator("#import-pdf-rows tr")).to_have_count(9)
        expect(dialog.locator("#import-account")).to_have_value(str(ids["A"]))
        dialog.locator("#confirm-import").click()
        expect(dialog.locator("#import-status")).to_contain_text("Imported 9 new transactions", timeout=30000)
        page.locator("#close-import").click()
        with manager.store.connection() as db:
            assert tuple(db.execute("SELECT COUNT(*), COUNT(DISTINCT account_id) FROM transactions").fetchone()) == (9, 1)
        page.reload()
        page.wait_for_selector("#rc2-table tbody tr")
        expect(step("K.pdf")).to_have_text("Add missed")
        nxt = document_page("K.pdf")
        expect(nxt.get_by_role("button", name="Add missed transactions")).to_be_enabled()
        # Kn, Ku, Kc and Kr changed nothing.
        with manager.store.connection() as db:
            assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 9
        assert not failures
        browser.close()


@browser_test
def test_a_second_preview_shows_the_already_recorded_totals_beside_the_new_ones(tmp_path):
    """FR-05: money in and out are shown for ticked New rows, separately from Already recorded rows."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)
    token = "pdf-dialog-recorded-totals"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        import_pdf(manager, base, token, "K.pdf", fx.k_pages())
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/transactions")
        page.wait_for_selector("#tx2-import")
        dialog = page.locator("#import-dialog")
        page.locator("#tx2-import").click()
        page.get_by_role("button", name="Import K.pdf").click()
        expect(dialog.locator("#import-pdf-rows tr")).to_have_count(9)
        status = dialog.locator("#import-status")
        expect(status).to_contain_text("0 new, 9 already recorded")
        expect(status).to_contain_text("New: money out 0.00 USD; money in 0.00 USD.")
        expect(status).to_contain_text("Already recorded: money out -641.50 USD; money in 2,020.11 USD.")
        assert failures == []
        browser.close()
