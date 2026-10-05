"""Tax engines (docs/taxes.md "The tax engines"): numbered slots, the capability check, Engine 1's mapping and refusals, and hand-worked
2026 returns it must match.

The golden returns are worked by hand from 2026 law (Rev. Proc. 2025-32 and the OBBBA): each line within a dollar
(tax_engine.AGREE_WITHIN), since the engine works some forms in whole dollars. Tests that run the engine skip when
Node.js isn't installed."""

import json
import shutil

import pytest

from home_manager.finance import tax_engine
from home_manager.finance.engines import opentax, taxcalc
from home_manager.finance.ledger import HouseholdConfig
from home_manager.finance.tax_return import Business, Job, Person, ReturnInput, Student
from home_manager.library.storage import Store
import tax_returns

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
needs_engine_2 = pytest.mark.skipif(taxcalc.installed() != taxcalc.PINNED, reason='Engine 2 isn\'t installed (pip install ".[engine2]")')


def table(brackets, standard, threshold, status):
    return {"status": "verified", "filing_status": status, "standard_deduction_minor": standard, "brackets_json": json.dumps(brackets),
            "ss_rate_bp": 620, "ss_wage_base_minor": 18450000, "medicare_rate_bp": 145, "additional_medicare_rate_bp": 90,
            "additional_medicare_threshold_minor": threshold}


def brackets(starts):
    return [{"from_minor": start * 100, "rate_bp": rate} for start, rate in zip(starts, (1000, 1200, 2200, 2400, 3200, 3500, 3700))]


# 2026's federal tables, as the pay stub lookup confirms them: only the marginal rate is read from them for the return.
US_2026 = {"single": table(brackets((0, 12400, 50400, 105700, 201775, 256225, 640600)), 1610000, 20000000, "single"),
           "married_joint": table(brackets((0, 24800, 100800, 211400, 403550, 512450, 768700)), 3220000, 25000000, "married_joint")}


def profile(**changes):
    return ReturnInput.model_validate({"year": 2026, "filing_status": "single", **changes})


def worked(value, slot="engine_1"):
    return tax_engine.calculate(slot, value, {"US": US_2026[value.filing_status]})


def amounts(result):
    return {line["key"]: line["amount_minor"] for line in result["lines"]}


def matches(result, expected):
    """Each expected line within a dollar of the hand-worked figure."""
    lines = {**amounts(result), "result": result["result_minor"]}
    for key, want in expected.items():
        assert abs(lines[key] - want) <= tax_engine.AGREE_WITHIN, (key, want, lines[key])


def test_engines_are_numbered_slots_and_old_settings_still_load():
    assert list(tax_engine.ENGINES) == ["engine_1", "engine_2"] and tax_engine.label_of("engine_2") == "Engine 2"
    assert tax_engine.slot_of("opentax") == tax_engine.slot_of("builtin") == "engine_1" and tax_engine.others("engine_1") == ["engine_2"]
    with pytest.raises(ValueError):
        tax_engine.slot_of("taxsim")
    # Settings saved with an engine's name load as the slot that does its work now.
    assert HouseholdConfig.model_validate({"tax_engine": "builtin", "tax_engine_compare": True}).tax_engine == "engine_1"


def test_an_engine_that_doesnt_cover_the_return_gives_no_estimate_and_says_why():
    # Checked before the engine runs: no Node needed.
    value = profile(jobs=[Job(wages=5000000)], energy_home_expenses=100000, other_credits=5000)
    result = worked(value)
    assert result["result_minor"] is None and result["unsupported"] == ["energy_credit", "other_credits"]
    assert result["notes"][0].startswith("Engine 1 doesn't cover") and "energy efficient home improvement credit" in result["notes"][0]
    assert result["engine"] == {"slot": "engine_1", "label": "Engine 1", "version": opentax.pin()["version"]}
    later = worked(profile(year=2031, jobs=[Job(wages=5000000)]))
    assert later["unsupported"] == ["year:2031"] and "not 2031" in later["notes"][0]
    couple = profile(filing_status="married_joint", businesses=[Business(owner="", income=100), Business(owner="spouse", income=100)], educator_expenses=100)
    assert tax_engine.requirements(couple) == {"two_self_employed", "joint_educator"}


def test_the_profile_maps_to_the_engines_facts():
    value = profile(filing_status="married_joint", people=[Person(birth_year=1960), Person(birth_year=1990)],
                    jobs=[Job(owner="", wages=6000000, ss_wages=6000000), Job(owner="spouse", wages=2000000, ss_wages=2000000)],
                    ordinary_dividends=50000, qualified_dividends=30000, short_term_gain=100000, long_term_gain=-200000, capital_loss_carryover=300000,
                    businesses=[Business(owner="spouse", income=1000000, expenses=250000)], ira_deduction=700000, hsa_contributions=300000,
                    hsa_coverage="family", mortgage_interest=900000, mortgage_average_balance=40000000, charity=10000, charity_noncash=20000,
                    dependent_care_expenses=500000, dependent_care_people=1, students=[Student(expenses=400000), Student(expenses=300000, aotc=False)],
                    qualified_tips=500000, tipped_occupation="bartenders", qualified_overtime=200000)
    facts, notes = opentax.facts_for(value)
    assert (facts["filingStatus"], facts["wages"], facts["qualifiedDividends"], facts["ordinaryDividends"]) == ("mfj", "80000.00", "300.00", "200.00")
    # The carryover comes off short-term first: 1,000 − 3,000 = a 2,000 short-term loss.
    assert (facts["shortTermCapitalLoss"], facts["longTermCapitalLoss"]) == ("2000.00", "2000.00") and "shortTermCapitalGains" not in facts
    # Schedule SE's wage base room is the self-employed spouse's own Social Security wages.
    assert (facts["selfEmploymentNetProfit"], facts["socialSecurityWages"]) == ("7500.00", "20000.00")
    assert (facts["iraContribution"], facts["isActivePlanParticipant"], facts["hsaCoverage"], facts["mortgageAverageBalance"]) == ("7000.00", False, "family", "400000.00")
    assert (facts["charitableCashContributions"], facts["noncashCharitableContributions"]) == ("100.00", "200.00")
    # The lower earner's earned income limits the dependent care credit: the spouse's 20,000 wages + 7,500 profit.
    assert (facts["secondaryEarnedIncome"], facts["aotcExpensesStudent1"], facts["llcQualifiedExpenses"]) == ("27500.00", "4000.00", "3000.00")
    assert (facts["isAge65OrOlder"], facts["isAge50OrOlder"], facts["spouseIsAge65OrOlder"], facts["isAtLeastAge25"]) == (True, True, False, True)
    assert (facts["qualifiedTips"], facts["occupation"], facts["qualifiedOvertimePremium"]) == ("5000.00", "bartenders", "2000.00")
    assert any("short-term gains first" in note for note in notes) and any("IRA" in note for note in notes)
    assert opentax.dollars(-1234) == "-12.34"


@needs_node
def test_the_engine_asks_for_what_it_needs_and_never_guesses():
    result = worked(profile(people=[Person(birth_year=1980)], jobs=[Job(wages=5000000)], mortgage_interest=900000))
    assert result["result_minor"] is None and result["needs"] == ["mortgageAverageBalance"]
    assert "the mortgage's average balance" in result["notes"][0]
    tips = worked(profile(people=[Person(birth_year=1980)], jobs=[Job(wages=5000000)], qualified_tips=300000))
    assert tips["needs"] == ["occupation"] and "Tipped occupation" in tips["notes"][0]


@needs_node
def test_the_engine_isnt_run_when_its_file_doesnt_match_the_pin(monkeypatch):
    monkeypatch.setattr(opentax, "_cache", opentax.OrderedDict())
    monkeypatch.setattr(opentax, "_checked", {})
    monkeypatch.setattr(opentax, "pin", lambda: {**json.loads((opentax.VENDOR / "PIN.json").read_text(encoding="utf-8")), "files": {"main.js": "0" * 64}})
    result = worked(profile(jobs=[Job(wages=5000001)]))
    assert result["result_minor"] is None and result["notes"][0] == "Engine 1 isn't run: its file doesn't match its pinned SHA-256."
    assert not tax_engine.readiness()["ready"]


def test_the_engine_without_node_says_so(monkeypatch):
    monkeypatch.setattr(opentax, "_cache", opentax.OrderedDict())
    monkeypatch.setattr(opentax.shutil, "which", lambda name: None)
    monkeypatch.delenv("HOME_MANAGER_NODE", raising=False)
    result = worked(profile(jobs=[Job(wages=5000002)]))
    assert result["result_minor"] is None and result["notes"][0].startswith("Engine 1 needs Node.js")
    ready = tax_engine.readiness()
    assert not ready["ready"] and ready["note"].startswith("Engine 1 needs Node.js")


@needs_node
def test_readiness_names_the_slot_and_its_years():
    assert tax_engine.readiness() == {"slot": "engine_1", "label": "Engine 1", "ready": True,
                                      "note": "Taxes are worked out on this computer by Engine 1, for 2025, 2026 returns."}


# The hand-worked returns, by every engine: each must match the hand figures (and so each other).
ENGINE_SLOTS = [pytest.param("engine_1", marks=needs_node), pytest.param("engine_2", marks=needs_engine_2)]
NAMES = {"engine_1": ("opentax", "OpenTax"), "engine_2": ("taxcalc", "Tax-Calculator")}


@pytest.mark.parametrize("slot", ENGINE_SLOTS)
def test_a_w2_return(slot):
    result = worked(tax_returns.W2, slot)
    # 85,300 less the 16,100 standard deduction; 69,200 is in the 69,200–69,250 row of the Tax Table: 9,942. 9,000 withheld.
    assert (amounts(result)["taxable_income"], amounts(result)["tax"], result["result_minor"]) == (6920000, 994200, -94200)
    label = tax_engine.label_of(slot)
    assert result["marginal_bp"] == 2200 and result["complete"] and f"Worked out by {label}" in result["notes"][-1]
    name, brand = NAMES[slot]
    assert brand not in json.dumps({key: item for key, item in result.items() if key != "raw"})  # The page never sees its name.
    assert result["raw"]["engine"]["name"] == name  # The records do.


@pytest.mark.parametrize("slot", ENGINE_SLOTS)
def test_a_joint_return_with_children_gains_and_contract_work(slot):
    value = tax_returns.JOINT_CONTRACT
    # SE: 20,000 × 92.35% = 18,470 × 15.3% = 2,825.91 (2,826 in whole dollars); half, 1,413, comes off. Income 178,200, AGI 176,787.
    # 32,200 standard: 144,587; QBI 20% of (20,000 − 1,413) = 3,717.40: taxable 140,869.60. Ordinary 134,269.60:
    # 2,480 + 9,120 + 22% of 33,469.60 (7,363.31) = 18,963.31, and 6,600 of gains and qualified dividends at 15%: 990.
    # Tax 19,953.31 − 4,400 child credit + 2,826 SE = 18,379.31 against 14,000 withheld and 3,000 estimated.
    matches(worked(value, slot), {"other_se": 282600, "adjust_se_half": -141300, "total_income": 17820000, "agi": 17678700, "qbi": -371740,
                                  "taxable_income": 14086960, "tax": 1995331, "credit_child": -440000, "total_tax": 1837931, "total_payments": 1700000,
                                  "result": -137931})


@pytest.mark.parametrize("slot", ENGINE_SLOTS)
def test_high_wages_with_additional_medicare_and_investment_income_tax(slot):
    value = tax_returns.HIGH_WAGES
    # AGI 290,000; taxable 273,900. Ordinary 253,900: 1,240 + 4,560 + 12,166 + 23,058 + 32% of 52,125 (16,680) = 57,704; 20,000 at 15%: 3,000.
    # Additional Medicare 0.9% of 60,000 = 540 (all withheld above 1.45%); NIIT 3.8% of 30,000 = 1,140.
    matches(worked(value, slot), {"agi": 29000000, "taxable_income": 27390000, "tax": 6070400, "other_additional_medicare": 54000, "other_niit": 114000,
                                  "total_tax": 6238400, "pay_additional_medicare": 54000, "result": -184400})


@pytest.mark.parametrize("slot", ENGINE_SLOTS)
def test_2026_law_the_old_hand_written_return_lacked(slot):
    # OBBBA: a couple not itemizing deducts up to 2,000 of cash gifts to charity; tips and overtime come off below the line.
    charity = worked(tax_returns.CHARITY, slot)
    matches(charity, {"charity_nonitemizer": -200000, "taxable_income": 10000000 - 3220000 - 200000})
    tipped = worked(tax_returns.TIPPED, slot)
    matches(tipped, {"other_deductions": -700000, "taxable_income": 6000000 - 1610000 - 700000})


@needs_node
@needs_engine_2
def test_the_second_engine_checks_the_first_line_by_line():
    value = profile(filing_status="married_joint", people=[Person(birth_year=1985), Person(birth_year=1987)],
                    jobs=[Job(wages=15000000, medicare_wages=15000000, federal_withheld=1400000)], interest=120000, ordinary_dividends=200000,
                    qualified_dividends=160000, businesses=[Business(owner="spouse", income=2500000, expenses=500000)], qualifying_children=2)
    found = tax_engine.compare(worked(value), worked(value, "engine_2"))
    assert found["ready"] and found["agree"] and found["engine"]["label"] == "Engine 2", found


# Engine 2's own work: the mapping and the rules it works from the law (no Tax-Calculator needed).
POLICY_2026_SINGLE = {**{f"II_rt{n}": rate for n, rate in enumerate((.10, .12, .22, .24, .32, .35, .37), 1)},
                      **{f"II_brk{n}": top for n, top in enumerate((12400, 50400, 105700, 201775, 256225, 640600), 1)}}


def test_the_second_engine_maps_the_profile_and_works_what_its_model_takes_as_given():
    value = profile(filing_status="married_joint", people=[Person(birth_year=1970), Person(birth_year=1990)],
                    jobs=[Job(owner="", wages=6000000, medicare_wages=6500000), Job(owner="spouse", wages=2000000, medicare_wages=2000000)],
                    businesses=[Business(owner="spouse", income=1000000, expenses=250000), Business(owner="", income=300000)],
                    qualifying_children=2, other_dependents=1, students=[Student(expenses=400000), Student(expenses=150000), Student(expenses=300000, aotc=False)],
                    hsa_contributions=900000, hsa_coverage="family", mortgage_interest=900000, mortgage_average_balance=100000000,
                    retirement_distributions=1000000, early_distributions=400000, hsa_nonqualified=50000, other_income=10000)
    record, notes = taxcalc.record_for(value)
    assert (record["MARS"], record["age_head"], record["age_spouse"], record["XTOT"], record["n24"], record["EIC"]) == (2, 56, 36, 5, 2, 2)
    # Each person's wages and business apart (Schedule SE for each); 5,000 of deferrals above box 1 come back for payroll tax.
    assert (record["e00200p"], record["e00200s"], record["pencon_p"], record["e00900p"], record["e00900s"]) == (60000, 20000, 5000, 3000, 7500)
    # AOTC: 2,000 + 25% of 2,000 = 2,500 and 1,500; the rest is lifetime learning.
    assert (record["e87521"], record["e87530"]) == (4000, 3000)
    # HSA: 9,000 is within the 2026 family limit, 8,750 plus 1,000 from 55. Mortgage: 9,000 × 750,000 ÷ 1,000,000.
    assert (record["e03290"], record["e19200"]) == (9000, 6750) and any("$750,000" in note for note in notes)
    assert taxcalc.record_for(value.model_copy(update={"hsa_coverage": "self"}))[0]["e03290"] == 5400  # 4,400 self-only plus 1,000.
    # 10% of 4,000 early and 20% of 500 HSA money; the HSA money and other income are ordinary income.
    assert (record["e09900"], record["e00700"]) == (500, 600)
    assert taxcalc.needed(profile(jobs=[Job(wages=100)])) == []
    assert taxcalc.needed(profile(filing_status="married_joint", people=[Person(birth_year=1980)], qualified_tips=100, mortgage_interest=100,
                                  hsa_contributions=100)) == ["mortgageAverageBalance", "hsaCoverage", "occupation"]
    # No birth year: Engine 1's documented default, not 65 or older, and said so.
    unknown, notes = taxcalc.record_for(profile(filing_status="married_joint", people=[Person(birth_year=1950)]))
    assert (unknown["age_head"], unknown["age_spouse"]) == (76, taxcalc.UNKNOWN_AGE) and any("25 to 64" in note for note in notes)


def test_the_tax_table_rule_below_100000():
    # 69,200 is in the 69,200–69,250 row: the schedule on 69,225 is 9,941.50, which the table rounds to 9,942.
    assert taxcalc.table_tax(6920000, POLICY_2026_SINGLE) == 994200
    assert taxcalc.table_tax(10000000, POLICY_2026_SINGLE) is None  # The schedules from 100,000.
    assert taxcalc.table_tax(1000, POLICY_2026_SINGLE) == 100  # 5–15 row: 10% of 10.
    assert taxcalc.table_tax(290000, POLICY_2026_SINGLE) == 29100  # The 2,900–2,925 row: 10% of 2,912.50 = 291.25, rounded to 291.


def test_a_missing_second_engine_says_how_to_add_it(monkeypatch):
    monkeypatch.setattr(taxcalc, "installed", lambda: None)
    ready = tax_engine.readiness("engine_2")
    assert not ready["ready"] and ready["note"].startswith("Engine 2 isn't installed") and "home-manager[engine2]" in ready["note"]
    result = worked(profile(people=[Person(birth_year=1980)], jobs=[Job(wages=100)]), "engine_2")
    assert result["result_minor"] is None and result["notes"][0].startswith("Engine 2 isn't installed")


def test_only_lines_both_engines_work_out_are_compared():
    first = {"result_minor": 0, "engine": {"label": "Engine 1"}, "lines": [{"key": "credit_savers", "label": "Saver's credit", "amount_minor": -5000},
                                                                          {"key": "tax", "label": "Tax", "amount_minor": 100000}]}
    second = {"result_minor": 500, "engine": {"label": "Engine 2"}, "reports": ["tax"],
              "lines": [{"key": "tax", "label": "Tax", "amount_minor": 100500, "within": 650}]}
    found = tax_engine.compare(first, second)
    # The saver's credit isn't one Engine 2 works out, and its tax carries its own leeway: they agree.
    assert found["agree"] and found["lines"] == [] and found["display"]["within"] == "6.50 USD"


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / "managed")
    try:
        yield value
    finally:
        value.close()


def test_a_calculation_is_kept_once_per_engine_version_and_profile(store):
    records = tax_engine.TaxCalculations(store)
    value = profile(jobs=[Job(wages=8500000)])
    implementation = {"name": "opentax", "version": "0.4.0", "pin_sha256": "ab" * 32}
    result = {"result_minor": -94200, "total_tax_minor": 994200, "agi_minor": 8530000, "lines": [], "engine": {"slot": "engine_1", "label": "Engine 1"}}
    records.record("me", value, {**result, "raw": {"engine": implementation, "facts": {"wages": "85000.00"}, "proof": {"huge": True}}})
    records.record("me", value, {**result, "raw": {"engine": implementation}})  # The same engine and profile again: nothing new.
    changed = value.model_copy(update={"interest": 100})
    records.record("me", changed, {**result, "raw": {"engine": implementation}})
    rows = records.list(2026)
    assert [(row["engine"], row["engine_version"], row["pin_sha256"]) for row in rows] == [("opentax", "0.4.0", "ab" * 32)] * 2
    with store.connection() as db:
        raw = db.execute("SELECT raw_json FROM tax_calculations WHERE id=?", (rows[1]["id"],)).fetchone()[0]
    assert json.loads(raw) == {"facts": {"wages": "85000.00"}}  # The proof tree isn't kept: the facts and engine version re-run it.
    assert records.list(2026, "unit-3") == []
    # Next year's safe harbor reads this year's newest return when the filed figures aren't typed.
    prior = records.prior(2026)
    assert (prior["tax_minor"], prior["agi_minor"]) == (994200, 8530000) and "worked out here" in prior["source"]
    assert records.prior(2025) is None


def test_two_engines_compared_line_by_line():
    first = {"result_minor": -94200, "engine": {"label": "Engine 1"},
             "lines": [{"key": "tax", "label": "Tax", "amount_minor": 994200}, {"key": "other_se", "label": "Self-employment tax", "amount_minor": 282591}]}
    second = {"result_minor": -94209, "engine": {"label": "Engine 2"}, "lines": [{"key": "tax", "label": "Tax", "amount_minor": 994200},
              {"key": "other_se", "label": "Self-employment tax", "amount_minor": 282600}]}
    assert tax_engine.compare(first, second)["agree"]  # 9 cents apart: within a dollar.
    third = {**second, "result_minor": 105800, "lines": [*second["lines"], {"key": "charity_nonitemizer", "label": "Charitable deduction", "amount_minor": -200000}]}
    found = tax_engine.compare(first, third)
    assert not found["agree"] and found["other_refund"] and [line["key"] for line in found["lines"]] == ["charity_nonitemizer"]
    assert found["display"]["difference"] == "2,000.00 USD"
    assert tax_engine.compare(first, {"result_minor": None, "notes": ["Needs Node.js."], "engine": {}}) == {"engine": {}, "ready": False, "note": "Needs Node.js."}
