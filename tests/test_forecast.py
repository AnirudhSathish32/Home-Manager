"""Deterministic forecast: baseline from the ledger, month-by-month projection, assets and charts."""

from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.api import create_app
from home_manager.charts import compact, forecast_charts, line_chart, nice_ticks
from home_manager.finance import Ledger
from home_manager.finance_tools import FinanceTools
from home_manager.forecast import AssetInput, Assets, ForecastInput, baseline, forecast, project
from home_manager.scanner import ScanLimits
from home_manager.storage import Store

TODAY = date(2026, 9, 25)


def base(**changes):
    value = {"currency": "USD", "cash": 100000, "monthly_income": Decimal(300000), "monthly_spending": {"groceries": Decimal(200000)},
             "assets": [], "balances": [], "notes": [], "history": {"start": "2026-03-01", "end": "2026-08-31", "months": 6, "months_with_data": 6}}
    return {**value, **changes}


def asset(kind, value_minor, rate_bp=0, payment=None, name=None):
    return {"name": name or kind, "kind": kind, "value_minor": value_minor, "annual_rate_bp": rate_bp, "monthly_payment_minor": payment,
            "value": {}, "annual_rate_percent": str(rate_bp / 100), "monthly_payment": None, "currency": "USD"}


def test_projection_matches_hand_calculation_without_inflation():
    loan = asset("loan", 1_000_000, 600, 50_000, "Car loan")
    result = project(base(assets=[asset("vehicle", 2_000_000, -1500, name="Car"), loan]), ForecastInput(years=1, inflation_percent="0"), TODAY)
    first = result["months"][0]
    assert result["start_month"] == "2026-10" and first["month"] == "2026-10"
    # 10,000.00 owed at 6%/12 accrues 50.00, then the 500.00 payment: 9,550.00 left.
    assert (first["income"], first["spending"], first["loan_payments"], first["loans"]) == (300000, 200000, 50000, 955000)
    assert first["cash"] == 100000 + 300000 - 200000 - 50000
    last = result["months"][-1]
    assert last["cash"] == 100000 + 12 * 50000
    assert last["assets"] == 1_700_000  # A car losing 15% a year, compounded monthly, is worth 85% after twelve months.
    owed = 1_000_000
    for _ in range(12):
        owed = owed + int((Decimal(owed) * Decimal(6) / 1200).to_integral_value()) - 50_000
    assert last["loans"] == owed
    assert last["net_worth"] == last["cash"] + last["assets"] - last["loans"] == last["net_worth_today"]
    assert result["years"][0]["year"] == "2026-10 to 2027-09" and result["years"][0]["end_net_worth"] == last["net_worth"]


def test_inflation_raises_spending_and_today_dollars_remove_it():
    result = project(base(), ForecastInput(years=2, inflation_percent="2"), TODAY)
    assert result["months"][11]["spending"] == 204000  # 2,000.00 a month, 2% higher after a year.
    assert result["months"][23]["spending"] == 208080
    assert result["months"][0]["income"] == 300000 and result["months"][23]["income"] == 300000  # Income is flat unless told otherwise.
    month = result["months"][11]
    assert month["net_worth_today"] == int((Decimal(month["net_worth"]) / Decimal("1.02")).to_integral_value())
    assert project(base(), ForecastInput(years=2), TODAY) == project(base(), ForecastInput(years=2), TODAY)  # Deterministic.


def test_adjustments_one_offs_income_changes_and_warnings():
    value = ForecastInput(years=1, inflation_percent="0", income_growth_percent="0",
                          spending_changes=[{"category": "groceries", "percent": "10"}, {"category": "travel", "percent": "5"}],
                          one_offs=[{"month": "2026-12", "amount": "-3000.00", "label": "Vacation"}],
                          income_changes=[{"month": "2027-03", "monthly_amount": "500.00"}])
    result = project(base(), value, TODAY)
    months = {row["month"]: row for row in result["months"]}
    assert months["2026-10"]["spending"] == 220000
    assert months["2026-12"]["one_offs"] == -300000 and months["2026-11"]["one_offs"] == 0
    assert months["2027-02"]["income"] == 300000 and months["2027-03"]["income"] == 350000
    assert any("travel" in note for note in result["notes"])
    short = project(base(cash=0, monthly_income=Decimal(100000)), ForecastInput(years=1, inflation_percent="0"), TODAY)
    assert short["first_month_cash_below_zero"] == "2026-10"
    stuck = project(base(assets=[asset("loan", 1_000_000, 1200, 5_000, "Underpaid loan")]), ForecastInput(years=1, inflation_percent="0"), TODAY)
    assert any("never shrinks" in note for note in stuck["notes"])
    assert len(project(base(), ForecastInput(years=100), TODAY)["months"]) == 1200
    with pytest.raises(ValueError):
        ForecastInput(years=101)
    with pytest.raises(ValueError):
        ForecastInput(inflation_percent="two")


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n", "statement.png": b"statement bytes", "old.png": b"older statement"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def test_baseline_reads_balances_income_categories_and_reviewed_assets(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    card = ledger.create_account("Card Co", "credit_card", "USD", last_four="7314")
    ledger.create_account("Empty Savings", "savings", "USD")
    with store.connection() as db:
        for account, doc, end, closing in ((checking, docs["statement.png"], "2026-08-31", 523456), (card, docs["old.png"], "2026-08-31", 12345)):
            db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_end,closing_balance_minor,currency,review_status,created_at,updated_at) "
                       "VALUES(?,?,?,?,?,?,'USD','verified','t','t')", (account["id"], doc["id"], doc["current_hash"],
                                                                        "credit_card" if account is card else "bank", end, closing))
        rows = [{"posted_date": f"2026-{month:02d}-15", "description": "PAYROLL ACME", "amount_minor": 600000, "currency": "USD", "locator": {"rows": [month]}}
                for month in range(3, 9)]
        rows += [{"posted_date": f"2026-{month:02d}-16", "description": "GROCER", "amount_minor": -30000, "currency": "USD", "locator": {"rows": [month + 20]}}
                 for month in range(3, 9)]
        rows.append({"posted_date": "2026-02-10", "description": "GROCER", "amount_minor": -99999, "currency": "USD", "locator": {"rows": [99]}})  # Outside the window.
        inserted, _ = ledger.insert_transactions(db, checking, rows, "import", {"document_id": docs["export.csv"]["id"], "blob_hash": docs["export.csv"]["current_hash"],
                                                                              "source_key": "import:1", "run_id": "import:1"}, review_status="verified")
    for transaction_id in inserted:
        ledger.set_category(transaction_id, "groceries")
    assets = Assets(store)
    car = assets.add(AssetInput(name="Honda", kind="vehicle", value="18,000.00", currency="usd", as_of="2026-09-01"))
    assert car["annual_rate_percent"] == "-15" and car["review_status"] == "verified" and car["source"] == "manual"
    assets.add(AssetInput(name="House", kind="real_estate", value="350000", currency="USD", as_of="2026-09-01", annual_rate_percent="3"))
    with pytest.raises(ValueError, match="Only loans"):
        AssetInput(name="x", kind="vehicle", value="1", currency="USD", as_of="2026-09-01", monthly_payment="5")
    with store.connection() as db:
        db.execute("INSERT INTO assets(name,kind,value_minor,currency,as_of,source,review_status,created_at,updated_at) "
                   "VALUES('401k from statement','retirement',9000000,'USD','2026-08-31','statement','proposed','t','t')")
    start = baseline(FinanceTools(store), assets, 6, today=TODAY)
    assert start["currency"] == "USD" and start["cash"] == 523456 - 12345  # A card balance is owed.
    assert start["monthly_income"] == 600000
    assert start["monthly_spending"] == {"groceries": Decimal(30000)}
    assert sorted(item["name"] for item in start["assets"]) == ["Honda", "House"]
    assert any("Empty Savings" in note for note in start["notes"]) and any("401k" in note for note in start["notes"])
    result = forecast(store, ForecastInput(years=3), TODAY)
    assert result["starting_point"]["monthly_income"]["display"] == "6,000.00 USD"
    assets.archive(car["id"])
    assert [item["name"] for item in assets.list()] == ["401k from statement", "House"]


def test_charts_are_deterministic_escaped_and_include_zero():
    assert compact(Decimal("1284")) == "1,284" and compact(Decimal("12900")) == "12.9K" and compact(Decimal("-4200000")) == "-4.2M"
    ticks = nice_ticks(Decimal(1200), Decimal(98000))
    assert ticks[0] == 0 and ticks[-1] >= 98000 and len(ticks) <= 7
    result = project(base(assets=[asset("loan", 500000, 500, 20000)]), ForecastInput(years=30), TODAY)
    charts = forecast_charts(result)
    assert charts == forecast_charts(result) and set(charts) == {"net_worth", "cash_flow", "balance_sheet"}
    assert all(svg.startswith("<svg") and "<script" not in svg for svg in charts.values())
    svg = line_chart("A <b>&", "sub", ["2026", "2027"], [{"name": "x<script>", "values": [100, -50000]}], "USD")
    assert "<script>" not in svg and "&lt;script&gt;" in svg and "A &lt;b&gt;&amp;" in svg
    with pytest.raises(ValueError):
        line_chart("t", "s", ["2026"], [{"name": str(n), "values": [1]} for n in range(4)], "USD")


def test_forecast_and_asset_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        added = client.post("/api/assets", json={"name": "Car", "kind": "vehicle", "value": "20000", "currency": "USD", "as_of": "2026-09-01"})
        assert added.status_code == 201
        assert client.post("/api/assets", json={"name": "x", "kind": "spaceship", "value": "1", "currency": "USD", "as_of": "2026-09-01"}).status_code == 422
        loan = client.post("/api/assets", json={"name": "Mortgage", "kind": "loan", "value": "200000", "currency": "USD", "as_of": "2026-09-01",
                                                 "annual_rate_percent": "6.5", "monthly_payment": "1500"}).json()
        assert loan["annual_rate_percent"] == "6.5" and loan["monthly_payment"]["display"] == "1,500.00 USD"
        result = client.post("/api/forecast", json={"years": 40}).json()
        assert len(result["years"]) == 40 and result["charts"]["net_worth"].startswith("<svg")
        assert result["years"][0]["end_assets"] < 2_000_000 and result["years"][-1]["end_loans"] == 0
        assert client.post("/api/forecast", json={"years": 0}).status_code == 422
        assert client.delete(f"/api/assets/{added.json()['id']}").json()["archived"] is True
        assert [item["name"] for item in client.get("/api/assets").json()] == ["Mortgage"]


@pytest.mark.skipif(__import__("os").environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_forecast_page(tmp_path):
    import os
    import socket
    import threading
    import time
    import uvicorn
    playwright = pytest.importorskip("playwright.sync_api")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "forecast-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        app.state.manager.configure(str(tmp_path / "managed"))
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 1000})
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=forecast-test")
            page.locator("#nav-forecast").click()
            playwright.expect(page.locator("#asset-rows")).to_contain_text("No assets or loans yet")
            page.locator("#asset-name").fill("Family car")
            page.locator("#asset-value").fill("18000")
            page.locator("#add-asset").click()
            playwright.expect(page.locator("#asset-rows")).to_contain_text("Family car")
            playwright.expect(page.locator("#asset-rows")).to_contain_text("-15%")
            page.locator("#asset-kind").select_option("loan")
            page.locator("#asset-name").fill("Car loan")
            page.locator("#asset-value").fill("9000")
            page.locator("#asset-rate").fill("6")
            page.locator("#asset-payment").fill("400")
            page.locator("#add-asset").click()
            playwright.expect(page.locator("#asset-rows")).to_contain_text("400.00 USD")
            page.locator("#forecast-years").fill("25")
            page.locator("#add-one-off").click()
            page.locator("#forecast-one-offs input[type=month]").fill("2027-06")
            page.locator("#forecast-one-offs input[inputmode=decimal]").fill("-3000")
            page.locator("#run-forecast").click()
            playwright.expect(page.locator("#forecast-charts svg")).to_have_count(3)
            page.locator("#forecast-charts details summary").first.click()
            playwright.expect(page.locator("#forecast-charts table").first).to_contain_text("USD")
            playwright.expect(page.locator("#forecast-alerts")).to_contain_text("About these numbers")
            if os.environ.get("FORECAST_SCREENSHOT"):
                page.screenshot(path=os.environ["FORECAST_SCREENSHOT"], full_page=True)
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
