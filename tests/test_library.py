from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from home_manager.api import create_app
from home_manager.scanner import ScanLimits
from home_manager.vision import VisionTranscription
from test_receipts import make_receipt


def test_folder_enum_rejects_model_filesystem_paths():
    for folder in ("../../Sources", "P:/Finances", "Trash", "01_Banking", "invented"):
        with pytest.raises(ValidationError):
            VisionTranscription(title="Receipt", full_text="USD 25.00", folder=folder)


def test_scan_organizes_trash_is_confirmed_and_persistent(tmp_path, local_model):
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    image = month / "receipt.png"
    make_receipt(image)
    original_bytes = image.read_bytes()
    (month / "copy.png").write_bytes(original_bytes)
    (month / "statement.csv").write_text("date,amount\n2026-09-22,25\n")
    control = tmp_path / "control"
    app = create_app(control, "local-test", limits=ScanLimits(stability_seconds=0))
    auth = {"Authorization": "Bearer local-test"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/folders").status_code == 401
        assert client.post("/api/documents/1/trash", json={}).status_code == 401
        client.headers.update(auth)
        client.put("/api/settings", json={"source_directory": str(source), "managed_directory": str(tmp_path / "managed")})
        client.put("/api/vision-settings", json=local_model["config"].model_dump())
        scan = client.post("/api/scans", json={}).json()["job_id"]
        manager = app.state.manager
        manager.future.result(timeout=30)
        job = client.get(f"/api/scans/{scan}").json()
        assert job["status"] == "completed"
        assert job["organization_status"] == "completed", job
        assert len(local_model["requests"]) == 1
        docs = client.get("/api/documents", params={"folder": "03_Purchases/Receipts"}).json()
        assert docs["total"] == 2
        doc = next(doc for doc in docs["items"] if doc["relative_path"].endswith("receipt.png"))
        digest = doc["current_hash"]
        blob = manager.store.blob_path(digest)
        assert client.get("/api/documents", params={"folder": "Unfiled"}).json()["total"] == 1
        assert client.get("/api/documents", params={"folder": "03_Purchases"}).json()["total"] == 2
        counts = client.get("/api/folders").json()["counts"]
        assert counts["03_Purchases"] == counts["03_Purchases/Receipts"] == 2
        assert client.get("/api/documents?folder=../../invalid").status_code == 400
        base = f"/api/documents/{doc['id']}"
        assert client.put(base + "/folder", json={"expected_hash": digest, "folder": "../invalid"}).status_code == 422
        assert client.put(base + "/folder", json={"expected_hash": digest, "folder": "04_Bills/Utilities"}).status_code == 200
        assert client.get("/api/documents?folder=04_Bills/Utilities").json()["total"] == 1
        assert client.post(base + "/trash", json={"expected_hash": digest}).status_code == 422
        assert client.post(base + "/trash", json={"expected_hash": digest, "confirmed": False}).status_code == 422
        assert client.post(base + "/trash", json={"expected_hash": "a"*64, "confirmed": True}).status_code == 409
        assert client.post(base + "/trash", json={"expected_hash": digest, "confirmed": True}).status_code == 200
        assert client.get("/api/documents").json()["total"] == 2
        assert client.get("/api/documents?folder=trash").json()["total"] == 1
        assert client.post(base + "/receipt-runs", json={}).status_code == 400
        assert client.put(base + "/folder", json={"expected_hash": digest, "folder": "Unfiled"}).status_code == 400
        manager.start(); manager.future.result(timeout=30)
        assert client.get("/api/documents?folder=trash").json()["total"] == 1
        assert image.read_bytes() == blob.read_bytes() == original_bytes
    # Trash survives restart and does not affect an identical active occurrence.
    app = create_app(control, "local-test", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers=auth) as client:
        manager = app.state.manager
        assert client.get("/api/documents?folder=trash").json()["total"] == 1
        batch = manager.start_receipt_batch(force=True)["batch_id"]
        manager.future.result(timeout=30)
        assert manager.batches.get(batch)["total"] == 1
        assert client.post(base + "/restore", json={"expected_hash": digest}).status_code == 200
        assert client.get("/api/documents?folder=04_Bills/Utilities").json()["total"] == 1
        manager.start_receipt_batch(force=True); manager.future.result(timeout=30)
        assert client.get("/api/documents?folder=04_Bills/Utilities").json()["total"] == 1  # Manual choice wins.
        image.write_bytes(original_bytes + b"new version")
        manager.start(); manager.future.result(timeout=30)
        assert client.get("/api/documents?folder=04_Bills/Utilities").json()["total"] == 0
        assert client.get("/api/documents?folder=03_Purchases/Receipts").json()["total"] == 2
        assert client.post(base + "/trash", json={"expected_hash": digest, "confirmed": True}).status_code == 409


def test_bad_classification_keeps_capture_unfiled(tmp_path, local_model):
    from home_manager.manager import Manager
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    make_receipt(month / "receipt.png")
    local_model["output"]["folder"] = "../../escape"
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(source), str(tmp_path / "managed"))
        manager.configure_vision(local_model["config"])
        scan = manager.start()
        manager.future.result(timeout=30)
        assert manager.store.job(scan)["status"] == "completed"
        assert manager.store.job(scan)["organization_status"] == "partial"
        assert manager.store.documents(source, folder="Unfiled")["total"] == 1
        doc = manager.store.documents(source)["items"][0]
        assert doc["title"] is None and doc["parse_status"] == "failed"
    finally:
        manager.close()
