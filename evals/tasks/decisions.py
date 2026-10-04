"""Decision model (models/decisions.py): the app's two System One questions, plus calibration.

Two kinds of case, over the synthetic documents:
- classify: the first 40 lines of a document; the model picks its type from DOCUMENT_TYPES.
- support: a claim and the line it was read from, as ExtractionService.assess asks it. Half the claims are true
  (the printed merchant, date or total) and half are planted errors with the same citation (a wrong value).

Every answer keeps the model's probabilities, so the report can show calibration (expected calibration error and
Brier score) and fit the calibration temperature that minimises log loss. The fitted value goes in Settings with
calibrated set, after a run on the corpus agrees.
"""

from decimal import Decimal
import math

from home_manager.core.money import EXPONENTS
from home_manager.models import decisions
from home_manager.models.decisions import DOCUMENT_TYPES, SUPPORT_THRESHOLD

from ..synthetic import documents, money
from .common import make_case, result
from .reviewer import PRINTED_DATE, cite

NAME, ROLE, VERSION, PROMPT_VERSION = "decisions", "decision", "decisions-v1", decisions.DECISION_VERSION
TEMPERATURES = [round(0.25 * step, 2) for step in range(1, 33)]  # 0.25 to 8.
BINS = 10


def claims(document):
    """[(claim, quotes, true?)] for one receipt: merchant, date and total, each true once and wrong once."""
    lines, fields = document["lines"], document["fields"]
    exponent = EXPONENTS[fields["currency"]]
    total = money(fields["total_minor"], exponent)
    date_line = next(line for line in lines if PRINTED_DATE.search(line))
    day = Decimal(fields["purchase_date"][-2:])
    wrong_date = fields["purchase_date"][:-2] + f"{int(day % 28) + 1:02d}"
    total_quote = [cite(lines, total)[0]["quote"]]
    return [(f"merchant: {fields['merchant']}", [lines[0]], True), ("merchant: Lakeview Outfitters", [lines[0]], False),
            (f"purchase date: {fields['purchase_date']}", [date_line], True), (f"purchase date: {wrong_date}", [date_line], False),
            (f"total: {total}", total_quote, True),
            (f"total: {money(fields['total_minor'] + 10 ** exponent, exponent)}", total_quote, False)]


def cases():
    out = []
    for document in documents():
        out.append(make_case(NAME, {"kind": "classify", "text": "\n".join(document["lines"][:40])},
                             {"label": document["document_type"]}, ["classify", document["document_type"], *document["tags"]]))
    for document in documents():
        if document["document_type"] != "receipt":
            continue
        for claim, quotes, true in claims(document):
            out.append(make_case(NAME, {"kind": "support", "claim": claim, "quotes": quotes}, {"label": "true" if true else "false"},
                                 ["support", "true_claim" if true else "planted_error", *document["tags"]]))
    # Documents that start alike (the same shop or bank) ask the same question; each is kept once.
    unique = {}
    for case in out:
        unique.setdefault(case["id"], case)
    return list(unique.values())


def run(case, config, work):
    """{"answer", "probabilities"}: the chosen label (None when the model gave no label) and the full distribution."""
    data = case["input"]
    if data["kind"] == "classify":
        question = {"document_type": {"type": "choice", "instructions": "What kind of household financial document is this?",
                                      "criteria": DOCUMENT_TYPES}}
        item = decisions.decide(config, data["text"], question, work)["document_type"]
        return {"answer": item["answer"], "probabilities": item["probabilities"], "coverage": item.get("coverage")}
    item = decisions.decide(config, {"claim": data["claim"], "source": data["quotes"]}, decisions.SUPPORTED, work)["supported"]
    if item["answer"] is None:
        return {"answer": None, "probabilities": None, "coverage": item.get("coverage")}
    # The app's rule: supported at SUPPORT_THRESHOLD or above.
    return {"answer": "true" if item["answer"] >= SUPPORT_THRESHOLD else "false", "probabilities": item["probabilities"],
            "coverage": item.get("coverage")}


def grade(case, output):
    answered = output["answer"] is not None
    return result({"answered": answered, "correct": answered and output["answer"] == case["expected"]["label"]}, ["answered", "correct"])


# Calibration, for the report ------------------------------------------------------

def tempered(probabilities, temperature):
    usable = {name: value for name, value in probabilities.items() if value > 0}
    logs = {name: math.log(value) / temperature for name, value in usable.items()}
    peak = max(logs.values())
    weights = {name: math.exp(value - peak) for name, value in logs.items()}
    total = sum(weights.values())
    return {name: weights.get(name, 0.0) / total for name in probabilities}


def log_loss(pairs, temperature):
    return sum(-math.log(max(tempered(probabilities, temperature).get(label, 0.0), 1e-9)) for probabilities, label in pairs) / len(pairs)


def calibration(rows):
    """{answered, ece, brier, fitted_temperature, loss_before, loss_after} over one candidate's answered rows, or None."""
    pairs = [(row["output"]["probabilities"], row_label(row)) for row in rows
             if row["status"] == "ok" and row["output"] and row["output"].get("probabilities")]
    if not pairs:
        return None
    bins = [[0, 0.0, 0] for _ in range(BINS)]  # count, confidence sum, correct
    brier = 0.0
    for probabilities, label in pairs:
        chosen = max(probabilities, key=probabilities.get)
        confidence = probabilities[chosen]
        slot = bins[min(int(confidence * BINS), BINS - 1)]
        slot[0], slot[1], slot[2] = slot[0] + 1, slot[1] + confidence, slot[2] + (chosen == label)
        brier += sum((value - (name == label)) ** 2 for name, value in probabilities.items())
    ece = sum(abs(total / count - correct / count) * count for count, total, correct in bins if count) / len(pairs)
    fitted = min(TEMPERATURES, key=lambda value: log_loss(pairs, value))
    return {"answered": len(pairs), "ece": round(ece, 4), "brier": round(brier / len(pairs), 4), "fitted_temperature": fitted,
            "loss_before": round(log_loss(pairs, 1.0), 4), "loss_after": round(log_loss(pairs, fitted), 4)}


def row_label(row):
    """The expected label, recovered from the result line's tags (results.jsonl does not repeat the case)."""
    tags = row["tags"]
    if "support" in tags:
        return "true" if "true_claim" in tags else "false"
    return next(tag for tag in tags if tag in DOCUMENT_TYPES)


def report_lines(rows_by_candidate):
    out = ["", "Calibration (all answered cases; the fitted temperature minimises log loss, 1.0 means as the model gave them):", "",
           "| Candidate | Answered | Calibration error | Brier | Fitted temperature | Log loss before / after |", "|---|---|---|---|---|---|"]
    for name, rows in rows_by_candidate.items():
        value = calibration(rows)
        if value:
            out.append(f"| {name} | {value['answered']} | {value['ece']:.3f} | {value['brier']:.3f} | {value['fitted_temperature']} | "
                       f"{value['loss_before']:.3f} / {value['loss_after']:.3f} |")
        else:
            out.append(f"| {name} | 0 | — | — | — | — |")
    return out
