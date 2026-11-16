"""Receipt layout (docs/evals.md "Reading formats"): a drawn receipt is read under whichever reading format is active, and the rows,
amounts, indents and positions of the reading are counted against what was drawn (specs/receipt-layout-eval).

The cases are evals/receipt_layouts.py's 24 receipts: printed the way real ones print (prices at the right edge, indented side lines,
centred headings, a handwritten tip), in several photo conditions, with exact answers. Graded by evals/layout_grading.py.
The task is measured only: it counts in no ranking, gate or weighted accuracy.
"""

from collections import defaultdict
import functools
from pathlib import Path
import tempfile

from home_manager.documents.vision_layout import usable
from home_manager.models.vision import DEFAULT_FORMAT, READING_FORMATS, VISION_VERSION, active_format, transcribe

from ..layout_grading import grade_reading
from ..receipt_layouts import CASES, answers, draw, make, png_bytes
from ..report import MIN_CELL, wilson
from .common import make_case, result

NAME, ROLE, VERSION, PROMPT_VERSION = "receipt_layout", "vision", "receipt-layout-v1", VISION_VERSION
MEASURED_ONLY = True
FAMILIES = ("grocery", "dining", "fuel", "terminal", "itemized", "long", "ereceipt", "return")
CONDITIONS = ("clean", "faded", "tilted", "angled", "blurred", "small_text", "background")


@functools.cache
def _cases():
    out = []
    for family, condition, index in CASES:
        receipt = make(family, condition, index)
        image, boxes = draw(receipt)
        out.append(make_case(NAME, {"family": family, "condition": condition, "index": index}, answers(receipt, boxes, image.size), receipt.tags))
    return tuple(out)


def cases():
    return list(_cases())


def run(case, config, work):
    receipt = make(case["input"]["family"], case["input"]["condition"], case["input"]["index"])
    with tempfile.TemporaryDirectory(prefix="hm-eval-") as folder:
        path = Path(folder) / "receipt.png"
        path.write_bytes(png_bytes(draw(receipt)[0]))
        reading = transcribe(config, path, work)
    return {"format": active_format(), "lines": [[text, indent] for text, indent in reading.lines], "rows": reading.rows, "spans": reading.spans,
            "notes": reading.notes, "text": reading.full_text, "table_issue": bool(reading.table_issue)}


def share(count, total):
    return round(count / total, 4) if total else None


def grade(case, output):
    counts = grade_reading(case["expected"], output)
    rows, amounts = counts["rows"], counts["amounts"]
    indent_right = counts["indented_right"] + counts["edge_right"]
    reported = counts["indent_reported"]
    checks = {**{key: value for key, value in counts.items() if key != "evaluations"},
              "no_split_rows": counts["split"] == 0, "no_merged_rows": counts["merged"] == 0, "no_missing_rows": counts["missing"] == 0,
              "amounts_on_their_rows": counts["amounts_on_row"] == amounts,
              "indents_right": not reported or (counts["indented_wrong"] + counts["edge_wrong"] + counts["indented_unknown"] + counts["edge_unknown"] == 0
                                                and indent_right == counts["indented_rows"] + counts["edge_rows"]),
              "whole_share": share(counts["whole"], rows), "amounts_on_row_share": share(counts["amounts_on_row"], amounts),
              "indent_share": share(indent_right, rows) if reported else None, "accuracy": round(max(0.0, 1 - counts["cer"]), 4),
              "output_characters": len(str((output or {}).get("text") or ""))}
    required = ["no_split_rows", "no_merged_rows", "no_missing_rows", "amounts_on_their_rows", "indents_right"]
    return result(checks, required, ["whole_share", "amounts_on_row_share", "indent_share", "accuracy"])


# The report ----------------------------------------------------------------------------------------------------------------------

TOTALS = ("rows", "whole", "split", "merged", "missing", "extra", "out_of_order", "amounts", "amounts_read", "amounts_on_row", "amounts_wrong",
          "amounts_missing", "indented_rows", "indented_right", "indented_wrong", "indented_unknown", "edge_rows", "edge_right", "edge_wrong",
          "edge_unknown", "cell_rows", "cell_rows_match", "align_rows", "align_right", "handwritten_expected", "handwritten_reported",
          "handwritten_correct", "distance", "characters")


def format_of(candidate, line):
    """The reading format of a result line: the one the reading recorded, else the line's label, else the candidate's `@format` suffix."""
    output = line.get("output") or {}
    for name in (output.get("format"), line.get("reading_format"), candidate.rpartition("@")[2]):
        if name in READING_FORMATS:
            return name
    return DEFAULT_FORMAT


def sums(lines):
    """Counts added up over the cases that were read and graded, and how many were not."""
    total = dict.fromkeys(TOTALS, 0)
    reported = defaultdict(int)
    graded = [line for line in lines if line["status"] == "ok" and line["grades"]["checks"]]
    for line in graded:
        checks = line["grades"]["checks"]
        for key in TOTALS:
            total[key] += checks.get(key) or 0
        for key in ("indent_reported", "cells_reported", "position_reported"):
            reported[key] += bool(checks.get(key))
        reported["passed"] += bool(line["grades"]["passed"])
        reported["pieces"] += len((line.get("output") or {}).get("spans") or [])
        reported["unusable"] += sum(not usable(piece.get("box")) for piece in (line.get("output") or {}).get("spans") or [])
    return {**total, **reported, "cases": len(lines), "graded": len(graded),
            "truncated": sum(line.get("failure") == "truncated" for line in lines), "failed": sum(line["status"] != "ok" for line in lines)}


def interval(count, total):
    low, high = wilson(count, total)
    return "—" if low is None else f"{count} of {total} ({low:.0%}–{high:.0%})"


def of(count, total):
    return f"{count} of {total}"


def reading_table(name, rows):
    lines = [f"#### {name} ({READING_FORMATS[name]})", "",
             "| Candidate | Cases passed | Rows read whole | Split rows | Merged rows | Missing rows | Extra lines | Out of order | "
             "Amounts on their row | Amounts read | Wrong amounts | Missing amounts | Character error |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    positions = ["", "Positions the model reported (never a measurement):", "",
                 "| Candidate | Indented rows right | Edge rows right | Rows with cells right | Alignment right | Handwriting precision / recall | "
                 "Usable boxes | Median overlap |", "|---|---|---|---|---|---|---|---|"]
    for candidate, found in rows.items():
        total = sums(found)
        out = f"| {candidate} | {of(total['passed'], total['cases'])} | {interval(total['whole'], total['rows'])} | {of(total['split'], total['rows'])} | " \
              f"{of(total['merged'], total['rows'])} | {of(total['missing'], total['rows'])} | {total['extra']} | {total['out_of_order']} | " \
              f"{interval(total['amounts_on_row'], total['amounts'])} | {of(total['amounts_read'], total['amounts'])} | " \
              f"{of(total['amounts_wrong'], total['amounts'])} | {of(total['amounts_missing'], total['amounts'])} | " \
              f"{total['distance'] / max(1, total['characters']):.1%} |"
        lines.append(out)
        indent = "not reported" if not total["indent_reported"] else \
            f"{of(total['indented_right'], total['indented_rows'])} (wrong {total['indented_wrong']}, unknown {total['indented_unknown']})"
        edge = "not reported" if not total["indent_reported"] else \
            f"{of(total['edge_right'], total['edge_rows'])} (wrong {total['edge_wrong']}, unknown {total['edge_unknown']})"
        cells = of(total["cell_rows_match"], total["cell_rows"]) if total["cells_reported"] else "not reported"
        align = of(total["align_right"], total["align_rows"]) if total["position_reported"] else "not reported"
        hand = "not reported"
        boxes = overlap = "not reported"
        if total["position_reported"]:
            precision = share(total["handwritten_correct"], total["handwritten_reported"])
            recall = share(total["handwritten_correct"], total["handwritten_expected"])
            hand = f"{'—' if precision is None else format(precision, '.0%')} / {'—' if recall is None else format(recall, '.0%')} " \
                   f"({total['handwritten_correct']} of {total['handwritten_expected']} written by hand)"
            boxes = of(total["pieces"] - total["unusable"], total["pieces"])
            overlaps = [line["grades"]["checks"]["overlap"] for line in found if line["status"] == "ok" and line["grades"]["checks"].get("overlap") is not None]
            overlap = f"{sorted(overlaps)[len(overlaps) // 2]:.2f}" if overlaps else "—"
        positions.append(f"| {candidate} | {indent} | {edge} | {cells} | {align} | {hand} | {boxes} | {overlap} |")
    return lines + positions + [""]


def breakdown(name, rows, key):
    """Rows read whole and amounts on their row by family or by condition, with denominators; a cell of fewer than MIN_CELL cases is "few"."""
    groups = defaultdict(list)
    for candidate, found in rows.items():
        for line in found:
            for tag in line["tags"]:
                if tag in key:
                    groups[(candidate, tag)].append(line)
    heading = "family" if key is FAMILIES else "photo condition"
    lines = [f"By {heading} ({name}):", "", f"| Candidate | {heading.capitalize()} | Cases | Rows read whole | Amounts on their row |", "|---|---|---|---|---|"]
    for candidate in rows:
        for tag in key:
            found = groups.get((candidate, tag))
            if not found:
                continue
            total = sums(found)
            note = " (few)" if total["cases"] < MIN_CELL else ""
            lines.append(f"| {candidate} | {tag} | {total['graded']} of {total['cases']} read{note} | {of(total['whole'], total['rows'])} | "
                         f"{of(total['amounts_on_row'], total['amounts'])} |")
    return lines + [""]


def report_lines(grouped):
    """The "Reading formats" section: one table per format with every count against its total, then rows whole and amounts on their row
    per family and per photo condition."""
    by_format = defaultdict(dict)
    for candidate, found in grouped.items():
        formats = defaultdict(list)
        for line in found:
            formats[format_of(candidate, line)].append(line)
        for name, lines in formats.items():
            by_format[name][candidate] = lines
    out = ["", "### Reading formats", "",
           "Drawn receipts with known rows, read under each reading format. Measured only: this task counts in no ranking, gate or weighted "
           "accuracy, and a format comparison names no winner. Counts are against the printed rows and amounts of the cases that were read; "
           "intervals are 95% Wilson intervals; \"few\" marks fewer than "
           f"{MIN_CELL} cases.", ""]
    for name in READING_FORMATS:
        if name in by_format:
            out += reading_table(name, by_format[name])
            out += breakdown(name, by_format[name], FAMILIES) + breakdown(name, by_format[name], CONDITIONS)
    return out
