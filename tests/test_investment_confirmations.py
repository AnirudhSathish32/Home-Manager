"""Investments phase 3 (docs/investments.md): purchase confirmations, values estimated from terms, maturities. Synthetic data only."""

from datetime import date
from decimal import Decimal

import pytest

from conftest import inbox_scan
from home_manager.finance.forecast import ForecastInput, project
from home_manager.finance.investments import AccountInput, HoldingInput, Investments, MaturedInput, ValueInput, accrued, add_months, ibond_value
from test_extraction import cite, extract, transcribe, value

TREASURY = ["TreasuryDirect", "Account number ending 7788", "Purchase confirmation", "Issue date 2026-07-01 Currency USD",
            "26-Week Bill CUSIP 912797AB1 Face amount $10,000.00", "Purchase price $9,750.00 Maturity date 2026-12-31",
            "Series I Savings Bond Issue date 2026-07-01 $1,000.00 Composite rate 4.28%"]


def trade(number, **fields):
    empty = {"identifier": None, "quantity": None, "price": None, "principal": None, "face_value": None, "fees": None, "rate": None,
             "issue_date": None, "maturity_date": None}
    lines = fields.pop("lines", [number])
    return {**empty, **fields, "evidence": [quote for line in lines for quote in cite(line, TREASURY[line - 1])]}


def treasury_outputs():
    classified = {"document_type": "investment_confirmation", "evidence": cite(3, TREASURY[2]), "issuer": value("TreasuryDirect", 1, TREASURY[0]),
                  "document_date": value("2026-07-01", 4, TREASURY[3])}
    summary = {"institution": value("TreasuryDirect", 1, TREASURY[0]), "account_name": value("TreasuryDirect", 1, TREASURY[0]),
               "account_reference": value("7788", 2, TREASURY[1]), "trade_date": value("2026-07-01", 4, TREASURY[3]), "currency": value("USD", 4, TREASURY[3])}
    trades = [trade(5, lines=[5, 6], action="buy", description="26-Week Bill", identifier="912797AB1", instrument_class="treasury_bill", amount="9,750.00",
                    face_value="10,000.00", maturity_date="2026-12-31"),
              trade(7, action="buy", description="Series I Savings Bond", instrument_class="i_bond", amount="1,000.00", rate="4.28%", issue_date="2026-07-01")]
    return [classified, summary, {"trades": trades}]


def test_values_accrue_exactly_from_terms():
    # A bill bought at a discount rises in a straight line to its face value; a CD compounds at its APY; neither grows after maturity.
    assert accrued(975000, "2026-07-01", "2026-09-30", face_minor=1000000, maturity="2026-12-31") == 987432
    assert accrued(1000000, "2026-03-31", "2026-09-30", rate_bp=410, maturity="2027-03-31") == 1020350
    assert accrued(1000000, "2026-03-31", "2027-06-30", rate_bp=410, maturity="2027-03-31") == 1041000
    assert accrued(500000, "2026-09-30", "2026-09-01", rate_bp=410) == 500000
    assert (add_months("2026-08-31", 6), add_months("2024-02-29", 12)) == ("2027-02-28", "2025-02-28")


def test_a_treasury_confirmation_adds_holdings_that_count_once_confirmed(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, TREASURY)
    try:
        local_model["outputs"] = treasury_outputs()
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        publication = run["publication"]
        assert (publication["record_type"], publication["trades"], publication["review_status"]) == ("investment_confirmation", 2, "proposed")
        bond = run["result"]["normalized"]["trades"][1]
        assert (bond["rate_bp"], bond["redeemable_date"]) == (428, "2027-07-01")  # An I bond can be cashed a year after issue.
        investments = Investments(manager.store, date(2026, 9, 30))
        account = investments.get(publication["account_id"])
        assert account["kind"] == "treasury" and account["current"] is None  # Nothing counts until the confirmation is confirmed.
        ibond, bill = sorted(account["holdings"], key=lambda holding: holding["instrument_class"])
        assert ibond["redeemable_date"] == "2027-07-01"
        assert (bill["review_status"], bill["estimated"], bill["face"]["display"], bill["at_maturity"]["display"]) == ("proposed", True, "10,000.00 USD", "10,000.00 USD")
        [pending] = investments.pending()
        assert pending["record_type"] == "investment_confirmation" and pending["review_path"].endswith(f"/confirmations/{publication['id']}/review")
        assert [trade["type_label"] for trade in pending["trades"]] == ["Buy", "Buy"]
        investments.review_confirmation(publication["id"], "verified")
        account = investments.get(publication["account_id"])
        # Today's value is estimated from the terms: the bill 91 days along to its face value, the I bond from the published
        # rates (whole months of interest, as TreasuryDirect counts them).
        with manager.store.connection() as db:
            rates = Investments.ibond_rates(db)
        ibond_on = lambda day: ibond_value(100000, "2026-07-01", day, rates)
        expected = accrued(975000, "2026-07-01", "2026-09-30", face_minor=1000000, maturity="2026-12-31") + ibond_on("2026-09-30")
        assert (account["current"]["source"], account["current"]["value_minor"], account["current"]["as_of"]) == ("estimated", expected, "2026-09-30")
        assert investments.summary()["totals"][0]["estimated_accounts"] == 1
        assert {event["review_status"] for event in account["events"]} == {"verified"}
        # A re-extraction keeps the decision.
        local_model["outputs"] = treasury_outputs()
        assert extract(manager, doc, parse_id, force=True)["publication"]["status"] == "kept_reviewed"
        # Coming due: the bill within 90 days of mid-October; the I bond's lock ends later.
        later = Investments(manager.store, date(2026, 10, 15))
        assert [(row["name"], row["kind"], row["state"], row["amount"]["display"]) for row in later.maturities()] == [
            ("26-Week Bill", "matures", "due", "10,000.00 USD")]
        after = Investments(manager.store, date(2027, 1, 5))
        [due] = [row for row in after.maturities() if row["kind"] == "matures"]
        assert due["state"] == "matured"
        after.mark_matured(due["holding_id"], MaturedInput(outcome="cash"))
        account = after.get(publication["account_id"])
        assert [holding["name"] for holding in account["holdings"]] == ["Series I Savings Bond"]
        assert account["events"][0]["type_label"] == "Maturity" and account["events"][0]["amount"]["display"] == "10,000.00 USD"
        assert account["current"]["value_minor"] == ibond_on("2027-01-05")
        with pytest.raises(ValueError, match="already closed"):
            after.mark_matured(due["holding_id"], MaturedInput(outcome="cash"))
    finally:
        manager.close()


def test_holdings_the_user_enters_and_statements_win_over_estimates(tmp_path):
    from home_manager.library.storage import Store
    store = Store(tmp_path / "managed")
    try:
        inbox_scan(store, {"cd.png": b"cd statement"})
        investments = Investments(store, date(2026, 9, 30))
        bank = investments.add(AccountInput(name="Ally CDs", kind="cd", institution="Ally", currency="USD", value="0", as_of="2026-03-01"))
        investments.add_holding(bank["id"], HoldingInput(name="12-month CD", instrument_class="cd", principal="10000", issue_date="2026-03-31",
                                                         annual_rate_percent="4.10", maturity_date="2027-03-31"))
        account = investments.get(bank["id"])
        assert (account["current"]["source"], account["current"]["value"]["display"]) == ("estimated", "10,203.50 USD")
        [cd] = account["holdings"]
        assert (cd["at_maturity"]["display"], cd["review_status"]) == ("10,410.00 USD", "verified")
        with pytest.raises(ValueError, match="already has"):
            investments.add_holding(bank["id"], HoldingInput(name="12-month CD", instrument_class="cd", principal="1", issue_date="2026-03-31"))
        with pytest.raises(ValueError, match="after the issue date"):
            HoldingInput(name="x", instrument_class="cd", principal="1", issue_date="2026-03-31", maturity_date="2026-01-01")
        # A value typed for today wins over the estimate.
        investments.record_value(bank["id"], ValueInput(value="10300", as_of="2026-09-30"))
        assert investments.get(bank["id"])["current"]["source"] == "manual"
        # Renewing: the matured CD is closed, and the renewal is added as a new holding.
        later = Investments(store, date(2027, 4, 2))
        later.mark_matured(cd["id"], MaturedInput(outcome="rollover"))
        assert later.get(bank["id"])["events"][0]["note"] == "Renewed" and later.get(bank["id"])["current"]["value_minor"] == 0
    finally:
        store.close()


def test_the_forecast_pays_out_maturities_and_moves_contributions():
    base = {"currency": "USD", "cash": 0, "balances": [], "monthly_income": Decimal(0), "monthly_spending": {}, "bills": [], "notes": [],
            "history": {"start": "2026-03-01", "end": "2026-08-31", "months": 6, "months_with_data": 6},
            "assets": [{"name": "Ally CDs", "kind": "cd", "value_minor": 1100000, "value": None, "annual_rate_bp": 0, "annual_rate_percent": "0",
                        "monthly_payment_minor": None, "monthly_payment": None, "source": "investment",
                        "terms": [{"name": "12-month CD", "value_minor": 1000000, "maturity_month": "2026-12", "maturity_value_minor": 1010000, "to_cash": True}]},
                       {"name": "Work 401(k)", "kind": "401k", "value_minor": 0, "value": None, "annual_rate_bp": 0, "annual_rate_percent": "0",
                        "monthly_payment_minor": None, "monthly_payment": None, "source": "investment", "terms": [],
                        "payroll_monthly_minor": 50000, "personal_monthly_minor": 20000}]}
    result = project(base, ForecastInput(years=1, inflation_percent="0"), today=date(2026, 9, 28))
    months = {row["month"]: row for row in result["months"]}
    # October to December: the CD grows to its value at maturity, then pays out; the rest of the account stays.
    assert months["2026-11"]["matured"] == 0 and months["2026-12"]["matured"] == 1010000
    assert months["2026-12"]["assets"] == 100000 + 3 * 70000
    # Pay contributions leave cash alone; your own come out of it.
    assert months["2026-10"]["cash"] == -20000 and months["2026-12"]["cash"] == -60000 + 1010000
    assert result["years"][0]["contributions"] == 12 * 70000
