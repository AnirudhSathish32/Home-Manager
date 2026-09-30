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
"""

from datetime import date, timedelta
from decimal import ROUND_CEILING, Decimal

from ..core.money import format_minor, to_minor
from .paycheck import step2_table
from .paystub import income_tax

CURRENCY = "USD"
ZEN_WITHIN = 100  # A result under $1 either way is Tax Zen: withholding is in cents, the W-4 in whole dollars.
# Estimated tax safe harbors (IRC §6654(d)(1)(B)): 90% of this year's tax, or 100% of last year's (110% when last year's
# AGI was above $150,000); no penalty when less than $1,000 is owed after withholding (§6654(e)(1)).
SAFE_THIS_YEAR_BP, SAFE_LAST_YEAR_BP, SAFE_LAST_YEAR_HIGH_BP, SAFE_HIGH_AGI, NO_PENALTY_BELOW = 9000, 10000, 11000, 15_000_000, 100_000


def shown(amount):
    return format_minor(amount, CURRENCY)


def withholding(federal, wages, checks, w4):
    """One paycheck's federal withholding by Pub 15-T for these W-4 entries (all amounts in cents; 4(a), 4(b), Step 3 a year)."""
    table = step2_table(federal) if w4.get("step2") else federal
    part = income_tax("US", table, wages, checks, None, w4.get("other_income", 0), w4.get("deductions", 0), w4.get("credits", 0))
    return part["estimate_minor"] + w4.get("extra", 0)


def solve(federal, wages, checks, w4, offset, target):
    """The whole-dollar Step 4(a) (owing) or 4(b) (refund) that brings the paycheck's withholding nearest `target`."""
    def paid(changed):
        return max(0, withholding(federal, wages, checks, changed) + offset)
    now = paid(w4)
    if abs(target - now) < 1:
        return {"field": None, "amount": 0, "per_check": now}
    key, up = ("other_income", True) if target > now else ("deductions", False)
    base = w4.get(key, 0)

    def at(dollars):
        return paid({**w4, key: base + dollars * 100})
    reached = (lambda value: value >= target) if up else (lambda value: value <= target)
    high = 1
    while not reached(at(high)):
        high *= 2
        if high > 50_000_000:  # $50 million: no W-4 entry gets there (withholding can't go below zero).
            return {"field": "4(b)" if not up else "4(a)", "amount": None, "per_check": at(high), "unreachable": True}
    low = 0
    while high - low > 1:
        middle = (low + high) // 2
        if reached(at(middle)):
            high = middle
        else:
            low = middle
    best = min((high, low), key=lambda dollars: (abs(at(dollars) - target), dollars))
    return {"field": "4(a)" if up else "4(b)", "key": key, "amount": base + best * 100, "per_check": at(best)}


def due_dates(year):
    """1040-ES due dates for a tax year: Apr 15, Jun 15, Sep 15 and Jan 15, moved to the next weekday when on a weekend."""
    dates = []
    for day in (date(year, 4, 15), date(year, 6, 15), date(year, 9, 15), date(year + 1, 1, 15)):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        dates.append(day)
    return dates


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


def advise(estimate, jobs, federal, w4s, estimated_payments, year, today=None, choose=None, prior=None):
    """Tax Zen for one return. jobs: the gathered jobs (tax_year.jobs); w4s: {job key: W-4 entries in cents}; prior: last
    year's {"tax_minor", "agi_minor"} for the estimated-tax safe harbor."""
    today = today or date.today()
    result = estimate.get("result_minor")
    if result is None or federal is None:
        return {"ready": False, "note": "Tax Zen needs the year's return first (it needs the confirmed federal tax table)."}
    zen = abs(result) < ZEN_WITHIN
    view = {"ready": True, "zen": zen, "result_minor": result, "display": {"result_minor": shown(abs(result))}, "jobs": [], "notes": []}
    changeable = [job for job in jobs if job["paychecks_left"] > 0 and job["pay_frequency"] and job["per_check"]["wages"] > 0]
    if changeable:
        chosen = next((job for job in changeable if job["key"] == choose), None) or max(changeable, key=lambda job: job["per_check"]["wages"])
        view["choices"] = [{"key": job["key"], "name": job["name"]} for job in changeable]
        view["job"] = job_advice(chosen, estimate, federal, w4s.get(chosen["key"], {}))
    elif jobs:
        view["notes"].append("No paychecks are left this year on the jobs here, so a W-4 change can't help this year; see January.")
    # Advance tax: what estimated payments must cover, after withholding and refundable credits.
    covered_elsewhere = estimate["payments_minor"] - estimate["estimated_minor"]
    needed = max(0, estimate["total_tax_minor"] - covered_elsewhere)
    safe = None
    if prior and prior.get("tax_minor") is not None:
        last = prior["tax_minor"] * (SAFE_LAST_YEAR_HIGH_BP if (prior.get("agi_minor") or 0) > SAFE_HIGH_AGI else SAFE_LAST_YEAR_BP) // 10000
        safe = min(estimate["total_tax_minor"] * SAFE_THIS_YEAR_BP // 10000, last)
    else:
        safe = estimate["total_tax_minor"] * SAFE_THIS_YEAR_BP // 10000
        view["notes"].append("Enter last year's total tax (and AGI) to see the safe harbor based on it; until then it is 90% of this year's.")
    safe = max(0, safe - covered_elsewhere)
    if needed or estimated_payments:
        view["advance"] = advance_tax(year, today, needed, estimated_payments, safe, needed)
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


def plan_tax_zen(paychecks, gathered, household, filing_status, year, tables_for, figures):
    """Tax Zen for a full year at planned pay: paychecks = [(label, paycheck result, PaycheckInput, replaces pay)]. The planned
    jobs take the place of this year's jobs when one replaces pay; the rest of the return (interest, tags, typed values) is
    this year's. Returns the year-end result with the W-4s in the plan, and the entry on the largest paycheck's W-4 that
    brings it to $0."""
    from .tax_return import estimate
    from .tax_year import merge
    planned = [(paycheck_job(label, result, value), label) for label, result, value, _ in paychecks]
    replaced = any(replaces for *_, replaces in paychecks)
    jobs = [job for (job, _), _ in planned] + ([] if replaced else gathered["jobs"])
    facts = {**gathered, "jobs": jobs, "state": planned[0][0][0]["work_state"] if replaced and planned else gathered["state"]}
    merged = merge(year, filing_status, household, facts, {})
    tables = tables_for(["US", *([merged.state] if merged.state else [])])
    federal = tables.get("US") if tables.get("US", {}).get("status") == "verified" else None
    result = estimate(merged, federal, figures, tables.get(merged.state) if merged.state else None)
    if result["result_minor"] is None or not planned:
        return {"ready": False, "year": year, "note": result["notes"][0] if result["notes"] else "No planned paycheck."}
    (main, w4), label = max(planned, key=lambda item: item[0][0]["per_check"]["wages"])
    advice = job_advice(main, result, federal, w4)
    rest = advice["rest"]
    return {"ready": True, "year": year, "zen": abs(result["result_minor"]) < ZEN_WITHIN, "result_minor": result["result_minor"],
            "display": {"result_minor": shown(abs(result["result_minor"]))}, "job": label, "w4": rest,
            "notes": ["A full year at the planned pay, with this year's other income, deductions and figures."]}


def job_advice(job, estimate, federal, w4):
    """Rest of the year and from January, for one job."""
    result, left, checks = estimate["result_minor"], job["paychecks_left"], job["pay_frequency"]
    wages, actual = job["per_check"]["wages"], job["per_check"]["federal"]
    offset = actual - withholding(federal, wages, checks, w4)  # What payroll does that the W-4 entered here doesn't explain.
    target = Decimal(actual) - Decimal(result) / left  # Per remaining paycheck: owing raises it, a refund lowers it.
    rest = solve(federal, wages, checks, w4, offset, target)
    rest_year_end = result + left * (rest["per_check"] - actual) if rest.get("amount") is not None or rest["field"] is None else None
    advice = {"key": job["key"], "name": job["name"], "paychecks_left": left, "frequency": checks, "per_check_now_minor": actual, "offset_minor": offset,
              "rest": {**rest, "year_end_minor": rest_year_end}}
    if result < 0:  # Owing: the same catch-up as a fixed extra amount per paycheck.
        extra = int((Decimal(-result) / left).to_integral_value(ROUND_CEILING))
        advice["extra"] = {"per_check_minor": extra, "total_4c_minor": w4.get("extra", 0) + extra, "year_end_minor": result + extra * left}
    # From January: a full year at this paycheck. This job's withholding must cover the tax the rest of the return doesn't.
    others = estimate["payments_minor"] - estimate["estimated_minor"] - job["values"]["federal_withheld"]
    full_target = Decimal(estimate["total_tax_minor"] - others) / checks
    january = solve(federal, wages, checks, w4, offset, full_target)
    january_year_end = (others + checks * january["per_check"]) - estimate["total_tax_minor"]
    advice["january"] = {**january, "year_end_minor": january_year_end}
    for part in (advice["rest"], advice["january"], advice.get("extra") or {}):
        part["display"] = {key: shown(value) for key, value in part.items() if key.endswith("_minor") and isinstance(value, int)}
        if part.get("amount") is not None and "field" in part:
            part["display"]["amount"] = f"${part['amount'] // 100:,}"
            part["display"]["per_check"] = shown(part["per_check"])
    advice["display"] = {"per_check_now_minor": shown(actual)}
    return advice
