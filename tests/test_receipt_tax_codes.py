"""Receipt tax codes (specs/receipt-tax-codes): what a receipt keeps of the codes beside its prices and the per-code tax lines it
prints, and that receipts recorded without them keep their shares. Synthetic receipts only, published through Ledger paths."""

import json

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.finance.ledger import Ledger, rate_display
from home_manager.finance.reconcile import Reconciler
from home_manager.library.storage import Store
from test_correction_preview import app_client  # noqa: F401
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
