"""The receipt item table on the document page (specs/receipt-item-table FR-01 – FR-07, FR-25; test contract SC-02, SC-11,
SC-12, SC-17, SC-20): its columns, Qty and Unit price, Line total and Paid, the footer under Line total, and Printed details
without the counts. specs/receipt-tax-codes adds the tax-code note and the footer's tax lines (FR-19, FR-26; SC-19, SC-15 step 3).
Synthetic receipts (tests/receipt_item_fixtures.py) read and recorded through the real path. Each scenario
checks the stored receipt and its shares by SQL against the contract's hand-worked values before it looks at the page."""
import pytest

from document_forms_fixtures import amount_on, cite, record_document
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
    r0_replies,
    ra_replies,
    tax_line_reply,
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


# R0 and two variants, recorded by tax_seed: the user's receipt (SC-19), its tax and total off by a dime so the tax lines fall back (SC-04),
# and its B tax split into two printed lines (SC-15).
R0_SHARES = [445, 4347, 1400]
R4_LINES = [*R_LINES[:12], "TAX $2.84", "TOTAL $62.02"]
R4_SHARES = [450, 4391, 1361]
R15_LINES = [*R_LINES[:11], "B = GA STATE TAX 2.17000 on $46.19 $1.00", "B = LOCAL TAX 1.58000 on $46.19 $0.73", R_LINES[12]]
TAX_ISSUE = "The tax lines (2.74 USD) don't add up to the tax (2.84 USD), so tax was shared across the taxed items."


def r4_replies():
    """SC-04: R0's two tax lines against a printed tax of 2.84 (and a total of 62.02, so the receipt itself adds up)."""
    return r0_replies(R4_LINES, tax=amount_on(R4_LINES, "TAX "))


def r15_replies():
    """SC-15: B printed as two lines, B 1.00 and B 0.73."""
    lines = R15_LINES
    tax_lines = [tax_line_reply(lines, "T = GA TAX", "T", "1.01", "12.99", "7.75000"),
                 tax_line_reply(lines, "B = GA STATE", "B", "1.00", "46.19", "2.17000"), tax_line_reply(lines, "B = LOCAL", "B", "0.73", "46.19", "1.58000")]
    tax = {"value": "2.74", "status": "proposed", "evidence": cite(lines, "T = GA TAX") + cite(lines, "B = GA STATE") + cite(lines, "B = LOCAL")}
    return r0_replies(lines, tax_lines=tax_lines, tax=tax)


def tax_seed(manager, model):
    """R0 (SC-19), its tax-lines-do-not-add-up variant (SC-04) and its two-B-lines variant (SC-15), USD first like seed()."""
    manager.configure_household(manager.household.model_copy(update={"home_currency": "USD", "auto_identify_items": False}))
    found = {}
    for key, lines, replies in (("r0", R_LINES, r0_replies()), ("r4", R4_LINES, r4_replies()), ("r15", R15_LINES, r15_replies())):
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


def footer(page):
    """The footer's rows: (label, Line total cell, whether it has a Find button), as shown."""
    return [(" ".join(row.locator("th").inner_text().split()), " ".join(row.locator("td[data-col=line_total]").inner_text().split()),
             row.get_by_role("button", name="Find", exact=False).count() == 1) for row in page.locator(".ledger-rows tfoot tr").all()]


@browser_test
def test_sc19_tax_lines_and_codes(tmp_path):
    """SC-19 (FR-19, FR-26): R0's Paid notes name the tax code, Ruffles' row says Tax code BF, the footer lists the B and T tax lines
    with Find, and on SC-04's receipt (lines kept, not used) the page is as before."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=tax_seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        # P-checks: the stored receipt, its shares by code, and the tax lines kept.
        amounts, shares, total, _ = stored(manager, ids["r0_record"])
        assert amounts == R_AMOUNTS and shares == R0_SHARES and total == R_AMOUNTS[2]
        with manager.store.connection() as db:
            before = [tuple(row) for row in db.execute("SELECT code, taxable_minor, amount_minor FROM receipt_tax_lines WHERE receipt_id=? ORDER BY position", (ids["r0_record"],))]
        assert before == [("T", 1299, 101), ("B", 4619, 173)]
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["r0_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        # 1. Paid, with the code of the tax line each share holds (FR-26).
        assert [cells(table_row(page, name))["paid"] for name in ("RUFFLES", "LITLE VEGET", "WATER FILTER")] == [
            "$4.45 with B tax", "$43.47 with B tax", "$14.00 with T tax"]
        # 2. Ruffles' row says its printed code; no column is added (FR-26).
        assert table_row(page, "RUFFLES").get_attribute("title") == "Tax code BF"
        assert table_row(page, "WATER FILTER").get_attribute("title") == "Tax code T"
        assert titles(page) == HEADER
        # 3. The footer: Subtotal, Tax with its two lines (B before T), Total; the amounts sit under Line total.
        assert footer(page) == [("Subtotal", "$59.18", False), ("Tax", "$2.74", False), ("T · 7.75% on $12.99", "$1.01", True),
                                ("B · 7.75% on $46.19", "$1.73", True), ("Total", "$61.92", False)]
        assert_footer_under_line_total(page)
        # 4. Find on the B tax line lights the B line of the source.
        page.locator(".ledger-rows tfoot").get_by_role("button", name="Find B tax line", exact=True).click()
        expect(page.locator("#doc2-viewer .sv-line.selected")).to_contain_text("B = GA TAX")
        # 5. Correct on Tax still opens the tax correction (the footer's buttons show once the record's Correct is open); Cancel closes it.
        page.locator("#doc2-decision").get_by_role("button", name="Correct…", exact=True).click()
        page.locator(".ledger-rows tfoot").get_by_role("button", name="Correct tax", exact=True).click()
        form = page.locator("#doc2-decision .cc-form")
        expect(form.get_by_label("Tax", exact=True)).to_be_focused()
        form.get_by_role("button", name="Cancel", exact=True).click()
        expect(page.locator("#doc2-decision").get_by_label("Tax", exact=True)).to_be_hidden()
        # 6. Reloading shows the same table, and the visit wrote nothing.
        page.reload()
        page.wait_for_selector(".ledger-rows tbody tr")
        assert [cells(table_row(page, name))["paid"] for name in ("RUFFLES", "LITLE VEGET", "WATER FILTER")] == [
            "$4.45 with B tax", "$43.47 with B tax", "$14.00 with T tax"]
        assert [row[0] for row in footer(page)] == ["Subtotal", "Tax", "T · 7.75% on $12.99", "B · 7.75% on $46.19", "Total"]
        assert stored(manager, ids["r0_record"])[:3] == (amounts, shares, total)
        with manager.store.connection() as db:
            assert [tuple(row) for row in db.execute("SELECT code, taxable_minor, amount_minor FROM receipt_tax_lines WHERE receipt_id=? ORDER BY position", (ids["r0_record"],))] == before
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        # Variant (SC-04's receipt): the lines are kept but don't set the shares, so the footer has the one Tax line and Paid says "with tax".
        amounts, shares, total, _ = stored(manager, ids["r4_record"])
        assert (amounts, shares, total) == ((5918, 284, 6202), R4_SHARES, 6202)
        page.set_viewport_size({"width": 1440, "height": 900})
        open_document(page, base, ids["r4_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        assert footer(page) == [("Subtotal", "$59.18", False), ("Tax", "$2.84", False), ("Total", "$62.02", False)]
        assert [cells(table_row(page, name))["paid"] for name in ("RUFFLES", "LITLE VEGET", "WATER FILTER")] == [
            "$4.50 with tax", "$43.91 with tax", "$13.61 with tax"]
        # The reason shows once, under the table, and the warnings block doesn't hold it.
        expect(page.locator(".item-warning", has_text=TAX_ISSUE)).to_have_count(1)
        expect(page.locator("#doc2-why")).not_to_contain_text("don't add up")
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert failures == []
        browser.close()


@browser_test
def test_sc15_footer_three_tax_lines(tmp_path):
    """SC-15 step 3 (FR-19, FR-23): B printed as two lines shows three tax lines in the footer, each with Find."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=tax_seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        amounts, shares, total, _ = stored(manager, ids["r15_record"])
        assert (amounts, shares, total) == (R_AMOUNTS, R0_SHARES, R_AMOUNTS[2])
        with manager.store.connection() as db:
            assert [row[0] for row in db.execute("SELECT amount_minor FROM receipt_tax_lines WHERE receipt_id=? ORDER BY position", (ids["r15_record"],))] == [101, 100, 73]
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["r15_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(3)
        assert footer(page) == [("Subtotal", "$59.18", False), ("Tax", "$2.74", False), ("T · 7.75% on $12.99", "$1.01", True),
                                ("B · 2.17% on $46.19", "$1.00", True), ("B · 1.58% on $46.19", "$0.73", True), ("Total", "$61.92", False)]
        assert_footer_under_line_total(page)
        page.locator(".ledger-rows tfoot").get_by_role("button", name="Find B tax line", exact=True).nth(1).click()
        expect(page.locator("#doc2-viewer .sv-line.selected")).to_contain_text("LOCAL TAX")
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert failures == []
        browser.close()


def order_seed(manager, model):
    """O: an online order with an order-wide discount and an order number (tests/test_receipt_discounts.py)."""
    from test_receipt_discounts import O_LINES, o_replies
    manager.configure_household(manager.household.model_copy(update={"home_currency": "USD", "auto_identify_items": False}))
    doc, _, run = record_document(manager, model, "o-items.png", O_LINES, o_replies())
    return {"o_doc": doc["id"], "o_record": run["publication"]["id"]}


@browser_test
def test_an_order_discount_shows_under_subtotal_and_the_order_number_as_the_code(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=order_seed) as (base, ids, manager), playwright.sync_playwright() as driver:
        browser, page, failures = launch(driver)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["o_doc"])
        expect(page.locator(".ledger-rows tbody tr")).to_have_count(1)
        assert [row[:2] for row in footer(page)] == [("Subtotal", "$89.99"), ("Discounts", f"{MINUS}$8.99"), ("Tax", "$3.04"), ("Total", "$84.04")]
        assert cells(page.locator(".ledger-rows tbody tr").first)["code"] == "4401304"
        expect(page.locator(".item-warning", has_text="Doesn't add up")).to_have_count(0)
        assert_footer_under_line_total(page)
        assert not failures
        browser.close()
