"""The estimated-tax safe harbor (IRC §6654; docs/tax_intelligence_architecture.md §13–14, §22): whether the year's
withholding and estimated payments avoid an underpayment penalty, worked out apart from the return and from Tax Zen.

No penalty applies when (§6654(e)(1)) less than $1,000 is owed after withholding and refundable credits, or when the
payments made reach the required annual payment (§6654(d)(1)(B)): the smaller of 90% of this year's tax and 100% of
last year's (110% when last year's AGI was above $150,000), last year's counting only when it's entered.

Timing (§22): withholding counts as paid evenly through the year (§6654(g)(1)), so it covers each quarter's share;
estimated payments count on the day they're made, for the first due date on or after it. A quarter whose cumulative
payments fall below its share of the required payment is an underpaid quarter (Form 2210), unless less than $1,000 is
owed in all. Annualized-income installments (Schedule AI) aren't worked out, and the page says so.
"""

from datetime import date, timedelta

RULES_VERSION = "2026-1"  # Fixed in the law, not indexed; a change in law is a new version.
THIS_YEAR_BP, LAST_YEAR_BP, LAST_YEAR_HIGH_BP = 9000, 10000, 11000  # §6654(d)(1)(B), (C)
HIGH_AGI = 15_000_000  # §6654(d)(1)(C)(i): $150,000 of last year's AGI.
NO_PENALTY_BELOW = 100_000  # §6654(e)(1): less than $1,000 owed.


def due_dates(year):
    """1040-ES due dates for a tax year: Apr 15, Jun 15, Sep 15 and Jan 15, moved to the next weekday when on a weekend."""
    dates = []
    for day in (date(year, 4, 15), date(year, 6, 15), date(year, 9, 15), date(year + 1, 1, 15)):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        dates.append(day)
    return dates


def required_payment(total_tax, prior):
    """The required annual payment, and which rule set it. prior: last year's {"tax_minor", "agi_minor"}, or None."""
    this_year = total_tax * THIS_YEAR_BP // 10000
    if not prior or prior.get("tax_minor") is None:
        return this_year, "90% of this year's tax"
    high = (prior.get("agi_minor") or 0) > HIGH_AGI
    last_year = prior["tax_minor"] * (LAST_YEAR_HIGH_BP if high else LAST_YEAR_BP) // 10000
    if last_year < this_year:
        return last_year, f"{'110' if high else '100'}% of last year's tax"
    return this_year, "90% of this year's tax"


def evaluate(year, total_tax, withheld, refundable, estimated_payments, prior=None, today=None):
    """The safe harbor at year end, given the year's projected withholding (to Dec 31) and refundable credits and the
    estimated payments made. estimated_payments: [{"date", "amount_minor"}]."""
    today = today or date.today()
    required, basis = required_payment(total_tax, prior)
    estimated = sum(payment["amount_minor"] for payment in estimated_payments)
    owed = total_tax - withheld - refundable - estimated
    under_1000 = owed < NO_PENALTY_BELOW
    paid = withheld + refundable + estimated
    meets_required = paid >= required
    # By quarter: withholding a quarter of the year's each; estimated payments by date.
    dates = due_dates(year)
    by_quarter = [0, 0, 0, 0]
    for payment in estimated_payments:
        day = date.fromisoformat(payment["date"])
        by_quarter[next((number for number, due in enumerate(dates) if day <= due), 3)] += payment["amount_minor"]
    quarters, running = [], 0
    for index, due in enumerate(dates):
        running += by_quarter[index]
        share = required * (index + 1) // 4
        covered = (withheld + refundable) * (index + 1) // 4 + running
        quarters.append({"quarter": index + 1, "due": due.isoformat(), "required_by_now_minor": share, "paid_by_now_minor": covered,
                         "short": covered < share and due < today})
    short = [row["quarter"] for row in quarters if row["short"]]
    satisfied = under_1000 or meets_required
    risk = "none" if satisfied and not short or under_1000 else "possible" if satisfied else "likely"
    notes = []
    if not prior or prior.get("tax_minor") is None:
        notes.append("Enter last year's total tax (and AGI) to use the prior-year safe harbor; until then it is 90% of this year's.")
    if short and not under_1000:
        notes.append(f"Payments through quarter {short[-1]} were below the safe harbor, so an underpayment penalty may apply for that period "
                     "(Form 2210). The annualized-income method can lower it; it isn't worked out here.")
    return {"rules_version": RULES_VERSION, "required_minor": required, "required_basis": basis, "paid_minor": paid, "owed_minor": owed,
            "less_than_1000": under_1000, "meets_required_payment": meets_required, "prior_year_used": basis.endswith("last year's tax"),
            "satisfied": satisfied, "underpaid_quarters": short, "risk": risk, "quarters": quarters, "notes": notes}
