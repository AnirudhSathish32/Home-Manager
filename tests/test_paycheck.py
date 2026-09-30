"""The paycheck planner: a paycheck worked out forward from gross pay (docs/what-if.md). The tables are synthetic, the same
as test_withholding.py's, so the planner and the pay stub explanation can be checked against each other."""

from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from home_manager.app.api import create_app
from home_manager.finance.paycheck import PaycheckInput, calculate, from_stub
from home_manager.finance.paystub import explain
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_withholding import FEDERAL, GEORGIA, LINES, RECORD, confirmed

# 104,000 a year every two weeks = 4,000.00 a paycheck; the same deductions as the pay stub in test_withholding.py.
TOM = {"year": 2026, "filing_status": "single", "work_state": "GA", "pay_frequency": 26, "annual_salary": "104000",
       "pre_tax": [{"category": "retirement_pretax", "percent": "6"}, {"category": "health", "amount": "100"},
                   {"category": "dental", "amount": "10"}, {"category": "vision", "amount": "5"}],
       "post_tax": [{"category": "life_insurance", "amount": "2.50"}],
       "match_percent": "100", "match_limit_percent": "4"}


@pytest.fixture
def tables(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        service = TaxTables(store)
        confirmed(service, "US", FEDERAL)
        confirmed(service, "GA", GEORGIA)
        yield service
    finally:
        store.close()


def plan(tables, **changes):
    value = PaycheckInput.model_validate({**TOM, **changes})
    return calculate(value, tables.for_year(2026, ["US", *([value.work_state] if value.work_state else [])], value.filing_status))


def lines_of(result, group):
    found = next((item for item in result["groups"] if item["group"] == group), None)
    return [(line["category"], line["per_check_minor"], line["annual_minor"]) for line in found["lines"]] if found else []


def test_gross_to_net_every_line(tables):
    result = plan(tables)
    assert result["complete"] and result["frequency_name"] == "every two weeks"
    assert lines_of(result, "earnings") == [("regular_pay", 400000, 10400000)]
    # A 401(k) lowers income-tax wages only; health, dental and vision also lower Social Security and Medicare wages.
    assert lines_of(result, "pre_tax") == [("retirement_pretax", 24000, 624000), ("health", 10000, 260000), ("dental", 1000, 26000), ("vision", 500, 13000)]
    assert result["groups"][1]["lines"][0]["how"] == "6% of gross pay; lowers income-tax wages only"
    assert result["wages"]["income_tax"] == {"per_check_minor": 364500, "annual_minor": 9477000, "display": {
        "per_check_minor": "3,645.00 USD", "annual_minor": "94,770.00 USD"}}
    assert result["wages"]["fica"]["per_check_minor"] == 388500
    # The same figures the pay stub explanation gives for this paycheck: 479.36 federal, 159.23 Georgia, 240.87 and 56.33 FICA.
    assert lines_of(result, "tax") == [("federal_income_tax", 47936, 1246336), ("state_income_tax", 15923, 413998),
                                       ("social_security", 24087, 626262), ("medicare", 5633, 146458)]
    stub = explain(RECORD, LINES, tables.for_year(2026, ["US", "GA"], "single"), "single")
    assert [part["estimate_minor"] for part in stub["jurisdictions"]] == [47936, 15923]
    tax = next(item for item in result["groups"] if item["group"] == "tax")
    assert (tax["fica"]["per_check_minor"], tax["fica"]["annual_minor"]) == (29720, 772720)
    assert lines_of(result, "post_tax") == [("life_insurance", 250, 6500)]
    # The match: 100% of what goes in, up to 4% of 4,000.00 = 160.00; it is paid beside pay, not taken from it.
    assert lines_of(result, "employer_paid") == [("employer_match", 16000, 416000)]
    # 4,000 - 355 - 479.36 - 159.23 - 240.87 - 56.33 - 2.50 = 2,706.71.
    assert result["net"] == {"per_check_minor": 270671, "annual_minor": 7037446, "monthly_minor": 586454, "regular_monthly_minor": 586454, "display": {
        "per_check_minor": "2,706.71 USD", "annual_minor": "70,374.46 USD", "monthly_minor": "5,864.54 USD", "regular_monthly_minor": "5,864.54 USD"}}
    assert result["contributions"] == {"retirement_per_check_minor": 40000, "hsa_per_check_minor": 0, "display": {
        "retirement_per_check_minor": "400.00 USD", "hsa_per_check_minor": "0.00 USD"}}
    assert len(result["schedule"]) == 1 and result["rates"]["federal_marginal_bp"] == 2200
    federal = result["jurisdictions"][0]
    assert federal["table_deduction_minor"] == 1500000 and not federal["deduction_overridden"]


def test_social_security_stops_at_the_wage_base_during_the_year(tables):
    tables.review(tables.for_year(2026, ["US"], "single")["US"]["id"], "rejected")
    confirmed(tables, "US", {**FEDERAL, "ss_wage_base_minor": 10000000})
    result = plan(tables)
    # 25 paychecks of 3,885.00 = 97,125.00; the 26th has only 2,875.00 under the 100,000.00 base: 178.25.
    assert [(part["from_check"], part["to_check"], part["social_security_minor"], part["net_minor"]) for part in result["schedule"]] == [
        (1, 25, 24087, 270671), (26, 26, 17825, 276933)]
    assert lines_of(result, "tax")[2] == ("social_security", 24087, 24087 * 25 + 17825)
    assert result["net"]["annual_minor"] == 270671 * 25 + 276933
    assert any("Some paychecks differ from a regular one" in note for note in result["notes"])


def test_w4_step2_uses_the_half_size_schedule(tables):
    # Half of every threshold, in whole dollars: 7,500 untaxed, then brackets from 13,463 (5,963 above it), 31,738 and 59,175.
    federal = plan(tables, federal_step2=True)["jurisdictions"][0]
    assert [(bucket["label"], bucket["from_minor"], bucket["tax_minor"]) for bucket in federal["buckets"]] == [
        ("Half the standard deduction (W-4 Step 2)", 0, 0), ("10%", 750000, 59630), ("12%", 1346300, 219300), ("22%", 3173800, 603614),
        ("24%", 5917500, 854280)]
    # 94,770 of wages: 17,368.24 a year over 26 paychecks = 668.01, against 479.36 without the box.
    assert (federal["annual_tax_minor"], federal["estimate_minor"], federal["step2"]) == (1736824, 66801, True)


def test_state_credits_come_off_the_states_year(tables):
    # Georgia: 79,770 × 5.19% = 4,140.06, less 100 of credits = 4,040.06 a year, 155.39 a paycheck.
    result = plan(tables, state_credits="100")
    georgia = result["jurisdictions"][1]
    assert (georgia["credits_minor"], georgia["annual_tax_minor"], georgia["estimate_minor"]) == (10000, 404006, 15539)
    assert "after 100.00 USD of credits" in lines_of_how(result, "state_income_tax")


def lines_of_how(result, category):
    return next(line["how"] for group in result["groups"] for line in group["lines"] if line["category"] == category)


def test_a_bonus_is_withheld_at_the_supplemental_rate_in_its_paycheck(tables):
    result = plan(tables, bonuses=[{"label": "Year-end", "amount": "10000", "month": 12}], state_supplemental_percent="5.19")
    [bonus] = result["bonuses"]
    # December's first paycheck is the 24th of 26. The 401(k) takes 6% (600.00); 9,400 is taxed: 22% federal (2,068.00),
    # 5.19% Georgia (487.86); Social Security and Medicare on all 10,000 (620.00 + 145.00). The match adds 4% of 10,000.
    assert (bonus["check"], bonus["taxable_minor"], bonus["federal_minor"], bonus["state_minor"], bonus["fica_minor"], bonus["match_minor"]) == (
        24, 940000, 206800, 48786, 76500, 40000)
    assert (bonus["net_minor"], bonus["retirement_minor"]) == (607914, 100000)
    checks = {part["from_check"]: part for part in result["schedule"]}
    assert checks[24]["to_check"] == 24 and checks[24]["bonus_minor"] == 1000000 and checks[24]["net_minor"] == 270671 + 607914
    assert result["net"]["per_check_minor"] == 270671 and result["net"]["annual_minor"] == 7037446 + 607914
    assert result["net"]["regular_monthly_minor"] == 586454  # What the forecast pays monthly; the bonus comes in its month.
    earnings = lines_of(result, "earnings")
    assert earnings[1] == ("supplemental", None, 1000000)
    assert lines_of(result, "pre_tax")[0] == ("retirement_pretax", 24000, 624000 + 60000)
    assert lines_of(result, "tax")[0] == ("federal_income_tax", 47936, 1246336 + 206800)
    assert result["wages"]["fica"]["annual_minor"] == 10101000 + 1000000


def test_bonuses_above_a_million_are_withheld_at_37_percent(tables):
    result = plan(tables, bonuses=[{"amount": "1200000", "month": 6}], state_supplemental_percent="5")
    [bonus] = result["bonuses"]
    # 1,200,000 less the 6% 401(k) = 1,128,000 taxed: 22% of the first 1,000,000 and 37% of the other 128,000.
    assert (bonus["taxable_minor"], bonus["federal_minor"]) == (112800000, 22000000 + 4736000)
    # Social Security stops at the wage base in the bonus's paycheck: the year's never tops 6.2% of the base.
    assert lines_of(result, "tax")[2][2] <= 17610000 * 62 // 1000
    missing_rate = plan(tables, bonuses=[{"amount": "1000", "month": 3}])
    assert any("Enter Georgia's supplemental rate" in note for note in missing_rate["notes"])


def test_deduction_you_type_and_w4_adjustments(tables):
    # A 20,000 deduction: taxable 74,770 → 1,192.50 + 4,386.00 + 5,784.90 = 11,363.40, less 2,000 credits = 9,363.40 a year.
    result = plan(tables, federal_deduction="20000", federal_credits="2000", federal_extra_withholding="25")
    federal = result["jurisdictions"][0]
    assert (federal["taxable_minor"], federal["tax_before_credits_minor"], federal["credits_minor"], federal["annual_tax_minor"]) == (
        7477000, 1136340, 200000, 936340)
    assert federal["deduction_overridden"] and federal["buckets"][0]["to_minor"] == 2000000
    # 9,363.40 / 26 = 360.13, plus 25.00 extra withholding.
    assert lines_of(result, "tax")[0] == ("federal_income_tax", 38513, 38513 * 26)
    # The same 20,000 reached as the table's 15,000 plus 5,000 of W-4 deductions shows its own 0% bucket.
    other = plan(tables, federal_deductions="5000")["jurisdictions"][0]
    assert other["tax_before_credits_minor"] == 1136340
    assert [(bucket["label"], bucket["income_minor"]) for bucket in other["buckets"][:2]] == [("Standard deduction", 1500000), ("Other deductions", 500000)]
    # Other income raises the year's wages.
    assert plan(tables, federal_other_income="1000")["jurisdictions"][0]["annual_wages_minor"] == 9577000


def test_states_without_tax_typed_rates_disability_and_local_tax(tables):
    texas = plan(tables, work_state="TX")
    assert "state_income_tax" not in [line[0] for line in lines_of(texas, "tax")]
    assert "Texas has no state income tax on wages." in texas["notes"]
    # No Colorado table: the state waits, and net pay is marked incomplete…
    colorado = plan(tables, work_state="CO")
    assert not colorado["complete"] and colorado["jurisdictions"][1]["status"] == "missing"
    # …unless a flat rate is typed, with the deduction filled in (here none): 94,770 × 4.4% / 26 = 160.38.
    typed = plan(tables, work_state="CO", state_rate_percent="4.4", state_deduction="0")
    assert typed["complete"] and lines_of(typed, "tax")[1] == ("state_income_tax", 16038, 16038 * 26)
    assert typed["jurisdictions"][1]["source"] == "typed"
    # A state deduction you type replaces the table's: Georgia with 5,000 instead of 15,000 → 89,770 × 5.19% / 26 = 179.19.
    assert lines_of(plan(tables, state_deduction="5000"), "tax")[1][1] == 17919
    # Disability insurance 1.1% up to 50,000 of wages: 12 full paychecks (46,620), then 3,380 of the 13th, then none.
    disability = plan(tables, state_disability_percent="1.1", state_disability_wage_limit="50000", local_tax_percent="1", local_tax_wages="gross")
    assert [(part["from_check"], part["to_check"], part["state_disability_minor"]) for part in disability["schedule"]] == [
        (1, 12, 4274), (13, 13, 3718), (14, 26, 0)]
    assert ("local_tax", 4000, 104000) in lines_of(disability, "tax")


def test_missing_federal_table_leaves_out_income_tax_and_fica():
    result = calculate(PaycheckInput.model_validate({**TOM, "work_state": "TX"}), {})
    assert not result["complete"] and result["jurisdictions"][0]["message"] == "The 2026 Federal tax table hasn't been looked up yet."
    assert lines_of(result, "tax") == [] and result["net"]["per_check_minor"] == 400000 - 11500 - 24000 - 250


def test_start_from_a_real_pay_stub(tables):
    value = from_stub(RECORD, LINES, "single")
    assert value["gross_per_check"] == "4000.00" and value["pay_frequency"] == 26 and value["work_state"] == "GA"
    assert [(line["category"], line["amount"]) for line in value["pre_tax"]] == [
        ("retirement_pretax", "240.00"), ("health", "100.00"), ("dental", "10.00"), ("vision", "5.00")]
    assert value["employer"] == [{"category": "other", "label": "other", "amount": "160.00"}]
    result = calculate(PaycheckInput.model_validate(value), tables.for_year(2026, ["US", "GA"], "single"))
    assert [line[1] for line in lines_of(result, "tax")] == [47936, 15923, 24087, 5633]


@pytest.mark.parametrize("changes, message", [
    ({"gross_per_check": "4000"}, "yearly salary or the gross pay"),
    ({"pre_tax": [{"category": "bonus", "amount": "1"}]}, "can't be a pre-tax line"),
    ({"pre_tax": [{"category": "hsa", "amount": "1", "percent": "1"}]}, "amount per paycheck or a percent"),
    ({"match_limit_percent": None}, "Give both the match percent"),
    ({"pay_frequency": 25}, "pay_frequency"),
])
def test_inputs_are_checked(changes, message):
    with pytest.raises(ValidationError, match=message):
        PaycheckInput.model_validate({**TOM, **changes})


def test_paycheck_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        tables = TaxTables(app.state.manager.store)
        confirmed(tables, "US", FEDERAL)
        result = client.post("/api/paycheck", json={**TOM, "work_state": "TX"}).json()
        assert result["net"]["display"]["per_check_minor"] == "2,865.94 USD"
        assert result["jurisdictions"][0]["chart_svg"].startswith("<svg")
        assert client.post("/api/paycheck", json={**TOM, "annual_salary": None}).status_code == 422
        assert client.post("/api/tax-tables/lookup", json={"jurisdiction": "CO", "year": 2026, "filing_status": "widowed"}).status_code == 422
