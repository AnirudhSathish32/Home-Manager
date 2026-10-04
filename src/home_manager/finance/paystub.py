"""A pay stub, explained (docs/taxes.md "Jobs and pay stubs").

breakdown(): the printed lines grouped from gross pay down to net pay, with subtotals for this period and year to date.
explain(): how the income taxes and FICA on the stub are figured. Federal and state income tax use the year's tax table
(confirmed by the user): the period's taxable wages are annualized over the paychecks in a year, the standard
deduction is the 0% bucket, each bracket taxes its own slice, and the year's tax is spread back over the paychecks.
Payroll uses IRS Publication 15-T's method and the W-4, so this is an estimate beside what was actually withheld.
Exact integer and Decimal arithmetic only; amounts are minor units, rates basis points.
"""

from decimal import ROUND_HALF_EVEN, Decimal
import json

from ..core.money import format_minor

GROUPS = (("earnings", "Earnings"), ("pre_tax", "Pre-tax deductions"), ("tax", "Taxes"), ("post_tax", "Post-tax deductions"),
          ("employer_paid", "Paid by your employer (not taken from your pay)"))
FICA = ("social_security", "medicare")
# Pre-tax lines that also lower wages for Social Security and Medicare (cafeteria-plan benefits). A 401(k) lowers
# income-tax wages only.
FICA_EXEMPT = ("health", "dental", "vision", "hsa", "fsa")
STATUS_NAMES = {"single": "single", "married_joint": "married filing jointly", "head_of_household": "head of household"}
STATE_NAMES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut",
               "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
               "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
               "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
               "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
               "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
               "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
               "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
# States with no wage income tax: nothing to look up.
NO_WAGE_TAX = frozenset({"AK", "FL", "NV", "NH", "SD", "TN", "TX", "WA", "WY"})


def jurisdiction_name(code):
    return "Federal" if code == "US" else STATE_NAMES.get(code, code)


def rounded(value):
    return int(Decimal(value).to_integral_value(ROUND_HALF_EVEN))


def total(values):
    values = list(values)
    return None if not values or any(value is None for value in values) else sum(values)


def with_display(value, currency):
    """Every *_minor amount, anywhere inside, gets its exact display text beside it."""
    if isinstance(value, list):
        return [with_display(item, currency) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: with_display(item, currency) for key, item in value.items()}
    display = {key: format_minor(item, currency) for key, item in value.items() if key.endswith("_minor") and isinstance(item, int)}
    if display:
        result["display"] = {**result.get("display", {}), **display}
    return result


def breakdown(record, lines):
    """Gross to net: each group's lines and subtotal (this period and year to date), FICA as Social Security plus
    Medicare, and whether gross less deductions and taxes is the printed net pay."""
    groups = []
    for key, title in GROUPS:
        members = [line for line in lines if line["line_group"] == key]
        if not members and key != "earnings":
            continue
        group = {"group": key, "title": title, "lines": members,
                 "current_minor": total(line["current_minor"] for line in members),
                 "ytd_minor": total(line["ytd_minor"] for line in members)}
        if key == "tax":
            fica = [line for line in members if line["category"] in FICA]
            if fica:
                group["fica"] = {"current_minor": total(line["current_minor"] for line in fica), "ytd_minor": total(line["ytd_minor"] for line in fica)}
        groups.append(group)
    taken = {column: total([group[column] for group in groups if group["group"] in ("pre_tax", "tax", "post_tax")] or [0])
             for column in ("current_minor", "ytd_minor")}
    checks = []
    for column, gross, net, label in (("current_minor", record.get("gross_pay_minor"), record.get("net_pay_minor"), "This period"),
                                      ("ytd_minor", record.get("gross_pay_ytd_minor"), record.get("net_pay_ytd_minor"), "Year to date")):
        if gross is None or net is None or taken[column] is None or not lines:
            continue
        checks.append({"label": label, "gross_minor": gross, "taken_minor": taken[column], "computed_net_minor": gross - taken[column],
                       "net_minor": net, "difference_minor": net - (gross - taken[column]), "matches": gross - taken[column] == net})
    return {"groups": groups, "checks": checks}


def taxable_wages(lines):
    """(income-tax wages, FICA wages) for this period and year to date: gross less the pre-tax lines that lower each."""
    earnings = [line for line in lines if line["line_group"] == "earnings"]
    pre_tax = [line for line in lines if line["line_group"] == "pre_tax"]
    fica_pre_tax = [line for line in pre_tax if line["category"] in FICA_EXEMPT]
    result = {}
    for column in ("current_minor", "ytd_minor"):
        gross = total(line[column] for line in earnings)
        result[column] = (None if gross is None else gross - (total(line[column] for line in pre_tax) or 0),
                          None if gross is None else gross - (total(line[column] for line in fica_pre_tax) or 0))
    return result


def income_tax(code, table, wages, paychecks, actual, other_income=0, extra_deductions=0, credits=0):
    """One jurisdiction's income tax, bucket by bucket, for a year of paychecks like this one. The W-4 adjustments (the
    paycheck planner, finance/paycheck.py) add other income to the year's wages, add deductions beside the standard
    deduction as a second 0% bucket, and take credits off the year's tax."""
    annual = wages * paychecks + other_income
    standard = table["standard_deduction_minor"]
    deduction = standard + extra_deductions
    brackets = json.loads(table["brackets_json"])
    taxable = max(0, annual - deduction)
    buckets = [{"label": "Standard deduction", "rate_bp": 0, "from_minor": 0, "to_minor": standard,
                "income_minor": min(annual, standard), "tax_minor": 0}]
    if extra_deductions:
        buckets.append({"label": "Other deductions", "rate_bp": 0, "from_minor": standard, "to_minor": deduction,
                        "income_minor": max(0, min(annual, deduction) - standard), "tax_minor": 0})
    exact = Decimal(0)
    for index, bracket in enumerate(brackets):
        start = bracket["from_minor"]
        end = brackets[index + 1]["from_minor"] if index + 1 < len(brackets) else None
        slice_ = max(0, min(taxable, end) - start) if end is not None else max(0, taxable - start)
        tax = Decimal(slice_) * bracket["rate_bp"] / 10000
        exact += tax
        # Bracket bounds are over taxable income; shown over wages, they start after the standard deduction.
        buckets.append({"label": f"{Decimal(bracket['rate_bp']) / 100:g}%", "rate_bp": bracket["rate_bp"], "from_minor": deduction + start,
                        "to_minor": deduction + end if end is not None else None, "income_minor": slice_, "tax_minor": rounded(tax)})
    for bucket in buckets:
        bucket["per_paycheck_income_minor"] = rounded(Decimal(bucket["income_minor"]) / paychecks)
        bucket["per_paycheck_tax_minor"] = rounded(Decimal(bucket["tax_minor"]) / paychecks)
    before_credits = exact
    exact = max(Decimal(0), exact - credits)
    estimate = rounded(exact / paychecks)
    top = next((bucket for bucket in reversed(buckets) if bucket["income_minor"] > 0), buckets[0])
    return {"jurisdiction": code, "name": jurisdiction_name(code), "status": "verified", "period_wages_minor": wages,
            "annual_wages_minor": annual, "standard_deduction_minor": standard,
            "standard_deduction_per_paycheck_minor": rounded(Decimal(standard) / paychecks), "taxable_minor": taxable,
            "other_income_minor": other_income, "extra_deductions_minor": extra_deductions,
            "tax_before_credits_minor": rounded(before_credits), "credits_minor": min(credits, rounded(before_credits)),
            "buckets": buckets, "annual_tax_minor": rounded(exact), "estimate_minor": estimate, "actual_minor": actual,
            "difference_minor": None if actual is None else actual - estimate, "top_rate_bp": top["rate_bp"],
            "effective_rate_bp": rounded(exact * 10000 / annual) if annual else 0,
            "sources": json.loads(table["sources_json"])}


def fica(table, wages, ytd_wages, actual):
    """Social Security (up to the year's wage base) and Medicare (plus the additional rate above its threshold) on
    this paycheck's FICA wages; year-to-date wages decide how much of the paycheck is still under each limit."""
    before = None if ytd_wages is None else max(0, ytd_wages - wages)
    rows = []
    base = table.get("ss_wage_base_minor")
    under = wages if before is None or base is None else max(0, min(wages, base - before))
    if table.get("ss_rate_bp") is not None:
        rows.append({"name": "Social Security", "category": "social_security", "rate_bp": table["ss_rate_bp"], "wages_minor": under,
                     "limit_minor": base, "estimate_minor": rounded(Decimal(under) * table["ss_rate_bp"] / 10000),
                     "actual_minor": actual.get("social_security")})
    if table.get("medicare_rate_bp") is not None:
        estimate = Decimal(wages) * table["medicare_rate_bp"] / 10000
        threshold, extra_rate = table.get("additional_medicare_threshold_minor"), table.get("additional_medicare_rate_bp")
        above = 0
        if threshold is not None and extra_rate and before is not None:
            above = max(0, before + wages - max(threshold, before))
            estimate += Decimal(above) * extra_rate / 10000
        rows.append({"name": "Medicare", "category": "medicare", "rate_bp": table["medicare_rate_bp"], "wages_minor": wages,
                     "additional_rate_bp": extra_rate, "additional_wages_minor": above, "limit_minor": threshold,
                     "estimate_minor": rounded(estimate), "actual_minor": actual.get("medicare")})
    for row in rows:
        row["difference_minor"] = None if row["actual_minor"] is None else row["actual_minor"] - row["estimate_minor"]
    return rows


def explain(record, lines, tables, filing_status):
    """How this stub's taxes are figured. tables: {jurisdiction: tax_tables row} for the pay date's year, any status."""
    year = int(record["pay_date"][:4]) if record.get("pay_date") else None
    paychecks = record.get("pay_frequency")
    state = record.get("work_state")
    result = {"year": year, "filing_status": filing_status, "filing_status_name": STATUS_NAMES[filing_status], "paychecks": paychecks,
              "state": state, "jurisdictions": [], "fica": [], "notes": []}
    wages = taxable_wages(lines)
    (income_wages, fica_wages), (_, fica_ytd) = wages["current_minor"], wages["ytd_minor"]
    if year is None or not lines or income_wages is None:
        result["notes"].append("The pay date or the earnings lines weren't read, so the taxes can't be explained.")
        return with_display(result, record["currency"])
    actual = {}
    for line in lines:
        if line["line_group"] == "tax" and line["current_minor"] is not None:
            actual[line["category"]] = actual.get(line["category"], 0) + line["current_minor"]
    result.update(income_tax_wages_minor=income_wages, fica_wages_minor=fica_wages)
    for code in ["US", *([state] if state and state not in NO_WAGE_TAX else [])]:
        table = tables.get(code)
        name = jurisdiction_name(code)
        withheld = actual.get("federal_income_tax" if code == "US" else "state_income_tax")
        if table is None or table["status"] != "verified":
            waiting = table is not None and table["status"] == "proposed"
            result["jurisdictions"].append({"jurisdiction": code, "name": name, "status": "proposed" if waiting else "missing", "actual_minor": withheld,
                                            "message": f"The {year} {name} tax table waits for your confirmation in Review." if waiting else
                                            f"The {year} {name} tax table hasn't been looked up yet."})
            continue
        if not paychecks:
            result["jurisdictions"].append({"jurisdiction": code, "name": name, "status": "unknown_frequency", "actual_minor": withheld,
                                            "message": "How often you're paid isn't printed, so a year of paychecks can't be worked out."})
            continue
        result["jurisdictions"].append(income_tax(code, table, income_wages, paychecks, withheld))
    federal = tables.get("US")
    if federal and federal["status"] == "verified" and fica_wages is not None:
        result["fica"] = fica(federal, fica_wages, fica_ytd, actual)
    if state in NO_WAGE_TAX:
        result["notes"].append(f"{jurisdiction_name(state)} has no state income tax on wages.")
    if any(line["line_group"] == "pre_tax" and line["category"] == "other" for line in lines):
        result["notes"].append("A pre-tax deduction the stub doesn't name clearly was taken off income-tax wages but not FICA wages.")
    result["notes"].append("Payroll figures withholding with IRS Publication 15-T and your W-4 (extra withholding, credits, other income), "
                           "so the estimate and what was withheld can differ.")
    return with_display(result, record["currency"])
