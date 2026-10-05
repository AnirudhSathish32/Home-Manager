"""Engine worksheets (docs/taxes.md "The tax engines", docs/ui.md "Trace contract"): how a tax engine worked out each line
of the return, as one engine-neutral graph that the `tax.node` trace reads (finance/tax_traces.py).

Each engine's adapter produces the graph (`TaxEngine.worksheet`). A node is a dict:
`{id, label, amount_minor, op, inputs: [node ids], cite, source, when, detail}`, plus `count` and `value` (text) on a node
that isn't money (a number of steps or children, yes/no, a filing status). Ops:
- sum (inputs added, or signed by detail["signs"]), difference (the first less the rest), min, max;
- multiply (inputs multiplied; with detail["divide"], a × b ÷ c), rate (an input at detail["num"]/["den"]),
  round (to the dollar), steps (an input in whole steps of detail["unit_minor"]), lookup (detail["table"], a rate table);
- leaves: fact (a value the app sent: `source` names the ReturnInput fields, or the engine's documented default),
  law (a parameter of the law: `source` names it with its year and filing status), constant (a number written in the
  rule), opaque (the engine's value, not broken down further).
An `if` or `match` is never a node: the node takes the op of the branch taken, and `when` says why it was taken.

`Evaluator` runs one rule written in OpenTax's expression language over known values, exactly as the engine does
(integer cents, its rounding modes), and adds a node for each step. Tax-Calculator's maps are written in the same
language, so one interpreter serves both engines. A node whose inputs don't give its amount under its op doesn't
reconcile (`reconciles`): the trace says so, and the conformance test fails.
"""

from decimal import Decimal

from ..core.money import format_minor

CURRENCY = "USD"
OPS = frozenset({"sum", "difference", "min", "max", "multiply", "rate", "round", "steps", "lookup", "fact", "law", "constant", "opaque"})
LEAVES = frozenset({"fact", "law", "constant", "opaque"})
LABEL_MOST = 140


class Unsupported(Exception):
    """A rule the evaluator can't run (outside the engine's corpus, or an expression it doesn't know)."""


def node(id, label, op, amount_minor=None, inputs=(), cite="", source=None, when=(), detail=None, count=None, value=None):
    if op not in OPS:
        raise ValueError(f"Unknown worksheet op {op}.")
    found = {"id": id, "label": short(label), "op": op, "amount_minor": amount_minor, "inputs": list(inputs), "cite": cite or "",
             "source": source, "when": list(when), "detail": detail or {}}
    if count is not None:
        found["count"] = count
    if value is not None or count is not None:
        found["value"] = value if value is not None else str(count)
    return found


def short(text):
    text = " ".join(str(text).split())
    return text if len(text) <= LABEL_MOST else text[:LABEL_MOST - 1].rstrip() + "…"


def shown(minor):
    return format_minor(minor, CURRENCY)


def div_round(n, d, mode):
    """n ÷ d in whole units, rounded as OpenTax rounds (floor, ceil, half-up or half-even, away from zero for negatives
    as its BigInt arithmetic does)."""
    if d == 0:
        raise Unsupported("division by zero")
    if d < 0:
        n, d = -n, -d
    q = abs(n) // d * (1 if n >= 0 else -1)  # Truncated toward zero, as BigInt division is.
    r = n - q * d
    if r == 0:
        return q
    negative, twice = n < 0, abs(r) * 2
    if mode == "floor":
        return q - 1 if negative else q
    if mode == "ceil":
        return q if negative else q + 1
    if mode == "half-up":
        return (q - 1 if negative else q + 1) if twice >= d else q
    if mode == "half-even":
        if twice != d:
            return (q - 1 if negative else q + 1) if twice > d else q
        return q if q % 2 == 0 else q - 1 if negative else q + 1
    raise Unsupported(f"rounding mode {mode}")


def bracket_tax(amount, table):
    """Tax on an amount over a rate table [{from_minor, num, den}], each slice rounded half-up (OpenTax's `brackets`)."""
    tax = 0
    for index, row in enumerate(table):
        lower = row["from_minor"]
        if amount <= lower:
            break
        upper = table[index + 1]["from_minor"] if index + 1 < len(table) else amount
        tax += div_round((min(amount, upper) - lower) * row["num"], row["den"], "half-up")
    return tax


def percent(num, den):
    return f"{(Decimal(num) * 100 / Decimal(den)).normalize():f}%"


def number(item):
    """A node's number: its cents, or its count."""
    return item["amount_minor"] if item["amount_minor"] is not None else item.get("count")


def expected(item, nodes):
    """What the node's op gives from its inputs, or None for a leaf (or an input that isn't here)."""
    op, detail = item["op"], item["detail"]
    if op in LEAVES:
        return None
    values = [number(nodes[key]) if key in nodes else None for key in item["inputs"]]
    if not values or any(value is None for value in values):
        return None
    if op == "sum":
        return sum(value * sign for value, sign in zip(values, detail.get("signs") or [1] * len(values)))
    if op == "difference":
        return values[0] - sum(values[1:])
    if op == "min":
        return min(values)
    if op == "max":
        return max(values)
    if op == "multiply":
        if detail.get("divide"):
            return div_round(values[0] * values[1], values[2], detail.get("round", "half-up"))
        product = 1
        for value in values:
            product *= value
        return product
    if op == "rate":
        return div_round(values[0] * detail["num"], detail["den"], detail.get("round", "half-up"))
    if op == "round":
        return div_round(values[0], 100, detail.get("round", "half-up")) * 100
    if op == "steps":
        return div_round(values[0], detail["unit_minor"], detail.get("round", "floor"))
    if op == "lookup":
        return bracket_tax(values[0], detail["table"])
    return None


def reconciles(item, nodes, tolerance=0):
    """Whether the node's inputs give its number under its op (within tolerance; leaves always do)."""
    if item["op"] in LEAVES:
        return True
    want = expected(item, nodes)
    return want is not None and abs(want - number(item)) <= tolerance


def problems(nodes, tolerance=0):
    """What's wrong with a worksheet: unknown ops, missing inputs, nodes that don't reconcile."""
    found = []
    for key, item in nodes.items():
        if item["id"] != key:
            found.append(f"{key}: id is {item['id']}")
        missing = [name for name in item["inputs"] if name not in nodes]
        if missing:
            found.append(f"{key}: missing inputs {missing}")
        elif not reconciles(item, nodes, tolerance):
            found.append(f"{key}: {item['op']} of {[number(nodes[name]) for name in item['inputs']]} isn't {number(item)}")
    return found


# The expression language (OpenTax's corpus formulas; Tax-Calculator's maps) ----------------------------------------

def typed(found):
    """An engine value {type, value} as (type, Python value): money and int as integers."""
    kind, value = found.get("type"), found.get("value")
    if kind in ("money", "int"):
        return kind, int(value)
    return kind, value


class Result:
    __slots__ = ("kind", "value", "ref", "when")

    def __init__(self, kind, value, ref=None, when=()):
        self.kind, self.value, self.ref, self.when = kind, value, ref, list(when)


# A step deeper than a label spells out is named by what it does; wrappers don't count toward the depth.
NOUNS = {"add": "a sum", "sub": "a difference", "min": "the smaller amount", "max": "the larger amount", "mulRate": "a share", "mulInt": "a product",
         "mulDiv": "a product", "stepUnits": "a count of steps", "brackets": "a rate-table tax", "if": "the amount that applies",
         "match": "the amount that applies", "clamp": "a limited amount"}
WRAPPERS = frozenset({"max0", "roundToDollar"})
COMPARE = {"lt": ("is below", "is at least"), "le": ("is at most", "is above"), "gt": ("is above", "is at most"),
           "ge": ("is at least", "is below"), "eq": ("is", "is not"), "ne": ("is not", "is")}


class Evaluator:
    """Runs one rule's formula over known values and adds its nodes to `nodes`.

    values: {rule or fact id: (type, value)}; refs: {rule or fact id: node id} (a value with no node isn't linked);
    labels: {rule or fact id: label}; params: {name: {type, value}}; law: {"year", "filing_status"} for law leaves;
    words: enum values as said in a condition ("mfj" → "married filing jointly")."""

    def __init__(self, rule_id, title, cite, values, refs, labels, params, law, nodes, words=None):
        self.rule_id, self.title, self.cite = rule_id, title, cite
        self.values, self.refs, self.labels, self.params, self.law, self.nodes = values, refs, labels, params or {}, law, nodes
        self.words = words or {}

    def run(self, formula):
        """The rule's own node id, after adding the nodes its formula worked through."""
        found = self.emit(formula, "", self.rule_id, [])
        if found.kind not in ("money", "int"):
            raise Unsupported(f"{self.rule_id} gives {found.kind}")
        if found.ref != self.rule_id:  # The rule is one value as it stands (a fact, a parameter, a constant or another rule).
            self.add(self.rule_id, self.title, "sum", found, [found.ref], found.when)
        return found

    # Nodes.
    def add(self, key, label, op, found, inputs, when, detail=None):
        money = found.kind == "money"
        self.nodes[key] = node(key, label, op, found.value if money else None, inputs, self.cite, when=dict.fromkeys(when), detail=detail,
                               count=None if money else found.value)
        return key

    def constant(self, found):
        key = f"const:{found.kind}:{found.value}"
        if key not in self.nodes:
            self.nodes[key] = node(key, shown(found.value) if found.kind == "money" else str(found.value), "constant",
                                   found.value if found.kind == "money" else None, count=None if found.kind == "money" else found.value)
        return key

    # Values.
    def known(self, kind, name):
        if name not in self.values:
            raise Unsupported(f"{self.rule_id} reads {kind} {name}, which the engine didn't report")
        return self.values[name]

    def emit(self, expr, path, own, when):
        """The expression's value; a money or count value gets a node (own: the id for this node, else `<rule>~<path>`).
        when: the conditions behind the branches taken to get here, kept until a node takes them."""
        kind = expr.get("kind")
        key = own or f"{self.rule_id}~{path.strip('.') or '0'}"
        if kind in ("money", "int", "bool", "enum"):
            found = Result(kind, int(expr["cents"]) if kind == "money" else int(expr["value"]) if kind == "int" else expr["value"], when=when)
            if kind in ("money", "int"):
                found.ref = self.constant(found)
            return found
        if kind in ("fact", "rule"):
            name = expr["factId" if kind == "fact" else "ruleId"]
            value_kind, value = self.known(kind, name)
            return Result(value_kind, value, self.refs.get(name), when)
        if kind == "param":
            spec = self.params.get(expr["name"])
            if not spec:
                raise Unsupported(f"{self.rule_id} has no parameter {expr['name']}")
            value_kind, value = typed(spec)
            found = Result(value_kind, value, when=when)
            if value_kind in ("money", "int"):
                found.ref = f"law:{self.rule_id}:{expr['name']}"
                self.nodes[found.ref] = node(found.ref, f"{self.title}: {spaced(expr['name'])}", "law", value if value_kind == "money" else None,
                                             cite=self.cite, source={"parameter": expr["name"], **self.law}, count=None if value_kind == "money" else value)
            return found
        if kind == "if":
            truth, text = self.condition(expr["cond"])
            return self.emit(expr["then" if truth else "else"], path + (".t" if truth else ".e"), own, when + [text])
        if kind == "match":
            on = self.value(expr["on"])
            text = f"{self.describe(expr['on'])} is {self.words.get(on.value, on.value)}"
            for number_, case in enumerate(expr["cases"]):
                if case["when"] == on.value:
                    return self.emit(case["value"], f"{path}.m{number_}", own, when + [text])
            if expr.get("else") is not None:
                return self.emit(expr["else"], path + ".e", own, when + [text])
            raise Unsupported(f"{self.rule_id}: no case for {on.value}")
        if kind in ("cmp", "and", "or", "not"):
            truth, _ = self.condition(expr)
            return Result("bool", truth, when=when)
        if kind in ("add", "sub", "min", "max"):
            parts = [self.emit(item, f"{path}.{number_}", None, []) for number_, item in enumerate(expr["args"] if kind != "sub" else [expr["left"], expr["right"]])]
            values = [part.value for part in parts]
            value = sum(values) if kind == "add" else values[0] - sum(values[1:]) if kind == "sub" else min(values) if kind == "min" else max(values)
            op = {"add": "sum", "sub": "difference"}.get(kind, kind)
            return self.made(key, self.expression(expr), op, Result(parts[0].kind, value), parts, when, own)
        if kind == "max0":
            part = self.emit(expr["arg"], path + ".0", None, [])
            zero = Result("money", 0)
            zero.ref = self.constant(zero)
            return self.made(key, self.expression(expr), "max", Result("money", max(part.value, 0)), [part, zero], when, own)
        if kind == "clamp":
            value, low, high = (self.emit(item, f"{path}.{number_}", None, []) for number_, item in enumerate((expr["value"], expr["lo"], expr["hi"])))
            raised = self.made(f"{self.rule_id}~{path.strip('.') or '0'}.lo", f"{self.describe(expr['value'])}, at least {self.describe(expr['lo'])}", "max",
                               Result("money", max(value.value, low.value)), [value, low], [], None)
            return self.made(key, self.expression(expr), "min", Result("money", min(raised.value, high.value)), [raised, high], when, own)
        if kind == "mulRate":
            base = self.emit(expr["base"], path + ".0", None, [])
            num, den = int(expr["rate"]["num"]), int(expr["rate"]["den"])
            return self.made(key, self.expression(expr), "rate", Result("money", div_round(base.value * num, den, expr["round"])),
                             [base], when, own, {"num": num, "den": den, "rate": percent(num, den), "round": expr["round"]})
        if kind == "mulInt":
            base, count = self.emit(expr["base"], path + ".0", None, []), self.emit(expr["count"], path + ".1", None, [])
            return self.made(key, self.expression(expr), "multiply", Result("money", base.value * count.value), [base, count], when, own)
        if kind == "mulDiv":
            a, b, c = (self.emit(item, f"{path}.{number_}", None, []) for number_, item in enumerate((expr["a"], expr["b"], expr["c"])))
            return self.made(key, self.expression(expr), "multiply", Result("money", div_round(a.value * b.value, c.value, expr["round"])), [a, b, c], when, own,
                             {"divide": True, "round": expr["round"]})
        if kind == "roundToDollar":
            part = self.emit(expr["value"], path + ".0", None, [])
            return self.made(key, self.expression(expr), "round", Result("money", div_round(part.value, 100, expr["mode"]) * 100), [part], when, own,
                             {"round": expr["mode"]})
        if kind == "stepUnits":
            part = self.emit(expr["value"], path + ".0", None, [])
            unit = int(expr["unitCents"])
            return self.made(key, self.expression(expr), "steps", Result("int", div_round(part.value, unit, expr["mode"])), [part], when, own,
                             {"unit_minor": unit, "round": expr["mode"]})
        if kind == "brackets":
            base = self.emit(expr["base"], path + ".0", None, [])
            table = [{"from_minor": int(row["threshold"]), "num": int(row["rate"]["num"]), "den": int(row["rate"]["den"]),
                      "rate": percent(int(row["rate"]["num"]), int(row["rate"]["den"]))} for row in expr["table"]]
            return self.made(key, self.expression(expr), "lookup", Result("money", bracket_tax(base.value, table)), [base], when, own, {"table": table})
        if kind == "unsupported":
            raise Unsupported(expr.get("reason") or f"{self.rule_id} isn't modeled")
        raise Unsupported(f"{self.rule_id}: unknown expression {kind}")

    def made(self, key, label, op, found, parts, when, own, detail=None):
        """A step's node: its inputs are the parts' nodes; it takes the conditions that led here and the parts' own."""
        if any(part.ref is None for part in parts):
            raise Unsupported(f"{self.rule_id}: a step reads a value with no node")
        conditions = list(when) + [text for part in parts for text in part.when]
        self.add(key, self.title if own == self.rule_id else label, op, found, [part.ref for part in parts], conditions, detail)
        return Result(found.kind, found.value, key)

    # Conditions: evaluated without nodes, described in words.
    def value(self, expr):
        kind = expr.get("kind")
        if kind in ("fact", "rule"):
            value_kind, value = self.known(kind, expr["factId" if kind == "fact" else "ruleId"])
            return Result(value_kind, value)
        if kind in ("cmp", "and", "or", "not"):
            return Result("bool", self.condition(expr)[0])
        scratch = Evaluator(self.rule_id, self.title, self.cite, self.values, self.refs, self.labels, self.params, self.law, {}, self.words)
        found = scratch.emit(expr, "c", None, [])
        return Result(found.kind, found.value)

    def condition(self, expr):
        """(truth, the condition in words as it turned out)."""
        kind = expr.get("kind")
        if kind == "cmp":
            left, right = self.value(expr["left"]), self.value(expr["right"])
            if expr["op"] in ("eq", "ne"):
                truth = (left.kind, left.value) == (right.kind, right.value)
                truth = truth if expr["op"] == "eq" else not truth
            else:
                truth = {"lt": left.value < right.value, "le": left.value <= right.value, "gt": left.value > right.value, "ge": left.value >= right.value}[expr["op"]]
            words = COMPARE[expr["op"]][0 if truth else 1]
            return truth, f"{self.describe(expr['left'], left)} {words} {self.describe(expr['right'], right)}"
        if kind == "not":
            truth, text = self.condition(expr["arg"])
            return not truth, text
        if kind in ("and", "or"):
            # Stops at the first part that decides, as the engine does (it never reads what comes after).
            decider, results = kind == "or", []
            for item in expr["args"]:
                results.append(self.condition(item))
                if results[-1][0] == decider:
                    return decider, results[-1][1]
            return not decider, (" and " if kind == "and" else " or ").join(text for _, text in results)
        found = self.value(expr)
        if found.kind != "bool":
            raise Unsupported(f"{self.rule_id}: a condition gives {found.kind}")
        return found.value, f"{self.describe(expr)}: {'yes' if found.value else 'no'}"

    def describe(self, expr, found=None):
        """An expression in words, with its value when it isn't written in the rule."""
        kind = expr.get("kind")
        if kind == "money":
            return shown(int(expr["cents"]))
        if kind in ("int", "enum"):
            return str(self.words.get(expr["value"], expr["value"]))
        if kind == "bool":
            return "yes" if expr["value"] else "no"
        name = self.expression(expr)
        if found is not None and found.kind == "money":
            return f"{name} ({shown(found.value)})"
        if found is not None and found.kind in ("int", "enum"):
            return f"{name} ({self.words.get(found.value, found.value)})"
        return name

    def expression(self, expr, depth=0):
        """A step written out with the names of what it reads, two levels deep ("Wages + Self-employment net profit − (…)")."""
        kind = expr.get("kind")
        if kind in ("money", "int", "enum", "bool"):
            return self.describe(expr)
        if kind == "param":
            return spaced(expr["name"])
        if kind in ("fact", "rule"):
            name = expr["factId" if kind == "fact" else "ruleId"]
            return self.labels.get(name, name)
        if depth >= 2 and kind not in WRAPPERS:
            return NOUNS.get(kind, "the amount worked out")

        def inner(item):
            deeper = depth if kind in WRAPPERS else depth + 1
            text = self.expression(item, deeper)
            return f"({text})" if item.get("kind") in ("add", "sub", "mulDiv", "mulInt") and deeper < 2 else text
        if kind == "add":
            return " + ".join(inner(item) for item in expr["args"])
        if kind == "sub":
            return f"{inner(expr['left'])} − {inner(expr['right'])}"
        if kind in ("min", "max"):
            return ("the smaller of " if kind == "min" else "the larger of ") + " and ".join(inner(item) for item in expr["args"])
        if kind == "max0":
            return f"{inner(expr['arg'])}, not below {shown(0)}"
        if kind == "clamp":
            return f"{inner(expr['value'])}, between {inner(expr['lo'])} and {inner(expr['hi'])}"
        if kind == "mulRate":
            return f"{percent(int(expr['rate']['num']), int(expr['rate']['den']))} of {inner(expr['base'])}"
        if kind == "mulInt":
            return f"{inner(expr['base'])} × {inner(expr['count'])}"
        if kind == "mulDiv":
            return f"{inner(expr['a'])} × {inner(expr['b'])} ÷ {inner(expr['c'])}"
        if kind == "roundToDollar":
            return f"{inner(expr['value'])}, rounded to the dollar"
        if kind == "stepUnits":
            return f"{inner(expr['value'])} in whole steps of {shown(int(expr['unitCents']))}"
        if kind == "brackets":
            return f"tax on {inner(expr['base'])} from the rate table"
        if kind in ("if", "match"):
            return "the amount that applies"
        return "the amount worked out"


def spaced(name):
    """A camelCase or snake_case parameter name as words ("limitFamily" → "limit family")."""
    words, current = [], ""
    for char in name.replace("_", " "):
        if char.isupper() and current and not current[-1].isupper():
            words.append(current)
            current = char.lower()
        else:
            current += char
    words.append(current)
    return " ".join(word.strip() for word in words if word.strip())
