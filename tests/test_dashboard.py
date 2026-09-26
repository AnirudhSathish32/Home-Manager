from datetime import date

from fastapi.testclient import TestClient

from home_manager.api import create_app
from home_manager.dashboard import dashboard
from home_manager.finance_tools import FinanceTools, TransactionsInput
from home_manager.scanner import ScanLimits
from test_reconcile_tools import books, add, receipt


def test_dashboard_totals_categories_series_and_drilldowns(books):
    store, ledger, docs = books
    account = ledger.create_account("Local Bank", "checking", "USD")
    ids = add(store, ledger, account, docs["export.csv"], [
        ("2026-08-01", "SHOP", -2000), ("2026-08-28", "AFTER COMPARISON", -9900),
        ("2026-09-01", "SHOP", -5000), ("2026-09-03", "REFUND SHOP", 1000),
        ("2026-09-02", "PAYROLL", 20000), ("2026-09-26", "FUTURE SHOP", -9900)])
    with store.connection() as db:
        db.execute("UPDATE transactions SET transaction_type='refund' WHERE id=?", (ids[3],))
        db.execute("UPDATE transactions SET category='groceries' WHERE id=?", (ids[2],))
    pending = add(store, ledger, account, docs["export.csv"], [("2026-09-10", "PENDING", -500)], origin="extraction")
    receipt(ledger, docs["receipt.png"], "Unmatched cafe", "2026-09-10", 2500)
    result = dashboard(store, "2026-09", today=date(2026, 9, 25))
    assert result["totals"]["net_spending"]["minor"] == 4000
    assert result["gross"]["minor"] == 5000
    assert result["cashflow"]["inflow"]["minor"] == 20000
    assert result["cashflow"]["net"]["minor"] == 16000
    assert result["comparison"]["first"]["minor"] == 2000
    assert result["comparison"]["change"]["minor"] == 2000
    assert result["series"][-1]["totals"]["net_spending"]["minor"] == 4000
    assert result["series"][0]["totals"] is None
    assert result["series"][-1]["partial"] is True
    assert result["attention"]["unmatched"]["total"]["minor"] == 2500
    assert abs(result["pending"]["amount"]["minor"]) == 500
    category = result["categories"][0]
    assert (category["category"], category["share"]) == ("groceries", "100.0")
    rows = FinanceTools(store).get_transactions(TransactionsInput(start="2026-09-01", end="2026-09-25", currency="USD", metric="categories", categories=category["members"]))
    assert [row["id"] for row in rows["transactions"]] == [ids[2]]
    assert pending[0] not in [row["id"] for row in rows["transactions"]]


def test_dashboard_other_uncategorized_and_currency_separation(books):
    store, ledger, docs = books
    account = ledger.create_account("USD Bank", "checking", "USD")
    ids = add(store, ledger, account, docs["export.csv"], [("2026-09-01", f"SHOP {index}", -(index + 1) * 100) for index in range(8)])
    with store.connection() as db:
        for index, transaction_id in enumerate(ids[:-1]):
            db.execute("UPDATE transactions SET category=? WHERE id=?", (f"category {index}", transaction_id))
        db.execute("UPDATE transactions SET currency='EUR' WHERE id=?", (ids[0],))
    result = dashboard(store, "2026-09", currency="USD", today=date(2026, 9, 25))
    assert result["currencies"] == ["EUR", "USD"]
    assert result["gross"]["minor"] == 3500
    assert {row["category"] for row in result["categories"]} >= {"Other", "uncategorized"}
    assert sum(row["spending"]["minor"] for row in result["categories"]) == result["gross"]["minor"]
    other = next(row for row in result["categories"] if row["category"] == "Other")
    rows = FinanceTools(store).get_transactions(TransactionsInput(currency="USD", metric="categories", categories=other["members"]))
    assert -sum(row["amount_minor"] for row in rows["transactions"]) == other["spending"]["minor"]
    euro = dashboard(store, "2026-09", currency="EUR", today=date(2026, 9, 25))
    assert euro["totals"]["net_spending"]["minor"] == 100


def test_dashboard_api_auth_and_empty_state(tmp_path):
    app = create_app(tmp_path / "control", "token", limits=ScanLimits(stability_seconds=0))
    source = tmp_path / "source"
    source.mkdir()
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        app.state.manager.configure(str(tmp_path / "managed"))
        url = f"/api/dashboard?month={date.today().isoformat()[:7]}&months=12"
        assert client.get(url).status_code == 401
        response = client.get(url, headers={"Authorization": "Bearer token"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["totals"] is None and result["categories"] == []
        assert len(result["series"]) == 12 and result["currency"] == "USD"
        assert client.get("/api/dashboard?month=2026-99", headers={"Authorization": "Bearer token"}).status_code == 400
