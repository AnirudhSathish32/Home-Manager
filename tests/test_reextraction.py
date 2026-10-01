"""Reading a statement or receipt again keeps the lines it finds again, with everything attached to them
(db_audit_report.md, INT-3 and INT-4)."""

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.finance.ledger import Ledger
from home_manager.library.storage import Store, now
from test_spending_splits import costco_receipt, source_of

COFFEE, COSTCO = ("2026-09-03", "BLUE BOTTLE", -500), ("2026-09-10", "COSTCO", -62161)


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"statement.pdf": b"synthetic statement", "costco.png": b"synthetic costco receipt"})
    try:
        yield store, Ledger(store), documents_by_name(store)
    finally:
        store.close()


def read(ledger, doc, rows, status="verified"):
    """Publish one reading of the statement, as an extraction run does."""
    return ledger.publish_statement({"institution": "Fidelity", "statement_type": "credit_card", "last_four": "7314", "currency": "USD",
                                     "period_start": "2026-09-01", "period_end": "2026-09-30", "statement_balance_minor": 0, "summary": {},
                                     "issues": [], "locator": {"line_ids": ["line-1"]},
                                     "transactions": [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                       "locator": {"line_ids": [f"line-{index}"]}} for index, (day, text, amount) in enumerate(rows, 2)]},
                                    source_of(doc), status)


def lines(store):
    with store.connection() as db:
        return {row["description_raw"]: row["id"] for row in db.execute("SELECT id,description_raw FROM transactions")}


def tag(store, transaction_id):
    """A write-off the user chose for a statement line."""
    with store.connection() as db:
        db.execute("INSERT INTO tax_tags(transaction_id,kind,line,amount_minor,currency,tax_date,source,review_status,created_at,updated_at) "
                   "VALUES(?,'business_expense','supplies',500,'USD','2026-09-03','user','verified',?,?)", (transaction_id, now(), now()))


def count(store, query, *params):
    with store.connection() as db:
        return db.execute(query, params).fetchone()[0]


def test_a_line_read_again_keeps_its_id_its_tag_and_its_receipt_match(books):
    store, ledger, docs = books
    read(ledger, docs["statement.pdf"], [COFFEE, COSTCO])
    before = lines(store)
    tag(store, before["BLUE BOTTLE"])
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    with store.connection() as db:  # The reconciler's proposal; deleting the line used to fail on it.
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   "VALUES(?,?,90,'amount_date','proposed',?,?)", (before["COSTCO"], receipt_id, now(), now()))
    # A better reading of the same lines: same dates and amounts, clearer text.
    published = read(ledger, docs["statement.pdf"], [COFFEE, ("2026-09-10", "COSTCO WHSE #1067", -62161)])
    assert published["status"] == "published" and published["kept"] == 0
    after = lines(store)
    assert after == {"BLUE BOTTLE": before["BLUE BOTTLE"], "COSTCO WHSE #1067": before["COSTCO"]}
    assert count(store, "SELECT count(*) FROM tax_tags WHERE transaction_id=? AND source='user'", before["BLUE BOTTLE"]) == 1
    assert count(store, "SELECT count(*) FROM transaction_receipt_links WHERE transaction_id=?", before["COSTCO"]) == 1
    # Each line cites this reading once, not every reading so far.
    assert count(store, "SELECT count(*) FROM financial_evidence_links WHERE record_type='transaction' AND record_id=?", before["COSTCO"]) == 1
    assert_ledger_healthy(store)


def test_a_line_no_longer_read_goes_with_the_machines_rows_about_it(books):
    store, ledger, docs = books
    read(ledger, docs["statement.pdf"], [COFFEE, COSTCO])
    before = lines(store)
    receipt_id = costco_receipt(ledger, docs["costco.png"])
    with store.connection() as db:
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   "VALUES(?,?,90,'amount_date','proposed',?,?)", (before["COSTCO"], receipt_id, now(), now()))
        db.execute("INSERT INTO reconciliation_issues(issue_type,record_type,record_id,detail_json,status,created_at,updated_at) "
                   "VALUES('ambiguous_refund','transaction',?,'{}','open',?,?)", (before["COSTCO"], now(), now()))
    published = read(ledger, docs["statement.pdf"], [COFFEE])  # A misread line the new reading drops.
    assert published["kept"] == 0
    assert lines(store) == {"BLUE BOTTLE": before["BLUE BOTTLE"]}
    assert count(store, "SELECT count(*) FROM transaction_receipt_links") == 0
    assert count(store, "SELECT count(*) FROM reconciliation_issues WHERE record_type='transaction'") == 0
    assert count(store, "SELECT review_status FROM statements") == "verified"
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert_ledger_healthy(store)


def test_a_line_you_worked_on_stays_and_the_statement_waits_in_review(books):
    store, ledger, docs = books
    read(ledger, docs["statement.pdf"], [COFFEE, COSTCO])
    before = lines(store)
    tag(store, before["BLUE BOTTLE"])
    published = read(ledger, docs["statement.pdf"], [COSTCO])
    assert published["kept"] == 1
    assert lines(store) == before
    assert count(store, "SELECT count(*) FROM tax_tags WHERE transaction_id=?", before["BLUE BOTTLE"]) == 1
    with store.connection() as db:
        statement = db.execute("SELECT review_status,review_source,validation_json FROM statements").fetchone()
    assert (statement["review_status"], statement["review_source"]) == ("needs_review", None)
    assert "no longer finds 1 transaction you worked on" in statement["validation_json"]


# Receipts --------------------------------------------------------------------------------------------------

MILK, EGGS, BREAD, BANANAS = ("MILK 1GAL", 349), ("EGGS 12CT", 599), ("BREAD", 299), ("BANANAS", 129)


def read_receipt(ledger, doc, lines, status="verified"):
    items = [{"description": name, "product_code": None, "quantity": "1", "unit_price_minor": total, "line_total_minor": total, "discount_minor": None,
              "taxed": False, "category": "groceries", "locator": {"line_ids": [f"line-{index}"]}} for index, (name, total) in enumerate(lines, 2)]
    total = sum(amount for _, amount in lines)
    return ledger.publish_receipt({"merchant": "Safeway", "purchase_date": "2026-09-12", "subtotal_minor": total, "tax_minor": 0, "tip_minor": None,
                                   "total_minor": total, "currency": "USD", "issues": [], "items": items, "category": "groceries",
                                   "locator": {"line_ids": ["line-1"]}}, source_of(doc), status)


def items(store):
    with store.connection() as db:
        return {row["description"]: (row["id"], row["position"]) for row in db.execute("SELECT id,description,position FROM receipt_items")}


def worked_on(store, receipt_id, item_id, position):
    """The user identified the line, tagged it as a write-off and keeps it in the household."""
    with store.connection() as db:
        db.execute("INSERT INTO item_resolutions(receipt_item_id,name,category,consumable,confidence,method,review_status,created_at) "
                   "VALUES(?,'Milk','groceries',1,'high','user','verified',?)", (item_id, now()))
        db.execute("INSERT INTO tax_tags(receipt_item_id,kind,line,amount_minor,currency,tax_date,source,review_status,created_at,updated_at) "
                   "VALUES(?,'business_expense','supplies',349,'USD','2026-09-12','user','verified',?,?)", (item_id, now(), now()))
        product = db.execute("INSERT INTO products(name,normalized_name,category,consumable,created_at,updated_at) VALUES('Milk','MILK','groceries',1,?,?)",
                             (now(), now())).lastrowid
        db.execute("INSERT INTO inventory_lots(product_id,receipt_id,position,status,created_at,updated_at) VALUES(?,?,?,'in_stock',?,?)",
                   (product, receipt_id, position, now(), now()))


def test_an_item_read_again_keeps_its_identification_tag_lot_and_your_category(books):
    store, ledger, docs = books
    receipt_id = read_receipt(ledger, docs["costco.png"], [MILK, EGGS, BREAD])["id"]
    before = items(store)
    milk, eggs = before["MILK 1GAL"], before["EGGS 12CT"]
    worked_on(store, receipt_id, *milk)
    ledger.set_item_category(receipt_id, eggs[1], "dining")
    # A better reading finds a line the first one missed, above the others.
    published = read_receipt(ledger, docs["costco.png"], [BANANAS, MILK, EGGS, BREAD])
    assert published["status"] == "published" and published["kept"] == 0
    after = items(store)
    assert after["MILK 1GAL"] == (milk[0], 2) and after["EGGS 12CT"] == (eggs[0], 3) and after["BREAD"][0] == before["BREAD"][0]
    assert after["BANANAS"][1] == 1
    assert count(store, "SELECT count(*) FROM item_resolutions WHERE receipt_item_id=?", milk[0]) == 1
    assert count(store, "SELECT count(*) FROM tax_tags WHERE receipt_item_id=?", milk[0]) == 1
    assert count(store, "SELECT position FROM inventory_lots") == 2  # The lot moved with its line.
    with store.connection() as db:
        assert tuple(db.execute("SELECT category,category_source FROM receipt_items WHERE id=?", (eggs[0],)).fetchone()) == ("dining", "user")
        assert db.execute("SELECT count(*) FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=?", (milk[0],)).fetchone()[0] == 1
    assert_ledger_healthy(store)


def test_an_item_no_longer_read_is_removed_unless_you_worked_on_it(books):
    store, ledger, docs = books
    receipt_id = read_receipt(ledger, docs["costco.png"], [MILK, EGGS, BREAD])["id"]
    before = items(store)
    worked_on(store, receipt_id, *before["MILK 1GAL"])
    # This reading misses the milk (which the user worked on) and the bread (which they did not).
    published = read_receipt(ledger, docs["costco.png"], [EGGS])
    assert published["kept"] == 1
    after = items(store)
    assert after == {"EGGS 12CT": (before["EGGS 12CT"][0], 1), "MILK 1GAL": (before["MILK 1GAL"][0], 2)}
    assert count(store, "SELECT position FROM inventory_lots") == 2
    with store.connection() as db:
        receipt = db.execute("SELECT review_status,validation_json FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert receipt["review_status"] == "needs_review" and "no longer finds 1 item you worked on" in receipt["validation_json"]
