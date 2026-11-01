"""Receipt tax codes (specs/receipt-tax-codes): what a receipt keeps of the codes beside its prices and the per-code tax lines it
prints, and that receipts recorded without them keep their shares. Synthetic receipts only, published through Ledger paths."""

import json

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.finance.ledger import Ledger, rate_display
from home_manager.finance.reconcile import Reconciler
from home_manager.library.storage import Store
from test_reconcile_tools import source_of


def item(description, total, taxed, category, code=None, line="line-1"):
    return {"description": description, "product_code": None, "quantity": None, "unit_price_minor": None, "line_total_minor": total,
            "discount_minor": None, "taxed": taxed, "category": category, "tax_code": code, "locator": {"line_ids": [line]}}


def tax_line(code, amount, taxable=None, rate="7.75000", line="line-11"):
    return {"code": code, "rate_text": rate, "taxable_minor": taxable, "amount_minor": amount, "locator": {"line_ids": [line]}}


def receipt(items, tax, total, subtotal, **more):
    return {"merchant": "Synth Mart", "purchase_date": "2026-10-20", "subtotal_minor": subtotal, "tax_minor": tax, "tip_minor": None,
            "total_minor": total, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]}, "items": items, **more}


def r_items(coded=True):
    """R: Ruffles and Little Veg carry BF, the water filter T (the stored flags are the reported ones: BF items untaxed)."""
    return [item("RUFFLES", 429, False, "groceries", "BF" if coded else None, "line-2"),
            item("LITLE VEGET", 4190, False, "groceries", "BF" if coded else None, "line-3"),
            item("WATER FILTER", 1299, True, "household supplies", "T" if coded else None, "line-7")]


R_LINES = [tax_line("T", 101, 1299, line="line-11"), tax_line("B", 173, 4619, line="line-12")]


def r_receipt(**more):
    return receipt(r_items(), 274, 6192, 5918, tax_source="tax_lines", tax_lines=R_LINES, **more)


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"r.png": b"synthetic mart receipt", "d.png": b"synthetic costco receipt"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def rows(store, sql, *args):
    with store.connection() as db:
        return [tuple(row) for row in db.execute(sql, args)]


def stored_lines(store, receipt_id):
    return rows(store, "SELECT position,code,rate_text,taxable_minor,amount_minor,locator_json FROM receipt_tax_lines WHERE receipt_id=? ORDER BY position",
                receipt_id)


def test_publish_keeps_codes_lines_and_source(books):
    store, ledger, docs = books
    published = ledger.publish_receipt(r_receipt(), source_of(docs["r.png"], "extraction:r"), "verified")
    receipt_id = published["id"]
    assert rows(store, "SELECT tax_source FROM receipts WHERE id=?", receipt_id) == [("tax_lines",)]
    assert rows(store, "SELECT description,tax_code FROM receipt_items WHERE receipt_id=? ORDER BY position", receipt_id) == [
        ("RUFFLES", "BF"), ("LITLE VEGET", "BF"), ("WATER FILTER", "T")]
    assert stored_lines(store, receipt_id) == [(1, "T", "7.75000", 1299, 101, json.dumps({"line_ids": ["line-11"]})),
                                               (2, "B", "7.75000", 4619, 173, json.dumps({"line_ids": ["line-12"]}))]
    record = ledger.record("receipt", receipt_id)
    assert record["tax_source"] == "tax_lines"
    assert [item["tax_code"] for item in record["items"]] == ["BF", "BF", "T"]
    assert [(line["position"], line["code"], line["rate_display"], line["taxable_minor"], line["amount_minor"], line["line_ids"])
            for line in record["tax_lines"]] == [(1, "T", "7.75%", 1299, 101, ["line-11"]), (2, "B", "7.75%", 4619, 173, ["line-12"])]
    assert record["tax_lines"][1]["display"] == {"taxable_minor": "46.19 USD", "amount_minor": "1.73 USD"}
    assert_ledger_healthy(store)


def test_publishing_the_same_reading_again_leaves_one_copy_and_a_new_reading_replaces_it(books):
    store, ledger, docs = books
    source = source_of(docs["r.png"], "extraction:r")
    receipt_id = ledger.publish_receipt(r_receipt(), source, "verified")["id"]
    before = stored_lines(store, receipt_id)
    assert ledger.publish_receipt(r_receipt(), source, "verified")["id"] == receipt_id
    assert stored_lines(store, receipt_id) == before
    assert rows(store, "SELECT count(*) FROM receipts") == [(1,)]
    # Extract again with a reading that finds no tax lines and a different code: the old ones go.
    items = r_items()
    items[2]["tax_code"] = "N"
    ledger.publish_receipt(receipt(items, 274, 6192, 5918, tax_source="printed"), source, "verified")
    assert stored_lines(store, receipt_id) == []
    assert rows(store, "SELECT tax_code FROM receipt_items WHERE receipt_id=? ORDER BY position", receipt_id) == [("BF",), ("BF",), ("N",)]
    assert rows(store, "SELECT tax_source FROM receipts WHERE id=?", receipt_id) == [("printed",)]
    assert ledger.record("receipt", receipt_id)["tax_lines"] == []


def test_codes_and_lines_survive_reopening_the_library(books, tmp_path):
    store, ledger, docs = books
    receipt_id = ledger.publish_receipt(r_receipt(), source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    first = ledger.record("receipt", receipt_id)
    store.close()
    reopened = Store(tmp_path / "managed")
    try:
        again = Ledger(reopened).record("receipt", receipt_id)
        assert (again["tax_source"], again["tax_lines"], [i["tax_code"] for i in again["items"]]) == \
            (first["tax_source"], first["tax_lines"], [i["tax_code"] for i in first["items"]])
        assert_ledger_healthy(reopened)
    finally:
        reopened.close()


def test_a_reviewed_record_is_not_rewritten_by_a_new_reading(books):
    store, ledger, docs = books
    source = source_of(docs["r.png"], "extraction:r")
    receipt_id = ledger.publish_receipt(r_receipt(), source, "verified")["id"]
    ledger.review("receipt", receipt_id, "verified")
    before = (stored_lines(store, receipt_id), rows(store, "SELECT tax_code FROM receipt_items WHERE receipt_id=? ORDER BY position", receipt_id),
              rows(store, "SELECT tax_source FROM receipts WHERE id=?", receipt_id))
    items = r_items(coded=False)
    result = ledger.publish_receipt(receipt(items, 274, 6192, 5918, tax_source="printed"), source, "verified")
    assert result["status"] == "kept_reviewed"
    assert (stored_lines(store, receipt_id), rows(store, "SELECT tax_code FROM receipt_items WHERE receipt_id=? ORDER BY position", receipt_id),
            rows(store, "SELECT tax_source FROM receipts WHERE id=?", receipt_id)) == before


def test_a_return_shows_its_tax_lines_with_the_receipts_sign(books):
    """Tax lines are stored as magnitudes; the receipt's own tax carries the sign (spec Errors)."""
    store, ledger, docs = books
    items = [{**i, "line_total_minor": -i["line_total_minor"]} for i in r_items()]
    receipt_id = ledger.publish_receipt(receipt(items, -274, -6192, -5918, tax_source="tax_lines", tax_lines=R_LINES),
                                        source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    assert stored_lines(store, receipt_id)[1][3:5] == (4619, 173)
    record = ledger.record("receipt", receipt_id)
    assert [(line["taxable_minor"], line["amount_minor"]) for line in record["tax_lines"]] == [(-1299, -101), (-4619, -173)]
    assert record["tax_lines"][1]["display"]["amount_minor"] == "-1.73 USD"


def test_an_unreadable_amount_and_an_unparseable_rate_do_not_break_the_record(books):
    store, ledger, docs = books
    lines = [tax_line("T", None, None, rate="abc"), tax_line("B", 173, 4619, rate="10.000", line="line-12")]
    receipt_id = ledger.publish_receipt(receipt(r_items(), 274, 6192, 5918, tax_source="tax_lines", tax_lines=lines),
                                        source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    first, second = ledger.record("receipt", receipt_id)["tax_lines"]
    assert (first["rate_text"], first["rate_display"], first["amount_minor"], first["taxable_minor"], first["display"]) == ("abc", None, None, None, {})
    assert (second["rate_display"], second["amount_minor"]) == ("10%", 173)


@pytest.mark.parametrize("printed, shown", [("7.75000", "7.75%"), ("10.000", "10%"), ("0.5", "0.5%"), ("7.75%", "7.75%"), ("abc", None),
                                           ("", None), (None, None), ("NaN", None), ("Infinity", None)])
def test_rate_display(printed, shown):
    assert rate_display(printed) == shown


def test_sc09_receipts_recorded_without_codes_keep_their_shares(books, tmp_path):
    """Receipts recorded the old way (no codes, no tax lines, no tax source) share tax by their stored flags before and after
    a full rebuild, a reconciliation run and a reopen (FR-13). R stays 429 / 4190 / 1573."""
    store, ledger, docs = books
    d_items = [item("HOT DOG", 150, True, "dining", line="line-2"), item("MATTRESS", 49999, True, "furniture & decor", line="line-3"),
               item("BANANAS", 8000, False, "groceries", line="line-4")]
    ids = {name: ledger.publish_receipt(record, source_of(docs[name], f"extraction:{name}"), "verified")["id"]
           for name, record in (("r.png", receipt(r_items(coded=False), 274, 6192, 5918)),
                                ("d.png", receipt(d_items, 4012, 62161, 58149)))}

    def snapshot(current):
        return (rows(current, "SELECT s.receipt_id,i.position,s.category,s.amount_minor FROM category_splits s "
                              "LEFT JOIN receipt_items i ON i.id=s.receipt_item_id ORDER BY s.receipt_id,s.id"),
                rows(current, "SELECT receipt_id,position,taxed FROM receipt_items ORDER BY receipt_id,position"))

    first = snapshot(store)
    assert [row for row in first[0] if row[0] == ids["r.png"]] == [(ids["r.png"], 1, "groceries", 429), (ids["r.png"], 2, "groceries", 4190),
                                                                   (ids["r.png"], 3, "household supplies", 1573)]
    assert [row[3] for row in first[0] if row[0] == ids["d.png"]] == [162, 53999, 8000]
    with store.connection() as db:
        ledger.refresh_splits(db)
    Reconciler(store).run()
    assert snapshot(store) == first
    store.close()
    reopened = Store(tmp_path / "managed")
    try:
        assert snapshot(reopened) == first
        for receipt_id in ids.values():
            record = Ledger(reopened).record("receipt", receipt_id)
            assert record["tax_source"] is None and record["tax_lines"] == [] and [i["tax_code"] for i in record["items"]] == [None] * len(record["items"])
        assert rows(reopened, "SELECT count(*) FROM receipt_tax_lines") == [(0,)]
        assert_ledger_healthy(reopened)
    finally:
        reopened.close()
