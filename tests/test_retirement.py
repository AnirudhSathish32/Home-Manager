"""Required minimum distributions and retirement withdrawals in the forecast (docs/investments.md, docs/forecast.md). Synthetic data only."""

from datetime import date
from decimal import Decimal

import pytest

from conftest import inbox_scan
from home_manager.finance.forecast import ForecastInput, RetirementPlan, project
from home_manager.finance.investments import AccountInput, Investments, ValueInput
from home_manager.finance.ledger import HouseholdConfig
from home_manager.finance.retirement import divisor, required, rmd_start_age
from home_manager.library.storage import Store


def test_the_uniform_lifetime_table_and_start_ages():
    assert [rmd_start_age(year) for year in (1949, 1950, 1951, 1959, 1960, 1975)] == [72, 72, 73, 73, 75, 75]
    assert (divisor(72), divisor(73), divisor(100), divisor(120), divisor(125), divisor(71)) == (
        Decimal("27.4"), Decimal("26.5"), Decimal("6.4"), Decimal("2.0"), Decimal("2.0"), None)
    assert required(2650000, 1953, 2026) == 100000  # Age 73: 26,500.00 / 26.5.
    assert required(2650000, 1953, 2025) == 0 and required(2650000, 1960, 2033) == 0  # Before 73, and before 75.
    assert required(1000000, 1953, 2026) == 37736  # 10,000.00 / 26.5 = 377.358… rounds half-even.
    with pytest.raises(ValueError):
        HouseholdConfig(birth_year=date.today().year + 1)


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"x.png": b"x"})
    try:
        yield store
    finally:
        store.close()


def test_this_years_required_distributions(store):
    investments = Investments(store, date(2026, 9, 28))
    ira = investments.add(AccountInput(name="Rollover IRA", kind="ira", currency="USD", value="26500", as_of="2025-12-31"))
    investments.add(AccountInput(name="Old 401(k)", kind="401k", currency="USD", value="10000", as_of="2025-10-31"))
    investments.add(AccountInput(name="Roth IRA", kind="roth_ira", currency="USD", value="50000", as_of="2025-12-31"))
    investments.add(AccountInput(name="HSA", kind="hsa", currency="USD", value="5000", as_of="2025-12-31"))
    investments.record_value(ira["id"], ValueInput(value="30000", as_of="2026-06-30"))
    with store.connection() as db:
        db.execute("INSERT INTO investment_events(account_id,event_date,event_type,amount_minor,review_status,created_at) VALUES(?,'2026-03-01','withdrawal',40000,'verified','t')",
                   (ira["id"],))
    assert investments.required_distributions(2026, None) == {"year": 2026, "birth_year": None, "accounts": [], "has_accounts": True}
    later = investments.required_distributions(2026, 1970)
    assert (later["begins_later"], later["first_year"], later["start_age"], later["accounts"]) == (True, 2045, 75, [])
    due = investments.required_distributions(2026, 1953)
    rows = {row["name"]: row for row in due["accounts"]}
    assert set(rows) == {"Rollover IRA", "Old 401(k)"}  # A Roth IRA and an HSA have none.
    first = rows["Rollover IRA"]
    # The balance at the end of last year, not today's; the first year's deadline is April 1 of the next.
    assert (first["balance"]["display"], first["divisor"], first["required"]["display"], first["taken"]["display"], first["left"]["display"],
            first["deadline"], first["status"], first["stale"]) == ("26,500.00 USD", "26.5", "1,000.00 USD", "400.00 USD", "600.00 USD", "2027-04-01", "due", False)
    assert (rows["Old 401(k)"]["stale"], rows["Old 401(k)"]["balance_as_of"]) == (True, "2025-10-31")
    assert investments.required_distributions(2027, 1953)["accounts"][0]["deadline"] == "2027-12-31"


def base(assets, cash=0, income=500000, pay=400000, spending=300000):
    return {"currency": "USD", "cash": cash, "balances": [], "monthly_income": Decimal(income), "monthly_pay": Decimal(pay),
            "monthly_spending": {"groceries": Decimal(spending)}, "bills": [], "notes": [],
            "history": {"start": "2026-03-01", "end": "2026-08-31", "months": 6, "months_with_data": 6},
            "assets": [{"name": name, "kind": kind, "value_minor": value, "value": None, "annual_rate_bp": 0, "annual_rate_percent": "0",
                        "monthly_payment_minor": None, "monthly_payment": None, "source": "investment", "terms": [], "tax_treatment": tax,
                        "payroll_monthly_minor": payroll, "personal_monthly_minor": 0}
                       for name, kind, value, tax, payroll in assets]}


TODAY = date(2026, 9, 28)  # The projection starts in October 2026.


def test_fixed_withdrawals_draw_taxable_money_first_and_gross_up_tax_deferred():
    plan = RetirementPlan(start_month="2026-10", mode="fixed", monthly_amount="2000", tax_percent="20")
    result = project(base([("Brokerage", "brokerage", 300000, "taxable", 0), ("IRA", "ira", 1000000, "tax_deferred", 0),
                           ("Work 401(k)", "401k", 0, "tax_deferred", 50000)]),
                     ForecastInput(years=1, inflation_percent="0", retirement=plan), today=TODAY)
    october, november, december = result["months"][:3]
    # Pay stops (5,000 less 4,000 take-home leaves 1,000) and so do contributions from pay.
    assert (october["income"], october["contributions"]) == (100000, 0)
    assert (october["withdrawals"], october["withdrawal_tax"]) == (200000, 0)  # All from the brokerage.
    # 1,000 left in the brokerage, then 1,000 after tax from the IRA: 1,250 taken, 250 tax.
    assert (november["withdrawals"], november["withdrawal_tax"]) == (200000, 25000)
    assert (december["withdrawals"], december["withdrawal_tax"]) == (200000, 50000)
    # The IRA gives 2,500 a month (2,000 after tax) until March, when its last 1,250 gives 1,000.
    assert [row["withdrawals"] for row in result["months"][3:6]] == [200000, 200000, 100000]
    assert any("run out in 2027-03" in note for note in result["notes"])
    # Before retirement nothing is drawn, and pay stays.
    later = project(base([("IRA", "ira", 1000000, "tax_deferred", 0)]), ForecastInput(years=1, inflation_percent="0",
                    retirement=RetirementPlan(start_month="2027-03", mode="fixed", monthly_amount="100")), today=TODAY)
    assert later["months"][0]["income"] == 500000 and later["months"][0]["withdrawals"] == 0 and later["months"][5]["withdrawals"] == 10000


def test_shortfall_withdrawals_keep_cash_at_the_floor_until_money_runs_out():
    plan = RetirementPlan(start_month="2026-10", mode="shortfall", cash_floor="1000")
    result = project(base([("Brokerage", "brokerage", 800000, "taxable", 0)]), ForecastInput(years=1, inflation_percent="0", retirement=plan), today=TODAY)
    months = result["months"]
    # October: 1,000 income less 3,000 spending leaves -2,000; 3,000 is drawn to reach the 1,000 floor. Then 2,000 a month.
    assert [(row["withdrawals"], row["cash"]) for row in months[:4]] == [(300000, 100000), (200000, 100000), (200000, 100000), (100000, 0)]
    assert "Investments run out in 2027-01: from then on the planned withdrawals can't be met." in result["notes"]
    assert project(base([("Brokerage", "brokerage", 800000, "taxable", 0)]), ForecastInput(years=1, inflation_percent="0", retirement=plan), today=TODAY) == result
    with pytest.raises(ValueError, match="monthly amount"):
        RetirementPlan(start_month="2026-10", mode="fixed")


def test_december_takes_the_required_distribution_even_before_retirement():
    assets = [("IRA", "ira", 100000000, "tax_deferred", 0), ("Roth IRA", "roth_ira", 50000000, "tax_free", 0)]
    result = project(base(assets, pay=0), ForecastInput(years=2, inflation_percent="0"), today=TODAY, birth_year=1953)
    december = next(row for row in result["months"] if row["month"] == "2026-12")
    # Age 73: 1,000,000.00 / 26.5, from the IRA only; the Roth IRA has none.
    assert (december["rmd"], december["withdrawals"]) == (3773585, 3773585)
    next_december = next(row for row in result["months"] if row["month"] == "2027-12")
    assert next_december["rmd"] == int((Decimal(100000000 - 3773585) / Decimal("25.5")).to_integral_value())  # Age 74, from last December's balance.
    assert any("begin in 2026 (age 73)" in note for note in result["notes"])
    # A planned withdrawal from the IRA that already covers it leaves nothing more to take.
    plan = RetirementPlan(start_month="2026-10", mode="fixed", monthly_amount="20000")
    covered = project(base([("IRA", "ira", 100000000, "tax_deferred", 0)], pay=0), ForecastInput(years=1, inflation_percent="0", retirement=plan),
                      today=TODAY, birth_year=1953)
    assert next(row for row in covered["months"] if row["month"] == "2026-12")["rmd"] == 0
    assert any("birth year" in note.lower() or "born" in note for note in project(base(assets), ForecastInput(years=1), today=TODAY)["notes"])
