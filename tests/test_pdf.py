"""Phase 3: page-aware PDF ingestion with embedded text and per-page vision fallback."""

from conftest import inbox_scan
import json

import pytest

from home_manager.jobs import Work
from home_manager.manager import Manager
from home_manager.reasoning import ReasoningConfig
from home_manager.receipt_service import ReceiptService
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store
from home_manager.vision import VisionConfig


def make_pdf(path, pages):
    """Minimal valid PDF. A string page has an embedded text layer; None is an image-only (scanned) page."""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", None, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    kids = []
    for text in pages:
        if text is None:
            stream = b"0.2 g 72 600 300 80 re f"  # Pixels only: nothing extractable.
        else:
            escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in text.split("\n")]
            stream = b"BT /F1 10 Tf 12 TL 40 760 Td " + b" ".join(f"({line}) Tj T*".encode("latin-1") for line in escaped) + b" ET"
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        objects.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (len(objects)))
        kids.append(len(objects))
    objects[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % kid for kid in kids) + b"] /Count %d >>" % len(kids)
    data, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    data += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    path.write_bytes(bytes(data))


STATEMENT = "FIRST LOCAL BANK\nStatement period 2026-08-01 to 2026-08-31\nAccount ending 4821\nOpening balance 1,000.00\nClosing balance 1,250.00"


@pytest.fixture
def pdf_store(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        yield store.library.inbox, store
    finally:
        store.close()


def capture(source, store):
    inbox_scan(store)
    return store.documents()["items"][0]


def test_mixed_pdf_uses_embedded_text_and_vision_only_for_scanned_pages(pdf_store, local_model):
    source, store = pdf_store
    make_pdf(source / "statement.pdf", [STATEMENT, None, "Transactions continued\n2026-08-03 GROCERY MART -45.10\n2026-08-09 PAYROLL DEPOSIT +2,000.00"])
    doc = capture(source, store)
    local_model["output"] = {"full_text": "SCANNED PAGE TWO\nHandwritten note 12.00"}
    service = ReceiptService(store)
    run_id, created = service.enqueue(doc["id"], vision=local_model["config"])
    service.run(run_id, Work("inference", "transcription", "PDF", sink=store.record_model_run))
    run = service.get(run_id)
    assert run["status"] == "succeeded", run["error"]
    result = run["result"]
    assert [page["method"] for page in result["pages"]] == ["embedded_text", "vision_model", "embedded_text"]
    assert len(local_model["requests"]) == 1  # Only the scanned page reached the vision model.
    assert local_model["requests"][0]["messages"][1]["content"][1]["type"] == "image_url"
    assert [line["text"] for line in result["pages"][1]["lines"]] == ["SCANNED PAGE TWO", "Handwritten note 12.00"]
    assert "FIRST LOCAL BANK" in result["pages"][0]["lines"][0]["text"]
    assert "PAYROLL DEPOSIT" in " ".join(line["text"] for line in result["pages"][2]["lines"])
    # Every line carries a page-scoped evidence ID; no page is silently omitted.
    assert all(line["id"].startswith(f"page-{page['number']}-line-") for page in result["pages"] for line in page["lines"])
    assert [line["id"] for line in result["lines"]] == [line["id"] for page in result["pages"] for line in page["lines"]]
    assert store.blob_path(doc["current_hash"]).read_bytes() == (source / "statement.pdf").read_bytes()
    [telemetry] = store.model_runs(run_id)
    assert telemetry["task"] == "transcription" and telemetry["prompt_version"] == "pdf-pages-v1"


def test_digital_pdf_needs_no_vision_model_and_scanned_pages_never_vanish(pdf_store):
    source, store = pdf_store
    make_pdf(source / "digital.pdf", [STATEMENT])
    make_pdf(source / "scan.pdf", [None])
    inbox_scan(store)
    docs = {doc["relative_path"].split("/")[-1]: doc for doc in store.documents()["items"]}
    service = ReceiptService(store)
    digital, _ = service.enqueue(docs["digital.pdf"]["id"], vision=VisionConfig())
    service.run(digital)
    assert service.get(digital)["status"] == "succeeded"
    assert service.get(digital)["result"]["pages"][0]["method"] == "embedded_text"
    # Without a model there is nothing whose identity could change: the result is reusable.
    assert service.enqueue(docs["digital.pdf"]["id"], vision=VisionConfig()) == (digital, False)
    scanned, _ = service.enqueue(docs["scan.pdf"]["id"], vision=VisionConfig())
    service.run(scanned)
    failed = service.get(scanned)
    assert failed["status"] == "failed" and failed["result"] is None
    assert "vision model" in failed["error"]


def test_pdf_limits_and_damaged_files_fail_explicitly(pdf_store):
    source, store = pdf_store
    (source / "damaged.pdf").write_bytes(b"%PDF-1.4\nnot really a pdf")
    doc = capture(source, store)
    service = ReceiptService(store)
    run_id, _ = service.enqueue(doc["id"], vision=VisionConfig())
    service.run(run_id)
    run = service.get(run_id)
    assert run["status"] == "failed" and "PDF could not be read" in run["error"]


def test_long_statement_analysis_is_chunked_not_one_monolithic_prompt(tmp_path, local_model):
    rows = [f"2026-08-{day % 28 + 1:02d} MERCHANT {day:03d} -{day}.00" for day in range(1, 181)]
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "managed"))
        make_pdf(manager.store.library.inbox / "long.pdf", ["\n".join(rows[:60]), "\n".join(rows[60:120]), "\n".join(rows[120:])])
        manager.configure_vision(local_model["config"].model_copy(update={"organize_after_scan": False}))
        manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
        manager.start_inbox()
        manager.future.result(timeout=30)
        doc = manager.store.documents()["items"][0]
        parse = manager.start_receipt(doc["id"])
        manager.future.result(timeout=30)
        lines = [line["id"] for line in manager.receipts.get(parse["run_id"])["result"]["lines"]]
        assert len(lines) == 180 and not local_model["requests"]
        chunks = [lines[:150], lines[150:]]
        local_model["outputs"] = [{
            "title": "Bank statement", "document_type": "bank_statement",
            "classification_evidence": [{"line_id": chunk[0], "quote": "MERCHANT"}], "facts": [], "receipt_items": [],
            "itemization_status": "not_present", "itemization_note": "Statement rows, not receipt items.",
            "other_lines": [{"line_ids": chunk[1:], "kind": "non_receipt"}], "insights": [],
            "limitations": ["Synthetic statement."]} for chunk in chunks]
        analysis = manager.start_reasoning(doc["id"], parse["run_id"])["run_id"]
        manager.future.result(timeout=30)
        run = manager.reasoning.get(analysis)
        assert run["status"] == "succeeded", run["error"]
        assert len(local_model["requests"]) == 2  # Two bounded chunks, never one prompt with 180 rows.
        sent = [json.loads(request["messages"][1]["content"])["lines"] for request in local_model["requests"]]
        assert [len(chunk) for chunk in sent] == [150, 30]
        assert [row["line_id"] for chunk in sent for row in chunk] == lines
        assert [row["task"] for row in manager.store.model_runs(analysis)] == ["reasoning", "reasoning"]
    finally:
        manager.close()
