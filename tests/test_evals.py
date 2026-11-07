"""The eval suite (evals/) on synthetic data only: grading, the local-only guard, intake, a full run and the summary allowlist."""

import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import zipfile

import pytest

from evals import intake
from evals.corpus import TAGS, Corpus
from evals.graders import (
    FAILURE_KINDS,
    GUESS_KINDS,
    arithmetic,
    compare,
    failure_kind,
    grade,
    grade_stubs,
    guess_counts,
    match_rows,
    pay_reader,
    same_name,
    score,
    split_is_right,
    table_reader,
)
from evals.guard import GuardError, _hook, check_server
from evals.report import case_pass, check_summary, rebuild
from evals.run import load_config, run
from evals.synthetic import PAYSTUB_FILES, PAYSTUB_SEED, aligned_paystub, documents, money, write_case
from evals.synthetic import create as create_synthetic
from home_manager.core.answers import CRITICAL as CRITICAL_FIELDS
from home_manager.core.answers import ROWS, Answers, FieldAnswer, empty_answers
from home_manager.core.money import EXPONENTS
from home_manager.documents.layout_context import evidence_lines
from home_manager.documents.pdf_reader import complete_pdf, read_result, worker
from home_manager.finance.statement_dates import Rebuild
from home_manager.library.storage import digest_file
from test_donations import DESCRIBE, extracted  # noqa: F401
from test_extraction import MISSING, RECEIPT, classification, identity, receipt, receipt_items, receipt_summary  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def receipt_answers(**states):
    answers = empty_answers("receipt", {"merchant": "Local Test Cafe", "purchase_date": "2026-09-22", "currency": "USD", "subtotal_minor": 2000,
                                        "tax_minor": 200, "tip_minor": 300, "total_minor": 2500,
                                        "items": [{"description": "LATTE", "line_total_minor": 500}, {"description": "LATTE", "line_total_minor": 500},
                                                  {"description": "SANDWICH", "line_total_minor": 1000}]})
    for name, state in states.items():
        answers.fields[name].state = state
    return answers


# Grading ---------------------------------------------------------------------------------------------------------

def test_mismatches_get_one_category_each():
    assert compare("total_minor", 2500, 2500) is None and compare("total_minor", None, None) is None
    assert [compare("total_minor", 2500, value) for value in (None, -2500, 250, 25000, 2600, 2050, 1234)] == [
        "missing", "sign", "scale", "scale", "digit", "digit", "wrong_value"]
    assert compare("tip_minor", None, 300) == "invented"
    assert [compare("purchase_date", "2026-09-04", value) for value in ("2026-04-09", "2025-09-04", "2026-09-05")] == ["date_swap", "year", "wrong_value"]
    assert compare("currency", "USD", "CAD") == "wrong_value"
    assert same_name("Costco", "COSTCO WHOLESALE #123") and same_name("Local Test Cafe Inc", "LOCAL TEST CAFE")
    assert not same_name("Target", "Walmart") and not same_name("Ab", "Ab Foods")


def test_rows_match_as_a_multiset_and_count_duplicates():
    expected = [{"description": "LATTE", "line_total_minor": 500}] * 2 + [{"description": "SANDWICH", "line_total_minor": 1000}]
    predicted = [{"description": "LATTE", "line_total_minor": 500}] * 3 + [{"description": "WATER", "line_total_minor": 100}]
    pairs, missing, extra, duplicate = match_rows("receipt", expected, predicted)
    assert (len(pairs), missing, extra, duplicate) == (2, 1, 1, 1)


def test_only_checked_fields_and_complete_rows_are_scored():
    answers = receipt_answers(total_minor="correct", merchant="fixed")
    graded = grade(answers, {"merchant": "LOCAL TEST CAFE", "total_minor": 250, "tip_minor": 999, "items": []})
    assert graded["fields"]["total_minor"] == {"checked": True, "correct": False, "error": "scale", "state": "correct"}
    assert graded["fields"]["merchant"]["correct"] and graded["fields"]["tip_minor"] == {"checked": False, "correct": None, "error": None}
    assert graded["rows"] == {"scored": False} and graded["document"] == {"checked_fields": 2, "fully_checked": False, "perfect": None}
    everything = Answers.model_validate({**receipt_answers().model_dump(), "rows_state": "correct", "rows_complete": True,
                                         "fields": {name: {"value": answer.value, "state": "correct"} for name, answer in receipt_answers().fields.items()}})
    record = {**{name: answer.value for name, answer in everything.fields.items()}, "items": everything.rows}
    assert grade(everything, record)["document"] == {"checked_fields": 7, "fully_checked": True, "perfect": True}
    assert grade(everything, record)["arithmetic"] is True and score(grade(everything, record)) == 1.0
    assert grade(everything, None)["fields"]["total_minor"]["error"] == "missing" and grade(everything, None)["arithmetic"] is None
    # One wrong field of 7 and one of 3 rows missing: 8 of 10 right.
    assert score(grade(everything, {**record, "tip_minor": 30, "items": record["items"][:2]})) == 0.8
    assert score(None) == 0.0 and score(grade(receipt_answers(), record)) is None  # Nothing was checked.


def test_arithmetic_checks_the_models_own_numbers():
    receipt = {"subtotal_minor": 2000, "tax_minor": 200, "tip_minor": None, "total_minor": 2200, "items": [{"line_total_minor": 1200}, {"line_total_minor": 800}]}
    assert arithmetic("receipt", receipt) is True
    assert arithmetic("receipt", {**receipt, "total_minor": 2300}) is False
    assert arithmetic("receipt", {**receipt, "items": [{"line_total_minor": 1200}]}) is False
    assert arithmetic("receipt", {"total_minor": 600, "items": []}) is None  # A total alone: nothing to add up.
    bank = {"opening_balance_minor": 1000, "closing_balance_minor": 1500, "transactions": [{"amount_minor": -500}, {"amount_minor": 1000}]}
    assert arithmetic("bank_statement", bank) is True and arithmetic("bank_statement", {**bank, "closing_balance_minor": 1400}) is False
    card = {"previous_balance_minor": 1000, "statement_balance_minor": 1300, "transactions": [{"amount_minor": -1300}, {"amount_minor": 1000}]}
    assert arithmetic("credit_card_statement", card) is True  # Charges (negative) add to what is owed.
    stub = {"gross_pay_minor": 1000, "net_pay_minor": 700, "lines": [{"line_group": "earnings", "current_minor": 1000},
                                                                      {"line_group": "tax", "current_minor": 200}, {"line_group": "pre_tax", "current_minor": 100},
                                                                      {"line_group": "employer_paid", "current_minor": 50}]}
    assert arithmetic("paystub", stub) is True and arithmetic("paystub", {**stub, "net_pay_minor": 650}) is False
    # A bill's lines make up its new charges; a past-due balance is in the amount due, not in them.
    phone = {"total_minor": 1500, "amount_due_minor": 2000, "items": [{"line_total_minor": 1000}, {"line_total_minor": 500}]}
    assert arithmetic("bill", phone) is True and arithmetic("bill", {**phone, "total_minor": 2000}) is False


def test_table_reader_counts_exact_rows_and_reconciliation_and_never_values():
    def statement(kind, opening, closing, rows, state="correct"):
        names = ("previous_balance_minor", "statement_balance_minor") if kind == "credit_card_statement" else ("opening_balance_minor", "closing_balance_minor")
        fields = {name: {"value": None, "state": "correct"} for name in CRITICAL_FIELDS[kind]}
        fields.update({names[0]: {"value": opening, "state": state}, names[1]: {"value": closing, "state": state}})
        return Answers(document_type=kind, fields=fields, rows=[{"posted_date": day, "description": "X", "amount_minor": amount} for day, amount in rows],
                       rows_state="correct", rows_complete=True)

    def read(*rows, dropped=0):
        return Rebuild(True, rows=[{"posted_date": day, "amount_minor": amount} for day, amount in rows], dropped=dropped)

    bank = statement("bank_statement", 1000, 1300, [("2026-10-01", -200), ("2026-10-01", -200), ("2026-10-02", 700)])
    assert table_reader(bank, read(("2026-10-01", -200), ("2026-10-01", -200), ("2026-10-02", 700))) == {
        "rows": 3, "recorded": 3, "exact": 3, "reconciled": True, "dropped": 0, "unplaced": None, "failed": False}
    # A repeated row counts once each; a wrong direction, a wrong date and an extra row are not exact; recorded rows still decide reconciliation.
    wrong = table_reader(bank, read(("2026-10-01", -200), ("2026-10-02", -700), ("2026-10-03", 700), ("2026-10-03", 5), dropped=2), unplaced=1)
    assert (wrong["recorded"], wrong["exact"], wrong["reconciled"], wrong["dropped"], wrong["unplaced"]) == (4, 1, False, 2, 1)
    # A card statement's charges are negative and add to what is owed.
    card = statement("credit_card_statement", 1000, 1500, [("2026-10-01", -700), ("2026-10-02", 200)])
    assert table_reader(card, read(("2026-10-01", -700), ("2026-10-02", 200)))["reconciled"] is True
    assert table_reader(card, read(("2026-10-01", 700), ("2026-10-02", 200)))["reconciled"] is False
    # Balances nobody checked cannot be reconciled; a reader that raised recorded nothing.
    assert table_reader(statement("bank_statement", None, None, [("2026-10-01", 1)], "unchecked"), read(("2026-10-01", 1)))["reconciled"] is None
    assert table_reader(bank, None, failed=True) == {"rows": 3, "recorded": 0, "exact": 0, "reconciled": False, "dropped": 0, "unplaced": None, "failed": True}


def test_every_failure_gets_one_kind():
    def attempt(status="succeeded", category=None, finish="stop"):
        return {"status": status, "error_category": category, "finish_reason": finish, "follow_up": False}

    cases = [("The model server stopped responding while switching models.", [], "load_fail"),
             ("Local model server returned HTTP 500. The server reported insufficient memory.", [attempt("failed", "http_500")], "out_of_memory"),
             ("Local model server returned HTTP 400. The server reported a context limit.", [attempt("failed", "http_400")], "context_limit"),
             ("Local model request timed out", [attempt("failed", "timeout")], "model_timeout"),
             ("Local model connection failed", [attempt("failed", "connection")], "model_connection"),
             ("Local model server returned HTTP 503.", [attempt("failed", "http_503")], "model_http"),
             ("Local model returned an invalid completion stream.", [attempt("failed", "invalid_stream")], "model_stream"),
             ("Extraction output failed validation: field: json_invalid.", [attempt(finish="length")], "truncated"),
             ("Extraction output failed validation: field: json_invalid. Nothing was published.", [attempt()], "parse_fail"),
             ("Extraction output failed validation: total.value: missing.", [attempt()], "schema_fail"),
             ("Model output did not match the full-text schema. No result was published.", [attempt()], "schema_fail"),
             ("Extraction failed validation: total: the amount is not printed in its cited evidence.", [attempt(), attempt()], "validator_fail"),
             ("Something else.", [attempt()], "other")]
    assert {kind for *_, kind in cases} == set(FAILURE_KINDS)
    for error, attempts, kind in cases:
        assert failure_kind(error, attempts) == kind, error


# Local-only guard --------------------------------------------------------------------------------------------------

def test_the_guard_refuses_remote_servers_the_gpu_relay_and_role_aliases(monkeypatch):
    for url in ("http://192.168.1.5:1234/v1", "http://100.64.1.2:1234/v1", "https://127.0.0.1:1234/v1", "http://127.0.0.1:8766/v1"):
        with pytest.raises(GuardError):
            check_server(url, probe=False)
    with pytest.raises(GuardError, match="not a model ID"):
        check_server("http://127.0.0.1:1234/v1", ["home-manager/reasoning"], probe=False)
    monkeypatch.setattr("evals.guard.get_json", lambda config, path: {"managed_by": "home-manager-gpu-host"})
    with pytest.raises(GuardError, match="relay"):
        check_server("http://127.0.0.1:9000/v1", ["some-model"])
    monkeypatch.setattr("evals.guard.get_json", lambda config, path: {"models": []})
    assert check_server("http://127.0.0.1:9000/v1", ["some-model"]) == "http://127.0.0.1:9000/v1"


def test_the_network_guard_allows_only_loopback():
    _hook("socket.connect", (None, ("127.0.0.1", 1234)))
    _hook("socket.getaddrinfo", ("localhost", 1234, 0, 0, 0, 0))
    with pytest.raises(GuardError):
        _hook("socket.connect", (None, ("93.184.216.34", 443)))
    with pytest.raises(GuardError):
        _hook("socket.getaddrinfo", ("api.example.com", 443, 0, 0, 0, 0))
    # Installed for real in a child process: the web is unreachable, loopback is not.
    script = ("import socket\nfrom evals.guard import install_network_guard, GuardError\ninstall_network_guard()\n"
              "try:\n    socket.create_connection(('example.com', 443), timeout=2)\nexcept GuardError:\n    print('refused')\n")
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert result.stdout.strip() == "refused", result.stderr


# Intake ------------------------------------------------------------------------------------------------------------

def donation_bundle(manager, receipt_id, tmp_path):
    donations = manager.donations()
    check = donations.start("receipt", receipt_id)
    rows = [{"description": row["description"]["input"], "line_total_minor": row["line_total_minor"]["input"]} for row in check["rows"]]
    fields = {field["name"]: {"text": field["input"] or None, "state": "correct"} for field in check["fields"]}
    fields["merchant"] = {"text": "Local Test Cafe Inc", "state": "fixed"}
    donations.save(check["id"], fields, rows=rows, rows_state="correct", rows_complete=True, finish=True)
    exported = donations.export([check["id"]], donor="d07")
    path = tmp_path / exported["name"]
    path.write_bytes(donations.bundle_file(exported["name"]).read_bytes())
    return path


class AlwaysTest(random.Random):
    def random(self):
        return 0.0


def test_intake_takes_a_bundle_once_admits_tunes_and_withdraws(extracted, tmp_path):  # noqa: F811
    manager, receipt_id = extracted
    bundle = donation_bundle(manager, receipt_id, tmp_path)
    corpus = Corpus.create(tmp_path / "corpus")
    [case_id] = intake.add(corpus, bundle, rng=AlwaysTest())
    case = corpus.case(case_id)
    assert (case.info.donor, case.info.status, case.info.split, case.info.document_type) == ("d07", "pending", "test", "receipt")
    assert case.original.read_bytes().startswith(b"\x89PNG") and case.answers().fields["merchant"].value == "Local Test Cafe Inc"
    assert corpus.cases() == [] and len(corpus.cases(("pending",))) == 1
    with pytest.raises(ValueError, match="already taken in"):
        intake.add(corpus, bundle)
    intake.admit(corpus, case_id)
    assert [case.id for case in corpus.cases(split="test")] == [case_id]
    intake.tuned(corpus, case_id)
    assert corpus.case(case_id).info.split == "dev" and corpus.case(case_id).info.used_for_tuning
    assert intake.withdraw(corpus, "d07") == 1
    assert corpus.cases(("pending", "admitted", "dropped")) == [] and "d07" in corpus.manifest()["withdrawn"]


def test_intake_refuses_unsafe_or_foreign_bundles(tmp_path):
    corpus = Corpus.create(tmp_path / "corpus")
    unsafe = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(unsafe, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format": "home-manager-donation/1", "bundle_id": "x", "cases": []}))
        bundle.writestr("../escape.txt", "x")
    with pytest.raises(ValueError, match="unsafe path"):
        intake.add(corpus, unsafe, donor="d01")
    foreign = tmp_path / "foreign.zip"
    with zipfile.ZipFile(foreign, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps({"format": "something-else"}))
    with pytest.raises(ValueError, match="not a Home Manager donation"):
        intake.add(corpus, foreign, donor="d01")
    assert intake.main(["list", str(tmp_path / "not-a-corpus")]) == 1


# A full run ---------------------------------------------------------------------------------------------------------

def config_for(local_model):
    return {"base_url": local_model["config"].base_url, "timeout_seconds": 60,
            "candidates": [{"name": "synthetic", "vision": "synthetic-vision", "reasoning": "synthetic-reasoning"}]}


def scripted(summary):
    return [{"full_text": "\n".join(RECEIPT)}, classification(), summary, identity(), receipt_items(), DESCRIBE, {"rewards": []}]


def test_a_run_reads_each_case_through_the_real_pipeline_grades_it_and_reports_regressions(extracted, local_model, tmp_path):  # noqa: F811
    manager, receipt_id = extracted
    bundle = donation_bundle(manager, receipt_id, tmp_path)
    corpus = Corpus.create(tmp_path / "corpus")
    [case_id] = intake.add(corpus, bundle, rng=AlwaysTest())
    intake.admit(corpus, case_id)
    local_model["outputs"] = scripted(receipt_summary())
    first = run(corpus, config_for(local_model), network_guard=False, echo=lambda _: None, keep_outputs=True)
    [line] = [json.loads(text) for text in (first / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert line["status"] == "ok" and line["type_correct"] is True, line
    assert line["grades"]["document"] == {"checked_fields": 7, "fully_checked": True, "perfect": True}
    assert line["details"]["reading"]["model_calls"] >= 1 and line["details"]["extraction"]["model_calls"] == 6
    # Every model attempt is counted per stage; nothing needed a correction turn.
    assert line["details"]["attempts"] == {"transcription": {"calls": 1, "follow_ups": 0, "failed": 0, "truncated": 0},
                                           "extraction": {"calls": 6, "follow_ups": 0, "failed": 0, "truncated": 0}}
    assert line["details"]["first_try_valid"] is True and line["grades"]["arithmetic"] is True
    # --keep-outputs: each answer's text, in a private file of its own.
    [kept] = [json.loads(text) for text in (first / "outputs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert kept["case_id"] == case_id and [attempt["task"] for attempt in kept["attempts"]] == ["transcription"] + ["extraction"] * 6
    assert json.loads(kept["attempts"][0]["text"]) == {"full_text": "\n".join(RECEIPT)}
    report = (first / "report.md").read_text(encoding="utf-8")
    assert "## Leaderboard" in report and "| synthetic | 1 of 1 | 100.0% | 0 of 7 | 3 of 3 | 1 of 1 |" in report
    assert "**synthetic is the only candidate that passes the gate.**" in report
    summary = json.loads((first / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert summary["documents"] == {"fully_checked": 1, "perfect": 1} and summary["status"] == {"ok": 1}
    assert summary["fields"]["receipt"]["total_minor"] == {"suppressed": True}  # One case is too few to report.
    assert "| receipt | total_minor | 0 of 1 |" in (first / "report.md").read_text(encoding="utf-8")
    shared = json.loads((first / "summary.json").read_text(encoding="utf-8"))
    assert shared["sampling"] == {"temperature": 0.1, "seed": None, "schema_enforced": True}
    # The next run misses the tip: the case fails and the report names it as newly failing. It also sets a seed.
    local_model["outputs"] = scripted(receipt_summary(tip=MISSING))
    requests_before = len(local_model["requests"])
    second = run(corpus, {**config_for(local_model), "sampling": {"temperature": 0.0, "seed": 7}}, network_guard=False, echo=lambda _: None)
    sent = [request for request in local_model["requests"][requests_before:] if "messages" in request]
    assert sent and all((request["temperature"], request["seed"]) == (0.0, 7) for request in sent)
    assert json.loads((second / "run.json").read_text(encoding="utf-8"))["sampling"] == {"temperature": 0.0, "seed": 7, "schema_enforced": True}
    assert "Sampling: temperature 0.0, seed 7, schema enforced." in (second / "report.md").read_text(encoding="utf-8")
    [line] = [json.loads(text) for text in (second / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert line["grades"]["fields"]["tip_minor"]["error"] == "missing" and line["grades"]["document"]["perfect"] is False
    summary = json.loads((second / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert summary["regressions"] == {"newly_failing": [case_id], "newly_passing": []}
    report = (second / "report.md").read_text(encoding="utf-8")
    assert f"newly failing {case_id}" in report and "tip_minor | 1 of 1" in report
    assert not (second / "outputs.jsonl").exists()  # Only kept when asked for.
    # An invented total fails the app's evidence check twice: a validator failure after one correction turn.
    invented = receipt_summary(total={"value": "26.00", "status": "proposed", "evidence": [{"line_id": "line-7", "quote": "Total 25.00"}]})
    local_model["outputs"] = [{"full_text": "\n".join(RECEIPT)}, classification(), invented, invented]
    third = run(corpus, config_for(local_model), network_guard=False, echo=lambda _: None)
    [line] = [json.loads(text) for text in (third / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert line["status"] == "extract_failed" and line["details"]["failure"] == "validator_fail" and line["details"]["first_try_valid"] is False
    assert line["details"]["attempts"]["extraction"] == {"calls": 3, "follow_ups": 1, "failed": 0, "truncated": 0}
    summary = json.loads((third / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert summary["failures"] == {"validator_fail": 1} and summary["first_try"] == {"valid": 0, "of": 1}
    assert summary["attempts"] == {"calls": 4, "follow_ups": 1, "truncated": 0} and summary["mean_score"] == 0.0
    assert "synthetic is excluded: valid answers 0.0% < 99%" in (third / "report.md").read_text(encoding="utf-8")


def test_a_dry_run_checks_everything_and_writes_nothing(tmp_path, local_model):
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    said = []
    assert run(corpus, config_for(local_model), repeat=3, network_guard=False, echo=said.append, dry_run=True) is None
    assert said[0].startswith("Dry run: 53 test cases x 1 candidates x 3 repeats = 159 documents.")
    assert local_model["requests"] == [] and not (corpus.root / "results").exists()
    said.clear()
    run(corpus, config_for(local_model), network_guard=False, echo=said.append, dry_run=True, compare_schema=True)
    assert said[0].startswith("Dry run: 53 test cases x 2 candidates") and said[2].startswith("  synthetic@no-schema:")


def test_a_model_that_cannot_load_is_one_load_failure_per_case(tmp_path, local_model, monkeypatch):
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    chosen = [case.id for case in corpus.cases()[:2]]

    def out_of_memory(config, work):
        raise ValueError("Local model server returned HTTP 500. The server reported insufficient memory.")

    monkeypatch.setattr("evals.run.ensure_loaded", out_of_memory)
    folder = run(corpus, config_for(local_model), case_ids=chosen, repeat=2, network_guard=False, echo=lambda _: None)
    lines = [json.loads(text) for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["status"] for line in lines] == ["load_fail"] * 4 and local_model["requests"] == []
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert summary["status"] == {"load_fail": 4} and summary["failures"] == {"load_fail": 4}


def test_a_run_refuses_tuned_test_cases_and_an_empty_split(tmp_path, local_model):
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    case = corpus.cases()[0]
    case.info.used_for_tuning = True
    case.save()
    with pytest.raises(ValueError, match="used to tune"):
        run(corpus, config_for(local_model), network_guard=False, echo=lambda _: None)
    with pytest.raises(ValueError, match="No admitted dev cases"):
        run(corpus, config_for(local_model), split="dev", network_guard=False, echo=lambda _: None)
    missing = config_for(local_model)
    missing["candidates"][0]["reasoning"] = "not-downloaded"
    with pytest.raises(ValueError, match="not-downloaded: The server is running but does not list"):
        run(corpus, missing, network_guard=False, echo=lambda _: None)
    assert not (corpus.root / "results").exists()


def test_the_synthetic_corpus_and_the_example_config_are_valid(tmp_path):
    created = create_synthetic(tmp_path / "synthetic")
    corpus = Corpus(tmp_path / "synthetic")
    cases = corpus.cases(split="test")
    assert len(created) == len(set(created)) == len(cases) == 53
    assert {kind: sum(case.info.document_type == kind for case in cases) for kind in ROWS} == {
        "receipt": 24, "bank_statement": 9, "credit_card_statement": 6, "paystub": 12, "bill": 2}
    assert {tag for case in cases for tag in case.info.tags} == set(TAGS)  # Every edge is tested at least once.
    assert all(case.answers().rows_complete for case in cases)
    assert {case.original.suffix for case in cases} == {".png", ".pdf"} and max(case.info.pages for case in cases) >= 6
    assert create_synthetic(tmp_path / "again") == created  # The same seed makes the same corpus.
    config = load_config(ROOT / "evals" / "models.toml")
    assert config["base_url"] == "http://127.0.0.1:1234/v1" and config["candidates"][0]["name"] == "baseline"
    assert config["sampling"] == {}  # The example measures the app's own sampling.
    custom = tmp_path / "models.toml"
    custom.write_text('[sampling]\ntemperature = 0.0\nseed = 1234\nschema_enforced = false\n[[candidate]]\nvision = "v"\nreasoning = "r"\n', encoding="utf-8")
    assert load_config(custom)["sampling"] == {"temperature": 0.0, "seed": 1234, "schema_enforced": False}
    custom.write_text('[sampling]\ntemperature = 5\n[[candidate]]\nvision = "v"\nreasoning = "r"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(custom)


EXISTING_DOCUMENTS = "fbabda291e8cc424a7658a29b1a010aa3af93050fd9b75ef53e8af1d84a94609"  # sha256 of the 44 documents of the corpus before the aligned statements.
BEFORE_PAY_STUBS = "4435fba7588668761baac7447daef1614598343b62f24bb158b905e8f69bf8aa"  # sha256 of the 48 documents before the aligned pay stubs.


def test_table_engine_aligned_statements_are_added_after_the_existing_documents_and_change_none_of_them(tmp_path):
    """FR-34 / SC-20: the existing 44 cases keep their ids and answers; four text-PDF statements in aligned columns follow them."""
    everything = documents()
    keys = ("document_type", "lines", "fields", "rows", "tags", "source", "faded")
    assert hashlib.sha256(json.dumps([{key: document[key] for key in keys} for document in everything[:44]], sort_keys=True).encode()).hexdigest() == EXISTING_DOCUMENTS
    added = everything[44:48]
    assert [document["document_type"] for document in added] == ["bank_statement"] * 3 + ["credit_card_statement"]
    assert all(document["tags"] == ["aligned"] and document["source"] == "pdf" and document["layout"] for document in added)
    # What the four print: the Wells Fargo-style two-line heading and daily balances, day-first dates, wrapped descriptions over two pages, sections.
    texts = ["\n".join(document["lines"]) for document in added]
    assert all(word in texts[0] for word in ("Deposits/", "Additions", "Withdrawals/", "Subtractions", "Ending daily", "Daily ending balance"))
    assert any(int(row["posted_date"][8:10]) > 12 for row in added[1]["rows"]) and "/" in texts[1] and re.search(r"\b1[3-9]/\d\d/\d{4}\b|\b2\d/\d\d/\d{4}\b|\b3[01]/\d\d/\d{4}\b", texts[1])
    assert len(added[2]["layout"]) == 2 and max(len(row["description"].split()) for row in added[2]["rows"]) >= 5
    assert any(title in texts[3] for title in ("Payments and Credits", "Payments", "Credits and Refunds")) and any(title in texts[3] for title in ("Purchases", "Charges and Interest"))
    created = create_synthetic(tmp_path / "synthetic")
    assert len(created) == 53 and all(len(identifier) == 16 for identifier in created)
    corpus = Corpus(tmp_path / "synthetic")
    aligned = [case for case in corpus.cases() if "aligned" in case.info.tags and case.info.document_type != "paystub"]
    assert len(aligned) == 4 and all(case.info.source_kind == "native_pdf" and case.original.read_bytes().startswith(b"%PDF") for case in aligned)
    assert all(case.answers().rows_complete and case.answers().document_type in ("bank_statement", "credit_card_statement") for case in aligned)


def test_pay_stub_aligned_files_are_added_after_the_existing_documents_and_change_none_of_them(tmp_path):
    """FR-71 / SC-68: the existing 48 cases keep their ids and answers; five text-PDF pay stub files in aligned columns follow them, from the layout
    generator's inputs, and the three-stub file carries one answer file per stub."""
    everything = documents()
    keys = ("document_type", "lines", "fields", "rows", "tags", "source", "faded")
    assert hashlib.sha256(json.dumps([{key: document[key] for key in keys} for document in everything[:48]], sort_keys=True).encode()).hexdigest() == BEFORE_PAY_STUBS
    added = everything[48:]
    assert len(everything) == 53 and [document["document_type"] for document in added] == ["paystub"] * 5
    assert all(document["tags"] == ["aligned"] and document["source"] == "pdf" and document["layout"] for document in added)
    texts = ["\n".join(document["lines"]) for document in added]
    assert all(word in texts[0] for word in ("Hours", "Rate")) and re.search(r"YTD|Year to", texts[0]) and re.search(r"YTD|Year to", texts[3])
    assert "\nThis\nYear to\n" in texts[3] and "\nPeriod\nDate\n" in texts[3]  # Headings over two lines.
    assert not any("Current" in line or "This Period" in line for line in added[1]["lines"])  # Stacked sections with no headings.
    assert any(line in ("Gross Pay", "Taxes", "Deductions", "Net Pay") for line in added[2]["lines"])  # The summary box.
    assert any(row["current_minor"] is None and row["ytd_minor"] for row in added[3]["rows"])  # A year-to-date-only row.
    assert [len(document["stubs"] or []) for document in added] == [0, 0, 0, 0, 3] and len({stub["fields"]["pay_date"] for stub in added[4]["stubs"]}) == 3
    assert added[4]["stubs"][0]["fields"] == added[4]["fields"] and added[4]["stubs"][0]["rows"] == added[4]["rows"]
    created = create_synthetic(tmp_path / "synthetic")
    corpus = Corpus(tmp_path / "synthetic")
    stubs = [case for case in corpus.cases() if "aligned" in case.info.tags and case.info.document_type == "paystub"]
    assert len(created) == 53 and len(stubs) == 5 and all(case.info.source_kind == "native_pdf" and case.answers().rows_complete for case in stubs)
    assert sorted(len(case.stubs()) for case in stubs) == [1, 1, 1, 1, 3]
    assert all(len(case.stubs()) == 1 for case in corpus.cases() if case not in stubs)  # Every other case, one-stub pay stubs included, is its own stub.
    three = next(case for case in stubs if len(case.stubs()) == 3)
    assert three.stubs()[0] == three.answers() and (three.folder / "stubs.json").is_file()
    assert [(folder / "stubs.json").exists() for folder in (case.folder for case in corpus.cases())].count(True) == 1


def test_every_synthetic_answer_is_printed_and_adds_up():
    """A perfect reader could give exactly these answers: every amount is on the page, and they add up as the app checks."""
    for document in documents():
        kind, text = document["document_type"], "\n".join(document["lines"])
        exponent = EXPONENTS[document["fields"]["currency"]]
        key, _ = ROWS[kind]
        amounts = [value for name, value in document["fields"].items() if name.endswith("_minor") and value is not None]
        amounts += [row[name] for row in document["rows"] for name in row if name.endswith("_minor") and row[name] is not None]
        missing = [value for value in amounts if money(abs(value), exponent) not in text]
        assert not missing, (document["lines"][0], missing)
        assert document["fields"]["currency"] in text
        record = {**document["fields"], key: document["rows"]}
        expected = None if "no_items" in document["tags"] else True
        assert arithmetic(kind, record) is expected, document["lines"][0]
        Answers(document_type=kind, fields={name: {"value": value, "state": "correct"} for name, value in document["fields"].items()},
                rows=document["rows"], rows_state="correct", rows_complete=True)


# The two table readers --------------------------------------------------------------------------------------------------

def test_table_engine_and_the_old_reader_are_compared_on_text_pdf_statements(tmp_path, local_model):
    """SC-20: `evals.run.run` over the synthetic corpus's text-PDF statements reports the old reader and the engine side by side."""
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    statements = [case for case in corpus.cases() if case.info.document_type in ("bank_statement", "credit_card_statement") and case.info.source_kind == "native_pdf"]
    aligned = {case.id for case in statements if "aligned" in case.info.tags}
    assert len(statements) == 7 and len(aligned) == 4  # The four aligned ones and the three statements of flowed text.
    folder = run(corpus, config_for(local_model), case_ids=[case.id for case in statements], network_guard=False, echo=lambda _: None)
    lines = [json.loads(text) for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    by_case = {line["case_id"]: line["details"]["table_readers"] for line in lines}
    assert set(by_case) == {case.id for case in statements}
    # The engine records every printed row of the four aligned statements with the right date, amount and direction, and each reconciles.
    for case in statements:
        if case.id in aligned:
            engine = by_case[case.id]["engine"]
            assert engine == {"rows": len(case.answers().rows), "recorded": len(case.answers().rows), "exact": len(case.answers().rows),
                              "reconciled": True, "dropped": 0, "unplaced": 0, "failed": False}, case.info.tags
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]["table_readers"]
    old, engine = summary["legacy"], summary["engine"]
    assert old["documents"] == engine["documents"] == 7 and old["rows"] == engine["rows"] == sum(len(case.answers().rows) for case in statements)
    assert old["reconcilable"] == engine["reconcilable"] == 7 and old["failed"] == engine["failed"] == 0
    assert old["unplaced"] is None and isinstance(engine["unplaced"], int)  # The old reader names no unplaced lines.
    # The engine is at least as good as the old reader on each metric, over the corpus and on every statement.
    assert engine["exact"] >= old["exact"] and engine["reconciled"] >= old["reconciled"]
    assert engine["exact_share"] >= old["exact_share"] and engine["reconciled_share"] >= old["reconciled_share"]
    for each in by_case.values():
        assert each["engine"]["exact"] >= each["legacy"]["exact"] and bool(each["engine"]["reconciled"]) >= bool(each["legacy"]["reconciled"])
    assert engine["exact"] >= sum(len(case.answers().rows) for case in statements if case.id in aligned) and engine["reconciled"] >= 4
    # summary.json passes the report's allowlist and holds no description, amount or date of any statement.
    text = (folder / "summary.json").read_text(encoding="utf-8")
    check_summary(json.loads(text))
    for case in statements:
        for row in case.answers().rows:
            assert row["description"] not in text and money(abs(row["amount_minor"])) not in text and row["posted_date"] not in text
    # report.md shows both readers side by side.
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "side by side (7 statements" in report
    table = [line for line in report.splitlines() if line.startswith(("| Reader |", "| Old reader |", "| Table engine |"))]
    assert len(table) == 3 and "Unplaced lines" in table[0]
    assert f"| Old reader | {old['exact']} of {old['rows']} (" in table[1] and f"| Table engine | {engine['exact']} of {engine['rows']} (" in table[2]
    assert f" | {engine['unplaced']} | {engine['dropped']} | {engine['failed']} |" in table[2] and " | n/a | " in table[1]


def test_table_engine_comparison_leaves_out_what_is_not_a_text_pdf_statement_and_counts_a_failing_reader(tmp_path, local_model, monkeypatch):
    """Receipts and statement images have no table readers to compare; a reader that raises recorded nothing, and is counted."""
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    cases = corpus.cases()
    others = [case.id for case in cases if case.info.document_type == "receipt"][:1] + [case.id for case in cases if case.info.source_kind == "scan" and case.info.document_type == "bank_statement"][:1]
    folder = run(corpus, config_for(local_model), case_ids=others, network_guard=False, echo=lambda _: None)
    assert all("table_readers" not in json.loads(text)["details"] for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines())
    assert "table_readers" not in json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert "side by side" not in (folder / "report.md").read_text(encoding="utf-8")

    def broken(*args, **kwargs):
        raise RuntimeError("injected engine fault")

    monkeypatch.setattr("evals.run.statement_tables.read", broken)
    aligned = [case.id for case in cases if "aligned" in case.info.tags and case.info.document_type != "paystub"][:3]
    folder = run(corpus, config_for(local_model), case_ids=aligned, network_guard=False, echo=lambda _: None)
    readers = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]["table_readers"]
    assert readers["engine"]["failed"] == 3 and readers["engine"]["exact"] == 0 and readers["engine"]["reconciled"] == 0 and readers["legacy"]["failed"] == 0
    assert readers["engine"]["recorded"] == 0 and readers["engine"]["rows"] == readers["legacy"]["rows"]


def test_table_engine_comparison_is_suppressed_in_the_summary_for_few_statements(tmp_path, local_model):
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    chosen = [case.id for case in corpus.cases() if "aligned" in case.info.tags and case.info.document_type != "paystub"][:2]
    folder = run(corpus, config_for(local_model), case_ids=chosen, network_guard=False, echo=lambda _: None)
    assert json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]["table_readers"] == {"suppressed": True}


# The pay engine's counts ------------------------------------------------------------------------------------------------

def stub_answers(rows, gross=None, net=None):
    fields = {name: FieldAnswer(value=None, state="unchecked") for name in CRITICAL_FIELDS["paystub"]}
    fields.update(gross_pay_minor=FieldAnswer(value=gross, state="correct" if gross is not None else "unchecked"),
                  net_pay_minor=FieldAnswer(value=net, state="correct" if net is not None else "unchecked"))
    return Answers(document_type="paystub", fields=fields, rows=[{"description": label, "line_group": group, "current_minor": current, "ytd_minor": ytd}
                                                                 for label, group, current, ytd in rows], rows_state="correct", rows_complete=True)


def test_pay_reader_counts_values_left_out_and_checks_and_never_text():
    stub = stub_answers([("Regular", "earnings", 100000, 1200000), ("Federal Tax", "tax", 20000, 240000), ("401K", "pre_tax", 5000, None)], gross=100000, net=75000)
    exact = [("regular", 100000, 1200000), ("FEDERAL  TAX", -20000, 240000), ("401k", 5000, None), ("Total Taxes", 20000, 240000)]
    assert pay_reader([stub], exact, True, unplaced=0) == {"stubs": 1, "values": 5, "exact": 5, "left_out": 0, "checkable": 1, "checks_held": 1,
                                                          "unplaced": 0, "split_right": 1, "failed": False}
    # A value the reader put in the wrong column is wrong, not left out; a row it has no cell for is left out and the stub's checks cannot hold.
    wrong = pay_reader([stub], [("Regular", 1200000, 100000), ("Federal Tax", None, None), ("401K", 5000, None)], False)
    assert (wrong["values"], wrong["exact"], wrong["left_out"], wrong["checks_held"], wrong["split_right"], wrong["unplaced"]) == (
        5, 1, 2, 0, 0, None)
    assert pay_reader([stub], [], False, failed=True) == {"stubs": 1, "values": 5, "exact": 0, "left_out": 5, "checkable": 1, "checks_held": 0,
                                                          "unplaced": None, "split_right": 0, "failed": True}
    # Two stubs print the same labels: each answer line takes the next unused row, in order.
    second = stub_answers([("Regular", "earnings", 200000, None)], gross=200000, net=200000)
    both = pay_reader([stub, second], [("Regular", 100000, 1200000), ("Federal Tax", 20000, 240000), ("401K", 5000, None), ("Regular", 200000, None)], True)
    assert (both["values"], both["exact"], both["checkable"], both["checks_held"]) == (6, 6, 2, 2)
    unchecked = stub_answers([("Regular", "earnings", 100000, None)])
    assert pay_reader([unchecked], [("Regular", 100000, None)], True)["checkable"] == 0  # Without gross and net there is nothing to add up.
    parts = [{1, 75000, 2}, {200000}]
    assert split_is_right([stub, second], parts) and not split_is_right([stub, second], parts[:1]) and not split_is_right([stub, second], [parts[1], parts[0]])
    assert split_is_right([unchecked], [{5}])  # A stub with no net pay answer only needs the right count of parts.


def test_a_pay_stub_file_is_graded_stub_by_stub_and_a_wrong_count_is_a_split_miss():
    first = stub_answers([("Regular", "earnings", 100000, None)], gross=100000, net=100000)
    second = stub_answers([("Regular", "earnings", 200000, None)], gross=200000, net=200000)

    def record(amount, guesses=()):
        return {"gross_pay_minor": amount, "net_pay_minor": amount, "lines": [{"description": "Regular", "line_group": "earnings", "current_minor": amount,
                                                                                "ytd_minor": None}], "details": {"guesses": list(guesses)}}
    good = [record(100000, [{"kind": "columns_guessed", "text": "x"}]), record(200000, [{"kind": "columns_guessed"}, {"kind": "group_guessed"}])]
    grades, each = grade_stubs([first, second], good)
    assert len(each) == 2 and grades["fields"]["gross_pay_minor"]["correct"] and grades["rows"]["matched"] == grades["rows"]["expected"] == 2
    assert guess_counts(good, each) == {"columns_guessed": {"made": 2, "right": 2}, "group_guessed": {"made": 1, "right": 1}}
    # One stub's money wrong: its guesses are wrong, the other stub's right, and the file's grades show the wrong field.
    bad = [good[0], record(250000, [{"kind": "columns_guessed"}])]
    grades, each = grade_stubs([first, second], bad)
    assert not grades["fields"]["gross_pay_minor"]["correct"] and guess_counts(bad, each) == {"columns_guessed": {"made": 2, "right": 1}}
    # Fewer records than stubs: a split miss, graded as if nothing was read, and no guess is judged.
    grades, each = grade_stubs([first, second], good[:1])
    assert each is None and not grades["fields"]["gross_pay_minor"]["correct"] and guess_counts(good[:1], each) == {}
    assert guess_counts([record(1, [{"kind": "something else"}])], grade_stubs([first], [record(1)])[1]) == {}  # Only the engine's kinds are counted.
    assert set(GUESS_KINDS) == {"headings_overruled", "columns_guessed", "group_guessed", "box_columns_guessed", "split_changed"}


def read_original(path, folder):
    """A pay stub PDF read like the app reads it, with no model: its saved reading."""
    folder.mkdir()
    worker(str(path), folder)
    complete_pdf(folder, config=None, digest=digest_file(path))
    return read_result(json.loads((folder / "result.json").read_text(encoding="utf-8")))


def scripted_pay_stubs(corpus, local_model, tmp_path, files=PAYSTUB_FILES):
    """The model double for pay stub files (the five aligned ones unless `files`, a list of (index, choices), says otherwise) in the order a run reads
    them (case id order): what test_paystub_engine_generator answers for each file from the generator's inputs, one reply per schema and stub."""
    from evals import paystub_layouts
    from test_paystub_engine_generator import Generated
    made = {}
    for index, choices in files:
        lines = aligned_paystub(index, **choices)["lines"]
        made[hashlib.sha256(("synthetic:pdf:" + "|".join(lines)).encode()).hexdigest()[:16]] = (index, choices)
    replies = {}
    for case_id in sorted(made):
        index, choices = made[case_id]
        reader = object.__new__(Generated)
        reader.evidence = read_original(corpus.case(case_id).original, tmp_path / ("read-" + case_id))
        reader.lines = evidence_lines(reader.evidence)
        reader.local_model = {"requests": []}
        reader.answer(paystub_layouts.make(PAYSTUB_SEED, index, **choices))
        for schema, found in reader.local_model["by_schema"].items():
            replies.setdefault(schema, []).extend(found)
    local_model["by_schema"] = replies
    return sorted(made)


def test_pay_stub_readers_are_compared_and_the_engine_reads_every_aligned_file_exactly(tmp_path, local_model):
    """SC-68: `evals.run.run` over the five aligned pay stub files (the model double answers from the generator's inputs) shows the pay engine alone
    (FR-96: no legacy reader); the engine records every pay value exactly, splits the three-stub file into three, sends nothing to review and guesses
    nothing wrong; summary.json holds counts only."""
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    chosen = scripted_pay_stubs(corpus, local_model, tmp_path)
    folder = run(corpus, config_for(local_model), case_ids=chosen, network_guard=False, echo=lambda _: None)
    lines = [json.loads(text) for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert sorted(line["case_id"] for line in lines) == chosen
    for line in lines:
        stubs = len(corpus.case(line["case_id"]).stubs())
        assert line["status"] == ("split" if stubs == 3 else "ok") and line["details"]["split_miss"] is False, line["details"]
        assert line["grades"]["document"]["perfect"] is True and case_pass(line), line["case_id"]
        engine = line["details"]["pay_readers"]["engine"]
        assert (engine["stubs"], engine["exact"], engine["left_out"], engine["checks_held"], engine["checkable"], engine["split_right"], engine["unplaced"],
                engine["to_review"], engine["failed"]) == (stubs, engine["values"], 0, stubs, stubs, 1, 0, 0, False), line["case_id"]
        assert set(line["details"]["pay_readers"]) == {"engine"}
    assert sum(line["details"]["pay_readers"]["engine"]["split_right"] for line in lines) == 5
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert set(summary["pay_readers"]) == {"engine"}
    engine = summary["pay_readers"]["engine"]
    assert engine["documents"] == 5 and engine["stubs"] == 7 and engine["values"] > 0
    assert engine["exact"] == engine["values"] and engine["left_out"] == 0 and engine["checks_held"] == engine["checkable"] == 7
    assert engine["exact_share"] == engine["checks_share"] == 1.0 and engine["to_review"] == 0 and engine["split_right"] == 5 and engine["unplaced"] == 0
    # Every guess is counted by kind and, on this corpus, right.
    assert set(summary["guesses"]) == set(GUESS_KINDS)
    assert all(each["made"] == each["right"] for each in summary["guesses"].values())
    assert summary["guesses"]["split_changed"] == {"made": 0, "right": 0}
    # summary.json passes the allowlist and holds no description, amount, date or employer of any stub; report.md shows the engine's counts and no legacy column.
    text = (folder / "summary.json").read_text(encoding="utf-8")
    check_summary(json.loads(text))
    for case_id in chosen:
        for stub in corpus.case(case_id).stubs():
            assert stub.fields["payer_or_employer"].value not in text and stub.fields["pay_date"].value not in text
            assert all(row["description"] not in text for row in stub.rows)
            assert not [value for value in (stub.fields["net_pay_minor"].value, stub.fields["gross_pay_minor"].value) if money(value) in text]
    report = (folder / "report.md").read_text(encoding="utf-8")
    assert "read by the pay engine (5 files, 7 stubs" in report and "Today's reader" not in report and "stand-in" not in report
    table = [line for line in report.splitlines() if line.startswith(("| Reader | Pay values", "| Pay engine |"))]
    assert len(table) == 2 and "Stubs sent to review" in table[0]
    assert f"| Pay engine | {engine['exact']} of {engine['values']} (" in table[1] and "| 0 of 7 | 5 of 5 | 0 | 0 |" in table[1]
    assert "Guesses the engine made:" in report


def test_guesses_are_counted_by_kind_and_are_right_when_the_values_they_chose_equal_the_answers(tmp_path, local_model):
    """FR-74: a summary box with no column headings makes the engine guess which column is taxes; the guess is counted, and right only when the stub's
    money values come out as the answers say."""
    boxed = [(index, {**dict(PAYSTUB_FILES[0][1]), "box": True, "box_heads": "none", "box_shuffled": False, "heading": "known1", "stubs": 1})
             for index in (5, 6, 7, 8)]
    corpus = Corpus.create(tmp_path / "boxed")
    rng = random.Random(1)
    written = [write_case(corpus, aligned_paystub(index, **choices), rng) for index, choices in boxed]
    assert len(set(written)) == 4
    wrong = corpus.case(sorted(written)[0])  # Its answers claim another net pay: whatever the engine chose is wrong.
    answers = wrong.answers()
    answers.fields["net_pay_minor"].value += 1
    (wrong.folder / "answers.json").write_text(answers.model_dump_json(indent=2) + "\n", encoding="utf-8")
    scripted_pay_stubs(corpus, local_model, tmp_path, boxed)
    folder = run(corpus, config_for(local_model), case_ids=sorted(written), network_guard=False, echo=lambda _: None)
    lines = [json.loads(text) for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines()]
    assert all(line["details"]["guesses"] == {"box_columns_guessed": {"made": 1, "right": 1 - (line["case_id"] == wrong.id)}} for line in lines)
    guesses = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]["guesses"]
    assert guesses["box_columns_guessed"] == {"made": 4, "right": 3} and guesses["columns_guessed"] == {"made": 0, "right": 0}
    assert "box_columns_guessed 3 right of 4" in (folder / "report.md").read_text(encoding="utf-8")


def test_pay_stub_comparison_leaves_out_other_documents_counts_a_failing_reader_and_suppresses_few_files(tmp_path, local_model, monkeypatch):
    """A receipt has no pay readers; a reader that raises placed nothing and is counted; fewer than three files are suppressed in the summary."""
    corpus = Corpus(tmp_path / "synthetic")
    create_synthetic(corpus.root)
    cases = corpus.cases()
    others = [case.id for case in cases if case.info.document_type == "receipt"][:1] + [case.id for case in cases if case.info.document_type == "paystub"
                                                                                           and case.info.source_kind == "scan"][:1]
    folder = run(corpus, config_for(local_model), case_ids=others, network_guard=False, echo=lambda _: None)
    assert all("pay_readers" not in json.loads(text)["details"] for text in (folder / "results.jsonl").read_text(encoding="utf-8").splitlines())
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert "pay_readers" not in summary and "read by the pay engine" not in (folder / "report.md").read_text(encoding="utf-8")
    aligned = [case.id for case in cases if "aligned" in case.info.tags and case.info.document_type == "paystub"]
    folder = run(corpus, config_for(local_model), case_ids=aligned[:2], network_guard=False, echo=lambda _: None)
    summary = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]
    assert summary["pay_readers"] == {"suppressed": True} and summary["guesses"] == {"suppressed": True}

    def broken(*args, **kwargs):
        raise RuntimeError("injected engine fault")

    monkeypatch.setattr("evals.run.paystub_tables.read", broken)
    folder = run(corpus, config_for(local_model), case_ids=aligned[:3], network_guard=False, echo=lambda _: None)
    readers = json.loads((folder / "summary.json").read_text(encoding="utf-8"))["candidates"]["synthetic"]["pay_readers"]
    assert readers["engine"]["failed"] == 3 and readers["engine"]["exact"] == 0 and readers["engine"]["checks_held"] == 0 and "legacy" not in readers
    assert readers["engine"]["values"] > 0


# The shareable summary -----------------------------------------------------------------------------------------------

def test_the_summary_never_holds_private_values(tmp_path):
    corpus = Corpus(tmp_path / "corpus")
    create_synthetic(corpus.root)
    secrets = ["SECRETMERCHANT", "OTHERSECRET", "P:/Finances/secret.pdf", "123-45-6789", "4111111111111111", "987654321"]
    folder = corpus.root / "results" / "20261003T000000Z-abcdef"
    folder.mkdir(parents=True)
    run_manifest = {"format": "home-manager-eval-run/1", "run_id": folder.name, "started_at": "2026-10-03T00:00:00Z", "finished_at": "2026-10-03T00:01:00Z",
                    "split": "test", "repeat": 1, "cases": 4, "git": "abc1234", "extraction_version": "typed-extraction-v16",
                    "vision_version": "receipt-vision-v5-text", "base_url": "http://127.0.0.1:1234/v1",
                    "candidates": [{"name": "m", "vision": "v", "reasoning": "r", "identity": {"vision": {"quantization": "Q4_K_M"}, "reasoning": {}}}]}
    (folder / "run.json").write_text(json.dumps(run_manifest), encoding="utf-8")
    lines = []
    for case in corpus.cases():
        answers = case.answers()
        if answers.document_type == "receipt":
            answers.fields["merchant"].value = "SECRETMERCHANT"
        record = {name: answer.value for name, answer in answers.fields.items()}
        record.update(merchant="OTHERSECRET", total_minor=987654321)
        lines.append({"run_id": folder.name, "candidate": "m", "run_index": 0, "case_id": case.id, "donor": case.info.donor, "split": "test",
                      "document_type": case.info.document_type, "source_kind": "scan", "pages": 1, "tags": case.info.tags, "status": "ok",
                      "type_correct": True, "grades": grade(answers, record),
                      "details": {"wall_seconds": 3.0, "error": "P:/Finances/secret.pdf 123-45-6789 4111111111111111", "first_try_valid": True}})
    # A document that could not be read counts as a processing failure, not as wrong fields.
    lines.append({**lines[0], "status": "read_failed", "type_correct": None, "grades": None, "run_index": 1,
                  "details": {"failure": "schema_fail", "error": "SECRETMERCHANT 4111111111111111", "first_try_valid": False}})
    (folder / "results.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    rebuild(corpus, folder)
    text = (folder / "summary.json").read_text(encoding="utf-8")
    assert not [secret for secret in secrets if secret in text]
    count = len(corpus.cases())
    stats = json.loads(text)["candidates"]["m"]
    assert stats["status"] == {"ok": count, "read_failed": 1} and stats["documents"]["fully_checked"] == count
    assert stats["failures"] == {"schema_fail": 1} and stats["first_try"] == {"valid": count, "of": count + 1}
    assert stats["strata"]["tag"]["non_usd"]["cases"] == 5 and stats["strata"]["tag"]["injection"] == {"suppressed": True}
    # No row lists were extracted, so no case passes; one case was run twice and scored 0 the second time.
    consistency = stats["consistency"]
    assert {key: consistency[key] for key in ("cases", "pass_all", "pass_any", "repeats")} == {"cases": count, "pass_all": 0, "pass_any": 0, "repeats": 2}
    assert consistency["score_spread"] > 0
    good = json.loads(text)
    for bad in ({**good, "note": "x"}, {**good, "git": "C:/Users/someone"}, {**good, "candidates": {"P:/Finances": {}}},
                {**good, "candidates": {"m": {**good["candidates"]["m"], "runs": "SECRETMERCHANT"}}}):
        with pytest.raises(ValueError):
            check_summary(bad)
