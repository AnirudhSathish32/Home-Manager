"""Synthetic household items for Inventory v2's browser test and ui_shots.py (design-system/home-manager/phase2-system-plan.md
"Seeding"): prices that rise, a smaller box, waste, a return window closing, warranties, a returned item to answer and two
check-in questions. Synthetic data only."""
from datetime import date, timedelta

from conftest import inbox_scan
from home_manager.finance.reconcile import Reconciler
from home_manager.household.items import ItemLedger, ResolutionFields, checkin_day
from home_manager.household.warranty import Warranties

OAT_MILK = ResolutionFields(name="Oat Milk", brand="Oatly", size_text="64 oz", category="dairy & eggs", consumable=True)
SPINACH = ResolutionFields(name="Baby Spinach", category="produce", consumable=True)
DRILL = ResolutionFields(name="Cordless Drill", brand="Torque", category="home maintenance", consumable=False)
KETTLE = ResolutionFields(name="Electric Kettle", brand="Brewline", category="other", consumable=False)
TOWELS = ResolutionFields(name="Bath Towel Set", category="other", consumable=False)


def cereal(size):
    return ResolutionFields(name="Honey Nut Cheerios", brand="General Mills", size_text=size, category="pantry", consumable=True)


def seed_items(manager):
    """Purchases over the last 90 days, each line approved as a product. Returns {"drill_lot": id, "towel_lot": id}."""
    store, ledger, items, today = manager.store, manager.ledger, ItemLedger(manager.store), date.today()
    day = lambda back: (today - timedelta(days=back)).isoformat()  # noqa: E731
    names = [f"items-{n}.png" for n in range(10)]
    inbox_scan(store, {name: f"synthetic household receipt {name}".encode() for name in names})
    docs = iter(doc for doc in store.documents()["items"] if doc["relative_path"].rsplit("/", 1)[-1] in names)

    def buy(on, merchant, lines):
        """lines: (printed text, cost, fields or None). Approves every line with fields; returns the new lots in order."""
        doc = next(docs)
        rows = [{"description": text, "product_code": None, "quantity": "1", "unit_price_minor": None, "line_total_minor": cost, "discount_minor": None,
                 "locator": {"line_ids": [f"l{n}"]}} for n, (text, cost, _) in enumerate(lines, 1)]
        record = {"merchant": merchant, "purchase_date": on, "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                  "total_minor": sum(cost for _, cost, _ in lines), "currency": "USD", "issues": [], "items": rows, "locator": {"line_ids": ["l0"]}}
        receipt_id = ledger.publish_receipt(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:" + doc["relative_path"],
                                                     "run_id": doc["relative_path"]}, "verified")["id"]
        for line, (_, _, fields) in zip(items.lines(receipt_id), lines):
            if fields:
                items.review(items.propose(line["id"], fields, "search", "high")["id"], "verified", today=today)
        return sorted((lot for lot in items.inventory(include_closed=True, limit=1000) if lot["receipt_id"] == receipt_id), key=lambda lot: lot["position"])

    # Oat milk three times at rising prices; the first two finished (cost per day, a price rise and next month's forecast).
    [milk_1] = buy(day(88), "Fresh Market", [("OATLY OAT 64OZ", 449, OAT_MILK)])
    [milk_2] = buy(day(60), "Fresh Market", [("OATLY OAT 64OZ", 479, OAT_MILK)])
    [cereal_big, milk_3] = buy(day(30), "Fresh Market", [("HN CHEERIOS 18OZ", 499, cereal("18 oz")), ("OATLY OAT 64OZ", 529, OAT_MILK)])
    items.update_lot(milk_1["id"], "finished", day(68), today=today)
    items.update_lot(milk_2["id"], "finished", day(38), today=today)
    # The same cereal in a smaller box at the same price: a package-size change.
    [cereal_small, spinach] = buy(day(12), "Fresh Market", [("HN CHEERIOS 15.5OZ", 499, cereal("15.5 oz")), ("BABY SPINACH", 399, SPINACH)])
    items.update_lot(spinach["id"], "thrown_out", day(5), today=today)
    # Two consumables this week's check-in asks about: due by the latest check-in day, whatever day the seed runs.
    due = checkin_day(today, manager.household.checkin_weekday).isoformat()
    with store.connection() as db:
        db.execute("UPDATE inventory_lots SET next_check_on=? WHERE id IN (?,?)", (due, milk_3["id"], cereal_big["id"]))
    # A drill 10 days ago at a store with a 14-day policy: its return window closes in four days.
    items.set_policy("Hardware Depot", 14, "Unopened tools only")
    [drill] = buy(day(10), "Hardware Depot", [("TORQUE DRILL 20V", 8999, DRILL)])
    # A kettle bought almost a year ago with a one-year warranty: it ends within 30 days.
    [kettle] = buy(day(340), "Home Goods", [("BREWLINE KETTLE", 3499, KETTLE)])
    warranties = Warranties(store)
    warranties.add(kettle["id"], "manufacturer", 12)
    # The seeded Acme toaster (seed_documents.seed_review_items), when there is one, gets an extended warranty of the user's.
    toaster = next((lot for lot in items.inventory(limit=1000) if lot["name"] == "Toaster"), None)
    if toaster:
        warranties.add(toaster["id"], "extended", 24, note="Protection plan, claim line 1-800-555-0100")
    # Towels bought, then a return receipt for them: the reconciler asks "did this go back?".
    [towels] = buy(day(20), "Target", [("TOWEL SET", 2500, TOWELS)])
    buy(day(3), "Target", [("TOWEL SET", -2500, None)])
    with store.connection() as db:
        line_id = db.execute("SELECT id FROM receipt_items WHERE line_total_minor<0 AND description='TOWEL SET'").fetchone()[0]
    # Identifying a returned line never puts it in stock (tests/test_returns.py).
    items.review(items.propose(line_id, TOWELS, "search", "high")["id"], "verified", today=today)
    Reconciler(store).run()
    return {"drill_lot": drill["id"], "towel_lot": towels["id"], "cereal_lot": cereal_small["id"]}
