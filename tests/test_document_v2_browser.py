"""The document page, redesigned (document_v2.js; design-system/home-manager/pages/document.md), on synthetic read
and recorded documents (tests/seed_documents.py): its states, Find, Correct with its preview and Undo, the decision in
view, the URL, Esc, every width, and its figures against their traces and the record."""
from datetime import date, timedelta
import json
import re
from urllib.parse import quote

import pytest

from seed_documents import document_server
from test_ui_parity import browser_test, check_figures

TOKEN = "document-v2-test"
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


@browser_test
def test_native_pdf_cells_highlight_transformed_words_and_keep_original_text(tmp_path):
    from conftest import inbox_scan
    from home_manager.core.jobs import Work
    from test_pdf import make_pdf
    from test_pdf_layout import payroll_items

    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN) as (base, _, manager), playwright.sync_playwright() as driver:
        make_pdf(manager.store.library.inbox / "positioned.pdf", [
            {"items": payroll_items()}, {"items": payroll_items(), "rotation": 180, "crop": "20 30 580 760"}])
        inbox_scan(manager.store)
        doc = next(doc for doc in manager.store.documents()["items"] if doc["relative_path"].endswith("positioned.pdf"))
        run_id, _ = manager.receipts.enqueue(doc["id"], vision=manager.vision)
        manager.receipts.run(run_id, Work.detached())
        result = manager.receipts.get(run_id)["result"]
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(f"{base}/#token={TOKEN}")
        open_document(page, base, doc["id"])
        source = page.locator("#doc2-viewer")
        expect(source.locator(".sv-img")).to_be_visible()
        source.get_by_role("tab", name="Tables", exact=True).click()
        expect(source.locator(".sv-table caption").first).to_contain_text("From PDF text positions")
        source.get_by_role("button", name="Show 2000.00 on PDF page 1", exact=True).click()
        expect(source.get_by_role("tab", name="Image", exact=True)).to_have_attribute("aria-selected", "true")
        expect(source.locator(".sv-overlay polygon.selected")).to_have_count(1)
        expect(source.locator(".sv-overlay polygon title")).to_have_text("2000.00")
        source.locator(".sv-page select").select_option("2")
        expect(source.locator(".sv-overlay polygon")).to_have_count(0)
        source.get_by_role("tab", name="Tables", exact=True).click()
        # Rotated text has no reconstructed table, but its layout line still locates real words.
        line = result["pages"][1]["layout"]["lines"][0]
        page.evaluate("id => doc2.viewer.highlight([id])", line["id"])
        expect(source.locator(".sv-overlay polygon.selected")).to_have_count(len(line["word_ids"]))
        assert source.locator(".sv-overlay").get_attribute("viewBox") == f"0 0 {result['pages'][1]['layout']['preview_width']} {result['pages'][1]['layout']['preview_height']}"
        source.get_by_role("tab", name="Text", exact=True).click()
        source.get_by_label("Original text order").check()
        expect(source.locator(f'.sv-line[data-line-id="{result["lines"][0]["id"]}"]')).to_be_visible()
        source.get_by_role("button", name="Original", exact=True).click()
        expect(source.locator("iframe")).to_be_visible()
        browser.close()


@browser_test
def test_invoice_bill_label_can_be_removed_without_losing_invoice_details(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN) as (base, ids, manager), playwright.sync_playwright() as driver:
        rid = ids["receipt_record"]
        invoice = {"number": "FURN-101", "balance_due_minor": 0, "payment_status": "Paid"}
        with manager.store.connection() as db:
            db.execute("UPDATE receipts SET document_kind='bill',invoice_json=?,issue_date=purchase_date,due_date=purchase_date WHERE id=?",
                       (json.dumps(invoice), rid))
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(f"{base}/#token={TOKEN}")
        open_document(page, base, ids["receipt_doc"])
        page.locator(".doc2-fields").get_by_role("button", name="Correct record as").click()
        form = page.locator("#doc2-decision .cc-form")
        expect(form.get_by_label("Record as", exact=True)).to_have_value("bill")
        form.get_by_label("Record as", exact=True).select_option(label="Purchase")
        form.get_by_role("button", name="Save").click()
        expect(form).to_be_hidden()
        field = page.locator(".doc2-fields dt").filter(has_text="Record as").locator("xpath=following-sibling::dd[1]")
        expect(field).to_contain_text("Purchase")
        expect(page.locator(".invoice-details")).to_contain_text("FURN-101")
        expect(page.locator("#doc2-record-title")).to_contain_text("Invoice from")
        assert manager.ledger.record("receipt", rid)["document_kind"] == "receipt"
        page.locator(".toast", has_text="Saved.").get_by_role("button", name="Undo").click()
        expect(field).to_contain_text("Bill")
        expect(page.locator(".invoice-details")).to_contain_text("FURN-101")
        browser.close()


def watch_errors(page):
    """Page errors and Content Security Policy violations, as they happen."""
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.on("console", lambda message: failures.append(message.text) if "Content Security Policy" in message.text else None)
    return failures


@browser_test
def test_document_forms_show_printed_details_and_change_the_kind(tmp_path):
    """SC-14 (FR-10, FR-11): each record's printed details with their source, and changing a receipt's kind."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, forms=True) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = watch_errors(page)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        details = page.locator(".doc2-details-section")
        # 1. Fuel: its kind and details; volume's Find lights line-4.
        open_document(page, base, ids["forms_fuel_doc"])
        expect(page.locator("#doc2-kind-choice")).to_have_value("fuel")
        for text in ("10.312 gal", "3.459", "REG UNL", "17", "35.67"):
            expect(details).to_contain_text(text)
        details.get_by_role("button", name="Find volume in the source").click()
        expect(page.locator("#doc2-viewer .sv-line.selected")).to_contain_text("10.312")
        assert page.evaluate(NO_OVERFLOW)
        # 2. Grocery: weights and counts beside their items, tenders apart from the items, and Total · Gift card · Paid.
        open_document(page, base, ids["forms_grocery_doc"])
        expect(details).to_contain_text("2.31 lb @ 0.59/lb")
        expect(details.locator("dd", has_text="2 ×")).to_contain_text("2.00")
        for text in ("Gift card ****5555", "5.00", "EBT", "3.55"):
            expect(details).to_contain_text(text)
        items = page.locator("#doc2-panel-record .doc2-section", has=page.locator("h3", has_text="Items"))
        expect(items).to_contain_text("BOTTLE DEPOSIT")
        expect(items).to_contain_text("BAG FEE")
        expect(items).not_to_contain_text("GIFT CARD")
        paid = page.locator(".doc2-paid-line")
        expect(paid).to_contain_text("Total")
        expect(paid).to_contain_text("8.55")
        expect(paid).to_contain_text("−5.00")
        expect(paid).to_contain_text("3.55")
        paid.locator("[data-figure-ref]").click()
        expect(page.locator("#breakdown")).to_be_visible()
        expect(page.locator("#breakdown-body")).to_contain_text("Gift card")
        page.keyboard.press("Escape")
        # 3. Pay stub: hours and rate, PTO, deposits, and each amount's printed column heading.
        open_document(page, base, ids["forms_paystub_doc"])
        pay = page.locator(".doc2-pay-details")
        for text in ("80.00 h", "31.25", "This period", "Year to date"):
            expect(pay).to_contain_text(text)
        for text in ("56.00 hrs", "****1234", "****9876"):
            expect(details).to_contain_text(text)
        # 4. Bank statement, 5. card statement.
        open_document(page, base, ids["forms_bank_doc"])
        for text in ("Checking", "2,500.00", "1,200.50", "0.42", "0.50%", "Fees"):
            expect(details).to_contain_text(text)
        open_document(page, base, ids["forms_card_doc"])
        for text in ("24.99%", "29.99%", "5,000.00", "4,207.55", "812 points"):
            expect(details).to_contain_text(text)
        # 6. Change the fuel receipt to dining: preview, save, one reading, and it stays dining.
        open_document(page, base, ids["forms_fuel_doc"])
        page.locator("#doc2-kind-choice").select_option("dining")
        page.get_by_role("button", name="Change kind…").click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("the image isn't read again")
        dialog.get_by_role("button", name="Read again").click()
        expect(page.locator(".toast", has_text="Read as dining.")).to_be_visible(timeout=30000)
        expect(page.locator("#doc2-kind-choice")).to_have_value("dining")
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#doc2-kind-choice")).to_have_value("dining")
        assert failures == [], failures
        browser.close()


@browser_test
def test_kind_trace_opens_from_the_page_and_finds_its_line(tmp_path):
    """SC-19 step 8: the fuel figure opens its trace, whose result is the page's figure; an input's source lights line-4."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, forms=True) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = watch_errors(page)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["forms_fuel_doc"])
        shown = page.locator(".doc2-checks [data-figure-ref]").first
        display, ref = shown.get_attribute("data-figure-display"), shown.get_attribute("data-figure-ref")
        assert ref.startswith("receipt.fuel")
        result = page.request.get(f"{base}/api/traces/{quote(ref, safe='')}", headers={"Authorization": f"Bearer {TOKEN}"}).json()
        assert result["result"]["display"] == display and result["reconciles"]
        shown.click()
        inputs = page.locator("#breakdown .input-row", has_text="Volume")
        expect(inputs).to_contain_text("10.312")
        inputs.get_by_role("link", name="Open source").click()
        expect(page.locator("#doc2-viewer .sv-line.selected")).to_contain_text("10.312")
        assert failures == [], failures
        browser.close()


def open_document(page, base, doc_id, query=""):
    page.goto(f"{base}/#/documents/{doc_id}{query}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#doc2-panel:not([hidden]) #doc2-steps li")


@browser_test
def test_paystub_totals_and_lines_can_be_corrected_on_document_page(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, paystub=True) as (base, ids, manager), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page()
        page.goto(f"{base}/#token={TOKEN}")
        open_document(page, base, ids["paystub_doc"])
        source = page.locator("#doc2-viewer")
        source.get_by_role("tab", name="Text", exact=True).click()
        source.get_by_role("button", name="View extracted tables").click()
        expect(source.get_by_role("tab", name="Tables", exact=True)).to_have_attribute("aria-selected", "true")
        expect(source.locator(".sv-table thead")).to_contain_text("This period")
        expect(source.locator(".sv-table tbody tr").first).to_contain_text("Regular pay")
        expect(source.locator(".sv-table caption")).to_contain_text("From text separators")
        source.get_by_role("button", name="Find line-5 in extracted text", exact=True).click()
        expect(source.locator(".sv-line.selected")).to_contain_text("Regular pay")
        page.locator(".doc2-fields").get_by_role("button", name="Correct gross pay this period").click()
        form = page.locator("#doc2-decision .cc-form")
        expect(form.get_by_label("Gross pay", exact=True)).to_have_value("52000.00")
        form.get_by_label("Gross pay", exact=True).fill("2000.00")
        with page.expect_response(lambda response: response.request.method == "PATCH" and
                                  response.url.endswith(f"/api/finance/records/income_record/{ids['paystub_record']}")):
            form.get_by_role("button", name="Save").click()
        expect(form).to_be_hidden()
        gross = page.locator(".doc2-fields dt").filter(has_text="Gross pay this period").locator("xpath=following-sibling::dd[1]")
        expect(gross).to_have_text(re.compile(r"^(?!.*52,000).*2,000\.00"))
        page.locator(".paystub-breakdown").get_by_role("button", name="Correct Regular pay").click()
        line_form = page.locator(".paystub-breakdown .doc2-row-form .cc-form")
        expect(line_form.get_by_label("This period")).to_have_value("52000.00")
        line_form.get_by_label("This period").fill("2000.00")
        with page.expect_response(lambda response: response.request.method == "PATCH" and
                                  response.url.endswith(f"/api/paystubs/{ids['paystub_record']}/lines/1")) as saved:
            line_form.get_by_role("button", name="Save").click()
        assert saved.value.status == 200, saved.value.text()
        expect(page.locator(".paystub-breakdown tbody tr").filter(has_text="Regular pay").locator("td").first).to_have_text(
            re.compile(r"^(?!.*52,000).*2,000\.00"))
        assert manager.ledger.record("income_record", ids["paystub_record"])["lines"][0]["current_minor"] == 200000
        browser.close()


@browser_test
def test_document_page_states_find_correct_and_decide(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")

        # Unread: one step, and the one next action is to read it.
        open_document(page, base, ids["unread_doc"])
        expect(page.locator("[data-page='document']")).to_have_count(1)  # One section per page.
        expect(page.locator("#doc2-steps li")).to_have_count(1)
        expect(page.locator('#doc2-steps li[data-state="todo"]')).to_contain_text("not started")
        expect(page.locator("#doc2-next").get_by_role("button", name="Read document")).to_be_visible()
        expect(page.locator("#doc2-decision")).to_be_empty()

        # Needs review: the why, then Confirm, in view at 1366×768 (Layout rule 1).
        open_document(page, base, ids["review_doc"])
        expect(page.locator("#doc2-title")).to_have_text("Hardware Depot - Tools")
        expect(page.locator("#doc2-record-title")).to_have_text("Receipt from Hardware Depot")
        expect(page.locator('#doc2-steps li[data-state="attention"]')).to_contain_text("Recorded")
        expect(page.locator("#doc2-why")).to_contain_text("do not equal the total")
        confirm = page.locator("#doc2-decision").get_by_role("button", name="Confirm", exact=True)
        expect(confirm).to_be_visible()
        box = confirm.bounding_box()
        assert box["y"] + box["height"] <= 768, box
        assert page.evaluate(NO_OVERFLOW)

        # Find lights the field's cited line in the source's text.
        page.locator(".doc2-fields").get_by_role("button", name="Find purchase date in the source").click()
        selected = page.locator("#doc2-viewer .sv-line.selected")
        expect(selected).to_have_count(1)
        expect(selected).to_have_text((date.today() - timedelta(days=2)).isoformat())

        # Confirm posts the decision; the record is verified and Undo verification is offered.
        with page.expect_request(lambda request: request.method == "POST" and request.url.endswith(f"/receipt/{ids['review_record']}/review")):
            confirm.click()
        expect(page.locator(".toast", has_text="Confirmed.")).to_be_visible()
        expect(page.locator("#doc2-record-badge")).to_contain_text("Verified")
        expect(page.locator("#doc2-decision").get_by_role("button", name="Undo verification")).to_be_visible()
        expect(page.locator('#doc2-steps li[data-state="done"]')).to_have_count(2)
        expect(page.locator("#doc2-why")).to_be_empty()

        # Checked automatically: Correct with a preview of what moves, Save, Undo, and the History tab lists it.
        open_document(page, base, ids["receipt_doc"])
        expect(page.locator("#doc2-record-badge")).to_contain_text("Checked automatically")
        page.locator(".doc2-fields").get_by_role("button", name="Correct purchase date").click()
        form = page.locator("#doc2-decision .cc-form")
        date_field = form.get_by_label("Purchase date")
        expect(date_field).to_be_focused()
        date_field.fill((date.today().replace(day=1) - timedelta(days=20)).isoformat())
        expect(form.locator(".cc-preview-row").first).to_be_visible(timeout=10000)
        save = form.get_by_role("button", name="Save")
        box = save.bounding_box()
        assert box["y"] >= 0 and box["y"] + box["height"] <= 768, box  # The preview scrolls on its own, and Save stays in view.
        save.click()
        toast = page.locator(".toast", has_text="Saved.")
        expect(toast).to_be_visible()
        expect(page.locator(".doc2-fields .status-badge", has_text="Changed by")).to_have_count(1)
        toast.get_by_role("button", name="Undo").click()
        expect(page.locator(".toast", has_text="Undone.")).to_be_visible()
        page.locator("#doc2-tab-history").click()
        expect(page.locator('#doc2-history .history-row[data-kind="correction"]')).to_have_count(2)
        assert "tab=history" in page.evaluate("location.hash")
        # The tab survives a reload.
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#doc2-tab-history")).to_have_attribute("aria-selected", "true")
        expect(page.locator('#doc2-history .history-row[data-kind="correction"]')).to_have_count(2)

        # A statement's rows each take their own correction.
        open_document(page, base, ids["statement_doc"])
        expect(page.locator("#doc2-record-title")).to_contain_text("Statement from")
        page.locator("#doc2-panel-record").get_by_role("button", name="Correct CORNER BOOKS").click()
        row_form = page.locator(".doc2-row-form .cc-form")
        expect(row_form.get_by_label("Date", exact=True)).to_be_focused()
        expect(row_form.get_by_label("Amount")).to_have_value("25.00")
        page.keyboard.press("Escape")
        expect(page.locator(".doc2-row-form")).to_have_count(0)
        expect(page.locator("#doc2-panel-record").get_by_role("button", name="Correct CORNER BOOKS")).to_be_focused()

        # Esc goes back to the list once nothing is open.
        page.locator("#doc2-title").focus()
        page.keyboard.press("Escape")
        page.wait_for_function("() => location.hash.startsWith('#/documents') && !location.hash.match(/documents\\/\\d/)")
        assert failures == [], failures
        browser.close()


@browser_test
def test_document_page_fits_every_width_and_its_figures_match_their_traces_and_the_record(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with document_server(tmp_path, TOKEN) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        for doc in ("receipt_doc", "review_doc", "statement_doc"):
            for width, height in ((390, 844), (768, 1024), (1440, 900)):
                page.set_viewport_size({"width": width, "height": height})
                open_document(page, base, ids[doc])
                assert page.evaluate(NO_OVERFLOW), (doc, width)
        # Under 900 the decision is pinned to the bottom of the screen.
        page.set_viewport_size({"width": 390, "height": 844})
        open_document(page, base, ids["review_doc"])
        assert page.evaluate("getComputedStyle(document.getElementById('doc2-decision')).position") == "fixed"
        confirm = page.locator("#doc2-decision").get_by_role("button", name="Confirm", exact=True)
        box = confirm.bounding_box()
        assert box["y"] + box["height"] <= 844, box

        page.set_viewport_size({"width": 1440, "height": 900})
        open_document(page, base, ids["receipt_doc"])
        found = check_figures(page, base, TOKEN)
        counts_as = page.locator(".doc2-fields dd:right-of(dt:text('Counts as')) [data-figure-ref]").first.get_attribute("data-figure-display")
        assert any(display == counts_as for _, display in found)
        # "Counts as" is the receipt's own total, as the server records it (a receipt with no splits counts whole).
        headers = {"Authorization": f"Bearer {TOKEN}"}
        record = page.request.get(f"{base}/api/finance/records/receipt/{ids['receipt_record']}", headers=headers).json()
        ref = page.locator(".doc2-fields dd:right-of(dt:text('Counts as')) [data-figure-ref]").first.get_attribute("data-figure-ref")
        result = page.request.get(f"{base}/api/traces/{quote(ref, safe='')}", headers=headers).json()["result"]
        assert (result["minor"], result["currency"]) == (abs(record["total_minor"]), record["currency"]), (result, record["total_minor"])
        assert failures == [], failures
        browser.close()
