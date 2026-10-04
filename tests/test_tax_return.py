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


def test_the_simplified_state_return_leaves_out_treasury_interest():
    georgia = {"status": "verified", "standard_deduction_minor": 1200000, "brackets_json": json.dumps([{"from_minor": 0, "rate_bp": 519}])}
    found = state_return(value(state="GA", jobs=[Job(wages=6000000, state_withheld=250000)], interest=100000, us_obligation_interest=40000), 6100000, georgia)
    # 61,000 less 400 of Treasury interest and the 12,000 deduction: 48,600 at 5.19% = 2,522.34; 2,500 withheld.
    assert (found["taxable_minor"], found["tax_minor"], found["result_minor"]) == (4860000, 252234, -2234)
    assert "Simplified" in found["note"]
    waiting = state_return(value(state="GA"), 0, {**georgia, "status": "proposed"})
    assert not waiting["complete"] and "isn't confirmed" in waiting["note"]
    assert state_return(value(), 0, georgia) is None
