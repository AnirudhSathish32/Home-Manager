"""Household items (docs/household-items.md): receipt lines resolved to products, and inventory.

Only the user's approval creates a product, an alias or an inventory lot. Resolutions from
the model, the alias table or a barcode lookup are proposals. Run-out answers and manual lot
updates are the user's own input and apply directly. Nothing here calls a model or the network.
"""

from datetime import date, timedelta
import json
import re
from statistics import median
import unicodedata

from typing import Literal

from pydantic import Field, field_validator

from .finance import normalize_name
from .receipt_schema import StrictModel
from .storage import now

CATEGORIES = ("produce", "dairy & eggs", "meat & seafood", "bakery", "pantry", "frozen", "snacks", "beverages",
              "household cleaning", "paper & disposables", "personal care", "health", "baby", "pet", "home maintenance", "other")
# Days to the first run-out question for a product with fewer than two finished lots.
FIRST_CHECK_DAYS = {"produce": 7, "dairy & eggs": 7, "meat & seafood": 7, "bakery": 7}
DEFAULT_FIRST_CHECK_DAYS = 28
BASE_INTERVAL_DAYS, MAX_INTERVAL_DAYS = 7, 182
LOT_EVENTS = ("still_have", "finished", "thrown_out", "reopened", "opened")
LOT_STATE = ("status", "closed_on", "closed_precision_days", "next_check_on", "check_interval_days", "opened_on")
# Food and drink are not tracked as opened or returnable; everything else is (docs/items-assets-search.md §5).
FOOD = ("produce", "dairy & eggs", "meat & seafood", "bakery", "pantry", "frozen", "snacks", "beverages")
OPENABLE = tuple(category for category in CATEGORIES if category not in FOOD)
RETURNS_CLOSING_DAYS = 14
# Return policies printed on receipts. Each pattern yields the number of days, or 0 for "no returns".
PRINTED_RETURNS = [
    (re.compile(r"\b(?:no returns?|all sales? (?:are )?final|non-?returnable)\b", re.IGNORECASE), lambda match: 0),
    (re.compile(r"\breturns?\b[^.\n]{0,60}?\b(?:within|up to|for|in)\s+(\d{1,3})\s+days?\b", re.IGNORECASE), lambda match: int(match.group(1))),
    (re.compile(r"\b(\d{1,3})[- ]days?\s+(?:return|refund|money[- ]back)", re.IGNORECASE), lambda match: int(match.group(1))),
]
CHECKIN_LIMIT = 15
# One-tap check-in answers -> (lot event, days before today, precision in days). "This week" is the midpoint of the last week.
CHECKIN_ANSWERS = {"still_have": ("still_have", 0, 0), "finished_today": ("finished", 0, 0), "finished_this_week": ("finished", 3, 3),
                   "thrown_out": ("thrown_out", 0, 0), "thrown_out_this_week": ("thrown_out", 3, 3)}


def printed_return_days(lines):
    """(days, quote) for a return policy printed on a receipt, or (None, None). 0 days means no returns.
    The first line that states a policy wins; implausible numbers (over two years) are ignored."""
    for text in lines:
        for pattern, days in PRINTED_RETURNS:
            match = pattern.search(text or "")
            if match and 0 <= days(match) <= 730:
                return days(match), " ".join(text.split())[:200]
    return None, None


def checkin_day(today: date, weekday: int) -> date:
    """The latest check-in day on or before today. weekday: Monday 0 … Sunday 6."""
    return today - timedelta(days=(today.weekday() - weekday) % 7)


def normalize_text(text) -> str:
    """Stable key for printed item text: case, punctuation and spacing removed; digits kept (1GL, 12CT)."""
    text = unicodedata.normalize("NFKC", text or "").upper()
    return " ".join("".join(char if char.isalnum() or char == "&" else " " for char in text).split())


def valid_gtin(code) -> bool:
    """UPC-A, EAN-8, EAN-13 or GTIN-14 with a correct check digit."""
    digits = "".join((code or "").split())
    if not digits.isdigit() or len(digits) not in (8, 12, 13, 14):
        return False
    body, check = digits[:-1], int(digits[-1])
    total = sum(int(digit) * (3 if index % 2 == 0 else 1) for index, digit in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def iso_day(value) -> date:
    return date.fromisoformat(value)


class ResolutionFields(StrictModel):
    name: str = Field(min_length=1, max_length=160)
    brand: str | None = Field(default=None, max_length=80)
    size_text: str | None = Field(default=None, max_length=40)
    category: Literal[*CATEGORIES]
    consumable: bool = Field(description="True for anything that can run out: food, cleaning supplies, toiletries, sealant.")
    barcode: str | None = Field(default=None, max_length=14)

    @field_validator("barcode")
    @classmethod
    def checked(cls, value):
        if value and not valid_gtin(value):
            raise ValueError("The barcode check digit does not validate.")
        return value or None


class ItemLedger:
    def __init__(self, store):
        self.store = store

    # Receipt lines ------------------------------------------------------------

    @staticmethod
    def _line(db, item_id):
        row = db.execute("SELECT i.*,r.merchant_id,r.purchase_date,r.currency,m.canonical_name AS merchant FROM receipt_items i "
                         "JOIN receipts r ON r.id=i.receipt_id LEFT JOIN merchants m ON m.id=r.merchant_id WHERE i.id=?", (item_id,)).fetchone()
        if row is None:
            raise ValueError("Receipt line not found.")
        return dict(row)

    def line(self, item_id):
        with self.store.connection() as db:
            return self._line(db, item_id)

    def lines(self, receipt_id):
        with self.store.connection() as db:
            rows = db.execute("SELECT i.*,(SELECT r.review_status FROM item_resolutions r WHERE r.receipt_item_id=i.id AND r.review_status<>'rejected' "
                              "ORDER BY r.review_status='verified' DESC,r.id DESC LIMIT 1) AS resolution_status FROM receipt_items i "
                              "WHERE i.receipt_id=? ORDER BY i.position", (receipt_id,))
            return [dict(row) for row in rows]

    def unresolved(self, receipt_id):
        """Lines with no open proposal and no approved product."""
        return [line for line in self.lines(receipt_id) if line["resolution_status"] is None]

    def known(self, item_id):
        """The alias or history match for a line, as proposal fields, or None. Deterministic; no network."""
        with self.store.connection() as db:
            line = self._line(db, item_id)
            text = normalize_text(line["description"])
            if line["merchant_id"] is not None:
                for column, value in (("product_code", line["product_code"]), ("normalized_text", text)):
                    if not value:
                        continue
                    row = db.execute(f"SELECT p.* FROM item_aliases a JOIN products p ON p.id=a.product_id WHERE a.merchant_id=? AND a.{column}=? "
                                     "ORDER BY a.id DESC LIMIT 1", (line["merchant_id"], value)).fetchone()
                    if row:
                        return {"method": "alias", "confidence": "high", "product_id": row["id"], **self._fields(row)}
            # The same printed code at another merchant identifies the same product.
            if line["product_code"]:
                row = db.execute("SELECT p.* FROM item_aliases a JOIN products p ON p.id=a.product_id WHERE a.product_code=? ORDER BY a.id DESC LIMIT 1",
                                 (line["product_code"],)).fetchone()
                if row:
                    return {"method": "history", "confidence": "medium", "product_id": row["id"], **self._fields(row)}
        return None

    def similar(self, item_id, limit=5):
        """Approved products whose printed text shares words with this line, most overlap first."""
        with self.store.connection() as db:
            line = self._line(db, item_id)
            words = {word for word in normalize_text(line["description"]).split() if len(word) > 1}
            rows = db.execute("SELECT a.normalized_text,a.merchant_id,m.canonical_name AS merchant,p.* FROM item_aliases a "
                              "JOIN products p ON p.id=a.product_id LEFT JOIN merchants m ON m.id=a.merchant_id ORDER BY a.id DESC LIMIT 5000").fetchall()
        scored = []
        for row in rows:
            overlap = len(words & set(row["normalized_text"].split()))
            if overlap:
                scored.append((overlap, row["merchant_id"] == line["merchant_id"], row))
        scored.sort(key=lambda value: (value[0], value[1]), reverse=True)
        return [{"printed_text": row["normalized_text"], "merchant": row["merchant"], "product_id": row["id"], **self._fields(row)}
                for _, _, row in scored[:limit]]

    @staticmethod
    def _fields(row):
        return {"name": row["name"], "brand": row["brand"], "size_text": row["size_text"], "category": row["category"],
                "consumable": bool(row["consumable"]), "barcode": row["barcode"]}

    # Proposals and review -----------------------------------------------------

    def propose(self, item_id, fields: ResolutionFields, method, confidence, sources=(), run_id=None, product_id=None):
        with self.store.connection() as db:
            self._line(db, item_id)
            if db.execute("SELECT 1 FROM item_resolutions WHERE receipt_item_id=? AND review_status IN ('proposed','verified')", (item_id,)).fetchone():
                raise ValueError("This line already has a proposal or an approved product.")
            rejected = {normalize_text(row[0]) for row in db.execute("SELECT name FROM item_resolutions WHERE receipt_item_id=? AND review_status='rejected'", (item_id,))}
            if normalize_text(fields.name) in rejected:
                raise ValueError("The user already rejected this product for this line. Propose a different one or none.")
            resolution_id = db.execute(
                "INSERT INTO item_resolutions(receipt_item_id,product_id,name,brand,size_text,category,consumable,barcode,confidence,method,sources_json,run_id,review_status,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'proposed',?)",
                (item_id, product_id, fields.name, fields.brand, fields.size_text, fields.category, int(fields.consumable), fields.barcode,
                 confidence, method, json.dumps(list(sources)), run_id, now())).lastrowid
        return self.resolution(resolution_id)

    def resolution(self, resolution_id):
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM item_resolutions WHERE id=?", (resolution_id,)).fetchone()
        if row is None:
            raise ValueError("Item resolution not found.")
        value = dict(row)
        value["sources"], value["consumable"] = json.loads(value.pop("sources_json")), bool(value["consumable"])
        return value

    def resolutions(self, receipt_id=None, status="proposed", limit=200):
        clauses, params = ["r.review_status=?"], [status]
        if receipt_id is not None:
            clauses, params = [*clauses, "i.receipt_id=?"], [*params, receipt_id]
        with self.store.connection() as db:
            rows = db.execute("SELECT r.id FROM item_resolutions r JOIN receipt_items i ON i.id=r.receipt_item_id WHERE "
                              + " AND ".join(clauses) + " ORDER BY i.receipt_id,i.position LIMIT ?", (*params, limit)).fetchall()
        values = [self.resolution(row[0]) for row in rows]
        return [{**value, "line": self.line(value["receipt_item_id"])} for value in values]

    def review(self, resolution_id, status, edits: ResolutionFields | None = None, today=None):
        """Approve (optionally with the user's corrections) or reject. Approval creates the product, alias and lot."""
        if status not in ("verified", "rejected"):
            raise ValueError("Approve or reject the proposal.")
        today = today or date.today()
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM item_resolutions WHERE id=?", (resolution_id,)).fetchone()
            if row is None:
                raise ValueError("Item resolution not found.")
            if row["review_status"] != "proposed":
                raise ValueError("This proposal was already reviewed.")
            if status == "rejected":
                db.execute("UPDATE item_resolutions SET review_status='rejected',reviewed_at=? WHERE id=?", (now(), resolution_id))
                return self.resolution(resolution_id)
            fields = edits or ResolutionFields(name=row["name"], brand=row["brand"], size_text=row["size_text"], category=row["category"],
                                               consumable=bool(row["consumable"]), barcode=row["barcode"])
            line = self._line(db, row["receipt_item_id"])
            product_id = self._product(db, fields)
            if line["merchant_id"] is not None:
                # The user's latest approval for a printed text wins.
                db.execute("INSERT INTO item_aliases(merchant_id,normalized_text,product_code,product_id,created_at) VALUES(?,?,?,?,?) "
                           "ON CONFLICT(merchant_id,normalized_text) DO UPDATE SET product_id=excluded.product_id,product_code=excluded.product_code",
                           (line["merchant_id"], normalize_text(line["description"]), line["product_code"], product_id, now()))
            db.execute("UPDATE item_resolutions SET review_status='verified',product_id=?,name=?,brand=?,size_text=?,category=?,consumable=?,barcode=?,"
                       "method=CASE WHEN ? THEN 'user' ELSE method END,reviewed_at=? WHERE id=?",
                       (product_id, fields.name, fields.brand, fields.size_text, fields.category, int(fields.consumable), fields.barcode,
                        edits is not None, now(), resolution_id))
            self._add_lot(db, line, product_id, fields, today)
        return self.resolution(resolution_id)

    @staticmethod
    def _product(db, fields):
        key = normalize_text(fields.name)
        row = db.execute("SELECT id FROM products WHERE normalized_name=? AND brand IS ? AND size_text IS ?", (key, fields.brand, fields.size_text)).fetchone()
        if row:
            db.execute("UPDATE products SET name=?,category=?,consumable=?,barcode=coalesce(?,barcode),updated_at=? WHERE id=?",
                       (fields.name, fields.category, int(fields.consumable), fields.barcode, now(), row[0]))
            return row[0]
        return db.execute("INSERT INTO products(name,normalized_name,brand,size_text,category,consumable,barcode,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                          (fields.name, key, fields.brand, fields.size_text, fields.category, int(fields.consumable), fields.barcode, now(), now())).lastrowid

    def _add_lot(self, db, line, product_id, fields, today):
        bought = line["purchase_date"] or today.isoformat()
        existing = db.execute("SELECT id FROM inventory_lots WHERE receipt_id=? AND position=?", (line["receipt_id"], line["position"])).fetchone()
        if existing:  # A re-approved line (after re-extraction) changes the lot's product, never adds a second lot.
            db.execute("UPDATE inventory_lots SET product_id=?,updated_at=? WHERE id=?", (product_id, now(), existing[0]))
            return existing[0]
        first = self._first_check(db, product_id, fields.category, bought, today) if fields.consumable else None
        lot_id = db.execute("INSERT INTO inventory_lots(product_id,receipt_id,position,units,cost_minor,currency,bought_on,status,next_check_on,"
                            "check_interval_days,created_at,updated_at) VALUES(?,?,?,?,?,?,?,'in_stock',?,?,?,?)",
                            (product_id, line["receipt_id"], line["position"], line["quantity"], line["line_total_minor"], line["currency"], bought,
                             first, None, now(), now())).lastrowid
        db.execute("INSERT INTO lot_events(lot_id,event,effective_on,source,created_at) VALUES(?,'created',?,'approval',?)", (lot_id, bought, now()))
        if fields.consumable:
            # Buying again often means the older lot ran out: ask about it at the next check-in. Never closed automatically.
            db.execute("UPDATE inventory_lots SET next_check_on=min(coalesce(next_check_on,?),?),updated_at=? WHERE product_id=? AND status='in_stock' "
                       "AND id<>? AND bought_on<=?", (today.isoformat(), today.isoformat(), now(), product_id, lot_id, bought))
        return lot_id

    @staticmethod
    def _first_check(db, product_id, category, bought, today):
        days = [(iso_day(row[1]) - iso_day(row[0])).days for row in db.execute(
            "SELECT bought_on,closed_on FROM inventory_lots WHERE product_id=? AND status='finished' AND bought_on IS NOT NULL AND closed_on IS NOT NULL", (product_id,))]
        span = max(1, round(median(days))) if len(days) >= 2 else FIRST_CHECK_DAYS.get(category, DEFAULT_FIRST_CHECK_DAYS)
        return max(iso_day(bought) + timedelta(days=span), today).isoformat()

    # Inventory ----------------------------------------------------------------

    def inventory(self, query=None, include_closed=False, limit=200, today=None):
        clauses, params = [], []
        if not include_closed:
            clauses.append("l.status='in_stock'")
        for word in normalize_text(query).split()[:8]:
            clauses.append("(p.normalized_name LIKE ? OR upper(coalesce(p.brand,'')) LIKE ? OR p.category LIKE ?)")
            params += [f"%{word}%", f"%{word}%", f"%{word.lower()}%"]
        with self.store.connection() as db:
            rows = db.execute("SELECT l.*,p.name,p.brand,p.size_text,p.category,p.consumable,r.return_days_printed,r.return_policy_quote,"
                              "m.canonical_name AS merchant FROM inventory_lots l JOIN products p ON p.id=l.product_id "
                              "LEFT JOIN receipts r ON r.id=l.receipt_id LEFT JOIN merchants m ON m.id=r.merchant_id"
                              + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY p.name,l.bought_on,l.id LIMIT ?", (*params, limit)).fetchall()
            policies = self._policies(db)
        return [self._with_return(dict(row), policies, today) for row in rows]

    # Return windows -------------------------------------------------------------

    @staticmethod
    def _policies(db):
        return [(set(row["pattern"].split()), dict(row)) for row in db.execute("SELECT * FROM return_policies ORDER BY length(pattern) DESC,id")]

    @staticmethod
    def _with_return(lot, policies, today=None):
        """A non-food lot's return window: printed on its receipt, else its merchant's policy. Food is not tracked."""
        today = today or date.today()
        lot["consumable"], lot["openable"] = bool(lot["consumable"]), lot["category"] in OPENABLE
        lot.update(return_days=None, return_by=None, return_source=None, return_note=None, returnable=False)
        if not lot["openable"] or not lot.get("bought_on"):
            return lot
        if lot.get("return_days_printed") is not None:
            lot.update(return_days=lot["return_days_printed"], return_source="receipt", return_note=f"Printed on the receipt: “{lot['return_policy_quote']}”")
        else:
            words = set(normalize_name(lot.get("merchant")).split())
            policy = next((row for pattern, row in policies if words and pattern <= words), None)
            if policy is None:
                return lot
            lot.update(return_source="policy", return_note=f"{policy['merchant']} policy{' (typical)' if policy['source'] == 'typical' else ''}: "
                       + (f"{policy['days']} days" if policy["days"] is not None else "no fixed limit") + (f". {policy['note']}" if policy["note"] else ""))
            if policy["days"] is None:
                lot["returnable"] = lot["status"] == "in_stock" and not lot["opened_on"]
                return lot
            lot["return_days"] = policy["days"]
        lot["return_by"] = (iso_day(lot["bought_on"]) + timedelta(days=lot["return_days"])).isoformat()
        lot["returnable"] = lot["status"] == "in_stock" and not lot["opened_on"] and lot["return_days"] > 0 and today.isoformat() <= lot["return_by"]
        return lot

    def returns_closing(self, within_days=RETURNS_CLOSING_DAYS, today=None):
        """Unopened, in-stock lots whose return window closes within the given days, soonest first."""
        today = today or date.today()
        limit = (today + timedelta(days=within_days)).isoformat()
        lots = [lot for lot in self.inventory(limit=1000, today=today) if lot["returnable"] and lot["return_by"] and lot["return_by"] <= limit]
        return sorted(lots, key=lambda lot: (lot["return_by"], lot["id"]))

    def policies(self):
        with self.store.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM return_policies ORDER BY merchant")]

    def set_policy(self, merchant, days, note="", pattern=None):
        """Add or change a merchant's return policy. days None means no fixed limit. The user's entry replaces a typical one."""
        key = normalize_name(pattern or merchant)
        if not key:
            raise ValueError("Enter the merchant's name.")
        if days is not None and not 0 <= days <= 730:
            raise ValueError("Enter a number of days from 0 to 730, or leave it empty for no fixed limit.")
        with self.store.connection() as db:
            db.execute("INSERT INTO return_policies(pattern,merchant,days,note,source,created_at,updated_at) VALUES(?,?,?,?,'user',?,?) "
                       "ON CONFLICT(pattern) DO UPDATE SET merchant=excluded.merchant,days=excluded.days,note=excluded.note,source='user',updated_at=excluded.updated_at",
                       (key, " ".join(merchant.split())[:80], days, " ".join((note or "").split())[:200], now(), now()))
            return dict(db.execute("SELECT * FROM return_policies WHERE pattern=?", (key,)).fetchone())

    def delete_policy(self, policy_id):
        with self.store.connection() as db:
            if db.execute("DELETE FROM return_policies WHERE id=?", (policy_id,)).rowcount == 0:
                raise ValueError("Return policy not found.")
        return {"id": policy_id, "deleted": True}

    def lot(self, lot_id, db=None):
        if db is None:
            with self.store.connection() as db:
                return self.lot(lot_id, db)
        row = db.execute("SELECT * FROM inventory_lots WHERE id=?", (lot_id,)).fetchone()
        if row is None:
            raise ValueError("Inventory item not found.")
        return dict(row)

    def update_lot(self, lot_id, event, effective_on=None, precision_days=0, source="manual", today=None):
        """Apply the user's answer: still have it, finished, thrown out, or reopened. Applies directly; no review."""
        if event not in LOT_EVENTS:
            raise ValueError("Choose still have it, opened, finished, thrown out or reopen.")
        today = today or date.today()
        effective = iso_day(effective_on) if effective_on else today
        if effective > today:
            raise ValueError("The date cannot be in the future.")
        with self.store.connection() as db:
            lot = self.lot(lot_id, db)
            if lot["bought_on"] and effective < iso_day(lot["bought_on"]):
                raise ValueError("The date cannot be before the item was bought.")
            open_lot = lot["status"] == "in_stock"
            if event == "reopened" and open_lot or event != "reopened" and not open_lot:
                raise ValueError("This item is already " + ("in stock." if open_lot else "closed. Reopen it first."))
            consumable, category = db.execute("SELECT consumable,category FROM products WHERE id=?", (lot["product_id"],)).fetchone()
            if event == "opened":
                if category not in OPENABLE:
                    raise ValueError("Food and drink aren't tracked as opened.")
                if lot["opened_on"]:
                    raise ValueError("This item is already marked opened.")
                change = {"opened_on": effective.isoformat()}
            elif event == "still_have":
                # 7, 14, 28 ... days between questions, capped so a rarely used item is still asked about twice a year.
                interval = min(lot["check_interval_days"] * 2, MAX_INTERVAL_DAYS) if lot["check_interval_days"] else BASE_INTERVAL_DAYS
                change = {"check_interval_days": interval, "next_check_on": (effective + timedelta(days=interval)).isoformat()}
            elif event == "reopened":
                change = {"status": "in_stock", "closed_on": None, "closed_precision_days": 0, "check_interval_days": None,
                          "next_check_on": (today + timedelta(days=BASE_INTERVAL_DAYS)).isoformat() if consumable else None}
            else:
                change = {"status": event, "closed_on": effective.isoformat(), "closed_precision_days": precision_days, "next_check_on": None}
            self._set(db, lot_id, change)
            db.execute("INSERT INTO lot_events(lot_id,event,effective_on,precision_days,source,previous_json,created_at) VALUES(?,?,?,?,?,?,?)",
                       (lot_id, event, effective.isoformat(), precision_days, source, json.dumps({key: lot[key] for key in LOT_STATE}), now()))
            return self.lot(lot_id, db)

    def undo_lot(self, lot_id):
        """Restore the state before the latest answer. One level: an undo cannot itself be undone."""
        with self.store.connection() as db:
            latest = db.execute("SELECT * FROM lot_events WHERE lot_id=? ORDER BY id DESC LIMIT 1", (lot_id,)).fetchone()
            if latest is None or latest["event"] in ("created", "undone"):
                raise ValueError("There is nothing to undo for this item.")
            lot = self.lot(lot_id, db)
            self._set(db, lot_id, json.loads(latest["previous_json"]))
            db.execute("INSERT INTO lot_events(lot_id,event,effective_on,source,previous_json,created_at) VALUES(?,'undone',?,'manual',?,?)",
                       (lot_id, date.today().isoformat(), json.dumps({key: lot[key] for key in LOT_STATE}), now()))
            return self.lot(lot_id, db)

    @staticmethod
    def _set(db, lot_id, change):
        db.execute(f"UPDATE inventory_lots SET {','.join(f'{key}=?' for key in change)},updated_at=? WHERE id=?", (*change.values(), now(), lot_id))

    # Weekly check-in --------------------------------------------------------------

    def checkin(self, weekday, today=None, limit=CHECKIN_LIMIT):
        """This week's run-out questions: consumables in stock whose next question is due by the latest check-in day,
        most overdue first. Answered lots move their next question forward, so leftovers carry over by themselves."""
        today = today or date.today()
        day = checkin_day(today, weekday)
        with self.store.connection() as db:
            rows = db.execute("SELECT l.*,p.name,p.brand,p.size_text,p.category FROM inventory_lots l JOIN products p ON p.id=l.product_id "
                              "WHERE l.status='in_stock' AND p.consumable=1 AND l.next_check_on IS NOT NULL AND l.next_check_on<=? "
                              "ORDER BY l.next_check_on,l.bought_on,l.id", (day.isoformat(),)).fetchall()
        lots = [dict(row) for row in rows]
        return {"checkin_on": day.isoformat(), "next_checkin_on": (day + timedelta(days=7)).isoformat(), "lots": lots[:limit],
                "waiting": max(0, len(lots) - limit)}

    def answer(self, lot_id, answer, source="checkin", today=None):
        """Apply a one-tap check-in answer. 'This week' is stored as three days ago, give or take three."""
        if answer not in CHECKIN_ANSWERS:
            raise ValueError("Choose still have it, finished or thrown out.")
        today = today or date.today()
        event, back, precision = CHECKIN_ANSWERS[answer]
        effective = today - timedelta(days=back)
        bought = self.lot(lot_id)["bought_on"]
        if bought and effective < iso_day(bought):
            effective = iso_day(bought)
        return self.update_lot(lot_id, event, effective.isoformat() if event != "still_have" else None, precision, source, today)

    def receipts_to_identify(self, limit=20):
        """Receipts with lines that have no open proposal and no approved product, newest first."""
        with self.store.connection() as db:
            rows = db.execute(
                "SELECT r.id,r.document_id,r.purchase_date,r.review_status,m.canonical_name AS merchant,count(i.id) AS lines,"
                "sum(NOT EXISTS(SELECT 1 FROM item_resolutions x WHERE x.receipt_item_id=i.id AND x.review_status IN ('proposed','verified'))) AS unresolved "
                "FROM receipts r JOIN receipt_items i ON i.receipt_id=r.id LEFT JOIN merchants m ON m.id=r.merchant_id "
                "WHERE r.review_status<>'rejected' GROUP BY r.id HAVING unresolved>0 ORDER BY r.purchase_date DESC,r.id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def lot_history(self, lot_id):
        with self.store.connection() as db:
            self.lot(lot_id, db)
            return [dict(row) for row in db.execute("SELECT id,event,effective_on,precision_days,source,created_at FROM lot_events WHERE lot_id=? ORDER BY id", (lot_id,))]
