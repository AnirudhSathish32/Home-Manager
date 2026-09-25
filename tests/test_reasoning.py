import copy
import json

import pytest
from fastapi.testclient import TestClient

from home_manager.api import create_app
from home_manager.manager import Manager
from home_manager.reasoning import ReasoningConfig
from home_manager.scanner import ScanLimits
from test_receipts import make_receipt


def proposal():
    return {"title": "Cafe purchase", "document_type": "receipt",
            "classification_evidence": [{"line_id": "line-1", "quote": "LOCAL TEST CAFE"}],
            "facts": [{"kind": "total", "value": "25.00 USD", "status": "proposed",
                       "evidence": [{"line_id": "line-7", "quote": "Total 25.00"},
                                    {"line_id": "line-3", "quote": "USD"}], "note": "Check the image."}],
            "receipt_items": [
                {"description": name, "product_code": None, "quantity": "1", "unit_price": price,
                 "line_total": price, "discount": None, "status": "proposed", "note": "",
                 "evidence": [{"line_id": f"line-{index}", "quote": f"{name} 1 @ {price} {price}"}]}
                for index, name, price in [(9, "LATTE", "5.00"), (10, "LATTE", "5.00"), (11, "SANDWICH", "10.00")]],
            "itemization_status": "itemized", "itemization_note": "All three printed item rows are listed separately.",
            "other_lines": [{"line_ids": ["line-1", "line-2", "line-3"], "kind": "header"},
                            {"line_ids": ["line-4", "line-5", "line-6", "line-7"], "kind": "totals"},
                            {"line_ids": ["line-8"], "kind": "footer"}],
            "insights": [{"kind": "fee", "observation": "The receipt includes a 3.00 tip.",
                          "evidence": [{"line_id": "line-6", "quote": "Tip 3.00"}]}],
            "limitations": ["Unverified transcription; one document cannot establish spending trends."]}


@pytest.fixture
def prepared(tmp_path, local_model):
    local_model["output"]["full_text"] += "\nLATTE 1 @ 5.00 5.00\nLATTE 1 @ 5.00 5.00\nSANDWICH 1 @ 10.00 10.00"
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    make_receipt(month / "receipt.png", local_model["output"]["full_text"].splitlines())
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    manager.configure(str(source), str(tmp_path / "managed"))
    manager.configure_vision(local_model["config"])
    manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    manager.start()
    manager.future.result(timeout=30)
    doc = manager.store.documents(source)["items"][0]
    run = manager.receipts.history(doc["id"])[0]["id"]
    assert manager.receipts.get(run)["status"] == "succeeded", manager.receipts.get(run)
    local_model["output"] = proposal()
    try:
        yield manager, doc, run
    finally:
        manager.close()


def test_analysis_http_provenance_reuse_and_preserved_text(prepared, local_model):
    manager, doc, parse_id = prepared
    before = copy.deepcopy(manager.receipts.get(parse_id))
    queued = manager.start_reasoning(doc["id"], parse_id)
    manager.future.result(timeout=10)
    run = manager.reasoning.get(queued["run_id"])
    assert run["status"] == "succeeded", run
    assert run["result"] == proposal()
    assert [item["description"] for item in run["result"]["receipt_items"]] == ["LATTE", "LATTE", "SANDWICH"]
    assert run["review_status"] == "needs_review"
    assert run["parse_run_id"] == parse_id
    assert manager.receipts.get(parse_id) == before
    payload = local_model["requests"][-1]
    assert payload["model"] == "synthetic-reasoning"
    assert isinstance(payload["messages"][1]["content"], str)
    assert "image_url" not in json.dumps(payload)
    assert json.loads(payload["messages"][1]["content"])["lines"][6] == {"line_id": "line-7", "text": "Total 25.00"}
    assert manager.start_reasoning(doc["id"], parse_id) == {"run_id": run["id"], "reused": True}
    assert manager.store.documents(manager.source)["items"][0]["folder"] == "Unfiled"
    with manager.store.connection() as db:
        db.execute("UPDATE reasoning_runs SET status='running' WHERE id=?", (run["id"],))
    manager.reasoning.recover()
    assert manager.reasoning.get(run["id"])["status"] == "interrupted"


@pytest.mark.parametrize("failure", ["invented_line", "altered_quote", "truncated", "unresolved_value", "schema", "omitted_item", "bad_item_quote", "duplicate_assignment", "false_complete"])
def test_invalid_analysis_does_not_replace_success(prepared, local_model, failure):
    manager, doc, parse_id = prepared
    first = manager.start_reasoning(doc["id"], parse_id)["run_id"]
    manager.future.result(timeout=10)
    if failure == "invented_line":
        local_model["output"]["facts"][0]["evidence"][0]["line_id"] = "line-999"
    elif failure == "altered_quote":
        local_model["output"]["facts"][0]["evidence"][0]["quote"] = "Total 999.99"
    elif failure == "truncated":
        local_model["finish_reason"] = "length"
    elif failure == "unresolved_value":
        local_model["output"]["facts"][0]["status"] = "ambiguous"
    elif failure == "omitted_item":
        local_model["output"]["receipt_items"].pop()
    elif failure == "bad_item_quote":
        local_model["output"]["receipt_items"][0]["evidence"][0]["quote"] = "LATTE 999.00"
    elif failure == "duplicate_assignment":
        local_model["output"]["other_lines"][0]["line_ids"].append("line-9")
    elif failure == "false_complete":
        local_model["output"]["receipt_items"][0]["status"] = "ambiguous"
    else:
        local_model["output"] = {"private": "PRIVATE_INVALID_OUTPUT"}
    second = manager.start_reasoning(doc["id"], parse_id, force=True)["run_id"]
    manager.future.result(timeout=10)
    result = manager.reasoning.get(second)
    assert result["status"] == "failed"
    assert result["result"] is None
    assert "PRIVATE_INVALID_OUTPUT" not in result["error"]
    assert manager.reasoning.get(first)["result"] == proposal()
    assert len(manager.reasoning.history(parse_id)) == 2
    if failure == "unresolved_value":
        assert "facts.0" in result["error"]
        assert "value=null" in result["error"]
    assert len(local_model["requests"]) == (3 if failure == "truncated" else 4)


@pytest.mark.parametrize("problem", ["ambiguous_value", "missing_line"])
def test_repairs_invalid_output_without_publishing_invalid_values(prepared, local_model, problem):
    manager, doc, parse_id = prepared
    bad = proposal()
    if problem == "ambiguous_value":
        bad["facts"][0]["status"] = "ambiguous"
    else:
        bad["receipt_items"].pop()
    local_model["outputs"] = [bad, proposal()]
    before = manager.receipts.get(parse_id)
    run_id = manager.start_reasoning(doc["id"], parse_id)["run_id"]
    manager.future.result(timeout=10)
    run = manager.reasoning.get(run_id)
    assert run["status"] == "succeeded", run
    assert run["result"] == proposal()
    assert manager.receipts.get(parse_id) == before
    assert len(local_model["requests"]) == 3  # vision, initial analysis, one correction
    repair = local_model["requests"][-1]["messages"][-1]["content"]
    if problem == "ambiguous_value":
        assert "facts.0" in repair and "value=null" in repair
    else:
        assert "line-11" in repair
    assert "COMPLETE JSON" in repair


def test_settings_persist_and_api_auth(tmp_path):
    control = tmp_path / "control"
    with TestClient(create_app(control, "secret"), base_url="http://127.0.0.1:8765") as client:
        assert client.put("/api/reasoning-settings", json={"model": "reasoner"}).status_code == 401
        headers = {"Authorization": "Bearer secret"}
        assert client.put("/api/reasoning-settings", headers=headers, json={"model": "reasoner", "base_url": "https://example.com/v1"}).status_code == 422
        assert client.put("/api/reasoning-settings", headers=headers, json={"model": "reasoner"}).status_code == 200
        assert client.get("/api/settings", headers=headers).json()["reasoning"]["model"] == "reasoner"
        assert client.post("/api/documents/1/reasoning-runs", headers=headers, json={"parse_run_id": "a" * 32}).status_code == 400
    manager = Manager(control)
    try:
        assert manager.reasoning_config.model == "reasoner"
    finally:
        manager.close()


def test_metadata_citations_count_without_duplicate_other_line_assignments(prepared, local_model):
    manager, doc, parse_id = prepared
    output = proposal()
    output["other_lines"][0]["line_ids"] = ["line-2"]  # merchant classification and currency fact already cite 1 and 3
    output["other_lines"][1]["line_ids"].remove("line-7")  # total fact already cites this line
    local_model["output"] = output
    run_id = manager.start_reasoning(doc["id"], parse_id)["run_id"]
    manager.future.result(timeout=10)
    assert manager.reasoning.get(run_id)["status"] == "succeeded"
    assert len(local_model["requests"]) == 2


def test_rejects_wrong_document_deleted_and_missing_model(prepared):
    manager, doc, parse_id = prepared
    with pytest.raises(ValueError):
        manager.start_reasoning(9999, parse_id)
    manager.configure_reasoning(ReasoningConfig())
    with pytest.raises(ValueError, match="Configure a local reasoning"):
        manager.start_reasoning(doc["id"], parse_id)
    manager.configure_reasoning(ReasoningConfig(model="reasoner"))
    manager.library_action(doc["id"], doc["current_hash"], "trash")
    with pytest.raises(ValueError, match="Restore"):
        manager.start_reasoning(doc["id"], parse_id)
