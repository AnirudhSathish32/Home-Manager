"""Invaro OpenTax (docs/tax-engines.md): the federal return from an open-source, cited rule corpus, run as a separate Node
process.

The engine is the pinned, unmodified npm build in vendor/opentax (AGPL-3.0; PIN.json). Each run:
- checks the bundle against its pinned SHA-256;
- writes the profile as OpenTax facts to a temporary folder and runs `main.js eval --facts … --target us.federal.net_tax
  --json` under Node's permission model (read-only: the bundle and that folder), with its usage ping turned off
  (OPENTAX_TELEMETRY=0, DO_NOT_TRACK=1);
- reads the proof tree: every Form 1040 line is a rule with its value in cents and the law it cites.
The engine refuses rather than guesses: facts it needs are named (NEEDS_FACTS) and cases outside its corpus aren't
covered. Payments (withholding, estimated tax) are added up here: the engine's balance due counts withholding only. The
state return is the simplified one (tax_return.state_return), labeled.

The app shows this engine as its slot ("Engine 1"); its name stays in this file, the records and docs/tax-engines.md.
"""

from collections import OrderedDict
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

from ...core.money import format_minor
from ..tax_engine import NEEDS, STATUSES, Capabilities, completed
from ..tax_return import CURRENCY, ReturnInput

VENDOR = Path(__file__).resolve().parents[2] / "vendor" / "opentax"
STATUS = {"single": "single", "married_joint": "mfj", "head_of_household": "hoh"}
YEARS = frozenset({2025, 2026})  # The pinned corpus's law (corpus-us-federal 0.37.0).
TARGET = "us.federal.net_tax"
TIMEOUT = 60
CACHE_SIZE = 32
_cache: OrderedDict = OrderedDict()


class EngineFailed(Exception):
    pass


def pin():
    return json.loads((VENDOR / "PIN.json").read_text(encoding="utf-8"))


def dollars(minor):
    """Cents as the dollar text OpenTax reads ("1234.56"), exact."""
    sign = "-" if minor < 0 else ""
    return f"{sign}{abs(minor) // 100}.{abs(minor) % 100:02d}"


def earned_by_owner(value: ReturnInput):
    earned: dict[str, int] = {}
    for job in value.jobs:
        earned[job.owner] = earned.get(job.owner, 0) + job.wages
    for business in value.businesses:
        earned[business.owner] = earned.get(business.owner, 0) + max(0, business.income - business.expenses)
    return earned


def facts_for(value: ReturnInput):
    """The OpenTax facts for this profile, and notes on how it was mapped (docs/tax-engines.md has the table)."""
    facts: dict = {"filingStatus": STATUS[value.filing_status], "wages": dollars(sum(job.wages for job in value.jobs))}
    notes = []

    def money(key, minor):
        if minor:
            facts[key] = dollars(minor)
    money("medicareWages", sum(job.medicare_wages for job in value.jobs))
    money("taxableInterest", value.interest)
    money("taxExemptInterest", value.tax_exempt_interest)
    qualified = min(value.qualified_dividends, value.ordinary_dividends) if value.ordinary_dividends else value.qualified_dividends
    money("qualifiedDividends", qualified)
    money("ordinaryDividends", max(0, value.ordinary_dividends - qualified))  # OpenTax's ordinary dividends are the non-qualified part.
    short, long = value.short_term_gain - value.capital_loss_carryover, value.long_term_gain
    if value.capital_loss_carryover:
        notes.append("Last year's capital loss carryover comes off short-term gains first (it isn't split short and long term here).")
    money("shortTermCapitalGains" if short >= 0 else "shortTermCapitalLoss", abs(short))
    money("longTermCapitalGains" if long >= 0 else "longTermCapitalLoss", abs(long))
    money("taxableIraDistributions", value.retirement_distributions)
    money("earlyDistributionSubjectToPenalty", value.early_distributions)
    money("hsaDistributions", value.hsa_nonqualified)  # Only the part not spent on medical care, so no qualified expenses against it.
    money("socialSecurityBenefits", value.social_security_benefits)
    money("unemploymentCompensation", value.unemployment)
    money("otherOrdinaryIncome", value.other_income)
    profit = sum(business.income - business.expenses for business in value.businesses)
    money("selfEmploymentNetProfit" if profit >= 0 else "scheduleCNetLoss", abs(profit))
    owners = {business.owner for business in value.businesses if business.income or business.expenses}
    if profit > 0 and owners:  # Schedule SE's wage-base room is that person's own Social Security wages.
        owner = next(iter(owners))
        money("socialSecurityWages", sum(job.ss_wages for job in value.jobs if job.owner == owner))
    money("educatorExpenses", value.educator_expenses)
    money("hsaContribution", value.hsa_contributions)
    if value.hsa_contributions and value.hsa_coverage:
        facts["hsaCoverage"] = value.hsa_coverage
    money("selfEmployedHealthPremiums", value.se_health_insurance)
    if value.ira_deduction:  # The deductible part, as entered: the plan-participant phase-out isn't applied again.
        money("iraContribution", value.ira_deduction)
        facts["isActivePlanParticipant"] = False
        facts["spouseIsActivePlanParticipant"] = False
        notes.append("Traditional IRA: the deductible part you entered counts as is (the workplace-plan phase-out isn't applied again).")
    money("studentLoanInterest", value.student_loan_interest)
    money("otherAdjustments", value.other_adjustments)
    money("medicalExpenses", value.medical)
    money("stateAndLocalTaxesPaid", value.state_local_tax + value.property_tax)
    money("mortgageInterestPaid", value.mortgage_interest)
    if value.mortgage_interest and value.mortgage_average_balance is not None:
        facts["mortgageAverageBalance"] = dollars(value.mortgage_average_balance)
    money("charitableCashContributions", value.charity)
    money("noncashCharitableContributions", value.charity_noncash)
    money("otherItemizedDeductions", value.other_itemized)
    if value.itemize:
        facts["forceItemized"] = True
    money("qualifiedTips", value.qualified_tips)
    if value.qualified_tips and value.tipped_occupation:
        facts["occupation"] = value.tipped_occupation
    money("qualifiedOvertimePremium", value.qualified_overtime)
    if value.qualifying_children:
        facts["qualifyingChildren"] = value.qualifying_children
    if value.other_dependents:
        facts["otherDependents"] = value.other_dependents
    if value.dependent_care_expenses:
        money("dependentCareExpenses", value.dependent_care_expenses)
        facts["careQualifyingIndividuals"] = value.dependent_care_people
        if value.filing_status == "married_joint":
            earned = earned_by_owner(value)
            facts["secondaryEarnedIncome"] = dollars(min(earned.values()) if len(earned) > 1 else 0)
    aotc = [student.expenses for student in value.students if student.aotc and student.expenses]
    for number, expenses in enumerate(aotc[:3], 1):
        facts[f"aotcExpensesStudent{number}"] = dollars(expenses)
    money("llcQualifiedExpenses", sum(student.expenses for student in value.students if not student.aotc))
    you = value.people[0].birth_year if value.people else None
    spouse = value.people[1].birth_year if len(value.people) > 1 else None
    if you:
        age = value.year - you  # Age at the end of the year, by calendar year.
        facts |= {"isAge65OrOlder": age >= 65, "isAge50OrOlder": age >= 50, "isAge55OrOlder": age >= 55, "isAtLeastAge25": age >= 25}
    if spouse and value.filing_status == "married_joint":
        facts["spouseIsAge65OrOlder"] = value.year - spouse >= 65
    return facts, notes


def node_path():
    found = os.environ.get("HOME_MANAGER_NODE") or shutil.which("node")
    if not found:
        raise EngineFailed("needs Node.js 20 or later (nodejs.org). It isn't installed, or isn't on PATH.")
    return found


_checked: dict = {}  # The bundle's file time and size when it last matched its pin: unchanged, it isn't hashed again.


def check_bundle():
    path = VENDOR / "main.js"
    info = path.stat()
    if _checked.get("stamp") == (info.st_mtime_ns, info.st_size):
        return
    expected = pin()["files"]["main.js"]
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise EngineFailed("isn't run: its file doesn't match its pinned SHA-256.")
    _checked["stamp"] = (info.st_mtime_ns, info.st_size)


def evaluate(facts, year):
    """The engine's JSON answer for these facts and tax year: a proof, or an error with its code."""
    key = hashlib.sha256(json.dumps([facts, year], sort_keys=True).encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    check_bundle()
    node = node_path()
    env = {"OPENTAX_TELEMETRY": "0", "DO_NOT_TRACK": "1", "NO_COLOR": "1",
           **{name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if name in os.environ}}
    with tempfile.TemporaryDirectory(prefix="hm-opentax-") as folder:
        path = Path(folder) / "facts.json"
        path.write_text(json.dumps(facts), encoding="utf-8")
        command = [node, "--permission", f"--allow-fs-read={VENDOR}{os.sep}*", f"--allow-fs-read={folder}{os.sep}*", str(VENDOR / "main.js"),
                   "eval", "--facts", str(path), "--as-of", f"{year}-12-31", "--target", TARGET, "--json"]
        try:
            done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT, env=env, cwd=folder,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired as exc:
            raise EngineFailed(f"didn't answer within {TIMEOUT} seconds.") from exc
        except OSError as exc:
            raise EngineFailed(f"couldn't start: {exc}.") from exc
    try:
        answer = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        raise EngineFailed(f"gave no answer (exit {done.returncode}: {detail[0][:200]}).") from exc
    _cache[key] = answer
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return answer


def cents(node):
    """A proof node's money value in cents, or None."""
    value = (node.get("value") or {})
    if value.get("type") != "money":
        return None
    try:
        return int(Decimal(str(value.get("value"))).to_integral_value(ROUND_HALF_EVEN))
    except (InvalidOperation, ValueError):
        return None


def rules_in(root):
    """{rule id: {"cents", "title", "cite"}} for every rule in the proof tree (first occurrence)."""
    found: dict = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        rule = node.get("ruleId")
        if rule and node.get("kind") == "rule" and rule not in found:
            citation = node.get("citation") or {}
            found[rule] = {"cents": cents(node), "title": node.get("title", ""), "cite": citation.get("source", "")}
        stack.extend(node.get("children") or [])
    return found


class OpenTaxEngine:
    name = "opentax"  # For the records only: the page shows the slot's label (finance/tax_engine.py).

    def version(self):
        pinned = pin()
        return {"name": self.name, "version": pinned["version"], "engine": f"{pinned['engine']['name']} {pinned['engine']['version']}",
                "corpus": f"{pinned['corpus']['name']} {pinned['corpus']['version']}", "pin_sha256": pinned["files"]["main.js"]}

    def readiness(self):
        """None when the engine can run here, else why not (the start of a sentence after its label)."""
        try:
            check_bundle()
            node_path()
        except (EngineFailed, OSError) as exc:
            return str(exc)
        return None

    def capabilities(self):
        # FEATURES (finance/tax_engine.py) it covers: none of them yet (docs/tax-engines.md lists each gap).
        return Capabilities(years=YEARS, statuses=STATUSES, features=frozenset(), states=frozenset())

    def calculate(self, value: ReturnInput, context, label="The tax engine"):
        facts, notes = facts_for(value)
        try:
            answer = evaluate(facts, value.year)
        except EngineFailed as exc:
            return self.empty(value, [f"{label} {exc}"])
        if not answer.get("ok"):
            return self.refused(value, answer.get("error") or {}, notes, label)
        return self.shaped(value, answer, context, notes, slot_label=label)

    def empty(self, value, notes, needs=(), unsupported=()):
        return {"complete": False, "year": value.year, "filing_status": value.filing_status, "lines": [], "notes": notes, "missing": [],
                "needs": list(needs), "unsupported": list(unsupported), "result_minor": None, "state": None}

    def refused(self, value, error, notes, label):
        code = error.get("code", "ERROR")
        if code == "NEEDS_FACTS":
            wanted = [item.get("factId", "") for item in (error.get("data") or {}).get("missing", [])]
            known = [fact for fact in wanted if fact in NEEDS]
            other = [fact for fact in wanted if fact not in NEEDS]
            reasons = []
            if known:
                reasons.append("To work out the return, enter " + "; ".join(dict.fromkeys(NEEDS[fact] for fact in known)) + ".")
            if other:
                reasons.append(f"{label} needs facts Home Manager doesn't collect yet: " + ", ".join(other) + ".")
            return self.empty(value, reasons + notes, needs=known, unsupported=[f"fact:{fact}" for fact in other])
        if code == "FACT_INVALID":
            return self.empty(value, [f"{label} didn't accept the return's facts ({error.get('message', '')[:200]})."])
        return self.empty(value, [f"{label} doesn't cover this return: {error.get('message', code)[:300]}"], unsupported=[f"engine:{code}"])

    def shaped(self, value: ReturnInput, answer, context, notes, slot_label):
        rules = rules_in(answer["proof"]["root"])
        lines: list[dict] = []

        def got(rule):
            return (rules.get(rule) or {}).get("cents") or 0

        def how(rule, extra=""):
            found = rules.get(rule)
            text = f"{found['title']} ({found['cite']})" if found else ""
            return "; ".join(part for part in (extra, text) if part)

        def line(key, label, amount, explained="", section=""):
            lines.append({"key": key, "label": label, "amount_minor": amount, "how": explained, "section": section})
            return amount
        # Income: what was sent, with the engine's capital gain or loss and taxable Social Security.
        line("wages", "Wages (every job's W-2 box 1)", sum(job.wages for job in value.jobs), f"{len(value.jobs)} job{'s' if len(value.jobs) != 1 else ''}", "income")
        line("interest", "Taxable interest", value.interest, section="income")
        line("dividends", "Ordinary dividends", value.ordinary_dividends, f"qualified: {format_minor(value.qualified_dividends, CURRENCY)}", "income")
        capital = got("us.federal.schedule_d.ordinary_st_gain") + got("us.federal.schedule_d.preferential_lt_gain") - got("us.federal.capital_loss_ordinary_offset")
        line("capital", "Capital gain or loss", capital, how("us.federal.capital_loss_ordinary_offset", "Schedule D netting; a loss counts up to $3,000"), "income")
        line("distributions", "Taxable retirement distributions", value.retirement_distributions, section="income")
        profit = sum(business.income - business.expenses for business in value.businesses)
        line("business", "Business profit or loss (Schedule C)", profit,
             "; ".join(f"{business.name}: {format_minor(business.income - business.expenses, CURRENCY)}" for business in value.businesses), "income")
        line("unemployment", "Unemployment", value.unemployment, section="income")
        line("hsa_nonqualified", "HSA money not spent on medical care", value.hsa_nonqualified, section="income")
        line("other_income", "Other income", value.other_income, section="income")
        line("social_security", "Taxable Social Security benefits", got("us.federal.taxable_social_security"),
             how("us.federal.taxable_social_security", f"of {format_minor(value.social_security_benefits, CURRENCY)} received"), "income")
        agi = got("us.federal.agi")
        known_adjustments = {"se_half": ("us.federal.se_tax_half_deduction", "Half of self-employment tax"), "hsa": ("us.federal.hsa_deduction", "HSA contributions (not through payroll)"),
                             "se_health": ("us.federal.sehi_deduction", "Self-employed health insurance"), "ira": ("us.federal.ira_deduction", "Traditional IRA deduction"),
                             "sep": ("us.federal.sep_deduction", "SEP or solo 401(k) contributions")}
        above = got("us.federal.above_the_line_adjustments")
        student_loan = got("us.federal.student_loan_interest_deduction")
        total_income = agi + above + student_loan
        counted = sum(item["amount_minor"] for item in lines if item["section"] == "income")
        if counted != total_income:
            line("income_engine", "Other income as the engine counts it", total_income - counted, "the engine's total income less the lines above", "income")
        line("total_income", "Total income", total_income, section="total")
        listed = 0
        for key, (rule, label) in known_adjustments.items():
            if got(rule):
                listed += line(f"adjust_{key}", label, -got(rule), how(rule), "adjustments") * -1
        if above - listed:
            line("adjust_other", "Educator expenses and other adjustments", -(above - listed), how("us.federal.above_the_line_adjustments"), "adjustments")
        if student_loan:
            line("adjust_student_loan", "Student-loan interest", -student_loan, how("us.federal.student_loan_interest_deduction"), "adjustments")
        line("agi", "Adjusted gross income (AGI)", agi, section="total")
        # Deduction: standard (with the charitable deduction for non-itemizers) or itemized, as the engine elected.
        standard, itemized = got("us.federal.standard_deduction"), got("us.federal.itemized_deductions")
        election, nonitemizer = got("us.federal.deduction_election"), got("us.federal.charitable_deduction_nonitemizer")
        itemizing = bool(itemized) and election == itemized and (election != standard + nonitemizer or bool(value.itemize))
        line("deduction", "Itemized deductions" if itemizing else "Standard deduction", -(itemized if itemizing else standard),
             f"itemized {format_minor(itemized, CURRENCY)} against standard {format_minor(standard, CURRENCY)}", "deductions")
        shown = itemized if itemizing else standard
        if not itemizing and nonitemizer:
            shown += line("charity_nonitemizer", "Charitable deduction (not itemizing)", -nonitemizer, how("us.federal.charitable_deduction_nonitemizer"), "deductions") * -1
        senior = got("us.federal.senior_deduction")
        if senior:
            shown += line("senior", "Senior deduction", -senior, how("us.federal.senior_deduction"), "deductions") * -1
        before_qbi = got("us.federal.taxable_income_before_qbi")
        rest = max(0, agi - before_qbi) - shown
        if rest:
            line("other_deductions", "Tips, overtime and car-loan interest deductions", -rest, "the engine's other deductions", "deductions")
        qbi = got("us.federal.qbi_deduction")
        if qbi:
            line("qbi", "Qualified business income deduction", -qbi, how("us.federal.qbi_deduction"), "deductions")
        taxable = line("taxable_income", "Taxable income", got("us.federal.taxable_income"), section="total")
        # Tax, alternative minimum tax and credits.
        # Below $100,000 of taxable income the Tax Table rule stands in for the general one.
        table_rule = "us.federal.income_tax_before_credits.tax_table"
        tax_rule = "us.federal.income_tax_before_credits" if "us.federal.income_tax_before_credits" in rules else table_rule
        tax = got(tax_rule)
        line("tax", "Tax", tax, how(tax_rule, "the Tax Table" if tax_rule == table_rule else "the rate schedules and the capital gains worksheet"), "tax")
        alternative = got("us.federal.amt")
        if alternative:
            line("amt", "Alternative minimum tax", alternative, how("us.federal.amt"), "tax")
        after = got("us.federal.income_tax_after_credits")
        credited = 0
        for key, rule, label in (("dependent_care", "us.federal.cdcc", "Child and dependent care credit"),
                                 ("education", "us.federal.education.nonrefundable", "Education credits (nonrefundable part)"),
                                 ("savers", "us.federal.savers_credit", "Saver's credit"),
                                 ("child", "us.federal.ctc", "Child tax credit and credit for other dependents")):
            if got(rule):
                credited += line(f"credit_{key}", label, -got(rule), how(rule), "credits") * -1
        if tax + alternative - after - credited:
            line("credit_other", "Other credits", -(tax + alternative - after - credited), "adoption, elderly or disabled, and others", "credits")
        other = got("us.federal.other_taxes")
        listed = 0
        for key, rule, label in (("se", "us.federal.se_tax", "Self-employment tax"), ("additional_medicare", "us.federal.additional_medicare_tax", "Additional Medicare tax"),
                                 ("niit", "us.federal.niit", "Net investment income tax")):
            if got(rule):
                listed += line(f"other_{key}", label, got(rule), how(rule), "other_taxes")
        if other - listed:
            line("other_other", "Other taxes", other - listed, "10% on early distributions, 20% on HSA money, household employment, excess premium credit", "other_taxes")
        total_tax = line("total_tax", "Total tax", after + other, section="total")
        # Payments are added up by the app (tax_engine.completed); refundable credits come from the engine.
        refundable = got("us.federal.refundable_credits")
        credits = [(key, label, got(rule), how(rule)) for key, rule, label in (
            ("eitc", "us.federal.eitc", "Earned income credit"), ("actc", "us.federal.actc", "Additional child tax credit"),
            ("aotc", "us.federal.education.aotc_refundable", "American opportunity credit (refundable part)"), ("ptc", "us.federal.ptc.net", "Net premium tax credit"))]
        if got(TARGET) != total_tax - refundable:
            notes.append(f"The engine's net tax ({format_minor(got(TARGET), CURRENCY)}) differs from the lines above; check the return.")
        defaults = [item.get("factId", "") for item in answer.get("assumptions", []) if item.get("source") == "default"]
        notes += [f"Worked out by {slot_label}: every line follows a cited rule. It relied on {len(defaults)} documented defaults for things not "
                  "entered (e.g. not blind, not claimed as a dependent)."]
        return completed(value, lines, agi=agi, taxable=taxable, tax=tax, total_tax=total_tax, refundable=refundable, refundable_lines=credits,
                         context=context, notes=notes, slot_label=slot_label,
                         raw={"corpus_merkle_root": answer.get("corpusMerkleRoot"), "artifact_hash": answer.get("artifactHash"),
                              "facts": answer["proof"].get("facts"), "assumptions": answer.get("assumptions"), "proof": answer["proof"]})
