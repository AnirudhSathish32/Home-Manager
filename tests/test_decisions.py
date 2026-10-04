"""Plug-and-play decision models (models/decisions.py): LM Studio logprobs and /v1/systemone, advisory only."""

import math

import pytest

from home_manager.documents.reviewer import ReviewerConfig
from home_manager.models import decisions
from home_manager.models.decisions import DecisionConfig
from test_extraction import receipt  # noqa: F401 (fixture)


def responses_reply(top):
    return {"output": [{"type": "message", "content": [{"type": "output_text", "text": "A",
            "logprobs": [{"token": "A", "logprob": 0, "top_logprobs": [{"token": t, "logprob": math.log(p)} for t, p in top]}]}]}],
            "usage": {"input_tokens": 40, "output_tokens": 1}}


def config(local_model, provider="lmstudio", **changes):
    return DecisionConfig(provider=provider, base_url=local_model["config"].base_url, model="synthetic-reasoning", **changes)


def test_lmstudio_reads_label_probabilities_merging_variants(local_model):
    local_model["decide"] = lambda path, body: responses_reply([("A", 0.6), (" A", 0.2), ("b", 0.1), ("The", 0.1)])
    assert decisions.support(config(local_model), [("total: 25.00", ["Total 25.00"])]) == [pytest.approx(0.8 / 0.9)]
    path, body = local_model["decisions"][0]
    assert path == "/v1/responses" and body["max_output_tokens"] == 1 and body["top_logprobs"] == 20


def test_lmstudio_low_coverage_is_unknown_and_oversize_is_refused(local_model):
    local_model["decide"] = lambda path, body: responses_reply([("<think>", 0.9), ("A", 0.05)])
    assert decisions.support(config(local_model), [("x", ["y"]), ("x", ["z" * 30000])]) == [None, None]
    assert len(local_model["decisions"]) == 1  # The oversize claim never reached the server.


def test_systemone_choice_and_temperature(local_model):
    local_model["decide"] = lambda path, body: {"answers": {"document_type": {"type": "choice", "choice": "receipt",
                                                            "probabilities": {"receipt": 0.7, "bill": 0.3}}}}
    kind, confidence = decisions.classify(config(local_model, "systemone"), "LOCAL TEST CAFE", {"receipt": "r", "bill": "b"})
    assert (kind, confidence) == ("receipt", pytest.approx(0.7))
    sharper = decisions.classify(config(local_model, "systemone", calibration_temperature=0.5), "x", {"receipt": "r", "bill": "b"})[1]
    assert sharper > 0.7


def scripted(doubted=(), kind="bill"):
    """LM Studio replies: the document type `kind`, and every claim supported unless it names a doubted word."""
    def reply(path, body):
        prompt = body["input"][1]["content"]
        if "What kind of household financial document" in prompt:
            label = decisions.LABELS[list(decisions.DOCUMENT_TYPES).index(kind)]
            return responses_reply([(label, 0.9), ("A" if label != "A" else "B", 0.1)])
        state = prompt.split("</state>")[0]
        return responses_reply([("B", 0.9), ("A", 0.1)] if any(word in state for word in doubted) else [("A", 0.95), ("B", 0.05)])
    return reply


def test_every_extraction_is_checked_and_a_doubted_value_sends_the_record_to_review(receipt, local_model):
    from test_extraction import classification, extract, identity, receipt_items, receipt_summary
    manager, doc, parse_id = receipt
    manager.configure_decision(config(local_model))
    local_model["decide"] = scripted(doubted=('"claim": "merchant',))
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    run = extract(manager, doc, parse_id)
    check = run["result"]["decision"]
    assert check["model"]["model"] == "synthetic-reasoning" and check["advisory"]
    assert check["classification"] == {"document_type": "bill", "confidence": pytest.approx(0.9), "agrees": False}
    assert [item["field"] for item in check["checks"] if not item["supported"]] == ["merchant"]
    assert len(check["checks"]) == 10 and len(local_model["decisions"]) == 11  # One type question, then one per value.
    assert "D. bill: a bill or invoice asking for payment" in local_model["decisions"][0][1]["input"][1]["content"]
    assert run["config"]["decision"]["model"] == "synthetic-reasoning"  # Part of the reuse key.
    record = manager.ledger.record("receipt", run["publication"]["id"])
    # A doubted value is a veto; the shadow classification alone is not.
    assert record["review_status"] == "needs_review"
    assert record["issues"] == ["Merchant: the independent check could not confirm it from its cited text."]
    assert manager.store.documents()["items"][0]["folder"] == "Receipts"  # Filing unaffected.
    assert "synthetic-reasoning" in [row["model_id"] for row in manager.store.model_runs(run["id"])]


def test_a_failing_decision_model_never_blocks_and_off_skips_it(receipt, local_model):
    from test_extraction import classification, extract, identity, receipt_items, receipt_summary
    manager, doc, parse_id = receipt
    manager.configure_decision(config(local_model))  # No "decide" script: the server answers 404.
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    run = extract(manager, doc, parse_id)
    assert run["status"] == "succeeded" and run["publication"]["status"] == "published"
    assert run["result"]["decision"]["error"] and run["result"]["decision"]["advisory"]
    assert manager.ledger.record("receipt", run["publication"]["id"])["review_status"] == "verified"
    manager.configure_decision(DecisionConfig())
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    assert "decision" not in extract(manager, doc, parse_id)["result"]  # A different option set: a new run, unchecked.


def test_decision_review_is_advisory_and_never_blocks_filing(receipt, local_model):
    from home_manager.core.jobs import Work
    from home_manager.documents.reviewer import decision_review, review
    from test_reasoning import proposal
    manager, doc, parse_id = receipt
    analysis = proposal()
    analysis["facts"] += [{"kind": "merchant", "value": "Local Test Cafe", "status": "proposed", "note": "", "evidence": [{"line_id": "line-1", "quote": "LOCAL TEST CAFE"}]},
                          {"kind": "purchase_date", "value": "2026-09-22", "status": "proposed", "note": "", "evidence": [{"line_id": "line-2", "quote": "2026-09-22"}]}]
    local_model["decide"] = scripted(doubted=('"claim": "merchant',))
    result = decision_review(config(local_model), analysis, Work.detached())
    assert result["advisory"] and result["verdict"] == "needs_attention" and "not yet calibrated" in result["scope"]
    assert [finding for finding in result["findings"] if "could not confirm" in finding] == ["fact 3: the decision model could not confirm this from its cited text."]
    with pytest.raises(ValueError, match="Choose a decision model"):
        review(ReviewerConfig(provider="decision"), analysis, {"lines": []}, decision=DecisionConfig())

    def filed(reviewer, status):
        run = {"status": "succeeded", "parse_run_id": parse_id, "result": analysis,
               "review": {"status": status, "result": None, "config_json": ReviewerConfig(provider=reviewer, model="m").model_dump_json()}}
        manager.store.library.file_analysis(doc["id"], run)
        return manager.store.documents()["items"][0]["folder"]

    assert filed("chat", "failed") == "Unfiled"  # A failed chat reviewer still blocks automatic filing.
    assert filed("decision", "failed") == "Receipts"  # A failed decision review never does.


def test_settings_test_reports_a_model_that_answers_without_a_label(local_model):
    local_model["decide"] = lambda path, body: responses_reply([("<think>", 0.99)])
    result = decisions.check_decision_model(config(local_model))
    assert result["reachable"] and "did not answer with an option letter" in result["problem"]
    local_model["decide"] = scripted()
    assert decisions.check_decision_model(config(local_model))["problem"] is None
    local_model["decide"] = lambda path, body: {"answers": {"supported": {"type": "noul", "noul": 0.1}}}
    assert decisions.check_decision_model(config(local_model, "systemone"))["problem"] is None
    assert local_model["decisions"][-1][0] == "/v1/systemone"


def test_config_rules_and_legacy_reviewer():
    with pytest.raises(ValueError):
        DecisionConfig(provider="lmstudio", base_url="http://example.com:1234/v1", model="m")
    assert not DecisionConfig().enabled
    assert ReviewerConfig(provider="laya").provider == "decision"
