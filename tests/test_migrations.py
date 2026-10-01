"""A failed schema upgrade keeps earlier steps and the pre-upgrade copy, and the app still starts and says what happened."""

import re
import sqlite3

import pytest

from home_manager.app.manager import Manager
from home_manager.library import storage
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import MIGRATIONS, MigrationError, Store, readable_database

LATEST = MIGRATIONS[-1][0]
NEXT = LATEST + 1


def version_of(root):
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def tables(root):
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    finally:
        db.close()


@pytest.fixture
def next_step(tmp_path, monkeypatch):
    """next_step(text) adds one more schema script after the real ones (or rewrites it) and returns its path."""
    script = tmp_path / f"{NEXT:03d}_test_step.sql"

    def add(text):
        script.write_text(text)
        monkeypatch.setattr(storage, "MIGRATIONS", [*MIGRATIONS, (NEXT, script)])
        return script
    return add


def test_a_failing_step_keeps_earlier_steps_and_the_pre_upgrade_copy(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    next_step(f"CREATE TABLE half_done(x);\nTHIS IS NOT SQL;\nPRAGMA user_version={NEXT};")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    error = failure.value
    assert (error.number, error.version) == (NEXT, LATEST)
    assert f"step {NEXT:03d}" in str(error) and error.snapshot.name in str(error)
    assert error.snapshot == root / f"inventory.before-v{NEXT}.sqlite3" and readable_database(error.snapshot)
    assert version_of(root) == LATEST
    assert "half_done" not in tables(root)  # The failed step left nothing behind.
    # Fixed script: the next start resumes and keeps the copy it already had.
    next_step(f"CREATE TABLE half_done(x);\nPRAGMA user_version={NEXT};")
    Store(root).close()
    assert version_of(root) == NEXT and "half_done" in tables(root)
    assert error.snapshot.exists()


def receipt_with_lines(store):
    """One receipt with an item and a reward: rows that cascade from receipts."""
    stamp, digest = "2026-09-30T00:00:00+00:00", "a" * 64
    with store.connection() as db:
        db.execute("INSERT INTO blobs VALUES(?,1,?)", (digest, stamp))
        db.execute("INSERT INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','root','completed',?,?)", (stamp, stamp))
        db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,folder_year,folder_month,current_hash,first_seen,last_seen,last_job) "
                   "VALUES('root','r.png','r.png',0,0,?,?,?,'job')", (digest, stamp, stamp))
        db.execute("INSERT INTO receipts(document_id,blob_hash,currency,review_status,created_at,updated_at) VALUES(1,?,'USD','verified',?,?)", (digest, stamp, stamp))
        db.execute("INSERT INTO receipt_items(receipt_id,position,description,review_status) VALUES(1,1,'MILK','verified')")
        db.execute("INSERT INTO receipt_rewards(receipt_id,position,kind,description,locator_json) VALUES(1,1,'earned','points','{}')")


def counts(root, *names):
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        return [db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in names]
    finally:
        db.close()


def test_a_table_rebuild_keeps_the_rows_that_cascade_from_it(tmp_path, next_step):
    # SQLite's rebuild procedure (new table, copy, drop, rename): with foreign keys on, the DROP would delete the receipt's lines.
    root = tmp_path / "managed"
    store = Store(root)
    receipt_with_lines(store)
    with store.connection() as db:
        create = re.sub(r'^CREATE TABLE\s+"?receipts"?', "CREATE TABLE receipts_new", db.execute("SELECT sql FROM sqlite_schema WHERE name='receipts'").fetchone()[0])
    store.close()
    next_step(f"{create};\nINSERT INTO receipts_new SELECT * FROM receipts;\nDROP TABLE receipts;\n"
              f"ALTER TABLE receipts_new RENAME TO receipts;\nPRAGMA user_version={NEXT};")
    store = Store(root)
    try:
        with store.connection() as db:
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # Back on for the app.
    finally:
        store.close()
    assert version_of(root) == NEXT
    assert counts(root, "receipts", "receipt_items", "receipt_rewards") == [1, 1, 1]


def test_a_step_that_breaks_references_is_rolled_back(tmp_path, next_step):
    root = tmp_path / "managed"
    store = Store(root)
    receipt_with_lines(store)
    store.close()
    next_step(f"DELETE FROM receipts;\nPRAGMA user_version={NEXT};")  # Would orphan the item and the reward.
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number == NEXT and "broken references" in str(failure.value.__cause__)
    assert version_of(root) == LATEST
    assert counts(root, "receipts", "receipt_items", "receipt_rewards") == [1, 1, 1]


def test_a_step_that_does_not_record_its_version_is_refused(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    next_step("CREATE TABLE forgot_version(x);")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number == NEXT
    assert version_of(root) == LATEST
    assert "forgot_version" not in tables(root)  # Checked before the step commits.


def test_an_unreadable_pre_upgrade_copy_is_replaced(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    copy = root / f"inventory.before-v{NEXT}.sqlite3"
    copy.write_bytes(b"damaged")
    next_step(f"PRAGMA user_version={NEXT};")
    Store(root).close()
    assert readable_database(copy)
    db = sqlite3.connect(copy)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
    finally:
        db.close()


def test_a_damaged_database_is_not_upgraded(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE filler(id INTEGER PRIMARY KEY, body TEXT)")
        db.execute("CREATE INDEX filler_body ON filler(body)")
        db.executemany("INSERT INTO filler(body) VALUES(?)", [(f"row {i} " * 20,) for i in range(2000)])
        db.commit()
        page = db.execute("PRAGMA page_size").fetchone()[0]
    finally:
        db.close()
    data = bytearray((root / "inventory.sqlite3").read_bytes())
    for start in range(len(data) - 6 * page, len(data), page):  # Scribble over the last pages (filler rows and index).
        data[start + 100:start + page - 100] = b"\xff" * (page - 200)
    (root / "inventory.sqlite3").write_bytes(bytes(data))
    next_step(f"CREATE TABLE never(x);\nPRAGMA user_version={NEXT};")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number is None and "integrity check" in str(failure.value)
    assert version_of(root) == LATEST
    assert not (root / f"inventory.before-v{NEXT}.sqlite3").exists()


def test_the_app_starts_and_explains_a_failed_upgrade(tmp_path, next_step):
    control, managed = tmp_path / "control", tmp_path / "managed"
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(managed))
    finally:
        manager.close()
    next_step(f"THIS IS NOT SQL;\nPRAGMA user_version={NEXT};")
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        assert manager.store is None
        assert f"step {NEXT:03d}" in manager.settings()["startup_error"]
    finally:
        manager.close()
