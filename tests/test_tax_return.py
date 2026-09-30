"""The year's return, estimated (docs/taxes.md): hand-worked returns on synthetic tables and figures (not any year's
real numbers, except where a test names them)."""

import json

from home_manager.finance.tax_return import Business, Job, Person, ReturnInput, Student, estimate, table_tax
from test_withholding import FEDERAL


def table(values, status="single"):
    return {**values, "brackets_json": json.dumps(values["brackets"]), "status": "verified", "filing_status": status}


SINGLE = table(FEDERAL)
JOINT = table({**FEDERAL, "standard_deduction_minor": 3000000, "additional_medicare_threshold_minor": 25000000,
               "brackets": [{"from_minor": 0, "rate_bp": 1000}, {"from_minor": 2385000, "rate_bp": 1200}, {"from_minor": 9695000, "rate_bp": 2200},
                            {"from_minor": 20670000, "rate_bp": 2400}, {"from_minor": 39460000, "rate_bp": 3200}]}, "married_joint")
CG = {"cg_zero_max": 4835000, "cg_fifteen_max": 53340000}


def value(**changes):
    return ReturnInput.model_validate({"year": 2026, "filing_status": "single", **changes})


def amounts(result):
    return {line["key"]: line["amount_minor"] for line in result["lines"]}


def test_the_tax_table_uses_the_middle_of_each_row():
    brackets = FEDERAL["brackets"]
    # 79,770 is in the 79,750–79,800 row: tax on 79,775 = 1,192.50 + 4,386.00 + 6,886.00 = 12,464.50, rounded to 12,465.
    assert table_tax(7977000, brackets) == 1246500
    assert (table_tax(400, brackets), table_tax(1200, brackets), table_tax(420000, brackets)) == (0, 100, 42300)
    # From 100,000 the worksheet is exact: 1,192.50 + 4,386 + 12,072.50 + 24% of 13,650.
    assert table_tax(11700000, brackets) == 2092700


def test_a_w2_only_return():
    # Tom's year: 94,770 of wages, 479.36 withheld from each of 26 paychecks.
    result = estimate(value(jobs=[Job(name="Acme", wages=9477000, federal_withheld=1246336)]), SINGLE, {})
    lines = amounts(result)
    assert (lines["agi"], lines["taxable_income"], lines["tax"], lines["total_tax"]) == (9477000, 7977000, 1246500, 1246500)
    # Withholding estimated the tax without the Tax Table's rounding: 1.64 is owed.
    assert (result["result_minor"], result["result"]["refund"], result["complete"]) == (-164, False, True)


def test_contract_work_adds_self_employment_tax_and_the_qbi_deduction():
    inputs = value(jobs=[Job(wages=5000000, ss_wages=5000000, medicare_wages=5000000, federal_withheld=400000)],
                   businesses=[Business(name="Contract work", income=3000000, expenses=500000)], federal_estimated_paid=300000)
    result = estimate(inputs, SINGLE, {"qbi_threshold": 19730000})
    lines = amounts(result)
    # SE: 25,000 × 92.35% = 23,087.50; 12.4% = 2,862.85 and 2.9% = 669.54: 3,532.39, half (1,766.20) deducted.
    assert (lines["other_se"], lines["adjust_se_half"]) == (353239, -176620)
    assert lines["agi"] == 7500000 - 176620
    # QBI: 20% of 23,233.80 = 4,646.76; taxable 53,587.04 is in the 53,550–53,600 row: 6,700.50 rounds to 6,701.
    assert (lines["qbi"], lines["taxable_income"], lines["tax"]) == (-464676, 5358704, 670100)
    assert (lines["total_tax"], lines["total_payments"], result["result_minor"]) == (670100 + 353239, 700000, 700000 - 670100 - 353239)


def test_qualified_dividends_and_long_term_gains_at_zero_and_fifteen_percent():
    below = estimate(value(jobs=[Job(wages=4000000)], ordinary_dividends=200000, qualified_dividends=200000, long_term_gain=1000000), SINGLE, CG)
    # Taxable 37,000: 25,000 ordinary (2,765 from the table) and all 12,000 of gains and dividends at 0%.
    assert amounts(below)["tax"] == 276500 and "12,000.00 USD at 0%" in next(line["how"] for line in below["lines"] if line["key"] == "tax")
    across = estimate(value(jobs=[Job(wages=6000000)], long_term_gain=2000000), SINGLE, CG)
    # Taxable 65,000: ordinary 45,000 (5,165); 3,350 at 0% up to 48,350; 16,650 at 15% (2,497.50).
    assert amounts(across)["tax"] == 516500 + 249750


def test_itemized_beats_the_standard_deduction_and_salt_is_capped():
    figures = {"salt_cap": 4000000, "salt_phaseout_start": 50000000}
    result = estimate(value(jobs=[Job(wages=15000000)], state_local_tax=1200000, property_tax=800000, mortgage_interest=1000000, charity=300000,
                            medical=500000), SINGLE, figures)
    lines = amounts(result)
    # Medical under 7.5% of AGI counts nothing; 20,000 of SALT + 10,000 + 3,000 = 33,000 against 15,000.
    assert (lines["deduction"], lines["taxable_income"], lines["tax"]) == (-3300000, 11700000, 2092700)
    # Without the year's SALT limit it's counted in full, and the missing figure is named.
    uncapped = estimate(value(jobs=[Job(wages=15000000)], state_local_tax=6000000), SINGLE, {})
    assert amounts(uncapped)["deduction"] == -6000000 and "salt_cap" in uncapped["missing"] and not uncapped["complete"]


def test_a_couples_child_tax_credit_phases_out_and_additional_medicare_applies():
    jobs = [Job(owner="Ana", wages=21000000, medicare_wages=21000000), Job(owner="Tom", wages=21000000, medicare_wages=21000000)]
    result = estimate(value(filing_status="married_joint", jobs=jobs, qualifying_children=2), JOINT, {"ctc_per_child": 220000, "ctc_refundable_max": 170000})
    lines = amounts(result)
    # Taxable 390,000: 2,385 + 8,772 + 24,145 + 43,992 = 79,294. Credit 4,400 less $50 per $1,000 above 400,000 (20 × 50).
    assert (lines["tax"], lines["credit_child"]) == (7929400, -340000)
    # Additional Medicare: 0.9% of the 170,000 of Medicare wages above 250,000.
    assert (lines["other_additional_medicare"], lines["total_tax"]) == (153000, 7929400 - 340000 + 153000)


def test_social_security_benefits_and_the_deductions_at_65():
    inputs = value(people=[Person(name="Grace", birth_year=1956)], social_security_benefits=3000000, retirement_distributions=2000000, interest=100000)
    result = estimate(inputs, SINGLE, {"additional_standard_65": 200000, "senior_deduction": 600000})
    lines = amounts(result)
    # 15,000 half of benefits + 21,000 = 36,000; 11,000 above 25,000: 4,500 (half of the first 9,000) + 85% of 2,000 = 6,200 taxable.
    assert lines["social_security"] == 620000
    # 15,000 + 2,000 standard, 6,000 senior; taxable 4,200 in the 4,200–4,250 row: 422.50 rounds to 423.
    assert (lines["deduction"], lines["senior"], lines["taxable_income"], lines["tax"]) == (-1700000, -600000, 420000, 42300)


def test_credits_from_spending_and_missing_figures_are_named():
    inputs = value(jobs=[Job(wages=6000000)], dependent_care_expenses=500000, dependent_care_people=1, students=[Student(expenses=400000)],
                   ordinary_dividends=100000, qualified_dividends=100000)
    result = estimate(inputs, SINGLE, {"dc_limit_one": 300000, "dc_rate_high": 3500, "dc_rate_low": 2000})
    lines = amounts(result)
    # Dependent care: 3,000 counted at 20% (AGI far above 15,000). Education: 2,000 + 25% of 2,000 = 2,500, 40% refundable.
    assert (lines["credit_dependent_care"], lines["credit_education"], lines["pay_aotc"]) == (-60000, -150000, 100000)
    # No capital-gains thresholds: the dividends are taxed as ordinary income, and that is said.
    assert "cg_zero_max" in result["missing"] and any("taxed as ordinary income" in note for note in result["notes"])


def test_no_confirmed_federal_table_no_estimate():
    result = estimate(value(), None, {})
    assert result["result_minor"] is None and result["missing"] == ["federal_table"]
