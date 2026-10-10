"""A tax year's return inputs, gathered from records and adjusted by you (docs/taxes.md).

gather(): every figure the records give, with where it came from:
- jobs: this year's confirmed pay stubs, one job per employer. The latest stub's year-to-date figures (or the sum of the
  year's stubs when they aren't printed), plus its paycheck for each payday left in the year;
- interest (bank interest and taxable investment accounts) and dividends: year to date, projected to Dec 31 at the same
  pace; confirmed 1099-INT/-DIV forms replace them once they arrive;
- realized gains in taxable accounts (tax lots); distributions from tax-deferred accounts (early before 59½);
- businesses, adjustments, itemized deductions, credit spending and tax paid ahead: confirmed tax tags;
- the facts the tax engine needs that records can answer: Form 1098's interest and property tax, the mortgage's average
  balance (1098 box 2 and the recorded mortgage, or interest ÷ rate; Pub 936), and HSA coverage (from the year's HSA
  contributions against the self-only limit).
merge(): your typed values over them: any field, any job's field, jobs typed in (a spouse's), people, students.
The result is a tax_return.ReturnInput, and each field keeps its source for the page.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
import json
import re

from ..core import actor
from ..core.money import format_minor, money, to_minor
from ..core.trace import NULL
from ..library.storage import now
from .investments import Investments
from .ledger import COUNTABLE, clean_reason
from .paystub import FICA_EXEMPT
from .provenance import light
from .tax_lots import realized
from .tax_return import TIPPED_OCCUPATIONS, Job, ReturnInput, rate
from .tax_tags import TaxTags

CURRENCY = "USD"
MONEY_FIELDS = ("interest", "us_obligation_interest", "tax_exempt_interest", "ordinary_dividends", "qualified_dividends", "short_term_gain", "long_term_gain",
                "capital_loss_carryover", "retirement_distributions", "early_distributions", "hsa_nonqualified", "social_security_benefits",
                "unemployment", "other_income", "educator_expenses", "hsa_contributions", "se_health_insurance", "ira_deduction",
                "student_loan_interest", "other_adjustments", "medical", "state_local_tax", "property_tax", "mortgage_interest", "charity",
                "charity_noncash", "mortgage_average_balance", "other_itemized", "qualified_tips", "qualified_overtime", "dependent_care_expenses", "energy_home_expenses", "other_credits",
                "other_refundable_credits", "other_federal_withholding", "federal_estimated_paid", "state_deduction", "state_credits",
                "state_estimated_paid")
# Accounts whose interest is US savings bond or Treasury interest: federal-taxable, state-exempt (the Education Savings Bond
# exclusion for I bonds cashed for tuition isn't worked out; enter it typed over the records).
US_OBLIGATION_KINDS = ("i_bond", "treasury")
# HSA contribution limits (IRC §223(b)(2), inflation-adjusted): (self-only, family) in cents. Rev. Proc. 2024-25 (2025) and
# Rev. Proc. 2025-19 (2026). Used only to tell the coverage from what went in; the engine applies the limit itself.
HSA_LIMITS = {2025: (430_000, 855_000), 2026: (440_000, 875_000)}
HSA_CATCH_UP = 100_000  # §223(b)(3): $1,000 more from age 55.
# A loan is the mortgage when its name says so (assets of kind 'loan': a home loan statement or one typed in).
MORTGAGE_WORDS = re.compile(r"MORTGAGE|HOME\s*LOAN|HOME\s*EQUITY|HELOC", re.IGNORECASE)
# Kinds of value (docs/taxes.md "Design"), from most to least certain: a record as it stands, worked
# out from records, projected to Dec 31, or still to enter. What you type is "typed".
KIND_ORDER = ("record", "worked_out", "projected", "to_enter")
# The likely range (docs/taxes.md "Design"): projected pay moves by how much this year's paychecks
# varied, at least 5%; projected interest and dividends by 25%. Recorded and typed values don't move.
SPREAD_FLOOR_BP = 500
PACED_SPREAD_BP = 2500
COUNT_FIELDS = ("qualifying_children", "other_dependents", "dependent_care_people")
JOB_FIELDS = ("wages", "ss_wages", "medicare_wages", "federal_withheld", "state_withheld", "medicare_withheld")
# Tax tag lines -> return fields.
TAG_FIELDS = {("adjustment", "educator"): "educator_expenses", ("adjustment", "hsa"): "hsa_contributions",
              ("adjustment", "se_health_insurance"): "se_health_insurance", ("adjustment", "ira"): "ira_deduction",
              ("adjustment", "student_loan_interest"): "student_loan_interest", ("itemized", "medical"): "medical",
              ("itemized", "state_local_tax"): "state_local_tax", ("itemized", "property_tax"): "property_tax",
              ("itemized", "mortgage_interest"): "mortgage_interest", ("itemized", "charity_cash"): "charity", ("itemized", "charity_noncash"): "charity_noncash",
              ("itemized", "other"): "other_itemized", ("credit_spending", "dependent_care"): "dependent_care_expenses",
              ("credit_spending", "energy_home"): "energy_home_expenses"}  # Tax paid ahead is gathered by its own year window below.


def scaled(amount, factor):
    return int((Decimal(amount) * factor).to_integral_value(ROUND_HALF_EVEN))


def paydays(last, frequency, year):
    """The paydays after `last` up to Dec 31 of `year`, at the stub's frequency."""
    if not last or not frequency:
        return []
    day, end = date.fromisoformat(last), date(year, 12, 31)
    if frequency in (52, 26):
        step = timedelta(days=7 if frequency == 52 else 14)
        return [day + step * count for count in range(1, (end - day).days // step.days + 1)]
    if frequency == 24:  # The 15th and the last day of each month.
        found = []
        for month in range(day.month, 13):
            last_day = (date(year, month + 1, 1) - timedelta(days=1)) if month < 12 else end
            found += [payday for payday in (date(year, month, 15), last_day) if payday > day]
        return found
    return [date(year, month, min(day.day, 28)) for month in range(day.month + 1, 13)]  # Monthly, about the same day.


def paydays_left(last, frequency, year):
    return len(paydays(last, frequency, year))


def amounts(lines, column, group, categories=None):
    return sum(line[column] or 0 for line in lines if line["line_group"] == group and (categories is None or line["category"] in categories))


def year_to_date(stubs, lines_of, group, categories=None):
    """(amount, printed): the latest stub's year-to-date figures when every such line has one; else the sum of the year's stubs."""
    latest = [line for line in lines_of[stubs[-1]["id"]] if line["line_group"] == group and (categories is None or line["category"] in categories)]
    if latest and all(line["ytd_minor"] is not None for line in latest):
        return amounts(latest, "ytd_minor", group, categories), True
    return sum(amounts(lines_of[stub["id"]], "current_minor", group, categories) for stub in stubs), False


def record_job(recorder, field, stubs, gross_ytd, deducted, so_far, left, per_check, printed):
    """jobs()'s steps for one of a job's figures: so far this year, less what isn't counted, plus the paydays left."""
    where = "the latest stub's year to date" if printed else "the year's stubs added up"
    if field in ("wages", "ss_wages", "medicare_wages"):
        recorder.add(f"Gross pay so far ({where})", gross_ytd, CURRENCY)
        recorder.add("Pre-tax deductions so far" if field == "wages" else "Pre-tax deductions Social Security and Medicare don't tax", -deducted, CURRENCY)
    else:
        recorder.add(f"Withheld so far ({where})", so_far, CURRENCY)
    recorder.add(f"{left} payday{'s' if left != 1 else ''} left this year × {format_minor(per_check, CURRENCY)} (the latest paycheck)", left * per_check, CURRENCY)
    for stub in stubs:
        recorder.input(f"income_record:{stub['id']}", f"Pay stub · {stub['pay_date']}", stub["gross_pay_minor"] or 0, CURRENCY, light("income_record", stub["id"]))


def jobs(db, year, today, recorder=NULL, only=None):
    """One job per employer from this year's confirmed stubs, projected to the year's end. only: (job key, field) whose
    steps a live recorder gets (finance/tax_traces.py)."""
    records = db.execute("SELECT r.*,coalesce(m.canonical_name,'Employer') AS employer FROM income_records r LEFT JOIN merchants m ON m.id=r.payer_merchant_id "
                         "WHERE r.review_status='verified' AND r.currency=? AND substr(r.pay_date,1,4)=? ORDER BY r.pay_date,r.id", (CURRENCY, str(year))).fetchall()
    by_employer: dict = {}
    for record in records:
        by_employer.setdefault(record["payer_merchant_id"], []).append(dict(record))
    found = []
    for key, stubs in by_employer.items():
        latest = stubs[-1]
        lines_of = {stub["id"]: [dict(row) for row in db.execute("SELECT line_group,category,current_minor,ytd_minor FROM income_lines WHERE income_record_id=?",
                                                                  (stub["id"],))] for stub in stubs}
        gross_ytd = latest["gross_pay_ytd_minor"] if latest["gross_pay_ytd_minor"] is not None else sum(stub["gross_pay_minor"] or 0 for stub in stubs)
        pre_ytd, printed = year_to_date(stubs, lines_of, "pre_tax")
        exempt_ytd, _ = year_to_date(stubs, lines_of, "pre_tax", FICA_EXEMPT)
        federal_ytd, _ = year_to_date(stubs, lines_of, "tax", ("federal_income_tax",))
        state_ytd, _ = year_to_date(stubs, lines_of, "tax", ("state_income_tax",))
        medicare_ytd, _ = year_to_date(stubs, lines_of, "tax", ("medicare",))
        latest_lines = lines_of[latest["id"]]
        gross_now = latest["gross_pay_minor"] or 0
        # HSA money through payroll, yours and the employer's: it counts toward the HSA limit (finance/tax_year.hsa_coverage).
        hsa_ytd = sum(year_to_date(stubs, lines_of, group, ("hsa",))[0] for group in ("pre_tax", "employer_paid"))
        per_check = {"wages": gross_now - amounts(latest_lines, "current_minor", "pre_tax"),
                     "fica": gross_now - amounts(latest_lines, "current_minor", "pre_tax", FICA_EXEMPT),
                     "federal": amounts(latest_lines, "current_minor", "tax", ("federal_income_tax",)),
                     "state": amounts(latest_lines, "current_minor", "tax", ("state_income_tax",)),
                     "medicare": amounts(latest_lines, "current_minor", "tax", ("medicare",)),
                     "hsa": sum(amounts(latest_lines, "current_minor", group, ("hsa",)) for group in ("pre_tax", "employer_paid"))}
        # Every payday after the latest stub counts in the year (paid like it, whether or not its stub is here yet); only the
        # ones still ahead can change with a new W-4.
        coming = paydays(latest["pay_date"], latest["pay_frequency"], year) if year >= today.year else []
        left = len(coming)
        ahead = sum(1 for payday in coming if payday > today)
        # How much paychecks vary: the year's stubs' gross pay, low to high against the latest (at least 5%), for the range.
        grosses = [stub["gross_pay_minor"] for stub in stubs if stub["gross_pay_minor"]]
        spread_bp = max(SPREAD_FLOOR_BP, (max(grosses) - min(grosses)) * 10000 // gross_now if grosses and gross_now else 0)
        if recorder.live and only and only[0] == f"employer-{key}":
            field = only[1]
            per = {"wages": "wages", "ss_wages": "fica", "medicare_wages": "fica", "federal_withheld": "federal", "state_withheld": "state",
                   "medicare_withheld": "medicare"}[field]
            so_far = {"federal_withheld": federal_ytd, "state_withheld": state_ytd, "medicare_withheld": medicare_ytd}.get(field, 0)
            record_job(recorder, field, stubs, gross_ytd, pre_ytd if field == "wages" else exempt_ytd, so_far, len(coming), per_check[per], printed)
        found.append({"key": f"employer-{key}", "name": latest["employer"], "stubs": len(stubs), "last_pay_date": latest["pay_date"],
                      "pay_frequency": latest["pay_frequency"], "work_state": latest["work_state"], "paychecks_left": ahead,
                      "next_pay_date": next((payday.isoformat() for payday in coming if payday > today), None),
                      "paychecks_projected": left, "paydays_without_stub": left - ahead, "ytd_printed": printed,
                      "per_check": per_check,
                      "values": {"wages": gross_ytd - pre_ytd + left * per_check["wages"], "ss_wages": gross_ytd - exempt_ytd + left * per_check["fica"],
                                 "medicare_wages": gross_ytd - exempt_ytd + left * per_check["fica"], "federal_withheld": federal_ytd + left * per_check["federal"],
                                 "state_withheld": state_ytd + left * per_check["state"], "medicare_withheld": medicare_ytd + left * per_check["medicare"]},
                      "withheld_so_far": federal_ytd, "hsa_minor": abs(hsa_ytd) + left * abs(per_check["hsa"]),
                      # The part of each figure that's projected (the paydays without a stub yet), and how much pay varies.
                      "projected": {"wages": left * per_check["wages"], "ss_wages": left * per_check["fica"], "medicare_wages": left * per_check["fica"],
                                    "federal_withheld": left * per_check["federal"], "state_withheld": left * per_check["state"],
                                    "medicare_withheld": left * per_check["medicare"]},
                      "spread_bp": spread_bp,
                      # Each stub, oldest first, for the Taxes page's pay-stub table: record values, sourced by the document link.
                      "stub_list": [{"income_id": stub["id"], "document_id": stub["document_id"], "pay_date": stub["pay_date"],
                                     "gross": money(stub["gross_pay_minor"] or 0, CURRENCY), "net": money(stub["net_pay_minor"] or 0, CURRENCY),
                                     "federal": money(amounts(lines_of[stub["id"]], "current_minor", "tax", ("federal_income_tax",)), CURRENCY)}
                                    for stub in stubs]})
    return found


def balance_at(loan, day):
    """A loan's balance on a day, from its recorded balance, yearly rate and monthly payment (month by month, with the
    forecast's own step, forecast.loan_month); None without a payment to project with."""
    from .forecast import loan_month  # forecast imports the ledger tools, which the tax year needn't load at import
    when = date.fromisoformat(loan["as_of"][:10])
    months = (day.year - when.year) * 12 + day.month - when.month
    balance, monthly = Decimal(loan["value_minor"]), Decimal(loan["annual_rate_bp"]) / 10000 / 12
    if months == 0:
        return loan["value_minor"]
    payment = loan["monthly_payment_minor"]
    if not payment:
        return None
    for _ in range(abs(months)):
        balance = loan_month(balance, monthly, Decimal(payment))[0] if months > 0 else (balance + payment) / (1 + monthly)
    return int(balance.to_integral_value(ROUND_HALF_EVEN))


def average_balance(interest, start, loans, year):
    """The mortgage's average balance for the year (Pub 936, Table 1's methods) and how it was worked out, or None.
    start: 1098 box 2 (principal outstanding on Jan 1); loans: the recorded mortgages."""
    end = balance_at(loans[0], date(year, 12, 31)) if len(loans) == 1 else None
    if start is not None and end is not None:
        return (start + end) // 2, f"Average of the principal on Jan 1 (1098 box 2) and {loans[0]['name']}'s balance on Dec 31 (Pub 936)"
    if start is not None:
        return start, "The principal on Jan 1 (1098 box 2); the average is at most this, since the loan is paid down (Pub 936)"
    if len(loans) == 1 and loans[0]["annual_rate_bp"] > 0:
        average = int((Decimal(interest) * 10000 / loans[0]["annual_rate_bp"]).to_integral_value(ROUND_HALF_EVEN))
        return average, f"The year's mortgage interest divided by {loans[0]['name']}'s yearly rate (Pub 936)"
    return None


def hsa_coverage(total, year, birth_year):
    """Self-only or family HDHP coverage, from the year's HSA contributions (payroll, the employer's and your own), and why;
    None when the year's limits aren't here or nothing was put in."""
    if not total or year not in HSA_LIMITS:
        return None
    self_only, family = HSA_LIMITS[year]
    catch_up = HSA_CATCH_UP if birth_year and year - birth_year >= 55 else 0
    shown = format_minor(self_only + catch_up, CURRENCY)
    if total <= self_only + catch_up:
        return "self", f"{format_minor(total, CURRENCY)} went into the HSA, within the self-only limit of {shown}, so the coverage doesn't change the deduction"
    note = f"{format_minor(total, CURRENCY)} went into the HSA, more than the self-only limit of {shown}, so family coverage"
    if total > family + catch_up:
        note += f"; that's also more than the family limit of {format_minor(family + catch_up, CURRENCY)}, and the excess is taxed until it's withdrawn"
    return "family", note


def gather(store, year, household, today=None, recorder=NULL, only=None):
    """Every return field the records give for the year, with its source: {"values": {...}, "sources": {...}, "jobs": [...], "businesses": [...]}.
    only: (job key, field) whose steps a live recorder gets (jobs())."""
    today = today or date.today()
    pace = Decimal(12) / today.month if year == today.year else Decimal(1)  # Interest and dividends so far, projected to Dec 31.
    values, sources = {}, {}
    investments = Investments(store, today)
    with store.connection() as db:
        found_jobs = jobs(db, year, today, recorder, only)
        accounts = investments.rows(db, True)
        taxable = [account["id"] for account in accounts if account["tax_treatment"] == "taxable" and account["currency"] == CURRENCY]
        deferred = [account["id"] for account in accounts if account["tax_treatment"] in ("tax_deferred",) and account["currency"] == CURRENCY]
        # I bond and Treasury interest is federal-taxable and state-exempt.
        federal_only = [account["id"] for account in accounts if account["kind"] in US_OBLIGATION_KINDS and account["id"] in taxable]
        education = investments.education_earnings(db, year)

        def events(kind, ids):
            if not ids:
                return 0
            return db.execute(f"SELECT coalesce(sum(amount_minor),0) FROM investment_events WHERE review_status='verified' AND event_type=? AND substr(event_date,1,4)=? "
                              f"AND account_id IN ({','.join('?' * len(ids))})", (kind, str(year), *ids)).fetchone()[0]
        bank_interest = db.execute(f"SELECT coalesce(sum(t.amount_minor),0) FROM transactions t WHERE {COUNTABLE} AND t.transaction_type='interest' "
                                   "AND t.amount_minor>0 AND t.currency=? AND substr(t.posted_date,1,4)=?", (CURRENCY, str(year))).fetchone()[0]
        forms = {}
        for row in db.execute("SELECT b.form,b.box,sum(b.amount_minor) AS total FROM tax_form_boxes b JOIN tax_forms f ON f.id=b.form_id "
                              "WHERE f.review_status='verified' AND f.tax_year=? AND f.currency=? GROUP BY b.form,b.box", (year, CURRENCY)):
            forms[(row["form"], row["box"])] = row["total"]
        gains = realized(db, taxable, year) if taxable else {"short_minor": 0, "long_minor": 0}
        # Summed while the connection is open (it closes with this block).
        investment_interest, dividends = events("interest", taxable), events("dividend", taxable)
        federal_only_interest, deferred_withdrawals = events("interest", federal_only), events("withdrawal", deferred)
        mortgages = [dict(row) for row in db.execute("SELECT name,value_minor,as_of,annual_rate_bp,monthly_payment_minor FROM assets WHERE kind='loan' "
                                                     "AND review_status='verified' AND archived_at IS NULL AND currency=? ORDER BY id", (CURRENCY,))
                     if MORTGAGE_WORDS.search(row["name"])]
    if ("1099-INT", "1") in forms or ("1099-INT", "3") in forms:
        # Box 3 (savings bond and Treasury interest) is taxable interest too, reported apart from box 1.
        values["interest"] = forms.get(("1099-INT", "1"), 0) + forms.get(("1099-INT", "3"), 0) + scaled(bank_interest, pace)
        sources["interest"] = "1099-INT forms (boxes 1 and 3), plus bank interest projected to Dec 31"
        values["us_obligation_interest"] = forms.get(("1099-INT", "3"), 0)
        sources["us_obligation_interest"] = "1099-INT box 3 (I bonds and Treasuries), exempt from state tax"
    else:
        values["interest"] = scaled(bank_interest + investment_interest, pace)
        sources["interest"] = "Interest so far (bank and taxable investment accounts), projected to Dec 31" if pace != 1 else "Interest recorded"
        values["us_obligation_interest"] = scaled(federal_only_interest, pace)
        sources["us_obligation_interest"] = "I bond and Treasury interest so far, exempt from state tax" + (", projected to Dec 31" if pace != 1 else "")
    nonqualified = [entry for entry in education if entry["currency"] == CURRENCY and entry["taxable_earnings_minor"]]
    if nonqualified:
        values["other_income"] = sum(entry["taxable_earnings_minor"] for entry in nonqualified)
        sources["other_income"] = "Earnings on non-qualified 529 withdrawals (1099-Q box 2 share); a 10% additional tax may also apply"
    if ("1099-DIV", "1a") in forms:
        values["ordinary_dividends"], sources["ordinary_dividends"] = forms[("1099-DIV", "1a")], "1099-DIV box 1a"
        values["qualified_dividends"], sources["qualified_dividends"] = forms.get(("1099-DIV", "1b"), 0), "1099-DIV box 1b"
    else:
        values["ordinary_dividends"] = scaled(dividends, pace)
        sources["ordinary_dividends"] = "Dividends so far in taxable accounts, projected to Dec 31" if pace != 1 else "Dividends recorded"
        values["qualified_dividends"], sources["qualified_dividends"] = 0, "Enter the qualified part (1099-DIV box 1b) when you know it"
    if ("1099-INT", "8") in forms:
        values["tax_exempt_interest"], sources["tax_exempt_interest"] = forms[("1099-INT", "8")], "1099-INT box 8"
    values["short_term_gain"], values["long_term_gain"] = gains["short_minor"], gains["long_minor"]
    sources["short_term_gain"] = sources["long_term_gain"] = "Realized in taxable accounts so far (tax lots)"
    distributions = forms.get(("1099-R", "2a")) if ("1099-R", "2a") in forms else deferred_withdrawals
    values["retirement_distributions"] = distributions
    sources["retirement_distributions"] = "1099-R box 2a" if ("1099-R", "2a") in forms else "Withdrawals from tax-deferred accounts so far"
    if household.birth_year and distributions and year - household.birth_year < 59:
        values["early_distributions"], sources["early_distributions"] = distributions, "Taken before 59½ (from your birth year); enter 0 if an exception applies"
    withheld = [form for form in ("1099-INT", "1099-DIV", "1099-R") if (form, "4") in forms]  # Box 4 on each: federal tax withheld.
    if withheld:
        values["other_federal_withholding"] = sum(forms[(form, "4")] for form in withheld)
        sources["other_federal_withholding"] = " and ".join(withheld) + " box 4"
    # Tax tags: businesses, adjustments, itemized deductions, credit spending, tax paid ahead.
    tagged = TaxTags(store).year(year, CURRENCY)
    businesses: dict = {}
    for line in tagged["lines"]:
        if line["kind"] in ("business_income", "business_expense"):
            entry = businesses.setdefault(line["business_id"], {"key": f"business-{line['business_id']}", "name": line["business"], "income": 0, "expenses": 0})
            entry["income" if line["kind"] == "business_income" else "expenses"] += line["counted_minor"]
            continue
        field = TAG_FIELDS.get((line["kind"], line["line"]))
        if field:
            values[field] = values.get(field, 0) + line["counted_minor"]
            sources[field] = "Tagged items"
        elif line["kind"] == "credit_spending" and line["line"] == "education":
            values.setdefault("students", []).append({"expenses": line["counted_minor"], "aotc": True})
            sources["students"] = "Tagged tuition; say which student and whether it's their first four years"
    # Form 1098: the lender's mortgage interest and property tax, when no tag already counts them; then the mortgage's
    # average balance, which the tax engine needs whenever there's mortgage interest (the $750,000 limit, Pub 936).
    for box, field in (("1", "mortgage_interest"), ("10", "property_tax")):
        if ("1098", box) in forms and not values.get(field):
            values[field], sources[field] = forms[("1098", box)], f"1098 box {box}"
    if values.get("mortgage_interest"):
        average = average_balance(values["mortgage_interest"], forms.get(("1098", "2")), mortgages, year)
        if average:
            values["mortgage_average_balance"], sources["mortgage_average_balance"] = average
    # HSA coverage, from what went in: 5498-SA box 2 (every contribution for the year) once it's here, else payroll lines
    # (yours and the employer's) projected to Dec 31 plus your own tagged contributions.
    if ("5498-SA", "2") in forms:
        hsa_total = forms[("5498-SA", "2")]
    else:
        hsa_total = sum(job["hsa_minor"] for job in found_jobs) + values.get("hsa_contributions", 0)
    coverage = hsa_coverage(hsa_total, year, household.birth_year)
    if coverage:
        values["hsa_coverage"], sources["hsa_coverage"] = coverage
    # Estimated tax belongs to the year it's paid for: the fourth quarter is due Jan 15 of the next year, so federal and state
    # estimated payments dated Feb 1 to Jan 31 count for this year (1040-ES).
    payments = {"federal_estimated": [], "state_estimated": []}
    for tag in TaxTags(store).list(status="verified", kind="tax_payment"):
        if f"{year}-02-01" <= tag["tax_date"] <= f"{year + 1}-01-31" and tag["line"] in payments and tag["currency"] == CURRENCY:
            payments[tag["line"]].append({"date": tag["tax_date"], "amount_minor": tag["amount_minor"]})
    for line, field in (("federal_estimated", "federal_estimated_paid"), ("state_estimated", "state_estimated_paid")):
        values[field] = sum(payment["amount_minor"] for payment in payments[line])
        sources[field] = "Tagged tax payments, Feb 1 to Jan 31 (the fourth quarter is due in January)"
    work_state = next((job["work_state"] for job in reversed(found_jobs) if job["work_state"]), None)
    # What kind of value each one is (KIND_ORDER). A value you type is "typed" on the page (merge keeps it over these).
    projected = pace != 1
    kinds = {field: "record" for field in sources}
    interest_forms = ("1099-INT", "1") in forms or ("1099-INT", "3") in forms
    paced = {"interest": bank_interest if interest_forms else bank_interest + investment_interest,  # The parts scaled to Dec 31.
             "us_obligation_interest": 0 if interest_forms else federal_only_interest,
             "ordinary_dividends": 0 if ("1099-DIV", "1a") in forms else dividends}
    projected_parts = {}
    for field, amount in paced.items():
        if projected and amount:
            kinds[field] = "projected"
            projected_parts[field] = scaled(amount, pace) - amount
    if ("1099-DIV", "1a") not in forms:
        kinds["qualified_dividends"] = "to_enter"
    for field in ("early_distributions", "mortgage_average_balance", "hsa_coverage"):
        if field in kinds:
            kinds[field] = "worked_out"
    for job in found_jobs:
        job["kind"] = "projected" if job["paychecks_projected"] else "record"
    return {"values": values, "sources": sources, "kinds": kinds, "projected": projected_parts, "jobs": found_jobs, "businesses": list(businesses.values()), "state": work_state,
            "estimated_payments": payments,
            "notes": tagged["notes"] + ([] if year < today.year else ["Business income and expenses count what's tagged so far; add the rest of the year's in "
                                                                      "“Typed over the records” to project it."] if businesses else [])}


def likely_range(merged: ReturnInput, gathered, inputs):
    """The return with its projected parts moved down and up (§23): (lower, higher, confidence). Pay and its withholding
    move by how much this year's paychecks varied (at least 5%), interest and dividends still to come by 25%; recorded and
    typed values stay. Confidence: high when under 10% of income is projected, medium under 30%, else low."""
    typed = {key for key, text in inputs.get("fields", {}).items() if text not in (None, "")}

    def moved(sign):
        changes: dict = {}
        for field, part in gathered.get("projected", {}).items():
            if field not in typed:
                changes[field] = max(0, getattr(merged, field) + sign * rate(part, PACED_SPREAD_BP))
        if "ordinary_dividends" in changes:
            changes["qualified_dividends"] = min(merged.qualified_dividends, changes["ordinary_dividends"])
        jobs = list(merged.jobs)
        for index, job in enumerate(gathered["jobs"]):  # merge() lists the gathered jobs first, in order.
            mine = inputs.get("jobs", {}).get(job["key"], {})
            jobs[index] = jobs[index].model_copy(update={key: max(0, getattr(jobs[index], key) + sign * rate(part, job.get("spread_bp", SPREAD_FLOOR_BP)))
                                                         for key, part in job.get("projected", {}).items() if part and mine.get(key) in (None, "")})
        return merged.model_copy(update={**changes, "jobs": jobs})
    projected = sum(part for field, part in gathered.get("projected", {}).items() if field not in typed and field != "us_obligation_interest") \
        + sum(job.get("projected", {}).get("wages", 0) for job in gathered["jobs"] if inputs.get("jobs", {}).get(job["key"], {}).get("wages") in (None, ""))
    income = sum(job.wages for job in merged.jobs) + merged.interest + merged.ordinary_dividends + sum(business.income for business in merged.businesses) \
        + max(merged.short_term_gain + merged.long_term_gain, 0) + merged.retirement_distributions + merged.social_security_benefits + merged.unemployment
    share = projected * 10000 // income if income > 0 else 0
    return moved(-1), moved(1), "high" if share < 1000 else "medium" if share < 3000 else "low"


def merge(year, filing_status, household, gathered, inputs):
    """The ReturnInput: the gathered values with your typed ones over them. inputs: the saved typed values."""
    fields = dict(gathered["values"])
    typed = inputs.get("fields", {})
    for key, text in typed.items():
        if key in MONEY_FIELDS:
            fields[key] = None if text in (None, "") else to_minor(str(text), CURRENCY)
        elif key in COUNT_FIELDS:
            fields[key] = int(text or 0)
        elif key == "itemize":
            fields[key] = text
        elif key == "hsa_coverage":
            fields[key] = text if text in ("self", "family") else None
        elif key == "tipped_occupation":
            fields[key] = text if text in TIPPED_OCCUPATIONS else None
        elif key == "state":
            fields[key] = text or None
    job_rows = []
    for job in gathered["jobs"]:
        override = inputs.get("jobs", {}).get(job["key"], {})
        row = {**job["values"], **{key: to_minor(str(text), CURRENCY) for key, text in override.items() if key in JOB_FIELDS and text not in (None, "")}}
        job_rows.append(Job(name=job["name"], owner=job.get("owner", ""), **row))
    for extra in inputs.get("extra_jobs", []):
        job_rows.append(Job(name=extra.get("name", "Another job"), owner=extra.get("owner", "spouse"),
                            **{key: to_minor(str(extra[key]), CURRENCY) for key in JOB_FIELDS if extra.get(key) not in (None, "")}))
    businesses = []
    for business in gathered["businesses"]:
        override = inputs.get("businesses", {}).get(business["key"], {})
        businesses.append({"name": business["name"], "owner": business.get("owner", ""), "income": to_minor(str(override["income"]), CURRENCY) if override.get("income") not in (None, "") else business["income"],
                           "expenses": to_minor(str(override["expenses"]), CURRENCY) if override.get("expenses") not in (None, "") else business["expenses"]})
    people = [{"name": "You", "birth_year": household.birth_year}] + [{"name": person.get("name", "Spouse"), "birth_year": person.get("birth_year")}
                                                                      for person in inputs.get("people", [])]
    students = [{"expenses": to_minor(str(student["expenses"]), CURRENCY), "aotc": bool(student.get("aotc", True))} for student in inputs["students"]] \
        if "students" in inputs else fields.pop("students", [])
    fields.pop("students", None)
    state = fields.pop("state", None) if "state" in typed else gathered["state"]
    clean = {key: value for key, value in fields.items() if value is not None}
    return ReturnInput(year=year, filing_status=filing_status, people=people, jobs=job_rows, businesses=businesses, students=students, state=state, **clean)


def w4s(inputs):
    """Your current W-4 per job, in cents: {job key: {"step2", "credits", "other_income", "deductions", "extra"}}."""
    found = {}
    for key, entries in inputs.get("w4", {}).items():
        found[key] = {"step2": bool(entries.get("step2"))}
        for field in ("credits", "other_income", "deductions", "extra"):
            if entries.get(field) not in (None, ""):
                found[key][field] = to_minor(str(entries[field]), CURRENCY)
    return found


def prior_year(inputs):
    """Last year's total tax and AGI, for the estimated-tax safe harbor; None when not entered."""
    prior = inputs.get("prior_year_tax") or {}
    if prior.get("tax") in (None, ""):
        return None
    return {"tax_minor": to_minor(str(prior["tax"]), CURRENCY), "agi_minor": to_minor(str(prior["agi"]), CURRENCY) if prior.get("agi") not in (None, "") else None}


class TaxYears:
    """Your typed values per year and filing unit (tax_years)."""

    def __init__(self, store):
        self.store = store

    def inputs(self, year, unit="me"):
        with self.store.connection() as db:
            row = db.execute("SELECT inputs_json FROM tax_years WHERE year=? AND unit=?", (year, unit)).fetchone()
        return json.loads(row["inputs_json"]) if row else {}

    def spouse_names(self):
        """The spouse named on your latest return (its typed people), so they can be chosen in who's here (core/actor.py)."""
        with self.store.connection() as db:
            row = db.execute("SELECT inputs_json FROM tax_years WHERE unit='me' ORDER BY year DESC LIMIT 1").fetchone()
        people = json.loads(row["inputs_json"]).get("people", []) if row else []
        return [" ".join(person["name"].split()) for person in people if isinstance(person, dict) and str(person.get("name") or "").strip()]

    def save(self, year, inputs, unit="me", gathered=None):
        """Save the typed values. Each typed value that changed is kept in tax_input_changes beside the value the
        records gave at the time (gathered: gather()'s result, when the caller has it), with the person and an optional
        reason (inputs["reason"], not saved with the values)."""
        inputs = dict(inputs)
        reason = clean_reason(inputs.pop("reason", None))
        allowed = {"fields", "jobs", "extra_jobs", "businesses", "people", "students", "w4", "prior_year_tax", "zen_job", "zen_policy"}
        unknown = set(inputs) - allowed
        if unknown:
            raise ValueError(f"Unknown inputs: {', '.join(sorted(unknown))}.")
        for key in inputs.get("fields", {}):
            if key not in MONEY_FIELDS + COUNT_FIELDS + ("itemize", "state", "hsa_coverage", "tipped_occupation"):
                raise ValueError(f"Unknown field {key}.")
        before = self.inputs(year, unit)
        with self.store.connection() as db:
            db.execute("INSERT INTO tax_years(year,unit,inputs_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(year,unit) DO UPDATE SET "
                       "inputs_json=excluded.inputs_json,updated_at=excluded.updated_at", (year, unit, json.dumps(inputs), now()))
            for key, gathered_value, previous, typed in typed_changes(before, inputs, gathered):
                db.execute("INSERT INTO tax_input_changes(year,unit,key,gathered_json,previous_json,typed_json,reason,actor,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (year, unit, key, json.dumps(gathered_value), json.dumps(previous), json.dumps(typed), reason, actor.current(), now()))
        return self.inputs(year, unit)

    def changes(self, year, unit="me", key=None):
        """The history of typed values, newest first: what the records gave, what was typed before and now, who, why."""
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM tax_input_changes WHERE year=? AND unit=? AND (? IS NULL OR key=?) ORDER BY id DESC", (year, unit, key, key))
            return [{**{name: row[name] for name in ("id", "year", "unit", "key", "reason", "actor", "created_at")},
                     **{name: json.loads(row[f"{name}_json"]) if row[f"{name}_json"] is not None else None for name in ("gathered", "previous", "typed")}}
                    for row in rows]


def typed(text):
    """A typed value as saved, with blank meaning "not typed" (None)."""
    return None if text in (None, "") else text


def typed_changes(before, after, gathered=None):
    """[(key, gathered value, typed before, typed now)] for each typed return field and job field that changed. A job's
    key is "job:<job key>:<field>". gathered values are the records' (cents for money), or None when not known."""
    gathered = gathered or {}
    found = []
    old, new = before.get("fields", {}), after.get("fields", {})
    for key in sorted(set(old) | set(new)):
        if typed(old.get(key)) != typed(new.get(key)):
            found.append((key, gathered.get("values", {}).get(key), typed(old.get(key)), typed(new.get(key))))
    jobs = {job["key"]: job for job in gathered.get("jobs", [])}
    old_jobs, new_jobs = before.get("jobs", {}), after.get("jobs", {})
    for job_key in sorted(set(old_jobs) | set(new_jobs)):
        was, now_typed = old_jobs.get(job_key, {}), new_jobs.get(job_key, {})
        for field in sorted(set(was) | set(now_typed)):
            if typed(was.get(field)) != typed(now_typed.get(field)):
                found.append((f"job:{job_key}:{field}", jobs.get(job_key, {}).get("values", {}).get(field), typed(was.get(field)), typed(now_typed.get(field))))
    return found


def typed_over(gathered, inputs):
    """Each typed value beside the value the records give (tax_year.merge keeps only the typed one): the return
    page shows both. [{key, gathered, typed}]."""
    return [{"key": key, "gathered": value, "typed": text} for key, value, _, text in typed_changes({}, inputs, gathered) if text is not None]
