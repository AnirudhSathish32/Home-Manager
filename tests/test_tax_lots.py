"""Investments phase 5 (docs/planning.md "Investments"): tax lots, realized gains, and 1099/5498 forms checked against records. Synthetic data only."""

from datetime import date

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.finance.health import check_ledger
from home_manager.finance.investments import Investments, LotInput
from home_manager.finance.tax_lots import account_lots, realized
from test_extraction import cite, extract, transcribe, value

FORM = ["Vanguard Brokerage Services", "Account ending 1111", "2026 Consolidated Form 1099 Currency USD",
        "1099-DIV Box 1a Total ordinary dividends 42.10", "1099-INT Box 1 Interest income 12.00",
        "1099-B Box 1d Proceeds 3,800.00", "1099-B Box 1e Cost or other basis 2,900.00"]


def brokerage(store, docs):
    """A taxable Vanguard account ending 1111, from a confirmed statement, holding one fund."""
    investments = Investments(store, date(2026, 12, 31))
    record = {"investment_kind": "brokerage", "institution": "Vanguard Brokerage Services", "account_name": "Brokerage", "last_four": "1111",
              "value_minor": 100000, "period_end": "2026-11-30", "currency": "USD", "issues": [],
              "holdings": [{"name": "Total Stock Market ETF", "identifier": "VTI", "instrument_class": "etf", "quantity": "5", "value_minor": 100000}],
              "activity": [{"name": "Dividend VTI", "identifier": "VTI", "event_date": "2026-06-30", "event_type": "dividend", "amount_minor": 4210}]}
    published = investments.publish_statement(record, {"document_id": docs["statement.png"]["id"], "blob_hash": docs["statement.png"]["current_hash"], "run_id": "s"})
    investments.review(published["id"], "verified")
    with store.connection() as db:
        holding = db.execute("SELECT id FROM holdings WHERE account_id=?", (published["account_id"],)).fetchone()[0]
    return investments, published["account_id"], holding


def trade(store, account_id, holding_id, day, kind, quantity, amount):
    with store.connection() as db:
        db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,quantity,review_status,confirmation_id,created_at) "
                   "VALUES(?,?,?,?,?,?,'verified',NULL,'t')", (account_id, holding_id, day, kind, amount, quantity))


@pytest.fixture
def books(tmp_path):
    from home_manager.library.storage import Store
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"statement.png": b"statement"})
    try:
        yield store, documents_by_name(store)
    finally:
        store.close()


def test_sales_close_lots_first_in_first_out(books):
    store, docs = books
    investments, account_id, holding = brokerage(store, docs)
    for day, kind, quantity, amount in [("2025-01-10", "buy", "10", 100000), ("2025-06-01", "buy", "10", 120000), ("2026-03-01", "buy", "5", 70000),
                                        ("2025-01-10", "buy", "10", 100000),  # The same buy listed again on a statement: one lot.
                                        ("2026-01-10", "sell", "15", 225000), ("2026-06-02", "sell", "5", 80000), ("2026-07-01", "sell", "10", 150000)]:
        trade(store, account_id, holding, day, kind, quantity, amount)
    with store.connection() as db:
        found = account_lots(db, account_id)[holding]
        year = realized(db, [account_id], 2026)
    sales = [(sale["disposed_date"], sale["acquired_date"], sale["shares"], sale["proceeds_minor"], sale["cost_minor"], sale["term"]) for sale in found["disposals"]]
    assert sales == [
        # Held exactly one year is still short-term; the proceeds split by shares, the last piece taking the remainder.
        ("2026-01-10", "2025-01-10", "10", 150000, 100000, "short"), ("2026-01-10", "2025-06-01", "5", 75000, 60000, "short"),
        ("2026-06-02", "2025-06-01", "5", 80000, 60000, "long"),  # One day past the anniversary.
        ("2026-07-01", "2026-03-01", "5", 75000, 70000, "short")]
    assert found["missing"] == [{"sell_event_id": found["missing"][0]["sell_event_id"], "date": "2026-07-01", "shares": "5"}]
    assert (year["proceeds_minor"], year["cost_minor"], year["short_minor"], year["long_minor"]) == (380000, 290000, 70000, 20000)
    assert found["lots"] == [] and found["open_shares"] == "0"
    # Shares bought before the documents begin: entered by hand, they are the oldest lot and change which lots each sale takes.
    investments.add_lot(holding, LotInput(acquired_date="2024-01-02", quantity="5", cost="400"))
    with store.connection() as db:
        again = account_lots(db, account_id)[holding]
    assert again["missing"] == [] and (again["disposals"][0]["acquired_date"], again["disposals"][0]["term"]) == ("2024-01-02", "long")
    with store.connection() as db:  # Every sale is covered now; the statement's 5 shares predate these trades, so only that remains.
        assert [(item.code, item.record_id) for item in check_ledger(db)] == [("lots_vs_holding", holding)]
    with pytest.raises(ValueError, match="number of shares"):
        LotInput(acquired_date="2024-01-02", quantity="none", cost="1")
    # A form from a bank with no account here is kept on its own, with nothing to compare it to.
    record = {"institution": "Chase", "last_four": "9999", "tax_year": 2026, "currency": "USD", "issues": [],
              "boxes": [{"form": "1099-INT", "box": "1", "label": "Interest income", "amount_minor": 1200, "locator": {}}]}
    form = investments.publish_tax_form(record, {"document_id": docs["statement.png"]["id"], "blob_hash": docs["statement.png"]["current_hash"], "run_id": "f"})
    assert form["account_id"] is None
    [check] = investments.tax_year(2026)["checks"]
    assert (check["review_status"], check["form_amount"]["display"], check["recorded"]) == ("proposed", "12.00 USD", None)


def test_a_consolidated_1099_is_compared_with_what_is_recorded(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, FORM)
    try:
        store = manager.store
        inbox_scan(store, {"statement.png": b"statement"})
        investments, account_id, holding = brokerage(store, documents_by_name(store))
        trade(store, account_id, holding, "2025-02-01", "buy", "40", 290000)
        trade(store, account_id, holding, "2026-05-01", "sell", "35", 380000)  # Shares' cost 290000 * 35/40 = 253750.
        classified = {"document_type": "investment_tax_form", "evidence": cite(3, FORM[2]), "issuer": value("Vanguard Brokerage Services", 1, FORM[0]),
                      "document_date": {"value": None, "status": "missing", "evidence": []}}
        summary = {"institution": value("Vanguard Brokerage Services", 1, FORM[0]), "account_reference": value("1111", 2, FORM[1]),
                   "tax_year": value("2026", 3, FORM[2]), "document_date": {"value": None, "status": "missing", "evidence": []},
                   "currency": value("USD", 3, FORM[2])}
        boxes = [{"form": form, "box": box, "label": label, "amount": amount, "evidence": cite(line, FORM[line - 1])}
                 for line, form, box, label, amount in [(4, "1099-DIV", "Box 1a", "Total ordinary dividends", "42.10"), (5, "1099-INT", "1", "Interest income", "12.00"),
                                                        (6, "1099-B", "1d", "Proceeds", "3,800.00"), (7, "1099-B", "1e", "Cost or other basis", "2,900.00")]]
        local_model["outputs"] = [classified, summary, {"boxes": boxes}]
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        publication = run["publication"]
        assert (publication["record_type"], publication["account_id"], publication["boxes"]) == ("tax_form", account_id, 4)
        [pending] = [item for item in investments.pending() if item["record_type"] == "tax_form"]
        assert pending["name"] == "Vanguard Brokerage Services 1099-DIV, 1099-INT, 1099-B for 2026"
        investments.review_tax_form(publication["id"], "verified")
        year = investments.tax_year(2026)
        checks = {check["label"]: (check["form_amount"]["display"], check["recorded"]["display"], check["matches"]) for check in year["checks"]}
        assert checks == {"Interest": ("12.00 USD", "0.00 USD", False), "Dividends": ("42.10 USD", "42.10 USD", True),
                          "Sale proceeds": ("3,800.00 USD", "3,800.00 USD", True), "Cost of shares sold": ("2,900.00 USD", "2,537.50 USD", False)}
        [gains] = year["gains"]
        assert (gains["proceeds"]["display"], gains["long"]["display"], gains["short"]["display"]) == ("3,800.00 USD", "1,262.50 USD", "0.00 USD")
        assert 2026 in year["years"] and 2025 in year["years"]
    finally:
        manager.close()
