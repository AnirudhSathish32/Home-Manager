"""Deterministic grading of one model result against one case's checked answers. No model judges anything here.

Only checked fields are scored; an unchecked field is never counted right or wrong. Rows are scored only when someone
confirmed the list complete. Rows match as a multiset, so two identical lattes are two rows, and a third is a duplicate.
Every mismatch gets one error category from a fixed list, so reports carry no values.
"""

from datetime import date
import re

from home_manager.core.answers import CRITICAL, ROWS, kind_of

FIELD_ERRORS = ("missing", "invented", "sign", "scale", "digit", "date_swap", "year", "wrong_value")
ROW_ERRORS = ("missing_row", "extra_row", "duplicate_row")
# Why a document was not read or extracted: the model's JSON did not parse, broke the schema, or failed the app's
# evidence checks; it was cut off at max_tokens; or the model server failed (loading, memory, context, network).
FAILURE_KINDS = ("parse_fail", "schema_fail", "validator_fail", "truncated", "context_limit", "out_of_memory", "load_fail",
                 "model_timeout", "model_connection", "model_http", "model_stream", "other")
# The app's own words for an answer of the wrong shape ("...did not follow the check-in format", "...does not follow the assistant format").
FORMAT_ERROR = re.compile(r"(?:did not|does not) follow the [\w -]+ format")
# The app's own checks rejecting a well-formed answer (documents/reasoning.validate_interpretation, documents/reviewer.review).
APP_CHECK = re.compile(r"contradicts its findings|cited invalid source evidence|cites missing or altered|lacks supporting evidence|"
                       r"Item breakdown|Itemization status contradicts|must be marked partial|An item line was also")
SUFFIXES = {"inc", "llc", "ltd", "co", "corp", "corporation", "company", "the", "store", "stores", "na", "plc", "gmbh"}


def tokens(text):
    words = re.sub(r"[^0-9a-z&]+", " ", str(text).casefold()).split()
    return [word for word in words if word not in SUFFIXES and not re.fullmatch(r"#?\d{1,5}", word)] or words


def same_name(expected, predicted):
    """Names match ignoring case, punctuation, legal suffixes and store numbers, or when one is the other with words added
    at the end (Costco and Costco Wholesale)."""
    a, b = tokens(expected), tokens(predicted)
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return a == b or (bool(shorter) and longer[:len(shorter)] == shorter and len("".join(shorter)) >= 4)


def money_error(expected, predicted):
    if predicted == -expected:
        return "sign"
    for power in (1, 2, 3):
        if expected and (predicted == expected * 10**power or predicted * 10**power == expected):
            return "scale"
    a, b = str(abs(expected)), str(abs(predicted))
    if len(a) == len(b) and (sum(x != y for x, y in zip(a, b)) == 1 or sorted(a) == sorted(b)):
        return "digit"
    return "wrong_value"


def date_error(expected, predicted):
    try:
        a, b = date.fromisoformat(expected), date.fromisoformat(predicted)
    except (TypeError, ValueError):
        return "wrong_value"
    if (a.year, a.month, a.day) == (b.year, b.day, b.month):
        return "date_swap"
    if (a.month, a.day) == (b.month, b.day):
        return "year"
    return "wrong_value"


def compare(name, expected, predicted):
    """None when the values agree, else an error category."""
    if expected is None and predicted is None:
        return None
    if predicted is None:
        return "missing"
    if expected is None:
        return "invented"
    kind = kind_of(name)
    if kind == "money":
        if isinstance(predicted, bool) or not isinstance(predicted, int):
            return "wrong_value"
        return None if predicted == expected else money_error(expected, predicted)
    if kind == "date":
        return None if predicted == expected else date_error(expected, predicted)
    if kind == "text":
        return None if same_name(expected, predicted) else "wrong_value"
    return None if predicted == expected else "wrong_value"


def row_key(document_type, row):
    """The columns that must agree exactly for two rows to be the same row; descriptions are compared after matching."""
    _, columns = ROWS[document_type]
    return tuple(row.get(name) for name in columns if name != "description")


def match_rows(document_type, expected, predicted):
    """Multiset matching: each expected row takes the first unused predicted row with the same key, preferring one whose
    description also matches. Returns (pairs, missing, extra, duplicate)."""
    unused = list(range(len(predicted)))
    pairs, missing = [], 0
    for row in expected:
        candidates = [index for index in unused if row_key(document_type, predicted[index]) == row_key(document_type, row)]
        if not candidates:
            missing += 1
            continue
        named = [index for index in candidates if same_name(row["description"], predicted[index].get("description") or "")]
        chosen = (named or candidates)[0]
        unused.remove(chosen)
        pairs.append((row, predicted[chosen]))
    matched_keys = {row_key(document_type, row) for row, _ in pairs}
    duplicate = sum(1 for index in unused if row_key(document_type, predicted[index]) in matched_keys)
    return pairs, missing, len(unused) - duplicate, duplicate


def failure_kind(error, attempts=()):
    """One FAILURE_KINDS entry for a stage that failed, from its error text and its recorded model attempts."""
    error = error or ""
    if "switching models" in error:
        return "load_fail"
    if "insufficient memory" in error:
        return "out_of_memory"
    if "context limit" in error:
        return "context_limit"
    failed = [attempt for attempt in attempts if attempt["status"] == "failed"]
    if failed:
        category = failed[-1]["error_category"] or ""
        return {"timeout": "model_timeout", "connection": "model_connection", "invalid_stream": "model_stream"}.get(
            category, "model_http" if category.startswith("http_") else "other")
    if attempts and attempts[-1]["finish_reason"] == "length":
        return "truncated"
    if "json_invalid" in error:
        return "parse_fail"
    if "output failed validation" in error or "did not match the full-text schema" in error or FORMAT_ERROR.search(error):
        return "schema_fail"
    if "failed validation" in error or APP_CHECK.search(error):
        return "validator_fail"
    return "other"


def arithmetic(kind, record):
    """Whether the model's own numbers add up (rows to the subtotal or closing balance, pay lines to gross and net pay).
    Needs no answers, so it also measures documents nobody checked. None when the record prints too little to check."""
    def known(*values):
        return all(isinstance(value, int) and not isinstance(value, bool) for value in values)

    checks = []
    if kind == "receipt":
        items = [item.get("line_total_minor") for item in record.get("items") or []]
        subtotal, tax, tip, total = (record.get(name) for name in ("subtotal_minor", "tax_minor", "tip_minor", "total_minor"))
        if items and known(subtotal, *items):
            checks.append(sum(items) == subtotal)
        if known(subtotal, total):
            checks.append(subtotal + (tax if known(tax) else 0) + (tip if known(tip) else 0) == total)
    elif kind in ("bank_statement", "credit_card_statement"):
        card = kind == "credit_card_statement"
        amounts = [row.get("amount_minor") for row in record.get("transactions") or []]
        opening = record.get("previous_balance_minor" if card else "opening_balance_minor")
        closing = record.get("statement_balance_minor" if card else "closing_balance_minor")
        if known(opening, closing, *amounts):
            checks.append((opening - sum(amounts) if card else opening + sum(amounts)) == closing)
    elif kind == "paystub":
        lines = record.get("lines") or []
        gross, net = record.get("gross_pay_minor"), record.get("net_pay_minor")
        earnings = [line.get("current_minor") for line in lines if line.get("line_group") == "earnings"]
        taken = [line.get("current_minor") for line in lines if line.get("line_group") in ("pre_tax", "tax", "post_tax")]
        if earnings and known(gross, *earnings):
            checks.append(sum(earnings) == gross)
        if lines and known(gross, net, *taken):
            checks.append(gross - sum(taken) == net)
    return all(checks) if checks else None


def score(grades):
    """A case's share of checked fields and expected rows that came out right, 0 to 1; None when nothing was checked."""
    if grades is None:
        return 0.0
    fields = [field for field in grades["fields"].values() if field["checked"]]
    right, total = sum(1 for field in fields if field["correct"]), len(fields)
    rows = grades["rows"]
    if rows["scored"]:
        # Extra and duplicated rows cost as much as missing ones: the denominator is the larger list.
        right += rows["matched"] - rows["description_errors"]
        total += max(rows["expected"], rows["predicted"])
    return right / total if total else None


def grade(answers, record):
    """Scores for one case. record is the normalized result (None when nothing was read or extracted)."""
    record = record or {}
    kind = answers.document_type
    fields = {}
    for name in CRITICAL[kind]:
        answer = answers.fields[name]
        if answer.state == "unchecked":
            fields[name] = {"checked": False, "correct": None, "error": None}
            continue
        error = compare(name, answer.value, record.get(name))
        fields[name] = {"checked": True, "correct": error is None, "error": error, "state": answer.state}
    key, columns = ROWS[kind]
    rows = {"scored": False}
    if answers.rows_complete and answers.rows is not None:
        predicted = [{name: row.get(name) for name in columns} for row in record.get(key) or []]
        pairs, missing, extra, duplicate = match_rows(kind, answers.rows, predicted)
        description_errors = sum(1 for want, got in pairs if not same_name(want["description"], got.get("description") or ""))
        rows = {"scored": True, "expected": len(answers.rows), "predicted": len(predicted), "matched": len(pairs), "missing": missing,
                "extra": extra, "duplicate": duplicate, "description_errors": description_errors}
    checked = [field for field in fields.values() if field["checked"]]
    fully_checked = len(checked) == len(fields) and rows["scored"]
    perfect = None
    if fully_checked:
        perfect = (all(field["correct"] for field in checked) and rows["matched"] == rows["expected"] == rows["predicted"]
                   and rows["description_errors"] == 0)
    return {"fields": fields, "rows": rows, "document": {"checked_fields": len(checked), "fully_checked": fully_checked, "perfect": perfect},
            "arithmetic": arithmetic(kind, record) if record else None}
