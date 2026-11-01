"""The receipt item table on the document page (specs/receipt-item-table FR-01 – FR-07, FR-25; test contract SC-02, SC-11,
SC-12, SC-17, SC-20): its columns, Qty and Unit price, Line total and Paid, the footer under Line total, and Printed details
without the counts. Synthetic receipts (tests/receipt_item_fixtures.py) read and recorded through the real path. Each scenario
checks the stored receipt and its shares by SQL against the contract's hand-worked values before it looks at the page."""
import pytest

from document_forms_fixtures import record_document
from receipt_item_fixtures import (
    D_AMOUNTS,
    D_LINES,
    D_SHARES,
    G_AMOUNTS,
    G_LINES,
    N_AMOUNTS,
    N_LINES,
    N_SHARES,
    R_AMOUNTS,
    R_LINES,
    R_SHARES,
    d_replies,
    g_replies,
    na_replies,
    ra_replies,
)
from seed_documents import document_server
from test_document_v2_browser import NO_OVERFLOW, open_document, watch_errors
from test_ui_parity import browser_test

TOKEN = "receipt-item-table-test"
HEADER = ["Item", "Code", "Qty", "Unit price", "Category", "Line total", "Paid"]
MINUS = "−"  # what amount() shows for a negative figure with no direction


def seed(manager, model):
    """R, D, G and N, each recorded with its stub answers. The household's currency is USD first, so amounts show as $4.19."""
    manager.configure_household(manager.household.model_copy(update={"home_currency": "USD", "auto_identify_items": False}))
    found = {}
    for key, lines, replies in (("r", R_LINES, ra_replies()), ("d", D_LINES, d_replies()), ("g", G_LINES, g_replies()), ("n", N_LINES, na_replies())):
        doc, _, run = record_document(manager, model, f"{key}-items.png", lines, replies)
        found[f"{key}_doc"], found[f"{key}_record"] = doc["id"], run["publication"]["id"]
    return found


def stored(manager, record_id):
    """(subtotal, tax, total), the receipt's own shares per item in position order (transaction_id IS NULL), the shares' sum
    and the items' stored quantities, all by SQL."""
    with manager.store.connection() as db:
        amounts = tuple(db.execute("SELECT subtotal_minor, tax_minor, total_minor FROM receipts WHERE id=?", (record_id,)).fetchone())
        shares = [row[0] for row in db.execute(
            "SELECT s.amount_minor FROM category_splits s JOIN receipt_items i ON i.id=s.receipt_item_id "
            "WHERE s.receipt_id=? AND s.transaction_id IS NULL ORDER BY i.position", (record_id,))]
        total = db.execute("SELECT sum(amount_minor) FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL", (record_id,)).fetchone()[0]
        quantities = [row[0] for row in db.execute("SELECT quantity FROM receipt_items WHERE receipt_id=? ORDER BY position", (record_id,))]
    return amounts, shares, total, quantities


def cells(row):
    """A row's cells by data-col, as shown."""
    return {cell.get_attribute("data-col"): " ".join(cell.inner_text().split()) for cell in row.locator("td").all()}


def titles(page):
    return [" ".join(th.inner_text().split()) for th in page.locator(".ledger-rows thead th[data-col]:not([data-col=source])").all()]


def table_row(page, name):
    return page.locator(".ledger-rows tbody tr", has=page.locator("td[data-col=item]", has_text=name))


def within(inner, outer):
    """The inner box lies horizontally within the outer one (FR-07 by geometry, not by colspan)."""
    return outer["x"] - 1 <= inner["x"] and inner["x"] + inner["width"] <= outer["x"] + outer["width"] + 1


def assert_footer_under_line_total(page):
    head = page.locator(".ledger-rows thead th[data-col=line_total]").bounding_box()
    amounts = page.locator(".ledger-rows tfoot td[data-col=line_total]")
    assert amounts.count() >= 1
    for amount in amounts.all():
        assert within(amount.bounding_box(), head)


def launch(driver, width=1440, height=900):
    browser = driver.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": width, "height": height})
    return browser, page, watch_errors(page)


@browser_test
def test_sc02_item_table(tmp_path):
    """SC-02 (FR-01 – FR-07): R's table, its footer and its Correct buttons."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        # 1. P-check: the stored receipt and its shares.
        amounts, shares, total, quantities = stored(manager, ids["r_record"])
        assert amounts == R_AMOUNTS and shares == R_SHARES and total == R_AMOUNTS[2]
        assert quantities[0] is None  # Ruffles' quantity is empty, and showing 1 doesn't store it (D3).
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["r_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        # 2. The columns, in order, and the source button last in every row (FR-01).
        assert titles(page) == HEADER
        assert page.locator(".ledger-rows thead th").last.get_attribute("data-col") == "source"
        for row in page.locator(".ledger-rows tbody tr").all():
            assert row.locator("td").last.get_attribute("data-col") == "source"
            assert row.locator("td").last.locator("button").count() >= 1  # the source button, then any row Correct/Delete
        # 3-5. The three items.
        ruffles = cells(table_row(page, "RUFFLES"))
        assert [ruffles[key] for key in ("code", "qty", "unit_price", "line_total", "paid")] == ["071057174", "1", "$4.29", "$4.29", "$4.29"]
        expect(table_row(page, "RUFFLES").locator("td[data-col=paid]")).not_to_contain_text("with tax")
        veg = cells(table_row(page, "LITLE VEGET"))
        assert [veg[key] for key in ("code", "qty", "unit_price", "line_total", "paid")] == ["211180042", "10", "$4.19", "$41.90", "$41.90"]
        expect(table_row(page, "LITLE VEGET").locator("td[data-col=paid]")).not_to_contain_text("with tax")
        water = cells(table_row(page, "WATER FILTER"))
        assert [water[key] for key in ("code", "qty", "unit_price", "line_total")] == ["07200120", "1", "$12.99", "$12.99"]
        assert water["paid"] == "$15.73 with tax"
        # 6. No Paid cell reads "—" (FR-05).
        for paid in page.locator(".ledger-rows tbody td[data-col=paid]").all():
            assert "—" not in paid.inner_text()
        # 7. The footer's amounts sit in the Line total column (FR-07).
        foot = {" ".join(row.locator("th").inner_text().split()): " ".join(row.locator("td[data-col=line_total]").inner_text().split())
                for row in page.locator(".ledger-rows tfoot tr").all()}
        assert foot == {"Subtotal": "$59.18", "Tax": "$2.74", "Total": "$61.92"}
        assert_footer_under_line_total(page)
        # 8. Correct on Tax opens the tax correction, and cancelling closes it. The footer's buttons show once the record's Correct is open.
        expect(page.locator(".ledger-rows tfoot").get_by_role("button", name="Correct tax", exact=True)).to_be_hidden()
        page.locator("#doc2-decision").get_by_role("button", name="Correct…", exact=True).click()
        assert_footer_under_line_total(page)
        page.locator(".ledger-rows tfoot").get_by_role("button", name="Correct tax", exact=True).click()
        form = page.locator("#doc2-decision .cc-form")
        expect(form.get_by_label("Tax", exact=True)).to_be_focused()
        form.get_by_role("button", name="Cancel", exact=True).click()
        expect(page.locator("#doc2-decision").get_by_label("Tax", exact=True)).to_be_hidden()
        # 9. Reloading shows the same table, and viewing it wrote nothing.
        page.reload()
        page.wait_for_selector(".ledger-rows tbody tr")
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        assert titles(page) == HEADER
        assert cells(table_row(page, "WATER FILTER"))["paid"] == "$15.73 with tax"
        assert stored(manager, ids["r_record"]) == (amounts, shares, total, quantities)
        # The table fits the page at phone, tablet and desktop widths: it scrolls inside its wrap (R-c).
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert failures == []
        browser.close()


@browser_test
def test_sc11_count_and_weight(tmp_path):
    """SC-11 (FR-02, FR-03, FR-25): a weighed item, a counted item with no unit price, and a plain one."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        assert stored(manager, ids["g_record"])[0] == G_AMOUNTS
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["g_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        assert "Code" not in titles(page)  # G prints no product codes.
        bananas, yogurt, milk = (cells(table_row(page, name)) for name in ("BANANAS", "YOGURT", "MILK"))
        assert (bananas["qty"], bananas["unit_price"], bananas["line_total"]) == ("2.31 lb", "$0.59/lb", "$1.36")
        assert (yogurt["qty"], yogurt["unit_price"], yogurt["line_total"]) == ("3", "—", "$4.50")
        assert (milk["qty"], milk["unit_price"]) == ("1", "$3.49")
        # 4. Printed details has no line for Bananas or Yogurt (FR-25): G has no tenders, so the section may be absent.
        for section in page.locator(".doc2-details-section").all():
            text = section.inner_text()
            assert "BANANAS" not in text and "YOGURT" not in text and "2.31 lb" not in text
        assert failures == []
        browser.close()


@browser_test
def test_sc17_printed_details_without_counts(tmp_path):
    """SC-17 (FR-25): Printed details has no "10 × $4.19" line for Little Veg; the item table shows the count and price."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        assert stored(manager, ids["r_record"])[0] == R_AMOUNTS
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["r_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        veg = cells(table_row(page, "LITLE VEGET"))
        assert (veg["qty"], veg["unit_price"]) == ("10", "$4.19")
        # R has no tenders or savings, so Printed details may be absent; if it shows, it has no item or count line.
        for section in page.locator(".doc2-details-section").all():
            text = section.inner_text()
            assert "LITLE VEGET" not in text and "10 ×" not in text and "4.19" not in text
        assert failures == []
        browser.close()


@browser_test
def test_sc12_returned_item(tmp_path):
    """SC-12 (FR-04, FR-05): a returned item's Line total and Paid stay negative, Paid as stored."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        amounts, shares, total, _ = stored(manager, ids["n_record"])
        assert amounts == N_AMOUNTS and shares == N_SHARES and total == N_AMOUNTS[2]
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["n_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(1)
        row = table_row(page, "WATER FILTER")
        shown = cells(row)
        assert shown["line_total"] == f"{MINUS}$12.99"
        assert shown["paid"] == f"{MINUS}$14.00 with tax"
        assert failures == []
        browser.close()


@browser_test
def test_sc20_no_codes_untaxed_item(tmp_path):
    """SC-20 (FR-05, FR-06): no product codes means no Code column; an untaxed item's Paid has no "with tax"."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        amounts, shares, total, _ = stored(manager, ids["d_record"])
        assert amounts == D_AMOUNTS and shares == D_SHARES and total == D_AMOUNTS[2]
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["d_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        assert titles(page) == [title for title in HEADER if title != "Code"]
        assert page.locator(".ledger-rows [data-col=code]").count() == 0
        groceries = cells(table_row(page, "GROCERIES"))
        assert groceries["paid"] == "$80.00"
        for name, paid in (("HOT DOG", "$1.62 with tax"), ("MATTRESS", "$539.99 with tax")):
            assert cells(table_row(page, name))["paid"] == paid
        assert page.locator(".ledger-rows tfoot tr", has=page.locator("th", has_text="Tax")).count() == 1
        expect(page.locator(".ledger-rows tfoot tr", has=page.locator("th", has_text="Tax")).locator("td[data-col=line_total]")).to_have_text("$40.12")
        assert_footer_under_line_total(page)
        assert failures == []
        browser.close()
