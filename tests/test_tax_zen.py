"""Tax Zen (docs/taxes.md): the W-4 entries, or advance tax, that bring the year's return to $0. Synthetic tables only."""

from datetime import date

from home_manager.finance.tax_return import Job, ReturnInput, estimate
from home_manager.finance.tax_zen import advance_tax, advise, due_dates, withholding
from test_tax_return import SINGLE

FEDERAL = {**SINGLE, "sources_json": "[]"}
# Tom's paycheck: 3,645 of income-tax wages every two weeks, 479.36 withheld; ten paychecks left this year.
JOB = {"key": "employer-1", "name": "Acme", "paychecks_left": 10, "pay_frequency": 26, "work_state": None,
       "per_check": {"wages": 364500, "fica": 388500, "federal": 47936, "state": 0, "medicare": 5633},
       "values": {"federal_withheld": 1246336}}


def year(**changes):
    value = ReturnInput.model_validate({"year": 2026, "filing_status": "single", "jobs": [Job(name="Acme", wages=9477000, federal_withheld=1246336)], **changes})
    return estimate(value, FEDERAL, {})


def year_end(job, result, w4):
    """What the return comes to when the paychecks left withhold under these W-4 entries (the stub's offset kept)."""
    offset = job["per_check"]["federal"] - withholding(FEDERAL, job["per_check"]["wages"], job["pay_frequency"], {})
    return result + job["paychecks_left"] * (withholding(FEDERAL, job["per_check"]["wages"], job["pay_frequency"], w4) + offset - job["per_check"]["federal"])


def test_withholding_follows_pub_15t_for_each_w4_entry():
    wages, checks = 364500, 26
    assert withholding(FEDERAL, wages, checks, {}) == 47936
    assert withholding(FEDERAL, wages, checks, {"extra": 2500}) == 47936 + 2500
    # 4(a) of 1,000 adds 1,000 × 22% a year: 8.46 a paycheck; 4(b) of 1,000 takes it off; Step 3 credits of 2,600 take 100 a paycheck.
    assert withholding(FEDERAL, wages, checks, {"other_income": 100000}) == 48782
    assert withholding(FEDERAL, wages, checks, {"deductions": 100000}) == 47090
    assert withholding(FEDERAL, wages, checks, {"credits": 260000}) == 37936
    assert withholding(FEDERAL, wages, checks, {"step2": True}) == 66801


def test_owing_is_closed_with_4a_or_4c():
    estimate_ = year(interest=500000)  # 5,000 of interest nobody withholds on.
    assert estimate_["result_minor"] < -100000
    zen = advise(estimate_, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    rest = zen["job"]["rest"]
    assert rest["field"] == "4(a)" and not zen["zen"]
    # The whole-dollar 4(a) lands within a dollar of $0, and the page's year-end agrees with working it out again.
    assert abs(rest["year_end_minor"]) < 100 and rest["year_end_minor"] == year_end(JOB, estimate_["result_minor"], {"other_income": rest["amount"]})
    # The same with a fixed extra per paycheck (4(c)), rounded up to the cent.
    extra = zen["job"]["extra"]
    assert 0 <= extra["year_end_minor"] < 10 and extra["per_check_minor"] * 10 >= -estimate_["result_minor"]
    # From January: a full year at this paycheck. 4(a) is about the interest itself (it's taxed at the same 22%).
    january = zen["job"]["january"]
    assert january["field"] == "4(a)" and abs(january["amount"] - 500000) < 20000 and abs(january["year_end_minor"]) < 100


def test_a_refund_is_closed_with_4b_and_payrolls_own_withholding_is_kept():
    job = {**JOB, "per_check": {**JOB["per_check"], "federal": 57936}, "values": {"federal_withheld": 1246336 + 260000}}
    estimate_ = year(jobs=[Job(wages=9477000, federal_withheld=1246336 + 260000)])  # Payroll takes 100 more a paycheck than Pub 15-T says.
    zen = advise(estimate_, [job], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    rest = zen["job"]["rest"]
    assert zen["job"]["offset_minor"] == 10000 and rest["field"] == "4(b)" and abs(rest["year_end_minor"]) < 100
    assert "extra" not in zen["job"]  # A fixed extra can't lower withholding.
    # A refund no W-4 can close with ten paychecks left: 4(b) can't make withholding negative.
    big = year(jobs=[Job(wages=9477000, federal_withheld=1246336 + 3000000)])
    unreachable = advise(big, [{**job, "values": {"federal_withheld": 1246336 + 3000000}}], FEDERAL, {}, [], 2026, date(2026, 9, 30))["job"]["rest"]
    assert unreachable["unreachable"] and unreachable["field"] == "4(b)"


def test_zen_is_within_a_dollar():
    close = year(jobs=[Job(wages=9477000, federal_withheld=1246500)])
    zen = advise(close, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert zen["zen"] and zen["result_minor"] == 0 and zen["job"]["rest"]["field"] is None


def test_a_planned_paycheck_at_tax_time():
    from home_manager.finance.ledger import HouseholdConfig
    from home_manager.finance.paycheck import PaycheckInput, calculate
    from home_manager.finance.tax_zen import plan_tax_zen
    from test_paycheck import TOM
    value = PaycheckInput.model_validate({**TOM, "work_state": "TX", "post_tax": [], "match_percent": None, "match_limit_percent": None})
    result = calculate(value, {"US": FEDERAL})
    empty = {"values": {}, "sources": {}, "jobs": [], "businesses": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
    zen = plan_tax_zen([("Tom", result, value, True)], empty, HouseholdConfig(), "single", 2026, lambda codes: {"US": FEDERAL}, {})
    # 26 × 479.36 withheld against 12,465 of tax (the Tax Table's rounding): 1.64 owed, closed by a few dollars of 4(a).
    assert (zen["result_minor"], zen["job"], zen["w4"]["field"]) == (-164, "Tom", "4(a)")
    assert 0 < zen["w4"]["amount"] < 2000 and abs(zen["w4"]["year_end_minor"]) < 100
    # With 5,000 of interest from this year's records on the same return, the answer is about that much 4(a).
    interest = {**empty, "values": {"interest": 500000}}
    with_interest = plan_tax_zen([("Tom", result, value, True)], interest, HouseholdConfig(), "single", 2026, lambda codes: {"US": FEDERAL}, {})
    assert abs(with_interest["w4"]["amount"] - 500000) < 20000


def test_advance_tax_quarters_for_income_without_withholding():
    assert [day.isoformat() for day in due_dates(2028)] == ["2028-04-17", "2028-06-15", "2028-09-15", "2029-01-15"]  # Apr 15, 2028 is a Saturday.
    plan = advance_tax(2026, date(2026, 7, 1), 800000, [{"date": "2026-04-10", "amount_minor": 200000}], 720000, 800000)
    # Paid 2,000 by the April date; 6,000 left over the September and January dates. June's date has passed short of the safe harbor.
    assert [(row["quarter"], row["paid_minor"], row["pay_minor"]) for row in plan["quarters"]] == [(1, 200000, 0), (2, 0, 0), (3, 0, 300000), (4, 0, 300000)]
    assert plan["left_minor"] == 600000 and any("Form 2210" in note for note in plan["notes"])
    # Contract work only: no job to change, so the answer is the quarters.
    contract = estimate(ReturnInput(year=2026, filing_status="single", other_income=5000000), FEDERAL, {})
    zen = advise(contract, [], FEDERAL, {}, [], 2026, date(2026, 3, 1))
    assert "job" not in zen and zen["advance"]["left_minor"] == contract["total_tax_minor"]
    assert sum(row["pay_minor"] for row in zen["advance"]["quarters"]) == contract["total_tax_minor"]
    # Last year's tax sets the safe harbor when it's lower (100% of it, 110% above $150,000 of AGI).
    prior = advise(contract, [], FEDERAL, {}, [], 2026, date(2026, 3, 1), prior={"tax_minor": 300000, "agi_minor": 4000000})
    assert prior["advance"]["safe_harbor_minor"] == 300000
