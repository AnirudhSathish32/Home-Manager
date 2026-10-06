"""Engine worksheets' conformance (docs/taxes.md "The tax engines", docs/ui.md "Trace contract"): every registered engine,
on every synthetic return, explains each line through its worksheet (finance/worksheet.py). An engine counts as traced
once it passes, so this test is what adding an engine costs."""

import shutil

import pytest

from home_manager.finance import tax_engine, worksheet
from home_manager.finance.engines import taxcalc
from home_manager.finance.tax_return import ReturnInput
from tax_returns import RETURNS

READY = {"engine_1": shutil.which("node") is not None, "engine_2": taxcalc.installed() == taxcalc.PINNED}
SLOTS = [pytest.param(slot, marks=pytest.mark.skipif(not READY.get(slot, True), reason=f"{slot} can't run here")) for slot in tax_engine.ENGINES]


def worked(slot, value):
    result = tax_engine.calculate(slot, value, {})
    assert result["result_minor"] is not None, result["notes"]
    return result, tax_engine.worksheet(slot, value)


def fields_ok(source):
    """Every field a fact names is one of the return's inputs ("jobs.0.wages" is a job's)."""
    return all(field.partition(".")[0] in ReturnInput.model_fields for field, _ in source.get("fields") or [])


@pytest.mark.parametrize("name", list(RETURNS))
@pytest.mark.parametrize("slot", SLOTS)
def test_every_line_is_explained_by_the_engines_worksheet(slot, name):
    result, nodes = worked(slot, RETURNS[name])
    engine = tax_engine.ENGINES[slot]()
    assert worksheet.problems(nodes, engine.tolerance_minor) == []  # Every input is a node, and every step gives its value under its op.
    for line in result["lines"]:
        if line["section"] == "total" and not line["node"]:
            continue  # A total traces to the lines above it (tax.line); its node, when it has one, is checked like any other.
        assert line["node"] in nodes, (name, line["key"])
        item = nodes[line["node"]]
        assert abs(item["amount_minor"]) == abs(line["amount_minor"]), (name, line["key"], item["amount_minor"], line["amount_minor"])
        assert item["op"] != "opaque" or line["key"] in engine.opaque_lines, (name, line["key"], item["detail"])
    for item in nodes.values():
        assert item["op"] in worksheet.OPS
        if item["op"] == "fact":
            assert "assumed" in item["source"] or (item["source"]["fields"] and fields_ok(item["source"])), (name, item["id"], item["source"])
        if item["op"] == "law":
            assert item["cite"], (name, item["id"])
            assert {"parameter", "year", "filing_status"} <= set(item["source"])


@pytest.mark.skipif(not READY["engine_1"], reason="Node.js isn't installed")
def test_engine_1_breaks_every_rule_down_to_facts_and_law():
    # Engine 1 re-runs each rule from its corpus formula: none is left as the engine's value only, on any synthetic return.
    for name, value in RETURNS.items():
        _, nodes = worked("engine_1", value)
        assert [key for key, item in nodes.items() if item["op"] == "opaque"] == [], name
    # A rule's steps say which branch applied, and its parameters are the law with their year.
    _, nodes = worked("engine_1", RETURNS["hsa_family"])
    hsa = nodes["us.federal.hsa_deduction"]
    assert hsa["op"] == "min" and hsa["amount_minor"] == 200000 and hsa["inputs"][0] == "fact:hsaContribution"
    assert any("Personal HSA contributions" in text for text in hsa["when"]) and hsa["cite"].startswith("26 U.S.C. § 223")
    limit = next(item for key, item in nodes.items() if key.startswith("law:us.federal.hsa_deduction:limitFamily"))
    assert limit["amount_minor"] == 875000 and limit["source"] == {"parameter": "limitFamily", "year": 2026, "filing_status": "married_joint"}
    assert nodes["fact:hsaContribution"]["source"] == {"fields": [["hsa_contributions", 1]]}
    # A default the engine assumed for something not entered says so.
    assumed = [item for item in nodes.values() if item["op"] == "fact" and "assumed" in item["source"]]
    assert assumed and all(item["source"]["assumed"] for item in assumed)


def test_the_map_language_reads_rates_steps_shares_and_the_schedule():
    # No Tax-Calculator needed: how formulas compile, and which law each one asks the runner for.
    read: set = set()
    types = {"SeniorDed_prt": "rate", "II_rt1": "rate"}
    compiled = taxcalc.compile_formula("max0(SeniorDed_c - max0(c00100 - SeniorDed_ps) * SeniorDed_prt)", {"c00100"}, {}, {}, read, types)
    rate = compiled["arg"]["right"]
    assert rate == {"kind": "mulRate", "base": rate["base"], "rateParam": "SeniorDed_prt", "round": "half-even"}
    steps = taxcalc.compile_formula("steps_ceil(c00100, CTC_step) + steps_floor(c00100, 1000)", {"c00100"}, {}, {}, read, types)
    assert steps["args"][0]["unitParam"] == "CTC_step" and steps["args"][1]["unitCents"] == "100000" and steps["args"][1]["mode"] == "floor"
    share = taxcalc.compile_formula("muldiv(e87521, int(1000), c00100)", {"c00100"}, {"e87521": "AOTC"}, {}, read, types)
    assert share["kind"] == "mulDiv" and share["b"] == {"kind": "int", "value": "1000"} and share["a"] == {"kind": "fact", "factId": "e87521"}
    tax = taxcalc.compile_formula("schedule(c04800)", {"c04800"}, {}, {}, read, types)
    assert tax["kind"] == "brackets" and tax["round"] == "once" and tax["rates"][0] == "II_rt1" and tax["thresholds"][-1] == "II_brk7"
    assert {"SeniorDed_c", "SeniorDed_ps", "SeniorDed_prt", "CTC_step", "II_rt8", "II_brk7"} <= read and "muldiv" not in read
    # Law values by type: a rate as its exact fraction, a count, basis points, and what an indexed one was read by.
    assert taxcalc.law_param(0.06, "rate", None, {}) == {"type": "rate", "num": "6", "den": "100"}
    assert taxcalc.law_param(65.0, "int", None, {}) == {"type": "int", "value": "65"}
    assert taxcalc.law_param(0.5, "bp", None, {}) == {"type": "int", "value": "5000"}
    assert taxcalc.law_param(4328.0, "money", "EIC", {"EIC": 1}) == {"type": "money", "value": "432800", "source": {"read_by": "EIC", "at": 1}}


@pytest.mark.skipif(not READY["engine_2"], reason='Engine 2 isn\'t installed (pip install ".[engine2]")')
def test_engine_2_map_reproduces_every_output_it_writes_a_formula_for():
    # Every output has a formula: nothing is left as the engine's value only, on any line.
    assert taxcalc.worksheet_map()["opaque"] == {} and tax_engine.ENGINES["engine_2"]().opaque_lines == frozenset()
    mapped = set(taxcalc.worksheet_map()["nodes"])
    for name, value in RETURNS.items():
        _, nodes = worked("engine_2", value)
        assert {key: nodes[key]["detail"] for key in mapped if nodes[key]["op"] == "opaque"} == {}, name


@pytest.mark.skipif(not READY["engine_2"], reason='Engine 2 isn\'t installed (pip install ".[engine2]")')
def test_engine_2_alternative_minimum_tax_is_broken_down():
    # Nothing a profile enters reaches the AMT, so the record gets AMT preferences (Form 6251 lines 2c-3, as incentive stock
    # options would give) directly: the map must still reproduce the engine's AMT and its income, step by step.
    sources: dict = {}
    record, _ = taxcalc.record_for(RETURNS["high_wages"], sources)
    record["cmbtp"] = 40000000.0
    mapped = taxcalc.worksheet_map()
    answer = taxcalc.evaluate(record, 2026, mapped["extra_outputs"], mapped["extra_policy"],
                              {name: field for name, field in mapped["index"].items() if name in mapped["policy"]})
    nodes = taxcalc.map_worksheet({"record": record, "record_sources": sources, "values": answer["values"], "policy": answer["policy"]},
                                  2026, "single", taxcalc.TaxCalculatorEngine.tolerance_minor)
    assert nodes["c09600"]["amount_minor"] > 0 and nodes["c09600"]["op"] != "opaque", nodes["c09600"]["detail"]
    assert nodes["c62100"]["op"] != "opaque" and worksheet.problems(nodes, taxcalc.TaxCalculatorEngine.tolerance_minor) == []


@pytest.mark.skipif(not READY["engine_2"], reason='Engine 2 isn\'t installed (pip install ".[engine2]")')
def test_engine_2_map_written_for_another_release_isnt_used(monkeypatch):
    monkeypatch.setitem(taxcalc.worksheet_map(), "law_sha256", "0" * 64)
    monkeypatch.setattr(tax_engine, "_worksheets", tax_engine.OrderedDict())
    _, nodes = worked("engine_2", RETURNS["w2"])
    assert nodes["c00100"]["op"] == "opaque" and "another Tax-Calculator release" in nodes["c00100"]["detail"]["reason"]
