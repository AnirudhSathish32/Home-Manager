"""Records v2 in the browser (records_v2.js; design-system/home-manager/pages/records.md): synthetic data only."""
import os
import re

import pytest

from conftest import inbox_scan
from seed_documents import document_server
from test_receipts import make_receipt

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"


def no_overflow(page):
    for width in (390, 768, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        assert page.evaluate(NO_OVERFLOW), width
    page.set_viewport_size({"width": 1440, "height": 900})


@browser_test
def test_records_v2_filters_strip_read_all_and_trash(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "records-v2-test"
    with document_server(tmp_path, token) as (base, ids, manager), playwright.sync_playwright() as driver:
        # A dozen unread scans in the Inbox, so the list scrolls and Read all has several to send.
        for number in range(12):
            make_receipt(tmp_path / f"scan-{number:02}.png", [f"SHOP {number}", f"Total {number}.00"])
        inbox_scan(manager.store, {f"scan-{number:02}.png": (tmp_path / f"scan-{number:02}.png").read_bytes() for number in range(12)})
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.locator("#nav-documents").click()
        panel = page.locator("#rc2-panel")
        expect(panel).to_be_visible()
        expect(page.locator("#library-panel")).to_be_hidden()

        # The strip names the backlog and holds the page's only primary.
        read_all = page.locator("#rc2-read-all")
        expect(read_all).to_have_text(re.compile(r"Read all \d+"))
        expect(page.locator("#rc2-strip")).to_contain_text("not read yet")
        expect(panel.locator(".primary:visible")).to_have_count(1)
        no_overflow(page)

        # Filters survive reload: folder, state chip, sort and the same rows.
        page.goto(f"{base}/#/documents?folder=Inbox&status=needs_text&sort=name&offset=0")
        rows = page.locator("#rc2-table tbody tr")
        expect(rows.first).to_be_visible()
        expect(page).to_have_url(f"{base}/#/documents?folder=Inbox&status=needs_text&sort=name")
        names = rows.locator(".rc2-name").all_text_contents()
        assert names == sorted(names, key=str.lower)
        page.reload()
        expect(page.locator("#rc2-chips [data-status='needs_text']")).to_have_attribute("aria-pressed", "true")
        expect(page.locator("#rc2-tree [data-folder='Inbox']")).to_have_attribute("aria-current", "page")
        expect(page.locator("#rc2-sort")).to_have_value("name")
        expect(rows).to_have_count(len(names))
        assert rows.locator(".rc2-name").all_text_contents() == names
        expect(page.locator("#rc2-summary")).to_contain_text("Showing Inbox · Not read yet")

        # A chip writes the URL; a bad value in the URL is dropped.
        page.locator("#rc2-chips [data-status='all']").click()
        expect(page).to_have_url(f"{base}/#/documents?folder=Inbox&sort=name")
        page.goto(f"{base}/#/documents?folder=Nowhere&status=bogus&sort=sideways")
        expect(page).to_have_url(f"{base}/#/documents")

        # Read all posts every not-read document's id, as many as the strip names.
        posted = []

        def batch(route):
            posted.append(route.request.post_data_json)
            route.fulfill(status=202, content_type="application/json", body='{"batch_id": "synthetic"}')

        page.route("**/api/receipt-batches", batch)
        count = int(re.search(r"\d+", read_all.text_content()).group())
        read_all.click()
        expect(page.locator(".toast").last).to_contain_text(f"Reading {count} documents")
        assert len(posted) == 1 and len(set(posted[0]["document_ids"])) == count == 13
        page.unroute("**/api/receipt-batches")

        # At 390 the rows stack and the Name column keeps its width.
        page.set_viewport_size({"width": 390, "height": 900})
        page.wait_for_load_state("networkidle")  # Read all redraws the list; measure the redrawn rows.
        expect(page.locator("#rc2-table .rc2-name-cell").first).to_be_visible()
        cells = page.locator("#rc2-table .rc2-name-cell").evaluate_all(
            "cells => cells.map(cell => [cell.getBoundingClientRect().width, cell.textContent.slice(0, 40), cell.closest('tr').hidden])")
        assert cells and all(width >= 120 for width, _, _ in cells), cells
        assert page.evaluate(NO_OVERFLOW)
        page.set_viewport_size({"width": 1440, "height": 500})

        # Back from a document returns to the same filtered URL and scroll position.
        page.goto(f"{base}/#/documents?folder=Inbox&sort=name")
        expect(rows.first).to_be_visible()
        link = rows.locator("a.rc2-name").last
        link.scroll_into_view_if_needed()
        scrolled = page.evaluate("window.scrollY")
        assert scrolled > 0
        link.evaluate("a => a.click()")  # Not Playwright's click, which may scroll first.
        expect(page).to_have_url(re.compile(r"#/documents/\d+"))
        page.locator("#doc2-back").click()
        expect(page).to_have_url(f"{base}/#/documents?folder=Inbox&sort=name")
        for _ in range(20):  # The strict CSP rules out wait_for_function's eval.
            if abs(page.evaluate("window.scrollY") - scrolled) < 2:
                break
            page.wait_for_timeout(100)
        assert abs(page.evaluate("window.scrollY") - scrolled) < 2
        page.set_viewport_size({"width": 1440, "height": 900})

        # A row's ⋯ menu deletes to Trash; Empty trash asks first.
        first = rows.first
        title = first.locator(".rc2-name").text_content()
        page.get_by_role("button", name=f"More actions for {title}").click()
        page.get_by_role("menuitem", name="Delete").click()
        page.locator("#confirm-library-action").click()
        expect(page.locator("#library-action-dialog")).to_be_hidden()
        page.locator("#rc2-tree [data-folder='trash']").click()
        expect(page).to_have_url(f"{base}/#/documents?folder=trash&sort=name")
        expect(rows).to_have_count(1)
        expect(rows.first.get_by_role("button", name="Restore")).to_be_visible()
        page.locator("#rc2-empty-trash").click()
        expect(page.locator("#confirm-dialog")).to_be_visible()
        expect(page.locator("#confirm-title")).to_have_text("Permanently empty Trash?")
        page.locator("#confirm-cancel").click()
        expect(rows).to_have_count(1)

        # Receipts & statements: the money folders, its nav link highlighted.
        page.locator("#nav-receipts").click()
        expect(page.locator("#rc2-title")).to_have_text("Receipts & statements")
        expect(page.locator("#nav-receipts")).to_have_attribute("aria-current", "page")
        expect(page.locator("#rc2-tree [data-folder-group='Receipts']")).to_be_visible()
        expect(page.locator("#rc2-tree [data-folder='Inbox']")).to_have_count(0)
        expect(page.locator("#rc2-table tbody tr")).to_have_count(3)
        no_overflow(page)

        # The sidebar's Inbox link opens the Inbox folder on the redesigned screen.
        page.locator("#nav-inbox").click()
        expect(page).to_have_url(f"{base}/#/documents?folder=Inbox")
        expect(page.locator("#rc2-tree [data-folder='Inbox']")).to_have_attribute("aria-current", "page")
        browser.close()
        assert failures == []
