"""Processing v2 in the browser (processing_v2.js; design-system/home-manager/pages/system.md): synthetic data only."""
import os

import pytest

from seed_processing import seed_processing
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def no_overflow(page):
    for width in (390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate(NO_OVERFLOW), width
    page.set_viewport_size({"width": 1440, "height": 1000})


@browser_test
def test_processing_v2_strip_tabs_health_and_folders(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "processing-v2-test"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        (tmp_path / "scanner").mkdir()
        ids = seed_processing(manager, tmp_path / "scanner")
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.locator("#nav-processing").click()
        expect(page.locator("#pr2-panel")).to_be_visible()
        expect(page.locator("#scan-panel")).to_be_hidden()

        # The strip: nothing running, five stages; the failed reading shows under Reading.
        expect(page.locator("#pr2-activity")).to_have_text("Nothing running.")
        expect(page.locator("#pr2-lanes .pr2-lane")).to_have_count(5)
        expect(page.locator("#pr2-lanes .pr2-lane").nth(1)).to_contain_text("Failed")
        # Recent work, with the failed reading first under Failed; the filter is in the URL.
        work = page.locator("#pr2-work tbody tr")
        expect(work.first).to_be_visible()
        page.locator("#pr2-work-panel [data-result='failed']").click()
        expect(page).to_have_url(f"{base}/#/processing?status=failed")
        expect(work).to_have_count(1)
        expect(work.first).to_contain_text("Reading a document")
        expect(work.first.get_by_role("link", name="Open document")).to_be_visible()
        no_overflow(page)

        # Scan Inbox from the header: the Capture stage records the new run.
        page.locator("#pr2-scan").click()
        expect(page.locator("#pr2-lanes .pr2-lane").first).to_contain_text("Last", timeout=15000)
        expect(page.locator(".toast")).to_contain_text("Inbox capture started")

        # Data health: two warnings, one per rule; the statement's opens its document, the orphan's has no page.
        health = page.locator("#pr2-tab-health")
        expect(health).to_have_attribute("aria-label", "Data health, 2 problems")
        health.click()
        expect(page).to_have_url(f"{base}/#/processing?tab=health")
        expect(page.locator(".pr2-health-summary")).to_contain_text("2 warnings")
        rows = page.locator(".pr2-health-row")
        expect(rows).to_have_count(2)
        balance = rows.filter(has_text="opening balance")
        expect(balance).to_have_class("needs-row pr2-health-row attention")
        open_link = balance.get_by_role("link", name="Open statement #")
        expect(open_link).to_have_attribute("href", f"#/documents/{ids['old_statement_doc']}")
        orphan = rows.filter(has_text="no longer exists")
        orphan.locator("summary", has_text="Which record").click()
        expect(orphan).to_contain_text("(no page to open)")
        expect(page.locator(".pr2-engine")).not_to_have_count(0)
        no_overflow(page)
        open_link.click()
        expect(page).to_have_url(f"{base}/#/documents/{ids['old_statement_doc']}")

        # Reload keeps the tab.
        page.goto(f"{base}/#/processing?tab=folders")
        page.reload()
        expect(page.locator("#pr2-tab-folders")).to_have_attribute("aria-selected", "true")
        # Watched folders: the seeded one, then one added in the dialog (an error beside its field first) and stopped.
        folders = page.locator("#pr2-folders tbody tr")
        expect(folders).to_have_count(1)
        expect(folders.first).to_contain_text("Scanner")
        page.locator("#pr2-add-source").click()
        expect(page.locator("#pr2-source-dialog")).to_be_visible()
        page.locator("#pr2-source-save").click()
        expect(page.locator("#pr2-source-path-error")).to_contain_text("Enter the folder's full path.")
        (tmp_path / "downloads").mkdir()
        page.locator("#pr2-source-path").fill(str(tmp_path / "downloads"))
        page.locator("#pr2-source-label").fill("Downloads")
        page.locator("#pr2-source-save").click()
        expect(page.locator("#pr2-source-dialog")).to_be_hidden()
        expect(folders).to_have_count(2)
        no_overflow(page)
        page.get_by_role("button", name="Stop watching Downloads").click()
        page.locator("#confirm-accept").click()
        expect(folders).to_have_count(1)

        # Model runs: the filter lists the seeded failure's task and status, and narrows to it.
        page.locator("#pr2-tab-models").click()
        expect(page.locator("#pr2-models tbody tr")).to_have_count(1)
        page.locator("#pr2-status").select_option("failed")
        expect(page).to_have_url(f"{base}/#/processing?tab=models&status=failed")
        expect(page.locator("#pr2-models tbody tr").first).to_contain_text("Failed")
        page.reload()
        expect(page.locator("#pr2-status")).to_have_value("failed")
        no_overflow(page)

        # Keyboard: the tabs move with the arrow keys.
        page.locator("#pr2-tab-models").focus()
        page.keyboard.press("Home")
        expect(page.locator("#pr2-tab-work")).to_be_focused()
        expect(page.locator("#pr2-work-panel")).to_be_visible()
        browser.close()
        assert failures == []
