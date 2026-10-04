"""Picking a model by a rule set in advance (eval_plan.md A13): gate, rank, tie-break, usability floor.

1. Gate: a candidate is eligible only if its final answers were valid in at least min_valid_rate of runs, it made at most
   max_money_errors wrong money amounts, and every task passed in every repeat (pass^N) for at least min_pass_all of its
   cases (with one repeat, simply passed).
2. Usability floor: a candidate whose 95th-percentile time per case is above max_p95_seconds is excluded (off by default).
3. Rank the eligible by weighted accuracy: the mean score of each task, weighted by [decision.weights] (1 by default).
4. Tie-break: candidates within tie_points percentage points of the leader are ordered by mean pass^N, then by a
   calibrated judge's mean score. An uncalibrated judge never counts.

Thresholds live in [decision] of the config (models.toml); these defaults are eval_plan.md's proposals.
"""

DEFAULTS = {"min_valid_rate": 0.99, "max_money_errors": 0, "min_pass_all": 0.9, "max_p95_seconds": None, "tie_points": 2.0}


def rules(config_section):
    """The decision rules from a config's [decision] table, checked; unknown keys are refused."""
    section = dict(config_section or {})
    weights = section.pop("weights", {}) or {}
    unknown = set(section) - set(DEFAULTS)
    if unknown:
        raise ValueError("Unknown [decision] settings: " + ", ".join(sorted(unknown)) + ".")
    out = {**DEFAULTS, **section}
    for key in ("min_valid_rate", "min_pass_all"):
        if not isinstance(out[key], (int, float)) or not 0 <= out[key] <= 1:
            raise ValueError(f"[decision] {key} must be a share from 0 to 1.")
    if not isinstance(out["max_money_errors"], int) or out["max_money_errors"] < 0:
        raise ValueError("[decision] max_money_errors must be a whole number, 0 or more.")
    if out["max_p95_seconds"] is not None and (not isinstance(out["max_p95_seconds"], (int, float)) or out["max_p95_seconds"] <= 0):
        raise ValueError("[decision] max_p95_seconds must be a positive number of seconds.")
    if not isinstance(weights, dict) or any(not isinstance(value, (int, float)) or value < 0 for value in weights.values()):
        raise ValueError("[decision.weights] must map task names to weights of 0 or more.")
    out["weights"] = dict(weights)
    return out


def weighted(scores, weights):
    total = sum(weights.get(task, 1) for task in scores)
    return sum(score * weights.get(task, 1) for task, score in scores.items()) / total if total else 0.0


def decide(rows, settings):
    """rows: [{name, runs, valid, money_errors, pass_all: {task: share}, scores: {task: mean}, p95: seconds or None,
    judge: calibrated mean (1-4) or None}]. Returns {winner, ranking, excluded: {name: [reasons]}, accuracy: {name: share}, note}."""
    excluded, accuracy = {}, {}
    for row in rows:
        reasons = []
        valid_rate = row["valid"] / row["runs"] if row["runs"] else 0.0
        if valid_rate < settings["min_valid_rate"]:
            reasons.append(f"valid answers {valid_rate:.1%} < {settings['min_valid_rate']:.0%}")
        if row["money_errors"] > settings["max_money_errors"]:
            reasons.append(f"{row['money_errors']} wrong money amounts > {settings['max_money_errors']}")
        for task, share in sorted(row["pass_all"].items()):
            if share < settings["min_pass_all"]:
                reasons.append(f"{task}: passed every repeat in {share:.0%} of cases < {settings['min_pass_all']:.0%}")
        if settings["max_p95_seconds"] is not None and (row["p95"] is None or row["p95"] > settings["max_p95_seconds"]):
            reasons.append(f"95th-percentile time {row['p95']} s > {settings['max_p95_seconds']} s")
        accuracy[row["name"]] = round(weighted(row["scores"], settings["weights"]), 4)
        if reasons:
            excluded[row["name"]] = reasons
    eligible = [row for row in rows if row["name"] not in excluded]
    eligible.sort(key=lambda row: -accuracy[row["name"]])
    if eligible:
        leader = accuracy[eligible[0]["name"]]
        close = [row for row in eligible if (leader - accuracy[row["name"]]) * 100 <= settings["tie_points"]]
        rest = [row for row in eligible if row not in close]

        def tie_key(row):
            consistency = sum(row["pass_all"].values()) / len(row["pass_all"]) if row["pass_all"] else 0.0
            return (-consistency, -(row["judge"] or 0), -accuracy[row["name"]])
        eligible = sorted(close, key=tie_key) + rest
    ranking = [row["name"] for row in eligible]
    if not rows:
        note = "No candidates were run."
    elif not ranking:
        note = "No candidate passes the gate."
    elif len(ranking) == 1:
        note = f"{ranking[0]} is the only candidate that passes the gate."
    else:
        note = f"{ranking[0]} ranks first of {len(ranking)} that pass the gate."
    return {"winner": ranking[0] if ranking else None, "ranking": ranking, "excluded": excluded, "accuracy": accuracy, "note": note}


def markdown(decision, settings):
    out = ["## Decision", "", f"**{decision['note']}**", "",
           f"Gate: valid answers at least {settings['min_valid_rate']:.0%}, at most {settings['max_money_errors']} wrong money amounts, "
           f"every task passed in every repeat for at least {settings['min_pass_all']:.0%} of its cases"
           + (f", 95th-percentile time at most {settings['max_p95_seconds']} s" if settings["max_p95_seconds"] is not None else "")
           + f". Ranked by weighted accuracy; within {settings['tie_points']} points, by consistency, then a calibrated judge.", ""]
    if decision["ranking"]:
        out += ["| Rank | Candidate | Weighted accuracy |", "|---|---|---|"]
        out += [f"| {index} | {name} | {decision['accuracy'][name]:.1%} |" for index, name in enumerate(decision["ranking"], 1)]
        out.append("")
    for name, reasons in decision["excluded"].items():
        out.append(f"- {name} is excluded: " + "; ".join(reasons) + ".")
    return out + [""]
