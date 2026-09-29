"""Filing from a saved analysis: only with a cited analysis, never over a manual or existing filing, and runs a
stopped app left behind are marked interrupted."""

import pytest

from home_manager.library.organization import OrganizationService
from test_reasoning import prepared, proposal  # noqa: F401 (prepared is a fixture)


def test_filing_needs_a_saved_analysis_and_never_repeats_or_overrides(prepared, local_model):
    manager, doc, parse_id = prepared
    service = OrganizationService(manager.store)
    with pytest.raises(ValueError, match="Analyze the transcription"):
        service.enqueue(doc["id"], doc["current_hash"])
    result = proposal()  # Filing names the document from its cited merchant and date.
    result["facts"] += [
        {"kind": "merchant", "value": "Local Test Cafe", "status": "proposed", "note": "", "evidence": [{"line_id": "line-1", "quote": "LOCAL TEST CAFE"}]},
        {"kind": "purchase_date", "value": "2026-09-22", "status": "proposed", "note": "", "evidence": [{"line_id": "line-2", "quote": "2026-09-22"}]}]
    local_model["output"] = result
    manager.start_reasoning(doc["id"], parse_id)
    manager.future.result(timeout=15)
    filed = manager.store.documents()["items"][0]
    assert filed["folder"] == "Receipts"  # Filed automatically from the analysis.
    service.enqueue(doc["id"], doc["current_hash"])  # Filing again from the same analysis changes nothing.
    assert manager.store.documents()["items"][0]["managed_path"] == filed["managed_path"]
    manager.library_action(doc["id"], doc["current_hash"], "move", "Housing")
    with pytest.raises(ValueError, match="manual folder choice"):
        service.enqueue(doc["id"], doc["current_hash"])
    assert manager.store.documents()["items"][0]["folder"] == "Housing"
    with manager.store.connection() as db:
        intent = db.execute("SELECT id FROM managed_organization_intents ORDER BY rowid DESC LIMIT 1").fetchone()[0]
    assert service.get(intent)["id"] == intent
    with pytest.raises(ValueError, match="not found"):
        service.get("no-such-run")


def test_runs_left_running_are_marked_interrupted(prepared):
    manager, doc, parse_id = prepared
    with manager.store.connection() as db:
        db.execute("INSERT INTO organization_runs(id,document_id,blob_hash,parse_run_id,config_json,status,created_at,updated_at) "
                   "VALUES('legacy-run',?,?,?,'{}','running','t','t')", (doc["id"], doc["current_hash"], parse_id))
    service = OrganizationService(manager.store)
    service.recover()
    run = service.get("legacy-run")
    assert run["status"] == "interrupted" and "Use Move" in run["error"]
