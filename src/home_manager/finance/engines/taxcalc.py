"""PSLmodels Tax-Calculator (docs/tax-engines.md): the federal return from a public-domain (CC0) model of federal income
and payroll tax that tax economists maintain, run in a separate Python process (engines/taxcalc_run.py).

It is installed as an optional extra (`pip install "home-manager[engine2]"`, pinned in pyproject.toml); without it the
app runs as before and Settings says Engine 2 isn't installed. Each run sends the profile as one Tax-Calculator record
and reads back its totals: AGI, the deduction, taxable income, tax, credits and other taxes. Payments are added up by
the app, as for every engine (tax_engine.completed).

Tax-Calculator models tax totals, not forms. Where the forms work something its model takes as given, this file works
it from the law and says so in the notes:
- the Tax Table: below $100,000 of taxable income the tax is the Tax Table's (the rate schedule on the middle of the
  table's $25 or $50 row, rounded to the dollar), from the year's rate schedule as Tax-Calculator has it. With
  qualified dividends or long-term gains the worksheet's own Tax Table steps aren't redone: that tax may differ by a
  few dollars and is compared with that leeway;
- the mortgage interest limit (IRC §163(h)(3)(F), Pub 936): interest × $750,000 ÷ the average balance when it's higher;
- the HSA deduction: the contributions up to the year's §223(b) limit for the coverage;
- the American opportunity credit's tentative amount per student (§25A(b)): 100% of the first $2,000 and 25% of the next.
Like Engine 1 it asks rather than guesses: a fact it needs that wasn't entered is named (tax_engine.NEEDS ids). With no
birth year it takes the same documented default (not 65 or older), and asks when the earned income credit turns on age.

The app shows this engine as its slot ("Engine 2"); its name stays in this file, the records and docs/tax-engines.md.
"""

from collections import OrderedDict
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
import hashlib
from importlib import metadata, util
import json
from pathlib import Path
import subprocess
import sys

from ..tax_engine import NEEDS, STATUSES, Capabilities, completed
from ..tax_return import ReturnInput, rate

PACKAGE = "taxcalc"
PINNED = "6.8.4"  # pyproject.toml's engine2 extra; tested against this release.
YEARS = frozenset({2025, 2026})  # The pinned release's known law (Policy.LAST_KNOWN_YEAR 2026); later years would be projections.
MARS = {"single": 1, "married_joint": 2, "head_of_household": 4}
RUNNER = Path(__file__).with_name("taxcalc_run.py")
TIMEOUT = 120  # The first run on a computer compiles the model (numba); later ones take a second or two.
CACHE_SIZE = 32
TABLE_BELOW = Decimal(100_000)  # Form 1040 instructions: the Tax Table below $100,000 of taxable income.
MORTGAGE_LIMIT = 75_000_000  # IRC §163(h)(3)(F): acquisition debt after Dec 15, 2017, in cents.
UNKNOWN_AGE = 40  # With no birth year: between 25 and 64, where no age rule applies (the earned income credit asks, below).
AOTC_FULL, AOTC_QUARTER = 200_000, 200_000  # §25A(b)(1): 100% of the first $2,000 and 25% of the next $2,000.
# The lines it works out (tax_engine.compare leaves the others out): not the SEP deduction, saver's credit or premium credit.
REPORTS = frozenset({
    "wages", "interest", "dividends", "capital", "distributions", "business", "unemployment", "hsa_nonqualified", "other_income", "social_security",
    "income_engine", "total_income", "adjust_se_half", "adjust_hsa", "adjust_se_health", "adjust_ira", "adjust_other", "adjust_student_loan", "agi",
    "deduction", "charity_nonitemizer", "senior", "other_deductions", "qbi", "taxable_income", "tax", "amt", "credit_dependent_care",
    "credit_education", "credit_child", "credit_other", "other_se", "other_additional_medicare", "other_niit", "other_other", "total_tax",
    "pay_withheld", "pay_additional_medicare", "pay_estimated", "pay_eitc", "pay_actc", "pay_aotc", "pay_other", "total_payments"})
_cache: OrderedDict = OrderedDict()


class EngineFailed(Exception):
    pass


def installed():
    """The installed release, or None."""
    if util.find_spec(PACKAGE) is None:
        return None
    try:
        return metadata.version(PACKAGE)
    except metadata.PackageNotFoundError:
        return None


def law_sha256():
    """The SHA-256 of the installed release's law file (policy_current_law.json), kept with each calculation."""
    spec = util.find_spec(PACKAGE)
    if spec is None or not spec.origin:
        return None
    path = Path(spec.origin).with_name("policy_current_law.json")
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def cents(dollars):
    """Tax-Calculator's dollars (a float) as exact cents."""
    return int((Decimal(str(dollars)) * 100).to_integral_value(ROUND_HALF_EVEN))


def dollars(minor):
    return float(Decimal(minor) / 100)


def aotc_tentative(expenses):
    """§25A(b)(1) for one student, in cents: 100% of the first $2,000 of expenses and 25% of the next $2,000."""
    return min(expenses, AOTC_FULL) + min(max(expenses - AOTC_FULL, 0), AOTC_QUARTER) // 4


def hsa_deduction(value: ReturnInput, age):
    """Contributions outside payroll up to the year's §223(b) limit for the coverage (tax_year.HSA_LIMITS), $1,000 more from 55."""
    from ..tax_year import HSA_CATCH_UP, HSA_LIMITS
    if not value.hsa_contributions or value.hsa_coverage is None or value.year not in HSA_LIMITS:
        return value.hsa_contributions
    self_only, family = HSA_LIMITS[value.year]
    limit = (self_only if value.hsa_coverage == "self" else family) + (HSA_CATCH_UP if age is not None and age >= 55 else 0)
    return min(value.hsa_contributions, limit)


def deductible_mortgage_interest(value: ReturnInput):
    """Pub 936 Table 1: the interest × $750,000 ÷ the average balance, when the balance is over the limit."""
    balance = value.mortgage_average_balance
    if not value.mortgage_interest or not balance or balance <= MORTGAGE_LIMIT:
        return value.mortgage_interest
    return int((Decimal(value.mortgage_interest) * MORTGAGE_LIMIT / balance).to_integral_value(ROUND_HALF_EVEN))


def needed(value: ReturnInput):
    """Facts this engine needs that weren't entered (tax_engine.NEEDS ids)."""
    wanted = []
    if value.mortgage_interest and value.mortgage_average_balance is None:
        wanted.append("mortgageAverageBalance")
    if value.hsa_contributions and value.hsa_coverage is None:
        wanted.append("hsaCoverage")
    if value.qualified_tips and not value.tipped_occupation:
        wanted.append("occupation")
    return wanted


def record_for(value: ReturnInput):
    """One Tax-Calculator record for this profile (dollars), and notes on how it was mapped. docs/tax-engines.md has the table."""
    joint = value.filing_status == "married_joint"
    notes = []
    whose = lambda owner: "s" if joint and owner == "spouse" else "p"
    ages = [value.year - person.birth_year if person.birth_year else None for person in value.people[:2]]
    ages += [None] * (2 - len(ages))
    if ages[0] is None or (joint and ages[1] is None):  # As Engine 1's documented default: not 65 or older.
        notes.append("With no birth year, you're taken to be 25 to 64 (no senior deduction or extra standard deduction for age).")
    record: dict = {"RECID": 1, "FLPDYR": value.year, "MARS": MARS[value.filing_status], "age_head": ages[0] or UNKNOWN_AGE,
                    "age_spouse": (ages[1] or UNKNOWN_AGE) if joint else 0}
    sums = {key: 0 for key in ("e00200p", "e00200s", "pencon_p", "pencon_s", "e00900p", "e00900s")}
    for job in value.jobs:
        sums[f"e00200{whose(job.owner)}"] += job.wages
        # Medicare wages above box 1 are the 401(k)-type deferrals: Tax-Calculator adds them back for payroll tax.
        sums[f"pencon_{whose(job.owner)}"] += max(0, job.medicare_wages - job.wages)
    for business in value.businesses:
        sums[f"e00900{whose(business.owner)}"] += business.income - business.expenses
    record |= {key: dollars(amount) for key, amount in sums.items()}
    record["e00200"], record["e00900"] = record["e00200p"] + record["e00200s"], record["e00900p"] + record["e00900s"]
    filers = 2 if joint else 1
    record |= {"XTOT": filers + value.qualifying_children + value.other_dependents, "n24": value.qualifying_children,
               "nu18": value.qualifying_children, "EIC": min(value.qualifying_children, 3), "f2441": value.dependent_care_people}
    if value.qualifying_children:
        notes.append("Children under 17 for the child tax credit are counted as earned income credit children too.")
    short = value.short_term_gain - value.capital_loss_carryover
    if value.capital_loss_carryover:
        notes.append("Last year's capital loss carryover comes off short-term gains first (it isn't split short and long term here).")
    qualified = min(value.qualified_dividends, value.ordinary_dividends) if value.ordinary_dividends else value.qualified_dividends
    age = ages[0]
    money = {"e00300": value.interest, "e00400": value.tax_exempt_interest, "e00600": max(value.ordinary_dividends, qualified), "e00650": qualified,
             "p22250": short, "p23250": value.long_term_gain, "e01500": value.retirement_distributions, "e01700": value.retirement_distributions,
             "e02400": value.social_security_benefits, "e02300": value.unemployment,
             # Other income and HSA money not spent on medical care are ordinary income no other rule treats specially.
             "e00700": value.other_income + value.hsa_nonqualified,
             # §72(t) 10% on early distributions and §223(f)(4) 20% on HSA money not spent on medical care.
             "e09900": rate(value.early_distributions, 1000) + rate(value.hsa_nonqualified, 2000),
             "e03220": value.educator_expenses, "e03290": hsa_deduction(value, age), "e03270": value.se_health_insurance,
             "e03150": value.ira_deduction, "e03210": value.student_loan_interest, "e03400": value.other_adjustments,
             "e17500": value.medical, "e18400": value.state_local_tax, "e18500": value.property_tax, "e19200": deductible_mortgage_interest(value),
             "e19800": value.charity, "e20100": value.charity_noncash, "e32800": value.dependent_care_expenses,
             "e87521": sum(aotc_tentative(student.expenses) for student in value.students if student.aotc and student.expenses),
             "e87530": sum(student.expenses for student in value.students if not student.aotc), "p08000": value.other_credits,
             "tip_income": value.qualified_tips, "overtime_income": value.qualified_overtime}
    record |= {key: dollars(amount) for key, amount in money.items()}
    if value.mortgage_interest and money["e19200"] != value.mortgage_interest:
        notes.append("Mortgage interest is limited to the share of a $750,000 average balance (Pub 936).")
    if value.hsa_contributions and money["e03290"] != value.hsa_contributions:
        notes.append("HSA contributions count up to the year's limit for the coverage.")
    if value.ira_deduction:
        notes.append("Traditional IRA: the deductible part you entered counts as is (the workplace-plan phase-out isn't applied again).")
    return record, notes


def evaluate(record, year):
    """The runner's JSON answer for this record and year (cached by both)."""
    key = hashlib.sha256(json.dumps([record, year], sort_keys=True).encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    try:
        done = subprocess.run([sys.executable, "-I", str(RUNNER)], input=json.dumps({"year": year, "record": record}).encode(), capture_output=True,
                              timeout=TIMEOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
    except subprocess.TimeoutExpired as exc:
        raise EngineFailed(f"didn't answer within {TIMEOUT} seconds.") from exc
    except OSError as exc:
        raise EngineFailed(f"couldn't start: {exc}.") from exc
    try:
        answer = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        raise EngineFailed(f"gave no answer (exit {done.returncode}: {detail[0][:200]}).") from exc
    if answer.get("ok"):
        _cache[key] = answer
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return answer


def schedule(amount: Decimal, policy):
    """Tax on taxable income (dollars) over the year's rate schedule for this filing status."""
    tax, start = Decimal(0), Decimal(0)
    for number in range(1, 8):
        end = Decimal(str(policy[f"II_brk{number}"])) if number < 7 else None
        rate = Decimal(str(policy[f"II_rt{number}"]))
        if end is None or amount <= end:
            return tax + (amount - start) * rate
        tax, start = tax + (end - start) * rate, end
    return tax


def table_tax(taxable_minor, policy):
    """The Tax Table's tax (cents) below $100,000: the rate schedule on the middle of the income's row ($0–5, $5–15, $15–25,
    then $25 rows to $3,000 and $50 rows above), rounded to the whole dollar. None at $100,000 or more."""
    amount = Decimal(max(taxable_minor, 0)) / 100
    if amount >= TABLE_BELOW:
        return None
    if amount < 25:
        middle = Decimal("2.5") if amount < 5 else Decimal(10) if amount < 15 else Decimal(20)
    else:
        width = 25 if amount < 3000 else 50
        middle = (amount // width) * width + Decimal(width) / 2
    return int(schedule(middle, policy).to_integral_value(ROUND_HALF_UP)) * 100


class TaxCalculatorEngine:
    name = "taxcalc"  # For the records only: the page shows the slot's label (finance/tax_engine.py).

    def version(self):
        return {"name": self.name, "version": installed() or PINNED, "pinned": PINNED, "pin_sha256": law_sha256()}

    def readiness(self):
        """None when the engine can run here, else why not (the start of a sentence after its label)."""
        found = installed()
        if found is None:
            return 'isn\'t installed. To add it, run: pip install "home-manager[engine2]"'
        if found != PINNED:
            return f'is version {found}; this app is checked with {PINNED}. Run: pip install "home-manager[engine2]"'
        return None

    def capabilities(self):
        # FEATURES (finance/tax_engine.py) it covers beyond Engine 1: each spouse's Schedule SE, any number of AOTC
        # students, and other nonrefundable credits typed in.
        return Capabilities(years=YEARS, statuses=STATUSES, features=frozenset({"two_self_employed", "many_aotc_students", "other_credits"}),
                            states=frozenset())

    def empty(self, value, notes, needs=(), unsupported=()):
        return {"complete": False, "year": value.year, "filing_status": value.filing_status, "lines": [], "notes": notes, "missing": [],
                "needs": list(needs), "unsupported": list(unsupported), "result_minor": None, "state": None, "reports": sorted(REPORTS)}

    def calculate(self, value: ReturnInput, context, label="The tax engine"):
        problem = self.readiness()
        if problem:
            return self.empty(value, [f"{label} {problem}"])
        wanted = needed(value)
        if wanted:
            return self.empty(value, ["To work out the return, enter " + "; ".join(dict.fromkeys(NEEDS[fact] for fact in wanted)) + "."], needs=wanted)
        if value.other_itemized:
            return self.empty(value, [f"{label} doesn't cover other itemized deductions typed in."], unsupported=["engine:other_itemized"])
        record, notes = record_for(value)
        try:
            answer = evaluate(record, value.year)
        except EngineFailed as exc:
            return self.empty(value, [f"{label} {exc}"])
        if not answer.get("ok"):
            if answer.get("code") == "YEAR":
                return self.empty(value, [f"{label} works out {', '.join(str(year) for year in sorted(YEARS))} returns, not {value.year}."],
                                  unsupported=[f"year:{value.year}"])
            return self.empty(value, [f"{label} couldn't work out this return ({answer.get('message', answer.get('code', ''))[:200]})."],
                              unsupported=[f"engine:{answer.get('code', 'FAILED')}"])
        found = {name: cents(amount) for name, amount in answer["values"].items()}
        if found["eitc"] and not (value.people and value.people[0].birth_year):  # The credit turns on age (25 to 64 without children).
            return self.empty(value, ["To work out the return, enter " + NEEDS["isAtLeastAge25"] + "."], needs=["isAtLeastAge25"])
        itemizing = found["c04470"] > 0
        if value.itemize and not itemizing:
            return self.empty(value, [f"{label} doesn't cover itemizing when the standard deduction is larger."], unsupported=["engine:force_itemize"])
        return self.shaped(value, found, answer, record, context, notes, label)

    def shaped(self, value: ReturnInput, found, answer, record, context, notes, slot_label):
        policy = answer["policy"]
        lines: list[dict] = []

        def line(key, label, amount, explained="", section="", within=0):
            lines.append({"key": key, "label": label, "amount_minor": amount, "how": explained, "section": section, **({"within": within} if within else {})})
            return amount
        # Income: what was sent, with the model's capital gain or loss and taxable Social Security.
        line("wages", "Wages (every job's W-2 box 1)", sum(job.wages for job in value.jobs), f"{len(value.jobs)} job{'s' if len(value.jobs) != 1 else ''}", "income")
        line("interest", "Taxable interest", value.interest, section="income")
        line("dividends", "Ordinary dividends", value.ordinary_dividends, section="income")
        line("capital", "Capital gain or loss", found["c01000"], "Schedule D netting; a loss counts up to $3,000", "income")
        line("distributions", "Taxable retirement distributions", value.retirement_distributions, section="income")
        line("business", "Business profit or loss (Schedule C)", sum(business.income - business.expenses for business in value.businesses), section="income")
        line("unemployment", "Unemployment", value.unemployment, section="income")
        line("hsa_nonqualified", "HSA money not spent on medical care", value.hsa_nonqualified, section="income")
        line("other_income", "Other income", value.other_income, section="income")
        line("social_security", "Taxable Social Security benefits", found["c02500"], "the taxable share of benefits (IRC §86)", "income")
        agi, adjustments = found["c00100"], found["c02900"]
        total_income = agi + adjustments
        counted = sum(item["amount_minor"] for item in lines if item["section"] == "income")
        if counted != total_income:
            line("income_engine", "Other income as the engine counts it", total_income - counted, "the engine's total income less the lines above", "income")
        line("total_income", "Total income", total_income, section="total")
        listed = 0
        for key, amount, label in (("se_half", found["c03260"], "Half of self-employment tax"), ("hsa", cents(record["e03290"]), "HSA contributions (not through payroll)"),
                                   ("se_health", value.se_health_insurance, "Self-employed health insurance"), ("ira", value.ira_deduction, "Traditional IRA deduction")):
            if amount:
                listed += line(f"adjust_{key}", label, -amount, section="adjustments") * -1
        student_loan = min(value.student_loan_interest, max(adjustments - listed, 0))
        if adjustments - listed - student_loan:
            line("adjust_other", "Educator expenses and other adjustments", -(adjustments - listed - student_loan), section="adjustments")
        if student_loan:
            line("adjust_student_loan", "Student-loan interest", -student_loan, section="adjustments")
        line("agi", "Adjusted gross income (AGI)", agi, section="total")
        # Deduction: the model's standard deduction includes the non-itemizer's charitable deduction; it's shown apart.
        standard, itemized = found["standard"], found["c04470"]
        charity = 0 if itemized else min(value.charity, cents(policy["STD_charity_ded_nonitemizers_max"]), standard)
        line("deduction", "Itemized deductions" if itemized else "Standard deduction", -(itemized or standard - charity),
             "itemized, after limits" if itemized else "standard, with any extra for age", "deductions")
        if charity:
            line("charity_nonitemizer", "Charitable deduction (not itemizing)", -charity, "cash gifts, up to the year's limit", "deductions")
        if found["senior_deduction"]:
            line("senior", "Senior deduction", -found["senior_deduction"], "65 or older, phased out above the income limit", "deductions")
        other = found["tip_income_deduction"] + found["overtime_income_deduction"] + found["auto_loan_interest_deduction"]
        if other:
            line("other_deductions", "Tips, overtime and car-loan interest deductions", -other, "each up to its limit, phased out above the income limit", "deductions")
        if found["qbided"]:
            line("qbi", "Qualified business income deduction", -found["qbided"], section="deductions")
        taxable = line("taxable_income", "Taxable income", found["c04800"], section="total")
        # Tax: the Tax Table below $100,000 (redone here when there's no preferential income), else the model's.
        preferential = value.qualified_dividends > 0 or (value.long_term_gain > 0 and value.long_term_gain + min(value.short_term_gain - value.capital_loss_carryover, 0) > 0)
        table = None if preferential else table_tax(taxable, policy)
        tax = table if table is not None else found["taxbc"]
        leeway = 2500 * 22 // 100 + 100 if preferential and taxable < int(TABLE_BELOW) * 100 else 0  # 22% of half a $50 row, plus a dollar.
        if leeway:
            notes.append("With qualified dividends or long-term gains below $100,000 of taxable income, the tax is worked from the rate schedule, "
                         "not the Tax Table's rows: it can differ by a few dollars.")
        line("tax", "Tax", tax, "the Tax Table" if table is not None else "the rate schedules and the capital gains worksheet", "tax", leeway)
        if found["c09600"]:
            line("amt", "Alternative minimum tax", found["c09600"], section="tax")
        credits = found["c07100"]
        credited = 0
        for key, amount, label in (("dependent_care", found["c07180"], "Child and dependent care credit"), ("education", found["c07230"], "Education credits (nonrefundable part)"),
                                   ("child", found["c07220"] + found["odc"], "Child tax credit and credit for other dependents")):
            if amount:
                credited += line(f"credit_{key}", label, -amount, section="credits") * -1
        if credits - credited:
            line("credit_other", "Other credits", -(credits - credited), "other credits typed in", "credits")
        other_taxes = found["othertaxes"]
        listed = 0
        for key, amount, label in (("se", found["setax"], "Self-employment tax"), ("additional_medicare", found["ptax_amc"], "Additional Medicare tax"),
                                   ("niit", found["niit"], "Net investment income tax")):
            if amount:
                listed += line(f"other_{key}", label, amount, section="other_taxes")
        if other_taxes - listed:
            line("other_other", "Other taxes", other_taxes - listed, "10% on early distributions, 20% on HSA money", "other_taxes")
        # Nonrefundable credits can't exceed the tax: with the Tax Table's tax they're used against it the same way.
        after = max(0, tax + found["c09600"] - credits)
        total_tax = line("total_tax", "Total tax", after + other_taxes, section="total", within=leeway)
        refundable = found["refund"]
        refundable_lines = [("eitc", "Earned income credit", found["eitc"], ""), ("actc", "Additional child tax credit", found["c11070"], ""),
                            ("aotc", "American opportunity credit (refundable part)", found["c10960"], "")]
        notes.append(f"Worked out by {slot_label} from the {value.year} law as published.")
        result = completed(value, lines, agi=agi, taxable=taxable, tax=tax, total_tax=total_tax, refundable=refundable, refundable_lines=refundable_lines,
                           context=context, notes=notes, slot_label=slot_label, raw={"record": record, "values": answer["values"], "policy": policy})
        result["reports"] = sorted(REPORTS)
        return result
