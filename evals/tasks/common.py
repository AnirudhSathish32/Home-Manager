"""Helpers shared by the per-task evals: stable case IDs, transcription lines, name and text comparison."""

import hashlib
import json
import re

from home_manager.documents.receipt_schema import TextLine

from ..graders import same_name


def case_id(task, value):
    """A stable 16-hex ID from the case's content, so a changed case is a new case in the regression diff."""
    return hashlib.sha256((task + ":" + json.dumps(value, sort_keys=True, default=str)).encode()).hexdigest()[:16]


def make_case(task, input, expected, tags=()):
    return {"id": case_id(task, {"input": input, "expected": expected}), "tags": list(tags), "input": input, "expected": expected}


def text_lines(texts, prefix="line"):
    """The app's transcription lines (line-1, line-2, ...) for a list of printed lines."""
    return [TextLine(id=f"{prefix}-{number}", text=text, block_ids=[]) for number, text in enumerate(texts, 1)]


def normal(text):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(text or "").casefold()).split())


def names_match(expected, predicted):
    if expected is None or predicted is None:
        return expected is None and predicted is None
    return same_name(expected, predicted)


def result(checks, required, scored=None):
    """{passed, score, checks}: passed when every required check is true; the score is the mean of the scored checks
    (booleans count 1 or 0, numbers are already 0 to 1)."""
    scored = scored if scored is not None else required
    values = [float(checks[name]) for name in scored if checks.get(name) is not None]
    return {"passed": all(bool(checks.get(name)) for name in required), "score": round(sum(values) / len(values), 4) if values else 0.0,
            "checks": checks}
