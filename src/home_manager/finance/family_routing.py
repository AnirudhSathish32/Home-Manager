"""Family inbox: who each document uploaded to a family is for, and how it reaches that person's own library.

A family's own library is a staging area. Its records are never counted in family totals (those come from each
member's library). Every record gets an assignment in family_assignments: one person, or shared by the family.
A shared receipt or bill is divided into equal whole-cent parts among the people chosen (splits.equal_shares), and each
person's library receives the record with their part in record_shares. Statements and pay stubs go to one person.

Owners are only suggested: from the card or account's last four digits when exactly one member has an account ending in
them, and for a pay stub from an employer exactly one member already has pay stubs from. The user confirms each one.
"""

import hashlib
import json
import uuid

from ..core import actor
from ..core.money import money
from ..library.storage import now
from .ledger import Ledger, normalize_name
from .splits import equal_shares

ROUTED = ("receipt", "bill", "statement", "income_record")
SHAREABLE = ("receipt", "bill")
TABLES = {"receipt": "receipts", "bill": "bills", "statement": "statements", "income_record": "income_records"}
ALIASES = {"receipt": "r", "bill": "b", "statement": "s", "income_record": "i"}  # As SUMMARY names each table.
# One row per routable record in the family library: what it is, for the Review list.
SUMMARY = {
    "receipt": "SELECT 'receipt' AS record_type,r.id,r.purchase_date AS date,m.canonical_name AS name,r.total_minor AS amount_minor,r.currency,"
               "r.review_status,r.document_id,r.blob_hash,r.payment_last_four AS last_four FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id",
    "bill": "SELECT 'bill' AS record_type,b.id,coalesce(b.due_date,b.issue_date) AS date,m.canonical_name AS name,b.amount_due_minor AS amount_minor,"
            "b.currency,b.review_status,b.document_id,b.blob_hash,a.account_last_four AS last_four FROM bills b "
            "LEFT JOIN merchants m ON m.id=b.provider_merchant_id LEFT JOIN accounts a ON a.id=b.account_id",
    "statement": "SELECT 'statement' AS record_type,s.id,s.period_end AS date,a.institution AS name,"
                 "coalesce(s.closing_balance_minor,s.statement_balance_minor) AS amount_minor,s.currency,s.review_status,s.document_id,s.blob_hash,"
                 "a.account_last_four AS last_four FROM statements s JOIN accounts a ON a.id=s.account_id",
    "income_record": "SELECT 'income_record' AS record_type,i.id,i.pay_date AS date,m.canonical_name AS name,i.net_pay_minor AS amount_minor,i.currency,"
                     "i.review_status,i.document_id,i.blob_hash,NULL AS last_four FROM income_records i LEFT JOIN merchants m ON m.id=i.payer_merchant_id",
}


def member_facts(members):
    """{member_id: {"last_four": set, "employers": set}} from each member's copy: the clues for suggesting an owner.
    members: [(member dict, store)] such as family.views() opened read-only."""
    facts = {}
    for member, store in members:
        with store.connection() as db:
            last_four = {row[0] for row in db.execute("SELECT account_last_four FROM accounts WHERE account_last_four IS NOT NULL")}
            employers = {normalize_name(row[0]) for row in db.execute(
                "SELECT m.canonical_name FROM income_records i JOIN merchants m ON m.id=i.payer_merchant_id WHERE i.review_status<>'rejected'")}
        facts[member["member_id"]] = {"last_four": last_four, "employers": employers}
    return facts


def suggest(row, facts):
    """(member id, reason) when exactly one member fits, else (None, reason)."""
    if row["last_four"]:
        owners = [member for member, known in facts.items() if row["last_four"] in known["last_four"]]
        if len(owners) == 1:
            return owners[0], f"Paid with a card or account ending {row['last_four']}"
        if owners:
            return None, f"More than one person has an account ending {row['last_four']}"
    if row["record_type"] == "income_record" and row["name"]:
        owners = [member for member, known in facts.items() if normalize_name(row["name"]) in known["employers"]]
        if len(owners) == 1:
            return owners[0], f"Earlier pay stubs from {row['name']}"
    return None, "Nothing on it says whose it is"


class FamilyRouting:
    def __init__(self, store):
        self.store, self.ledger = store, Ledger(store)

    def refresh(self, facts):
        """An assignment row for every routable record, with a suggestion for new ones. Confirmed ones are kept."""
        with self.store.connection() as db:
            for record_type in ROUTED:
                alias = ALIASES[record_type]
                for row in db.execute(SUMMARY[record_type] + f" WHERE {alias}.review_status<>'rejected' AND NOT EXISTS("
                                      f"SELECT 1 FROM family_assignments f WHERE f.record_type='{record_type}' AND f.record_id={alias}.id)").fetchall():
                    member, reason = suggest(dict(row), facts)
                    db.execute("INSERT INTO family_assignments(record_type,record_id,family_record_key,mode,members_json,suggested_json,status,updated_at) "
                               "VALUES(?,?,?,?,?,?,?,?)", (record_type, row["id"], uuid.uuid4().hex, "member" if member else None,
                                                           json.dumps([member] if member else []), json.dumps({"member_id": member, "reason": reason}),
                                                           "suggested" if member else "unassigned", now()))

    def list(self, include_delivered=False):
        rows = []
        with self.store.connection() as db:
            for record_type in ROUTED:
                rows += [dict(row) for row in db.execute(
                    f"SELECT x.*,f.family_record_key,f.mode,f.members_json,f.suggested_json,f.status AS routing,f.delivered_json,f.updated_at "
                    f"FROM ({SUMMARY[record_type]}) x JOIN family_assignments f ON f.record_type=x.record_type AND f.record_id=x.id "
                    "WHERE x.review_status<>'rejected'" + ("" if include_delivered else " AND f.status IN ('unassigned','suggested')"))]
        for row in rows:
            for key in ("members_json", "suggested_json", "delivered_json"):
                row[key[:-5]] = json.loads(row.pop(key))
            row["shareable"] = row["record_type"] in SHAREABLE
            row["amount"] = money(row["amount_minor"], row["currency"]) if row["amount_minor"] is not None else None
        return sorted(rows, key=lambda row: (row["date"] or "", row["record_type"], row["id"]), reverse=True)

    def get(self, record_type, record_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM family_assignments WHERE record_type=? AND record_id=?", (record_type, record_id)).fetchone()
        if row is None:
            raise ValueError("This record has no family assignment yet. Refresh the page.")
        return {**dict(row), "members": json.loads(row["members_json"]), "delivered": json.loads(row["delivered_json"])}

    def assign(self, record_type, record_id, mode, members, known_members):
        """Confirm who a record is for. Returns the assignment, ready to deliver."""
        if record_type not in ROUTED:
            raise ValueError("Only receipts, bills, statements and pay stubs are routed.")
        members = list(dict.fromkeys(members))
        if any(member not in known_members for member in members):
            raise ValueError("Choose people who are in the family.")
        if mode == "member" and len(members) != 1:
            raise ValueError("Choose the one person this is for.")
        if mode == "shared":
            if record_type not in SHAREABLE:
                raise ValueError("Statements and pay stubs belong to one person; only receipts and bills can be shared.")
            if not members:
                raise ValueError("Choose at least one person to share it.")
        if mode not in ("member", "shared"):
            raise ValueError("Choose a person or Shared by the family.")
        self.get(record_type, record_id)
        with self.store.connection() as db:
            db.execute("UPDATE family_assignments SET mode=?,members_json=?,status='confirmed',updated_at=?,actor=? WHERE record_type=? AND record_id=?",
                       (mode, json.dumps([member for member in known_members if member in members]), now(), actor.current(), record_type, record_id))
        return self.get(record_type, record_id)

    def pending(self):
        """Assignments confirmed but not yet delivered to everyone."""
        with self.store.connection() as db:
            return [(row["record_type"], row["record_id"]) for row in db.execute("SELECT record_type,record_id FROM family_assignments WHERE status='confirmed'")]

    def deliveries(self, record_type, record_id):
        """[(member_id, action, share or None)] for one confirmed assignment: each person's record, and a retraction for
        anyone it was delivered to before who is no longer on it."""
        assignment = self.get(record_type, record_id)
        record, _, _ = self.payload(record_type, record_id)
        total = record.get("total_minor") if record_type == "receipt" else record.get("amount_due_minor") if record_type == "bill" else None
        people = assignment["members"]
        shares = equal_shares(total, len(people)) if assignment["mode"] == "shared" and total else [None] * len(people)
        plan = [(member, "record", share) for member, share in zip(people, shares)]
        plan += [(member, "retract", None) for member, state in assignment["delivered"].items() if state == "delivered" and member not in people]
        return assignment, plan

    def mark_delivered(self, record_type, record_id, results):
        """results: {member_id: 'delivered'|'retracted'}. The assignment is delivered once every person has theirs."""
        with self.store.connection() as db:
            row = db.execute("SELECT delivered_json FROM family_assignments WHERE record_type=? AND record_id=?", (record_type, record_id)).fetchone()
            delivered = {**json.loads(row[0]), **results}
            db.execute("UPDATE family_assignments SET delivered_json=?,status='delivered',updated_at=? WHERE record_type=? AND record_id=?",
                       (json.dumps(delivered), now(), record_type, record_id))

    # The record as it travels: the family's confirmed values, including any corrections made in the family's Review.

    def payload(self, record_type, record_id):
        """(record, document name, document bytes) for publishing the record in a person's library."""
        with self.store.connection() as db:
            table = TABLES[record_type]
            row = db.execute(f"SELECT * FROM {table} WHERE id=?", (record_id,)).fetchone()
            if row is None:
                raise ValueError("Financial record not found.")
            row = dict(row)
            name = lambda merchant_id: (db.execute("SELECT canonical_name FROM merchants WHERE id=?", (merchant_id,)).fetchone() or [None])[0]
            base = {"currency": row["currency"], "issues": json.loads(row.get("validation_json") or "[]"), "locator": {"family": True}}
            if record_type == "receipt":
                items = [{"description": item["description"], "product_code": item["product_code"], "quantity": item["quantity"],
                          "unit_price_minor": item["unit_price_minor"], "line_total_minor": item["line_total_minor"],
                          "discount_minor": item["discount_minor"], "taxed": None if item["taxed"] is None else bool(item["taxed"]),
                          "category": item["category"], "locator": {"family": True}}
                         for item in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? AND review_status<>'rejected' ORDER BY position", (record_id,))]
                record = {**base, "merchant": name(row["merchant_id"]), "purchase_date": row["purchase_date"], "subtotal_minor": row["subtotal_minor"],
                          "tax_minor": row["tax_minor"], "tip_minor": row["tip_minor"], "total_minor": row["total_minor"], "items": items,
                          "description": row["description"], "location": row["location"], "category": row["category"], "recurrence": row["recurrence"],
                          "payment_last_four": row["payment_last_four"], "return_days_printed": row["return_days_printed"],
                          "return_policy_quote": row["return_policy_quote"]}
            elif record_type == "bill":
                record = {**base, "provider": name(row["provider_merchant_id"]), "issue_date": row["issue_date"], "due_date": row["due_date"],
                          "period_start": row["period_start"], "period_end": row["period_end"], "amount_due_minor": row["amount_due_minor"]}
            elif record_type == "statement":
                account = dict(db.execute("SELECT * FROM accounts WHERE id=?", (row["account_id"],)).fetchone())
                transactions = [{"posted_date": item["posted_date"], "transaction_date": item["transaction_date"], "description": item["description_raw"],
                                 "amount_minor": item["amount_minor"], "currency": item["currency"], "transaction_type": item["transaction_type"],
                                 "locator": {"family": True}}
                                for item in db.execute("SELECT * FROM transactions WHERE statement_id=? AND review_status<>'rejected' ORDER BY posted_date,id", (record_id,))]
                record = {**base, "statement_type": row["statement_type"], "institution": account["institution"], "last_four": account["account_last_four"],
                          "period_start": row["period_start"], "period_end": row["period_end"], "due_date": row["due_date"],
                          "opening_balance_minor": row["opening_balance_minor"], "closing_balance_minor": row["closing_balance_minor"],
                          "statement_balance_minor": row["statement_balance_minor"], "minimum_payment_minor": row["minimum_payment_minor"],
                          "summary": json.loads(row["summary_json"] or "{}"), "transactions": transactions, "reconciliation": row["reconciliation"]}
            else:
                lines = [{"description": line["description"], "line_group": line["line_group"], "category": line["category"],
                          "current_minor": line["current_minor"], "ytd_minor": line["ytd_minor"], "locator": {"family": True}}
                         for line in db.execute("SELECT * FROM income_lines WHERE income_record_id=? ORDER BY position", (record_id,))]
                record = {**base, "payer_or_employer": name(row["payer_merchant_id"]), "pay_date": row["pay_date"], "period_start": row["period_start"],
                          "period_end": row["period_end"], "gross_pay_minor": row["gross_pay_minor"], "net_pay_minor": row["net_pay_minor"],
                          "taxes_minor": row["taxes_minor"], "deductions_minor": row["deductions_minor"], "gross_pay_ytd_minor": row["gross_pay_ytd_minor"],
                          "net_pay_ytd_minor": row["net_pay_ytd_minor"], "work_state": row["work_state"], "pay_frequency": row["pay_frequency"],
                          "lines": lines}
            document = db.execute("SELECT relative_path FROM occurrences WHERE id=?", (row["document_id"],)).fetchone()
        blob = self.store.blob_path(row["blob_hash"])
        return record, document[0].rsplit("/", 1)[-1] if document else "document", blob.read_bytes()


# A person's library: applying what the family sent ---------------------------------------------

def filing(record_type, record):
    """(document type, merchant or issuer, date) for filing a delivered document, as extraction would have filed it."""
    if record_type == "receipt":
        return "receipt", record.get("merchant"), record.get("purchase_date")
    if record_type == "bill":
        return "bill", record.get("provider"), record.get("due_date") or record.get("issue_date")
    if record_type == "statement":
        kind = "credit_card_statement" if record.get("statement_type") == "credit_card" else "bank_statement"
        return kind, record.get("institution"), record.get("period_end")
    return "paystub", record.get("payer_or_employer"), record.get("pay_date")


def find_delivered(db, key):
    """(record_type, record_id) a family delivery with this key published here, or None."""
    row = db.execute("SELECT record_type,record_id FROM financial_evidence_links WHERE source_key=? AND record_type IN ('receipt','bill','statement','income_record') "
                     "ORDER BY id DESC LIMIT 1", ("family:" + key,)).fetchone()
    return (row[0], row[1]) if row else None


def apply_delivery(store, delivery, document):
    """Publish one delivery in this library: the preserved document, the confirmed record (counted, since the family
    confirmed it) and this person's part when shared. The same key or document updates rather than duplicates."""
    ledger, key = Ledger(store), delivery["key"]
    if delivery["action"] == "retract":
        with store.connection() as db:
            found = find_delivered(db, key)
        if found:
            ledger.review(*found, "rejected", "Removed from a family split.")
        return {"action": "retract", "record": found}
    record_type, record = delivery["record_type"], delivery["record"]
    if record_type not in ROUTED:
        raise ValueError("This delivery holds a record Home Manager cannot use.")
    digest = hashlib.sha256(document).hexdigest()
    if digest != delivery["blob_hash"]:
        raise ValueError("The delivered document does not match its record.")
    with store.connection() as db:
        existing = db.execute("SELECT id FROM occurrences WHERE current_hash=? ORDER BY id LIMIT 1", (digest,)).fetchone()
    if existing:
        document_id = existing[0]
    else:
        name = "".join(ch for ch in f"From family {delivery['name']}" if ch.isalnum() or ch in " ._-()")[:120] or "From family"
        document_id, _ = store.import_document(name, document)
    source = {"document_id": document_id, "blob_hash": digest, "source_key": "family:" + key, "run_id": None}
    publish = {"receipt": ledger.publish_receipt, "bill": ledger.publish_bill, "statement": ledger.publish_statement,
               "income_record": ledger.publish_income}[record_type]
    published = publish(record, source, "verified")
    with store.connection() as db:
        if record_type in SHAREABLE:
            if delivery.get("share") is None:
                db.execute("DELETE FROM record_shares WHERE record_type=? AND record_id=?", (record_type, published["id"]))
            else:
                total = record["total_minor"] if record_type == "receipt" else record["amount_due_minor"]
                db.execute("INSERT OR REPLACE INTO record_shares VALUES(?,?,?,?,?,?,?)",
                           (record_type, published["id"], delivery["share"], total, json.dumps(delivery.get("people", [])), key, now()))
            if record_type == "receipt":
                ledger.refresh_splits(db, published["id"])
        if record_type == "statement" and record.get("reconciliation") == "reconciled":
            db.execute("UPDATE statements SET reconciliation='reconciled' WHERE id=?", (published["id"],))
    kind, name, dated = filing(record_type, record)
    try:
        store.library.file_classified(document_id, digest, kind, name, dated, "Filed from the record the family confirmed.")
    except (ValueError, OSError, RuntimeError):
        pass  # The record counts either way; the document stays in Unfiled until it is filed.
    return {"action": "record", "record": (record_type, published["id"]), "status": published["status"]}
