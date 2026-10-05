"""The tax profile and the simplified state return (finance/tax_return.py), and the synthetic federal tax tables other tax
tests confirm for pay stub withholding (Pub 15-T). The federal return itself is the tax engine's: tests/test_tax_engines.py."""

import json

from home_manager.finance.tax_return import Job, ReturnInput, bracket_tax, marginal, state_return
from test_withholding import FEDERAL


def table(values, status="single"):
    return {**values, "brackets_json": json.dumps(values["brackets"]), "status": "verified", "filing_status": status}


SINGLE = table(FEDERAL)
JOINT = table({**FEDERAL, "standard_deduction_minor": 3000000, "additional_medicare_threshold_minor": 25000000,
               "brackets": [{"from_minor": 0, "rate_bp": 1000}, {"from_minor": 2385000, "rate_bp": 1200}, {"from_minor": 9695000, "rate_bp": 2200},
                            {"from_minor": 20670000, "rate_bp": 2400}, {"from_minor": 39460000, "rate_bp": 3200}]}, "married_joint")


def value(**changes):
    return ReturnInput.model_validate({"year": 2026, "filing_status": "single", **changes})


def test_bracket_tax_is_exact_and_the_marginal_rate_is_the_next_dollars():
    brackets = FEDERAL["brackets"]
    # 1,192.50 + 4,386 + 12,072.50 + 24% of 13,650 = 20,927.
    assert bracket_tax(11700000, brackets) == 2092700
    assert (marginal(11700000, brackets), marginal(0, brackets)) == (2400, 1000)


def test_the_pay_stub_the_planner_the_state_return_and_engine_2_agree_on_one_income():
    """docs/open-work.md "UI redesign" 1: bracket tax and the marginal rate are worked out once (tax_return.bracket_slices)."""
    from decimal import Decimal

    from home_manager.finance.engines.taxcalc import schedule
    from home_manager.finance.paycheck import PaycheckInput, calculate
    from home_manager.finance.paystub import income_tax
    from test_paycheck import TOM
    confirmed = {**SINGLE, "sources_json": "[]"}
    planned = calculate(PaycheckInput.model_validate({**TOM, "work_state": "TX"}), {"US": confirmed})
    federal = next(part for part in planned["jurisdictions"] if part["jurisdiction"] == "US")
    annual, taxable = federal["annual_wages_minor"], federal["taxable_minor"]
    stub = income_tax("US", confirmed, annual, 1, None)
    # The same table as a state's: the state return on the same income.
    state = state_return(value(state="GA"), annual, SINGLE)
    # Engine 2's rate schedule over the same brackets (dollars, fractions).
    starts = [bracket["from_minor"] for bracket in FEDERAL["brackets"]]
    policy = {**{f"II_brk{number}": (starts[number] if number < len(starts) else 10**12) / 100 for number in range(1, 7)},
              **{f"II_rt{number}": FEDERAL["brackets"][min(number, len(starts)) - 1]["rate_bp"] / 10000 for number in range(1, 8)}}
    engine = int((schedule(Decimal(taxable) / 100, policy) * 100).to_integral_value())
    assert federal["annual_tax_minor"] == stub["annual_tax_minor"] == state["tax_minor"] == engine == round(bracket_tax(taxable, FEDERAL["brackets"]))
    assert federal["top_rate_bp"] == stub["top_rate_bp"] == marginal(taxable, FEDERAL["brackets"])
    # Rates reach the pages as percent text, never divided in the browser (docs/open-work.md "UI redesign" 2).
    from home_manager.core.money import percent_text
    assert [percent_text(bp) for bp in (2200, 519, 620, 1000, 0, None)] == ["22", "5.19", "6.2", "10", "0", None]
    assert (federal["top_rate_percent"], planned["rates"]["federal_marginal_percent"]) == ("22", "22")
    assert planned["rates"]["take_home_percent"] == percent_text(planned["rates"]["take_home_bp"])
    # Still inside the standard deduction, the next dollar is untaxed.
    assert income_tax("US", confirmed, 1000000, 1, None)["top_rate_bp"] == 0


def test_the_simplified_state_return_leaves_out_treasury_interest():
    georgia = {"status": "verified", "standard_deduction_minor": 1200000, "brackets_json": json.dumps([{"from_minor": 0, "rate_bp": 519}])}
    found = state_return(value(state="GA", jobs=[Job(wages=6000000, state_withheld=250000)], interest=100000, us_obligation_interest=40000), 6100000, georgia)
    # 61,000 less 400 of Treasury interest and the 12,000 deduction: 48,600 at 5.19% = 2,522.34; 2,500 withheld.
    assert (found["taxable_minor"], found["tax_minor"], found["result_minor"]) == (4860000, 252234, -2234)
    assert "Simplified" in found["note"]
    waiting = state_return(value(state="GA"), 0, {**georgia, "status": "proposed"})
    assert not waiting["complete"] and "isn't confirmed" in waiting["note"]
    assert state_return(value(), 0, georgia) is None
