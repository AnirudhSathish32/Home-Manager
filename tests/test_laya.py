"""In-process Laya: offline loading, advisory scoring and shadow classification (never gating)."""

import os
from pathlib import Path
import socket
import sys
import types

import pytest

from home_manager.jobs import Work
from home_manager.laya_runtime import OFFLINE, LayaRuntime, LayaUnavailable
from home_manager.reviewer import ReviewerConfig
from test_extraction import classification, extract, identity, receipt, receipt_items, receipt_summary  # noqa: F401 (fixture)


class FakeLaya(LayaRuntime):
    """The real runtime (batching, validation, telemetry) with a scripted model in place of the 846 MB checkpoint."""

    def __init__(self, supported=0.95, doubted=(), kind="receipt", fail=False, present=True):
        super().__init__(Path("unused"))
        self.supported, self.doubted, self.kind, self.fail, self.present, self.calls = supported, doubted, kind, fail, present, []

    def installed(self):
        return self.present

    def _load(self):
        if self.fail:
            raise LayaUnavailable("Laya weights are not installed.")
        self._agent = self

    def predict_batch(self, states, questions):
        self.calls.append((states, questions))
        if "document_type" in questions:
            return [{"answers": {"document_type": {"type": "choice", "choice": self.kind, "answer_confidence": 0.9}}}]
        return [{"answers": {"supported": {"type": "noul", "noul": 0.1 if any(word in state["claim"] for word in self.doubted) else self.supported}}}
                for state in states]


def test_runtime_reports_missing_weights_and_loads_offline(tmp_path, monkeypatch):
    runtime = LayaRuntime(tmp_path / "laya")
    assert runtime.status()["installed"] is False
    with pytest.raises(LayaUnavailable, match="not installed"):
        runtime.decide(["x"], {})
    for name in ("rl_agent_config.json", "model.safetensors", "tokenizer/tokenizer.json"):
        (tmp_path / "laya" / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "laya" / name).write_text("{}")
    loaded = {}

    class Agent:
        def __init__(self, path):
            loaded.update(path=path, env={key: os.environ.get(key) for key in OFFLINE})

        def predict_batch(self, states, questions):
            return [{"answers": {"supported": {"noul": 0.9}}} for _ in states]

    for key in OFFLINE:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setitem(sys.modules, "laya.agent", types.SimpleNamespace(Agent=Agent))
    long_claim = ("total: 1", ["x" * 400])
    assert runtime.support([("total: 13.52", ["TOTAL $13.52"]), long_claim]) == [0.9, None]  # Never truncated.
    assert loaded == {"path": str(tmp_path / "laya"), "env": OFFLINE}  # Offline and telemetry-free before loading.
    assert runtime.status()["loaded"] is True


def test_laya_runs_on_every_extraction_and_a_doubted_value_sends_the_record_to_review(receipt, local_model):
    manager, doc, parse_id = receipt
    fake = FakeLaya(doubted=("merchant",), kind="bill")
    manager.laya = manager.extractions.laya = fake  # Installed; no setting needed.
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    run = extract(manager, doc, parse_id)
    laya = run["result"]["laya"]
    assert laya["classification"] == {"document_type": "bill", "confidence": 0.9, "agrees": False}
    assert [check["field"] for check in laya["checks"] if not check["supported"]] == ["merchant"]
    assert len(laya["checks"]) == 10  # 7 proposed summary values + 3 item rows, in one batched call.
    assert len(fake.calls) == 2 and len(fake.calls[1][0]) == 10
    receipt_id = run["publication"]["id"]
    record = manager.ledger.record("receipt", receipt_id)
    # A doubted value is a veto; the shadow classification alone is not (its scores are not calibrated for these documents).
    assert record["review_status"] == "needs_review"
    assert record["issues"] == ["Merchant: the independent check could not confirm it from its cited text."]
    assert manager.store.documents(manager.source)["items"][0]["folder"] == "Receipts"  # Filing unaffected.
    assert [row["model_id"] for row in manager.store.model_runs(run["id"])][:2] == ["laya (in-process)"] * 2
    # Confirming the merchant answers the doubt, and the record passes the automatic checks.
    record = manager.ledger.correct("receipt", receipt_id, {"merchant": "Local Test Cafe"})
    assert (record["review_status"], record["review_source"], record["issues"]) == ("verified", "automatic", [])


def test_laya_can_only_flag_a_failure_never_blocks_and_absent_weights_skip_it(receipt, local_model):
    manager, doc, parse_id = receipt
    manager.laya = manager.extractions.laya = FakeLaya(fail=True)
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    run = extract(manager, doc, parse_id)
    assert run["status"] == "succeeded" and run["publication"]["status"] == "published"
    assert run["result"]["laya"] == {"advisory": True, "error": "Laya weights are not installed."}
    assert manager.ledger.record("receipt", run["publication"]["id"])["review_status"] == "verified"  # No doubt, no veto.
    manager.laya = manager.extractions.laya = FakeLaya(present=False)
    local_model["outputs"] = [classification(), receipt_summary(), identity(), receipt_items()]
    assert "laya" not in extract(manager, doc, parse_id)["result"]  # A different option set: a new run, without Laya.
    assert ReviewerConfig().enabled is False and ReviewerConfig(provider="chat", model="m").enabled and ReviewerConfig(provider="laya").enabled


def test_laya_audit_review_is_advisory_and_never_blocks_filing(receipt):
    from home_manager.reviewer import laya_review
    from test_reasoning import proposal
    manager, doc, parse_id = receipt
    analysis = proposal()
    analysis["facts"] += [{"kind": "merchant", "value": "Local Test Cafe", "status": "proposed", "note": "", "evidence": [{"line_id": "line-1", "quote": "LOCAL TEST CAFE"}]},
                          {"kind": "purchase_date", "value": "2026-09-22", "status": "proposed", "note": "", "evidence": [{"line_id": "line-2", "quote": "2026-09-22"}]}]
    review = laya_review(FakeLaya(doubted=("merchant",)), analysis, Work.detached())
    assert review["advisory"] and review["classification_supported"] and review["verdict"] == "needs_attention"
    assert review["findings"] == ["fact 3: Laya could not confirm this from its cited text."]

    def filed(reviewer, status, result):
        run = {"status": "succeeded", "parse_run_id": parse_id, "result": analysis,
               "review": {"status": status, "result": result, "config_json": ReviewerConfig(provider=reviewer, model="m").model_dump_json()}}
        manager.store.library.file_analysis(doc["id"], run)
        return manager.store.documents(manager.source)["items"][0]["folder"]

    assert filed("chat", "failed", None) == "Unfiled"  # A failed chat reviewer still blocks automatic filing.
    assert filed("laya", "failed", None) == "Receipts"  # A failed or doubtful Laya review never does.


@pytest.mark.skipif(os.environ.get("RUN_LAYA_TESTS") != "1", reason="Opt-in: loads the real 846 MB Laya checkpoint")
def test_real_laya_checkpoint_runs_without_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Laya attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    runtime = LayaRuntime(Path(os.environ["LOCALAPPDATA"]) / "HomeManager" / "models" / "laya")
    right, wrong = runtime.support([("total: 13.52", ["TOTAL $13.52"]), ("total: 31.52", ["TOTAL $13.52"])])
    assert right > 0.8 > 0.2 > wrong
