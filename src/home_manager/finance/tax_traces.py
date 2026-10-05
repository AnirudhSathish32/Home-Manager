"""Tax and pay figures' traces (docs/ui.md "Trace contract"; finance/traces.py has the ledger's).

A tax figure is worked out with the app's settings, tax tables and engine, so each builder here takes the app's Manager
(context) as well as the store, and re-runs what the page runs:
- the return (tax.result, tax.line): the engine's own lines run as a chain (income → total income → AGI → taxable income;
  tax, credits and other taxes → total tax; payments → total payments), so a total traces to the lines it adds up, each
  line says how the engine worked it out, and the refund or amount owed is the payments less the total tax;
- the return's inputs (tax.field, tax.job): what the records give (tax_year.gather: form boxes, sales lot by lot, tags,
  payments, what's projected), with anything typed over it;
- Tax Zen: the safe harbor, estimated tax, the likely range, the cushion, state advice and each W-4 answer;
- a pay stub's estimates (paystub.tax), a planned paycheck (paycheck.net, paycheck.line, taxzen.paycheck, taxzen.plan)
  and a plan against what happened (plan.actual).
A family return is the same with `unit` (unit-<id>): its view comes from the family's returns (Manager.family_tax), and
each member's share of an input traces on that member's copy (`member`).
"""

from datetime import date

from ..core.money import format_minor, to_minor
from ..core.trace import Recorder, build, figure, ref
from . import rules, tax_engine
from .tax_return import ReturnInput
from .tax_year import CURRENCY, JOB_FIELDS, MONEY_FIELDS, PACED_SPREAD_BP, SPREAD_FLOOR_BP, TAG_FIELDS, TaxYears, gather, rate, w4s

# A total line and the total it carries on from (None: it starts afresh).
CHAIN = {"total_income": None, "agi": "total_income", "taxable_income": "agi", "total_tax": None, "total_payments": None}
# Income lines that are one return input each.
LINE_FIELDS = {"interest": "interest", "dividends": "ordinary_dividends", "distributions": "retirement_distributions", "unemployment": "unemployment",
               "hsa_nonqualified": "hsa_nonqualified", "other_income": "other_income"}
# Return inputs a tax form's box gives (tax_year.gather), when the form is here.
FORM_BOXES = {"interest": (("1099-INT", "1"), ("1099-INT", "3")), "us_obligation_interest": (("1099-INT", "3"),),
              "ordinary_dividends": (("1099-DIV", "1a"),), "qualified_dividends": (("1099-DIV", "1b"),), "tax_exempt_interest": (("1099-INT", "8"),),
              "retirement_distributions": (("1099-R", "2a"),), "other_federal_withholding": (("1099-INT", "4"), ("1099-DIV", "4")),
              "mortgage_interest": (("1098", "1"),), "property_tax": (("1098", "10"),)}


def _year(params):
    try:
        return int(params["year"])
    except (KeyError, ValueError):
        raise ValueError("The trace needs the tax year.") from None


def scope(params):
    """The return a ref is about: its year, and the family return (unit) when it's one."""
    return {"year": _year(params), "unit": params.get("unit") or None}


def _view(context, params, result=True):
    """The tax view, as the Taxes page has it: your return, or a family return."""
    year, unit = _year(params), params.get("unit")
    if unit:
        if not context.family:
            raise ValueError("Family returns are in the family profile.")
        view = next((item["view"] for item in context.family_tax(year)["returns"] if f"unit-{item['id']}" == unit), None)
        if view is None:
            raise ValueError("That return isn't in the family.")
    else:
        view = context.tax_year(year)
    if result and view["return"].get("result_minor") is None:
        raise ValueError((view["return"].get("notes") or ["There's no estimate for this year yet."])[0])
    return view


def line_ref(where, key):
    return ref("tax.line", **where, key=key)


# The return ------------------------------------------------------------------------------------------------------

def tax_result(store, ref_text, params, context):
    """The year-end refund (positive) or amount owed (negative): total payments less total tax."""
    return result_trace(ref_text, _view(context, params), scope(params))


def result_trace(ref_text, view, where=None):
    """tax.result from a tax view already worked out (the Taxes page's), so showing it doesn't work the return out twice."""
    estimate, where = view["return"], where or {"year": view["year"]}
    recorder = Recorder()
    recorder.add("Total payments", estimate["payments_minor"], CURRENCY, trace=line_ref(where, "total_payments"))
    recorder.add("Total tax", -estimate["total_tax_minor"], CURRENCY, trace=line_ref(where, "total_tax"))
    found = build(ref_text, f"{view['year']} refund (owed if below zero)", estimate["result_minor"], CURRENCY,
                  f"Withholding, estimated tax paid and refundable credits, less the year's total tax, as {estimate['engine']['label']} works out the return.",
                  recorder, pinned(view))
    return {**found, "engine": estimate["engine"]}


def pinned(view):
    """The engine's pinned SHA-256, hashed with a return figure so a changed engine marks it stale."""
    return tax_engine.pin_of(view["return"]["engine"]["slot"])


def node_ref(where, key):
    return ref("tax.node", **where, key=key)


def worksheet_of(view):
    """The engine's worksheet for this return (tax_engine.worksheet): built when first asked, then kept."""
    return tax_engine.worksheet(view["return"]["engine"]["slot"], ReturnInput.model_validate(view["input"]))


def tax_line(store, ref_text, params, context):
    """One line of the return: a total from the lines before it, or a line as the engine worked it out."""
    view, where = _view(context, params), scope(params)
    estimate, key = view["return"], params.get("key", "")
    lines = estimate["lines"]
    index = next((number for number, line in enumerate(lines) if line["key"] == key), None)
    if index is None:
        raise ValueError("That line isn't on this return.")
    line, recorder = lines[index], Recorder()
    if line["section"] == "total":
        start = max((number for number, item in enumerate(lines[:index]) if item["section"] == "total"), default=-1) + 1
        carried = CHAIN.get(key)
        counted = 0
        if carried:
            previous = next(item for item in lines if item["key"] == carried)
            recorder.add(previous["label"], previous["amount_minor"], CURRENCY, trace=line_ref(where, carried))
            counted += previous["amount_minor"]
        for item in lines[start:index]:
            if item["section"] != "total":
                recorder.add(item["label"], item["amount_minor"], CURRENCY, trace=line_ref(where, item["key"]))
                counted += item["amount_minor"]
        if counted != line["amount_minor"]:
            recorder.add(f"As {estimate['engine']['label']} counts it (not below zero, or a limit it applies)", line["amount_minor"] - counted, CURRENCY,
                         trace=node_ref(where, line["node"]) if line.get("node") else None)
        formula = f"{line['label']}: the lines above it added up" + (", carried on from " + previous["label"] if carried else "") + "."
    elif key == "wages":
        jobs, gathered = view["input"]["jobs"], view["gathered"]["jobs"]
        for number, job in enumerate(jobs):
            known = number < len(gathered)
            recorder.add(job["name"], job["wages"], CURRENCY, trace=ref("tax.job", **where, job=gathered[number]["key"], field="wages") if known else None)
        formula = "Every job's wages (W-2 box 1): pay so far less pre-tax deductions, plus the paydays left."
    else:
        field = LINE_FIELDS.get(key)
        nodes = worksheet_of(view) if line.get("node") and not field else {}
        item = nodes.get(line.get("node"))
        if item and item["amount_minor"] == line["amount_minor"]:  # The engine's own step: shown as it is.
            return {**node_trace(ref_text, view, where, nodes, item), "label": line["label"]}
        if item and item["amount_minor"] == -line["amount_minor"]:  # A deduction or credit: the engine's step, taken away.
            recorder.add(item["label"], line["amount_minor"], CURRENCY, trace=node_ref(where, item["id"]))
            formula = f"{line['label']}: {item['label']}, as {estimate['engine']['label']} works it out, taken away."
        else:
            recorder.add(line["how"] or line["label"], line["amount_minor"], CURRENCY, trace=ref("tax.field", **where, key=field) if field else None)
            formula = f"{line['label']}, as {estimate['engine']['label']} works it out" + (f": {line['how']}" if line["how"] else "") + "."
    return {**build(ref_text, line["label"], line["amount_minor"], CURRENCY, formula, recorder, pinned(view)), "engine": estimate["engine"]}


# The engine's worksheet ------------------------------------------------------------------------------------------

FORMULAS = {"sum": "The amounts below added up", "difference": "The first amount less the others", "min": "The smaller of the amounts below",
            "max": "The larger of the amounts below", "rate": "A share of the amount below", "multiply": "The amounts below multiplied",
            "round": "The amount below rounded to the whole dollar", "lookup": "The tax on the amount below from the rate table, bracket by bracket",
            "fact": "As sent to the engine, from the return's inputs", "constant": "A fixed amount written in the rule",
            "opaque": "The engine's own value: it isn't broken down further"}


def tax_node(store, ref_text, params, context):
    """One step of how the engine worked out the return (finance/worksheet.py): its inputs, each a step of its own, down
    to the facts sent (which join the return's inputs, tax.field and tax.job) and the law (a rule card)."""
    view, where = _view(context, params), scope(params)
    nodes, key = worksheet_of(view), params.get("key", "")
    if key not in nodes:
        raise ValueError("That step isn't in this return's worksheet.")
    return node_trace(ref_text, view, where, nodes, nodes[key])


def node_trace(ref_text, view, where, nodes, item):
    """A worksheet node's trace. A sum or difference shows each input as a signed step; a smaller-of or larger-of shows the
    input it took; a rate, product, rounding or rate table lists its inputs with the rule as a card and gives the engine's
    value; a fact gives the return's inputs it came from; the law and constants are cards of their own. Where the inputs
    don't give the value under the op, a labelled row says so: no explanation is invented."""
    from . import worksheet
    estimate, recorder = view["return"], Recorder()
    engine, op, amount, detail = estimate["engine"]["label"], item["op"], item["amount_minor"], item["detail"]
    if amount is None:
        raise ValueError("That step is a count or a yes/no, not an amount: it's shown on the step that uses it.")
    inputs = [nodes[name] for name in item["inputs"] if name in nodes]
    link = lambda input_: node_ref(where, input_["id"]) if input_["op"] != "constant" else None
    counts = {input_["label"]: input_["value"] for input_ in inputs if input_["amount_minor"] is None}
    card = {"key": item["id"], "name": item["label"], "version": estimate["engine"].get("version", ""), "tax_year": view["year"],
            "source": item["cite"] or engine, "checked_on": None, "cpa_reviewed_on": None,
            "values": {**{key: value for key, value in detail.items() if key not in ("signs", "reason")}, **({"counts": counts} if counts else {})},
            "when": item["when"]}
    if op in ("sum", "difference"):
        signs = detail.get("signs") or [1 if op == "sum" or number == 0 else -1 for number in range(len(inputs))]
        for input_, sign in zip(inputs, signs):
            if input_["amount_minor"] is not None:
                recorder.add(input_["label"], sign * input_["amount_minor"], CURRENCY, trace=link(input_))
    elif op in ("min", "max"):
        for input_ in inputs:
            if input_["amount_minor"] is not None:
                recorder.input(input_["id"], input_["label"], input_["amount_minor"], CURRENCY, {"kind": "computed", "record": None}, trace=link(input_))
        taken = next((input_ for input_ in inputs if input_["amount_minor"] == amount), None)
        if taken:
            recorder.add(f"{taken['label']} (the {'smaller' if op == 'min' else 'larger'})", amount, CURRENCY, trace=link(taken))
    elif op in ("rate", "multiply", "round", "lookup", "opaque"):
        for input_ in inputs:
            if input_["amount_minor"] is not None:
                recorder.input(input_["id"], input_["label"], input_["amount_minor"], CURRENCY, {"kind": "computed", "record": None}, trace=link(input_))
        recorder.rule(card)
        recorder.add(f"As {engine} works it out, not broken down further ({detail.get('reason', 'the engine gives no steps')})" if op == "opaque"
                     else "As the rule gives it", amount, CURRENCY)
    elif op == "fact":
        fact_steps(item, view, where, recorder)
    else:  # law, constant
        recorder.rule(card)
        recorder.add(item["label"], amount, CURRENCY)
    if item["cite"] and recorder.rule_card is None:  # The law the step rests on (its amounts may be written in the rule itself).
        recorder.rule(card)
    counted = sum(step["minor"] if step["op"] == "+" else -step["minor"] for step in recorder.steps)
    if counted != amount:
        recorder.add(f"As {engine} applies it", amount - counted, CURRENCY)
    formula = (f"{detail['rate']} of the amount below" if op == "rate" else
               "The first two amounts multiplied, divided by the third" if op == "multiply" and detail.get("divide") else
               f"The law's amount for {view['year']}" if op == "law" else FORMULAS.get(op, item["label"]))
    formula += (", not below zero" if op == "max" and any(input_["op"] == "constant" and input_["amount_minor"] == 0 for input_ in inputs) else "") + "."
    if item["when"]:
        formula += " This applies because: " + "; ".join(item["when"]) + "."
    if item["cite"]:
        formula += f" ({item['cite']})"
    found = build(ref_text, item["label"], amount, CURRENCY, formula, recorder, pinned(view))
    shown = {key: item[key] for key in ("id", "op", "cite", "when", "source") if item.get(key)}
    return {**found, "engine": estimate["engine"], "node": {**shown, "reconciles": worksheet.reconciles(item, nodes, tax_engine.ENGINES[
        tax_engine.slot_of(estimate["engine"]["slot"])]().tolerance_minor)}}


def fact_steps(item, view, where, recorder):
    """A fact sent to the engine, from the return's inputs: each field (tax.field), each job's figure (tax.job), each
    business's profit; or the engine's documented default for something not entered."""
    source, amount = item["source"] or {}, item["amount_minor"]
    if "assumed" in source:
        recorder.add(f"Not entered, so the engine's documented default: {source['assumed']}", amount, CURRENCY)
        return
    entered, gathered = view["input"], view["gathered"]["jobs"]
    for field, sign in source.get("fields") or []:
        head, _, rest = field.partition(".")
        index, _, attribute = rest.rpartition(".")
        if head == "jobs" and attribute:  # "jobs.wages": every job's; "jobs.0.wages": one job's; "jobs": none of them here.
            for number in [int(index)] if index else range(len(entered["jobs"])):
                job = entered["jobs"][number]
                known = number < len(gathered) and attribute in JOB_FIELDS
                recorder.add(f"{job['name']}: {attribute.replace('_', ' ')}", sign * (job.get(attribute) or 0), CURRENCY,
                             trace=ref("tax.job", **where, job=gathered[number]["key"], field=attribute) if known else None)
        elif head == "businesses" and attribute:
            for number in [int(index)] if index else range(len(entered["businesses"])):
                business = entered["businesses"][number]
                recorder.add(f"{business['name']}: profit", sign * (business["income"] - business["expenses"]), CURRENCY)
        elif head == "students":
            recorder.add("Students' qualified education expenses", sign * sum(student["expenses"] for student in entered["students"]), CURRENCY)
        elif field in MONEY_FIELDS:
            recorder.add(field.replace("_", " ").capitalize(), sign * (entered.get(field) or 0), CURRENCY, trace=ref("tax.field", **where, key=field))


# The return's inputs ---------------------------------------------------------------------------------------------

def _typed_by(store, year, key, unit="me"):
    """The person and time a typed value was last changed (tax_input_changes)."""
    change = next((row for row in reversed(TaxYears(store).changes(year, unit=unit)) if row["key"] == key), None)
    return {"kind": "manual", "record": {"type": "tax_input", "id": key}, "actor": {"person": change["actor"], "at": change["created_at"]} if change else None}


def record_gathered(store, year, key, value, source, gathered, recorder, member=None):
    """What one return input's records add up to (tax_year.gather), from the records themselves: each tax form's box,
    each sale lot by lot, each tag line, each estimated payment; the rest as its source says, split into so far and
    projected to Dec 31 when part of it is projected."""
    remaining, source = value, source or "From the records"
    if key in FORM_BOXES and any(form in source for form, _ in FORM_BOXES[key]):
        with store.connection() as db:
            for form, box in FORM_BOXES[key]:
                for row in db.execute("SELECT f.id,f.institution,b.amount_minor FROM tax_form_boxes b JOIN tax_forms f ON f.id=b.form_id WHERE f.review_status='verified' "
                                      "AND f.tax_year=? AND f.currency=? AND b.form=? AND b.box=? ORDER BY f.id", (year, CURRENCY, form, box)):
                    recorder.add(f"{row['institution']} {form} box {box}", row["amount_minor"], CURRENCY)
                    recorder.input(f"tax_form:{row['id']}:{form}:{box}", f"{row['institution']} {form} box {box}", row["amount_minor"], CURRENCY,
                                   {"kind": "extracted", "record": {"type": "tax_form", "id": row["id"]}})
                    remaining -= row["amount_minor"]
    elif key in ("short_term_gain", "long_term_gain") and source.startswith("Realized"):
        from .investments import Investments
        from .tax_lots import realized
        with store.connection() as db:
            taxable = [account["id"] for account in Investments(store).rows(db, True) if account["tax_treatment"] == "taxable" and account["currency"] == CURRENCY]
            found = realized(db, taxable, year, recorder, "short" if key == "short_term_gain" else "long")
        remaining -= found["short_minor" if key == "short_term_gain" else "long_minor"]
    elif source.endswith("Tagged items"):
        from .tax_tags import TaxTags
        tags = [(kind, line) for (kind, line), field in TAG_FIELDS.items() if field == key]
        for row in TaxTags(store).year(year, CURRENCY)["lines"]:
            if (row["kind"], row["line"]) in tags:
                shown = ref("tax.tags", year=year, currency=CURRENCY, kind=row["kind"], line=row["line"], member=member)
                recorder.add(f"{row['line_label']} (tagged)", row["counted_minor"], CURRENCY, trace=shown)
                remaining -= row["counted_minor"]
    elif key in ("federal_estimated_paid", "state_estimated_paid"):
        for payment in gathered["estimated_payments"]["federal_estimated" if key.startswith("federal") else "state_estimated"]:
            recorder.add(f"Paid {payment['date']}", payment["amount_minor"], CURRENCY)
            remaining -= payment["amount_minor"]
    part = gathered.get("projected", {}).get(key) or 0
    if remaining - part:
        recorder.add(f"So far: {source}" if part else source, remaining - part, CURRENCY)
    if part:
        recorder.add("Projected to Dec 31 at the same pace", part, CURRENCY)


def tax_field(store, ref_text, params, context):
    """One of the return's inputs: what the records give (tax_year.gather), and anything typed over it (merge). On a
    family return, each member's share, traced on their copy."""
    view, where = _view(context, params, result=False), scope(params)
    year, key = view["year"], params.get("key", "")
    if key not in MONEY_FIELDS:
        raise ValueError("That isn't an amount on the return.")
    gathered, recorder = view["gathered"], Recorder()
    value = gathered["values"].get(key, 0)
    if where["unit"]:
        ids = {member["name"]: member["member_id"] for member, _ in family_members(context)}
        stores = {member["member_id"]: member_store for member, member_store in family_members(context)}
        for name, amount, source in gathered.get("parts", {}).get(key, []):
            member_recorder = Recorder()
            if ids.get(name) in stores:
                record_gathered(stores[ids[name]], year, key, amount, source, {"projected": {}, "estimated_payments": gathered["estimated_payments"]},
                                member_recorder, ids[name])
            if member_recorder.steps and sum(step["minor"] if step["op"] == "+" else -step["minor"] for step in member_recorder.steps) == amount:
                for step in member_recorder.steps:
                    recorder.step(f"{name}: {step['label']}", step["op"], step["minor"], CURRENCY, step["trace"])
                recorder.inputs += member_recorder.inputs
            else:
                recorder.add(f"{name}: {source or 'from their records'}", amount, CURRENCY)
    else:
        record_gathered(store, year, key, value, gathered["sources"].get(key), gathered, recorder)
    result = view["input"].get(key) or 0
    typed = (view["inputs"].get("fields") or {}).get(key)
    if typed not in (None, ""):
        recorder.add("You typed over it", result - value, CURRENCY)
        recorder.input(f"typed:{key}", "Typed over the records", result, CURRENCY, _typed_by(store, year, key, where["unit"] or "me"))
    return build(ref_text, key.replace("_", " ").capitalize(), result, CURRENCY,
                 "What the records give for the year" + (", with what you typed over it." if typed not in (None, "") else "."), recorder)


def family_members(context):
    with context.family.mutex:
        return context.family_members()


def tax_job(store, ref_text, params, context):
    """One of a job's figures for the year (tax_year.jobs): so far, plus its paydays left at the latest paycheck. A family
    return's job ("<member>:<key>") is worked out on that member's copy."""
    where, job_key, field = scope(params), params.get("job", ""), params.get("field", "")
    if field not in JOB_FIELDS:
        raise ValueError("That isn't one of a job's figures.")
    source, inner = store, job_key
    if where["unit"]:
        name, _, inner = job_key.partition(":")
        source = next((member_store for member, member_store in family_members(context) if member["name"] == name), None)
        if source is None:
            raise ValueError("That member has no shared records here.")
    recorder = Recorder()
    found = gather(source, where["year"], context.household, date.today(), recorder, (inner, field))
    job = next((item for item in found["jobs"] if item["key"] == inner), None)
    if job is None:
        raise ValueError("That job has no confirmed pay stubs this year.")
    result = job["values"][field]
    typed = (TaxYears(store).inputs(where["year"], where["unit"] or "me").get("jobs") or {}).get(job_key, {}).get(field)
    if typed not in (None, ""):
        typed_minor = to_minor(str(typed), CURRENCY)
        recorder.add("You typed over it", typed_minor - result, CURRENCY)
        recorder.input(f"typed:{job_key}:{field}", "Typed over the records", typed_minor, CURRENCY,
                       _typed_by(store, where["year"], f"job:{job_key}:{field}", where["unit"] or "me"))
        result = typed_minor
    return build(ref_text, f"{job['name']}: {field.replace('_', ' ')}", result, CURRENCY,
                 "This year's pay stubs so far, plus each payday left this year paid like the latest paycheck"
                 + (", with what you typed over it." if typed not in (None, "") else "."), recorder)


# Tax Zen ---------------------------------------------------------------------------------------------------------

def safe_harbor(store, ref_text, params, context):
    """The estimated-tax safe harbor's required payment (safe_harbor.required_payment)."""
    from .safe_harbor import required_payment
    view, where = _view(context, params), scope(params)
    recorder = Recorder()
    required, basis = required_payment(view["return"]["total_tax_minor"], view.get("prior_year"), recorder, line_ref(where, "total_tax"))
    recorder.rule(rules.rule("safe_harbor"))
    return build(ref_text, f"{view['year']} safe harbor", required, CURRENCY,
                 f"No underpayment penalty when withholding and estimated tax reach the smaller of 90% of this year's tax and 100% of last "
                 f"year's (110% when last year's AGI was over $150,000). Here: {basis}.", recorder)


def advance(store, ref_text, params, context):
    """What estimated tax payments must cover this year (tax_zen.advance_needed)."""
    from .tax_zen import advance_needed
    view, where = _view(context, params), scope(params)
    recorder = Recorder()
    needed = advance_needed(view["return"], recorder, line_ref(where, "total_tax"))
    return build(ref_text, f"{view['year']} estimated tax to cover", needed, CURRENCY,
                 "The year's total tax less withholding and refundable credits: what estimated payments must make up.", recorder)


def extra(store, ref_text, params, context):
    """Tax Zen's extra withholding a paycheck (W-4 Step 4(c)), tax_zen.extra_per_check."""
    from .tax_zen import extra_per_check
    view, where = _view(context, params), scope(params)
    job = view["zen"].get("job") or {}
    shown = (job.get("extra") or {}).get("per_check_minor")
    if shown is None:
        raise ValueError("Tax Zen isn't suggesting extra withholding this year.")
    recorder = Recorder()
    first = extra_per_check(job["goal_minor"], view["zen"]["result_minor"], job["paychecks_left"], recorder)
    if shown != first:
        recorder.add("Raised or lowered after the tax engine re-checked the answer", shown - first, CURRENCY, trace=ref("tax.result", **where))
    return build(ref_text, f"Extra withholding a paycheck at {job['name']}", shown, CURRENCY,
                 "How far the year-end result is short of your aim, spread over the paychecks a new W-4 still changes, rounded up.", recorder)


def likely_range(store, ref_text, params, context):
    """One end of the likely range (tax_year.likely_range): the return worked out again with the projected pay, withholding,
    interest and dividends moved down and up."""
    view, where, end = _view(context, params), scope(params), params.get("end", "low")
    found = view["zen"].get("range")
    if not found or end not in ("low", "high"):
        raise ValueError("There's no likely range for this return.")
    expected, shown = view["zen"]["result_minor"], found[f"{end}_minor"]
    recorder = Recorder()
    recorder.add("Where the year is expected to end", expected, CURRENCY, trace=ref("tax.result", **where))
    if shown != expected:
        recorder.add(f"With the projected figures moved {'down' if end == 'low' else 'up'} or {'up' if end == 'low' else 'down'}: "
                     f"{view['return']['engine']['label']}'s result again", shown - expected, CURRENCY)
    gathered, inputs = view["gathered"], view["inputs"]
    typed = {key for key, text in (inputs.get("fields") or {}).items() if text not in (None, "")}
    for key, part in gathered.get("projected", {}).items():
        if key not in typed and part:
            recorder.input(f"projected:{key}", f"{key.replace('_', ' ').capitalize()} still to come, moved by 25%", rate(part, PACED_SPREAD_BP), CURRENCY,
                           {"kind": "computed", "record": None})
    for job in gathered["jobs"]:
        for key, part in (job.get("projected") or {}).items():
            if part and (inputs.get("jobs") or {}).get(job["key"], {}).get(key) in (None, ""):
                spread = job.get("spread_bp", SPREAD_FLOOR_BP)
                recorder.input(f"projected:{job['key']}:{key}", f"{job['name']}: {key.replace('_', ' ')} still to come, moved by {spread / 100:g}%",
                               rate(part, spread), CURRENCY, {"kind": "computed", "record": None})
    return build(ref_text, f"The {end} end of where {view['year']} likely ends", shown, CURRENCY,
                 "The return worked out again with what's still projected (pay and its withholding by how much this year's paychecks varied, at "
                 "least 5%; interest and dividends by 25%) moved down and up. Recorded and typed values stay.", recorder)


def cushion(store, ref_text, params, context):
    """Tax Zen's cushion: extra withholding a paycheck so even the low end owes under $1,000 (tax_zen.cushion_short)."""
    from .tax_zen import cushion_short, per_check_up
    view, where = _view(context, params), scope(params)
    zen = view["zen"]
    if not zen.get("cushion"):
        raise ValueError("Tax Zen isn't suggesting a cushion this year.")
    recorder = Recorder()
    low = zen["range"]["low_minor"]
    recorder.input("low_end", "The low end of the likely range", low, CURRENCY, {"kind": "computed", "record": None},
                   trace=ref("taxzen.range", **where, end="low"))
    shown = per_check_up(cushion_short(low), zen["job"]["paychecks_left"], "Owed at the low end beyond just under $1,000", recorder)
    return build(ref_text, f"Cushion a paycheck at {zen['cushion']['job']}", shown, CURRENCY,
                 "What the low end of the likely range would owe beyond just under $1,000, spread over the paychecks a new W-4 still changes, "
                 "rounded up.", recorder)


def state_advice(store, ref_text, params, context):
    """Tax Zen's state advice: the state's year-end gap spread over the paychecks left."""
    from .tax_zen import per_check_up
    view = _view(context, params)
    zen, state = view["zen"], view["return"].get("state") or {}
    if (zen.get("state") or {}).get("per_check_minor") is None:
        raise ValueError("Tax Zen has no state advice a paycheck this year.")
    recorder = Recorder()
    shown = per_check_up(abs(state["result_minor"]), zen["job"]["paychecks_left"], f"{state['state']}'s year-end gap", recorder)
    return build(ref_text, f"{state['state']} withholding a paycheck to change", shown, CURRENCY,
                 "The state return's refund or amount owed, spread over the paychecks a new W-4 still changes, rounded up.", recorder)


def _w4_part(view, part_name):
    zen = view["zen"]
    advice = zen.get("job") or {}
    part = advice.get(part_name)
    if not part or part.get("per_check") is None:
        raise ValueError("Tax Zen has no such W-4 answer this year.")
    return advice, part


def w4(store, ref_text, params, context):
    """A paycheck's federal withholding with one of Tax Zen's W-4 answers (rest of the year, from January, or Step 3):
    Pub 15-T on the paycheck with the answer's entry, plus what payroll does beyond the W-4 as entered here."""
    from .tax_zen import withheld_with
    view, part_name = _view(context, params), params.get("part", "rest")
    advice, part = _w4_part(view, part_name)
    job = next(item for item in view["gathered"]["jobs"] if item["key"] == advice["key"])
    entries = dict(w4s(view["inputs"]).get(advice["key"], {}))
    if part.get("key") and part.get("amount") is not None:
        entries[part["key"]] = part["amount"]
    federal = _tables(context, view["year"], ["US"], view["filing_status"]).get("US")
    if not federal or federal["status"] != "verified":
        raise ValueError("The federal tax table isn't confirmed.")
    recorder = Recorder()
    withheld_with(federal, job["per_check"]["wages"], advice["frequency"], entries, advice["offset_minor"], recorder)
    label = {"rest": "for the rest of the year", "january": "from January", "step3": "with Step 3"}.get(part_name, "")
    entry = f" (W-4 {part['field']}: {format_minor(part['amount'], CURRENCY)})" if part.get("field") and part.get("amount") is not None else ""
    return build(ref_text, f"{advice['name']}: withholding a paycheck {label}{entry}", part["per_check"], CURRENCY,
                 "IRS Publication 15-T's percentage method on one paycheck with the W-4 entry, bucket by bucket, plus what payroll withholds "
                 "beyond the W-4 as entered here.", recorder)


def w4_year_end(store, ref_text, params, context):
    """Where the year ends with one of Tax Zen's W-4 answers."""
    view, where, part_name = _view(context, params), scope(params), params.get("part", "rest")
    advice, part = _w4_part(view, part_name)
    estimate, recorder = view["return"], Recorder()
    per_check = ref("taxzen.w4", **where, part=part_name)
    if part_name == "january":
        job = next(item for item in view["gathered"]["jobs"] if item["key"] == advice["key"])
        others = estimate["payments_minor"] - estimate["estimated_minor"] - job["values"]["federal_withheld"]
        recorder.add("Withholding, credits and payments from the rest of the return", others, CURRENCY)
        recorder.add(f"{advice['frequency']} paychecks × {format_minor(part['per_check'], CURRENCY)}", advice["frequency"] * part["per_check"], CURRENCY, trace=per_check)
        recorder.add("Total tax", -estimate["total_tax_minor"], CURRENCY, trace=line_ref(where, "total_tax"))
        formula = "A whole year at this paycheck's withholding, with the rest of the return as it is."
    else:
        left = advice["paychecks_left"]
        recorder.add("Where the year ends now", view["zen"]["result_minor"], CURRENCY, trace=ref("tax.result", **where))
        change = left * (part["per_check"] - advice["per_check_now_minor"])
        recorder.add(f"{left} paychecks × {format_minor(part['per_check'] - advice['per_check_now_minor'], CURRENCY)} more withheld", change, CURRENCY, trace=per_check)
        formula = "Where the year ends now, plus the change in withholding on each paycheck the new W-4 changes."
    counted = sum(step["minor"] if step["op"] == "+" else -step["minor"] for step in recorder.steps)
    if part["year_end_minor"] != counted:
        recorder.add("As the tax engine re-checked it", part["year_end_minor"] - counted, CURRENCY, trace=ref("tax.result", **where))
    return build(ref_text, f"{advice['name']}: the year's end with this W-4", part["year_end_minor"], CURRENCY, formula, recorder)


# Pay stubs, planned paychecks and plans --------------------------------------------------------------------------

def paystub_tax(store, ref_text, params, context):
    """A pay stub's estimated income tax (a jurisdiction) or Social Security or Medicare (paystub.explain)."""
    try:
        income_id = int(params["income_id"])
    except (KeyError, ValueError):
        raise ValueError("The trace needs income_id.") from None
    part = params.get("part", "")
    record = context.ledger.record("income_record", income_id)
    recorder = Recorder()
    found = context.paystub_taxes(record, recorder, part)
    row = next((item for item in [*found["jurisdictions"], *found["fica"]] if (item.get("jurisdiction") or item.get("category")) == part), None)
    if row is None or row.get("estimate_minor") is None:
        raise ValueError("That estimate isn't on this pay stub.")
    recorder.input(f"income_record:{income_id}", f"Pay stub · {record.get('pay_date')}", record.get("gross_pay_minor") or 0, record["currency"],
                   {"kind": "extracted", "record": {"type": "income_record", "id": income_id}})
    name = row.get("name") or part.replace("_", " ").capitalize()
    return build(ref_text, f"{name} a paycheck, estimated", row["estimate_minor"], record["currency"],
                 "The year's tax on a year of paychecks like this one, bucket by bucket from the confirmed tax table, spread back over the paychecks."
                 if row.get("jurisdiction") else "The rate on this paycheck's wages, within the year's limits.", recorder)


def _paycheck(store, params, context):
    """(planner input, label, tax tables) from a ref: the paycheck's own input, or a saved plan's paycheck."""
    from .paycheck import PaycheckInput
    from .scenarios import Scenarios
    try:
        if params.get("input"):
            value, label = PaycheckInput.model_validate_json(params["input"]), "This paycheck"
        else:
            plan = Scenarios(store).input(int(params["scenario_id"])).paychecks[int(params.get("index", 0))]
            value, label = plan.paycheck, plan.label
    except (KeyError, ValueError, IndexError):
        raise ValueError("That planned paycheck can't be found.") from None
    tables = _tables(context, value.year, ["US", *([value.work_state] if value.work_state else [])], value.filing_status) if context.family \
        else context.paycheck_tables(value)
    return value, label, tables


def _tables(context, year, codes, status):
    """This library's tax tables, and in the family view each member's too (Manager.scenario_tables)."""
    if context.family:
        with context.family.mutex:
            return context.scenario_tables()(year, codes, status)
    return context.scenario_tables()(year, codes, status)


def paycheck_net(store, ref_text, params, context):
    """A planned paycheck's take-home pay, a regular paycheck or a month (paycheck.calculate)."""
    from .paycheck import calculate
    value, label, tables = _paycheck(store, params, context)
    recorder, monthly = Recorder(), params.get("per") == "month"
    result = calculate(value, tables, recorder, "monthly" if monthly else "net")
    if monthly:
        return build(ref_text, f"{label}: take-home pay a month", result["net"]["monthly_minor"], CURRENCY,
                     "The year's take-home pay, every paycheck and bonus, over twelve months.", recorder)
    return build(ref_text, f"{label}: take-home pay a paycheck", result["net"]["per_check_minor"], CURRENCY,
                 "A regular paycheck's earnings, less pre-tax deductions, taxes and post-tax deductions.", recorder)


def paycheck_line(store, ref_text, params, context):
    """One tax line of a planned paycheck, a regular paycheck's (paycheck.calculate)."""
    from .paycheck import calculate
    value, label, tables = _paycheck(store, params, context)
    category, recorder = params.get("category", ""), Recorder()
    result = calculate(value, tables, recorder, category)
    line = next((item for group in result["groups"] if group["group"] == "tax" for item in group["lines"] if item["category"] == category), None)
    if line is None or line["per_check_minor"] is None:
        raise ValueError("That tax isn't on this paycheck.")
    return build(ref_text, f"{label}: {line['label']} a paycheck", line["per_check_minor"], CURRENCY,
                 line["how"] or "As worked out for a regular paycheck.", recorder)


def _plan_result(ref_text, label, found):
    recorder = Recorder()
    recorder.add("Total payments", found["payments_minor"], CURRENCY)
    recorder.add("Total tax", -found["total_tax_minor"], CURRENCY)
    return build(ref_text, label, found["result_minor"], CURRENCY,
                 f"The year's return with this pay for a whole year: payments less total tax, as {(found.get('engine') or {}).get('label', 'the tax engine')} "
                 "works it out.", recorder)


def paycheck_tax_time(store, ref_text, params, context):
    """The paycheck planner's tax time: this paycheck alone for a full year, its refund or amount owed."""
    from .paycheck import calculate
    value, _, tables = _paycheck(store, params, context)
    found = context.paycheck_tax_time(value, calculate(value, tables), tables)
    if found.get("result_minor") is None:
        raise ValueError(found.get("note") or "No estimate for this paycheck.")
    return _plan_result(ref_text, "This paycheck for a whole year: refund (owed if below zero)", found)


def plan_tax_zen(store, ref_text, params, context):
    """A What If plan's Tax Zen: the year's return at the pay the plan ends with."""
    from .scenarios import ScenarioInput
    try:
        value = ScenarioInput.model_validate_json(params["scenario"])
        today = date.fromisoformat(params["today"])
    except (KeyError, ValueError):
        raise ValueError("The trace needs the plan and the day it was worked out.") from None
    if context.family:
        raise ValueError("Tax Zen for the family is on the Taxes page.")
    found = context.plan_tax_zen(value, context.scenario_tables(), today)
    if found.get("result_minor") is None:
        raise ValueError(found.get("note") or "No estimate for this plan.")
    return _plan_result(ref_text, f"{value.name}: refund (owed if below zero)", found)


def plan_actual(store, ref_text, params, context):
    """A figure of a plan against what happened (plan_tracking.plan_vs_actual)."""
    from . import plan_tracking
    from .scenarios import Scenarios
    from .tools import FinanceTools
    try:
        scenario_id, today = int(params["scenario_id"]), date.fromisoformat(params["today"])
    except (KeyError, ValueError):
        raise ValueError("The trace needs the plan and the day it was worked out.") from None
    part = params.get("part")
    if part == "pay":
        only = ("pay", int(params.get("index", 0)), params.get("group"), params.get("category"), params.get("figure"))
    elif part == "spending":
        only = ("spending", params.get("month"), params.get("category"))
    else:
        only = ("month", params.get("month"), params.get("figure"))
    value = context.personal_plan(scenario_id)
    recorder = Recorder()
    found = plan_tracking.plan_vs_actual(store, FinanceTools(store), Scenarios(store).get(scenario_id), context.scenario_tables(),
                                         context.plan_currency(value), today, recorder, only)
    shown = None
    if part == "pay":
        for paycheck in found["pay"]:
            for row in paycheck["rows"]:
                if row[only[4]] and row[only[4]].get("trace") == ref_text:
                    shown, label = row[only[4]], f"{paycheck['label']}: {row['label']}, {only[4]}"
    else:
        for month in found["spending"]:
            if month["month"] != only[1]:
                continue
            if part == "spending":
                row = next((row for row in month["rows"] if row["category"] == only[2]), None)
                shown, label = (row["difference"], f"{only[2]}, {only[1]}: spent against planned") if row else (None, "")
            else:
                shown, label = month[only[2]], f"{only[1]}: {only[2]}"
    if shown is None:
        raise ValueError("That figure isn't in the plan's comparison.")
    return build(ref_text, label, shown["minor"], shown["currency"], "What the plan said against what happened.", recorder)


def refs(view, unit=None):
    """The Taxes page's figures (your return, or a family return), each given its trace ref: the result, every line, the
    inputs, the jobs' figures and Tax Zen's amounts."""
    where = {"year": view["year"], "unit": unit}
    estimate, zen = view["return"], view["zen"]
    if estimate.get("result_minor") is not None:
        estimate["result_figure"] = figure(estimate["result_minor"], CURRENCY, ref("tax.result", **where))
        for line in estimate["lines"]:
            line["trace"] = line_ref(where, line["key"])
    view["gathered"]["traces"] = {key: ref("tax.field", **where, key=key) for key in view["gathered"]["values"] if key in MONEY_FIELDS}
    for job in view["gathered"]["jobs"]:
        job["traces"] = {field: ref("tax.job", **where, job=job["key"], field=field) for field in JOB_FIELDS}
    if zen.get("ready"):
        zen["safe_harbor"]["trace"] = ref("tax.safe_harbor", **where)
        if zen.get("advance"):
            zen["advance"]["trace"] = ref("taxzen.advance", **where)
        if zen.get("range"):
            zen["range"]["traces"] = {end: ref("taxzen.range", **where, end=end) for end in ("low", "high")}
        if zen.get("cushion"):
            zen["cushion"]["trace"] = ref("taxzen.cushion", **where)
        if (zen.get("state") or {}).get("per_check_minor") is not None:
            zen["state"]["trace"] = ref("taxzen.state", **where)
        job = zen.get("job") or {}
        if job.get("extra"):
            job["extra"]["trace"] = ref("taxzen.extra", **where)
        for name in ("rest", "january", "step3"):
            if (job.get(name) or {}).get("per_check") is not None:
                job[name]["traces"] = {"per_check": ref("taxzen.w4", **where, part=name)}
                if job[name].get("year_end_minor") is not None:
                    job[name]["traces"]["year_end"] = ref("taxzen.w4_year_end", **where, part=name)
    return view


TRACES = {"tax.result": tax_result, "tax.line": tax_line, "tax.node": tax_node, "tax.field": tax_field, "tax.job": tax_job, "tax.safe_harbor": safe_harbor,
          "taxzen.advance": advance, "taxzen.extra": extra, "taxzen.range": likely_range, "taxzen.cushion": cushion, "taxzen.state": state_advice,
          "taxzen.w4": w4, "taxzen.w4_year_end": w4_year_end, "paystub.tax": paystub_tax, "paycheck.net": paycheck_net,
          "paycheck.line": paycheck_line, "taxzen.paycheck": paycheck_tax_time, "taxzen.plan": plan_tax_zen, "plan.actual": plan_actual}
