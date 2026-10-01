"""Several receipts in one file: split, read one receipt at a time, confirmed once (docs/document-parsing.md)."""

from types import SimpleNamespace

from home_manager.documents.extraction import SPLIT_NOTE, codes_within, looks_like_several, merge_parts, unit_breaks
from home_manager.documents.pdf_reader import PDFPage, PDFResult
from home_manager.documents.receipt_schema import CodeEvidence, Region, TextLine
from test_extraction import MISSING, extract, transcribe

SHOPS = [("CORNER COFFEE", "2026-09-20", "LATTE", "4.00", "0.40", "4.40"), ("TOWN BAKERY", "2026-09-21", "BREAD", "3.00", "0.30", "3.30")]


def receipt_lines(name, day, item, subtotal, tax, total):
    return [name, day, "USD", f"{item} 1 @ {subtotal} {subtotal}", f"Subtotal {subtotal}", f"Tax {tax}", f"Total {total}"]


LINES = [line for shop in SHOPS for line in receipt_lines(*shop)]


def cite(number, quote):
    return [{"line_id": f"line-{number}", "quote": quote}]


def value(text, number, quote=None):
    return {"value": text, "status": "proposed", "evidence": cite(number, quote or text)}


def classification(kind="receipt", start=1):
    return {"document_type": kind, "evidence": cite(start, LINES[start - 1]), "issuer": value(LINES[start - 1], start), "document_date": value(LINES[start], start + 1)}


def answers(start, name, day, item, subtotal, tax, total):
    """The model's answers for one receipt whose first line is line-{start}."""
    return [classification(start=start),
            {"merchant": value(name, start), "purchase_date": value(day, start + 1), "currency": value("USD", start + 2),
             "subtotal": value(subtotal, start + 4, f"Subtotal {subtotal}"), "tax": value(tax, start + 5, f"Tax {tax}"), "tip": MISSING,
             "total": value(total, start + 6, f"Total {total}"), "card_last_four": MISSING},
            {"seller": value(name, start), "seller_basis": "printed", "location": MISSING},
            {"items": [{"description": item, "product_code": None, "quantity": "1", "unit_price": subtotal, "line_total": subtotal, "discount": None,
                        "taxed": None, "evidence": cite(start + 3, LINES[start + 2])}]},
            {"description": "Snacks", "category": "groceries", "recurrence": None, "item_categories": ["groceries"]},
            {"rewards": []}]


def split_answers(starts=(1, 8)):
    return [classification(), {"starts": [{"line_id": f"line-{start}", "quote": LINES[start - 1]} for start in starts]},
            # Each part is classified first, then each is read.
            answers(1, *SHOPS[0])[0], answers(8, *SHOPS[1])[0], *answers(1, *SHOPS[0])[1:], *answers(8, *SHOPS[1])[1:]]


def receipts(manager):
    with manager.store.connection() as db:
        return [dict(row) for row in db.execute("SELECT r.segment,r.review_status,r.total_minor,r.validation_json,m.canonical_name AS merchant "
                                                "FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id ORDER BY r.segment")]


def test_two_receipts_in_one_file_are_recorded_and_confirmed_once(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, LINES)
    try:
        local_model["outputs"] = split_answers()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        names = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"][1:]]
        assert names[:2] == ["Classification", "ReceiptStarts"] and names.count("ReceiptSummary") == 2
        found = receipts(manager)
        assert [(row["segment"], row["merchant"], row["total_minor"]) for row in found] == [(0, "CORNER COFFEE", 440), (1, "TOWN BAKERY", 330)]
        # Each receipt passed its checks, but waits until the user confirms the split.
        assert all(row["review_status"] == "needs_review" and SPLIT_NOTE in row["validation_json"] for row in found)
        assert [part["first_line"] for part in run["publication"]["segments"]] == ["line-1", "line-8"]
        assert run["publication"]["split_confirmed"] is False
        split = manager.split(doc["id"])
        assert [(row["first_line_id"], row["last_line_id"], row["status"]) for row in split["segments"]] == [
            ("line-1", "line-7", "proposed"), ("line-8", "line-14", "proposed")]
        listed = manager.store.document(doc["id"])
        assert listed["title"].startswith("CORNER COFFEE + 1 more") and listed["ledger_amount"] is None and listed["receipt_count"] == 2
        assert manager.confirm_split(doc["id"])["confirmed"]
        assert [row["review_status"] for row in receipts(manager)] == ["verified", "verified"]
        # Reading again finds the same split: still confirmed, no new note.
        local_model["outputs"] = split_answers()
        again = extract(manager, doc, parse_id, force=True)
        assert again["publication"]["split_confirmed"] is True
        assert [row["review_status"] for row in receipts(manager)] == ["verified", "verified"]
    finally:
        manager.close()


def test_the_user_can_make_it_one_receipt(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, LINES)
    try:
        local_model["outputs"] = split_answers()
        extract(manager, doc, parse_id)
        local_model["outputs"] = [classification(), *answers(1, *SHOPS[0])[1:]]
        manager.set_split(doc["id"], ["line-1"])
        manager.future.result(timeout=30)
        names = [request["response_format"]["json_schema"]["name"] for request in local_model["requests"]]
        assert names[-6:] == ["Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription", "Rewards"]  # No segmentation asked.
        found = receipts(manager)
        assert [(row["segment"], row["review_status"]) for row in found] == [(0, "verified"), (1, "rejected")]  # The second stops counting.
        assert manager.split(doc["id"])["segments"][0]["source"] == "user"
    finally:
        manager.close()


def test_unusable_answers_and_other_documents_are_not_split(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, LINES)
    try:
        # A start citing a line that does not exist: no page breaks to fall back on, so one document.
        local_model["outputs"] = [classification(), {"starts": [{"line_id": "line-99", "quote": "X"}]}, *answers(1, *SHOPS[0])[1:]]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert "segments" not in run["publication"] and any("could not be read" in note for note in run["result"]["split_notes"])
        # A part that is not a receipt: the file is read as one document.
        local_model["outputs"] = [classification(), {"starts": [{"line_id": "line-1", "quote": LINES[0]}, {"line_id": "line-8", "quote": LINES[7]}]},
                                  classification(start=1), classification("bank_statement", 8), *answers(1, *SHOPS[0])[1:]]
        run = extract(manager, doc, parse_id, force=True)
        assert run["status"] == "succeeded", run["error"]
        assert "segments" not in run["publication"] and any("not a receipt" in note for note in run["result"]["split_notes"])
        assert manager.split(doc["id"])["segments"] == []
    finally:
        manager.close()


def lines(prefix, texts):
    return [TextLine(id=f"{prefix}{number}", text=text, block_ids=[]) for number, text in enumerate(texts, 1)]


def test_page_and_paper_breaks_and_parts():
    pdf = PDFResult(input_hash="0" * 64, pages=[PDFPage(number=1, method="embedded_text", lines=lines("page-1-line-", ["A", "Total 1.00"])),
                                                PDFPage(number=2, method="vision_model", lines=lines("page-2-line-", ["B", "Total 2.00", "C", "Total 3.00"]),
                                                        regions=[Region(number=1, bbox=(0, 0, 10, 10), first_line="page-2-line-1", last_line="page-2-line-2"),
                                                                 Region(number=2, bbox=(10, 0, 20, 10), first_line="page-2-line-3", last_line="page-2-line-4")])])
    assert unit_breaks(pdf, pdf.lines) == [2, 4]
    assert looks_like_several(pdf.lines) and not looks_like_several(lines("line-", ["Subtotal 4.00", "Total 4.40", "Total tax 0.40"]))
    text = lines("line-", ["SHOP", "Total 1.00", "Thank you", "page 2 footer", "OTHER", "Visa 2.00"])
    # A heading-only part joins the receipt after it; a trailing part without money joins the one before.
    assert merge_parts([(0, 1), (1, 3), (3, 4), (4, 6)], text) == [(0, 4), (4, 6)]


def test_codes_follow_their_piece_of_paper():
    code = lambda key, x: CodeEvidence(id=key, format="QRCode", text=key, bytes_base64="", valid=True, polygon=[(x, 1), (x + 2, 1), (x + 2, 3), (x, 3)])  # noqa: E731
    evidence = SimpleNamespace(lines=lines("line-", ["A", "B", "C"]), codes=[code("left", 2), code("right", 12)],
                               regions=[Region(number=1, bbox=(0, 0, 10, 10), first_line="line-1", last_line="line-2"),
                                        Region(number=2, bbox=(10, 0, 20, 10), first_line="line-3", last_line="line-3")])
    assert [item.id for item in codes_within(evidence, evidence.lines[2:])] == ["right"]
    assert [item.id for item in codes_within(evidence, evidence.lines)] == ["left", "right"]
