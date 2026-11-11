"""Run candidate models over the corpus through the app's real pipeline, then grade and report.

  python -m evals.run --corpus P:\\EvalCorpus --config evals\\models.toml [--split test] [--repeat 1] [--case ID ...]
                      [--dry-run] [--keep-outputs] [--compare-schema]

Each case is read and extracted from its original exactly as the app does it (capture, reading, extraction), in a
throwaway library that is deleted afterwards, so no case sees another's accounts or merchants. Inference only on this
computer (evals/guard.py). Results stay in <corpus>/results/<run_id>/: results.jsonl, run.json, report.md, and
summary.json, the only file meant to be shared. --keep-outputs also writes outputs.jsonl, every model answer as
text (private: it holds the documents' contents). --dry-run checks the server, models and cases, then stops.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib

from home_manager.app.manager import Manager
from home_manager.core.jobs import Work
from home_manager.core.money import MoneyError, to_minor
from home_manager.documents import bill_split
from home_manager.documents.extraction import EXTRACTION_VERSION, cell_amount, line_amounts, paystub_columns
from home_manager.documents.layout_context import evidence_lines
from home_manager.documents.paystub_split import stub_parts
from home_manager.documents.pdf_reader import PDFResult, read_result
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance import bill_tables, paystub_tables, statement_rows, statement_tables
from home_manager.finance.ledger import HouseholdConfig
from home_manager.library.scanner import ScanLimits
from home_manager.models.model_client import DEFAULT_TEMPERATURE, check_connection, model_identity, recording
from home_manager.models.residency import ensure_loaded
from home_manager.models.vision import VISION_VERSION, Sampling, VisionConfig

from .corpus import Corpus, write_json
from .decision import rules as decision_rules
from .graders import bill_reader, failure_kind, grade, grade_stubs, guess_counts, pay_reader, split_is_right, table_reader
from .guard import GuardError, check_server, install_network_guard

RUN_FORMAT = "home-manager-eval-run/1"
LABEL = re.compile(r"[A-Za-z0-9._:/@+-]{1,80}")
CASE_TIMEOUT = 1800


def utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config(path):
    """{base_url, timeout_seconds, sampling, candidates: [{name, vision, reasoning}]} from a models.toml.

    A candidate may also name a decision model (models/decisions.py) for the decisions task: decision (its model ID),
    decision_provider ("lmstudio", the default, or "systemone") and decision_url (default: the [server] base_url).
    A candidate with only a decision model runs the decisions task only."""
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    # Only the overrides set in [sampling]; the rest stay the app's own. A bad value raises ValueError.
    sampling = Sampling.model_validate(data.get("sampling", {})).model_dump()
    base_url = data.get("server", {}).get("base_url", "http://127.0.0.1:1234/v1")
    candidates = []
    for item in data.get("candidate", []):
        decision = item.get("decision", "")
        candidate = {"name": item.get("name") or item.get("reasoning") or decision,
                     "vision": item.get("vision", ""), "reasoning": item.get("reasoning", "")}
        for key, value in candidate.items():
            if decision and key != "name" and value == "":
                continue  # A decision-only candidate.
            if not isinstance(value, str) or not LABEL.fullmatch(value):
                raise ValueError(f"Candidate {key} must be a model ID or label of letters, digits and ._:/@+- (got {value!r}).")
        if decision:
            if not isinstance(decision, str) or not LABEL.fullmatch(decision):
                raise ValueError(f"Candidate decision must be a model ID of letters, digits and ._:/@+- (got {decision!r}).")
            provider = item.get("decision_provider", "lmstudio")
            if provider not in ("lmstudio", "systemone"):
                raise ValueError(f"Candidate decision_provider must be lmstudio or systemone (got {provider!r}).")
            candidate.update(decision=decision, decision_provider=provider, decision_url=item.get("decision_url", base_url))
        candidates.append(candidate)
    if not candidates:
        raise ValueError("The config lists no [[candidate]] with a vision and a reasoning model.")
    if len({candidate["name"] for candidate in candidates}) != len(candidates):
        raise ValueError("Candidate names must be different.")
    return {"base_url": base_url, "timeout_seconds": int(data.get("run", {}).get("case_timeout_seconds", CASE_TIMEOUT)), "sampling": sampling,
            "decision": decision_rules(data.get("decision")), "candidates": candidates}


NO_SCHEMA = "@no-schema"


def schema_variants(candidates):
    """docs/evals.md: each candidate twice, as configured and with the JSON schema only in the prompt (the server
    enforces nothing), to measure how well each model keeps to the format unaided."""
    return [variant for candidate in candidates
            for variant in (candidate, {**candidate, "name": candidate["name"] + NO_SCHEMA, "schema_enforced": False})]


def candidate_sampling(candidate, sampling):
    """The run's sampling with a schema variant's override."""
    return {**(sampling or {}), **({"schema_enforced": False} if candidate.get("schema_enforced") is False else {})}


def effective_sampling(sampling):
    """What every request of the run sends, for run.json and the summary."""
    return {"temperature": sampling.get("temperature", DEFAULT_TEMPERATURE), "seed": sampling.get("seed"),
            "schema_enforced": sampling.get("schema_enforced", True)}


def refuse(*_args, **_kwargs):
    raise GuardError("Evals never fetch from the web.")


def identity(base_url, model):
    """The model's server-reported identity, with the metadata worth reporting; unknown when the server does not say."""
    fingerprint, metadata = model_identity(VisionConfig(base_url=base_url, model=model))
    details = metadata.get("details") or {}
    return {"model": model, "fingerprint": fingerprint or "unknown", "quantization": str(details.get("quantization") or "unknown"),
            "architecture": str(details.get("arch") or "unknown"), "context_length": details.get("max_context_length") or "unknown"}


def telemetry(runs):
    usable = [run for run in runs if run.get("status") == "succeeded"]
    return {"model_calls": len(runs), "model_ms": round(sum(run.get("total_ms") or 0 for run in runs)),
            "prompt_tokens": sum(run.get("prompt_tokens") or 0 for run in usable), "completion_tokens": sum(run.get("completion_tokens") or 0 for run in usable)}


def attempt_counts(attempts):
    return {"calls": len(attempts), "follow_ups": sum(attempt["follow_up"] for attempt in attempts),
            "failed": sum(attempt["status"] == "failed" for attempt in attempts),
            "truncated": sum(attempt["finish_reason"] == "length" for attempt in attempts)}


def run_case(case, candidate, base_url, timeout=CASE_TIMEOUT, sampling=None):
    """One case through capture, reading and extraction in a throwaway library, with every model attempt recorded.

    Returns (status, record, details, outputs). details counts each stage's attempts and correction turns, names the
    failure kind of a stage that failed, and says whether the model's first answers were all valid. outputs holds every
    answer's text, for --keep-outputs only.
    """
    attempts = []
    with recording(attempts.append):
        status, record, details = pipeline(case, candidate, base_url, timeout, sampling or {}, attempts)
    stages = {stage: [attempt for attempt in attempts if attempt["task"] == stage] for stage in ("transcription", "extraction")}
    details["attempts"] = {stage: attempt_counts(items) for stage, items in stages.items() if items}
    if status in ("ok", "split"):
        details["first_try_valid"] = not any(attempt["follow_up"] for attempt in attempts)
    elif details.get("failure") in ("parse_fail", "schema_fail", "validator_fail", "truncated"):
        details["first_try_valid"] = False
    else:
        details["first_try_valid"] = None  # The model never gave a usable answer to judge (server, load or timeout).
    outputs = [{"task": attempt["task"], "follow_up": attempt["follow_up"], "finish_reason": attempt["finish_reason"], "text": attempt["text"]}
               for attempt in attempts]
    return status, record, details, outputs


def table_readers(case, answers, evidence):
    """docs/evals.md "The two table readers": for a native-PDF bank or card statement whose row list the donor confirmed complete, the old
    reader (`statement_rows.rebuild`, which reads through `pdf_import.analyze_legacy`) and the table engine (`statement_tables.read`) each
    read the saved reading, given the statement's own currency and period, as Record gives them from the model's summary. Neither uses a
    model, so these counts measure the readers and nothing else. None when the case is not such a statement."""
    kind = case.info.document_type
    if (kind not in ("bank_statement", "credit_card_statement") or case.info.source_kind != "native_pdf" or not isinstance(evidence, PDFResult)
            or not answers.rows_complete or answers.rows is None):
        return None
    given = {name: answers.fields[name].value if answers.fields[name].state != "unchecked" else None for name in ("currency", "period_start", "period_end")}
    currency = given["currency"] or case.info.home_currency or "USD"
    statement_type = "credit_card" if kind == "credit_card_statement" else "bank"
    out = {}
    for reader in ("legacy", "engine"):
        unplaced = None
        try:
            if reader == "legacy":
                rebuild = statement_rows.rebuild(evidence, statement_type=statement_type, period_start=given["period_start"],
                                                 period_end=given["period_end"], currency=currency)
            else:
                period = (given["period_start"], given["period_end"]) if given["period_start"] and given["period_end"] else None
                reading = statement_tables.read(evidence, statement_type=statement_type, currency=currency, fallback_period=period)
                rebuild, unplaced = reading.as_rebuild(), len(reading.unplaced)
            if not rebuild.available:
                return None
            out[reader] = table_reader(answers, rebuild, unplaced)
        except Exception:  # A reader that raises recorded nothing; that is a result, not a stop.
            out[reader] = table_reader(answers, None, failed=True)
    return out


def minor(text, currency):
    """A printed amount as minor units, signed as printed; None when it is not an amount."""
    try:
        return to_minor(str(text), currency)
    except (MoneyError, ArithmeticError, ValueError):
        return None


def cell_minor(row, column, currency):
    """The amount in a row's cell at `column`, in minor units; None when there is no such cell or no single amount in it."""
    if column is None or column >= len(row.cells):
        return None
    printed = cell_amount(row.cells[column])
    return minor(printed, currency) if printed else None


def pay_rows(tables, currency):
    """What a reader placed of a pay stub file: (label, this period, year to date) in minor units for each row of its tables, in the order printed. A
    table whose this-period and year-to-date columns can't be told (paystub_columns is None) places no value; a total is no pay line."""
    found = []
    for table in tables:
        columns = paystub_columns(table) or (None, None)
        for row in table.rows:
            if getattr(row, "total", False) or not row.cells:
                continue
            found.append((row.cells[0].quote, *(cell_minor(row, column, currency) for column in columns)))
    return found


def pay_readers(case, stubs, evidence):
    """docs/evals.md "The two table readers": for a native-PDF pay stub whose pay lines the donor confirmed complete, the pay engine
    (`paystub_tables.read`, whose columns are decided from the printed numbers) reads the saved reading, with no model. Its file split
    (`paystub_split.stub_parts`) is the rule Record uses. None when the case is not such a pay stub."""
    if (case.info.document_type != "paystub" or case.info.source_kind != "native_pdf" or not isinstance(evidence, PDFResult)
            or any(not answers.rows_complete or answers.rows is None for answers in stubs)):
        return None
    first = stubs[0].fields["currency"]
    currency = (first.value if first.state != "unchecked" else None) or case.info.home_currency or "USD"
    lines = [line for line in evidence_lines(evidence) if line.text.strip()]
    def printed(first, last):
        return {minor(amount, currency) for line in lines[first:last] for amount in line_amounts(line.text)}
    try:
        pay = paystub_tables.read(evidence)
        rows, unplaced = pay_rows(pay.adapted, currency), len(pay.unplaced)
        try:
            right = split_is_right(stubs, [printed(first, last) for first, last in stub_parts(lines)])
        except Exception:  # A split that raises is a split missed, not a stop.
            right = False
        return {"engine": pay_reader(stubs, rows, right, unplaced)}
    except Exception:  # An engine that raises placed nothing; that is a result, not a stop.
        return {"engine": pay_reader(stubs, [], False, failed=True)}


def bill_rows(tables, currency):
    """What the bill engine placed: the charge amount of each row of its charge tables, in minor units as printed, in the order printed. A table whose charge
    column can't be told places no value; a total is no charge line."""
    found = []
    for table in tables:
        column = next((number for number, role in table.roles.items() if role == "charge"), None)
        for row in table.rows:
            if getattr(row, "total", False) or not row.cells:
                continue
            value = cell_minor(row, column, currency)
            if value is not None:
                found.append(value)
    return found


def bill_readers(case, bills, evidence):
    """docs/evals.md "The two table readers": for a native-PDF bill with a text page whose charge lines the donor confirmed complete, the bill engine
    (`bill_tables.read`, whose columns are decided from the printed numbers) reads the saved reading, with no model. Its file split
    (`bill_split.bill_parts` with the engine's anchors) is the rule Record uses. None when the case is not such a bill; image bills are not counted."""
    if (case.info.document_type != "bill" or case.info.source_kind != "native_pdf" or not isinstance(evidence, PDFResult)
            or not any(page.method == "embedded_text" and page.layout is not None for page in evidence.pages)
            or any(not answers.rows_complete or answers.rows is None for answers in bills)):
        return None
    first = bills[0].fields["currency"]
    currency = (first.value if first.state != "unchecked" else None) or case.info.home_currency or "USD"
    lines = [line for line in evidence_lines(evidence) if line.text.strip()]
    def printed(first, last):
        return {minor(amount, currency) for line in lines[first:last] for amount in line_amounts(line.text)}
    try:
        engine = bill_tables.read(evidence)
        rows, unplaced = bill_rows(engine.adapted, currency), len(engine.reading.unplaced)
        try:
            found = bill_split.bill_parts(lines, bill_tables.split_anchors(engine))
            parts, reasons = [printed(first, last) for first, last in found.parts], len(found.reasons)
        except Exception:  # A split that raises is a split missed (the app reads the file as one bill with a review reason), not a stop.
            parts, reasons = [], 1
        return {"engine": bill_reader(bills, rows, parts, reasons, unplaced)}
    except Exception:  # An engine that raises placed nothing; that is a result, not a stop.
        return {"engine": bill_reader(bills, [], [], 0, failed=True)}


def review_count(publication):
    """How many pay stubs or bills of an extraction run were sent to review: published and not counted automatically (a stub rejected as a duplicate or
    VOID is not). None when the run published nothing."""
    if not isinstance(publication, dict):
        return None
    statuses = [segment.get("review_status") for segment in publication["segments"]] if publication.get("segments") else [publication.get("review_status")]
    return sum(status not in ("verified", "rejected") for status in statuses)


def grade_case(case, answers, record, details):
    """The case's grades. A pay stub or bill file's records (a list, one per stub or bill) are graded one at a time against `Case.stubs` and merged; a
    different count than the file has is a split miss. Its guesses are counted by kind in `details`."""
    if not isinstance(record, list):
        return grade(answers, record)
    grades, each = grade_stubs(case.stubs(), record)
    details["split_miss"] = each is None
    guesses = guess_counts(record, each)
    if guesses:
        details["guesses"] = guesses
    return grades


def pipeline(case, candidate, base_url, timeout, sampling, attempts):
    """Capture, reading and extraction for one case. Returns (status, record, details)."""
    def failed(status, stage, run, details):
        error = run.get("error") or ""
        kind = failure_kind(error, [attempt for attempt in attempts if attempt["task"] == stage])
        return status, None, {**details, "failure": kind, "error": error[:300]}

    with tempfile.TemporaryDirectory(prefix="hm-eval-") as temporary:
        root = Path(temporary)
        manager = Manager(root / "control", ScanLimits(stability_seconds=0))
        try:
            manager.rate_fetch = manager.price_fetch = refuse
            manager.configure(str(root / "library"))
            manager.configure_vision(VisionConfig(base_url=base_url, model=candidate["vision"], **sampling))
            manager.configure_reasoning(ReasoningConfig(base_url=base_url, model=candidate["reasoning"], **sampling))
            manager.configure_household(HouseholdConfig(home_currency=case.info.home_currency, auto_identify_items=False,
                                                        fetch_exchange_rates=False, fetch_crypto_prices=False))
            shutil.copyfile(case.original, manager.store.library.inbox / ("document" + case.original.suffix))
            started = time.monotonic()
            manager.start_inbox()
            try:
                manager.future.result(timeout=timeout)
            except TimeoutError:
                manager.cancel()  # Stops the model request; close() then waits for the queues to finish.
                return "timeout", None, {"wall_seconds": round(time.monotonic() - started, 1)}
            wall = round(time.monotonic() - started, 1)
            documents = manager.store.documents()["items"]
            if not documents:
                return "not_captured", None, {"wall_seconds": wall}
            document = documents[0]
            readings = manager.receipts.history(document["id"])
            if not readings:
                return "not_read", None, {"wall_seconds": wall}
            reading = manager.receipts.get(readings[0]["id"])
            details = {"wall_seconds": wall, "reading": telemetry(reading["model_runs"])}
            if reading["status"] not in ("succeeded", "partial"):
                return failed("read_failed", "transcription", reading, details)
            evidence = read_result(reading["result"]) if reading["result"] else None
            readers = table_readers(case, case.answers(), evidence)
            if readers:
                details["table_readers"] = readers
            pay = pay_readers(case, case.stubs(), evidence) if case.info.document_type == "paystub" else None
            if pay:
                details["pay_readers"] = pay
            billed = bill_readers(case, case.stubs(), evidence) if case.info.document_type == "bill" else None
            if billed:
                details["bill_readers"] = billed
            with manager.store.connection() as db:
                row = db.execute("SELECT id FROM extraction_runs WHERE document_id=? ORDER BY created_at DESC LIMIT 1", (document["id"],)).fetchone()
            if row is None:
                return "not_extracted", None, details
            extraction = manager.extractions.get(row["id"])
            details["extraction"] = telemetry(extraction["model_runs"])
            if extraction["status"] != "succeeded":
                return failed("extract_failed", "extraction", extraction, details)
            result = extraction["result"] or {}
            details["predicted_type"] = (result.get("classification") or {}).get("document_type")
            listed = case.info.document_type in ("paystub", "bill")
            for readers in (pay, billed):
                if readers:
                    readers["engine"]["to_review"] = review_count(extraction.get("publication"))
            if result.get("segments"):  # A pay stub or bill file is graded one at a time (grade_case); any other split document by its first part.
                records = [(segment or {}).get("normalized") for segment in result["segments"]]
                return "split", records if listed else records[0], details
            if not result.get("normalized"):
                return "no_record", None, details
            return "ok", [result["normalized"]] if listed else result["normalized"], details
        finally:
            manager.close()


def git_revision():
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10,
                              cwd=Path(__file__).resolve().parent).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def load_models(candidate, base_url):
    """Load the candidate's two models in turn before its cases. A model that cannot load (out of memory, a broken
    file) is one clear load_fail per case instead of every case failing in its own words. None when both loaded."""
    try:
        for model in (candidate["vision"], candidate["reasoning"]):
            ensure_loaded(VisionConfig(base_url=base_url, model=model), Work.detached())
    except (ValueError, OSError) as exc:
        return f"{type(exc).__name__}: {str(exc)[:300]}"
    return None


def run(corpus, config, split="test", repeat=1, case_ids=None, network_guard=True, probe=True, echo=print, dry_run=False, keep_outputs=False,
        compare_schema=False):
    """Run every candidate over the chosen cases. Returns the run folder, or None for a dry run."""
    if compare_schema:
        config = {**config, "candidates": schema_variants(config["candidates"])}
    if network_guard:
        install_network_guard()
    if not 1 <= repeat <= 10:
        raise ValueError("Repeat each case 1 to 10 times.")
    partial = [candidate["name"] for candidate in config["candidates"] if not (candidate["vision"] and candidate["reasoning"])]
    if partial:
        raise ValueError("These candidates have only a decision model, which `python -m evals.tasks --tasks decisions` measures: "
                         + ", ".join(partial) + ".")
    models = [model for candidate in config["candidates"] for model in (candidate["vision"], candidate["reasoning"])]
    base_url = check_server(config["base_url"], models, probe=probe)
    for model in dict.fromkeys(models):  # Fail before the first case, not with every case unread.
        state = check_connection(VisionConfig(base_url=base_url, model=model))
        if not state["model_listed"]:
            raise ValueError(f"{model}: {state['problem']}")
    cases = corpus.cases(("admitted",), split)
    if case_ids:
        wanted = set(case_ids)
        cases = [case for case in cases if case.id in wanted]
        if len(cases) != len(wanted):
            raise ValueError("Some cases are not admitted cases of this split.")
    if not cases:
        raise ValueError(f"No admitted {split} cases to run.")
    tuned = [case.id for case in cases if case.info.split == "test" and case.info.used_for_tuning]
    if tuned:
        raise ValueError("Test cases were used to tune prompts, so they no longer measure anything: " + ", ".join(tuned)
                         + ". Move them to dev with `python -m evals.intake tuned`.")
    if dry_run:
        sampling = effective_sampling(config.get("sampling", {}))
        echo(f"Dry run: {len(cases)} {split} cases x {len(config['candidates'])} candidates x {repeat} repeats = "
             f"{len(cases) * len(config['candidates']) * repeat} documents. Server {base_url}; every model is listed. "
             f"Sampling: temperature {sampling['temperature']}, seed {sampling['seed']}, schema enforced {sampling['schema_enforced']}.")
        for candidate in config["candidates"]:
            echo(f"  {candidate['name']}: vision {candidate['vision']}, reasoning {candidate['reasoning']}")
        return None
    # Microseconds, so runs started in the same second still sort in order for the regression diff.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(3)
    folder = corpus.root / "results" / run_id
    folder.mkdir(parents=True)
    manifest = {"format": RUN_FORMAT, "run_id": run_id, "started_at": utc(), "finished_at": None, "split": split, "repeat": repeat,
                "cases": len(cases), "git": git_revision(), "extraction_version": EXTRACTION_VERSION, "vision_version": VISION_VERSION,
                "base_url": base_url, "sampling": effective_sampling(config.get("sampling", {})),
                "decision": config.get("decision") or decision_rules(None), "candidates": []}
    for candidate in config["candidates"]:
        manifest["candidates"].append({**candidate, "identity": {"vision": identity(base_url, candidate["vision"]),
                                                                   "reasoning": identity(base_url, candidate["reasoning"])}})
    write_json(folder / "run.json", manifest)
    total = len(cases) * len(config["candidates"]) * repeat
    done = 0
    outputs_file = open(folder / "outputs.jsonl", "a", encoding="utf-8") if keep_outputs else None
    try:
        with open(folder / "results.jsonl", "a", encoding="utf-8") as results:
            for candidate in config["candidates"]:
                load_error = load_models(candidate, base_url)
                for index in range(repeat):
                    for case in cases:
                        done += 1
                        outputs = []
                        if load_error:
                            status, record, details = "load_fail", None, {"failure": "load_fail", "error": load_error}
                        else:
                            try:
                                status, record, details, outputs = run_case(case, candidate, base_url, config.get("timeout_seconds", CASE_TIMEOUT),
                                                                            candidate_sampling(candidate, config.get("sampling")))
                            except GuardError:
                                raise
                            except Exception as exc:  # One broken case never stops the run; its category is reported.
                                status, record, details = "error", None, {"error": type(exc).__name__}
                        answers = case.answers()
                        grades = grade_case(case, answers, record, details) if status in ("ok", "split") else None
                        line = {"run_id": run_id, "candidate": candidate["name"], "run_index": index, "case_id": case.id, "donor": case.info.donor,
                                "split": case.info.split, "document_type": case.info.document_type, "source_kind": case.info.source_kind,
                                "pages": case.info.pages, "tags": list(case.info.tags), "status": status,
                                "type_correct": details.get("predicted_type") == case.info.document_type if "predicted_type" in details else None,
                                # A document that was not read or extracted is a processing failure, counted by status, never as wrong fields.
                                "grades": grades, "details": details}
                        results.write(json.dumps(line) + "\n")
                        results.flush()
                        if outputs_file and outputs:
                            outputs_file.write(json.dumps({"run_id": run_id, "candidate": candidate["name"], "run_index": index, "case_id": case.id,
                                                           "attempts": outputs}, ensure_ascii=False) + "\n")
                            outputs_file.flush()
                        echo(f"[{done}/{total}] {candidate['name']} {case.id} {status}")
    finally:
        if outputs_file:
            outputs_file.close()
    manifest["finished_at"] = utc()
    write_json(folder / "run.json", manifest)
    from .report import rebuild
    rebuild(corpus, folder)
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evals.run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--config", default=str(Path(__file__).with_name("models.toml")))
    parser.add_argument("--split", choices=("test", "dev", "all"), default="test")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--dry-run", action="store_true", help="Check the server, models and cases, print what would run, and stop.")
    parser.add_argument("--keep-outputs", action="store_true", help="Also write outputs.jsonl: every model answer as text. Private.")
    parser.add_argument("--compare-schema", action="store_true", help="Also run each candidate with the JSON schema only in the prompt.")
    args = parser.parse_args(argv)
    try:
        folder = run(Corpus(args.corpus), load_config(args.config), args.split, args.repeat, args.cases, dry_run=args.dry_run,
                     keep_outputs=args.keep_outputs, compare_schema=args.compare_schema)
    except (ValueError, OSError, GuardError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if folder is None:
        return 0
    print(f"Done. Report: {folder / 'report.md'}\nShareable summary (counts only): {folder / 'summary.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
