"""A kinded bill's document page (specs/bill-kinds FR-42 UI, FR-50, FR-51; test contract SC-46, SC-46e, SC-48, SC-50):
its rows under the lines, a rent line's type, period and usage with Find, Amount due last, and the bill kind control.
Synthetic bills read and recorded through the real path (tests/seed_documents.py, tests/bill_kinds_fixtures.py)."""
import pytest

from bill_kinds_fixtures import AMOUNT_LINE, RENT, RENT_LINE, WATER_LINE, general_replies, rent_carried, rent_replies, rent_row, water_row, with_line
from document_forms_fixtures import record_document
from seed_documents import document_server, seed_bill
from test_bill_kinds import carried_replies
from test_document_v2_browser import NO_OVERFLOW, open_document, watch_errors
from test_ui_parity import browser_test

TOKEN = "bill-kinds-test"


def usd(manager):
    """The rent fixtures print $ with no currency code, so the household's currency is USD (as read_bill does)."""
    manager.configure_household(manager.household.model_copy(update={"home_currency": "USD", "auto_identify_items": False}))


def record_bill(manager, model, name, lines, replies):
    doc, _, run = record_document(manager, model, name, lines, replies)
    return doc["id"], run["publication"]["id"]


def seed_rent(manager, model):
    """SC-38's RENT bill, with the model left ready to read it again as a general bill (SC-48 step 7)."""
    usd(manager)
    doc, record = record_bill(manager, model, "rent.png", RENT, rent_replies())
    model["by_schema"] = general_replies()
    return {"rent_doc": doc, "rent_record": record}


def seed_rows(manager, model):
    """The PHONE bill (seed_bill, read general), RENT-CARRIED (a) and (b), and RENT-WARNING read with a 75.00 fee line."""
    phone = seed_bill(manager, model)  # Its replies are in call order, so it is read before any reply by schema is set.
    usd(manager)
    found = {"phone_doc": phone["doc_id"], "phone_record": phone["record_id"]}
    for key, due in (("carried_a", "1,488.42"), ("carried_b", "1,588.42")):
        lines = with_line(rent_carried(), 10, f"Amount Due......................................................... ${due}")
        found[f"{key}_doc"], found[f"{key}_record"] = record_bill(manager, model, f"{key}.png", lines, carried_replies(lines, due))
    lines = [*RENT, "A late fee of $75.00 applies after 10/05/2026"]
    rows = [rent_row(lines=lines), water_row(lines), rent_row(description="Late fee", amount="75.00", line=8, lines=lines, rent_type="fee", period=None)]
    found["warning_doc"], found["warning_record"] = record_bill(manager, model, "warning.png", lines, rent_replies(lines, rows=rows))
    return found


def foot_rows(page):
    """The bill's rows under its lines, in order: (label, amount as shown without its currency symbol)."""
    return [(row.locator("th").evaluate("node => node.firstChild.textContent"), row.locator("td.numeric").inner_text().strip().replace("$", ""))
            for row in page.locator(".bill-lines tfoot tr").all()]


def open_bill(page, base, doc_id, count):
    """Open a bill's page and wait for its count lines (opening clears the last record's)."""
    open_document(page, base, doc_id)
    page.locator(".bill-lines tbody tr").nth(count - 1).wait_for()
    page.locator(".bill-lines tfoot tr.bill-total").wait_for()


def line_names(page):
    return [row.locator("td").first.locator("span").first.inner_text() for row in page.locator(".bill-lines tbody tr").all()]


def field(page, label):
    return page.locator(".doc2-fields dt").filter(has_text=label)


def selected(page):
    return page.locator("#doc2-viewer .sv-line.selected")


@browser_test
def test_sc48_a_rent_bills_page_its_lines_and_its_kind(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed_rent) as (base, ids, _), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = watch_errors(page)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        open_document(page, base, ids["rent_doc"])
        # 1. The top fields: Provider, Due, Period and Billed, with no money rows and no Issued.
        for label in ("Provider", "Due", "Period", "Billed"):
            expect(field(page, label)).to_have_count(1)
        for label in ("Issued", "New charges", "Amount due"):
            expect(field(page, label)).to_have_count(0)
        expect(page.locator(".doc2-fields")).to_contain_text("Oct 1, 2026 to Oct 31, 2026")
        # 2. The Bill kind control shows Rent.
        expect(page.locator("#doc2-kind-choice")).to_have_value("rent")
        expect(page.locator(".doc2-kind dd")).to_contain_text("Rent")
        # 3. Water Usage: Utility, its period and usage; Find lights line 5.
        water = page.locator(".bill-lines tbody tr", has_text="Water Usage")
        expect(water.get_by_label("Type of Water Usage")).to_have_value("utility")
        expect(water.get_by_label("Type of Water Usage").locator("option:checked")).to_have_text("Utility")
        expect(water).to_contain_text("Aug 15 – Sep 14, 2026")
        expect(water).to_contain_text("3,200 GAL")
        water.get_by_role("button", name="Find this row in the transcription").click()
        expect(selected(page)).to_have_count(1)
        expect(selected(page)).to_contain_text(RENT[WATER_LINE - 1][:20])
        water.get_by_role("button", name="Find the usage of Water Usage").click()
        expect(selected(page)).to_contain_text("3,200 GAL")
        # 4. Rent: its type and period; Find lights line 4.
        rent = page.locator(".bill-lines tbody tr", has_text="Oct 1 – Oct 31, 2026")
        expect(rent.get_by_label("Type of Rent")).to_have_value("rent")
        rent.get_by_role("button", name="Find the period of Rent").click()
        expect(selected(page)).to_contain_text(RENT[RENT_LINE - 1][:20])
        # 5. Amount due is the section's last row; Find lights its printed line and Correct opens the correction form.
        assert foot_rows(page) == [("Amount due", "1,488.42")]
        last = page.locator(".bill-lines tfoot tr").last
        last.get_by_role("button", name="Find the amount due in the source").click()
        expect(selected(page)).to_contain_text(RENT[AMOUNT_LINE - 1][:12])
        last.get_by_role("button", name="Correct amount due").click()
        expect(page.locator("#doc2-decision .cc-form")).to_be_visible()
        page.keyboard.press("Escape")
        # 6. No New charges or Counts as anywhere on the page.
        expect(page.locator("#doc2-panel-record")).not_to_contain_text("New charges")
        expect(page.locator("#doc2-panel-record")).not_to_contain_text("Counts as")
        # The page fits a phone's width.
        page.set_viewport_size({"width": 360, "height": 800})
        page.wait_for_load_state("networkidle")
        assert page.evaluate(NO_OVERFLOW)
        page.set_viewport_size({"width": 1440, "height": 900})
        # 7. Read it as General: one stubbed reading, and it stays General after a reload.
        page.locator("#doc2-kind-choice").select_option("general")
        page.get_by_role("button", name="Change kind…").click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_contain_text("Read this bill as general?")
        dialog.get_by_role("button", name="Read again").click()
        expect(page.locator(".toast", has_text="Read as general.")).to_be_visible(timeout=30000)
        expect(page.locator("#doc2-kind-choice")).to_have_value("general")
        page.reload()
        page.wait_for_load_state("networkidle")
        expect(page.locator("#doc2-kind-choice")).to_have_value("general")
        expect(page.locator(".doc2-kind dd")).to_contain_text("General")
        # 8. Records: the bill's row shows its period.
        page.goto(f"{base}/#/documents")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#rc2-table .rc2-date", has_text="For Oct 1 – Oct 31, 2026")).to_have_count(1)
        assert failures == [], failures
        browser.close()


@browser_test
def test_sc46_sc46e_phone_the_rows_under_a_bills_lines(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    with document_server(tmp_path, TOKEN, seed=seed_rows) as (base, ids, manager), playwright.sync_playwright() as driver:
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = watch_errors(page)
        page.goto(f"{base}/#token={TOKEN}")
        page.wait_for_load_state("networkidle")
        record = page.locator("#doc2-panel-record")
        carried = [("Previous balance", "100.00"), ("Payment received", "−100.00")]
        # SC-46 step 2: (a) the lines, the carried rows, then Amount due under a rule; Counts in stays.
        open_bill(page, base, ids["carried_a_doc"], 2)
        assert line_names(page) == ["Rent", "Water Usage"]
        assert foot_rows(page) == [*carried, ("Amount due", "1,488.42")]
        expect(page.locator(".bill-lines tfoot tr.bill-total")).to_have_count(1)
        expect(field(page, "Counts in")).to_have_count(1)
        for text in ("New charges", "Counts as", "Not accounted for"):
            expect(record).not_to_contain_text(text)
        # SC-46 step 4: (b) the same rows, then Not accounted for 100.00 with the reason, then Amount due last.
        open_bill(page, base, ids["carried_b_doc"], 2)
        assert foot_rows(page) == [*carried, ("Not accounted for", "100.00"), ("Amount due", "1,588.42")]
        expect(page.locator(".bill-lines tfoot tr.bill-gap")).to_contain_text("but the amount due is 1,588.42 USD")
        # SC-46e (b): a fee read from a warning is Not accounted for −75.00, with the lines check's reason.
        open_bill(page, base, ids["warning_doc"], 3)
        assert line_names(page) == ["Rent", "Water Usage", "Late fee"]
        assert foot_rows(page) == [("Not accounted for", "−75.00"), ("Amount due", "1,488.42")]
        expect(page.locator(".bill-lines tfoot tr.bill-gap")).to_contain_text("the lines add up to 1,563.42 USD")
        # SC-50: the PHONE bill's lines, Earlier balance 12.00 worked out, then Amount due 79.99; still verified.
        open_bill(page, base, ids["phone_doc"], 3)
        assert line_names(page) == ["Unlimited", "Apple TV+", "Taxes and fees"]
        assert foot_rows(page) == [("Earlier balance", "12.00"), ("Amount due", "79.99")]
        expect(page.locator(".bill-lines tfoot tr.bill-earlier")).to_contain_text("Worked out")
        for text in ("Not accounted for", "Counts as", "Only the new charges count"):
            expect(record).not_to_contain_text(text)
        shown = manager.ledger.record("receipt", ids["phone_record"])
        assert (shown["review_status"], shown["review_source"]) == ("verified", "automatic")
        page.set_viewport_size({"width": 360, "height": 800})
        page.wait_for_load_state("networkidle")
        assert page.evaluate(NO_OVERFLOW)
        assert failures == [], failures
        browser.close()
