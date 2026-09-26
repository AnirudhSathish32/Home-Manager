"""Category rules and monthly budgets (docs/money-review-inventory.md §2), with synthetic data only."""

from conftest import inbox_scan

from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.finance import Ledger
from home_manager.finance_tools import FinanceTools, call_tool
from home_manager.reconcile import Reconciler
from home_manager.scanner import ScanLimits
from home_manager.storage import Store


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n"})
    doc = store.documents()["items"][0]
    ledger = Ledger(store)
    account = ledger.create_account("First Local Bank", "checking", "USD")
    source = {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:test"}

    def add(*items, account=account):
        rows = [{"posted_date": day, "description": text, "amount_minor": amount, "currency": account["currency"], "locator": {"rows": [index]}}
                for index, (day, text, amount) in enumerate(items, 1)]
        with store.connection() as db:
            return ledger.insert_transactions(db, account, rows, "import", source)[0]
    try:
        yield store, ledger, account, add
    finally:
        store.close()


def categories(store):
    with store.connection() as db:
        return {row["description_raw"]: (row["category"], row["category_source"]) for row in db.execute("SELECT * FROM transactions ORDER BY id")}


def test_rules_categorize_existing_and_new_rows_and_never_override_the_user(books):
    store, ledger, account, add = books
    costco, gas, coffee = add(("2026-09-02", "COSTCO WHSE #0123", -15000), ("2026-09-03", "COSTCO GAS #0123", -4000), ("2026-09-04", "BLUE BOTTLE COFFEE", -600))
    rule = ledger.add_rule("costco", "Groceries")
    assert (rule["pattern"], rule["category"], rule["changed"], rule["transactions"]) == ("COSTCO", "groceries", 2, 2)
    # The more specific rule wins for the gas station, whichever was written first.
    assert ledger.add_rule("Costco gas", "fuel")["changed"] == 1
    assert categories(store)["COSTCO GAS #0123"] == ("fuel", "rule")
    # A hand-set category is the user's decision and survives every rule change.
    assert ledger.set_category(coffee, " Eating  Out ")["category_source"] == "user"
    ledger.add_rule("blue bottle", "coffee")
    assert categories(store)["BLUE BOTTLE COFFEE"] == ("eating out", "user")
    # New rows are categorized as they arrive.
    [later] = add(("2026-09-20", "COSTCO WHSE #0999", -2500))
    assert categories(store)["COSTCO WHSE #0999"] == ("groceries", "rule")
    # Clearing a hand-set category hands the row back to the rules.
    assert ledger.set_category(coffee, None) == {"id": coffee, "category": "coffee", "category_source": "rule"}
    # Deleting the specific rule sends its rows to the next matching rule; deleting the last one uncategorizes them.
    fuel = next(item for item in ledger.rules() if item["category"] == "fuel")
    ledger.delete_rule(fuel["id"])
    assert categories(store)["COSTCO GAS #0123"] == ("groceries", "rule")
    ledger.delete_rule(rule["id"])
    assert categories(store)["COSTCO WHSE #0123"] == (None, None)
    assert {costco, gas, later}  # All three rows were touched above.


def test_rules_rerun_when_reconciliation_attaches_or_removes_a_merchant(books):
    store, ledger, account, add = books
    [charge] = add(("2026-09-05", "SQ *CB 0042", -1500))  # The card text doesn't name the bakery.
    ledger.add_rule("corner bakery", "cafe")
    assert categories(store)["SQ *CB 0042"] == (None, None)
    doc = store.documents()["items"][0]
    record = {"merchant": "Corner Bakery", "purchase_date": "2026-09-05", "subtotal_minor": None, "tax_minor": None, "tip_minor": None, "total_minor": 1500,
              "currency": "USD", "issues": [], "items": [], "locator": {"line_ids": ["line-1"]}}
    ledger.publish_receipt(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:x", "run_id": "x"}, "verified")
    reconciler = Reconciler(store)
    assert reconciler.run()["receipt_links"] == 1
    assert categories(store)["SQ *CB 0042"] == ("cafe", "rule")  # The matched receipt named the merchant.
    link = FinanceTools(store).review_queue(None)["links"][0]
    reconciler.review_link("receipt", link["id"], "rejected")
    assert categories(store)["SQ *CB 0042"] == (None, None)
    assert charge


def test_rule_validation_and_account_scope(books):
    store, ledger, account, add = books
    card = ledger.create_account("Card Co", "credit_card", "USD")
    add(("2026-09-02", "SHELL OIL 123", -3000))
    add(("2026-09-02", "SHELL OIL 123", -3000), account=card)
    ledger.add_rule("shell", "fuel", card["id"])
    with store.connection() as db:
        assert dict(db.execute("SELECT account_id,category FROM transactions").fetchall()) == {account["id"]: None, card["id"]: "fuel"}
    with pytest.raises(ValueError, match="already exists"):
        ledger.add_rule("SHELL", "car", card["id"])
    with pytest.raises(ValueError, match="words"):
        ledger.add_rule("#123 !!", "fuel")
    with pytest.raises(ValueError, match="uncategorized"):
        ledger.add_rule("shell", "Uncategorized")
    with pytest.raises(ValueError, match="Account not found"):
        ledger.add_rule("shell", "fuel", 999)


def test_budgets_measure_counted_category_spending_and_pace(books):
    store, ledger, account, add = books
    ledger.add_rule("grocer", "groceries")
    add(("2026-09-02", "GROCER ONE", -20000), ("2026-09-09", "GROCER TWO", -10000), ("2026-09-10", "CINEMA", -2500),
        ("2026-08-30", "GROCER OLD", -99999), ("2026-09-11", "GROCER REFUND", 5000))
    ledger.set_budget("Groceries", "usd", "450.00")
    ledger.set_budget("fun", "USD", "20")
    assert ledger.set_budget("groceries", "USD", "400")["amount"]["display"] == "400.00 USD"  # Setting again changes it.
    with pytest.raises(ValueError, match="more than zero"):
        ledger.set_budget("fun", "USD", "0")
    tools = FinanceTools(store)
    result = call_tool(tools, "get_budgets", {"month": "2026-09", "as_of": "2026-09-10"})
    rows = {row["category"]: row for row in result["budgets"]}
    assert (result["days"], result["elapsed_days"]) == (30, 10)
    groceries = rows["groceries"]
    assert (groceries["spent"]["display"], groceries["remaining"]["display"], groceries["percent_used"], groceries["transactions"]) == (
        "300.00 USD", "100.00 USD", "75.0", 2)
    assert groceries["status"] == "ahead_of_pace"  # 75% spent after a third of the month.
    assert rows["fun"]["spent"]["minor"] == 0 and rows["fun"]["status"] == "on_track"
    assert [(row["spent"]["display"], row["transactions"]) for row in result["unbudgeted"]] == [("25.00 USD", 1)]
    with store.connection() as db:
        db.execute("UPDATE transactions SET category='fun' WHERE description_raw='CINEMA'")
    over = {row["category"]: row["status"] for row in call_tool(tools, "get_budgets", {"month": "2026-09", "as_of": "2026-09-10"})["budgets"]}
    assert over["fun"] == "over"
    past = {row["category"]: row["status"] for row in call_tool(tools, "get_budgets", {"month": "2026-09", "as_of": "2026-10-05"})["budgets"]}
    assert past == {"fun": "over", "groceries": "within"}
    future = call_tool(tools, "get_budgets", {"month": "2026-11", "as_of": "2026-10-05"})
    assert future["elapsed_days"] == 0 and {row["status"] for row in future["budgets"]} == {"not_started"}
    assert [row["category"] for row in call_tool(tools, "get_categories", {})["categories"]] == ["fun", "groceries"]


def test_rule_and_budget_endpoints(tmp_path, books):
    store, ledger, account, add = books
    add(("2026-09-02", "TRADER JOES #55", -4200))
    managed = store.root
    store.close()
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(managed)})
        created = client.post("/api/finance/category-rules", json={"pattern": "trader joes", "category": "groceries"})
        assert created.status_code == 201 and created.json()["changed"] == 1
        rule_id = created.json()["id"]
        assert client.put(f"/api/finance/category-rules/{rule_id}", json={"pattern": "trader", "category": "food"}).json()["category"] == "food"
        assert client.get("/api/finance/category-rules").json()[0]["transactions"] == 1
        assert client.post("/api/finance/category-rules", json={"pattern": "x", "category": "y", "extra": 1}).status_code == 422
        budget = client.put("/api/finance/budgets", json={"category": "food", "currency": "USD", "amount": "100.00"}).json()
        assert client.post("/api/finance/tools/get_budgets", json={"month": "2026-09", "as_of": "2026-09-30"}).json()["budgets"][0]["spent"]["display"] == "42.00 USD"
        assert client.put("/api/finance/budgets", json={"category": "food", "currency": "USD", "amount": "1.2.3"}).status_code == 400
        assert client.delete(f"/api/finance/budgets/{budget['id']}").json()["deleted"]
        assert client.delete(f"/api/finance/category-rules/{rule_id}").json()["changed"] == 1
        assert client.delete(f"/api/finance/category-rules/{rule_id}").status_code == 400
        [row] = client.post("/api/finance/tools/get_transactions", json={"start": "2026-09-01", "end": "2026-09-30"}).json()["transactions"]
        assert row["category"] is None and row["category_source"] is None
