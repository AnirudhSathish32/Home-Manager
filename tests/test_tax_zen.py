"""Tax Zen (docs/taxes.md): the W-4 entries, or advance tax, that bring the year's return to $0. Synthetic tables only.

Tax Zen works from the tax engine's answer; these tests hand it canned answers (the year's tax, what's paid), so they need
no engine. A planned paycheck runs the real engine and skips without Node.js."""

from datetime import date
import shutil

import pytest

from home_manager.finance import safe_harbor
from home_manager.finance.tax_zen import TaxZenEvaluations, TaxZenPolicy, advance_tax, advise, changes, due_dates, goal, solve, w4_summary, withholding
from home_manager.finance.withholding import W4_DELAY_CHECKS, projection
from home_manager.library.storage import Store
from test_tax_return import SINGLE

FEDERAL = {**SINGLE, "sources_json": "[]"}
# Tom's paycheck: 3,645 of income-tax wages every two weeks, 479.36 withheld; eleven paychecks left this year. A W-4 handed
# in now takes effect after the next one (finance/withholding.py), so it changes ten.
JOB = {"key": "employer-1", "name": "Acme", "paychecks_left": 11, "pay_frequency": 26, "work_state": None, "next_pay_date": "2026-10-09",
       "per_check": {"wages": 364500, "fica": 388500, "federal": 47936, "state": 0, "medicare": 5633},
       "values": {"federal_withheld": 1246336}}


def answer(total_tax, paid, estimated=0):
    """The tax engine's answer, as much of it as Tax Zen reads."""
    return {"result_minor": paid - total_tax, "total_tax_minor": total_tax, "payments_minor": paid, "estimated_minor": estimated,
            "refundable_credits_minor": 0, "state": None, "unsupported": [], "notes": [], "lines": []}


def year(withheld=1246336, interest=0):
    """Tom's year: 12,465 of tax on his wages, and interest nobody withholds on at his 22% rate."""
    return answer(1246500 + interest * 22 // 100, withheld)


def year_end(job, result, w4):
    """What the return comes to when the paychecks left withhold under these W-4 entries (the stub's offset kept)."""
    offset = job["per_check"]["federal"] - withholding(FEDERAL, job["per_check"]["wages"], job["pay_frequency"], {})
    return result + (job["paychecks_left"] - W4_DELAY_CHECKS) * (withholding(FEDERAL, job["per_check"]["wages"], job["pay_frequency"], w4) + offset - job["per_check"]["federal"])


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
    estimate_ = year(withheld=1246336 + 260000)  # Payroll takes 100 more a paycheck than Pub 15-T says.
    zen = advise(estimate_, [job], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    rest = zen["job"]["rest"]
    assert zen["job"]["offset_minor"] == 10000 and rest["field"] == "4(b)" and abs(rest["year_end_minor"]) < 100
    assert "extra" not in zen["job"]  # A fixed extra can't lower withholding.
    # A refund no W-4 can close with ten paychecks left: 4(b) can't make withholding negative.
    big = year(withheld=1246336 + 3000000)
    unreachable = advise(big, [{**job, "values": {"federal_withheld": 1246336 + 3000000}}], FEDERAL, {}, [], 2026, date(2026, 9, 30))["job"]["rest"]
    assert unreachable["unreachable"] and unreachable["field"] == "4(b)"


def test_zen_is_within_a_dollar():
    close = year(withheld=1246500)
    zen = advise(close, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert zen["zen"] and zen["result_minor"] == 0 and zen["job"]["rest"]["field"] is None
    assert zen["display"]["aim"] == "0.00 USD"  # The page's "your aim" text, from the server.
    refund = advise(close, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), policy=TaxZenPolicy(strategy="small_refund", refund_minor=25000))
    assert refund["display"]["aim"] == "a refund of 250.00 USD"


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js isn't installed")
def test_a_planned_paycheck_at_tax_time():
    from home_manager.finance.ledger import HouseholdConfig
    from home_manager.finance.paycheck import PaycheckInput, calculate
    from home_manager.finance.tax_zen import plan_tax_zen
    from test_paycheck import TOM
    value = PaycheckInput.model_validate({**TOM, "work_state": "TX", "post_tax": [], "match_percent": None, "match_limit_percent": None})
    result = calculate(value, {"US": FEDERAL})
    empty = {"values": {}, "sources": {}, "jobs": [], "businesses": [], "state": None, "notes": [], "estimated_payments": {"federal_estimated": [], "state_estimated": []}}
    zen = plan_tax_zen([("Tom", result, value, True)], empty, HouseholdConfig(), "single", 2026, lambda codes: {"US": FEDERAL})
    # 2026 law (Engine 1): 94,770 of wages less the 16,100 standard deduction; 78,670 is in the 78,650–78,700 row of the Tax
    # Table: 1,240 + 4,560 + 22% of 28,275 = 12,020.50, so 12,021. 26 × 479.36 = 12,463.36 withheld: 442.36 comes back,
    # closed with 4(b).
    assert abs(zen["result_minor"] - 44236) <= 100 and (zen["job"], zen["w4"]["field"]) == ("Tom", "4(b)")
    assert abs(zen["w4"]["year_end_minor"]) < 100
    # 5,000 of interest from this year's records on the same return: 1,100 more tax at 22%, so about 657.64 owed, closed with 4(a).
    interest = {**empty, "values": {"interest": 500000}}
    with_interest = plan_tax_zen([("Tom", result, value, True)], interest, HouseholdConfig(), "single", 2026, lambda codes: {"US": FEDERAL})
    assert abs(with_interest["result_minor"] - (zen["result_minor"] - 110000)) <= 100 and with_interest["w4"]["field"] == "4(a)"


def test_advance_tax_quarters_for_income_without_withholding():
    assert [day.isoformat() for day in due_dates(2028)] == ["2028-04-17", "2028-06-15", "2028-09-15", "2029-01-15"]  # Apr 15, 2028 is a Saturday.
    payments = [{"date": "2026-04-10", "amount_minor": 200000}]
    safe = safe_harbor.evaluate(2026, 800000, 0, 0, payments, today=date(2026, 7, 1))
    plan = advance_tax(2026, date(2026, 7, 1), 800000, payments, safe)
    # Paid 2,000 by the April date; 6,000 left over the September and January dates. June's date has passed short of the safe harbor.
    assert [(row["quarter"], row["paid_minor"], row["pay_minor"]) for row in plan["quarters"]] == [(1, 200000, 0), (2, 0, 0), (3, 0, 300000), (4, 0, 300000)]
    assert plan["left_minor"] == 600000 and any("Form 2210" in note for note in plan["notes"])
    # Contract work only: no job to change, so the answer is the quarters.
    contract = answer(745600, 0)  # 50,000 of contract income and nothing withheld.
    zen = advise(contract, [], FEDERAL, {}, [], 2026, date(2026, 3, 1))
    assert "job" not in zen and zen["advance"]["left_minor"] == contract["total_tax_minor"]
    assert sum(row["pay_minor"] for row in zen["advance"]["quarters"]) == contract["total_tax_minor"]
    # Last year's tax sets the safe harbor when it's lower (100% of it, 110% above $150,000 of AGI).
    prior = advise(contract, [], FEDERAL, {}, [], 2026, date(2026, 3, 1), prior={"tax_minor": 300000, "agi_minor": 4000000})
    assert prior["advance"]["safe_harbor_minor"] == 300000


def test_the_safe_harbor_by_its_own_rules():
    # 10,000 of tax, 7,000 withheld: 3,000 owed and 90% of this year's (9,000) not reached.
    short = safe_harbor.evaluate(2026, 1000000, 700000, 0, [], today=date(2026, 9, 30))
    assert (short["required_minor"], short["less_than_1000"], short["satisfied"], short["risk"]) == (900000, False, False, "likely")
    # Last year's tax of 6,000 (AGI under $150,000) sets a lower required payment, which withholding meets.
    prior = safe_harbor.evaluate(2026, 1000000, 700000, 0, [], {"tax_minor": 600000, "agi_minor": 9000000}, date(2026, 9, 30))
    assert (prior["required_minor"], prior["required_basis"], prior["satisfied"], prior["prior_year_used"]) == (600000, "100% of last year's tax", True, True)
    # Above $150,000 of last year's AGI it's 110%: 6,600.
    assert safe_harbor.evaluate(2026, 1000000, 700000, 0, [], {"tax_minor": 600000, "agi_minor": 20000000})["required_minor"] == 660000
    # Owing under $1,000 is safe whatever was paid.
    small = safe_harbor.evaluate(2026, 1000000, 910000 - 20000, 20000, [])
    assert small["less_than_1000"] and small["satisfied"] and small["risk"] == "none"
    # Timing: withholding counts evenly; an estimated payment counts for the first due date on or after it.
    timed = safe_harbor.evaluate(2026, 1000000, 0, 0, [{"date": "2026-09-01", "amount_minor": 900000}], today=date(2026, 10, 1))
    assert timed["meets_required_payment"] and timed["underpaid_quarters"] == [1, 2] and timed["risk"] == "possible"
    assert any("Form 2210" in note for note in timed["notes"])


def test_advance_tax_and_the_safe_harbor_agree_on_each_quarter():
    # 10,000 of tax, 4,000 withheld evenly, 1,500 paid in June: the safe harbor needs 9,000, so estimated payments must reach
    # 9,000 × q/4 less the withholding's q/4 by each date. Both views name the same underpaid quarters.
    estimate_ = answer(1000000, 550000, estimated=150000)
    payments = [{"date": "2026-06-10", "amount_minor": 150000}]
    zen = advise(estimate_, [], FEDERAL, {}, payments, 2026, date(2026, 10, 1))
    safe = zen["safe_harbor"]
    assert [row["safe_by_now_minor"] for row in zen["advance"]["quarters"]] == [125000, 250000, 375000, 500000]
    assert [row["safe_by_now_minor"] for row in zen["advance"]["quarters"]] == [row["estimated_needed_by_now_minor"] for row in safe["quarters"]]
    assert zen["advance"]["safe_harbor_minor"] == safe["required_minor"] - 400000
    assert safe["underpaid_quarters"] == [1, 2, 3] and any("quarter 3" in note for note in zen["advance"]["notes"])


def test_the_aim_follows_the_policy():
    assert goal(TaxZenPolicy(), 1000000, 900000) == 0
    assert goal(TaxZenPolicy(strategy="small_refund", refund_minor=25000), 1000000, 900000) == 25000
    # Keep cash: owe at most 999, less a 400 buffer, so aim at owing 599 (§24).
    assert goal(TaxZenPolicy(strategy="cash_retention"), 1000000, 900000) == -59900
    # Safe harbor first: owe up to what the required payment leaves (1,000 of 10,000), less the buffer.
    assert goal(TaxZenPolicy(strategy="safe_harbor"), 1000000, 900000) == -60000


def test_tax_zen_is_a_status_with_a_reason():
    close = advise(year(withheld=1246500), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert (close["status"], close["zen"]) == ("ZEN", True)
    # 300 owed: within the 500 watch band, safe (under $1,000): no change asked under the default policy.
    watch = advise(year(interest=136400), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert watch["status"] == "WATCH" and not watch["zen"] and "no change is needed" in watch["reason"]
    owing = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert owing["status"] == "ACTION_RECOMMENDED" and owing["job"]["primary"] == "extra"  # One W-4 box: a fixed extra a paycheck (§20).
    # Keeping cash: owing 599 is the aim, so the W-4 answer steers the year there instead of to $0.
    cash = TaxZenPolicy(strategy="cash_retention", band_minor=60000)
    kept = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), policy=cash)
    assert kept["target_minor"] == -59900 and abs(kept["job"]["rest"]["year_end_minor"] + 59900) < 100
    disagree = advise({**year(), "comparison": {"ready": True, "agree": False}}, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert disagree["status"] == "REVIEW_REQUIRED" and not disagree["zen"]
    missing = advise({"result_minor": None, "notes": ["The 2026 federal tax table isn't confirmed yet."], "unsupported": []}, [JOB], None, {}, [], 2026)
    assert (missing["ready"], missing["status"]) == (False, "INSUFFICIENT_DATA")
    uncovered = advise({"result_minor": None, "notes": ["Not covered."], "unsupported": ["energy_credit"]}, [JOB], None, {}, [], 2026)
    assert uncovered["status"] == "ENGINE_UNSUPPORTED"


def test_a_w4_answer_is_checked_by_working_the_return_out_again():
    estimate_ = year(interest=500000)

    def recheck(key, more):  # The engine again, with the job's withholding raised by `more`.
        return year(withheld=1246336 + more, interest=500000)["result_minor"]
    zen = advise(estimate_, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), recheck=recheck)
    assert zen["job"]["rest"]["checked"] and zen["job"]["extra"]["checked"]
    wrong = advise(estimate_, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), recheck=lambda key, more: 0 - 50000)
    assert not wrong["job"]["rest"]["checked"]


def test_on_track_but_at_risk_when_the_likely_range_reaches_a_penalty():
    # About 1.64 owed: close enough to watch. But if the rest of the year comes in at the low end, 1,500 would be owed.
    risky = advise(year(), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), outcomes={"low_minor": -150000, "high_minor": 20000, "confidence": "medium"})
    assert risky["status"] == "AT_RISK" and "owe up to 1,500.00 USD" in risky["reason"]
    assert risky["range"]["display"] == {"low_minor": "owing 1,500.00 USD", "high_minor": "refund of 200.00 USD"}
    # The cushion: (1,500 − 999) over ten paychecks, rounded up to the cent: 50.10.
    assert risky["cushion"]["per_check_minor"] == 5010 and "Step 4(c)" in risky["cushion"]["text"]
    calm = advise(year(), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), outcomes={"low_minor": -50000, "high_minor": 20000, "confidence": "high"})
    assert calm["status"] == "WATCH" and "cushion" not in calm


def test_tax_zen_is_left_only_past_one_and_a_half_times_its_band():
    nearly = year(withheld=1246500 - 120)  # 1.20 owed: more than a dollar from $0.
    assert advise(nearly, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))["status"] == "WATCH"
    # Tax Zen last time: it stays Tax Zen until 1.50 away.
    assert advise(nearly, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), previous={"status": "ZEN"})["status"] == "ZEN"
    further = year(withheld=1246500 - 160)
    assert advise(further, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), previous={"status": "ZEN"})["status"] == "WATCH"


def test_a_w4_answer_stays_put_unless_it_moves_withholding_by_25_a_paycheck():
    first = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    previous = {"status": first["status"], "w4": w4_summary(first["job"]), "created_at": "2026-09-01T12:00:00+00:00"}
    # 100 more interest: about 2.20 a paycheck more. Not worth a new W-4: the last answer stands, worked out again for today.
    small = advise(year(interest=510000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), previous=previous, changed={"texts": [], "material": False})
    extra = small["job"]["extra"]
    assert small["job"]["steady"]["since"] == "2026-09-01" and extra["per_check_minor"] == first["job"]["extra"]["per_check_minor"]
    assert extra["year_end_minor"] == year(interest=510000)["result_minor"] + 10 * extra["per_check_minor"]
    # Something material (a new job, a new form, pay moving 10%): a new answer.
    material = advise(year(interest=510000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), previous=previous, changed={"texts": ["New job: B"], "material": True})
    assert "steady" not in material["job"] and material["job"]["extra"]["per_check_minor"] > first["job"]["extra"]["per_check_minor"]
    # 2,000 more interest: 44 a paycheck more. A new answer.
    large = advise(year(interest=700000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), previous=previous, changed={"texts": [], "material": False})
    assert "steady" not in large["job"]


def test_what_changed_is_said_in_words():
    before = {"fields": {"interest": 100000}, "sources": {"interest": "Interest so far, projected to Dec 31"},
              "jobs": {"e1": {"name": "Acme", "wages": 400000, "federal": 47000, "stubs": 3, "paychecks_left": 8}}, "typed_jobs": []}
    after = {"fields": {"interest": 160000}, "sources": {"interest": "1099-INT forms (boxes 1 and 3), plus bank interest projected to Dec 31"},
             "jobs": {"e1": {"name": "Acme", "wages": 400000, "federal": 43000, "stubs": 4, "paychecks_left": 7},
                      "e2": {"name": "Bistro", "wages": 90000, "federal": 5000, "stubs": 1, "paychecks_left": 7}}, "typed_jobs": []}
    found = changes(before, after)
    assert found["material"] and found["texts"] == [
        "Acme: 1 new pay stub", "Acme: federal withheld per paycheck 470.00 USD → 430.00 USD", "New job: Bistro",
        "A tax form now gives interest (1099-INT forms (boxes 1 and 3), plus bank interest projected to Dec 31)", "Interest: 1,000.00 USD → 1,600.00 USD"]
    assert changes(None, after) == {"texts": [], "material": False}
    raise_ = {**before, "jobs": {"e1": {**before["jobs"]["e1"], "wages": 450000}}}
    assert changes(before, raise_)["material"]  # Pay per paycheck up 12.5%.


def test_evaluations_are_kept_when_something_changes_and_shown_on_home_until_seen(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        evaluations = TaxZenEvaluations(store)
        watch = advise(year(), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
        evaluations.record(2026, "me", watch, None, {"fields": {"interest": 1}}, None)
        evaluations.seen(2026)
        assert evaluations.attention(2026) is None  # Seen, and nothing worse.
        evaluations.record(2026, "me", watch, None, {"fields": {"interest": 1}}, None)  # The same again: no new row.
        owing = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
        evaluations.record(2026, "me", owing, None, {"fields": {"interest": 500000}}, "Interest: 0.01 USD → 5,000.00 USD")
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM tax_zen_evaluations").fetchone()[0] == 2
        latest = evaluations.latest(2026)
        assert latest["w4"]["primary"] == "extra" and latest["w4"]["per_check_minor"] == JOB["per_check"]["federal"] + owing["job"]["extra"]["per_check_minor"]
        # Worse than when last seen: Home points at the Taxes page with what changed, until it's opened.
        assert evaluations.attention(2026) == {"year": 2026, "status": "ACTION_RECOMMENDED", "status_text": "A W-4 change is recommended",
                                               "trigger": "Interest: 0.01 USD → 5,000.00 USD", "since": latest["created_at"]}
        evaluations.seen(2026)
        assert evaluations.attention(2026) is None and evaluations.attention(2026, "unit-1") is None
    finally:
        store.close()


def test_a_new_w4_takes_effect_after_the_next_paycheck():
    zen = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert zen["job"]["payroll"] == {"next_pay_date": "2026-10-09", "paychecks_left": 11, "delay_checks": 1, "paychecks_changed": 10}
    assert zen["job"]["paychecks_left"] == 10
    # Payroll that puts it in at once: all eleven change.
    at_once = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), policy=TaxZenPolicy(w4_delay_checks=0))
    assert at_once["job"]["paychecks_left"] == 11
    # One paycheck left: a W-4 handed in now changes nothing this year.
    last = advise(year(interest=500000), [{**JOB, "paychecks_left": 1}], FEDERAL, {}, [], 2026, date(2026, 12, 20))
    assert "job" not in last and any("wouldn't take effect" in note for note in last["notes"])
    assert projection(JOB, date(2026, 9, 30), 3).paychecks_changed == 8


def test_with_two_jobs_the_one_with_the_most_paychecks_left_changes():
    bistro = {**JOB, "key": "employer-2", "name": "Bistro", "paychecks_left": 5, "per_check": {**JOB["per_check"], "wages": 500000}}
    zen = advise(year(interest=500000), [bistro, JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert zen["job"]["name"] == "Acme" and [choice["name"] for choice in zen["choices"]] == ["Bistro", "Acme"]


def test_every_w4_answer_is_listed_and_step_3_is_offered_with_dependents():
    owing = advise(year(interest=500000), [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))
    assert {item["field"] for item in owing["job"]["recommendations"]} == {"4(a)", "4(c)"}
    assert all(abs(item["year_end_minor"]) < 100 for item in owing["job"]["recommendations"])
    # A refund, with 2,000 of Step 3 credits on the W-4: raising Step 3 lowers withholding as 4(b) does.
    job = {**JOB, "per_check": {**JOB["per_check"], "federal": 47936 - 7692}, "values": {"federal_withheld": 1246336}}
    refund = advise(year(withheld=1246336 + 300000), [job], FEDERAL, {job["key"]: {"credits": 200000}}, [], 2026, date(2026, 9, 30))
    step3 = refund["job"]["step3"]
    assert step3["field"] == "3" and step3["amount"] > 200000 and abs(step3["year_end_minor"]) < 100
    assert {item["field"] for item in refund["job"]["recommendations"]} == {"4(b)", "3"}


def test_the_architecture_example_owing_3700_steered_to_owing_500():
    # docs/taxes.md "Design": 3,700 owed, keeping cash with at most 999 owed and a 499 buffer: aim to owe 500.
    estimate_ = answer(1246500 + 370000, 1246500)
    policy = TaxZenPolicy(strategy="cash_retention", max_owed_minor=99900, buffer_minor=49900)
    zen = advise(estimate_, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), policy=policy)
    assert (zen["target_minor"], zen["status"], zen["job"]["primary"]) == (-50000, "ACTION_RECOMMENDED", "extra")
    # 3,200 more over the ten paychecks it changes: 320 each.
    assert zen["job"]["extra"]["per_check_minor"] == 32000 and zen["job"]["extra"]["year_end_minor"] == -50000


def test_the_1000_line_for_the_safe_harbor():
    # Paying only 80% of a 5,000 tax: owing 999 is under the line; owing 1,000 isn't, and 80% is short of the 90% required.
    assert safe_harbor.evaluate(2026, 500000, 400100, 0, [], None, date(2026, 12, 31))["satisfied"]
    assert not safe_harbor.evaluate(2026, 500000, 400000, 0, [], None, date(2026, 12, 31))["satisfied"]


def test_solving_a_w4_box_only_moves_withholding_one_way():
    wages, checks, offset = JOB["per_check"]["wages"], JOB["pay_frequency"], 0
    higher = [solve(FEDERAL, wages, checks, {}, offset, target)["per_check"] for target in range(48000, 60000, 1500)]
    lower = [solve(FEDERAL, wages, checks, {}, offset, target)["per_check"] for target in range(47000, 30000, -2000)]
    assert higher == sorted(higher) and lower == sorted(lower, reverse=True)
    # Asking 4(a) to lower withholding can't be done: it only raises it.
    assert solve(FEDERAL, wages, checks, {}, offset, 30000, "other_income")["unreachable"]


def test_an_answer_the_engine_doesnt_confirm_is_adjusted_and_checked_again():
    estimate_ = year(interest=500000)
    first = advise(estimate_, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30))

    def recheck(key, more):  # An engine that counts 50 more paid than the straight line does (a credit that grows, say).
        return year(withheld=1246336 + more, interest=500000)["result_minor"] + 5000
    zen = advise(estimate_, [JOB], FEDERAL, {}, [], 2026, date(2026, 9, 30), recheck=recheck)
    extra, rest = zen["job"]["extra"], zen["job"]["rest"]
    # Asked again with each paycheck aimed at the gap it reported: 5.00 less a paycheck, and then it agrees.
    assert extra["checked"] and extra["per_check_minor"] == first["job"]["extra"]["per_check_minor"] - 500 and abs(extra["checked_year_end_minor"]) < 100
    assert rest["checked"] and abs(rest["checked_year_end_minor"]) < 100 and rest["amount"] < first["job"]["rest"]["amount"]
