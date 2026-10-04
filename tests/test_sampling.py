"""Eval hooks in the model transport: sampling overrides (eval_plan.md A2) and attempt recording (A3)."""

import json

import pytest

from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.reviewer import ReviewerConfig
from home_manager.models.model_client import recording, request_completion
from home_manager.models.vision import VisionConfig
from test_extraction import RECEIPT, classification, extract, receipt_summary, transcribe, value

SCHEMA = {"type": "object", "properties": {"full_text": {"type": "string"}}, "required": ["full_text"], "additionalProperties": False}


def ask(config, system="Read it."):
    return request_completion(config, {"max_tokens": 64, "messages": [{"role": "system", "content": system}, {"role": "user", "content": "hi"}],
                                       "response_format": {"type": "json_schema", "json_schema": {"name": "t", "strict": True, "schema": SCHEMA}}})


def test_unset_overrides_keep_saved_settings_and_reuse_keys_unchanged():
    # Configs are saved as settings and copied into run options (reuse keys); the new fields must not appear.
    assert ReasoningConfig(model="m").model_dump() == {"base_url": "http://127.0.0.1:1234/v1", "model": "m"}
    assert json.loads(VisionConfig(model="m").model_dump_json()) == {"base_url": "http://127.0.0.1:1234/v1", "model": "m", "organize_after_scan": True}
    assert ReviewerConfig(model="m", provider="chat").model_dump() == {"base_url": "http://127.0.0.1:1234/v1", "model": "m", "provider": "chat"}
    # Settings saved before the fields existed still load.
    assert ReasoningConfig.model_validate_json('{"base_url": "http://127.0.0.1:1234/v1", "model": "m"}').temperature is None


def test_set_overrides_are_saved_and_round_trip():
    config = ReasoningConfig(model="m", temperature=0, seed=1234, schema_enforced=False)
    data = config.model_dump()
    assert (data["temperature"], data["seed"], data["schema_enforced"]) == (0, 1234, False)
    assert ReasoningConfig.model_validate(data) == config
    with pytest.raises(ValueError):
        ReasoningConfig(model="m", temperature=3)


def test_default_request_keeps_the_app_sampling(local_model):
    ask(local_model["config"])
    request = local_model["requests"][-1]
    assert request["temperature"] == 0.1 and "seed" not in request and request["response_format"]["json_schema"]["schema"] == SCHEMA


def test_overrides_reach_the_request(local_model):
    config = VisionConfig(base_url=local_model["config"].base_url, model=local_model["config"].model, temperature=0, seed=7)
    ask(config)
    request = local_model["requests"][-1]
    assert (request["temperature"], request["seed"]) == (0, 7)


def test_unenforced_schema_moves_into_the_system_prompt(local_model):
    config = VisionConfig(base_url=local_model["config"].base_url, model=local_model["config"].model, schema_enforced=False)
    assert json.loads(ask(config)) == local_model["output"]
    request = local_model["requests"][-1]
    assert "response_format" not in request
    system = request["messages"][0]
    assert system["role"] == "system" and system["content"].startswith("Read it.\n\nReply with one JSON object")
    assert json.dumps(SCHEMA, separators=(",", ":")) in system["content"] and len(request["messages"]) == 2


def test_recording_sees_both_attempts_of_a_correction_turn(tmp_path, local_model):
    manager, doc, parse_id = transcribe(tmp_path, local_model, RECEIPT)
    try:
        attempts = []
        invented = receipt_summary(total=value("26.00", 7, "Total 25.00"))  # Rejected, so the header step is asked again.
        local_model["outputs"] = [classification(), invented, invented]
        with recording(attempts.append):
            run = extract(manager, doc, parse_id)
        assert run["status"] == "failed"
        assert [attempt["task"] for attempt in attempts] == ["extraction"] * 3 and len({attempt["work_id"] for attempt in attempts}) == 1
        # The raw text of every attempt, including the first, rejected try that the correction turn hides.
        assert [json.loads(attempt["text"]) for attempt in attempts] == [classification(), invented, invented]
        assert all(attempt["status"] == "succeeded" and attempt["finish_reason"] == "stop" for attempt in attempts)
        assert attempts[1]["params"] == {"temperature": 0.1, "seed": None, "max_tokens": 2048, "schema_enforced": True}
        assert attempts[1]["owner_id"] == run["id"] and attempts[1]["metrics"]["total_ms"] >= 0
    finally:
        manager.close()
    # Outside the block nothing is recorded.
    ask(local_model["config"])
    assert len(attempts) == 3


def test_failed_requests_are_recorded_and_a_broken_recorder_changes_nothing(local_model):
    attempts = []

    def broken(_attempt):
        raise RuntimeError("recorder bug")

    with recording(broken), recording(attempts.append):
        assert json.loads(ask(local_model["config"])) == local_model["output"]
        local_model["status"] = 500
        with pytest.raises(ValueError):
            ask(local_model["config"])
    assert [(attempt["status"], attempt["error_category"], attempt["text"] is None) for attempt in attempts] == [
        ("succeeded", None, False), ("failed", "http_500", True)]
