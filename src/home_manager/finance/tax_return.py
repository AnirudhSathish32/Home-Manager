"""The year's federal return, estimated (docs/taxes.md), in Form 1040 order, plus a simplified state return.

estimate() is pure: ReturnInput (whole-year amounts in cents, gathered from records by tax_year.py and adjusted by the
user) + the year's federal table (brackets, standard deduction, Social Security and Medicare) + the year's figures
(household/tax_figures.py) -> every line with how it was worked out, and the refund or amount owed.

Correctness rules: yearly figures come from confirmed lookups or the user; amounts fixed in the law are the constants
below, each citing its section; a figure that is missing is named (in `missing` and the notes) and the line that needs
it is left as the note says, never filled with a guess. Exact integer and Decimal arithmetic, rounded half-even to the
cent; the Tax Table method is used below $100,000 of taxable income, as the Form 1040 instructions require.
"""

from decimal import ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
import json

from pydantic import BaseModel, ConfigDict, Field

from ..core.money import format_minor

CURRENCY = "USD"
# Fixed in the law (not inflation-adjusted), in cents or basis points.
SE_EARNINGS_BP = 9235  # IRC §1402(a)(12): net earnings from self-employment are 92.35% of profit.
SE_FLOOR = 40_000  # §1402(b)(2): no self-employment tax under $400 of net earnings.
NIIT_RATE_BP = 380  # §1411(a): net investment income tax.
NIIT_THRESHOLD = {"single": 20_000_000, "head_of_household": 20_000_000, "married_joint": 25_000_000}  # §1411(b)
MEDICAL_FLOOR_BP = 750  # §213(a): medical costs above 7.5% of AGI.
CAPITAL_LOSS_LIMIT = 300_000  # §1211(b): $3,000 of net capital loss against other income a year.
EARLY_PENALTY_BP = 1000  # §72(t): 10% on early retirement distributions.
HSA_PENALTY_BP = 2000  # §223(f)(4): 20% on HSA money not spent on medical care.
SS_BENEFIT_BASES = {"married_joint": (3_200_000, 1_200_000), "single": (2_500_000, 900_000), "head_of_household": (2_500_000, 900_000)}  # §86(c)
QBI_RATE_BP = 2000  # §199A(a)
CTC_PHASEOUT = {"married_joint": 40_000_000, "single": 20_000_000, "head_of_household": 20_000_000}  # §24(b)(2)
CTC_STEP, CTC_STEP_CUT = 100_000, 5_000  # §24(b)(1): $50 less for each $1,000 (or part) above the threshold.
ACTC_FLOOR, ACTC_RATE_BP = 250_000, 1500  # §24(d)(1)(B): 15% of earned income above $2,500.
DC_START, DC_STEP = 1_500_000, 200_000  # §21(a)(2): the rate falls 1 point for each $2,000 (or part) of AGI above $15,000.
AOTC_FULL, AOTC_QUARTER = 200_000, 200_000  # §25A(b)(1): 100% of the first $2,000, 25% of the next $2,000.
AOTC_REFUNDABLE_BP = 4000  # §25A(i)(5)
LLC_RATE_BP, LLC_EXPENSES = 2000, 1_000_000  # §25A(c)(1)
EDUCATION_PHASEOUT = {"married_joint": (16_000_000, 18_000_000), "single": (8_000_000, 9_000_000), "head_of_household": (8_000_000, 9_000_000)}  # §25A(d)
STUDENT_LOAN_MAX = 250_000  # §221(b)(1)
SALT_PHASEDOWN_BP, SALT_FLOOR = 3000, 1_000_000  # §164(b)(7) as amended in 2025: the limit shrinks by 30% of MAGI above the start, not below $10,000.
SENIOR_PHASEOUT = {"married_joint": 15_000_000, "single": 7_500_000, "head_of_household": 7_500_000}  # §151(f) (2025–2028)
SENIOR_PHASEOUT_BP = 600  # §151(f)(2): 6% of MAGI above the threshold.


def cents(value):
    return int(Decimal(value).to_integral_value(ROUND_HALF_EVEN))


def rate(amount, basis_points):
    return cents(Decimal(amount) * basis_points / 10000)


def bracket_tax(amount, brackets):
    """Exact tax on taxable income over the brackets (starts in cents over taxable income, rates in basis points)."""
    tax = Decimal(0)
    for index, bracket in enumerate(brackets):
        end = brackets[index + 1]["from_minor"] if index + 1 < len(brackets) else None
        piece = max(0, (min(amount, end) if end is not None else amount) - bracket["from_minor"])
        tax += Decimal(piece) * bracket["rate_bp"] / 10000
    return tax


def table_tax(amount, brackets):
    """Tax on taxable income as Form 1040 figures it: under $100,000 the Tax Table (the tax at the middle of each $50 row,
    $25 below $3,000, rounded to the dollar); from $100,000 the Tax Computation Worksheet (exact)."""
    if amount <= 0:
        return 0
    if amount >= 10_000_000:
        return cents(bracket_tax(amount, brackets))
    if amount < 500:
        return 0
    if amount < 1500:
        middle = 1000
    elif amount < 2500:
        middle = 2000
    elif amount < 300_000:
        middle = amount // 2500 * 2500 + 1250
    else:
        middle = amount // 5000 * 5000 + 2500
    dollars = (bracket_tax(middle, brackets) / 100).quantize(Decimal(1), ROUND_HALF_UP)
    return int(dollars) * 100


class Job(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    owner: str = ""
    wages: int = 0  # W-2 box 1: pay less pre-tax deductions.
    ss_wages: int = 0
    medicare_wages: int = 0
    federal_withheld: int = 0
    state_withheld: int = 0
    medicare_withheld: int = 0


class Business(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    owner: str = ""
    income: int = 0
    expenses: int = 0  # The part that counts (meals at 50%).


class Student(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expenses: int = 0
    aotc: bool = True  # One of the first four years of college, at least half-time.


class Person(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = ""
    birth_year: int | None = None


class ReturnInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    year: int
    filing_status: str
    people: list[Person] = Field(default_factory=list)
    jobs: list[Job] = Field(default_factory=list)
    interest: int = 0
    tax_exempt_interest: int = 0
    ordinary_dividends: int = 0  # 1099-DIV box 1a, qualified ones included.
    qualified_dividends: int = 0
    short_term_gain: int = 0  # Net; negative for a loss.
    long_term_gain: int = 0
    capital_loss_carryover: int = 0  # From last year, as a positive number.
    retirement_distributions: int = 0  # Taxable part.
    early_distributions: int = 0  # The part taken before 59½ with no exception.
    hsa_nonqualified: int = 0
    social_security_benefits: int = 0
    unemployment: int = 0
    other_income: int = 0
    businesses: list[Business] = Field(default_factory=list)
    educator_expenses: int = 0
    hsa_contributions: int = 0
    se_health_insurance: int = 0
    ira_deduction: int = 0
    student_loan_interest: int = 0
    other_adjustments: int = 0
    medical: int = 0
    state_local_tax: int = 0
    property_tax: int = 0
    mortgage_interest: int = 0
    charity: int = 0
    other_itemized: int = 0
    itemize: bool | None = None  # None: whichever is larger.
    other_deductions: int = 0  # Below the line, e.g. qualified tips or overtime, typed.
    qualifying_children: int = 0
    other_dependents: int = 0
    dependent_care_expenses: int = 0
    dependent_care_people: int = 0
    students: list[Student] = Field(default_factory=list)
    energy_home_expenses: int = 0
    other_credits: int = 0
    other_refundable_credits: int = 0
    other_federal_withholding: int = 0  # 1099 box 4 and the like.
    federal_estimated_paid: int = 0
    state: str | None = None
    state_deduction: int | None = None
    state_credits: int = 0
    state_estimated_paid: int = 0


def estimate(value: ReturnInput, federal, figures, state_table=None):
    """The return. federal: the year's confirmed federal tax table row (or None); figures: {key: value} that count."""
    status, lines, notes, missing = value.filing_status, [], [], []

    def line(key, label, amount, how="", section=""):
        lines.append({"key": key, "label": label, "amount_minor": amount, "how": how, "section": section})
        return amount

    def need(key, why):
        if key not in figures:
            missing.append(key)
            notes.append(why)
            return False
        return True
    if federal is None or federal.get("status") != "verified":
        return {"complete": False, "lines": [], "notes": [f"The {value.year} federal tax table isn't confirmed yet, so the return can't be estimated."],
                "missing": ["federal_table"], "result_minor": None}
    brackets = json.loads(federal["brackets_json"])
    # Income.
    line("wages", "Wages (every job's W-2 box 1)", sum(job.wages for job in value.jobs), f"{len(value.jobs)} job{'s' if len(value.jobs) != 1 else ''}", "income")
    line("interest", "Taxable interest", value.interest, section="income")
    line("dividends", "Ordinary dividends", value.ordinary_dividends, f"qualified: {format_minor(value.qualified_dividends, CURRENCY)}", "income")
    net = value.short_term_gain + value.long_term_gain - value.capital_loss_carryover
    if net >= 0:
        capital = net
        net_capital_gain = max(0, min(value.long_term_gain, net))
    else:
        capital = -min(-net, CAPITAL_LOSS_LIMIT)
        net_capital_gain = 0
        if -net > CAPITAL_LOSS_LIMIT:
            notes.append(f"{format_minor(-net - CAPITAL_LOSS_LIMIT, CURRENCY)} of capital loss carries over to next year (at most $3,000 counts a year).")
    line("capital", "Capital gain or loss", capital, "short-term + long-term − carryover; a loss counts up to $3,000", "income")
    line("distributions", "Taxable retirement distributions", value.retirement_distributions, section="income")
    profits: dict[str, int] = {}
    for business in value.businesses:
        profits.setdefault(business.owner, 0)
        profits[business.owner] += business.income - business.expenses
    schedule_c = line("business", "Business profit or loss (Schedule C)", sum(profits.values()),
                      "; ".join(f"{business.name}: {format_minor(business.income - business.expenses, CURRENCY)}" for business in value.businesses), "income")
    line("unemployment", "Unemployment", value.unemployment, section="income")
    line("hsa_nonqualified", "HSA money not spent on medical care", value.hsa_nonqualified, section="income")
    line("other_income", "Other income", value.other_income, section="income")
    before_ss = sum(item["amount_minor"] for item in lines if item["section"] == "income")
    # Self-employment tax (Schedule SE), per person: 92.35% of profit; Social Security up to the wage base less their W-2 wages.
    se_by_owner: dict[str, tuple[int, int]] = {}  # owner: (net earnings, SE tax)
    ss_rate, medicare_rate = federal.get("ss_rate_bp"), federal.get("medicare_rate_bp")
    for owner, profit in profits.items():
        earnings = rate(max(profit, 0), SE_EARNINGS_BP)
        if earnings < SE_FLOOR:
            continue
        if ss_rate is None or medicare_rate is None:
            notes.append("The federal table has no Social Security and Medicare rates, so self-employment tax is left out.")
            break
        room = max(0, (federal.get("ss_wage_base_minor") or 0) - sum(job.ss_wages for job in value.jobs if job.owner == owner))
        se_by_owner[owner] = (earnings, rate(min(earnings, room), 2 * ss_rate) + rate(earnings, 2 * medicare_rate))
    se_tax = sum(owed for _, owed in se_by_owner.values())
    se_earnings_total = sum(earnings for earnings, _ in se_by_owner.values())
    se_half = sum(cents(Decimal(owed) / 2) for _, owed in se_by_owner.values())
    # Adjustments (Schedule 1 part II).
    educator = value.educator_expenses
    if educator and need("educator_max", "The year's educator-expense limit is missing, so educator expenses aren't counted."):
        educator = min(educator, figures["educator_max"] * (2 if status == "married_joint" else 1))
    elif educator:
        educator = 0
    adjustments = {"educator": educator, "hsa": value.hsa_contributions, "se_half": se_half, "se_health": value.se_health_insurance,
                   "ira": value.ira_deduction, "other": value.other_adjustments}
    # Social Security benefits: the taxable part by the Form 1040 worksheet (§86).
    taxable_ss = 0
    if value.social_security_benefits:
        half = cents(Decimal(value.social_security_benefits) / 2)
        combined = half + before_ss + value.tax_exempt_interest - sum(adjustments.values())
        base, band = SS_BENEFIT_BASES[status]
        above = max(0, combined - base)
        over = max(0, above - band)
        taxable_ss = min(min(cents(Decimal(min(above, band)) / 2), half) + rate(over, 8500), rate(value.social_security_benefits, 8500))
    line("social_security", "Taxable Social Security benefits", taxable_ss, f"of {format_minor(value.social_security_benefits, CURRENCY)} received", "income")
    total_income = line("total_income", "Total income", before_ss + taxable_ss, section="total")
    student_loan = min(value.student_loan_interest, STUDENT_LOAN_MAX)
    if student_loan:
        modified = total_income - sum(adjustments.values())
        if need("student_loan_phaseout_start", "The year's student-loan interest phase-out is missing, so the deduction isn't reduced for income.") and "student_loan_phaseout_end" in figures:
            start, end = figures["student_loan_phaseout_start"], figures["student_loan_phaseout_end"]
            if modified >= end:
                student_loan = 0
            elif modified > start:
                student_loan = cents(Decimal(student_loan) * (end - modified) / (end - start))
    adjustments["student_loan"] = student_loan
    for key, label in (("educator", "Educator expenses"), ("hsa", "HSA contributions (not through payroll)"), ("se_half", "Half of self-employment tax"),
                       ("se_health", "Self-employed health insurance"), ("ira", "Traditional IRA deduction"), ("student_loan", "Student-loan interest"),
                       ("other", "Other adjustments")):
        if adjustments[key]:
            line(f"adjust_{key}", label, -adjustments[key], section="adjustments")
    agi = line("agi", "Adjusted gross income (AGI)", total_income - sum(adjustments.values()), section="total")
    # Deduction: the standard deduction (plus for 65 or older) or itemized, whichever is larger unless you choose.
    older = [person for person in value.people if person.birth_year and value.year - person.birth_year >= 65]
    standard = federal["standard_deduction_minor"]
    if older and need("additional_standard_65", "The year's additional standard deduction for 65 or older is missing, so it isn't added."):
        standard += figures["additional_standard_65"] * len(older)
    medical = max(0, value.medical - rate(agi, MEDICAL_FLOOR_BP))
    salt = value.state_local_tax + value.property_tax
    if salt and need("salt_cap", "The year's SALT limit is missing, so state and local taxes are counted without it."):
        cap = figures["salt_cap"]
        if "salt_phaseout_start" in figures:
            cap = max(SALT_FLOOR, cap - rate(max(0, agi - figures["salt_phaseout_start"]), SALT_PHASEDOWN_BP))
        salt = min(salt, cap)
    itemized = medical + salt + value.mortgage_interest + value.charity + value.other_itemized
    use_itemized = value.itemize if value.itemize is not None else itemized > standard
    deduction = itemized if use_itemized else standard
    line("deduction", "Itemized deductions" if use_itemized else "Standard deduction", -deduction,
         f"itemized {format_minor(itemized, CURRENCY)} (medical above 7.5% of AGI {format_minor(medical, CURRENCY)}, state and local taxes "
         f"{format_minor(salt, CURRENCY)}) against standard {format_minor(standard, CURRENCY)}", "deductions")
    senior = 0
    if older and "senior_deduction" in figures:
        senior = max(0, figures["senior_deduction"] * len(older) - rate(max(0, agi - SENIOR_PHASEOUT[status]), SENIOR_PHASEOUT_BP) * len(older))
        if senior:
            line("senior", "Senior deduction", -senior, section="deductions")
    if value.other_deductions:
        line("other_deductions", "Other deductions", -value.other_deductions, section="deductions")
    before_qbi = max(0, agi - deduction - senior - value.other_deductions)
    qbi = 0
    qualified_business = max(0, schedule_c - se_half - value.se_health_insurance)
    if qualified_business and need("qbi_threshold", "The year's qualified business income threshold is missing, so that deduction is left out."):
        if before_qbi <= figures["qbi_threshold"]:
            qbi = min(rate(qualified_business, QBI_RATE_BP), rate(max(0, before_qbi - net_capital_gain - value.qualified_dividends), QBI_RATE_BP))
            line("qbi", "Qualified business income deduction", -qbi, "20% of business profit, limited by taxable income", "deductions")
        else:
            notes.append("Taxable income is above the qualified business income threshold, where wage and property limits apply; the deduction is left out.")
    taxable = line("taxable_income", "Taxable income", max(0, before_qbi - qbi), section="total")
    # Tax: ordinary rates, with qualified dividends and long-term gains at 0/15/20% (Qualified Dividends and Capital Gain Tax Worksheet).
    preferred = min(taxable, value.qualified_dividends + net_capital_gain)
    if preferred and need("cg_zero_max", "The year's capital-gains thresholds are missing, so gains and qualified dividends are taxed as ordinary income.") \
            and need("cg_fifteen_max", "The year's 15% capital-gains threshold is missing, so gains and qualified dividends are taxed as ordinary income."):
        ordinary = taxable - preferred
        at_zero = max(0, min(taxable, figures["cg_zero_max"]) - ordinary)
        at_zero = min(at_zero, preferred)
        rest = preferred - at_zero
        at_fifteen = min(rest, max(0, min(taxable, figures["cg_fifteen_max"]) - ordinary - at_zero))
        at_twenty = rest - at_fifteen
        worksheet = rate(at_fifteen, 1500) + rate(at_twenty, 2000) + table_tax(ordinary, brackets)
        tax = min(worksheet, table_tax(taxable, brackets))
        how = (f"ordinary {format_minor(ordinary, CURRENCY)} on the brackets; {format_minor(at_zero, CURRENCY)} at 0%, {format_minor(at_fifteen, CURRENCY)} at 15%, "
               f"{format_minor(at_twenty, CURRENCY)} at 20%")
    else:
        tax = table_tax(taxable, brackets)
        how = "the Tax Table" if taxable < 10_000_000 else "the Tax Computation Worksheet"
    line("tax", "Tax", tax, how, "tax")
    # Nonrefundable credits, in the order the credit limit worksheets take them: dependent care, education, energy, other; then the child tax credit.
    room = tax
    earned: dict[str, int] = {}
    for job in value.jobs:
        earned[job.owner] = earned.get(job.owner, 0) + job.wages
    for owner, (earnings, owed) in se_by_owner.items():  # Earned income from self-employment: net earnings less half the SE tax.
        earned[owner] = earned.get(owner, 0) + earnings - cents(Decimal(owed) / 2)
    earned_total = sum(earned.values())
    credits = {}
    if value.dependent_care_expenses and value.dependent_care_people:
        limit_key = "dc_limit_one" if value.dependent_care_people == 1 else "dc_limit_two"
        if need(limit_key, "The year's dependent care expense limit is missing, so that credit is left out.") \
                and need("dc_rate_high", "The year's dependent care credit rates are missing, so that credit is left out.") and "dc_rate_low" in figures:
            lowest = min(earned.values()) if status == "married_joint" and len(earned) > 1 else earned_total
            counted = min(value.dependent_care_expenses, figures[limit_key], max(lowest, 0))
            steps = int((Decimal(max(0, agi - DC_START)) / DC_STEP).to_integral_value(ROUND_CEILING))
            credit_rate = max(figures["dc_rate_low"], figures["dc_rate_high"] - steps * 100)
            credits["dependent_care"] = rate(counted, credit_rate)
    aotc_refundable = 0
    if value.students:
        start, end = EDUCATION_PHASEOUT[status]
        share = Decimal(1) if agi <= start else Decimal(0) if agi >= end else Decimal(end - agi) / (end - start)
        aotc = sum(min(student.expenses, AOTC_FULL) + rate(min(max(0, student.expenses - AOTC_FULL), AOTC_QUARTER), 2500) for student in value.students if student.aotc)
        llc = rate(min(sum(student.expenses for student in value.students if not student.aotc), LLC_EXPENSES), LLC_RATE_BP)
        aotc, llc = cents(aotc * share), cents(llc * share)
        aotc_refundable = rate(aotc, AOTC_REFUNDABLE_BP)
        credits["education"] = aotc - aotc_refundable + llc
    if value.energy_home_expenses and need("energy_home_rate", "The year's energy home improvement credit isn't found for this year, so it is left out.") \
            and need("energy_home_cap", "The year's energy home improvement credit limit is missing, so that credit is left out."):
        credits["energy"] = min(rate(value.energy_home_expenses, figures["energy_home_rate"]), figures["energy_home_cap"])
    if value.other_credits:
        credits["other"] = value.other_credits
    used = {}
    for key in ("dependent_care", "education", "energy", "other"):
        if key in credits:
            used[key] = min(credits[key], room)
            room -= used[key]
    child_credit = actc = 0
    if value.qualifying_children or value.other_dependents:
        if (not value.qualifying_children or need("ctc_per_child", "The year's child tax credit amount is missing, so that credit is left out.")) \
                and (not value.other_dependents or need("odc_per_dependent", "The year's credit for other dependents is missing, so it is left out.")):
            full = value.qualifying_children * figures.get("ctc_per_child", 0) + value.other_dependents * figures.get("odc_per_dependent", 0)
            cut = int((Decimal(max(0, agi - CTC_PHASEOUT[status])) / CTC_STEP).to_integral_value(ROUND_CEILING)) * CTC_STEP_CUT
            allowed = max(0, full - cut)
            child_credit = min(allowed, room)
            room -= child_credit
            child_part = max(0, min(allowed, value.qualifying_children * figures.get("ctc_per_child", 0)) - child_credit)
            if child_part and need("ctc_refundable_max", "The year's refundable child tax credit limit is missing, so its refundable part is left out."):
                actc = min(child_part, value.qualifying_children * figures["ctc_refundable_max"], rate(max(0, earned_total - ACTC_FLOOR), ACTC_RATE_BP))
    for key, label in (("dependent_care", "Child and dependent care credit"), ("education", "Education credits (nonrefundable part)"),
                       ("energy", "Energy efficient home improvement credit"), ("other", "Other credits")):
        if used.get(key):
            line(f"credit_{key}", label, -used[key], section="credits")
    if child_credit:
        line("credit_child", "Child tax credit and credit for other dependents", -child_credit, section="credits")
    income_tax = tax - sum(used.values()) - child_credit
    # Other taxes (Schedule 2).
    other = {}
    if se_tax:
        other["se"] = se_tax
    medicare_wages = sum(job.medicare_wages for job in value.jobs)
    threshold, extra = federal.get("additional_medicare_threshold_minor"), federal.get("additional_medicare_rate_bp")
    if threshold is not None and extra:
        other["additional_medicare"] = rate(max(0, medicare_wages + se_earnings_total - threshold), extra)
    investment = value.interest + value.ordinary_dividends + max(0, capital)
    other["niit"] = rate(min(investment, max(0, agi - NIIT_THRESHOLD[status])), NIIT_RATE_BP)
    other["early"] = rate(value.early_distributions, EARLY_PENALTY_BP)
    other["hsa"] = rate(value.hsa_nonqualified, HSA_PENALTY_BP)
    for key, label in (("se", "Self-employment tax"), ("additional_medicare", "Additional Medicare tax"), ("niit", "Net investment income tax"),
                       ("early", "10% tax on early retirement distributions"), ("hsa", "20% tax on HSA money not spent on medical care")):
        if other.get(key):
            line(f"other_{key}", label, other[key], section="other_taxes")
    total_tax = line("total_tax", "Total tax", income_tax + sum(other.values()), section="total")
    # Payments and refundable credits.
    withheld = sum(job.federal_withheld for job in value.jobs)
    extra_medicare_withheld = sum(max(0, job.medicare_withheld - rate(job.medicare_wages, medicare_rate or 0)) for job in value.jobs) if medicare_rate else 0
    payments = {"withheld": withheld + value.other_federal_withholding, "additional_medicare": extra_medicare_withheld, "estimated": value.federal_estimated_paid,
                "actc": actc, "aotc": aotc_refundable, "other": value.other_refundable_credits}
    for key, label in (("withheld", "Federal income tax withheld"), ("additional_medicare", "Additional Medicare tax withheld"),
                       ("estimated", "Estimated tax paid"), ("actc", "Additional child tax credit"), ("aotc", "American opportunity credit (refundable part)"),
                       ("other", "Other refundable credits")):
        if payments[key]:
            line(f"pay_{key}", label, payments[key], section="payments")
    paid = line("total_payments", "Total payments", sum(payments.values()), section="total")
    result = paid - total_tax
    notes += ["Business meals count at 50%; charitable gifts and mortgage interest are counted without their AGI and loan limits.",
              "Not modelled: the alternative minimum tax, the qualified business income deduction above its threshold, IRA deductibility limits "
              "(enter the deductible part), and credits not listed here."]
    state = state_return(value, agi, state_table)
    return {"complete": not missing, "year": value.year, "filing_status": status, "lines": [{**item, "display": format_minor(item["amount_minor"], CURRENCY)} for item in lines],
            "agi_minor": agi, "taxable_minor": taxable, "tax_minor": tax, "total_tax_minor": total_tax, "payments_minor": paid,
            "withheld_minor": payments["withheld"] + payments["additional_medicare"], "estimated_minor": value.federal_estimated_paid,
            "refundable_credits_minor": actc + aotc_refundable + value.other_refundable_credits,
            "result_minor": result, "result": {"refund": result > 0, "display": format_minor(abs(result), CURRENCY)},
            "marginal_bp": marginal(taxable, brackets), "missing": sorted(set(missing)), "notes": notes, "state": state}


def marginal(taxable, brackets):
    """The ordinary rate on the next dollar of taxable income."""
    found = brackets[0]["rate_bp"]
    for bracket in brackets:
        if taxable >= bracket["from_minor"]:
            found = bracket["rate_bp"]
    return found


def state_return(value: ReturnInput, agi, table):
    """A simplified state return: AGI less the state's deduction, the state's brackets, less its credits, against state
    withholding and estimated payments. State rules differ from federal in many ways; this is labelled simplified."""
    withheld = sum(job.state_withheld for job in value.jobs)
    if not value.state:
        return None
    if table is None or table.get("status") != "verified":
        return {"state": value.state, "complete": False, "withheld_minor": withheld, "note": "The state's tax table isn't confirmed, so its return isn't estimated."}
    deduction = value.state_deduction if value.state_deduction is not None else table["standard_deduction_minor"]
    taxable = max(0, agi - deduction)
    tax = max(0, cents(bracket_tax(taxable, json.loads(table["brackets_json"]))) - value.state_credits)
    paid = withheld + value.state_estimated_paid
    return {"state": value.state, "complete": True, "taxable_minor": taxable, "tax_minor": tax, "withheld_minor": withheld, "estimated_minor": value.state_estimated_paid,
            "payments_minor": paid, "result_minor": paid - tax,
            "display": {key: format_minor(amount, CURRENCY) for key, amount in (("taxable_minor", taxable), ("tax_minor", tax), ("payments_minor", paid),
                                                                                  ("result_minor", abs(paid - tax)))},
            "note": "Simplified: federal AGI less the state's deduction, on the state's brackets, less the credits you entered."}
