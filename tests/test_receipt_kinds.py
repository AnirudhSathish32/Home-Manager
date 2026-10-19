"""Receipt kinds (specs/document-forms FR-01 – FR-19): each kind read with its own form, its printed details kept and
checked, and what counts unchanged except where the spec says."""

from contextlib import contextmanager
import json

import pytest

from document_forms_fixtures import (
    AMBIGUOUS,
    DINING,
    FUEL,
    GIFT_CARD_STATEMENT,
    GIFT_RECEIPT,
    GROCERY,
    MISSING,
    amount_on,
    card_replies,
    cite,
    dining_replies,
    fuel,
    fuel_replies,
    grocery_items,
    grocery_replies,
    item,
    library,
    receipt_replies,
    record_document,
    stored_identifiers,
    uncited,
    value,
)
from home_manager.documents.extraction import DETAILS_FAILED, EXTRACTION_VERSION, HEADERS
from home_manager.finance import traces
from home_manager.finance.health import check_ledger
from home_manager.finance.tools import FinanceTools, PeriodInput
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
        # The gift card is a way of paying (D15): the printed total is kept, and the amount paid is what counts.
        assert (row["printed_total_minor"], row["total_minor"]) == (855, 355)
        assert (record["printed_total"]["minor"], record["amount_paid"]["minor"]) == (855, 355)
        assert [(tender["label"], tender["amount"]["decimal"]) for tender in record["tenders"]] == [("Gift card", "5.00"), ("EBT", "3.55")]
        assert sum(split["amount_minor"] for split in record["splits"]) == 355
        with manager.store.connection() as db:
            assert stored_identifiers(db, ("6006491234565555",)) == []  # C-ids
            assert check_ledger(db) == []


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
        assert record["receipt_kind"] == "general" and record["details"] == {} and record["checks"] == []
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


def test_sc04_d_a_gift_card_read_as_an_item_fails_the_item_sum(tmp_path, local_model):
    replies = grocery_replies(items=[*grocery_items(GROCERY), item(GROCERY, "GIFT CARD", "GIFT CARD", "-5.00")])
    replies["ReceiptGrocerySummary"][0]["tenders"] = [replies["ReceiptGrocerySummary"][0]["tenders"][1]]  # EBT only.
    with read_receipt(tmp_path, local_model, GROCERY, replies) as (_, _run, record, row):
        assert record["review_status"] == "needs_review" and any(issue.startswith("Item line totals") for issue in record["issues"])
        assert (row["total_minor"], row["printed_total_minor"]) == (855, None)  # With no gift card tender, the total is what was paid.


def test_sc04_e_gift_card_deductions_above_the_total(tmp_path, local_model):
    lines = [line.replace("-5.00", "-9.00") for line in GROCERY]
    replies = grocery_replies(lines)
    replies["ReceiptGrocerySummary"][0]["tenders"][0]["amount"] = "9.00"
    with read_receipt(tmp_path, local_model, lines, replies) as (_, _run, record, row):
        assert record["review_status"] == "needs_review"
        assert any("gift card deductions exceed the total" in issue.lower() for issue in record["issues"])
        assert (row["total_minor"], row["printed_total_minor"]) == (855, None)


def test_sc04_f_no_gift_card_counts_the_total_as_today(tmp_path, local_model):
    lines = [line for line in GROCERY if not line.startswith("GIFT CARD")]
    lines[-1] = "EBT SNAP 8.55"
    with read_receipt(tmp_path, local_model, lines, grocery_replies(lines)) as (_, _run, record, row):
        assert (row["total_minor"], row["printed_total_minor"], record["review_status"]) == (855, None, "verified")


def test_sc04_a_gift_card_on_a_return_is_not_handled(tmp_path, local_model):
    """Plan variant: correcting the receipt to a return counts the signed printed total with a note; undo puts the amount
    paid back and the note goes."""
    with read_receipt(tmp_path, local_model, GROCERY, grocery_replies()) as (manager, _run, _record, row):
        returned = manager.ledger.correct("receipt", row["id"], {"direction": "return"})
        assert returned["total_minor"] == -855 and any(issue.startswith("Gift card on a return") for issue in returned["issues"])
        undone = manager.ledger.undo_corrections("receipt", row["id"], returned["correction_ids"])
        assert undone["total_minor"] == 355 and not any(issue.startswith("Gift card on a return") for issue in undone["issues"])
        with manager.store.connection() as db:
            assert check_ledger(db) == []


def test_a_receipt_with_no_total_publishes_as_today(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, GROCERY, grocery_replies(total=MISSING)) as (_, _run, _record, row):
        assert (row["total_minor"], row["printed_total_minor"]) == (None, None)


def october(manager):
    """October 2026 spending by category, as the app counts it."""
    found = FinanceTools(manager.store).get_spending_by_category(PeriodInput(start="2026-10-01", end="2026-10-31"))
    return {row["category"]: row["spending"]["minor"] for row in found["categories"]}


def gift_receipt_replies(lines=GIFT_RECEIPT):
    gift = next((line for line in lines if line.startswith("GIFT CARD")), None)
    visa = next(line for line in lines if line.startswith("VISA"))
    tenders = ([{"tender_type": "gift_card", "amount": "5.00", "last_four": "5555", "evidence": cite(lines, gift)}] if gift else []) + [
        {"tender_type": "card", "amount": visa.split()[-1], "last_four": "4242", "evidence": cite(lines, visa)}]
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": amount_on(lines, "TAX "), "total": amount_on(lines, "TOTAL "),
               "card_last_four": value(lines, "4242", visa, "4242"), "tenders": tenders}
    return receipt_replies(lines, "grocery", "Synth Market", "SYNTH MARKET", "2026-10-03", summary,
                           [item(lines, "GROCERIES", "GROCERIES 8.55", "8.55")], category="groceries", kind_evidence=cite(lines, "GROCERIES"))


def gift_card_library(tmp_path, local_model, receipt_lines=GIFT_RECEIPT, statement=GIFT_CARD_STATEMENT):
    """SC-27's library: the receipt recorded, then the card statement recorded and reconciled. The household has a
    category rule for the market: today a statement line with no receipt is uncategorized without one, and the
    contract counts the unrelated -8.55 line as groceries."""
    manager = library(tmp_path, local_model)
    manager.ledger.add_rule("SYNTH MARKET", "groceries")
    _, _, run = record_document(manager, local_model, "receipt.png", receipt_lines, gift_receipt_replies(receipt_lines))
    receipt_id = run["publication"]["id"]
    before = october(manager)
    _, _, statement_run = record_document(manager, local_model, "card.png", statement, card_replies(statement))
    manager.reconciler.reconcile_statement(statement_run["publication"]["id"])
    return manager, receipt_id, before


def links(manager, receipt_id):
    with manager.store.connection() as db:
        return [dict(row) for row in db.execute("SELECT t.amount_minor,l.match_method,l.match_score FROM transaction_receipt_links l "
                                                "JOIN transactions t ON t.id=l.transaction_id WHERE l.receipt_id=? AND l.review_status<>'rejected'",
                                                (receipt_id,))]


def test_sc27_a_gift_card_lowers_what_is_charged_and_what_counts(tmp_path, local_model):
    """One library across the checkpoints (the contract's journey). Trace checkpoints are with the traces (SL-07)."""
    manager, receipt_id, before = gift_card_library(tmp_path, local_model)
    try:
        record = manager.ledger.record("receipt", receipt_id)
        assert (record["printed_total"]["minor"], record["amount_paid"]["minor"]) == (855, 355)
        assert [tender["amount"]["minor"] for tender in record["tenders"] if tender["tender_type"] == "gift_card"] == [500]
        assert before["groceries"] == 355  # Before reconciling, the receipt counts on its own, at what was paid.
        # The receipt links to the -3.55 line, not the -8.55 one, as any exact match is linked.
        [link] = links(manager, receipt_id)
        assert link["amount_minor"] == -355 and link["match_method"] and link["match_score"]
        # The linked line counts once with the receipt's categories, scaled to 3.55, and the other line on its own.
        assert october(manager) == {"groceries": 1210}
        with manager.store.connection() as db:
            charged = db.execute("SELECT sum(s.amount_minor) FROM category_splits s JOIN transactions t ON t.id=s.transaction_id "
                                 "WHERE s.receipt_id=? AND t.amount_minor=-355", (receipt_id,)).fetchone()[0]
        assert charged == 355
        paid = trace_of(manager, check_named(record, "paid")["figure"]["trace"])  # Compared with the VISA charge printed on it.
        assert (paid["result"]["decimal"], paid["compared_with"]["decimal"], paid["reconciles"]) == ("3.55", "3.55", True)
        # Correct the gift card: what was paid follows, the link stays, and the receipt waits for the user.
        gift = next(entry["field"] for entry in record["correctable"] if entry["label"] == "Gift card amount")
        corrected = manager.ledger.correct("receipt", receipt_id, {gift: "4.00"})
        assert corrected["amount_paid"]["minor"] == 455 and corrected["printed_total"]["minor"] == 855
        overridden = inputs_by_key(trace_of(manager, check_named(corrected, "paid")["figure"]["trace"]))["gift_card:1"]
        assert (overridden["provenance"]["kind"], overridden["provenance"]["original"], overridden["value"]["decimal"]) == ("override", "5.00", "4.00")
        assert len(links(manager, receipt_id)) == 1 and corrected["review_status"] == "needs_review"
        assert "Amount paid (4.55) no longer equals the linked charge (3.55)." in corrected["issues"]
        entry = next(item for item in manager.ledger.history("receipt", receipt_id) if item.get("field") == gift)
        assert (entry["label"], entry["from"], entry["to"], entry["undoable"]) == ("Gift card amount", "5.00 USD", "4.00 USD", True)
        undone = manager.ledger.undo_corrections("receipt", receipt_id, corrected["correction_ids"])
        assert undone["amount_paid"]["minor"] == 355 and not any(issue.startswith("Amount paid (") for issue in undone["issues"])
        assert october(manager) == {"groceries": 1210} and len(links(manager, receipt_id)) == 1
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
            assert check_ledger(db) == []  # Every receipt's split rows sum to what it counts.
    finally:
        manager.close()


def trace_of(manager, ref):
    """GET /api/traces/{ref} as the API answers it (traces.trace with the app's manager)."""
    return traces.trace(manager.store, ref, manager)


def check_named(record, name):
    return next(check for check in record["checks"] if check["name"] == name)


def inputs_by_key(trace):
    return {item["key"]: item for item in trace["inputs"]}


def test_sc19_the_fuel_trace(tmp_path, local_model):
    """Steps 1 and 3: the fuel figure, its inputs extracted from line-4, its rounding; a corrected volume is an override."""
    lines = fuel()
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (manager, _run, record, row):
        shown = check_named(record, "fuel")
        trace = trace_of(manager, shown["figure"]["trace"])
        assert (trace["result"]["decimal"], trace["compared_with"]["decimal"], trace["reconciles"]) == ("35.67", "35.67", True)
        assert trace["result"] == {key: shown["figure"][key] for key in trace["result"]}  # The trace is the figure shown.
        inputs = inputs_by_key(trace)
        assert (inputs["volume"]["value"]["text"], inputs["price_per_unit"]["value"]["text"]) == ("10.312", "3.459")
        for key in ("volume", "price_per_unit"):
            provenance = inputs[key]["provenance"]
            assert provenance["kind"] == "extracted" and provenance["line_ids"] == ["line-4"] and provenance["quote"] in lines[3]
        assert trace["rounding"]["method"] == "half_up_minor" and trace["rounding"]["note"] == "10.312 × 3.459 = 35.669208"
        corrected = manager.ledger.correct("receipt", row["id"], {"detail:volume": "10.000"})
        again = trace_of(manager, check_named(corrected, "fuel")["figure"]["trace"])
        volume = inputs_by_key(again)["volume"]
        assert (volume["provenance"]["kind"], volume["provenance"]["original"], volume["value"]["text"]) == ("override", "10.312", "10.000")
        assert (again["result"]["decimal"], again["reconciles"]) == ("34.59", False)
        assert again["inputs_hash"] != trace["inputs_hash"]


def test_sc19_a_fuel_mismatch_doesnt_reconcile(tmp_path, local_model):
    lines = fuel(sale="36.67", total="38.86")
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (manager, _run, record, _row):
        trace = trace_of(manager, check_named(record, "fuel")["figure"]["trace"])
        assert (trace["result"]["decimal"], trace["compared_with"]["decimal"], trace["reconciles"]) == ("35.67", "36.67", False)
        assert check_named(record, "fuel")["passes"] is False


def test_sc19_the_dining_trace(tmp_path, local_model):
    with read_receipt(tmp_path, local_model, DINING, dining_replies()) as (manager, _run, record, _row):
        trace = trace_of(manager, check_named(record, "dining")["figure"]["trace"])
        assert [(step["label"], step["value"]["decimal"] if step["value"] else None) for step in trace["steps"]] == [
            ("Subtotal", "50.00"), ("Tax", "4.00"), ("Gratuity", "9.00"), ("Tip (not printed)", None)]
        assert (trace["result"]["decimal"], trace["compared_with"]["decimal"], trace["reconciles"]) == ("63.00", "63.00", True)


def test_sc19_the_multi_unit_and_amount_paid_traces(tmp_path, local_model):
    """Steps 5 and 6 on SC-04's receipt."""
    with read_receipt(tmp_path, local_model, GROCERY, grocery_replies()) as (manager, _run, record, _row):
        line = trace_of(manager, check_named(record, "unit_line:3")["figure"]["trace"])
        inputs = inputs_by_key(line)
        assert (inputs["count"]["value"]["text"], inputs["unit_price"]["value"]["decimal"]) == ("2", "2.00")
        assert all(inputs[key]["provenance"]["kind"] == "extracted" and inputs[key]["provenance"]["line_ids"] == ["line-5"] for key in ("count", "unit_price"))
        assert (line["result"]["decimal"], line["compared_with"]["decimal"], line["reconciles"]) == ("4.00", "4.00", True)
        paid = trace_of(manager, check_named(record, "paid")["figure"]["trace"])
        assert [(step["label"], step["op"], step["value"]["decimal"]) for step in paid["steps"]] == [("Total", "+", "8.55"), ("Gift card", "−", "5.00")]
        inputs = inputs_by_key(paid)
        assert (inputs["total"]["provenance"]["line_ids"], inputs["gift_card:1"]["provenance"]["line_ids"]) == (["line-11"], ["line-12"])
        assert all(item["provenance"]["kind"] == "extracted" for item in paid["inputs"])
        assert (paid["result"]["decimal"], paid["compared_with"]["decimal"], paid["reconciles"]) == ("3.55", "3.55", True)
        assert inputs["tender:2"]["provenance"]["line_ids"] == ["line-13"]  # Compared with the other printed tender, EBT.
        assert paid["result"]["minor"] == record["amount_paid"]["minor"]


def test_sc19_b_the_multi_unit_trace_on_a_mismatch(tmp_path, local_model):
    lines = [{"2x CHIPS @ 2.00 4.00": "2x CHIPS @ 2.00 4.50", "SUBTOTAL 8.55": "SUBTOTAL 9.05", "TOTAL 8.55": "TOTAL 9.05"}.get(line, line) for line in GROCERY]
    with read_receipt(tmp_path, local_model, lines, grocery_replies(lines)) as (manager, _run, record, _row):
        line = trace_of(manager, check_named(record, "unit_line:3")["figure"]["trace"])
        assert (line["compared_with"]["decimal"], line["reconciles"]) == ("4.50", False)


def test_sc19_a_figure_a_record_doesnt_have(tmp_path, local_model):
    """Step 7: a fuel trace on a dining receipt, a dining trace on a fuel receipt, a multi-unit trace on MILK, and an
    amount-paid trace on a receipt with no gift card."""
    lines = fuel()
    with read_receipt(tmp_path, local_model, lines, fuel_replies(lines)) as (manager, _run, _record, row):
        for name in ("receipt.dining", "receipt.paid", "receipt.fuel"):
            ref = f"{name}?receipt_id={row['id']}"
            if name == "receipt.fuel":
                trace_of(manager, ref)  # Its own figure is worked out.
                continue
            with pytest.raises(ValueError, match="This isn't worked out for this record."):
                trace_of(manager, ref)
        with pytest.raises(ValueError, match="This isn't worked out for this record."):
            trace_of(manager, f"receipt.fuel?receipt_id={row['id'] + 99}")
    with read_receipt(tmp_path / "dining", local_model, DINING, dining_replies()) as (manager, _run, _record, row):
        with pytest.raises(ValueError, match="This isn't worked out for this record."):
            trace_of(manager, f"receipt.fuel?receipt_id={row['id']}")
    with read_receipt(tmp_path / "grocery", local_model, GROCERY, grocery_replies()) as (manager, _run, _record, row):
        with pytest.raises(ValueError, match="This isn't worked out for this record."):
            trace_of(manager, f"receipt.unit_line?receipt_id={row['id']}&position=1")


def test_sc27_a_without_a_gift_card_it_links_to_the_full_charge(tmp_path, local_model):
    lines = [line for line in GIFT_RECEIPT if not line.startswith("GIFT CARD")]
    lines[-1] = "VISA ****4242 8.55"
    manager, receipt_id, _ = gift_card_library(tmp_path, local_model, receipt_lines=lines)
    try:
        assert [link["amount_minor"] for link in links(manager, receipt_id)] == [-855]
    finally:
        manager.close()


def test_sc27_b_only_the_full_charge_printed_means_no_match(tmp_path, local_model):
    statement = [line for line in GIFT_CARD_STATEMENT if "-3.55" not in line]
    statement[statement.index("NEW BALANCE 12.10")] = "NEW BALANCE 8.55"
    manager, receipt_id, _ = gift_card_library(tmp_path, local_model, statement=statement)
    try:
        assert links(manager, receipt_id) == []
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM reconciliation_issues WHERE status='open'").fetchone()[0] == 0  # No near match either.
        assert october(manager) == {"groceries": 355 + 855}
    finally:
        manager.close()
