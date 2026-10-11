"""A record's history and undoing a correction (finance/ledger.py history, undo_corrections), and the record view's
correctable fields and figures (docs/money.md "Corrections"). Synthetic data only."""

from urllib.parse import quote

from home_manager.finance.ledger import AUTO_VERIFIED_NOTE
from test_correction_preview import app_client, itemised_receipt  # noqa: F401  (the fixture)
from test_provenance import bank_statement
from test_reconcile_tools import source_of


def test_history_is_newest_first_with_who_what_and_why(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"], "needs_review", ["Purchase date is missing."], day=None)
    first = client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"purchase_date": "2026-09-28"}, "reason": "Printed at the top"})
    assert first.status_code == 200 and len(first.json()["correction_ids"]) == 1
    client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"location": "Main St"}})
    entries = client.get(f"/api/finance/records/receipt/{receipt_id}/history").json()["entries"]
    assert [entry["kind"] for entry in entries] == ["correction", "review", "correction"]
    location, automatic, date = entries
    assert (location["label"], location["from"], location["to"], location["undoable"]) == ("Location", None, "Main St", True)
    # A profile with one person records them without the who's-here choice.
    assert (date["label"], date["from"], date["to"], date["reason"], date["who"]) == ("Purchase date", None, "2026-09-28", "Printed at the top", manager.people()[0])
    assert date["resolved_issues"] == ["Purchase date is missing."]
    assert automatic["automatic"] and automatic["who"] == "Automatic check" and automatic["note"] == AUTO_VERIFIED_NOTE
    assert (automatic["from_status"], automatic["to_status"]) == ("needs_review", "verified")


def test_undo_restores_the_value_the_issues_and_needs_review(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"], "needs_review", ["Purchase date is missing."], day=None)
    ids = client.patch(f"/api/finance/records/receipt/{receipt_id}", json={"changes": {"purchase_date": "2026-09-28"}}).json()["correction_ids"]
    assert manager.ledger.record("receipt", receipt_id)["review_status"] == "verified"
    undone = client.post(f"/api/finance/records/receipt/{receipt_id}/corrections/undo", json={"ids": ids})
    assert undone.status_code == 200, undone.text
    record = undone.json()["record"]
    assert record["purchase_date"] is None and record["issues"] == ["Purchase date is missing."] and record["review_status"] == "needs_review"
    again = client.post(f"/api/finance/records/receipt/{receipt_id}/corrections/undo", json={"ids": ids})
    assert again.status_code == 400 and "changed again since" in again.json()["detail"]
    entries = client.get(f"/api/finance/records/receipt/{receipt_id}/history").json()["entries"]
    assert entries[0]["kind"] == "review" and entries[0]["note"] == "Undid a correction"
    assert entries[1]["reason"] == "Undid a change" and entries[1]["undoable"]


def test_a_statements_history_includes_its_rows(app_client):
    client, manager, docs = app_client
    found = bank_statement(150000)
    found["transactions"] = [{"posted_date": "2026-09-12", "description": "CORNER BOOKS", "amount_minor": -2500, "currency": "USD", "transaction_type": "purchase",
                              "locator": {"line_ids": ["line-3"]}}]
    published = manager.ledger.publish_statement(found, source_of(docs["statement.png"], "extraction:statement"), "proposed")
    record = client.get(f"/api/finance/records/statement/{published['id']}").json()
    [row] = record["transactions"]
    assert {item["field"] for item in row["correctable"]} == {"posted_date", "amount", "direction", "merchant", "transaction_type"}
    ids = client.patch(f"/api/finance/records/transaction/{row['id']}", json={"changes": {"amount": "25.50"}}).json()["correction_ids"]
    [entry] = client.get(f"/api/finance/records/statement/{published['id']}/history").json()["entries"]
    assert (entry["label"], entry["from"], entry["to"], entry["row"]["id"]) == ("Amount", "25.00 USD", "25.50 USD", row["id"])
    assert client.post(f"/api/finance/records/statement/{published['id']}/corrections/undo", json={"ids": ids}).status_code == 200
    assert manager.ledger.record("transaction", row["id"])["amount_minor"] == -2500


def test_correctable_fields_per_record_type(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"])
    correctable = {item["field"]: item for item in client.get(f"/api/finance/records/receipt/{receipt_id}").json()["correctable"]}
    assert set(correctable) == {"purchase_date", "merchant", "location", "category", "direction"}
    assert correctable["merchant"]["value"] == "Fresh Market" and correctable["purchase_date"]["value"] == "2026-09-28"
    assert "groceries" in correctable["category"]["options"] and correctable["direction"]["options"] == ["sale", "return"]
    bill = manager.ledger.publish_bill({"provider": "City Water", "issue_date": "2026-09-01", "due_date": "2026-09-20", "period_start": None, "period_end": None,
                                        "amount_due_minor": 4500, "currency": "USD", "issues": [], "locator": {}}, source_of(docs["bill.png"], "extraction:bill"), "verified")["id"]
    bill_fields = {item["field"]: item for item in client.get(f"/api/finance/records/bill/{bill}").json()["correctable"]}
    assert bill_fields["provider"]["shown_as"] == "merchant" and bill_fields["provider"]["value"] == "City Water"
    statement = manager.ledger.publish_statement(bank_statement(150000), source_of(docs["statement.png"], "extraction:statement"), "verified")
    money = {item["field"]: item for item in client.get(f"/api/finance/records/statement/{statement['id']}").json()["correctable"]}
    assert money["closing_balance"]["value"] == "1500.00" and money["closing_balance"]["kind"] == "money"


def test_figures_show_what_a_receipt_counts_as_and_in(app_client):
    client, manager, docs = app_client
    receipt_id = itemised_receipt(manager.ledger, docs["receipt.png"])
    record = client.get(f"/api/finance/records/receipt/{receipt_id}?figures=1").json()
    split = record["figures"]["split"]
    assert split["label"] == "Counts as" and split["minor"] == 5000 and split["trace"] == f"split.receipt?receipt_id={receipt_id}"
    traced = client.get("/api/traces/" + quote(split["trace"], safe="")).json()
    assert traced["result"]["minor"] == split["minor"] and traced["reconciles"]
    counts_in = {item["label"]: item["minor"] for item in record["figures"]["counts_in"]}
    assert counts_in == {"Groceries, September 2026": 4000, "Household supplies, September 2026": 1000}
    assert "figures" not in client.get(f"/api/finance/records/receipt/{receipt_id}").json()
    statement = manager.ledger.publish_statement(bank_statement(150000), source_of(docs["statement.png"], "extraction:statement"), "verified")
    assert client.get(f"/api/finance/records/statement/{statement['id']}?figures=1").json()["figures"]["balance"]["minor"] == 150000
