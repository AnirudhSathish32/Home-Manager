"""Family inbox: upload once to the family, route to one person or share a cost, and each person's library receives it."""

from datetime import date

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.app.family_sync import read_deliveries
from home_manager.app.manager import Manager
from home_manager.finance.family import family_dashboard
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.splits import equal_shares, scale
from home_manager.finance.tools import FinanceTools, PeriodInput
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_reconcile_tools import add, source_of

PASSPHRASE = "correct horse battery staple"
TODAY = date(2026, 9, 25)
SEPTEMBER = PeriodInput(start="2026-09-01", end="2026-09-25")


def costco(ledger, doc, card=None, total=6000):
    """A receipt with two item categories: 30.00 groceries and 30.00 household supplies (scaled to total)."""
    half = total // 2
    return ledger.publish_receipt({
        "merchant": "Costco Wholesale", "purchase_date": "2026-09-10", "subtotal_minor": total, "tax_minor": 0, "tip_minor": None,
        "total_minor": total, "currency": "USD", "issues": [], "payment_last_four": card, "locator": {"line_ids": ["line-1"]},
        "items": [{"description": "BANANAS", "product_code": None, "quantity": None, "unit_price_minor": None, "line_total_minor": half,
                   "discount_minor": None, "taxed": False, "category": "groceries", "locator": {}},
                  {"description": "PAPER TOWELS", "product_code": None, "quantity": None, "unit_price_minor": None, "line_total_minor": total - half,
                   "discount_minor": None, "taxed": False, "category": "household supplies", "locator": {}}]},
        source_of(doc, "extraction:" + doc["relative_path"]), "verified")["id"]


def spending(store):
    tools = FinanceTools(store)
    total = next((row for row in tools.get_spending(SEPTEMBER)["by_currency"] if row["currency"] == "USD"), None)
    categories = {row["category"]: row["spending"]["minor"] for row in tools.get_spending_by_category(SEPTEMBER)["categories"]}
    return (total["net_spending"]["minor"] if total else 0), categories


def test_equal_shares_add_up_exactly():
    assert equal_shares(5000, 3) == [1667, 1667, 1666]
    for total in (1, 99, 5001, 123457):
        for people in (1, 2, 3, 7):
            parts = equal_shares(total, people)
            assert sum(parts) == total and max(parts) - min(parts) <= 1
    with pytest.raises(ValueError):
        equal_shares(100, 0)
    rows = [(0, "groceries", 3000), (1, "household supplies", 3000), (None, "dining", 1)]
    assert sum(amount for _, _, amount in scale(rows, 2001)) == 2001


def test_a_shared_receipt_and_its_card_charge_count_only_this_persons_part(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        inbox_scan(store, {"receipt.png": b"synthetic costco receipt", "card.csv": b"date,amount\n"})
        docs, ledger = documents_by_name(store), Ledger(store)
        receipt = costco(ledger, docs["receipt.png"])
        assert spending(store) == (6000, {"groceries": 3000, "household supplies": 3000})
        with store.connection() as db:
            db.execute("INSERT INTO record_shares VALUES('receipt',?,2000,6000,'[]','key','now')", (receipt,))
            ledger.refresh_splits(db, receipt)
        assert spending(store) == (2000, {"groceries": 1000, "household supplies": 1000})
        with store.connection() as db:
            ledger.refresh_splits(db)  # A full rebuild keeps the share: it is read from record_shares, not from the old splits.
        assert spending(store) == (2000, {"groceries": 1000, "household supplies": 1000})
        # The person whose card paid: the full charge is matched to the receipt and counts only their part.
        card = ledger.create_account("Chase", "credit_card", "USD", last_four="1234")
        add(store, ledger, card, docs["card.csv"], [("2026-09-11", "COSTCO WHSE #1", -6000)], status="verified")
        Reconciler(store).run()
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM transaction_receipt_links WHERE receipt_id=? AND review_status<>'rejected'", (receipt,)).fetchone()[0] == 1
        assert spending(store) == (2000, {"groceries": 1000, "household supplies": 1000})
        assert_ledger_healthy(store)
    finally:
        store.close()


def test_import_document_preserves_the_file_without_model_work(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        document_id, digest = store.import_document("From family Costco.png", b"delivered receipt bytes")
        assert store.blob_path(digest).read_bytes() == b"delivered receipt bytes"
        assert store.document(document_id)["current_hash"] == digest
        with store.connection() as db:
            assert db.execute("SELECT count(*) FROM parse_runs").fetchone()[0] == 0
        assert not any(store.library.inbox.iterdir())  # Nothing waits in Inbox for a scan.
    finally:
        store.close()


def test_upload_to_the_family_route_share_and_retract(tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    mom = Manager(tmp_path / "mom-pc", ScanLimits(stability_seconds=0), hub_port=0, hub_loopback=True)
    dad = Manager(tmp_path / "dad-pc", ScanLimits(stability_seconds=0))
    try:
        mom.configure(str(tmp_path / "mom-lib"))
        mom.rename_profile(mom.profile["id"], "Mom")
        inbox_scan(mom.store, {"mom.csv": b"mom,amount\n"})
        Ledger(mom.store).create_account("Chase", "credit_card", "USD", last_four="1234")  # Mom's card: receipts paid with it are hers.
        mom_profile = mom.profile["id"]
        family = mom.create_family("The Smiths", str(tmp_path / "family"), ["Dad"], my_profile=mom_profile)
        folder = mom.family_for(family["id"])[0]  # Held open by the hub.
        dad_id, mom_id = (member["member_id"] for member in folder.data["members"])
        invite = mom.invite_member(family["id"], dad_id, str(outbox), PASSPHRASE)["path"]
        dad.configure(str(tmp_path / "dad-lib"))
        dad.rename_profile(dad.profile["id"], "Dad")
        dad.join_family(invite, PASSPHRASE)
        dad.future.result(timeout=30)

        mom.switch_profile(family["id"])
        mom.future.result(timeout=30)
        assert mom.store is not None and mom.store.root == tmp_path / "family" / "library"  # The family's own inbox.
        inbox_scan(mom.store, {"costco.png": b"family costco receipt"})
        doc = documents_by_name(mom.store)["costco.png"]
        receipt = costco(Ledger(mom.store), doc, card="1234", total=5001)
        routing = mom.family_routing()
        [row] = routing["records"]
        assert (row["record_type"], row["id"], row["routing"]) == ("receipt", receipt, "suggested")
        assert row["suggested"]["member_id"] == mom_id and "1234" in row["suggested"]["reason"]
        with pytest.raises(ValueError, match="only receipts and bills"):
            mom.assign_family_record("statement", receipt, "shared", [mom_id])

        mom.assign_family_record("receipt", receipt, "shared", [mom_id, dad_id])
        mom.future.result(timeout=30)
        assert mom.family_routing()["records"] == []  # Nothing waits once it is sent.
        # Mom is on this computer: her library got her part straight away. Dad's waits in the family's outbox for his computer.
        mine = Store(tmp_path / "mom-lib")
        try:
            assert spending(mine)[0] == 2500  # 50.01 shared by two: Dad (listed first) 25.01, Mom 25.00.
            assert mine.documents(query="costco")["total"] == 1
        finally:
            mine.close()
        link = dad.profiles.get(dad.profile["id"])["family"]
        assert len(read_deliveries(tmp_path / "family", link)) == 1
        assert b"BANANAS" not in next((tmp_path / "family" / "outbox" / f"to-{dad_id}").iterdir()).read_bytes()  # Encrypted.
        dad.check_family()  # Asks the hub, pulls the delivery, applies it and acknowledges it.
        dad.future.result(timeout=30)
        # 25.01 of 50.01, divided in the items' proportions (25.00 groceries, 25.01 household supplies).
        assert spending(dad.store) == (2501, {"groceries": 1250, "household supplies": 1251})
        assert_ledger_healthy(dad.store)
        assert read_deliveries(tmp_path / "family", link) == []
        dad.start_family_publish()
        dad.future.result(timeout=30)

        mom.start_family_refresh()
        mom.future.result(timeout=30)
        with mom.family.mutex:
            result = family_dashboard(mom.family_members(), "2026-09", today=TODAY)
        assert result["totals"]["net_spending"]["minor"] == 5001  # The purchase, counted once across the family.

        # Reassigned to Mom alone: Dad's copy is withdrawn and Mom carries all of it.
        mom.assign_family_record("receipt", receipt, "member", [mom_id])
        mom.future.result(timeout=30)
        dad.check_family()
        dad.future.result(timeout=30)
        assert spending(dad.store)[0] == 0
        mom.switch_profile(mom_profile)
        assert spending(mom.store)[0] == 5001
        assert_ledger_healthy(mom.store)
        assert_ledger_healthy(dad.store)
    finally:
        mom.close()
        dad.close()
