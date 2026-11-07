"""Deterministic grading of one model result against one case's checked answers. No model judges anything here.

Only checked fields are scored; an unchecked field is never counted right or wrong. Rows are scored only when someone
confirmed the list complete. Rows match as a multiset, so two identical lattes are two rows, and a third is a duplicate.
Every mismatch gets one error category from a fixed list, so reports carry no values.
"""

from collections import Counter
from datetime import date
from decimal import Decimal
import re

from home_manager.core.answers import CRITICAL, ROWS, kind_of
from home_manager.finance import paystub_tables

# The kinds of guess the pay engine and Record record on a pay stub (FR-74), the only names the summary may hold for them.
GUESS_KINDS = (paystub_tables.HEADINGS_OVERRULED, paystub_tables.COLUMNS_GUESSED, paystub_tables.GROUP_GUESSED, paystub_tables.BOX_COLUMNS_GUESSED,
               paystub_tables.SPLIT_CHANGED)
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
    elif kind == "bill":  # The lines make up the new charges (docs/money.md "Bills and their lines").
        lines = [item.get("line_total_minor") for item in record.get("items") or []]
        if lines and known(record.get("total_minor"), *lines):
            checks.append(sum(lines) == record["total_minor"])
    return all(checks) if checks else None


def table_reader(answers, rebuild, unplaced=None, failed=False):
    """How one table reader did on a text-PDF statement (specs/pdf-table-engine FR-34). `rebuild` is the reader's `Rebuild`: its rows are
    in the order printed, with posted_date and a signed amount_minor (money out negative, for a card statement too). Counts only, no values.

    rows       the printed rows the donor confirmed (the answers' row list)
    recorded   the rows the reader recorded
    exact      printed rows recorded with exactly the right date and signed amount (so the right direction); a repeated row counts once each
    reconciled whether the recorded rows take the answers' opening balance to the answers' closing one (a card statement's previous
               balance to its new balance); None when either balance is not among the checked answers
    dropped    what the reader itself counted as read but not recorded (rejected rows, undated rows, and the engine's unplaced lines). The old
               reader counts no line it never took for a row, so this is not comparable between the two readers
    unplaced   printed lines the engine found no column for and listed (None for the old reader, which names none)
    failed     the reader raised, so it recorded nothing
    """
    expected = Counter((row["posted_date"], row["amount_minor"]) for row in answers.rows)
    recorded = [] if failed else rebuild.rows
    exact = sum((expected & Counter((row["posted_date"], row["amount_minor"]) for row in recorded)).values())
    card = answers.document_type == "credit_card_statement"
    names = ("previous_balance_minor", "statement_balance_minor") if card else ("opening_balance_minor", "closing_balance_minor")
    opening, closing = (answers.fields[name].value if answers.fields[name].state != "unchecked" else None for name in names)
    reconciled = None
    if isinstance(opening, int) and isinstance(closing, int):
        moved = sum(row["amount_minor"] for row in recorded)
        reconciled = not failed and (opening - moved if card else opening + moved) == closing
    return {"rows": len(answers.rows), "recorded": len(recorded), "exact": exact, "reconciled": reconciled,
            "dropped": 0 if failed else rebuild.dropped, "unplaced": unplaced, "failed": failed}


def label_key(text):
    return " ".join((text or "").casefold().split())


def pay_reader(stubs, rows, split_right, unplaced=None, failed=False):
    """How the pay engine did on a text-PDF pay stub file (specs/pdf-table-engine-paystubs FR-71). `stubs` is the answers of each pay stub in file
    order (Case.stubs); `rows` is what the engine placed, in the order printed: (label, this period, year to date) in minor units, a value None
    where it had no cell for it; `split_right` is whether its parts are the file's stubs (`split_is_right`). Counts only, no values.

    Each answer line (in file order) takes the first unused row with the same label, ignoring case and spacing; taxes and deductions are
    compared by magnitude, as the answers keep them.

    stubs      pay stubs the file holds (the answers)
    values     the answers' this-period and year-to-date values (a blank cell is no value)
    exact      values the engine placed exactly right
    left_out   values the engine placed nowhere: no row with the label, or no value in its cell
    checkable  stubs whose answers include gross and net pay, so their lines can be added up
    checks_held checkable stubs whose every this-period value was placed and add up to the answers' gross and net pay
    unplaced   printed lines the engine found no column for and listed
    split_right 1 when the engine made as many parts as the file has stubs, each holding its stub's net pay amount; else 0
    failed     the engine raised, so it placed nothing
    """
    unused = [] if failed else list(rows)
    out = {"stubs": len(stubs), "values": 0, "exact": 0, "left_out": 0, "checkable": 0, "checks_held": 0, "unplaced": unplaced,
           "split_right": int(bool(split_right) and not failed), "failed": failed}
    for answers in stubs:
        sums, complete = {"gross": Decimal(0), "taken": Decimal(0)}, True
        for line in answers.rows or []:
            found = next((row for row in unused if label_key(row[0]) == label_key(line["description"])), None)
            if found is not None:
                unused.remove(found)
            group = line["line_group"]
            for column, value in (("current", line["current_minor"]), ("ytd", line["ytd_minor"])):
                if value is None:
                    continue
                got = None if found is None else found[1 if column == "current" else 2]
                got = got if got is None or group == "earnings" else abs(got)
                out["values"] += 1
                if got is None:
                    out["left_out"] += 1
                    if column == "current":
                        complete = False
                else:
                    out["exact"] += got == value
                    if column == "current":
                        if group == "earnings":
                            sums["gross"] += got
                        elif group != "employer_paid":
                            sums["taken"] += got
        gross, net = (answers.fields[name].value if answers.fields[name].state != "unchecked" else None for name in ("gross_pay_minor", "net_pay_minor"))
        if isinstance(gross, int) and isinstance(net, int):
            out["checkable"] += 1
            out["checks_held"] += complete and sums["gross"] == gross and sums["gross"] - sums["taken"] == net
    return out


def split_is_right(stubs, parts):
    """Whether a reader's parts are the file's stubs: as many parts as stubs, and part k's printed amounts include stub k's net pay. `parts` is
    the list of each part's amounts as minor units (sets)."""
    nets = [stub.fields["net_pay_minor"].value if stub.fields["net_pay_minor"].state != "unchecked" else None for stub in stubs]
    return len(parts) == len(stubs) and all(net is None or net in amounts for net, amounts in zip(nets, parts))


def values_right(grades):
    """Whether every money value of a stub came out right: its pay lines found once each with the right group, this period and year to date,
    and every checked money field. None when its rows were not confirmed complete, so nothing can be said (the guess goes unjudged)."""
    if grades is None or not grades["rows"]["scored"]:
        return None
    rows = grades["rows"]
    return (rows["matched"] == rows["expected"] == rows["predicted"]
            and all(field["correct"] for name, field in grades["fields"].items() if field["checked"] and name.endswith("_minor")))


def merge_grades(parts):
    """One grades dict for a file of several pay stubs: a field is right when it is right in every stub that checked it, rows and counts add up,
    and the file is perfect only when every stub is."""
    fields = {}
    for name in parts[0]["fields"]:
        checked = [part["fields"][name] for part in parts if part["fields"][name]["checked"]]
        fields[name] = ({"checked": False, "correct": None, "error": None} if not checked else
                        {"checked": True, "correct": all(field["correct"] for field in checked),
                         "error": next((field["error"] for field in checked if field["error"]), None),
                         "state": "fixed" if any(field["state"] == "fixed" for field in checked) else "correct"})
    scored = all(part["rows"]["scored"] for part in parts)
    rows = ({"scored": True, **{key: sum(part["rows"][key] for part in parts) for key in ("expected", "predicted", "matched", "missing", "extra", "duplicate",
                                                                                              "description_errors")}} if scored else {"scored": False})
    fully = all(part["document"]["fully_checked"] for part in parts)
    perfect = all(part["document"]["perfect"] for part in parts) if fully else None
    checks = [part["arithmetic"] for part in parts if part["arithmetic"] is not None]
    return {"fields": fields, "rows": rows, "document": {"checked_fields": sum(1 for field in fields.values() if field["checked"]),
                                                          "fully_checked": fully, "perfect": perfect}, "arithmetic": all(checks) if checks else None}


def grade_stubs(stubs, records):
    """(grades, per-stub grades) of a pay stub file's records against its stubs' answers, in order. A different number of records than stubs is a
    split miss (the file was split wrong): the case is graded as if nothing was read, and no stub is judged on its own (per-stub is None)."""
    if len(records) != len(stubs):
        return grade(stubs[0], None), None
    each = [grade(answers, record) for answers, record in zip(stubs, records)]
    return (each[0] if len(each) == 1 else merge_grades(each)), each


def guess_counts(records, each):
    """{kind: {"made": n, "right": n}} of the guesses recorded on a pay stub file's records (details.guesses, FR-74). A guess is right when the
    values it chose equal the answers: the stub's money values are all right (`values_right`). Guesses on a stub that cannot be judged (no
    per-stub grades, or its rows not confirmed complete) are not counted. Kinds are the engine's fixed list, so nothing else is recorded."""
    counts = {}
    for record, grades in zip(records, each or []):
        right = values_right(grades)
        if right is None:
            continue
        for guess in ((record or {}).get("details") or {}).get("guesses") or []:
            if guess.get("kind") in GUESS_KINDS:
                entry = counts.setdefault(guess["kind"], {"made": 0, "right": 0})
                entry["made"] += 1
                entry["right"] += right
    return counts


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
