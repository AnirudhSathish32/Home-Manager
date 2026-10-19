"""Receipt kinds (specs/document-forms FR-01 – FR-19): each kind read with its own form, its printed details kept and
checked, and what counts unchanged except where the spec says."""

from contextlib import contextmanager
import json

from document_forms_fixtures import (
    AMBIGUOUS,
    DINING,
    FUEL,
    GROCERY,
    MISSING,
    amount_on,
    cite,
    dining_replies,
    fuel,
    fuel_replies,
    grocery_items,
    grocery_replies,
    item,
    stored_identifiers,
    uncited,
    value,
)
from home_manager.documents.extraction import DETAILS_FAILED, EXTRACTION_VERSION, HEADERS
from test_extraction import RECEIPT, classification, extract, identity, receipt_items, receipt_summary, transcribe

KIND_FORMS = ("ReceiptFuelSummary", "ReceiptDiningSummary", "ReceiptGrocerySummary")


@contextmanager
def read_receipt(tmp_path, local_model, lines, replies):
    """Transcribe lines and record them with replies keyed by schema name; yields (manager, run, record, row) where row
    is the receipt's database row (raw columns, for the final-state checks)."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        with manager.store.connection() as db:
            parses = db.execute("SELECT count(*) FROM parse_runs").fetchone()[0]
        local_model["requests"].clear()
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM parse_runs").fetchone()[0] == parses  # C-noimg: no new reading of the image.
            row = dict(db.execute("SELECT * FROM receipts WHERE id=?", (run["publication"]["id"],)).fetchone())
        assert "image_url" not in json.dumps(local_model["requests"])  # C-noimg
        yield manager, run, manager.ledger.record("receipt", row["id"]), row
    finally:
        manager.close()


def asked(local_model):
    return [request["response_format"]["json_schema"]["name"] for request in local_model["requests"]]


def details_of(row):
    return json.loads(row["details_json"])[row["receipt_kind"]]


def item_details(manager, receipt_id):
    with manager.store.connection() as db:
        return {row[0]: json.loads(row[1]) if row[1] else None for row in db.execute(
            "SELECT description,details_json FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,))}


def test_sc01_a_fuel_receipt_is_read_with_the_fuel_form(tmp_path, local_model):
    lines = fuel()
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (manager, run, record, row):
        names = asked(local_model)
        assert names.count("ReceiptFuelSummary") == 1 and not {"ReceiptDiningSummary", "ReceiptGrocerySummary", "ReceiptSummary"} & set(names)
        schema = next(request for request in local_model["requests"] if request["response_format"]["json_schema"]["name"] == "ReceiptFuelSummary")
        properties = schema["response_format"]["json_schema"]["schema"]["properties"]
        assert {"volume", "volume_unit", "price_per_unit", "fuel_grade", "pump_number", "fuel_amount"} <= set(properties)
        assert not {"gratuity", "tenders", "savings_total", "party_size"} & set(properties)  # FR-03: no other kind's fields.
        assert row["receipt_kind"] == "fuel" and record["review_status"] == "verified" and record["review_source"] == "automatic", record["issues"]
        details = details_of(row)
        assert (details["volume"]["text"], details["volume"]["unit"], details["price_per_unit"]["text"]) == ("10.312", "gallon", "3.459")
        assert (details["fuel_grade"]["text"], details["pump_number"]["text"], details["fuel_amount"]["minor"]) == ("REG UNL", "17", 3567)
        assert (record["total_minor"], record["currency"]) == (3786, "USD")
        assert [(entry["description"], entry["line_total_minor"], entry["category"]) for entry in record["items"]] == [
            ("REG UNL", 3567, "transportation"), ("COFFEE", 219, None)]
        assert run["result"]["normalized"]["cross_checks"] >= 1
        assert all(uncited(detail, lines) == [] for detail in details.values())  # C-cite
        with manager.store.connection() as db:
            assert tuple(db.execute("SELECT json_type(details_json,'$.fuel.fuel_amount.minor'),json_type(details_json,'$.fuel.volume.text') "
                                    "FROM receipts").fetchone()) == ("integer", "text")  # C-money: no floats.


def test_sc01_a_grade_that_is_not_printed_stays_null(tmp_path, local_model):
    lines = fuel(grade="")
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (_, _run, record, row):
        assert "fuel_grade" not in details_of(row) and record["review_status"] == "verified", record["issues"]


def test_sc01_b_litres_are_read_as_printed(tmp_path, local_model):
    lines = fuel(volume="10.312 L")
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (_, run, record, row):
        assert details_of(row)["volume"]["unit"] == "litre" and record["review_status"] == "verified", record["issues"]
        assert run["result"]["normalized"]["cross_checks"] == 1


def test_sc01_a_pump_number_is_never_an_item(tmp_path, local_model):
    """FR-06: a row the model lists for the pump line alone is left out, with a note."""
    lines = fuel()
    replies = fuel_replies(lines)
    replies["Items"][0]["items"].insert(0, item(lines, "PUMP 17", "PUMP 17", "17"))
    with read_receipt(tmp_path, local_model, lines, replies) as (_, _run, record, _row):
        assert [entry["description"] for entry in record["items"]] == ["REG UNL", "COFFEE"]
        assert "Item 1 is the pump number, not an item; it was left out." in record["issues"]


def test_sc02_a_fuel_arithmetic_mismatch_goes_to_review(tmp_path, local_model):
    lines = fuel(sale="36.67", total="38.86")
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (_, _run, record, row):
        assert record["review_status"] == "needs_review"
        [issue] = [issue for issue in record["issues"] if issue.startswith("Fuel:")]
        assert all(printed in issue for printed in ("10.312", "3.459", "36.67"))
        assert details_of(row)["fuel_amount"]["minor"] == 3667 and details_of(row)["volume"]["text"] == "10.312"  # Stored as printed.


def test_sc02_a_an_ambiguous_price_skips_the_fuel_check(tmp_path, local_model):
    lines = fuel(sale="36.67", total="38.86")
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines, price_per_unit=AMBIGUOUS)) as (_, _run, record, _row):
        assert not any(issue.startswith("Fuel:") for issue in record["issues"])


def test_sc03_dining_with_an_included_gratuity_and_a_blank_tip(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, DINING, dining_replies()) as (_, run, record, row):
        assert row["receipt_kind"] == "dining" and record["review_status"] == "verified", record["issues"]
        details = details_of(row)
        assert details["gratuity"]["minor"] == 900 and details["gratuity_included"]["text"] == "GRATUITY 18% INCLUDED"
        assert record["tip_minor"] is None  # Missing, not 0.
        assert (details["party_size"]["text"], details["server"]["text"], details["table"]["text"]) == ("4", "SAM", "9")
        assert all(uncited(detail, DINING) == [] for detail in details.values())
        assert run["result"]["normalized"]["cross_checks"] == 2  # 50.00 + 4.00 + 9.00 = 63.00, and the items make the subtotal.
        assert sum(split["amount_minor"] for split in record["splits"]) == 6300  # Counted once.


def test_sc03_a_a_printed_tip_with_no_gratuity(tmp_path, local_model):
    lines = [*DINING[:7], "TIP 10.00", "TOTAL 64.00"]
    replies = dining_replies(lines, gratuity_included=MISSING, gratuity=MISSING)
    with read_receipt(tmp_path, local_model, lines, replies) as (_, _run, record, _row):
        assert record["tip_minor"] == 1000 and record["review_status"] == "verified", record["issues"]


def test_sc03_b_a_zero_tip_on_a_blank_line_is_rejected(tmp_path, local_model):
    """The stub fills the blank tip line with 0.00: the amount-printed check rejects it, and the correction leaves it missing."""
    replies = dining_replies()
    invented = {**replies["ReceiptDiningSummary"][0], "tip": value(DINING, "0.00", "TIP ______")}
    replies["ReceiptDiningSummary"] = [invented, replies["ReceiptDiningSummary"][0]]
    with read_receipt(tmp_path, local_model, DINING, replies) as (_, _run, record, _row):
        assert record["tip_minor"] is None and asked(local_model).count("ReceiptDiningSummary") == 2


def test_sc04_a_grocery_receipt_keeps_weights_units_and_tenders(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, GROCERY, grocery_replies()) as (manager, run, record, row):
        assert row["receipt_kind"] == "grocery" and asked(local_model).count("GroceryItems") == 1
        items = {entry["description"]: entry for entry in record["items"]}
        weighed = item_details(manager, row["id"])["BANANAS"]
        assert (weighed["weight"]["text"], weighed["weight"]["unit"], weighed["price_per_weight"]["text"], items["BANANAS"]["line_total_minor"]) == (
            "2.31", "lb", "0.59", 136)
        assert (items["CHIPS"]["quantity"], items["CHIPS"]["unit_price_minor"], items["CHIPS"]["line_total_minor"]) == ("2", 200, 400)
        assert (items["BOTTLE DEPOSIT"]["line_total_minor"], items["BAG FEE"]["line_total_minor"], items["MEMBER SAVINGS"]["line_total_minor"]) == (10, 10, -50)
        details = details_of(row)
        assert details["savings_total"]["minor"] == -50
        assert [(tender["tender_type"], tender["minor"], tender["last_four"]) for tender in details["tenders"]] == [("gift_card", 500, "5555"), ("ebt", 355, None)]
        assert "GIFT CARD" not in items and not any(entry["discount_minor"] for entry in record["items"])  # A tender, never an item or discount.
        # Subtotal, tax and total; items make the subtotal; 2 × 2.00 = 4.00.
        assert run["result"]["normalized"]["cross_checks"] == 3 and record["review_status"] == "verified", record["issues"]
        assert record["total_minor"] == 855
        with manager.store.connection() as db:
            assert stored_identifiers(db, ("6006491234565555",)) == []  # C-ids


def test_sc04_a_no_printed_price_per_weight(tmp_path, local_model):
    lines = [line.replace(" @ 0.59/lb", "") for line in GROCERY]
    with read_receipt(tmp_path, local_model, lines, grocery_replies(lines)) as (manager, _run, record, row):
        assert "price_per_weight" not in item_details(manager, row["id"])["BANANAS"]
        assert next(entry for entry in record["items"] if entry["description"] == "BANANAS")["line_total_minor"] == 136


def test_sc04_b_a_multi_unit_mismatch_goes_to_review(tmp_path, local_model):
    lines = [{"2x CHIPS @ 2.00 4.00": "2x CHIPS @ 2.00 4.50", "SUBTOTAL 8.55": "SUBTOTAL 9.05", "TOTAL 8.55": "TOTAL 9.05"}.get(line, line) for line in GROCERY]
    with read_receipt(tmp_path, local_model, lines, grocery_replies(lines)) as (_, _run, record, _row):
        assert record["review_status"] == "needs_review"
        [issue] = [issue for issue in record["issues"] if "CHIPS" in issue]
        assert issue.startswith("Item 3 (CHIPS): 2 × 2.00 = 4.00 USD, not the printed line total 4.50 USD")
        assert not any(issue.startswith("Item line totals") for issue in record["issues"])  # The item sum still holds.
        assert next(entry for entry in record["items"] if entry["description"] == "CHIPS")["line_total_minor"] == 450


def test_sc04_c_no_printed_count_skips_the_multi_unit_check(tmp_path, local_model):
    lines = [{"2x CHIPS @ 2.00 4.00": "CHIPS 4.00"}.get(line, line) for line in GROCERY]
    with read_receipt(tmp_path, local_model, lines, grocery_replies(lines)) as (_, run, record, _row):
        assert next(entry for entry in record["items"] if entry["description"] == "CHIPS")["quantity"] is None
        assert run["result"]["normalized"]["cross_checks"] == 2 and record["review_status"] == "verified", record["issues"]


def test_sc05_a_general_receipt_is_read_as_today(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, RECEIPT)
    try:
        local_model["requests"].clear()
        local_model["outputs"] = [{**classification(), "receipt_kind": "general", "receipt_kind_evidence": []}, receipt_summary(), identity(),
                                  receipt_items(), {"description": "coffee & lunch", "category": "dining", "recurrence": None,
                                                    "item_categories": ["dining", "dining", None]}, {"rewards": []}]
        run = extract(manager, doc, parse_id)
        assert run["publication"]["review_status"] == "verified"
        record = manager.ledger.record("receipt", run["publication"]["id"])
        assert (record["subtotal_minor"], record["tax_minor"], record["tip_minor"], record["total_minor"]) == (2000, 200, 300, 2500)
        assert [(row["category"], row["amount_minor"]) for row in record["splits"]] == [("dining", 2500)]
        assert asked(local_model) == ["Classification", "ReceiptSummary", "ReceiptIdentity", "Items", "PurchaseDescription", "Rewards"]
        assert record["receipt_kind"] == "general" and json.loads(record["details_json"]) == {"general": {}}
    finally:
        manager.close()


def test_sc06_an_invoice_stays_a_bill_with_no_receipt_kind(tmp_path, local_model):
    text = ["EXAMPLE REPAIRS", "Invoice INV-104", "Bill to Alex Example", "Issued 2026-09-10", "Due 2026-09-28", "USD", "Parts 100.00",
            "Invoice total 100.00", "Balance due 100.00"]
    manager, doc, parse_id = transcribe(tmp_path, local_model, text)
    try:
        header = {name: MISSING for name in HEADERS["bill"]}
        header.update(provider=value(text, "EXAMPLE REPAIRS", "EXAMPLE REPAIRS"), invoice_marker=value(text, "Invoice", "Invoice INV-104", "Invoice"),
                      invoice_number=value(text, "INV-104", "Invoice INV-104", "INV-104"), issue_date=value(text, "2026-09-10", "Issued", "2026-09-10"),
                      due_date=value(text, "2026-09-28", "Due ", "2026-09-28"), currency=value(text, "USD", "USD"),
                      invoice_total=amount_on(text, "Invoice total"), balance_due=amount_on(text, "Balance due"), amount_due=amount_on(text, "Balance due"))
        local_model["by_schema"] = {
            "Classification": [{"document_type": "bill", "evidence": cite(text, "Invoice INV-104"), "issuer": value(text, "EXAMPLE REPAIRS", "EXAMPLE REPAIRS"),
                                "document_date": value(text, "2026-09-10", "Issued", "2026-09-10"), "receipt_kind": "fuel",
                                "receipt_kind_evidence": cite(text, "Parts 100.00")}],
            "BillSummary": [header],
            "BillLines": [{"line_items": [{"description": "Parts", "amount": "100.00", "category": None, "line_kind": "other", "line_holder": None,
                                           "evidence": cite(text, "Parts 100.00")}]}]}
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        with manager.store.connection() as db:
            row = db.execute("SELECT document_kind,invoice_json,receipt_kind,details_json FROM receipts").fetchone()
        assert row["document_kind"] == "bill" and json.loads(row["invoice_json"])["number"] == "INV-104"
        assert (row["receipt_kind"], row["details_json"]) == (None, None)
        assert not set(KIND_FORMS) & set(asked(local_model))
    finally:
        manager.close()


def general_fallback(tmp_path, local_model, classified):
    """An unusable kind proposal: the receipt is read with today's form, with a note, and waits in Review (FR-02)."""
    lines = fuel()
    replies = fuel_replies(lines, kind="general")
    replies["Classification"][0].update(classified)
    with read_receipt(tmp_path, local_model, lines, replies) as (_, _run, record, row):
        assert row["receipt_kind"] == "general" and record["review_status"] == "needs_review"
        assert not set(KIND_FORMS) & set(asked(local_model))
        return [issue for issue in record["issues"] if issue.startswith("Receipt kind:")]


def test_sc07_a_fuel_kind_with_a_bad_citation_is_read_as_general(tmp_path, local_model):
    issues = general_fallback(tmp_path, local_model, {"receipt_kind": "fuel", "receipt_kind_evidence": [{"line_id": "line-3", "quote": "PUMP 99"}]})
    assert issues == ["Receipt kind: fuel was not used: a citation is not an exact quote of an existing line. It was read as a general receipt."]


def test_sc07_a_an_unlisted_kind_is_read_as_general(tmp_path, local_model):
    issues = general_fallback(tmp_path, local_model, {"receipt_kind": "pharmacy", "receipt_kind_evidence": cite(FUEL, "PUMP 17")})
    assert issues == ["Receipt kind: pharmacy was not used: it is not one of fuel, dining, grocery or general. It was read as a general receipt."]


def test_sc07_b_an_uncited_kind_is_read_as_general(tmp_path, local_model):
    issues = general_fallback(tmp_path, local_model, {"receipt_kind": "fuel", "receipt_kind_evidence": []})
    assert issues == ["Receipt kind: fuel was not used: no line was cited for it. It was read as a general receipt."]


def test_sc08_fuel_details_that_fail_twice_are_left_out(tmp_path, local_model):
    """FR-14: the fuel form fails twice (its fuel amount isn't printed in its citation); today's receipt fields publish,
    with no fuel detail at all and the reason."""
    lines = fuel()
    replies = fuel_replies(lines, fuel_amount=value(lines, "36.67", "FUEL SALE 35.67"))
    replies["ReceiptFuelSummary"] *= 2
    with read_receipt(tmp_path, local_model, lines, replies) as (_, _run, record, row):
        assert asked(local_model).count("ReceiptFuelSummary") == 2
        second = next(request for request in reversed(local_model["requests"]) if request["response_format"]["json_schema"]["name"] == "ReceiptFuelSummary")
        assert "failed validation" in second["messages"][-1]["content"]  # The second request is the correction.
        assert (record["merchant"], record["purchase_date"], record["total_minor"], len(record["items"])) == ("Synth Fuel", "2026-10-01", 3786, 2)
        assert details_of(row) == {} and record["review_status"] == "needs_review" and DETAILS_FAILED in record["issues"]


def test_sc08_a_shared_fields_that_fail_twice_still_fail_the_receipt(tmp_path, local_model):
    lines = fuel()
    replies = fuel_replies(lines, total=value(lines, "38.00", "TOTAL 37.86"))
    replies["ReceiptFuelSummary"] *= 2
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "failed" and run["publication"] is None
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 0
    finally:
        manager.close()


def test_version_changed_and_a_receipt_read_before_is_read_again(tmp_path, local_model):
    """SC-15 for receipts (FR-16): a reading at the old version is never reused."""
    assert EXTRACTION_VERSION != "typed-extraction-v22-native-cells"
    lines = fuel()
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["by_schema"] = fuel_replies(lines)
        run = extract(manager, doc, parse_id)
        with manager.store.connection() as db:
            db.execute("UPDATE extraction_runs SET prompt_version='typed-extraction-v22-native-cells' WHERE id=?", (run["id"],))
        local_model["by_schema"] = fuel_replies(lines)
        started = manager.start_extraction(doc["id"], parse_id)
        manager.future.result(timeout=30)
        assert started["reused"] is False and manager.extractions.get(started["run_id"])["status"] == "succeeded"
    finally:
        manager.close()


def test_grocery_items_fixture_matches_the_printed_subtotal():
    """The fixture's rows add up to its printed subtotal (349 + 136 + 400 + 10 + 10 − 50 = 855)."""
    assert sum(round(float(row["line_total"]) * 100) for row in grocery_items(GROCERY)) == 855
