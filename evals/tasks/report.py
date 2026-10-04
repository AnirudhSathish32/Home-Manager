"""report.md for a per-task run: a leaderboard, the decision, one table per task, failures, judge scores and the
cases that changed since the previous run of the same tasks."""

from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

from ..decision import decide
from ..decision import markdown as decision_markdown
from ..decision import rules as decision_rules
from ..report import percentile, schema_comparison, schema_pairs


def read_lines(folder):
    path = Path(folder) / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def aggregate(lines):
    """Per (candidate, task): the counts the report and the decision use."""
    out = {}
    groups = defaultdict(list)
    for line in lines:
        groups[(line["candidate"], line["task"])].append(line)
    for key, rows in groups.items():
        by_case, scores = defaultdict(list), defaultdict(list)
        for row in rows:
            by_case[row["case_id"]].append(row["grades"]["passed"])
            scores[row["case_id"]].append(row["grades"]["score"])
        repeats = max(len(values) for values in by_case.values())
        spreads = [statistics.pstdev(values) for values in scores.values() if len(values) > 1]
        first = [row["first_try_valid"] for row in rows if row["first_try_valid"] is not None]
        out[key] = {"runs": len(rows), "cases": len(by_case), "repeats": repeats,
                    "passed": sum(1 for values in by_case.values() if values[0]),
                    "pass_all": sum(all(values) for values in by_case.values()), "pass_any": sum(any(values) for values in by_case.values()),
                    "score": round(statistics.fmean(row["grades"]["score"] for row in rows), 4),
                    "spread": round(statistics.fmean(spreads), 4) if spreads else None,
                    "valid": sum(row["status"] == "ok" for row in rows), "first_try": (sum(first), len(first)),
                    "failures": Counter(row["failure"] for row in rows if row["failure"]),
                    "money_errors": sum(row["grades"]["checks"].get("money_errors", 0) or 0 for row in rows),
                    "latency": [row["latency_s"] for row in rows if row["status"] != "load_fail"],
                    "failed_cases": sorted({row["case_id"] for row in rows if row["run_index"] == 0 and not row["grades"]["passed"]})}
    return out


def judge_scores(folder):
    """{judge_model: {"calibrated": {rubric: bool}, "self_judged": bool, "scores": {(candidate, task): [score]}}} from judge/*.jsonl."""
    found = {}
    for path in sorted((Path(folder) / "judge").glob("*.jsonl")):
        entries = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not entries:
            continue
        judge = entries[0]["judge"]
        scores = defaultdict(list)
        for entry in entries:
            if entry.get("score") is not None:
                scores[(entry["candidate"], entry["task"])].append(entry["score"])
        found[judge] = {"calibrated": entries[0].get("calibrated", {}), "self_judged": any(entry.get("self_judged") for entry in entries),
                        "failures": sum(entry.get("score") is None for entry in entries), "scores": dict(scores)}
    return found


def decision_rows(manifest, stats, judges):
    rows = []
    for candidate in manifest["candidates"]:
        name = candidate["name"]
        mine = {task: value for (who, task), value in stats.items() if who == name}
        if not mine or candidate.get("schema_enforced") is False:  # Schema variants (A15) are measured, never ranked.
            continue
        calibrated = []
        for judge in judges.values():
            if judge["self_judged"]:
                continue
            for (who, task), values in judge["scores"].items():
                rubric = manifest["tasks"].get(task, {}).get("rubric")
                if who == name and judge["calibrated"].get(rubric):
                    calibrated += values
        rows.append({"name": name, "runs": sum(value["runs"] for value in mine.values()), "valid": sum(value["valid"] for value in mine.values()),
                     "money_errors": sum(value["money_errors"] for value in mine.values()),
                     "pass_all": {task: (value["pass_all"] if value["repeats"] > 1 else value["passed"]) / value["cases"] for task, value in mine.items()},
                     "scores": {task: value["score"] for task, value in mine.items()},
                     "p95": percentile([seconds for value in mine.values() for seconds in value["latency"]], .95),
                     "judge": statistics.fmean(calibrated) if calibrated else None})
    return rows


def previous_run(folder, manifest):
    """The latest finished earlier run in the same output folder with the same task versions, for the regression diff."""
    versions = {name: task["version"] for name, task in manifest["tasks"].items()}
    for path in sorted(Path(folder).parent.glob("*"), reverse=True):
        if path.name >= Path(folder).name or not (path / "run.json").is_file():
            continue
        other = json.loads((path / "run.json").read_text(encoding="utf-8"))
        if other.get("finished_at") and {name: task["version"] for name, task in other.get("tasks", {}).items() if name in versions} == versions:
            return path
    return None


def regression_diff(lines, previous_lines):
    def outcome(rows):
        return {(row["candidate"], row["task"], row["case_id"]): row["grades"]["passed"] for row in rows if row["run_index"] == 0}
    now, before = outcome(lines), outcome(previous_lines)
    diff = defaultdict(lambda: {"newly_failing": [], "newly_passing": []})
    for key in sorted(now.keys() & before.keys()):
        if before[key] and not now[key]:
            diff[key[:2]]["newly_failing"].append(key[2])
        elif now[key] and not before[key]:
            diff[key[:2]]["newly_passing"].append(key[2])
    return dict(diff)


def rebuild(folder):
    folder = Path(folder)
    manifest = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    lines = read_lines(folder)
    stats, judges = aggregate(lines), judge_scores(folder)
    previous = previous_run(folder, manifest)
    regressions = regression_diff(lines, read_lines(previous)) if previous else {}
    settings = decision_rules(manifest.get("decision"))
    decision = decide(decision_rows(manifest, stats, judges), settings)
    (folder / "report.md").write_text(markdown(manifest, stats, judges, decision, settings, regressions, previous.name if previous else None, lines),
                                      encoding="utf-8")
    return decision


def task_extras(task, manifest, lines):
    """The task module's own report lines (report_lines), from its result lines grouped by candidate."""
    from . import TASKS  # The task modules import the app; report.md for an old run still builds without them.
    extra = getattr(TASKS.get(task), "report_lines", None)
    if extra is None:
        return []
    grouped = {candidate["name"]: [line for line in lines if line["task"] == task and line["candidate"] == candidate["name"]]
               for candidate in manifest["candidates"]}
    return extra({name: rows for name, rows in grouped.items() if rows})


def markdown(manifest, stats, judges, decision, settings, regressions, previous, lines=()):
    sampling = manifest["sampling"]
    tasks = list(manifest["tasks"])
    out = [f"# Task eval run {manifest['run_id']}", "",
           f"Tasks: {', '.join(f'{name} ({task['cases']} cases, {task['version']})' for name, task in manifest['tasks'].items())}; "
           f"repeated {manifest['repeat']}x. Code {manifest['git']}. Sampling: temperature {sampling['temperature']}, "
           f"seed {sampling['seed'] if sampling['seed'] is not None else 'none'}, schema {'enforced' if sampling['schema_enforced'] else 'in the prompt only'}. "
           "Synthetic cases only.", "", "## Leaderboard", "",
           "| Candidate | Weighted accuracy | Valid answers | " + " | ".join(tasks) + " |", "|---|---|---|" + "---|" * len(tasks)]
    for candidate in manifest["candidates"]:
        name = candidate["name"]
        if name not in decision["accuracy"]:
            continue
        mine = {task: stats.get((name, task)) for task in tasks}
        runs = sum(value["runs"] for value in mine.values() if value)
        valid = sum(value["valid"] for value in mine.values() if value)
        cells = [f"{value['score']:.0%} ({value['passed']}/{value['cases']})" if value else "—" for value in mine.values()]
        out.append(f"| {name} | {decision['accuracy'][name]:.1%} | {valid} of {runs} | " + " | ".join(cells) + " |")
    out += ["", "Each task cell is the mean score with the cases passed on the first repeat.", ""]
    out += decision_markdown(decision, settings)
    summaries = {}
    for (name, _), value in stats.items():
        summary = summaries.setdefault(name, {"runs": 0, "valid": 0, "failures": Counter(), "first_try": (0, 0), "scores": []})
        summary["runs"] += value["runs"]
        summary["valid"] += value["valid"]
        summary["failures"] += value["failures"]
        summary["first_try"] = (summary["first_try"][0] + value["first_try"][0], summary["first_try"][1] + value["first_try"][1])
        summary["scores"].append(value["score"])
    for summary in summaries.values():
        summary["score"] = statistics.fmean(summary.pop("scores"))
    out += schema_comparison(schema_pairs(manifest, summaries))
    for task in tasks:
        info = manifest["tasks"][task]
        out += [f"## {task}", "", f"{info['cases']} cases, dataset {info['version']}, {info['role']} model.", "",
                "| Candidate | Passed | Mean score | Every / any repeat | Score spread | First answers valid | Failed | Time p50 / p95 |",
                "|---|---|---|---|---|---|---|---|"]
        for candidate in manifest["candidates"]:
            value = stats.get((candidate["name"], task))
            if not value:
                continue
            consistency = f"{value['pass_all']} / {value['pass_any']} (of {value['repeats']})" if value["repeats"] > 1 else "—"
            failures = ", ".join(f"{count} {kind}" for kind, count in value["failures"].most_common()) or "—"
            out.append(f"| {candidate['name']} | {value['passed']} of {value['cases']} | {value['score']:.1%} | {consistency} | "
                       f"{'—' if value['spread'] is None else value['spread']} | {value['first_try'][0]} of {value['first_try'][1]} | {failures} | "
                       f"{percentile(value['latency'], .5)} s / {percentile(value['latency'], .95)} s |")
        for candidate in manifest["candidates"]:
            value = stats.get((candidate["name"], task))
            if value and value["failed_cases"]:
                out.append(f"\n{candidate['name']} did not pass: {', '.join(value['failed_cases'])}.")
            diff = regressions.get((candidate["name"], task))
            if previous and diff and (diff["newly_failing"] or diff["newly_passing"]):
                out.append(f"\n{candidate['name']} compared with {previous}: newly failing {', '.join(diff['newly_failing']) or 'none'}; "
                           f"newly passing {', '.join(diff['newly_passing']) or 'none'}.")
        out += task_extras(task, manifest, lines)
        out.append("")
    if judges:
        out += ["## Judge scores", "", "Scores from 1 to 4. An uncalibrated judge's scores are shown but never count toward the decision.", "",
                "| Judge | Candidate | Task | Mean | Scored | Calibrated |", "|---|---|---|---|---|---|"]
        for judge, value in judges.items():
            for (candidate, task), scores in sorted(value["scores"].items()):
                rubric = manifest["tasks"].get(task, {}).get("rubric")
                status = "self-judged" if value["self_judged"] else "yes" if value["calibrated"].get(rubric) else "uncalibrated"
                out.append(f"| {judge} | {candidate} | {task} | {statistics.fmean(scores):.2f} | {len(scores)} | {status} |")
            if value["failures"]:
                out.append(f"\n{judge} failed to give a valid verdict {value['failures']} times; those are judge failures, not scores.")
        out.append("")
    elif any(task.get("rubric") for task in manifest["tasks"].values()):
        out += ["Rubric checks (description quality, reasoning, review findings, answer helpfulness) are not judged in this run. "
                "Judge them with `python -m evals.judge --run <this folder> --judge MODEL`.", ""]
    return "\n".join(out)
