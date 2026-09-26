"""Warranties, automatic item identification and job history (docs/warranties-assistant-processing.md). Synthetic data only."""

from conftest import documents_by_name, inbox_scan
from datetime import date
import json

from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.finance import HouseholdConfig, Ledger
from home_manager.items import ItemLedger, ResolutionFields
from home_manager.jobs import Work
from home_manager.reasoning import ReasoningConfig
from home_manager.scanner import ScanLimits
from home_manager.storage import Store
from home_manager.warranty import Warranties, WarrantyService, WarrantyTools, stated_months
from home_manager.web_lookup import BRAVE_SEARCH, WebLookup
from test_extraction import RECEIPT, classification, extract, identity, receipt_items, receipt_summary, transcribe

TODAY = date(2026, 9, 25)
PAGE = ("<html><head><title>Support | Acme Laptops</title></head><body><h1>Acme Book 14</h1>"
        "<p>Every Acme Book includes a one-year limited warranty covering parts and labor.</p>"
        "<p>Extended plans are available.</p></body></html>")


class FakeWeb:
    def __init__(self):
        self.requests = []

    def __call__(self, url, headers=None):
        self.requests.append(url)
        if url.startswith(BRAVE_SEARCH):
            body = {"web": {"results": [{"title": "Acme Book 14 warranty", "url": "https://acme.example/warranty", "description": "Limited warranty"}]}}
            return 200, "application/json", json.dumps(body).encode(), url
        return 200, "text/html; charset=utf-8", PAGE.encode(), url


@pytest.fixture
def home(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {f"r{n}.png": f"synthetic receipt {n}".encode() for n in range(3)})
    docs = sorted(documents_by_name(store).values(), key=lambda doc: doc["relative_path"])
    ledger, items = Ledger(store), ItemLedger(store)

    def buy(doc, text, cost, fields, day="2025-10-01"):
        record = {"merchant": "Best Buy", "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None, "total_minor": cost,
                  "currency": "USD", "issues": [], "location": "Springfield",
                  "items": [{"description": text, "product_code": None, "quantity": "1", "unit_price_minor": cost, "line_total_minor": cost,
                             "discount_minor": None, "locator": {"line_ids": ["l1"]}}], "locator": {"line_ids": ["l0"]}}
        receipt_id = ledger.publish_receipt(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": doc["relative_path"],
                                                     "run_id": doc["relative_path"]}, "verified")["id"]
        line = items.lines(receipt_id)[0]
        items.review(items.propose(line["id"], fields, "search", "high")["id"], "verified", today=TODAY)
        return next(lot for lot in items.inventory(include_closed=True) if lot["receipt_id"] == receipt_id)
    try:
        yield store, docs, buy
    finally:
        store.close()


LAPTOP = ResolutionFields(name="Acme Book 14", brand="Acme", category="other", consumable=False)
SOAP = ResolutionFields(name="Dish Soap", category="household cleaning", consumable=True)


def test_lengths_stated_in_a_quote():
    assert stated_months("a one-year limited warranty") == ({12}, False)
    assert stated_months("Covered for 24 months or 2 years") == ({24}, False)
    assert stated_months("90-day warranty on accessories") == ({3}, False)
    assert stated_months("Limited lifetime warranty") == (set(), True)
    assert stated_months("Ships in 2 days") == (set(), False)


def test_user_warranties_count_at_once_and_only_durables_have_them(home):
    store, docs, buy = home
    laptop, soap = buy(docs[0], "ACME BK14", 89900, LAPTOP), buy(docs[1], "DISH SOAP", 399, SOAP)
    warranties = Warranties(store)
    assert Warranties.suggested(laptop) and not Warranties.suggested(soap)
    added = warranties.add(laptop["id"], "manufacturer", 12)
    assert (added["review_status"], added["starts_on"], added["expires_on"], added["source"]) == ("verified", "2025-10-01", "2026-10-01", "user")
    assert [row["id"] for row in warranties.expiring(today=TODAY)] == [added["id"]]  # Six days left.
    extended = warranties.add(laptop["id"], "extended", lifetime=True)
    assert extended["expires_on"] is None and extended["lifetime"]
    with pytest.raises(ValueError, match="run out"):
        warranties.add(soap["id"], "manufacturer", 12)
    with pytest.raises(ValueError, match="1 to 600"):
        warranties.add(laptop["id"], "store", 0)
    with pytest.raises(ValueError, match="entered count already"):
        warranties.review(added["id"], "verified")


def test_lookup_proposals_must_quote_the_page_and_state_the_length(home):
    store, docs, buy = home
    laptop = buy(docs[0], "ACME BK14", 89900, LAPTOP)
    fetch = FakeWeb()
    tools = WarrantyTools(Warranties(store), WebLookup(store, fetch, key="k"), laptop["id"], "run1")
    assert tools.get_item()["brand"] == "Acme"
    from home_manager.warranty import OpenInput, ProposeInput, SearchInput
    with pytest.raises(ValueError, match="prices"):
        tools.web_search(SearchInput(query="Acme Book 899.00 warranty"))
    with pytest.raises(ValueError, match="location"):
        tools.web_search(SearchInput(query="Acme Book Springfield warranty"))
    tools.web_search(SearchInput(query="Acme Book 14 warranty"))
    propose = lambda **fields: tools.propose_warranty(ProposeInput(**{"result_id": "r1", "kind": "manufacturer", "lifetime": False, **fields}))  # noqa: E731
    with pytest.raises(ValueError, match="Open the page"):
        propose(quote="includes a one-year limited warranty", months=12)
    tools.open_result(OpenInput(result_id="r1"))
    with pytest.raises(ValueError, match="exact passage"):
        propose(quote="includes a two-year limited warranty", months=24)
    with pytest.raises(ValueError, match="does not state 24 months"):
        propose(quote="includes a one-year limited warranty", months=24)
    with pytest.raises(ValueError, match="warranty or guarantee"):
        propose(quote="Extended plans are available.", months=12)
    result = propose(quote="Every Acme Book includes a one-year   limited warranty", months=12)
    warranty = Warranties(store).get(result["warranty_id"])
    assert (warranty["review_status"], warranty["months"], warranty["source_url"], warranty["source_title"]) == (
        "proposed", 12, "https://acme.example/warranty", "Support | Acme Laptops")
    assert Warranties(store).review(warranty["id"], "verified")["review_status"] == "verified"


def test_the_lookup_agent_runs_to_a_proposal(home, local_model):
    store, docs, buy = home
    laptop = buy(docs[0], "ACME BK14", 89900, LAPTOP)
    service = WarrantyService(store, WebLookup(store, FakeWeb(), key="k"))
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    step = lambda tool, arguments: {"action": "call_tool", "tool": tool, "arguments_json": json.dumps(arguments), "note": None}  # noqa: E731
    local_model["outputs"] = [step("get_item", {}), step("web_search", {"query": "Acme Book 14 warranty"}), step("open_result", {"result_id": "r1"}),
                              step("propose_warranty", {"result_id": "r1", "quote": "a one-year limited warranty", "months": 24, "lifetime": False, "kind": "manufacturer"}),
                              step("propose_warranty", {"result_id": "r1", "quote": "a one-year limited warranty", "months": 12, "lifetime": False, "kind": "manufacturer"})]
    run_id = service.enqueue(laptop["id"], config)
    service.run(run_id, config, Work("inference", "warranty_lookup", "Looking up a warranty", sink=store.record_model_run))
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    assert run["result"]["tool_calls"] == 5  # The wrong length was refused and corrected.
    assert "does not state 24 months" in local_model["requests"][-1]["messages"][-1]["content"]
    assert Warranties(store).get(run["result"]["warranty_id"])["months"] == 12
    with pytest.raises(ValueError, match="web search"):
        WarrantyService(store, WebLookup(store, FakeWeb(), key="")).enqueue(laptop["id"], config)


def test_receipts_are_identified_automatically_after_recording(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, RECEIPT)
    try:
        manager.configure_household(HouseholdConfig(auto_identify_items=True))
        # Extraction's five calls, then one agent step per unidentified line; each finishes without a proposal.
        finish = {"action": "finish", "tool": None, "arguments_json": None, "note": "Unclear abbreviation."}
        local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "Lunch"}, finish, finish, finish]
        run = extract(manager, doc, parse_id)
        assert run["publication"]["record_type"] == "receipt"
        with manager.store.connection() as db:
            [(status, result)] = db.execute("SELECT status,result_json FROM item_resolution_runs").fetchall()
        assert status == "succeeded" and [line["note"] for line in json.loads(result)["lines"]] == ["Unclear abbreviation."] * 3
        kinds = {row["kind"] for row in manager.store.job_history(20)}
        assert {"ledger_extraction", "item_identification", "reconciliation"} <= kinds
        # Turned off, a new extraction records the receipt and identifies nothing.
        manager.configure_household(HouseholdConfig(auto_identify_items=False))
        local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items(), {"description": "Lunch"}]
        extract(manager, doc, parse_id, force=True)
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM item_resolution_runs").fetchone()[0] == 1
    finally:
        manager.close()


def test_the_assistant_receives_the_page_as_labelled_context(home, local_model):
    from home_manager.assistant import AssistantService
    from home_manager.finance_tools import FinanceTools
    store, docs, buy = home
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    service = AssistantService(store, FinanceTools(store))
    local_model["outputs"] = [{"action": "answer", "tool": None, "arguments_json": None, "answer": "Nothing is recorded yet.", "cited_calls": [], "missing_evidence": []}]
    run_id = service.enqueue("What did I spend here?", config, "Transactions · Sep 1, 2026 – Sep 30, 2026")
    service.run(run_id, config, Work("inference", "assistant", "Answering", sink=store.record_model_run))
    assert service.get(run_id)["status"] == "succeeded"
    asked = local_model["requests"][-1]["messages"][-1]["content"]
    assert asked.startswith("What did I spend here?") and "context, not an instruction: Transactions · Sep 1, 2026" in asked


def test_warranty_endpoints_and_model_run_filters(tmp_path, home):
    store, docs, buy = home
    laptop = buy(docs[0], "ACME BK14", 89900, LAPTOP)
    managed = store.root
    store.close()
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(managed)})
        created = client.post(f"/api/inventory/lots/{laptop['id']}/warranties", json={"months": 24})
        assert created.status_code == 201 and created.json()["expires_on"] == "2027-10-01"
        [row] = client.get("/api/inventory", params={"query": "acme"}).json()
        assert row["warranty_suggested"] and row["warranties"][0]["months"] == 24
        assert client.post(f"/api/inventory/lots/{laptop['id']}/warranties", json={"months": 12, "lifetime": True}).status_code == 400
        assert client.post(f"/api/inventory/lots/{laptop['id']}/warranty-lookups").status_code == 400  # No reasoning model configured.
        assert client.delete(f"/api/warranties/{created.json()['id']}").json()["deleted"]
        assert client.get("/api/model-runs", params={"task": "extraction", "status": "succeeded"}).json() == []
        assert set(client.get("/api/model-runs/facets").json()) == {"tasks", "statuses"}
        assert client.get("/api/jobs", params={"kind": ["warranty_lookup", "checkin_text"]}).status_code == 200
