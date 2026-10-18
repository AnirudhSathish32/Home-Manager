"""Synthetic supplier invoices use the existing bill ledger without confusing charges and payments."""
from decimal import Decimal
import json

import pytest

from home_manager.documents.extraction import HEADER_MODELS, HEADERS, BillLine, normalize
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, PeriodInput
from test_extraction import MISSING, cite, extract, transcribe, value
from test_reconcile_tools import add


@pytest.mark.parametrize("paid,balance,status,review", [
    ("0.00", "110.00", "Unpaid", "verified"),
    ("110.00", "0.00", "Paid", "verified"),
    ("30.00", "80.00", "Partially paid", "needs_review"),
])
def test_invoice_total_survives_payments_and_balance(tmp_path, local_model, paid, balance, status, review):
    text = ["EXAMPLE REPAIRS", "Invoice INV-104", "Bill to Alex Example", "Issued 2026-09-10", "Due 2026-09-28", "USD",
            "Description | Quantity | Unit price | Amount", "Parts | 2 | 50.00 | 100.00", "Tax | | | 10.00",
            "Subtotal 100.00", "Invoice total 110.00", f"Payments received {paid}", f"Balance due {balance}", status]
    manager, doc, parse_id = transcribe(tmp_path, local_model, text)
    header = {name: MISSING for name in HEADERS["bill"]}
    header.update(provider=value("EXAMPLE REPAIRS", 1), invoice_marker=value("Invoice", 2), invoice_number=value("INV-104", 2),
                  bill_to=value("Alex Example", 3), issue_date=value("2026-09-10", 4), due_date=value("2026-09-28", 5),
                  currency=value("USD", 6), invoice_subtotal=value("100.00", 10), invoice_tax=value("10.00", 9),
                  invoice_total=value("110.00", 11), amount_due=value(balance, 13), balance_due=value(balance, 13),
                  payments_received=value(paid, 12), payment_status=value(status, 14))
    rows = [{"description": "Parts", "amount": "100.00", "quantity": "2", "unit_price": "50.00", "category": "utilities",
             "line_kind": "other", "line_holder": None, "evidence": cite(8, text[7])},
            {"description": "Tax", "amount": "10.00", "category": None, "line_kind": "tax_fee", "line_holder": None, "evidence": cite(9, text[8])}]
    local_model["outputs"] = [{"document_type": "bill", "evidence": cite(2, text[1]), "issuer": value("EXAMPLE REPAIRS", 1),
                               "document_date": value("2026-09-10", 4)}, header, {"line_items": rows}]
    try:
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        assert run["publication"]["review_status"] == review
        record_id = run["publication"]["id"]
        record = manager.ledger.record("receipt", record_id)
        assert record["total_minor"] == 11000
        assert record["amount_due_minor"] == int(Decimal(balance) * 100)
        assert record["invoice"]["number"] == "INV-104"
        assert record["invoice"]["bill_to"] == "Alex Example"
        assert record["invoice"]["display"]["total_minor"]
        assert record["recurrence"] is None
        assert (record["items"][0]["quantity"], record["items"][0]["unit_price_minor"]) == ("2", 5000)
        assert manager.receipts.get(parse_id)["result"]["vision_tables"]["origin"] == "text_separators"
        summary = next(request for request in local_model["requests"] if request["response_format"]["json_schema"]["name"] == "BillSummary")
        assert json.loads(summary["messages"][1]["content"])["reported_tables"]
        account = manager.ledger.create_account("Synthetic Bank", "checking", "USD")
        # A remaining payment must not replace a partially paid invoice in the one-payment matching path.
        amount = -8000 if review == "needs_review" else -11000
        add(manager.store, manager.ledger, account, doc, [("2026-09-27", "EXAMPLE REPAIRS", amount)])
        Reconciler(manager.store).run()
        assert FinanceTools(manager.store).get_recurring_obligations()["obligations"] == []
        record = manager.ledger.record("receipt", record_id)
        assert bool(record["links"]) == (review == "verified")
        if review == "verified":
            totals = FinanceTools(manager.store).get_spending(PeriodInput(start="2026-09-01", end="2026-09-30"))["by_currency"]
            assert totals[0]["spending"]["minor"] == 11000  # Invoice and payment count once.
    finally:
        manager.close()


def test_invoice_missing_total_never_uses_zero_balance_as_purchase():
    header = {name: MISSING for name in HEADERS["bill"]}
    header.update(invoice_marker=value("Invoice", 1), amount_due=value("0.00", 2))
    record, issues = normalize("bill", HEADER_MODELS["bill"].model_validate(header), [], "USD")
    assert record["total_minor"] is None
    assert record["amount_due_minor"] == 0
    assert any("Invoice total" in issue for issue in issues)


def test_invoice_rejects_unit_price_as_line_total_and_inconsistent_balance():
    header = {name: MISSING for name in HEADERS["bill"]}
    header.update(invoice_marker=value("Invoice", 1), invoice_total=value("100.00", 2),
                  payments_received=value("30.00", 3), balance_due=value("100.00", 4))
    row = BillLine(description="Parts", amount="50.00", quantity="2", unit_price="50.00", category=None,
                   line_kind="other", line_holder=None, evidence=cite(5, "Parts 2 50.00 100.00"))
    record, issues = normalize("bill", HEADER_MODELS["bill"].model_validate(header), [row], "USD")
    assert record["total_minor"] == 10000
    assert any("quantity times unit price" in issue for issue in issues)
    assert any("minus payments" in issue for issue in issues)
