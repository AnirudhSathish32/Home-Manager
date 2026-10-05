"""Invaro OpenTax (docs/taxes.md "The tax engines"): the federal return from an open-source, cited rule corpus, run as a separate Node
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

The app shows this engine as its slot ("Engine 1"); its name stays in this file, the records and docs/taxes.md "The tax engines".
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
from .. import worksheet
from ..tax_engine import NEEDS, STATUSES, Capabilities, Lines, completed
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


def facts_for(value: ReturnInput, sources: dict | None = None):
    """The OpenTax facts for this profile, and notes on how it was mapped (docs/taxes.md "The tax engines" has the table).
    sources, when given, gets each fact's ReturnInput fields as the worksheet's `fact` source ([field, sign];
    finance/worksheet.py), written beside the mapping so the two can't drift."""
    facts: dict = {}
    notes = []
    sources = {} if sources is None else sources

    def put(key, fact, *fields):
        """A fact from these fields ("-field" takes it away; "jobs.wages" adds up every job's)."""
        facts[key] = fact
        sources[key] = [[field.lstrip("-"), -1 if field.startswith("-") else 1] for field in fields]

    def money(key, minor, *fields):
        if minor:
            put(key, dollars(minor), *fields)
    put("filingStatus", STATUS[value.filing_status], "filing_status")
    put("wages", dollars(sum(job.wages for job in value.jobs)), "jobs.wages")
    money("medicareWages", sum(job.medicare_wages for job in value.jobs), "jobs.medicare_wages")
    money("taxableInterest", value.interest, "interest")
    money("taxExemptInterest", value.tax_exempt_interest, "tax_exempt_interest")
    qualified = min(value.qualified_dividends, value.ordinary_dividends) if value.ordinary_dividends else value.qualified_dividends
    money("qualifiedDividends", qualified, "qualified_dividends")
    # OpenTax's ordinary dividends are the non-qualified part.
    money("ordinaryDividends", max(0, value.ordinary_dividends - qualified), "ordinary_dividends", "-qualified_dividends")
    short, long = value.short_term_gain - value.capital_loss_carryover, value.long_term_gain
    if value.capital_loss_carryover:
        notes.append("Last year's capital loss carryover comes off short-term gains first (it isn't split short and long term here).")
    if short >= 0:
        money("shortTermCapitalGains", short, "short_term_gain", "-capital_loss_carryover")
    else:
        money("shortTermCapitalLoss", -short, "-short_term_gain", "capital_loss_carryover")
    money("longTermCapitalGains" if long >= 0 else "longTermCapitalLoss", abs(long), "long_term_gain" if long >= 0 else "-long_term_gain")
    money("taxableIraDistributions", value.retirement_distributions, "retirement_distributions")
    money("earlyDistributionSubjectToPenalty", value.early_distributions, "early_distributions")
    money("hsaDistributions", value.hsa_nonqualified, "hsa_nonqualified")  # Only the part not spent on medical care, so no qualified expenses against it.
    money("socialSecurityBenefits", value.social_security_benefits, "social_security_benefits")
    money("unemploymentCompensation", value.unemployment, "unemployment")
    money("otherOrdinaryIncome", value.other_income, "other_income")
    profit = sum(business.income - business.expenses for business in value.businesses)
    money("selfEmploymentNetProfit" if profit >= 0 else "scheduleCNetLoss", abs(profit), "businesses.profit" if profit >= 0 else "-businesses.profit")
    owners = {business.owner for business in value.businesses if business.income or business.expenses}
    if profit > 0 and owners:  # Schedule SE's wage-base room is that person's own Social Security wages.
        owner = next(iter(owners))
        money("socialSecurityWages", sum(job.ss_wages for job in value.jobs if job.owner == owner),
              *(f"jobs.{index}.ss_wages" for index, job in enumerate(value.jobs) if job.owner == owner))
    money("educatorExpenses", value.educator_expenses, "educator_expenses")
    money("hsaContribution", value.hsa_contributions, "hsa_contributions")
    if value.hsa_contributions and value.hsa_coverage:
        put("hsaCoverage", value.hsa_coverage, "hsa_coverage")
    money("selfEmployedHealthPremiums", value.se_health_insurance, "se_health_insurance")
    if value.ira_deduction:  # The deductible part, as entered: the plan-participant phase-out isn't applied again.
        money("iraContribution", value.ira_deduction, "ira_deduction")
        put("isActivePlanParticipant", False, "ira_deduction")
        put("spouseIsActivePlanParticipant", False, "ira_deduction")
        notes.append("Traditional IRA: the deductible part you entered counts as is (the workplace-plan phase-out isn't applied again).")
    money("studentLoanInterest", value.student_loan_interest, "student_loan_interest")
    money("otherAdjustments", value.other_adjustments, "other_adjustments")
    money("medicalExpenses", value.medical, "medical")
    money("stateAndLocalTaxesPaid", value.state_local_tax + value.property_tax, "state_local_tax", "property_tax")
    money("mortgageInterestPaid", value.mortgage_interest, "mortgage_interest")
    if value.mortgage_interest and value.mortgage_average_balance is not None:
        put("mortgageAverageBalance", dollars(value.mortgage_average_balance), "mortgage_average_balance")
    money("charitableCashContributions", value.charity, "charity")
    money("noncashCharitableContributions", value.charity_noncash, "charity_noncash")
    money("otherItemizedDeductions", value.other_itemized, "other_itemized")
    if value.itemize:
        put("forceItemized", True, "itemize")
    money("qualifiedTips", value.qualified_tips, "qualified_tips")
    if value.qualified_tips and value.tipped_occupation:
        put("occupation", value.tipped_occupation, "tipped_occupation")
    money("qualifiedOvertimePremium", value.qualified_overtime, "qualified_overtime")
    if value.qualifying_children:
        put("qualifyingChildren", value.qualifying_children, "qualifying_children")
    if value.other_dependents:
        put("otherDependents", value.other_dependents, "other_dependents")
    if value.dependent_care_expenses:
        money("dependentCareExpenses", value.dependent_care_expenses, "dependent_care_expenses")
        put("careQualifyingIndividuals", value.dependent_care_people, "dependent_care_people")
        if value.filing_status == "married_joint":
            earned = earned_by_owner(value)
            put("secondaryEarnedIncome", dollars(min(earned.values()) if len(earned) > 1 else 0), "jobs.wages", "businesses.profit")
    aotc = [student.expenses for student in value.students if student.aotc and student.expenses]
    for number, expenses in enumerate(aotc[:3], 1):
        put(f"aotcExpensesStudent{number}", dollars(expenses), "students.expenses")
    money("llcQualifiedExpenses", sum(student.expenses for student in value.students if not student.aotc), "students.expenses")
    you = value.people[0].birth_year if value.people else None
    spouse = value.people[1].birth_year if len(value.people) > 1 else None
    if you:
        age = value.year - you  # Age at the end of the year, by calendar year.
        for key, held in (("isAge65OrOlder", age >= 65), ("isAge50OrOlder", age >= 50), ("isAge55OrOlder", age >= 55), ("isAtLeastAge25", age >= 25)):
            put(key, held, "people.birth_year")
    if spouse and value.filing_status == "married_joint":
        put("spouseIsAge65OrOlder", value.year - spouse >= 65, "people.birth_year")
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


def run(arguments, files=None):
    """The engine's JSON answer to one command, run under Node's permission model (read-only: the bundle and a temporary
    folder holding `files`, {name: JSON}), with its usage ping turned off. An argument that names one of the files is
    given as its path."""
    check_bundle()
    node = node_path()
    env = {"OPENTAX_TELEMETRY": "0", "DO_NOT_TRACK": "1", "NO_COLOR": "1",
           **{name: os.environ[name] for name in ("SYSTEMROOT", "WINDIR") if name in os.environ}}
    with tempfile.TemporaryDirectory(prefix="hm-opentax-") as folder:
        for name, content in (files or {}).items():
            (Path(folder) / name).write_text(json.dumps(content), encoding="utf-8")
        command = [node, "--permission", f"--allow-fs-read={VENDOR}{os.sep}*", f"--allow-fs-read={folder}{os.sep}*", str(VENDOR / "main.js"),
                   *(str(Path(folder) / argument) if argument in (files or {}) else argument for argument in arguments)]
        try:
            done = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, timeout=TIMEOUT, env=env, cwd=folder,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0)
        except subprocess.TimeoutExpired as exc:
            raise EngineFailed(f"didn't answer within {TIMEOUT} seconds.") from exc
        except OSError as exc:
            raise EngineFailed(f"couldn't start: {exc}.") from exc
    try:
        return json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        detail = done.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no output"]
        raise EngineFailed(f"gave no answer (exit {done.returncode}: {detail[0][:200]}).") from exc


def evaluate(facts, year):
    """The engine's JSON answer for these facts and tax year: a proof, or an error with its code."""
    key = hashlib.sha256(json.dumps([facts, year], sort_keys=True).encode()).hexdigest()
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    answer = run(["eval", "--facts", "facts.json", "--as-of", f"{year}-12-31", "--target", TARGET, "--json"], {"facts.json": facts})
    _cache[key] = answer
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return answer


_corpus: dict = {}  # The pinned bundle's rules, by its pin: {"pin", "rules": {(id, version): rule}, "facts": {id: label}}.


def corpus():
    """The pinned corpus's federal rules (each with its formula and parameters) and its facts' labels, from
    `main.js corpus export`: read once per run of the app, since the bundle is pinned."""
    pinned = pin()["files"]["main.js"]
    if _corpus.get("pin") != pinned:
        exported = run(["corpus", "export"])
        keep = ("id", "version", "title", "citation", "formula", "parameters")
        rules = {(rule["id"], rule["version"]): {key: rule.get(key) for key in keep} for rule in exported["rules"] if rule["id"].startswith("us.federal.")}
        _corpus.clear()
        _corpus.update({"pin": pinned, "rules": rules, "facts": {fact["id"]: fact_label(fact) for fact in exported["facts"]}})
    return _corpus


def fact_label(fact):
    """A fact's description up to its first aside ("Wages, salaries, tips (Form W-2 box 1), in dollars" → "Wages, salaries, tips")."""
    return plain(fact.get("description") or fact["id"])


def plain(text):
    """A title or description without its asides, as a label."""
    text = text.strip()
    for mark in (" (", " — ", ". ", "; ", ", in dollars"):
        text = text.split(mark)[0]
    return text.rstrip(".:,")


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


# Enum values as the worksheet says them.
WORDS = {"single": "single", "mfj": "married filing jointly", "mfs": "married filing separately", "hoh": "head of household",
         "qss": "qualifying surviving spouse", "self": "self-only", "family": "family"}


def proof_worksheet(proof, assumptions, sources, year, status):
    """The proof tree as a worksheet (finance/worksheet.py). The proof records each rule's value and the values it read, but
    not its arithmetic, so each rule is re-run from its formula in the pinned corpus over those values: that shows each
    step (and which branch applied), and checks it against the engine's value. A rule that can't be re-run, or comes out
    differently, is `opaque`. A memoized rule appears once in full and elsewhere without children."""
    found = corpus()
    full, facts = {}, {}
    stack = [proof["root"]]
    while stack:
        item = stack.pop()
        if not isinstance(item, dict):
            continue
        if item.get("kind") == "rule" and "children" in item:
            full.setdefault(item["ruleId"], item)
        elif item.get("kind") in ("fact", "assumption"):
            facts.setdefault(item["factId"], item)
        stack.extend(item.get("children") or [])
    aliases = {item["resolvedFrom"]: rule for rule, item in full.items() if item.get("resolvedFrom")}  # A rule another one overrode.
    labels = {**found["facts"], **{rule: plain(item.get("title") or rule) for rule, item in full.items()}}
    labels |= {base: labels[rule] for base, rule in aliases.items()}
    rationale = {item.get("factId"): item.get("rationale") or "" for item in assumptions or []}
    nodes, refs = {}, {rule: rule for rule in [*full, *aliases]}
    for fact, item in facts.items():
        kind, value = worksheet.typed(item["value"])
        key = refs[fact] = f"fact:{fact}"
        source = {"assumed": rationale.get(fact) or "the engine's documented default"} if item["kind"] == "assumption" else {"fields": sources.get(fact, [])}
        nodes[key] = worksheet.node(key, found["facts"].get(fact, fact), "fact", value if kind == "money" else None, source=source,
                                    count=value if kind == "int" else None,
                                    value=None if kind in ("money", "int") else ("yes" if value else "no") if kind == "bool" else WORDS.get(value, value))
    law = {"year": year, "filing_status": status}
    for item in full.values():
        nodes.update(rule_nodes(item, found["rules"], aliases, refs, labels, law))
    for base, rule in aliases.items():
        if rule in nodes:
            nodes[base] = worksheet.node(base, labels[rule], "sum", nodes[rule]["amount_minor"], [rule], nodes[rule]["cite"],
                                         when=[f"{labels[rule]} applies, in place of the general rule"])
    return nodes


def rule_nodes(item, rules, aliases, refs, labels, law):
    """One applied rule's nodes: its formula re-run over the values it read, or one `opaque` node when that can't be done."""
    kind, amount = worksheet.typed(item["value"])
    if kind != "money":
        return {}  # A yes/no rule only decides a branch: the branch's `when` says it in words.
    rule, title = item["ruleId"], plain(item.get("title") or item["ruleId"])
    cite = (item.get("citation") or {}).get("source", "")
    values = {name: worksheet.typed(value) for name, value in (item.get("inputs") or {}).items()}
    values |= {base: values[rule_id] for base, rule_id in aliases.items() if rule_id in values}
    spec = rules.get((rule, item.get("ruleVersion")))
    reason = "its rule isn't in the pinned corpus"
    if spec:
        made: dict = {}
        try:
            top = worksheet.Evaluator(rule, title, cite, values, refs, labels, spec.get("parameters"), law, made, WORDS).run(spec["formula"])
            if top.value == amount:
                return made
            reason = f"re-running its rule gives {worksheet.shown(top.value)}"
        except (worksheet.Unsupported, KeyError, TypeError, ValueError) as exc:
            reason = f"its rule couldn't be re-run ({str(exc)[:120]})"
    read = item.get("inputs") or {}
    money = [refs[name] for name, (value_kind, _) in values.items() if value_kind == "money" and name in read and name in refs]
    return {rule: worksheet.node(rule, title, "opaque", amount, money, cite, detail={"reason": reason})}


class OpenTaxEngine:
    name = "opentax"  # For the records only: the page shows the slot's label (finance/tax_engine.py).
    opaque_lines: frozenset = frozenset()  # Every line is broken down to the law and the facts sent.
    tolerance_minor = 0  # It works in exact cents.

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
        # FEATURES (finance/tax_engine.py) it covers: none of them yet (docs/taxes.md "The tax engines" lists each gap).
        return Capabilities(years=YEARS, statuses=STATUSES, features=frozenset(), states=frozenset())

    def calculate(self, value: ReturnInput, context, label="The tax engine"):
        sources: dict = {}
        facts, notes = facts_for(value, sources)
        try:
            answer = evaluate(facts, value.year)
        except EngineFailed as exc:
            return self.empty(value, [f"{label} {exc}"])
        if not answer.get("ok"):
            return self.refused(value, answer.get("error") or {}, notes, label)
        result = self.shaped(value, answer, context, notes, slot_label=label)
        result["raw"]["fact_sources"] = sources
        return result

    def worksheet(self, result):
        """How this return was worked out, node by node (finance/worksheet.py): the proof's rules re-run from the corpus,
        the facts sent with their ReturnInput fields, and the lines' own nodes."""
        raw = result.get("raw") or {}
        nodes = proof_worksheet(raw["proof"], raw.get("assumptions"), raw.get("fact_sources") or {}, result["year"], result["filing_status"]) \
            if raw.get("proof") else {}
        return {**nodes, **(raw.get("line_nodes") or {})}

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
        lines = Lines()
        line = lines.add

        def got(rule):
            return (rules.get(rule) or {}).get("cents") or 0

        def how(rule, extra=""):
            found = rules.get(rule)
            text = f"{found['title']} ({found['cite']})" if found else ""
            return "; ".join(part for part in (extra, text) if part)

        def node(rule):
            """The rule's node in the worksheet (proof_worksheet), when the engine applied it."""
            return rule if rule in rules else None

        def present(*names):
            return [name for name in names if name in rules]
        gains = present("us.federal.schedule_d.ordinary_st_gain", "us.federal.schedule_d.preferential_lt_gain", "us.federal.capital_loss_ordinary_offset")
        capital = got("us.federal.schedule_d.ordinary_st_gain") + got("us.federal.schedule_d.preferential_lt_gain") - got("us.federal.capital_loss_ordinary_offset")
        capital_node = lines.made("capital", "Capital gain or loss", "sum", capital, gains,
                                  signs=[-1 if name.endswith("offset") else 1 for name in gains]) if gains else None
        lines.income(value, capital, got("us.federal.taxable_social_security"),
                     capital_how=how("us.federal.capital_loss_ordinary_offset", "Schedule D netting; a loss counts up to $3,000"),
                     social_security_how=how("us.federal.taxable_social_security", f"of {format_minor(value.social_security_benefits, CURRENCY)} received"),
                     dividends_how=f"qualified: {format_minor(value.qualified_dividends, CURRENCY)}",
                     business_how="; ".join(f"{business.name}: {format_minor(business.income - business.expenses, CURRENCY)}" for business in value.businesses),
                     capital_node=capital_node, social_security_node=node("us.federal.taxable_social_security"))
        agi = got("us.federal.agi")
        known_adjustments = {"se_half": ("us.federal.se_tax_half_deduction", "Half of self-employment tax"), "hsa": ("us.federal.hsa_deduction", "HSA contributions (not through payroll)"),
                             "se_health": ("us.federal.sehi_deduction", "Self-employed health insurance"), "ira": ("us.federal.ira_deduction", "Traditional IRA deduction"),
                             "sep": ("us.federal.sep_deduction", "SEP or solo 401(k) contributions")}
        above = got("us.federal.above_the_line_adjustments")
        student_loan = got("us.federal.student_loan_interest_deduction")
        lines.total_income(agi + above + student_loan, lines.made("total_income", "Total income: AGI with the adjustments added back", "sum", agi + above + student_loan,
                                                                  present("us.federal.agi", "us.federal.above_the_line_adjustments",
                                                                          "us.federal.student_loan_interest_deduction")))
        listed, listed_nodes = 0, []
        for key, (rule, label) in known_adjustments.items():
            if got(rule):
                listed += line(f"adjust_{key}", label, -got(rule), how(rule), "adjustments", node=rule) * -1
                listed_nodes.append(rule)
        if above - listed:
            line("adjust_other", "Educator expenses and other adjustments", -(above - listed), how("us.federal.above_the_line_adjustments"), "adjustments",
                 node=lines.made("adjust_other", "Educator expenses and other adjustments", "difference", above - listed,
                                 ["us.federal.above_the_line_adjustments", *listed_nodes]))
        if student_loan:
            line("adjust_student_loan", "Student-loan interest", -student_loan, how("us.federal.student_loan_interest_deduction"), "adjustments",
                 node="us.federal.student_loan_interest_deduction")
        line("agi", "Adjusted gross income (AGI)", agi, section="total", node=node("us.federal.agi"))
        # Deduction: standard (with the charitable deduction for non-itemizers) or itemized, as the engine elected.
        standard, itemized = got("us.federal.standard_deduction"), got("us.federal.itemized_deductions")
        election, nonitemizer = got("us.federal.deduction_election"), got("us.federal.charitable_deduction_nonitemizer")
        itemizing = bool(itemized) and election == itemized and (election != standard + nonitemizer or bool(value.itemize))
        elected = "us.federal.itemized_deductions" if itemizing else "us.federal.standard_deduction"
        line("deduction", "Itemized deductions" if itemizing else "Standard deduction", -(itemized if itemizing else standard),
             f"itemized {format_minor(itemized, CURRENCY)} against standard {format_minor(standard, CURRENCY)}", "deductions",
             node=node(elected) or lines.zero("deduction", "Deduction"))
        shown, shown_nodes = itemized if itemizing else standard, present(elected)
        if not itemizing and nonitemizer:
            shown += line("charity_nonitemizer", "Charitable deduction (not itemizing)", -nonitemizer, how("us.federal.charitable_deduction_nonitemizer"), "deductions",
                          node="us.federal.charitable_deduction_nonitemizer") * -1
            shown_nodes.append("us.federal.charitable_deduction_nonitemizer")
        senior = got("us.federal.senior_deduction")
        if senior:
            shown += line("senior", "Senior deduction", -senior, how("us.federal.senior_deduction"), "deductions", node="us.federal.senior_deduction") * -1
            shown_nodes.append("us.federal.senior_deduction")
        before_qbi = got("us.federal.taxable_income_before_qbi")
        # Taxable income before the QBI deduction isn't below zero: when the deductions are larger than AGI, what's left
        # isn't other deductions (the taxable income line shows the floor as the engine applies it).
        rest = max(0, max(0, agi - before_qbi) - shown)
        if rest:
            gap = lines.made("other_deductions~gap", "AGI less taxable income before the QBI deduction", "difference", agi - before_qbi,
                             present("us.federal.agi", "us.federal.taxable_income_before_qbi")) if agi >= before_qbi else None
            line("other_deductions", "Tips, overtime and car-loan interest deductions", -rest, "the engine's other deductions", "deductions",
                 node=lines.made("other_deductions", "Tips, overtime and car-loan interest deductions", "difference", rest, [gap, *shown_nodes]) if gap else None)
        qbi = got("us.federal.qbi_deduction")
        if qbi:
            line("qbi", "Qualified business income deduction", -qbi, how("us.federal.qbi_deduction"), "deductions", node="us.federal.qbi_deduction")
        taxable = line("taxable_income", "Taxable income", got("us.federal.taxable_income"), section="total", node=node("us.federal.taxable_income"))
        # Tax, alternative minimum tax and credits.
        # Below $100,000 of taxable income the Tax Table rule stands in for the general one.
        table_rule = "us.federal.income_tax_before_credits.tax_table"
        tax_rule = "us.federal.income_tax_before_credits" if "us.federal.income_tax_before_credits" in rules else table_rule
        tax = got(tax_rule)
        line("tax", "Tax", tax, how(tax_rule, "the Tax Table" if tax_rule == table_rule else "the rate schedules and the capital gains worksheet"), "tax",
             node=node(tax_rule) or lines.zero("tax", "Tax"))
        alternative = got("us.federal.amt")
        if alternative:
            line("amt", "Alternative minimum tax", alternative, how("us.federal.amt"), "tax", node="us.federal.amt")
        after = got("us.federal.income_tax_after_credits")
        credited, credit_nodes = 0, []
        for key, rule, label in (("dependent_care", "us.federal.cdcc", "Child and dependent care credit"),
                                 ("education", "us.federal.education.nonrefundable", "Education credits (nonrefundable part)"),
                                 ("savers", "us.federal.savers_credit", "Saver's credit"),
                                 ("child", "us.federal.ctc", "Child tax credit and credit for other dependents")):
            if got(rule):
                credited += line(f"credit_{key}", label, -got(rule), how(rule), "credits", node=rule) * -1
                credit_nodes.append(rule)
        if tax + alternative - after - credited:
            parts = [*present(tax_rule, "us.federal.amt"), *present("us.federal.income_tax_after_credits"), *credit_nodes]
            line("credit_other", "Other credits", -(tax + alternative - after - credited), "adoption, elderly or disabled, and others", "credits",
                 node=lines.made("credit_other", "Other credits: the tax less the tax after credits and the credits above", "sum",
                                 tax + alternative - after - credited, parts, signs=[1 if name in (tax_rule, "us.federal.amt") else -1 for name in parts]))
        other = got("us.federal.other_taxes")
        listed, listed_nodes = 0, []
        for key, rule, label in (("se", "us.federal.se_tax", "Self-employment tax"), ("additional_medicare", "us.federal.additional_medicare_tax", "Additional Medicare tax"),
                                 ("niit", "us.federal.niit", "Net investment income tax")):
            if got(rule):
                listed += line(f"other_{key}", label, got(rule), how(rule), "other_taxes", node=rule)
                listed_nodes.append(rule)
        if other - listed:
            line("other_other", "Other taxes", other - listed, "10% on early distributions, 20% on HSA money, household employment, excess premium credit", "other_taxes",
                 node=lines.made("other_other", "Other taxes", "difference", other - listed, ["us.federal.other_taxes", *listed_nodes]))
        total_tax = line("total_tax", "Total tax", after + other, section="total",
                         node=lines.made("total_tax", "Total tax: the tax after credits plus other taxes", "sum", after + other,
                                         present("us.federal.income_tax_after_credits", "us.federal.other_taxes")))
        # Payments are added up by the app (tax_engine.completed); refundable credits come from the engine.
        refundable = got("us.federal.refundable_credits")
        credits = [(key, label, got(rule), how(rule), node(rule)) for key, rule, label in (
            ("eitc", "us.federal.eitc", "Earned income credit"), ("actc", "us.federal.actc", "Additional child tax credit"),
            ("aotc", "us.federal.education.aotc_refundable", "American opportunity credit (refundable part)"), ("ptc", "us.federal.ptc.net", "Net premium tax credit"))]
        if got(TARGET) != total_tax - refundable:
            notes.append(f"The engine's net tax ({format_minor(got(TARGET), CURRENCY)}) differs from the lines above; check the return.")
        defaults = [item.get("factId", "") for item in answer.get("assumptions", []) if item.get("source") == "default"]
        notes += [f"Worked out by {slot_label}: every line follows a cited rule. It relied on {len(defaults)} documented defaults for things not "
                  "entered (e.g. not blind, not claimed as a dependent)."]
        return completed(value, lines, agi=agi, taxable=taxable, tax=tax, total_tax=total_tax, refundable=refundable, refundable_lines=credits,
                         context=context, notes=notes, slot_label=slot_label, refundable_node=node("us.federal.refundable_credits"),
                         raw={"corpus_merkle_root": answer.get("corpusMerkleRoot"), "artifact_hash": answer.get("artifactHash"),
                              "facts": answer["proof"].get("facts"), "assumptions": answer.get("assumptions"), "proof": answer["proof"]})
