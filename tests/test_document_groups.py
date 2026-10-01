"""Several images as one document: suggested, confirmed, read as pages, reordered and separated (documents/grouping.py)."""

import os

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.manager import Manager
from home_manager.documents.grouping import Groups, series
from home_manager.finance.ledger import Ledger
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_receipts import make_receipt


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "managed")
    yield store
    store.close()


def images(folder, names):
    for name in names:
        make_receipt(folder / name, [name])


def test_series_names():
    assert series("IMG_0012.png") == ("", "img_", 12)
    assert series("scans/scan (2).jpg") == ("scans", "scan (", 2)
    assert series("receipt_p3.png") == ("", "receipt_p", 3) and series("receipt.png") is None


def test_numbered_images_saved_together_are_suggested(store):
    images(store.library.inbox, ["IMG_0012.png", "IMG_0013.png", "IMG_0014.png", "IMG_0020.png", "other.png"])
    job = inbox_scan(store)
    groups = Groups(store)
    [group_id] = groups.suggest(job)
    group = groups.get(group_id)
    assert group["status"] == "proposed" and [page["relative_path"] for page in group["pages"]] == ["IMG_0012.png", "IMG_0013.png", "IMG_0014.png"]
    assert groups.suggest(job) == []  # Never suggested twice.
    assert len(store.documents()["items"]) == 5  # A suggestion hides nothing.


def test_images_saved_far_apart_are_not_suggested(store):
    images(store.library.inbox, ["scan (1).png", "scan (2).png"])
    later = store.library.inbox / "scan (2).png"
    os.utime(later, (later.stat().st_atime, later.stat().st_mtime + 3600))
    assert Groups(store).suggest(inbox_scan(store)) == []


def test_combining_checks_its_images(store):
    inbox_scan(store, {"statement.csv": b"date,amount\n2026-09-01,1.00\n"})
    images(store.library.inbox, ["a.png", "b.png", "c.png"])
    inbox_scan(store)
    docs = documents_by_name(store)
    groups = Groups(store)
    with pytest.raises(ValueError, match="Only PNG and JPEG"):
        groups.create([docs["a.png"]["id"], docs["statement.csv"]["id"]])
    with pytest.raises(ValueError, match="2 to 20"):
        groups.create([docs["a.png"]["id"]])
    groups.create([docs["a.png"]["id"], docs["b.png"]["id"]])
    with pytest.raises(ValueError, match="already part"):
        groups.create([docs["b.png"]["id"], docs["c.png"]["id"]])


def test_a_combined_document_reads_as_pages(tmp_path, local_model):
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "managed"))
        store = manager.store
        images(store.library.inbox, ["receipt_p1.png", "receipt_p2.png"])
        manager.start_inbox()
        manager.future.result(timeout=30)  # No vision model yet: captured and suggested, not read.
        [group] = manager.suggested_groups()
        first, second = (page["document_id"] for page in group["pages"])
        # The second page had a receipt of its own before it was combined: it stops counting.
        Ledger(store).publish_receipt({"merchant": "Shop", "purchase_date": "2026-09-20", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                       "total_minor": 500, "currency": "USD", "issues": [], "items": [], "locator": {"line_ids": ["line-1"]}},
                                      {"document_id": second, "blob_hash": group["pages"][1]["current_hash"], "source_key": "extraction:x", "run_id": "x"}, "proposed")
        manager.configure_vision(local_model["config"])
        local_model["outputs"] = [{"full_text": "SHOP\nITEM 1.00"}, {"full_text": "ITEM 2.00\nTotal 3.00"}]
        manager.change_group(group["id"], "confirmed")
        manager.future.result(timeout=60)
        [run] = [row for row in manager.receipts.history(first) if row["parser_version"] == "receipt-images-v1"]
        reading = manager.receipts.get(run["id"])
        assert reading["status"] == "succeeded", reading["error"]
        assert [line["id"] for line in reading["result"]["lines"]] == ["page-1-line-1", "page-1-line-2", "page-2-line-1", "page-2-line-2"]
        assert reading["result"]["lines"][3]["text"] == "Total 3.00"
        assert manager.receipts.page_image(run["id"], 2).is_file()
        listed = documents_by_name(store)
        assert "receipt_p2.png" not in listed and listed["receipt_p1.png"]["page_count"] == 2
        with store.connection() as db:
            assert db.execute("SELECT review_status FROM receipts WHERE document_id=?", (second,)).fetchone()[0] == "rejected"
        with pytest.raises(ValueError, match="page of a combined document"):
            manager.start_receipt(second)
        # New order: read again with the pages swapped.
        local_model["outputs"] = [{"full_text": "SECOND"}, {"full_text": "FIRST"}]
        manager.change_group(group["id"], document_ids=[second, first])
        manager.future.result(timeout=60)
        assert documents_by_name(store)["receipt_p2.png"]["page_count"] == 2 and "receipt_p1.png" not in documents_by_name(store)
        # Separated: both are documents again, each read on its own.
        local_model["outputs"] = [{"full_text": "ONE"}, {"full_text": "TWO"}]
        manager.change_group(group["id"], "dismissed")
        manager.future.result(timeout=60)
        listed = documents_by_name(store)
        assert {"receipt_p1.png", "receipt_p2.png"} <= set(listed) and listed["receipt_p1.png"]["page_count"] == 0
        assert manager.document_group(first) is None
    finally:
        manager.close()
