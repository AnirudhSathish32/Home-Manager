"""Model categorisation of items already stored: receipts recorded before items had their own categories, and items
filed under a category since retired (LEGACY_CATEGORIES, such as "shopping") that need re-sorting into the current list.

The local model is asked the same question new receipts get (ExtractionService.describe_purchase), from the item
names already stored: nothing is transcribed again. Tax flags cannot be recovered this way, so tax on receipts
categorised here for the first time is shared across all items. An item the user categorised under a current
category is never changed; when the user corrected the whole receipt's category, that is each new item's category
unless the model names another. A retired receipt category the user chose is replaced by an audited correction.
"""

from types import SimpleNamespace

from ..core.categories import LEGACY_CATEGORIES
from ..core.jobs import Work
from ..documents.extraction import ExtractionService
from ..library.storage import now
from ..models.model_client import resolve_identity
from .ledger import Ledger, normalize_name

BACKFILL_VERSION = "item-categories-v2"
LEGACY = ",".join(f"'{name}'" for name in LEGACY_CATEGORIES)


class ItemCategorizer:
    def __init__(self, store):
        self.store, self.ledger = store, Ledger(store)

    def pending(self):
        """IDs of receipts with items but no item categories yet, or with an item or receipt category since retired, newest first."""
        with self.store.connection() as db:
            return [row[0] for row in db.execute(
                "SELECT r.id FROM receipts r WHERE r.review_status<>'rejected' AND ("
                "EXISTS(SELECT 1 FROM receipt_items i WHERE i.receipt_id=r.id) AND NOT EXISTS(SELECT 1 FROM receipt_items i WHERE i.receipt_id=r.id AND i.category IS NOT NULL) "
                f"OR EXISTS(SELECT 1 FROM receipt_items i WHERE i.receipt_id=r.id AND i.category_source='legacy') OR r.category IN ({LEGACY})) "
                "ORDER BY r.purchase_date DESC,r.id DESC")]

    def run(self, config, work=None):
        """Categorise or re-sort each pending receipt's items. Returns {"receipts", "items"}; a receipt the model can't answer is left for next time."""
        work = work or Work.detached()
        receipts = self.pending() if config.model else []
        identity = resolve_identity(self.store, config) if receipts else None
        done = items = 0
        for number, receipt_id in enumerate(receipts, 1):
            work.check()
            work.report(f"{number} of {len(receipts)} receipts")
            with self.store.connection() as db:
                receipt = db.execute("SELECT r.*,m.canonical_name AS merchant FROM receipts r LEFT JOIN merchants m ON m.id=r.merchant_id WHERE r.id=?",
                                     (receipt_id,)).fetchone()
                rows = db.execute("SELECT id,description,category,category_source FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,)).fetchall()
                correction = db.execute("SELECT value FROM record_corrections WHERE record_type='receipt' AND record_id=? AND field='category' "
                                        "ORDER BY id DESC LIMIT 1", (receipt_id,)).fetchone()
            with work.attribute("item_categories", receipt_id, BACKFILL_VERSION, identity):
                answer = ExtractionService.describe_purchase(config, work, [], [SimpleNamespace(description=row["description"]) for row in rows],
                                                             receipt["merchant"], receipt["location"])
            _, receipt_answer, _, categories = answer
            if categories is None:
                continue
            first_time = not any(row["category"] for row in rows)
            # The whole receipt's category the user chose is each new item's starting point, unless it has been retired.
            fallback = correction["value"] if correction and correction["value"] not in LEGACY_CATEGORIES else None
            with self.store.connection() as db:
                remembered = self.ledger.remembered_categories(db, receipt["merchant"])
                for row, category in zip(rows, categories):
                    if first_time:
                        chosen = remembered.get(normalize_name(row["description"]))
                        source = "memory" if chosen else "model" if category else "receipt" if fallback else None
                        value = chosen or category or fallback
                    elif row["category_source"] == "legacy":
                        chosen = remembered.get(normalize_name(row["description"]))
                        source, value = ("memory", chosen) if chosen else ("model", category or "other")
                    else:
                        continue
                    db.execute("UPDATE receipt_items SET category=?,category_source=?,updated_at=? WHERE id=?", (value, source, now(), row["id"]))
                    items += 1
                if receipt["category"] in LEGACY_CATEGORIES:
                    replacement = receipt_answer or "other"
                    db.execute("UPDATE receipts SET category=?,updated_at=? WHERE id=?", (replacement, now(), receipt_id))
                    if correction and correction["value"] in LEGACY_CATEGORIES:
                        # The user's own choice no longer exists: record the replacement like a correction, so re-extraction keeps it.
                        db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,created_at) "
                                   "VALUES('receipt',?,'category',?,?,'[]',?)", (receipt_id, replacement, correction["value"], now()))
                self.ledger.refresh_splits(db, receipt_id)
            done += 1
        return {"receipts": done, "items": items}
