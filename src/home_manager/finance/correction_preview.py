"""What a correction would change, before it is saved (docs/money.md "Corrections").

The correction runs for real inside one write transaction, with the reconciliation pass a save runs, and every figure
it touches is worked out after it; then the transaction rolls back and the same figures are worked out as they stand.
Nothing persists: the traces are built, never remembered (figure_snapshots), and the rollback runs in a finally.
"""

import calendar
import json

from ..core.money import money
from ..core.trace import figure, parse, ref
from .dashboard import SnapshotStore
from .ledger import RECORD_TABLES, Ledger
from .reconcile import Reconciler
from .tools import last_day, month_index
from .traces import build_for

TAX_NOTE = "Taxes for {year} are worked out again from your pay stubs."


def month_name(month):
    year, number = month.split("-")
    return f"{calendar.month_name[int(number)]} {year}"


def _period(month, currency):
    return {"start": month + "-01", "end": last_day(month_index(month)), "currency": currency}


def _state(ledger, db, record_type, record_id):
    """What the preview compares: the record's review state, issues, matches and correctable values, and the months,
    categories and accounts its figures depend on."""
    row = db.execute(f"SELECT * FROM {RECORD_TABLES[record_type]} WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise ValueError("Financial record not found.")
    state = {"row": dict(row), "issues": json.loads(row["validation_json"]) if "validation_json" in row.keys() and row["validation_json"] else [],
             "links": ledger.links(db, record_type, record_id) if record_type in ("receipt", "transaction") else None,
             "correctable": {item["field"]: item for item in ledger.correctable(db, record_type, row)}, "refs": []}
    currency = row["currency"]
    if record_type == "receipt":
        months = {row["purchase_date"][:7]} if row["purchase_date"] else set()
        months |= {link["counterpart"]["date"][:7] for link in state["links"] if link["counterpart"] and link["counterpart"]["date"]}
        categories = {split[0] for split in db.execute("SELECT DISTINCT category FROM category_splits WHERE receipt_id=?", (record_id,))}
        categories |= {row["category"]} if row["category"] else set()
        for month in sorted(months):
            state["refs"] += [ref("spending.net", **_period(month, currency)), ref("cashflow.net", **_period(month, currency))]
            state["refs"] += [ref("spending.category", **_period(month, currency), category=category) for category in sorted(categories)]
        state["refs"].append(ref("split.receipt", receipt_id=record_id))
        state["refs"] += [ref("split.charge", transaction_id=link["counterpart"]["id"]) for link in state["links"] if link["counterpart"]]
    elif record_type == "transaction":
        month = row["posted_date"][:7]
        categories = {split[0] for split in db.execute("SELECT DISTINCT category FROM category_splits WHERE transaction_id=?", (record_id,))}
        categories |= {row["category"]} if row["category"] else set()
        state["refs"] += [ref(name, **_period(month, currency)) for name in ("spending.net", "cashflow.net", "cashflow.in")]
        state["refs"] += [ref("spending.category", **_period(month, currency), category=category) for category in sorted(categories)]
        if any(link["kind"] == "receipt" for link in state["links"]):
            state["refs"].append(ref("split.charge", transaction_id=record_id))
    elif record_type == "income_record" and row["pay_date"]:
        # A pay stub counts as money in until its deposit replaces it (docs/money.md "Money in and paystubs").
        state["refs"] += [ref(name, **_period(row["pay_date"][:7], currency)) for name in ("cashflow.in", "cashflow.net")]
    elif record_type == "statement":
        state["refs"].append(ref("account.balance", account_id=row["account_id"]))
        state["refs"] += [ref("worth.today", figure=name, currency=currency, history_months=3) for name in ("cash", "net_worth")]
    return state


def _label(db, ref_text):
    name, params = parse(ref_text)
    month = params.get("start", "")[:7]
    if name == "spending.net":
        return f"Spending in {month_name(month)}"
    if name == "cashflow.net":
        return f"Cash flow in {month_name(month)}"
    if name == "cashflow.in":
        return f"Money in during {month_name(month)}"
    if name == "spending.category":
        return f"{params['category'].capitalize()} in {month_name(month)}"
    if name == "split.receipt":
        return "This receipt by category"
    if name == "split.charge":
        return "The matched charge by category"
    if name == "account.balance":
        row = db.execute("SELECT display_name FROM accounts WHERE id=?", (int(params["account_id"]),)).fetchone()
        return f"{row[0] if row else 'Account'} balance"
    return {"cash": "Cash across accounts", "net_worth": "Net worth"}.get(params.get("figure"), name)


def _values(store, refs):
    """Each ref's result (money), or None when there's nothing to work out (a ValueError)."""
    found = {}
    for ref_text in refs:
        try:
            found[ref_text] = build_for(store, ref_text)["result"]
        except ValueError:
            found[ref_text] = None
    return found


def _matches(links):
    return [{"kind": link["kind"], "counterpart": link["counterpart"]} for link in links or []]


def _match_keys(links):
    return {(link["kind"], (link["counterpart"] or {}).get("record_type"), (link["counterpart"] or {}).get("id")) for link in links or []}


def preview(store, record_type, record_id, changes):
    """What saving changes on this record would change: the fields, the figures that move, matches, review and issues."""
    if record_type not in RECORD_TABLES:
        raise ValueError("Unknown financial record type.")
    with store.connection() as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            snap = SnapshotStore(store, db)
            ledger = Ledger(snap)
            before = _state(ledger, db, record_type, record_id)
            db.execute("SAVEPOINT correction_preview")
            if record_type == "transaction":
                ledger.correct_transaction(record_id, changes)
            else:
                ledger.correct(record_type, record_id, changes)
            Reconciler(snap).run("correction")
            after = _state(ledger, db, record_type, record_id)
            refs = list(dict.fromkeys(before["refs"] + after["refs"]))
            after_values = _values(snap, refs)
            db.execute("ROLLBACK TO correction_preview")
            before_values = _values(snap, refs)
            labels = {ref_text: _label(db, ref_text) for ref_text in refs}
        finally:
            db.rollback()
    figures, unchanged = [], 0
    for ref_text in refs:
        old, new = before_values[ref_text], after_values[ref_text]
        if old == new:
            unchanged += old is not None
            continue
        same_currency = old is not None and new is not None and old["currency"] == new["currency"]
        figures.append({"ref": ref_text, "label": labels[ref_text],
                        "before": figure(old["minor"], old["currency"], ref_text) if old else None,
                        "after": money(new["minor"], new["currency"]) if new else None,
                        "difference": money(new["minor"] - old["minor"], new["currency"]) if same_currency else None, "changed": True})
    shown = [{"field": field, "label": before["correctable"][field]["label"], "kind": before["correctable"][field]["kind"],
              "from": before["correctable"][field]["value"], "to": after["correctable"][field]["value"]} for field in changes if field in before["correctable"]]
    old_status, new_status = before["row"]["review_status"], after["row"]["review_status"]
    notes = []
    if record_type == "receipt" and "document_kind" in changes:
        notes.append("Invoice details, items and payment matches are kept. This changes the financial record's Bill label; the library folder stays as filed.")
        if changes["document_kind"] == "receipt":
            notes.append("The existing counting date becomes the purchase date. Check Purchase date after saving and correct it if needed.")
    if record_type == "income_record":
        pay_date = after["row"]["pay_date"] or before["row"]["pay_date"]
        notes.append(TAX_NOTE.format(year=pay_date[:4] if pay_date else "the year"))
    matching = None
    if before["links"] is not None:
        matching = {"before": _matches(before["links"]), "after": _matches(after["links"]),
                    "changed": _match_keys(before["links"]) != _match_keys(after["links"])}
    return {"record_type": record_type, "record_id": record_id, "changes": shown, "figures": figures, "unchanged_count": unchanged,
            "matching": matching,
            "review": {"before": old_status, "after": new_status,
                       "automatic": new_status != old_status and after["row"].get("review_source") == "automatic"},
            "issues": {"resolved": [issue for issue in before["issues"] if issue not in after["issues"]], "remaining": after["issues"]},
            "notes": notes}
