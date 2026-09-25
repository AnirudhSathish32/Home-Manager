"""Phase 2: model telemetry, model identity, independent queues and cancellation."""

import threading
import time

from fastapi.testclient import TestClient

from home_manager.api import create_app
from home_manager.manager import Manager
from home_manager.scanner import ScanLimits
from test_reasoning import prepared, proposal  # noqa: F401 (fixture)
from test_receipts import make_receipt


def model_runs(manager, owner):
    return manager.store.model_runs(owner)


def test_transcription_and_analysis_record_inference_telemetry(prepared, local_model):
    manager, doc, parse_id = prepared
    [transcription] = model_runs(manager, parse_id)
    assert transcription["task"] == "transcription" and transcription["status"] == "succeeded"
    assert transcription["model_id"] == "synthetic-vision" and transcription["model_identity"]
    assert transcription["prompt_version"] == manager.receipts.get(parse_id)["parser_version"]
    assert transcription["metrics_source"] == "estimated"  # No server usage: labelled estimate.
    assert transcription["time_to_first_token_ms"] is not None and transcription["total_ms"] > 0
    assert '"n_params"' in transcription["metadata_json"]
    local_model["timings"] = {"prompt_n": 812, "prompt_ms": 400.0, "prompt_per_second": 2030.0,
                              "predicted_n": 256, "predicted_ms": 5120.0, "predicted_per_second": 50.0}
    run_id = manager.start_reasoning(doc["id"], parse_id)["run_id"]
    manager.future.result(timeout=10)
    [analysis] = model_runs(manager, run_id)
    assert analysis["task"] == "reasoning" and analysis["metrics_source"] == "server_timings"
    assert (analysis["prompt_tokens"], analysis["completion_tokens"]) == (812, 256)
    assert analysis["generation_tokens_per_second"] == 50.0 and analysis["prompt_eval_ms"] == 400.0
    assert manager.reasoning.get(run_id)["model_runs"][0]["id"] == analysis["id"]


def test_changed_weights_or_unknown_identity_never_reuse_results(prepared, local_model):
    manager, doc, parse_id = prepared
    first = manager.start_reasoning(doc["id"], parse_id)["run_id"]
    manager.future.result(timeout=10)
    assert manager.start_reasoning(doc["id"], parse_id) == {"run_id": first, "reused": True}
    manager.future.result(timeout=10)
    # Same model ID, different weights: the server metadata changes, so the cache key does.
    local_model["model_meta"] = {"size": 5_100_000_000, "n_params": 9_000_000_000}
    second = manager.start_reasoning(doc["id"], parse_id)
    manager.future.result(timeout=10)
    assert not second["reused"] and second["run_id"] != first
    # A server that cannot identify its model disables reuse instead of trusting the ID.
    local_model["models"] = None
    third = manager.start_reasoning(doc["id"], parse_id)
    manager.future.result(timeout=10)
    assert not third["reused"]
    assert manager.reasoning.get(third["run_id"])["status"] == "succeeded"
    requests = len(local_model["requests"])
    batch = manager.start_receipt_batch()["batch_id"]
    manager.future.result(timeout=30)
    assert manager.batches.get(batch)["reused"] == 0 and len(local_model["requests"]) == requests + 1


def test_cancel_releases_inference_queue_during_silent_prompt_processing(prepared, local_model):
    manager, doc, parse_id = prepared
    first = manager.start_reasoning(doc["id"], parse_id)["run_id"]
    manager.future.result(timeout=10)
    local_model["response_gate"] = threading.Event()  # Server sends headers, then no bytes.
    run_id = manager.start_reasoning(doc["id"], parse_id, force=True)["run_id"]
    for _ in range(100):
        if len(local_model["requests"]) == 3:
            break
        time.sleep(.05)
    assert manager.busy("inference")
    # Library actions and capture are not blocked by model generation.
    manager.library_action(doc["id"], doc["current_hash"], "move", "Receipts")
    scan = manager.start()
    started = time.monotonic()
    assert manager.cancel()["cancelled"]
    for _ in range(100):
        if not manager.busy("inference"):
            break
        time.sleep(.05)
    assert not manager.busy("inference") and time.monotonic() - started < 3
    run = manager.reasoning.get(run_id)
    assert run["status"] == "cancelled" and run["result"] is None and "Cancelled" in run["error"]
    assert manager.reasoning.get(first)["result"] == proposal()  # Earlier results are preserved.
    assert [row["status"] for row in model_runs(manager, run_id)] == ["cancelled"]
    manager.future.result(timeout=30)
    assert manager.store.job(scan)["status"] == "completed"
    assert manager.store.documents(manager.source)["items"][0]["folder"] == "Receipts"
    local_model["response_gate"].set()
    local_model.pop("response_gate")
    retry = manager.start_reasoning(doc["id"], parse_id, force=True)["run_id"]
    manager.future.result(timeout=10)
    assert manager.reasoning.get(retry)["status"] == "succeeded"


def test_cancelled_batch_marks_remaining_runs_and_api_exposes_activity(tmp_path, local_model):
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    for index in range(3):
        make_receipt(month / f"receipt-{index}.png", [f"RECEIPT {index}", "Total 1.00"])
    app = create_app(tmp_path / "control", "jobs-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer jobs-token"}) as client:
        manager = app.state.manager
        local_model["config"].organize_after_scan = False
        client.put("/api/settings", json={"source_directory": str(source), "managed_directory": str(tmp_path / "managed")})
        client.put("/api/vision-settings", json=local_model["config"].model_dump())
        manager.start()
        manager.future.result(timeout=30)
        local_model["response_gate"] = threading.Event()
        batch = client.post("/api/receipt-batches", json={}).json()["batch_id"]
        for _ in range(200):
            if local_model["requests"]:
                break
            time.sleep(.05)
        activity = client.get("/api/activity").json()
        assert [(item["queue"], item["kind"], item["status"]) for item in activity] == [("inference", "transcription", "running")]
        assert client.get("/api/settings").json()["inference_busy"] is True
        assert client.post("/api/activity/cancel", json={"work_id": "0" * 32}).status_code == 400
        assert client.post("/api/activity/cancel", json={"work_id": activity[0]["id"]}).json() == {"cancelled": [activity[0]["id"]]}
        manager.future.result(timeout=10)
        status = client.get(f"/api/receipt-batches/{batch}").json()
        assert status["status"] == "cancelled" and status["counts"] == {"cancelled": 3}
        assert len(local_model["requests"]) == 1  # Remaining images were never sent.
        assert client.get("/api/activity").json() == []
        history = client.get("/api/model-runs").json()
        assert [row["status"] for row in history] == ["cancelled"]
        assert client.get("/api/model-runs", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_monitor_and_directory_changes_respect_queues(tmp_path, local_model):
    source = tmp_path / "source"
    (source / "2026" / "09").mkdir(parents=True)
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(source), str(tmp_path / "managed"))
        # Without auto-transcription, the Inbox scan has no model follow-up to queue.
        manager.configure_vision(local_model["config"].model_copy(update={"organize_after_scan": False}))
        gate, entered = threading.Event(), threading.Event()
        manager.submit("inference", "test", "Held model work", lambda work: (entered.set(), gate.wait(10)))
        assert entered.wait(5)
        try:
            assert manager.busy("inference") and not manager.busy("capture")
            job = manager.start_inbox()  # Capture is independent of model work.
            manager.future.result(timeout=10)
            assert manager.store.job(job)["status"] == "completed"
            for call in (lambda: manager.configure(str(source), str(tmp_path / "managed")),
                         lambda: manager.configure_vision(local_model["config"])):
                try:
                    call()
                    raise AssertionError("Expected a conflict while model work is running.")
                except RuntimeError:
                    pass
        finally:
            gate.set()
    finally:
        manager.close()
