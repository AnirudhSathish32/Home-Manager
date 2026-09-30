"""Deterministic reconciliation (spec section 10): receipts, transfers and refunds.

Rules use exact integer amounts, explicit date windows and merchant-name overlap. A
unique plausible match becomes a proposed link; several plausible matches become an
open issue and no link. Rejected links are never re-proposed. The model plays no part here;
recurring-bill proposals may use its stored answers about statement payees and contract terms.
The user answers an open issue by choosing one candidate (a verified link scored by the
same rules) or by leaving the record unmatched, which later passes respect.
"""

from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
import json

from ..core.categories import FREQUENCIES, FREQUENCY_MONTHS
from ..library.storage import now
from .ledger import COUNTABLE, MATCHABLE, NON_SPENDING, STANDALONE_RECEIPT, TRANSACTION_CATEGORY, Ledger, classify_transaction, name_tokens, normalize_name

RECEIPT_POSTING_DAYS, TRANSFER_DAYS, REFUND_DAYS = 5, 5, 120
# A charge up to 30% above a receipt's total (a tip added after printing, a currency conversion)
# from the same merchant is never linked automatically; the user is asked instead.
NEAR_PERCENT = 130
TRANSFERISH = ("transfer", "payment")
CADENCES = {"weekly": (6, 8), "monthly": (26, 35), "quarterly": (85, 95), "annual": (360, 370)}
# Charges in these categories propose a recurring bill after a single payment.
BILL_CATEGORIES = ("housing", "insurance", "subscriptions")
# A later payment pays a bill when it is 50% to 150% of the usual amount: utility bills vary month to month.
BILL_RANGE = (50, 150)
TRIGGERS = ("manual", "import", "extraction", "resolution", "correction")
OBLIGATION_DECISIONS = ("verified", "rejected", "ended")
# Issue type -> (table of the record the issue is about, how a chosen candidate is linked).
ISSUE_KINDS = {"ambiguous_receipt_match": "receipt", "ambiguous_transfer": "transfer", "ambiguous_refund": "refund",
               "ambiguous_investment_transfer": "investment"}


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


def due_after(day, frequency):
    return shift(day, 7) if frequency == "weekly" else add_months(day, FREQUENCY_MONTHS[frequency])


def payee_key(description):
    """A statement line's payee: its first three normalized words (store numbers and dates vary after them)."""
    return " ".join(normalize_name(description).split()[:3])


def bill_matches(bill, name, currency):
    """A payee name shares a word with the bill's payee, in the same currency."""
    return bill["currency"] == currency and bool(name_tokens(bill["merchant"]) & name_tokens(name))


def bill_payments(db, bill, start=None, end=None):
    """Counted payments to a bill's payee within BILL_RANGE of its usual amount, oldest first: card and bank lines,
    and receipts no line has replaced (so a receipt and its charge are one payment)."""
    low, high = BILL_RANGE
    window, params = "", []
    for column, bound, operator in (("day", start, ">="), ("day", end, "<=")):
        if bound:
            window += f" AND {column}{operator}?"
            params.append(bound)
    amounts = (bill["currency"], bill["expected_amount_minor"] * low, bill["expected_amount_minor"] * high)
    rows = db.execute(
        f"SELECT * FROM (SELECT 'transaction' AS record_type,t.id,coalesce(t.transaction_date,t.posted_date) AS day,-t.amount_minor AS amount,"
        f"{TRANSACTION_CATEGORY} AS category,t.description_raw||' '||coalesce(m.canonical_name,'') AS name FROM transactions t "
        f"LEFT JOIN merchants m ON m.id=t.merchant_id WHERE {COUNTABLE} AND t.transaction_type IN ('purchase','fee') AND t.currency=? "
        f"AND -t.amount_minor*100 BETWEEN ? AND ? "
        f"UNION ALL SELECT 'receipt',r.id,r.purchase_date,r.total_minor,coalesce(r.category,'uncategorized'),coalesce(m.canonical_name,'') FROM receipts r "
        f"LEFT JOIN merchants m ON m.id=r.merchant_id WHERE {STANDALONE_RECEIPT} AND r.currency=? AND r.total_minor*100 BETWEEN ? AND ?) "
        f"WHERE 1=1{window} ORDER BY day,record_type,id", (*amounts, *amounts, *params)).fetchall()
    return [dict(row) for row in rows if bill_matches(bill, row["name"], bill["currency"])]


# Scoring rules: integer points plus the signals that earned them. Callers have already
# required equal currencies and, except for a user's choice of a near match, equal amounts.

def receipt_match(receipt, transaction):
    exact = -transaction["amount_minor"] == receipt["total_minor"]
    points, signals = (60, ["amount"]) if exact else (30, ["near_amount"])
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
                           "investment_transfers": self.investment_transfers(db), "recurring": self.recurring(db) + self.propose_bills(db)}
                self.track_bills(db)
                summary["open_issues"] = db.execute("SELECT count(*) FROM reconciliation_issues WHERE status='open'").fetchone()[0]
                # Matched receipts can give transactions a merchant name, which category and tax rules also match.
                self.ledger.apply_rules(db)
                from .tax_tags import TaxTags  # tax_tags imports this module.
                TaxTags(self.ledger.store).refresh(db)
                # Every charge's item-category shares follow its current receipt link (restored or rejected ones included).
                self.ledger.refresh_splits(db)
        except Exception as exc:
            with self.store.connection() as db:  # Only the error class: messages could echo document text.
                db.execute("UPDATE reconciliation_runs SET status='failed',error=?,finished_at=? WHERE id=?", (type(exc).__name__, now(), run_id))
            raise
        with self.store.connection() as db:
            # Payments into investments are recorded as transfers in the run's history.
            db.execute("UPDATE reconciliation_runs SET status='succeeded',finished_at=?,receipt_links=?,transfers=?,refunds=?,recurring=?,open_issues=? WHERE id=?",
                       (now(), summary["receipt_links"], summary["transfers"] + summary["investment_transfers"], summary["refunds"], summary["recurring"],
                        summary["open_issues"], run_id))
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
        if kind == "investment":
            if db.execute("SELECT 1 FROM investment_events WHERE transaction_id=? AND id<>?", (chosen["id"], record_id)).fetchone():
                raise ValueError("That transaction already paid into another investment.")
            self.link_investment(db, record_id, chosen, "user")
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
        self.ledger.refresh_splits(db, receipt["id"])

    def link_transfer(self, db, outflow, inflow, points, method, status="proposed"):
        db.execute("INSERT INTO transaction_links(link_type,from_transaction_id,to_transaction_id,match_score,match_method,review_status,created_at,updated_at) "
                   f"VALUES('transfer',?,?,?,?,?,?,?) ON CONFLICT(link_type,from_transaction_id,to_transaction_id) {self._conflict(status)}",
                   (outflow["id"], inflow["id"], points, method, status, now(), now()))
        kind = "payment" if inflow["account_type"] == "credit_card" else "transfer"
        for row in (outflow, inflow):
            if row["transaction_type"] not in NON_SPENDING:
                db.execute("UPDATE transactions SET transaction_type=?,updated_at=? WHERE id=? AND review_status<>'verified'", (kind, now(), row["id"]))
        self.resolve(db, "ambiguous_transfer", "transaction", outflow["id"])

    def link_investment(self, db, event_id, transaction, how="auto"):
        """A bank or card line that paid into an investment account kept outside the ledger: the money moved, it wasn't spent.
        The line's type before the match is kept, so undoing it restores the line."""
        db.execute("UPDATE investment_events SET transaction_id=?,transaction_previous_type=?,transaction_link=? WHERE id=?",
                   (transaction["id"], transaction["transaction_type"], how, event_id))
        if transaction["transaction_type"] not in NON_SPENDING:
            db.execute("UPDATE transactions SET transaction_type='transfer',updated_at=? WHERE id=? AND review_status<>'verified'", (now(), transaction["id"]))
        self.resolve(db, "ambiguous_investment_transfer", "investment_event", event_id)

    def unlink_investment(self, event_id):
        """The user's "not this payment": the line goes back to what it was (unless they verified it), the pair is never proposed
        again, and if other lines could have paid it Review asks which one; otherwise the contribution is left unmatched."""
        with self.store.connection() as db:
            event = db.execute("SELECT e.*,a.institution,a.currency FROM investment_events e JOIN investment_accounts a ON a.id=e.account_id WHERE e.id=?",
                               (event_id,)).fetchone()
            if event is None:
                raise ValueError("Investment activity not found.")
            if event["transaction_id"] is None:
                raise ValueError("No bank or card payment is matched to this.")
            db.execute("UPDATE transactions SET transaction_type=?,updated_at=? WHERE id=? AND transaction_type='transfer' AND review_status<>'verified' "
                       "AND ? IS NOT NULL", (event["transaction_previous_type"], now(), event["transaction_id"], event["transaction_previous_type"]))
            db.execute("INSERT OR IGNORE INTO investment_payment_rejections(event_id,transaction_id,created_at) VALUES(?,?,?)",
                       (event_id, event["transaction_id"], now()))
            db.execute("UPDATE investment_events SET transaction_id=NULL,transaction_previous_type=NULL,transaction_link=NULL WHERE id=?", (event_id,))
            candidates = [row["id"] for row in self.investment_candidates(db, event)]
            if candidates:  # After an undo the user chooses, even between one.
                self.issue(db, "ambiguous_investment_transfer", "investment_event", event_id, candidates)
            else:
                db.execute("INSERT INTO reconciliation_issues(issue_type,record_type,record_id,detail_json,status,resolution,created_at,updated_at) "
                           "VALUES('ambiguous_investment_transfer','investment_event',?,?,'resolved','left_unmatched',?,?) ON CONFLICT(issue_type,record_type,record_id) "
                           "DO UPDATE SET status='resolved',resolution='left_unmatched',updated_at=excluded.updated_at",
                           (event_id, json.dumps({"candidate_transaction_ids": []}), now(), now()))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('investment_payment_link',?,'linked','unlinked',?,?)",
                       (event_id, f"Transaction {event['transaction_id']} is not this payment.", now()))
        return {"event_id": event_id, "question": bool(candidates), "candidates": len(candidates)}

    @staticmethod
    def investment_candidates(db, event):
        """Bank or card outflows that could have paid an investment event: exactly its amount within a few days, not paying another,
        not in a ledger transfer, and never a pair the user rejected. A purchase line counts only when it names the institution."""
        rows = db.execute(
            "SELECT t.*,a.account_type FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.currency=? AND t.amount_minor=? "
            f"AND {MATCHABLE} AND t.posted_date BETWEEN ? AND ? AND t.transaction_type IN ('transfer','withdrawal','payment','purchase','other') "
            "AND NOT EXISTS(SELECT 1 FROM investment_events o WHERE o.transaction_id=t.id) AND NOT EXISTS(SELECT 1 FROM transaction_links l "
            "WHERE l.link_type='transfer' AND (l.from_transaction_id=t.id OR l.to_transaction_id=t.id) AND l.review_status<>'rejected') "
            "AND NOT EXISTS(SELECT 1 FROM investment_payment_rejections r WHERE r.event_id=? AND r.transaction_id=t.id)",
            (event["currency"], -event["amount_minor"], shift(event["event_date"], -TRANSFER_DAYS), shift(event["event_date"], TRANSFER_DAYS), event["id"])).fetchall()
        return [row for row in rows if row["transaction_type"] != "purchase" or name_tokens(event["institution"]) & name_tokens(row["description_raw"])]

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
        unlinked = ("coalesce(t.transaction_date,t.posted_date) BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l "
                    "WHERE l.transaction_id=t.id AND (l.review_status<>'rejected' OR l.receipt_id=?))")
        for receipt in receipts:
            window = (receipt["purchase_date"], shift(receipt["purchase_date"], RECEIPT_POSTING_DAYS), receipt["id"])
            candidates = db.execute(f"SELECT t.* FROM transactions t WHERE t.currency=? AND t.amount_minor=? AND {MATCHABLE} AND {unlinked}",
                                    (receipt["currency"], -receipt["total_minor"], *window)).fetchall()
            scored = sorted(((*receipt_match(receipt, transaction), transaction) for transaction in candidates), key=lambda item: -item[0])
            # One candidate, or one candidate clearly better (by at least one whole rule) than the rest.
            if scored and (len(scored) == 1 or scored[0][0] >= 80 and scored[0][0] - scored[1][0] >= 20):
                points, method, transaction = scored[0]
                self.link_receipt(db, receipt, transaction, points, method)
                created += 1
            elif len(scored) > 1:
                self.issue(db, "ambiguous_receipt_match", "receipt", receipt["id"], [item[2]["id"] for item in scored])
            elif receipt["total_minor"] > 0 and receipt["merchant"]:
                # No exact charge: a same-merchant charge a little larger is probably this purchase with a tip or
                # conversion. Counting both would count the purchase twice, so the user decides.
                near = [row for row in db.execute(
                    f"SELECT t.* FROM transactions t WHERE t.currency=? AND -t.amount_minor>? AND -t.amount_minor*100<=?*{NEAR_PERCENT} AND {MATCHABLE} AND {unlinked}",
                    (receipt["currency"], receipt["total_minor"], receipt["total_minor"], *window))
                        if name_tokens(receipt["merchant"]) & name_tokens(row["description_raw"])]
                if near:
                    self.issue(db, "ambiguous_receipt_match", "receipt", receipt["id"], [row["id"] for row in near])
        return created

    # Statements waiting for the user ---------------------------------------------------

    def awaiting(self):
        """Recorded bank and card statements whose lines wait for the user to reconcile receipts against them."""
        with self.store.connection() as db:
            rows = db.execute("SELECT s.id,s.statement_type,s.period_start,s.period_end,s.currency,s.document_id,a.institution,a.display_name AS account,"
                              "(SELECT count(*) FROM transactions t WHERE t.statement_id=s.id AND t.origin='extraction' AND t.review_status<>'rejected') AS lines,"
                              "(SELECT count(*) FROM receipts r WHERE r.review_status<>'rejected' AND r.currency=s.currency AND r.purchase_date "
                              "BETWEEN coalesce(s.period_start,s.period_end) AND s.period_end AND NOT EXISTS(SELECT 1 FROM transaction_receipt_links l "
                              "WHERE l.receipt_id=r.id AND l.review_status<>'rejected')) AS receipts "
                              "FROM statements s JOIN accounts a ON a.id=s.account_id WHERE s.reconciliation='awaiting' AND s.review_status<>'rejected' "
                              "ORDER BY s.period_end,s.id").fetchall()
        return [dict(row) for row in rows]

    def reconcile_statement(self, statement_id):
        """The user's yes: release the statement's lines, match receipts against them, and report what happened."""
        with self.store.connection() as db:
            if db.execute("UPDATE statements SET reconciliation='reconciled',updated_at=? WHERE id=? AND review_status<>'rejected'",
                          (now(), statement_id)).rowcount == 0:
                raise ValueError("Statement not found.")
        summary = self.run("manual")
        with self.store.connection() as db:
            lines = [row[0] for row in db.execute("SELECT id FROM transactions WHERE statement_id=? AND origin='extraction' AND review_status<>'rejected' "
                                                  "AND amount_minor<0", (statement_id,))]
            marks = ",".join("?" * len(lines))
            matched = db.execute(f"SELECT count(*) FROM transaction_receipt_links WHERE review_status<>'rejected' AND transaction_id IN ({marks})",
                                 lines).fetchone()[0] if lines else 0
            questions = sum(1 for (detail,) in db.execute("SELECT detail_json FROM reconciliation_issues WHERE issue_type='ambiguous_receipt_match' AND status='open'")
                            if set(json.loads(detail)["candidate_transaction_ids"]) & set(lines))
        return {"statement_id": statement_id, "charges": len(lines), "matched_receipts": matched, "questions": questions,
                "charges_without_receipt": len(lines) - matched, "summary": summary}

    def transfers(self, db):
        """Equal and opposite amounts between two owned accounts within a few days."""
        created = 0
        outflows = db.execute("SELECT t.*,a.account_type FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.amount_minor<0 "
                              f"AND {MATCHABLE} AND t.transaction_type IN ('transfer','payment','purchase','withdrawal') AND NOT EXISTS("
                              "SELECT 1 FROM transaction_links l WHERE l.link_type='transfer' AND l.from_transaction_id=t.id AND l.review_status<>'rejected')").fetchall()
        for outflow in outflows:
            candidates = db.execute(
                "SELECT t.*,a.account_type FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.account_id<>? AND t.currency=? "
                f"AND t.amount_minor=? AND {MATCHABLE} AND t.posted_date BETWEEN ? AND ? AND NOT EXISTS(SELECT 1 FROM transaction_links l "
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

    def investment_transfers(self, db):
        """Money paid into an investment account kept outside the ledger (a brokerage, an IRA, TreasuryDirect, a bank CD): a bank or
        card outflow of exactly a contribution or deposit you made, or of a CD or Treasury bought, within a few days of it. A
        purchase line counts only when it names the institution, so a same-sized store charge is never taken for one. Money paid
        between an account and its linked savings account is already a ledger transfer."""
        created = 0
        events = db.execute("SELECT e.*,a.institution,a.currency FROM investment_events e JOIN investment_accounts a ON a.id=e.account_id "
                            "JOIN investment_kinds k ON k.key=a.kind WHERE e.transaction_id IS NULL AND e.review_status<>'rejected' "
                            "AND a.ledger_account_id IS NULL AND a.archived_at IS NULL AND ((e.event_type='contribution' AND e.contribution_source='personal') "
                            "OR e.event_type='transfer_in' OR (e.event_type='buy' AND e.confirmation_id IS NOT NULL AND k.value_model='accrual')) "
                            # Left unmatched by the user, or a question they are being asked (after an undo it asks even about one line).
                            "AND NOT EXISTS(SELECT 1 FROM reconciliation_issues i WHERE i.issue_type='ambiguous_investment_transfer' "
                            "AND i.record_type='investment_event' AND i.record_id=e.id AND (i.resolution='left_unmatched' OR i.status='open'))").fetchall()
        for event in events:
            plausible = self.investment_candidates(db, event)
            if len(plausible) == 1:
                self.link_investment(db, event["id"], plausible[0])
                created += 1
            elif len(plausible) > 1:
                self.issue(db, "ambiguous_investment_transfer", "investment_event", event["id"], [row["id"] for row in plausible])
        return created

    def refunds(self, db):
        """A credit from the same merchant on the same account after a purchase at least as large."""
        created = 0
        credits = db.execute(f"SELECT t.* FROM transactions t WHERE t.amount_minor>0 AND t.transaction_type='refund' AND {MATCHABLE} "
                             "AND NOT EXISTS(SELECT 1 FROM transaction_links l WHERE l.link_type='refund' AND l.to_transaction_id=t.id AND l.review_status<>'rejected')").fetchall()
        for credit in credits:
            candidates = db.execute(
                "SELECT t.* FROM transactions t WHERE t.account_id=? AND t.currency=? AND t.amount_minor<0 AND -t.amount_minor>=? "
                f"AND t.transaction_type='purchase' AND {MATCHABLE} AND t.posted_date BETWEEN ? AND ? AND NOT EXISTS("
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
        known = self.bills(db)
        groups = defaultdict(list)
        for row in db.execute(f"SELECT t.* FROM transactions t WHERE t.amount_minor<0 AND t.transaction_type IN ('purchase','fee') AND {COUNTABLE} ORDER BY t.posted_date,t.id"):
            key = payee_key(row["description_raw"])
            if key:
                groups[(row["account_id"], key, row["amount_minor"], row["currency"])].append(row)
        found = 0
        for (account_id, key, amount, currency), rows in groups.items():
            gaps = [gap(later["posted_date"], earlier["posted_date"]) for earlier, later in zip(rows, rows[1:])]
            frequency = next((name for name, (low, high) in CADENCES.items() if len(rows) >= 3 and all(low <= days <= high for days in gaps)), None)
            if frequency is None:
                continue
            merchant = self.ledger.merchant(db, key)
            # A bill already known for this payee (proposed from a receipt or one payment, or decided by the user) is tracked, not re-proposed.
            if any(bill_matches(bill, key, currency) and (bill["merchant_id"], bill["account_id"], bill["frequency"]) != (merchant, account_id, frequency)
                   for bill in known):
                continue
            next_due = due_after(rows[-1]["posted_date"], frequency)
            db.execute("INSERT INTO recurring_obligations(merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,next_due_date,status,"
                       "confidence_source,created_at,updated_at) VALUES(?,?,'subscription_or_bill',?,?,?,?,'proposed',?,?,?) "
                       "ON CONFLICT(merchant_id,account_id,currency,frequency) DO UPDATE SET next_due_date=excluded.next_due_date,updated_at=excluded.updated_at,"
                       "expected_amount_minor=CASE WHEN recurring_obligations.status='proposed' THEN excluded.expected_amount_minor ELSE recurring_obligations.expected_amount_minor END "
                       "WHERE recurring_obligations.status NOT IN ('rejected','ended')",
                       (merchant, account_id, -amount, currency, frequency, next_due, f"deterministic_cadence:{len(rows)}_payments", now(), now()))
            found += 1
        return found

    # Recurring bills from one payment ---------------------------------------------------
    # A receipt the model read as a scheduled bill payment, or a housing or insurance charge, proposes a recurring
    # bill after a single payment. Later payments to the same payee, within BILL_RANGE of the usual amount, keep it
    # current: last paid, next due, and an expected amount that follows recent payments (utilities vary).

    @staticmethod
    def bills(db):
        return [dict(row) for row in db.execute("SELECT o.*,m.canonical_name AS merchant FROM recurring_obligations o JOIN merchants m ON m.id=o.merchant_id")]

    def propose_bills(self, db):
        """Proposals from single payments. A payee with any bill already, including one the user rejected, gets none."""
        known, created = self.bills(db), 0

        def propose(merchant_id, account_id, amount, currency, frequency, paid, category, source, receipt_id=None):
            nonlocal created
            cursor = db.execute(
                "INSERT OR IGNORE INTO recurring_obligations(merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,next_due_date,"
                "status,confidence_source,category,last_paid_date,source_receipt_id,created_at,updated_at) VALUES(?,?,'bill',?,?,?,?,'proposed',?,?,?,?,?,?)",
                (merchant_id, account_id, amount, currency, frequency, due_after(paid, frequency), source, category, paid, receipt_id, now(), now()))
            if cursor.rowcount:
                created += 1
                known.append(dict(db.execute("SELECT o.*,m.canonical_name AS merchant FROM recurring_obligations o JOIN merchants m ON m.id=o.merchant_id "
                                             "WHERE o.id=?", (cursor.lastrowid,)).fetchone()))

        marks = ",".join("?" * len(BILL_CATEGORIES))
        for receipt in db.execute("SELECT r.*,m.canonical_name AS merchant FROM receipts r JOIN merchants m ON m.id=r.merchant_id "
                                  f"WHERE (r.recurrence IS NOT NULL OR r.category IN ({marks})) AND r.review_status='verified' AND r.total_minor>0 "
                                  "AND r.purchase_date IS NOT NULL ORDER BY r.purchase_date DESC,r.id", BILL_CATEGORIES).fetchall():
            if not any(bill_matches(bill, receipt["merchant"], receipt["currency"]) for bill in known):
                propose(receipt["merchant_id"], None, receipt["total_minor"], receipt["currency"], receipt["recurrence"] or "monthly",
                        receipt["purchase_date"], receipt["category"], "receipt_single_payment", receipt["id"])
        for row in db.execute(f"SELECT t.*,m.canonical_name AS merchant,{TRANSACTION_CATEGORY} AS spending_category FROM transactions t "
                              f"LEFT JOIN merchants m ON m.id=t.merchant_id WHERE {COUNTABLE} AND t.amount_minor<0 AND t.transaction_type IN ('purchase','fee') "
                              f"AND {TRANSACTION_CATEGORY} IN ({marks}) ORDER BY t.posted_date DESC,t.id DESC",
                              BILL_CATEGORIES).fetchall():
            name = row["merchant"] or payee_key(row["description_raw"])
            if name and not any(bill_matches(bill, f"{row['description_raw']} {name}", row["currency"]) for bill in known):
                # How often is unknown from one charge: monthly, which the user changes when confirming.
                propose(row["merchant_id"] or self.ledger.merchant(db, name), row["account_id"], -row["amount_minor"], row["currency"], "monthly",
                        row["transaction_date"] or row["posted_date"], row["spending_category"], "category_single_payment")
        # Payees the local model read as ongoing services (finance/recurring_scan.py); its answers are stored, so this stays deterministic.
        answers = {(row["payee_key"], row["currency"]): row for row in db.execute("SELECT * FROM payee_recurrence WHERE recurrence IS NOT NULL")}
        if answers:
            for row in db.execute(f"SELECT t.*,m.canonical_name AS merchant FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id "
                                  f"WHERE {COUNTABLE} AND t.amount_minor<0 AND t.transaction_type IN ('purchase','fee') "
                                  "ORDER BY t.posted_date DESC,t.id DESC").fetchall():
                answer = answers.get((payee_key(row["description_raw"]), row["currency"]))
                name = row["merchant"] or payee_key(row["description_raw"])
                if answer and not any(bill_matches(bill, f"{row['description_raw']} {name}", row["currency"]) for bill in known):
                    propose(row["merchant_id"] or self.ledger.merchant(db, name), row["account_id"], -row["amount_minor"], row["currency"],
                            answer["recurrence"], row["transaction_date"] or row["posted_date"], answer["category"], "statement_model")
        return created

    def propose_terms(self, terms, source):
        """Recurring payment terms read from a contract, lease or policy (documents/extraction.py), each a proposal.
        A payee that already has a bill, including one the user rejected, gets none. Returns the new ids."""
        created = []
        with self.store.connection() as db:
            known = self.bills(db)
            for term in terms:
                if any(bill_matches(bill, term["payee"], term["currency"]) for bill in known):
                    continue
                cursor = db.execute(
                    "INSERT OR IGNORE INTO recurring_obligations(merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,"
                    "next_due_date,status,confidence_source,category,source_document_id,evidence,created_at,updated_at) "
                    "VALUES(?,NULL,'bill',?,?,?,?,'proposed','contract_terms',?,?,?,?,?)",
                    (self.ledger.merchant(db, term["payee"]), term["amount_minor"], term["currency"], term["frequency"], term["next_due_date"],
                     term["category"], source["document_id"], term["evidence"], now(), now()))
                if cursor.rowcount:
                    created.append(cursor.lastrowid)
                    known.append(dict(db.execute("SELECT o.*,m.canonical_name AS merchant FROM recurring_obligations o JOIN merchants m ON m.id=o.merchant_id "
                                                 "WHERE o.id=?", (cursor.lastrowid,)).fetchone()))
        return created

    def track_bills(self, db):
        """Bring every open bill up to date with its latest matched payment."""
        for bill in self.bills(db):
            if bill["status"] not in ("proposed", "verified"):
                continue
            paid = bill_payments(db, bill)
            if not paid:
                continue
            latest = paid[-1]["day"]
            recent = [payment["amount"] for payment in paid[-3:]]
            expected = int((Decimal(sum(recent)) / len(recent)).to_integral_value(ROUND_HALF_EVEN))
            update = (expected, latest, due_after(latest, bill["frequency"]))
            if update != (bill["expected_amount_minor"], bill["last_paid_date"], bill["next_due_date"]):
                db.execute("UPDATE recurring_obligations SET expected_amount_minor=?,last_paid_date=?,next_due_date=?,updated_at=? WHERE id=?",
                           (*update, now(), bill["id"]))

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
            if kind == "receipt":
                self.ledger.refresh_splits(db, link["receipt_id"])
            if status == "rejected" and kind == "transfer":
                for transaction in (link["from_transaction_id"], link["to_transaction_id"]):
                    row = self.transaction(db, transaction)
                    if row["review_status"] != "verified":
                        db.execute("UPDATE transactions SET transaction_type=?,updated_at=? WHERE id=?",
                                   (classify_transaction(row["description_raw"], row["amount_minor"], row["account_type"]), now(), transaction))
            if status == "rejected" and kind == "receipt":  # The merchant name came from the receipt; rules decide again without it.
                self.ledger.apply_rules(db, [link["transaction_id"]])
                from .tax_tags import TaxTags  # tax_tags imports this module.
                TaxTags(self.ledger.store).apply_rules(db, [link["transaction_id"]])
        return {"kind": kind, "id": link_id, "review_status": status}

    def review_obligation(self, obligation_id, status, note="", frequency=None):
        """Confirm, reject or end a detected recurring payment, optionally correcting how often it recurs.
        Rejected and ended ones are never re-proposed."""
        if status not in OBLIGATION_DECISIONS:
            raise ValueError("Choose confirm, not recurring, or ended.")
        if frequency is not None and frequency not in FREQUENCIES:
            raise ValueError("Choose weekly, monthly, quarterly, every six months or yearly.")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM recurring_obligations WHERE id=?", (obligation_id,)).fetchone()
            if row is None:
                raise ValueError("Recurring payment not found.")
            if frequency and frequency != row["frequency"]:
                if db.execute("SELECT 1 FROM recurring_obligations WHERE merchant_id=? AND account_id IS ? AND currency=? AND frequency=? AND id<>?",
                              (row["merchant_id"], row["account_id"], row["currency"], frequency, obligation_id)).fetchone():
                    raise ValueError("This payee already has a recurring payment with that frequency.")
                paid = row["last_paid_date"]
                db.execute("UPDATE recurring_obligations SET frequency=?,next_due_date=coalesce(?,next_due_date) WHERE id=?",
                           (frequency, due_after(paid, frequency) if paid else None, obligation_id))
                note = f"How often: {frequency}. {note}".strip()
            db.execute("UPDATE recurring_obligations SET status=?,updated_at=? WHERE id=?", (status, now(), obligation_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('recurring_obligation',?,?,?,?,?)",
                       (obligation_id, row["status"], status, note[:1000], now()))
        return {"id": obligation_id, "status": status}
