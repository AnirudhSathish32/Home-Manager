"""Family corrections (docs/family.md "Family corrections"): a change made in the family ledger to a member's record.

The family checks the value with the same rules a person's own correction uses, keeps a 'sent' row in its own library
(family_corrections, migration 062) and sends the member a delivery. Until the member's next copy says what happened, the
family's view copies show the new value, tagged "Waiting for <member>".

On the member's computer the delivery applies once per key:
- the field still reads what the family saw (previous): it is corrected, as a record_corrections row whose actor is
  "Family · <who>", with the reason "Family correction";
- it already reads the new value: nothing changes, and it counts as applied;
- anything else (the member changed it since): it becomes a Review question, "Keep mine" or "Use family's".
The member can reject an applied correction from the record's history: the previous value goes back, under their own
name, and the family isn't told; the record simply reverts in the family view when their next copy arrives.
"""

from datetime import date
import json

from ..core import actor
from ..core.categories import receipt_category
from ..core.money import money, to_minor
from ..library.storage import now
from .ledger import CORRECTABLE, TRANSACTION_CORRECTABLE, TRANSACTION_TYPES, Ledger, category_name, normalize_name, receipt_direction

REASON = "Family correction"
RECORD_TYPES = ("transaction", "receipt", "bill", "income_record", "statement")
TABLES = {"transaction": "transactions", "receipt": "receipts", "bill": "bills", "income_record": "income_records", "statement": "statements"}


def field_kind(record_type, field):
    """The kind of value a field holds, or ValueError when the family can't correct it."""
    if record_type == "transaction":
        if field == "category":
            return "transaction_category"
        if field in TRANSACTION_CORRECTABLE:
            return TRANSACTION_CORRECTABLE[field][1]
    elif field in CORRECTABLE.get(record_type, {}):
        return CORRECTABLE[record_type][field][1]
    raise ValueError(f"The family can't correct a {record_type.replace('_', ' ')}'s {field.replace('_', ' ')}.")


def _row(db, record_type, record_id):
    if record_type not in TABLES:
        raise ValueError("Unknown financial record type.")
    row = db.execute(f"SELECT * FROM {TABLES[record_type]} WHERE id=?", (record_id,)).fetchone()
    if row is None:
        raise ValueError("Financial record not found.")
    return row


def current_text(db, record_type, record_id, field):
    """A field as the record reads now, as text in the form corrections store (a merchant's name, a decimal amount)."""
    row, kind = _row(db, record_type, record_id), field_kind(record_type, field)
    if kind == "transaction_category":
        return row["category"]
    if record_type == "transaction":
        return Ledger(None)._transaction_text(db, row, field)
    column = CORRECTABLE[record_type][field][0]
    if kind == "name":
        return Ledger._merchant_name(db, row[column])
    if kind == "money":
        return money(row[column], row["currency"])["decimal"] if row[column] is not None else None
    if kind == "sale_type":
        return receipt_direction(row)
    return row[column]


def checked_value(db, record_type, record_id, field, value):
    """The value as corrections store it, checked with a person's own correction's rules, without writing anything
    (the family checks against a member's read-only copy)."""
    row, kind = _row(db, record_type, record_id), field_kind(record_type, field)
    text = " ".join(str(value).split()) if value is not None else None
    if kind == "transaction_category":
        return category_name(text) if text else None
    if not text:
        if kind in ("text", "category") and record_type != "transaction":
            return None
        raise ValueError(f"Enter the {field.replace('_', ' ')}.")
    if kind == "name":
        if len(text) > 120 or not normalize_name(text):
            raise ValueError("Enter a business name of up to 120 characters, with letters or digits.")
        return text
    if kind == "date":
        try:
            if len(text) != 10:
                raise ValueError
            date.fromisoformat(text)
        except ValueError:
            raise ValueError(f"Enter the {field.replace('_', ' ')} as a full date (YYYY-MM-DD).") from None
        return text
    if kind == "money":
        return money(to_minor(text, row["currency"]), row["currency"])["decimal"]
    if kind == "amount":
        minor = to_minor(text, row["currency"])
        if minor <= 0:
            raise ValueError("Enter the amount as a positive number; its direction is corrected separately.")
        return money(minor, row["currency"])["decimal"]
    if kind == "direction":
        if text not in ("out", "in"):
            raise ValueError("Choose money out or money in.")
        return text
    if kind == "sale_type":
        if text not in ("sale", "return"):
            raise ValueError("Choose sale or return.")
        return text
    if kind == "type":
        if text not in TRANSACTION_TYPES:
            raise ValueError("Choose a type: " + ", ".join(TRANSACTION_TYPES) + ".")
        return text
    if kind == "category":
        return receipt_category(text)
    if len(text) > 60:
        raise ValueError(f"Keep the {field.replace('_', ' ')} to 60 characters or fewer.")
    return text


def same(record_type, field, first, second):
    """Whether two stored texts say the same thing (merchant names compare as merchant keys)."""
    if first is None or second is None:
        return first is None and second is None
    if field_kind(record_type, field) == "name":
        return normalize_name(first) == normalize_name(second)
    return str(first) == str(second)


def apply_to_view(db, record_type, record_id, field, value):
    """Show a pending correction in the family's own view copy of the member's records (never the member's library)."""
    row, kind = _row(db, record_type, record_id), field_kind(record_type, field)
    ledger = Ledger(None)
    if kind == "transaction_category":
        db.execute("UPDATE transactions SET category=?,category_source=? WHERE id=?", (value, "user" if value else None, record_id))
        return
    if record_type == "transaction":
        column = TRANSACTION_CORRECTABLE[field][0]
        stored, _ = ledger._transaction_value(db, row, field, value)
    else:
        column, kind, _ = CORRECTABLE[record_type][field]
        stored, _ = ledger._correction_value(db, kind, field, value, stored=True, currency=row["currency"])
        if kind == "sale_type":
            ledger.set_receipt_direction(db, record_id, stored)
            return
    db.execute(f"UPDATE {TABLES[record_type]} SET {column}=? WHERE id=?", (stored, record_id))


# Member side ---------------------------------------------------------------------------

def _correct(store, record_type, record_id, field, value, person):
    """Correct one field through the ledger, as `person`. Returns the record_corrections row it wrote."""
    ledger = Ledger(store)
    with actor.acting_as(person):
        if field == "category" and record_type == "transaction":
            ledger.set_category(record_id, value)
        elif record_type == "transaction":
            ledger.correct_transaction(record_id, {field: value}, REASON)
        else:
            ledger.correct(record_type, record_id, {field: value}, REASON)
    with store.connection() as db:
        found = db.execute("SELECT max(id) FROM record_corrections WHERE record_type=? AND record_id=? AND field=?",
                           (record_type, record_id, field)).fetchone()
    return found[0] if found else None


def apply_correction(store, delivery):
    """Apply one correction the family sent, once per key. Returns its status: applied, conflict or rejected (a record
    that no longer exists, or a value this library refuses)."""
    key, record_type, record_id, field = delivery["key"], delivery["record_type"], int(delivery["record_id"]), delivery["field"]
    with store.connection() as db:
        known = db.execute("SELECT status FROM family_corrections WHERE key=?", (key,)).fetchone()
        if known:
            return known[0]
        try:
            current = current_text(db, record_type, record_id, field)
            value = checked_value(db, record_type, record_id, field, delivery.get("value"))
        except ValueError:
            current = value = None
            status = "rejected"
        else:
            status = "applied" if same(record_type, field, current, value) else \
                "pending" if same(record_type, field, current, delivery.get("previous")) else "conflict"
    who = f"Family · {delivery.get('actor') or 'family'}"
    correction_id = None
    if status == "pending":
        correction_id = _correct(store, record_type, record_id, field, value, who)
        status = "applied"
    with store.connection() as db:
        db.execute("INSERT INTO family_corrections(key,direction,member_id,record_type,record_id,field,value,previous,actor,correction_id,status,"
                   "created_at,updated_at) VALUES(?,'received',?,?,?,?,?,?,?,?,?,?,?)",
                   (key, delivery.get("member_id") or "", record_type, record_id, field, value if value is not None else delivery.get("value"),
                    delivery.get("previous"), who, correction_id, status, now(), now()))
        if status == "conflict":  # A reconciliation question like the others, so Review lists it.
            _ask(db, record_type, record_id, {"key": key, "field": field, "value": value, "previous": delivery.get("previous"),
                                              "current": current, "actor": who})
    return status


def _ask(db, record_type, record_id, correction):
    """Raise (or add to) the record's family_correction question: one per record, listing each conflicting correction."""
    issue = db.execute("SELECT id,detail_json,status FROM reconciliation_issues WHERE issue_type='family_correction' AND record_type=? AND record_id=?",
                       (record_type, record_id)).fetchone()
    detail = json.loads(issue["detail_json"]) if issue and issue["status"] == "open" else {"candidate_transaction_ids": [], "corrections": []}
    detail["corrections"] = [item for item in detail["corrections"] if item["field"] != correction["field"]] + [correction]
    db.execute("INSERT INTO reconciliation_issues(issue_type,record_type,record_id,detail_json,status,created_at,updated_at) "
               "VALUES('family_correction',?,?,?,'open',?,?) ON CONFLICT(issue_type,record_type,record_id) DO UPDATE SET "
               "detail_json=excluded.detail_json,status='open',resolution=NULL,updated_at=excluded.updated_at",
               (record_type, record_id, json.dumps(detail), now(), now()))


def resolve_conflict(store, issue_id, take_family):
    """Answer a family_correction question: "Use family's" applies each listed correction under the family's name;
    "Keep mine" leaves the record and marks them rejected. Either way the family learns it from the next copy."""
    with store.connection() as db:
        issue = db.execute("SELECT * FROM reconciliation_issues WHERE id=?", (issue_id,)).fetchone()
        if issue is None or issue["issue_type"] != "family_correction":
            raise ValueError("Family question not found.")
        if issue["status"] != "open":
            raise ValueError("This question was already answered.")
        corrections = json.loads(issue["detail_json"])["corrections"]
    for item in corrections:
        correction_id = _correct(store, issue["record_type"], issue["record_id"], item["field"], item["value"], item["actor"]) if take_family else None
        with store.connection() as db:
            db.execute("UPDATE family_corrections SET status=?,correction_id=coalesce(?,correction_id),updated_at=? WHERE key=? AND direction='received'",
                       ("applied" if take_family else "rejected", correction_id, now(), item["key"]))
    resolution = "took_family" if take_family else "kept_mine"
    with store.connection() as db:
        db.execute("UPDATE reconciliation_issues SET status='resolved',resolution=?,updated_at=? WHERE id=?", (resolution, now(), issue_id))
        db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at,actor) VALUES('reconciliation_issue',?,'open',?,?,?,?)",
                   (issue_id, resolution, "Family correction", now(), actor.current()))
    return {"id": issue_id, "resolution": resolution}


def reject_correction(store, key):
    """The member undoes a family correction: the previous value goes back under their own name. The family isn't told;
    their next copy shows the record as it is."""
    with store.connection() as db:
        row = db.execute("SELECT * FROM family_corrections WHERE key=? AND direction='received'", (key,)).fetchone()
    if row is None:
        raise ValueError("Family correction not found.")
    if row["status"] != "applied":
        raise ValueError("Only a correction the family made here can be rejected.")
    ledger = Ledger(store)
    if row["field"] == "category" and row["record_type"] == "transaction":
        ledger.set_category(row["record_id"], row["previous"])
    elif row["record_type"] == "transaction":
        ledger.correct_transaction(row["record_id"], {row["field"]: row["previous"]}, "Rejected a family correction")
    else:
        ledger.correct(row["record_type"], row["record_id"], {row["field"]: row["previous"]}, "Rejected a family correction")
    with store.connection() as db:
        db.execute("UPDATE family_corrections SET status='rejected',updated_at=? WHERE key=?", (now(), key))
    return {"key": key, "status": "rejected"}


