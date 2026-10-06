"""Return receipts (docs/money.md "Returns"): reading them, counting them, sharing them, and returned household items."""

from datetime import date

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.finance.ledger import CHARGE_SHARE, Ledger, charge_share, sale_label, says_return
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.splits import allocate, equal_shares, item_amount
from home_manager.finance.tools import FinanceTools, TransactionsInput, call_tool
from home_manager.household.items import ItemLedger, ResolutionFields
from home_manager.library.storage import Store
from test_extraction import MISSING, cite, extract, transcribe, value

SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}


# Reading ---------------------------------------------------------------------------------------------------------

RETURN = ["TARGET", "2026-09-19", "USD", "RETURN", "TOWEL SET 25.00", "Subtotal 25.00", "Tax 2.00", "REFUND TOTAL 27.00",
          "CREDIT TO VISA ****1234"]
EXCHANGE = ["TARGET", "2026-09-19", "USD", "RETURN LAMP -30.00", "MUG 10.00", "Subtotal 20.00", "Tax 1.60", "Total 21.60"]


def read(tmp_path, local_model, lines, summary, items, outputs_after=None):
    """Extract a synthetic receipt with the given model answers; returns (manager, run)."""
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    local_model["outputs"] = [
        {"document_type": "receipt", "evidence": cite(1, lines[0]), "issuer": value("Target", 1, lines[0]), "document_date": value("2026-09-19", 2)},
        summary, {"seller": value("Target", 1, lines[0]), "seller_basis": "printed", "location": MISSING}, {"items": items},
        {"description": None, "category": None, "recurrence": None, "item_categories": [None] * len(items)}, {"rewards": []},
        *(outputs_after or [])]
    return manager, doc, parse_id, extract(manager, doc, parse_id)


def summary_of(lines, subtotal, tax, total, marker=None):
    number = {text: index for index, text in enumerate(lines, 1)}
    return {"merchant": value("Target", 1, lines[0]), "purchase_date": value("2026-09-19", 2), "currency": value("USD", 3),
            "subtotal": value(subtotal[0], number[subtotal[1]], subtotal[1]), "tax": value(tax[0], number[tax[1]], tax[1]), "tip": MISSING,
            "total": value(total[0], number[total[1]], total[1]), "card_last_four": MISSING,
            "return_marker": value(marker[0], number[marker[1]], marker[1]) if marker else MISSING}


def item(lines, text, description, amount, returned):
    return {"description": description, "product_code": None, "quantity": "1", "unit_price": None, "line_total": amount, "discount": None,
            "taxed": None, "returned": returned, "evidence": cite(lines.index(text) + 1, text)}


def test_an_unsigned_refund_total_with_a_cited_marker_is_money_back(tmp_path, local_model):
    summary = summary_of(RETURN, ("25.00", "Subtotal 25.00"), ("2.00", "Tax 2.00"), ("27.00", "REFUND TOTAL 27.00"), ("REFUND TOTAL", "REFUND TOTAL 27.00"))
    manager, *_, run = read(tmp_path, local_model, RETURN, summary, [item(RETURN, "TOWEL SET 25.00", "TOWEL SET", "25.00", True)])
    try:
        assert run["status"] == "succeeded", run["error"]
        record = manager.ledger.record("receipt", run["publication"]["id"])
        # Every sign is decided in code; the arithmetic still checks, so it counts without review.
        assert (record["subtotal_minor"], record["tax_minor"], record["total_minor"]) == (-2500, -200, -2700)
        assert [line["line_total_minor"] for line in record["items"]] == [-2500]
        assert (record["review_status"], record["issues"], record["direction"], record["sale_label"]) == ("verified", [], "return", "Return")
        assert sum(row["amount_minor"] for row in record["splits"]) == -2700
    finally:
        manager.close()


def test_an_exchange_takes_the_sign_its_arithmetic_supports(tmp_path, local_model):
    summary = summary_of(EXCHANGE, ("20.00", "Subtotal 20.00"), ("1.60", "Tax 1.60"), ("21.60", "Total 21.60"))
    items = [item(EXCHANGE, "RETURN LAMP -30.00", "LAMP", "30.00", True), item(EXCHANGE, "MUG 10.00", "MUG", "10.00", False)]
    manager, *_, run = read(tmp_path, local_model, EXCHANGE, summary, items)
    try:
        record = manager.ledger.record("receipt", run["publication"]["id"])
        # The lamp back (30.00) less the mug (10.00): 20.00 and its tax are paid out, not charged.
        assert (record["subtotal_minor"], record["tax_minor"], record["total_minor"]) == (-2000, -160, -2160)
        assert [line["line_total_minor"] for line in record["items"]] == [-3000, 1000]
        assert (record["review_status"], record["sale_label"]) == ("verified", "Exchange")
    finally:
        manager.close()


def test_a_marker_that_is_not_a_refund_word_needs_review(tmp_path, local_model):
    lines = ["TARGET", "2026-09-19", "USD", "TOWEL SET 25.00", "Subtotal 25.00", "Tax 2.00", "Total 27.00", "Returns within 30 days"]
    summary = summary_of(lines, ("25.00", "Subtotal 25.00"), ("2.00", "Tax 2.00"), ("27.00", "Total 27.00"), ("Returns within 30 days", "Returns within 30 days"))
    manager, *_, run = read(tmp_path, local_model, lines, summary, [item(lines, "TOWEL SET 25.00", "TOWEL SET", "25.00", False)])
    try:
        record = manager.ledger.record("receipt", run["publication"]["id"])
        assert record["total_minor"] == 2700 and record["review_status"] == "needs_review"
        assert record["issues"][0].startswith("Sale or return:")
    finally:
        manager.close()


def test_a_refund_total_nothing_marked_needs_review_and_a_correction_makes_it_a_return(tmp_path, local_model):
    summary = summary_of(RETURN, ("25.00", "Subtotal 25.00"), ("2.00", "Tax 2.00"), ("27.00", "REFUND TOTAL 27.00"))
    sale = [item(RETURN, "TOWEL SET 25.00", "TOWEL SET", "25.00", False)]
    manager, doc, parse_id, run = read(tmp_path, local_model, RETURN, summary, sale)
    try:
        receipt_id = run["publication"]["id"]
        record = manager.ledger.record("receipt", receipt_id)
        assert record["total_minor"] == 2700 and record["review_status"] == "needs_review"
        assert record["issues"] == ["Sale or return: a total line says refund or return, so this may be a return; check the total's sign."]
        with pytest.raises(ValueError, match="sale or return"):
            manager.ledger.correct("receipt", receipt_id, {"direction": "refund"})
        record = manager.ledger.correct("receipt", receipt_id, {"direction": "return"})
        assert (record["total_minor"], record["subtotal_minor"], [line["line_total_minor"] for line in record["items"]]) == (-2700, -2500, [-2500])
        assert (record["issues"], record["review_status"], record["corrections"][-1]["previous"]) == ([], "verified", "sale")
        # A later reading prints the same unsigned amounts; the correction is applied again on top.
        local_model["outputs"] = [
            {"document_type": "receipt", "evidence": cite(1, "TARGET"), "issuer": value("Target", 1, "TARGET"), "document_date": value("2026-09-19", 2)},
            summary, {"seller": value("Target", 1, "TARGET"), "seller_basis": "printed", "location": MISSING}, {"items": sale},
            {"description": None, "category": None, "recurrence": None, "item_categories": [None]}, {"rewards": []}]
        extract(manager, doc, parse_id, force=True)
        record = manager.ledger.record("receipt", receipt_id)
        assert (record["total_minor"], [line["line_total_minor"] for line in record["items"]]) == (-2700, [-2500])
    finally:
        manager.close()


def test_return_words_and_signs_are_decided_in_code():
    assert [says_return(text) for text in ("REFUND TOTAL 27.00", "Merchandise credit", "CREDIT TO VISA", "Returns within 30 days",
                                           "Return policy: receipt required", "TOTAL 27.00")] == [True, True, True, False, False, False]
    assert [sale_label(total, lines) for total, lines in ((2500, [2500]), (-2500, [-2500]), (-2000, [-3000, 1000]), (-500, []))] == [
        None, "Return", "Exchange", "Return"]
    # A returned line's discount makes the refund smaller, as a bought line's makes the price smaller.
    assert (item_amount({"line_total_minor": -1000, "discount_minor": -200}), item_amount({"line_total_minor": 1000, "discount_minor": 200})) == (-800, 800)
    rows = allocate([{"line_total_minor": -2500, "category": "home"}, {"line_total_minor": -500, "category": "toys"}], -3000, -240, None, -3240, None)
    assert sum(amount for _, _, amount in rows) == -3240 and all(amount < 0 for _, _, amount in rows)
    assert equal_shares(-2599, 2) == [-1300, -1299]


# Counting --------------------------------------------------------------------------------------------------------

@pytest.fixture
def library(tmp_path):
    def make(name="managed"):
        store = Store(tmp_path / name)
        inbox_scan(store, {"export.csv": b"date,amount\n", "purchase.png": f"{name} purchase".encode(), "return.png": f"{name} return".encode()})
        return store, Ledger(store), documents_by_name(store)
    made = []
    yield lambda name="managed": made.append(make(name)) or made[-1]
    for store, *_ in made:
        store.close()


def publish(ledger, doc, total, day, status="verified", category=None, items=None, merchant="Target"):
    record = {"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None, "total_minor": total,
              "currency": "USD", "issues": [], "items": items or [], "category": category, "locator": {"line_ids": ["line-1"]}}
    source = {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:" + doc["relative_path"], "run_id": doc["relative_path"]}
    return ledger.publish_receipt(record, source, status)["id"]


def transactions(store, ledger, account, doc, rows):
    with store.connection() as db:
        inserted, _ = ledger.insert_transactions(db, account, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                                "locator": {"rows": [index]}} for index, (day, text, amount) in enumerate(rows, 1)],
                                                 "import", {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import", "run_id": "import"})
    return inserted


def usd(tools):
    [row] = call_tool(tools, "get_spending", SEPTEMBER)["by_currency"]
    return row


def test_a_return_receipt_counts_until_its_credit_posts_then_the_credit_counts_instead(library):
    store, ledger, docs = library()
    publish(ledger, docs["purchase.png"], 2700, "2026-09-02", category="home")
    publish(ledger, docs["return.png"], -2700, "2026-09-19", category="home")
    tools = FinanceTools(store)
    row = usd(tools)
    assert (row["spending"]["decimal"], row["refunds"]["decimal"], row["net_spending"]["decimal"]) == ("27.00", "27.00", "0.00")
    assert (row["refunds_from_receipts"]["decimal"], row["return_receipts"]) == ("27.00", 1)
    assert call_tool(tools, "get_refunds", {})["refund_evidence"][0]["settlement"] == "counted_from_receipt"
    # Home's category view nets the return against the purchase.
    assert {(c["category"], c["spending"]["decimal"]) for c in call_tool(tools, "get_spending_by_category", SEPTEMBER)["categories"]} == {("home", "0.00")}
    card = ledger.create_account("Visa", "credit_card", "USD", last_four="1234")
    transactions(store, ledger, card, docs["export.csv"], [("2026-09-02", "TARGET 0123", -2700), ("2026-09-20", "TARGET 0123", 2700)])
    Reconciler(store).run()
    row = usd(tools)
    # The card lines replace both receipts: still 27.00 out and 27.00 back, never twice.
    assert (row["spending"]["decimal"], row["refunds"]["decimal"], row["refunds_from_receipts"]["decimal"], row["receipts"]) == ("27.00", "27.00", "0.00", 0)
    assert call_tool(tools, "get_refunds", {})["refund_evidence"][0]["settlement"] == "posted_credit_found"
    # The credit takes the return receipt's category, so the category still nets to zero; so do top merchants.
    by_category = call_tool(tools, "get_spending_by_category", SEPTEMBER)
    assert {(c["category"], c["spending"]["decimal"]) for c in by_category["categories"]} == {("home", "0.00")}
    assert [m["spending"]["decimal"] for m in by_category["top_merchants"]] == ["0.00"]
    assert_ledger_healthy(store)


def test_a_refund_without_a_receipt_takes_the_category_of_the_purchase_it_refunds(library):
    store, ledger, docs = library()
    card = ledger.create_account("Visa", "credit_card", "USD", last_four="1234")
    purchase, credit = transactions(store, ledger, card, docs["export.csv"], [("2026-09-02", "BOOKSHOP 12", -4000), ("2026-09-12", "BOOKSHOP 12 REFUND", 1500)])
    ledger.set_category(purchase, "books")
    Reconciler(store).run()
    tools = FinanceTools(store)
    assert {(c["category"], c["spending"]["decimal"]) for c in call_tool(tools, "get_spending_by_category", SEPTEMBER)["categories"]} == {("books", "25.00")}
    ledger.set_budget("books", "USD", "100")
    [books] = call_tool(tools, "get_budgets", {"month": "2026-09", "as_of": "2026-09-30"})["budgets"]
    assert books["spent"]["decimal"] == "25.00"
    rows = tools.get_transactions(TransactionsInput(metric="categories", categories=["books"]))["transactions"]
    assert {row["id"] for row in rows} == {purchase, credit}  # The category's drilldown lists the refund too.


def test_charge_share_rounds_a_refund_the_same_way_in_python_and_sqlite(library):
    store, *_ = library()
    cases = [(2500, 1300, 2599), (-2500, -1300, -2599), (-2599, -1300, -2599), (-1, -1, -3), (1, 1, 3), (-7, -3, -10), (99999, 33333, 100000)]
    with store.connection() as db:
        # CHARGE_SHARE's expression, evaluated on one charge (t) and one share (x).
        expression = CHARGE_SHARE[CHARGE_SHARE.index("CASE"):CHARGE_SHARE.index(" FROM transaction_receipt_links")]
        for charged, share, total in cases:
            found = db.execute(f"SELECT {expression} FROM (SELECT ? AS amount_minor) t, (SELECT ? AS share_minor, ? AS total_minor) x",
                               (-charged, share, total)).fetchone()[0]
            assert found == charge_share(charged, share, total), (charged, share, total)


def shared(store, receipt_id, share, total):
    with store.connection() as db:
        db.execute("INSERT INTO record_shares VALUES('receipt',?,?,?,'[]','key',datetime('now'))", (receipt_id, share, total))
        Ledger(store).refresh_splits(db, receipt_id)


def test_a_shared_purchase_and_its_shared_return_net_to_zero_for_each_member(library):
    # The card holder paid 25.99 and got it back; the purchase and the return were each shared 13.00 / 12.99.
    holder, holder_ledger, holder_docs = library("holder")
    other, other_ledger, other_docs = library("other")
    for store, ledger, docs, part in ((holder, holder_ledger, holder_docs, 1300), (other, other_ledger, other_docs, 1299)):
        shared(store, publish(ledger, docs["purchase.png"], 2599, "2026-09-02", category="home"), part, 2599)
        shared(store, publish(ledger, docs["return.png"], -2599, "2026-09-19", category="home"), -part, -2599)
    card = holder_ledger.create_account("Visa", "credit_card", "USD", last_four="1234")
    transactions(holder, holder_ledger, card, holder_docs["export.csv"], [("2026-09-02", "TARGET 0123", -2599), ("2026-09-20", "TARGET 0123", 2599)])
    Reconciler(holder).run()
    Reconciler(other).run()
    for store, part in ((holder, "13.00"), (other, "12.99")):
        tools = FinanceTools(store)
        row = usd(tools)
        # Each member's refund is their part, whether it comes from the card's credit (holder) or the return receipt (other).
        assert (row["spending"]["decimal"], row["refunds"]["decimal"], row["net_spending"]["decimal"]) == (part, part, "0.00")
        assert {(c["category"], c["spending"]["decimal"]) for c in call_tool(tools, "get_spending_by_category", SEPTEMBER)["categories"]} == {("home", "0.00")}
        assert_ledger_healthy(store)
    with holder.connection() as db:
        assert db.execute("SELECT count(*) FROM transaction_receipt_links").fetchone()[0] == 2


def test_a_partly_refunded_shared_return_counts_this_members_fraction(library):
    store, ledger, docs = library()
    receipt_id = publish(ledger, docs["return.png"], -2599, "2026-09-19", category="home")
    shared(store, receipt_id, -1300, -2599)
    card = ledger.create_account("Visa", "credit_card", "USD", last_four="1234")
    [credit] = transactions(store, ledger, card, docs["export.csv"], [("2026-09-20", "TARGET 0123", 2500)])
    with store.connection() as db:  # The user matched the 25.00 credit (a restocking fee kept 0.99) to the return.
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   "VALUES(?,?,60,'user_choice','verified',datetime('now'),datetime('now'))", (credit, receipt_id))
        ledger.refresh_splits(db, receipt_id)
    assert usd(FinanceTools(store))["refunds"]["decimal"] == "12.50"  # 25.00 × 1300/2599, rounded half up.
    assert_ledger_healthy(store)


def test_a_shared_return_delivered_by_the_family_counts_this_members_part(library):
    import hashlib

    from home_manager.finance.family_routing import apply_delivery
    store, *_ = library()
    document = b"synthetic family return receipt"
    record = {"merchant": "Target", "purchase_date": "2026-09-19", "subtotal_minor": None, "tax_minor": None, "tip_minor": None, "total_minor": -2599,
              "currency": "USD", "issues": [], "items": [], "category": "home", "locator": {"family": True}}
    delivery = {"key": "a" * 32, "action": "record", "record_type": "receipt", "record": record, "blob_hash": hashlib.sha256(document).hexdigest(),
                "name": "Target return", "share": equal_shares(-2599, 2)[1], "people": ["Mom", "Dad"]}
    receipt_id = apply_delivery(store, delivery, document)["record"][1]
    row = usd(FinanceTools(store))
    assert (row["spending"]["decimal"], row["refunds"]["decimal"], row["return_receipts"]) == ("0.00", "12.99", 1)
    assert Ledger(store).record("receipt", receipt_id)["sale_label"] == "Return"
    assert_ledger_healthy(store)


def test_a_family_correction_can_make_a_receipt_a_return(library):
    from home_manager.finance.family_corrections import checked_value, current_text
    store, ledger, docs = library()
    receipt_id = publish(ledger, docs["return.png"], 2700, "2026-09-19")
    with store.connection() as db:
        assert current_text(db, "receipt", receipt_id, "direction") == "sale"
        assert checked_value(db, "receipt", receipt_id, "direction", "return") == "return"
        with pytest.raises(ValueError, match="sale or return"):
            checked_value(db, "receipt", receipt_id, "direction", "out")


# Household -------------------------------------------------------------------------------------------------------

TOWELS = ResolutionFields(name="Bath Towel Set", category="other", consumable=False)


def test_a_returned_line_closes_its_lot_after_the_user_confirms_and_undo_reopens_it(library):
    store, ledger, docs = library()
    items = ItemLedger(store)
    line = {"description": "TOWEL SET", "product_code": "0123", "quantity": "1", "unit_price_minor": 2500, "discount_minor": None, "locator": {"line_ids": ["line-1"]}}
    bought = publish(ledger, docs["purchase.png"], 2500, "2026-09-02", items=[{**line, "line_total_minor": 2500}])
    [bought_line] = [row["id"] for row in items.lines(bought)]
    items.review(items.propose(bought_line, TOWELS, "search", "high")["id"], "verified", today=date(2026, 9, 2))
    [lot] = items.inventory(today=date(2026, 9, 10))
    returned = publish(ledger, docs["return.png"], -2500, "2026-09-19", items=[{**line, "line_total_minor": -2500}])
    [returned_line] = [row["id"] for row in items.lines(returned)]
    # Identifying a returned line never puts it in stock.
    items.review(items.propose(returned_line, TOWELS, "search", "high")["id"], "verified", today=date(2026, 9, 19))
    assert [row["id"] for row in items.inventory(today=date(2026, 9, 20))] == [lot["id"]]
    Reconciler(store).run()
    [proposal] = items.return_proposals()
    assert (proposal["receipt_item_id"], [row["id"] for row in proposal["lots"]], proposal["returned_on"]) == (returned_line, [lot["id"]], "2026-09-19")
    with pytest.raises(ValueError, match="listed"):
        items.review_return(returned_line, 9999)
    items.review_return(returned_line, lot["id"], today=date(2026, 9, 20))
    closed = items.lot(lot["id"])
    assert (closed["status"], closed["closed_on"]) == ("returned", "2026-09-19")
    assert items.inventory(today=date(2026, 9, 20)) == [] and items.return_proposals() == []
    assert items.lot_history(lot["id"])[-1]["event"] == "returned"
    with pytest.raises(ValueError, match="already answered"):
        items.review_return(returned_line, None)
    items.undo_lot(lot["id"])
    assert items.lot(lot["id"])["status"] == "in_stock"
    Reconciler(store).run()
    assert items.return_proposals() == []  # Answered once; never asked again.


def test_a_returned_line_with_no_matching_lot_is_not_asked_about(library):
    store, ledger, docs = library()
    items = ItemLedger(store)
    publish(ledger, docs["return.png"], -2500, "2026-09-19", items=[{"description": "LAMP", "product_code": None, "quantity": "1", "unit_price_minor": 2500,
                                                                     "line_total_minor": -2500, "discount_minor": None, "locator": {"line_ids": ["line-1"]}}])
    Reconciler(store).run()
    assert items.return_proposals() == []
