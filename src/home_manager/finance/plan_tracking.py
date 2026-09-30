"""A What If plan put to use (docs/what-if.md, phase 3).

budget_changes(): the budgets a plan's set spending would make for a month, beside the budgets there are now; nothing
changes until adopt() applies them (ledger.set_budget) and marks the plan adopted from that month.
plan_vs_actual(): what was planned against what happened:
- pay: each paycheck that replaces pay, line by line (gross, each pre-tax deduction, each tax, each post-tax deduction,
  net) against the confirmed pay stubs paid in its months: the latest stub and the average of up to six;
- spending: each set spending amount against the category's counted spending, month by month from the adoption month
  (or the plan's first set spending month), the current month so far.
Exact integer arithmetic; amounts are minor units with display text.
"""

from datetime import date
from decimal import Decimal

from ..core.money import money, to_minor
from ..library.storage import now
from .forecast import month_add, month_end, month_steps
from .ledger import category_name
from .paycheck import CURRENCY, LABELS, calculate
from .paystub import rounded
from .scenarios import ScenarioInput, Scenarios

MAX_STUBS = 6  # Stubs averaged per paycheck: the latest six in its months.
MAX_MONTHS = 6  # Months of spending shown: the latest six from the adoption month.
PAY_GROUPS = (("earnings", "Gross pay"), ("pre_tax", "Pre-tax deductions"), ("tax", "Taxes"), ("post_tax", "Post-tax deductions"))


def planned_amounts(value: ScenarioInput, month, currency):
    """{category: monthly amount in minor units} set for that month: each category's latest amount from a month on or before."""
    found = {}
    for item in sorted(value.forecast.category_amounts, key=lambda item: item.from_month):
        if item.from_month <= month:
            found[item.category] = to_minor(item.monthly_amount, currency)
    return found


def budget_changes(value: ScenarioInput, month, currency, budgets):
    """The budgets the plan's set spending makes for `month`, beside today's budgets. budgets: ledger.budgets()."""
    current = {(budget["category"], budget["currency"]): budget for budget in budgets}
    rows, skipped = [], []
    for category, amount in sorted(planned_amounts(value, month, currency).items()):
        name = category_name(category)
        if amount <= 0:
            skipped.append(name)
            continue
        existing = current.get((name, currency))
        change = "new" if existing is None else "same" if existing["amount_minor"] == amount else "changed"
        rows.append({"category": name, "currency": currency, "planned": money(amount, currency),
                     "current": existing["amount"] if existing else None, "change": change})
    planned = {row["category"] for row in rows}
    untouched = [{"category": budget["category"], "amount": budget["amount"]} for budget in budgets
                 if budget["currency"] == currency and budget["category"] not in planned]
    notes = ["Set spending is in today's dollars, so each budget is the amount as you entered it."]
    if skipped:
        notes.append(f"A zero amount can't be a budget, so these are left as they are: {', '.join(skipped)}.")
    if not rows:
        notes.append(f"The plan sets no spending for {month}; add set spending to budget from it.")
    return {"month": month, "currency": currency, "rows": rows, "untouched": untouched, "notes": notes}


def adopt(store, ledger, scenario_id, month, currency):
    """Set the plan's budgets for `month` and mark it adopted from then; budgets it doesn't name are left alone."""
    value = Scenarios(store).input(scenario_id)
    changes = budget_changes(value, month, currency, ledger.budgets())
    applied = 0
    for row in changes["rows"]:
        if row["change"] != "same":
            ledger.set_budget(row["category"], currency, row["planned"]["decimal"])
            applied += 1
    with store.connection() as db:
        db.execute("UPDATE scenarios SET adopted_at=?,adopted_month=?,updated_at=? WHERE id=?", (now(), month, now(), scenario_id))
    return {"applied": applied, "scenario": Scenarios(store).get(scenario_id), **budget_changes(value, month, currency, ledger.budgets())}


def stop_tracking(store, scenario_id):
    """The plan is no longer followed. Budgets it set stay: they are ordinary budgets now."""
    Scenarios(store).get(scenario_id)
    with store.connection() as db:
        db.execute("UPDATE scenarios SET adopted_at=NULL,adopted_month=NULL,updated_at=? WHERE id=?", (now(), scenario_id))
    return Scenarios(store).get(scenario_id)


def stub_lines(db, record):
    """{(group, category): amount this period} for one stub, with gross and net as their own rows."""
    found = {("earnings", "gross"): record["gross_pay_minor"], ("net", "net"): record["net_pay_minor"]}
    for line in db.execute("SELECT line_group,category,current_minor FROM income_lines WHERE income_record_id=?", (record["id"],)):
        if line["line_group"] in ("pre_tax", "tax", "post_tax") and line["current_minor"] is not None:
            key = (line["line_group"], line["category"])
            found[key] = (found.get(key) or 0) + line["current_minor"]
    return found


def pay_vs_actual(db, plan, result, today):
    """One planned paycheck against the confirmed stubs paid in its months."""
    start, end = plan.from_month + "-01", month_end(plan.to_month) if plan.to_month else today.isoformat()
    records = [dict(row) for row in db.execute(
        "SELECT id,pay_date,gross_pay_minor,net_pay_minor FROM income_records WHERE review_status='verified' AND currency=? AND pay_date BETWEEN ? AND ? "
        "ORDER BY pay_date DESC,id DESC LIMIT ?", (CURRENCY, start, end, MAX_STUBS))]
    planned = {("earnings", "gross"): result["groups"][0]["per_check_minor"], ("net", "net"): result["net"]["per_check_minor"]}
    order = [("earnings", "gross")]
    for group in result["groups"]:
        if group["group"] in ("pre_tax", "tax", "post_tax"):
            for line in group["lines"]:
                key = (group["group"], line["category"])
                planned[key] = planned.get(key, 0) + line["per_check_minor"]
                if key not in order:
                    order.append(key)
    actual = [stub_lines(db, record) for record in records]
    for lines in actual:
        order += [key for key in lines if key not in order and key != ("net", "net")]
    order.append(("net", "net"))
    rows = []
    for key in order:
        group, category = key
        mine = planned.get(key)
        values = [lines.get(key, 0 if key[0] in ("pre_tax", "tax", "post_tax") else None) for lines in actual]
        known = [value for value in values if value is not None]
        average = rounded(Decimal(sum(known)) / len(known)) if known else None
        label = "Gross pay" if category == "gross" else "Net pay" if category == "net" else LABELS.get(category, category.replace("_", " ").capitalize())
        rows.append({"group": group, "category": category, "label": label, "planned": money(mine, CURRENCY) if mine is not None else None,
                     "latest": money(values[0], CURRENCY) if values and values[0] is not None else None,
                     "average": money(average, CURRENCY) if average is not None else None,
                     "difference": money(average - mine, CURRENCY) if average is not None and mine is not None else None,
                     "total": category in ("gross", "net")})
    return {"label": plan.label, "from_month": plan.from_month, "to_month": plan.to_month, "complete": result["complete"],
            "stubs": [{"id": record["id"], "pay_date": record["pay_date"]} for record in records], "rows": rows,
            "message": None if records else f"No confirmed pay stubs paid from {plan.from_month} yet; they are compared here once they're recorded."}


def plan_vs_actual(store, tools, scenario, tables_for, currency, today=None):
    """What the plan said against what happened. scenario: Scenarios.get(); tools: FinanceTools on the same library."""
    today = today or date.today()
    value = ScenarioInput.model_validate(scenario["inputs"])
    this_month = today.isoformat()[:7]
    pay = []
    with store.connection() as db:
        for plan in value.paychecks:
            if plan.mode != "replace_pay" or plan.from_month > this_month:
                continue
            paycheck = plan.paycheck
            result = calculate(paycheck, tables_for(paycheck.year, ["US", *([paycheck.work_state] if paycheck.work_state else [])], paycheck.filing_status))
            pay.append(pay_vs_actual(db, plan, result, today))
    froms = [item.from_month for item in value.forecast.category_amounts]
    first = scenario["adopted_month"] or (min(froms) if froms else None)
    months = []
    if first and first <= this_month:
        first = max(first, month_add(this_month, -(MAX_MONTHS - 1)))
        for step in range(month_steps(first, this_month) + 1):
            month = month_add(first, step)
            planned = planned_amounts(value, month, currency)
            if not planned:
                continue
            spent = tools._category_totals(month + "-01", month_end(month), None)
            rows = []
            for category, amount in sorted(planned.items()):
                used = spent.get((currency, category_name(category)), (0, 0))[0]
                rows.append({"category": category, "planned": money(amount, currency), "actual": money(used, currency),
                             "difference": money(used - amount, currency), "status": "over" if used > amount else "within"})
            months.append({"month": month, "partial": month == this_month, "rows": rows,
                           "planned": money(sum(planned.values()), currency), "actual": money(sum(row["actual"]["minor"] for row in rows), currency)})
    notes = ["Pay compares each paycheck that replaces pay with the confirmed pay stubs paid in its months: the latest, and the average "
             f"of up to {MAX_STUBS}. A line the stub doesn't print counts as zero on it.",
             "Spending is counted spending in the category, the same figure as budgets; planned amounts are in today's dollars."]
    if any(plan.mode == "add" for plan in value.paychecks):
        notes.append("Paychecks that add another earner aren't compared: their pay stubs belong to that person's profile.")
    return {"scenario_id": scenario["id"], "adopted_month": scenario["adopted_month"], "currency": currency, "pay": pay,
            "spending": list(reversed(months)), "notes": notes}
