import base64
from pathlib import Path
import sqlite3

import pytest
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import zxingcpp

from home_manager.receipt_fields import financial_fields, reading_lines
from home_manager.receipt_schema import TextBlock, TextLine
from home_manager.receipt_service import ReceiptService
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store


def make_receipt(path):
    image = Image.new("RGB", (900, 1100), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default(size=34)
    texts = ["LOCAL TEST CAFE", "2026-09-22", "Currency USD", "Coffee 8.00", "Cake 12.00",
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


def lines(*texts):
    return [TextLine(id=f"line-{i}", text=text, block_ids=[]) for i, text in enumerate(texts)]


def test_financial_suggestions_and_exact_breakdown():
    fields = financial_fields(lines("2026-09-22", "USD", "Subtotal 20.00", "Tax 2.00", "Tip 3.00", "Total 25.00"))
    assert fields.date.value == "2026-09-22"
    assert fields.currency.value == "USD"
    assert fields.total.value == "25.00"
    assert fields.calculated_total == "25.00"
    assert fields.calculation_status == "matches"
    assert fields.difference == "0.00"


def test_ambiguous_fields_are_not_guessed():
    fields = financial_fields(lines("03/04/2026", "$", "Total 25.00", "Total 27.00", "Suggested tip 20% 5.00"))
    assert fields.date.value is None
    assert fields.date.status == "ambiguous"
    assert fields.currency.value is None
    assert fields.total.value is None
    assert fields.components == []
    assert fields.calculation_status == "incomplete"


def test_currency_decimal_formats_and_incomplete_total():
    fields = financial_fields(lines("EUR", "Subtotal 1.000,00", "Tax 200,00", "Total 1.250,00"))
    assert fields.total.value == "1250.00"
    assert fields.calculated_total == "1200.00"
    assert fields.difference == "50.00"
    assert fields.calculation_status == "mismatch"
    missing = financial_fields(lines("Total 25.00"))
    assert missing.calculation_status == "incomplete"
    assert missing.calculated_total is None


def test_multiple_tax_components_not_blindly_added():
    fields = financial_fields(lines("Subtotal 20.00", "Tax 1.00", "Tax 2.00", "Total 23.00"))
    assert len(fields.components) == 3
    assert fields.calculation_status == "incomplete"


def test_included_tax_is_preserved_but_not_added_again():
    fields = financial_fields(lines("Subtotal 22.00", "Tax included 2.00", "Total 22.00"))
    assert fields.components[1].value == "2.00"
    assert fields.components[1].status == "ambiguous"
    assert fields.calculation_status == "incomplete"


def test_reading_order_retains_low_confidence_nonfinancial_text():
    blocks = [TextBlock(id="b", text="Footer text", confidence=.1, polygon=[(0,50),(90,50),(90,70),(0,70)]),
              TextBlock(id="c", text="25.00", confidence=.9, polygon=[(150,0),(200,0),(200,20),(150,20)]),
              TextBlock(id="a", text="Total", confidence=.9, polygon=[(0,0),(100,0),(100,20),(0,20)])]
    result = reading_lines(blocks)
    assert [line.text for line in result] == ["Total 25.00", "Footer text"]
    assert sorted(key for line in result for key in line.block_ids) == ["a", "b", "c"]


def test_real_local_ocr_and_qr_persist_exact_evidence(receipt_store):
    source, store, doc, payload = receipt_store
    before = store.blob_path(doc["current_hash"]).read_bytes()
    service = ReceiptService(store)
    run_id, created = service.enqueue(doc["id"])
    assert created
    service.run(run_id)
    run = service.get(run_id)
    assert run["status"] in ("succeeded", "partial"), run["error"]
    result = run["result"]
    assert "LOCAL TEST CAFE" in result["ocr_text"].upper()
    assert "RETURNS" in result["ocr_text"].upper()
    assert "THANK YOU" in result["ocr_text"].upper()
    assert payload in result["extracted_text"]
    code = next(code for code in result["codes"] if code["text"] == payload)
    assert base64.b64decode(code["bytes_base64"]) == payload.encode()
    assert result["fields"]["total"]["value"] == "25.00", result["ocr_text"]
    assert result["fields"]["currency"]["value"] == "USD"
    assert result["fields"]["calculation_status"] == "matches", result["ocr_text"]
    assert len(result["model_hashes"]) == 3
    from home_manager.receipt_schema import ReceiptResult
    from pydantic import ValidationError
    omitted = dict(result, extracted_text=result["ocr_text"])
    with pytest.raises(ValidationError, match="retain every"):
        ReceiptResult.model_validate(omitted)
    assert service.preview(run_id).exists()
    assert store.blob_path(doc["current_hash"]).read_bytes() == before
    reused, created = service.enqueue(doc["id"])
    assert reused == run_id and not created
    new_id, created = service.enqueue(doc["id"], force=True)
    assert created and new_id != run_id
    service.recover()
    assert service.get(new_id)["status"] == "interrupted"
    assert service.get(run_id)["result"] == result


def test_invalid_image_failure_is_not_empty_success(tmp_path):
    source = tmp_path / "source"
    month = source / "2026" / "09"
    month.mkdir(parents=True)
    (month / "bad.jpg").write_bytes(b"not an image")
    store = Store(tmp_path / "managed")
    try:
        Scanner(store, ScanLimits(stability_seconds=0)).run(store.create_job(source), source)
        doc = store.documents(source)["items"][0]
        service = ReceiptService(store)
        run_id, _ = service.enqueue(doc["id"])
        service.run(run_id)
        assert service.get(run_id)["status"] == "failed"
        assert service.get(run_id)["result"] is None
    finally:
        store.close()


def test_version_checks_and_rotation_are_explicit(receipt_store):
    source, store, doc, payload = receipt_store
    service = ReceiptService(store)
    with pytest.raises(ValueError):
        service.enqueue(doc["id"], digest="a"*64)
    with pytest.raises(ValueError):
        service.enqueue(doc["id"], rotation=45)
    run_id, _ = service.enqueue(doc["id"], rotation=90)
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
            assert db.execute("PRAGMA user_version").fetchone()[0] == 4
            assert db.execute("SELECT size FROM blobs").fetchone()[0] == 123
        assert (managed / "inventory.before-v2.sqlite3").exists()
        with sqlite3.connect(managed / "inventory.before-v2.sqlite3") as backup:
            assert backup.execute("PRAGMA user_version").fetchone()[0] == 1
    finally:
        store.close()
