"""The engine-neutral worksheet (finance/worksheet.py): OpenTax's rounding, each op's reconciliation, and the expression
evaluator's steps, branches and conditions, on hand-written rules."""

import pytest

from home_manager.finance import worksheet
from home_manager.finance.worksheet import Evaluator, Unsupported, div_round


def test_rounding_matches_the_engines_integer_arithmetic():
    # BigInt division truncates toward zero; each mode then rounds as OpenTax's divRound does.
    assert [div_round(7, 2, mode) for mode in ("floor", "ceil", "half-up", "half-even")] == [3, 4, 4, 4]
    assert [div_round(-7, 2, mode) for mode in ("floor", "ceil", "half-up", "half-even")] == [-4, -3, -4, -4]
    assert div_round(5, 2, "half-even") == 2 and div_round(10, 4, "half-up") == 3 and div_round(9, 3, "floor") == 3
    # Each bracket's slice is rounded half-up: 10% of 1,000.05 and 12% of the rest.
    table = [{"from_minor": 0, "num": 10, "den": 100}, {"from_minor": 100005, "num": 12, "den": 100}]
    assert worksheet.bracket_tax(100005, table) == 10001 and worksheet.bracket_tax(200005, table) == 10001 + 12000
    assert worksheet.percent(1598, 10000) == "15.98%" and worksheet.percent(21, 100) == "21%"


def test_each_op_reconciles_from_its_inputs():
    nodes = {"a": worksheet.node("a", "A", "fact", 300), "b": worksheet.node("b", "B", "fact", 100), "n": worksheet.node("n", "N", "fact", None, count=3)}
    cases = [("sum", 400, {}), ("difference", 200, {}), ("min", 100, {}), ("max", 300, {}), ("sum", 200, {"signs": [1, -1]})]
    for op, amount, detail in cases:
        assert worksheet.reconciles(worksheet.node("x", "X", op, amount, ["a", "b"], detail=detail), nodes), op
    assert worksheet.reconciles(worksheet.node("x", "X", "multiply", 900, ["a", "n"]), nodes)
    assert worksheet.reconciles(worksheet.node("x", "X", "rate", 23, ["a"], detail={"num": 765, "den": 10000, "round": "half-up"}), nodes)
    assert worksheet.reconciles(worksheet.node("x", "X", "round", 300, ["a"], detail={"round": "half-up"}), nodes)
    assert not worksheet.reconciles(worksheet.node("x", "X", "sum", 401, ["a", "b"]), nodes)
    assert worksheet.reconciles(worksheet.node("x", "X", "sum", 401, ["a", "b"]), nodes, tolerance=1)
    assert worksheet.problems({**nodes, "x": worksheet.node("x", "X", "sum", 400, ["a", "missing"])}) == ["x: missing inputs ['missing']"]
    with pytest.raises(ValueError):
        worksheet.node("x", "X", "guess", 1)


def evaluate(formula, values, params=None):
    nodes: dict = {}
    refs = {name: f"fact:{name}" if name.islower() else name for name in values}
    labels = {"wages": "Wages", "children": "Qualifying children", "status": "Filing status", "AGI": "Adjusted gross income"}
    found = Evaluator("rule.x", "The credit", "26 U.S.C. § 1", values, refs, labels, params or {}, {"year": 2026, "filing_status": "single"}, nodes,
                      {"mfj": "married filing jointly"}).run(formula)
    return found, nodes


def fact(name):
    return {"kind": "fact", "factId": name}


def money(cents):
    return {"kind": "money", "cents": str(cents)}


def test_a_rule_becomes_steps_with_the_branch_it_took():
    # min(wages, if AGI > 1,000: 5% of wages else the 300 parameter) + 2 × 100 per child
    formula = {"kind": "add", "args": [
        {"kind": "min", "args": [fact("wages"), {"kind": "if", "cond": {"kind": "cmp", "op": "gt", "left": {"kind": "rule", "ruleId": "AGI"}, "right": money(100000)},
                                                 "then": {"kind": "mulRate", "base": fact("wages"), "rate": {"num": "5", "den": "100"}, "round": "half-up"},
                                                 "else": {"kind": "param", "name": "flatAmount"}}]},
        {"kind": "mulInt", "base": money(10000), "count": fact("children")}]}
    values = {"wages": ("money", 500000), "children": ("int", 2), "AGI": ("money", 50000)}
    found, nodes = evaluate(formula, values, {"flatAmount": {"type": "money", "value": "30000"}})
    assert found.value == 30000 + 20000
    top = nodes["rule.x"]
    assert top["op"] == "sum" and top["label"] == "The credit" and top["amount_minor"] == 50000
    smaller = nodes[top["inputs"][0]]
    assert smaller["op"] == "min" and smaller["inputs"] == ["fact:wages", "law:rule.x:flatAmount"]
    assert smaller["when"] == ["Adjusted gross income (500.00 USD) is at most 1,000.00 USD"]  # The branch not taken is never shown.
    assert nodes["law:rule.x:flatAmount"]["source"] == {"parameter": "flatAmount", "year": 2026, "filing_status": "single"}
    assert worksheet.problems({**nodes, "fact:wages": worksheet.node("fact:wages", "Wages", "fact", 500000),
                               "fact:children": worksheet.node("fact:children", "Children", "fact", None, count=2)}) == []


def test_a_rate_table_rounded_once_is_the_exact_sum():
    # Tax-Calculator works the schedule in floats: three slices of x.5 cents round once, not each half-up.
    table = [{"from_minor": 0, "num": 1, "den": 2}, {"from_minor": 1, "num": 1, "den": 2}, {"from_minor": 2, "num": 1, "den": 2}]
    assert worksheet.bracket_tax(3, table) == 3 and worksheet.bracket_tax(3, table, once=True) == 2  # 1.5 → 2 (half-even)
    assert worksheet.reconciles(worksheet.node("t", "T", "lookup", 2, ["a"], detail={"table": table, "round": "once"}),
                                {"a": worksheet.node("a", "A", "fact", 3)})


LAW = {"SeniorDed_prt": {"type": "rate", "num": "6", "den": "100"}, "Step": {"type": "money", "value": "100000"},
       "II_rt1": {"type": "rate", "num": "10", "den": "100"}, "II_rt2": {"type": "rate", "num": "12", "den": "100"},
       "II_rt3": {"type": "rate", "num": "22", "den": "100"}, "II_brk1": {"type": "money", "value": "1240000"},
       "II_brk2": {"type": "money", "value": "900000000000000000000"},
       "EITC_c": {"type": "money", "value": "430000", "source": {"read_by": "EIC", "at": 1}}}


def test_law_read_into_a_step_rates_step_sizes_and_rate_tables():
    values = {"wages": ("money", 2000000), "children": ("int", 3)}
    # A rate parameter: the step carries it as detail, so it still reconciles from its one input.
    found, nodes = evaluate({"kind": "mulRate", "base": fact("wages"), "rateParam": "SeniorDed_prt", "round": "half-even"}, values, LAW)
    top = nodes["rule.x"]
    assert found.value == 120000 and top["op"] == "rate" and top["detail"]["parameter"] == "SeniorDed_prt"
    assert top["detail"]["source"] == {"parameter": "SeniorDed_prt", "year": 2026, "filing_status": "single"} and top["label"] == "The credit"
    # Whole steps of a money parameter, rounded up.
    found, nodes = evaluate({"kind": "stepUnits", "value": fact("wages"), "unitParam": "Step", "mode": "ceil"}, {"wages": ("money", 2000001)}, LAW)
    assert found.value == 21 and found.kind == "int" and nodes["rule.x"]["detail"]["unit_minor"] == 100000
    # The rate schedule from the law: the inactive row (9e18 dollars) ends it, and it's rounded once.
    schedule = {"kind": "brackets", "base": fact("wages"), "rates": ["II_rt1", "II_rt2", "II_rt3"], "thresholds": ["II_brk1", "II_brk2"], "round": "once"}
    found, nodes = evaluate(schedule, values, LAW)
    assert found.value == 124000 + (2000000 - 1240000) * 12 // 100 and len(nodes["rule.x"]["detail"]["table"]) == 2
    assert nodes["rule.x"]["detail"]["round"] == "once"
    # money × count ÷ money is a count: a share in thousandths.
    share = {"kind": "mulDiv", "a": fact("wages"), "b": {"kind": "int", "value": "1000"}, "c": money(3000000), "round": "half-even"}
    found, _ = evaluate(share, values, LAW)
    assert (found.kind, found.value) == ("int", 667)
    # Not below zero keeps a count a count; a parameter read by something other than filing status says by what.
    found, nodes = evaluate({"kind": "max0", "arg": {"kind": "sub", "left": fact("children"), "right": {"kind": "int", "value": "5"}}}, values, LAW)
    assert (found.kind, found.value) == ("int", 0) and nodes["rule.x"]["count"] == 0
    _, nodes = evaluate({"kind": "param", "name": "EITC_c"}, values, LAW)
    assert nodes["law:rule.x:EITC_c"]["source"] == {"parameter": "EITC_c", "year": 2026, "filing_status": "single", "read_by": "EIC", "at": 1}
    with pytest.raises(Unsupported):  # A rate is only read as amount × rate.
        evaluate({"kind": "param", "name": "SeniorDed_prt"}, values, LAW)


def test_conditions_stop_where_the_engine_stops_and_enums_read_as_words():
    # The engine never reads a fact after the part of an `or` that decides it, so a fact it didn't report is fine there.
    formula = {"kind": "if", "cond": {"kind": "or", "args": [{"kind": "cmp", "op": "eq", "left": fact("status"), "right": {"kind": "enum", "value": "mfj"}},
                                                         fact("neverRead")]},
               "then": money(200), "else": money(100)}
    found, nodes = evaluate(formula, {"status": ("enum", "mfj")})
    assert found.value == 200 and nodes["rule.x"]["when"] == ["Filing status (married filing jointly) is married filing jointly"]
    with pytest.raises(Unsupported):
        evaluate(formula, {"status": ("enum", "single")})  # Now the second part decides, and it wasn't reported.
    with pytest.raises(Unsupported):
        evaluate({"kind": "unsupported", "reason": "not modeled"}, {})
