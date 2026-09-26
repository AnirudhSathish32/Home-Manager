"""Phases 7-8: deterministic reconciliation and financial tools over the canonical ledger."""

from conftest import documents_by_name, inbox_scan
from fastapi.testclient import TestClient
import pytest

from home_manager.api import create_app
from home_manager.finance import Ledger
from home_manager.finance_tools import AsOfInput, FinanceTools, TransactionsInput, call_tool
from home_manager.reconcile import Reconciler
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n", "receipt.png": b"synthetic receipt bytes",
                       "return.png": b"synthetic return receipt", "bill.png": b"synthetic bill"})
    docs = documents_by_name(store)
    ledger = Ledger(store)
    try:
        yield store, ledger, docs
    finally:
        store.close()


def source_of(doc, key):
    return {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": key}


def add(store, ledger, account, doc, rows, origin="import", status="proposed"):
    with store.connection() as db:
        inserted, _ = ledger.insert_transactions(db, account, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                                "locator": {"rows": [index]}} for index, (day, text, amount) in enumerate(rows, 1)],
                                                 origin, source_of(doc, f"{origin}:{account['id']}"), review_status=status)
    return inserted


def receipt(ledger, doc, merchant, day, total):
    return ledger.publish_receipt({"merchant": merchant, "purchase_date": day, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                   "total_minor": total, "currency": "USD", "issues": [], "items": [], "locator": {"line_ids": ["line-1"]}},
                                  source_of(doc, "extraction:" + doc["relative_path"]), "proposed")["id"]


def test_reconciliation_links_receipts_transfers_refunds_and_detects_recurring(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD", last_four="4821")
    card = ledger.create_account("Fidelity", "credit_card", "USD", last_four="7314")
    bank_ids = add(store, ledger, checking, docs["export.csv"], [
        ("2026-09-01", "PAYROLL ACME", 300000), ("2026-09-20", "ONLINE PAYMENT TO CREDIT CARD 7314", -50000),
        ("2026-09-25", "ACH DEBIT FIDELITY", -25000), ("2026-06-05", "NETFLIX.COM 866-579", -1549), ("2026-07-05", "NETFLIX.COM 866-579", -1549),
        ("2026-08-05", "NETFLIX.COM 866-579", -1549), ("2026-09-05", "NETFLIX.COM 866-579", -1549)])
    card_ids = add(store, ledger, card, docs["export.csv"], [
        ("2026-09-15", "COSTCO WHSE #1234 SEATTLE WA", -16382), ("2026-09-21", "PAYMENT - THANK YOU", 50000),
        ("2026-09-26", "ONLINE CREDIT", 25000), ("2026-09-02", "AMAZON MKTPLACE", -5999), ("2026-09-10", "AMAZON MKTPLACE", 5999),
        ("2026-09-18", "CAFE ONE", -1200), ("2026-09-18", "BOOKSHOP TWO", -1200), ("2026-09-19", "TARGET STORE", 2599)])
    costco = receipt(ledger, docs["receipt.png"], "Costco Wholesale", "2026-09-15", 16382)
    ambiguous = receipt(ledger, docs["bill.png"], "Corner Market", "2026-09-18", 1200)
    target_return = receipt(ledger, docs["return.png"], "Target", "2026-09-19", -2599)
    summary = Reconciler(store).run()
    assert summary == {"receipt_links": 2, "transfers": 2, "refunds": 1, "recurring": 1, "open_issues": 1}
    with store.connection() as db:
        links = [dict(row) for row in db.execute("SELECT * FROM transaction_receipt_links ORDER BY receipt_id")]
        transfer_links = {(row[0], row[1]) for row in db.execute("SELECT from_transaction_id,to_transaction_id FROM transaction_links WHERE link_type='transfer'")}
        types = dict(db.execute("SELECT id,transaction_type FROM transactions"))
        issue = db.execute("SELECT issue_type,record_id,detail_json FROM reconciliation_issues").fetchone()
        merchant = db.execute("SELECT m.canonical_name FROM transactions t JOIN merchants m ON m.id=t.merchant_id WHERE t.id=?", (card_ids[0],)).fetchone()[0]
    assert [(link["receipt_id"], link["transaction_id"], link["match_score"], link["match_method"]) for link in links] == [
        (costco, card_ids[0], 100, "amount+same_day+merchant"), (target_return, card_ids[7], 100, "amount+same_day+merchant")]
    assert merchant == "Costco Wholesale"
    # Two same-amount, same-day charges with no merchant evidence: an issue, never a guessed link.
    assert issue[0] == "ambiguous_receipt_match" and issue[1] == ambiguous and str(card_ids[5]) in issue[2] and str(card_ids[6]) in issue[2]
    assert transfer_links == {(bank_ids[1], card_ids[1]), (bank_ids[2], card_ids[2])}
    assert types[card_ids[2]] == "payment" and types[bank_ids[2]] == "payment"  # No keywords, but money arrived on a card.
    tools = FinanceTools(store)
    obligations = tools.get_recurring_obligations()["obligations"]
    assert [(row["merchant"], row["frequency"], row["expected_amount"]["display"], row["next_due_date"]) for row in obligations] == [
        ("NETFLIX COM", "monthly", "15.49 USD", "2026-10-05")]
    refunds = tools.get_refunds()
    assert [(row["description_raw"], row["purchase_id"]) for row in refunds["posted_credits"]] == [("TARGET STORE", None), ("AMAZON MKTPLACE", card_ids[3])]
    assert refunds["refund_evidence"][0]["settlement"] == "posted_credit_found"
    # Rejected links are never proposed again; rejecting a transfer restores the rows' own types.
    reconciler = Reconciler(store)
    with store.connection() as db:
        costco_link = db.execute("SELECT id FROM transaction_receipt_links WHERE receipt_id=?", (costco,)).fetchone()[0]
        transfer = db.execute("SELECT id FROM transaction_links WHERE from_transaction_id=?", (bank_ids[2],)).fetchone()[0]
    reconciler.review_link("receipt", costco_link, "rejected")
    reconciler.review_link("transfer", transfer, "rejected")
    assert reconciler.run()["receipt_links"] == 0
    with store.connection() as db:
        assert db.execute("SELECT merchant_id FROM transactions WHERE id=?", (card_ids[0],)).fetchone()[0] is None
        assert db.execute("SELECT transaction_type FROM transactions WHERE id=?", (card_ids[2],)).fetchone()[0] == "refund"


def test_refund_evidence_without_posted_credit_is_not_settled(books):
    store, ledger, docs = books
    receipt(ledger, docs["return.png"], "Target", "2026-09-19", -2599)
    Reconciler(store).run()
    evidence = FinanceTools(store).get_refunds()["refund_evidence"]
    assert [(row["settlement"], row["amount"]["display"]) for row in evidence] == [("evidence_only_not_settled", "25.99 USD")]


def test_spending_tools_are_exact_exclude_transfers_and_pending_model_rows(books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    card = ledger.create_account("Fidelity", "credit_card", "USD", last_four="7314")
    add(store, ledger, checking, docs["export.csv"], [("2026-08-03", "GROCERY MART", -10010), ("2026-08-20", "ONLINE PAYMENT TO CREDIT CARD", -30000),
                                                        ("2026-09-03", "GROCERY MART", -12012), ("2026-09-15", "PAYROLL", 250000)])
    add(store, ledger, card, docs["export.csv"], [("2026-08-21", "PAYMENT THANK YOU", 30000), ("2026-09-07", "BOOKS", -3333),
                                                    ("2026-09-08", "BOOKS REFUND", 1111)])
    statement = ledger.publish_statement({"statement_type": "credit_card", "institution": "Fidelity", "last_four": "7314", "currency": "USD",
                                          "period_start": "2026-09-01", "period_end": "2026-09-30", "statement_balance_minor": 50000, "summary": {},
                                          "issues": [], "locator": {"line_ids": ["page-1-line-1"]},
                                          "transactions": [{"posted_date": "2026-09-12", "description": "HARDWARE STORE", "amount_minor": -4444,
                                                            "currency": "USD", "locator": {"line_ids": ["page-1-line-9"]}}]},
                                         source_of(docs["bill.png"], "extraction:statement"), "proposed")
    Reconciler(store).run()
    tools = FinanceTools(store)
    september = call_tool(tools, "get_spending", {"start": "2026-09-01", "end": "2026-09-30"})
    [usd] = september["by_currency"]
    # 120.12 + 33.33 spent, 11.11 refunded; the unverified model-extracted 44.44 is pending, not counted.
    assert (usd["spending"]["decimal"], usd["refunds"]["decimal"], usd["net_spending"]["decimal"]) == ("153.45", "11.11", "142.34")
    assert september["pending_review"][0]["amount"]["decimal"] == "44.44"
    august = call_tool(tools, "get_spending", {"start": "2026-08-01", "end": "2026-08-31"})
    assert august["by_currency"][0]["net_spending"]["decimal"] == "100.10" and august["excluded_transfers_and_card_payments"] == 2
    ledger.review("statement", statement["id"], "verified")
    comparison = call_tool(tools, "compare_periods", {"first": {"start": "2026-08-01", "end": "2026-08-31"},
                                                     "second": {"start": "2026-09-01", "end": "2026-09-30"}})
    [change] = comparison["by_currency"]
    assert (change["second"]["decimal"], change["change"]["decimal"], change["percent_change"]) == ("186.78", "86.68", "86.6")
    cashflow = call_tool(tools, "calculate_cashflow", {"start": "2026-09-01", "end": "2026-09-30"})
    assert [(row["inflow"]["decimal"], row["outflow"]["decimal"], row["net"]["decimal"]) for row in cashflow["by_currency"]] == [("2500.00", "186.78", "2313.22")]
    empty = call_tool(tools, "compare_periods", {"first": {"start": "2026-01-01", "end": "2026-01-31"}, "second": {"start": "2026-09-01", "end": "2026-09-30"}})
    assert empty["by_currency"][0]["percent_change"] is None
    balance = call_tool(tools, "get_account_balance", {"account_id": card["id"]})["balance"]
    assert (balance["decimal"], balance["as_of"], balance["meaning"]) == ("500.00", "2026-09-30", "amount owed")
    assert call_tool(tools, "get_account_balance", {"account_id": checking["id"]})["balance"] is None
    ledger.set_category(tools.get_transactions(TransactionsInput(query="grocery"))["transactions"][0]["id"], "Groceries")
    categories = call_tool(tools, "get_spending_by_category", {"start": "2026-09-01", "end": "2026-09-30"})["categories"]
    assert {(row["category"], row["spending"]["decimal"]) for row in categories} == {("groceries", "120.12"), ("uncategorized", "77.77")}
    with pytest.raises(ValueError):
        call_tool(tools, "get_spending", {"start": "2026-09-30", "end": "2026-09-01"})


def test_bills_payment_state_and_tool_api(tmp_path, books):
    store, ledger, docs = books
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["export.csv"], [("2026-09-28", "CITY POWER UTILITY AUTOPAY", -12000)])
    source = source_of(docs["bill.png"], "extraction:bill")
    ledger.publish_bill({"provider": "City Power", "issue_date": "2026-09-10", "due_date": "2026-10-01", "period_start": None, "period_end": None,
                         "amount_due_minor": 12000, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]}}, source, "proposed")
    other = source_of(docs["receipt.png"], "extraction:water")
    ledger.publish_bill({"provider": "Water District", "issue_date": "2026-08-01", "due_date": "2026-09-01", "period_start": None, "period_end": None,
                         "amount_due_minor": 4500, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]}}, other, "proposed")
    bills = FinanceTools(store).get_upcoming_bills(AsOfInput(as_of="2026-09-24"))["bills"]
    assert [(bill["provider"], bill["payment_state"]) for bill in bills] == [("Water District", "past_due_no_payment_found"), ("City Power", "payment_found")]
    queue = FinanceTools(store).review_queue()
    assert [(item["record_type"], item["review_status"]) for item in queue["records"]] == [("bill", "proposed"), ("bill", "proposed")]


def test_tools_endpoint_validates_typed_arguments(tmp_path):
    app = create_app(tmp_path / "control", "tools-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.post("/api/finance/tools/get_spending", json={}).status_code == 401
        client.headers.update({"Authorization": "Bearer tools-token"})
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        ok = client.post("/api/finance/tools/get_spending", json={"start": "2026-09-01", "end": "2026-09-30"})
        assert ok.status_code == 200 and ok.json()["by_currency"] == []
        assert client.post("/api/finance/tools/get_spending", json={"start": "2026-09-01"}).status_code == 400
        assert client.post("/api/finance/tools/get_spending", json={"start": "2026-09-01", "end": "2026-09-30", "extra": 1}).status_code == 400
        assert client.post("/api/finance/tools/delete_everything", json={}).status_code == 422
        assert client.post("/api/finance/reconcile").json()["open_issues"] == 0
        assert client.post("/api/finance/links/receipt/1/review", json={"status": "verified"}).status_code == 400
