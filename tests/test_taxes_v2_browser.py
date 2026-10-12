"""Taxes v2 in the browser (taxes_v2.js; docs/ui.md "Pages"): the six tabs on synthetic data."""
from contextlib import contextmanager
from datetime import date
import os
import re
import socket
import threading
import time

import pytest
import uvicorn

from conftest import assert_tiles_fit_beside_ask, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder
from home_manager.finance.engines import taxcalc
from home_manager.finance.tax_tags import TaxTags
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from seed_taxes import seed_tax_year, this_year_covered
from test_reconcile_tools import receipt
from test_tax_family import paid
from test_tax_return import JOINT
from test_ui_parity import check_figures
from test_withholding import FEDERAL, confirmed

browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
NO_OVERFLOW = "document.documentElement.scrollWidth <= window.innerWidth"
TABS = ["year", "built", "writeoffs", "jobs", "pack", "rules"]


@contextmanager
def served(tmp_path, token):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", token, port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        yield app.state.manager, f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def open_taxes_v2(page, base, token):
    page.goto(f"{base}/#token={token}")
    page.locator("#nav-taxes").click()
    page.wait_for_selector("#taxes2-panel:not([hidden])")


@browser_test
@this_year_covered
def test_taxes_v2_answers_explains_and_edits_the_year(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)  # Each save works the return out again with the tax engine.
    token, year = "taxes-v2-test", date.today().year
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        assert seed_tax_year(manager, manager.store, manager.ledger)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1366, "height": 768})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        open_taxes_v2(page, base, token)
        panel = page.locator("#taxes2-year-panel")

        # This year: the answer first, unsigned with its direction in words; "What to do" in view at 1366×768.
        tiles = panel.locator(".taxes2-answer > .figure-tile")
        expect(tiles).to_have_count(3)
        expect(tiles.first.locator(".figure-label")).to_have_text("You'd owe")
        answer = tiles.first.locator(".figure-button").first
        expect(answer).to_have_attribute("data-magnitude", "true")
        assert not any(glyph in answer.inner_text() for glyph in "+−-"), answer.inner_text()
        advice = panel.locator(".taxes2-advice")
        expect(advice.locator(".taxes2-advice-lead")).to_contain_text("of extra withholding a paycheck")
        expect(advice.locator(".status-badge[data-status=tax_action]")).to_contain_text("Change recommended")
        expect(advice).to_contain_text("A W-4 handed in now takes effect after the next paycheck")
        box = page.locator("#taxes2-advice-title").bounding_box()
        assert box["y"] + box["height"] <= 768, box
        expect(panel.locator(".taxes2-return [data-figure-ref]").first).to_be_visible()
        check_figures(page, base, token)
        if taxcalc.installed() == taxcalc.PINNED:  # The second engine checks the return line by line.
            expect(panel.locator(".taxes2-meta")).to_contain_text("Engine 2 agrees")
        # A figure opens its breakdown, which follows its sign; Esc returns to it.
        answer.click()
        expect(page.locator("#breakdown")).to_be_visible()
        expect(page.locator("#breakdown-title")).to_be_focused()
        assert not any(glyph in page.locator(".breakdown-answer").inner_text() for glyph in "+−-")
        page.keyboard.press("Escape")
        expect(page.locator("#breakdown")).to_be_hidden()
        expect(answer).to_be_focused()

        # Built from: the section is in the URL; typing counts as a change and survives switching sections; Save re-estimates.
        page.locator("#taxes2-tab-built").click()
        page.locator("#taxes2-sec-income").click()
        assert re.search(r"tab=built&section=income", page.url), page.url
        built = page.locator("#taxes2-built-panel")
        count = built.locator(".taxes2-savebar-count")
        expect(count).to_have_text("No changes")
        built.locator('[data-field="interest"]').fill("25000")
        expect(count).to_have_text("1 unsaved change")
        expect(page.locator("#taxes2-sec-income .nav-count")).to_have_text("1")
        page.locator("#taxes2-sec-jobs").click()
        expect(built.locator("[data-job]").first).to_be_visible()
        page.locator("#taxes2-sec-income").click()
        expect(built.locator('[data-field="interest"]')).to_have_value("25000")
        check_figures(page, base, token)
        built.get_by_role("button", name="Save and estimate again").click()
        expect(built.locator(".taxes2-savebar-count")).to_have_text("No changes")
        expect(built.locator('[data-field="interest"]')).to_have_value("25000")
        expect(built.locator(".value-kind-typed").first).to_contain_text("You typed")
        # Moving between tabs with the keyboard: arrows move along the tabs.
        page.locator("#taxes2-tab-built").focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator("#taxes2-tab-writeoffs")).to_be_focused()
        expect(page.locator("#taxes2-tab-writeoffs")).to_have_attribute("aria-selected", "true")

        # Jobs & pay stubs: the W-4 on file is part of the same draft; saving it changes Tax Zen's other ways.
        page.locator("#taxes2-tab-year").click()
        ways = panel.locator(".taxes2-ways")
        expect(ways).to_contain_text("Step 4(a)")
        before = ways.text_content()
        page.locator("#taxes2-tab-jobs").click()
        jobs = page.locator("#taxes2-jobs-panel")
        expect(jobs.locator(".taxes2-job h2")).to_have_count(1)
        expect(jobs.locator("table a").first).to_have_attribute("href", re.compile(r"^#/documents/\d+$"))
        expect(jobs).to_contain_text("Tax Zen suggests: Step 4(c)")
        check_figures(page, base, token)
        jobs.locator("[data-w4][data-key=other_income]").fill("5000")
        expect(jobs.locator(".taxes2-savebar-count")).to_have_text("1 unsaved change")
        jobs.get_by_role("button", name="Save and estimate again").click()
        expect(jobs.locator(".taxes2-savebar-count")).to_have_text("No changes")
        expect(jobs.locator("[data-w4][data-key=other_income]")).to_have_value("5000")
        page.locator("#taxes2-tab-year").click()
        expect(ways).not_to_have_text(before)
        # A different aim is saved with the year and steers the advice: keep cash, owing at most $999 less the buffer.
        advice_before = panel.locator(".taxes2-advice-lead").text_content()
        page.locator("#taxes2-zen-strategy").select_option("cash_retention")
        expect(page.locator("#taxes2-zen-amount")).to_be_visible()
        expect(panel.locator(".taxes2-advice-lead")).not_to_have_text(advice_before)
        page.reload()
        expect(page.locator("#taxes2-zen-strategy")).to_have_value("cash_retention")

        # Write-offs, the CPA pack, and the rules with their sources.
        page.locator("#taxes2-tab-writeoffs").click()
        expect(page.locator("#taxes2-writeoffs-panel")).to_contain_text(f"Nothing tagged for {year} yet.")
        # A receipt's write-off links to its document page; a transaction's opens the drawer.
        inbox_scan(manager.store, {"goodwill.png": b"receipt"})
        doc = next(doc for doc in manager.store.documents()["items"] if doc["relative_path"].endswith("goodwill.png"))
        given = receipt(manager.ledger, doc, "Goodwill", date.today().isoformat(), 8000)
        manager.ledger.review("receipt", given, "verified")
        TaxTags(manager.store).tag("receipt", given, "itemized", "charity_cash")
        page.reload()
        writeoffs = page.locator("#taxes2-writeoffs-panel")
        writeoffs.locator("details.tax-items summary").click()
        expect(writeoffs.get_by_role("link", name="Goodwill")).to_have_attribute("href", f"#/documents/{doc['id']}")
        page.locator("#taxes2-tab-pack").click()
        expect(page.locator("#taxes2-pack-body").get_by_role("button", name=f"Build the {year} CPA pack")).to_be_visible()
        page.locator("#taxes2-tab-rules").click()
        rules = page.locator("#taxes2-rules-panel")
        expect(rules.locator(".rule-card").first).to_be_visible()
        expect(rules.locator(".taxes2-table-row").first).to_contain_text("Confirmed")
        assert "OpenTax" not in page.content()

        # No sideways scroll on any tab, at any width.
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            for tab in TABS:
                page.evaluate(f"activateTaxes2Tab('taxes2-tab-{tab}')")
                expect(page.locator(f"#taxes2-{tab}-panel")).to_be_visible()
                page.wait_for_selector("[aria-busy='true']", state="detached")
                assert page.evaluate(NO_OVERFLOW), (width, tab)
        # Under 900px Built from's sections are a select.
        page.set_viewport_size({"width": 768, "height": 900})
        page.evaluate("activateTaxes2Tab('taxes2-tab-built')")
        expect(page.locator("#taxes2-section")).to_be_visible()
        expect(page.locator(".taxes2-sections")).to_be_hidden()
        page.locator("#taxes2-section").select_option("people")
        expect(page.locator("#taxes2-secpanel-people")).to_be_visible()

        # A failed load shows on the page, not as a toast, and the year can still be changed.
        page.set_viewport_size({"width": 1440, "height": 900})
        page.route("**/api/tax/year/*", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"Test unavailable"}'))
        page.locator("#taxes2-year").select_option(str(year - 1))
        expect(page.locator("#taxes2-state").get_by_role("alert")).to_contain_text("Couldn't load this year's taxes.")
        expect(page.locator("#taxes2-body")).to_be_hidden()
        expect(page.locator("#taxes2-year")).to_be_enabled()
        expect(page.locator('.toast[data-tone="error"]')).to_have_count(0)
        page.unroute("**/api/tax/year/*")
        page.locator("#taxes2-year").select_option(str(year))
        expect(page.locator("#taxes2-state")).to_be_empty()
        expect(page.locator("#taxes2-body")).to_be_visible()

        # A million or more shrinks the answer's figures to fit, with Ask open and without.
        page.evaluate("activateTaxes2Tab('taxes2-tab-year')")
        page.wait_for_selector("[aria-busy='true']", state="detached")
        expect(page.locator(".taxes2-answer")).to_be_visible()
        assert_tiles_fit_beside_ask(page, ".taxes2-answer")
        assert not failures, failures
        browser.close()


@browser_test
@this_year_covered
def test_taxes_v2_family_view_shows_returns_not_write_offs(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)
    token = "taxes-v2-family"
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "mom"))
        manager.rename_profile(manager.profile["id"], "Mom")
        mom = manager.profile["id"]
        paid(manager, "mom", 30000)
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1980}))
        tables = TaxTables(manager.store)
        tables.review(tables.propose("US", date.today().year, "married_joint", JOINT, [])["id"], "verified")
        dad = manager.create_profile("Dad", str(tmp_path / "dad"))
        manager.switch_profile(dad["id"])
        paid(manager, "dad", 20000)
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1978}))
        manager.switch_profile(mom)
        family = manager.create_family("The Smiths", str(tmp_path / "family"), ["Dad"], my_profile=mom)
        folder = FamilyFolder(tmp_path / "family")
        dad_member = next(member["member_id"] for member in folder.data["members"] if member["name"] == "Dad")
        folder.close()
        manager.set_up_local_member(family["id"], dad_member, dad["id"], None)
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        open_taxes_v2(page, base, token)
        for tab in ("writeoffs", "pack", "rules"):
            expect(page.locator(f"#taxes2-tab-{tab}")).to_be_hidden()
        expect(page.locator("#taxes2-family-note")).to_be_visible()
        expect(page.locator("#taxes2-unit")).to_be_visible()
        year_panel = page.locator("#taxes2-year-panel")
        page.wait_for_load_state("networkidle")  # A refresh after the family's first sync would redraw the form under the clicks.
        for name in ("Mom", "Dad"):
            year_panel.get_by_label(name).check()
        page.locator("#taxes-unit-status").select_option("married_joint")
        for name in ("Mom", "Dad"):
            expect(year_panel.get_by_label(name)).to_be_checked()
        year_panel.get_by_role("button", name="Add a return").click()
        expect(page.locator("#taxes2-unit option")).to_have_count(1)
        expect(page.locator("#taxes2-unit option").first).to_have_text(re.compile(r"(Mom & Dad|Dad & Mom) · married filing jointly"))
        expect(year_panel.locator(".taxes2-advice")).to_contain_text("What to do")
        page.locator("#taxes2-tab-built").click()
        page.locator("#taxes2-sec-jobs").click()
        expect(page.locator("#taxes2-built-panel")).to_contain_text("Mom · ")
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()


@browser_test
@this_year_covered
def test_taxes_v2_adds_up_tags_from_the_drawer_and_to_check(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    expect = playwright.expect
    expect.set_options(timeout=30000)
    token, year = "taxes-v2-tags", date.today().year
    with served(tmp_path, token) as (manager, base), playwright.sync_playwright() as driver:
        manager.configure(str(tmp_path / "managed"))
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1985}))
        store, ledger = manager.store, manager.ledger
        confirmed(TaxTables(store), "US", FEDERAL)
        inbox_scan(store, {"export.csv": b"date,amount\n"})
        doc = store.documents()["items"][0]
        account = ledger.create_account("First Local Bank", "checking", "USD")
        rows = [(f"{year}-01-05", "ADOBE *CREATIVE CLD 800-833", -5999), (f"{year}-02-05", "ADOBE *CREATIVE CLD 800-833", -5999),
                (f"{year}-04-15", "IRS USATAXPYMT 270612345", -300000)]
        with store.connection() as db:
            ids = ledger.insert_transactions(db, account, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                            "locator": {"rows": [index]}} for index, (day, text, amount) in enumerate(rows, 1)],
                                             "import", {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:test"})[0]
        browser = driver.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        open_taxes_v2(page, base, token)
        page.locator("#taxes2-tab-writeoffs").click()
        expect(page.locator("#taxes2-writeoffs-panel")).to_contain_text("1 suggestion waits in Review")
        # The drawer: tag Adobe as an office expense of a new business, with a rule for every Adobe line.
        page.evaluate(f"openTransaction({ids[0]})")
        drawer = page.locator("#tx-drawer")
        expect(drawer).to_contain_text("Not tagged for taxes.")
        drawer.get_by_role("button", name="Tag for taxes…").click()
        drawer.get_by_label("Counts as").select_option("business_expense")
        drawer.get_by_label("Line", exact=True).select_option("office")
        drawer.get_by_label("New business name").fill("Contract work")
        drawer.locator(".tax-tag-form .compact-check input[type=checkbox]").check()
        drawer.get_by_role("button", name="Save tag").click()
        expect(drawer).to_contain_text("Business expense: Office expense and software")
        expect(drawer).to_contain_text("Tagged by a tax rule")
        page.locator("#close-tx-drawer").click()
        # To check suggests the IRS payment as estimated tax.
        page.locator("#nav-review").click()
        expect(page.locator("#review2-queue")).to_contain_text("Possible write-offs and tax payments")
        page.locator("#review2-queue").get_by_text("IRS USATAXPYMT").click()
        expect(page.locator("#review2-panel")).to_contain_text("looks like a payment to the IRS")
        page.locator("#review2-bar").get_by_role("button", name="Tag it").click()
        expect(page.locator("#toasts")).to_contain_text("Tagged; it counts in this year's taxes.")
        # Taxes adds them up for the year.
        page.locator("#nav-taxes").click()
        page.locator("#taxes2-tab-writeoffs").click()
        writeoffs = page.locator("#taxes2-writeoffs-panel")
        expect(writeoffs).to_contain_text("Office expense and software")
        expect(writeoffs).to_contain_text("119.98")
        expect(writeoffs).to_contain_text("Federal estimated tax (1040-ES)")
        page.locator("#taxes2-tab-rules").click()
        expect(page.locator("#taxes2-rules-panel")).to_contain_text("ADOBE CREATIVE")
        page.locator("#taxes2-tab-built").click()
        page.locator("#taxes2-sec-businesses").click()
        expect(page.locator("#taxes2-built-panel")).to_contain_text("Contract work")
        # The return: 3,000 of estimated tax paid and a small business loss, so all of it comes back; worked out by Engine 1.
        page.locator("#taxes2-tab-year").click()
        panel = page.locator("#taxes2-year-panel")
        answer = panel.locator(".taxes2-answer > .figure-tile").first
        expect(answer).to_contain_text("3,000.00")
        expect(answer.locator(".figure-label")).to_have_text("Refund")
        expect(panel.locator(".taxes2-meta")).to_contain_text("worked out by Engine 1")
        assert "OpenTax" not in page.content()
        # A job typed in (not in pay stubs): 94,770 of wages less the 119.98 loss and the 16,100 standard deduction; 78,550.02 is in
        # the 78,550–78,600 row of the Tax Table: 1,240 + 4,560 + 22% of 28,175 = 11,998.50, about 11,999.
        page.locator("#taxes2-tab-built").click()
        page.locator("#taxes2-sec-jobs").click()
        built = page.locator("#taxes2-built-panel")
        built.get_by_role("button", name="Add a job not in your pay stubs").click()
        job = built.locator(".taxes2-extra-job").last
        job.locator("[data-key=name]").fill("Spouse's job")
        job.locator("[data-key=wages]").fill("94770")
        job.locator("[data-key=federal_withheld]").fill("12463.36")
        built.get_by_role("button", name="Save and estimate again").click()
        expect(built.locator(".taxes2-savebar-count")).to_have_text("No changes")
        page.locator("#taxes2-tab-year").click()
        expect(answer).to_contain_text(re.compile(r"3,46[45]\.36"))
        expect(panel.locator(".taxes2-return")).to_contain_text(re.compile(r"11,99[89]\.00"))
        for width in (390, 768, 1440):
            page.set_viewport_size({"width": width, "height": 900})
            assert page.evaluate(NO_OVERFLOW), width
        assert not failures, failures
        browser.close()
