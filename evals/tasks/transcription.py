"""Transcription (eval_plan.md task 1): the vision model reads a drawn document image into text.

The cases are the synthetic corpus's image documents (evals/synthetic.py), so the printed text is known exactly.
Graded by character and word error rate against that text, and by the lines that matter most being read exactly:
the merchant or issuer, every line with the date, and every line holding the total or a balance.
"""

from pathlib import Path
import random
import re
import tempfile

from home_manager.models.vision import VISION_VERSION, transcribe

from ..synthetic import SEED, documents, draw
from .common import make_case, normal, result

NAME, ROLE, VERSION, PROMPT_VERSION = "transcription", "vision", "transcription-v1", VISION_VERSION
KEY_LINE = re.compile(r"\b(?:total|balance|net pay|gross pay|date|period)\b", re.IGNORECASE)
MAX_CER = 0.02


def cases():
    return [make_case(NAME, {"lines": document["lines"], "faded": document["faded"]}, {"text": "\n".join(document["lines"])},
                      [document["document_type"], *document["tags"]])
            for document in documents() if document["source"] == "png"]


def run(case, config, work):
    with tempfile.TemporaryDirectory(prefix="hm-eval-") as folder:
        path = Path(folder) / "page.png"
        draw(case["input"]["lines"], path, case["input"]["faded"], random.Random(SEED))
        return {"text": transcribe(config, path, work).full_text}


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
    return result(checks, ["low_error", "all_key_lines", "no_unreadable"], ["accuracy", "key_lines"])
