"""Statement accounts in the browser (specs/statement-accounts/test-contract.md SC-24, SC-25, SC-26): synthetic data only.

S (the contract's 1-page savings statement) is captured, read and Recorded in the served library with the local model stub, as
tests/test_statement_accounts.py does through the API; the browser then works on what Record left.
"""
import json
import os

import pytest

from home_manager.documents.pdf_reader import read_result
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance.ledger import CONFIRMED
import statement_account_fixtures as sf
from test_pdf import make_pdf
from test_statement_rebuild import Recorded, s_replies
from test_taxes_v2_browser import served

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
NAME = "SYNTH BANK Savings 3456"
NOTE = f"New account: {NAME} — added to Accounts when you confirm this statement."
DOCUMENTS_STAY = "The documents stay in your library; you can record or import them again."


def record_s(manager, model, name="s.pdf", pages=None):
    """S captured and read by the real reader, then Recorded through the service (the model is the `local_model` stub): one account
    that waits for Confirm and a `proposed` statement with five rebuilt rows."""
    make_pdf(manager.store.library.inbox / name, pages or sf.s_pages())
    manager.start_inbox()
    manager.future.result(timeout=30)
    [doc] = [item for item in manager.store.documents()["items"] if item["relative_path"].endswith(name)]
    with manager.store.connection() as db:
        parse_id = db.execute("SELECT id FROM parse_runs WHERE blob_hash=? AND status IN ('succeeded','partial') ORDER BY created_at DESC LIMIT 1",
                              (doc["current_hash"],)).fetchone()[0]
    service = ReceiptService(manager.store)
    lines = sf.reading_lines(read_result(service.get(parse_id)["result"]))
    recorded = Recorded(manager.store, service, doc, parse_id, lines, model)
    recorded.run(s_replies())
    return doc, recorded


def sql(manager, query, *args):
    with manager.store.connection() as db:
        return [tuple(row) for row in db.execute(query, args)]


def open_page(driver, base, token, route, width=1440):
    browser = driver.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": width, "height": 1000})
    failures = []
    page.on("pageerror", lambda error: failures.append(str(error)))
    page.goto(f"{base}/#token={token}")
    page.goto(f"{base}/#/{route}")
    # The app shows its route twice on load (shell.js, then again once settings are in), and the second draw replaces the page's
    # elements; wait for both, or a focus or keypress lands on an element that is replaced a moment later.
    page.wait_for_load_state("networkidle")
    return browser, page, failures


def focused(page):
    return page.evaluate("document.activeElement.id")


def label_of_focus(page):
    return page.evaluate("document.activeElement.getAttribute('aria-label')")


def press_enter_on(page, locator):
    locator.focus()
    page.keyboard.press("Enter")


@browser_test
def test_sc24_the_account_waits_under_waiting_for_confirm_until_the_statement_is_confirmed(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-sc24"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        browser, page, failures = open_page(driver, base, token, "accounts")
        panel = page.locator("#accounts2-panel")
        expect(panel).to_be_visible()
        # 1: no account in the groups; "Waiting for confirm" lists it, collapsed, at the bottom.
        expect(panel.locator("#accounts2-groups section.today-region")).to_have_count(0)
        waiting = page.locator("#accounts2-waiting")
        expect(waiting).to_be_visible()
        assert waiting.get_attribute("open") is None
        expect(waiting.locator("summary")).to_have_text("Waiting for confirm (1)")
        waiting.locator("summary").click()
        row = waiting.locator(".accounts2-row", has_text=NAME)
        expect(row).to_contain_text("SYNTH BANK ··3456")
        expect(row.get_by_role("link", name=f"Open the statement for {NAME}")).to_have_attribute("href", f"#/documents/{doc['id']}")
        # 2: the statement's page says where the account goes, and offers Confirm.
        row.get_by_role("link", name=f"Open the statement for {NAME}").click()
        expect(page.locator("#doc2-panel-record")).to_contain_text(NOTE, timeout=15000)
        expect(page.locator("#doc2-decision").get_by_role("button", name="Confirm")).to_be_visible()
        # 3: Confirm moves the account into the Savings group, and Today's Cash includes its balance.
        page.locator("#doc2-decision").get_by_role("button", name="Confirm").click()
        expect(page.locator("#doc2-panel-record")).not_to_contain_text(NOTE, timeout=15000)
        assert sql(manager, "SELECT review_status,review_source FROM statements") == [("verified", "user")]
        page.goto(f"{base}/#/accounts")
        group = page.locator("#accounts2-groups section.today-region")
        expect(group).to_have_count(1)
        expect(group.locator(".accounts2-row", has_text=NAME)).to_be_visible()
        expect(page.locator("#accounts2-waiting")).to_have_count(0)
        page.goto(f"{base}/#/home")
        page.wait_for_load_state("networkidle")
        expect(page.locator("#today-tiles > .figure-tile").first).to_contain_text("1,000.00")
        assert page.evaluate(NO_OVERFLOW) and not failures, failures
        browser.close()


@browser_test
def test_sc25_delete_from_waiting_for_confirm_by_keyboard(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-sc25-a"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        files = {path.name for path in manager.store.originals.rglob("*") if path.is_file()}
        browser, page, failures = open_page(driver, base, token, "accounts")
        expect(page.locator("#accounts2-waiting")).to_be_visible()
        press_enter_on(page, page.locator("#accounts2-waiting summary"))
        delete = page.get_by_role("button", name=f"Delete {NAME}…")
        expect(delete).to_be_visible()
        # 1: the dialog names the account and shows the counts and the documents-stay text; focus is inside it, on Cancel.
        press_enter_on(page, delete)
        dialog = page.locator("#account-delete-dialog")
        expect(dialog).to_be_visible()
        expect(dialog.locator("#account-delete-name")).to_have_text(NAME)
        expect(dialog.locator("[data-count='statements']")).to_have_text("1 statement")
        expect(dialog.locator("[data-count='transactions']")).to_have_text("5 transactions")
        expect(dialog.locator("[data-count='imports']")).to_have_text("0 import records")
        expect(dialog.locator(".account-delete-count")).to_have_count(3)  # Everything else shows only when it isn't 0.
        expect(dialog).to_contain_text(DOCUMENTS_STAY)
        expect(dialog).to_contain_text("This can't be undone.")
        expect(dialog.locator("#account-delete-family")).to_be_hidden()
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        assert focused(page) == "account-delete-cancel"
        # 2: Cancel (Enter) returns focus to the opener and changes nothing.
        before = sql(manager, "SELECT count(*) FROM accounts"), sql(manager, "SELECT count(*) FROM transactions")
        page.keyboard.press("Enter")
        expect(dialog).to_be_hidden()
        assert label_of_focus(page) == f"Delete {NAME}…"
        assert (sql(manager, "SELECT count(*) FROM accounts"), sql(manager, "SELECT count(*) FROM transactions")) == before
        # Escape closes it too, with focus back on the opener.
        page.keyboard.press("Enter")
        expect(dialog).to_be_visible()
        page.keyboard.press("Escape")
        expect(dialog).to_be_hidden()
        assert label_of_focus(page) == f"Delete {NAME}…"
        # 3: Delete account is the second click; the account is gone from the page, and after a reload.
        page.keyboard.press("Enter")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        page.keyboard.press("Tab")
        assert focused(page) == "account-delete-accept"
        page.keyboard.press("Enter")
        expect(dialog).to_be_hidden()
        expect(page.locator("#accounts2-waiting")).to_have_count(0)
        expect(page.locator("#accounts2-groups")).to_contain_text("No accounts yet.")
        page.reload()
        expect(page.locator("#accounts2-panel")).to_be_visible()
        expect(page.locator("#accounts2-groups")).to_contain_text("No accounts yet.")
        assert sql(manager, "SELECT count(*) FROM accounts") == [(0,)] and sql(manager, "SELECT count(*) FROM statements") == [(0,)]
        assert {path.name for path in manager.store.originals.rglob("*") if path.is_file()} == files  # The documents stay.
        assert page.evaluate(NO_OVERFLOW) and not failures, failures
        browser.close()


@browser_test
def test_sc25_delete_from_the_statements_page_then_record_it_again(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-sc25-b"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        files = {path.name for path in manager.store.originals.rglob("*") if path.is_file()}
        browser, page, failures = open_page(driver, base, token, f"documents/{doc['id']}")
        record = page.locator("#doc2-panel-record")
        expect(record).to_contain_text(NOTE, timeout=15000)
        delete = record.get_by_role("button", name=f"Delete account {NAME}…")
        press_enter_on(page, delete)
        dialog = page.locator("#account-delete-dialog")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        expect(dialog.locator("[data-count='transactions']")).to_have_text("5 transactions")
        assert focused(page) == "account-delete-cancel"
        page.keyboard.press("Enter")  # Cancel
        expect(dialog).to_be_hidden()
        assert label_of_focus(page) == f"Delete account {NAME}…"
        page.keyboard.press("Enter")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        page.keyboard.press("Tab")
        page.keyboard.press("Enter")
        expect(dialog).to_be_hidden()
        # The page shows its statement as not recorded and offers Record it (FR-13); the document is as it was.
        expect(record).to_contain_text("Nothing is recorded from this document yet.", timeout=15000)
        expect(page.locator("#doc2-next").get_by_role("button", name="Record it")).to_be_visible()
        assert sql(manager, "SELECT count(*) FROM accounts") == [(0,)]
        assert manager.extractions.get(recorded.extraction["id"])["publication"]["removed"] is True
        assert {path.name for path in manager.store.originals.rglob("*") if path.is_file()} == files  # C-docs: the document is untouched.
        page.reload()
        expect(page.locator("#doc2-next").get_by_role("button", name="Record it")).to_be_visible(timeout=15000)
        expect(page.locator("#doc2-panel-record")).to_contain_text("Nothing is recorded from this document yet.")
        assert page.evaluate(NO_OVERFLOW) and not failures, failures
        browser.close()


@browser_test
def test_sc25_a_changed_account_is_refused_and_the_dialog_shows_the_counts_again(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-sc25-c"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        browser, page, failures = open_page(driver, base, token, "accounts")
        page.locator("#accounts2-waiting summary").click()
        page.get_by_role("button", name=f"Delete {NAME}…").click()
        dialog = page.locator("#account-delete-dialog")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        expect(dialog.locator("[data-count='transactions']")).to_have_text("5 transactions")
        # A row changes while the dialog is open (FR-14): Delete is refused with the server's sentence, nothing is deleted, and
        # the dialog loads the preview again so the next click uses the current token.
        with manager.store.connection() as db:
            db.execute("UPDATE transactions SET updated_at='later' WHERE id=(SELECT min(id) FROM transactions)")
        dialog.locator("#account-delete-accept").click()
        error = dialog.locator("#account-delete-error")
        expect(error).to_have_text("This account changed since you opened Delete; check the counts again.")
        expect(dialog).to_be_visible()
        assert sql(manager, "SELECT count(*) FROM accounts") == [(1,)]
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        dialog.locator("#account-delete-accept").click()
        expect(dialog).to_be_hidden()
        assert sql(manager, "SELECT count(*) FROM accounts") == [(0,)]
        assert not failures, failures
        browser.close()


@browser_test
def test_a_confirmed_accounts_row_has_delete_beside_rename_and_the_dialog_counts_what_goes(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-row"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        manager.ledger.create_account("Household checking", "checking", "USD")
        manager.ledger.create_account("Second checking", "checking", "USD")
        browser, page, failures = open_page(driver, base, token, "accounts")
        row = page.locator(".accounts2-row", has_text="Household checking")
        expect(row.get_by_role("button", name="Rename Household checking")).to_be_visible()
        expect(row.get_by_role("button", name="Delete Household checking…")).to_be_visible()
        expect(page.locator("#accounts2-waiting")).to_have_count(0)  # Nothing waits.
        row.get_by_role("button", name="Delete Household checking…").click()
        dialog = page.locator("#account-delete-dialog")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        expect(dialog.locator(".account-delete-count")).to_have_text(["0 statements", "0 transactions", "0 import records"])
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        assert label_of_focus(page) == "Delete Household checking…"
        # Delete there removes just that account.
        row.get_by_role("button", name="Delete Household checking…").click()
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        dialog.locator("#account-delete-accept").click()
        expect(dialog).to_be_hidden()
        expect(page.locator(".accounts2-row")).to_have_count(1)
        expect(page.locator(".accounts2-row")).to_contain_text("Second checking")
        assert not failures, failures
        browser.close()


@browser_test
def test_p4_a_statement_checked_automatically_before_accounts_waited_offers_confirm(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-p4"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        # What an upgrade leaves (073): the account is a `record` one and the statement was `verified`/`automatic` before accounts waited.
        with manager.store.connection() as db:
            db.execute("UPDATE statements SET review_status='verified',review_source='automatic'")
            db.execute("UPDATE transactions SET review_status='verified',review_source='automatic'")
        browser, page, failures = open_page(driver, base, token, f"documents/{doc['id']}")
        decision = page.locator("#doc2-decision")
        expect(page.locator("#doc2-panel-record")).to_contain_text(NOTE, timeout=15000)
        expect(decision.get_by_role("button", name="Confirm")).to_be_visible()
        expect(decision.get_by_role("button", name="Reject", exact=True)).to_be_visible()
        expect(decision.get_by_role("button", name="Not right? Reject")).to_have_count(0)
        decision.get_by_role("button", name="Confirm").click()
        expect(page.locator("#doc2-panel-record")).not_to_contain_text(NOTE, timeout=15000)
        assert sql(manager, "SELECT review_status,review_source FROM statements") == [("verified", "user")]
        assert sql(manager, f"SELECT count(*) FROM accounts a WHERE {CONFIRMED}") == [(1,)]
        assert not failures, failures
        browser.close()


@browser_test
@pytest.mark.parametrize("flagged", [False, True])
def test_sc26_a_rebuilt_rows_source_lights_the_rows_own_words(tmp_path, local_model, flagged):
    """S's s2 is a native table row (its source cites the table's cells); S-flag's has no native table (it cites word ids)."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-sc26"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model, pages=sf.s_flag_pages() if flagged else None)
        [(locator,)] = sql(manager, "SELECT e.locator_json FROM transactions t JOIN financial_evidence_links e ON e.record_type='transaction' AND e.record_id=t.id "
                                    "WHERE t.amount_minor=2")
        located = json.loads(locator)
        words = located["word_ids"] if flagged else located["cell_ids"]
        assert located["rebuilt"] and located["line_ids"] and words
        browser, page, failures = open_page(driver, base, token, f"documents/{doc['id']}")
        record = page.locator("#doc2-panel-record")
        expect(record).to_contain_text(NOTE, timeout=15000)
        # The record's notes show under its fields, as a bill's do (FR-20: S-bad lists a row the printed columns don't have).
        expect(record.locator(".doc2-notes")).to_contain_text("The reading listed a row the printed columns don't have")
        # What reaches the source viewer: s2's line and its own words or cells.
        page.evaluate("""() => { const real = doc2.viewer.highlight; window.lit = [];
          doc2.viewer.highlight = ids => { window.lit.push(ids); return real(ids); }; }""")
        row = record.locator("tbody tr", has=page.locator("td.numeric", has_text="0.02"))
        expect(row).to_have_count(1)
        row.get_by_role("button", name="Find this row in the transcription").click()
        viewer = page.locator("#doc2-viewer")
        expect(viewer.locator(".sv-overlay polygon.selected").first).to_be_attached(timeout=15000)
        assert page.evaluate("window.lit") == [[*located["line_ids"], *words]]
        # Page 1 opens with the row's words lit, and nothing else on the page.
        expect(viewer.locator(".sv-page select")).to_have_value("1")
        lit = viewer.locator(".sv-overlay polygon.selected title").all_text_contents()
        assert lit == located["quotes"][0].split(), lit
        assert not failures, failures
        browser.close()


@browser_test
def test_the_dialog_shows_the_other_counts_and_the_family_line_only_when_there_are_some(tmp_path, local_model):
    """The numbers are the server's (the preview route is answered with other counts here); the dialog only decides which lines show."""
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-dialog"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        [(account_id,)] = sql(manager, "SELECT id FROM accounts")
        browser, page, failures = open_page(driver, base, token, "accounts", width=390)
        page.locator("#accounts2-waiting summary").click()
        with_more = {"receipts": 1, "pay_stubs": 2, "transfer_links": 1, "refund_links": 0, "recurring_payments": 1, "recurring_bills": 1, "category_rules": 3}

        def answer(route):
            found = route.fetch().json()
            found["counts"].update(with_more)
            found["family"] = {"rows": 3, "copy": {"statements": 1, "transactions": 5}}
            route.fulfill(json=found)
        page.route(f"**/api/finance/accounts/{account_id}/delete-preview", answer)
        page.get_by_role("button", name=f"Delete {NAME}…").click()
        dialog = page.locator("#account-delete-dialog")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        expect(dialog.locator(".account-delete-count")).to_have_text([
            "1 statement", "5 transactions", "0 import records", "1 receipt linked to its transactions", "2 pay stubs linked to its transactions",
            "1 transfer link", "1 recurring payment tied to it", "1 recurring bill tied to it", "3 category rules for it"])
        expect(dialog.locator("#account-delete-stay")).to_have_text(
            "Linked receipts and pay stubs stay and count on their own again. Recurring payments and bills stay, with no account.")
        expect(dialog.locator("#account-delete-family")).to_have_text(
            "Your family's copy has 1 statement and 5 transactions of this account; it drops them at your next share. "
            "3 family records in this library about them are deleted too.")
        assert page.evaluate(NO_OVERFLOW)
        box = dialog.bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 390 and box["y"] >= 0 and box["y"] + box["height"] <= page.viewport_size["height"]
        assert not failures, failures
        browser.close()


@browser_test
def test_review_shows_the_note_and_delete_account_for_a_waiting_statement(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    token = "statement-accounts-review"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        doc, recorded = record_s(manager, local_model)
        browser, page, failures = open_page(driver, base, token, "review")
        evidence = page.locator("#review2-evidence")
        expect(evidence).to_contain_text(NOTE, timeout=15000)
        page.wait_for_load_state("networkidle")  # The queue's polling has settled, so the note isn't redrawn under the dialog.
        expect(page.locator("#review2-confirm")).to_be_visible()
        press_enter_on(page, evidence.get_by_role("button", name=f"Delete account {NAME}…"))
        dialog = page.locator("#account-delete-dialog")
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        dialog.get_by_role("button", name="Cancel").click()
        expect(dialog).to_be_hidden()
        assert label_of_focus(page) == f"Delete account {NAME}…"
        evidence.get_by_role("button", name=f"Delete account {NAME}…").click()
        expect(dialog.locator("#account-delete-accept")).to_be_enabled()
        dialog.locator("#account-delete-accept").click()
        expect(dialog).to_be_hidden()
        expect(page.locator("#review2-empty")).to_be_visible(timeout=15000)
        assert sql(manager, "SELECT count(*) FROM accounts") == [(0,)] and sql(manager, "SELECT count(*) FROM statements") == [(0,)]
        assert page.evaluate(NO_OVERFLOW) and not failures, failures
        browser.close()
