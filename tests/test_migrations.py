"""A failed schema upgrade keeps earlier steps and the pre-upgrade copy, and the app still starts and says what happened."""

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


def test_a_step_that_does_not_record_its_version_is_refused(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    next_step("CREATE TABLE forgot_version(x);")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number == NEXT
    assert version_of(root) == LATEST


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
