"""Family inbox: who each document uploaded to a family is for, and how it reaches that person's own library.

A family's own library is a staging area. Its records are never counted in family totals (those come from each
member's library). Every record gets an assignment in family_assignments: one person, shared by the family, or (a
bill) shared by its lines. A shared receipt or bill is divided into equal whole-cent parts among the people chosen
(splits.equal_shares); a bill shared by line gives each person their own lines and their part of the rest
(splits.line_shares). Each person's library receives the record with their part in record_shares. Statements and pay
stubs go to one person.

Owners come from the family's Who has what list (docs/family.md "Who has what"), never a guess: a receipt, bill or
statement paid with a listed card goes to that card's member, and a bill line whose printed number ends in a listed
phone line is that member's. A card or line that isn't listed stays unassigned, and Review offers to add it. A pay stub
is suggested for the one member who already has pay stubs from that employer. The user confirms each one.
"""

import hashlib
import json
import re
import uuid

from ..core import actor
from ..core.money import money
from ..library.storage import now
from .ledger import Ledger, normalize_name
from .splits import equal_shares, line_shares

ROUTED = ("receipt", "statement", "income_record")
SHAREABLE = ("receipt",)
TABLES = {"receipt": "receipts", "statement": "statements", "income_record": "income_records"}
ALIASES = {"receipt": "r", "statement": "s", "income_record": "i"}  # As SUMMARY names each table.
# One row per routable record in the family library: what it is, for the Review list. A bill is a receipt; its card is
# unknown (the account number on a bill is the provider's, not a card).
SUMMARY = {
    "receipt": "SELECT 'receipt' AS record_type,r.id,r.purchase_date AS date,m.canonical_name AS name,r.total_minor AS amount_minor,r.currency,"
               "r.review_status,r.document_id,r.blob_hash,r.payment_last_four AS last_four,r.document_kind FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id",
    "statement": "SELECT 'statement' AS record_type,s.id,s.period_end AS date,a.institution AS name,"
                 "coalesce(s.closing_balance_minor,s.statement_balance_minor) AS amount_minor,s.currency,s.review_status,s.document_id,s.blob_hash,"
                 "a.account_last_four AS last_four,'statement' AS document_kind FROM statements s JOIN accounts a ON a.id=s.account_id",
    "income_record": "SELECT 'income_record' AS record_type,i.id,i.pay_date AS date,m.canonical_name AS name,i.net_pay_minor AS amount_minor,i.currency,"
                     "i.review_status,i.document_id,i.blob_hash,NULL AS last_four,'paystub' AS document_kind FROM income_records i "
                     "LEFT JOIN merchants m ON m.id=i.payer_merchant_id",
}


def member_facts(members):
    """{member_id: {"accounts": [...], "employers": set}} from each member's copy. Employers suggest a pay stub's owner;
    members' own accounts are only offered as Who has what entries to add, never used to guess.
    members: [(member dict, store)] such as family.views() opened read-only."""
    facts = {}
    for member, store in members:
        with store.connection() as db:
            accounts = [{"institution": row[0], "account_type": row[1], "last_four": row[2]} for row in db.execute(
                "SELECT institution,account_type,account_last_four FROM accounts WHERE account_last_four IS NOT NULL ORDER BY institution,id")]
            employers = {normalize_name(row[0]) for row in db.execute(
                "SELECT m.canonical_name FROM income_records i JOIN merchants m ON m.id=i.payer_merchant_id WHERE i.review_status<>'rejected'")}
        facts[member["member_id"]] = {"accounts": accounts, "employers": employers}
    return facts


def phone_member(holder, who):
    """The member whose listed phone line the printed holder's number ends in, or None (docs/family.md "Who has what")."""
    digits = re.sub(r"\D", "", holder or "")
    if len(digits) < 4:
        return None
    return next((entry["member_id"] for entry in who if entry["kind"] == "phone" and entry["last_four"] == digits[-4:]), None)


def suggest(row, facts, who, lines=()):
    """(mode, members, reason, ask) for a new record: ask is a card or phone line to offer adding to Who has what, else
    None. mode is None when nothing says whose it is."""
    owners = sorted({line["member_id"] for line in lines if line["member_id"]})
    unlisted = sorted({re.sub(r"\D", "", line["line_holder"])[-4:] for line in lines if line["line_holder"] and not line["member_id"]
                       and len(re.sub(r"\D", "", line["line_holder"])) >= 4})
    if unlisted:  # Asked once; until it is added, the lines no one is named on are shared out with the taxes and fees.
        return "lines" if owners else None, owners, f"A phone line ending {unlisted[0]} isn't in Who has what", {"kind": "phone", "last_four": unlisted[0]}
    if len(owners) > 1:  # A bill whose phone lines name the family's people.
        return "lines", owners, "Its phone lines are in Who has what", None
    if owners:
        return "member", owners, "Its phone line is in Who has what", None
    if row["last_four"]:
        member = next((entry["member_id"] for entry in who if entry["kind"] == "card" and entry["last_four"] == row["last_four"]), None)
        if member:
            return "member", [member], f"Paid with a card ending {row['last_four']}", None
        return None, [], f"A card ending {row['last_four']} isn't in Who has what", {"kind": "card", "last_four": row["last_four"]}
    if unlisted:
        return None, [], f"A phone line ending {unlisted[0]} isn't in Who has what", {"kind": "phone", "last_four": unlisted[0]}
    if row["record_type"] == "income_record" and row["name"]:
        found = [member for member, known in facts.items() if normalize_name(row["name"]) in known["employers"]]
        if len(found) == 1:
            return "member", found, f"Earlier pay stubs from {row['name']}", None
    return None, [], "Nothing on it says whose it is", None


class FamilyRouting:
    def __init__(self, store):
        self.store, self.ledger = store, Ledger(store)

    def lines(self, db, record_id):
        return [dict(row) for row in db.execute("SELECT id,position,description,line_total_minor,discount_minor,line_holder,line_kind,member_id,member_source "
                                                "FROM receipt_items WHERE receipt_id=? AND review_status<>'rejected' ORDER BY position", (record_id,))]

    def refresh(self, facts, who=()):
        """An assignment row for every routable record, with a suggestion for each one not confirmed yet. Who has what
        applies again to everything not yet delivered: a bill's phone lines take their listed member (a person's own
        choice of member stays), and the suggestion is worked out again."""
        with self.store.connection() as db:
            for record_type in ROUTED:
                alias = ALIASES[record_type]
                for row in db.execute(SUMMARY[record_type] + f" WHERE {alias}.review_status<>'rejected'").fetchall():
                    current = db.execute("SELECT status FROM family_assignments WHERE record_type=? AND record_id=?", (record_type, row["id"])).fetchone()
                    if current and current["status"] in ("confirmed", "delivered"):
                        continue
                    lines = []
                    if row["document_kind"] == "bill":
                        for line in self.lines(db, row["id"]):
                            if line["member_source"] != "user":
                                member = phone_member(line["line_holder"], who)
                                if member != line["member_id"]:
                                    db.execute("UPDATE receipt_items SET member_id=?,member_source=? WHERE id=?",
                                               (member, "configured" if member else None, line["id"]))
                                    line["member_id"] = member
                            lines.append(line)
                        self.ledger.refresh_splits(db, row["id"])
                    mode, members, reason, ask = suggest(dict(row), facts, who, lines)
                    requested = db.execute("SELECT source_key FROM financial_evidence_links WHERE record_type='receipt' AND record_id=? "
                                           "AND source_key LIKE 'request:%' ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone() if record_type == "receipt" else None
                    suggested = {"mode": mode, "member_id": members[0] if len(members) == 1 else None, "members": members, "reason": reason, "ask": ask,
                                 "requested_by": requested[0].split(":")[1] if requested else None}
                    values = (mode, json.dumps(members), json.dumps(suggested), "suggested" if mode else "unassigned", now())
                    if current:
                        db.execute("UPDATE family_assignments SET mode=?,members_json=?,suggested_json=?,status=?,updated_at=? WHERE record_type=? AND record_id=?",
                                   (*values, record_type, row["id"]))
                    else:
                        db.execute("INSERT INTO family_assignments(mode,members_json,suggested_json,status,updated_at,record_type,record_id,family_record_key) "
                                   "VALUES(?,?,?,?,?,?,?,?)", (*values, record_type, row["id"], uuid.uuid4().hex))

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
                row["bill"] = row["document_kind"] == "bill"
                row["lines"] = self.lines(db, row["id"]) if row["bill"] else []
                row["amount"] = money(row["amount_minor"], row["currency"]) if row["amount_minor"] is not None else None
        return sorted(rows, key=lambda row: (row["date"] or "", row["record_type"], row["id"]), reverse=True)

    def get(self, record_type, record_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM family_assignments WHERE record_type=? AND record_id=?", (record_type, record_id)).fetchone()
        if row is None:
            raise ValueError("This record has no family assignment yet. Refresh the page.")
        return {**dict(row), "members": json.loads(row["members_json"]), "delivered": json.loads(row["delivered_json"])}

    def assign(self, record_type, record_id, mode, members, known_members):
        """Confirm who a record is for. Returns the assignment, ready to deliver. A bill shared by line goes to the people
        its lines name; members is ignored."""
        if record_type not in ROUTED:
            raise ValueError("Only receipts, bills, statements and pay stubs are routed.")
        members = list(dict.fromkeys(members))
        if any(member not in known_members for member in members):
            raise ValueError("Choose people who are in the family.")
        if mode == "lines":
            with self.store.connection() as db:
                kind = db.execute("SELECT document_kind,total_minor FROM receipts WHERE id=?", (record_id,)).fetchone() if record_type == "receipt" else None
                lines = self.lines(db, record_id) if kind and kind["document_kind"] == "bill" else []
            if not kind or kind["document_kind"] != "bill":
                raise ValueError("Only a bill can be shared by its lines.")
            if not line_shares(lines, kind["total_minor"] or 0):
                raise ValueError("Say whose each line is first: no line names anyone in the family yet.")
            members = [member for member in known_members if any(line["member_id"] == member for line in lines)]
        if mode == "member" and len(members) != 1:
            raise ValueError("Choose the one person this is for.")
        if mode == "shared":
            if record_type not in SHAREABLE:
                raise ValueError("Statements and pay stubs belong to one person; only receipts and bills can be shared.")
            if not members:
                raise ValueError("Choose at least one person to share it.")
        if mode not in ("member", "shared", "lines"):
            raise ValueError("Choose a person, Shared by the family, or Share by line.")
        self.get(record_type, record_id)
        with self.store.connection() as db:
            db.execute("UPDATE family_assignments SET mode=?,members_json=?,status='confirmed',updated_at=?,actor=? WHERE record_type=? AND record_id=?",
                       (mode, json.dumps([member for member in known_members if member in members]), now(), actor.current(), record_type, record_id))
        return self.get(record_type, record_id)

    def set_line_member(self, record_id, position, member, known_members):
        """Whose one line of a bill in the family's inbox is (None for nobody: it is shared out with the taxes and fees)."""
        if member is not None and member not in known_members:
            raise ValueError("Choose someone in the family.")
        with self.store.connection() as db:
            status = db.execute("SELECT status FROM family_assignments WHERE record_type='receipt' AND record_id=?", (record_id,)).fetchone()
        if status and status["status"] == "delivered":
            raise ValueError("This bill was already sent. Send it again to change whose lines are whose.")
        return self.ledger.correct_line(record_id, position, "member", member, members=known_members)

    def pending(self):
        """Assignments confirmed but not yet delivered to everyone."""
        with self.store.connection() as db:
            return [(row["record_type"], row["record_id"]) for row in db.execute("SELECT record_type,record_id FROM family_assignments WHERE status='confirmed'")]

    def deliveries(self, record_type, record_id):
        """[(member_id, action, share or None)] for one confirmed assignment: each person's record, and a retraction for
        anyone it was delivered to before who is no longer on it."""
        assignment = self.get(record_type, record_id)
        record, _, _ = self.payload(record_type, record_id)
        total = record.get("total_minor") if record_type == "receipt" else None
        people = assignment["members"]
        if assignment["mode"] == "lines":
            parts = line_shares(record["items"], total or 0)
            people = [member for member in people if member in parts]
            shares = [parts[member] for member in people]
        else:
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
        record, row = record_payload(self.store, record_type, record_id)
        with self.store.connection() as db:
            document = db.execute("SELECT relative_path FROM occurrences WHERE id=?", (row["document_id"],)).fetchone()
        blob = self.store.blob_path(row["blob_hash"])
        return record, document[0].rsplit("/", 1)[-1] if document else "document", blob.read_bytes()


def record_payload(store, record_type, record_id):
    """(record as publish_* takes it, its row) from any library, read-only: the family's own inbox, or a member's copy."""
    with store.connection() as db:
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
                      "category": item["category"], "line_holder": item["line_holder"], "line_kind": item["line_kind"], "member_id": item["member_id"],
                      "member_source": "configured" if item["member_id"] else None, "locator": {"family": True}}
                     for item in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? AND review_status<>'rejected' ORDER BY position", (record_id,))]
            record = {**base, "merchant": name(row["merchant_id"]), "purchase_date": row["purchase_date"], "subtotal_minor": row["subtotal_minor"],
                      "tax_minor": row["tax_minor"], "tip_minor": row["tip_minor"], "total_minor": row["total_minor"], "items": items,
                      "description": row["description"], "location": row["location"], "category": row["category"], "recurrence": row["recurrence"],
                      "payment_last_four": row["payment_last_four"], "return_days_printed": row["return_days_printed"],
                      "return_policy_quote": row["return_policy_quote"], "document_kind": row["document_kind"], "issue_date": row["issue_date"],
                      "due_date": row["due_date"], "period_start": row["period_start"], "period_end": row["period_end"],
                      "amount_due_minor": row["amount_due_minor"], "account_last_four": row["account_last_four"]}
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
    return record, row


def import_request(store, member_id, receipt_id, record, document_name, document):
    """A bill a member asked the family to share by line (share_requests in their copy), put in the family's inbox with
    the member's own values, once per request (docs/family.md "Sharing a bill by line"). Returns the inbox receipt's id,
    or None when it is there already."""
    key = f"request:{member_id}:{receipt_id}"
    with store.connection() as db:
        if db.execute("SELECT 1 FROM financial_evidence_links WHERE source_key=?", (key,)).fetchone():
            return None
        existing = db.execute("SELECT id FROM occurrences WHERE current_hash=? ORDER BY id LIMIT 1", (hashlib.sha256(document).hexdigest(),)).fetchone()
    document_id = existing[0] if existing else store.import_document(f"From family {document_name}"[:120], document)[0]
    record = {**record, "items": [{**item, "member_id": None, "member_source": None} for item in record["items"]]}  # Who has what decides here.
    source = {"document_id": document_id, "blob_hash": hashlib.sha256(document).hexdigest(), "source_key": key, "run_id": None}
    return Ledger(store).publish_receipt(record, source, "verified")["id"]


# A person's library: applying what the family sent ---------------------------------------------

def filing(record_type, record):
    """(document type, merchant or issuer, date) for filing a delivered document, as extraction would have filed it."""
    if record_type == "receipt":
        if record.get("document_kind") == "bill":
            return "bill", record.get("merchant"), record.get("due_date") or record.get("issue_date") or record.get("purchase_date")
        return "receipt", record.get("merchant"), record.get("purchase_date")
    if record_type == "bill":  # Sent before bills were receipts.
        return "bill", record.get("provider"), record.get("due_date") or record.get("issue_date")
    if record_type == "statement":
        kind = "credit_card_statement" if record.get("statement_type") == "credit_card" else "bank_statement"
        return kind, record.get("institution"), record.get("period_end")
    return "paystub", record.get("payer_or_employer"), record.get("pay_date")


def find_delivered(db, key):
    """(record_type, record_id) a family delivery with this key published here, or None."""
    row = db.execute("SELECT record_type,record_id FROM financial_evidence_links WHERE source_key=? AND record_type IN ('receipt','statement','income_record') "
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
    if record_type not in (*ROUTED, "bill"):
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
    kind, name, dated = filing(record_type, record)
    if record_type == "bill":  # A bill sent before bills were receipts: its amount due is its total.
        published = ledger.publish_bill(record, source, "verified")
        record_type, record = "receipt", {**record, "total_minor": record.get("amount_due_minor")}
    else:
        publish = {"receipt": ledger.publish_receipt, "statement": ledger.publish_statement, "income_record": ledger.publish_income}[record_type]
        published = publish(record, source, "verified")
    with store.connection() as db:
        if record_type in SHAREABLE:
            if delivery.get("share") is None:
                db.execute("DELETE FROM record_shares WHERE record_type=? AND record_id=?", (record_type, published["id"]))
            else:
                # Shared by line: whose lines this person's part is (Ledger.shares divides by them).
                db.execute("INSERT OR REPLACE INTO record_shares(record_type,record_id,share_minor,total_minor,people_json,family_record_key,created_at,member_id) "
                           "VALUES(?,?,?,?,?,?,?,?)", (record_type, published["id"], delivery["share"], record["total_minor"],
                                                       json.dumps(delivery.get("people", [])), key, now(), delivery.get("share_member")))
            db.execute("DELETE FROM share_requests WHERE receipt_id=?", (published["id"],))  # The family has answered it.
            ledger.refresh_splits(db, published["id"])
        if record_type == "statement" and record.get("reconciliation") == "reconciled":
            db.execute("UPDATE statements SET reconciliation='reconciled' WHERE id=?", (published["id"],))
    try:
        store.library.file_classified(document_id, digest, kind, name, dated, "Filed from the record the family confirmed.")
    except (ValueError, OSError, RuntimeError):
        pass  # The record counts either way; the document stays in Unfiled until it is filed.
    return {"action": "record", "record": (record_type, published["id"]), "status": published["status"]}
