"""H4 item analysis tools and assistant routing (docs/items-assets-search.md §4), with synthetic data only."""

from conftest import documents_by_name, inbox_scan
from datetime import date
from decimal import Decimal

import pytest

from home_manager.assistant import route
from home_manager.finance import Ledger
from home_manager.finance_tools import FINANCE_ROUTE, ITEM_ROUTE, FinanceTools, call_tool
from home_manager.item_analysis import parse_size, quantity_of
from home_manager.items import ItemLedger, ResolutionFields
from home_manager.storage import Store

TODAY = date(2026, 9, 25)


@pytest.fixture
def pantry(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {f"r{n}.png": f"synthetic receipt {n}".encode() for n in range(8)})
    docs = iter(sorted(documents_by_name(store).values(), key=lambda doc: doc["relative_path"]))
    ledger, items = Ledger(store), ItemLedger(store)

    def buy(day, merchant, lines):
        """lines: (printed text, cost, fields, quantity). Approves every line; returns the lots."""
        doc = next(docs)
        rows = [{"description": text, "product_code": None, "quantity": quantity, "unit_price_minor": None, "line_total_minor": cost, "discount_minor": None,
                 "locator": {"line_ids": [f"l{index}"]}} for index, (text, cost, _, quantity) in enumerate(lines, 1)]
        record = {"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                  "total_minor": sum(cost for _, cost, _, _ in lines), "currency": "USD", "issues": [], "items": rows, "locator": {"line_ids": ["l0"]}}
        receipt_id = ledger.publish_receipt(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": doc["relative_path"],
                                                     "run_id": doc["relative_path"]}, "verified")["id"]
        for line, (_, _, fields, _) in zip(items.lines(receipt_id), lines):
            items.review(items.propose(line["id"], fields, "search", "high")["id"], "verified", today=TODAY)
        return [lot for lot in items.inventory(include_closed=True, limit=1000) if lot["receipt_id"] == receipt_id]
    try:
        yield store, ledger, items, buy
    finally:
        store.close()


def milk(size="1 gal"):
    return ResolutionFields(name="Whole Milk", brand="Great Value", size_text=size, category="dairy & eggs", consumable=True)


def cereal(size):
    return ResolutionFields(name="Honey Nut Cheerios", brand="General Mills", size_text=size, category="pantry", consumable=True)


def test_sizes_and_quantities_parse_exactly():
    assert parse_size("1 gal") == ("volume", Decimal("3785.411784"))
    assert parse_size("19 OZ") == ("mass", Decimal("19") * Decimal("28.349523125"))
    assert parse_size("12 x 12 fl oz") == ("volume", Decimal(144) * Decimal("29.5735295625"))
    assert parse_size("6 pack") == ("count", Decimal(6))
    assert parse_size("500ml") == ("volume", Decimal(500))
    assert parse_size("family size") is None and parse_size(None) is None
    assert quantity_of("2") == (Decimal(2), False) and quantity_of(None) == (Decimal(1), True) and quantity_of("ea") == (Decimal(1), True)


def test_price_history_changes_and_merchant_comparison(pantry):
    store, ledger, items, buy = pantry
    buy("2026-07-01", "Walmart Supercenter", [("HN CHEERIOS", 399, cereal("12 oz"), "1"), ("GV MILK", 348, milk(), "1")])
    buy("2026-09-01", "Walmart Supercenter", [("HN CHEERIOS", 399, cereal("10.8 oz"), "1")])  # Same price, smaller box.
    buy("2026-09-10", "Target", [("GV MILK", 700, milk(), "2")])
    tools = FinanceTools(store)
    history = call_tool(tools, "item_price_history", {"query": "cheerios"})
    assert [(row["bought_on"], row["unit_price"]["amount"]["display"], row["unit_price"]["per"]) for row in history["purchases"]] == [
        ("2026-07-01", "1.17 USD", "per 100 g"), ("2026-09-01", "1.30 USD", "per 100 g")]
    changes = call_tool(tools, "get_price_changes", {"start": "2026-06-01", "end": "2026-09-30"})["increases"]
    assert [(row["product"], row["percent_change"], row["package_size_changed"]) for row in changes] == [
        ("General Mills Honey Nut Cheerios", "11.1", True), ("Great Value Whole Milk", "0.6", False)]  # 3.48 -> 3.50 a gallon.
    # Milk: 3.48/gal at Walmart vs 7.00 for two at Target (3.50 each): Walmart is cheaper per 100 ml.
    compared = call_tool(tools, "compare_merchant_prices", {"query": "milk"})["merchants"]
    assert [(row["merchant"], row["unit_price"]["display"]) for row in compared] == [("Walmart Supercenter", "0.09 USD"), ("Target", "0.09 USD")]
    spending = call_tool(tools, "get_item_spending", {"start": "2026-09-01", "end": "2026-09-30"})
    assert spending["by_currency"][0]["spent"]["display"] == "10.99 USD" and spending["top_products"][0]["product"] == "Great Value Whole Milk 1 gal"
    with pytest.raises(ValueError):
        call_tool(tools, "get_item_spending", {"start": "2026-09-30", "end": "2026-09-01"})


def test_consumption_waste_and_forecast(pantry):
    store, ledger, items, buy = pantry
    first = buy("2026-08-01", "Walmart", [("GV MILK", 350, milk(), "1")])[0]
    second = buy("2026-08-11", "Walmart", [("GV MILK", 350, milk(), "1")])[0]
    spoiled = buy("2026-09-01", "Walmart", [("SPINACH", 299, ResolutionFields(name="Baby Spinach", category="produce", consumable=True), "1")])[0]
    items.update_lot(first["id"], "finished", "2026-08-08", today=TODAY)   # 7 days
    items.update_lot(second["id"], "finished", "2026-08-24", today=TODAY)  # 13 days
    items.update_lot(spoiled["id"], "thrown_out", "2026-09-06", today=TODAY)
    tools = FinanceTools(store)
    consumption = call_tool(tools, "get_consumption_cost", {"query": "milk"})
    [row] = consumption["products"]
    # 7.00 over 20 days = 0.35 a day, 10.50 per 30 days; two lots is still approximate.
    assert (row["per_day"]["display"], row["per_30_days"]["display"], row["approximate"]) == ("0.35 USD", "10.50 USD", True)
    waste = call_tool(tools, "get_waste", {"start": "2026-09-01", "end": "2026-09-30"})
    assert waste["by_currency"] == [{"currency": "USD", "wasted": {"minor": 299, "currency": "USD", "decimal": "2.99", "display": "2.99 USD"}, "items": 1}]
    projected = call_tool(tools, "forecast_consumables_spend", {"month": "2026-10"})
    assert (projected["days"], projected["by_currency"][0]["projected"]["display"]) == (31, "10.85 USD")
    assert "1 product(s)" not in projected["notes"][0]  # Spinach was thrown out, not finished: it has no rate at all.


def test_spending_anomalies_compare_with_the_three_earlier_periods(pantry):
    store, ledger, items, buy = pantry
    account = ledger.create_account("First Local Bank", "checking", "USD")
    doc = store.documents()["items"][0]
    rows = [("2026-06-10", "HARDWARE STORE", -3000), ("2026-07-10", "HARDWARE STORE", -3000), ("2026-08-10", "HARDWARE STORE", -3000),
            ("2026-09-10", "HARDWARE STORE", -12000), ("2026-09-12", "NEW GYM", -5000), ("2026-09-14", "COFFEE", -900)]
    with store.connection() as db:
        ledger.insert_transactions(db, account, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD", "locator": {"rows": [n]}}
                                                 for n, (day, text, amount) in enumerate(rows, 1)], "import", {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:t"})
    result = call_tool(FinanceTools(store), "detect_spending_anomalies", {"start": "2026-09-01", "end": "2026-09-30"})
    merchants = {row["name"]: row for row in result["anomalies"] if row["kind"] == "merchant"}
    assert set(merchants) == {"HARDWARE STORE", "NEW GYM"}  # Coffee is new but under the minimum.
    assert (merchants["HARDWARE STORE"]["usual"]["display"], merchants["HARDWARE STORE"]["percent_above_usual"]) == ("30.00 USD", "300.0")
    assert merchants["NEW GYM"]["new"] and len(result["compared_with"]) == 3


def test_routing_limits_the_assistants_tools():
    assert route("Is milk cheaper at Costco or Walmart?") == "items"
    assert route("What did I throw away last month?") == "items"
    assert route("How much did I spend on groceries in August?") == "finance"
    assert route("Which bills are due next week?") == "finance"
    assert "compare_merchant_prices" in ITEM_ROUTE and "compare_merchant_prices" not in FINANCE_ROUTE
    assert "detect_spending_anomalies" in FINANCE_ROUTE and "get_upcoming_bills" not in ITEM_ROUTE
