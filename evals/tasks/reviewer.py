"""Reviewer (eval_plan.md task 10): a second model checks a proposed analysis against the transcription.

Each case is a synthetic receipt with a correct analysis, into which one error is planted in most cases: a wrong
total, a wrong date, the wrong merchant, an invented item or a missing item. The reviewer must say needs_attention
and point at the planted error (by citing its line or naming the right or wrong value) when there is one, and say
no_issues_found when the analysis is right. The app's own checks (exact citations, a verdict that agrees with its
findings) run inside review().
"""

from decimal import Decimal
import re

from home_manager.core.money import EXPONENTS
from home_manager.documents.reviewer import review

from ..synthetic import documents, money
from .common import make_case, normal, result

NAME, ROLE, VERSION, PROMPT_VERSION, RUBRIC, REVIEWER = "reviewer", "reasoning", "reviewer-v1", "financial-review-v1", "reviewer", True
PLANTS = ("total", "date", "merchant", "invented_item", "missing_item", None, "total", None, "date", "invented_item", None)
PRINTED_DATE = re.compile(r"\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4}|\b\d{1,2} [A-Z][a-z]{2} \d{4}\b")


def cite(lines, text):
    """The first line holding text, as an exact citation."""
    for number, line in enumerate(lines, 1):
        if text in line:
            return [{"line_id": f"line-{number}", "quote": text}]
    raise ValueError(f"{text!r} is not printed.")


def analysis(document):
    """A correct analysis of a synthetic receipt, in the shape interpret() produces."""
    lines, fields = document["lines"], document["fields"]
    exponent = EXPONENTS[fields["currency"]]
    total = money(fields["total_minor"], exponent)
    date_line = next(line for line in lines if PRINTED_DATE.search(line))
    facts = [{"kind": "merchant", "value": fields["merchant"], "status": "proposed", "evidence": cite(lines, lines[0]), "note": ""},
             {"kind": "purchase_date", "value": fields["purchase_date"], "status": "proposed", "evidence": cite(lines, date_line), "note": ""},
             {"kind": "currency", "value": fields["currency"], "status": "proposed", "evidence": cite(lines, fields["currency"]), "note": ""},
             {"kind": "total", "value": f"{total} {fields['currency']}", "status": "proposed", "evidence": cite(lines, total), "note": ""}]
    items = []
    for row in document["rows"]:
        price = money(row["line_total_minor"], exponent)
        items.append({"description": row["description"], "product_code": None, "quantity": None, "unit_price": None, "line_total": price,
                      "discount": None, "status": "proposed", "note": "", "evidence": cite(lines, f"{row['description']} ")})
    return {"title": f"{fields['merchant']} purchase", "document_type": "receipt", "facts": facts, "receipt_items": items,
            "itemization_status": "itemized" if items else "not_present"}


def plant(found, kind, document):
    """Plant one error. Returns (analysis, the line it concerns, words that name it)."""
    facts = {item["kind"]: item for item in found["facts"]}
    exponent = EXPONENTS[document["fields"]["currency"]]
    if kind == "total":
        wrong = money(document["fields"]["total_minor"] + 10 ** exponent, exponent)
        facts["total"]["value"] = f"{wrong} {document['fields']['currency']}"
        return found, facts["total"]["evidence"][0]["line_id"], [wrong, money(document["fields"]["total_minor"], exponent)]
    if kind == "date":
        day = Decimal(document["fields"]["purchase_date"][-2:])
        wrong = document["fields"]["purchase_date"][:-2] + f"{int(day % 28) + 1:02d}"
        facts["purchase_date"]["value"] = wrong
        return found, facts["purchase_date"]["evidence"][0]["line_id"], [wrong, document["fields"]["purchase_date"]]
    if kind == "merchant":
        facts["merchant"]["value"] = "Lakeview Outfitters"
        return found, "line-1", ["lakeview", normal(document["fields"]["merchant"])]
    if kind == "invented_item":
        found["receipt_items"].append({**found["receipt_items"][0], "description": "GIFT CARD", "line_total": "25.00"})
        return found, found["receipt_items"][0]["evidence"][0]["line_id"], ["gift card", "25.00"]
    removed = found["receipt_items"].pop(-1)
    return found, removed["evidence"][0]["line_id"], [normal(removed["description"]), removed["line_total"]]


def cases():
    receipts = [document for document in documents() if document["document_type"] == "receipt" and len(document["rows"]) >= 2]
    out = []
    for index, document in enumerate(receipts):
        kind = PLANTS[index % len(PLANTS)]
        found, line, words = analysis(document), None, []
        if kind:
            found, line, words = plant(found, kind, document)
        lines = [{"id": f"line-{number}", "text": text} for number, text in enumerate(document["lines"], 1)]
        out.append(make_case(NAME, {"lines": lines, "analysis": found},
                             {"verdict": "needs_attention" if kind else "no_issues_found", "planted": kind, "line": line, "words": words},
                             [f"planted_{kind}" if kind else "clean"]))
    return out


def run(case, config, work):
    return review(config, case["input"]["analysis"], {"lines": case["input"]["lines"]}, work)


def grade(case, output):
    expected = case["expected"]
    checks = {"verdict": output["verdict"] == expected["verdict"]}
    if expected["planted"]:
        said = normal(" ".join(output["findings"]))
        cited = {item["line_id"] for item in output["evidence"]}
        checks["found_planted"] = expected["line"] in cited or any(normal(word) and normal(word) in said for word in expected["words"])
    else:
        checks["no_false_alarm"] = not output["findings"]
    required = ["verdict", "found_planted" if expected["planted"] else "no_false_alarm"]
    return result(checks, required)
