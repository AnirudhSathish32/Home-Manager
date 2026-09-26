"""Household items: resolution proposals, approval, inventory lots, run-out schedule and agent tools."""

from conftest import documents_by_name, inbox_scan
from datetime import date
import json

from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.checkin import CheckinService
from home_manager.finance import Ledger
from home_manager.finance_tools import FinanceTools, call_tool
from home_manager.item_resolver import ItemResolver
from home_manager.item_tools import ItemTools, call_item_tool
from home_manager.items import ItemLedger, ResolutionFields, normalize_text, printed_return_days, valid_gtin
from home_manager.jobs import Work
from home_manager.reasoning import ReasoningConfig
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store
from home_manager.web_lookup import BRAVE_SEARCH, LookupFailed, WebLookup, https_get, page_text, public_address

TODAY = date(2026, 9, 25)
MILK = ResolutionFields(name="Great Value Whole Milk", brand="Great Value", size_text="1 gal", category="dairy & eggs", consumable=True)
UPC = "036000291452"  # Valid UPC-A check digit.


@pytest.fixture
def shop(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {name: f"synthetic {name}".encode() for name in ("a.png", "b.png", "c.png")})
    docs = documents_by_name(store)
    try:
        yield store, Ledger(store), ItemLedger(store), docs
    finally:
        store.close()


def receipt(ledger, doc, lines, day="2026-09-10", merchant="Walmart Supercenter #1234", location="Springfield"):
    items = [{"description": text, "product_code": code, "quantity": "1", "unit_price_minor": cost, "line_total_minor": cost,
              "discount_minor": None, "locator": {"line_ids": [f"line-{index}"]}} for index, (text, code, cost) in enumerate(lines, 1)]
    record = {"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
              "total_minor": sum(cost for _, _, cost in lines), "currency": "USD", "issues": [], "items": items, "location": location,
              "locator": {"line_ids": ["line-0"]}}
    source = {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": doc["relative_path"], "run_id": doc["relative_path"]}
    return ledger.publish_receipt(record, source, "proposed")["id"]


def line_ids(items, receipt_id):
    return [line["id"] for line in items.lines(receipt_id)]


def test_normalization_and_barcode_check_digits():
    assert normalize_text("  gv whl-mlk, 1gl ") == "GV WHL MLK 1GL"
    assert valid_gtin(UPC) and not valid_gtin("036000291453") and not valid_gtin("1234") and not valid_gtin(None)
    with pytest.raises(ValueError):
        ResolutionFields(name="x", category="groceries", consumable=True)
    with pytest.raises(ValueError, match="check digit"):
        ResolutionFields(name="x", category="pantry", consumable=True, barcode="036000291453")


def test_approval_creates_product_alias_and_lot_and_the_alias_resolves_the_next_receipt(shop):
    store, ledger, items, docs = shop
    first = receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", None, 348), ("PAPER TWL 6RL", None, 899)])
    milk_line, towel_line = line_ids(items, first)
    proposal = items.propose(milk_line, ResolutionFields(name="Whole Milk", category="dairy & eggs", consumable=True), "search", "medium")
    with pytest.raises(ValueError, match="already has a proposal"):
        items.propose(milk_line, MILK, "search", "high")
    approved = items.review(proposal["id"], "verified", edits=MILK, today=TODAY)  # The user corrects the name while approving.
    assert approved["review_status"] == "verified" and approved["method"] == "user" and approved["name"] == MILK.name
    with pytest.raises(ValueError, match="already reviewed"):
        items.review(proposal["id"], "rejected")
    [lot] = items.inventory("milk")
    assert (lot["bought_on"], lot["cost_minor"], lot["status"], lot["next_check_on"]) == ("2026-09-10", 348, "in_stock", "2026-09-25")
    assert items.unresolved(first) == [items.lines(first)[1]]  # Only the towels are left.

    second = receipt(ledger, docs["b.png"], [("GV  whl mlk 1gl", None, 358)], day="2026-09-20")
    known = items.known(line_ids(items, second)[0])
    assert known["method"] == "alias" and known["name"] == MILK.name and known["confidence"] == "high"
    # A rejected product is never proposed again for that line.
    towel = items.propose(towel_line, ResolutionFields(name="Paper Towels", category="paper & disposables", consumable=True), "search", "low")
    items.review(towel["id"], "rejected")
    with pytest.raises(ValueError, match="already rejected"):
        items.propose(towel_line, ResolutionFields(name="paper  towels", category="paper & disposables", consumable=True), "search", "low")


def test_run_out_schedule_backs_off_and_answers_apply_directly(shop):
    store, ledger, items, docs = shop
    first = receipt(ledger, docs["a.png"], [("SEALANT", None, 1299), ("DRILL", None, 5999)], day="2026-09-01")
    sealant_line, drill_line = line_ids(items, first)
    items.review(items.propose(sealant_line, ResolutionFields(name="Grout Sealer", category="home maintenance", consumable=True), "search", "high")["id"],
                 "verified", today=TODAY)
    items.review(items.propose(drill_line, ResolutionFields(name="Cordless Drill", category="home maintenance", consumable=False), "search", "high")["id"],
                 "verified", today=TODAY)
    lots = {lot["name"]: lot for lot in items.inventory()}
    assert lots["Cordless Drill"]["next_check_on"] is None  # Durables are never asked about.
    sealant = lots["Grout Sealer"]
    assert sealant["next_check_on"] == "2026-09-29"  # Category default: 28 days after purchase.

    day, gaps = TODAY, []
    for _ in range(7):
        updated = items.update_lot(sealant["id"], "still_have", day.isoformat(), today=day)
        gaps.append(updated["check_interval_days"])
    assert gaps == [7, 14, 28, 56, 112, 182, 182]  # Capped: still asked about twice a year.
    with pytest.raises(ValueError, match="future"):
        items.update_lot(sealant["id"], "finished", "2026-12-01", today=TODAY)
    with pytest.raises(ValueError, match="before the item was bought"):
        items.update_lot(sealant["id"], "finished", "2026-08-01", today=TODAY)
    closed = items.update_lot(sealant["id"], "finished", "2026-09-20", precision_days=3, today=TODAY)
    assert (closed["status"], closed["closed_on"], closed["closed_precision_days"], closed["next_check_on"]) == ("finished", "2026-09-20", 3, None)
    with pytest.raises(ValueError, match="Reopen it first"):
        items.update_lot(sealant["id"], "thrown_out", today=TODAY)
    restored = items.undo_lot(sealant["id"])
    assert restored["status"] == "in_stock" and restored["check_interval_days"] == 182
    with pytest.raises(ValueError, match="nothing to undo"):
        items.undo_lot(sealant["id"])
    assert [event["event"] for event in items.lot_history(sealant["id"])][-2:] == ["finished", "undone"]
    assert items.inventory("sealer", include_closed=True)[0]["status"] == "in_stock"


def test_repurchase_moves_the_older_lot_forward_and_history_predicts_run_out(shop):
    store, ledger, items, docs = shop
    for doc, day in (("a.png", "2026-08-01"), ("b.png", "2026-08-11")):
        receipt_id = receipt(ledger, docs[doc], [("GV WHL MLK 1GL", None, 348)], day=day)
        [line] = line_ids(items, receipt_id)
        items.review(items.propose(line, MILK, "search", "high")["id"], "verified", today=date(2026, 8, 12))
    older, newer = sorted(items.inventory("milk"), key=lambda lot: lot["bought_on"])
    assert older["next_check_on"] == "2026-08-12"  # Asked about at the next check-in; never closed automatically.
    items.update_lot(older["id"], "finished", "2026-08-11", today=date(2026, 8, 12))
    items.update_lot(newer["id"], "finished", "2026-08-21", today=date(2026, 8, 22))
    third = receipt(ledger, docs["c.png"], [("GV WHL MLK 1GL", None, 348)], day="2026-09-01")
    [line] = line_ids(items, third)
    items.review(items.propose(line, MILK, "alias", "high")["id"], "verified", today=date(2026, 9, 1))
    [current] = items.inventory("milk")
    assert current["next_check_on"] == "2026-09-11"  # Median of two finished lots: 10 days.


def test_reapproving_a_re_extracted_line_keeps_one_lot(shop):
    store, ledger, items, docs = shop
    receipt_id = receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", None, 348)])
    items.review(items.propose(line_ids(items, receipt_id)[0], MILK, "search", "high")["id"], "verified", today=TODAY)
    receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", None, 348)])  # Re-extraction rewrites the lines.
    [line] = items.unresolved(receipt_id)
    known = items.known(line["id"])
    items.review(items.propose(line["id"], ResolutionFields(**{k: v for k, v in known.items() if k not in ("method", "confidence", "product_id")}),
                               "alias", "high")["id"], "verified", today=TODAY)
    assert len(items.inventory(include_closed=True)) == 1


class FakeWeb:
    """Stands in for https_get: Brave JSON, Open Food Facts JSON, and one HTML page."""

    def __init__(self):
        self.requests = []

    def __call__(self, url, headers=None):
        self.requests.append((url, headers))
        if url.startswith(BRAVE_SEARCH):
            body = {"web": {"results": [{"title": "Great Value Whole Milk, 1 gal", "url": "https://shop.example/milk", "description": "Vitamin D whole milk"},
                                        {"title": "Insecure", "url": "http://plain.example/", "description": "dropped"}]}}
            return 200, "application/json", json.dumps(body).encode(), url
        if "openfoodfacts" in url:
            if UPC in url:
                body = {"status": 1, "product": {"product_name": "Honey Nut Cheerios", "brands": "General Mills,GM", "quantity": "10.8 oz",
                                                 "categories_tags": ["en:breakfast-cereals"]}}
                return 200, "application/json", json.dumps(body).encode(), url
            return 404, "application/json", b"{}", url
        html = b"<html><head><title>Milk</title><script>ignore()</script></head><body><h1>Great Value Whole Milk</h1><p>Size: 1 gallon (128 fl oz)</p></body></html>"
        return 200, "text/html; charset=utf-8", html, url


def test_item_tools_refuse_private_query_text_and_enforce_limits(shop):
    store, ledger, items, docs = shop
    receipt_id = receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", "4011", 348)])
    fetch = FakeWeb()
    tools = ItemTools(items, WebLookup(store, fetch, key="test-key"), line_ids(items, receipt_id)[0])
    assert call_item_tool(tools, "get_receipt_line", {})["merchant"].startswith("Walmart")
    for query, reason in (("GV WHL MLK 3.48", "prices"), ("milk 2026-09-10", "dates"), ("walmart milk 5521", "product code"),
                          ("walmart springfield milk", "location")):
        with pytest.raises(ValueError, match=reason):
            call_item_tool(tools, "web_search", {"query": query})
    assert not fetch.requests  # Nothing was sent for a refused query.
    results = call_item_tool(tools, "web_search", {"query": "Walmart GV WHL MLK 1GL 4011"})["results"]
    assert [result["result_id"] for result in results] == ["r1"]  # The http:// result is dropped.
    assert fetch.requests[0][1]["X-Subscription-Token"] == "test-key"
    call_item_tool(tools, "web_search", {"query": "walmart gv whl mlk 1gl 4011"})  # Served from the cache.
    assert len(fetch.requests) == 1
    with pytest.raises(ValueError, match="Unknown result"):
        call_item_tool(tools, "open_result", {"result_id": "r9"})
    page = call_item_tool(tools, "open_result", {"result_id": "r1"})
    assert page["title"] == "Milk" and "ignore" not in page["text_start"]
    assert call_item_tool(tools, "find_in_page", {"result_id": "r1", "pattern": "1 gallon"})["matches"]
    with pytest.raises(ValueError, match="Unknown sources"):
        call_item_tool(tools, "propose_item_resolution", {**MILK.model_dump(), "confidence": "high", "source_ids": ["r7"]})
    proposed = call_item_tool(tools, "propose_item_resolution", {**MILK.model_dump(), "confidence": "high", "source_ids": ["r1"]})
    assert items.resolution(proposed["proposal_id"])["sources"][0]["url"] == "https://shop.example/milk"
    call_item_tool(tools, "web_search", {"query": "walmart whole milk"})  # The third search, counting the cached one.
    with pytest.raises(ValueError, match="search limit"):
        call_item_tool(tools, "web_search", {"query": "walmart milk again"})
    with pytest.raises(ValueError, match="not configured"):
        WebLookup(store, fetch, key="").search("uncached query")


def test_fetch_refuses_plain_http_and_non_public_addresses():
    with pytest.raises(LookupFailed, match="https"):
        https_get("http://example.com/")
    with pytest.raises(LookupFailed, match="public"):
        public_address("127.0.0.1")
    with pytest.raises(LookupFailed, match="public"):
        https_get("https://10.0.0.1/")
    assert page_text(b"<style>x{}</style><p>One</p><p>Two</p>", "text/html") == ("", "One\nTwo")


def test_resolver_uses_alias_then_barcode_then_the_agent(shop, local_model):
    store, ledger, items, docs = shop
    first = receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", None, 348)])
    items.review(items.propose(line_ids(items, first)[0], MILK, "search", "high")["id"], "verified", today=TODAY)
    second = receipt(ledger, docs["b.png"], [("GV WHL MLK 1GL", None, 348), ("HN CHEERIOS", UPC, 499), ("DAWN ULT 19OZ", None, 329)])
    resolver = ItemResolver(store, WebLookup(store, FakeWeb(), key="k"))
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    step = lambda **fields: {"action": "call_tool", "tool": None, "arguments_json": None, "note": None, **fields}  # noqa: E731
    local_model["outputs"] = [
        step(tool="web_search", arguments_json=json.dumps({"query": "walmart DAWN ULT 19OZ 3.29"})),  # Refused: contains a price.
        step(tool="web_search", arguments_json=json.dumps({"query": "walmart DAWN ULT 19OZ"})),
        step(tool="propose_item_resolution", arguments_json=json.dumps({"name": "Dawn Ultra Dish Soap", "brand": "Dawn", "size_text": "19 oz",
                                                                        "category": "household cleaning", "consumable": True, "barcode": None,
                                                                        "confidence": "medium", "source_ids": ["r1"]}))]
    run_id = resolver.enqueue(second, config)
    resolver.run(run_id, config, Work("inference", "item_resolution", "Identifying receipt items", sink=store.record_model_run))
    run = resolver.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    assert [line["method"] for line in run["result"]["lines"]] == ["alias", "barcode", "search"]
    assert len(local_model["requests"]) == 3  # The model saw only the line nothing else could resolve.
    assert "prices" in local_model["requests"][1]["messages"][-1]["content"]
    cereal = items.resolution(run["result"]["lines"][1]["proposal_id"])
    assert (cereal["name"], cereal["brand"], cereal["barcode"], cereal["review_status"]) == ("Honey Nut Cheerios", "General Mills", UPC, "proposed")
    assert not items.inventory("dawn")  # Nothing enters inventory before approval.
    with pytest.raises(ValueError, match="already has a proposal"):
        resolver.enqueue(second, config)


def stock(items, ledger, doc, count, category="produce", consumable=True, prefix="Item"):
    """Approve `count` distinct products from one receipt; returns their lots in line order."""
    receipt_id = receipt(ledger, doc, [(f"{prefix} {chr(65 + n)}".upper(), None, 100 + n) for n in range(count)])
    for n, line in enumerate(line_ids(items, receipt_id)):
        fields = ResolutionFields(name=f"{prefix} {chr(65 + n)}", category=category, consumable=consumable)
        items.review(items.propose(line, fields, "search", "high")["id"], "verified", today=TODAY)
    return [lot for lot in items.inventory(include_closed=True) if lot["receipt_id"] == receipt_id]


def test_weekly_checkin_window_limit_and_one_tap_answers(shop):
    store, ledger, items, docs = shop
    lots = stock(items, ledger, docs["a.png"], 17)  # Produce bought Sep 10: first question due Sep 17, asked from today.
    stock(items, ledger, docs["b.png"], 2, category="home maintenance", consumable=False, prefix="Tool")  # Durables are never asked about.
    assert TODAY.weekday() == 4
    sunday = items.checkin(6, TODAY)  # The latest Sunday (Sep 20) is before the questions came due.
    assert (sunday["checkin_on"], sunday["lots"], sunday["waiting"]) == ("2026-09-20", [], 0)
    friday = items.checkin(4, TODAY)
    assert (friday["checkin_on"], friday["next_checkin_on"], len(friday["lots"]), friday["waiting"]) == ("2026-09-25", "2026-10-02", 15, 2)
    assert all(lot["category"] == "produce" for lot in friday["lots"])
    first, second = friday["lots"][0]["id"], friday["lots"][1]["id"]
    finished = items.answer(first, "finished_this_week", today=TODAY)
    assert (finished["status"], finished["closed_on"], finished["closed_precision_days"]) == ("finished", "2026-09-22", 3)
    kept = items.answer(second, "still_have", today=TODAY)
    assert (kept["status"], kept["next_check_on"]) == ("in_stock", "2026-10-02")
    after = items.checkin(4, TODAY)
    assert (len(after["lots"]), after["waiting"]) == (15, 0)  # Leftovers moved up; answered lots left the check-in.
    assert {first, second}.isdisjoint(lot["id"] for lot in after["lots"])
    assert items.lot_history(first)[-1]["source"] == "checkin"
    with pytest.raises(ValueError, match="still have it"):
        items.answer(lots[2]["id"], "eaten", today=TODAY)
    # A lot bought today that is "finished this week" cannot close before it was bought.
    fresh = stock(items, ledger, docs["c.png"], 1, prefix="Fresh")[0]
    with store.connection() as db:
        db.execute("UPDATE inventory_lots SET bought_on=? WHERE id=?", (TODAY.isoformat(), fresh["id"]))
    assert items.answer(fresh["id"], "thrown_out_this_week", today=TODAY)["closed_on"] == TODAY.isoformat()


def test_free_text_checkin_is_staged_and_applies_only_on_confirmation(shop, local_model):
    store, ledger, items, docs = shop
    milk, rice = [lot["id"] for lot in stock(items, ledger, docs["a.png"], 2)]
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    service = CheckinService(store)
    with pytest.raises(ValueError, match="reasoning model"):
        service.enqueue("finished the milk", 4, ReasoningConfig(base_url=local_model["config"].base_url, model=""), today=TODAY)
    update = lambda lot, answer, when, day=None: {"lot_id": lot, "answer": answer, "when": when, "date": day}  # noqa: E731
    local_model["outputs"] = [{"updates": [update(milk, "finished", "tuesday"), update(999, "finished", "today"),
                                           update(rice, "still_have", "today"), update(milk, "thrown_out", "today")],
                               "not_understood": "the bread"}]
    run_id = service.enqueue("Finished item A on Tuesday, still have item B, the bread went off", 4, config, today=TODAY)
    service.run(run_id, config, 4, Work("inference", "checkin_text", "Reading", sink=store.record_model_run), today=TODAY)
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    assert "Item A" in local_model["requests"][0]["messages"][0]["content"]
    staged = run["result"]["updates"]
    assert [(row["lot_id"], row["event"], row["effective_on"]) for row in staged] == [(milk, "finished", "2026-09-22"), (rice, "still_have", None)]
    assert [row["lot_id"] for row in run["result"]["set_aside"]] == [999, milk] and run["result"]["not_understood"] == "the bread"
    assert items.lot(milk)["status"] == "in_stock"  # Nothing changed before confirmation.
    assert service.apply(run_id, [milk], today=TODAY)["outcomes"] == [{"lot_id": milk, "status": "applied"}]
    assert (items.lot(milk)["status"], items.lot(milk)["closed_on"]) == ("finished", "2026-09-22")
    assert items.lot(rice)["check_interval_days"] is None  # Not confirmed, not applied.
    assert items.lot_history(milk)[-1]["source"] == "checkin_text"
    assert service.apply(run_id, [milk], today=TODAY)["outcomes"] == [{"lot_id": milk, "status": "already_applied"}]


def test_printed_return_policies_are_read_from_receipt_text():
    assert printed_return_days(["TOTAL 25.00", "Returns within 14 days with receipt"]) == (14, "Returns within 14 days with receipt")
    assert printed_return_days(["30-DAY RETURN POLICY"])[0] == 30
    assert printed_return_days(["ALL SALES FINAL"])[0] == 0
    assert printed_return_days(["Return up to 999 days"]) == (None, None)  # Implausible.
    assert printed_return_days(["THANK YOU", "2 ITEMS"]) == (None, None)


def test_opened_items_and_return_windows(shop):
    store, ledger, items, docs = shop
    soap = stock(items, ledger, docs["a.png"], 1, category="household cleaning", prefix="Soap")[0]
    bread = stock(items, ledger, docs["b.png"], 1, category="bakery", prefix="Bread")[0]
    [soap_view] = [lot for lot in items.inventory(today=TODAY) if lot["id"] == soap["id"]]
    # Walmart's typical 90-day policy applies to the non-food item bought Sep 10; food is never tracked.
    assert (soap_view["return_source"], soap_view["return_by"], soap_view["returnable"]) == ("policy", "2026-12-09", True)
    assert "Walmart policy (typical): 90 days" in soap_view["return_note"]
    [bread_view] = [lot for lot in items.inventory(today=TODAY) if lot["id"] == bread["id"]]
    assert (bread_view["openable"], bread_view["return_by"], bread_view["returnable"]) == (False, None, False)
    with pytest.raises(ValueError, match="Food"):
        items.update_lot(bread["id"], "opened", today=TODAY)
    # Opening it ends returnability; undo brings it back.
    assert items.update_lot(soap["id"], "opened", today=TODAY)["opened_on"] == TODAY.isoformat()
    with pytest.raises(ValueError, match="already marked opened"):
        items.update_lot(soap["id"], "opened", today=TODAY)
    assert not next(lot for lot in items.inventory(today=TODAY) if lot["id"] == soap["id"])["returnable"]
    assert items.undo_lot(soap["id"])["opened_on"] is None
    # A policy printed on the receipt wins over the merchant's; the user can change a merchant policy.
    with store.connection() as db:
        db.execute("UPDATE receipts SET return_days_printed=14,return_policy_quote='Returns within 14 days' WHERE id=?", (soap["receipt_id"],))
    printed = next(lot for lot in items.inventory(today=TODAY) if lot["id"] == soap["id"])
    assert (printed["return_source"], printed["return_by"], printed["returnable"]) == ("receipt", "2026-09-24", False)  # Closed yesterday.
    with store.connection() as db:
        db.execute("UPDATE receipts SET return_days_printed=NULL WHERE id=?", (soap["receipt_id"],))
    policy = items.set_policy("Walmart", 20, "My store's rule")
    assert (policy["source"], policy["days"]) == ("user", 20)
    assert [lot["id"] for lot in items.returns_closing(today=TODAY)] == [soap["id"]]  # Sep 30: within 14 days.
    assert items.returns_closing(within_days=3, today=TODAY) == []
    items.delete_policy(policy["id"])
    assert next(lot for lot in items.inventory(today=TODAY) if lot["id"] == soap["id"])["return_source"] is None
    with pytest.raises(ValueError, match="730"):
        items.set_policy("Target", 1000)


def test_receipts_to_identify_lists_unresolved_lines(shop):
    store, ledger, items, docs = shop
    receipt_id = receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", None, 348), ("DAWN ULT 19OZ", None, 329)])
    assert [(row["id"], row["lines"], row["unresolved"]) for row in items.receipts_to_identify()] == [(receipt_id, 2, 2)]
    items.propose(line_ids(items, receipt_id)[0], MILK, "search", "high")
    assert items.receipts_to_identify()[0]["unresolved"] == 1


def test_item_endpoints_and_assistant_inventory_tool(tmp_path, shop):
    store, ledger, items, docs = shop
    receipt_id = receipt(ledger, docs["a.png"], [("GV WHL MLK 1GL", None, 348)])
    items.review(items.propose(line_ids(items, receipt_id)[0], MILK, "search", "high")["id"], "verified", today=TODAY)
    found = call_tool(FinanceTools(store), "get_inventory", {"query": "milk"})
    assert found["items"][0]["product"] == MILK.name
    managed = store.root
    store.close()
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(managed)})
        [lot] = client.get("/api/inventory", params={"query": "milk"}).json()
        assert client.post(f"/api/inventory/lots/{lot['id']}/events", json={"event": "finished"}).json()["status"] == "finished"
        assert client.post(f"/api/inventory/lots/{lot['id']}/events", json={"event": "eaten"}).status_code == 422
        assert client.post(f"/api/inventory/lots/{lot['id']}/undo").json()["status"] == "in_stock"
        assert [event["event"] for event in client.get(f"/api/inventory/lots/{lot['id']}/history").json()] == ["created", "finished", "undone"]
        assert client.get(f"/api/receipts/{receipt_id}/items").json()[0]["resolution_status"] == "verified"
        assert client.get("/api/items/resolutions", params={"status": "verified"}).json()[0]["line"]["description"] == "GV WHL MLK 1GL"
        assert client.post("/api/items/resolutions/999/review", json={"status": "verified"}).status_code == 400
        assert client.post(f"/api/receipts/{receipt_id}/item-resolution-runs").status_code == 400  # Nothing left to resolve.
        assert client.get("/api/inventory/checkin").json()["weekday"] == 6  # Sunday unless changed.
        assert client.put("/api/household-settings", json={"home_currency": None, "checkin_weekday": 7}).status_code == 422
        client.put("/api/household-settings", json={"home_currency": None, "checkin_weekday": 2})
        assert client.get("/api/settings").json()["household"]["checkin_weekday"] == 2
        assert client.post(f"/api/inventory/lots/{lot['id']}/checkin-answer", json={"answer": "still_have"}).json()["check_interval_days"] == 7
        assert client.post(f"/api/inventory/lots/{lot['id']}/checkin-answer", json={"answer": "eaten"}).status_code == 422
        assert client.post("/api/inventory/checkin-runs", json={"answer": "finished it"}).status_code == 400  # No reasoning model set.
        assert client.get("/api/inventory/receipts-to-identify").json() == []
