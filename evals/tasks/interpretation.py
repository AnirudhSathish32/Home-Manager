"""Interpretation (docs/evals.md, task 9): the financial reading of a receipt's transcription (documents/reasoning.py).

The app's own validate_interpretation runs inside interpret(), so an answer that cites text not on the page or
leaves a line unaccounted for fails there. Graded here against the synthetic receipts' known answers: the type,
merchant, date, total, and every item with its exact amount. Whether the reasoning is sound is the judge's rubric.
"""

from decimal import Decimal, InvalidOperation
import re
from types import SimpleNamespace

from home_manager.core.money import EXPONENTS
from home_manager.documents.reasoning import REASONING_VERSION, interpret

from ..graders import match_rows
from ..synthetic import documents
from .common import make_case, names_match, result, text_lines

NAME, ROLE, VERSION, PROMPT_VERSION, RUBRIC = "interpretation", "reasoning", "interpretation-v1", REASONING_VERSION, "interpretation"
NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
US_DATE = re.compile(r"\b(\d{2})/(\d{2})/\d{4}\b")


def cases():
    out = []
    for document in documents():
        if document["document_type"] != "receipt" or "return" in document["tags"]:  # A return's answers are signed, its print is not.
            continue
        fields, exponent = document["fields"], EXPONENTS[document["fields"]["currency"]]
        unclear = [match for line in document["lines"] for match in US_DATE.findall(line) if int(match[1]) <= 12]
        expected = {"document_type": "receipt", "merchant": fields["merchant"], "purchase_date": fields["purchase_date"],
                    "date_may_be_ambiguous": bool(unclear), "total": str(Decimal(fields["total_minor"]).scaleb(-exponent)),
                    "exponent": exponent, "items": document["rows"]}
        out.append(make_case(NAME, {"lines": document["lines"]}, expected, document["tags"]))
    return out


def run(case, config, work):
    source = SimpleNamespace(transcription_method="vision_model", model_text=True, lines=text_lines(case["input"]["lines"]), issues=[])
    return interpret(config, source, work).model_dump()


def amount(text):
    match = NUMBER.search(str(text or ""))
    try:
        return Decimal(match.group().replace(",", "")) if match else None
    except InvalidOperation:
        return None


def fact(output, kind):
    return next((item for item in output["facts"] if item["kind"] == kind and item["status"] == "proposed"), None)


def grade(case, output):
    expected = case["expected"]
    merchant, day, total = fact(output, "merchant"), fact(output, "purchase_date"), fact(output, "total")
    exponent = expected["exponent"]
    predicted = [{"description": item["description"],
                  "line_total_minor": int(amount(item["line_total"]).scaleb(exponent)) if amount(item["line_total"]) is not None else None}
                 for item in output["receipt_items"]]
    pairs, missing, extra, duplicate = match_rows("receipt", expected["items"], predicted)
    date_ok = bool(day and day["value"] == expected["purchase_date"])
    if expected["date_may_be_ambiguous"] and day is None:
        date_ok = True  # 03/05/2026 alone does not say which is the month; marking it ambiguous is right too.
    total_ok = bool(total and amount(total["value"]) == Decimal(expected["total"]))
    checks = {"document_type": output["document_type"] == expected["document_type"],
              "merchant": bool(merchant and names_match(expected["merchant"], merchant["value"])), "purchase_date": date_ok, "total": total_ok,
              "items": round(len(pairs) / max(len(expected["items"]), len(predicted)), 4) if expected["items"] or predicted else 1.0,
              "items_exact": missing == extra == duplicate == 0,
              # Wrong amounts only: an item listed without its printed amount is missing, not wrong.
              "money_errors": (0 if total_ok or total is None else 1)
                              + sum(row["line_total_minor"] is not None for row in predicted) - len(pairs)}
    return result(checks, ["document_type", "merchant", "purchase_date", "total", "items_exact"],
                  ["document_type", "merchant", "purchase_date", "total", "items"])
