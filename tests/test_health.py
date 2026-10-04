"""Ledger health: a reconciled library breaks no rule, and each kind of damage is reported by its rule."""

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.ledger_check import main as check_ledger_cli
from home_manager.finance import tax_engine
from home_manager.finance.health import RULES, check_ledger, summary
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store


def source_of(doc):
    key = "extraction:" + doc["relative_path"]
    return {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": key}


def publish_receipt(ledger, doc, merchant, total, items):
    rows = [{"description": name, "product_code": None, "quantity": "1", "unit_price_minor": amount, "line_total_minor": amount, "discount_minor": None,
             "taxed": None, "category": category, "locator": {"line_ids": [f"line-{index}"]}} for index, (name, amount, category) in enumerate(items, 2)]
    return ledger.publish_receipt({"merchant": merchant, "purchase_date": "2026-09-10", "subtotal_minor": total, "tax_minor": None, "tip_minor": None,
                                   "total_minor": total, "currency": "USD", "issues": [], "items": rows, "category": "groceries",
                                   "locator": {"line_ids": ["line-1"]}}, source_of(doc), "verified")["id"]


@pytest.fixture
def books(tmp_path):
    """A card statement reconciled against an itemized receipt, plus an unmatched receipt and line."""
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"statement.pdf": b"synthetic statement", "market.png": b"synthetic market receipt", "cafe.png": b"synthetic cafe receipt"})
    docs, ledger = documents_by_name(store), Ledger(store)
    market = publish_receipt(ledger, docs["market.png"], "Corner Market", 5000, [("EGGS", 3000, "groceries"), ("SOAP", 2000, "household supplies")])
    cafe = publish_receipt(ledger, docs["cafe.png"], "Cafe One", 800, [("LATTE", 800, "dining")])
    statement = ledger.publish_statement({"institution": "Fidelity", "statement_type": "credit_card", "last_four": "7314", "currency": "USD",
                                          "period_start": "2026-09-01", "period_end": "2026-09-30", "statement_balance_minor": 0, "summary": {},
                                          "issues": [], "locator": {"line_ids": ["line-1"]},
                                          "transactions": [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                            "locator": {"line_ids": [f"line-{index}"]}}
                                                           for index, (day, text, amount) in enumerate([("2026-09-11", "CORNER MARKET", -5000),
                                                                                                        ("2026-09-20", "BOOKSHOP", -1200)], 2)]},
                                         source_of(docs["statement.pdf"]), "verified")["id"]
    Reconciler(store).reconcile_statement(statement)
    with store.connection() as db:
        charge, bookshop = [row[0] for row in db.execute("SELECT id FROM transactions ORDER BY posted_date")]
    try:
        yield store, {"market": market, "cafe": cafe, "statement": statement, "charge": charge, "bookshop": bookshop}
    finally:
        store.close()


def found(store):
    with store.connection() as db:
        return {(item.code, item.record_type, item.record_id) for item in check_ledger(db)}


def damage(store, sql, *args):
    with store.connection() as db:
        db.execute(sql, args)


def test_a_reconciled_library_breaks_no_rule(books):
    store, ids = books
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM transaction_receipt_links WHERE review_status<>'rejected'").fetchone()[0] == 1
        problems = check_ledger(db)
    assert problems == []
    assert summary(problems) == {"error": 0, "warning": 0, "info": 0, "by_rule": {}}


def test_category_shares_that_do_not_add_up(books):
    store, ids = books
    damage(store, "UPDATE category_splits SET amount_minor=amount_minor+1 WHERE id=(SELECT min(id) FROM category_splits WHERE receipt_id=? AND transaction_id IS NULL)",
           ids["market"])
    damage(store, "UPDATE category_splits SET amount_minor=amount_minor-1 WHERE id=(SELECT min(id) FROM category_splits WHERE transaction_id=?)", ids["charge"])
    assert {("split_receipt_sum", "receipt", ids["market"]), ("split_charge_sum", "transaction", ids["charge"])} <= found(store)


def test_missing_and_stale_category_shares(books):
    store, ids = books
    damage(store, "DELETE FROM category_splits WHERE receipt_id=?", ids["cafe"])
    assert ("split_missing", "receipt", ids["cafe"]) in found(store)
    damage(store, "DELETE FROM category_splits WHERE transaction_id=?", ids["charge"])
    assert ("split_missing", "transaction", ids["charge"]) in found(store)
    damage(store, "INSERT INTO category_splits(receipt_id,transaction_id,receipt_item_id,category,amount_minor) VALUES(?,?,NULL,'dining',1200)",
           ids["cafe"], ids["bookshop"])
    assert ("split_stale", "transaction", ids["bookshop"]) in found(store)


def test_matches_that_break_the_one_receipt_per_charge_rule(books):
    store, ids = books
    link = "INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) VALUES(?,?,0,'test',?,'t','t')"
    damage(store, link, ids["charge"], ids["cafe"], "verified")
    problems = found(store)
    assert ("link_multi_receipt", "transaction", ids["charge"]) in problems
    damage(store, "DELETE FROM transaction_receipt_links WHERE receipt_id=?", ids["cafe"])
    damage(store, link, ids["bookshop"], ids["market"], "verified")
    assert ("link_multi_charge", "receipt", ids["market"]) in found(store)


def test_matches_across_currencies_or_amounts(books):
    store, ids = books
    damage(store, "UPDATE transaction_receipt_links SET review_status='proposed' WHERE receipt_id=?", ids["market"])
    damage(store, "UPDATE receipts SET total_minor=4999 WHERE id=?", ids["market"])
    assert ("link_amount", "receipt", ids["market"]) in found(store)
    damage(store, "UPDATE receipts SET currency='EUR' WHERE id=?", ids["market"])
    assert ("link_currency", "receipt", ids["market"]) in found(store)


def test_a_matched_receipt_whose_charge_does_not_count(books):
    store, ids = books
    damage(store, "UPDATE statements SET reconciliation='awaiting' WHERE id=?", ids["statement"])
    assert ("receipt_uncounted", "receipt", ids["market"]) in found(store)


def test_unsupported_currency(books):
    store, ids = books
    damage(store, "UPDATE accounts SET currency='XYZ'")
    assert any(code == "currency_unknown" and table == "accounts" for code, table, _ in found(store))


def test_statement_balances_either_sign_convention(books):
    store, ids = books
    damage(store, "UPDATE statements SET opening_balance_minor=10000,closing_balance_minor=16200 WHERE id=?", ids["statement"])  # Card: owed grows.
    assert not any(code == "statement_balance" for code, _, _ in found(store))
    damage(store, "UPDATE statements SET closing_balance_minor=3800 WHERE id=?", ids["statement"])  # Bank-style: balance falls.
    assert not any(code == "statement_balance" for code, _, _ in found(store))
    damage(store, "UPDATE statements SET closing_balance_minor=16000 WHERE id=?", ids["statement"])  # A line is missing or misread.
    assert ("statement_balance", "statement", ids["statement"]) in found(store)


def test_a_share_recorded_against_another_total(books):
    store, ids = books
    damage(store, "INSERT INTO record_shares(record_type,record_id,share_minor,total_minor,family_record_key,created_at) VALUES('receipt',?,400,900,'k','t')",
           ids["cafe"])
    assert ("share_total", "receipt", ids["cafe"]) in found(store)


def test_rows_that_name_a_record_that_no_longer_exists(books):
    store, ids = books
    damage(store, "INSERT INTO record_shares(record_type,record_id,share_minor,total_minor,family_record_key,created_at) VALUES('receipt',9999,400,900,'k','t')")
    damage(store, "INSERT INTO reconciliation_issues(issue_type,record_type,record_id,detail_json,status,created_at,updated_at) "
                  "VALUES('ambiguous_refund','transaction',9999,'{}','open','t','t')")
    damage(store, "INSERT INTO review_events(record_type,record_id,previous_status,new_status,created_at) VALUES('warranty',9999,'proposed','verified','t')")
    problems = found(store)
    assert {code for code, table, _ in problems if code.startswith("orphan_")} == {"orphan_share", "orphan_reference"}
    assert not any(table == "review_events" for code, table, _ in problems)  # Other kinds of record are not checked.


def test_tax_lots_that_do_not_cover_sales_or_holdings(books):
    store, ids = books
    with store.connection() as db:
        account = db.execute("INSERT INTO investment_accounts(kind,name,currency,source,created_at,updated_at) VALUES('brokerage','Brokerage','USD','manual','t','t')").lastrowid
        holding = db.execute("INSERT INTO holdings(account_id,instrument_class,name,holding_key,created_at,updated_at) VALUES(?,'stock','Fund','fund','t','t')",
                             (account,)).lastrowid
        db.execute("INSERT INTO tax_lots(account_id,holding_id,acquired_date,quantity,cost_minor,created_at) VALUES(?,?,'2026-01-02','5',50000,'t')", (account, holding))
        sell = db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,quantity,review_status,created_at) "
                          "VALUES(?,?,'2026-03-02','sell',80000,'8','verified','t')", (account, holding)).lastrowid
        db.execute("INSERT INTO investment_valuations(account_id,holding_id,as_of,value_minor,quantity,source,review_status,created_at,updated_at) "
                   "VALUES(?,?,'2026-06-30',20000,'2','manual','verified','t','t')", (account, holding))
    problems = found(store)
    assert ("lots_uncovered", "investment_event", sell) in problems
    assert ("lots_vs_holding", "holding", holding) in problems  # No open lots, but the statement shows 2 shares.
    with store.connection() as db:
        assert {item.severity for item in check_ledger(db) if item.code.startswith("lots_")} == {"info"}


def test_every_rule_has_a_severity_and_a_plain_description():
    assert all(severity in ("error", "warning", "info") and detail.endswith(".") for severity, detail in RULES.values())


def test_the_report_endpoint_and_command(tmp_path, capsys):
    app = create_app(tmp_path / "control", "health-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        client.headers.update({"Authorization": "Bearer health-token"})
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        response = client.get("/api/finance/health")
        assert response.status_code == 200
        found = response.json()
        assert {key: found[key] for key in ("summary", "problems")} == {"summary": {"error": 0, "warning": 0, "info": 0, "by_rule": {}}, "problems": []}
        # Whether each tax engine can run here shows before tax season, by its slot's label only.
        assert [item["label"] for item in found["tax_engines"]] == [tax_engine.label_of(slot) for slot in tax_engine.ENGINES]
        assert all(item["label"] in item["note"] for item in found["tax_engines"])
        # The command reads the same library read-only while the app holds it open.
        assert check_ledger_cli(["--control-dir", str(tmp_path / "control")]) == 0
    printed = capsys.readouterr().out
    assert "0 error, 0 warning, 0 info" in printed and printed.startswith("Tax engines\n") and "Engine 1" in printed.split("\n\n")[0]


def test_the_command_reports_rules_by_record_id(books, capsys):
    store, ids = books
    damage(store, "UPDATE accounts SET currency='XYZ'")
    assert check_ledger_cli(["--library", str(store.root)]) == 1
    out = capsys.readouterr().out
    assert "[error] currency_unknown x1" in out and "accounts " in out
