"""trace.js's record components in the real app (docs/ui.md "Observability components"): sourceViewer(),
confirmCorrect() with its preview, and historyList(), mounted into a test container on synthetic documents
(tests/seed_documents.py)."""
from datetime import date, timedelta

import pytest

from seed_documents import document_server
from test_ui_parity import browser_test

NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
FIXTURE = """() => { let fixture = document.getElementById("parity-fixture");
  if (!fixture) { fixture = element("div"); fixture.id = "parity-fixture"; document.querySelector("main").prepend(fixture); }
  return true; }"""


def open_app(driver, base, token, width=1440):
    browser = driver.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": width, "height": 1000})
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.goto(f"{base}/#token={token}")
    page.wait_for_load_state("networkidle")
    page.evaluate(FIXTURE)
    return browser, page, failures


@browser_test
def test_source_viewer_highlights_lines_and_reports_a_chosen_line(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, "components-test") as (base, ids, _), playwright.sync_playwright() as driver:
        browser, page, failures = open_app(driver, base, "components-test")
        page.evaluate("""async doc => {
          const reading = await loadReading(doc);
          window.testViewer = sourceViewer(reading.doc, reading, {runId: reading.run.id});
          window.regionClicks = [];
          testViewer.onRegionClick(found => regionClicks.push(found));
          document.getElementById("parity-fixture").replaceChildren(testViewer.el);
        }""", ids["receipt_doc"])
        viewer = page.locator("#parity-fixture .source-viewer")
        expect(viewer).to_have_attribute("aria-label", "Source document")
        expect(viewer.locator(".sv-line")).to_have_count(9)
        image_tab, text_tab = viewer.get_by_role("tab", name="Image"), viewer.get_by_role("tab", name="Text")
        expect(image_tab).to_have_attribute("aria-selected", "true")
        # A vision reading's lines are found in the Text tab.
        page.evaluate("testViewer.highlight(['line-2', 'line-6'])")
        expect(text_tab).to_have_attribute("aria-selected", "true")
        expect(viewer.locator(".sv-line.selected")).to_have_text([(date.today() - timedelta(days=2)).isoformat(), "Total 52.00"])
        # The tabs take arrow keys; the lines are one roving list, and Enter reports the line.
        text_tab.focus()
        page.keyboard.press("ArrowLeft")
        expect(image_tab).to_be_focused()
        expect(image_tab).to_have_attribute("aria-selected", "true")
        text_tab.click()
        viewer.locator(".sv-line").first.click()
        page.keyboard.press("ArrowDown")
        expect(viewer.locator(".sv-line").nth(1)).to_be_focused()
        page.keyboard.press("Enter")
        assert page.evaluate("regionClicks") == [{"blockId": None, "lineIds": ["line-2"]}]
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(NO_OVERFLOW)
        assert failures == []
        browser.close()


@browser_test
def test_correct_previews_two_months_saves_undoes_and_the_history_shows_both(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, "components-test") as (base, ids, _), playwright.sync_playwright() as driver:
        browser, page, failures = open_app(driver, base, "components-test")
        page.evaluate("""async id => {
          const record = await api(`/api/finance/records/receipt/${id}`);
          window.changes = 0;
          const mount = async () => {
            const fresh = await api(`/api/finance/records/receipt/${id}`);
            const cc = confirmCorrect({recordType: "receipt", recordId: id, reviewStatus: fresh.review_status, reviewSource: fresh.review_source,
                                       correctable: fresh.correctable, onChange: async () => { await mount(); changes += 1; }});
            document.getElementById("parity-fixture").replaceChildren(cc.el);
          };
          await mount();
        }""", ids["receipt_record"])
        box = page.locator("#parity-fixture .confirm-correct")
        expect(box.get_by_role("group", name="Decision")).to_be_visible()
        # Recorded automatically: Reject is offered, and Correct opens the form at the named field.
        expect(box.get_by_role("button", name="Not right? Reject")).to_be_visible()
        correct = box.get_by_role("button", name="Correct…")
        expect(correct).to_have_attribute("aria-expanded", "false")
        correct.click()
        expect(correct).to_have_attribute("aria-expanded", "true")
        form = box.locator(".cc-form")
        expect(form).to_be_visible()
        # Esc closes the form and gives focus back to Correct…, and the page stays.
        hash_before = page.evaluate("location.hash")
        page.keyboard.press("Escape")
        expect(form).to_be_hidden()
        expect(correct).to_be_focused()
        assert page.evaluate("location.hash") == hash_before

        # Moving the purchase back a month moves both months' totals; nothing is saved yet.
        moved = (date.today().replace(day=1) - timedelta(days=20)).isoformat()
        correct.click()
        form.get_by_label("Purchase date").fill(moved)
        rows = box.locator(".cc-preview-row")
        expect(rows.first).to_be_visible(timeout=10000)
        labels = rows.locator(".cc-label").all_inner_texts()
        months = {label.split(" in ")[-1] for label in labels if label.startswith("Spending in ")}
        assert len(months) == 2, labels
        expect(box.locator(".cc-preview")).to_contain_text("other total")
        # Before is the traced figure as it stands; after is a plain amount.
        expect(rows.first.locator(".figure-button")).to_have_count(1)
        form.get_by_label("Why (optional)").fill("The date on the receipt is smudged")
        form.get_by_role("button", name="Save").click()
        toast = page.locator(".toast", has_text="Saved.")
        expect(toast).to_contain_text("totals changed")
        page.wait_for_function("() => changes === 1")
        toast.get_by_role("button", name="Undo").click()
        page.wait_for_function("() => changes === 2")

        page.evaluate("""async id => {
          document.getElementById("parity-fixture").replaceChildren(historyList(await loadHistory("receipt", id)));
        }""", ids["receipt_record"])
        history = page.locator("#parity-fixture .history-list")
        corrections = history.locator('.history-row[data-kind="correction"]')
        expect(corrections).to_have_count(2)
        expect(corrections.first.locator(".history-why")).to_have_text("Undid a change")
        expect(corrections.nth(1).locator(".history-why")).to_have_text("The date on the receipt is smudged")
        expect(corrections.nth(1).locator(".history-what")).to_contain_text("Purchase date:")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate(NO_OVERFLOW)
        assert failures == []
        browser.close()
