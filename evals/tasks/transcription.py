"""Transcription (docs/evals.md, task 1): the vision model reads a drawn document image into text.

The cases are the synthetic corpus's image documents (evals/synthetic.py), so the printed text is known exactly.
Graded by character and word error rate against that text, and by the lines that matter most being read exactly:
the merchant or issuer, every line with the date, and every line holding the total or a balance.
"""

from pathlib import Path
import random
import re
import tempfile

from home_manager.documents.vision_tables import validate_tables
from home_manager.models.vision import VISION_VERSION, transcribe

from ..synthetic import SEED, documents, draw
from .common import make_case, normal, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION = "transcription", "vision", "transcription-v2-tables", VISION_VERSION
KEY_LINE = re.compile(r"\b(?:total|balance|net pay|gross pay|date|period)\b", re.IGNORECASE)
MAX_CER = 0.02


def cases():
    return [make_case(NAME, {"lines": document["lines"], "faded": document["faded"]}, {"text": "\n".join(document["lines"])},
                      [document["document_type"], *document["tags"]])
            for document in documents() if document["source"] == "png"] + table_cases()


def table_cases():
    cases = []
    for headings, rows in [
        (["Description", "Current", "YTD"], [["Regular pay", "2000.00", "52000.00"], ["Tax", "200.00", "5200.00"]]),
        (["Description", "YTD", "Current"], [["Regular pay", "52000.00", "2000.00"], ["Bonus", "500.00", ""]]),
        (["Description", "Current", "YTD"], [["Match", "50.00", "50.00"], ["Adjustment", "0.00", "-10.00"]]),
        (["Description", "Hours", "Rate", "Current", "YTD"], [["Regular", "80", "25.00", "2000.00", "52000.00"],
                                                                  ["Overtime", "5", "37.50", "187.50", "1187.50"]]),
        (["Item", "Qty", "Unit price", "Total"], [["Widgets", "2", "12.50", "25.00"], ["Delivery", "1", "5.00", "5.00"]]),
    ]:
        for faded in (False, True):
            matrix = [headings, *rows]
            lines = [" | ".join(row) for row in matrix]
            tables = [{"header_rows": [{"line_index": 0, "cells": headings}],
                       "rows": [{"line_index": i, "cells": row} for i, row in enumerate(rows, 1)]}]
            cases.append(make_case(NAME, {"lines": lines, "faded": faded}, {"text": "\n".join(lines), "tables": tables},
                                   ["structured_table", "faded" if faded else "clear"]))
    return cases


def run(case, config, work):
    with tempfile.TemporaryDirectory(prefix="hm-eval-") as folder:
        path = Path(folder) / "page.png"
        draw(case["input"]["lines"], path, case["input"]["faded"], random.Random(SEED))
        reading = transcribe(config, path, work)
        return {"text": reading.full_text, "tables": reading.tables, "table_issue": bool(reading.table_issue)}


def distance(a, b):
    """Levenshtein distance between two sequences."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def squash(text):
    return " ".join(str(text or "").split())


def grade(case, output):
    expected, got = squash(case["expected"]["text"]), squash((output or {}).get("text"))
    cer = distance(expected, got) / max(1, len(expected))
    wer = distance(expected.split(), got.split()) / max(1, len(expected.split()))
    read = {normal(line) for line in str((output or {}).get("text") or "").splitlines()}
    lines = case["input"]["lines"]
    key = [lines[0]] + [line for line in lines[1:] if KEY_LINE.search(line)]
    found = sum(normal(line) in read or normal(line) in normal(got) for line in key)
    checks = {"cer": round(cer, 4), "wer": round(wer, 4), "accuracy": round(max(0.0, 1 - cer), 4), "key_lines": round(found / len(key), 4),
              "low_error": cer <= MAX_CER, "all_key_lines": found == len(key),
              "no_unreadable": case["input"]["faded"] or "[unreadable]" not in got.lower()}
    required = ["low_error", "all_key_lines", "no_unreadable"]
    if "tables" in case["expected"]:
        checks.update(table_checks(case["expected"]["tables"], output or {}))
        required += ["all_table_cells", "no_wrong_column_values"]
    checks["output_characters"] = len(str((output or {}).get("text") or ""))
    return result(checks, required, ["accuracy", "key_lines"])


def table_checks(expected, output):
    """Placement is scored against known drawn cells, separately from transcription.

    These are reported cells, not proof that vision located independent pixels.
    Missing tables fail coverage, even when a flat transcription is perfect.
    """
    try:
        tables = validate_tables(output.get("tables", []), text_lines(str(output.get("text") or "").split("\n"))).tables
    except ValueError:
        tables = []
    wanted = [row["cells"] for table in expected for key in ("header_rows", "rows") for row in table[key]]
    got = [[cell.quote for cell in row.cells] for table in tables for row in [*table.header_rows, *table.rows]]
    missing, wrong, misplaced, correct = 0, 0, 0, 0
    for r, row in enumerate(wanted):
        for c, text in enumerate(row):
            actual = got[r][c] if r < len(got) and c < len(got[r]) else None
            if actual == text:
                correct += 1
            elif actual is None or (text and not actual):
                missing += 1
            else:
                wrong += 1
                if re.fullmatch(r"[-+\d.,]+", actual or "") and actual in row:
                    misplaced += 1
    extra = max(0, sum(map(len, got)) - sum(map(len, wanted)))
    return {"table_cells_expected": sum(map(len, wanted)), "table_cells_correct": correct,
            "table_cells_missing": missing, "table_cells_wrong": wrong, "table_cells_extra": extra,
            "wrong_column_values": misplaced, "all_table_cells": not (missing or wrong or extra),
            "no_wrong_column_values": misplaced == 0, "table_review": bool(output.get("table_issue")) or not tables}


def report_lines(grouped):
    out = ["", "Structured table placement (known synthetic cells; separate from text accuracy):", "",
           "| Candidate | Correct / expected cells | Missing | Wrong | Wrong column values | Table review cases | Text characters |",
           "|---|---|---|---|---|---|---|"]
    for name, rows in grouped.items():
        checks = [row["grades"]["checks"] for row in rows if "table_cells_expected" in row["grades"]["checks"]]
        if not checks:
            continue
        total = lambda key, checks=checks: sum(check.get(key, 0) for check in checks)
        out.append(f"| {name} | {total('table_cells_correct')} / {total('table_cells_expected')} | {total('table_cells_missing')} | "
                   f"{total('table_cells_wrong')} | {total('wrong_column_values')} | {total('table_review')} / {len(checks)} | "
                   f"{total('output_characters')} |")
    out += ["", "Timing and failed requests are reported above. These placement checks do not establish the end-to-end auto-counting gate."]
    return out
