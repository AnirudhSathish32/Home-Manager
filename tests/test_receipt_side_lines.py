"""SC-13 and SC-14 of specs/dining-receipt-indent: a line printed indented under an item with no price of its own stays with that
item (FR-22: the row instruction says so; FR-23: the backstop in ExtractionService.record drops a row that only cites such lines).
Synthetic breakfast receipt and the local model stub only.

SC-13 step 5 (the receipt split, C-sum 6155 and C-cat dining) needs the charged total and one category (FR-01, FR-10); it is
checked with those features, not here."""

import json

import pytest

from bill_kinds_fixtures import RENT, general_replies, general_rows
from dining_receipt_fixtures import (
    BREAKFAST_INDENTS,
    BREAKFAST_ROWS,
    SIDE_LINES,
    b11_stub,
    breakfast_stub,
    image_id,
    row,
    side_line_stub,
    vision_lines,
)
from home_manager.documents.extraction import SIDE_LINES_RULE, Item, attach_side_lines
from home_manager.documents.receipt_schema import TextLine
from test_dining_baseline_capture import record, start_reasoning
from test_extraction import cite
from test_vision_indent import image_document, line_payloads, old_library

DROPPED = ("“{line}” is printed under “{item}” with no price of its own, so it was kept with that item, not as an item.")
KEY_PHRASES = ["A line indented under an item", "with no price of its own belongs to that item", "cite it with the item", "never make it an item",
               "An indented line that prints its own price keeps the rules above", "a count line belongs to its item", "any other priced line is its own row"]


def read(tmp_path, local_model, texts, indents, replies):
    """The breakfast image read with the stub's lines and indents, then recorded with replies: (manager, run, requests)."""
    manager, doc_id, run_id = image_document(tmp_path, local_model, vision_lines(texts, indents))
    start_reasoning(manager, local_model)
    run, requests = record(manager, local_model, doc_id, run_id, replies)
    return manager, run, requests


def stored_items(manager, run):
    """[(description, line_total_minor)] of the receipt's items, in order."""
    with manager.store.connection() as db:
        return [tuple(item) for item in db.execute("SELECT description,line_total_minor FROM receipt_items WHERE receipt_id=? ORDER BY position",
                                                  (run["publication"]["id"],))]


def drop_notes(manager, run):
    """The receipt's issues about lines kept with an item, in order."""
    issues = manager.ledger.record("receipt", run["publication"]["id"])["issues"]
    return [issue for issue in issues if "is printed under" in issue or issue.startswith("and ") and issue.endswith(" more")]


def evidence_lines(run, position):
    return [cite["line_id"] for cite in run["result"]["rows"][position]["evidence"]]


B0_ITEMS = [("Bottled Water", 395), ("Bottled Water", 395), ("Coffee", 1495), ("Georgia Peach Stack", 1870), ("Better Than No Y'all Biscuits", 730)]


def three_dropped(item="Georgia Peach Stack"):
    return [DROPPED.format(line=name, item=item) for name in ("No Allergies", "Fresh Berry Pancakes", "Veggie Sausage")] + ["and 1 more"]


def test_sc13_step1_the_rows_instruction_names_the_rule_for_every_receipt_form(tmp_path, local_model):
    for name, build, schema in (("dining", breakfast_stub, "Items"), ("grocery", b11_stub, "GroceryItems")):
        texts, indents, replies = build(image_id)
        manager, _run, requests = read(tmp_path / name, local_model, texts, indents, replies)
        try:
            [rows] = [request for request in requests if request["response_format"]["json_schema"]["name"] == schema]
            instruction = rows["messages"][0]["content"]
            assert SIDE_LINES_RULE in instruction and all(phrase in instruction for phrase in KEY_PHRASES), name
            # Every other question's instruction leaves the rule out.
            assert not any(SIDE_LINES_RULE in request["messages"][0]["content"] for request in requests if request is not rows)
        finally:
            manager.close()


def test_sc13_side_lines_stay_with_their_item(tmp_path, local_model):
    texts, indents, replies = side_line_stub()
    manager, run, requests = read(tmp_path, local_model, texts, indents, replies)
    try:
        # 2. The five B0 items, sum 4885; no item is named after a side line.
        items = stored_items(manager, run)
        assert items == B0_ITEMS and sum(total for _, total in items) == 4885
        assert [name for name, _ in SIDE_LINES if name in [item for item, _ in items]] == []
        # 3. Georgia Peach Stack cites lines 10 to 14, and the others cite their own.
        assert evidence_lines(run, 3) == ["line-10", "line-11", "line-12", "line-13", "line-14"]
        assert [len(run["result"]["rows"][position]["evidence"]) for position in (0, 1, 2, 4)] == [1, 1, 1, 1]
        # The categories follow the kept rows (B0's), and the request was the indented reading's.
        assert run["result"]["item_categories"] == ["groceries", "groceries", "dining", "dining", "dining"]
        assert len(run["result"]["rows"]) == 5 and all(entry["indent"] == 1 for entry in dict(line_payloads(requests))["Items"][10:14])
        # 4. The notes, in order, and nothing more.
        assert drop_notes(manager, run) == three_dropped()
        assert run["result"]["notes"][-4:] == three_dropped()
    finally:
        manager.close()


def test_sc13a_side_lines_published_as_zero_dollar_items_are_dropped_too():
    """B6z: the four rows carry line_total 0.00. The extraction model's answer can't carry that through a whole reading, because an amount
    must be printed in its cited lines (problems_in) and a side line prints none, so the rule is checked on the rows themselves."""
    texts, indents, replies = side_line_stub(zero=True)
    lines = [TextLine(id=image_id(number), text=text, block_ids=[], indent=indent) for number, (text, indent) in enumerate(zip(texts, indents), 1)]
    rows = [Item.model_validate(entry) for entry in replies["Items"][0]["items"]]
    categories = replies["PurchaseDescription"][0]["item_categories"]
    kept, kept_categories, references, notes = attach_side_lines(rows, lines, categories, [[number] for number in range(len(rows))])
    assert [(item.description, item.line_total) for item in kept] == [(name, total) for name, _, _, total in BREAKFAST_ROWS]
    assert [cite.line_id for cite in kept[3].evidence] == ["line-10", "line-11", "line-12", "line-13", "line-14"]
    assert kept_categories == ["groceries", "groceries", "dining", "dining", "dining"] and references == [[0], [1], [2], [3], [8]]
    assert notes == three_dropped()


def test_sc13b_a_side_line_with_no_item_before_it_stays_an_item(tmp_path, local_model):
    texts, indents, replies = breakfast_stub("B0")
    replies["Items"][0]["items"].insert(0, row(texts, 11, image_id, "No Allergies", None))
    replies["PurchaseDescription"][0]["item_categories"].insert(0, "groceries")
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        assert stored_items(manager, run) == [("No Allergies", None), *B0_ITEMS]
        assert evidence_lines(run, 0) == ["line-11"] and drop_notes(manager, run) == []
    finally:
        manager.close()


def test_sc13c_an_indented_line_that_prints_an_amount_stays_its_own_item(tmp_path, local_model):
    """D17: line 12 reads "Fresh Berry Pancakes $2.00" and is published as an item at 2.00. The unpriced lines around it are
    dropped: line 11 joins Georgia Peach Stack, lines 13 and 14 join the priced item before them."""
    texts, indents, replies = side_line_stub()
    texts[11] = "Fresh Berry Pancakes $2.00"
    replies["Items"][0]["items"][5] = row(texts, 12, image_id, "Fresh Berry Pancakes", "2.00")
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        assert stored_items(manager, run) == [*B0_ITEMS[:4], ("Fresh Berry Pancakes", 200), B0_ITEMS[4]]
        assert evidence_lines(run, 3) == ["line-10", "line-11"]
        assert evidence_lines(run, 4) == ["line-12", "line-13", "line-14"]
        assert drop_notes(manager, run) == [DROPPED.format(line="No Allergies", item="Georgia Peach Stack"),
                                            DROPPED.format(line="Veggie Sausage", item="Fresh Berry Pancakes"),
                                            DROPPED.format(line="Jalapeno Cheese Grits", item="Fresh Berry Pancakes")]
    finally:
        manager.close()


def test_sc13d_a_bill_with_an_unpriced_indented_row_is_unaffected(tmp_path, local_model):
    """The same backstop sits in front of receipts only: a general bill's unpriced row, printed indented under a charge, stays a line."""
    lines = [*RENT, "Includes covered parking"]
    indents = [0] * len(RENT) + [1]
    rows = [*general_rows(RENT), {"description": "Covered parking", "amount": None, "quantity": None, "unit_price": None, "category": None,
                                  "line_kind": "service", "line_holder": None, "evidence": cite(8, lines[7])}]
    replies = general_replies(RENT, rows=rows)
    manager, doc_id, run_id = image_document(tmp_path, local_model, vision_lines(lines, indents))
    try:
        start_reasoning(manager, local_model)
        local_model["by_schema"] = {name: list(reply) for name, reply in replies.items()}
        extraction = manager.start_extraction(doc_id, run_id, False)["run_id"]
        manager.future.result(timeout=60)
        run = manager.extractions.get(extraction)
        assert run["status"] == "succeeded", run["error"]  # The bill itself may wait (no account); its lines are what is checked.
        descriptions = [item["description"] for item in run["result"]["rows"]]
        assert descriptions == ["Rent", "Water Usage", "Covered parking"]
        assert not [note for note in run["result"]["notes"] if "is printed under" in note]
    finally:
        manager.close()


def test_sc13e_two_dropped_lines_give_two_notes_and_no_more_line(tmp_path, local_model):
    texts, indents, replies = side_line_stub()
    del replies["Items"][0]["items"][6:8]  # Only No Allergies and Fresh Berry Pancakes are published as items.
    del replies["PurchaseDescription"][0]["item_categories"][6:8]
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        assert stored_items(manager, run) == B0_ITEMS
        assert evidence_lines(run, 3) == ["line-10", "line-11", "line-12"]
        assert drop_notes(manager, run) == three_dropped()[:2]
    finally:
        manager.close()


def test_sc13_exactly_three_notes_and_no_more_line_for_three_dropped_lines(tmp_path, local_model):
    texts, indents, replies = side_line_stub()
    del replies["Items"][0]["items"][7]
    del replies["PurchaseDescription"][0]["item_categories"][7]
    manager, run, _ = read(tmp_path, local_model, texts, indents, replies)
    try:
        assert drop_notes(manager, run) == three_dropped()[:3]
    finally:
        manager.close()


def test_sc14_no_indent_no_backstop(tmp_path, local_model):
    """Vision answers with no indent keys (unknown, D25): the nine items stay, nothing is noted."""
    texts, _, replies = side_line_stub()
    manager, run, requests = read(tmp_path, local_model, texts, [None] * len(texts), replies)
    try:
        items = stored_items(manager, run)
        assert [name for name, _ in items] == ["Bottled Water", "Bottled Water", "Coffee", "Georgia Peach Stack", "No Allergies", "Fresh Berry Pancakes",
                                               "Veggie Sausage", "Jalapeno Cheese Grits", "Better Than No Y'all Biscuits"]
        assert drop_notes(manager, run) == [] and evidence_lines(run, 3) == ["line-10"]
        assert not any("indent" in json.dumps(entry) for _, entries in line_payloads(requests) for entry in entries)
    finally:
        manager.close()


def test_sc14_step2_extract_again_from_an_old_reading_keeps_the_nine_items(tmp_path, local_model):
    manager, doc_id, old_id = old_library(tmp_path, local_model, "R6")
    try:
        start_reasoning(manager, local_model)
        _, _, replies = side_line_stub()
        run, _ = record(manager, local_model, doc_id, old_id, replies)
        assert len(stored_items(manager, run)) == 9 and drop_notes(manager, run) == []  # The old reading's lines carry no indent.
    finally:
        manager.close()


@pytest.mark.parametrize("indent", [0, None])
def test_an_unpriced_row_on_a_line_that_is_not_indented_stays_an_item(tmp_path, local_model, indent):
    texts, indents, replies = side_line_stub()
    manager, run, _ = read(tmp_path, local_model, texts, [indent if number in (11, 12, 13, 14) else value for number, value in enumerate(BREAKFAST_INDENTS, 1)],
                           replies)
    try:
        assert len(stored_items(manager, run)) == 9 and drop_notes(manager, run) == []
    finally:
        manager.close()
