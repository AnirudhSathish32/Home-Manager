"""The document page, redesigned (document_v2.js; design-system/home-manager/pages/document.md), on synthetic read
and recorded documents (tests/seed_documents.py): its states, Find, Correct with its preview and Undo, the decision in
view, the URL, Esc, every width, and its figures against their traces and the old page."""
from datetime import date, timedelta

import pytest

from seed_documents import document_server
from test_ui_parity import browser_test, check_figures, shown_before, v1_amounts

TOKEN = "document-v2-test"
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def open_document(page, base, doc_id, query=""):
    page.goto(f"{base}/#/documents/{doc_id}{query}")
    page.wait_for_load_state("networkidle")
    page.wait_for_selector("#doc2-panel:not([hidden]) #doc2-steps li")


@browser_test
def test_document_page_states_find_correct_and_decide(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, ["document"]) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")

        # Unread: one step, and the one next action is to read it.
        open_document(page, base, ids["unread_doc"])
        expect(page.locator("#document-page")).to_be_hidden()
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
def test_document_page_fits_every_width_and_its_figures_match_their_traces_and_the_old_page(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, ["document"]) as (base, ids, _), playwright.sync_playwright() as driver:
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
        # The same document on the old page shows the same amount.
        response = page.request.put(f"{base}/api/ui-screens", data={"routes": []}, headers={"Authorization": f"Bearer {TOKEN}"})
        assert response.ok
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#document-page")).to_be_visible()
        page.wait_for_selector("#extraction-result .receipt-summary")
        assert shown_before(counts_as, v1_amounts(page)), counts_as
        assert failures == [], failures
        browser.close()
