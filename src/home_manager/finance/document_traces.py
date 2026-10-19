"""Traces of the arithmetic checks document forms add (specs/document-forms FR-19; docs/ui.md "Trace contract").

Each check is one function in finance/document_checks.py. A record's `checks` (Ledger.record) and the trace behind each
are the same call: with the NULL recorder for the figure, and with a live one here for its breakdown. So the page does
no arithmetic, and a trace's result is the figure shown.

The trace contract's one exception: for these figures `reconciles` is the check's outcome, the result compared with
the printed amount (`compared_with`), not whether the steps add up to the result. A product (volume × price, hours ×
rate, count × unit price) is one step at its rounded value, with the exact product in its rounding note.

Inputs keep their provenance: `extracted`, with the document, cited lines and quote, or `override`, with the value the
reading had and who corrected it, when a person corrected it.
"""

import json

from ..core.money import money
from ..core.trace import NULL, Recorder, build, figure, ref
from . import document_checks
from .provenance import verification_of

NOT_WORKED_OUT = "This isn't worked out for this record."
UNDO_REASON = "Undid a change"


def reading(db, row):
    """The saved result of the reading that wrote this record (its own part of a split file), or {}."""
    found = db.execute("SELECT result_json FROM extraction_runs WHERE id=?", (row["extraction_run_id"],)).fetchone() if row["extraction_run_id"] else None
    result = json.loads(found["result_json"]) if found and found["result_json"] else {}
    segments = result.get("segments")
    if segments:
        segment = row["segment"] if "segment" in row.keys() else 0
        return segments[segment] if segment < len(segments) else {}
    return result


def provenance(db, record_type, row, field, locator=None, result=None):
    """Where one input came from: a person's correction of `field` (override, with the reading's own value), else the
    reading (extracted: the document, its cited lines and quote; locator, or the reading's citation of the field)."""
    corrections = db.execute("SELECT previous,value,reason,actor FROM record_corrections WHERE record_type=? AND record_id=? AND field=? ORDER BY id",
                             (record_type, row["id"], field)).fetchall() if field else []
    if corrections and not (corrections[-1]["reason"] == UNDO_REASON and corrections[-1]["value"] == corrections[0]["previous"]):
        latest = corrections[-1]
        return {"kind": "override", "record": {"type": record_type, "id": row["id"]}, "original": corrections[0]["previous"], "value": latest["value"],
                "reason": latest["reason"], "actor": latest["actor"]}
    if locator is None:
        evidence = ((result or {}).get("header") or {}).get(field.removeprefix("detail:") if field else "", {}) or {}
        locator = {"line_ids": [cite["line_id"] for cite in evidence.get("evidence", [])], "quotes": [cite["quote"] for cite in evidence.get("evidence", [])]}
    return {"kind": "extracted", "record": {"type": record_type, "id": row["id"]}, "document_id": row["document_id"],
            "line_ids": locator.get("line_ids", []), "quote": (locator.get("quotes") or [None])[0]}


def current(row):
    """A receipt's details for the kind it is read as now."""
    if "receipt_kind" in row.keys():
        if not row["details_json"] or not row["receipt_kind"]:
            return {}
        return json.loads(row["details_json"]).get(row["receipt_kind"]) or {}
    return json.loads(row["details_json"]) if row["details_json"] else {}


def decimal(minor, currency):
    return money(abs(minor), currency)["decimal"]


# Each check: {name, label, ref, check (the document_checks function), args, inputs, formula}. An input is
# ("money", key, label, minor, provenance) or ("text", key, label, text, unit, provenance).

def receipt_checks(db, row):
    details, currency = current(row), row["currency"]
    if row["document_kind"] == "bill" or not row["receipt_kind"]:
        return []
    found, result = [], reading(db, row)

    def detail(name):
        return provenance(db, "receipt", row, f"detail:{name}", details[name]["locator"])
    if row["receipt_kind"] == "fuel" and all(details.get(name) for name in ("volume", "price_per_unit", "fuel_amount")) and details["volume"].get("unit") \
            and details["fuel_amount"].get("minor") is not None:
        volume, price, amount = details["volume"], details["price_per_unit"], details["fuel_amount"]
        found.append({"name": "fuel", "label": "Fuel: volume × price per unit", "ref": ref("receipt.fuel", receipt_id=row["id"]),
                      "check": document_checks.fuel, "args": (volume["text"], price["text"], amount["minor"]),
                      "inputs": [("text", "volume", "Volume", volume["text"], volume["unit"], detail("volume")),
                                 ("text", "price_per_unit", "Price per unit", price["text"], volume["unit"] and f"per {volume['unit']}", detail("price_per_unit")),
                                 ("money", "fuel_amount", "Fuel amount", amount["minor"], detail("fuel_amount"))],
                      "formula": "The volume times the price per unit, rounded half-up to the cent, against the printed fuel amount (within a cent)."})
    if row["receipt_kind"] == "dining" and None not in (row["subtotal_minor"], row["tax_minor"], row["total_minor"]):
        gratuity = (details.get("gratuity") or {}).get("minor")
        inputs = [("money", name, label, row[f"{name}_minor"], provenance(db, "receipt", row, name, result=result))
                  for name, label in (("subtotal", "Subtotal"), ("tax", "Tax"), ("total", "Total")) if row[f"{name}_minor"] is not None]
        if row["tip_minor"] is not None:
            inputs.append(("money", "tip", "Tip", row["tip_minor"], provenance(db, "receipt", row, "tip", result=result)))
        if gratuity is not None:
            inputs.append(("money", "gratuity", "Gratuity", gratuity, detail("gratuity")))
        found.append({"name": "dining", "label": "Subtotal, tax, gratuity and tip", "ref": ref("receipt.dining", receipt_id=row["id"]),
                      "check": document_checks.dining, "args": (row["subtotal_minor"], row["tax_minor"], row["tip_minor"], gratuity, row["total_minor"]),
                      "inputs": inputs, "formula": "Subtotal plus tax plus an included gratuity plus the tip, against the printed total. A tip that "
                                                   "isn't printed adds nothing."})
    if row["receipt_kind"] == "grocery":
        for item in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? AND review_status<>'rejected' ORDER BY position", (row["id"],)):
            if not item["quantity"] or item["unit_price_minor"] is None or item["line_total_minor"] is None:
                continue
            evidence = db.execute("SELECT locator_json FROM financial_evidence_links WHERE record_type='receipt_item' AND record_id=? ORDER BY id LIMIT 1",
                                  (item["id"],)).fetchone()
            locator = json.loads(evidence["locator_json"]) if evidence else {}
            unit_price = decimal(item["unit_price_minor"], currency)
            found.append({"name": f"unit_line:{item['position']}", "label": f"{item['description']}: count × unit price",
                          "ref": ref("receipt.unit_line", receipt_id=row["id"], position=item["position"]), "check": document_checks.unit_line,
                          "args": (item["quantity"], unit_price, item["line_total_minor"]),
                          "inputs": [("text", "count", "Count", item["quantity"], None, provenance(db, "receipt", row, None, locator)),
                                     ("money", "unit_price", "Unit price", item["unit_price_minor"], provenance(db, "receipt", row, None, locator)),
                                     ("money", "line_total", "Line total", item["line_total_minor"],
                                      provenance(db, "receipt_item", row, f"price:{item['position']}", locator))],
                          "formula": "The printed count times the unit price, rounded half-up to the cent, against the line total (within a cent)."})
    tenders = details.get("tenders") or []
    gifts = [(number, tender) for number, tender in enumerate(tenders, 1) if tender.get("tender_type") == "gift_card" and tender.get("minor")]
    printed = row["printed_total_minor"] if row["printed_total_minor"] is not None else (abs(row["total_minor"]) if row["total_minor"] is not None else None)
    if gifts and printed is not None:
        others = [tender["minor"] for tender in tenders if tender.get("tender_type") != "gift_card" and tender.get("minor") is not None]
        inputs = [("money", "total", "Total", printed, provenance(db, "receipt", row, "total", result=result))]
        inputs += [("money", f"gift_card:{number}", "Gift card", tender["minor"],
                    provenance(db, "receipt", row, f"detail:tenders.{number}.amount", tender["locator"])) for number, tender in gifts]
        inputs += [("money", f"tender:{number}", tender.get("tender_type", "other").replace("_", " ").capitalize(), tender["minor"],
                    provenance(db, "receipt", row, f"detail:tenders.{number}.amount", tender["locator"]))
                   for number, tender in enumerate(tenders, 1) if tender.get("tender_type") != "gift_card" and tender.get("minor") is not None]
        found.append({"name": "paid", "label": "Amount paid after gift cards", "ref": ref("receipt.paid", receipt_id=row["id"]),
                      "check": document_checks.amount_paid, "args": (printed, [tender["minor"] for _, tender in gifts], sum(others) if others else None),
                      "inputs": inputs, "formula": "The printed total less its gift card deductions: what was paid, and what counts. Compared with the "
                                                   "other payments printed, when there are any."})
    return found


def income_checks(db, row):
    details, found = current(row), []
    for line in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY position", (row["id"],)):
        line_details = json.loads(line["details_json"]) if line["details_json"] else {}
        hours, rate = line_details.get("hours"), line_details.get("rate")
        if line["line_group"] != "earnings" or not hours or not rate or line["current_minor"] is None:
            continue
        locator = json.loads(line["locator_json"])
        found.append({"name": f"hours:{line['position']}", "label": f"{line['description']}: hours × rate",
                      "ref": ref("paystub.hours", income_id=row["id"], position=line["position"]), "check": document_checks.hours_rate,
                      "args": (hours["text"], rate["text"], line["current_minor"]),
                      "inputs": [("text", "hours", "Hours", hours["text"], hours.get("unit"), provenance(db, "income_record", row, None, hours["locator"])),
                                 ("text", "rate", "Rate", rate["text"], None, provenance(db, "income_record", row, None, rate["locator"])),
                                 ("money", "amount", "This period", line["current_minor"], provenance(db, "income_record", row, None, locator))],
                      "formula": "The hours times the hourly rate, rounded half-up to the cent, against this period's amount (within a cent)."})
    splits = details.get("deposit_splits") or []
    if splits and all(split.get("minor") is not None for split in splits) and row["net_pay_minor"] is not None:
        inputs = [("money", f"deposit:{number}", f"Deposit to ****{split['last_four']}" if split.get("last_four") else f"Deposit {number}", split["minor"],
                   provenance(db, "income_record", row, None, split["locator"])) for number, split in enumerate(splits, 1)]
        inputs.append(("money", "net_pay", "Net pay", row["net_pay_minor"], provenance(db, "income_record", row, "net_pay", result=reading(db, row))))
        found.append({"name": "deposits", "label": "Direct deposits", "ref": ref("paystub.deposits", income_id=row["id"]),
                      "check": document_checks.deposit_splits, "args": ([split["minor"] for split in splits], row["net_pay_minor"]),
                      "inputs": inputs, "formula": "Each direct deposit added up, against net pay."})
    return found


def statement_checks(db, row):
    details, result = current(row), reading(db, row)
    summary = json.loads(row["summary_json"] or "{}")
    if row["statement_type"] == "bank":
        deposits, withdrawals = ((details.get(name) or {}).get("minor") for name in ("deposits_total", "withdrawals_total"))
        terms = (row["opening_balance_minor"], deposits, withdrawals, row["closing_balance_minor"])
        if None in terms:
            return []
        inputs = [("money", "opening_balance", "Opening balance", terms[0], provenance(db, "statement", row, "opening_balance", result=result)),
                  ("money", "deposits_total", "Deposits", deposits, provenance(db, "statement", row, None, details["deposits_total"]["locator"])),
                  ("money", "withdrawals_total", "Withdrawals", withdrawals, provenance(db, "statement", row, None, details["withdrawals_total"]["locator"])),
                  ("money", "closing_balance", "Closing balance", terms[3], provenance(db, "statement", row, "closing_balance", result=result))]
        return [{"name": "summary", "label": "Opening balance, deposits and withdrawals", "ref": ref("statement.summary", statement_id=row["id"]),
                 "check": document_checks.bank_summary, "args": terms, "inputs": inputs,
                 "formula": "The printed opening balance plus deposits less withdrawals, against the printed closing balance."}]
    names = ("previous_balance", "payments", "credits", "purchases", "fees", "interest", "statement_balance")
    terms = tuple(summary.get(name) for name in names)  # summary_json: the printed summary amounts, by field name.
    if None in terms:
        return []
    inputs = [("money", name, name.replace("_", " ").capitalize(), amount, provenance(db, "statement", row, name, result=result))
              for name, amount in zip(names, terms)]
    return [{"name": "summary", "label": "The statement's printed summary", "ref": ref("statement.summary", statement_id=row["id"]),
             "check": document_checks.card_summary, "args": terms, "inputs": inputs,
             "formula": "The printed previous balance less payments and credits, plus purchases, fees and interest, against the printed "
                        "statement balance."}]


FINDERS = {"receipt": ("receipts", receipt_checks), "income_record": ("income_records", income_checks), "statement": ("statements", statement_checks)}


def checks(db, record_type, row):
    """A record's check figures for its page (Ledger.record): [{name, label, figure, compared_with, passes}], worked out
    with the same functions as the traces."""
    if record_type not in FINDERS:
        return []
    found = []
    for spec in FINDERS[record_type][1](db, row):
        computed, compared, passes = spec["check"](*spec["args"], row["currency"], NULL)
        found.append({"name": spec["name"], "label": spec["label"], "figure": figure(computed, row["currency"], spec["ref"]),
                      "compared_with": money(compared, row["currency"]) if compared is not None else None, "passes": passes})
    return found


def check_trace(store, ref_text, params, record_type, key, name):
    """The trace of one check: its steps, its inputs with their provenance, its rounding, the printed amount it's
    compared with, and reconciles = the check's outcome (FR-19)."""
    try:
        record_id = int(params[key])
    except (KeyError, ValueError):
        raise ValueError(f"The trace needs {key} as a number.") from None
    table, finder = FINDERS[record_type]
    with store.connection() as db:
        row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
        spec = next((spec for spec in finder(db, row) if spec["name"] == name(params)), None) if row is not None else None
        if spec is None:
            raise ValueError(NOT_WORKED_OUT)
        recorder, currency, verification = Recorder(), row["currency"], verification_of(row)
        for kind, input_key, label, *rest in spec["inputs"]:
            if kind == "text":
                recorder.input_text(input_key, label, rest[0], rest[1], rest[2], verification)
            else:
                recorder.input(input_key, label, rest[0], currency, rest[1], verification)
        computed, compared, passes = spec["check"](*spec["args"], currency, recorder)
    trace = build(ref_text, spec["label"], computed, currency, spec["formula"], recorder)
    return {**trace, "compared_with": money(compared, currency) if compared is not None else None, "reconciles": passes}


def position(params):
    try:
        return int(params["position"])
    except (KeyError, ValueError):
        raise ValueError("The trace needs position as a number.") from None


TRACES = {
    "receipt.fuel": lambda store, text, params: check_trace(store, text, params, "receipt", "receipt_id", lambda _: "fuel"),
    "receipt.dining": lambda store, text, params: check_trace(store, text, params, "receipt", "receipt_id", lambda _: "dining"),
    "receipt.unit_line": lambda store, text, params: check_trace(store, text, params, "receipt", "receipt_id", lambda found: f"unit_line:{position(found)}"),
    "receipt.paid": lambda store, text, params: check_trace(store, text, params, "receipt", "receipt_id", lambda _: "paid"),
    "paystub.hours": lambda store, text, params: check_trace(store, text, params, "income_record", "income_id", lambda found: f"hours:{position(found)}"),
    "paystub.deposits": lambda store, text, params: check_trace(store, text, params, "income_record", "income_id", lambda _: "deposits"),
    "statement.summary": lambda store, text, params: check_trace(store, text, params, "statement", "statement_id", lambda _: "summary"),
}
