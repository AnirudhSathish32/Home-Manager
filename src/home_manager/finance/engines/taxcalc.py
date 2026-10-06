"""PSLmodels Tax-Calculator (docs/taxes.md "The tax engines"): the federal return from a public-domain (CC0) model of federal income
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

The app shows this engine as its slot ("Engine 2"); its name stays in this file, the records and docs/taxes.md "The tax engines".
"""

import ast
from collections import OrderedDict
from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal
import hashlib
from importlib import metadata, util
import json
from pathlib import Path
import subprocess
import sys

from .. import worksheet
from ..tax_engine import NEEDS, STATUSES, Capabilities, Lines, completed
from ..tax_return import ReturnInput, bracket_tax, rate

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


# Where each record input comes from in the return's inputs ([field, sign]): the worksheet's `fact` source
# (finance/worksheet.py). The per-person ones (…p, …s) are filled in by record_for.
SOURCES = {"MARS": ["filing_status"], "XTOT": ["qualifying_children", "other_dependents"], "n24": ["qualifying_children"], "nu18": ["qualifying_children"],
           "EIC": ["qualifying_children"], "f2441": ["dependent_care_people"], "age_head": ["people.birth_year"], "age_spouse": ["people.birth_year"],
           "e00200": ["jobs.wages"], "e00900": ["businesses.profit"], "e00300": ["interest"], "e00400": ["tax_exempt_interest"], "e00600": ["ordinary_dividends"],
           "e00650": ["qualified_dividends"], "p22250": ["short_term_gain", "-capital_loss_carryover"], "p23250": ["long_term_gain"],
           "e01500": ["retirement_distributions"], "e01700": ["retirement_distributions"], "e02400": ["social_security_benefits"], "e02300": ["unemployment"],
           "e00700": ["other_income", "hsa_nonqualified"], "e09900": ["early_distributions", "hsa_nonqualified"], "e03220": ["educator_expenses"],
           "e03290": ["hsa_contributions"], "e03270": ["se_health_insurance"], "e03150": ["ira_deduction"], "e03210": ["student_loan_interest"],
           "e03400": ["other_adjustments"], "e17500": ["medical"], "e18400": ["state_local_tax"], "e18500": ["property_tax"], "e19200": ["mortgage_interest"],
           "e19800": ["charity"], "e20100": ["charity_noncash"], "e32800": ["dependent_care_expenses"], "e87521": ["students.expenses"],
           "e87530": ["students.expenses"], "p08000": ["other_credits"], "tip_income": ["qualified_tips"], "overtime_income": ["qualified_overtime"]}
INT_FIELDS = frozenset({"RECID", "FLPDYR", "MARS", "XTOT", "n24", "nu18", "nu06", "EIC", "f2441", "age_head", "age_spouse", "PT_SSTB_income", "f6251"})


def record_for(value: ReturnInput, sources: dict | None = None):
    """One Tax-Calculator record for this profile (dollars), and notes on how it was mapped. docs/taxes.md "The tax engines" has the table.
    sources, when given, gets each record input's ReturnInput fields ([field, sign]; SOURCES, and the per-person ones here)."""
    joint = value.filing_status == "married_joint"
    notes = []
    whose = lambda owner: "s" if joint and owner == "spouse" else "p"
    if sources is not None:
        sources |= {key: [[field.lstrip("-"), -1 if field.startswith("-") else 1] for field in fields] for key, fields in SOURCES.items()}
        for person in "ps":  # One person's jobs and businesses; just "jobs" or "businesses" when they have none (it's zero).
            jobs = [index for index, job in enumerate(value.jobs) if whose(job.owner) == person]
            businesses = [index for index, business in enumerate(value.businesses) if whose(business.owner) == person]
            sources[f"e00200{person}"] = [[f"jobs.{index}.wages", 1] for index in jobs] or [["jobs", 1]]
            sources[f"pencon_{person}"] = [item for index in jobs for item in ([f"jobs.{index}.medicare_wages", 1], [f"jobs.{index}.wages", -1])] or [["jobs", 1]]
            sources[f"e00900{person}"] = [[f"businesses.{index}.profit", 1] for index in businesses] or [["businesses", 1]]
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


def evaluate(record, year, outputs=(), policy=(), index=None):
    """The runner's JSON answer for this record and year (cached by both), with the extra outputs and law parameters the
    worksheet map reads. index: {parameter: record field} for a parameter read by something other than filing status
    (the EITC's by the number of qualifying children)."""
    key = hashlib.sha256(json.dumps([record, year, list(outputs), list(policy), index or {}], sort_keys=True).encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    request = {"year": year, "record": record, "outputs": list(outputs), "policy": list(policy), "index": index or {}}
    try:
        done = subprocess.run([sys.executable, "-I", str(RUNNER)], input=json.dumps(request).encode(), capture_output=True,
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
    """Tax on taxable income (dollars) over the year's rate schedule for this filing status, through the one bracket function
    (tax_return.bracket_tax): the schedule's bounds become cents and its rates basis points."""
    brackets = [{"from_minor": Decimal(str(policy[f"II_brk{number - 1}"])) * 100 if number > 1 else Decimal(0),
                 "rate_bp": Decimal(str(policy[f"II_rt{number}"])) * 10000} for number in range(1, 8)]
    return bracket_tax(amount * 100, brackets) / 100


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


# The worksheet ---------------------------------------------------------------------------------------------------

MAP = Path(__file__).with_name("taxcalc_map.json")
_map: dict = {}


def worksheet_map():
    """taxcalc_map.json with each formula compiled to the worksheet's expression language (finance/worksheet.py), and the
    outputs and law parameters it reads beyond what every run reads back (OUTPUTS and POLICY in taxcalc_run.py).
    param_types: a parameter is money unless named a "rate" (a share: `amount * RATE`), "int" (a count or age) or "bp" (a
    rate as whole basis points, for rate arithmetic). param_index: a parameter read by a record field, not filing status."""
    if not _map:
        from .taxcalc_run import OUTPUTS, POLICY
        found = json.loads(MAP.read_text(encoding="utf-8"))
        found["types"] = {**{name: "rate" for name in SCHEDULE_RATES}, **found.get("param_types", {})}
        found["index"] = found.get("param_index", {})
        outputs, read = set(found["nodes"]) | set(found["opaque"]), set()
        for spec in found["nodes"].values():
            spec["compiled"] = compile_formula(spec["formula"], outputs, found["facts"], found["parts"], read, found["types"])
            spec["reads"] = sorted(name for name in names_in(spec["formula"], found["parts"]) if name in outputs or name in found["facts"])
        found["policy"] = sorted(read)
        found["extra_outputs"] = sorted(outputs - set(OUTPUTS))
        found["extra_policy"] = sorted(read - set(POLICY))
        _map.update(found)
    return _map


# schedule(x): the year's ordinary rate schedule, its rates and the thresholds between them (Tax-Calculator's SchXYZ).
SCHEDULE_RATES = tuple(f"II_rt{n}" for n in range(1, 9))
SCHEDULE_THRESHOLDS = tuple(f"II_brk{n}" for n in range(1, 8))


def names_in(text, parts):
    found = set()
    for item in ast.walk(ast.parse(text, mode="eval")):
        if isinstance(item, ast.Name) and item.id not in FUNCTIONS:
            found |= names_in(parts[item.id], parts) if item.id in parts else {item.id}
    return found


FUNCTIONS = frozenset({"min", "max", "max0", "if_", "int", "usd", "muldiv", "steps_floor", "steps_ceil", "schedule"})


def fraction(literal):
    """A rate written as a decimal (0.9235) as the exact fraction {num, den}."""
    value = Decimal(repr(literal))
    places = max(0, -value.as_tuple().exponent)
    return {"num": str(int(value.scaleb(places))), "den": str(10 ** places)}


def compile_formula(text, outputs, facts, parts, read, types=None):
    """A map formula as an expression: + and − add and take away, `x * 0.5` is a rate (rounded half-even, as cents), as is
    `x * RATE` with a rate parameter (types), `x * y` a product with a count, min/max/max0, `if_(condition, then, else)`,
    comparisons with and/or/not, `int(n)` a count, `usd(n)` dollars in a product (`usd(1000) * steps`, where a bare number
    would be a rate); any other number is dollars. Further functions: `muldiv(a, b, c)`
    (a × b ÷ c, half-even; money × count ÷ money is a count), `steps_floor(x, UNIT)` and `steps_ceil(x, UNIT)` (x in whole
    steps of a money parameter or a number of dollars), and `schedule(x)` (the ordinary rate schedule, rounded once). A name
    is an output (a rule), a record input (a fact), a part (its formula) or else a law parameter (read collects those)."""
    types = types or {}

    def rate_param(item):
        return isinstance(item, ast.Name) and types.get(item.id) == "rate" and item.id not in parts

    def walk(item):
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Add):
            left, right = walk(item.left), walk(item.right)
            return {"kind": "add", "args": (left["args"] if left["kind"] == "add" else [left]) + [right]}
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Sub):
            return {"kind": "sub", "left": walk(item.left), "right": walk(item.right)}
        if isinstance(item, ast.BinOp) and isinstance(item.op, ast.Mult):
            literal, other = (item.right, item.left) if isinstance(item.right, ast.Constant) else (item.left, item.right) \
                if isinstance(item.left, ast.Constant) else (None, None)
            if literal is not None:
                return {"kind": "mulRate", "base": walk(other), "rate": fraction(literal.value), "round": "half-even"}
            rate, other = (item.right, item.left) if rate_param(item.right) else (item.left, item.right) if rate_param(item.left) else (None, None)
            if rate is not None:
                read.add(rate.id)
                return {"kind": "mulRate", "base": walk(other), "rateParam": rate.id, "round": "half-even"}
            return {"kind": "mulInt", "base": walk(item.left), "count": walk(item.right)}
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.USub):
            return {"kind": "sub", "left": {"kind": "money", "cents": "0"}, "right": walk(item.operand)}
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.Not):
            return {"kind": "not", "arg": walk(item.operand)}
        if isinstance(item, ast.BoolOp):
            return {"kind": "and" if isinstance(item.op, ast.And) else "or", "args": [walk(value) for value in item.values]}
        if isinstance(item, ast.Compare) and len(item.ops) == 1:
            op = {ast.Lt: "lt", ast.LtE: "le", ast.Gt: "gt", ast.GtE: "ge", ast.Eq: "eq", ast.NotEq: "ne"}[type(item.ops[0])]
            return {"kind": "cmp", "op": op, "left": walk(item.left), "right": walk(item.comparators[0])}
        if isinstance(item, ast.Call) and isinstance(item.func, ast.Name):
            name, args = item.func.id, item.args
            if name in ("min", "max"):
                return {"kind": name, "args": [walk(value) for value in args]}
            if name == "max0":
                return {"kind": "max0", "arg": walk(args[0])}
            if name == "if_":
                return {"kind": "if", "cond": walk(args[0]), "then": walk(args[1]), "else": walk(args[2])}
            if name == "int":
                return {"kind": "int", "value": str(int(args[0].value))}
            if name == "usd":  # A dollar amount where a bare number would read as a rate: `usd(1000) * steps`.
                return {"kind": "money", "cents": str(int(Decimal(repr(args[0].value)) * 100))}
            if name == "muldiv":
                return {"kind": "mulDiv", "a": walk(args[0]), "b": walk(args[1]), "c": walk(args[2]), "round": "half-even"}
            if name in ("steps_floor", "steps_ceil"):
                found = {"kind": "stepUnits", "value": walk(args[0]), "mode": "floor" if name == "steps_floor" else "ceil"}
                unit = args[1]
                if isinstance(unit, ast.Constant):
                    return {**found, "unitCents": str(int(Decimal(repr(unit.value)) * 100))}
                read.add(unit.id)
                return {**found, "unitParam": unit.id}
            if name == "schedule":
                read.update(SCHEDULE_RATES + SCHEDULE_THRESHOLDS)
                return {"kind": "brackets", "base": walk(args[0]), "rates": list(SCHEDULE_RATES), "thresholds": list(SCHEDULE_THRESHOLDS), "round": "once"}
        if isinstance(item, ast.Constant) and isinstance(item.value, int | float):
            return {"kind": "money", "cents": str(int(Decimal(repr(item.value)) * 100))}
        if isinstance(item, ast.Name):
            if item.id in parts:
                return walk(ast.parse(parts[item.id], mode="eval").body)
            if item.id in outputs:
                return {"kind": "rule", "ruleId": item.id}
            if item.id in facts:
                return {"kind": "fact", "factId": item.id}
            read.add(item.id)
            return {"kind": "param", "name": item.id}
        raise ValueError(f"The worksheet map can't read {ast.unparse(item)} in {text}.")
    return walk(ast.parse(text, mode="eval").body)


def law_param(value, kind, field, record):
    """A law parameter for the worksheet (finance/worksheet.py params): money as cents, a rate as its exact fraction, a count,
    or a rate in whole basis points; read by a record field (field) when it isn't read by filing status."""
    if kind == "rate":
        found = {"type": "rate", **fraction(value)}
    elif kind == "int":
        found = {"type": "int", "value": str(int(round(value)))}
    elif kind == "bp":
        found = {"type": "int", "value": str(int((Decimal(str(value)) * 10000).to_integral_value(ROUND_HALF_EVEN)))}
    else:
        found = {"type": "money", "value": str(cents(value))}
    if field:
        found["source"] = {"read_by": field, "at": record.get(field, 0)}
    return found


def map_worksheet(raw, year, status, tolerance):
    """The engine's outputs as worksheet nodes: each one the map writes a formula for, re-run over the values the engine
    reported (within tolerance: it works in float dollars); the rest, and any formula that doesn't reproduce the engine's
    value, as `opaque`. A map written for another release or law file isn't used."""
    found = worksheet_map()
    record, sources = raw.get("record") or {}, raw.get("record_sources") or {}
    amounts = {name: cents(amount) for name, amount in (raw.get("values") or {}).items()}
    refusal = None
    if found["pinned"] != installed() or found["law_sha256"] != law_sha256():
        refusal = "the worksheet map was written for another Tax-Calculator release or law file"
    elif year not in found["years"]:
        refusal = f"the worksheet map doesn't cover {year}"
    nodes, typed = {}, {}
    for name, label in found["facts"].items():
        number = int(record.get(name, 0)) if name in INT_FIELDS else cents(record.get(name, 0))
        typed[name] = ("int" if name in INT_FIELDS else "money", number)
        source = {"fields": sources.get(name, [])} if name in record else {"assumed": "Not sent: Tax-Calculator takes it as zero"}
        nodes[f"fact:{name}"] = worksheet.node(f"fact:{name}", label, "fact", None if name in INT_FIELDS else number, source=source,
                                               count=number if name in INT_FIELDS else None)
    typed |= {name: ("money", amount) for name, amount in amounts.items()}
    refs = {name: name for name in amounts} | {name: f"fact:{name}" for name in found["facts"]}
    labels = {**found["facts"], **found["opaque"], **{name: spec["label"] for name, spec in found["nodes"].items()}}
    params = {name: law_param(value, found["types"].get(name, "money"), found["index"].get(name), record)
              for name, value in (raw.get("policy") or {}).items() if name in found["policy"]}
    law = {"year": year, "filing_status": status}
    for name, label in found["opaque"].items():
        if name in amounts:
            nodes[name] = worksheet.node(name, label, "opaque", amounts[name], detail={"reason": "Tax-Calculator gives this amount without its steps"})
    for name, spec in found["nodes"].items():
        if name not in amounts:
            continue
        reason = refusal
        if not refusal:
            made: dict = {}
            try:
                top = worksheet.Evaluator(name, spec["label"], spec["cite"], typed, refs, labels, params, law, made).run(spec["compiled"])
                if abs(top.value - amounts[name]) <= tolerance:
                    made[name]["amount_minor"] = amounts[name]  # The engine's value; its steps agree within the tolerance.
                    nodes.update(made)
                    continue
                reason = f"its formula gives {worksheet.shown(top.value)}"
            except (worksheet.Unsupported, KeyError, TypeError, ValueError) as exc:
                reason = f"its formula couldn't be run ({str(exc)[:120]})"
        nodes[name] = worksheet.node(name, spec["label"], "opaque", amounts[name], [refs[item] for item in spec["reads"] if item in refs], spec["cite"],
                                     detail={"reason": reason})
    return nodes


class TaxCalculatorEngine:
    name = "taxcalc"  # For the records only: the page shows the slot's label (finance/tax_engine.py).
    # Lines it gives without steps: none. Every output is written out in taxcalc_map.json under current law, and one whose
    # formula stops reproducing the engine (a law change) turns opaque and fails the conformance test (docs/taxes.md "The tax engines").
    opaque_lines: frozenset = frozenset()
    tolerance_minor = 2  # It works in float dollars: each output is rounded to the cent.

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
        sources: dict = {}
        record, notes = record_for(value, sources)
        mapped = worksheet_map()
        try:
            answer = evaluate(record, value.year, mapped["extra_outputs"], mapped["extra_policy"],
                              {name: field for name, field in mapped["index"].items() if name in mapped["policy"]})
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
        result = self.shaped(value, found, answer, record, context, notes, label)
        result["raw"]["record_sources"] = sources
        return result

    def worksheet(self, result):
        """How this return was worked out, node by node (finance/worksheet.py): the outputs the map writes formulas for,
        re-run over what the engine reported; the rest as the engine's values; the lines' own nodes."""
        raw = result.get("raw") or {}
        nodes = map_worksheet(raw, result["year"], result["filing_status"], self.tolerance_minor) if raw.get("values") else {}
        return {**nodes, **(raw.get("line_nodes") or {})}

    def shaped(self, value: ReturnInput, found, answer, record, context, notes, slot_label):
        """The return's lines from the engine's outputs, each with its node: an output's node is the output's name
        (map_worksheet); what this file works out itself gets its own (Lines.made, Lines.fact)."""
        policy = answer["policy"]
        lines = Lines()
        line = lines.add
        lines.income(value, found["c01000"], found["c02500"], capital_how="Schedule D netting; a loss counts up to $3,000",
                     social_security_how="the taxable share of benefits (IRC §86)", capital_node="c01000", social_security_node="c02500")
        agi, adjustments = found["c00100"], found["c02900"]
        lines.total_income(agi + adjustments, lines.made("total_income", "Total income: AGI with the adjustments added back", "sum", agi + adjustments,
                                                         ["c00100", "c02900"]))
        listed, listed_nodes = 0, []
        for key, amount, label, node in (("se_half", found["c03260"], "Half of self-employment tax", "c03260"),
                                         ("hsa", cents(record["e03290"]), "HSA contributions (not through payroll)", self.hsa_node(lines, value, cents(record["e03290"]))),
                                         ("se_health", value.se_health_insurance, "Self-employed health insurance", None),
                                         ("ira", value.ira_deduction, "Traditional IRA deduction", None)):
            if amount:
                node = node or lines.fact(f"adjust_{key}", label, amount, [["se_health_insurance" if key == "se_health" else "ira_deduction", 1]])
                listed += line(f"adjust_{key}", label, -amount, section="adjustments", node=node) * -1
                listed_nodes.append(node)
        student_loan = min(value.student_loan_interest, max(adjustments - listed, 0))
        loan_node = (lines.fact("adjust_student_loan", "Student-loan interest", student_loan, [["student_loan_interest", 1]])
                     if student_loan == value.student_loan_interest else
                     lines.made("adjust_student_loan", "Student-loan interest", "difference", student_loan, ["c02900", *listed_nodes])) if student_loan else None
        if adjustments - listed - student_loan:
            line("adjust_other", "Educator expenses and other adjustments", -(adjustments - listed - student_loan), section="adjustments",
                 node=lines.made("adjust_other", "Educator expenses and other adjustments", "difference", adjustments - listed - student_loan,
                                 ["c02900", *listed_nodes, *([loan_node] if loan_node else [])]))
        if student_loan:
            line("adjust_student_loan", "Student-loan interest", -student_loan, section="adjustments", node=loan_node)
        line("agi", "Adjusted gross income (AGI)", agi, section="total", node="c00100")
        # Deduction: the model's standard deduction includes the non-itemizer's charitable deduction; it's shown apart.
        standard, itemized = found["standard"], found["c04470"]
        limit = cents(policy["STD_charity_ded_nonitemizers_max"])
        charity = 0 if itemized else min(value.charity, limit, standard)
        charity_node = lines.made("charity_nonitemizer", "Charitable deduction (not itemizing)", "min", charity, [
            lines.fact("charity_nonitemizer~gifts", "Cash gifts to charity", value.charity, [["charity", 1]]),
            self.law_node(lines, "charity_nonitemizer~limit", "The year's limit on the charitable deduction for non-itemizers", limit,
                          "STD_charity_ded_nonitemizers_max", value, "26 U.S.C. § 170(p)"), "standard"]) if charity else None
        line("deduction", "Itemized deductions" if itemized else "Standard deduction", -(itemized or standard - charity),
             "itemized, after limits" if itemized else "standard, with any extra for age", "deductions",
             node="c04470" if itemized else lines.made("deduction", "Standard deduction, less the charitable deduction shown on its own line", "difference",
                                                       standard - charity, ["standard", *([charity_node] if charity_node else [])]))
        if charity:
            line("charity_nonitemizer", "Charitable deduction (not itemizing)", -charity, "cash gifts, up to the year's limit", "deductions", node=charity_node)
        if found["senior_deduction"]:
            line("senior", "Senior deduction", -found["senior_deduction"], "65 or older, phased out above the income limit", "deductions", node="senior_deduction")
        other = found["tip_income_deduction"] + found["overtime_income_deduction"] + found["auto_loan_interest_deduction"]
        if other:
            line("other_deductions", "Tips, overtime and car-loan interest deductions", -other, "each up to its limit, phased out above the income limit", "deductions",
                 node=lines.made("other_deductions", "Tips, overtime and car-loan interest deductions", "sum", other,
                                 ["tip_income_deduction", "overtime_income_deduction", "auto_loan_interest_deduction"]))
        if found["qbided"]:
            line("qbi", "Qualified business income deduction", -found["qbided"], section="deductions", node="qbided")
        taxable = line("taxable_income", "Taxable income", found["c04800"], section="total", node="c04800")
        # Tax: the Tax Table below $100,000 (redone here when there's no preferential income), else the model's.
        preferential = value.qualified_dividends > 0 or (value.long_term_gain > 0 and value.long_term_gain + min(value.short_term_gain - value.capital_loss_carryover, 0) > 0)
        table = None if preferential else table_tax(taxable, policy)
        tax = table if table is not None else found["taxbc"]
        leeway = 2500 * 22 // 100 + 100 if preferential and taxable < int(TABLE_BELOW) * 100 else 0  # 22% of half a $50 row, plus a dollar.
        if leeway:
            notes.append("With qualified dividends or long-term gains below $100,000 of taxable income, the tax is worked from the rate schedule, "
                         "not the Tax Table's rows: it can differ by a few dollars.")
        tax_node = table_nodes(lines, taxable, policy, tax) if table is not None else "taxbc"
        line("tax", "Tax", tax, "the Tax Table" if table is not None else "the rate schedules and the capital gains worksheet", "tax", leeway, node=tax_node)
        if found["c09600"]:
            line("amt", "Alternative minimum tax", found["c09600"], section="tax", node="c09600")
        credits = found["c07100"]
        credited, credit_nodes = 0, []
        for key, amount, label, node in (("dependent_care", found["c07180"], "Child and dependent care credit", "c07180"),
                                         ("education", found["c07230"], "Education credits (nonrefundable part)", "c07230"),
                                         ("child", found["c07220"] + found["odc"], "Child tax credit and credit for other dependents", None)):
            if amount:
                node = node or lines.made("credit_child", label, "sum", amount, ["c07220", "odc"])
                credited += line(f"credit_{key}", label, -amount, section="credits", node=node) * -1
                credit_nodes.append(node)
        if credits - credited:
            line("credit_other", "Other credits", -(credits - credited), "other credits typed in", "credits",
                 node=lines.made("credit_other", "Other credits", "difference", credits - credited, ["c07100", *credit_nodes]))
        other_taxes = found["othertaxes"]
        listed, listed_nodes = 0, []
        for key, amount, label, node in (("se", found["setax"], "Self-employment tax", "setax"), ("additional_medicare", found["ptax_amc"], "Additional Medicare tax", "ptax_amc"),
                                         ("niit", found["niit"], "Net investment income tax", "niit")):
            if amount:
                listed += line(f"other_{key}", label, amount, section="other_taxes", node=node)
                listed_nodes.append(node)
        if other_taxes - listed:
            line("other_other", "Other taxes", other_taxes - listed, "10% on early distributions, 20% on HSA money", "other_taxes",
                 node=lines.made("other_other", "Other taxes", "difference", other_taxes - listed, ["othertaxes", *listed_nodes]))
        # Nonrefundable credits can't exceed the tax: with the Tax Table's tax they're used against it the same way.
        after = max(0, tax + found["c09600"] - credits)
        before = lines.made("total_tax~before", "The tax and the alternative minimum tax, less nonrefundable credits", "sum", tax + found["c09600"] - credits,
                            [tax_node, "c09600", "c07100"], signs=[1, 1, -1])
        after_node = lines.made("total_tax~after", "The tax after credits, not below zero", "max", after, [before, constant(lines, 0)])
        total_tax = line("total_tax", "Total tax", after + other_taxes, section="total", within=leeway,
                         node=lines.made("total_tax", "Total tax: the tax after credits plus other taxes", "sum", after + other_taxes, [after_node, "othertaxes"]))
        refundable = found["refund"]
        refundable_lines = [("eitc", "Earned income credit", found["eitc"], "", "eitc"), ("actc", "Additional child tax credit", found["c11070"], "", "c11070"),
                            ("aotc", "American opportunity credit (refundable part)", found["c10960"], "", "c10960")]
        notes.append(f"Worked out by {slot_label} from the {value.year} law as published.")
        result = completed(value, lines, agi=agi, taxable=taxable, tax=tax, total_tax=total_tax, refundable=refundable, refundable_lines=refundable_lines,
                           context=context, notes=notes, slot_label=slot_label, raw={"record": record, "values": answer["values"], "policy": policy},
                           refundable_node="refund")
        result["reports"] = sorted(REPORTS)
        return result

    @staticmethod
    def law_node(lines, key, label, amount, parameter, value, cite):
        name = f"line:{key}"
        lines.nodes[name] = worksheet.node(name, label, "law", amount, cite=cite, source={"parameter": parameter, "year": value.year,
                                                                                           "filing_status": value.filing_status})
        return name

    def hsa_node(self, lines, value: ReturnInput, deduction):
        """The HSA deduction as this file limits it (hsa_deduction): the contributions, or the year's §223(b) limit."""
        if not deduction:
            return None
        contributions = lines.fact("adjust_hsa~sent", "HSA contributions (not through payroll)", value.hsa_contributions, [["hsa_contributions", 1]])
        if deduction == value.hsa_contributions:
            return contributions
        limit = self.law_node(lines, "adjust_hsa~limit", "The year's HSA contribution limit for the coverage", deduction, "HSA limit", value, "26 U.S.C. § 223(b)")
        return lines.made("adjust_hsa", "HSA contributions, up to the year's limit", "min", deduction, [contributions, limit])


def table_nodes(lines: Lines, taxable, policy, tax):
    """The Tax Table's tax (table_tax) as nodes: the middle of taxable income's row, the year's rate schedule on it (a
    rate table), rounded to the dollar."""
    amount = Decimal(max(taxable, 0)) / 100
    if amount < 25:
        middle = 250 if amount < 5 else 1000 if amount < 15 else 2000  # The rows $0-5, $5-15 and $15-25.
        middle_node = constant(lines, middle)
    else:
        width = 2500 if amount < 3000 else 5000
        rows = lines.made("tax~rows", f"Whole ${width // 100} rows below taxable income", "steps", None, ["c04800"],
                          detail={"unit_minor": width, "round": "floor"})
        count = max(taxable, 0) // width
        lines.nodes[rows] |= {"count": count, "value": str(count)}
        start = lines.made("tax~start", "Where taxable income's row starts", "multiply", count * width, [constant(lines, width), rows])
        middle = count * width + width // 2
        middle_node = lines.made("tax~middle", "The middle of taxable income's row in the Tax Table", "sum", middle, [start, constant(lines, width // 2)])
    table = [{"from_minor": int(Decimal(str(policy[f"II_brk{number - 1}"])) * 100) if number > 1 else 0, **rate_of(policy[f"II_rt{number}"])}
             for number in range(1, 8)]
    scheduled = worksheet.bracket_tax(middle, table)
    on_schedule = lines.made("tax~schedule", "The rate schedule on the middle of the row", "lookup", scheduled, [middle_node], detail={"table": table})
    return lines.made("tax", "The Tax Table's tax: the rate schedule on the middle of the row, rounded to the dollar", "round", tax, [on_schedule],
                      detail={"round": "half-up"}, cite="Form 1040 instructions, Tax Table (taxable income below $100,000)")


def rate_of(rate):
    """A rate from the law file (0.22) as the worksheet's {num, den, rate}."""
    found = fraction(rate)
    return {"num": int(found["num"]), "den": int(found["den"]), "rate": worksheet.percent(int(found["num"]), int(found["den"]))}


def constant(lines: Lines, minor):
    name = f"const:money:{minor}"
    lines.nodes[name] = worksheet.node(name, worksheet.shown(minor), "constant", minor)
    return name
