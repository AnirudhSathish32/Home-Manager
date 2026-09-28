"""Spending categories belong to receipt items: one Costco receipt can be dining, furniture & decor and groceries at once."""

from conftest import documents_by_name, inbox_scan
import pytest

from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance.item_categories import ItemCategorizer
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.splits import allocate, by_category
from home_manager.finance.tools import FinanceTools, PeriodInput, SpendingItemsInput, TransactionsInput
from home_manager.library.storage import Store

SEPTEMBER = PeriodInput(start="2026-09-01", end="2026-09-30")


def item(total, category, taxed=None, discount=None):
    return {"line_total_minor": total, "discount_minor": discount, "taxed": taxed, "category": category}


# The worked example in docs/receipts-and-statements.md: tax falls only on the taxed hot dog and mattress.
COSTCO = [item(150, "dining", True), item(49999, "furniture & decor", True), item(8000, "groceries", False)]


def test_tax_is_shared_only_across_taxed_items():
    rows = allocate(COSTCO, 58149, 4012, None, 62161, "groceries")
    assert by_category(rows) == {"dining": 162, "furniture & decor": 53999, "groceries": 8000}
    assert [amount for _, _, amount in rows] == [162, 53999, 8000]


def test_without_tax_flags_tax_is_shared_across_every_item():
    unflagged = [{**row, "taxed": None} for row in COSTCO]
    assert by_category(allocate(unflagged, 58149, 4012, None, 62161, None)) == {"dining": 160, "furniture & decor": 53449, "groceries": 8552}


def test_discounts_tips_and_charge_differences():
    # A coupon printed on the mattress comes off the mattress; the order-wide 10% comes off everything.
    assert by_category(allocate([item(10000, "furniture & decor", discount=-2000), item(2000, "groceries")], 10000, None, None, 9000, None)) == \
        {"furniture & decor": 7200, "groceries": 1800}
    # A printed tip is dining; so is a tip added to a restaurant charge after the receipt printed.
    assert by_category(allocate([item(2500, "dining")], 2500, 200, 400, 3100, "dining")) == {"dining": 3100}
    assert by_category(allocate([item(2500, "dining")], 2500, None, None, 3000, "dining")) == {"dining": 3000}
    # Any other difference is shared by amount; the shares always add up to the charge exactly.
    rows = allocate([item(100, "furniture & decor"), item(100, "groceries"), item(100, "health")], 300, None, None, 301, "furniture & decor")
    assert sum(amount for _, _, amount in rows) == 301
    # Items without a category, or without prices, fall back to the receipt's category.
    assert by_category(allocate([item(500, None), item(None, "dining")], None, None, None, 500, "furniture & decor")) == {"furniture & decor": 500, "dining": 0}


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"statement.pdf": b"synthetic statement", "costco.png": b"synthetic costco receipt", "cafe.png": b"synthetic cafe receipt"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def source_of(doc):
    key = "extraction:" + doc["relative_path"]
    return {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": key}


def costco_receipt(ledger, doc):
    items = [{"description": name, "product_code": None, "quantity": "1", "unit_price_minor": total, "line_total_minor": total, "discount_minor": None,
              "taxed": taxed, "category": category, "locator": {"line_ids": [f"line-{index}"]}}
             for index, (name, total, taxed, category) in enumerate([("HOT DOG COMBO", 150, True, "dining"), ("QUEEN MATTRESS", 49999, True, "furniture & decor"),
                                                                    ("KS EGGS 24CT", 8000, False, "groceries")], 2)]
    return ledger.publish_receipt({"merchant": "Costco", "purchase_date": "2026-09-10", "subtotal_minor": 58149, "tax_minor": 4012, "tip_minor": None,
                                   "total_minor": 62161, "currency": "USD", "issues": [], "items": items, "category": "groceries",
                                   "locator": {"line_ids": ["line-1"]}}, source_of(doc), "verified")["id"]


def statement(ledger, doc, rows):
    return ledger.publish_statement({"institution": "Fidelity", "statement_type": "credit_card", "last_four": "7314", "currency": "USD",
                                     "period_start": "2026-09-01", "period_end": "2026-09-30", "statement_balance_minor": 0, "summary": {},
                                     "issues": [], "locator": {"line_ids": ["line-1"]},
                                     "transactions": [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                       "locator": {"line_ids": [f"line-{index}"]}} for index, (day, text, amount) in enumerate(rows, 2)]},
                                    source_of(doc), "verified")["id"]


def categories(tools):
    return {row["category"]: row["spending"]["minor"] for row in tools.get_spending_by_category(SEPTEMBER)["categories"]}


def test_a_receipt_counts_by_item_category_and_its_charge_takes_over_the_split(books):
    store, ledger, docs = books
    tools, reconciler = FinanceTools(store), Reconciler(store)
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    assert categories(tools) == {"dining": 162, "furniture & decor": 53999, "groceries": 8000}
    items = tools.get_spending_items(SpendingItemsInput(start="2026-09-01", end="2026-09-30"))["items"]
    assert [(row["item"], row["category"], row["amount_minor"], row["status"]) for row in items] == [
        ("HOT DOG COMBO", "dining", 162, "receipt"), ("QUEEN MATTRESS", "furniture & decor", 53999, "receipt"), ("KS EGGS 24CT", "groceries", 8000, "receipt")]
    # The Receipts folder lists the receipt under each of its items' categories.
    store.library_action(docs["costco.png"]["id"], docs["costco.png"]["current_hash"], "move", "Receipts")
    assert {row["category"]: row["count"] for row in store.folders()["receipt_categories"] if row["count"]} == {"dining": 1, "furniture & decor": 1, "groceries": 1}
    assert [doc["id"] for doc in store.documents(folder="Receipts", category="furniture & decor")["items"]] == [docs["costco.png"]["id"]]

    # A rule for the merchant no longer overrides the receipt's items once the charge matches it.
    ledger.add_rule("COSTCO", "groceries")
    statement_id = statement(ledger, docs["statement.pdf"], [("2026-09-11", "COSTCO WHSE #1234", -62161), ("2026-09-20", "BOOKSHOP", -800)])
    reconciler.reconcile_statement(statement_id)
    assert categories(tools) == {"dining": 162, "furniture & decor": 53999, "groceries": 8000, "uncategorized": 800}
    items = tools.get_spending_items(SpendingItemsInput(start="2026-09-01", end="2026-09-30"))["items"]
    assert {(row["item"] or row["merchant"], row["status"]) for row in items} == {
        ("HOT DOG COMBO", "reconciled"), ("QUEEN MATTRESS", "reconciled"), ("KS EGGS 24CT", "reconciled"), ("BOOKSHOP", "statement")}
    assert [row["description_raw"] for row in tools.get_transactions(TransactionsInput(category="furniture & decor"))["transactions"]] == ["COSTCO WHSE #1234"]
    charge = next(row["transaction_id"] for row in items if row["item"] == "QUEEN MATTRESS")
    assert {row["category"]: row["amount_minor"] for row in ledger.record("transaction", charge)["splits"]} == {"dining": 162, "furniture & decor": 53999, "groceries": 8000}

    # Changing one item moves its share, and the choice is remembered for the same item from the same seller.
    ledger.set_item_category(receipt_id, 2, "housing")
    assert categories(tools) == {"dining": 162, "housing": 53999, "groceries": 8000, "uncategorized": 800}
    with store.connection() as db:
        assert Ledger.remembered_categories(db, "COSTCO") == {"QUEEN MATTRESS": "housing"}
    # A category the user sets on the charge itself covers all of it.
    ledger.set_category(charge, "Warehouse")
    assert categories(tools) == {"warehouse": 62161, "uncategorized": 800}
    # Rejecting the match hands the charge back to its own category and the receipt counts on its own again.
    ledger.set_category(charge, None)
    link = ledger.record("receipt", receipt_id)["links"][0]
    reconciler.review_link("receipt", link["id"], "rejected")
    assert categories(tools) == {"groceries": 62161 + 8000, "dining": 162, "housing": 53999, "uncategorized": 800}


def test_receipts_recorded_before_item_categories_are_categorised_once(books, local_model):
    store, ledger, docs = books
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    with store.connection() as db:  # As recorded before this change: items without categories.
        db.execute("UPDATE receipt_items SET category=NULL,category_source=NULL,taxed=NULL")
        ledger.refresh_splits(db)
    categorizer = ItemCategorizer(store)
    assert categorizer.pending() == [receipt_id]
    assert categories(FinanceTools(store)) == {"groceries": 62161}
    local_model["outputs"] = [{"description": "Bulk run", "category": "groceries", "recurrence": None, "item_categories": ["dining", "furniture & decor", "groceries"]}]
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    assert categorizer.run(config) == {"receipts": 1, "items": 3}
    assert categorizer.pending() == []
    # Without tax flags the tax is shared across every item.
    assert categories(FinanceTools(store)) == {"dining": 160, "furniture & decor": 53449, "groceries": 8552}
    assert '"HOT DOG COMBO"' in local_model["requests"][-1]["messages"][1]["content"]


def test_items_under_a_retired_category_are_re_sorted_once(books, local_model):
    store, ledger, docs = books
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    ledger.set_item_category(receipt_id, 1, "entertainment")  # A current category the user chose: kept.
    with store.connection() as db:  # As stored before the list changed, then marked by migration 034.
        db.execute("UPDATE receipt_items SET category='shopping',category_source='legacy' WHERE position IN (2,3)")
        db.execute("UPDATE receipts SET category='shopping' WHERE id=?", (receipt_id,))
        db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,created_at) "
                   "VALUES('receipt',?,'category','shopping','groceries','[]','2026-09-01T00:00:00+00:00')", (receipt_id,))
        ledger.refresh_splits(db, receipt_id)
    # Until re-sorted it still adds up, and the Library lists the retired folder; it is never offered as a choice.
    assert categories(FinanceTools(store))["shopping"] == 53999 + 8000
    store.library_action(docs["costco.png"]["id"], docs["costco.png"]["current_hash"], "move", "Receipts")
    assert [row for row in store.folders()["receipt_categories"] if row.get("legacy")] == [{"category": "shopping", "count": 1, "legacy": True}]
    with pytest.raises(ValueError, match="listed categories"):
        ledger.correct("receipt", receipt_id, {"category": "shopping"})
    categorizer = ItemCategorizer(store)
    assert categorizer.pending() == [receipt_id]
    local_model["outputs"] = [{"description": "Warehouse run", "category": "groceries", "recurrence": None,
                               "item_categories": ["dining", "furniture & decor", None]}]
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    assert categorizer.run(config) == {"receipts": 1, "items": 2}
    record = ledger.record("receipt", receipt_id)
    # The user's item is unchanged; the model sorts the others, and one it can't place becomes other.
    assert [(row["category"], row["category_source"]) for row in record["items"]] == [
        ("entertainment", "user"), ("furniture & decor", "model"), ("other", "model")]
    # The receipt's retired category is replaced, and the user's old choice by a recorded correction that re-extraction keeps.
    assert (record["category"], record["corrections"][-1]["value"], record["corrections"][-1]["previous"]) == ("groceries", "groceries", "shopping")
    costco_receipt(ledger, docs["costco.png"])
    assert ledger.record("receipt", receipt_id)["category"] == "groceries"
    assert categorizer.pending() == []


def test_migration_marks_items_under_the_retired_category_as_legacy():
    import sqlite3
    from home_manager.library.storage import MIGRATIONS
    db = sqlite3.connect(":memory:")
    for number, script in MIGRATIONS:
        if number == 34:  # Data recorded under the old list, just before the change.
            db.execute("INSERT INTO receipts(id,blob_hash,document_id,review_status,currency,created_at,updated_at) VALUES(1,'h',1,'verified','USD','t','t')")
            db.executemany("INSERT INTO receipt_items(receipt_id,position,description,category,category_source,review_status) VALUES(1,?,?,?,?,'verified')",
                           [(1, "MATTRESS", "shopping", "model"), (2, "HOT DOG", "dining", "user"), (3, "LAMP", "shopping", "user")])
            db.executemany("INSERT INTO item_category_memory VALUES(?,?,?,'t')", [("COSTCO", "LAMP", "shopping"), ("COSTCO", "HOT DOG", "dining")])
        db.executescript(script.read_text())
    assert db.execute("SELECT description,category,category_source FROM receipt_items ORDER BY position").fetchall() == [
        ("MATTRESS", "shopping", "legacy"), ("HOT DOG", "dining", "user"), ("LAMP", "shopping", "legacy")]
    assert db.execute("SELECT item_key FROM item_category_memory").fetchall() == [("HOT DOG",)]
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE receipt_items SET category_source='guess' WHERE position=1")


def test_the_whole_receipt_category_sets_items_the_user_has_not_chosen(books):
    store, ledger, docs = books
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    ledger.set_item_category(receipt_id, 1, "entertainment")
    record = ledger.correct("receipt", receipt_id, {"category": "furniture & decor"})
    assert [(row["category"], row["category_source"]) for row in record["items"]] == [("entertainment", "user"), ("furniture & decor", "receipt"), ("furniture & decor", "receipt")]
    assert {row["category"]: row["amount_minor"] for row in record["splits"]} == {"furniture & decor": 61999, "entertainment": 162}
    # Extracted again: the remembered item keeps the user's category; the others take the model's.
    costco_receipt(ledger, docs["costco.png"])
    items = ledger.record("receipt", receipt_id)["items"]
    assert [(row["category"], row["category_source"]) for row in items] == [("entertainment", "memory"), ("furniture & decor", "model"), ("groceries", "model")]
    with pytest.raises(ValueError, match="listed categories"):
        ledger.set_item_category(receipt_id, 1, "coffee")
