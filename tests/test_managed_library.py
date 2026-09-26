import hashlib
from pathlib import Path
import sqlite3

import pytest

from home_manager.manager import Manager
from home_manager.managed_library import LIBRARY_FOLDERS, filename
from conftest import inbox_scan
from home_manager.scanner import ScanLimits
from home_manager.storage import MIGRATIONS, Store
from home_manager.reasoning import ReasoningConfig
from test_receipts import make_receipt
from test_reasoning import proposal


def scan(store, *_):
    return inbox_scan(store)


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        yield store, store.library.inbox
    finally:
        store.close()


def test_manual_moves_keep_evidence_and_never_overwrite_edited_copies(library):
    store, inbox = library
    content = b"date,amount\n2026-09-24,25.00\n"
    (inbox / "bank.csv").write_bytes(content)
    scan(store)
    doc = store.documents()["items"][0]
    blob = store.blob_path(doc["current_hash"])
    assert doc["folder"] == "Inbox" and store.library.path(doc["managed_path"]).read_bytes() == blob.read_bytes() == content
    assert all((store.library.root / name).is_dir() for name in LIBRARY_FOLDERS)
    store.library_action(doc["id"], doc["current_hash"], "move", "Bank_Statements")
    moved = store.documents()["items"][0]
    assert moved["folder"] == "Bank_Statements"
    assert not (inbox / "bank.csv").exists()
    assert store.library.path(moved["managed_path"]).read_bytes() == content
    scan(store)
    assert store.documents()["items"][0]["managed_path"] == moved["managed_path"]
    store.library.path(moved["managed_path"]).write_bytes(b"user edited")
    assert blob.read_bytes() == content
    with pytest.raises(ValueError, match="edited"):
        store.library_action(doc["id"], doc["current_hash"], "move", "Bills")
    assert store.library.path(moved["managed_path"]).read_bytes() == b"user edited"
    assert store.documents()["items"][0]["managed_status"] == "blocked"


def test_inbox_capture_before_move_and_recovery_after_move(library, monkeypatch):
    store, source = library
    inbox_file = store.library.inbox / "download.csv"
    content = b"date,amount\n2026-09-24,25.00\n"
    inbox_file.write_bytes(content)
    scan(store)
    doc = store.documents()["items"][0]
    assert doc["source_kind"] == "inbox" and doc["folder"] == "Inbox"
    assert doc["folder_year"] == doc["folder_month"] == 0
    assert store.blob_path(doc["current_hash"]).read_bytes() == content
    class SimulatedCrash(BaseException):
        pass
    finish = store.library.finish
    def crash(intent):
        assert store.blob_path(doc["current_hash"]).read_bytes() == content
        assert store.library.path(intent["target_path"]).read_bytes() == content
        raise SimulatedCrash()
    monkeypatch.setattr(store.library, "finish", crash)
    with pytest.raises(SimulatedCrash):
        store.library_action(doc["id"], doc["current_hash"], "move", "Receipts")
    monkeypatch.setattr(store.library, "finish", finish)
    store.library.recover()
    organized = store.documents()["items"][0]
    assert organized["folder"] == "Receipts" and organized["managed_status"] == "succeeded"
    assert not inbox_file.exists()
    assert store.library.path(organized["managed_path"]).read_bytes() == content
    store.library.recover()
    scan(store)
    assert store.documents()["items"][0]["source_status"] == "organized"
    assert len(list((store.library.root / "Receipts").iterdir())) == 1
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM managed_organization_events").fetchone()[0] == 1


def test_capture_failure_keeps_inbox_file(library, monkeypatch):
    store, source = library
    item = store.library.inbox / "photo.jpg"
    item.write_bytes(b"synthetic capture bytes")
    def fail(*args):
        raise OSError("simulated capture failure")
    monkeypatch.setattr(store, "publish", fail)
    job = scan(store)
    assert store.job(job)["status"] == "partial"
    assert item.read_bytes() == b"synthetic capture bytes"
    assert store.documents()["total"] == 0
    assert not list((store.library.root / "Receipts").iterdir())


def test_changed_inbox_versions_and_readded_identical_file(library):
    store, source = library
    path = store.library.inbox / "receipt.csv"
    path.write_bytes(b"original bytes")
    scan(store)
    first = store.documents()["items"][0]
    path.write_bytes(b"replacement bytes")
    scan(store)
    second = store.documents()["items"][0]
    assert second["current_hash"] != first["current_hash"]
    assert second["folder"] == "Inbox" and second["version_count"] == 2
    archived = store.library.current_file(first["id"], first["current_hash"])
    assert archived["folder"] == "Unfiled"
    assert store.library.path(archived["relative_path"]).read_bytes() == b"original bytes"
    assert path.read_bytes() == b"replacement bytes"
    store.library.organize(second["id"], second["current_hash"], "Receipts", "Supported metadata", merchant="Shop", document_date="2026-09-24")
    named = store.documents()["items"][0]["managed_path"]
    path.write_bytes(b"replacement bytes")
    scan(store)
    assert not path.exists()
    assert store.documents()["items"][0]["managed_path"] == named
    assert len(list((store.library.root / "Receipts").iterdir())) == 1


def test_restart_backfills_capture_before_organization_intent(tmp_path, monkeypatch):
    root = tmp_path / "managed"
    store = Store(root)
    original = store.library.inbox / "one.csv"
    original.write_bytes(b"preserved before crash")
    class Crash(BaseException):
        pass
    def crash(*args):
        raise Crash()
    monkeypatch.setattr(store.library, "ensure_capture", crash)
    with pytest.raises(Crash):
        scan(store)
    doc = store.documents()["items"][0]
    assert doc["managed_path"] is None
    assert store.blob_path(doc["current_hash"]).read_bytes() == original.read_bytes()
    store.close()
    store = Store(root)
    try:
        doc = store.documents()["items"][0]
        assert doc["managed_path"] == "Inbox/one.csv"  # Registered where it waits for classification.
        assert store.library.path(doc["managed_path"]).read_bytes() == b"preserved before crash"
    finally:
        store.close()


def test_corrupt_blob_blocks_organization(library):
    store, source = library
    original = source / "a.csv"
    original.write_bytes(b"known capture")
    scan(store)
    doc = store.documents()["items"][0]
    store.blob_path(doc["current_hash"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        store.library_action(doc["id"], doc["current_hash"], "move", "Bills")
    assert original.read_bytes() == store.library.path(doc["managed_path"]).read_bytes() == b"known capture"


def test_library_rejects_reparse_component(library, monkeypatch):
    from home_manager import paths
    store, source = library
    original = source / "a.csv"
    original.write_bytes(b"known capture")
    scan(store)
    doc = store.documents()["items"][0]
    check = paths.is_link
    target = store.library.root / "Bills"
    monkeypatch.setattr(paths, "is_link", lambda path: path == target or check(path))
    with pytest.raises(ValueError, match="reparse"):
        store.library_action(doc["id"], doc["current_hash"], "move", "Bills")
    assert store.library.path(doc["managed_path"]).read_bytes() == original.read_bytes()


def test_recovery_never_truncates_a_published_file_renamed_by_user(library, monkeypatch):
    store, source = library
    original = source / "a.csv"
    original.write_bytes(b"captured")
    scan(store)
    doc = store.documents()["items"][0]
    # Fail after a move is published but before its DB commit.
    class Crash(BaseException):
        pass
    finish = store.library.finish
    def crash(intent):
        raise Crash()
    monkeypatch.setattr(store.library, "finish", crash)
    with pytest.raises(Crash):
        store.library_action(doc["id"], doc["current_hash"], "move", "Receipts")
    target = next((store.library.root / "Receipts").iterdir())
    edited = target.with_name("user-renamed.csv")
    target.rename(edited)
    edited.write_bytes(b"user edited after crash")
    monkeypatch.setattr(store.library, "finish", finish)
    store.library.recover()
    assert edited.read_bytes() == b"user edited after crash"
    doc = store.documents()["items"][0]
    assert store.library.path(doc["managed_path"]).read_bytes() == store.blob_path(doc["current_hash"]).read_bytes() == b"captured"


def test_collision_and_path_confinement(library):
    store, source = library
    content = b"same bytes"
    for name in ("a.csv", "b.csv"):
        (source / name).write_bytes(content)
    scan(store)
    docs = store.documents()["items"]
    assert len({doc["managed_path"] for doc in docs}) == 2
    doc = docs[0]
    reserved = store.library.root / "Receipts" / filename(doc["id"], doc["current_hash"], ".csv", "Receipts")
    reserved.write_bytes(b"unrelated user file")
    store.library_action(doc["id"], doc["current_hash"], "move", "Receipts")
    moved = next(item for item in store.documents()["items"] if item["id"] == doc["id"])
    assert doc["current_hash"] in moved["managed_path"]
    assert reserved.read_bytes() == b"unrelated user file"
    generated = filename(1, "a" * 64, ".jpg", "Receipts", "../C:\\CON 1234 5678 9012", "2026-09-24")
    assert all(value not in generated for value in ("..", ":", "\\", "/", "1234", "5678", "9012"))
    for unsafe in ("../escape.csv", "Receipts/../escape.csv", "C:/secret", "Receipts\\x.csv", "/Receipts/x.csv"):
        with pytest.raises(ValueError):
            store.library.path(unsafe)


def test_v6_migration_preserves_events_and_originals(tmp_path):
    root = tmp_path / "managed"
    root.mkdir()
    (root / ".home-manager-store").write_text("home-manager-store-v1\n")
    payload = b"legacy capture"
    digest = hashlib.sha256(payload).hexdigest()
    blob = root / "originals" / digest[:2] / (digest + ".blob")
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    migrations = Path(__file__).parents[1] / "src/home_manager/migrations"
    with sqlite3.connect(root / "inventory.sqlite3") as db:
        for path in sorted(migrations.glob("*.sql"))[:6]:
            db.executescript(path.read_text())
        db.execute("INSERT INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','legacy','completed','old','old')")
        db.execute("INSERT INTO blobs VALUES(?,?,'old')", (digest, len(payload)))
        db.execute("INSERT INTO occurrences(id,source_root,path_key,relative_path,folder_year,folder_month,current_hash,first_seen,last_seen,last_job) VALUES(1,'legacy','2026/09/a.jpg','2026/09/a.jpg',2026,9,?,'old','old','job')", (digest,))
        db.execute("INSERT INTO versions(occurrence_id,hash,captured_at,source_mtime_ns) VALUES(1,?,'old',0)", (digest,))
        db.execute("INSERT INTO document_folders VALUES(1,?,'03_Purchases/Receipts','old')", (digest,))
        db.execute("INSERT INTO library_events(document_id,blob_hash,action,detail,created_at) VALUES(1,?,'move','03_Purchases/Receipts','old')", (digest,))
    store = Store(root)
    try:
        with store.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == MIGRATIONS[-1][0]
            assert db.execute("SELECT folder FROM document_folders").fetchone()[0] == "Receipts"
            assert db.execute("SELECT detail FROM library_events WHERE action='move'").fetchone()[0] == "03_Purchases/Receipts"
            assert db.execute("SELECT count(*) FROM library_events WHERE action='folder_migration'").fetchone()[0] == 1
        with sqlite3.connect(root / f"inventory.before-v{MIGRATIONS[-1][0]}.sqlite3") as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 6
        managed = store.library.current_file(1, digest)
        assert managed["folder"] == "Receipts"
        assert store.library.path(managed["relative_path"]).read_bytes() == blob.read_bytes() == payload
    finally:
        store.close()


def test_inbox_analysis_files_supported_receipt_and_preserves_manual_override(tmp_path, local_model):
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "managed"))
        local_model["output"]["full_text"] += "\nLATTE 1 @ 5.00 5.00\nLATTE 1 @ 5.00 5.00\nSANDWICH 1 @ 10.00 10.00"
        image = manager.store.library.inbox / "random.png"
        make_receipt(image)
        original = image.read_bytes()
        manager.configure_vision(local_model["config"])
        manager.configure_reasoning(ReasoningConfig(base_url=local_model["config"].base_url, model="test-reasoning"))
        manager.start_inbox(); manager.future.result(timeout=30)
        doc = manager.store.documents()["items"][0]
        parse_id = manager.receipts.history(doc["id"])[0]["id"]
        result = proposal()
        result["facts"].extend([
            {"kind": "merchant", "value": "Local Test Cafe", "status": "proposed", "note": "", "evidence": [{"line_id": "line-1", "quote": "LOCAL TEST CAFE"}]},
            {"kind": "purchase_date", "value": "2026-09-22", "status": "proposed", "note": "", "evidence": [{"line_id": "line-2", "quote": "2026-09-22"}]}])
        local_model["output"] = result
        manager.start_reasoning(doc["id"], parse_id); manager.future.result(timeout=15)
        filed = manager.store.documents()["items"][0]
        assert filed["folder"] == "Receipts", filed
        assert not image.exists()
        assert "2026-09-22__Local_Test_Cafe" in filed["managed_path"]
        assert manager.store.library.path(filed["managed_path"]).read_bytes() == original
        assert manager.store.blob_path(doc["current_hash"]).read_bytes() == original
        # Uncertain identifying metadata must never guess a destination.
        result["facts"][-1]["status"] = "ambiguous"
        result["facts"][-1]["value"] = None
        manager.start_reasoning(doc["id"], parse_id, True); manager.future.result(timeout=15)
        uncertain = manager.store.documents()["items"][0]
        assert uncertain["folder"] == "Receipts"
        manager.library_action(doc["id"], doc["current_hash"], "move", "Bills")
        manager.start_reasoning(doc["id"], parse_id, True); manager.future.result(timeout=15)
        assert manager.store.documents()["items"][0]["folder"] == "Bills"
    finally:
        manager.close()


def test_old_migration_copies_are_pruned_only_when_the_newest_kept_copy_is_readable(tmp_path):
    root = tmp_path / "managed"
    Store(root).close()
    latest = MIGRATIONS[-1][0]

    def snapshot(version):
        db = sqlite3.connect(root / f"inventory.before-v{version}.sqlite3")
        db.execute("CREATE TABLE marker(v)")
        db.close()  # A connection's context manager commits but does not close; Windows would keep the file locked.
        return root / f"inventory.before-v{version}.sqlite3"

    old = [snapshot(version) for version in (2, 5)]
    sidecars = [old[0].with_name(old[0].name + suffix) for suffix in ("-wal", "-shm")]
    for sidecar in sidecars:
        sidecar.write_bytes(b"")
    kept = [snapshot(latest - 1), snapshot(latest)]
    future = snapshot(latest + 1)  # From a newer app version: never ours to delete.
    (root / "inventory.before-v3.sqlite3.bak").write_bytes(b"not an exact snapshot name")
    (root / "inventory.before-v4.sqlite3").mkdir()  # Not a regular file.
    kept[1].write_bytes(b"damaged")
    Store(root).close()
    assert all(path.exists() for path in old)  # The newest copy is unreadable: keep everything.

    kept[1].unlink()
    kept[1] = snapshot(latest)
    Store(root).close()
    assert not any(path.exists() for path in old + sidecars)
    assert all(path.exists() for path in kept) and future.exists()
    assert not any(path.with_name(path.name + "-shm").exists() for path in kept)  # Checking a copy leaves nothing beside it.
    assert (root / "inventory.before-v3.sqlite3.bak").exists() and (root / "inventory.before-v4.sqlite3").is_dir()
    assert (root / "inventory.sqlite3").exists()


def test_category_files_live_in_year_month_folders_and_existing_files_move_there(tmp_path):
    root = tmp_path / "managed"
    store = Store(root)
    try:
        inbox_scan(store, {"lunch.png": b"receipt bytes", "power.png": b"bill bytes", "mystery.png": b"unknown bytes"})
        docs = {doc["relative_path"]: doc for doc in store.documents()["items"]}
        lunch, power, mystery = docs["lunch.png"], docs["power.png"], docs["mystery.png"]
        # Classification with a cited date files straight into its month.
        store.library.file_classified(lunch["id"], lunch["current_hash"], "receipt", "Cafe", "2026-09-22", "Cited.")
        filed = store.document(lunch["id"])["managed_path"]
        assert filed.startswith("Receipts/2026/09/2026-09-22__Cafe__Receipts__") and store.library.path(filed).read_bytes() == b"receipt bytes"
        # Unconfirmed documents stay flat in Unfiled; a manual move without a known date stays at the category's top.
        store.library.file_classified(mystery["id"], mystery["current_hash"], "unknown", None, None, "Not cited.")
        assert store.document(mystery["id"])["managed_path"].count("/") == 1
        store.library_action(power["id"], power["current_hash"], "move", "Bills")
        assert store.document(power["id"])["managed_path"].startswith("Bills/Bills__")
        # Moving the dated receipt elsewhere tidies the month and year folders it leaves empty.
        store.library_action(lunch["id"], lunch["current_hash"], "move", "Housing")
        assert not (store.library.root / "Receipts" / "2026").exists() and (store.library.root / "Receipts").is_dir()
        moved = store.document(lunch["id"])["managed_path"]
        assert moved.startswith("Housing/2026/09/2026-09-22__Housing__")  # The known date carries over to name and folder.
        # A date that becomes known later (a published bill) moves the file into its month on the next start.
        with store.connection() as db:
            db.execute("INSERT INTO bills(document_id,blob_hash,issue_date,due_date,amount_due_minor,currency,review_status,created_at,updated_at) "
                       "VALUES(?,?,'2026-08-01','2026-08-20',4200,'USD','proposed','t','t')", (power["id"], power["current_hash"]))
        name = store.document(power["id"])["managed_path"].split("/")[-1]
        # An older version filed before this layout existed: its copy sits at the category's top level.
        inbox_scan(store, {"lunch.png": b"receipt bytes, second version"})
        assert store.document(lunch["id"])["current_hash"] != lunch["current_hash"]
        flat = "Housing/" + moved.split("/")[-1]
        store.library.path(moved).rename(store.library.path(flat))
        with store.connection() as db:
            db.execute("UPDATE managed_files SET relative_path=? WHERE document_id=? AND blob_hash=?", (flat, lunch["id"], lunch["current_hash"]))
    finally:
        store.close()
    store = Store(root)
    try:
        assert store.document(power["id"])["managed_path"] == f"Bills/2026/08/{name}"  # Same name, new folder.
        assert store.library.current_file(lunch["id"], lunch["current_hash"])["relative_path"] == moved
        assert store.library.path(moved).read_bytes() == b"receipt bytes"
        assert store.library.path(f"Bills/2026/08/{name}").read_bytes() == b"bill bytes"
        assert store.document(power["id"])["folder"] == "Bills"
        for unsafe in ("Inbox/2026/09/x.png", "Unfiled/2026/09/x.png", "Receipts/2026/13/x.png", "Receipts/abcd/09/x.png",
                       "Receipts/2026/x.png", "Receipts/2026/09/extra/x.png"):
            with pytest.raises(ValueError):
                store.library.path(unsafe)
    finally:
        store.close()
