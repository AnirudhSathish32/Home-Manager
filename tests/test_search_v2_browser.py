"""Search v2 and Ask in the browser (search_v2.js, assistant.js; design-system/home-manager/pages/search-ask.md):
synthetic data only."""
import os

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
def test_search_v2_groups_kinds_and_next_steps(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "search-v2-test"
    with document_server(tmp_path, token) as (base, ids, manager), playwright.sync_playwright() as driver:
        # Eight more "fresh" scans, so Documents has more than the six "All" shows.
        for number in range(8):
            make_receipt(tmp_path / f"fresh-{number}.png", [f"FRESH STALL {number}"])
        inbox_scan(manager.store, {f"fresh-{number}.png": (tmp_path / f"fresh-{number}.png").read_bytes() for number in range(8)})
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")

        # The statement's water bill is both a document (its text) and a transaction.
        page.goto(f"{base}/#/search?q=water")
        expect(page.locator("#se2-panel")).to_be_visible()
        expect(page.locator("[data-page='search']")).to_have_count(1)  # One section per page.
        expect(page.locator(".se2-group[data-kind='documents'] h2")).to_contain_text("Documents · ")
        expect(page.locator(".se2-group[data-kind='transactions'] h2")).to_contain_text("Transactions · ")
        expect(page.locator("#se2-status")).to_contain_text("for “water”")
        expect(page.locator("#se2-kinds [data-kind='items']")).to_be_disabled()
        expect(page.locator("#se2-panel .primary:visible")).to_have_count(1)
        no_overflow(page)
        page.locator(".se2-group[data-kind='transactions'] button.se2-title").first.click()
        expect(page.locator("#tx-drawer")).to_be_visible()
        page.keyboard.press("Escape")

        # "All" shows six documents and offers the rest; the chip keeps the kind in the URL, through a reload.
        page.goto(f"{base}/#/search?q=fresh")
        documents = page.locator(".se2-group[data-kind='documents']")
        expect(documents.locator(".se2-row")).to_have_count(6)
        expect(documents.locator(".se2-more")).to_be_visible()
        page.locator("#se2-kinds [data-kind='documents']").click()
        expect(page).to_have_url(f"{base}/#/search?q=fresh&kind=documents")
        page.reload()
        expect(page.locator("#se2-kinds [data-kind='documents']")).to_have_attribute("aria-pressed", "true")
        expect(page.locator(".se2-group")).to_have_count(1)
        assert documents.locator(".se2-row").count() > 6
        expect(documents.locator(".se2-more")).to_have_count(0)
        # The page's own form keeps the kind.
        page.locator("#se2-input").fill("fresh stall")
        page.locator("#se2-submit").click()
        expect(page).to_have_url(f"{base}/#/search?q=fresh+stall&kind=documents")

        # Nothing found: both next steps.
        page.goto(f"{base}/#/search?q=coffee")
        empty = page.locator("#se2-results .empty-state")
        expect(empty).to_contain_text("Nothing matches “coffee”.")
        expect(empty.get_by_role("link", name="the text of your documents")).to_have_attribute("href", "#/documents?q=coffee")
        expect(empty.get_by_role("link", name="your transactions")).to_have_attribute("href", "#/transactions?q=coffee&period=all")

        # No query: the hint, with focus in the box.
        page.goto(f"{base}/#/search")
        expect(page.locator("#se2-results")).to_contain_text("Search names, merchants")
        expect(page.locator("#se2-input")).to_be_focused()
        assert not failures, failures
        browser.close()


@browser_test
def test_ask_is_a_column_beside_the_page(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "ask-column-test"
    with document_server(tmp_path, token) as (base, ids, manager), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        page.goto(f"{base}/#token={token}")
        page.goto(f"{base}/#/accounts")
        expect(page.locator("#accounts2-panel")).to_be_visible()
        no_overflow(page)

        page.keyboard.press("Control+j")
        ask = page.locator("#assistant-panel")
        expect(ask).to_be_visible()
        expect(page.locator("#assistant-question")).to_be_focused()
        expect(page.locator("#assistant-log")).to_contain_text("Ask about your spending, bills or documents.")
        # An example fills the box.
        page.locator(".assistant-examples .link-button").first.click()
        expect(page.locator("#assistant-question")).not_to_have_value("")
        no_overflow(page)

        # Beside the page, not over it; a toast stays clear of it.
        panel, main = ask.bounding_box(), page.locator("main").bounding_box()
        assert panel["x"] >= main["x"] + main["width"] - 1, (panel, main)
        page.evaluate("notice('Saved.')")
        toast = page.locator("#toasts .toast").first
        expect(toast).to_be_visible()
        box = toast.bounding_box()
        assert box["x"] + box["width"] <= panel["x"], (box, panel)

        # One side panel at a time: a breakdown takes Ask's slot, and Ask takes it back.
        page.locator(".figure-button").first.click()
        expect(page.locator("#breakdown")).to_be_visible()
        expect(ask).to_be_hidden()
        page.locator("#nav-ask").click()
        expect(ask).to_be_visible()
        expect(page.locator("#breakdown")).to_be_hidden()
        page.keyboard.press("Escape")
        expect(ask).to_be_hidden()
        expect(page.locator("#nav-ask")).to_be_focused()

        # The bottom sheet below 900px.
        page.set_viewport_size({"width": 390, "height": 800})
        page.keyboard.press("Control+j")
        expect(ask).to_be_visible()
        sheet = ask.bounding_box()
        assert sheet["width"] <= 390 and sheet["y"] > 0, sheet
        assert page.evaluate(NO_OVERFLOW)
        assert not failures, failures
        browser.close()
