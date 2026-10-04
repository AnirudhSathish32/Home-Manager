"""Jobs: an employer folder per employer with Paystubs and Documents, pay stub lines and titles (docs/taxes.md "Jobs and pay stubs").
Synthetic data only."""

import json
import os
import socket
import threading
import time

import pytest
import uvicorn

from home_manager.app.api import create_app
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance.ledger import HouseholdConfig
from home_manager.household.tax_tables import TaxTables
from home_manager.library.managed_library import clean_label, employer_folder, spelled
from home_manager.library.scanner import ScanLimits
from home_manager.library.trash import empty
from test_extraction import MISSING, cite, extract, transcribe, value
from test_receipts import make_receipt

PAYSTUB = ["GOOGLE LLC", "1600 Amphitheatre Parkway, Mountain View", "Pay date 2026-09-15", "Pay period 2026-09-01 to 2026-09-14",
           "Pay frequency: Biweekly", "Currency USD", "Regular Pay 4,000.00 72,000.00", "401(k) Pre-Tax 240.00 4,320.00", "Medical 100.00 1,800.00",
           "Dental 10.00 180.00", "Vision 5.00 90.00", "Federal Income Tax 380.00 6,840.00", "GA State Income Tax 170.00 3,060.00",
           "Social Security 240.87 4,335.66", "Medicare 56.33 1,013.99", "Roth 401(k) 40.00 720.00", "Employer 401(k) Match 160.00 2,880.00",
           "Gross Pay 4,000.00 72,000.00", "Net Pay 2,757.80 49,640.35"]
LINES = [(7, "Regular Pay", "earnings", "regular_pay"), (8, "401(k) Pre-Tax", "pre_tax", "retirement_pretax"), (9, "Medical", "pre_tax", "health"),
         (10, "Dental", "pre_tax", "dental"), (11, "Vision", "pre_tax", "vision"), (12, "Federal Income Tax", "tax", "federal_income_tax"),
         (13, "GA State Income Tax", "tax", "state_income_tax"), (14, "Social Security", "tax", "social_security"), (15, "Medicare", "tax", "medicare"),
         (16, "Roth 401(k)", "post_tax", "retirement_roth"), (17, "Employer 401(k) Match", "employer_paid", "other")]


def stub_classification(lines=PAYSTUB, kind="paystub", employer="Google", date_line=3, date="2026-09-15"):
    return {"document_type": kind, "evidence": cite(1, lines[0]), "issuer": value(employer, 1, lines[0]),
            "document_date": value(date, date_line, date)}


def stub_summary(employer="Google", net="2,757.80"):
    return {"payer_or_employer": value(employer, 1, PAYSTUB[0]), "pay_date": value("2026-09-15", 3, "2026-09-15"),
            "period_start": value("2026-09-01", 4, "2026-09-01"), "period_end": value("2026-09-14", 4, "2026-09-14"),
            "pay_frequency": value("Biweekly", 5, "Biweekly"), "work_state": value("GA", 13, "GA State Income Tax"),
            "gross_pay": value("4,000.00", 18, PAYSTUB[17]), "gross_pay_ytd": value("72,000.00", 18, PAYSTUB[17]),
            "net_pay": value(net, 19, PAYSTUB[18]) if net == "2,757.80" else value(net, 19, PAYSTUB[18]),
            "net_pay_ytd": value("49,640.35", 19, PAYSTUB[18]), "taxes": MISSING, "deductions": MISSING, "currency": value("USD", 6, "Currency USD")}


def stub_lines(skip=None):
    rows = []
    for number, name, group, category in LINES:
        if number == skip:
            continue
        current, ytd = PAYSTUB[number - 1].split()[-2:]
        rows.append({"description": name, "group": group, "category": category, "current": current, "ytd": ytd,
                     "evidence": cite(number, PAYSTUB[number - 1])})
    return {"lines": rows}


def library_file(manager, doc):
    return manager.store.document(doc["id"])


def test_a_pay_stub_files_under_its_employer_with_its_breakdown(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, PAYSTUB)
    try:
        local_model["outputs"] = [stub_classification(), stub_summary(), stub_lines()]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert [request["response_format"]["json_schema"]["name"] for request in local_model["requests"][-3:]] == [
            "Classification", "PaystubSummary", "PayLines"]
        publication = run["publication"]
        # Earnings add up to gross, and gross less deductions and taxes is net, this period and year to date.
        assert (publication["record_type"], publication["review_status"], publication["lines"]) == ("income_record", "verified", 11)
        record = manager.paystub(publication["id"])
        assert (record["pay_frequency"], record["work_state"], record["gross_pay_ytd_minor"]) == (26, "GA", 7200000)
        groups = {group["group"]: group for group in record["breakdown"]["groups"]}
        assert groups["pre_tax"]["current_minor"] == 35500 and groups["tax"]["fica"]["display"]["current_minor"] == "297.20 USD"
        assert groups["employer_paid"]["lines"][0]["description"] == "Employer 401(k) Match"
        assert [(check["label"], check["matches"]) for check in record["breakdown"]["checks"]] == [("This period", True), ("Year to date", True)]
        # No tax table yet (no web search key in tests): the page says so rather than guessing.
        assert [part["status"] for part in record["withholding"]["jurisdictions"]] == ["missing", "missing"]
        filed = library_file(manager, doc)
        assert filed["folder"] == "Jobs" and filed["employer"] == "Google" and filed["job_section"] == "Paystubs"
        assert filed["title"] == "Paystub 09/15/2026"
        assert filed["managed_path"].startswith("Jobs/Google/Paystubs/2026/09/2026-09-15__Paystub__Google__")
        library = manager.store.library.root
        assert (library / "Jobs" / "Google" / "Documents").is_dir() and not (library / "Income").exists() or not os.listdir(library / "Income")
        folders = manager.store.folders()
        assert folders["jobs"] == [{"id": filed["employer_id"], "name": "Google", "folder": "Google", "sections": {"Paystubs": 1, "Documents": 0}}]
        assert manager.store.documents(folder="Jobs", employer=filed["employer_id"], section="Paystubs")["total"] == 1
        # Reading it again, the model is told Google already has a folder; "Google LLC" still maps to it.
        local_model["outputs"] = [stub_classification(employer="Google LLC"), stub_summary(employer="Google LLC"), stub_lines()]
        again = extract(manager, doc, parse_id, force=True)
        assert 'Employers that already have a folder: ["Google"]' in local_model["requests"][-2]["messages"][0]["content"]
        assert again["status"] == "succeeded" and library_file(manager, doc)["managed_path"].startswith("Jobs/Google/Paystubs/")
        assert len(manager.store.library.employers()) == 1
    finally:
        manager.close()


def test_a_misread_line_sends_the_stub_to_review(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, PAYSTUB)
    try:
        local_model["outputs"] = [stub_classification(), stub_summary(), stub_lines(skip=10)]
        run = extract(manager, doc, parse_id)
        record = manager.ledger.record("income_record", run["publication"]["id"])
        assert record["review_status"] == "needs_review"
        assert any("less deductions and taxes (2,767.80 USD) is not net pay (2,757.80 USD)" in issue for issue in record["issues"])
        [check, _] = record["breakdown"]["checks"]
        assert (check["matches"], check["display"]["difference_minor"]) == (False, "-10.00 USD")
    finally:
        manager.close()


OFFER = ["GOOGLE", "Offer Letter", "Date: 2026-08-01", "We are pleased to offer you the position of Engineer."]


def test_an_offer_letter_files_in_the_employers_documents(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, OFFER)
    try:
        local_model["outputs"] = [stub_classification(OFFER, "employment_document", date_line=3, date="2026-08-01"),
                                  {"employer": value("Google", 1, "GOOGLE"), "document_name": value("Offer Letter", 2, "Offer Letter"),
                                   "document_date": value("2026-08-01", 3, "2026-08-01")}]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded" and run["publication"] is None  # Filed only; nothing reaches the ledger.
        filed = library_file(manager, doc)
        assert (filed["folder"], filed["employer"], filed["job_section"], filed["title"]) == ("Jobs", "Google", "Documents", "Offer Letter")
        assert filed["managed_path"].startswith("Jobs/Google/Documents/2026/08/2026-08-01__Offer_Letter__Google__")
    finally:
        manager.close()


W2 = ["GOOGLE", "W-2 Wage and Tax Statement", "Date: 2027-01-31", "Wages, tips, other compensation 94,770.00"]


def test_a_w2_files_in_the_employers_documents_with_its_number_spelled(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, W2)
    try:
        local_model["outputs"] = [stub_classification(W2, "employment_document", date_line=3, date="2027-01-31"),
                                  {"employer": value("Google", 1, "GOOGLE"), "document_name": value("W-2", 2, "W-2"),
                                   "document_date": value("2027-01-31", 3, "2027-01-31")}]
        extract(manager, doc, parse_id)
        filed = library_file(manager, doc)
        assert (filed["job_section"], filed["title"]) == ("Documents", "W-2")
        assert filed["managed_path"].startswith("Jobs/Google/Documents/2027/01/2027-01-31__W-Two__Google__")
    finally:
        manager.close()


def test_short_numbers_in_document_names_are_spelled_out():
    assert clean_label(spelled("W-2")) == "W-Two"
    assert clean_label(spelled("Form 1099-NEC")) == "Form_-NEC"  # A longer number is still left out.
    assert clean_label(spelled("Section 42 notice")) == "Section_FortyTwo_notice"


def test_employer_folder_names():
    assert employer_folder("Google LLC") == "Google"
    assert employer_folder("Acme Widgets, Inc.") == "Acme_Widgets"
    assert employer_folder("3M") == "M"  # Digits never reach a path.
    assert employer_folder("LLC") == "LLC"


def test_income_folder_files_move_into_jobs(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, PAYSTUB)
    try:
        local_model["outputs"] = [stub_classification(), stub_summary(), stub_lines()]
        extract(manager, doc, parse_id)
        store, library = manager.store, manager.store.library
        # As an older library had it: the pay stub in Library/Income/YYYY/MM with no employer folder.
        before = library_file(manager, doc)["managed_path"]
        old = f"Income/2026/09/2026-09-15__Google__Income__{doc['current_hash'][:16]}__d{doc['id']}.png"
        library.path(old).parent.mkdir(parents=True)
        os.rename(library.path(before), library.path(old))
        with store.connection() as db:
            db.execute("UPDATE managed_files SET relative_path=?,folder='Income' WHERE document_id=?", (old, doc["id"]))
            db.execute("DELETE FROM job_filings")
            db.execute("DELETE FROM employers")
        library.retire_folders()
        filed = library_file(manager, doc)
        assert filed["managed_path"].startswith("Jobs/Google/Paystubs/2026/09/2026-09-15__Paystub__Google__") and filed["folder"] == "Jobs"
        assert not library.path(old).exists()
    finally:
        manager.close()


def test_emptying_trash_keeps_the_employer(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, PAYSTUB)
    try:
        local_model["outputs"] = [stub_classification(), stub_summary(), stub_lines()]
        extract(manager, doc, parse_id)
        store = manager.store
        current = library_file(manager, doc)["current_hash"]
        store.library_action(doc["id"], current, "trash")
        assert empty(store)["deleted"] == 1
        with store.connection() as db:
            assert [db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("job_filings", "income_lines", "income_records", "employers")] == [0, 0, 0, 1]
            assert not db.execute("PRAGMA foreign_key_check").fetchall()
        assert json.dumps(store.folders()["jobs"][0]["sections"]) == '{"Paystubs": 0, "Documents": 0}'
    finally:
        manager.close()


@pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_shows_jobs_and_how_a_stubs_taxes_were_figured(tmp_path, local_model):
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "jobs-browser", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        manager = app.state.manager
        manager.configure(str(tmp_path / "managed"))
        make_receipt(manager.store.library.inbox / "stub.png")
        local_model["output"] = {"full_text": "\n".join(PAYSTUB)}
        manager.configure_vision(local_model["config"])
        manager.start_inbox()
        manager.future.result(timeout=30)
        manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
        manager.configure_household(HouseholdConfig(auto_identify_items=False))
        doc = manager.store.documents()["items"][0]
        local_model["outputs"] = [stub_classification(), stub_summary(), stub_lines()]
        manager.start_extraction(doc["id"], manager.receipts.history(doc["id"])[0]["id"])
        manager.future.result(timeout=30)
        tables = TaxTables(manager.store)
        source = [{"url": "https://example.gov/rates", "title": "Synthetic rates", "quote": "synthetic"}]
        for code, values in (("US", {"standard_deduction_minor": 1500000, "brackets": [{"from_minor": 0, "rate_bp": 1000}, {"from_minor": 1192500, "rate_bp": 1200},
                                                                                          {"from_minor": 4847500, "rate_bp": 2200}],
                                     "ss_rate_bp": 620, "ss_wage_base_minor": 17610000, "medicare_rate_bp": 145}),
                             ("GA", {"standard_deduction_minor": 1500000, "brackets": [{"from_minor": 0, "rate_bp": 519}]})):
            tables.review(tables.propose(code, 2026, "single", values, source)["id"], "verified")
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=jobs-browser")
            page.locator("#nav-documents").click()
            tree = page.locator("#folder-tree")
            tree.locator('[data-folder-group="Jobs"]').click()
            tree.locator('[data-folder-group^="employer-"]').click()
            tree.locator('[data-section="Paystubs"]').click()
            playwright.expect(page.locator("#folder-breadcrumb")).to_have_text("Jobs › Google › Paystubs")
            playwright.expect(page.locator("#documents")).to_contain_text("Paystub 09/15/2026")
            page.goto(f"http://127.0.0.1:{port}/#/documents/{doc['id']}")
            breakdown = page.locator(".paystub-breakdown")
            playwright.expect(breakdown).to_contain_text("FICA (Social Security + Medicare)")
            playwright.expect(breakdown).to_contain_text("is the printed net pay")
            taxes = page.locator(".paystub-taxes")
            playwright.expect(taxes).to_contain_text("Federal income tax")
            playwright.expect(taxes.locator("svg.tax-buckets")).to_have_count(2)
            playwright.expect(taxes).to_contain_text("Georgia income tax")
            playwright.expect(taxes).to_contain_text("Social Security and Medicare (FICA)")
            if os.environ.get("JOBS_SCREENSHOT"):
                page.screenshot(path=os.environ["JOBS_SCREENSHOT"], full_page=True)
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
