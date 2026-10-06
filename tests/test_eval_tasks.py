"""Per-task evals (evals/tasks), the decision rule and the opt-in judge, on synthetic data and the fake model server only."""

import json

import pytest

from evals.decision import decide, rules
from evals.judge import calibrate, export_labels, judge_run, kappa
from evals.synthetic import money
from evals.tasks import TASKS
from evals.tasks.runner import run_tasks


def oracle(task, case):
    """The answer a perfect model would give, in each task's output shape."""
    expected = case["expected"]
    if task == "transcription":
        return {"text": expected["text"]}
    if task == "identify":
        return {"seller": expected["seller"], "inferred": False, "location": expected["location"]}
    if task == "describe":
        return {"description": "Groceries", "category": next((value for value in expected["category"] if value), None),
                "recurrence": expected["recurrence"], "item_categories": [choices[0] for choices in expected["items"]]}
    if task == "rewards":
        return {"rewards": [dict(item) for item in expected["rewards"]]}
    if task == "payment_terms":
        return {"terms": [{**term, "currency": "USD"} for term in expected["terms"]], "notes": []}
    if task == "interpretation":
        exponent = expected["exponent"]
        facts = [{"kind": "merchant", "value": expected["merchant"], "status": "proposed"},
                 {"kind": "purchase_date", "value": expected["purchase_date"], "status": "proposed"},
                 {"kind": "total", "value": f"{expected['total']} USD", "status": "proposed"}]
        return {"document_type": "receipt", "facts": facts, "insights": [], "limitations": ["Unverified."], "title": "Purchase",
                "receipt_items": [{"description": row["description"], "line_total": money(row["line_total_minor"], exponent)} for row in expected["items"]]}
    if task == "reviewer":
        planted = expected["planted"]
        return {"verdict": expected["verdict"], "classification_supported": True, "findings": [f"Check {expected['words'][0]}."] if planted else [],
                "evidence": [{"line_id": expected["line"], "quote": "x"}] if planted else []}
    if task == "payees":
        return {"payees": [{"payee_id": index, "recurrence": payee["recurrence"], "category": (payee["category"] or [None])[0]}
                           for index, payee in enumerate(expected["payees"])]}
    if task == "checkin":
        return {"updates": [{"lot_id": int(lot), "event": event, "effective_on": day} for lot, (event, day) in expected["updates"].items()],
                "set_aside": [], "not_understood": "something else" if expected["unlisted"] else None, "applied": []}
    if task == "assistant":
        words = " ".join(expected["words"])
        if expected["abstain"]:
            return {"answer": "Your records do not show that.", "route": "finance", "unverified_figures": [], "missing_evidence": ["no such account"],
                    "cited_calls": [], "calls": [{"tool": expected["tools"][0], "ok": True}]}
        figures = (expected["figures_any"][:1] + expected["figures_all"])
        return {"answer": f"{words} " + " and ".join(f"{float(value):,.2f} USD" for value in figures), "route": "finance", "unverified_figures": [],
                "missing_evidence": [], "cited_calls": [1], "calls": [{"tool": expected["tools"][0], "ok": True}]}
    if task == "item_lookup":
        want = expected["product"]
        return {"proposal": want and {"name": " ".join(want["words"]).title(), "brand": want["brand"], "size_text": None, "category": want["category"][0],
                                      "consumable": True if want["consumable"] is None else want["consumable"], "confidence": "high"}}
    if task == "warranty":
        return {"warranty": None if expected["none"] else {"kind": "manufacturer", "months": expected["months"], "lifetime": expected["lifetime"]}}
    if task == "tax_table":
        return {"table": expected["table"]}
    if task == "decisions":
        return {"answer": expected["label"], "probabilities": {expected["label"]: 1.0}, "coverage": 1.0}
    raise AssertionError(task)


WEB_AGENTS = ("item_lookup", "warranty", "tax_table")


def test_every_task_has_enough_unique_cases_and_a_perfect_answer_passes():
    for name, module in TASKS.items():
        cases = module.cases()
        assert len(cases) >= (6 if name in WEB_AGENTS else 20) and len({case["id"] for case in cases}) == len(cases), name
        assert cases == module.cases(), name  # Deterministic: the same cases every time.
        for case in cases:
            graded = module.grade(case, oracle(name, case))
            assert graded["passed"] and graded["score"] == 1.0, (name, case["id"], graded)


def test_graders_catch_wrong_answers():
    first = {name: module.cases()[1] for name, module in TASKS.items()}
    assert not TASKS["transcription"].grade(first["transcription"], {"text": "nothing like it"})["passed"]
    assert not TASKS["identify"].grade(first["identify"], {"seller": "Somewhere Else", "inferred": False, "location": None})["passed"]
    case = first["describe"]
    assert not TASKS["describe"].grade(case, {**oracle("describe", case), "category": "travel"})["passed"]
    assert not TASKS["describe"].grade(case, {**oracle("describe", case), "item_categories": None})["passed"]
    rewards = next(case for case in TASKS["rewards"].cases() if case["expected"]["rewards"])
    graded = TASKS["rewards"].grade(rewards, {"rewards": [{"kind": "earned", "amount": "999", "link": None}]})
    assert not graded["passed"] and graded["checks"]["money_errors"] == 1
    terms = first["payment_terms"]
    wrong = {"terms": [{**term, "amount": "1.00", "currency": "USD"} for term in terms["expected"]["terms"]], "notes": []}
    graded = TASKS["payment_terms"].grade(terms, wrong)
    assert not graded["passed"] and graded["checks"]["money_errors"] == len(terms["expected"]["terms"])
    interpretation = first["interpretation"]
    answer = oracle("interpretation", interpretation)
    answer["facts"][2]["value"] = "1.00 USD"
    graded = TASKS["interpretation"].grade(interpretation, answer)
    assert not graded["passed"] and graded["checks"]["money_errors"] == 1
    # Items listed without their amounts are missing, not wrong: they fail the case but are not money errors.
    blank = oracle("interpretation", interpretation)
    blank["receipt_items"] = [{**item, "line_total": None} for item in blank["receipt_items"]]
    graded = TASKS["interpretation"].grade(interpretation, blank)
    assert not graded["passed"] and graded["checks"]["money_errors"] == 0
    linked = next(case for case in TASKS["rewards"].cases() if not case["expected"]["rewards"])
    graded = TASKS["rewards"].grade(linked, {"rewards": [{"kind": "survey", "amount": None, "link": "example.com"}]})
    assert not graded["passed"] and graded["checks"]["money_errors"] == 0
    from evals.graders import failure_kind
    assert failure_kind("Reviewer verdict contradicts its findings.", [{"status": "succeeded", "finish_reason": "stop"}]) == "validator_fail"
    planted = next(case for case in TASKS["reviewer"].cases() if case["expected"]["planted"])
    assert not TASKS["reviewer"].grade(planted, {"verdict": "no_issues_found", "findings": [], "evidence": [], "classification_supported": True})["passed"]
    payees = first["payees"]
    answer = oracle("payees", payees)
    answer["payees"][0]["recurrence"] = "weekly"
    assert not TASKS["payees"].grade(payees, answer)["passed"]
    checkin = first["checkin"]
    assert not TASKS["checkin"].grade(checkin, {"updates": [], "set_aside": [], "not_understood": None})["passed"]
    injection = next(case for case in TASKS["assistant"].cases() if "injection" in case["tags"])
    answer = oracle("assistant", injection)
    assert not TASKS["assistant"].grade(injection, {**answer, "answer": answer["answer"] + " or 999.99 USD"})["passed"]
    abstain = next(case for case in TASKS["assistant"].cases() if "abstain" in case["tags"])
    assert not TASKS["assistant"].grade(abstain, {**oracle("assistant", abstain), "answer": "Your balance is 12,000.00 USD.", "missing_evidence": []})["passed"]
    planted_claim = next(case for case in TASKS["decisions"].cases() if "planted_error" in case["tags"])
    assert not TASKS["decisions"].grade(planted_claim, {"answer": "true", "probabilities": {"true": .9, "false": .1}})["passed"]
    assert not TASKS["decisions"].grade(planted_claim, {"answer": None, "probabilities": None})["passed"]  # No label is no answer.


def step(tool, arguments):
    return {"action": "call_tool", "tool": tool, "arguments_json": json.dumps(arguments), "note": None}


def test_the_web_agents_run_their_real_tool_loops_against_recorded_pages(local_model):
    from evals.tasks.runner import run_one
    from home_manager.documents.reasoning import ReasoningConfig
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    scripts = {
        "item_lookup": [step("get_receipt_line", {}), step("web_search", {"query": "Walmart GV WHL MLK 1GL"}),
                        step("propose_item_resolution", {"name": "Great Value Whole Vitamin D Milk, 1 Gallon", "brand": "Great Value", "size_text": "1 gal",
                                                         "category": "dairy & eggs", "consumable": True, "barcode": None, "confidence": "high", "source_ids": ["r1"]})],
        # The first proposal states the wrong length: the agent's own check refuses it, and the corrected one is kept.
        "warranty": [step("web_search", {"query": "Acme Book 14 warranty"}), step("open_result", {"result_id": "r1"}),
                     step("propose_warranty", {"result_id": "r1", "quote": "includes a one-year limited warranty", "months": 24, "lifetime": False, "kind": "manufacturer"}),
                     step("propose_warranty", {"result_id": "r1", "quote": "includes a one-year limited warranty", "months": 12, "lifetime": False, "kind": "manufacturer"})],
        "tax_table": [step("web_search", {"query": "Georgia 2026 individual income tax rates"}), step("open_result", {"result_id": "r1"}),
                      step("propose_tax_table", {"quotes": [{"result_id": "r1", "text": "For tax year 2026, the standard deduction for single filers is $15,000."},
                                                            {"result_id": "r1", "text": "Tax rates for 2026 (single filers): 5.19% on taxable income from $0."}],
                                                 "standard_deduction": "15,000", "brackets": [{"starts_at": "0", "rate": "5.19%"}]})],
    }
    for name, script in scripts.items():
        case = TASKS[name].cases()[0]
        local_model["outputs"] = list(script)
        fields = run_one(TASKS[name], case, config)
        assert fields["status"] == "ok" and fields["grades"]["passed"], (name, fields)
        assert fields["first_try_valid"] is None and fields["output"]["tool_calls"] == len(script), name
    # Finishing without a proposal is right when no page states the warranty.
    unstated = next(case for case in TASKS["warranty"].cases() if case["expected"]["none"])
    local_model["outputs"] = [{"action": "finish", "tool": None, "arguments_json": None, "note": "No warranty is stated."}]
    assert run_one(TASKS["warranty"], unstated, config)["grades"]["passed"]


def test_compare_schema_runs_each_candidate_without_the_enforced_schema_too(tmp_path, local_model):
    case = TASKS["checkin"].cases()[0]
    reading = {"updates": [{"lot_id": int(lot), "answer": event, "when": "on_date" if day else "today", "date": day}
                           for lot, (event, day) in case["expected"]["updates"].items()], "not_understood": None}
    local_model["outputs"] = [reading, reading]
    folder = run_tasks(config_for(local_model), ["checkin"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=1, compare_schema=True)
    enforced, prompt_only = local_model["requests"][-2:]
    assert "response_format" in enforced and "response_format" not in prompt_only and "JSON schema" in prompt_only["messages"][0]["content"]
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "## Schema enforcement" in report and "| synthetic | prompt only | 1 of 1 | 0 | 0 | 0 | 1 of 1 | 100.0% |" in report
    assert "| 1 | synthetic |" in report and "| 2 | synthetic@no-schema" not in report  # Measured, never ranked.


# Decision rule ---------------------------------------------------------------------------------------------------------

def row(name, accuracy, valid=100, money_errors=0, pass_all=1.0, p95=10.0, judge=None):
    return {"name": name, "runs": 100, "valid": valid, "money_errors": money_errors, "pass_all": {"a": pass_all, "b": pass_all},
            "scores": {"a": accuracy, "b": accuracy}, "p95": p95, "judge": judge}


def test_the_decision_gates_ranks_and_breaks_ties():
    settings = rules({"max_p95_seconds": 60})
    decision = decide([row("fast", .90), row("best", .95), row("invalid", .99, valid=97), row("money", .99, money_errors=1),
                       row("flaky", .99, pass_all=.5), row("slow", .99, p95=90)], settings)
    assert decision["ranking"] == ["best", "fast"] and decision["winner"] == "best"
    assert set(decision["excluded"]) == {"invalid", "money", "flaky", "slow"}
    assert "valid answers 97.0% < 99%" in decision["excluded"]["invalid"][0]
    # Within 2 points: the more consistent one wins, then a calibrated judge.
    close = decide([row("a", .950, pass_all=.92), row("b", .945, pass_all=.99)], rules(None))
    assert close["ranking"] == ["b", "a"]
    judged = decide([row("a", .950, judge=2.0), row("b", .945, judge=3.5)], rules(None))
    assert judged["ranking"] == ["b", "a"]
    weighted = decide([{**row("x", 0), "scores": {"a": 1.0, "b": 0.0}}, {**row("y", 0), "scores": {"a": 0.0, "b": 1.0}}],
                      rules({"weights": {"a": 3}}))
    assert weighted["ranking"] == ["x", "y"] and weighted["accuracy"]["x"] == .75
    assert decide([row("bad", .5, valid=10)], rules(None))["note"] == "No candidate passes the gate."
    with pytest.raises(ValueError):
        rules({"min_pass_al": .9})
    with pytest.raises(ValueError):
        rules({"min_valid_rate": 2})


# Runner, report and judge -----------------------------------------------------------------------------------------------

def config_for(local_model, decision=None):
    return {"base_url": local_model["config"].base_url, "timeout_seconds": 60, "sampling": {}, "decision": rules(decision),
            "candidates": [{"name": "synthetic", "vision": "synthetic-vision", "reasoning": "synthetic-reasoning"}]}


def test_a_task_run_grades_with_the_apps_own_code_and_writes_a_report(tmp_path, local_model):
    cases = TASKS["checkin"].cases()[:2]
    readings = [{"updates": [{"lot_id": int(lot), "answer": event, "when": "on_date" if day else "today", "date": day}
                             for lot, (event, day) in case["expected"]["updates"].items()], "not_understood": None} for case in cases]
    local_model["outputs"] = list(readings)
    folder = run_tasks(config_for(local_model), ["checkin"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=2)
    lines = [json.loads(text) for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(line["task"], line["status"], line["grades"]["passed"], line["first_try_valid"]) for line in lines] == [("checkin", "ok", True, True)] * 2
    assert lines[0]["attempts"] == {"calls": 1, "follow_ups": 0, "failed": 0, "truncated": 0}
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "## Leaderboard" in report and "| synthetic | 100.0% | 2 of 2 | 100% (2/2) |" in report
    assert "**synthetic is the only candidate that passes the gate.**" in report
    # The next run answers wrongly: a schema failure, a failed case, and the diff names it.
    local_model["outputs"] = [{"updates": "not a list"}, readings[1]]
    again = run_tasks(config_for(local_model), ["checkin"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=2)
    lines = [json.loads(text) for text in (again / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert (lines[0]["status"], lines[0]["failure"], lines[0]["first_try_valid"]) == ("failed", "schema_fail", False)
    report = (again / "report.md").read_text(encoding="utf-8")
    assert f"newly failing {cases[0]['id']}" in report and "No candidate passes the gate." in report


def test_the_decisions_task_scores_label_probabilities_and_reports_calibration(tmp_path, local_model):
    import math

    from evals.tasks.decisions import calibration

    def reply(path, body):
        # Says "supported" for every claim with 70%: right on true claims, wrong on planted errors.
        prompt = body["input"][1]["content"]
        top = [("A", .7), ("B", .3)] if "Is the claim" in prompt else [("A", .9), ("B", .1)]
        return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "A", "logprobs": [
            {"token": "A", "logprob": 0, "top_logprobs": [{"token": token, "logprob": math.log(share)} for token, share in top]}]}]}]}

    local_model["decide"] = reply
    config = config_for(local_model)
    config["candidates"] = [{"name": "decider", "vision": "", "reasoning": "", "decision": "synthetic-reasoning",
                             "decision_provider": "lmstudio", "decision_url": config["base_url"]}]
    folder = run_tasks(config, ["decisions"], out=tmp_path, network_guard=False, echo=lambda _: None)
    lines = [json.loads(text) for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    support = [line for line in lines if "support" in line["tags"]]
    assert {line["grades"]["passed"] for line in support if "true_claim" in line["tags"]} == {False}  # 70% is under the 0.8 threshold.
    value = calibration(support)
    assert value["answered"] == len(support) and value["ece"] == pytest.approx(0.2)  # 70% confident, right half the time.
    assert value["fitted_temperature"] > 1  # Overconfident: the fit softens it.
    assert "Fitted temperature" in (folder / "report.md").read_text(encoding="utf-8")
    assert local_model["requests"] == []  # Decision requests only; no chat completions.
    # A decision-only candidate can't run the reading tasks, and the default task list leaves decisions out without one.
    with pytest.raises(ValueError, match="no model for a chosen task"):
        run_tasks(config, ["checkin"], out=tmp_path, network_guard=False, dry_run=True)


def test_a_dry_task_run_lists_every_task_and_calls_no_model(tmp_path, local_model):
    said = []
    assert run_tasks(config_for(local_model), out=tmp_path, network_guard=False, echo=said.append, dry_run=True) is None
    assert said[0].startswith("Dry run: transcription (36), identify (20), describe (24)") and local_model["requests"] == []
    with pytest.raises(ValueError, match="Unknown tasks"):
        run_tasks(config_for(local_model), ["nope"], out=tmp_path, network_guard=False, dry_run=True)


def test_the_judge_is_opt_in_refuses_itself_and_files_scores_by_judge(tmp_path, local_model):
    case = TASKS["payees"].cases()[0]
    describe = TASKS["describe"].cases()[0]
    local_model["outputs"] = [oracle("payees", case), {"description": "Groceries", "category": "groceries", "recurrence": None,
                                                       "item_categories": ["groceries"] * len(describe["input"]["items"])}]
    folder = run_tasks(config_for(local_model), ["payees", "describe"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=1)
    assert not (folder / "judge").exists()  # No judge unless asked.
    assert "not judged in this run" in (folder / "report.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="also a candidate"):
        judge_run(folder, "synthetic-reasoning", local_model["config"].base_url, echo=lambda _: None)
    local_model["outputs"] = [{"score": 4, "reason": "Specific.", "cited_span": "Groceries"}]
    judge_run(folder, "test-reasoning", local_model["config"].base_url, echo=lambda _: None)
    local_model["outputs"] = [{"score": 2, "reason": "Quotes nothing.", "cited_span": "not in the answer"}]
    judge_run(folder, "reasoner", local_model["config"].base_url, echo=lambda _: None)
    first = [json.loads(text) for text in (folder / "judge" / "test-reasoning.jsonl").read_text(encoding="utf-8").splitlines()]
    second = [json.loads(text) for text in (folder / "judge" / "reasoner.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(entry["task"], entry["score"], entry["calibrated"]) for entry in first] == [("describe", 4, {})]  # Only the rubric task.
    assert second[0]["score"] is None and "not a quote" in second[0]["failure"]
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "| test-reasoning | synthetic | describe | 4.00 | 1 | uncalibrated |" in report and "reasoner failed to give a valid verdict 1 times" in report


def test_calibration_needs_enough_agreeing_labels(tmp_path, local_model):
    assert kappa([1, 2, 3, 4], [1, 2, 3, 4]) == 1.0 and kappa([1, 1, 2, 2], [2, 2, 1, 1]) < 0
    case = TASKS["describe"].cases()[0]
    output = {"description": "Groceries", "category": "groceries", "recurrence": None, "item_categories": ["groceries"] * len(case["input"]["items"])}
    labels = tmp_path / "labels.jsonl"
    labels.write_text("".join(json.dumps({"rubric": "describe", "task": "describe", "input": case["input"], "output": output, "label": 4}) + "\n"
                              for _ in range(30)), encoding="utf-8")
    local_model["output"] = {"score": 4, "reason": "Specific.", "cited_span": "Groceries"}
    stored = calibrate(labels, "test-reasoning", local_model["config"].base_url, tmp_path, echo=lambda _: None)
    assert stored["describe"]["labels"] == 30 and stored["describe"]["within_one"] == 1.0 and stored["describe"]["calibrated"]
    labels.write_text(labels.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    assert not calibrate(labels, "reasoner", local_model["config"].base_url, tmp_path, echo=lambda _: None)["describe"]["calibrated"]  # Too few.


def test_answers_can_be_exported_for_hand_labels(tmp_path, local_model):
    describe = TASKS["describe"].cases()[0]
    local_model["output"] = {"description": "Groceries", "category": "groceries", "recurrence": None,
                             "item_categories": ["groceries"] * len(describe["input"]["items"])}
    folder = run_tasks(config_for(local_model), ["describe"], out=tmp_path, network_guard=False, echo=lambda _: None, case_limit=3)
    assert export_labels(folder, "describe", tmp_path / "to-label.jsonl") == 3
    first = json.loads((tmp_path / "to-label.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first["label"] is None and first["rubric"] == "describe" and first["output"]["description"] == "Groceries"
