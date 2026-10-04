"""Run the per-task evals: every chosen task's synthetic cases through the app's own task function, for every candidate.

  python -m evals.tasks --config evals\\models.toml [--tasks describe,payees] [--repeat 3] [--out .runtime\\eval-tasks]
                        [--limit N] [--dry-run] [--compare-schema] [--judge MODEL [--allow-self-judge]]

Inference only on this computer (evals/guard.py). The cases are made up, so results keep each model answer's parsed
output for the opt-in judge (evals/judge.py). Results go to <out>/<run_id>/: run.json, results.jsonl and report.md.
"""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sys
import time

from home_manager.core.jobs import Work
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.reviewer import ReviewerConfig
from home_manager.models.decisions import DecisionConfig
from home_manager.models.model_client import check_connection, recording
from home_manager.models.vision import VisionConfig

from ..corpus import write_json
from ..decision import rules as decision_rules
from ..graders import failure_kind
from ..guard import GuardError, check_server, install_network_guard
from ..run import attempt_counts, candidate_sampling, effective_sampling, git_revision, identity, load_config, load_models, schema_variants, utc
from . import TASKS

RUN_FORMAT = "home-manager-eval-tasks/1"
DEFAULT_OUT = Path(".runtime") / "eval-tasks"
ANSWER_FAILURES = ("parse_fail", "schema_fail", "validator_fail", "truncated")


def task_config(module, candidate, base_url, sampling):
    if module.ROLE == "decision":  # Reads probabilities, so sampling overrides don't apply.
        return DecisionConfig(provider=candidate["decision_provider"], base_url=candidate["decision_url"], model=candidate["decision"])
    model, sampling = candidate[module.ROLE], candidate_sampling(candidate, sampling)
    if module.ROLE == "vision":
        return VisionConfig(base_url=base_url, model=model, **sampling)
    if getattr(module, "REVIEWER", False):
        return ReviewerConfig(base_url=base_url, model=model, provider="chat", **sampling)
    return ReasoningConfig(base_url=base_url, model=model, **sampling)


def run_one(module, case, config):
    """One case once. Returns the result-line fields: status, failure, output, grades, attempts, first_try_valid, latency."""
    attempts, work = [], Work.detached()
    status, failure, error, output = "ok", None, None, None
    started = time.monotonic()
    with recording(attempts.append), work.attribute(module.NAME, case["id"], module.VERSION):
        try:
            output = module.run(case, config, work)
        except GuardError:
            raise
        except (ValueError, OSError) as exc:
            status, error = "failed", str(exc)
            failure = failure_kind(error, attempts)
        except Exception as exc:  # A broken case is reported, never stops the run.
            status, error, failure = "error", type(exc).__name__, "other"
    latency = round(time.monotonic() - started, 2)
    grades = module.grade(case, output) if status == "ok" else {"passed": False, "score": 0.0, "checks": {}}
    if getattr(module, "MULTI_STEP", False):
        first_try = None  # An agent loop's later steps carry earlier answers by design.
    elif status == "ok":
        first_try = not any(attempt["follow_up"] for attempt in attempts)
    else:
        first_try = False if failure in ANSWER_FAILURES else None
    return {"status": status, "failure": failure, "error": (error or "")[:300] or None, "output": output, "grades": grades,
            "attempts": attempt_counts(attempts), "first_try_valid": first_try, "latency_s": latency}


def run_tasks(config, tasks=None, repeat=1, out=DEFAULT_OUT, network_guard=True, probe=True, echo=print, dry_run=False,
              judge=None, allow_self_judge=False, case_limit=None, compare_schema=False):
    """Run the chosen tasks (all by default) for every candidate. Returns the run folder, or None for a dry run."""
    if compare_schema:
        config = {**config, "candidates": schema_variants(config["candidates"])}
    if network_guard:
        install_network_guard()
    if not 1 <= repeat <= 10:
        raise ValueError("Repeat each case 1 to 10 times.")
    candidates = config["candidates"]
    # By default, every task each candidate has models for: the decisions task only when every candidate names a decision model.
    names = list(tasks or [name for name in TASKS if all(candidate.get(TASKS[name].ROLE) for candidate in candidates)])
    unknown = [name for name in names if name not in TASKS]
    if unknown:
        raise ValueError("Unknown tasks: " + ", ".join(unknown) + ". Choose from: " + ", ".join(TASKS) + ".")
    if not names:
        raise ValueError("No task fits every candidate's models. Name the tasks with --tasks.")
    roles = {TASKS[name].ROLE for name in names}
    missing = [f"{candidate['name']} ({role})" for candidate in candidates for role in sorted(roles) if not candidate.get(role)]
    if missing:
        raise ValueError("These candidates have no model for a chosen task's role: " + ", ".join(missing) + ".")
    # Models on the [server] LM Studio; a decision model elsewhere (another port, a /v1/systemone server) is checked on its own.
    models = [candidate[role] for candidate in candidates for role in sorted(roles)
              if role != "decision" or (candidate["decision_provider"] == "lmstudio" and candidate["decision_url"] == config["base_url"])]
    for candidate in candidates:
        if "decision" in roles and candidate["decision_url"] != config["base_url"]:
            check_server(candidate["decision_url"], [candidate["decision"]], probe=probe)
    if judge:
        models.append(judge)
        own = {candidate[role] for candidate in config["candidates"] for role in ("vision", "reasoning")}
        if judge in own and not allow_self_judge:
            raise ValueError(f"The judge {judge} is also a candidate's model, and a model favours its own answers. "
                             "Choose another judge, or pass --allow-self-judge to mark its scores as self-judged.")
    base_url = check_server(config["base_url"], models, probe=probe)
    for model in dict.fromkeys(models):
        state = check_connection(VisionConfig(base_url=base_url, model=model))
        if not state["model_listed"]:
            raise ValueError(f"{model}: {state['problem']}")
    datasets = {name: TASKS[name].cases()[:case_limit] for name in names}
    sampling = config.get("sampling") or {}
    total = sum(len(cases) for cases in datasets.values()) * len(config["candidates"]) * repeat
    if dry_run:
        echo(f"Dry run: {', '.join(f'{name} ({len(cases)})' for name, cases in datasets.items())} x {len(config['candidates'])} candidates "
             f"x {repeat} repeats = {total} cases. Server {base_url}; every model is listed.")
        return None
    # Microseconds, so runs started in the same second still sort in order for the regression diff.
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + secrets.token_hex(3)
    folder = Path(out).resolve() / run_id
    folder.mkdir(parents=True)
    manifest = {"format": RUN_FORMAT, "run_id": run_id, "started_at": utc(), "finished_at": None, "repeat": repeat, "git": git_revision(),
                "base_url": base_url, "sampling": effective_sampling(sampling), "decision": config.get("decision") or decision_rules(None),
                "tasks": {name: {"version": TASKS[name].VERSION, "role": TASKS[name].ROLE, "cases": len(datasets[name]),
                                 "prompt_version": getattr(TASKS[name], "PROMPT_VERSION", None), "rubric": getattr(TASKS[name], "RUBRIC", None)}
                          for name in names},
                "candidates": [{**candidate, "identity": {role: identity(candidate["decision_url"] if role == "decision" else base_url, candidate[role])
                                                          for role in sorted(roles)}}
                               for candidate in config["candidates"]]}
    write_json(folder / "run.json", manifest)
    done = 0
    with open(folder / "results.jsonl", "a", encoding="utf-8") as results:
        for candidate in config["candidates"]:
            load_error = load_models(candidate, base_url)
            for name in names:
                module = TASKS[name]
                task_settings = task_config(module, candidate, base_url, sampling)
                for index in range(repeat):
                    for case in datasets[name]:
                        done += 1
                        if load_error:
                            fields = {"status": "load_fail", "failure": "load_fail", "error": load_error, "output": None,
                                      "grades": {"passed": False, "score": 0.0, "checks": {}}, "attempts": attempt_counts([]),
                                      "first_try_valid": None, "latency_s": 0.0}
                        else:
                            fields = run_one(module, case, task_settings)
                        line = {"run_id": run_id, "candidate": candidate["name"], "model": candidate[module.ROLE], "task": name,
                                "case_id": case["id"], "run_index": index, "tags": case["tags"], **fields}
                        results.write(json.dumps(line, default=str) + "\n")
                        results.flush()
                        echo(f"[{done}/{total}] {candidate['name']} {name} {case['id']} {fields['status']}"
                             f"{'' if fields['status'] != 'ok' else ' pass' if fields['grades']['passed'] else ' fail'}")
    manifest["finished_at"] = utc()
    write_json(folder / "run.json", manifest)
    if judge:
        from ..judge import judge_run
        judge_run(folder, judge, base_url, sampling, allow_self_judge=allow_self_judge, echo=echo)
    from .report import rebuild
    rebuild(folder)
    return folder


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m evals.tasks", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", default=str(Path(__file__).resolve().parents[1] / "models.toml"))
    parser.add_argument("--tasks", help="Comma-separated task names (default: all): " + ", ".join(TASKS))
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--judge", help="A model ID to score the rubric tasks after the run (opt-in).")
    parser.add_argument("--allow-self-judge", action="store_true")
    parser.add_argument("--limit", type=int, help="Only the first N cases of each task, for a quick check. Too few to choose a model.")
    parser.add_argument("--compare-schema", action="store_true", help="Also run each candidate with the JSON schema only in the prompt.")
    args = parser.parse_args(argv)
    try:
        folder = run_tasks(load_config(args.config), args.tasks.split(",") if args.tasks else None, args.repeat, args.out,
                           dry_run=args.dry_run, judge=args.judge, allow_self_judge=args.allow_self_judge, case_limit=args.limit,
                           compare_schema=args.compare_schema)
    except (ValueError, OSError, GuardError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if folder is not None:
        print(f"Done. Report: {folder / 'report.md'}")
    return 0
