import base64
from pathlib import Path
import sqlite3

import pytest
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import zxingcpp

from home_manager.receipt_service import ReceiptService
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import MIGRATIONS, Store


def make_receipt(path, texts=None):
    image = Image.new("RGB", (900, 1100), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default(size=34)
    texts = texts or ["LOCAL TEST CAFE", "2026-09-22", "Currency USD", "Coffee 8.00", "Cake 12.00",
             "Subtotal 20.00", "Tax 2.00", "Tip 3.00", "Total USD 25.00",
             "Thank you - keep this receipt", "Returns within 14 days"]
    for index, text in enumerate(texts):
        draw.text((40, 30 + index * 48), text, fill="black", font=font)
    payload = "https://example.invalid/receipt?id=42&total=25.00"
    barcode = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode)
    qr = Image.fromarray(np.asarray(zxingcpp.write_barcode_to_image(barcode, scale=7)))
    image.paste(qr, (40, 630))
    image.save(path)
    return payload


@pytest.fixture
def receipt_store(tmp_path):
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    image = month / "receipt.png"
    payload = make_receipt(image)
    with_store = Store(tmp_path / "managed")
    job = with_store.create_job(source)
    Scanner(with_store, ScanLimits(stability_seconds=0)).run(job, source)
    document = with_store.documents(source)["items"][0]
    yield source, with_store, document, payload
    with_store.close()


def test_vision_and_real_qr_persist_exact_evidence(receipt_store, local_model):
    source, store, doc, payload = receipt_store
    before = store.blob_path(doc["current_hash"]).read_bytes()
    service = ReceiptService(store)
    run_id, created = service.enqueue(doc["id"], vision=local_model["config"])
    assert created
    service.run(run_id)
    run = service.get(run_id)
    assert run["status"] in ("succeeded", "partial"), run["error"]
    result = run["result"]
    assert "LOCAL TEST CAFE" in result["model_text"].upper()
    assert "RETURNS" in result["model_text"].upper()
    assert payload in result["extracted_text"]
    code = next(code for code in result["codes"] if code["text"] == payload)
    assert base64.b64decode(code["bytes_base64"]) == payload.encode()
    assert result["fields"] is None
    assert result["title"] is None and result["folder"] is None
    assert result["model_hashes"] == {}
    from home_manager.receipt_schema import ReceiptResult
    from pydantic import ValidationError
    omitted = dict(result, extracted_text=result["model_text"])
    with pytest.raises(ValidationError, match="retain every"):
        ReceiptResult.model_validate(omitted)
    assert service.preview(run_id).exists()
    assert store.blob_path(doc["current_hash"]).read_bytes() == before
    reused, created = service.enqueue(doc["id"], vision=local_model["config"])
    assert reused == run_id and not created
    new_id, created = service.enqueue(doc["id"], force=True, vision=local_model["config"])
    assert created and new_id != run_id
    service.recover()
    assert service.get(new_id)["status"] == "interrupted"
    assert service.get(run_id)["result"] == result


def test_invalid_image_failure_is_not_empty_success(tmp_path, local_model):
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    (month / "bad.jpg").write_bytes(b"not an image")
    store = Store(tmp_path / "managed")
    try:
        Scanner(store, ScanLimits(stability_seconds=0)).run(store.create_job(source), source)
        doc = store.documents(source)["items"][0]
        service = ReceiptService(store)
        run_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
        service.run(run_id)
        assert service.get(run_id)["status"] == "failed"
        assert service.get(run_id)["result"] is None
    finally:
        store.close()


def test_version_checks_and_rotation_are_explicit(receipt_store, local_model):
    source, store, doc, payload = receipt_store
    service = ReceiptService(store)
    with pytest.raises(ValueError):
        service.enqueue(doc["id"], digest="a"*64)
    with pytest.raises(ValueError):
        service.enqueue(doc["id"], rotation=45)
    run_id, _ = service.enqueue(doc["id"], rotation=90, vision=local_model["config"])
    assert service.get(run_id)["options"]["clockwise_rotation"] == 90


def test_existing_v1_database_migrates_with_backup(tmp_path):
    managed = tmp_path / "managed"
    managed.mkdir()
    (managed / ".home-manager-store").write_text("home-manager-store-v1\n")
    migration = Path(__file__).parents[1] / "src" / "home_manager" / "migrations" / "001_inventory.sql"
    with sqlite3.connect(managed / "inventory.sqlite3") as db:
        db.executescript(migration.read_text())
        db.execute("INSERT INTO blobs VALUES (?,123,'original timestamp')", ("a"*64,))
    store = Store(managed)
    try:
        with store.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == MIGRATIONS[-1][0]
            assert db.execute("SELECT size FROM blobs").fetchone()[0] == 123
        # One consistent pre-migration snapshot, not one copy per intermediate version.
        assert [path.name for path in managed.glob("inventory.before-*")] == [f"inventory.before-v{MIGRATIONS[-1][0]}.sqlite3"]
        with sqlite3.connect(managed / f"inventory.before-v{MIGRATIONS[-1][0]}.sqlite3") as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        store.close()


def test_missing_model_does_not_queue_ocr(receipt_store):
    _, store, doc, _ = receipt_store
    service = ReceiptService(store)
    with pytest.raises(ValueError, match="Configure a local vision model"):
        service.enqueue(doc["id"])
    assert service.history(doc["id"]) == []


@pytest.mark.parametrize("text", ["Total [unreadable]", "[no visible text]"])
def test_unreadable_transcription_is_partial(receipt_store, local_model, text):
    _, store, doc, _ = receipt_store
    local_model["output"] = {"full_text": text}
    service = ReceiptService(store)
    run_id, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(run_id)
    run = service.get(run_id)
    assert run["status"] == "partial"
    assert run["result"]["model_text"] == text
    assert run["result"]["fields"] is None


def test_failed_reprocessing_preserves_completed_evidence(receipt_store, local_model):
    _, store, doc, _ = receipt_store
    service = ReceiptService(store)
    first, _ = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(first)
    saved = service.get(first)["result"]
    assert saved is not None
    local_model["finish_reason"] = "length"
    second, _ = service.enqueue(doc["id"], vision=local_model["config"], force=True)
    service.run(second)
    assert service.get(second)["status"] == "failed"
    assert service.get(second)["result"] is None
    assert service.get(first)["result"] == saved
    assert len(local_model["requests"]) == 2


def test_historical_ocr_fields_remain_readable():
    from home_manager.receipt_schema import ReceiptResult
    candidate = lambda name: {"name": name, "status": "missing"}
    historical = {
        "input_hash": "a" * 64, "image_format": "PNG",
        "original_width": 100, "original_height": 100, "width": 100, "height": 100,
        "engine": {}, "model_hashes": {},
        "blocks": [{"id": "text-1", "text": "Total 25.00", "confidence": .9,
                    "polygon": [(0, 0), (100, 0), (100, 20), (0, 20)]}],
        "lines": [{"id": "line-1", "text": "Total 25.00", "block_ids": ["text-1"]}],
        "ocr_text": "Total 25.00", "extracted_text": "Total 25.00", "codes": [], "issues": [],
        "fields": {"date": candidate("date"), "currency": candidate("currency"),
                   "total": {"name": "total", "value": "25.00", "status": "proposed", "evidence_ids": ["line-1"]},
                   "calculation_note": "Historical unreviewed suggestion."},
    }
    result = ReceiptResult.model_validate(historical)
    assert result.transcription_method == "ocr"
    assert result.fields.total.value == "25.00"
    assert ReceiptResult.model_validate_json(result.model_dump_json()) == result
