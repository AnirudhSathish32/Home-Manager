import base64
import time

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

from home_manager.api import create_app
from home_manager.manager import Manager
from home_manager.scanner import ScanLimits, Scanner
from home_manager.vision import VisionConfig, transcribe
from test_receipts import make_receipt


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://192.168.1.2:1234/v1", "http://localhost:1234/v1",
                                 "http://127.0.0.1:1234/other", "http://user:pass@127.0.0.1:1234/v1", "http://127.0.0.1:1234/v1?x=1"])
def test_model_endpoints_are_loopback_only(url):
    with pytest.raises(ValidationError):
        VisionConfig(base_url=url, model="test")


def test_real_http_image_payload_and_invalid_responses(tmp_path, local_model):
    image = tmp_path / "receipt.png"
    make_receipt(image)
    output = transcribe(local_model["config"], image)
    assert output.title == local_model["output"]["title"]
    request = local_model["requests"][0]
    assert local_model["path"] == "/v1/chat/completions"
    assert request["model"] == "synthetic-vision"
    assert request["response_format"]["type"] == "json_schema"
    schema = request["response_format"]["json_schema"]["schema"]
    assert schema["required"] == ["title", "full_text", "folder"]
    assert "03_Purchases/Receipts" in schema["properties"]["folder"]["enum"]
    payload = request["messages"][1]["content"][1]["image_url"]["url"]
    assert base64.b64decode(payload.split(",", 1)[1]) == image.read_bytes()
    local_model["finish_reason"] = "length"
    with pytest.raises(ValueError, match="truncated"):
        transcribe(local_model["config"], image)
    local_model["finish_reason"] = "stop"
    local_model["output"] = {"title": "", "full_text": "invented"}
    with pytest.raises(ValidationError):
        transcribe(local_model["config"], image)
    local_model["status"] = 302
    with pytest.raises(ValueError, match="redirects"):
        transcribe(local_model["config"], image)


@pytest.mark.parametrize("status,body,expected", [
    (400, "unsupported response_format json_object", "structured output"),
    (500, "CUDA out of memory", "insufficient memory"),
    (400, "input exceeds context length", "context limit"),
    (401, "missing token", "authorization"),
    (400, "missing mmproj", "vision component"),
    (400, "unknown server error", "rejection reason"),
])
def test_server_errors_are_actionable_without_echoing_private_content(tmp_path, local_model, status, body, expected):
    image = tmp_path / "receipt.png"
    make_receipt(image)
    local_model.update(status=status, error_body=body + " PRIVATE_RECEIPT_TEXT")
    with pytest.raises(ValueError) as error:
        transcribe(local_model["config"], image)
    assert f"HTTP {status}" in str(error.value)
    assert expected in str(error.value)
    assert "PRIVATE_RECEIPT_TEXT" not in str(error.value)


def wait(manager):
    manager.future.result(timeout=30)


def test_batch_versions_duplicates_failures_reuse_and_restart(tmp_path, local_model):
    local_model["config"].organize_after_scan = False
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    original = month / "receipt.png"
    qr = make_receipt(original)
    duplicate = month / "copy.png"
    duplicate.write_bytes(original.read_bytes())
    (month / "bad.jpg").write_bytes(b"not an image")
    (month / "statement.csv").write_text("date,total\n2026-09-22,25\n")
    control = tmp_path / "control"
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(source), str(tmp_path / "managed"))
        manager.configure_vision(local_model["config"])
        manager.start(); wait(manager)
        batch = manager.start_receipt_batch()["batch_id"]
        wait(manager)
        status = manager.batches.get(batch)
        assert status["counts"] == {"succeeded": 2, "failed": 1}, status
        assert status["total"] == 3 and status["unique_runs"] == 2 and status["skipped"] == 1
        assert status["status"] == "partial"
        assert len(local_model["requests"]) == 1
        documents = manager.store.documents(source)["items"]
        receipt = next(doc for doc in documents if doc["relative_path"].endswith("receipt.png"))
        assert receipt["title"] == local_model["output"]["title"]
        run = manager.receipts.history(receipt["id"])[0]
        result = manager.receipts.get(run["id"])["result"]
        assert result["transcription_method"] == "vision_model"
        assert result["model_text"] == local_model["output"]["full_text"]
        assert qr in result["extracted_text"]
        assert result["fields"]["calculation_status"] == "matches"
        assert not result["blocks"]  # Never fabricate spatial evidence for generated text.
        old_hash = receipt["current_hash"]
        manager.start_receipt_batch(); wait(manager)
        assert len(local_model["requests"]) == 1
        manager.start_receipt_batch(force=True); wait(manager)
        assert len(local_model["requests"]) == 2
        # A changed source version cannot inherit the older generated title.
        original.write_bytes(original.read_bytes() + b"changed bytes")
        manager.start(); wait(manager)
        receipt = next(doc for doc in manager.store.documents(source)["items"] if doc["id"] == receipt["id"])
        assert receipt["title"] is None
        assert manager.receipts.history(receipt["id"], old_hash)
    finally:
        manager.close()
    manager = Manager(control)
    try:
        assert manager.vision == local_model["config"]
        assert manager.batches.latest(source)["status"] == "partial"
        pending = manager.batches.enqueue(source, manager.vision, force=True)
    finally:
        manager.close()
    manager = Manager(control)
    try:
        assert manager.batches.get(pending)["status"] == "interrupted"
        assert manager.batches.get(pending)["counts"]["interrupted"] == 3
    finally:
        manager.close()


def test_batch_api_settings_auth_and_busy(tmp_path, local_model, monkeypatch):
    import threading
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    make_receipt(month / "receipt.png")
    app = create_app(tmp_path / "control", "test-token", limits=ScanLimits(stability_seconds=0))
    auth = {"Authorization": "Bearer test-token"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/receipt-batches", json={}).status_code == 401
        assert client.put("/api/vision-settings", json={}).status_code == 401
        client.headers.update(auth)
        assert client.put("/api/settings", json={"source_directory":str(source), "managed_directory":str(tmp_path / "managed")}).status_code == 200
        assert client.post("/api/receipt-batches", json={}).status_code == 400
        assert client.put("/api/vision-settings", json=local_model["config"].model_dump()).status_code == 200
        manager = app.state.manager
        manager.start(); wait(manager)
        entered, release = threading.Event(), threading.Event()
        original = manager.batches.run
        def held(batch):
            entered.set()
            release.wait(timeout=15)
            original(batch)
        monkeypatch.setattr(manager.batches, "run", held)
        try:
            response = client.post("/api/receipt-batches", json={})
            assert response.status_code == 202
            assert entered.wait(timeout=5)
            assert client.post("/api/receipt-batches", json={}).status_code == 409
            assert client.put("/api/vision-settings", json=local_model["config"].model_dump()).status_code == 409
        finally:
            release.set()
        wait(manager)
        assert client.get("/api/receipt-batches/" + response.json()["batch_id"]).json()["status"] == "completed"
