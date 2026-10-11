"""The correction preview (finance/correction_preview.py; docs/money.md "Corrections"): what a correction would change,
worked out inside a transaction that rolls back. Synthetic data only."""

import time
from urllib.parse import quote

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.library.scanner import ScanLimits
from test_reconcile_tools import add, source_of

TABLES = ("record_corrections", "reconciliation_runs", "merchants", "review_events", "figure_snapshots", "transaction_receipt_links")


@pytest.fixture
def app_client(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager = app.state.manager
        inbox_scan(manager.store, {"receipt.png": b"synthetic receipt", "statement.png": b"synthetic statement", "bill.png": b"synthetic bill",
                                   "stub.png": b"synthetic stub", "export.csv": b"date,amount\n"})
        yield client, manager, documents_by_name(manager.store)


def itemised_receipt(ledger, doc, status="verified", issues=(), day="2026-09-28"):
    items = [{"description": name, "product_code": None, "quantity": "1", "unit_price_minor": total, "line_total_minor": total, "discount_minor": None,
              "taxed": False, "category": category, "locator": {"line_ids": [f"line-{index}"]}}
             for index, (name, total, category) in enumerate([("EGGS", 4000, "groceries"), ("SOAP", 1000, "household supplies")], 2)]
    return ledger.publish_receipt({"merchant": "Fresh Market", "purchase_date": day, "subtotal_minor": 5000, "tax_minor": None, "tip_minor": None,
                                   "total_minor": 5000, "currency": "USD", "issues": list(issues), "items": items, "category": "groceries",
                                   "locator": {"line_ids": ["line-1"]}}, source_of(doc, "extraction:receipt"), status)["id"]


def snapshot(store):
    with store.connection() as db:
        rows = {table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall() for table in TABLES}
        rows["receipts"] = db.execute("SELECT * FROM receipts ORDER BY id").fetchall()
        rows["transactions"] = db.execute("SELECT * FROM transactions ORDER BY id").fetchall()
    return {table: [tuple(row) for row in found] for table, found in rows.items()}


def by_label(preview):
    return {item["label"]: item for item in preview["figures"]}


def test_moving_a_receipt_a_month_moves_both_months_and_nothing_persists(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"])
    before = snapshot(manager.store)
    started = time.monotonic()
    response = client.post(f"/api/finance/records/receipt/{receipt_id}/correction-preview", json={"changes": {"purchase_date": "2026-10-02"}, "reason": "ignored"})
    assert time.monotonic() - started < 5
    assert response.status_code == 200, response.text
    preview = response.json()
    assert preview["changes"] == [{"field": "purchase_date", "label": "Purchase date", "kind": "date", "from": "2026-09-28", "to": "2026-10-02"}]
    figures = by_label(preview)
    assert figures["Spending in September 2026"]["before"]["minor"] == 5000 and figures["Spending in September 2026"]["after"]["minor"] == 0
    assert figures["Spending in September 2026"]["difference"]["minor"] == -5000
    assert figures["Spending in October 2026"]["after"]["minor"] == 5000
    assert figures["Groceries in September 2026"]["after"]["minor"] == 0 and figures["Groceries in October 2026"]["after"]["minor"] == 4000
    assert figures["Household supplies in October 2026"]["after"]["minor"] == 1000
    assert figures["Spending in September 2026"]["before"]["trace"].startswith("spending.net?")
    assert preview["unchanged_count"] >= 1  # This receipt by category stays the same.
    assert snapshot(manager.store) == before

    # After the real save, every figure's trace equals the preview's "after".
    saved = client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"purchase_date": "2026-10-02"}})
    assert saved.status_code == 200 and saved.json()["correction_ids"]
    for item in preview["figures"]:
        traced = client.get("/api/traces/" + quote(item["ref"], safe=""))
        assert traced.json()["result"]["minor"] == item["after"]["minor"], item["label"]


def test_a_bad_value_gives_the_same_message_as_a_save(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"])
    preview = client.post(f"/api/finance/records/receipt/{receipt_id}/correction-preview", json={"changes": {"purchase_date": "2026-13-40"}})
    saved = client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"purchase_date": "2026-13-40"}})
    assert preview.status_code == saved.status_code == 400
    assert preview.json() == saved.json()
    family = client.post(f"/api/finance/records/receipt/{receipt_id}/correction-preview?member=0123456789ab", json={"changes": {"purchase_date": "2026-10-02"}})
    assert family.status_code == 400 and "family" in family.json()["detail"]


def test_the_preview_says_when_a_record_will_count_automatically(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"], "needs_review", ["Purchase date is missing."], day=None)
    preview = client.post(f"/api/finance/records/receipt/{receipt_id}/correction-preview", json={"changes": {"purchase_date": "2026-09-28"}}).json()
    assert preview["review"] == {"before": "needs_review", "after": "verified", "automatic": True}
    assert preview["issues"] == {"resolved": ["Purchase date is missing."], "remaining": []}
    assert by_label(preview)["Spending in September 2026"]["after"]["minor"] == 5000
    assert manager.ledger.record("receipt", receipt_id)["review_status"] == "needs_review"


def test_a_transaction_amount_change_previews_what_a_save_does(app_client):
    # A save keeps the charge's proposed match (reconciliation doesn't re-check a link), so the preview does too.
    client, manager, docs = app_client
    card = manager.ledger.create_account("Fidelity", "credit_card", "USD", last_four="7314")
    [charge] = add(manager.store, manager.ledger, card, docs["export.csv"], [("2026-09-28", "FRESH MARKET", -5000)])
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"])
    manager.reconciler.run()
    assert manager.ledger.record("receipt", receipt_id)["links"]
    before = snapshot(manager.store)
    preview = client.post(f"/api/finance/records/transaction/{charge}/correction-preview", json={"changes": {"amount": "80.00"}}).json()
    assert preview["changes"] == [{"field": "amount", "label": "Amount", "kind": "amount", "from": "50.00", "to": "80.00"}]
    assert not preview["matching"]["changed"] and preview["matching"]["before"] == preview["matching"]["after"]
    spending = by_label(preview)["Spending in September 2026"]
    assert (spending["before"]["minor"], spending["after"]["minor"]) == (5000, 8000)
    assert snapshot(manager.store) == before
    client.patch(f"/api/finance/records/transaction/{charge}", json={"changes": {"amount": "80.00"}})
    for item in preview["figures"]:
        assert client.get("/api/traces/" + quote(item["ref"], safe="")).json()["result"]["minor"] == item["after"]["minor"], item["label"]


def test_a_statement_balance_moves_the_account_balance(app_client):
    client, manager, docs = app_client
    from test_provenance import bank_statement
    published = manager.ledger.publish_statement(bank_statement(150000), source_of(docs["statement.png"], "extraction:statement"), "verified")
    preview = client.post(f"/api/finance/records/statement/{published['id']}/correction-preview", json={"changes": {"closing_balance": "1,525.10"}}).json()
    figures = by_label(preview)
    balance = next(item for label, item in figures.items() if label.endswith(" balance"))
    assert (balance["before"]["minor"], balance["after"]["minor"], balance["difference"]["minor"]) == (150000, 152510, 2510)
    assert {"Cash across accounts", "Net worth"} <= set(figures)


def test_bills_and_pay_stubs_show_notes_only(app_client):
    client, manager, docs = app_client
    bill = manager.ledger.publish_bill({"provider": "City Water", "issue_date": "2026-09-01", "due_date": "2026-09-20", "period_start": None, "period_end": None,
                                        "amount_due_minor": 4500, "currency": "USD", "issues": [], "locator": {}}, source_of(docs["bill.png"], "extraction:bill"), "verified")["id"]
    preview = client.post(f"/api/finance/records/bill/{bill}/correction-preview", json={"changes": {"due_date": "2026-09-25"}}).json()
    assert preview["figures"] == [] and preview["notes"] == ["Bills don't change any totals; the due date moves on Bills and Today."]
    assert preview["changes"][0]["from"] == "2026-09-20" and preview["changes"][0]["to"] == "2026-09-25"
    with manager.store.connection() as db:
        stub = db.execute("INSERT INTO income_records(document_id,blob_hash,pay_date,gross_pay_minor,net_pay_minor,currency,review_status,created_at,updated_at) "
                          "VALUES(?,?,'2026-09-15',400000,300000,'USD','verified','t','t')", (docs["stub.png"]["id"], docs["stub.png"]["current_hash"])).lastrowid
    preview = client.post(f"/api/finance/records/income_record/{stub}/correction-preview", json={"changes": {"pay_date": "2026-09-30"}}).json()
    assert preview["figures"] == [] and preview["notes"] == ["Taxes for 2026 are worked out again from your pay stubs."]
