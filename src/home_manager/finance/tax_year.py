"""A tax year's return inputs, gathered from records and adjusted by you (docs/taxes.md).

gather(): every figure the records give, with where it came from:
- jobs: this year's confirmed pay stubs, one job per employer. The latest stub's year-to-date figures (or the sum of the
  year's stubs when they aren't printed), plus its paycheck for each payday left in the year;
- interest (bank interest and taxable investment accounts) and dividends: year to date, projected to Dec 31 at the same
  pace; confirmed 1099-INT/-DIV forms replace them once they arrive;
- realized gains in taxable accounts (tax lots); distributions from tax-deferred accounts (early before 59½);
- businesses, adjustments, itemized deductions, credit spending and tax paid ahead: confirmed tax tags.
merge(): your typed values over them: any field, any job's field, jobs typed in (a spouse's), people, students.
The result is a tax_return.ReturnInput, and each field keeps its source for the page.
"""

from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
import json

from ..core.money import to_minor
from ..library.storage import now
from .investments import Investments
from .ledger import COUNTABLE
from .paystub import FICA_EXEMPT
from .tax_lots import realized
from .tax_return import Job, ReturnInput
from .tax_tags import TaxTags

CURRENCY = "USD"
MONEY_FIELDS = ("interest", "tax_exempt_interest", "ordinary_dividends", "qualified_dividends", "short_term_gain", "long_term_gain",
                "capital_loss_carryover", "retirement_distributions", "early_distributions", "hsa_nonqualified", "social_security_benefits",
                "unemployment", "other_income", "educator_expenses", "hsa_contributions", "se_health_insurance", "ira_deduction",
                "student_loan_interest", "other_adjustments", "medical", "state_local_tax", "property_tax", "mortgage_interest", "charity",
                "other_itemized", "other_deductions", "dependent_care_expenses", "energy_home_expenses", "other_credits",
                "other_refundable_credits", "other_federal_withholding", "federal_estimated_paid", "state_deduction", "state_credits",
                "state_estimated_paid")
COUNT_FIELDS = ("qualifying_children", "other_dependents", "dependent_care_people")
JOB_FIELDS = ("wages", "ss_wages", "medicare_wages", "federal_withheld", "state_withheld", "medicare_withheld")
# Tax tag lines -> return fields.
TAG_FIELDS = {("adjustment", "educator"): "educator_expenses", ("adjustment", "hsa"): "hsa_contributions",
              ("adjustment", "se_health_insurance"): "se_health_insurance", ("adjustment", "ira"): "ira_deduction",
              ("adjustment", "student_loan_interest"): "student_loan_interest", ("itemized", "medical"): "medical",
              ("itemized", "state_local_tax"): "state_local_tax", ("itemized", "property_tax"): "property_tax",
              ("itemized", "mortgage_interest"): "mortgage_interest", ("itemized", "charity_cash"): "charity", ("itemized", "charity_noncash"): "charity",
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


def jobs(db, year, today):
    """One job per employer from this year's confirmed stubs, projected to the year's end."""
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
        per_check = {"wages": gross_now - amounts(latest_lines, "current_minor", "pre_tax"),
                     "fica": gross_now - amounts(latest_lines, "current_minor", "pre_tax", FICA_EXEMPT),
                     "federal": amounts(latest_lines, "current_minor", "tax", ("federal_income_tax",)),
                     "state": amounts(latest_lines, "current_minor", "tax", ("state_income_tax",)),
                     "medicare": amounts(latest_lines, "current_minor", "tax", ("medicare",))}
        # Every payday after the latest stub counts in the year (paid like it, whether or not its stub is here yet); only the
        # ones still ahead can change with a new W-4.
        coming = paydays(latest["pay_date"], latest["pay_frequency"], year) if year >= today.year else []
        left = len(coming)
        ahead = sum(1 for payday in coming if payday > today)
        found.append({"key": f"employer-{key}", "name": latest["employer"], "stubs": len(stubs), "last_pay_date": latest["pay_date"],
                      "pay_frequency": latest["pay_frequency"], "work_state": latest["work_state"], "paychecks_left": ahead,
                      "paychecks_projected": left, "ytd_printed": printed,
                      "per_check": per_check,
                      "values": {"wages": gross_ytd - pre_ytd + left * per_check["wages"], "ss_wages": gross_ytd - exempt_ytd + left * per_check["fica"],
                                 "medicare_wages": gross_ytd - exempt_ytd + left * per_check["fica"], "federal_withheld": federal_ytd + left * per_check["federal"],
                                 "state_withheld": state_ytd + left * per_check["state"], "medicare_withheld": medicare_ytd + left * per_check["medicare"]},
                      "withheld_so_far": federal_ytd})
    return found


def gather(store, year, household, today=None):
    """Every return field the records give for the year, with its source: {"values": {...}, "sources": {...}, "jobs": [...], "businesses": [...]}"""
    today = today or date.today()
    pace = Decimal(12) / today.month if year == today.year else Decimal(1)  # Interest and dividends so far, projected to Dec 31.
    values, sources = {}, {}
    investments = Investments(store, today)
    with store.connection() as db:
        found_jobs = jobs(db, year, today)
        accounts = investments.rows(db, True)
        taxable = [account["id"] for account in accounts if account["tax_treatment"] == "taxable" and account["currency"] == CURRENCY]
        deferred = [account["id"] for account in accounts if account["tax_treatment"] in ("tax_deferred",) and account["currency"] == CURRENCY]

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
    investment_interest, dividends = events("interest", taxable), events("dividend", taxable)
    if ("1099-INT", "1") in forms:
        values["interest"] = forms[("1099-INT", "1")] + scaled(bank_interest, pace)
        sources["interest"] = "1099-INT forms, plus bank interest projected to Dec 31"
    else:
        values["interest"] = scaled(bank_interest + investment_interest, pace)
        sources["interest"] = "Interest so far (bank and taxable investment accounts), projected to Dec 31" if pace != 1 else "Interest recorded"
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
    distributions = forms.get(("1099-R", "2a")) if ("1099-R", "2a") in forms else events("withdrawal", deferred)
    values["retirement_distributions"] = distributions
    sources["retirement_distributions"] = "1099-R box 2a" if ("1099-R", "2a") in forms else "Withdrawals from tax-deferred accounts so far"
    if household.birth_year and distributions and year - household.birth_year < 59:
        values["early_distributions"], sources["early_distributions"] = distributions, "Taken before 59½ (from your birth year); enter 0 if an exception applies"
    if ("1099-INT", "4") in forms or ("1099-DIV", "4") in forms:
        values["other_federal_withholding"] = forms.get(("1099-INT", "4"), 0) + forms.get(("1099-DIV", "4"), 0)
        sources["other_federal_withholding"] = "1099 box 4"
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
    return {"values": values, "sources": sources, "jobs": found_jobs, "businesses": list(businesses.values()), "state": work_state,
            "estimated_payments": payments,
            "notes": tagged["notes"] + ([] if year < today.year else ["Business income and expenses count what's tagged so far; add the rest of the year's in "
                                                                      "“Typed over the records” to project it."] if businesses else [])}


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

    def save(self, year, inputs, unit="me"):
        allowed = {"fields", "jobs", "extra_jobs", "businesses", "people", "students", "w4", "prior_year_tax", "zen_job"}
        unknown = set(inputs) - allowed
        if unknown:
            raise ValueError(f"Unknown inputs: {', '.join(sorted(unknown))}.")
        for key in inputs.get("fields", {}):
            if key not in MONEY_FIELDS + COUNT_FIELDS + ("itemize", "state"):
                raise ValueError(f"Unknown field {key}.")
        with self.store.connection() as db:
            db.execute("INSERT INTO tax_years(year,unit,inputs_json,updated_at) VALUES(?,?,?,?) ON CONFLICT(year,unit) DO UPDATE SET "
                       "inputs_json=excluded.inputs_json,updated_at=excluded.updated_at", (year, unit, json.dumps(inputs), now()))
        return self.inputs(year, unit)
