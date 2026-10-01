"""Investments (docs/investments.md): kinds as data, values over time, review, totals and the 036 move. Synthetic data only."""

from datetime import date
import sqlite3

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.investments import (
    AccountInput,
    AccountUpdate,
    EventInput,
    HoldingInput,
    IbondRateInput,
    Investments,
    PensionInput,
    ValueInput,
    WithdrawalKind,
    ibond_cash_out,
    ibond_composite_bp,
    ibond_months,
    ibond_value,
    printed_kind,
)
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import MIGRATIONS, Store
from test_extraction import cite, extract, transcribe, value


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"july.png": b"july statement", "august.png": b"august statement", "september.png": b"september statement"})
    try:
        yield store, Investments(store), documents_by_name(store)
    finally:
        store.close()


def statement(docs, name, period_end, value_minor, **changes):
    record = {"investment_kind": "brokerage", "institution": "Vanguard", "account_name": "Brokerage", "last_four": "1111",
              "value_minor": value_minor, "period_end": period_end, "currency": "USD", "issues": [], **changes}
    return record, {"document_id": docs[name]["id"], "blob_hash": docs[name]["current_hash"], "run_id": name}


@pytest.mark.parametrize("printed, kind", [
    ("Fidelity 401(k) Plan", "401k"), ("Roth 401(k)", "401k"), ("Vanguard Roth IRA", "roth_ira"), ("Schwab Rollover IRA", "ira"),
    ("HealthEquity Health Savings Account", "hsa"), ("Ally High-Yield Savings", "hysa"), ("12-Month Certificate of Deposit", "cd"),
    ("TreasuryDirect", "treasury"), ("Series I Savings Bond", "i_bond"), ("Thrift Savings Plan", "retirement"),
    ("Vanguard Federal Money Market", "money_market"), ("my529 plan", "education_529"), ("Individual Brokerage", "brokerage")])
def test_kinds_come_only_from_printed_words(printed, kind):
    assert printed_kind(printed) == kind


def test_statements_add_values_over_time_and_keep_decisions(books):
    store, investments, docs = books
    august = investments.publish_statement(*statement(docs, "august.png", "2026-08-31", 100000))
    assert (august["record_type"], august["status"]) == ("investment_valuation", "published")
    account_id = august["account_id"]
    assert investments.get(account_id)["current"] is None  # Nothing counts until confirmed.
    investments.review(august["id"], "verified")
    september = investments.publish_statement(*statement(docs, "september.png", "2026-09-30", 125000))
    assert september["account_id"] == account_id and september["id"] != august["id"]
    account = investments.get(account_id)
    assert account["current"]["value_minor"] == 100000 and [row["as_of"] for row in account["awaiting_review"]] == ["2026-09-30"]
    investments.review(september["id"], "verified")
    account = investments.get(account_id)
    assert account["current"]["value_minor"] == 125000 and account["change"]["display"] == "250.00 USD" and account["change_since"] == "2026-08-31"
    # An older statement fills in history without changing today's value; nothing is overwritten.
    july = investments.publish_statement(*statement(docs, "july.png", "2026-07-31", 90000))
    assert july["status"] == "history"
    assert [row["as_of"] for row in investments.get(account_id)["history"]] == ["2026-09-30", "2026-08-31", "2026-07-31"]
    # Re-extracting a statement the user decided on keeps the decision; a value the user typed for a date wins over a statement.
    assert investments.publish_statement(*statement(docs, "august.png", "2026-08-31", 1))["status"] == "kept_reviewed"
    investments.record_value(account_id, ValueInput(value="1300", as_of="2026-07-31"))
    assert investments.publish_statement(*statement(docs, "july.png", "2026-07-31", 1))["status"] == "kept_reviewed"
    assert investments.get(account_id)["history"][-1]["value_minor"] == 130000
    with pytest.raises(ValueError, match="values you enter"):
        investments.review(investments.get(account_id)["history"][-1]["id"], "verified")
    # A kind the registry doesn't know lands as Other, waiting for the user to name it.
    stranger = investments.publish_statement(*statement(docs, "august.png", "2026-08-31", 5, investment_kind="timeshare", last_four="9999"))
    assert investments.get(stranger["account_id"])["kind"] == "other"
    assert [row["name"] for row in investments.pending()] == ["Vanguard Brokerage 9999"]


def test_accounts_totals_shares_and_settings(books):
    store, investments, docs = books
    retirement = investments.add(AccountInput(name="Work 401(k)", kind="401k", institution="Fidelity", currency="usd", value="60000", as_of="2026-09-01"))
    savings = investments.add(AccountInput(name="Rainy day", kind="hysa", currency="USD", value="30000", as_of="2026-09-01", annual_rate_percent="4.25"))
    investments.add(AccountInput(name="12-month CD", kind="cd", currency="USD", value="10000", as_of="2026-09-01"))
    assert retirement["current"]["value"]["display"] == "60,000.00 USD" and retirement["rate_is_default"] and retirement["tax_label"] == "Tax-deferred"
    assert savings["annual_rate_percent"] == "4.25" and savings["value_model"] == "cash"
    summary = investments.summary()
    [total] = summary["totals"]
    assert total["total"]["display"] == "100,000.00 USD" and total["oldest_as_of"] == "2026-09-01"
    assert [(row["key"], row["share_percent"]) for row in total["sections"]] == [("retirement", "60.0"), ("cash", "30.0"), ("fixed_income", "10.0")]
    assert [(row["key"], row["share_percent"]) for row in total["tax"]] == [("taxable", "40.0"), ("tax_deferred", "60.0")]
    # Reclassifying and overriding tax treatment are settings; the kind's defaults apply when left blank.
    changed = investments.update(retirement["id"], AccountUpdate(name="Roth 401(k)", kind="401k", institution="Fidelity", tax_treatment="tax_free", annual_rate_percent="7"))
    assert (changed["tax_treatment"], changed["tax_overridden"], changed["annual_rate_percent"]) == ("tax_free", True, "7")
    with pytest.raises(ValueError, match="investment kind"):
        investments.update(retirement["id"], AccountUpdate(name="x", kind="spaceship"))
    with pytest.raises(ValueError, match="Choose one of"):
        AccountUpdate(name="x", kind="401k", tax_treatment="offshore")
    investments.archive(savings["id"])
    assert investments.summary()["totals"][0]["total"]["display"] == "70,000.00 USD"
    assert "cd" in {kind["key"] for kind in investments.kinds()} and investments.kinds()[-1]["key"] == "other"
    assert {asset["name"]: asset["annual_rate_bp"] for asset in investments.forecast_assets()} == {"Roth 401(k)": 700, "12-month CD": 0}


def test_migration_moves_investment_assets_and_keeps_their_values():
    db = sqlite3.connect(":memory:")
    for number, script in MIGRATIONS:
        if number == 36:  # Values recorded as forecast assets, just before investments had their own tables.
            db.executemany("INSERT INTO assets(id,name,kind,value_minor,currency,as_of,annual_rate_bp,source,review_status,account_key,created_at,updated_at) "
                           "VALUES(?,?,?,?,'USD','2026-08-31',?,?,?,?,'t','t')", [
                               (1, "Vanguard Brokerage 1111", "investment", 100000, 0, "statement", "verified", "investment|VANGUARD|1111|USD"),
                               (2, "Old 401k", "retirement", 500000, 600, "manual", "verified", None),
                               (3, "Car", "vehicle", 900000, -1500, "manual", "verified", None)])
        db.executescript(script.read_text())
    assert db.execute("SELECT name FROM assets").fetchall() == [("Car",)]
    assert db.execute("SELECT id,kind,account_key,annual_rate_bp FROM investment_accounts ORDER BY id").fetchall() == [
        (1, "brokerage", "VANGUARD|1111|USD", None), (2, "retirement", None, 600)]
    assert db.execute("SELECT account_id,value_minor,review_status,legacy_asset_id FROM investment_valuations ORDER BY id").fetchall() == [
        (1, 100000, "verified", 1), (2, 500000, "verified", 2)]
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("INSERT INTO investment_kinds(key,label,section,tax_treatment,value_model,position) VALUES('Bad Key','x','other','taxable','market',1)")


def test_investment_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        assert any(kind["key"] == "hsa" for kind in client.get("/api/investment-kinds").json())
        added = client.post("/api/investments", json={"name": "HSA", "kind": "hsa", "currency": "USD", "value": "4200", "as_of": "2026-09-01"})
        assert added.status_code == 201 and added.json()["section_label"] == "Health savings"
        account_id = added.json()["id"]
        assert client.post("/api/investments", json={"name": "x", "kind": "spaceship", "currency": "USD", "value": "1", "as_of": "2026-09-01"}).status_code == 400
        assert client.post("/api/investments", json={"name": "x", "kind": "hsa", "currency": "USD", "value": "1", "as_of": "2026-02-30"}).status_code == 422
        recorded = client.post(f"/api/investments/{account_id}/values", json={"value": "4500", "as_of": "2026-09-28"}).json()
        assert recorded["current"]["value"]["display"] == "4,500.00 USD" and recorded["change"]["display"] == "300.00 USD"
        assert client.put(f"/api/investments/{account_id}", json={"name": "Family HSA", "kind": "hsa"}).json()["name"] == "Family HSA"
        assert client.get("/api/investments").json()["totals"][0]["total"]["display"] == "4,500.00 USD"
        assert client.get("/api/investments/review").json() == []
        assert client.delete(f"/api/investments/{account_id}").json()["archived"] is True
        assert client.get("/api/investments").json()["accounts"] == []
        assert client.get("/investments.js").status_code == 200


IRA = ["VANGUARD", "Rollover IRA account ending 4321", "Statement date 2026-09-30", "Currency USD", "Ending account value $15,000.00",
       "VTSAX Total Stock Mkt Idx 80.000 $125.00 $10,000.00 cost $8,000.00", "Ally CD 4.10% due 2027-03-31 $5,000.00",
       "2026-09-15 Contribution $500.00", "2026-09-20 Dividend VTSAX $42.10"]


def row(row_type, description, number, **fields):
    empty = {"identifier": None, "instrument_class": None, "activity_type": None, "contribution_source": None, "date": None, "quantity": None,
             "price": None, "amount": None, "cost_basis": None, "rate": None, "maturity_date": None}
    return {"row_type": row_type, "description": description, **empty, **fields, "evidence": cite(number, IRA[number - 1])}


def ira_outputs():
    summary = {"institution": value("Vanguard", 1, IRA[0]), "account_name": value("Rollover IRA", 2, IRA[1]), "account_reference": value("4321", 2, IRA[1]),
               "period_end": value("2026-09-30", 3, IRA[2]), "ending_value": value("15,000.00", 5, IRA[4]), "currency": value("USD", 4, IRA[3])}
    classified = {"document_type": "investment_statement", "evidence": cite(1, IRA[0]), "issuer": value("Vanguard", 1, IRA[0]),
                  "document_date": value("2026-09-30", 3, IRA[2])}
    entries = [row("holding", "Total Stock Mkt Idx", 6, identifier="VTSAX", instrument_class="mutual_fund", quantity="80.000", price="125.00",
                   amount="10,000.00", cost_basis="8,000.00"),
               row("holding", "Ally CD", 7, instrument_class="cd", amount="5,000.00", rate="4.10%", maturity_date="2027-03-31"),
               row("activity", "Contribution", 8, activity_type="contribution", contribution_source="personal", date="2026-09-15", amount="500.00"),
               row("activity", "Dividend VTSAX", 9, identifier="VTSAX", activity_type="dividend", date="2026-09-20", amount="42.10")]
    return [classified, summary, {"entries": entries}]


def test_a_statement_records_holdings_and_activity_that_follow_its_review(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, IRA)
    try:
        local_model["outputs"] = ira_outputs()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        publication = run["publication"]
        assert (publication["record_type"], publication["holdings"], publication["activity"]) == ("investment_valuation", 2, 2)
        investments = Investments(manager.store)
        assert investments.valuation(publication["id"])["issues"] == []  # The holdings reach the ending value.
        account = investments.get(publication["account_id"])
        assert (account["kind"], account["holdings_as_of"]) == ("ira", "2026-09-30")
        fund, cd = account["holdings"]
        assert (fund["identifier"], fund["class_label"], fund["quantity"], fund["price"]["display"], fund["gain"]["display"]) == (
            "VTSAX", "Mutual fund", "80.000", "125.00 USD", "2,000.00 USD")
        assert (cd["rate_percent"], cd["maturity_date"], cd["gain"]) == ("4.1", "2027-03-31", None)
        dividend, contribution = account["events"]
        assert (contribution["type_label"], contribution["source_label"], contribution["amount"]["display"]) == ("Contribution", "From you", "500.00 USD")
        assert dividend["holding_id"] == fund["id"] and {event["review_status"] for event in account["events"]} == {"proposed"}
        assert investments.pending()[0]["holding_count"] == 2 and investments.pending()[0]["activity_count"] == 2
        # Confirming the value confirms what the statement listed; a re-extraction keeps the decision and adds nothing.
        investments.review(publication["id"], "verified")
        account = investments.get(publication["account_id"])
        assert {holding["review_status"] for holding in account["holdings"]} == {"verified"} and {event["review_status"] for event in account["events"]} == {"verified"}
        local_model["outputs"] = ira_outputs()
        again = extract(manager, doc, parse_id, force=True)
        assert again["publication"]["status"] == "kept_reviewed" and len(investments.get(publication["account_id"])["events"]) == 2
    finally:
        manager.close()


def test_investment_rows_keep_only_what_is_printed():
    from home_manager.core.money import to_minor
    from home_manager.documents.extraction import InvestmentLine, investment_rows
    issues, record = [], {"value_minor": 1000000, "cross_checks": 0}
    rows = [InvestmentLine.model_validate(row("holding", "Total Stock Mkt Idx", 6, identifier="VFIAX", quantity="99", amount="10,000.00")),
            InvestmentLine.model_validate(row("activity", "Contribution", 8, activity_type="contribution", contribution_source="employer", amount="500.00"))]
    investment_rows(record, rows, lambda text, what, magnitude=False: None if text is None else abs(to_minor(text, "USD")) if magnitude else to_minor(text, "USD"),
                    issues, "USD", lambda values: None if None in values else sum(values))
    [holding] = record["holdings"]
    assert (holding["identifier"], holding["quantity"], holding["instrument_class"]) == (None, None, "other")  # Neither is printed on its line.
    assert record["activity"] == [] and record["cross_checks"] == 1
    assert any("quantity is not printed" in issue for issue in issues) and any("Activity 2" in issue for issue in issues)


def test_a_linked_savings_account_reads_its_statements_and_leaves_cash(books):
    from home_manager.finance.forecast import Assets, baseline
    from home_manager.finance.ledger import Ledger
    from home_manager.finance.tools import FinanceTools
    store, investments, docs = books
    ledger = Ledger(store)
    savings = ledger.create_account("Ally", "savings", "USD", last_four="5555")
    card = ledger.create_account("Card Co", "credit_card", "USD", last_four="7314")
    with store.connection() as db:
        for name, end, closing, status in (("august.png", "2026-08-31", 1500000, "verified"), ("september.png", "2026-09-30", 1505000, "needs_review")):
            db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_end,closing_balance_minor,currency,review_status,created_at,updated_at) "
                       "VALUES(?,?,?,'bank',?,?,'USD',?,'t','t')", (savings["id"], docs[name]["id"], docs[name]["current_hash"], end, closing, status))
        db.execute("INSERT INTO transactions(account_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,source_fingerprint,created_at,updated_at) "
                   "VALUES(?,'2026-08-31','INTEREST PAID',5000,'USD','interest','manual','verified','f1','t','t')", (savings["id"],))
    rainy = investments.add(AccountInput(name="Rainy day", kind="hysa", currency="USD", value="100", as_of="2026-06-30", ledger_account_id=savings["id"]))
    assert rainy["ledger_account_name"] and [option["id"] for option in rainy["linkable_accounts"]] == [savings["id"]]
    assert rainy["current"]["value"]["display"] == "15,000.00 USD" and rainy["current"]["source"] == "ledger_statement"
    assert [row["as_of"] for row in rainy["awaiting_review"]] == ["2026-09-30"] and investments.pending() == []  # Reviewed as a statement.
    assert [row["as_of"] for row in rainy["history"]] == ["2026-09-30", "2026-08-31", "2026-06-30"]
    assert [(event["type_label"], event["amount"]["display"]) for event in rainy["events"]] == [("Interest", "50.00 USD")]
    with pytest.raises(ValueError, match="cards and loans"):
        investments.update(rainy["id"], AccountUpdate(name="Rainy day", kind="hysa", ledger_account_id=card["id"]))
    with pytest.raises(ValueError, match="already linked"):
        investments.add(AccountInput(name="Twin", kind="hysa", currency="USD", value="1", as_of="2026-06-30", ledger_account_id=savings["id"]))
    start = baseline(FinanceTools(store), Assets(store), 6, today=date(2026, 9, 28))
    assert [row["account"] for row in start["balances"]] == [] and [asset["name"] for asset in start["assets"]] == ["Rainy day"]
    # Unlinked, the savings balance is cash again and the account keeps only its own values.
    investments.update(rainy["id"], AccountUpdate(name="Rainy day", kind="hysa"))
    assert investments.get(rainy["id"])["current"]["value"]["display"] == "100.00 USD"
    assert "Ally" in " ".join(row["account"] for row in baseline(FinanceTools(store), Assets(store), 6, today=date(2026, 9, 28))["balances"])


@pytest.mark.skipif(__import__("os").environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_investments_page(tmp_path):
    import os
    import socket
    import threading
    import time

    import uvicorn
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "investments-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        app.state.manager.configure(str(tmp_path / "managed"))
        investments = Investments(app.state.manager.store)
        investments.add(AccountInput(name="Work 401(k)", kind="401k", institution="Fidelity", currency="USD", value="60000", as_of="2026-08-31"))
        cds = investments.add(AccountInput(name="12-month CD", kind="cd", institution="Ally", currency="USD", value="10000", as_of="2026-09-01", annual_rate_percent="4.1"))
        # A CD coming due within the page's 90 days, whatever day the test runs.
        today = date.today()
        investments.add_holding(cds["id"], HoldingInput(name="Ally 12-month CD", instrument_class="cd", principal="10000", annual_rate_percent="4.10",
                                                        issue_date=date.fromordinal(today.toordinal() - 335).isoformat(),
                                                        maturity_date=date.fromordinal(today.toordinal() + 30).isoformat()))
        inbox_scan(app.state.manager.store, {"ira.png": b"ira statement", "form.png": b"tax form"})
        docs = documents_by_name(app.state.manager.store)
        form = investments.publish_tax_form({"institution": "Chase", "last_four": "9999", "tax_year": today.year - 1, "currency": "USD", "issues": [],
                                             "boxes": [{"form": "1099-INT", "box": "1", "label": "Interest income", "amount_minor": 1200, "locator": {}}]},
                                            {"document_id": docs["form.png"]["id"], "blob_hash": docs["form.png"]["current_hash"], "run_id": "f"})
        investments.review_tax_form(form["id"], "verified")
        # Someone old enough for required distributions, with a traditional IRA valued at the end of last year.
        from home_manager.finance.ledger import HouseholdConfig
        app.state.manager.configure_household(HouseholdConfig(birth_year=today.year - 80))
        investments.add(AccountInput(name="Traditional IRA", kind="ira", institution="Schwab", currency="USD", value="50000", as_of=f"{today.year - 1}-12-31"))
        record, source = statement(documents_by_name(app.state.manager.store), "ira.png", "2026-09-30", 1500000, investment_kind="ira", account_name="Rollover IRA")
        record["holdings"] = [{"name": "Total Stock Market Index Admiral", "identifier": "VTSAX", "instrument_class": "mutual_fund", "quantity": "80.000",
                               "value_minor": 1000000, "price_minor": 12500, "cost_basis_minor": 800000},
                              {"name": "Ally 12-month CD", "instrument_class": "cd", "value_minor": 500000, "rate_bp": 410, "maturity_date": "2027-03-31"}]
        record["activity"] = [{"name": "Contribution", "event_date": "2026-09-15", "event_type": "contribution", "contribution_source": "personal", "amount_minor": 50000}]
        ira = investments.publish_statement(record, source)
        # Phase 4 kinds: I bonds over the yearly limit, a pension's terms, and a 529 with a withdrawal not yet marked.
        bonds = investments.add(AccountInput(name="TreasuryDirect", kind="i_bond", currency="USD", value="0", as_of="2024-01-01"))
        for name, principal, issued in (("I bond Jan 2024", "10000", "2024-01-20"), ("I bond Mar 2024", "500", "2024-03-01")):
            investments.add_holding(bonds["id"], HoldingInput(name=name, instrument_class="i_bond", principal=principal, issue_date=issued))
        pension = investments.add(AccountInput(name="State pension", kind="pension", currency="USD"))
        investments.set_pension(pension["id"], PensionInput(monthly_benefit="2400", start_date="2040-06-01", cola_percent="2", survivor_percent=50, lump_sum="350000"))
        plan = investments.add(AccountInput(name="Maya 529", kind="education_529", currency="USD", value="40000", as_of="2026-01-01", beneficiary="Maya", plan_state="UT"))
        investments.add_event(plan["id"], EventInput(event_type="withdrawal", event_date=f"{today.year - 1}-09-10", amount="2000"))
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1366, "height": 900})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=investments-test")
            page.locator("#nav-investments").click()
            # The CD account counts at its estimate for today, so the shares move with the date; the split is still shown.
            playwright.expect(page.locator("#investments-summary")).to_contain_text("Tax-deferred")
            playwright.expect(page.locator("#investments-summary")).to_contain_text("Coming due")
            playwright.expect(page.locator("#investments-summary")).to_contain_text("Ally 12-month CD")
            playwright.expect(page.locator("#investments-taxes")).to_contain_text("Chase 1099-INT")
            playwright.expect(page.locator("#investments-taxes")).to_contain_text("No account")
            playwright.expect(page.locator("#investments-rmd")).to_contain_text("Required minimum distributions")
            playwright.expect(page.locator("#investments-rmd")).to_contain_text("Traditional IRA")
            page.locator("#investment-name").fill("Rainy day")
            page.locator("#investment-kind").select_option("hysa")
            page.locator("#investment-value").fill("15000")
            page.locator("#investment-rate").fill("4.25")
            page.locator("#add-investment").click()
            playwright.expect(page.locator("#investment-detail")).to_contain_text("High-yield savings")
            assert "account=" in page.url
            playwright.expect(page.locator("#investments-groups")).to_contain_text("Cash and savings")
            if os.environ.get("INVESTMENTS_SCREENSHOT"):
                page.screenshot(path=os.environ["INVESTMENTS_SCREENSHOT"], full_page=True)
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            # A statement's holdings and activity, waiting for review with its value.
            page.set_viewport_size({"width": 1366, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/#/investments?account={ira['account_id']}")
            playwright.expect(page.locator("#investment-detail")).to_contain_text("Holdings on Sep 30, 2026")
            playwright.expect(page.locator("#investment-detail")).to_contain_text("2,000.00")
            playwright.expect(page.locator("#investment-detail")).to_contain_text("Contribution · From you")
            if os.environ.get("INVESTMENTS_SCREENSHOT"):
                page.locator("#investment-detail").screenshot(path=os.environ["INVESTMENTS_SCREENSHOT"].replace(".png", "-detail.png"))
            for width in (390, 768):
                page.set_viewport_size({"width": width, "height": 900})
                # The signed gain column's screen-reader text once widened the page from inside its scrolling table.
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            # The CD account: its value estimated from the CD's terms, the add-a-CD form, and its maturity.
            page.set_viewport_size({"width": 1366, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/#/investments?account={cds['id']}")
            playwright.expect(page.locator("#investment-detail")).to_contain_text("estimated from its holdings' terms")
            playwright.expect(page.locator("#investment-detail")).to_contain_text("At maturity")
            page.locator("#investment-detail summary", has_text="Add a CD or Treasury").click()
            if os.environ.get("INVESTMENTS_SCREENSHOT"):
                page.screenshot(path=os.environ["INVESTMENTS_SCREENSHOT"].replace(".png", "-cd.png"), full_page=True)
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            # Home lists the CD coming due beside the bills.
            page.set_viewport_size({"width": 1366, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/#/home")
            playwright.expect(page.locator("#home-content")).to_contain_text("CDs and Treasuries coming due")
            if os.environ.get("INVESTMENTS_SCREENSHOT"):
                page.screenshot(path=os.environ["INVESTMENTS_SCREENSHOT"].replace(".png", "-home.png"), full_page=True)
            for width in (390, 768):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            # I bonds: the yearly limit, what each pays if cashed today, and the rates they follow.
            page.set_viewport_size({"width": 1366, "height": 900})
            page.goto(f"http://127.0.0.1:{port}/#/investments?account={bonds['id']}")
            detail = page.locator("#investment-detail")
            playwright.expect(detail).to_contain_text("more than the 10,000.00 USD")
            playwright.expect(detail).to_contain_text("If cashed today")
            detail.locator("summary", has_text="I bond rates").click()
            playwright.expect(detail).to_contain_text("Composite for new bonds")
            # The pension: an income from its terms, never a balance; the 529: its beneficiary and a withdrawal to mark.
            page.goto(f"http://127.0.0.1:{port}/#/investments?account={pension['id']}")
            playwright.expect(detail).to_contain_text("2,400.00 USD a month from")
            playwright.expect(detail).to_contain_text("not counted in totals")
            playwright.expect(page.locator("#investments-groups")).to_contain_text("Pays an income")
            page.goto(f"http://127.0.0.1:{port}/#/investments?account={plan['id']}&year={today.year - 1}")
            playwright.expect(detail).to_contain_text("Maya")
            playwright.expect(page.locator("#investments-taxes")).to_contain_text("isn't marked qualified or not yet")
            if os.environ.get("INVESTMENTS_SCREENSHOT"):
                page.screenshot(path=os.environ["INVESTMENTS_SCREENSHOT"].replace(".png", "-529.png"), full_page=True)
            for width in (390, 768, 1440):
                page.set_viewport_size({"width": width, "height": 900})
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), width
            page.set_viewport_size({"width": 1366, "height": 900})
            detail.get_by_role("button", name="Not qualified").click()
            playwright.expect(detail).to_contain_text("Non-qualified withdrawal")
            for account_id in (bonds["id"], pension["id"]):
                page.goto(f"http://127.0.0.1:{port}/#/investments?account={account_id}")
                playwright.expect(detail).to_contain_text("Kind")
                for width in (390, 768, 1440):
                    page.set_viewport_size({"width": width, "height": 900})
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (account_id, width)
                page.set_viewport_size({"width": 1366, "height": 900})
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True


# Phase 4 (docs/investments-next.md): I bonds, 529 plans, pensions and the new tax forms ---------------------------------------
RATES = [{"period_start": "2023-11-01", "fixed_bp": 130, "inflation_semiannual_bp": 197},
         {"period_start": "2024-05-01", "fixed_bp": 130, "inflation_semiannual_bp": 148},
         {"period_start": "2024-11-01", "fixed_bp": 120, "inflation_semiannual_bp": 95}]


@pytest.mark.parametrize("fixed, inflation, composite", [(130, 197, 527), (130, 148, 428), (120, 95, 311), (0, 481, 962), (40, 324, 689),
                                                         (90, 167, 426), (0, -80, 0)])
def test_ibond_composite_rates_match_treasurydirects_published_ones(fixed, inflation, composite):
    # TreasuryDirect's announced composites: Nov 2023 5.27%, May 2024 4.28%, Nov 2024 3.11%, May 2022 9.62%, Nov 2022 6.89%,
    # May 2026 4.26%; and May 2015's deflation floors at zero.
    assert ibond_composite_bp(fixed, inflation) == composite


def test_ibond_value_follows_treasurydirects_method():
    # $10,000 bought in January 2024 at 5.27%: a $25 bond is worth 25 × 1.02635 = $25.66 after six months, so $10,264.00.
    assert ibond_value(1_000_000, "2024-01-20", "2024-07-01", RATES) == 1_026_400
    # Interest is added on the first of each month: three months in, $25 × 1.02635^(1/2) = $25.33.
    assert ibond_value(1_000_000, "2024-01-20", "2024-04-30", RATES) == 1_013_200
    # The second period earns the fixed 1.30% with May 2024's inflation: 4.28%, so $25.66 × 1.0214 = $26.21.
    assert ibond_value(1_000_000, "2024-01-20", "2025-01-01", RATES) == 1_048_400
    assert ibond_value(1_000_000, "2022-01-01", "2024-07-01", RATES) is None  # No rate for its issue month.
    assert ibond_months("2024-01-20", "2084-01-01") == 360  # Interest stops after 30 years.


def test_ibond_cash_out_loses_three_months_before_five_years():
    assert ibond_cash_out(1_000_000, "2024-01-20", "2024-12-31", RATES) is None  # Locked for 12 months.
    assert ibond_cash_out(1_000_000, "2024-01-20", "2025-01-01", RATES) == ibond_value(1_000_000, "2024-01-20", "2024-10-01", RATES)
    before, after = "2028-12-15", "2029-01-02"  # 59 and 60 months.
    assert ibond_cash_out(1_000_000, "2024-01-20", before, RATES) == ibond_value(1_000_000, "2024-01-20", "2028-09-01", RATES)
    assert ibond_cash_out(1_000_000, "2024-01-20", after, RATES) == ibond_value(1_000_000, "2024-01-20", after, RATES)


def test_an_ibond_holding_is_valued_from_the_published_rates_and_warns_over_10k(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        investments = Investments(store, today=date(2024, 7, 15))
        account = investments.add(AccountInput(name="TreasuryDirect", kind="i_bond", currency="USD", value="0", as_of="2024-01-01"))
        added = investments.add_holding(account["id"], HoldingInput(name="I bond Jan 2024", instrument_class="i_bond", principal="10000", issue_date="2024-01-20"))
        [bond] = added["holdings"]
        assert bond["value_minor"] == 1_026_400 and bond["maturity_date"] == "2054-01-01" and bond["redeemable_date"] == "2025-01-20"
        assert bond["rate_percent"] == "4.28" and bond["at_maturity"] is None and bond["cash_out"] is None  # Earning May 2024's rate; still locked.
        assert added["current"]["value_minor"] == 1_026_400 and added["current"]["source"] == "estimated"
        assert added["ibond_warnings"] == []
        more = investments.add_holding(account["id"], HoldingInput(name="I bond Mar 2024", instrument_class="i_bond", principal="500", issue_date="2024-03-01"))
        [warning] = more["ibond_warnings"]
        assert warning["year"] == 2024 and warning["total"]["display"] == "10,500.00 USD"
        assert investments.summary()["ibond_warnings"] == [warning]
        assert investments.ibond_rate_table()[0]["period_start"] == "2026-05-01"
        # A rate the user adds moves values at once.
        before = Investments(store, today=date(2027, 4, 15)).get(account["id"])["current"]["value_minor"]
        investments.set_ibond_rate(IbondRateInput(period_start="2026-11-01", fixed_percent="1.00", inflation_percent="3.00"))
        later = Investments(store, today=date(2027, 4, 15)).get(account["id"])
        assert later["current"]["value_minor"] > before and later["holdings"][0]["cash_out"] is not None
    finally:
        store.close()


def test_a_pension_is_an_income_stream_not_a_balance(books):
    store, investments, docs = books
    pension = investments.add(AccountInput(name="State pension", kind="pension", currency="USD"))
    assert pension["is_income"] and pension["current"] is None and pension["pension"] is None
    with pytest.raises(ValueError, match="value and its date"):
        investments.add(AccountInput(name="Brokerage", kind="brokerage", currency="USD"))
    termed = investments.set_pension(pension["id"], PensionInput(monthly_benefit="2400", start_date="2040-06-01", cola_percent="2",
                                                                 survivor_percent=50, lump_sum="350000"))
    assert termed["pension"]["monthly_benefit"]["display"] == "2,400.00 USD" and termed["pension"]["lump_sum"]["display"] == "350,000.00 USD"
    investments.record_value(pension["id"], ValueInput(value="350000", as_of="2026-09-01"))  # Even a typed value isn't a balance.
    investments.add(AccountInput(name="Brokerage", kind="brokerage", currency="USD", value="1000", as_of="2026-09-01"))
    assert investments.summary()["totals"][0]["total"]["display"] == "1,000.00 USD"
    assert [asset["name"] for asset in investments.forecast_assets()] == ["Brokerage"]
    assert investments.forecast_pensions() == [{"label": "State pension", "currency": "USD", "monthly_amount": "2400.00", "start_month": "2040-06",
                                                "cola_percent": "2", "taxed": True}]
    assert investments.required_distributions(2040, 1950)["accounts"] == []
    brokerage = next(account for account in investments.summary()["accounts"] if account["kind"] == "brokerage")
    with pytest.raises(ValueError, match="Only a pension"):
        investments.set_pension(brokerage["id"], PensionInput(monthly_benefit="1", start_date="2040-01-01"))


def tax_form(investments, docs, name, institution, year, boxes):
    record = {"institution": institution, "last_four": None, "tax_year": year, "currency": "USD", "issues": [],
              "boxes": [{"form": form, "box": box, "label": box, "amount_minor": amount, "locator": {}} for form, box, amount in boxes]}
    form = investments.publish_tax_form(record, {"document_id": docs[name]["id"], "blob_hash": docs[name]["current_hash"], "run_id": name})
    investments.review_tax_form(form["id"], "verified")
    return form


def test_529_withdrawals_1099q_check_and_taxable_earnings(books):
    store, investments, docs = books
    plan = investments.add(AccountInput(name="Maya 529", kind="education_529", institution="my529", currency="USD", value="40000",
                                        as_of="2026-01-01", beneficiary="Maya", plan_state="ut"))
    assert (plan["beneficiary"], plan["plan_state"], plan["is_education"]) == ("Maya", "UT", True)
    investments.add_event(plan["id"], EventInput(event_type="qualified_withdrawal", event_date="2026-08-20", amount="6000", note="Fall tuition"))
    investments.add_event(plan["id"], EventInput(event_type="withdrawal", event_date="2026-09-10", amount="2000"))
    unmarked = next(event for event in investments.get(plan["id"])["events"] if event["event_type"] == "withdrawal")
    assert investments.tax_year(2026)["education"][0]["unmarked"]["display"] == "2,000.00 USD"
    investments.classify_withdrawal(unmarked["id"], WithdrawalKind(qualified=False))
    tax_form(investments, docs, "july.png", "my529", 2026, [("1099-Q", "1", 800000), ("1099-Q", "2", 200000), ("1099-Q", "3", 600000)])
    year = investments.tax_year(2026)
    [check] = [check for check in year["checks"] if check["forms"] == ["1099-Q"]]
    assert (check["label"], check["form_amount"]["display"], check["matches"]) == ("Withdrawals", "8,000.00 USD", True)
    [education] = year["education"]
    # $2,000 non-qualified × 25% earnings (box 2 $2,000 of box 1 $8,000) = $500 taxed as income.
    assert education["taxable_earnings"]["display"] == "500.00 USD" and education["earnings_share_percent"] == "25.0" and education["unmarked"] is None
    brokerage = investments.add(AccountInput(name="Brokerage", kind="brokerage", currency="USD", value="1", as_of="2026-01-01"))
    with pytest.raises(ValueError, match="Only a 529"):
        investments.add_event(brokerage["id"], EventInput(event_type="qualified_withdrawal", event_date="2026-08-20", amount="1"))


def test_1099da_proceeds_and_cost_are_checked_against_crypto_lots(books):
    store, investments, docs = books
    wallet = investments.add(AccountInput(name="Coinbase", kind="crypto", institution="Coinbase", currency="USD", value="1", as_of="2026-01-01"))
    with store.connection() as db:
        holding = db.execute("INSERT INTO holdings(account_id,instrument_class,name,identifier,holding_key,source,created_at,updated_at) "
                             "VALUES(?,'crypto','Bitcoin','BTC','id:BTC','manual','t','t')", (wallet["id"],)).lastrowid
        for day, kind, amount, units in (("2025-03-01", "buy", 300000, "0.1"), ("2026-05-01", "sell", 450000, "0.1")):
            db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,quantity,review_status,created_at) "
                       "VALUES(?,?,?,?,?,?,'verified','t')", (wallet["id"], holding, day, kind, amount, units))
    tax_form(investments, docs, "august.png", "Coinbase", 2026, [("1099-DA", "1f", 450000), ("1099-DA", "1g", 300000)])
    year = investments.tax_year(2026)
    checks = {check["label"]: check for check in year["checks"]}
    assert checks["Sale proceeds"]["matches"] and checks["Cost of shares sold"]["matches"]
    assert year["gains"][0]["long"]["display"] == "1,500.00 USD"
