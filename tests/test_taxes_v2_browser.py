"""Taxes v2 in the browser (taxes_v2.js; docs/ui.md "Pages"): the six tabs on synthetic data, behind the ui_v2_screens flag."""
from contextlib import contextmanager
from datetime import date
import os
import re
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from test_tax_family import paid
from test_tax_return import JOINT
from test_taxes_browser import seed_tax_year, this_year_covered
from test_ui_parity import check_figures

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
    assert page.request.put(f"{base}/api/ui-screens", data={"routes": ["taxes"]}, headers={"Authorization": f"Bearer {token}"}).ok
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

        # Write-offs, the CPA pack, and the rules with their sources.
        page.locator("#taxes2-tab-writeoffs").click()
        expect(page.locator("#taxes2-writeoffs-panel")).to_contain_text(f"Nothing tagged for {year} yet.")
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
        for name in ("Mom", "Dad"):
            year_panel.get_by_label(name).check()
        page.locator("#taxes-unit-status").select_option("married_joint")
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
