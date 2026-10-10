"""Taxes page and tagging in the browser (docs/taxes.md), with synthetic bank lines only."""
from datetime import date
import os
import re
import socket
import threading
import time

import pytest
import uvicorn

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder
from home_manager.finance.engines import taxcalc
from home_manager.finance.engines.opentax import YEARS
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from test_plan_tracking import stub
from test_tax_family import paid
from test_tax_return import JOINT
from test_withholding import FEDERAL, confirmed

# The page works out this year's return, and Engine 1 covers only the years it's pinned for: past them, re-pin the
# engine (docs/taxes.md "The tax engines") rather than let these tests fail as if the page were broken.
this_year_covered = pytest.mark.skipif(date.today().year not in YEARS, reason=f"Engine 1 covers {sorted(YEARS)} only; re-pin it for this year")


def seed_tax_year(manager, store, ledger):
    """This year's synthetic taxes: a 1985 birth year, the confirmed federal table, one biweekly pay stub and 20,000 of
    interest nobody withholds on, so Tax Zen recommends a W-4 change. False (and nothing seeded) when Engine 1 doesn't
    cover this year."""
    today = date.today()
    if today.year not in YEARS:
        return False
    manager.configure_household(manager.household.model_copy(update={"birth_year": 1985}))  # The tax engine's age facts.
    confirmed(TaxTables(store), "US", FEDERAL)
    inbox_scan(store, {"stub.png": b"stub", "tax-export.csv": b"date,amount\n"})
    docs = documents_by_name(store)
    stub(store, docs["stub.png"], f"{today.year}-01-02", 47936, 270671)
    with store.connection() as db:
        db.execute("UPDATE income_records SET pay_frequency=26")
    account = ledger.create_account("Savings", "savings", "USD")
    with store.connection() as db:  # 20,000 of interest nobody withholds on.
        ledger.insert_transactions(db, account, [{"posted_date": f"{today.year}-01-05", "description": "INTEREST PAID", "amount_minor": 2000000, "currency": "USD",
                                                  "locator": {"rows": [1]}}], "import",
                                   {"document_id": docs["tax-export.csv"]["id"], "blob_hash": docs["tax-export.csv"]["current_hash"], "source_key": "import:test"})
    return True


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
@this_year_covered
def test_tax_zen_tells_what_to_put_on_the_w4(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "zen-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        assert seed_tax_year(manager, manager.store, manager.ledger)
        today = date.today()
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=zen-test")
            page.locator("#nav-taxes").click()
            zen = page.locator("#taxes-zen")
            playwright.expect(zen).to_contain_text("Tax Zen")
            playwright.expect(zen).to_contain_text("in Step 4(a), other income")
            playwright.expect(zen).to_contain_text("From January")
            playwright.expect(zen).to_contain_text("Or pay it as estimated tax instead")
            # Owing: the simplest answer comes first, one box (Step 4(c) extra a paycheck), with Step 4(a) as the alternative.
            playwright.expect(zen.locator(".taxes-zen-headline")).to_contain_text("of extra withholding a paycheck")
            playwright.expect(zen.locator(".status-badge[data-status=tax_action]")).to_contain_text("Change recommended")
            # When a new W-4 takes effect: after the next paycheck.
            playwright.expect(zen).to_contain_text("A W-4 handed in now takes effect after the next paycheck")
            # Each value says what kind it is: the interest is as recorded (January's, nothing more to project), the job is projected.
            inputs = page.locator("#taxes-inputs")
            playwright.expect(inputs.locator(".value-kind").first).to_be_visible()
            playwright.expect(inputs).to_contain_text("Projected to Dec 31:")
            if taxcalc.installed() == taxcalc.PINNED:  # The second engine checks the return line by line.
                playwright.expect(page.locator("#taxes-return")).to_contain_text("Engine 2 checked it and agrees")
            # Entering the W-4 that's on file now changes the 4(a) advice to the new total for that box.
            four_a = zen.locator("p", has_text="Step 4(a), other income")
            before = four_a.first.inner_text()
            page.locator("[data-w4][data-key=other_income]").first.fill("5000")
            page.get_by_role("button", name="Save and estimate again").click()
            playwright.expect(four_a.first).not_to_have_text(before)
            playwright.expect(page.locator("[data-w4][data-key=other_income]").first).to_have_value("5000")
            # A different aim is saved with the year and steers the advice: keep cash, owing at most $999 less the buffer.
            page.locator("#taxes-zen-strategy").select_option("cash_retention")
            playwright.expect(page.locator("#taxes-zen-amount")).to_be_visible()
            playwright.expect(zen).to_contain_text("your aim is owing 599.00 USD")
            # A failed load shows on the page (ui.js pageState), not as a toast, and the year can still be changed.
            page.route("**/api/tax/year/*", lambda route: route.fulfill(status=503, content_type="application/json", body='{"detail":"Test unavailable"}'))
            page.locator("#taxes-year").select_option(str(today.year - 1))
            playwright.expect(page.locator("#taxes-state").get_by_role("alert")).to_contain_text("Couldn't load this year's taxes.")
            playwright.expect(page.locator("#taxes-body")).to_be_hidden()
            playwright.expect(page.locator("#taxes-year")).to_be_enabled()
            playwright.expect(page.locator('.toast[data-tone="error"]')).to_have_count(0)
            page.unroute("**/api/tax/year/*")
            page.locator("#taxes-year").select_option(str(today.year))
            playwright.expect(page.locator("#taxes-state")).to_be_empty()
            playwright.expect(zen).to_contain_text("Tax Zen")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
@this_year_covered
def test_the_family_files_a_joint_return(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "family-tax-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
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
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=family-tax-test")
            page.locator("#nav-taxes").click()
            returns = page.locator("#taxes-family")
            playwright.expect(returns).to_contain_text("Add a return")
            playwright.expect(page.locator(".taxes-personal").first).to_be_hidden()
            for name in ("Mom", "Dad"):
                returns.get_by_label(name).check()
            page.locator("#taxes-unit-status").select_option("married_joint")
            returns.get_by_role("button", name="Add a return").click()
            playwright.expect(returns).to_contain_text(re.compile(r"(Mom & Dad|Dad & Mom) · married filing jointly"))
            playwright.expect(page.locator("#taxes-return-title")).to_contain_text(re.compile(r"(Mom & Dad|Dad & Mom): the return, estimated"))
            playwright.expect(page.locator("#taxes-zen")).to_contain_text("Tax Zen")
            playwright.expect(page.locator("#taxes-inputs")).to_contain_text("Mom · ")
            playwright.expect(page.locator("#taxes-inputs")).to_contain_text("Dad · ")
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
@this_year_covered
def test_tagging_write_offs_and_tax_payments(tmp_path):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "taxes-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        assert server.started
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        manager.configure_household(manager.household.model_copy(update={"birth_year": 1985}))
        store, ledger = manager.store, manager.ledger
        confirmed(TaxTables(store), "US", FEDERAL)
        inbox_scan(store, {"export.csv": b"date,amount\n"})
        doc = store.documents()["items"][0]
        account = ledger.create_account("First Local Bank", "checking", "USD")
        year = date.today().year
        rows = [(f"{year}-01-05", "ADOBE *CREATIVE CLD 800-833", -5999), (f"{year}-02-05", "ADOBE *CREATIVE CLD 800-833", -5999),
                (f"{year}-04-15", "IRS USATAXPYMT 270612345", -300000)]
        with store.connection() as db:
            ids = ledger.insert_transactions(db, account, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                            "locator": {"rows": [index]}} for index, (day, text, amount) in enumerate(rows, 1)],
                                             "import", {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:test"})[0]
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=taxes-test")
            page.locator("#nav-taxes").click()
            playwright.expect(page.locator("#taxes-write-offs")).to_contain_text("1 suggestion waits in Review")
            # The drawer: tag Adobe as an office expense of a new business, with a rule for every Adobe line.
            page.evaluate(f"openTransaction({ids[0]})")
            drawer = page.locator("#tx-drawer")
            playwright.expect(drawer).to_contain_text("Not tagged for taxes.")
            drawer.get_by_role("button", name="Tag for taxes…").click()
            drawer.get_by_label("Counts as").select_option("business_expense")
            drawer.get_by_label("Line", exact=True).select_option("office")
            drawer.get_by_label("New business name").fill("Contract work")
            drawer.locator(".tax-tag-form .compact-check input[type=checkbox]").check()
            drawer.get_by_role("button", name="Save tag").click()
            playwright.expect(drawer).to_contain_text("Business expense: Office expense and software")
            playwright.expect(drawer).to_contain_text("Tagged by a tax rule")
            page.locator("#close-tx-drawer").click()
            # Review suggests the IRS payment as estimated tax.
            page.locator("#nav-review").click()
            playwright.expect(page.locator("#review-queue")).to_contain_text("Possible write-offs and tax payments")
            page.locator("#review-queue").get_by_text("IRS USATAXPYMT").click()
            playwright.expect(page.locator("#review-detail")).to_contain_text("looks like a payment to the IRS")
            page.get_by_role("button", name="Tag it").click()
            # The Taxes page adds them up for the year.
            page.locator("#nav-taxes").click()
            write_offs = page.locator("#taxes-write-offs")
            playwright.expect(write_offs).to_contain_text("Office expense and software")
            playwright.expect(write_offs).to_contain_text("119.98")
            playwright.expect(write_offs).to_contain_text("Federal estimated tax (1040-ES)")
            playwright.expect(page.locator("#taxes-rules")).to_contain_text("ADOBE CREATIVE")
            playwright.expect(page.locator("#taxes-businesses")).to_contain_text("Contract work")
            # The return: 3,000 of estimated tax paid and a small business loss, so all of it comes back.
            estimate = page.locator("#taxes-return")
            playwright.expect(estimate.locator(".plan-figure")).to_contain_text("3,000.00")
            playwright.expect(estimate).to_contain_text("Refund")
            # Worked out by Engine 1, never named otherwise on the page.
            playwright.expect(estimate).to_contain_text("worked out by Engine 1")
            assert "OpenTax" not in page.content()
            # A job typed in (not in pay stubs): 94,770 of wages less the 119.98 loss and the 16,100 standard deduction; 78,550.02 is in
            # the 78,550–78,600 row of the Tax Table: 1,240 + 4,560 + 22% of 28,175 = 11,998.50, about 11,999.
            page.get_by_role("button", name="Add a job not in your pay stubs").click()
            job = page.locator(".taxes-extra-job").last
            job.locator("[data-key=name]").fill("Spouse's job")
            job.locator("[data-key=wages]").fill("94770")
            job.locator("[data-key=federal_withheld]").fill("12463.36")
            page.get_by_role("button", name="Save and estimate again").click()
            playwright.expect(estimate.locator(".plan-figure")).to_contain_text(re.compile(r"3,46[45]\.36"))
            playwright.expect(estimate).to_contain_text(re.compile(r"11,99[89]\.00"))
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
