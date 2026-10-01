"""Tax tags (docs/taxes.md): marking ledger items as write-offs, business income, credit spending or tax paid ahead.

A tag sits on one item: a bank line, a receipt, or one line of a receipt. Three ways to tag:
- by hand: counts at once;
- a tax rule, matched like category rules (every word of the pattern in the bank line's description and merchant; the
  most words wins, then the newest): counts at once, and follows the rule when it changes;
- a suggestion: a bank line from a payee you tagged before, or one that looks like an IRS or state tax payment. It
  waits in Review; "Not a write-off" is remembered, so that payee isn't suggested again.
A tag set by hand, or a suggestion decided in Review, is never changed by a rule.

The same money is counted once: tags on a receipt's lines replace a tag on the receipt, and a receipt's tags replace a
tag on the bank line it is matched to.
"""

from decimal import ROUND_HALF_EVEN, Decimal
import re

from ..core.money import format_minor, money, to_minor
from ..library.storage import now
from .ledger import COUNTABLE, normalize_name
from .reconcile import payee_key
from .tax_lines import BUSINESS_KINDS, INCOME_KINDS, KINDS, LINES, SHARE_BP, check, labels

TARGETS = ("transaction", "receipt", "receipt_item")
# Bank lines that are tax payments made ahead: IRS Direct Pay ("IRS USATAXPYMT") and EFTPS, and state revenue departments.
PAYMENT_PATTERNS = ((re.compile(r"\bIRS\b.*\b(USATAXPYMT|TAX ?PYMT|TAX ?PAYMENT|EFTPS)\b|\bEFTPS\b"), "federal_estimated", "looks like a payment to the IRS"),
                    (re.compile(r"\b(DEPT|DEPARTMENT) OF (REVENUE|TAXATION)\b|\bFRANCHISE TAX\b|\bTAXATION AND FINANCE\b|\bSTATE TAX PAYMENT\b"),
                     "state_estimated", "looks like a payment to a state tax department"))


def counted(kind, line, amount):
    """The part of a tagged amount the return counts (business meals: 50%)."""
    share = SHARE_BP.get((kind, line))
    return amount if share is None else int((Decimal(amount) * share / 10000).to_integral_value(ROUND_HALF_EVEN))


class TaxTags:
    def __init__(self, store):
        self.store = store

    # Businesses -------------------------------------------------------------------
    # Contract (1099) work is a business to the IRS: it gets a Schedule C, even without a company.

    def businesses(self, include_archived=False):
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM businesses" + ("" if include_archived else " WHERE archived_at IS NULL") + " ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

    def add_business(self, name):
        name = " ".join((name or "").split())
        if not name or len(name) > 60:
            raise ValueError("Name the business in 1 to 60 characters, e.g. Contract work.")
        with self.store.connection() as db:
            business_id = db.execute("INSERT INTO businesses(name,created_at) VALUES(?,?)", (name, now())).lastrowid
        return {"id": business_id, "name": name}

    def rename_business(self, business_id, name):
        name = " ".join((name or "").split())
        if not name or len(name) > 60:
            raise ValueError("Name the business in 1 to 60 characters.")
        with self.store.connection() as db:
            if db.execute("UPDATE businesses SET name=? WHERE id=?", (name, business_id)).rowcount == 0:
                raise ValueError("Business not found.")
        return {"id": business_id, "name": name}

    def archive_business(self, business_id):
        """Stops offering it for new tags; its tags keep counting."""
        with self.store.connection() as db:
            if db.execute("UPDATE businesses SET archived_at=? WHERE id=?", (now(), business_id)).rowcount == 0:
                raise ValueError("Business not found.")
        return {"id": business_id, "archived": True}

    def _business(self, db, business_id):
        if business_id is not None and db.execute("SELECT 1 FROM businesses WHERE id=?", (business_id,)).fetchone() is None:
            raise ValueError("Business not found.")

    # Items -------------------------------------------------------------------------

    @staticmethod
    def target(db, target_type, target_id):
        """What a tag sits on: its date, words, full amount (positive), direction and currency."""
        if target_type == "transaction":
            row = db.execute("SELECT t.posted_date AS day,t.amount_minor,t.currency,t.description_raw,m.canonical_name AS merchant,a.display_name AS account "
                             "FROM transactions t JOIN accounts a ON a.id=t.account_id LEFT JOIN merchants m ON m.id=t.merchant_id WHERE t.id=?", (target_id,)).fetchone()
            if row is None:
                raise ValueError("Transaction not found.")
            return {"type": target_type, "id": target_id, "date": row["day"], "amount_minor": abs(row["amount_minor"]), "inflow": row["amount_minor"] > 0,
                    "currency": row["currency"], "description": row["merchant"] or row["description_raw"], "detail": row["account"]}
        if target_type == "receipt":
            row = db.execute("SELECT r.purchase_date,r.total_minor,r.currency,m.canonical_name AS merchant FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id "
                             "WHERE r.id=?", (target_id,)).fetchone()
            if row is None:
                raise ValueError("Receipt not found.")
            if row["purchase_date"] is None or row["total_minor"] is None:
                raise ValueError("The receipt's date or total wasn't read; correct it before tagging.")
            return {"type": target_type, "id": target_id, "date": row["purchase_date"], "amount_minor": abs(row["total_minor"]), "inflow": False,
                    "currency": row["currency"], "description": row["merchant"] or "Receipt", "detail": "Receipt"}
        if target_type == "receipt_item":
            row = db.execute("SELECT i.description,i.line_total_minor,coalesce(i.discount_minor,0) AS discount,r.id AS receipt_id,r.purchase_date,r.currency,"
                             "m.canonical_name AS merchant,(SELECT sum(s.amount_minor) FROM category_splits s WHERE s.receipt_item_id=i.id AND s.transaction_id IS NULL) AS split "
                             "FROM receipt_items i JOIN receipts r ON r.id=i.receipt_id LEFT JOIN merchants m ON m.id=r.merchant_id WHERE i.id=?", (target_id,)).fetchone()
            if row is None:
                raise ValueError("Receipt line not found.")
            if row["purchase_date"] is None:
                raise ValueError("The receipt's date wasn't read; correct it before tagging.")
            # The line's share of the receipt, with its part of tax and tip, when the receipt has been split; else its printed total.
            amount = row["split"] if row["split"] is not None else (row["line_total_minor"] or 0) - row["discount"]
            return {"type": target_type, "id": target_id, "date": row["purchase_date"], "amount_minor": abs(amount), "inflow": False,
                    "currency": row["currency"], "description": row["description"], "detail": row["merchant"] or "Receipt", "receipt_id": row["receipt_id"]}
        raise ValueError("Tag a transaction, a receipt or a receipt line.")

    def _write(self, db, target, kind, line, business_id, amount, source, status, rule_id=None, reason="", note=""):
        column = f"{target['type']}_id"
        existing = db.execute(f"SELECT id FROM tax_tags WHERE {column}=?", (target["id"],)).fetchone()
        values = {"kind": kind, "line": line, "business_id": business_id, "amount_minor": amount, "currency": target["currency"], "tax_date": target["date"],
                  "source": source, "rule_id": rule_id, "review_status": status, "reason": reason, "note": note, "updated_at": now()}
        if existing:
            db.execute(f"UPDATE tax_tags SET {','.join(f'{key}=?' for key in values)} WHERE id=?", (*values.values(), existing["id"]))
            return existing["id"]
        return db.execute(f"INSERT INTO tax_tags({column},{','.join(values)},created_at) VALUES(?,{','.join('?' * len(values))},?)",
                          (target["id"], *values.values(), now())).lastrowid

    def tag(self, target_type, target_id, kind, line, business_id=None, amount=None, note=""):
        """Your own tag: it counts at once, and no rule changes it."""
        check(kind, line, business_id)
        with self.store.connection() as db:
            self._business(db, business_id)
            target = self.target(db, target_type, target_id)
            value = target["amount_minor"] if amount is None else to_minor(amount, target["currency"])
            if value < 0:
                raise ValueError("Enter the amount that counts, zero or more.")
            if value > target["amount_minor"] and target["amount_minor"]:
                raise ValueError(f"The amount can't be more than the item's {format_minor(target['amount_minor'], target['currency'])}.")
            if (kind in INCOME_KINDS) != target["inflow"]:
                raise ValueError("Business income is money coming in; the other kinds are money going out.")
            tag_id = self._write(db, target, kind, line, business_id, value, "user", "verified", note=(note or "")[:200])
        return self.get(tag_id)

    def not_a_write_off(self, tag_id):
        """The item isn't for taxes. Kept as rejected, so the same payee isn't suggested again."""
        with self.store.connection() as db:
            row = db.execute("SELECT review_status FROM tax_tags WHERE id=?", (tag_id,)).fetchone()
            if row is None:
                raise ValueError("Tag not found.")
            db.execute("UPDATE tax_tags SET review_status='rejected',source=CASE WHEN source='rule' THEN 'user' ELSE source END,updated_at=? WHERE id=?", (now(), tag_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('tax_tag',?,?,'rejected','',?)",
                       (tag_id, row["review_status"], now()))
        return self.get(tag_id)

    def review(self, tag_id, status, rule_words=None):
        """Decide a suggestion. Confirming it can also make a rule for every bank line with these words."""
        if status not in ("verified", "rejected"):
            raise ValueError("Tag it or say it isn't a write-off.")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM tax_tags WHERE id=?", (tag_id,)).fetchone()
            if row is None:
                raise ValueError("Tag not found.")
            db.execute("UPDATE tax_tags SET review_status=?,updated_at=? WHERE id=?", (status, now(), tag_id))
            db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,note,created_at) VALUES('tax_tag',?,?,?,'',?)",
                       (tag_id, row["review_status"], status, now()))
        if status == "verified" and rule_words:
            self.add_rule(rule_words, row["kind"], row["line"], row["business_id"])
        return self.get(tag_id)

    def on(self, target_type, target_id):
        """The tag on one item, or None."""
        if target_type not in TARGETS:
            raise ValueError("Tag a transaction, a receipt or a receipt line.")
        with self.store.connection() as db:
            row = db.execute(f"SELECT id FROM tax_tags WHERE {target_type}_id=?", (target_id,)).fetchone()
        return self.get(row["id"]) if row else None

    def get(self, tag_id):
        found = self.list(tag_id=tag_id)
        if not found:
            raise ValueError("Tag not found.")
        return found[0]

    def list(self, status=None, year=None, tag_id=None, kind=None, receipt_id=None):
        """Tags, newest first. receipt_id: the tags on one receipt and on its lines."""
        clauses, params = [], []
        for clause, value in (("g.review_status=?", status), ("substr(g.tax_date,1,4)=?", str(year) if year else None), ("g.id=?", tag_id), ("g.kind=?", kind),
                              ("(g.receipt_id=? OR g.receipt_item_id IN (SELECT id FROM receipt_items WHERE receipt_id=?))", receipt_id)):
            if value is not None:
                clauses.append(clause)
                params += [value] * clause.count("?")
        names = labels()
        with self.store.connection() as db:
            rows = [dict(row) for row in db.execute("SELECT g.*,b.name AS business FROM tax_tags g LEFT JOIN businesses b ON b.id=g.business_id"
                                                    + (f" WHERE {' AND '.join(clauses)}" if clauses else "") + " ORDER BY g.tax_date DESC,g.id DESC", params)]
            for row in rows:
                target_type = next(name for name in TARGETS if row[f"{name}_id"] is not None)
                try:
                    target = self.target(db, target_type, row[f"{target_type}_id"])
                except ValueError:
                    target = {"type": target_type, "id": row[f"{target_type}_id"], "description": "", "detail": "", "amount_minor": row["amount_minor"]}
                row.update(target=target, kind_label=KINDS[row["kind"]], line_label=names[row["kind"]].get(row["line"], row["line"]),
                           counted_minor=counted(row["kind"], row["line"], row["amount_minor"]))
                row["display"] = {key: format_minor(row[key], row["currency"]) for key in ("amount_minor", "counted_minor")}
        return rows

    # Rules -------------------------------------------------------------------------

    def rules(self):
        with self.store.connection() as db:
            rows = db.execute("SELECT r.*,a.display_name AS account,b.name AS business,(SELECT count(*) FROM tax_tags g WHERE g.rule_id=r.id) AS tagged "
                              "FROM tax_rules r LEFT JOIN accounts a ON a.id=r.account_id LEFT JOIN businesses b ON b.id=r.business_id ORDER BY r.pattern").fetchall()
        names = labels()
        return [{**dict(row), "kind_label": KINDS[row["kind"]], "line_label": names[row["kind"]].get(row["line"], row["line"])} for row in rows]

    def _rule_values(self, db, pattern, kind, line, business_id, account_id):
        key = normalize_name(pattern)
        if not key:
            raise ValueError("Enter the words the rule matches, such as ADOBE.")
        check(kind, line, business_id)
        self._business(db, business_id)
        if account_id is not None and db.execute("SELECT 1 FROM accounts WHERE id=?", (account_id,)).fetchone() is None:
            raise ValueError("Account not found.")
        return {"pattern": key, "kind": kind, "line": line, "business_id": business_id, "account_id": account_id}

    def add_rule(self, pattern, kind, line, business_id=None, account_id=None):
        with self.store.connection() as db:
            values = self._rule_values(db, pattern, kind, line, business_id, account_id)
            if db.execute("SELECT 1 FROM tax_rules WHERE pattern=? AND coalesce(account_id,0)=coalesce(?,0)", (values["pattern"], account_id)).fetchone():
                raise ValueError("A tax rule for these words already exists. Change that rule instead.")
            rule_id = db.execute(f"INSERT INTO tax_rules({','.join(values)},created_at,updated_at) VALUES({','.join('?' * len(values))},?,?)",
                                 (*values.values(), now(), now())).lastrowid
            changed = self.apply_rules(db)
        return {**next(rule for rule in self.rules() if rule["id"] == rule_id), "changed": changed}

    def update_rule(self, rule_id, pattern, kind, line, business_id=None, account_id=None):
        with self.store.connection() as db:
            values = self._rule_values(db, pattern, kind, line, business_id, account_id)
            if db.execute("SELECT 1 FROM tax_rules WHERE pattern=? AND coalesce(account_id,0)=coalesce(?,0) AND id<>?", (values["pattern"], account_id, rule_id)).fetchone():
                raise ValueError("Another tax rule already uses these words.")
            if db.execute(f"UPDATE tax_rules SET {','.join(f'{key}=?' for key in values)},updated_at=? WHERE id=?", (*values.values(), now(), rule_id)).rowcount == 0:
                raise ValueError("Rule not found.")
            changed = self.refresh(db)["rules"]
        return {**next(rule for rule in self.rules() if rule["id"] == rule_id), "changed": changed}

    def delete_rule(self, rule_id):
        """Its tags go to the next matching rule, or are removed (and may be suggested again)."""
        with self.store.connection() as db:
            if db.execute("DELETE FROM tax_rules WHERE id=?", (rule_id,)).rowcount == 0:
                raise ValueError("Rule not found.")
            changed = self.refresh(db)["rules"]
        return {"id": rule_id, "deleted": True, "changed": changed}

    @staticmethod
    def _lines(db, transaction_ids):
        clause, params = "", []
        if transaction_ids is not None:
            ids = sorted(set(transaction_ids))
            if not ids:
                return []
            clause, params = f" WHERE t.id IN ({','.join('?' * len(ids))})", ids
        return db.execute("SELECT t.id,t.account_id,t.amount_minor,t.description_raw,m.canonical_name,g.id AS tag_id,g.source,g.review_status "
                          "FROM transactions t LEFT JOIN merchants m ON m.id=t.merchant_id LEFT JOIN tax_tags g ON g.transaction_id=t.id" + clause, params).fetchall()

    def apply_rules(self, db, transaction_ids=None):
        """Give bank lines their best tax rule's tag, where no hand tag or decided suggestion stands. Returns lines changed."""
        rules = sorted(((set(row["pattern"].split()), dict(row)) for row in db.execute("SELECT * FROM tax_rules")),
                       key=lambda item: (len(item[0]), item[1]["id"]), reverse=True)
        changed = 0
        for row in self._lines(db, transaction_ids):
            if row["tag_id"] is not None and not (row["source"] == "rule" or (row["source"] == "suggestion" and row["review_status"] == "proposed")):
                continue
            words = set(normalize_name(f"{row['description_raw']} {row['canonical_name'] or ''}").split())
            match = next((rule for pattern, rule in rules if pattern <= words and rule["account_id"] in (None, row["account_id"])
                          and (rule["kind"] in INCOME_KINDS) == (row["amount_minor"] > 0)), None)
            if match:
                target = self.target(db, "transaction", row["id"])
                current = db.execute("SELECT rule_id,kind,line,business_id,amount_minor FROM tax_tags WHERE id=?", (row["tag_id"],)).fetchone() if row["tag_id"] else None
                if current is None or tuple(current) != (match["id"], match["kind"], match["line"], match["business_id"], target["amount_minor"]):
                    self._write(db, target, match["kind"], match["line"], match["business_id"], target["amount_minor"], "rule", "verified", match["id"],
                                f"Tax rule: {match['pattern']}")
                    changed += 1
            elif row["source"] == "rule":
                db.execute("DELETE FROM tax_tags WHERE id=?", (row["tag_id"],))
                changed += 1
        return changed

    def suggest(self, db, transaction_ids=None):
        """Propose tags for untagged bank lines: payees you tagged before, and tax payments made ahead. Returns how many."""
        known, refused = {}, set()
        for row in db.execute("SELECT g.kind,g.line,g.business_id,g.review_status,g.source,g.tax_date,t.description_raw FROM tax_tags g "
                              "JOIN transactions t ON t.id=g.transaction_id ORDER BY g.tax_date,g.id"):
            key = payee_key(row["description_raw"])
            if row["review_status"] == "rejected":
                refused.add(key)
            elif row["review_status"] == "verified" and row["source"] in ("user", "suggestion"):
                known[key] = dict(row)  # The latest one you tagged.
        names, made = labels(), 0
        for row in self._lines(db, transaction_ids):
            if row["tag_id"] is not None or not row["amount_minor"]:
                continue
            key, inflow = payee_key(row["description_raw"]), row["amount_minor"] > 0
            if key in refused:
                continue
            before = known.get(key)
            if before and (before["kind"] in INCOME_KINDS) == inflow:
                reason = (f"You tagged {before['description_raw']} on {before['tax_date']} as {names[before['kind']][before['line']]}; "
                          "this is the same payee.")
                suggestion = (before["kind"], before["line"], before["business_id"])
            else:
                text = normalize_name(row["description_raw"])
                found = next(((line, why) for pattern, line, why in PAYMENT_PATTERNS if pattern.search(text)), None) if not inflow else None
                if not found:
                    continue
                suggestion, reason = ("tax_payment", found[0], None), f"It {found[1]}: tax paid ahead of the return."
            target = self.target(db, "transaction", row["id"])
            self._write(db, target, *suggestion, target["amount_minor"], "suggestion", "proposed", reason=reason)
            made += 1
        return made

    def refresh(self, db, transaction_ids=None):
        """After bank lines are added or reconciled: rules first, then suggestions for what's still untagged."""
        return {"rules": self.apply_rules(db, transaction_ids), "suggested": self.suggest(db, transaction_ids)}

    # The year -----------------------------------------------------------------------

    def year(self, year, currency):
        """Confirmed tags that count in a tax year, by kind and line (and business), each item once. Items that don't count
        (a rejected bank line, an unconfirmed receipt) are left out."""
        rows = [row for row in self.list(status="verified", year=year) if row["currency"] == currency]
        notes = []
        with self.store.connection() as db:
            countable = {row[0] for row in db.execute(f"SELECT t.id FROM transactions t WHERE {COUNTABLE} AND substr(t.posted_date,1,4)=?", (str(year),))}
            receipts = {row[0]: row[1] for row in db.execute("SELECT id,review_status FROM receipts")}
            linked = {}  # receipt -> the bank lines it is matched to
            for row in db.execute("SELECT receipt_id,transaction_id FROM transaction_receipt_links WHERE review_status<>'rejected'"):
                linked.setdefault(row[0], set()).add(row[1])
        item_receipts = {row["target"].get("receipt_id") for row in rows if row["receipt_item_id"]}
        tagged_receipts = {row["receipt_id"] for row in rows if row["receipt_id"]} | item_receipts
        replaced = set()
        for receipt in tagged_receipts:
            replaced |= linked.get(receipt, set())
        kept = []
        for row in rows:
            if row["transaction_id"] and (row["transaction_id"] not in countable or row["transaction_id"] in replaced):
                if row["transaction_id"] in replaced:
                    notes.append(f"{row['target']['description']} on {row['tax_date']} is tagged on its receipt too; the receipt's tag counts.")
                continue
            if row["receipt_id"] and (receipts.get(row["receipt_id"]) != "verified" or row["receipt_id"] in item_receipts):
                continue
            if row["receipt_item_id"] and receipts.get(row["target"].get("receipt_id")) != "verified":
                continue
            kept.append(row)
        totals: dict = {}
        for row in kept:
            key = (row["kind"], row["line"], row["business_id"] if row["kind"] in BUSINESS_KINDS else None)
            entry = totals.setdefault(key, {"kind": row["kind"], "line": row["line"], "business_id": key[2], "business": row["business"] if key[2] else None,
                                            "kind_label": row["kind_label"], "line_label": row["line_label"], "amount_minor": 0, "counted_minor": 0, "items": 0,
                                            "tag_ids": []})
            entry["amount_minor"] += row["amount_minor"]
            entry["counted_minor"] += row["counted_minor"]
            entry["items"] += 1
            entry["tag_ids"].append(row["id"])
        order = {kind: index for index, kind in enumerate(LINES)}
        lines = sorted(totals.values(), key=lambda entry: (order[entry["kind"]], entry["business"] or "", [key for key, _, _ in LINES[entry["kind"]]].index(entry["line"])))
        for entry in lines:
            entry["amount"], entry["counted"] = money(entry["amount_minor"], currency), money(entry["counted_minor"], currency)
        return {"year": year, "currency": currency, "lines": lines, "notes": notes}
