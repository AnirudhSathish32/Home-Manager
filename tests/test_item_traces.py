"""Item insights' traces and the Inventory page's insights endpoint (household/item_traces.py; docs/household.md "Item
analysis"): each trace re-runs its tool, gives the tool's figure, and its steps plus any rounding add up to it.
Synthetic data only."""

from datetime import date, timedelta
from urllib.parse import quote

from fastapi.testclient import TestClient

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.ledger import Ledger
from home_manager.finance.tools import FinanceTools, call_tool
from home_manager.finance.traces import trace
from home_manager.household.items import ItemLedger, ResolutionFields
from home_manager.library.scanner import ScanLimits
from test_item_analysis import TODAY, cereal, milk, pantry  # noqa: F401 (pantry is a fixture)


def food(name):
    return ResolutionFields(name=name, category="pantry", consumable=True)


def adds_up(found):
    """The steps, plus the rounding adjustment, are the result."""
    total = sum(step["value"]["minor"] * (1 if step["op"] == "+" else -1) for step in found["steps"])
    adjustment = found["rounding"]["adjustment"]["minor"] if found["rounding"] and found["rounding"]["adjustment"] else 0
    assert found["reconciles"] and total + adjustment == found["result"]["minor"], found["steps"]
    return found


def test_each_item_trace_is_its_tools_figure_one_step_per_product(pantry):  # noqa: F811
    store, _, items, buy = pantry
    first = buy("2026-08-01", "Walmart", [("GV MILK", 350, milk(), "1"), ("BANANAS", 100, food("Bananas"), "1"), ("BREAD", 100, food("Bread"), "1")])
    second = buy("2026-08-11", "Walmart", [("GV MILK", 350, milk(), "1")])[0]
    spoiled = buy("2026-09-01", "Walmart", [("SPINACH", 299, food("Baby Spinach"), "1"), ("SPINACH", 299, food("Baby Spinach"), "1")])
    for lot, day in ((first[0], "2026-08-08"), (first[1], "2026-08-08"), (first[2], "2026-08-08"), (second, "2026-08-24")):
        items.update_lot(lot["id"], "finished", day, today=TODAY)
    for lot in spoiled:
        items.update_lot(lot["id"], "thrown_out", "2026-09-06", today=TODAY)
    tools = FinanceTools(store)

    spending = adds_up(trace(store, "items.spending?currency=USD&end=2026-09-30&start=2026-08-01"))
    assert spending["result"]["minor"] == call_tool(tools, "get_item_spending", {"start": "2026-08-01", "end": "2026-09-30"})["by_currency"][0]["spent"]["minor"] == 1498
    assert [(step["label"], step["value"]["minor"], step["count"]) for step in spending["steps"]] == [
        ("Great Value Whole Milk 1 gal", 700, 2), ("Baby Spinach", 598, 2), ("Bananas", 100, 1), ("Bread", 100, 1)]

    waste = adds_up(trace(store, "items.waste?currency=USD&end=2026-09-30&start=2026-09-01"))
    assert waste["result"]["minor"] == 598 and [(step["label"], step["count"]) for step in waste["steps"]] == [("Baby Spinach", 2)]

    # Milk 7.00 over 20 days is 10.50 per 30; bananas and bread 1.00 over 7 days are 4.2857… each, shown as 4.29.
    # The exact total 19.0714… rounds to 19.07, a cent under the steps' 19.08.
    per_30 = adds_up(trace(store, "items.per_30_days?currency=USD"))
    assert per_30["result"]["minor"] == call_tool(tools, "get_consumption_cost", {})["per_30_days_by_currency"][0]["amount"]["minor"] == 1907
    assert sorted(step["value"]["minor"] for step in per_30["steps"]) == [429, 429, 1050] and per_30["rounding"]["adjustment"]["minor"] == -1
    milk_input = next(item for item in per_30["inputs"] if "Milk" in item["label"])
    assert (milk_input["value"]["minor"], milk_input["provenance"]) == (700, "your check-in answers") and "20 days" in milk_input["label"]

    # Only milk has two finished lots: 7.00 × 31 / 20 = 10.85 for October.
    forecast = adds_up(trace(store, "items.forecast?currency=USD&month=2026-10"))
    assert forecast["result"]["minor"] == call_tool(tools, "forecast_consumables_spend", {"month": "2026-10"})["by_currency"][0]["projected"]["minor"] == 1085
    assert [step["label"] for step in forecast["steps"]] == ["Great Value Whole Milk 1 gal"]


def test_a_trace_without_its_parameters_is_refused(pantry):  # noqa: F811
    store = pantry[0]
    for text in ("items.spending?currency=USD", "items.forecast?currency=USD&month=October", "items.per_30_days"):
        try:
            trace(store, text)
        except ValueError:
            continue
        raise AssertionError(f"{text} was traced")


def test_the_insights_endpoint_shows_traced_figures_and_the_rows_behind_them(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        store, today = app.state.manager.store, date.today()
        day = lambda back: (today - timedelta(days=back)).isoformat()
        inbox_scan(store, {f"r{n}.png": f"synthetic receipt {n}".encode() for n in range(4)})
        docs = iter(sorted(documents_by_name(store).values(), key=lambda doc: doc["relative_path"]))
        ledger, items = Ledger(store), ItemLedger(store)

        def buy(on, lines):
            doc = next(docs)
            rows = [{"description": text, "product_code": None, "quantity": "1", "unit_price_minor": None, "line_total_minor": cost, "discount_minor": None,
                     "locator": {"line_ids": [f"l{n}"]}} for n, (text, cost, _) in enumerate(lines, 1)]
            record = {"merchant": "Walmart", "purchase_date": on, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                      "total_minor": sum(cost for _, cost, _ in lines), "currency": "USD", "issues": [], "items": rows, "locator": {"line_ids": ["l0"]}}
            receipt_id = ledger.publish_receipt(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": doc["relative_path"],
                                                         "run_id": doc["relative_path"]}, "verified")["id"]
            for line, (_, _, fields) in zip(items.lines(receipt_id), lines):
                items.review(items.propose(line["id"], fields, "search", "high")["id"], "verified", today=today)
            return [lot for lot in items.inventory(include_closed=True, limit=1000) if lot["receipt_id"] == receipt_id]

        [a] = buy(day(60), [("CHEERIOS", 399, cereal("18 oz"))])
        [b] = buy(day(30), [("CHEERIOS", 399, cereal("15.5 oz"))])  # Same price, smaller box.
        [c] = buy(day(20), [("GV MILK", 350, milk())])
        items.update_lot(a["id"], "finished", day(40), today=today)
        items.update_lot(b["id"], "finished", day(10), today=today)
        items.update_lot(c["id"], "thrown_out", day(5), today=today)

        found = client.get("/api/inventory/insights?period=90&currency=USD").json()
        assert found["period"] == {"start": day(89), "end": today.isoformat()} and found["currency"] == "USD"
        assert set(found["figures"]) == {"spending", "waste", "per_30_days", "forecast"}
        for shown in found["figures"].values():
            assert {"display", "minor", "currency", "trace", "stale"} <= set(shown) and shown["stale"] is False
            opened = client.get(f"/api/traces/{quote(shown['trace'], safe='')}").json()
            assert opened["reconciles"] and opened["result"]["minor"] == shown["minor"]
        assert (found["figures"]["spending"]["minor"], found["figures"]["waste"]["minor"]) == (1148, 350)
        assert found["counts"] == {"purchases": 3, "thrown_out": 1, "finished_products": 2}  # Each box size is its own product.
        [rise] = found["increases"]
        assert rise["package_size_changed"] and rise["change_percent"] == rise["percent_change"] + "%"
        assert [row["product"] for row in found["top_products"]][0] == "General Mills Honey Nut Cheerios 18 oz"
        assert found["waste_items"][0]["cost"]["minor"] == 350 and found["consumption"][0]["approximate"] is True
        assert found["month"] == (f"{today.year + 1}-01" if today.month == 12 else f"{today.year}-{today.month + 1:02d}")

        year = client.get("/api/inventory/insights?period=year").json()
        assert (year["period"]["start"], year["currency"]) == (f"{today.year}-01-01", "USD")  # No home currency set: USD, as Home.
        assert client.get(f"/api/inventory/insights?start={day(0)}&end={day(5)}").status_code == 422
