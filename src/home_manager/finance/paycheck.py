"""The paycheck planner: a paycheck worked out forward from gross pay (docs/planning.md "What If").

paystub.py explains a real stub backward; this builds one from typed inputs, for a new job, a raise, a move to another state
or another person's salary. Every line from gross to net is shown for one paycheck and for the year:
- earnings, then each pre-tax deduction (a 401(k) lowers income-tax wages only; health, dental, vision, HSA and FSA also
  lower Social Security and Medicare wages, paystub.FICA_EXEMPT);
- federal income tax from the year's confirmed table, with its standard deduction (or yours) and the W-4 adjustments;
- state income tax from the state's table, with the state's deduction or exemption (or yours), or a flat rate you type;
- local tax and state disability insurance when set;
- Social Security and Medicare, check by check through the year, so the check where Social Security stops at the wage
  base (or additional Medicare starts) is visible;
- post-tax deductions, net pay, and what the employer pays in beside it (the 401(k) match, an HSA contribution).
Income taxes use the same annualized method as paystub.income_tax. Exact integer and Decimal arithmetic; amounts are minor
units, rates basis points. Nothing is stored.
"""

from decimal import ROUND_HALF_UP, Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..core.money import as_decimal_text, format_minor, percent_text, to_minor
from ..core.trace import NULL
from .paystub import FICA_EXEMPT, NO_WAGE_TAX, STATUS_NAMES, fica, income_tax, jurisdiction_name, record_fica, rounded, taxable_wages, with_display

CURRENCY = "USD"  # Tax tables are in dollars.
FREQUENCIES = {12: "monthly", 24: "twice a month", 26: "every two weeks", 52: "weekly"}
EARNING_CATEGORIES = ("regular_pay", "overtime", "bonus", "commission", "other_earnings")
PRE_TAX_CATEGORIES = ("retirement_pretax", "hsa", "fsa", "health", "dental", "vision", "other")
POST_TAX_CATEGORIES = ("retirement_roth", "life_insurance", "other")
EMPLOYER_CATEGORIES = ("retirement_pretax", "hsa", "health", "dental", "vision", "life_insurance", "other")
RETIREMENT = ("retirement_pretax", "retirement_roth")
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
TAX_ORDER = ("federal_income_tax", "state_income_tax", "local_tax", "social_security", "medicare", "state_disability")
LABELS = {"regular_pay": "Regular pay", "overtime": "Overtime", "bonus": "Bonus", "commission": "Commission", "other_earnings": "Other earnings",
          "retirement_pretax": "401(k)", "retirement_roth": "Roth 401(k)", "hsa": "HSA", "fsa": "FSA", "health": "Health insurance",
          "dental": "Dental insurance", "vision": "Vision insurance", "life_insurance": "Life insurance", "other": "Other",
          "federal_income_tax": "Federal income tax", "state_income_tax": "State income tax", "local_tax": "Local tax",
          "social_security": "Social Security", "medicare": "Medicare", "state_disability": "State disability insurance",
          "employer_match": "401(k) match"}
# Federal withholding on supplemental wages (bonuses) paid separately: a flat 22%, and a mandatory 37% on supplemental
# wages above $1 million in the year (26 CFR 31.3402(g)-1(a)(2) and (a)(7); IRS Publication 15, section 7).
SUPPLEMENTAL_RATE_BP, SUPPLEMENTAL_HIGH_RATE_BP, SUPPLEMENTAL_HIGH_OVER = 2200, 3700, 100_000_000
AMOUNT = Field(default=None, max_length=30)
RATE = r"^\d{1,3}(\.\d{1,2})?$"


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PayLine(StrictInput):
    category: str = Field(max_length=40)
    label: str = Field(default="", max_length=60)
    amount: str | None = Field(default=None, max_length=30, description="Per paycheck.")
    percent: str | None = Field(default=None, pattern=RATE, description="Of gross pay per paycheck.")

    @model_validator(mode="after")
    def one_amount(self):
        if (self.amount is None) == (self.percent is None):
            raise ValueError("Give each line an amount per paycheck or a percent of gross pay.")
        return self


class Bonus(StrictInput):
    """Supplemental wages paid once in a year, with the regular paycheck of its month."""
    label: str = Field(default="", max_length=60)
    amount: str = Field(min_length=1, max_length=30)
    month: int = Field(ge=1, le=12)


class PaycheckInput(StrictInput):
    year: int = Field(ge=2000, le=2100)
    filing_status: Literal["single", "married_joint", "head_of_household"]
    work_state: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    pay_frequency: Literal[12, 24, 26, 52]
    annual_salary: str | None = AMOUNT
    gross_per_check: str | None = AMOUNT
    earnings: list[PayLine] = Field(default_factory=list, max_length=10, description="Pay beside the salary, per paycheck.")
    pre_tax: list[PayLine] = Field(default_factory=list, max_length=15)
    post_tax: list[PayLine] = Field(default_factory=list, max_length=10)
    employer: list[PayLine] = Field(default_factory=list, max_length=10, description="Paid by the employer, not taken from pay.")
    match_percent: str | None = Field(default=None, pattern=RATE, description="The employer adds this percent of what you put in…")
    match_limit_percent: str | None = Field(default=None, pattern=RATE, description="…up to this percent of your gross pay.")
    federal_deduction: str | None = Field(default=None, max_length=30, description="Instead of the table's standard deduction, a year.")
    federal_other_income: str = Field(default="0", max_length=30, description="W-4 step 4(a), a year.")
    federal_deductions: str = Field(default="0", max_length=30, description="W-4 step 4(b), a year.")
    federal_credits: str = Field(default="0", max_length=30, description="W-4 step 3, a year.")
    federal_extra_withholding: str = Field(default="0", max_length=30, description="W-4 step 4(c), per paycheck.")
    federal_step2: bool = Field(default=False, description="W-4 step 2 checked (multiple jobs, or a spouse who works).")
    bonuses: list[Bonus] = Field(default_factory=list, max_length=12)
    state_credits: str = Field(default="0", max_length=30, description="Credits off the state's year of tax, e.g. an exemption credit.")
    state_supplemental_percent: str | None = Field(default=None, pattern=RATE, description="The state's withholding rate on bonuses.")
    state_deduction: str | None = Field(default=None, max_length=30, description="The state's deduction or exemption, a year.")
    state_rate_percent: str | None = Field(default=None, pattern=RATE, description="A flat state rate instead of the state's table.")
    state_extra_withholding: str = Field(default="0", max_length=30, description="Per paycheck.")
    state_disability_percent: str | None = Field(default=None, pattern=RATE)
    state_disability_wage_limit: str | None = Field(default=None, max_length=30, description="Wages a year it stops at, if any.")
    local_tax_percent: str | None = Field(default=None, pattern=RATE)
    local_tax_amount: str | None = Field(default=None, max_length=30, description="Per paycheck.")
    local_tax_wages: Literal["taxable", "gross"] = "taxable"

    @model_validator(mode="after")
    def consistent(self):
        if (self.annual_salary is None) == (self.gross_per_check is None):
            raise ValueError("Enter a yearly salary or the gross pay per paycheck.")
        for name, allowed in (("earnings", EARNING_CATEGORIES), ("pre_tax", PRE_TAX_CATEGORIES), ("post_tax", POST_TAX_CATEGORIES),
                              ("employer", EMPLOYER_CATEGORIES)):
            for line in getattr(self, name):
                if line.category not in allowed:
                    raise ValueError(f"{line.category} can't be a {name.replace('_', '-')} line; choose one of: {', '.join(allowed)}.")
        if any(line.percent is not None for line in self.earnings):
            raise ValueError("Give extra earnings as an amount per paycheck.")
        if (self.match_percent is None) != (self.match_limit_percent is None):
            raise ValueError("Give both the match percent and the percent of pay it stops at.")
        if self.local_tax_percent is not None and self.local_tax_amount is not None:
            raise ValueError("Give local tax as a percent or an amount, not both.")
        return self


def shown(amount, currency=CURRENCY):
    """Money in an explanation, as the page shows it: 104,000.00 USD."""
    return format_minor(amount, currency)


def cents(text, what):
    value = to_minor(text, CURRENCY)
    if value < 0:
        raise ValueError(f"{what} can't be negative.")
    return value


def basis_points(percent):
    return int(Decimal(percent) * 100)


def share(amount, rate_bp):
    return rounded(Decimal(amount) * rate_bp / 10000)


def priced(line: PayLine, gross):
    """A line's amount per paycheck and how it was figured."""
    if line.percent is not None:
        return share(gross, basis_points(line.percent)), f"{Decimal(line.percent):g}% of gross pay"
    return cents(line.amount, line.label or LABELS[line.category]), None


def row(category, label, per_check, annual, how=None, **extra):
    return {"category": category, "label": label or LABELS.get(category, category), "per_check_minor": per_check, "annual_minor": annual,
            "how": how, **extra}


def missing(code, year, table):
    name = jurisdiction_name(code)
    waiting = table is not None and table["status"] == "proposed"
    return {"jurisdiction": code, "name": name, "status": "proposed" if waiting else "missing",
            "message": f"The {year} {name} tax table waits for your confirmation in Review." if waiting else
            f"The {year} {name} tax table hasn't been looked up yet."}


def whole_dollars(value):
    """Minor units rounded to a whole dollar, half up, as the IRS rounds its withholding schedules."""
    return int((Decimal(value) / 100).quantize(Decimal(1), ROUND_HALF_UP)) * 100


def step2_table(table):
    """Publication 15-T's schedule for a W-4 with Step 2 checked: every threshold of the standard schedule halved, so the
    untaxed part is half the standard deduction and each bracket starts at half its usual wage level, in whole dollars.
    (Without the box, Pub 15-T's schedule is the brackets shifted by the standard deduction, which income_tax already does.)"""
    standard = table["standard_deduction_minor"]
    half = whole_dollars(Decimal(standard) / 2)
    brackets = [{"from_minor": 0 if bracket["from_minor"] == 0 else whole_dollars(Decimal(standard + bracket["from_minor"]) / 2) - half,
                 "rate_bp": bracket["rate_bp"]} for bracket in json.loads(table["brackets_json"])]
    return {**table, "standard_deduction_minor": half, "brackets_json": json.dumps(brackets)}


def supplemental(amount, paid_before):
    """Federal withholding on a bonus: 22%, and 37% on the part of the year's supplemental wages above $1 million."""
    room = max(0, SUPPLEMENTAL_HIGH_OVER - paid_before)
    return share(min(amount, room), SUPPLEMENTAL_RATE_BP) + share(max(0, amount - room), SUPPLEMENTAL_HIGH_RATE_BP)


def paycheck_of(month, checks):
    """The paycheck a bonus paid in `month` rides with: the first of that month."""
    return (month - 1) * checks // 12 + 1


def segments(values):
    """Consecutive paychecks with the same amounts, as ranges: [(first, last, amounts)]."""
    result: list[list] = []
    for number, amounts in enumerate(values, 1):
        if result and result[-1][2] == amounts:
            result[-1][1] = number
        else:
            result.append([number, number, amounts])
    return result


def record_net(recorder, groups):
    """A regular paycheck's take-home pay (one with no bonus in it), line by line: its earnings, less each deduction and
    tax. Social Security, Medicare and disability insurance are that paycheck's."""
    signs = {"earnings": 1, "pre_tax": -1, "tax": -1, "post_tax": -1}
    for group in groups:
        for line in group["lines"] if group["group"] in signs else []:
            if line["per_check_minor"]:
                recorder.add(line["label"] or line["category"].replace("_", " ").capitalize(), signs[group["group"]] * line["per_check_minor"], CURRENCY)


def record_monthly(recorder, schedule):
    """The year's take-home pay a month: each run of like paychecks' share of a twelfth, rounded down, then the rounding."""
    steps = 0
    for segment in schedule:
        count = segment["to_check"] - segment["from_check"] + 1
        part = count * segment["net_minor"] // 12
        recorder.add(f"Paychecks {segment['from_check']}–{segment['to_check']}: {count} × {format_minor(segment['net_minor'], CURRENCY)} ÷ 12", part, CURRENCY)
        steps += part
    return steps


def calculate(value: PaycheckInput, tables, recorder=NULL, only="net"):
    """The paycheck, gross to net. tables: {jurisdiction: tax_tables row} for the year and filing status (any status).
    only: what a live recorder gets (finance/tax_traces.py): "net" (a regular paycheck's take-home pay, line by line),
    "monthly" (the year's take-home pay a month), or a tax line's category (its amount a regular paycheck)."""
    line_recorder = lambda category: recorder if only == category else NULL
    checks = value.pay_frequency
    notes = []
    # Earnings.
    if value.annual_salary is not None:
        salary = cents(value.annual_salary, "The salary")
        regular = rounded(Decimal(salary) / checks)
        how = f"{shown(salary, CURRENCY)} a year over {checks} paychecks"
        if regular * checks != salary:
            notes.append(f"Each paycheck rounds to the cent, so the year's regular pay is {shown(regular * checks, CURRENCY)}.")
    else:
        regular, how = cents(value.gross_per_check, "Gross pay"), None
    earnings = [row("regular_pay", "", regular, regular * checks, how)]
    for line in value.earnings:
        amount, _ = priced(line, 0)
        earnings.append(row(line.category, line.label, amount, amount * checks))
    gross = sum(line["per_check_minor"] for line in earnings)
    # Pre-tax deductions, and the wages each tax is figured on (paystub.taxable_wages).
    pre_tax = []
    for line in value.pre_tax:
        amount, how = priced(line, gross)
        lowers = "lowers income-tax, Social Security and Medicare wages" if line.category in FICA_EXEMPT else "lowers income-tax wages only"
        explained = "; ".join(part for part in (how, lowers) if part)
        pre_tax.append(row(line.category, line.label, amount, amount * checks, explained[0].upper() + explained[1:],
                           fica_exempt=line.category in FICA_EXEMPT))
    lines = ([{"line_group": "earnings", "category": line["category"], "current_minor": line["per_check_minor"], "ytd_minor": None} for line in earnings]
             + [{"line_group": "pre_tax", "category": line["category"], "current_minor": line["per_check_minor"], "ytd_minor": None} for line in pre_tax])
    income_wages, fica_wages = taxable_wages(lines)["current_minor"]
    if income_wages < 0:
        raise ValueError("Pre-tax deductions are more than gross pay.")
    state = value.work_state
    state_wages = income_wages
    taxes, jurisdictions, complete = [], [], True
    # Federal income tax.
    federal = tables.get("US")
    extra = cents(value.federal_extra_withholding, "Extra withholding")
    if federal is None or federal["status"] != "verified":
        jurisdictions.append(missing("US", value.year, federal))
        complete = False
    else:
        used = ({**federal, "standard_deduction_minor": cents(value.federal_deduction, "The federal deduction")}
                if value.federal_deduction is not None else federal)
        if value.federal_step2:
            used = step2_table(used)
        part = income_tax("US", used, income_wages, checks, None, cents(value.federal_other_income, "Other income"),
                          cents(value.federal_deductions, "Deductions"), cents(value.federal_credits, "Credits"), line_recorder("federal_income_tax"))
        if extra:
            line_recorder("federal_income_tax").add("Extra withholding (W-4 Step 4(c))", extra, CURRENCY)
        part.update(table_deduction_minor=federal["standard_deduction_minor"], deduction_overridden=value.federal_deduction is not None,
                    extra_withholding_minor=extra, step2=value.federal_step2)
        if value.federal_step2:
            part["buckets"][0]["label"] = "Half the standard deduction (W-4 Step 2)"
        jurisdictions.append(part)
        how = f"{shown(part['annual_tax_minor'], CURRENCY)} a year over {checks} paychecks" + (
            " on the W-4 Step 2 schedule (half-size brackets)" if value.federal_step2 else "") + (
            f", plus {shown(extra, CURRENCY)} extra (W-4 4(c))" if extra else "")
        taxes.append(row("federal_income_tax", "", part["estimate_minor"] + extra, (part["estimate_minor"] + extra) * checks, how))
    # State income tax.
    state_extra = cents(value.state_extra_withholding, "State extra withholding")
    if state and state in NO_WAGE_TAX:
        notes.append(f"{jurisdiction_name(state)} has no state income tax on wages.")
    elif state:
        table = tables.get(state)
        deduction = cents(value.state_deduction, "The state deduction") if value.state_deduction is not None else None
        if value.state_rate_percent is not None:
            used = {"standard_deduction_minor": deduction or 0, "brackets_json": json.dumps([{"from_minor": 0, "rate_bp": basis_points(value.state_rate_percent)}]),
                    "sources_json": "[]"}
            source = "typed"
        elif table is not None and table["status"] == "verified":
            used = {**table, "standard_deduction_minor": deduction} if deduction is not None else table
            source = "table"
        else:
            used = None
            jurisdictions.append(missing(state, value.year, table))
            complete = False
        if used is not None:
            state_credits = cents(value.state_credits, "State credits")
            part = income_tax(state, used, state_wages, checks, None, credits=state_credits, recorder=line_recorder("state_income_tax"))
            if state_extra:
                line_recorder("state_income_tax").add("Extra state withholding", state_extra, CURRENCY)
            part.update(table_deduction_minor=table["standard_deduction_minor"] if table is not None and table["status"] == "verified" else None,
                        deduction_overridden=deduction is not None, extra_withholding_minor=state_extra, source=source)
            jurisdictions.append(part)
            how = (f"{Decimal(value.state_rate_percent or 0):g}% flat rate you entered, " if source == "typed" else "") + \
                f"{shown(part['annual_tax_minor'], CURRENCY)} a year" + (f" after {shown(part['credits_minor'], CURRENCY)} of credits" if state_credits else "") + \
                f" over {checks} paychecks" + (f", plus {shown(state_extra, CURRENCY)} extra" if state_extra else "")
            taxes.append(row("state_income_tax", f"{jurisdiction_name(state)} income tax", part["estimate_minor"] + state_extra,
                             (part["estimate_minor"] + state_extra) * checks, how))
            notes.append("State taxable wages are taken to be the federal ones; a few states treat some pre-tax deductions differently.")
    # Local tax.
    if value.local_tax_percent is not None:
        base = income_wages if value.local_tax_wages == "taxable" else gross
        amount = share(base, basis_points(value.local_tax_percent))
        taxes.append(row("local_tax", "", amount, amount * checks,
                         f"{Decimal(value.local_tax_percent):g}% of {'income-tax wages' if value.local_tax_wages == 'taxable' else 'gross pay'}"))
    elif value.local_tax_amount is not None:
        amount = cents(value.local_tax_amount, "Local tax")
        taxes.append(row("local_tax", "", amount, amount * checks))
    for line in taxes:
        if line["category"] == "local_tax":
            line_recorder("local_tax").add(line["how"] or "The local tax a paycheck, as you entered it", line["per_check_minor"], CURRENCY)
    # Post-tax deductions and what the employer pays, each paycheck.
    post_tax = []
    for line in value.post_tax:
        amount, how = priced(line, gross)
        post_tax.append(row(line.category, line.label, amount, amount * checks, how))
    employer = []
    for line in value.employer:
        amount, how = priced(line, gross)
        employer.append(row(line.category, line.label, amount, amount * checks, how))
    match_bp = limit_bp = None
    if value.match_percent is not None and value.match_limit_percent is not None:
        match_bp, limit_bp = basis_points(value.match_percent), basis_points(value.match_limit_percent)
        put_in = sum(line["per_check_minor"] for line in pre_tax + post_tax if line["category"] in RETIREMENT)
        amount = share(min(put_in, share(gross, limit_bp)), match_bp)
        employer.append(row("employer_match", "", amount, amount * checks,
                            f"{Decimal(value.match_percent):g}% of what you put in, up to {Decimal(value.match_limit_percent):g}% of gross pay"))
    # Bonuses (supplemental wages), each with the first paycheck of its month. Percent-of-pay deductions take their share;
    # federal withholding is the flat supplemental rate; the state's is the supplemental rate entered; Social Security,
    # Medicare and disability insurance count the bonus in its paycheck (below).
    state_taxes = bool(state) and state not in NO_WAGE_TAX
    bonuses: list[dict] = []
    bonus_fica: dict[int, int] = {}  # Paycheck number: the bonus wages it adds for Social Security and Medicare.
    paid = 0
    for bonus in sorted(value.bonuses, key=lambda item: item.month):
        amount = cents(bonus.amount, "A bonus")
        number = paycheck_of(bonus.month, checks)
        pre = {index: share(amount, basis_points(line.percent)) for index, line in enumerate(value.pre_tax) if line.percent is not None}
        post = {index: share(amount, basis_points(line.percent)) for index, line in enumerate(value.post_tax) if line.percent is not None}
        taxable = amount - sum(pre.values())
        fica_amount = amount - sum(part for index, part in pre.items() if value.pre_tax[index].category in FICA_EXEMPT)
        federal_tax = supplemental(taxable, paid)
        paid += taxable
        state_tax = share(taxable, basis_points(value.state_supplemental_percent)) if state_taxes and value.state_supplemental_percent is not None else 0
        local = share(taxable if value.local_tax_wages == "taxable" else amount, basis_points(value.local_tax_percent)) if value.local_tax_percent is not None else 0
        put = (sum(part for index, part in pre.items() if value.pre_tax[index].category in RETIREMENT)
               + sum(part for index, part in post.items() if value.post_tax[index].category in RETIREMENT))
        match = share(min(put, share(amount, limit_bp)), match_bp) if match_bp is not None and limit_bp is not None else 0
        bonus_fica[number] = bonus_fica.get(number, 0) + fica_amount
        bonuses.append({"label": bonus.label or "Bonus", "month": bonus.month, "check": number, "gross_minor": amount, "pre": pre, "post": post,
                        "taxable_minor": taxable, "fica_wages_minor": fica_amount, "federal_minor": federal_tax, "state_minor": state_tax,
                        "local_minor": local, "match_minor": match, "fica_minor": 0,
                        "retirement_minor": put + match,
                        "hsa_minor": sum(part for index, part in pre.items() if value.pre_tax[index].category == "hsa")})
    if bonuses and state_taxes and value.state_supplemental_percent is None:
        notes.append(f"Enter {jurisdiction_name(state)}'s supplemental rate to include its withholding on bonuses; it is left out now.")
    # Social Security, Medicare and state disability insurance, check by check: their wage limits are reached during the year,
    # and a bonus adds to its paycheck's wages.
    rates = {}
    if federal is not None and federal["status"] == "verified":
        rates["fica"] = federal
    disability = basis_points(value.state_disability_percent) if value.state_disability_percent is not None else None
    limit = cents(value.state_disability_wage_limit, "The disability wage limit") if value.state_disability_wage_limit else None

    def variable(wages, through):
        """Social Security, Medicare and disability insurance on one paycheck's wages, `through` the year's wages so far."""
        amounts = {}
        if "fica" in rates:
            for part in fica(federal, wages, through, {}):
                amounts[part["category"]] = part["estimate_minor"]
        if disability is not None:
            before = through - wages
            under = wages if limit is None else max(0, min(wages, limit - before))
            amounts["state_disability"] = share(under, disability)
        return amounts
    per_check, through, throughs = [], 0, []
    for number in range(1, checks + 1):
        wages = fica_wages + bonus_fica.get(number, 0)
        amounts = variable(wages, through + wages)
        if number in bonus_fica:
            # What the bonus itself adds: this paycheck's taxes less what they'd be without it. The first bonus of the paycheck carries it.
            without = variable(fica_wages, through + fica_wages)
            next(item for item in bonuses if item["check"] == number)["fica_minor"] = sum(amounts.values()) - sum(without.values())
        through += wages
        throughs.append(through)
        per_check.append(amounts)
    typical = next((number for number in range(1, checks + 1) if number not in bonus_fica), 1)
    if recorder.live and only in ("social_security", "medicare") and "fica" in rates:
        record_fica(recorder, next(part for part in fica(federal, fica_wages, throughs[typical - 1], {}) if part["category"] == only), CURRENCY)
    elif recorder.live and only == "state_disability" and disability is not None:
        recorder.add(f"{Decimal(value.state_disability_percent or 0):g}% of this paycheck's wages under the year's limit", per_check[typical - 1]["state_disability"], CURRENCY)
    fica_rows = fica(federal, fica_wages, fica_wages, {}) if "fica" in rates else []
    for category in ("social_security", "medicare", "state_disability"):
        if per_check and category in per_check[0]:
            detail = next((part for part in fica_rows if part["category"] == category), None)
            how = None
            if detail and category == "social_security":
                how = f"{Decimal(detail['rate_bp']) / 100:g}% of Social Security wages up to {shown(detail['limit_minor'], CURRENCY)} a year" \
                    if detail["limit_minor"] is not None else f"{Decimal(detail['rate_bp']) / 100:g}% of Social Security wages"
            elif detail:
                how = f"{Decimal(detail['rate_bp']) / 100:g}% of Medicare wages" + (
                    f", plus {Decimal(detail['additional_rate_bp']) / 100:g}% above {shown(detail['limit_minor'], CURRENCY)} a year"
                    if detail.get("additional_rate_bp") and detail["limit_minor"] is not None else "")
            elif category == "state_disability":
                how = f"{Decimal(value.state_disability_percent or 0):g}% of wages" + (f" up to {shown(limit, CURRENCY)} a year" if limit else "")
            taxes.append(row(category, "", per_check[typical - 1][category], sum(amounts[category] for amounts in per_check), how))
    if not rates:
        notes.append("Social Security and Medicare need the year's federal table, so they are left out until it is confirmed.")
    # Regular pay, before bonuses: gross less fixed deductions and income taxes each paycheck.
    regular_net = gross - sum(line["per_check_minor"] for line in pre_tax + post_tax) - sum(
        line["per_check_minor"] for line in taxes if line["category"] not in ("social_security", "medicare", "state_disability"))
    # Each bonus in the year's columns: its earnings line, its share of each deduction and its withholding.
    by_category = {line["category"]: line for line in taxes}
    for item in bonuses:
        earnings.append(row("supplemental", f"{item['label']} ({MONTH_NAMES[item['month'] - 1]})", None, item["gross_minor"],
                            f"A bonus, paid with paycheck {item['check']}"))
        for index, part in item["pre"].items():
            pre_tax[index]["annual_minor"] += part
        for index, part in item["post"].items():
            post_tax[index]["annual_minor"] += part
        for category, key in (("federal_income_tax", "federal_minor"), ("state_income_tax", "state_minor"), ("local_tax", "local_minor")):
            if item[key]:
                if category not in by_category:
                    by_category[category] = row(category, "", 0, 0)
                    taxes.append(by_category[category])
                by_category[category]["annual_minor"] += item[key]
        if item["match_minor"]:
            next(line for line in employer if line["category"] == "employer_match")["annual_minor"] += item["match_minor"]
        item["net_minor"] = (item["gross_minor"] - sum(item["pre"].values()) - sum(item["post"].values()) - item["federal_minor"]
                             - item["state_minor"] - item["local_minor"] - item["fica_minor"])
    if bonuses:
        notes.append("Bonuses are withheld at the federal supplemental rate: 22%, and 37% on bonuses above $1 million in the year. "
                     "Your tax return taxes them as ordinary wages.")
    taxes.sort(key=lambda line: TAX_ORDER.index(line["category"]))
    # Gross to net, a regular paycheck and the year.
    groups = []
    for key, title, members in (("earnings", "Earnings", earnings), ("pre_tax", "Pre-tax deductions", pre_tax), ("tax", "Taxes", taxes),
                                ("post_tax", "Post-tax deductions", post_tax),
                                ("employer_paid", "Paid by your employer (not taken from your pay)", employer)):
        if not members and key not in ("earnings", "tax"):
            continue
        group = {"group": key, "title": title, "lines": members, "per_check_minor": sum(line["per_check_minor"] or 0 for line in members),
                 "annual_minor": sum(line["annual_minor"] for line in members)}
        if key == "tax":
            fica_lines = [line for line in members if line["category"] in ("social_security", "medicare")]
            if fica_lines:
                group["fica"] = {"per_check_minor": sum(line["per_check_minor"] for line in fica_lines),
                                 "annual_minor": sum(line["annual_minor"] for line in fica_lines)}
        groups.append(group)
    totals = {group["group"]: group for group in groups}
    # Each paycheck's take-home pay: regular pay less its FICA and disability insurance, plus any bonus it carries. The
    # paycheck's FICA already includes what the bonus added, which the bonus's net also takes off, so it is added back once.
    net_each = []
    for number, amounts in enumerate(per_check, 1):
        riding = [item for item in bonuses if item["check"] == number]
        net_each.append(regular_net - sum(amounts.values()) + sum(item["net_minor"] + item["fica_minor"] for item in riding))
    bonus_net = sum(item["net_minor"] for item in bonuses)
    net = {"per_check_minor": net_each[typical - 1], "annual_minor": sum(net_each), "monthly_minor": rounded(Decimal(sum(net_each)) / 12),
           "regular_monthly_minor": rounded(Decimal(sum(net_each) - bonus_net) / 12)}
    schedule = [{"from_check": first, "to_check": last, "net_minor": net_each[first - 1],
                 **{f"{category}_minor": amount for category, amount in amounts.items()}}
                for first, last, amounts in segments([{**amounts, **({"bonus": sum(item["gross_minor"] for item in bonuses if item["check"] == number)}
                                                                      if number in bonus_fica else {})}
                                                      for number, amounts in enumerate(per_check, 1)])]
    if len(schedule) > 1:
        notes.append("Some paychecks differ from a regular one: a bonus, or a wage limit reached during the year (see the schedule).")
    annual_gross = totals["earnings"]["annual_minor"]
    top = {part["jurisdiction"]: part["top_rate_bp"] for part in jurisdictions if part.get("status") == "verified"}
    retirement = sum(line["per_check_minor"] for line in pre_tax + post_tax + employer if line["category"] in RETIREMENT + ("employer_match",))
    hsa = sum(line["per_check_minor"] for line in pre_tax + employer if line["category"] == "hsa")
    rates = {"total_tax_bp": rounded(Decimal(totals["tax"]["annual_minor"]) * 10000 / annual_gross) if annual_gross else 0,
             "take_home_bp": rounded(Decimal(net["annual_minor"]) * 10000 / annual_gross) if annual_gross else 0,
             "federal_marginal_bp": top.get("US"), "state_marginal_bp": top.get(state) if state else None}
    result = {"year": value.year, "filing_status": value.filing_status, "filing_status_name": STATUS_NAMES[value.filing_status],
              "state": state, "state_name": jurisdiction_name(state) if state else None, "paychecks": checks, "frequency_name": FREQUENCIES[checks],
              "currency": CURRENCY, "complete": complete, "groups": groups,
              "wages": {"income_tax": {"per_check_minor": income_wages, "annual_minor": income_wages * checks + sum(item["taxable_minor"] for item in bonuses)},
                        "state": {"per_check_minor": state_wages, "annual_minor": state_wages * checks + sum(item["taxable_minor"] for item in bonuses)},
                        "fica": {"per_check_minor": fica_wages, "annual_minor": fica_wages * checks + sum(item["fica_wages_minor"] for item in bonuses)}},
              "net": net, "jurisdictions": jurisdictions, "fica": fica_rows, "schedule": schedule,
              "bonuses": [{key: item[key] for key in ("label", "month", "check", "gross_minor", "taxable_minor", "federal_minor", "state_minor", "local_minor",
                                                     "fica_minor", "match_minor", "net_minor", "retirement_minor", "hsa_minor")} for item in bonuses],
              "contributions": {"retirement_per_check_minor": retirement, "hsa_per_check_minor": hsa},
              # Each rate in basis points and as the pages' percent text (core/money.py percent_text).
              "rates": {**rates, **{key.replace("_bp", "_percent"): percent_text(bp) for key, bp in rates.items()}},
              "notes": notes}
    if not complete:
        notes.append("Net pay leaves out the taxes whose tables are missing, so it is too high until they are confirmed.")
    if recorder.live and only == "net":
        record_net(recorder, groups)
    elif recorder.live and only == "monthly":
        recorder.round(net["monthly_minor"] - record_monthly(recorder, schedule), CURRENCY, note="The year's take-home pay over twelve, rounded once.")
    return with_display(result, CURRENCY)


def from_stub(record, lines, filing_status):
    """A planner input that starts from a real pay stub: its earnings and deductions as they were printed, this period."""
    def text(amount):
        return as_decimal_text(amount, CURRENCY)

    def pay_lines(group, allowed):
        return [{"category": line["category"] if line["category"] in allowed else "other", "label": (line.get("description") or "")[:60],
                 "amount": text(line["current_minor"])}
                for line in lines if line["line_group"] == group and line["current_minor"]]
    regular = sum(line["current_minor"] or 0 for line in lines if line["line_group"] == "earnings" and line["category"] == "regular_pay")
    extra = [line for line in pay_lines("earnings", EARNING_CATEGORIES) if line["category"] != "regular_pay"]
    if not regular:
        regular = (record.get("gross_pay_minor") or 0) - sum(to_minor(line["amount"], CURRENCY) for line in extra)
    frequency = record.get("pay_frequency")
    return {"year": int(record["pay_date"][:4]) if record.get("pay_date") else None, "filing_status": filing_status,
            "work_state": record.get("work_state"), "pay_frequency": frequency if frequency in FREQUENCIES else 26,
            "gross_per_check": text(max(regular, 0)), "earnings": [line for line in extra if line["category"] != "other"]
            + [{**line, "category": "other_earnings"} for line in extra if line["category"] == "other"],
            "pre_tax": pay_lines("pre_tax", PRE_TAX_CATEGORIES), "post_tax": pay_lines("post_tax", POST_TAX_CATEGORIES),
            "employer": pay_lines("employer_paid", EMPLOYER_CATEGORIES)}
