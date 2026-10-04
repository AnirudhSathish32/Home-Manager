"""Reports for one run: report.md (private, for the collector) and summary.json (counts only, safe to share).

Every rate is shown with its denominator ("2 wrong of 18 checked") and a 95% Wilson interval, because a small sample
cannot show that an error is rare. Fields the donor fixed (the donor's model got them wrong) are reported apart from
fields the donor marked correct. summary.json is built from an allowlist and checked against it before it is written:
no values, names, text, paths or errors; cells with fewer than MIN_CELL cases are suppressed.
"""

from collections import Counter, defaultdict
import json
import math
import re
import statistics

from home_manager.core.answers import CRITICAL, DOCUMENT_TYPES

from .corpus import CASE_ID, TAGS, write_json
from .decision import decide
from .decision import markdown as decision_markdown
from .decision import rules as decision_rules
from .graders import FAILURE_KINDS, FIELD_ERRORS, score

SUMMARY_FORMAT = "home-manager-eval-summary/1"
MIN_CELL = 3
STATUSES = ("ok", "split", "no_record", "extract_failed", "not_extracted", "read_failed", "not_read", "not_captured", "timeout",
            "load_fail", "error")
SOURCE_KINDS = ("phone_photo", "scan", "native_pdf", "image_pdf")
PAGE_BUCKETS = ("1", "2-3", "4+")
ROW_COUNTS = ("scored", "expected", "predicted", "matched", "missing", "extra", "duplicate", "description_errors")
LABEL = re.compile(r"[A-Za-z0-9._:/@+-]{1,80}")
PATHLIKE = re.compile(r"^(?:[A-Za-z]:|/|\\)|\\|\.\.")


def page_bucket(pages):
    return "1" if pages <= 1 else "2-3" if pages <= 3 else "4+"


def wilson(successes, total, z=1.96):
    """95% interval for a proportion; (None, None) for an empty sample."""
    if not total:
        return None, None
    p = successes / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    spread = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return round(max(0.0, centre - spread), 3), round(min(1.0, centre + spread), 3)


def percentile(values, share):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))]


def case_pass(line):
    grades = line["grades"]
    if grades is None:
        return False
    fields_ok = all(field["correct"] for field in grades["fields"].values() if field["checked"])
    rows = grades["rows"]
    rows_ok = not rows["scored"] or (rows["matched"] == rows["expected"] == rows["predicted"] and rows["description_errors"] == 0)
    return line["status"] in ("ok", "split") and fields_ok and rows_ok


def aggregate(lines):
    """Everything the reports show, for one candidate's lines."""
    out = {"runs": len(lines), "cases": len({line["case_id"] for line in lines}), "status": Counter(line["status"] for line in lines),
           "type": Counter("correct" if line["type_correct"] else "wrong" if line["type_correct"] is False else "unknown" for line in lines),
           "fields": defaultdict(lambda: defaultdict(lambda: {"checked": 0, "wrong": 0, "errors": Counter(), "by_state": defaultdict(lambda: [0, 0])})),
           "rows": Counter(), "documents": Counter(), "strata": defaultdict(lambda: defaultdict(lambda: {"checked": 0, "wrong": 0, "cases": 0, "passed": 0})),
           "wall": [], "model_ms": [], "tokens": Counter(), "failures": Counter(), "first_try": Counter(), "arithmetic": Counter(),
           "attempts": Counter()}
    for line in lines:
        kind, grades = line["document_type"], line["grades"] or {"fields": {}, "rows": {"scored": False}, "document": {"fully_checked": False, "perfect": None}}
        line_checked = line_wrong = 0
        for name, field in grades["fields"].items():
            if not field["checked"]:
                continue
            cell = out["fields"][kind][name]
            cell["checked"] += 1
            cell["by_state"][field["state"]][0] += 1
            line_checked += 1
            if not field["correct"]:
                cell["wrong"] += 1
                cell["errors"][field["error"]] += 1
                cell["by_state"][field["state"]][1] += 1
                line_wrong += 1
        rows = grades["rows"]
        if rows["scored"]:
            out["rows"]["scored"] += 1
            for key in ROW_COUNTS[1:]:
                out["rows"][key] += rows[key]
        document = grades["document"]
        out["documents"]["fully_checked"] += document["fully_checked"]
        out["documents"]["perfect"] += bool(document["perfect"])
        passed = case_pass(line)
        strata = [("document_type", kind), ("source_kind", line["source_kind"]), ("pages", page_bucket(line["pages"]))]
        strata += [("tag", tag) for tag in line.get("tags") or []]
        for dimension, value in strata:
            stratum = out["strata"][dimension][value]
            stratum["checked"] += line_checked
            stratum["wrong"] += line_wrong
            stratum["cases"] += 1
            stratum["passed"] += passed
        details = line.get("details", {})
        if details.get("failure"):
            out["failures"][details["failure"]] += 1
        if details.get("first_try_valid") is not None:
            out["first_try"]["of"] += 1
            out["first_try"]["valid"] += details["first_try_valid"]
        if grades.get("arithmetic") is not None:
            out["arithmetic"]["of"] += 1
            out["arithmetic"]["consistent"] += grades["arithmetic"]
        for stage in (details.get("attempts") or {}).values():
            for key in ("calls", "follow_ups", "truncated"):
                out["attempts"][key] += stage.get(key, 0)
        if "wall_seconds" in details:
            out["wall"].append(details["wall_seconds"])
        model_ms = sum((details.get(stage) or {}).get("model_ms", 0) for stage in ("reading", "extraction"))
        if model_ms:
            out["model_ms"].append(model_ms)
        for stage in ("reading", "extraction"):
            for key in ("prompt_tokens", "completion_tokens", "model_calls"):
                out["tokens"][key] += (details.get(stage) or {}).get(key, 0)
    by_case, scores = defaultdict(list), defaultdict(list)
    for line in lines:
        by_case[line["case_id"]].append(case_pass(line))
        value = score(line["grades"])
        if value is not None:
            scores[line["case_id"]].append(value)
    # pass_all is pass^N (passed in every repeat), pass_any is pass@N (in at least one); score_spread is the mean, over
    # cases, of the standard deviation of a case's score across repeats: 0 means the model gives the same answers each time.
    spreads = [statistics.pstdev(values) for values in scores.values() if len(values) > 1]
    out["consistency"] = {"cases": len(by_case), "pass_all": sum(all(runs) for runs in by_case.values()),
                          "pass_any": sum(any(runs) for runs in by_case.values()), "repeats": max((len(runs) for runs in by_case.values()), default=0),
                          "score_spread": round(statistics.fmean(spreads), 4) if spreads else None}
    out["mean_score"] = round(statistics.fmean(value for values in scores.values() for value in values), 4) if scores else None
    out["passed_cases"] = {case for case, runs in by_case.items() if runs and runs[0]}
    out["failed_cases"] = {case for case, runs in by_case.items() if runs and not runs[0]}
    return out


def previous_run(corpus, folder, manifest):
    """The latest finished run before this one over the same split, for the regression diff."""
    earlier = []
    for path in corpus.results():
        if path.name >= folder.name or not (path / "results.jsonl").exists():
            continue
        other = json.loads((path / "run.json").read_text(encoding="utf-8"))
        if other.get("finished_at") and other.get("split") == manifest["split"]:
            earlier.append(path)
    return earlier[-1] if earlier else None


def read_lines(folder):
    path = folder / "results.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def ratio(wrong, total, suppress=True):
    if suppress and total < MIN_CELL:
        return {"suppressed": True}
    low, high = wilson(total - wrong, total)
    return {"wrong": wrong, "of": total, "accuracy_low": low, "accuracy_high": high}


def summary(manifest, results, regressions):
    """The shareable summary: built only from allowlisted keys, enums and counts."""
    candidates = {}
    for candidate in manifest["candidates"]:
        name = candidate["name"]
        stats = results.get(name)
        if stats is None:
            continue
        fields = {}
        for kind in DOCUMENT_TYPES:
            for field in CRITICAL[kind]:
                cell = stats["fields"].get(kind, {}).get(field)
                if not cell or not cell["checked"]:
                    continue
                entry = ratio(cell["wrong"], cell["checked"])
                if not entry.get("suppressed"):
                    entry["errors"] = {error: cell["errors"][error] for error in FIELD_ERRORS if cell["errors"][error]}
                    entry["donor_marked"] = {state: ratio(counts[1], counts[0]) for state, counts in sorted(cell["by_state"].items())}
                fields.setdefault(kind, {})[field] = entry
        strata = {}
        for dimension, allowed in (("document_type", DOCUMENT_TYPES), ("source_kind", SOURCE_KINDS), ("pages", PAGE_BUCKETS), ("tag", TAGS)):
            for value in allowed:
                stratum = stats["strata"].get(dimension, {}).get(value)
                if stratum and stratum["cases"]:
                    strata.setdefault(dimension, {})[value] = ({"suppressed": True} if stratum["cases"] < MIN_CELL else
                                                               {"cases": stratum["cases"], "passed": stratum["passed"], "fields": ratio(stratum["wrong"], stratum["checked"])})
        identity = candidate.get("identity", {})
        candidates[name] = {
            "vision": candidate["vision"], "reasoning": candidate["reasoning"],
            "quantization": {role: identity.get(role, {}).get("quantization", "unknown") for role in ("vision", "reasoning")},
            "runs": stats["runs"], "cases": stats["cases"],
            "status": {status: stats["status"][status] for status in STATUSES if stats["status"][status]},
            "type": dict(stats["type"]), "fields": fields,
            "rows": {key: stats["rows"][key] for key in ROW_COUNTS},
            "documents": {"fully_checked": stats["documents"]["fully_checked"], "perfect": stats["documents"]["perfect"]},
            "strata": strata, "consistency": stats["consistency"], "mean_score": stats["mean_score"],
            "failures": {kind: stats["failures"][kind] for kind in FAILURE_KINDS if stats["failures"][kind]},
            "first_try": {"valid": stats["first_try"]["valid"], "of": stats["first_try"]["of"]},
            "arithmetic": {"consistent": stats["arithmetic"]["consistent"], "of": stats["arithmetic"]["of"]},
            "attempts": {key: stats["attempts"][key] for key in ("calls", "follow_ups", "truncated")},
            "timing": {"wall_seconds_p50": percentile(stats["wall"], .5), "wall_seconds_p95": percentile(stats["wall"], .95),
                       "model_seconds_p50": round(percentile(stats["model_ms"], .5) / 1000, 1) if stats["model_ms"] else None,
                       "model_seconds_p95": round(percentile(stats["model_ms"], .95) / 1000, 1) if stats["model_ms"] else None,
                       **{key: stats["tokens"][key] for key in ("model_calls", "prompt_tokens", "completion_tokens")}},
            "regressions": regressions.get(name, {"newly_failing": [], "newly_passing": []}),
        }
    data = {"format": SUMMARY_FORMAT, "run_id": manifest["run_id"], "split": manifest["split"], "repeat": manifest["repeat"],
            "git": manifest["git"], "extraction_version": manifest["extraction_version"], "vision_version": manifest["vision_version"],
            "started_at": manifest["started_at"], "finished_at": manifest["finished_at"], "candidates": candidates}
    if "sampling" in manifest:
        data["sampling"] = {key: manifest["sampling"][key] for key in ("temperature", "seed", "schema_enforced")}
    check_summary(data)
    return data


# The only strings summary.json may hold, by key. Everything else is a number, a boolean, null or an enum key.
LABEL_KEYS = {"run_id", "git", "extraction_version", "vision_version", "started_at", "finished_at", "vision", "reasoning"}
ENUM_VALUES = {"format": {SUMMARY_FORMAT}, "split": {"dev", "test", "all"}}
CASE_LISTS = {"newly_failing", "newly_passing"}


def allowed_keys():
    keys = {"format", "run_id", "split", "repeat", "git", "extraction_version", "vision_version", "started_at", "finished_at", "candidates",
            "vision", "reasoning", "quantization", "runs", "cases", "status", "type", "fields", "rows", "documents", "strata", "consistency",
            "timing", "regressions", "suppressed", "wrong", "of", "accuracy_low", "accuracy_high", "errors", "donor_marked", "passed",
            "fully_checked", "perfect", "pass_all", "pass_any", "repeats", "correct", "unknown", "fixed", "document_type", "source_kind", "pages",
            "wall_seconds_p50", "wall_seconds_p95", "model_seconds_p50", "model_seconds_p95", "model_calls", "prompt_tokens", "completion_tokens",
            "sampling", "temperature", "seed", "schema_enforced", "mean_score", "score_spread", "failures", "first_try", "valid", "arithmetic",
            "consistent", "attempts", "calls", "follow_ups", "truncated", "tag"}
    keys |= set(STATUSES) | set(SOURCE_KINDS) | set(PAGE_BUCKETS) | set(ROW_COUNTS) | set(DOCUMENT_TYPES) | set(FIELD_ERRORS) | CASE_LISTS
    keys |= set(FAILURE_KINDS) | set(TAGS)
    keys |= {field for fields in CRITICAL.values() for field in fields}
    return keys


def check_summary(data):
    """Refuse a summary holding anything outside the allowlist: the last line of defence for the shareable file."""
    keys = allowed_keys()

    def safe_label(value):
        return isinstance(value, str) and LABEL.fullmatch(value) is not None and not PATHLIKE.search(value)

    def walk(value, key=None, path="summary"):
        if isinstance(value, dict):
            for name, item in value.items():
                if key == "candidates":
                    if not safe_label(name):
                        raise ValueError(f"{path}: a candidate name is not a plain label.")
                elif name not in keys:
                    raise ValueError(f"{path}: key {name!r} is not allowed in a summary.")
                walk(item, name if key != "candidates" else "candidate", f"{path}.{name}")
        elif isinstance(value, list):
            if key not in CASE_LISTS:
                raise ValueError(f"{path}: lists are not allowed here.")
            for item in value:
                if not (isinstance(item, str) and CASE_ID.fullmatch(item)):
                    raise ValueError(f"{path}: only case IDs may be listed.")
        elif isinstance(value, str):
            if key in ENUM_VALUES:
                if value not in ENUM_VALUES[key]:
                    raise ValueError(f"{path}: unexpected value.")
            elif key in LABEL_KEYS or path.split(".")[-2:-1] == ["quantization"]:
                if not safe_label(value):
                    raise ValueError(f"{path}: not a plain label.")
            else:
                raise ValueError(f"{path}: text is not allowed here.")
        elif not (value is None or isinstance(value, (bool, int, float))):
            raise ValueError(f"{path}: unexpected value type.")

    walk(data)
    return data


def regression_diff(lines, previous_lines):
    """Per candidate: case IDs that failed now but passed in the previous run, and the reverse (first repeat only)."""
    def outcome(rows):
        return {(line["candidate"], line["case_id"]): case_pass(line) for line in rows if line["run_index"] == 0}
    now, before = outcome(lines), outcome(previous_lines)
    diff = defaultdict(lambda: {"newly_failing": [], "newly_passing": []})
    for key in sorted(now.keys() & before.keys()):
        if before[key] and not now[key]:
            diff[key[0]]["newly_failing"].append(key[1])
        elif now[key] and not before[key]:
            diff[key[0]]["newly_passing"].append(key[1])
    return dict(diff)


def rebuild(corpus, folder):
    """(Re)write report.md and summary.json from run.json and results.jsonl."""
    manifest = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    lines = read_lines(folder)
    previous = previous_run(corpus, folder, manifest)
    regressions = regression_diff(lines, read_lines(previous)) if previous else {}
    results = {candidate["name"]: aggregate([line for line in lines if line["candidate"] == candidate["name"]])
               for candidate in manifest["candidates"] if any(line["candidate"] == candidate["name"] for line in lines)}
    write_json(folder / "summary.json", summary(manifest, results, regressions))
    (folder / "report.md").write_text(markdown(manifest, results, regressions, previous.name if previous else None), encoding="utf-8")


def schema_comparison(pairs):
    """eval_plan.md A15: each candidate with the schema enforced by the server and with it only in the prompt.
    pairs: [(name, enforced, prompt_only)], each {runs, valid, failures: Counter, first_try: (valid, of), score}."""
    if not pairs:
        return []
    out = ["## Schema enforcement", "", "Each candidate ran twice: with the JSON schema enforced by the server (as the app runs), and with the "
           "schema only in the prompt. Only the enforced runs count in the decision.", "",
           "| Candidate | Schema | Valid answers | Not JSON | Wrong shape | Cut off | First answers valid | Mean score |", "|---|---|---|---|---|---|---|---|"]
    for name, enforced, prompt in pairs:
        for label, value in (("enforced", enforced), ("prompt only", prompt)):
            if value is None:
                continue
            out.append(f"| {name} | {label} | {value['valid']} of {value['runs']} | {value['failures']['parse_fail']} | {value['failures']['schema_fail']} | "
                       f"{value['failures']['truncated']} | {value['first_try'][0]} of {value['first_try'][1]} | {value['score']:.1%} |")
    return out + [""]


def schema_pairs(manifest, summaries):
    """[(name, enforced, prompt_only)] for every candidate that ran with a @no-schema variant."""
    from .run import NO_SCHEMA
    names = [candidate["name"] for candidate in manifest["candidates"]]
    return [(name, summaries.get(name), summaries.get(name + NO_SCHEMA)) for name in names
            if not name.endswith(NO_SCHEMA) and name + NO_SCHEMA in names]


def decision_rows(manifest, results):
    """One decision row per candidate for evals.decision: the documents suite counts as a single task. Schema variants
    (A15) are measurements only: the app always enforces the schema, so they are never ranked."""
    rows = []
    for candidate in manifest["candidates"]:
        stats = results.get(candidate["name"])
        if stats is None or candidate.get("schema_enforced") is False:
            continue
        consistency = stats["consistency"]
        share = (consistency["pass_all"] if consistency["repeats"] > 1 else len(stats["passed_cases"])) / consistency["cases"] if consistency["cases"] else 0.0
        money = sum(cell["wrong"] for kind in stats["fields"].values() for name, cell in kind.items() if name.endswith("_minor"))
        rows.append({"name": candidate["name"], "runs": stats["runs"], "valid": stats["status"]["ok"] + stats["status"]["split"],
                     "money_errors": money, "pass_all": {"documents": share}, "scores": {"documents": stats["mean_score"] or 0.0},
                     "p95": percentile(stats["wall"], .95), "judge": None})
    return rows


def leaderboard(manifest, results):
    """One row per candidate, in the config's order: no ranking or winner is computed here (eval_plan.md A13)."""
    out = ["## Leaderboard", "", "| Candidate | Cases passed | Mean score | Fields wrong of checked | Rows found | First answers valid "
           "| Every repeat / any repeat | Score spread | Failed to process | Time p50 / p95 |", "|---|---|---|---|---|---|---|---|---|---|"]
    for candidate in manifest["candidates"]:
        stats = results.get(candidate["name"])
        if stats is None:
            continue
        cells = [cell for kind in stats["fields"].values() for cell in kind.values()]
        wrong, checked = sum(cell["wrong"] for cell in cells), sum(cell["checked"] for cell in cells)
        consistency, rows, first = stats["consistency"], stats["rows"], stats["first_try"]
        repeats = consistency["repeats"]
        failed = sum(count for status, count in stats["status"].items() if status not in ("ok", "split"))
        out.append(f"| {candidate['name']} | {len(stats['passed_cases'])} of {consistency['cases']} | "
                   f"{'—' if stats['mean_score'] is None else f'{stats['mean_score']:.1%}'} | {wrong} of {checked} | "
                   f"{f'{rows['matched']} of {rows['expected']}' if rows['scored'] else '—'} | {first['valid']} of {first['of']} | "
                   f"{f'{consistency['pass_all']} / {consistency['pass_any']} (of {repeats})' if repeats > 1 else '—'} | "
                   f"{'—' if consistency['score_spread'] is None else consistency['score_spread']} | {failed} of {stats['runs']} | "
                   f"{percentile(stats['wall'], .5)} s / {percentile(stats['wall'], .95)} s |")
    return out + ["", "Cases passed counts the first repeat. Mean score is the share of checked fields and expected rows that came out "
                  "right, with unprocessed documents scoring 0. A valid answer is a document that was read and extracted.", ""]


def markdown(manifest, results, regressions, previous):
    out = [f"# Eval run {manifest['run_id']}", "",
           f"Split **{manifest['split']}**, {manifest['cases']} cases, repeated {manifest['repeat']}×. Code {manifest['git']}, "
           f"{manifest['extraction_version']}, {manifest['vision_version']}. Private: this report lists case IDs and error kinds; "
           "share summary.json instead.", ""]
    if "sampling" in manifest:  # Runs from before sampling overrides used the app's own: temperature 0.1, no seed, enforced schema.
        sampling = manifest["sampling"]
        out += [f"Sampling: temperature {sampling['temperature']}, seed {sampling['seed'] if sampling['seed'] is not None else 'none'}, "
                f"schema {'enforced' if sampling['schema_enforced'] else 'in the prompt only'}.", ""]
    out += leaderboard(manifest, results)
    settings = decision_rules(manifest.get("decision"))  # Runs from before the decision rule used its defaults.
    out += decision_markdown(decide(decision_rows(manifest, results), settings), settings)
    summaries = {name: {"runs": stats["runs"], "valid": stats["status"]["ok"] + stats["status"]["split"], "failures": stats["failures"],
                        "first_try": (stats["first_try"]["valid"], stats["first_try"]["of"]), "score": stats["mean_score"] or 0.0}
                 for name, stats in results.items()}
    out += schema_comparison(schema_pairs(manifest, summaries))
    for candidate in manifest["candidates"]:
        stats = results.get(candidate["name"])
        if stats is None:
            continue
        identity = candidate.get("identity", {})
        out += [f"## {candidate['name']}", "",
                f"Vision `{candidate['vision']}` ({identity.get('vision', {}).get('quantization', 'unknown')}), reasoning `{candidate['reasoning']}` "
                f"({identity.get('reasoning', {}).get('quantization', 'unknown')}).", ""]
        statuses = ", ".join(f"{count} {status}" for status, count in stats["status"].most_common())
        out += [f"- Runs: {stats['runs']} ({statuses}). Document type right in {stats['type']['correct']} of {stats['runs']}.",
                f"- Fully checked documents: {stats['documents']['fully_checked']}; read perfectly: {stats['documents']['perfect']}."]
        consistency = stats["consistency"]
        if consistency["repeats"] > 1:
            out.append(f"- Consistency over {consistency['repeats']} repeats: {consistency['pass_all']} of {consistency['cases']} cases passed "
                       f"every time (pass^{consistency['repeats']}); {consistency['pass_any']} passed at least once (pass@{consistency['repeats']}); "
                       f"a case's score varies by {consistency['score_spread']} on average (standard deviation, 0 to 1).")
        first, sums, attempts = stats["first_try"], stats["arithmetic"], stats["attempts"]
        out.append(f"- First answers valid without a correction turn: {first['valid']} of {first['of']}. "
                   f"{attempts['calls']} model calls, {attempts['follow_ups']} correction turns, {attempts['truncated']} cut off at the token limit.")
        if sums["of"]:
            out.append(f"- The model's own numbers add up (rows to totals, pay lines to gross and net) in {sums['consistent']} of {sums['of']} documents.")
        if stats["failures"]:
            out.append("- Why documents failed: " + ", ".join(f"{count} {kind}" for kind, count in stats["failures"].most_common()) + ".")
        out += ["", "| Document | Field | Wrong of checked | Accuracy (95% interval) | Errors | Donor fixed: wrong of |", "|---|---|---|---|---|---|"]
        for kind in DOCUMENT_TYPES:
            for field in CRITICAL[kind]:
                cell = stats["fields"].get(kind, {}).get(field)
                if not cell or not cell["checked"]:
                    continue
                low, high = wilson(cell["checked"] - cell["wrong"], cell["checked"])
                errors = ", ".join(f"{error} {count}" for error, count in cell["errors"].most_common()) or "—"
                fixed = cell["by_state"].get("fixed")
                small = " (small sample)" if cell["checked"] < 20 else ""
                out.append(f"| {kind} | {field} | {cell['wrong']} of {cell['checked']} | {low:.0%}–{high:.0%}{small} | {errors} | "
                           f"{f'{fixed[1]} of {fixed[0]}' if fixed else '—'} |")
        rows = stats["rows"]
        if rows["scored"]:
            precision = f"{rows['matched']} of {rows['predicted']}" if rows["predicted"] else "—"
            out += ["", f"Rows over {rows['scored']} documents with a complete row list: {rows['matched']} of {rows['expected']} found; "
                    f"{precision} listed rows were real; {rows['missing']} missing, {rows['extra']} extra, {rows['duplicate']} duplicated, "
                    f"{rows['description_errors']} with a wrong description."]
        out += ["", "| Stratum | Value | Cases passed | Fields wrong of checked |", "|---|---|---|---|"]
        for dimension in ("document_type", "source_kind", "pages", "tag"):
            for value, stratum in sorted(stats["strata"].get(dimension, {}).items()):
                out.append(f"| {dimension} | {value} | {stratum['passed']} of {stratum['cases']} | {stratum['wrong']} of {stratum['checked']} |")
        wall = stats["wall"]
        out += ["", f"Time per document: median {percentile(wall, .5)} s, 95th percentile {percentile(wall, .95)} s (whole pipeline). "
                f"{stats['tokens']['model_calls']} model calls, {stats['tokens']['prompt_tokens']} prompt and {stats['tokens']['completion_tokens']} completion tokens."]
        diff = regressions.get(candidate["name"])
        if previous:
            out += ["", f"Compared with {previous}: newly failing {', '.join(diff['newly_failing']) if diff and diff['newly_failing'] else 'none'}; "
                    f"newly passing {', '.join(diff['newly_passing']) if diff and diff['newly_passing'] else 'none'}."]
        if stats["failed_cases"]:
            out += ["", "Cases that did not pass (first repeat): " + ", ".join(sorted(stats["failed_cases"])) + "."]
        out.append("")
    out += ["Accuracy counts only documents that were read and extracted; the others are counted by status above. "
            "A pass means every checked field is right and, where the row list was confirmed complete, every row is found once. "
            "Few or no errors in a small sample does not show that errors are rare. Results from different people's documents are "
            "different workloads, not a controlled comparison: compare models on the same run.", ""]
    return "\n".join(out)
