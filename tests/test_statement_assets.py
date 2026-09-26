"""Investment and loan statements become proposed forecast assets (docs/items-assets-search.md §6). Synthetic data only."""

from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.forecast import AssetInput, Assets
from home_manager.scanner import ScanLimits
from test_extraction import RECEIPT, classification, extract, identity, receipt_items, receipt_summary, transcribe, value

INVESTMENT = ["FIDELITY INVESTMENTS", "Roth IRA account X12345678", "Statement date 2026-08-31", "Currency USD", "Ending account value $52,340.18"]
LOAN = ["SUNRISE MORTGAGE", "Loan number 000987654321", "Statement date 2026-09-01", "Principal balance 245,000.00", "Interest rate 6.125%",
        "Monthly payment 1,850.00", "USD"]
MISSING = {"value": None, "status": "missing", "evidence": []}


def classified(kind, lines):
    return {"document_type": kind, "evidence": [{"line_id": "line-1", "quote": lines[0]}], "issuer": value(lines[0].title(), 1, lines[0]),
            "document_date": value(lines[2].split()[-1], 3, lines[2])}


def test_an_investment_statement_publishes_a_proposed_retirement_asset(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, INVESTMENT)
    try:
        summary = {"institution": value("Fidelity Investments", 1, INVESTMENT[0]), "account_name": value("Roth IRA", 2, INVESTMENT[1]),
                   "account_reference": value("X12345678", 2, INVESTMENT[1]), "period_end": value("2026-08-31", 3, INVESTMENT[2]),
                   "ending_value": value("52,340.18", 5, INVESTMENT[4]), "currency": value("USD", 4, INVESTMENT[3])}
        local_model["outputs"] = [classified("investment_statement", INVESTMENT), summary]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert (run["publication"]["record_type"], run["publication"]["status"], run["publication"]["review_status"]) == ("asset", "published", "proposed")
        asset = Assets(manager.store).get(run["publication"]["id"])
        assert (asset["name"], asset["kind"], asset["value_minor"], asset["as_of"], asset["source"], asset["review_status"]) == (
            "Fidelity Investments Roth IRA 5678", "retirement", 5234018, "2026-08-31", "statement", "proposed")
        assert asset["document_id"] == doc["id"] and asset["issues"] == []
        assert manager.store.documents()["items"][0]["folder"] == "Investments"
        # A re-extraction of the same statement after review keeps the user's decision.
        Assets(manager.store).review(asset["id"], "verified")
        local_model["outputs"] = [classified("investment_statement", INVESTMENT), summary]
        again = extract(manager, doc, parse_id, force=True)
        assert again["publication"]["status"] == "kept_reviewed" and Assets(manager.store).get(asset["id"])["review_status"] == "verified"
    finally:
        manager.close()


def test_a_loan_statement_publishes_balance_rate_and_payment(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, LOAN)
    try:
        summary = {"institution": value("Sunrise Mortgage", 1, LOAN[0]), "account_name": MISSING, "account_reference": value("000987654321", 2, LOAN[1]),
                   "period_end": value("2026-09-01", 3, LOAN[2]), "principal_balance": value("245,000.00", 4, LOAN[3]),
                   "interest_rate": value("6.125%", 5, LOAN[4]), "monthly_payment": value("1,850.00", 6, LOAN[5]), "currency": value("USD", 7, LOAN[6])}
        local_model["outputs"] = [classified("loan_document", LOAN), summary]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        asset = Assets(manager.store).get(run["publication"]["id"])
        assert (asset["kind"], asset["value_minor"], asset["monthly_payment_minor"], asset["annual_rate_bp"]) == ("loan", 24500000, 185000, 612)
        assert "more than two decimals" in asset["issues"][0]  # 6.125% rounds half-even to 6.12%.
        assert asset["name"] == "Sunrise Mortgage Loan 4321" and "000987654321" not in str(asset)
        assert manager.store.documents()["items"][0]["folder"] == "Loans"
    finally:
        manager.close()


def test_one_asset_per_account_newer_statements_update_it(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, INVESTMENT)
    try:
        ledger, assets = manager.ledger, Assets(manager.store)
        record = {"asset_kind": "investment", "institution": "Vanguard", "account_name": "Brokerage", "last_four": "1111", "value_minor": 100000,
                  "period_end": "2026-08-31", "currency": "USD", "issues": []}
        source = {"document_id": doc["id"], "blob_hash": doc["current_hash"], "run_id": "a"}
        first = ledger.publish_asset(record, source)
        assets.review(first["id"], "verified")
        newer = ledger.publish_asset({**record, "value_minor": 120000, "period_end": "2026-09-30"}, {**source, "run_id": "b"})
        assert newer["id"] == first["id"] and assets.get(first["id"])["value_minor"] == 120000
        assert assets.get(first["id"])["review_status"] == "proposed"  # A new value waits for review again.
        older = ledger.publish_asset({**record, "value_minor": 90000, "period_end": "2026-07-31"}, {**source, "run_id": "c"})
        assert older["status"] == "kept_newer" and assets.get(first["id"])["value_minor"] == 120000
        assert ledger.publish_asset({**record, "last_four": "2222"}, source)["id"] != first["id"]  # Another account.
        car = assets.add(AssetInput(name="Car", kind="vehicle", value="9000", currency="USD", as_of="2026-09-01"))
        with pytest.raises(ValueError, match="values you enter"):
            assets.review(car["id"], "verified")
    finally:
        manager.close()


def test_a_printed_return_policy_is_stored_with_the_receipt(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, RECEIPT)
    try:
        local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "Lunch"}]
        run = extract(manager, doc, parse_id)
        with manager.store.connection() as db:
            row = db.execute("SELECT return_days_printed,return_policy_quote FROM receipts WHERE id=?", (run["publication"]["id"],)).fetchone()
        assert tuple(row) == (14, "Returns within 14 days")
    finally:
        manager.close()


def test_asset_review_and_search_endpoints(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, INVESTMENT)
    record = {"asset_kind": "investment", "institution": "Vanguard", "account_name": "Brokerage", "last_four": "1111", "value_minor": 100000,
              "period_end": "2026-08-31", "currency": "USD", "issues": []}
    asset_id = manager.ledger.publish_asset(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "run_id": "a"})["id"]
    managed = manager.store.root
    manager.close()
    app = create_app(tmp_path / "control2", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(managed)})
        assert client.post(f"/api/assets/{asset_id}/review", json={"status": "verified"}).json()["review_status"] == "verified"
        assert client.post(f"/api/assets/{asset_id}/review", json={"status": "maybe"}).status_code == 422
        found = client.get("/api/search", params={"q": "vanguard"}).json()
        assert found["accounts"]["total"] == 0 and found["documents"]["total"] == 0
        assert client.get("/api/search", params={"q": ""}).status_code == 422
        assert client.get("/api/return-policies").json()[0]["merchant"] == "Amazon"
        policy = client.put("/api/return-policies", json={"merchant": "Corner Hardware", "days": 30}).json()
        assert (policy["pattern"], policy["source"]) == ("CORNER HARDWARE", "user")
        assert client.delete(f"/api/return-policies/{policy['id']}").json()["deleted"]
        assert client.get("/api/inventory/returns").json() == []
