"""Deterministic reconciliation (spec section 10): receipts, transfers and refunds.

Rules use exact integer amounts, explicit date windows and merchant-name overlap. A
unique plausible match becomes a proposed link; several plausible matches become an
open issue and no link. Rejected links are never re-proposed. The model plays no part.
The user answers an open issue by choosing one candidate (a verified link scored by the
same rules) or by leaving the record unmatched, which later passes respect.
"""

from collections import defaultdict
from datetime import date, timedelta
import json

from .finance import COUNTABLE, NON_SPENDING, Ledger, classify_transaction, name_tokens, normalize_name
from .storage import now

RECEIPT_POSTING_DAYS, TRANSFER_DAYS, REFUND_DAYS = 5, 5, 120
TRANSFERISH = ("transfer", "payment")
CADENCES = {"weekly": (6, 8), "monthly": (26, 35), "quarterly": (85, 95), "annual": (360, 370)}
MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}
TRIGGERS = ("manual", "import", "extraction", "resolution", "correction")
OBLIGATION_DECISIONS = ("verified", "rejected", "ended")
# Issue type -> (table of the record the issue is about, how a chosen candidate is linked).
ISSUE_KINDS = {"ambiguous_receipt_match": "receipt", "ambiguous_transfer": "transfer", "ambiguous_refund": "refund"}


def shift(value, days):
    return (date.fromisoformat(value) + timedelta(days=days)).isoformat()


def add_months(value, months):
    """Same day of month, clamped to the month's end (Jan 31 + 1 month -> Feb 28/29)."""
    day = date.fromisoformat(value)
    year, month = divmod(day.month - 1 + months, 12)
    following = date(day.year + year, month + 1, 1)
    last = ((following.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).day
    return following.replace(day=min(day.day, last)).isoformat()


def gap(first, second):
    return abs((date.fromisoformat(first) - date.fromisoformat(second)).days)


# Scoring rules: integer points plus the signals that earned them. Callers have already
# required equal amounts and currencies.

def receipt_match(receipt, transaction):
    points, signals = 60, ["amount"]
    lag = gap(transaction["transaction_date"] or transaction["posted_date"], receipt["purchase_date"])
    if lag == 0:
        points, signals = points + 20, signals + ["same_day"]
    elif lag <= 2:
        points, signals = points + 10, signals + ["date"]
    if receipt["merchant"] and name_tokens(receipt["merchant"]) & name_tokens(transaction["description_raw"]):
        points, signals = points + 20, signals + ["merchant"]
    return points, "+".join(signals)


def transfer_match(outflow, inflow):
    points = 70 + (10 if outflow["posted_date"] == inflow["posted_date"] else 0) + (
        20 if outflow["transaction_type"] in TRANSFERISH and inflow["transaction_type"] in TRANSFERISH else 0)
    return points, "opposite_amount+date_window"


def refund_match(purchase, credit):
    exact = -purchase["amount_minor"] == credit["amount_minor"]
    return (90, "merchant+exact_amount") if exact else (70, "merchant+partial_amount")


class Reconciler:
    def __init__(self, store):
        self.store, self.ledger = store, Ledger(store)

    def recover(self):
        with self.store.connection() as db:
            db.execute("UPDATE reconciliation_runs SET status='failed',error='interrupted',finished_at=? WHERE status='running'", (now(),))

    def run(self, trigger="manual"):
        """One recorded pass. Returns the counts; the run row keeps them with timing."""
        if trigger not in TRIGGERS:
            raise ValueError("Unknown reconciliation trigger.")
        with self.store.connection() as db:
            run_id = db.execute("INSERT INTO reconciliation_runs(trigger,status,started_at) VALUES(?,'running',?)", (trigger, now())).lastrowid
        try:
            with self.store.connection() as db:
                summary = {"receipt_links": self.receipts(db), "transfers": self.transfers(db), "refunds": self.refunds(db),
                           "recurring": self.recurring(db)}
                summary["open_issues"] = db.execute("SELECT count(*) FROM reconciliation_issues WHERE status='open'").fetchone()[0]
                # Matched receipts can give transactions a merchant name, which category rules also match.
                self.ledger.apply_rules(db)
        except Exception as exc:
            with self.store.connection() as db:  # Only the error class: messages could echo document text.
                db.execute("UPDATE reconciliation_runs SET status='failed',error=?,finished_at=? WHERE id=?", (type(exc).__name__, now(), run_id))
            raise
        with self.store.connection() as db:
            db.execute("UPDATE reconciliation_runs SET status='succeeded',finished_at=?,receipt_links=?,transfers=?,refunds=?,recurring=?,open_issues=? WHERE id=?",
                       (now(), *summary.values(), run_id))
        return summary

    def history(self, limit=20):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM reconciliation_runs ORDER BY id DESC LIMIT ?", (limit,))]

    # Issues ---------------------------------------------------------------------

    @staticmethod
    def issue(db, kind, record_type, record_id, candidates):
        # A question the user answered "leave unmatched" stays answered.
        db.execute("INSERT INTO reconciliation_issues(issue_type,record_type,record_id,detail_json,status,created_at,updated_at) VALUES(?,?,?,?,'open',?,?) "
                   "ON CONFLICT(issue_type,record_type,record_id) DO UPDATE SET detail_json=excluded.detail_json,status='open',resolution=NULL,"
                   "updated_at=excluded.updated_at WHERE coalesce(reconciliation_issues.resolution,'')<>'left_unmatched'",
                   (kind, record_type, record_id, json.dumps({"candidate_transaction_ids": candidates}), now(), now()))

    @staticmethod
    def resolve(db, kind, record_type, record_id):
        db.execute("UPDATE reconciliation_issues SET status='resolved',updated_at=? WHERE issue_type=? AND record_type=? AND record_id=? AND status='open'",
                   (now(), kind, record_type, record_id))

    def resolve_issue(self, issue_id, transaction_id=None):
        """Answer an ambiguous match: link the chosen candidate (verified) or leave the record unmatched."""
        with self.store.connection() as db:
            issue = db.execute("SELECT * FROM reconciliation_issues WHERE id=?", (issue_id,)).fetchone()
            if issue is None:
                raise ValueError("Reconciliation question not found.")
            if issue["status"] != "open":
                raise ValueError("This question was already answered.")
            if issue["issue_type"] not in ISSUE_KINDS:
                raise ValueError("This question cannot be answered here.")
            resolution = "left_unmatched"
            if transaction_id is not None:
                if transaction_id not in json.loads(issue["detail_json"])["candidate_transaction_ids"]:
                    raise ValueError("Choose one of the listed transactions.")
                chosen = self.transaction(db, transaction_id)
                if chosen is None or chosen["review_status"] == "rejected":
                    raise ValueError("That transaction was rejected or no longer exists.")
                self.link_choice(db, ISSUE_KINDS[issue["issue_type"]], issue["record_id"], chosen)
                resolution = "linked"
            db.execute("UPDATE reconciliation_issues SET status='resolved',resolution=?,updated_at=? WHERE id=?", (resolution, now(), issue_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('reconciliation_issue',?,'open',?,?,?)",
                       (issue_id, resolution, f"Chose transaction {transaction_id}." if transaction_id else "", now()))
        return {"id": issue_id, "resolution": resolution, "transaction_id": transaction_id}

    def link_choice(self, db, kind, record_id, chosen):
        if kind == "receipt":
            receipt = db.execute("SELECT r.*,m.canonical_name AS merchant FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id WHERE r.id=?", (record_id,)).fetchone()
            if db.execute("SELECT 1 FROM transaction_receipt_links WHERE transaction_id=? AND receipt_id<>? AND review_status<>'rejected'", (chosen["id"], record_id)).fetchone():
                raise ValueError("That transaction is already matched to another receipt.")
            points, method = receipt_match(receipt, chosen)
            self.link_receipt(db, receipt, chosen, points, method + "+user_choice", "verified")
            return
        record = self.transaction(db, record_id)
        if kind == "transfer":
            points, method = transfer_match(record, chosen)
            self.link_transfer(db, record, chosen, points, method + "+user_choice", "verified")
        else:
            points, method = refund_match(chosen, record)
            self.link_refund(db, chosen, record, points, method + "+user_choice", "verified")

    @staticmethod
    def transaction(db, transaction_id):
        return db.execute("SELECT t.*,a.account_type FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (transaction_id,)).fetchone()

    # Link writers: proposals never revive a rejected pair; a user's choice overrides it.

    @staticmethod
    def _conflict(status):
        return "DO NOTHING" if status == "proposed" else "DO UPDATE SET review_status=excluded.review_status,match_score=excluded.match_score,match_method=excluded.match_method,updated_at=excluded.updated_at"

    def link_receipt(self, db, receipt, transaction, points, method, status="proposed"):
        db.execute("INSERT INTO transaction_receipt_links(transaction_id,receipt_id,match_score,match_method,review_status,created_at,updated_at) "
                   f"VALUES(?,?,?,?,?,?,?) ON CONFLICT(transaction_id,receipt_id) {self._conflict(status)}",
                   (transaction["id"], receipt["id"], points, method, status, now(), now()))
        if receipt["merchant_id"]:
            db.execute("UPDATE transactions SET merchant_id=coalesce(merchant_id,?),updated_at=? WHERE id=?", (receipt["merchant_id"], now(), transaction["id"]))
        self.resolve(db, "ambiguous_receipt_match", "receipt", receipt["id"])

    def link_transfer(self, db, outflow, inflow, points, method, status="proposed"):
        db.execute("INSERT INTO transaction_links(link_type,from_transaction_id,to_transaction_id,match_score,match_method,review_status,created_at,updated_at) "
                   f"VALUES('transfer',?,?,?,?,?,?,?) ON CONFLICT(link_type,from_transaction_id,to_transaction_id) {self._conflict(status)}",
                   (outflow["id"], inflow["id"], points, method, status, now(), now()))
        kind = "payment" if inflow["account_type"] == "credit_card" else "transfer"
        for row in (outflow, inflow):
            if row["transaction_type"] not in NON_SPENDING:
                db.execute("UPDATE transactions SET transaction_type=?,updated_at=? WHERE id=? AND review_status<>'verified'", (kind, now(), row["id"]))
        self.resolve(db, "ambiguous_transfer", "transaction", outflow["id"])

    def link_refund(self, db, purchase, credit, points, method, status="proposed"):
        db.execute("INSERT INTO transaction_links(link_type,from_transaction_id,to_transaction_id,match_score,match_method,review_status,created_at,updated_at) "
                   f"VALUES('refund',?,?,?,?,?,?,?) ON CONFLICT(link_type,from_transaction_id,to_transaction_id) {self._conflict(status)}",
                   (purchase["id"], credit["id"], points, method, status, now(), now()))
        self.resolve(db, "ambiguous_refund", "transaction", credit["id"])

    # Matching passes ----------------------------------------------------------------

    def receipts(self, db):
        """Receipt total == -transaction amount (same currency), posted within the posting window."""
        created = 0
        receipts = db.execute("SELECT r.*,m.canonical_name AS merchant FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id "
                              "WHERE r.review_status<>'rejected' AND r.total_minor IS NOT NULL AND r.purchase_date IS NOT NULL AND NOT EXISTS("
                              "SELECT 1 FROM transaction_receipt_links l WHERE l.receipt_id=r.id AND l.review_status<>'rejected')").fetchall()
        for receipt in receipts:
            candidates = db.execute(
                "SELECT t.* FROM transactions t WHERE t.currency=? AND t.amount_minor=? AND t.review_status<>'rejected' "
                "AND coalesce(t.transaction_date,t.posted_date) BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l "
                "WHERE l.transaction_id=t.id AND (l.review_status<>'rejected' OR l.receipt_id=?))",
                (receipt["currency"], -receipt["total_minor"], receipt["purchase_date"], shift(receipt["purchase_date"], RECEIPT_POSTING_DAYS), receipt["id"])).fetchall()
            scored = sorted(((*receipt_match(receipt, transaction), transaction) for transaction in candidates), key=lambda item: -item[0])
            # One candidate, or one candidate clearly better (by at least one whole rule) than the rest.
            if scored and (len(scored) == 1 or scored[0][0] >= 80 and scored[0][0] - scored[1][0] >= 20):
                points, method, transaction = scored[0]
                self.link_receipt(db, receipt, transaction, points, method)
                created += 1
            elif len(scored) > 1:
                self.issue(db, "ambiguous_receipt_match", "receipt", receipt["id"], [item[2]["id"] for item in scored])
        return created

    def transfers(self, db):
        """Equal and opposite amounts between two owned accounts within a few days."""
        created = 0
        outflows = db.execute("SELECT t.*,a.account_type FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.amount_minor<0 "
                              "AND t.review_status<>'rejected' AND t.transaction_type IN ('transfer','payment','purchase','withdrawal') AND NOT EXISTS("
                              "SELECT 1 FROM transaction_links l WHERE l.link_type='transfer' AND l.from_transaction_id=t.id AND l.review_status<>'rejected')").fetchall()
        for outflow in outflows:
            candidates = db.execute(
                "SELECT t.*,a.account_type FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.account_id<>? AND t.currency=? "
                "AND t.amount_minor=? AND t.review_status<>'rejected' AND t.posted_date BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM transaction_links l "
                "WHERE l.link_type='transfer' AND l.to_transaction_id=t.id AND (l.review_status<>'rejected' OR l.from_transaction_id=?))",
                (outflow["account_id"], outflow["currency"], -outflow["amount_minor"], shift(outflow["posted_date"], -TRANSFER_DAYS),
                 shift(outflow["posted_date"], TRANSFER_DAYS), outflow["id"])).fetchall()
            # Keywords on either side, or money arriving on a card account, mark it as moving money.
            plausible = [row for row in candidates if outflow["transaction_type"] in TRANSFERISH or row["transaction_type"] in TRANSFERISH
                         or row["account_type"] == "credit_card"]
            if len(plausible) == 1:
                self.link_transfer(db, outflow, plausible[0], *transfer_match(outflow, plausible[0]))
                created += 1
            elif len(plausible) > 1 and outflow["transaction_type"] in TRANSFERISH:
                self.issue(db, "ambiguous_transfer", "transaction", outflow["id"], [row["id"] for row in plausible])
        return created

    def refunds(self, db):
        """A credit from the same merchant on the same account after a purchase at least as large."""
        created = 0
        credits = db.execute("SELECT t.* FROM transactions t WHERE t.amount_minor>0 AND t.transaction_type='refund' AND t.review_status<>'rejected' "
                             "AND NOT EXISTS(SELECT 1 FROM transaction_links l WHERE l.link_type='refund' AND l.to_transaction_id=t.id AND l.review_status<>'rejected')").fetchall()
        for credit in credits:
            candidates = db.execute(
                "SELECT t.* FROM transactions t WHERE t.account_id=? AND t.currency=? AND t.amount_minor<0 AND -t.amount_minor>=? "
                "AND t.transaction_type='purchase' AND t.review_status<>'rejected' AND t.posted_date BETWEEN ? AND ? AND NOT EXISTS("
                "SELECT 1 FROM transaction_links l WHERE l.link_type='refund' AND l.from_transaction_id=t.id AND l.to_transaction_id=? AND l.review_status='rejected')",
                (credit["account_id"], credit["currency"], credit["amount_minor"], shift(credit["posted_date"], -REFUND_DAYS), credit["posted_date"], credit["id"])).fetchall()
            plausible = [row for row in candidates if name_tokens(row["description_raw"]) & name_tokens(credit["description_raw"])]
            exact = [row for row in plausible if -row["amount_minor"] == credit["amount_minor"]]
            chosen = exact if len(exact) == 1 else plausible if len(plausible) == 1 else []
            if chosen:
                self.link_refund(db, chosen[0], credit, *refund_match(chosen[0], credit))
                created += 1
            elif plausible:
                self.issue(db, "ambiguous_refund", "transaction", credit["id"], [row["id"] for row in plausible])
        return created

    def recurring(self, db):
        """Same account, merchant key and exact amount at a steady cadence, three or more times."""
        groups = defaultdict(list)
        for row in db.execute(f"SELECT t.* FROM transactions t WHERE t.amount_minor<0 AND t.transaction_type IN ('purchase','fee') AND {COUNTABLE} ORDER BY t.posted_date,t.id"):
            key = " ".join(normalize_name(row["description_raw"]).split()[:3])
            if key:
                groups[(row["account_id"], key, row["amount_minor"], row["currency"])].append(row)
        found = 0
        for (account_id, key, amount, currency), rows in groups.items():
            gaps = [gap(later["posted_date"], earlier["posted_date"]) for earlier, later in zip(rows, rows[1:])]
            frequency = next((name for name, (low, high) in CADENCES.items() if len(rows) >= 3 and all(low <= days <= high for days in gaps)), None)
            if frequency is None:
                continue
            merchant = self.ledger.merchant(db, key)
            next_due = shift(rows[-1]["posted_date"], 7) if frequency == "weekly" else add_months(rows[-1]["posted_date"], MONTHS[frequency])
            db.execute("INSERT INTO recurring_obligations(merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,next_due_date,status,"
                       "confidence_source,created_at,updated_at) VALUES(?,?,'subscription_or_bill',?,?,?,?,'proposed',?,?,?) "
                       "ON CONFLICT(merchant_id,account_id,currency,frequency) DO UPDATE SET next_due_date=excluded.next_due_date,updated_at=excluded.updated_at,"
                       "expected_amount_minor=CASE WHEN recurring_obligations.status='proposed' THEN excluded.expected_amount_minor ELSE recurring_obligations.expected_amount_minor END "
                       "WHERE recurring_obligations.status NOT IN ('rejected','ended')",
                       (merchant, account_id, -amount, currency, frequency, next_due, f"deterministic_cadence:{len(rows)}_payments", now(), now()))
            found += 1
        return found

    # User decisions -------------------------------------------------------------------

    def review_link(self, kind, link_id, status):
        """Verify or reject a proposed link. Rejecting a transfer re-derives the rows' original types."""
        if status not in ("verified", "rejected"):
            raise ValueError("Choose verify or reject.")
        table = {"receipt": "transaction_receipt_links", "transfer": "transaction_links", "refund": "transaction_links"}.get(kind)
        if table is None:
            raise ValueError("Unknown link type.")
        with self.store.connection() as db:
            link = db.execute(f"SELECT * FROM {table} WHERE id=?" + ("" if kind == "receipt" else " AND link_type=?"),
                              (link_id,) if kind == "receipt" else (link_id, kind)).fetchone()
            if link is None:
                raise ValueError("Link not found.")
            db.execute(f"UPDATE {table} SET review_status=?,updated_at=? WHERE id=?", (status, now(), link_id))
            if status == "rejected" and kind == "receipt":
                db.execute("UPDATE transactions SET merchant_id=NULL,updated_at=? WHERE id=? AND merchant_id=(SELECT merchant_id FROM receipts WHERE id=?)",
                           (now(), link["transaction_id"], link["receipt_id"]))
            if status == "rejected" and kind == "transfer":
                for transaction in (link["from_transaction_id"], link["to_transaction_id"]):
                    row = self.transaction(db, transaction)
                    if row["review_status"] != "verified":
                        db.execute("UPDATE transactions SET transaction_type=?,updated_at=? WHERE id=?",
                                   (classify_transaction(row["description_raw"], row["amount_minor"], row["account_type"]), now(), transaction))
            if status == "rejected" and kind == "receipt":  # The merchant name came from the receipt; rules decide again without it.
                self.ledger.apply_rules(db, [link["transaction_id"]])
        return {"kind": kind, "id": link_id, "review_status": status}

    def review_obligation(self, obligation_id, status, note=""):
        """Confirm, reject or end a detected recurring payment. Rejected and ended ones are never re-proposed."""
        if status not in OBLIGATION_DECISIONS:
            raise ValueError("Choose confirm, not recurring, or ended.")
        with self.store.connection() as db:
            row = db.execute("SELECT status FROM recurring_obligations WHERE id=?", (obligation_id,)).fetchone()
            if row is None:
                raise ValueError("Recurring payment not found.")
            db.execute("UPDATE recurring_obligations SET status=?,updated_at=? WHERE id=?", (status, now(), obligation_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('recurring_obligation',?,?,?,?,?)",
                       (obligation_id, row["status"], status, note[:1000], now()))
        return {"id": obligation_id, "status": status}
