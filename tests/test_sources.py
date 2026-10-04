"""Watched folders outside Library/Inbox: copied in, never changed (docs/documents.md, "Watched folders")."""

import hashlib

import pytest

from conftest import inbox_scan
from home_manager.app.manager import Manager
from home_manager.core.paths import path_key
from home_manager.library.scanner import ScanLimits, Scanner
from home_manager.library.storage import Store

CSV = b"date,amount\n2026-09-01,123.45\n"


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "managed")
    yield store
    store.close()


@pytest.fixture
def folder(tmp_path):
    path = tmp_path / "Downloads"
    path.mkdir()
    return path


def watch(store, folder, recursive=True):
    source = store.add_source(folder, "Downloads", recursive)
    job = store.create_job(folder)
    Scanner(store, ScanLimits(stability_seconds=0)).run(job, folder, recursive)
    return source, job


def by_path(store):
    with store.connection() as db:
        return {row["relative_path"]: dict(row) for row in db.execute("SELECT * FROM occurrences WHERE source_root<>?", (path_key(store.library.inbox),))}


def test_watched_folder_is_copied_never_changed(store, folder):
    original = folder / "statement.csv"
    original.write_bytes(CSV)
    (folder / "scans").mkdir()
    (folder / "scans" / "bill.csv").write_bytes(b"date,amount\n2026-09-02,9.99\n")
    (folder / "notes.docx").write_bytes(b"not supported")
    _, job = watch(store, folder)
    assert store.job(job)["status"] == "completed"  # Other files in a watched folder are not problems.
    assert store.job(job)["counts"] == {"captured": 2, "unsupported": 1}
    assert original.read_bytes() == CSV and (folder / "scans" / "bill.csv").exists()
    rows = by_path(store)
    assert set(rows) == {"statement.csv", "scans/bill.csv"}
    assert {row["source_kind"] for row in rows.values()} == {"external"}
    # The library has its own copy, filed from the preserved blob.
    managed = store.library.current_file(rows["statement.csv"]["id"], hashlib.sha256(CSV).hexdigest())
    assert managed and (store.library.root / managed["relative_path"]).read_bytes() == CSV
    assert original.exists()


def test_rescan_edit_and_delete(store, folder):
    path = folder / "statement.csv"
    path.write_bytes(CSV)
    watch(store, folder)
    again = store.create_job(folder)
    Scanner(store, ScanLimits(stability_seconds=0)).run(again, folder, True)
    assert store.job(again)["counts"] == {"unchanged": 1}  # A repeated scan captures nothing twice.
    path.write_bytes(b"date,amount\n2026-09-01,200.00\n")
    edited = store.create_job(folder)
    Scanner(store, ScanLimits(stability_seconds=0)).run(edited, folder, True)
    assert store.job(edited)["counts"] == {"new_version": 1}
    path.unlink()
    gone = store.create_job(folder)
    Scanner(store, ScanLimits(stability_seconds=0)).run(gone, folder, True)
    assert store.job(gone)["counts"] == {"missing": 1}
    row = by_path(store)["statement.csv"]
    assert row["source_status"] == "missing"
    assert store.library.current_file(row["id"], row["current_hash"])  # The library copy stays.


def test_subfolders_only_when_recursive(store, folder):
    (folder / "scans").mkdir()
    (folder / "scans" / "bill.csv").write_bytes(CSV)
    _, job = watch(store, folder, recursive=False)
    assert store.job(job)["status"] == "completed" and not by_path(store)


def test_inbox_scan_leaves_watched_folder_documents_alone(store, folder):
    (folder / "statement.csv").write_bytes(CSV)
    watch(store, folder)
    job = inbox_scan(store)
    assert "missing" not in store.job(job)["counts"]
    assert by_path(store)["statement.csv"]["source_status"] == "present"


def test_same_bytes_are_linked(store, folder):
    (folder / "statement.csv").write_bytes(CSV)
    watch(store, folder)
    job = inbox_scan(store, {"copy.csv": CSV})
    assert store.job(job)["counts"] == {"duplicate": 1}
    watched = by_path(store)["statement.csv"]["id"]
    links = store.linked_documents(watched)
    assert [(link["reason"], link["relative_path"]) for link in links] == [("same_bytes", "copy.csv")]
    assert store.document(links[0]["document_id"])["links"][0]["document_id"] == watched


def test_sources_are_validated_and_managed(store, folder):
    source = store.add_source(folder, " Downloads ")
    assert source["label"] == "Downloads" and source["recursive"] == 1 and source["enabled"] == 1
    with pytest.raises(ValueError, match="already watched"):
        store.add_source(folder)
    assert store.update_source(source["id"], enabled=False, label="DL")["enabled"] == 0
    store.remove_source(source["id"])
    assert store.sources() == []


def test_manager_watches_folders(tmp_path, folder):
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "managed"))
        with pytest.raises(ValueError):
            manager.add_source(str(tmp_path / "managed" / "Library"))  # Never inside the library itself.
        source = manager.add_source(str(folder), "Downloads")
        (folder / "statement.csv").write_bytes(CSV)
        manager.check_sources()  # Not scanned by this process yet: scanned now.
        manager.future.result(timeout=30)
        assert manager.store.source(source["id"])["last_scan_at"]
        assert "statement.csv" in by_path(manager.store)
        manager.check_sources()  # Unchanged: nothing starts.
        assert not manager.busy("capture")
        (folder / "receipt.csv").write_bytes(b"date,amount\n2026-09-03,5.00\n")
        manager.check_sources()  # First look at the change: waits for one more matching look.
        assert not manager.busy("capture") and "receipt.csv" not in by_path(manager.store)
        manager.check_sources()
        manager.future.result(timeout=30)
        assert "receipt.csv" in by_path(manager.store)
    finally:
        manager.close()
