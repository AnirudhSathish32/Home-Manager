"""The browser steps of the bill table engine (specs/pdf-table-engine-bills/test-contract.md), slice SL-08: SC-129 step 2 (the split panel of a file of three bills) and
step 6 (a file that is one bill is offered Split here), SC-110 step 7 (the line's Unit price is the server's text, `0.1430`, and your correction replaces it) and
SC-111 step 3 (the lines, then Previous balance and Payment received, then Amount due, with no outside resource). Opt-in (RUN_BROWSER_TESTS=1), synthetic data only,
following tests/test_paystub_engine_browser.py: each file is captured, read and extracted in the served library through the real services with the contract's
`local_model` double. The server's side of each step is asserted in tests/test_bill_engine_record.py and tests/test_bill_split.py.
"""
import os

import pytest

import bill_engine_fixtures as bf
from home_manager.documents.receipt_service import ReceiptService
from test_bill_engine_record import UTIL_FIELDS, UTIL_WRONG_AMOUNTS, BillRun
from test_bill_split import CITY, Bills
from test_paystub_engine_browser import watch
from test_pdf import make_pdf
from test_statement_accounts_browser import open_page
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")


def read_file(manager, local_model, pages, name, run_class):
    """The file captured and read by the real reader in the served library, ready for the contract's doubles."""
    make_pdf(manager.store.library.inbox / name, pages)
    manager.start_inbox()
    manager.future.result(timeout=30)
    [doc] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name)]
    with manager.store.connection() as db:
        parse_id = db.execute("SELECT id FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') ORDER BY created_at DESC LIMIT 1",
                              (doc["current_hash"],)).fetchone()[0]
    return run_class(manager.store, ReceiptService(manager.store), local_model, parse_id, doc)


def record_util(manager, local_model):
    """BL-UTIL read as a general bill by the stub that answers every amount wrong (STUB-UTIL-WRONG), extracted."""
    run = read_file(manager, local_model, bf.util_pages(), "util.pdf", BillRun)
    run.stub_bill(bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    run.extract()
    return run


def open_document(driver, base, token, doc, expect, text):
    """The document page, loaded from a reload so the page's own requests are watched; waits for the record to show `text`."""
    browser, page, _ = open_page(driver, base, token, f"documents/{doc['id']}")
    failures = watch(page, base)
    page.reload()
    page.wait_for_load_state("networkidle")
    expect(page.locator("#doc2-panel-record")).to_contain_text(text, timeout=15000)
    return browser, page, failures


@browser_test
def test_sc129_step_2_the_split_panel_names_the_bills_and_warns_of_no_review(tmp_path, local_model):
    """BL-MULTI: "This file holds 3 bills", a chip per bill (provider, due date, amount due), Confirm split, Merge with next and Split here, and no warning that the
    bills wait in To check (FR-131)."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bill-engine-sc129"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        run = read_file(manager, local_model, bf.mini_pages(1, 2, 3), "bills.pdf", Bills)
        run.answer([1, 2, 3])
        run.extract()
        browser, page, failures = open_document(driver, base, token, run.doc, expect, "Customer Charge")
        panel = page.locator("#doc2-panel-record .split-panel")
        expect(panel).to_have_attribute("aria-label", "Bills in this file")
        expect(panel.get_by_role("heading", name="This file holds 3 bills")).to_be_visible(timeout=15000)
        chips = panel.locator(".filter-chip")
        expect(chips).to_have_count(3)
        for chip, due, amount in zip(chips.all(), ("Jul 20, 2026", "Aug 20, 2026", "Sep 20, 2026"), ("81.42", "87.26", "111.98")):
            assert chip.locator("span").first.inner_text() == CITY
            assert chip.locator(".chip-count").inner_text() == f"{due} · {amount} USD"
        for label in ("Confirm split", "Merge with next", "Split here"):
            expect(panel.get_by_role("button", name=label)).to_be_visible()
        expect(panel).not_to_contain_text("To check")
        expect(panel).not_to_contain_text("receipt")
        # The last bill has no next one to merge with.
        chips.nth(2).click()
        expect(panel.get_by_role("button", name="Merge with next")).to_have_count(0)
        assert failures == [], failures
        browser.close()


@browser_test
def test_sc129_step_6_a_file_that_is_one_bill_is_offered_split_here(tmp_path, local_model):
    """BL-TWOONPAGE (reason a): the panel says the file may hold more than one bill and offers Split here from the bill's own lines; there is nothing to confirm or
    merge."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bill-engine-sc129-one"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        run = read_file(manager, local_model, bf.two_on_page_pages(), "two.pdf", Bills)
        run.answer([1])
        run.extract()
        browser, page, failures = open_document(driver, base, token, run.doc, expect, "Customer Charge")
        panel = page.locator("#doc2-panel-record .split-panel")
        expect(panel).to_have_attribute("aria-label", "Bills in this file")
        expect(panel.get_by_role("heading", name="This file may hold more than one bill")).to_be_visible(timeout=15000)
        chips = panel.locator(".filter-chip")
        expect(chips).to_have_count(1)
        assert chips.locator("span").first.inner_text() == CITY
        assert chips.locator(".chip-count").inner_text() == "Jul 20, 2026 · 81.42 USD"
        expect(panel.get_by_role("button", name="Split here")).to_be_visible()
        expect(panel.get_by_role("button", name="Confirm split")).to_have_count(0)
        expect(panel.get_by_role("button", name="Merge with next")).to_have_count(0)
        expect(panel).not_to_contain_text("To check")
        # Split here is offered at the bill's own lines, among them the second bill's first line.
        options = panel.locator("#doc2-split-at option").all_text_contents()
        assert options.count(CITY) == 1, options
        assert failures == [], failures
        browser.close()


@browser_test
def test_sc110_step_7_the_unit_price_is_the_servers_printed_rate_until_you_correct_it(tmp_path, local_model):
    """BL-UTIL: Energy Tier 2 reads `Unit price: 0.1430` (the server's text, the page does no money arithmetic) and Tier 1 its whole-cents rate; your unit price
    correction on line 2 shows as today, not `0.1430`."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bill-engine-sc110"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        run = record_util(manager, local_model)
        browser, page, failures = open_document(driver, base, token, run.doc, expect, "Energy Tier 2")
        record = page.locator("#doc2-panel-record")
        tier_1, tier_2 = record.locator("tbody tr", has_text="Energy Tier 1"), record.locator("tbody tr", has_text="Energy Tier 2")
        expect(tier_1).to_contain_text("Quantity: 500 kWh · Unit price: 0.12 USD")
        expect(tier_2).to_contain_text("Quantity: 140 kWh · Unit price: 0.1430")
        assert "0.14 USD" not in tier_2.inner_text()
        # Your correction replaces the printed rate, as it does today.
        manager.ledger.correct_item_fields(run.run["publication"]["id"], 2, {"unit_price": "0.15"})
        page.reload()
        page.wait_for_load_state("networkidle")
        tier_2 = page.locator("#doc2-panel-record tbody tr", has_text="Energy Tier 2")
        expect(tier_2).to_contain_text("Unit price: 0.15 USD", timeout=15000)
        assert "0.1430" not in tier_2.inner_text()
        assert failures == [], failures
        browser.close()


@browser_test
def test_sc111_step_3_the_page_shows_the_lines_then_the_carried_rows_then_the_amount_due(tmp_path, local_model):
    """BL-UTIL read as general: the four lines, then Previous balance and Payment received, then Amount due 97.55; the page loads no outside resource."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "bill-engine-sc111"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        run = record_util(manager, local_model)
        browser, page, failures = open_document(driver, base, token, run.doc, expect, "Energy Tier 2")
        record = page.locator("#doc2-panel-record")
        assert record.locator("tbody tr").evaluate_all("rows => rows.map(row => row.querySelector('td span').textContent)") == [
            "Energy Tier 1", "Energy Tier 2", "Customer Charge", "State Tax"]
        rows = record.locator("tfoot tr")
        expect(rows).to_have_count(3)
        assert rows.locator("th").all_text_contents() == ["Previous balance", "Payment received", "Amount due"]
        expect(rows.nth(0)).to_contain_text("82.10")
        expect(rows.nth(1)).to_contain_text("82.10")
        expect(rows.nth(2)).to_contain_text("97.55")
        assert failures == [], failures
        browser.close()
