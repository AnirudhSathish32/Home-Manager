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


def test_invoice_can_be_recorded_as_purchase_and_undone(app_client):
    client, manager, docs = app_client
    invoice = {"number": "FURN-101", "total_minor": 5000, "payments_received_minor": 5000, "balance_due_minor": 0}
    record = {"provider": "Example Furniture", "issue_date": "2026-09-28", "due_date": "2026-09-28",
              "total_minor": 5000, "amount_due_minor": 0, "currency": "USD", "issues": [], "locator": {}, "invoice": invoice,
              "items": [{"description": "Chair", "line_total_minor": 5000, "category": "household supplies", "locator": {}}]}
    rid = manager.ledger.publish_bill(record, source_of(docs["bill.png"], "extraction:invoice"), "verified")["id"]
    account = manager.ledger.create_account("Example Bank", "checking", "USD")
    add(manager.store, manager.ledger, account, docs["export.csv"], [("2026-09-28", "EXAMPLE FURNITURE", -5000)])
    manager.reconciler.run()
    before_record = manager.ledger.record("receipt", rid)
    assert before_record["links"]
    before = snapshot(manager.store)
    endpoint = f"/api/finance/records/receipt/{rid}"
    preview = client.post(endpoint + "/correction-preview", json={"changes": {"document_kind": "receipt"}})
    assert preview.status_code == 200, preview.text
    assert preview.json()["changes"] == [{"field": "document_kind", "label": "Record as", "kind": "document_kind", "from": "bill", "to": "receipt"}]
    assert not preview.json()["figures"] and not preview.json()["matching"]["changed"]
    assert snapshot(manager.store) == before
    saved = client.patch(endpoint, json={"changes": {"document_kind": "receipt"}})
    assert saved.status_code == 200, saved.text
    result = saved.json()["record"]
    assert result["document_kind"] == "receipt"
    for key in ("invoice", "links", "total_minor", "purchase_date", "amount_due_minor"):
        assert result[key] == before_record[key], key
    for key in ("id", "description", "line_total_minor", "category", "quantity", "unit_price_minor"):
        assert result["items"][0][key] == before_record["items"][0][key], key
    assert next(item for item in result["correctable"] if item["field"] == "document_kind")["options"] == ["receipt", "bill"]
    assert "purchase_date" in {item["field"] for item in result["correctable"]}
    # The library's Bill tag follows the ledger, independently of the folder the user filed it in.
    assert manager.store.document(docs["bill.png"]["id"])["ledger_kind"] is None
    for invalid in (None, "", "invoice", "paystub"):
        response = client.patch(endpoint, json={"changes": {"document_kind": invalid}})
        assert response.status_code == 400, response.text
    # A reread cannot reinstate the Bill label on a corrected record.
    manager.ledger.publish_bill(record, source_of(docs["bill.png"], "extraction:invoice-again"), "verified")
    assert manager.ledger.record("receipt", rid)["document_kind"] == "receipt"
    # If model fields are refreshed, restore kind before purchase-only fields, regardless of history order.
    with manager.store.connection() as db:
        db.execute("SAVEPOINT reread")
        manager.ledger._apply_correction(db, "receipt", rid, {"purchase_date": "2026-09-26"}, None)
        db.execute("UPDATE receipts SET document_kind='bill',purchase_date='2026-09-28' WHERE id=?", (rid,))
        manager.ledger.apply_corrections(db, "receipt", rid)
        assert tuple(db.execute("SELECT document_kind,purchase_date FROM receipts WHERE id=?", (rid,)).fetchone()) == ("receipt", "2026-09-26")
        db.execute("ROLLBACK TO reread")
        db.execute("RELEASE reread")
    undone = client.post(endpoint + "/corrections/undo", json={"ids": saved.json()["correction_ids"]})
    assert undone.status_code == 200, undone.text
    assert undone.json()["record"]["document_kind"] == "bill"
    assert undone.json()["record"]["invoice"] == before_record["invoice"]


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


def test_bills_and_pay_stubs_move_the_months_they_count_in(app_client):
    client, manager, docs = app_client
    bill = manager.ledger.publish_bill({"provider": "City Water", "issue_date": "2026-09-01", "due_date": "2026-09-20", "period_start": None, "period_end": None,
                                        "amount_due_minor": 4500, "currency": "USD", "issues": [], "locator": {}}, source_of(docs["bill.png"], "extraction:bill"), "verified")["id"]
    # A bill counts on its due date (docs/money.md "Bills and their lines"): a later due date in the same month moves nothing.
    preview = client.post(f"/api/finance/records/receipt/{bill}/correction-preview", json={"changes": {"due_date": "2026-09-25"}}).json()
    assert preview["figures"] == [] and preview["notes"] == []
    assert preview["changes"][0]["from"] == "2026-09-20" and preview["changes"][0]["to"] == "2026-09-25"
    moved = client.post(f"/api/finance/records/receipt/{bill}/correction-preview", json={"changes": {"due_date": "2026-10-02"}}).json()
    assert {item["label"]: item["difference"]["minor"] for item in moved["figures"] if item["label"] == "Spending in September 2026"} == {
        "Spending in September 2026": -4500}
    with manager.store.connection() as db:
        stub = db.execute("INSERT INTO income_records(document_id,blob_hash,pay_date,gross_pay_minor,net_pay_minor,currency,review_status,created_at,updated_at) "
                          "VALUES(?,?,'2026-09-15',400000,300000,'USD','verified','t','t')", (docs["stub.png"]["id"], docs["stub.png"]["current_hash"])).lastrowid
    preview = client.post(f"/api/finance/records/income_record/{stub}/correction-preview", json={"changes": {"pay_date": "2026-09-30"}}).json()
    assert preview["figures"] == [] and preview["notes"] == ["Taxes for 2026 are worked out again from your pay stubs."]
    # Its net pay counts as money in on its pay date until a deposit replaces it (docs/money.md "Money in and paystubs").
    moved = client.post(f"/api/finance/records/income_record/{stub}/correction-preview", json={"changes": {"pay_date": "2026-10-01"}}).json()
    assert {item["label"]: item["difference"]["minor"] for item in moved["figures"]} == {
        "Money in during September 2026": -300000, "Cash flow in September 2026": -300000,
        "Money in during October 2026": 300000, "Cash flow in October 2026": 300000}


def test_paystub_totals_and_current_ytd_lines_can_be_corrected_and_survive_a_new_reading(app_client):
    client, manager, docs = app_client
    stub = {"payer_or_employer": "Acme", "pay_date": "2026-09-15", "period_start": None, "period_end": None,
            "gross_pay_minor": 5200000, "net_pay_minor": 4000000, "gross_pay_ytd_minor": 5200000,
            "net_pay_ytd_minor": 4000000, "taxes_minor": 100000, "deductions_minor": 20000,
            "currency": "USD", "work_state": None, "pay_frequency": None, "issues": ["Gross pay needs review."],
            "locator": {}, "lines": [{"description": "Regular pay", "line_group": "earnings", "category": "regular_pay",
                                    "current_minor": 5200000, "ytd_minor": 5200000, "locator": {}}]}
    source = source_of(docs["stub.png"], "extraction:paystub")
    income_id = manager.ledger.publish_income(stub, source, "needs_review")["id"]
    changed = client.patch(f"/api/finance/records/income_record/{income_id}", json={"changes": {
        "gross_pay": "2000.00", "net_pay": "1500.00", "gross_pay_ytd": "52000.00", "net_pay_ytd": "40000.00",
        "pay_frequency": "26", "work_state": "NY"}})
    assert changed.status_code == 200, changed.text
    changed = client.patch(f"/api/paystubs/{income_id}/lines/1", json={"changes": {"current": "2000.00"}})
    assert changed.status_code == 200, changed.text
    line_correction_id = changed.json()["correction_ids"][0]
    record = manager.ledger.record("income_record", income_id)
    assert (record["gross_pay_minor"], record["net_pay_minor"], record["gross_pay_ytd_minor"], record["net_pay_ytd_minor"]) == (
        200000, 150000, 5200000, 4000000)
    assert (record["pay_frequency"], record["work_state"], record["lines"][0]["current_minor"]) == (26, "NY", 200000)
    assert record["lines"][0]["correctable"][0]["value"] == "2000.00"
    assert client.patch(f"/api/paystubs/{income_id}/lines/1", json={"changes": {"current": "bad"}}).status_code == 400
    assert manager.ledger.record("income_record", income_id)["lines"][0]["current_minor"] == 200000
    manager.ledger.publish_income(stub, source, "needs_review")
    assert manager.ledger.record("income_record", income_id)["lines"][0]["current_minor"] == 200000
    assert manager.ledger.record("income_record", income_id)["gross_pay_minor"] == 200000
    undone = client.post(f"/api/finance/records/income_record/{income_id}/corrections/undo", json={"ids": [line_correction_id]})
    assert undone.status_code == 200, undone.text
    assert manager.ledger.record("income_record", income_id)["lines"][0]["current_minor"] == 5200000
