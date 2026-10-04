"""Tax Zen (docs/taxes.md): what to put on a W-4, or pay ahead, so the year's return comes out at $0.

The return (finance/tax_return.py) says what the year's tax is and what will have been paid by Dec 31 at today's
withholding. Tax Zen changes one job's W-4 for the paychecks left:
- each paycheck's federal withholding is worked out as payroll does (IRS Publication 15-T, annual percentage method, 2020+
  W-4: Step 2's half-size schedule, Step 3 credits, 4(a) other income, 4(b) deductions, 4(c) extra), then matched to what
  the pay stub actually withholds (the difference is kept, so a W-4 you haven't entered or a payroll quirk carries over);
- owing: raise Step 4(a) other income (or add 4(c) extra per paycheck); getting a refund: raise Step 4(b) deductions. The
  search is over whole dollars, as the W-4 asks, and keeps the one that lands nearest $0. Withholding only rises as 4(a)
  rises and only falls as 4(b) rises, so the search is exact.
Two answers: for the paychecks left this year (larger, since fewer paychecks catch up), and from January (a full year at
the same pay). Without withholding to change (1099 work), it is advance tax instead: the 1040-ES quarters.

The aim is the household's policy (docs/tax_intelligence_architecture.md §12, §24): $0 (precision, the default), a small
refund, keeping cash while owing under a limit less a safety buffer, or owing as much as the safe harbor allows. Tax Zen
is a status, not a yes or no (§26): ZEN, WATCH, AT_RISK (on track, but the likely range reaches a penalty),
ACTION_RECOMMENDED, REVIEW_REQUIRED (the two tax engines disagree), INSUFFICIENT_DATA or ENGINE_UNSUPPORTED. The safe
harbor is finance/safe_harbor.py. A W-4 answer is checked by working the return out again with it (§46) before it's
shown as checked.

Steady advice (§25): each evaluation is kept (tax_zen_evaluations). Tax Zen leaves ZEN only past 1.5 times its band, and
a new W-4 answer replaces the last one only when it moves withholding by $25 or more a paycheck, the status got worse,
or something material changed (a new job or form, or pay per paycheck moving by more than 10%). What changed since the
last evaluation is said in words (§43), and a status that got worse is put on Home until the Taxes page is opened (§42).
"""

from datetime import date
from decimal import ROUND_CEILING, Decimal
import hashlib
import json
import logging
import sqlite3
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..core.logs import log_failure
from ..core.money import format_minor, to_minor
from ..library.storage import now
from .safe_harbor import NO_PENALTY_BELOW, due_dates, required_payment
from .safe_harbor import evaluate as safe_harbor
from .withholding import ENGINE as WITHHOLDING
from .withholding import W4_DELAY_CHECKS, W4Recommendation, projection

__all__ = ["due_dates", "advance_tax", "advise", "withholding", "plan_tax_zen", "TaxZenPolicy"]

log = logging.getLogger(__name__)

CURRENCY = "USD"
ZEN_WITHIN = 100  # A result under $1 either way is Tax Zen: withholding is in cents, the W-4 in whole dollars.
LEAVE_ZEN = Decimal("1.5")  # Once Tax Zen, it takes 1.5 times the band to leave it (§25).
STEADY_PER_CHECK = 2500  # A new W-4 answer must move withholding by $25 a paycheck to replace the last one (§25).
MATERIAL_PAY_BP = 1000  # Pay per paycheck moving by more than 10% is a material change.
STATUS_TEXT = {"ZEN": "Tax Zen", "WATCH": "Close: watch it", "AT_RISK": "On track, but it could turn", "ACTION_RECOMMENDED": "A W-4 change is recommended",
               "REVIEW_REQUIRED": "Check the return first", "INSUFFICIENT_DATA": "Not enough to go on yet", "ENGINE_UNSUPPORTED": "Not covered by the tax engine"}
# From best to worst, for "the status got worse" (the two that aren't advice rank with neither).
RANK = {"ZEN": 0, "WATCH": 1, "AT_RISK": 2, "ACTION_RECOMMENDED": 3, "REVIEW_REQUIRED": 4}
NOTIFY = frozenset({"AT_RISK", "ACTION_RECOMMENDED", "REVIEW_REQUIRED"})


class TaxZenPolicy(BaseModel):
    """What Tax Zen aims at, saved with the year's typed values ("zen_policy"). Amounts in cents."""
    model_config = ConfigDict(extra="forbid")
    strategy: Literal["precision", "small_refund", "cash_retention", "safe_harbor"] = "precision"
    refund_minor: int = Field(default=20_000, ge=0, le=10_000_000)  # small_refund: the refund to aim for.
    max_owed_minor: int = Field(default=99_900, ge=0, le=10_000_000)  # cash_retention: the most you're willing to owe in April.
    buffer_minor: int = Field(default=40_000, ge=0, le=10_000_000)  # cash_retention, safe_harbor: kept below the limit for forecast error.
    band_minor: int = Field(default=10_000, ge=100, le=1_000_000)  # Within this of the aim is Tax Zen (precision: within a dollar).
    watch_minor: int = Field(default=50_000, ge=100, le=10_000_000)  # Within this of the aim, and safe: watch, no change asked.
    w4_delay_checks: int = Field(default=W4_DELAY_CHECKS, ge=0, le=6)  # Paychecks before a new W-4 takes effect (finance/withholding.py).


def policy_of(inputs):
    """The saved policy: {"strategy", and dollar text for "refund", "max_owed", "buffer"} (the page sends what you typed)."""
    saved = dict(inputs.get("zen_policy") or {})
    try:
        for text, key in (("refund", "refund_minor"), ("max_owed", "max_owed_minor"), ("buffer", "buffer_minor")):
            if saved.get(text) not in (None, ""):
                saved[key] = to_minor(str(saved.pop(text)), CURRENCY)
            saved.pop(text, None)
        return TaxZenPolicy.model_validate(saved)
    except ValueError:
        return TaxZenPolicy()


def goal(policy: TaxZenPolicy, total_tax, required):
    """The year-end result to aim at (positive: a refund; negative: owed)."""
    if policy.strategy == "small_refund":
        return policy.refund_minor
    if policy.strategy == "cash_retention":
        return -max(0, policy.max_owed_minor - policy.buffer_minor)
    if policy.strategy == "safe_harbor":  # Owing up to what the required payment leaves, or under $1,000, carries no penalty.
        return -max(0, max(total_tax - required, NO_PENALTY_BELOW - 100) - policy.buffer_minor)
    return 0


def status_of(result, target, policy: TaxZenPolicy, safe, comparison=None, was_zen=False, low=None):
    """ZEN, WATCH, AT_RISK or ACTION_RECOMMENDED, or REVIEW_REQUIRED when two engines disagree; and why. was_zen: the last
    evaluation was ZEN, so it takes 1.5 times the band to leave it. low: the worst end of the likely range."""
    if comparison and comparison.get("ready") and not comparison.get("agree"):
        return "REVIEW_REQUIRED", "The two tax engines disagree on this return; check the lines before changing a W-4."
    status, reason = settled(result, target, policy, safe, was_zen)
    if status in ("ZEN", "WATCH") and low is not None and low <= -NO_PENALTY_BELOW < result:
        return "AT_RISK", (f"The year is on track, but if the rest of the year's pay or interest comes in differently you could owe up to "
                           f"{shown(-low)}, enough for an underpayment penalty; a little more withholding would cover it.")
    return status, reason


def settled(result, target, policy: TaxZenPolicy, safe, was_zen=False):
    gap = abs(result - target)
    within = ZEN_WITHIN if policy.strategy == "precision" else policy.band_minor
    if was_zen:
        within = int(within * LEAVE_ZEN)
    if gap < within and safe["satisfied"]:
        return "ZEN", "The year ends where your Tax Zen aim is."
    if gap <= policy.watch_minor and safe["satisfied"]:
        return "WATCH", f"The year ends {shown(gap)} from your aim, and no underpayment penalty is expected: no change is needed yet."
    if not safe["satisfied"]:
        return "ACTION_RECOMMENDED", "Payments are below the safe harbor, so an underpayment penalty is likely without a change."
    return "ACTION_RECOMMENDED", f"The year ends {shown(gap)} from your aim."


def shown(amount):
    return format_minor(amount, CURRENCY)


def withholding(federal, wages, checks, w4):
    """One paycheck's federal withholding for these W-4 entries, by the withholding engine (finance/withholding.py: Pub 15-T;
    all amounts in cents; 4(a), 4(b), Step 3 a year)."""
    return WITHHOLDING.per_check(federal, wages, checks, w4)


FIELDS = {"other_income": "4(a)", "deductions": "4(b)", "credits": "3"}


def solve(federal, wages, checks, w4, offset, target, key=None):
    """The whole-dollar Step 4(a) (owing) or 4(b) (refund) that brings the paycheck's withholding nearest `target`; or the
    given box (Step 3 credits lower withholding, as 4(b) does)."""
    def paid(changed):
        return max(0, withholding(federal, wages, checks, changed) + offset)
    now = paid(w4)
    if abs(target - now) < 1:
        return {"field": None, "amount": 0, "per_check": now}
    if key is None:
        key = "other_income" if target > now else "deductions"
    up = key == "other_income"
    if up != (target > now):
        return {"field": FIELDS[key], "key": key, "amount": None, "per_check": now, "unreachable": True}
    base = w4.get(key, 0)

    def at(dollars):
        return paid({**w4, key: base + dollars * 100})
    reached = (lambda value: value >= target) if up else (lambda value: value <= target)
    high = 1
    while not reached(at(high)):
        high *= 2
        if high > 50_000_000:  # $50 million: no W-4 entry gets there (withholding can't go below zero).
            return {"field": FIELDS[key], "amount": None, "per_check": at(high), "unreachable": True}
    low = 0
    while high - low > 1:
        middle = (low + high) // 2
        if reached(at(middle)):
            high = middle
        else:
            low = middle
    best = min((high, low), key=lambda dollars: (abs(at(dollars) - target), dollars))
    return {"field": FIELDS[key], "key": key, "amount": base + best * 100, "per_check": at(best)}


def advance_tax(year, today, needed, payments, safe_total, owed_after_withholding):
    """The quarters: paid so far (each payment counts for the first quarter due on or after it), and what to pay in each
    quarter still ahead so that estimated payments cover `needed`."""
    dates = due_dates(year)
    paid = [0, 0, 0, 0]
    for payment in payments:
        day = date.fromisoformat(payment["date"])
        index = next((number for number, due in enumerate(dates) if day <= due), 3)
        paid[index] += payment["amount_minor"]
    ahead = [index for index, due in enumerate(dates) if due >= today]
    left = max(0, needed - sum(paid))
    share = [0, 0, 0, 0]
    if ahead and left:
        each = int((Decimal(left) / len(ahead)).to_integral_value(ROUND_CEILING))
        for position, index in enumerate(ahead):
            share[index] = each if position < len(ahead) - 1 else left - each * (len(ahead) - 1)
    safe_each = int((Decimal(safe_total) / 4).to_integral_value(ROUND_CEILING)) if safe_total is not None else None
    rows = [{"quarter": index + 1, "due": dates[index].isoformat(), "paid_minor": paid[index], "pay_minor": share[index],
             "safe_by_now_minor": safe_each * (index + 1) if safe_each is not None else None,
             "display": {"paid_minor": shown(paid[index]), "pay_minor": shown(share[index]),
                         **({"safe_by_now_minor": shown(safe_each * (index + 1))} if safe_each is not None else {})}} for index in range(4)]
    notes = []
    if left and not ahead:
        notes.append("Every due date for this year has passed: pay what's left with the return, and a small underpayment penalty may apply.")
    missed = [row["quarter"] for row in rows if dates[row["quarter"] - 1] < today and safe_each is not None and sum(paid[:row["quarter"]]) < safe_each * row["quarter"]]
    if missed and owed_after_withholding >= NO_PENALTY_BELOW:
        notes.append(f"Payments through quarter {missed[-1]} were below the safe harbor, so an underpayment penalty may apply for that period (Form 2210).")
    return {"needed_minor": needed, "paid_minor": sum(paid), "left_minor": left, "quarters": rows, "safe_harbor_minor": safe_total,
            "display": {"needed_minor": shown(needed), "paid_minor": shown(sum(paid)), "left_minor": shown(left),
                        **({"safe_harbor_minor": shown(safe_total)} if safe_total is not None else {})}, "notes": notes}


def advise(estimate, jobs, federal, w4s, estimated_payments, year, today=None, choose=None, prior=None, policy=None, recheck=None,
           outcomes=None, previous=None, changed=None):
    """Tax Zen for one return. jobs: the gathered jobs (tax_year.jobs); w4s: {job key: W-4 entries in cents}; prior: last
    year's {"tax_minor", "agi_minor"} for the estimated-tax safe harbor; policy: TaxZenPolicy (default $0); recheck(job key,
    more withheld this year) -> the year-end result worked out again by the tax engine, to check a W-4 answer.
    outcomes: the likely range ({"low_minor", "high_minor", "confidence"}, §23); previous: the last evaluation
    (TaxZenEvaluations.latest); changed: what changed since then (changes())."""
    today = today or date.today()
    policy = policy or TaxZenPolicy()
    result = estimate.get("result_minor")
    if result is None:
        status = "ENGINE_UNSUPPORTED" if estimate.get("unsupported") else "INSUFFICIENT_DATA"
        reason = (estimate.get("notes") or [""])[0] or "Tax Zen needs the year's return first (it needs the confirmed federal tax table)."
        return {"ready": False, "status": status, "status_text": STATUS_TEXT[status], "note": reason, "policy": policy.model_dump()}
    covered_elsewhere = estimate["payments_minor"] - estimate["estimated_minor"]
    refundable = estimate.get("refundable_credits_minor", 0)
    safe = safe_harbor(year, estimate["total_tax_minor"], covered_elsewhere - refundable, refundable, estimated_payments, prior, today)
    required, _ = required_payment(estimate["total_tax_minor"], prior)
    target = goal(policy, estimate["total_tax_minor"], required)
    was_zen = bool(previous and previous.get("status") == "ZEN")
    status, reason = status_of(result, target, policy, safe, estimate.get("comparison"), was_zen, outcomes["low_minor"] if outcomes else None)
    view = {"ready": True, "zen": status == "ZEN", "status": status, "status_text": STATUS_TEXT[status], "reason": reason, "policy": policy.model_dump(),
            "target_minor": target, "result_minor": result, "safe_harbor": safe, "jobs": [], "notes": [],
            "display": {"result_minor": shown(abs(result)), "target_minor": shown(abs(target)), "required_minor": shown(safe["required_minor"]),
                        **{key: f"{getattr(policy, key) // 100}" for key in ("refund_minor", "max_owed_minor", "buffer_minor")}}}
    if outcomes:  # §23: where the year likely ends, with the projected pay and interest moved down and up.
        view["range"] = {**outcomes, "expected_minor": result,
                         "display": {key: f"{'refund of ' if value > 0 else 'owing ' if value < 0 else ''}{shown(abs(value))}"
                                     for key, value in (("low_minor", outcomes["low_minor"]), ("high_minor", outcomes["high_minor"]))}}
    if changed and changed.get("texts"):
        view["changed"] = changed
    changeable = [job for job in jobs if job["paychecks_left"] > 0 and job["pay_frequency"] and job["per_check"]["wages"] > 0]
    if changeable and federal is None:
        view["notes"].append("Confirm the year's federal tax table to get the W-4 entries: payroll's withholding is worked out from it.")
    elif changeable:
        # With two jobs, the one with the most paychecks left (the change spreads thinnest there), then the larger paycheck.
        chosen = next((job for job in changeable if job["key"] == choose), None) or max(changeable, key=lambda job: (job["paychecks_left"], job["per_check"]["wages"]))
        view["choices"] = [{"key": job["key"], "name": job["name"]} for job in changeable]
        advice = job_advice(chosen, estimate, federal, w4s.get(chosen["key"], {}), target, today, policy.w4_delay_checks)
        if advice is None:
            view["notes"].append(f"A W-4 handed in now wouldn't take effect before {chosen['name']}'s last paycheck this year; see January, or pay "
                                 "estimated tax.")
        else:
            view["job"] = advice
            if previous:
                steady(advice, previous, status, changed, result)
            if recheck:
                check_advice(advice, recheck, federal, chosen, w4s.get(chosen["key"], {}))
            advice["recommendations"] = recommendations(advice)
        if status == "AT_RISK" and advice:  # The cushion: enough extra a paycheck that even the low end owes under $1,000.
            short = -outcomes["low_minor"] - (NO_PENALTY_BELOW - 100)
            per_check = int((Decimal(short) / advice["paychecks_left"]).to_integral_value(ROUND_CEILING))
            view["cushion"] = {"per_check_minor": per_check, "job": chosen["name"],
                               "text": f"To be safe, add {shown(per_check)} of extra withholding a paycheck at {chosen['name']} (W-4 Step 4(c)): even if "
                                       "the rest of the year comes in at the low end, you'd owe under $1,000."}
    elif jobs:
        view["notes"].append("No paychecks are left this year on the jobs here, so a W-4 change can't help this year; see January.")
    # Advance tax: what estimated payments must cover, after withholding and refundable credits.
    needed = max(0, estimate["total_tax_minor"] - covered_elsewhere)
    if not prior or prior.get("tax_minor") is None:
        view["notes"].append("Enter last year's total tax (and AGI) to see the safe harbor based on it; until then it is 90% of this year's.")
    safe_total = max(0, required - covered_elsewhere)
    if needed or estimated_payments:
        view["advance"] = advance_tax(year, today, needed, estimated_payments, safe_total, needed)
    # State: extra withholding per paycheck on the chosen job, or estimated payments.
    state = estimate.get("state")
    if state and state.get("complete"):
        owed = -state["result_minor"]
        job = view.get("job")
        if abs(owed) >= ZEN_WITHIN and job:
            per_check = int((Decimal(abs(owed)) / job["paychecks_left"]).to_integral_value(ROUND_CEILING))
            view["state"] = {"state": state["state"], "owed": owed > 0, "per_check_minor": per_check,
                             "text": (f"Add {shown(per_check)} of extra {state['state']} withholding to each of {job['name']}'s remaining paychecks (on the state's "
                                      "withholding form)." if owed > 0 else
                                      f"{state['state']} is on track to refund about {shown(abs(owed))}: lower its withholding by about {shown(per_check)} a paycheck "
                                      "on the state's withholding form.")}
        elif abs(owed) >= ZEN_WITHIN:
            view["state"] = {"state": state["state"], "owed": owed > 0,
                             "text": f"{state['state']}: {'pay about ' + shown(owed) + ' in state estimated tax' if owed > 0 else 'refund of about ' + shown(-owed)} "
                                     "(most states use the federal due dates)."}
    return view


def paycheck_job(label, result, value):
    """A planned paycheck (finance/paycheck.py) as a whole year's job, with its W-4 as the planner has it."""
    groups = {group["group"]: group for group in result["groups"]}
    federal = next((line for line in groups["tax"]["lines"] if line["category"] == "federal_income_tax"), None)
    state = next((line for line in groups["tax"]["lines"] if line["category"] == "state_income_tax"), None)
    medicare = next((line for line in groups["tax"]["lines"] if line["category"] == "medicare"), None)
    job = {"key": f"plan:{label}", "name": label, "owner": "", "pay_frequency": result["paychecks"], "paychecks_left": result["paychecks"],
           "paychecks_projected": result["paychecks"], "work_state": result["state"],
           "per_check": {"wages": result["wages"]["income_tax"]["per_check_minor"], "fica": result["wages"]["fica"]["per_check_minor"],
                         "federal": federal["per_check_minor"] if federal else 0, "state": state["per_check_minor"] if state else 0,
                         "medicare": medicare["per_check_minor"] if medicare else 0},
           "values": {"wages": result["wages"]["income_tax"]["annual_minor"], "ss_wages": result["wages"]["fica"]["annual_minor"],
                      "medicare_wages": result["wages"]["fica"]["annual_minor"], "federal_withheld": federal["annual_minor"] if federal else 0,
                      "state_withheld": state["annual_minor"] if state else 0, "medicare_withheld": medicare["annual_minor"] if medicare else 0}}
    w4 = {"step2": value.federal_step2, "credits": to_minor(value.federal_credits, CURRENCY), "other_income": to_minor(value.federal_other_income, CURRENCY),
          "deductions": to_minor(value.federal_deductions, CURRENCY), "extra": to_minor(value.federal_extra_withholding, CURRENCY)}
    return job, w4


def plan_tax_zen(paychecks, gathered, household, filing_status, year, tables_for, engine="engine_1"):
    """Tax Zen for a full year at planned pay: paychecks = [(label, paycheck result, PaycheckInput, replaces pay)]. The planned
    jobs take the place of this year's jobs when one replaces pay; the rest of the return (interest, tags, typed values) is
    this year's. Returns the year-end result with the W-4s in the plan, and the entry on the largest paycheck's W-4 that
    brings it to $0. engine: the tax engine that works out the return (finance/tax_engine.py)."""
    from .tax_engine import calculate
    from .tax_year import merge
    planned = [(paycheck_job(label, result, value), label) for label, result, value, _ in paychecks]
    replaced = any(replaces for *_, replaces in paychecks)
    jobs = [job for (job, _), _ in planned] + ([] if replaced else gathered["jobs"])
    facts = {**gathered, "jobs": jobs, "state": planned[0][0][0]["work_state"] if replaced and planned else gathered["state"]}
    merged = merge(year, filing_status, household, facts, {})
    tables = tables_for(["US", *([merged.state] if merged.state else [])])
    federal = tables.get("US") if tables.get("US", {}).get("status") == "verified" else None
    result = calculate(engine, merged, tables)
    if result["result_minor"] is None or not planned:
        return {"ready": False, "year": year, "note": result["notes"][0] if result["notes"] else "No planned paycheck."}
    (main, w4), label = max(planned, key=lambda item: item[0][0]["per_check"]["wages"])
    advice = job_advice(main, result, federal, w4, delay=0)  # A full year at the planned pay: the W-4 counts from its first paycheck.
    rest = advice["rest"]
    return {"ready": True, "year": year, "zen": abs(result["result_minor"]) < ZEN_WITHIN, "result_minor": result["result_minor"],
            "display": {"result_minor": shown(abs(result["result_minor"]))}, "job": label, "w4": rest,
            "notes": ["A full year at the planned pay, with this year's other income and deductions."]}


ROUND_TRIPS = 3  # §46: a W-4 answer the tax engine doesn't confirm is adjusted by the gap it reports, up to three times.


def check_advice(advice, recheck, federal=None, job=None, w4=None):
    """§46: work the return out again with each answer's withholding. When the engine's year-end differs by more than a
    cent a paycheck, aim each changed paycheck at the gap it reports and check again (the 4(c) amount directly; 4(a) or
    4(b) by solving again, with the job and table), up to ROUND_TRIPS times. `checked` is True when they agree."""
    left, actual, goal_minor = advice["paychecks_left"], advice["per_check_now_minor"], advice["goal_minor"]
    for name in ("rest", "extra"):
        part = advice.get(name)
        if not part or part.get("year_end_minor") is None:
            continue
        for _ in range(ROUND_TRIPS):
            more = left * (part["per_check"] - actual) if name == "rest" else left * part["per_check_minor"]
            again = recheck(advice["key"], more)
            part["checked"] = again is not None and abs(again - part["year_end_minor"]) <= left
            part["checked_year_end_minor"] = again
            if part["checked"] or again is None or advice.get("steady"):
                break
            gap = Decimal(goal_minor - again) / left  # Per changed paycheck, by the engine's own figure.
            if name == "extra":
                step = int(gap.to_integral_value(ROUND_CEILING))
                part.update({"per_check_minor": part["per_check_minor"] + step, "total_4c_minor": part["total_4c_minor"] + step,
                             "year_end_minor": again + step * left})
            elif federal is not None and job is not None and part.get("amount") is not None:
                solved = solve(federal, job["per_check"]["wages"], advice["frequency"], w4 or {}, advice["offset_minor"], Decimal(part["per_check"]) + gap,
                               part.get("key"))
                if solved.get("amount") is None:
                    break
                part.update({**solved, "year_end_minor": again + left * (solved["per_check"] - part["per_check"])})
            else:
                break
        displayed(part)


def job_advice(job, estimate, federal, w4, goal_minor=0, today=None, delay=W4_DELAY_CHECKS):
    """Rest of the year and from January, for one job, aiming at goal_minor (the year-end result; 0 by default). A W-4
    handed in today changes the paychecks after the first `delay` (finance/withholding.py); None when none are left."""
    payroll = projection(job, today or date.today(), delay)
    result, left, checks = estimate["result_minor"], payroll.paychecks_changed, job["pay_frequency"]
    if not left:
        return None
    wages, actual = job["per_check"]["wages"], job["per_check"]["federal"]
    offset = actual - withholding(federal, wages, checks, w4)  # What payroll does that the W-4 entered here doesn't explain.
    target = Decimal(actual) - Decimal(result - goal_minor) / left  # Per changed paycheck: short of the aim raises it, past it lowers it.
    rest = solve(federal, wages, checks, w4, offset, target)
    rest_year_end = result + left * (rest["per_check"] - actual) if rest.get("amount") is not None or rest["field"] is None else None
    advice = {"key": job["key"], "name": job["name"], "paychecks_left": left, "frequency": checks, "per_check_now_minor": actual, "offset_minor": offset,
              "goal_minor": goal_minor, "rest": {**rest, "year_end_minor": rest_year_end}, "primary": "rest", "payroll": payroll.as_dict()}
    if result < goal_minor:  # Short of the aim: the same catch-up as a fixed extra amount per paycheck, one W-4 box (§20).
        extra = int((Decimal(goal_minor - result) / left).to_integral_value(ROUND_CEILING))
        advice["extra"] = {"per_check_minor": extra, "total_4c_minor": w4.get("extra", 0) + extra, "year_end_minor": result + extra * left}
        advice["primary"] = "extra"
    elif result > goal_minor and w4.get("credits"):  # A refund, and the W-4 claims dependents: Step 3 can lower withholding too (§19).
        step3 = solve(federal, wages, checks, w4, offset, target, "credits")
        if step3.get("amount") is not None:
            advice["step3"] = {**step3, "year_end_minor": result + left * (step3["per_check"] - actual)}
    # From January: a full year at this paycheck. This job's withholding must cover the tax the rest of the return doesn't.
    others = estimate["payments_minor"] - estimate["estimated_minor"] - job["values"]["federal_withheld"]
    full_target = Decimal(estimate["total_tax_minor"] - others + goal_minor) / checks
    january = solve(federal, wages, checks, w4, offset, full_target)
    january_year_end = (others + checks * january["per_check"]) - estimate["total_tax_minor"]
    advice["january"] = {**january, "year_end_minor": january_year_end}
    for part in (advice["rest"], advice["january"], advice.get("extra") or {}, advice.get("step3") or {}):
        displayed(part)
    advice["display"] = {"per_check_now_minor": shown(actual), "goal_minor": shown(abs(goal_minor))}
    advice["recommendations"] = recommendations(advice)
    return advice


def recommendations(advice):
    """Every W-4 answer for the rest of the year (§18–20), simplest first: fewest boxes changed, then the smallest change in
    withholding a paycheck. The page leads with the first."""
    found = []
    actual = advice["per_check_now_minor"]
    rest = advice["rest"]
    if rest.get("amount") is not None and rest.get("field"):
        found.append(W4Recommendation(advice["key"], rest["field"], rest["amount"], rest["per_check"], rest["year_end_minor"], checked=rest.get("checked")))
    if advice.get("extra"):
        extra = advice["extra"]
        found.append(W4Recommendation(advice["key"], "4(c)", extra["total_4c_minor"], actual + extra["per_check_minor"], extra["year_end_minor"],
                                      checked=extra.get("checked")))
    if advice.get("step3"):
        step3 = advice["step3"]
        found.append(W4Recommendation(advice["key"], "3", step3["amount"], step3["per_check"], step3["year_end_minor"]))
    return [item.as_dict() for item in sorted(found, key=lambda item: (item.fields_changed, abs(item.per_check_minor - actual)))]


def displayed(part):
    part["display"] = {key: shown(value) for key, value in part.items() if key.endswith("_minor") and isinstance(value, int)}
    if part.get("amount") is not None and "field" in part:
        part["display"]["amount"] = f"${part['amount'] // 100:,}"
        part["display"]["per_check"] = shown(part["per_check"])
    return part


def per_check_after(advice):
    """Each remaining paycheck's federal withholding with the main W-4 answer, or None when no entry gets there."""
    if advice["primary"] == "extra" and advice.get("extra"):
        return advice["per_check_now_minor"] + advice["extra"]["per_check_minor"]
    rest = advice["rest"]
    return rest["per_check"] if rest.get("amount") is not None or rest.get("field") is None else None


def w4_summary(advice):
    """What's kept of a W-4 answer (tax_zen_evaluations.w4_json), to hold it steady next time."""
    if not advice:
        return None
    rest, extra = advice["rest"], advice.get("extra") or {}
    return {"key": advice["key"], "name": advice["name"], "primary": advice["primary"], "field": rest.get("field"), "field_key": rest.get("key"),
            "amount": rest.get("amount"), "extra_minor": extra.get("per_check_minor"), "total_4c_minor": extra.get("total_4c_minor"),
            "per_check_minor": per_check_after(advice)}


def steady(advice, previous, status, changed, result):
    """§25: keep the last W-4 answer when the new one would move withholding by less than $25 a paycheck, the status isn't
    worse and nothing material changed. The kept answer's year-end is worked out again from today's figures."""
    before = previous.get("w4") or {}
    now_per_check = per_check_after(advice)
    if (before.get("key") != advice["key"] or before.get("primary") != advice["primary"] or (changed or {}).get("material")
            or RANK.get(status, 9) > RANK.get(previous.get("status"), 9) or now_per_check is None or before.get("per_check_minor") is None
            or abs(now_per_check - before["per_check_minor"]) >= STEADY_PER_CHECK):
        return
    year_end = result + advice["paychecks_left"] * (before["per_check_minor"] - advice["per_check_now_minor"])
    if advice["primary"] == "extra":
        advice["extra"].update({"per_check_minor": before["extra_minor"], "total_4c_minor": before["total_4c_minor"], "year_end_minor": year_end})
        displayed(advice["extra"])
    else:
        advice["rest"].update({"field": before["field"], "key": before["field_key"], "amount": before["amount"], "per_check": before["per_check_minor"],
                               "year_end_minor": year_end})
        displayed(advice["rest"])
    since = (previous.get("created_at") or "")[:10]
    advice["steady"] = {"since": since, "text": f"Your W-4 advice from {since} still stands: today's figures would change withholding by less "
                                                f"than {shown(STEADY_PER_CHECK)} a paycheck, not enough to file a new W-4 for."}


def assumptions(merged, gathered):
    """What an evaluation rests on, kept to say next time what changed: the return's amounts, each job's paycheck, the
    sources and kinds of the gathered values."""
    figures = {key: value for key, value in merged.model_dump().items() if isinstance(value, int) and not isinstance(value, bool) and key != "year" and value}
    return {"fields": figures, "sources": gathered.get("sources", {}), "kinds": gathered.get("kinds", {}),
            "jobs": {job["key"]: {"name": job["name"], "wages": job["per_check"]["wages"], "federal": job["per_check"]["federal"],
                                  "stubs": job.get("stubs", 0), "paychecks_left": job["paychecks_left"]} for job in gathered.get("jobs", [])},
            "typed_jobs": [[job.name, job.wages, job.federal_withheld] for job in merged.jobs[len(gathered.get("jobs", [])):]]}


FORM_SOURCES = ("1099", "1098", "5498")


def changes(before, after):
    """What changed between two evaluations' assumptions, in words (§43), and whether any of it is material (§25)."""
    if not before:
        return {"texts": [], "material": False}
    texts, material = [], False
    old_jobs, new_jobs = before.get("jobs", {}), after.get("jobs", {})
    for key, job in new_jobs.items():
        was = old_jobs.get(key)
        if not was:
            texts.append(f"New job: {job['name']}")
            material = True
            continue
        if job["stubs"] > was["stubs"]:
            count = job["stubs"] - was["stubs"]
            texts.append(f"{job['name']}: {count} new pay stub{'s' if count != 1 else ''}")
        if was["wages"] and abs(job["wages"] - was["wages"]) * 10000 > MATERIAL_PAY_BP * was["wages"]:
            texts.append(f"{job['name']}: pay per paycheck {shown(was['wages'])} → {shown(job['wages'])}")
            material = True
        if job["federal"] != was["federal"]:
            texts.append(f"{job['name']}: federal withheld per paycheck {shown(was['federal'])} → {shown(job['federal'])}")
    for key, job in old_jobs.items():
        if key not in new_jobs:
            texts.append(f"No longer counted: {job['name']}")
            material = True
    if before.get("typed_jobs") != after.get("typed_jobs"):
        texts.append("The jobs you typed in changed")
        material = True
    for field, source in after.get("sources", {}).items():
        if source.startswith(FORM_SOURCES) and not before.get("sources", {}).get(field, "").startswith(FORM_SOURCES):
            texts.append(f"A tax form now gives {field.replace('_', ' ')} ({source})")
            material = True
    old_fields, new_fields = before.get("fields", {}), after.get("fields", {})
    moved = sorted(((key, old_fields.get(key, 0), new_fields.get(key, 0)) for key in set(old_fields) | set(new_fields)
                    if abs(new_fields.get(key, 0) - old_fields.get(key, 0)) >= 10_000), key=lambda item: -abs(item[2] - item[1]))
    texts += [f"{key.replace('_', ' ').capitalize()}: {shown(old)} → {shown(new)}" for key, old, new in moved]
    return {"texts": texts[:8], "material": material}


class TaxZenEvaluations:
    """Tax Zen's past evaluations (tax_zen_evaluations, migration 060): never rewritten, except when they were seen."""

    def __init__(self, store):
        self.store = store

    def latest(self, year, unit="me"):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM tax_zen_evaluations WHERE year=? AND unit=? ORDER BY id DESC LIMIT 1", (year, unit)).fetchone()
        return self.shaped(row) if row else None

    @staticmethod
    def shaped(row):
        found = dict(row)
        found["policy"] = json.loads(found.pop("policy_json"))
        found["w4"] = json.loads(found.pop("w4_json")) if found.get("w4_json") else None
        found["assumptions"] = json.loads(found.pop("assumptions_json"))
        return found

    def record(self, year, unit, view, calculation_id, facts, trigger):
        """Keep this evaluation when its status, W-4 answer or inputs differ from the last one. A failure is logged, never raised."""
        w4 = w4_summary(view.get("job"))
        inputs_hash = hashlib.sha256(json.dumps(facts, sort_keys=True, default=str).encode()).hexdigest()
        outcome = view.get("range") or {}
        try:
            last = self.latest(year, unit)
            if last and last["status"] == view["status"] and last["w4"] == w4 and last["inputs_hash"] == inputs_hash:
                return last
            with self.store.connection() as db:
                db.execute("INSERT INTO tax_zen_evaluations(year,unit,calculation_id,policy_json,status,result_minor,low_minor,high_minor,confidence,"
                           "w4_json,assumptions_json,inputs_hash,trigger,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (year, unit, calculation_id, json.dumps(view.get("policy") or {}), view["status"], view.get("result_minor"),
                            outcome.get("low_minor"), outcome.get("high_minor"), outcome.get("confidence"), json.dumps(w4) if w4 else None,
                            json.dumps(facts, default=str), inputs_hash, trigger, now()))
            return self.latest(year, unit)
        except sqlite3.Error as exc:
            log_failure(log, "tax zen evaluation record", exc, year=year, unit=unit)
            return None

    def seen(self, year, unit="me"):
        """The Taxes page showed this return: what was new on it has been seen."""
        try:
            with self.store.connection() as db:
                db.execute("UPDATE tax_zen_evaluations SET seen_at=? WHERE year=? AND unit=? AND seen_at IS NULL", (now(), year, unit))
        except sqlite3.Error as exc:
            log_failure(log, "tax zen seen", exc, year=year, unit=unit)

    def attention(self, year, unit="me"):
        """For Home (§42): the newest evaluation when it's unseen and worse than the last one seen; else None."""
        with self.store.connection() as db:
            newest = db.execute("SELECT * FROM tax_zen_evaluations WHERE year=? AND unit=? ORDER BY id DESC LIMIT 1", (year, unit)).fetchone()
            seen = db.execute("SELECT status FROM tax_zen_evaluations WHERE year=? AND unit=? AND seen_at IS NOT NULL ORDER BY id DESC LIMIT 1",
                              (year, unit)).fetchone()
        if not newest or newest["seen_at"] or newest["status"] not in NOTIFY or RANK[newest["status"]] <= RANK.get(seen["status"] if seen else "ZEN", 0):
            return None
        return {"year": year, "status": newest["status"], "status_text": STATUS_TEXT[newest["status"]], "trigger": newest["trigger"],
                "since": newest["created_at"]}
