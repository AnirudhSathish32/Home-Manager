"""Tax engines (docs/taxes.md "The tax engines"): the year's return worked out behind one interface, so an engine can be added or
replaced without changing the Taxes page, Tax Zen, What If or the CPA pack.

Engines are numbered slots: the app says "Engine 1", "Engine 2" (ENGINES, in order), never an engine's own name. The
implementation behind a slot (its name, version and pinned SHA-256) is kept in the calculation records only.

The profile is tax_return.ReturnInput (whole-year amounts in cents, from tax_year.merge). Every engine returns one dict
shape (lines in Form 1040 order with how each was worked out, the result, `missing`, `needs` and `notes`), plus `engine`
({slot, label, version}) and `unsupported`. An engine's own output is kept in `raw` (with the implementation as
`raw["engine"]`) and never sent to the page.

Before an engine runs, the features the profile uses are checked against what it covers. A profile it doesn't cover
gets no estimate: `unsupported` names what's outside it. Nothing is approximated silently. Engine-specific behavior lives
in the engine's class only.
"""

from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import logging
import sqlite3
from typing import Protocol

from ..core.logs import log_failure
from ..core.money import format_minor, percent_text
from ..library.storage import now
from . import worksheet as worksheets
from .tax_return import CURRENCY, ReturnInput, marginal, rate, state_return

log = logging.getLogger(__name__)

STATUSES = frozenset({"single", "married_joint", "head_of_household"})
# Two engines agree on a line within a dollar: forms may be worked in whole dollars (Schedule SE) or cents. A line an
# engine works out approximately carries its own wider `within` (cents).
AGREE_WITHIN = 100
MEDICARE_RATE_BP = 145  # IRC §3101(b)(1): the employee's Medicare rate; withholding above it is Additional Medicare tax paid.
# Facts an engine can ask for that the app collects, by the fact's id: where to enter them. Every engine asks by these ids.
NEEDS = {"mortgageAverageBalance": "the mortgage's average balance for the year (Deductions; a Form 1098 or a loan with its rate fills it)",
         "hsaCoverage": "the HSA's coverage, self-only or family (Adjustments)",
         "occupation": "the job the tips are from (Deductions → Tipped occupation)",
         "isAtLeastAge25": "your birth year (Settings), for the earned income credit",
         "isAge65OrOlder": "your birth year (Settings)", "spouseIsAge65OrOlder": "your spouse's birth year (Your spouse on this return)"}
PAYMENTS = (("withheld", "Federal income tax withheld"), ("additional_medicare", "Additional Medicare tax withheld"), ("estimated", "Estimated tax paid"))
# What a profile can use that an engine may not cover. Each is named on the page when it isn't.
FEATURES = {
    "two_self_employed": "self-employment income for both spouses (Schedule SE for each)",
    "joint_educator": "educator expenses on a joint return (each spouse has a separate limit)",
    "force_standard": "taking the standard deduction when itemizing is larger",
    "energy_credit": "the energy efficient home improvement credit",
    "other_credits": "other nonrefundable credits typed in",
    "other_refundable_credits": "other refundable credits typed in",
    "many_aotc_students": "the American opportunity credit for more than three students",
}


def requirements(value: ReturnInput):
    """The FEATURES this profile uses."""
    owners = {business.owner for business in value.businesses if business.income or business.expenses}
    used = {
        "two_self_employed": len(owners) > 1,
        "joint_educator": value.filing_status == "married_joint" and value.educator_expenses > 0,
        "force_standard": value.itemize is False,
        "energy_credit": value.energy_home_expenses > 0,
        "other_credits": value.other_credits > 0,
        "other_refundable_credits": value.other_refundable_credits > 0,
        "many_aotc_students": sum(1 for student in value.students if student.aotc and student.expenses) > 3,
    }
    return {key for key, on in used.items() if on}


@dataclass(frozen=True)
class Capabilities:
    years: frozenset[int] | None = None  # None: any year.
    statuses: frozenset[str] = STATUSES
    features: frozenset[str] = frozenset(FEATURES)
    states: frozenset[str] | None = None  # Full state returns; others get the simplified state return, labeled.


@dataclass
class TaxContext:
    """What the app has for the year: the federal and state tax table rows (confirmed or proposed). An engine uses what
    it needs: the federal brackets give the marginal rate, the state table the simplified state return."""
    federal: dict | None = None
    state_table: dict | None = None


class TaxEngine(Protocol):
    name: str  # The implementation, for the records only; the app shows the slot's label.
    # Return lines whose node may be `opaque` (the engine doesn't break them down), and how far a worksheet step may be
    # off its op in cents (an engine working in float dollars rounds each value to the cent).
    opaque_lines: frozenset[str]
    tolerance_minor: int

    def version(self) -> dict: ...

    def readiness(self) -> str | None: ...

    def capabilities(self) -> Capabilities: ...

    def calculate(self, value: ReturnInput, context: TaxContext, label: str) -> dict: ...

    def worksheet(self, result: dict) -> dict: ...


def first_engine():
    from .engines.opentax import OpenTaxEngine
    return OpenTaxEngine()


def second_engine():
    from .engines.taxcalc import TaxCalculatorEngine
    return TaxCalculatorEngine()


# Slots, numbered in this order ("Engine 1", ...). A new engine is a new slot; replacing one keeps its slot.
ENGINES = {"engine_1": first_engine, "engine_2": second_engine}
DEFAULT = "engine_1"
# Engine names saved before the slots: each maps to the slot that now does its work.
LEGACY = {"builtin": "engine_1", "opentax": "engine_1"}


def label_of(slot):
    return f"Engine {list(ENGINES).index(slot) + 1}"


def slot_of(name):
    """The slot for a saved engine setting (a slot, or an engine name saved before the slots)."""
    slot = LEGACY.get(name, name)
    if slot not in ENGINES:
        raise ValueError(f"Unknown tax engine: {name}.")
    return slot


def others(slot):
    """The other slots, for a second opinion."""
    return [key for key in ENGINES if key != slot]


def shown(slot, engine: TaxEngine):
    """What the page and the assistant see of an engine: its slot, label and version, never its name."""
    return {"slot": slot, "label": label_of(slot), "version": engine.version().get("version", "")}


def pin_of(slot):
    """The pinned SHA-256 of the engine in this slot: part of what a tax figure's trace hashes, so a changed engine marks
    figures shown before it as stale (core/trace.py remember)."""
    return ENGINES[slot_of(slot)]().version().get("pin_sha256")


def readiness(slot=DEFAULT):
    """Whether the engine in this slot can run on this computer (Settings shows it before tax season)."""
    slot = slot_of(slot)
    engine = ENGINES[slot]()
    label = label_of(slot)
    problem = engine.readiness()
    years = engine.capabilities().years
    return {"slot": slot, "label": label, "ready": problem is None, "note": f"{label} {problem}" if problem else
            f"Taxes are worked out on this computer by {label}" + (f", for {', '.join(str(year) for year in sorted(years))} returns." if years else ".")}


def payments(value: ReturnInput):
    """What's been paid, added up by the app for every engine: withholding (every job and 1099 box 4), the Medicare
    withheld above 1.45% (Additional Medicare tax paid) and estimated tax."""
    return {"withheld": sum(job.federal_withheld for job in value.jobs) + value.other_federal_withholding,
            "additional_medicare": sum(max(0, job.medicare_withheld - rate(job.medicare_wages, MEDICARE_RATE_BP)) for job in value.jobs),
            "estimated": value.federal_estimated_paid}


class Lines(list):
    """A return's lines as every engine shows them: {key, label, amount_minor, how, section, node, within?}. The income lines
    from the input and the total-income reconciliation are shaped here once, so the engines can't drift apart.

    `node` is the line's node in the engine's worksheet (finance/worksheet.py). A line the app or the adapter works out
    itself (a value sent as is, a residual, a payment) gets its own `line:<key>` node, kept in `nodes`."""

    def __init__(self):
        super().__init__()
        self.nodes: dict = {}

    def add(self, key, label, amount, explained="", section="", within=0, node=None):
        self.append({"key": key, "label": label, "amount_minor": amount, "how": explained, "section": section, "node": node,
                     **({"within": within} if within else {})})
        return amount

    def fact(self, key, label, amount, fields, cite=""):
        """A node for a value sent as is: the ReturnInput fields it comes from, [field, sign] ("jobs.wages" adds up every
        job's; "jobs.0.wages" is one job's)."""
        name = f"line:{key}"
        self.nodes[name] = worksheets.node(name, label, "fact", amount, cite=cite, source={"fields": [list(item) for item in fields]})
        return name

    def made(self, key, label, op, amount, inputs, signs=None, detail=None, cite=""):
        """A node the adapter works out itself from other nodes (a residual line, a total)."""
        name = f"line:{key}"
        self.nodes[name] = worksheets.node(name, label, op, amount, inputs, cite, detail={**(detail or {}), **({"signs": signs} if signs else {})})
        return name

    def zero(self, key, label):
        """A node for a line the engine didn't work out at all: nothing on this return."""
        name = f"line:{key}"
        self.nodes[name] = worksheets.node(name, f"{label}: none on this return", "constant", 0)
        return name

    def income(self, value: ReturnInput, capital, social_security, capital_how="", social_security_how="", dividends_how="", business_how="",
               capital_node=None, social_security_node=None):
        """The income section: what was sent, with the engine's capital gain or loss and taxable Social Security (and their
        nodes in its worksheet)."""
        jobs = len(value.jobs)
        sent = (("wages", "Wages (every job's W-2 box 1)", sum(job.wages for job in value.jobs), f"{jobs} job{'s' if jobs != 1 else ''}", "jobs.wages"),
                ("interest", "Taxable interest", value.interest, "", "interest"),
                ("dividends", "Ordinary dividends", value.ordinary_dividends, dividends_how, "ordinary_dividends"))
        for key, label, amount, explained, field in sent:
            self.add(key, label, amount, explained, "income", node=self.fact(key, label, amount, [[field, 1]]))
        self.add("capital", "Capital gain or loss", capital, capital_how, "income", node=capital_node or self.zero("capital", "Capital gain or loss"))
        rest = (("distributions", "Taxable retirement distributions", value.retirement_distributions, "", "retirement_distributions"),
                ("business", "Business profit or loss (Schedule C)", sum(business.income - business.expenses for business in value.businesses), business_how,
                 "businesses.profit"),
                ("unemployment", "Unemployment", value.unemployment, "", "unemployment"),
                ("hsa_nonqualified", "HSA money not spent on medical care", value.hsa_nonqualified, "", "hsa_nonqualified"),
                ("other_income", "Other income", value.other_income, "", "other_income"))
        for key, label, amount, explained, field in rest:
            self.add(key, label, amount, explained, "income", node=self.fact(key, label, amount, [[field, 1]]))
        self.add("social_security", "Taxable Social Security benefits", social_security, social_security_how, "income",
                 node=social_security_node or self.zero("social_security", "Taxable Social Security benefits"))

    def total_income(self, total, node=None):
        """The engine's total income (node: its node in the worksheet), with a line for what it counts beyond the lines above."""
        income = [item for item in self if item["section"] == "income"]
        counted = sum(item["amount_minor"] for item in income)
        if counted != total:
            residual = self.made("income_engine", "Other income as the engine counts it", "difference", total - counted,
                                 [node, *(item["node"] for item in income)]) if node else None
            self.add("income_engine", "Other income as the engine counts it", total - counted, "the engine's total income less the lines above", "income",
                     node=residual)
        self.add("total_income", "Total income", total, section="total", node=node)


def payment_node(lines: Lines, value: ReturnInput, key, label, amount):
    """A payment line's node: what the app added up (payments), from the return's inputs."""
    if key == "withheld":
        return lines.fact("pay_withheld", label, amount, [["jobs.federal_withheld", 1], ["other_federal_withholding", 1]])
    if key == "estimated":
        return lines.fact("pay_estimated", label, amount, [["federal_estimated_paid", 1]])
    parts = []  # Additional Medicare tax paid: each job's Medicare withholding above 1.45% of its Medicare wages.
    for index, job in enumerate(value.jobs):
        above = job.medicare_withheld - rate(job.medicare_wages, MEDICARE_RATE_BP)
        if above <= 0:
            continue
        stem = f"pay_additional_medicare~{index}"
        withheld = lines.fact(f"{stem}.w", f"{job.name}: Medicare tax withheld", job.medicare_withheld, [[f"jobs.{index}.medicare_withheld", 1]])
        wages = lines.fact(f"{stem}.m", f"{job.name}: Medicare wages", job.medicare_wages, [[f"jobs.{index}.medicare_wages", 1]])
        employee = lines.made(f"{stem}.r", f"1.45% of {job.name}'s Medicare wages", "rate", rate(job.medicare_wages, MEDICARE_RATE_BP), [wages],
                              detail={"num": MEDICARE_RATE_BP, "den": 10000, "rate": "1.45%", "round": "half-even"}, cite="26 U.S.C. § 3101(b)(1)")
        parts.append(lines.made(stem, f"{job.name}: withheld above 1.45%", "difference", above, [withheld, employee]))
    return lines.made("pay_additional_medicare", label, "sum", amount, parts)


def completed(value: ReturnInput, lines, *, agi, taxable, tax, total_tax, refundable, refundable_lines, context, notes, slot_label, raw,
              refundable_node=None):
    """An engine's return finished the same way for every engine: the payment lines, the refundable credits the engine
    worked out ([(key, label, cents, how, node)]; the rest as "Other refundable credits", from refundable_node), the result
    and the simplified state return. lines: the engine's Lines so far; their own nodes go to raw["line_nodes"]."""
    line = lines.add
    paid_now = payments(value)
    for key, label in PAYMENTS:
        if paid_now[key]:
            line(f"pay_{key}", label, paid_now[key], section="payments", node=payment_node(lines, value, key, label, paid_now[key]))
    listed, nodes = 0, []
    for key, label, amount, explained, node in refundable_lines:
        if amount:
            listed += line(f"pay_{key}", label, amount, explained, "payments", node=node)
            nodes.append(node)
    if refundable - listed:
        other = lines.made("pay_other", "Other refundable credits", "difference", refundable - listed, [refundable_node, *nodes]) if refundable_node else None
        line("pay_other", "Other refundable credits", refundable - listed, "refundable adoption credit and others", "payments", node=other)
    paid = line("total_payments", "Total payments", sum(paid_now.values()) + refundable, section="total")
    raw = {**raw, "line_nodes": lines.nodes}
    result = paid - total_tax
    state = state_return(value, agi, context.state_table)
    if state:
        state["note"] = state.get("note", "") + f" ({slot_label} has no full state return here.)"
    brackets = json.loads(context.federal["brackets_json"]) if context.federal and context.federal.get("status") == "verified" else None
    top = marginal(taxable, brackets) if brackets else None
    return {"complete": True, "year": value.year, "filing_status": value.filing_status,
            "lines": [{**item, "display": format_minor(item["amount_minor"], CURRENCY)} for item in lines],
            "agi_minor": agi, "taxable_minor": taxable, "tax_minor": tax, "total_tax_minor": total_tax, "payments_minor": paid,
            "withheld_minor": paid_now["withheld"] + paid_now["additional_medicare"], "estimated_minor": value.federal_estimated_paid,
            "refundable_credits_minor": refundable, "result_minor": result, "result": {"refund": result > 0, "display": format_minor(abs(result), CURRENCY)},
            "marginal_bp": top, "marginal_percent": percent_text(top), "missing": [], "needs": [], "notes": notes, "state": state, "raw": raw}


def not_covered(value: ReturnInput, reasons, unsupported):
    """The result when an engine can't work out this return: no estimate, and why."""
    return {"complete": False, "year": value.year, "filing_status": value.filing_status, "lines": [], "notes": reasons, "missing": [], "needs": [],
            "unsupported": sorted(unsupported), "result_minor": None, "state": None}


def calculate(slot, value: ReturnInput, tables):
    """The return by the engine in this slot. tables: {jurisdiction: tax table row}."""
    slot = slot_of(slot)
    engine: TaxEngine = ENGINES[slot]()
    label = label_of(slot)
    covers = engine.capabilities()
    reasons, unsupported = [], set()
    if covers.years is not None and value.year not in covers.years:
        reasons.append(f"{label} works out {', '.join(str(year) for year in sorted(covers.years))} returns, not {value.year}.")
        unsupported.add(f"year:{value.year}")
    if value.filing_status not in covers.statuses:
        reasons.append(f"{label} doesn't cover this filing status.")
        unsupported.add(f"status:{value.filing_status}")
    outside = requirements(value) - covers.features
    if outside:
        reasons.append(f"{label} doesn't cover: " + "; ".join(FEATURES[key] for key in sorted(outside)) + ".")
        unsupported |= outside
    if unsupported:
        result = not_covered(value, reasons, unsupported)
    else:
        result = engine.calculate(value, TaxContext(tables.get("US"), tables.get(value.state) if value.state else None), label)
    result.setdefault("unsupported", [])
    result.setdefault("needs", [])
    result["engine"] = shown(slot, engine)
    result.setdefault("raw", {})["engine"] = engine.version()
    return result


WORKSHEETS_KEPT = 8
_worksheets: OrderedDict = OrderedDict()


def worksheet(slot, value: ReturnInput):
    """How the engine in this slot worked out this return, node by node ({node id: node}, finance/worksheet.py). Built only
    when a trace asks: the return is worked out again (the engine's answer cache makes that cheap; the tax tables only
    change the state return and the marginal rate, which have no nodes) and kept for the last few returns."""
    slot = slot_of(slot)
    engine: TaxEngine = ENGINES[slot]()
    key = (slot, engine.version().get("pin_sha256"), hashlib.sha256(value.model_dump_json().encode()).hexdigest())
    if key in _worksheets:
        _worksheets.move_to_end(key)
        return _worksheets[key]
    result = calculate(slot, value, {})
    if result.get("result_minor") is None:
        raise ValueError((result.get("notes") or ["There's no estimate for this return."])[0])
    nodes = engine.worksheet(result)
    _worksheets[key] = nodes
    while len(_worksheets) > WORKSHEETS_KEPT:
        _worksheets.popitem(last=False)
    return nodes


def compare(first, second):
    """Two engines' answers for the same profile, line by line (§38): every line that differs by more than AGREE_WITHIN
    (or the line's own `within`), and whether they agree on the refund or amount owed.

    A missing line counts as zero, except where an engine doesn't work that line out separately at all (its result's
    `reports` lists the lines it does; no `reports` means every line): those lines are left out of the comparison."""
    other = second.get("engine") or {}
    if second.get("result_minor") is None or first.get("result_minor") is None:
        return {"engine": other, "ready": False, "note": (second.get("notes") or [""])[0] if second.get("result_minor") is None else "This engine gave no estimate."}
    ours = {line["key"]: line for line in first["lines"]}
    theirs = {line["key"]: line for line in second["lines"]}
    keys = [key for key in list(ours) + [key for key in theirs if key not in ours]
            if all(found.get("reports") is None or key in found["reports"] for found in (first, second))]
    differ = []
    for key in keys:
        mine, its = (ours.get(key) or {}).get("amount_minor", 0), (theirs.get(key) or {}).get("amount_minor", 0)
        within = max(AGREE_WITHIN, (ours.get(key) or {}).get("within", 0), (theirs.get(key) or {}).get("within", 0))
        if abs(mine - its) > within:
            label = (ours.get(key) or theirs[key])["label"]
            differ.append({"key": key, "label": label, "this_minor": mine, "other_minor": its,
                           "display": {"this": format_minor(mine, CURRENCY), "other": format_minor(its, CURRENCY), "difference": format_minor(its - mine, CURRENCY)}})
    gap = second["result_minor"] - first["result_minor"]
    within = max([AGREE_WITHIN] + [line.get("within", 0) for line in [*first["lines"], *second["lines"]]])
    return {"engine": other, "ready": True, "agree": abs(gap) <= within and not differ, "result_difference_minor": gap,
            "display": {"other_result": format_minor(abs(second["result_minor"]), CURRENCY), "difference": format_minor(abs(gap), CURRENCY),
                        "within": format_minor(within, CURRENCY)},
            "other_refund": second["result_minor"] > 0, "lines": differ}


class TaxCalculations:
    """Each distinct return an engine worked out (tax_calculations, migration 058): never rewritten (§37)."""

    def __init__(self, store):
        self.store = store

    def record(self, unit, value: ReturnInput, result):
        """Keep this calculation unless the same engine version already worked out the same profile; its id (the row kept
        before, when it's the same). A failure is logged, never raised: the page still shows the return (and the id is None)."""
        engine = (result.get("raw") or {}).get("engine") or {}  # The implementation behind the slot.
        profile = value.model_dump_json()
        profile_hash = hashlib.sha256(profile.encode()).hexdigest()
        raw = {key: item for key, item in (result.get("raw") or {}).items() if key not in ("proof", "engine", "line_nodes")} or None
        shown = {key: item for key, item in result.items() if key not in ("raw", "comparison")}
        name, version = engine.get("name", "unknown"), str(engine.get("version", ""))
        try:
            with self.store.connection() as db:
                db.execute("INSERT OR IGNORE INTO tax_calculations(year,unit,engine,engine_version,pin_sha256,profile_hash,profile_json,result_json,raw_json,"
                           "result_minor,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                           (value.year, unit, name, version, engine.get("pin_sha256"), profile_hash, profile, json.dumps(shown, default=str),
                            json.dumps(raw, default=str) if raw else None, result.get("result_minor"), now()))
                row = db.execute("SELECT id FROM tax_calculations WHERE year=? AND unit=? AND engine=? AND engine_version=? AND profile_hash=?",
                                 (value.year, unit, name, version, profile_hash)).fetchone()
                return row["id"] if row else None
        except sqlite3.Error as exc:
            log_failure(log, "tax calculation record", exc, year=value.year, unit=unit)
            return None

    def prior(self, year, unit="me"):
        """Last year's total tax and AGI as the newest return worked out here for that year, for the estimated-tax safe
        harbor when the filed return's figures aren't typed; None when there is none."""
        with self.store.connection() as db:
            row = db.execute("SELECT result_json,created_at FROM tax_calculations WHERE year=? AND unit=? AND result_minor IS NOT NULL "
                             "ORDER BY created_at DESC,id DESC LIMIT 1", (year, unit)).fetchone()
        if not row:
            return None
        result = json.loads(row["result_json"])
        if result.get("total_tax_minor") is None:
            return None
        return {"tax_minor": result["total_tax_minor"], "agi_minor": result.get("agi_minor"),
                "source": f"Last year's tax ({format_minor(result['total_tax_minor'], CURRENCY)}) is {year}'s return as worked out here; type your filed "
                          "return's figures under “Last year's return” to replace it."}

    def list(self, year, unit="me", limit=20):
        with self.store.connection() as db:
            rows = db.execute("SELECT id,year,unit,engine,engine_version,pin_sha256,profile_hash,result_minor,created_at FROM tax_calculations "
                              "WHERE year=? AND unit=? ORDER BY created_at DESC,id DESC LIMIT ?", (year, unit, limit)).fetchall()
        return [dict(row) for row in rows]
