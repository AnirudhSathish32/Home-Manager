"""Order-wide discounts and order numbers (docs/money.md "Order discounts and order numbers"): a printed Discounts line comes off
the subtotal, makes the receipt add up and is shared across the items by amount; an online order's number is kept, and is the
code of an item that prints none without ever identifying a product. Synthetic receipts only."""

from contextlib import contextmanager

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from document_forms_fixtures import amount_on, receipt_replies, value
from document_forms_fixtures import item as reply_item
from home_manager.finance import splits
from home_manager.finance.ledger import Ledger
from home_manager.household.items import ItemLedger
from home_manager.library.storage import Store
from test_extraction import extract, transcribe
from test_receipt_tax_codes import rows, shares_of
from test_reconcile_tools import source_of

# O: a snippet of an online order like the one reported, from a made-up shop. The total sits beside the order number too.
O_LINES = ["SYNTH NUTRITION", "Order #4401304 $84.04", "2026-10-07", "Grass-Fed Whey Protein Isolate Every 45 days",
           "[unreadable] 1 x 4LB / Milk Chocolate $89.99", "Shipping", "Summary", "Subtotal $89.99", "Shipping Free", "Taxes $3.04",
           "Discounts $8.99", "Total $84.04"]


def o_replies(discount=True, order=True):
    lines = O_LINES
    summary = {"subtotal": amount_on(lines, "Subtotal"), "tax": amount_on(lines, "Taxes"), "total": amount_on(lines, "Total $84.04")}
    if discount:
        summary["order_discount"] = amount_on(lines, "Discounts")
    if order:
        summary["order_number"] = value(lines, "#4401304", "Order #4401304", "Order #4401304")
    items = [reply_item(lines, "Grass-Fed Whey Protein Isolate", "Grass-Fed Whey Protein Isolate", "89.99", product_code="[unreadable]",
                        quantity="1", also=["[unreadable] 1 x 4LB"])]
    return receipt_replies(lines, None, "Synth Nutrition", "SYNTH NUTRITION", "2026-10-07", summary, items, category="health")


@contextmanager
def reading(tmp_path, local_model, lines, replies):
    """Like test_receipt_tax_codes.reading, for O's transcription: partial, as it holds an [unreadable] mark."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines, status="partial")
    try:
        local_model["requests"].clear()
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        yield manager, (doc, parse_id), run["publication"]["id"]
    finally:
        manager.close()


def stored(store, receipt_id):
    return rows(store, "SELECT subtotal_minor,discount_minor,tax_minor,total_minor,order_number FROM receipts WHERE id=?", receipt_id)[0]


def test_an_order_discount_and_number_are_read_and_make_the_receipt_add_up(tmp_path, local_model):
    with reading(tmp_path, local_model, O_LINES, o_replies()) as (manager, _again, receipt_id):
        assert stored(manager.store, receipt_id) == (8999, 899, 304, 8404, "4401304")
        record = manager.ledger.record("receipt", receipt_id)
        assert [item["product_code"] for item in record["items"]] == ["4401304"]  # [unreadable] is no code; the order's number is.
        assert record["totals_mismatch"] is False and not [issue for issue in record["issues"] if "do not equal" in issue]
        assert record["display"]["discount_shown_minor"] == "-8.99 USD"
        assert shares_of(manager.store, receipt_id) == ([8404], [8404])
        assert {"discount", "order_number"} <= {entry["field"] for entry in record["correctable"]}
        # The order number shown as its code never identifies a product.
        item_id = record["items"][0]["id"]
        assert ItemLedger(manager.store).line(item_id)["product_code"] is None


def test_without_the_discount_the_receipt_does_not_add_up(tmp_path, local_model):
    with reading(tmp_path, local_model, O_LINES, o_replies(discount=False, order=False)) as (manager, _again, receipt_id):
        assert stored(manager.store, receipt_id) == (8999, None, 304, 8404, None)
        record = manager.ledger.record("receipt", receipt_id)
        assert record["totals_mismatch"] is True and record["items"][0]["product_code"] is None
        assert "Subtotal, tax and tip (93.03 USD) do not equal the total (84.04 USD)." in record["issues"]


def test_an_order_number_not_printed_where_it_is_cited_keeps_neither_new_field(tmp_path, local_model):
    from home_manager.documents.extraction import DETAILS_FAILED
    replies = o_replies()
    replies["ReceiptSummary"] = [{**replies["ReceiptSummary"][0], "order_number": value(O_LINES, "4401305", "Order #4401304", "Order #4401304")}] * 2
    # Asked again once, then the reading is kept with its usual fields only, like any new field that fails twice (FR-14).
    with reading(tmp_path, local_model, O_LINES, replies) as (manager, _again, receipt_id):
        assert stored(manager.store, receipt_id) == (8999, None, 304, 8404, None)
        assert DETAILS_FAILED in manager.ledger.record("receipt", receipt_id)["issues"]


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"a.png": b"synthetic order a", "b.png": b"synthetic order b"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def receipt(subtotal, discount, total):
    items = [{"description": name, "product_code": None, "quantity": None, "unit_price_minor": None, "line_total_minor": amount, "discount_minor": None,
              "taxed": None, "category": category, "locator": {"line_ids": ["line-1"]}} for name, amount, category in
             (("PROTEIN", 5000, "health"), ("SHAKER", 3000, "household supplies"))]
    return {"merchant": "Synth Nutrition", "purchase_date": "2026-10-07", "subtotal_minor": subtotal, "discount_minor": discount, "tax_minor": 0,
            "tip_minor": None, "total_minor": total, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]}, "items": items}


def test_the_discount_is_shared_by_item_amount_whether_or_not_the_subtotal_has_it_off(books):
    store, ledger, docs = books
    # Subtotal 80.00 less Discounts 8.00 is 72.00: each item keeps 90% (45.00 and 27.00).
    off = ledger.publish_receipt(receipt(8000, 800, 7200), source_of(docs["a.png"], "extraction:a"), "verified")["id"]
    # The same discount printed after a subtotal that already has it taken off (72.00): shared the same way, and still adds up.
    inside = ledger.publish_receipt(receipt(7200, 800, 7200), source_of(docs["b.png"], "extraction:b"), "verified")["id"]
    for receipt_id in (off, inside):
        assert shares_of(store, receipt_id) == ([4500, 2700], [4500, 2700])
        assert ledger.record("receipt", receipt_id)["totals_mismatch"] is False
    assert splits.discount_off(8000, 800, 0, None, 7200) == 800 and splits.discount_off(7200, 800, 0, None, 7200) == 0
    # A corrected discount is kept and checked: 80.00 less 16.00 no longer makes the 72.00 total.
    ledger.correct("receipt", off, {"discount": "16.00"})
    assert rows(store, "SELECT discount_minor FROM receipts WHERE id=?", off) == [(1600,)]
    assert ledger.record("receipt", off)["totals_mismatch"] is True and sum(shares_of(store, off)[1]) == 7200
    assert_ledger_healthy(store)
