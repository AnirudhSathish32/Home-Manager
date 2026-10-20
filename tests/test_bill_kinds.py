"""Bill kinds (specs/bill-kinds FR-40 – FR-58): a rent form beside the general bill form. Synthetic bills only."""

import json

from home_manager.documents.extraction import EXTRACTION_VERSION
from test_bills_ledger import PHONE_TEXT, bill, line, open_books
from test_extraction import MISSING, cite, extract, transcribe, value
from test_reconcile_tools import source_of

V30 = "typed-extraction-v30-pre-tax-deductions"


def phone_outputs():
    """The PHONE bill's classification, summary and lines, in the order a general bill asks them."""
    header = {"provider": value("ACME WIRELESS", 1), "account_reference": value("4821", 2, "Account 0000 4821"), "issue_date": value("2026-09-05", 3),
              "due_date": value("2026-09-28", 4), "period_start": MISSING, "period_end": MISSING, "amount_due": value("79.99", 10, "Amount due USD 79.99"),
              "new_charges": value("67.99", 9, "New charges 67.99"), "currency": value("USD", 10, "USD")}
    rows = [{"description": "Unlimited", "amount": "40.00", "category": "phone & internet", "line_kind": "service", "line_holder": "Alex 555-201-1111",
             "evidence": cite(5, PHONE_TEXT[4])},
            {"description": "Apple TV+", "amount": "9.99", "category": "subscriptions", "line_kind": "subscription", "line_holder": None,
             "evidence": cite(6, PHONE_TEXT[5])},
            {"description": "Taxes and fees", "amount": "18.00", "category": None, "line_kind": "tax_fee", "line_holder": None, "evidence": cite(7, PHONE_TEXT[6])}]
    return [{"document_type": "bill", "evidence": cite(1, "ACME WIRELESS"), "issuer": value("ACME WIRELESS", 1), "document_date": MISSING},
            header, {"line_items": rows}]


def test_version_ledger_stores_a_bills_kind_details_and_line_types(tmp_path):
    """SL-01 plumbing: a bill record carrying a kind, details and line types is stored and read back by kind; one without
    a kind keeps every new column empty (FR-52)."""
    store, ledger, docs = open_books(tmp_path / "managed")
    try:
        period = {"period": {"start": "2026-10-01", "end": "2026-10-31", "how": "printed", "locator": {"line_ids": ["line-2"]}}}
        lines = [{**line("Rent", 145000, "housing"), "line_type": "rent", "details": period},
                 {**line("Water", 3842, "utilities", "usage"), "line_type": "utility"}]
        record = {"provider": "Synth Property", "issue_date": None, "due_date": "2026-10-01", "period_start": None, "period_end": None,
                  "amount_due_minor": 148842, "total_minor": 148842, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]},
                  "items": lines, "category": None, "recurrence": "monthly", "bill_kind": "rent",
                  "details": {"previous_balance": {"minor": 0, "locator": {"line_ids": ["line-1"]}}, "notes": []}}
        rent = ledger.publish_bill(record, source_of(docs["rent.png"], "extraction:rent.png"), "needs_review")["id"]
        with store.connection() as db:
            row = db.execute("SELECT bill_kind,receipt_kind,details_json FROM receipts WHERE id=?", (rent,)).fetchone()
            assert (row["bill_kind"], row["receipt_kind"]) == ("rent", None)
            assert json.loads(row["details_json"])["rent"]["previous_balance"]["minor"] == 0
            assert [tuple(item) for item in db.execute("SELECT line_type,line_kind FROM receipt_items WHERE receipt_id=? ORDER BY position", (rent,))] == [
                ("rent", "service"), ("utility", "usage")]
        shown = ledger.record("receipt", rent)
        assert shown["bill_kind"] == "rent" and shown["details"]["previous_balance"]["minor"] == 0
        assert shown["items"][0]["details"]["period"]["start"] == "2026-10-01" and shown["items"][1]["line_type"] == "utility"

        phone = bill(ledger, docs["phone.png"], "Acme Wireless", "2026-09-28", [line("Unlimited plan", 4000, "phone & internet")])
        with store.connection() as db:
            row = db.execute("SELECT bill_kind,receipt_kind,details_json FROM receipts WHERE id=?", (phone,)).fetchone()
            assert tuple(row) == (None, None, None)
            assert tuple(db.execute("SELECT line_type,details_json FROM receipt_items WHERE receipt_id=?", (phone,)).fetchone()) == (None, None)
    finally:
        store.close()


def test_version_changed_and_a_bill_read_under_v30_is_read_again(tmp_path, local_model):
    """SC-49 step 2 (FR-52): the version changed, so a parse with only a v30 run gets a new run."""
    assert EXTRACTION_VERSION != V30
    manager, doc, parse_id = transcribe(tmp_path, local_model, PHONE_TEXT)
    try:
        local_model["outputs"] = phone_outputs()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        with manager.store.connection() as db:
            db.execute("UPDATE extraction_runs SET prompt_version=? WHERE id=?", (V30, run["id"]))
        local_model["outputs"] = phone_outputs()
        started = manager.start_extraction(doc["id"], parse_id)
        manager.future.result(timeout=30)
        assert started["reused"] is False and started["run_id"] != run["id"]
        again = manager.extractions.get(started["run_id"])
        assert (again["status"], again["prompt_version"]) == ("succeeded", EXTRACTION_VERSION)
        with manager.store.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1  # The same bill, read again.
    finally:
        manager.close()
