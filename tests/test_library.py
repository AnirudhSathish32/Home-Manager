from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from home_manager.api import create_app
from home_manager.scanner import ScanLimits
from home_manager.vision import VisionText
from test_receipts import make_receipt


def test_vision_rejects_interpretation_fields():
    for extra in ({"folder": "Receipts"}, {"title": "Receipt"}, {"total": "25.00"}):
        with pytest.raises(ValidationError):
            VisionText(full_text="USD 25.00", **extra)


def test_scan_transcribes_trash_is_confirmed_and_persistent(tmp_path, local_model):
    control = tmp_path / "control"
    app = create_app(control, "local-test", limits=ScanLimits(stability_seconds=0))
    auth = {"Authorization": "Bearer local-test"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get("/api/folders").status_code == 401
        assert client.post("/api/documents/1/trash", json={}).status_code == 401
        client.headers.update(auth)
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        month = app.state.manager.store.library.inbox
        image = month / "receipt.png"
        make_receipt(image)
        original_bytes = image.read_bytes()
        (month / "copy.png").write_bytes(original_bytes)
        (month / "statement.csv").write_text("date,amount\n2026-09-22,25\n")
        client.put("/api/vision-settings", json=local_model["config"].model_dump())
        scan = client.post("/api/inbox-scans", json={}).json()["job_id"]
        manager = app.state.manager
        manager.future.result(timeout=30)
        job = client.get(f"/api/scans/{scan}").json()
        assert job["status"] == "completed"
        assert job["organization_status"] == "completed", job
        assert len(local_model["requests"]) == 1
        docs = client.get("/api/documents", params={"folder": "Inbox"}).json()  # Unclassified Inbox documents stay in Inbox.
        assert docs["total"] == 3
        doc = next(doc for doc in docs["items"] if doc["relative_path"].endswith("receipt.png"))
        assert doc["title"] is None and doc["parse_status"] == "succeeded"
        digest = doc["current_hash"]
        blob = manager.store.blob_path(digest)
        assert client.get("/api/documents", params={"folder": "Inbox"}).json()["total"] == 3
        assert client.get("/api/documents", params={"folder": "Receipts"}).json()["total"] == 0
        counts = client.get("/api/folders").json()["counts"]
        assert counts["Receipts"] == 0 and "03_Purchases" not in counts
        assert client.get("/api/documents?folder=../../invalid").status_code == 400
        base = f"/api/documents/{doc['id']}"
        response = client.post(base + "/organization-runs", json={"expected_hash": digest})
        assert response.status_code == 400
        assert "reasoning model" in response.json()["detail"]
        assert len(local_model["requests"]) == 1
        assert client.put(base + "/folder", json={"expected_hash": digest, "folder": "../invalid"}).status_code == 422
        assert client.put(base + "/folder", json={"expected_hash": digest, "folder": "Bills"}).status_code == 200
        assert client.get("/api/documents?folder=Bills").json()["total"] == 1
        assert client.post(base + "/trash", json={"expected_hash": digest}).status_code == 422
        assert client.post(base + "/trash", json={"expected_hash": digest, "confirmed": False}).status_code == 422
        assert client.post(base + "/trash", json={"expected_hash": "a"*64, "confirmed": True}).status_code == 409
        assert client.post(base + "/trash", json={"expected_hash": digest, "confirmed": True}).status_code == 200
        assert client.get("/api/documents").json()["total"] == 2
        assert client.get("/api/documents?folder=trash").json()["total"] == 1
        assert client.post(base + "/receipt-runs", json={}).status_code == 400
        assert client.put(base + "/folder", json={"expected_hash": digest, "folder": "Unfiled"}).status_code == 400
        manager.start_inbox(); manager.future.result(timeout=30)
        assert client.get("/api/documents?folder=trash").json()["total"] == 1
        assert not image.exists() and blob.read_bytes() == original_bytes  # Filing moved the Inbox file; evidence is untouched.
    # Trash survives restart and does not affect an identical active occurrence.
    app = create_app(control, "local-test", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers=auth) as client:
        manager = app.state.manager
        assert client.get("/api/documents?folder=trash").json()["total"] == 1
        batch = manager.start_receipt_batch(force=True)["batch_id"]
        manager.future.result(timeout=30)
        assert manager.batches.get(batch)["total"] == 1
        assert client.post(base + "/restore", json={"expected_hash": digest}).status_code == 200
        assert client.get("/api/documents?folder=Bills").json()["total"] == 1
        manager.start_receipt_batch(force=True); manager.future.result(timeout=30)
        assert client.get("/api/documents?folder=Bills").json()["total"] == 1  # Manual choice wins.
        image.write_bytes(original_bytes + b"new version")
        manager.start_inbox(); manager.future.result(timeout=30)
        assert client.get("/api/documents?folder=Bills").json()["total"] == 0
        assert client.get("/api/documents?folder=Inbox").json()["total"] == 3  # The new version waits in Inbox.
        assert client.post(base + "/trash", json={"expected_hash": digest, "confirmed": True}).status_code == 409


def test_bad_classification_keeps_capture_unfiled(tmp_path, local_model):
    from home_manager.manager import Manager
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "managed"))
        month = manager.store.library.inbox
        make_receipt(month / "receipt.png")
        local_model["output"]["folder"] = "../../escape"
        manager.configure_vision(local_model["config"])
        scan = manager.start_inbox()
        manager.future.result(timeout=30)
        assert manager.store.job(scan)["status"] == "completed"
        assert manager.store.job(scan)["organization_status"] == "partial"
        assert manager.store.documents(folder="Inbox")["total"] == 1  # Unclassified Inbox documents stay in Inbox.
        doc = manager.store.documents()["items"][0]
        assert doc["title"] is None and doc["parse_status"] == "failed"
    finally:
        manager.close()


def test_document_dates_sorting_single_lookup_and_selected_batches(tmp_path, local_model):
    app = create_app(tmp_path / "control", "local-test", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer local-test"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        month = app.state.manager.store.library.inbox
        make_receipt(month / "a-receipt.png")
        make_receipt(month / "b-receipt.png", ["OTHER SHOP", "Total 9.00"])
        (month / "c-export.csv").write_text("date,amount\n2026-09-22,25\n")
        manager = app.state.manager
        client.post("/api/inbox-scans", json={}); manager.future.result(timeout=30)
        docs = {doc["relative_path"].split("/")[-1]: doc for doc in client.get("/api/documents").json()["items"]}
        assert all(doc["document_date"] is None for doc in docs.values())
        dated = docs["b-receipt.png"]
        with manager.store.connection() as db:  # A published receipt gives its document a date.
            db.execute("INSERT INTO receipts(document_id,blob_hash,purchase_date,total_minor,currency,review_status,created_at,updated_at) "
                       "VALUES(?,?,'2026-09-15',900,'USD','proposed','t','t')", (dated["id"], dated["current_hash"]))
        by_date = client.get("/api/documents", params={"sort": "date"}).json()["items"]
        assert by_date[0]["id"] == dated["id"] and by_date[0]["document_date"] == "2026-09-15"
        assert by_date[0]["ledger_amount"] == "9.00 USD"
        ranged = client.get("/api/documents", params={"date_from": "2026-09-01", "date_to": "2026-09-30"}).json()
        assert [doc["id"] for doc in ranged["items"]] == [dated["id"]] and ranged["total"] == 1
        assert client.get("/api/documents", params={"date_from": "2026-10-01"}).json()["total"] == 0
        assert client.get("/api/documents", params={"sort": "; DROP"}).status_code == 400
        assert client.get("/api/documents", params={"date_from": "09/01/2026"}).status_code == 422
        single = client.get(f"/api/documents/{dated['id']}").json()
        assert single["id"] == dated["id"] and single["document_date"] == "2026-09-15" and single["folder"] == dated["folder"]
        assert client.get("/api/documents/99999").status_code == 400
        # Selected batches read only the chosen readable documents.
        client.put("/api/vision-settings", json=local_model["config"].model_dump())
        rejected = client.post("/api/receipt-batches", json={"document_ids": [docs["c-export.csv"]["id"]]})
        assert rejected.status_code == 400 and "Import transactions" in rejected.json()["detail"]
        assert client.post("/api/receipt-batches", json={"document_ids": []}).status_code == 422
        batch = client.post("/api/receipt-batches", json={"document_ids": [docs["a-receipt.png"]["id"], docs["c-export.csv"]["id"]]}).json()["batch_id"]
        manager.future.result(timeout=30)
        result = manager.batches.get(batch)
        assert result["total"] == 1 and result["skipped"] == 1
        assert len(local_model["requests"]) == 1
        states = {doc["relative_path"].split("/")[-1]: doc["parse_status"] for doc in client.get("/api/documents").json()["items"]}
        assert states == {"a-receipt.png": "succeeded", "b-receipt.png": None, "c-export.csv": None}
