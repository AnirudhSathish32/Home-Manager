"""Receipt tax codes (specs/receipt-tax-codes): what a receipt keeps of the codes beside its prices and the per-code tax lines it
prints, and that receipts recorded without them keep their shares. Synthetic receipts only, published through Ledger paths."""

from contextlib import contextmanager
import json
from types import SimpleNamespace

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from document_forms_fixtures import MISSING, amount_on, cite, receipt_replies
from document_forms_fixtures import item as reply_item
from home_manager.documents.extraction import DETAILS_FAILED, EXTRACTION_VERSION, HEADER_MODELS, NEW_FIELDS, Item, food_stamp_meaning
from home_manager.finance.ledger import Ledger, rate_display
from home_manager.finance.reconcile import Reconciler
from home_manager.library.storage import Store
from receipt_item_fixtures import (
    D_LINES,
    D_SHARES,
    d_replies,
    legend_entry,
    one_tax_replies,
    r0_replies,
    r_one_tax_lines,
    r_tax_lines,
    tax_line_reply,
)
from receipt_item_fixtures import (
    R_LINES as R_PRINTED,
)
from test_correction_preview import app_client  # noqa: F401
from test_extraction import extract, transcribe
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


def r_derived_receipt(**more):
    """R0 as recording it stores it: the same codes and lines, with the taxed flags FR-11 derives from the tax lines (all three taxed)."""
    return receipt([{**entry, "taxed": True} for entry in r_items()], 274, 6192, 5918, tax_source="tax_lines", tax_lines=R_LINES, **more)


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"r.png": b"synthetic mart receipt", "d.png": b"synthetic costco receipt", "card.csv": b"date,amount\n", "euro.csv": b"date,amount\n"})
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


# The sharing rule through the ledger (specs/receipt-tax-codes FR-14 – FR-18, FR-26 – FR-28; the rule itself is tests/test_splits_by_code.py) --

R_SHARES = [445, 4347, 1400]  # The test contract's hand-worked shares for R0 (SC-01).


def shares_of(store, receipt_id, charge=None):
    """(shares per item in position order, every split row's amount) of the receipt itself, or of one matched charge."""
    where = "s.transaction_id IS NULL" if charge is None else f"s.transaction_id={int(charge)}"
    found = rows(store, f"SELECT i.position,s.amount_minor FROM category_splits s LEFT JOIN receipt_items i ON i.id=s.receipt_item_id "
                        f"WHERE s.receipt_id=? AND {where} ORDER BY i.position", receipt_id)
    return [amount for position, amount in found if position is not None], [amount for _, amount in found]


def test_the_record_shares_by_code_and_says_which_items_hold_which_lines_tax(books):
    store, ledger, docs = books
    receipt_id = ledger.publish_receipt(r_derived_receipt(), source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    assert shares_of(store, receipt_id)[0] == R_SHARES
    record = ledger.record("receipt", receipt_id)
    assert [entry["share_minor"] for entry in record["items"]] == R_SHARES
    assert (record["tax_lines_used"], record["tax_issues"], record["issues"]) == (True, [], [])
    assert [entry["table"]["tax_included"] for entry in record["items"]] == [True, True, True]
    assert [entry["table"].get("tax_note") for entry in record["items"]] == ["with B tax", "with B tax", "with T tax"]
    assert_ledger_healthy(store)


def test_a_record_that_falls_back_keeps_its_lines_and_reports_why_without_storing_it(books):
    store, ledger, docs = books
    # SC-04: the lines come to 2.74 but the receipt's tax is 2.84.
    items = [{**entry, "taxed": True} for entry in r_items()]  # The flags FR-11 derives from the lines.
    receipt_id = ledger.publish_receipt(receipt(items, 284, 6202, 5918, tax_source="tax_lines", tax_lines=R_LINES),
                                        source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    assert shares_of(store, receipt_id)[0] == [450, 4391, 1361]
    record = ledger.record("receipt", receipt_id)
    reason = "The tax lines (2.74 USD) don't add up to the tax (2.84 USD), so tax was shared across the taxed items."
    assert (record["tax_lines_used"], record["tax_issues"], record["issues"]) == (False, [reason], [reason])
    assert len(record["tax_lines"]) == 2
    assert [entry["table"]["tax_included"] for entry in record["items"]] == [True, True, True]
    assert all("tax_note" not in entry["table"] for entry in record["items"])
    assert rows(store, "SELECT validation_json FROM receipts WHERE id=?", receipt_id) == [("[]",)]  # Worked out on each read, never stored.
    assert ledger.record("receipt", receipt_id)["issues"] == [reason]  # Not added again by a second read.
    assert_ledger_healthy(store)


def test_an_item_with_two_codes_is_named_and_gets_no_tax_line(books):
    store, ledger, docs = books
    items = r_items()
    items[0]["tax_code"], items[0]["taxed"] = "BT", False  # BT belongs to no one line (FR-11).
    receipt_id = ledger.publish_receipt(receipt(items, 274, 6192, 5918, tax_source="tax_lines", tax_lines=R_LINES),
                                        source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    assert shares_of(store, receipt_id)[0] == [429, 4363, 1400]
    record = ledger.record("receipt", receipt_id)
    assert record["tax_issues"] == ["RUFFLES carries more than one tax line's code (B, T), so it got no share of either."]
    assert record["tax_lines_used"] is True
    assert [entry["table"].get("tax_note") for entry in record["items"]] == [None, "with B tax", "with T tax"]
    assert record["items"][0]["table"]["tax_included"] is False


def test_sc07_correcting_the_tax_falls_back_and_back(app_client):
    client, manager, docs = app_client
    store, ledger = manager.store, manager.ledger
    receipt_id = ledger.publish_receipt(r_derived_receipt(), source_of(docs["receipt.png"], "extraction:receipt"), "verified")["id"]
    assert shares_of(store, receipt_id) == (R_SHARES, [*R_SHARES])
    money = lambda: rows(store, "SELECT subtotal_minor,tax_minor,tip_minor,total_minor FROM receipts WHERE id=?", receipt_id)
    assert money() == [(5918, 274, None, 6192)]
    manager.correct_record("receipt", receipt_id, {"tax": "3.00"})  # Also runs the reconciler, which rebuilds every receipt's splits.
    assert money() == [(5918, 300, None, 6192)]  # FR-28: only the tax changed.
    assert shares_of(store, receipt_id) == ([449, 4384, 1359], [449, 4384, 1359])
    record = ledger.record("receipt", receipt_id)
    reason = "The tax lines (2.74 USD) don't add up to the tax (3.00 USD), so tax was shared across the taxed items."
    assert (record["tax_lines_used"], record["tax_issues"]) == (False, [reason]) and reason in record["issues"]
    assert len(record["tax_lines"]) == 2
    back = client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"tax": "2.74"}})
    assert back.status_code == 200, back.text
    assert money() == [(5918, 274, None, 6192)]
    assert shares_of(store, receipt_id)[0] == R_SHARES
    shown = client.get(f"/api/finance/records/receipt/{receipt_id}").json()
    assert (shown["tax_lines_used"], shown["tax_issues"], shown["issues"]) == (True, [], [])
    assert_ledger_healthy(store)


def test_correcting_the_tax_to_zero_falls_back_with_the_reason_and_back(app_client):
    client, manager, docs = app_client
    store, ledger = manager.store, manager.ledger
    receipt_id = ledger.publish_receipt(r_derived_receipt(), source_of(docs["receipt.png"], "extraction:receipt"), "verified")["id"]
    manager.correct_record("receipt", receipt_id, {"tax": "0.00"})
    assert rows(store, "SELECT tax_minor,total_minor FROM receipts WHERE id=?", receipt_id) in ([(0, 6192)], [(None, 6192)])
    # No tax to spread, so the 6192 - 5918 = 274 charge difference goes by amount: item x 274 / 5918 = 19.862, 193.995, 60.143 on
    # 429, 4190, 1299 -> 448.862, 4383.995, 1359.143; rounded down 448 + 4383 + 1359 = 6190, and the 2 cents left go to the largest
    # remainders (.995, .862): 449, 4384, 1359.
    assert shares_of(store, receipt_id) == ([449, 4384, 1359], [449, 4384, 1359])
    record = ledger.record("receipt", receipt_id)
    reason = "The tax lines (2.74 USD) don't add up to the tax (0.00 USD), so tax was shared across the taxed items."
    assert (record["tax_lines_used"], record["tax_issues"]) == (False, [reason]) and reason in record["issues"]
    assert len(record["tax_lines"]) == 2
    back = client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"tax": "2.74"}})
    assert back.status_code == 200, back.text
    assert shares_of(store, receipt_id)[0] == R_SHARES
    shown = client.get(f"/api/finance/records/receipt/{receipt_id}").json()
    assert (shown["tax_lines_used"], shown["tax_issues"], shown["issues"]) == (True, [], [])
    assert_ledger_healthy(store)


def test_sc10_charges_shares_and_currencies_stay_exact(books):
    store, ledger, docs = books
    receipt_id = ledger.publish_receipt(r_derived_receipt(), source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    # 1. A card charge of the full amount, matched by the reconciler: its split rows are the receipt's.
    from test_spending_splits import statement
    reconciler = Reconciler(store)
    statement_id = statement(ledger, docs["card.csv"], [("2026-10-21", "SYNTH MART #12", -6192)])
    reconciler.reconcile_statement(statement_id)
    charge = rows(store, "SELECT t.id FROM transactions t JOIN transaction_receipt_links l ON l.transaction_id=t.id WHERE l.receipt_id=? "
                         "AND l.review_status<>'rejected'", receipt_id)[0][0]
    by_item, every = shares_of(store, receipt_id, charge)
    assert by_item == R_SHARES and sum(every) == 6192 and all(isinstance(amount, int) for amount in every)
    # 2. Shared 50/50: this person's part is 3096 and each category is within a cent of half its share.
    with store.connection() as db:
        db.execute("INSERT INTO record_shares VALUES('receipt',?,3096,6192,'[]','key','now',NULL)", (receipt_id,))
        ledger.refresh_splits(db, receipt_id)
    for scope in (None, charge):
        by_item, every = shares_of(store, receipt_id, scope)
        assert sum(every) == 3096 and all(abs(2 * mine - theirs) <= 2 for mine, theirs in zip(by_item, R_SHARES))
    with store.connection() as db:
        db.execute("DELETE FROM record_shares WHERE record_type='receipt' AND record_id=?", (receipt_id,))
        ledger.refresh_splits(db, receipt_id)
    assert shares_of(store, receipt_id, charge)[0] == R_SHARES
    assert_ledger_healthy(store)
    # 3. A charge of 57.00 EUR for the same receipt: resized to the charge, each share within a cent of share x 5700 / 6192.
    account = ledger.create_account("Euro Bank", "checking", "EUR")
    with store.connection() as db:
        inserted, _ = ledger.insert_transactions(db, account, [{"posted_date": "2026-10-21", "description": "SYNTH MART PARIS", "amount_minor": -5700,
                                                                "currency": "EUR", "locator": {"rows": [1]}}], "import",
                                                 source_of(docs["euro.csv"], "import:euro"), review_status="verified")
        euro = inserted[0]["id"] if isinstance(inserted[0], dict) else inserted[0]
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   "VALUES(?,?,100,'test','verified','now','now')", (euro, receipt_id))
        ledger.refresh_splits(db, receipt_id)
    by_item, every = shares_of(store, receipt_id, euro)
    assert sum(every) == 5700 and all(abs(amount - mine * 5700 / 6192) <= 1 for amount, mine in zip(by_item, R_SHARES))
    assert shares_of(store, receipt_id, charge)[0] == R_SHARES  # The other charge is untouched.
    # (The health check isn't run here: a USD receipt linked to a EUR charge is a link the user has to choose, as the contract does by hand.)


def test_the_receipts_split_trace_names_the_tax_codes_only_when_they_set_the_shares(books):
    from home_manager.finance.traces import build_for
    store, ledger, docs = books
    by_code = ledger.publish_receipt(r_derived_receipt(), source_of(docs["r.png"], "extraction:r"), "verified")["id"]
    old = ledger.publish_receipt(receipt(r_items(coded=False), 274, 6192, 5918), source_of(docs["d.png"], "extraction:d"), "verified")["id"]
    trace = build_for(store, f"split.receipt?receipt_id={by_code}")
    assert "the tax shared by amount within each tax code" in trace["formula"]
    assert "within each tax code" not in build_for(store, f"split.receipt?receipt_id={old}")["formula"]


# Reading: the codes and tax lines a receipt prints, through the real extraction service (specs/receipt-tax-codes FR-08 – FR-12, FR-21 – FR-24, FR-29)

@contextmanager
def reading(tmp_path, local_model, lines, replies):
    """Transcribe lines and record them with replies keyed by schema name; yields (manager, (document, parse run), receipt id)."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        local_model["requests"].clear()
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        yield manager, (doc, parse_id), run["publication"]["id"]
    finally:
        manager.close()


def read_again(manager, again, local_model, replies):
    """Extract again from the same transcription with another stub; returns the run."""
    local_model["by_schema"] = replies
    return extract(manager, *again, force=True)


def stored(store, receipt_id):
    """The receipt's amounts (subtotal, tax, total), its items' (tax code, taxed flag) in position order, its tax source, and its tax lines."""
    return (rows(store, "SELECT subtotal_minor,tax_minor,total_minor FROM receipts WHERE id=?", receipt_id)[0],
            rows(store, "SELECT tax_code,taxed FROM receipt_items WHERE receipt_id=? ORDER BY position", receipt_id),
            rows(store, "SELECT tax_source FROM receipts WHERE id=?", receipt_id)[0][0],
            rows(store, "SELECT code,rate_text,taxable_minor,amount_minor FROM receipt_tax_lines WHERE receipt_id=? ORDER BY position", receipt_id))


def shown_lines(record):
    """What the record shows of its tax lines, without row ids and timestamps."""
    return [(line["position"], line["code"], line["rate_display"], line["taxable_minor"], line["amount_minor"], line["line_ids"], line["display"])
            for line in record["tax_lines"]]


def item_citations(store, receipt_id):
    """The line ids each item's evidence link names, in position order (C-cited)."""
    return [json.loads(locator)["line_ids"] for (locator,) in rows(
        store, "SELECT l.locator_json FROM financial_evidence_links l JOIN receipt_items i ON i.id=l.record_id WHERE l.record_type='receipt_item' "
               "AND i.receipt_id=? ORDER BY i.position", receipt_id)]


def test_sc01_records_codes_lines_and_shares_by_code(tmp_path, local_model):
    with reading(tmp_path, local_model, R_PRINTED, r0_replies()) as (manager, again, receipt_id):
        store = manager.store
        amounts, items, source, lines = stored(store, receipt_id)
        assert amounts == (5918, 274, 6192)  # P-check.
        assert items == [("BF", 1), ("BF", 1), ("T", 1)]  # The model answered false for both BF items (FR-11).
        assert (source, lines) == ("tax_lines", [("T", "7.75000", 1299, 101), ("B", "7.75000", 4619, 173)])
        # C-cited: R's T and B lines are lines 11 and 12 of the transcription; each item's link names the line it was read on.
        assert [json.loads(locator)["line_ids"] for (locator,) in rows(
            store, "SELECT locator_json FROM receipt_tax_lines WHERE receipt_id=? ORDER BY position", receipt_id)] == [["line-11"], ["line-12"]]
        assert item_citations(store, receipt_id) == [["line-4"], ["line-5", "line-6"], ["line-8"]]
        record = manager.ledger.record("receipt", receipt_id)
        assert [entry["tax_code"] for entry in record["items"]] == ["BF", "BF", "T"]
        assert [line["line_ids"] for line in record["tax_lines"]] == [["line-11"], ["line-12"]]
        assert shares_of(store, receipt_id) == (R_SHARES, [*R_SHARES]) and sum(R_SHARES) == 6192
        assert (record["tax_lines_used"], record["tax_issues"], record["issues"]) == (True, [], [])
        before = (items, source, lines, shares_of(store, receipt_id), shown_lines(record))
        # A second Record of the same document: no duplicate tax lines or split rows.
        run = read_again(manager, again, local_model, r0_replies())
        assert run["status"] == "succeeded" and run["publication"]["id"] == receipt_id
        assert rows(store, "SELECT count(*) FROM receipts") == [(1,)] and rows(store, "SELECT count(*) FROM receipt_tax_lines") == [(2,)]
        _, items, source, lines = stored(store, receipt_id)
        assert (items, source, lines, shares_of(store, receipt_id), shown_lines(manager.ledger.record("receipt", receipt_id))) == before
        assert_ledger_healthy(store)
    reopened = Store(tmp_path / "managed")  # Restart: the same library opened again.
    try:
        _, items, source, lines = stored(reopened, receipt_id)
        assert (items, source, lines, shares_of(reopened, receipt_id), shown_lines(Ledger(reopened).record("receipt", receipt_id))) == before
    finally:
        reopened.close()


def issues_of(manager, receipt_id):
    record = manager.ledger.record("receipt", receipt_id)
    return record["issues"], record["tax_issues"]


def test_sc03_one_tax_line_shares_as_today(tmp_path, local_model):
    with reading(tmp_path, local_model, D_LINES, d_replies()) as (manager, _again, receipt_id):
        amounts, items, source, lines = stored(manager.store, receipt_id)
        assert amounts == (58149, 4012, 62161)  # P-check.
        assert (items, source, lines) == ([(None, 1), (None, 1), (None, 0)], "printed", [])  # The model's own flags.
        assert shares_of(manager.store, receipt_id) == (D_SHARES, [*D_SHARES]) and sum(D_SHARES) == 62161
        assert issues_of(manager, receipt_id) == ([], [])


def test_sc04_tax_lines_that_do_not_add_up_fall_back(tmp_path, local_model):
    lines = [*R_PRINTED[:12], "TAX $2.84", "TOTAL $62.02"]
    with reading(tmp_path, local_model, lines, r0_replies(lines, tax=amount_on(lines, "TAX "))) as (manager, _again, receipt_id):
        amounts, items, source, tax_lines = stored(manager.store, receipt_id)
        assert amounts == (5918, 284, 6202)  # P-check.
        assert (items, source, len(tax_lines)) == ([("BF", 1), ("BF", 1), ("T", 1)], "tax_lines", 2)  # FR-27: the flags are FR-11's.
        # 284 over 5918: Ruffles 429 + 20.587, Little Veg 4190 + 201.075, Water filter 1299 + 62.338; rounded down 6201, the cent goes to Ruffles.
        assert shares_of(manager.store, receipt_id) == ([450, 4391, 1361], [450, 4391, 1361])
        issues, tax_issues = issues_of(manager, receipt_id)
        reason = "The tax lines (2.74 USD) don't add up to the tax (2.84 USD), so tax was shared across the taxed items."
        assert tax_issues == [reason] and reason in issues
        assert manager.ledger.record("receipt", receipt_id)["tax_lines_used"] is False


def test_sc05_a_tax_line_with_no_items_falls_back(tmp_path, local_model):
    lines = [line.replace("WATER FILTER T", "WATER FILTER") for line in R_PRINTED]  # The filter's line prints no code.
    with reading(tmp_path, local_model, lines, r0_replies(lines, codes=("BF", "BF", None))) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("BF", 1), ("BF", 1), (None, 0)], "tax_lines")  # The filter belongs to no line (FR-11).
        # 274 over 4619: Ruffles 429 + 25.448, Little Veg 4190 + 248.552, Water filter 1299; rounded down 6191, the cent goes to Little Veg.
        assert shares_of(manager.store, receipt_id) == ([454, 4439, 1299], [454, 4439, 1299])
        issues, tax_issues = issues_of(manager, receipt_id)
        assert tax_issues == ["The T tax line has no items carrying its code, so tax was shared across the taxed items."] and tax_issues[0] in issues


def test_sc06_an_item_carrying_two_tax_codes(tmp_path, local_model):
    lines = [line.replace("RUFFLES BF", "RUFFLES BT") for line in R_PRINTED]  # A code is read only where it is printed.
    with reading(tmp_path, local_model, lines, r0_replies(lines, codes=("BT", "BF", "T"))) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("BT", 0), ("BF", 1), ("T", 1)], "tax_lines")
        assert shares_of(manager.store, receipt_id) == ([429, 4363, 1400], [429, 4363, 1400])  # B's only item is Little Veg: 4190 + 173.
        issues, tax_issues = issues_of(manager, receipt_id)
        assert tax_issues == ["RUFFLES carries more than one tax line's code (B, T), so it got no share of either."] and tax_issues[0] in issues
        assert manager.ledger.record("receipt", receipt_id)["tax_lines_used"] is True


def r1_lines():
    """R as a second reading of the receipt sees it: the filter's code is printed N."""
    return [line.replace("WATER FILTER T", "WATER FILTER N") for line in R_PRINTED]


def r1_replies(lines):
    """R1: R0 with the filter coded N and untaxed, Ruffles and Little Veg taxed, no tax lines, and one tax of 2.74."""
    return r0_replies(lines, codes=("BF", "BF", "N"), taxed=(True, True, False), tax_lines=[])


def read_other_text(manager, local_model, lines):
    """A new transcription of the same document with other printed text; returns what to extract again from."""
    doc = manager.store.documents()["items"][0]
    local_model["output"] = {"full_text": "\n".join(lines)}
    manager.start_receipt(doc["id"], force=True)
    manager.future.result(timeout=30)
    return doc, manager.receipts.history(doc["id"])[0]["id"]


def test_sc08_extract_again_replaces_codes_and_lines_and_keeps_the_users_category(tmp_path, local_model):
    with reading(tmp_path, local_model, R_PRINTED, r0_replies()) as (manager, _again, receipt_id):
        store = manager.store
        filter_id = rows(store, "SELECT id FROM receipt_items WHERE receipt_id=? AND position=3", receipt_id)[0][0]
        manager.ledger.set_item_category(receipt_id, filter_id, "household supplies")
        lines = r1_lines()
        second = read_other_text(manager, local_model, lines)
        run = read_again(manager, second, local_model, r1_replies(lines))
        assert run["status"] == "succeeded" and run["publication"]["id"] == receipt_id
        amounts, items, source, tax_lines = stored(store, receipt_id)
        assert (amounts, items, source, tax_lines) == ((5918, 274, 6192), [("BF", 1), ("BF", 1), ("N", 0)], "printed", [])
        assert rows(store, "SELECT category,category_source FROM receipt_items WHERE id=?", filter_id) == [("household supplies", "user")]
        assert shares_of(store, receipt_id) == ([454, 4439, 1299], [454, 4439, 1299])  # 274 over 4619, as SC-05.
        assert manager.ledger.record("receipt", receipt_id)["tax_lines"] == []
        assert_ledger_healthy(store)


def test_sc08_b_a_reading_that_fails_leaves_the_codes_lines_and_shares(tmp_path, local_model):
    with reading(tmp_path, local_model, R_PRINTED, r0_replies()) as (manager, again, receipt_id):
        store = manager.store
        before = (stored(store, receipt_id), shares_of(store, receipt_id))
        broken = r0_replies()
        broken["GroceryItems"] = [{"items": [{**r0_replies()["GroceryItems"][0]["items"][0], "evidence": []}]}] * 2  # An item with no evidence, on both tries.
        run = read_again(manager, again, local_model, broken)
        assert run["status"] == "failed" and run["publication"] is None
        assert (stored(store, receipt_id), shares_of(store, receipt_id)) == before
        assert before[1] == (R_SHARES, R_SHARES)


def test_sc08_c_extracting_again_with_the_same_reading_leaves_two_tax_lines(tmp_path, local_model):
    with reading(tmp_path, local_model, R_PRINTED, r0_replies()) as (manager, again, receipt_id):
        for _ in range(2):
            assert read_again(manager, again, local_model, r0_replies())["status"] == "succeeded"
        assert rows(manager.store, "SELECT count(*) FROM receipt_tax_lines") == [(2,)]
        assert rows(manager.store, "SELECT count(*) FROM receipts") == [(1,)]
        assert shares_of(manager.store, receipt_id) == (R_SHARES, R_SHARES)


def test_sc13_tax_lines_without_codes_are_one_tax_total(tmp_path, local_model):
    lines = ["SYNTH SHOP", "2026-10-20", "LAMP 10.00", "CARDS 5.00", "SUBTOTAL 15.00", "STATE TAX 1.20", "LOCAL TAX 0.40", "TOTAL 16.60"]
    tax = {"value": "1.60", "status": "proposed", "evidence": cite(lines, "STATE TAX") + cite(lines, "LOCAL TAX")}
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": tax, "total": amount_on(lines, "TOTAL "),
               "tax_lines": [tax_line_reply(lines, "STATE TAX", None, "1.20"), tax_line_reply(lines, "LOCAL TAX", None, "0.40")]}
    items = [reply_item(lines, "LAMP", "LAMP 10.00", "10.00", taxed=True), reply_item(lines, "CARDS", "CARDS 5.00", "5.00", taxed=False)]
    replies = receipt_replies(lines, "general", "Synth Shop", "SYNTH SHOP", "2026-10-20", summary, items)
    with reading(tmp_path, local_model, lines, replies) as (manager, _again, receipt_id):
        amounts, stored_items, source, tax_lines = stored(manager.store, receipt_id)
        assert amounts == (1500, 160, 1660) and tax_lines == []  # P-check; nothing is kept for sharing by code.
        assert (stored_items, source) == ([(None, 1), (None, 0)], "printed")
        assert shares_of(manager.store, receipt_id) == ([1160, 500], [1160, 500])
        assert issues_of(manager, receipt_id) == ([], [])


SHOP = ["SYNTH SHOP", "2026-10-20", "MUG T 8.00", "BREAD N 3.00", "SUBTOTAL 11.00", "T = TAXABLE", "N = NON-TAXABLE", "TAX 0.62", "TOTAL 11.62"]


def shop_replies(lines, codes, taxed, legend):
    summary = {"subtotal": amount_on(lines, "SUBTOTAL"), "tax": amount_on(lines, "TAX "), "total": amount_on(lines, "TOTAL "), "tax_legend": legend}
    items = [reply_item(lines, "MUG", lines[2], "8.00", taxed=taxed[0], tax_code=codes[0]), reply_item(lines, "BREAD", lines[3], "3.00", taxed=taxed[1], tax_code=codes[1])]
    return receipt_replies(lines, "general", "Synth Shop", "SYNTH SHOP", "2026-10-20", summary, items)


def test_sc14_a_code_legend_sets_the_taxed_flags(tmp_path, local_model):
    legend = [legend_entry(SHOP, "T = TAXABLE", "T", True), legend_entry(SHOP, "N = NON-TAXABLE", "N", False)]
    with reading(tmp_path, local_model, SHOP, shop_replies(SHOP, ("T", "N"), (False, True), legend)) as (manager, _again, receipt_id):
        amounts, items, source, tax_lines = stored(manager.store, receipt_id)
        assert amounts == (1100, 62, 1162)  # P-check.
        assert (items, source, tax_lines) == ([("T", 1), ("N", 0)], "legend", [])  # Whatever the model answered.
        assert shares_of(manager.store, receipt_id) == ([862, 300], [862, 300])


def test_a_food_stamp_mark_is_not_in_the_legend_and_an_item_coded_tf_takes_ts_meaning(tmp_path, local_model):
    lines = [*SHOP[:5], "T = TAXABLE", "N = NON-TAXABLE", "F = FOOD STAMP", *SHOP[7:]]
    lines[2] = "MUG TF 8.00"
    legend = [legend_entry(lines, "T = TAXABLE", "T", True), legend_entry(lines, "N = NON-TAXABLE", "N", False)]
    with reading(tmp_path, local_model, lines, shop_replies(lines, ("TF", "N"), (False, True), legend)) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("TF", 1), ("N", 0)], "legend")
        assert shares_of(manager.store, receipt_id) == ([862, 300], [862, 300])
    # A food-stamp meaning that slips into the legend anyway is left out, so F never makes an item untaxed.
    again = [*legend, legend_entry(lines, "F = FOOD STAMP", "F", False)]
    with reading(tmp_path / "again", local_model, lines, shop_replies(lines, ("TF", "N"), (False, True), again)) as (manager, _again, receipt_id):
        assert stored(manager.store, receipt_id)[1] == [("TF", 1), ("N", 0)]


def test_sc14_a_legend_printed_on_one_line_keeps_t_and_n_and_drops_only_a_food_stamp_meaning(tmp_path, local_model):
    combined = "T = TAXABLE; N = NON-TAXABLE; F = FOOD STAMP"
    lines = [*SHOP[:5], combined, *SHOP[7:]]
    legend = [legend_entry(lines, combined, "T", True), legend_entry(lines, combined, "N", False)]
    with reading(tmp_path, local_model, lines, shop_replies(lines, ("T", "N"), (False, True), legend)) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("T", 1), ("N", 0)], "legend")  # The model's contradicting flags are replaced.
        assert shares_of(manager.store, receipt_id) == ([862, 300], [862, 300])
    # An F entry on that line is not used: an item coded F takes no meaning from it, while N still sets the bread's.
    again = [*legend, legend_entry(lines, combined, "F", False)]
    lines[2] = "MUG F 8.00"
    with reading(tmp_path / "again", local_model, lines, shop_replies(lines, ("F", "N"), (False, True), again)) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("F", None), ("N", 0)], "legend")


@pytest.mark.parametrize("quote, code, expected", [
    ("F = EBT: ELIGIBLE", "F", True),
    ("F = SNAP: ELIGIBLE", "F", True),
    ("F = FOOD STAMP: ELIGIBLE", "F", True),
    ("T = TAXABLE; N = NON-TAXABLE; F = EBT: ELIGIBLE", "F", True),
    ("T = TAXABLE; N = NON-TAXABLE; F = EBT: ELIGIBLE", "T", False),
    ("T = TAXABLE; N = NON-TAXABLE; F = EBT: ELIGIBLE", "N", False),
    ("T = TAXABLE; N = NON-TAXABLE; F = FOOD STAMP", "T", False),
    ("T = TAXABLE; N = NON-TAXABLE; F = FOOD STAMP", "N", False),
    ("T = TAXABLE; N = NON-TAXABLE; F = FOOD STAMP", "F", True),
    ("F: SNAP = YES", "F", True),
    ("T = TAXABLE SNAP = FOOD STAMP ITEM", "T", False),
    ("E = EXEMPT EBT = ELIGIBLE", "E", False),
])
def test_food_stamp_meaning_sees_a_food_stamp_word_before_a_colon_as_part_of_the_meaning(quote, code, expected):
    assert food_stamp_meaning(code, [SimpleNamespace(quote=quote)]) is expected


@pytest.mark.parametrize("printed", ["F = EBT: ELIGIBLE", "F = SNAP: ELIGIBLE"])
def test_sc14_a_food_stamp_word_with_a_colon_in_an_f_entry_does_not_hide_it(tmp_path, local_model, printed):
    lines = [*SHOP[:5], "T = TAXABLE", "N = NON-TAXABLE", printed, *SHOP[7:]]
    lines[2] = "MUG TF 8.00"
    # The model reads F as untaxed anyway; the guard drops that entry, so TF takes T's meaning and the legend still sets the flags.
    legend = [legend_entry(lines, "T = TAXABLE", "T", True), legend_entry(lines, "N = NON-TAXABLE", "N", False), legend_entry(lines, printed, "F", False)]
    with reading(tmp_path, local_model, lines, shop_replies(lines, ("TF", "N"), (False, True), legend)) as (manager, _again, receipt_id):
        amounts, items, source, _lines = stored(manager.store, receipt_id)
        assert amounts == (1100, 62, 1162)
        assert (items, source) == ([("TF", 1), ("N", 0)], "legend")
        assert shares_of(manager.store, receipt_id) == ([862, 300], [862, 300])


@pytest.mark.parametrize("rate, kept", [("7.75000", True), ("7.75", True), ("75", False), ("7.7", False)])
def test_a_tax_line_rate_is_kept_only_as_one_whole_printed_number(tmp_path, local_model, rate, kept):
    tax_lines = r_tax_lines()
    tax_lines[0]["rate"] = rate
    with reading(tmp_path, local_model, R_PRINTED, r0_replies(tax_lines=tax_lines)) as (manager, _again, receipt_id):
        _, _items, source, lines = stored(manager.store, receipt_id)
        assert source == "tax_lines" and lines[0][1] == (rate if kept else None)
        message = "Tax line 1 rate was not printed where it was cited and was left out."
        assert (message in issues_of(manager, receipt_id)[0]) is (not kept)


def test_sc15_two_lines_with_the_same_code_are_added(tmp_path, local_model):
    lines = [*R_PRINTED[:11], "B = GA STATE TAX 2.17000 on $46.19 $1.00", "B = LOCAL TAX 1.58000 on $46.19 $0.73", R_PRINTED[12]]
    tax_lines = [tax_line_reply(lines, "T = GA TAX", "T", "1.01", "12.99", "7.75000"),
                 tax_line_reply(lines, "B = GA STATE", "B", "1.00", "46.19", "2.17000"), tax_line_reply(lines, "B = LOCAL", "B", "0.73", "46.19", "1.58000")]
    tax = {"value": "2.74", "status": "proposed", "evidence": cite(lines, "T = GA TAX") + cite(lines, "B = GA STATE") + cite(lines, "B = LOCAL")}
    with reading(tmp_path, local_model, lines, r0_replies(lines, tax_lines=tax_lines, tax=tax)) as (manager, _again, receipt_id):
        _, items, source, stored_lines = stored(manager.store, receipt_id)
        assert source == "tax_lines" and len(stored_lines) == 3
        assert [(code, amount) for code, _rate, _taxable, amount in stored_lines] == [("T", 101), ("B", 100), ("B", 73)]
        assert items == [("BF", 1), ("BF", 1), ("T", 1)]
        assert shares_of(manager.store, receipt_id) == (R_SHARES, R_SHARES)
        assert issues_of(manager, receipt_id) == ([], [])
        record = manager.ledger.record("receipt", receipt_id)
        assert [line["line_ids"] for line in record["tax_lines"]] == [["line-11"], ["line-12"], ["line-13"]] and record["tax_lines_used"] is True


def test_sc16_food_stamp_marks_without_a_legend_leave_the_flags_empty(tmp_path, local_model):
    lines = r_one_tax_lines()
    with reading(tmp_path, local_model, lines, one_tax_replies(taxed=(None, None, None))) as (manager, _again, receipt_id):
        request = next(request for request in local_model["requests"] if request["response_format"]["json_schema"]["name"] == "GroceryItems")
        prompt = request["messages"][0]["content"]
        assert ("taxed: true or false only when the receipt says what the item's code means (a legend such as T = TAXABLE, or a tax line "
                "printed for its code); a food-stamp or EBT mark such as F or E never means untaxed on its own; otherwise null.") in prompt
        assert "tax_code: many receipts print a tax code beside each price" in prompt and "mark it untaxed or tax-exempt" not in prompt
        taxed = request["response_format"]["json_schema"]["schema"]["$defs"]["GroceryItem"]["properties"]["taxed"]["description"]
        assert "never means untaxed on its own" in taxed  # FR-24: the schema the model is given says the same.
        summary = next(request for request in local_model["requests"] if request["response_format"]["json_schema"]["name"] == "ReceiptGrocerySummary")
        assert {"tax_lines", "tax_legend"} <= set(summary["response_format"]["json_schema"]["schema"]["properties"])
        assert "never a single TAX line" in summary["messages"][0]["content"]
        amounts, items, source, tax_lines = stored(manager.store, receipt_id)
        assert amounts == (5918, 274, 6192)  # P-check.
        assert (items, source, tax_lines) == ([("BF", None), ("BF", None), ("T", None)], "printed", [])
        # 274 over 5918 (SC-07's arithmetic): 448.862, 4383.995, 1359.143; rounded down 6190, the two cents go to Little Veg and Ruffles.
        assert shares_of(manager.store, receipt_id) == ([449, 4384, 1359], [449, 4384, 1359])


def test_sc18_partly_answered_flags_share_tax_across_every_item(tmp_path, local_model):
    with reading(tmp_path, local_model, r_one_tax_lines(), one_tax_replies(taxed=(None, None, True))) as (manager, _again, receipt_id):
        _, items, source, tax_lines = stored(manager.store, receipt_id)
        assert (items, source, tax_lines) == ([("BF", None), ("BF", None), ("T", 1)], "printed", [])
        assert shares_of(manager.store, receipt_id) == ([449, 4384, 1359], [449, 4384, 1359])  # Not 429/4190/1573.


def test_sc18_variant_every_flag_answered_is_todays_rule(tmp_path, local_model):
    with reading(tmp_path, local_model, r_one_tax_lines(), one_tax_replies(taxed=(False, False, True))) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("BF", 0), ("BF", 0), ("T", 1)], "printed")
        assert shares_of(manager.store, receipt_id) == ([429, 4190, 1573], [429, 4190, 1573])


def test_a_code_that_is_not_printed_where_it_is_cited_is_left_out(tmp_path, local_model):
    lines = [line.replace("WATER FILTER T", "WATER FILTER") for line in R_PRINTED]  # No code beside the filter's price to read instead.
    with reading(tmp_path, local_model, lines, r0_replies(lines, codes=("BF", "BF", "N"))) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        # The N is not on the filter's line, so no code is kept (FR-08); the T line then names no item and the receipt falls back.
        assert items == [("BF", 1), ("BF", 1), (None, 0)] and source == "tax_lines"
        issues, tax_issues = issues_of(manager, receipt_id)
        assert "Item 3 tax code was not printed where it was cited and was left out." in issues
        assert tax_issues == ["The T tax line has no items carrying its code, so tax was shared across the taxed items."]
        assert shares_of(manager.store, receipt_id) == ([454, 4439, 1299], [454, 4439, 1299])


def test_a_code_the_model_got_wrong_is_read_beside_the_price(tmp_path, local_model):
    with reading(tmp_path, local_model, R_PRINTED, r0_replies(codes=("BF", "BF", "N"))) as (manager, _again, receipt_id):
        assert stored(manager.store, receipt_id)[1] == [("BF", 1), ("BF", 1), ("T", 1)]  # The filter's line prints T, not N.
        assert issues_of(manager, receipt_id) == ([], [])
        assert shares_of(manager.store, receipt_id) == (R_SHARES, [*R_SHARES])


def test_a_tax_line_amount_that_is_not_printed_is_kept_without_an_amount(tmp_path, local_model):
    tax_lines = r_tax_lines()
    tax_lines[1]["amount"] = "1.75"  # B prints 1.73.
    with reading(tmp_path, local_model, R_PRINTED, r0_replies(tax_lines=tax_lines)) as (manager, _again, receipt_id):
        _, items, source, lines = stored(manager.store, receipt_id)
        assert (items, source, lines[1]) == ([("BF", 1), ("BF", 1), ("T", 1)], "tax_lines", ("B", "7.75000", 4619, None))  # P7: still taxed.
        issues, tax_issues = issues_of(manager, receipt_id)
        assert "Tax line 2 amount was not printed where it was cited and was left out." in issues
        assert tax_issues == ["The B tax line's amount couldn't be read, so tax was shared across the taxed items."]
        assert shares_of(manager.store, receipt_id) == ([449, 4384, 1359], [449, 4384, 1359])


def test_a_tax_line_without_a_printed_code_means_one_tax_total(tmp_path, local_model):
    tax_lines = r_tax_lines()
    tax_lines[1]["code"] = "X"  # Not printed on the B line.
    with reading(tmp_path, local_model, R_PRINTED, r0_replies(tax_lines=tax_lines)) as (manager, _again, receipt_id):
        _, items, source, lines = stored(manager.store, receipt_id)
        assert (source, lines) == ("printed", []) and items == [("BF", 0), ("BF", 0), ("T", 1)]  # The model's own flags stay (FR-24).
        assert "Tax line 2 code was not printed where it was cited, so the tax lines were not used." in issues_of(manager, receipt_id)[0]
        assert shares_of(manager.store, receipt_id) == (R_SHARES_TODAY, R_SHARES_TODAY)


R_SHARES_TODAY = [429, 4190, 1573]  # R as recorded before tax codes: all the tax on the filter.


def test_new_fields_that_fail_leave_todays_reading_for_a_general_receipt(tmp_path, local_model):
    replies = d_replies()
    replies["ReceiptSummary"][0]["tax_lines"] = [{**tax_line_reply(D_LINES, "TAX ", "T", "40.12"), "evidence": []}]  # No evidence.
    replies["ReceiptSummary"] *= 2
    with reading(tmp_path, local_model, D_LINES, replies) as (manager, _again, receipt_id):
        assert [asked["response_format"]["json_schema"]["name"] for asked in local_model["requests"]].count("ReceiptSummary") == 2
        _, items, source, lines = stored(manager.store, receipt_id)
        assert (items, source, lines) == ([(None, 1), (None, 1), (None, 0)], "printed", [])
        assert DETAILS_FAILED in manager.ledger.record("receipt", receipt_id)["issues"]
        assert shares_of(manager.store, receipt_id) == (D_SHARES, D_SHARES)


def test_new_fields_that_fail_leave_todays_reading_for_a_grocery_receipt(tmp_path, local_model):
    replies = r0_replies()
    replies["ReceiptGrocerySummary"][0]["tax_lines"][0]["evidence"] = []
    replies["ReceiptGrocerySummary"] *= 2
    with reading(tmp_path, local_model, R_PRINTED, replies) as (manager, _again, receipt_id):
        amounts, items, source, lines = stored(manager.store, receipt_id)
        assert amounts == (5918, 274, 6192)
        assert (items, source, lines) == ([(None, 0), (None, 0), (None, 1)], "printed", [])  # The codes go with the other new fields.
        assert DETAILS_FAILED in manager.ledger.record("receipt", receipt_id)["issues"]
        assert shares_of(manager.store, receipt_id) == (R_SHARES_TODAY, R_SHARES_TODAY)


def test_every_receipt_form_and_row_schema_carries_the_new_fields_in_new_fields():
    assert {"tax_lines", "tax_legend"} <= set(NEW_FIELDS["ReceiptSummary"])
    assert all({"tax_lines", "tax_legend"} <= names for name, names in NEW_FIELDS.items() if name.startswith("Receipt") and name.endswith("Summary"))
    assert "tax_code" in NEW_FIELDS["Items"] and "tax_code" in NEW_FIELDS["GroceryItems"]
    old_answer = {"merchant": MISSING, "purchase_date": MISSING, "currency": MISSING, "subtotal": MISSING, "tax": MISSING, "tip": MISSING, "total": MISSING}
    assert HEADER_MODELS["receipt"].model_validate(old_answer).tax_lines == []  # An earlier stub or answer, with none of the new fields, still validates.
    assert Item.model_validate({"description": "X", "product_code": None, "quantity": None, "unit_price": None, "line_total": None, "discount": None,
                                "taxed": None, "evidence": [{"line_id": "line-1", "quote": "X"}]}).tax_code is None


def test_the_extraction_version_names_tax_codes_and_an_earlier_reading_is_read_again(tmp_path, local_model):
    assert EXTRACTION_VERSION != "typed-extraction-v32-table-engine"  # Bumped since (order discounts): a v32 reading is read again.
    with reading(tmp_path, local_model, R_PRINTED, r0_replies()) as (manager, again, receipt_id):
        doc, parse_id = again
        with manager.store.connection() as db:
            assert db.execute("SELECT prompt_version FROM extraction_runs").fetchone()[0] == EXTRACTION_VERSION
            db.execute("UPDATE extraction_runs SET prompt_version='typed-extraction-v32-table-engine'")
        local_model["by_schema"] = r0_replies()
        started = manager.start_extraction(doc["id"], parse_id)
        manager.future.result(timeout=30)
        assert started["reused"] is False and manager.extractions.get(started["run_id"])["status"] == "succeeded"


def test_a_code_the_model_missed_is_read_beside_the_price(tmp_path, local_model):
    # A model may answer no tax_code for items whose codes are printed: each is read beside its price instead.
    with reading(tmp_path, local_model, R_PRINTED, r0_replies(codes=(None, None, None))) as (manager, _again, receipt_id):
        _, items, source, _lines = stored(manager.store, receipt_id)
        assert (items, source) == ([("BF", 1), ("BF", 1), ("T", 1)], "tax_lines")
        assert shares_of(manager.store, receipt_id) == (R_SHARES, [*R_SHARES])
        assert issues_of(manager, receipt_id) == ([], [])


def test_a_unit_or_unknown_mark_beside_a_price_is_not_a_code():
    from home_manager.documents.extraction import code_beside_price
    lines = {"line-1": "BANANAS 2.31 LB 1.36", "line-2": "MILK 3.49 X", "line-3": "10 @ $4.19 ea", "line-4": "SOAP N $2.00"}
    cites = lambda *ids: [SimpleNamespace(line_id=line, quote=lines[line]) for line in ids]
    assert code_beside_price(cites("line-1"), lines, {"B"}) is None  # LB is a unit.
    assert code_beside_price(cites("line-2"), lines, {"X"}) == "X"
    assert code_beside_price(cites("line-4"), lines, {"T"}) is None  # N is no printed tax line's code.
    assert code_beside_price(cites("line-3"), lines, {"A"}) is None


def test_a_receipt_printing_only_its_tax_lines_has_their_sum_as_its_tax(tmp_path, local_model):
    from document_forms_fixtures import MISSING
    # R prints no TAX total, only its T and B lines: a model may leave the tax empty, and their sum is the receipt's tax.
    with reading(tmp_path, local_model, R_PRINTED, r0_replies(tax=MISSING)) as (manager, _again, receipt_id):
        amounts, items, source, lines = stored(manager.store, receipt_id)
        assert amounts == (5918, 274, 6192) and source == "tax_lines"
        assert [(code, amount) for code, _rate, _taxable, amount in lines] == [("T", 101), ("B", 173)]
        assert shares_of(manager.store, receipt_id) == (R_SHARES, [*R_SHARES])
        assert issues_of(manager, receipt_id) == ([], [])


def no_seller_replies(lines):
    """R0 answered as if its lines printed no seller: the merchant, the classifier's issuer and the identity question all missing."""
    from document_forms_fixtures import MISSING
    replies = r0_replies(lines)
    for schema in ("ReceiptGrocerySummary", "ReceiptIdentity"):
        replies[schema] = [{**reply, **({"merchant": MISSING} if "merchant" in reply else {}), **({"seller": MISSING} if "seller" in reply else {})}
                           for reply in replies[schema]]
    replies["Classification"] = [{**reply, "issuer": MISSING} for reply in replies["Classification"]]
    return replies


@pytest.mark.parametrize("file_name, merchant", [("walmart.com order.png", "Walmart"), ("IMG_1234.png", None)])
def test_a_receipt_naming_no_seller_takes_it_from_its_file_name(tmp_path, local_model, file_name, merchant):
    from test_extraction import transcribe
    lines = R_PRINTED  # Read as a snippet of an online order would be: the model finds no seller in its text.
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines, file_name=file_name)
    try:
        local_model["requests"].clear()
        local_model["by_schema"] = no_seller_replies(lines)
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        record = manager.ledger.record("receipt", run["publication"]["id"])
        assert record.get("merchant") == merchant
        reason = f"Merchant Walmart was taken from the file name “{file_name}”, not printed; confirm it with Edit details."
        assert (reason in record["issues"]) == (merchant is not None)
        assert record["review_status"] == "needs_review"
    finally:
        manager.close()


def test_a_file_name_names_a_seller_by_its_site_or_a_known_merchant():
    from home_manager.documents.extraction import file_seller
    known = ["Target", "The Home Depot", "Order Express"]
    assert file_seller("Screenshot 2026-10-20 walmart.com.png", known) == "Walmart"
    assert file_seller("www.homedepot.com.pdf", known) == "The Home Depot"  # The known merchant's own spelling.
    assert file_seller("best-buy.com.png", known) == "Best Buy"
    assert file_seller("target_receipt.jpg", known) == "Target"
    assert file_seller("Screenshot 2026-10-20 at 3.15.07 PM.png", known) is None
    assert file_seller("order receipt.pdf", known) is None  # Order is never a seller, and Order Express isn't spelled out.


def test_an_unreadable_mark_is_never_an_items_code(tmp_path, local_model):
    # The transcription writes [unreadable] for text it couldn't read; a model may copy it as an item's code.
    replies = r0_replies()
    items = replies["GroceryItems"][0]["items"]
    items[0] = {**items[0], "product_code": "[unreadable]"}
    with reading(tmp_path, local_model, R_PRINTED, replies) as (manager, _again, receipt_id):
        codes = rows(manager.store, "SELECT product_code FROM receipt_items WHERE receipt_id=? ORDER BY position", receipt_id)
        assert [code for (code,) in codes] == [None, "211180042", "07200120"]
