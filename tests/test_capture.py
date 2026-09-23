import hashlib
import os
from pathlib import Path
import uuid

import pytest

from home_manager.paths import DirectoryLock, PathError, source_reader, validate_roots
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store


@pytest.fixture
def setup(tmp_path):
    source = tmp_path / "sources"
    (source / "2026" / "09").mkdir(parents=True)
    store = Store(tmp_path / "managed")
    yield source, store
    store.close()


def scan(source, store, year=None, month=None, **limits):
    job = store.create_job(source, year, month)
    Scanner(store, ScanLimits(stability_seconds=0, **limits)).run(job, source, year, month)
    return job


def write(source, name="statement.csv", data=b"date,amount\n2026-09-01,123.45\n"):
    path = source / "2026" / "09" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_capture_unchanged_and_duplicates_preserve_source(setup):
    source, store = setup
    first = write(source)
    original = first.read_bytes()
    job = scan(source, store)
    assert store.job(job)["status"] == "completed"
    assert store.job(job)["counts"] == {"captured": 1}
    digest = hashlib.sha256(original).hexdigest()
    assert store.blob_path(digest).read_bytes() == original
    again = scan(source, store)
    assert store.job(again)["counts"] == {"unchanged": 1}
    second = write(source, "nested/copy.csv", original)
    third = scan(source, store)
    assert store.job(third)["counts"] == {"duplicate": 1, "unchanged": 1}
    assert first.read_bytes() == second.read_bytes() == original
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM blobs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 2


def test_change_rename_delete_and_scoped_missing(setup):
    source, store = setup
    path = write(source)
    old = path.read_bytes()
    scan(source, store)
    path.write_bytes(b"new values")
    job = scan(source, store)
    assert store.job(job)["counts"] == {"new_version": 1}
    doc = store.documents(source)["items"][0]
    assert len(store.versions(doc["id"])) == 2
    assert store.blob_path(hashlib.sha256(old).hexdigest()).read_bytes() == old
    new_path = source / "2026" / "08" / "renamed.csv"
    new_path.parent.mkdir()
    path.rename(new_path)
    scoped = scan(source, store, 2026, 8)
    assert "missing" not in store.job(scoped)["counts"]
    all_job = scan(source, store)
    assert store.job(all_job)["counts"]["missing"] == 1
    new_path.unlink()
    scan(source, store)
    assert all(row["source_status"] == "missing" for row in store.documents(source)["items"])
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM blobs").fetchone()[0] == 2


def test_same_size_timestamp_edit_is_detected(setup):
    source, store = setup
    path = write(source, data=b"aaaa")
    stamp = path.stat()
    scan(source, store)
    path.write_bytes(b"bbbb")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert store.job(scan(source, store))["counts"] == {"new_version": 1}


def test_ignored_unsupported_invalid_empty_and_limits(setup):
    source, store = setup
    write(source, "~$statement.xlsx", b"lock")
    write(source, "file.csv.part", b"copying")
    write(source, "document.pdf", b"pdf")
    write(source, "empty.csv", b"")
    write(source, "big.csv", b"123456")
    (source / "loose.csv").write_text("loose")
    (source / "2026" / "13").mkdir()
    (source / "2026" / "13" / "bad.csv").write_text("bad")
    job = scan(source, store, max_file_bytes=5)
    assert store.job(job)["status"] == "partial"
    assert store.job(job)["counts"] == {"ignored": 2, "unsupported": 1, "invalid_folder": 2, "rejected": 2}
    assert store.documents(source)["total"] == 0


def test_changed_during_stability_is_deferred(setup, monkeypatch):
    source, store = setup
    path = write(source)
    monkeypatch.setattr("home_manager.scanner.time.sleep", lambda _: path.write_bytes(b"changed"))
    job = scan(source, store)
    assert store.job(job)["counts"] == {"deferred": 1}
    assert store.documents(source)["total"] == 0


def test_failed_enumeration_does_not_mark_missing(setup, monkeypatch):
    source, store = setup
    path = write(source)
    scan(source, store)
    path.unlink()
    original = os.scandir
    def denied(path):
        if Path(path).name == "09":
            raise PermissionError("denied")
        return original(path)
    monkeypatch.setattr("home_manager.scanner.os.scandir", denied)
    job = scan(source, store)
    assert store.job(job)["status"] == "partial"
    assert store.documents(source)["items"][0]["source_status"] == "present"


def test_capture_recovery_after_atomic_publication(tmp_path):
    source = tmp_path / "sources"
    source.mkdir()
    managed = tmp_path / "managed"
    store = Store(managed)
    job = store.create_job(source)
    store.job_state(job, "running")
    capture = uuid.uuid4().hex
    data = b"preserve even if the original disappears"
    digest = hashlib.sha256(data).hexdigest()
    temp = store.work / (capture + ".part")
    temp.write_bytes(data)
    store.prepare(capture, job, source, "2026/09/test.csv", 2026, 9, digest, len(data), 123)
    final = store.blob_path(digest)
    final.parent.mkdir()
    os.link(temp, final)  # simulate death before SQLite metadata commit
    store.close()
    reopened = Store(managed)
    try:
        assert reopened.job(job)["status"] == "interrupted"
        assert reopened.documents(source)["items"][0]["current_hash"] == digest
        assert final.read_bytes() == data
        assert not temp.exists()
        reopened.recover()
        assert reopened.documents(source)["total"] == 1
    finally:
        reopened.close()


def test_quota_and_integrity_failure_do_not_overwrite(setup):
    source, store = setup
    path = write(source, data=b"1234")
    assert store.job(scan(source, store, max_store_bytes=3))["counts"] == {"deferred": 1}
    scan(source, store)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store.blob_path(digest).write_bytes(b"corrupt")
    job = scan(source, store)
    assert store.job(job)["status"] == "partial"
    assert store.blob_path(digest).read_bytes() == b"corrupt"
    assert path.read_bytes() == b"1234"


def test_roots_and_store_ownership(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(PathError):
        validate_roots(str(source), str(source / "managed"), tmp_path / "control")
    with pytest.raises(PathError):
        validate_roots("relative", str(tmp_path / "managed"), tmp_path / "control")
    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "personal.txt").write_text("keep")
    with pytest.raises(PathError):
        Store(nonempty)
    store = Store(tmp_path / "managed")
    try:
        with pytest.raises(PathError):
            DirectoryLock(store.root)
    finally:
        store.close()


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_windows_source_handle_denies_writes(setup):
    source, store = setup
    path = write(source)
    with source_reader(path):
        with pytest.raises(OSError):
            path.write_bytes(b"should not be written")


def test_link_not_followed(setup, tmp_path):
    source, store = setup
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"private")
    link = source / "2026" / "09" / "link.csv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links requires Windows developer mode or elevated permissions")
    job = scan(source, store)
    assert store.job(job)["counts"] == {"rejected": 1}
    assert store.documents(source)["total"] == 0


def test_recovery_preserves_newer_current_version(setup):
    source, store = setup
    path = write(source, data=b"initial")
    scan(source, store)
    old_job = store.create_job(source)
    capture = uuid.uuid4().hex
    data = b"older interrupted capture"
    digest = hashlib.sha256(data).hexdigest()
    (store.work / (capture + ".part")).write_bytes(data)
    store.prepare(capture, old_job, source, "2026/09/statement.csv", 2026, 9, digest, len(data), 123)
    path.write_bytes(b"newest")
    scan(source, store)
    store.recover()
    doc = store.documents(source)["items"][0]
    assert doc["current_hash"] == hashlib.sha256(b"newest").hexdigest()
    assert len(store.versions(doc["id"])) == 3
    assert store.job(old_job)["counts"] == {"recovered_version": 1}


def test_recover_staged_bytes_and_orphan_cleanup(setup):
    source, store = setup
    job = store.create_job(source)
    capture = uuid.uuid4().hex
    data = b"not published yet"
    digest = hashlib.sha256(data).hexdigest()
    (store.work / (capture + ".part")).write_bytes(data)
    orphan = store.work / (uuid.uuid4().hex + ".part")
    orphan.write_bytes(b"interrupted before intent")
    store.prepare(capture, job, source, "2026/09/source.csv", 2026, 9, digest, len(data), 123)
    store.recover()
    assert store.blob_path(digest).read_bytes() == data
    assert store.documents(source)["total"] == 1
    assert not orphan.exists()


def test_missing_capture_is_visible_as_recovery_failure(setup):
    source, store = setup
    job = store.create_job(source)
    store.prepare(uuid.uuid4().hex, job, source, "2026/09/source.csv", 2026, 9, "a" * 64, 10, 123)
    store.recover()
    assert store.job(job)["counts"] == {"recovery_failed": 1}
    assert store.documents(source)["total"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_locked_file_is_deferred_and_can_be_retried(setup):
    source, store = setup
    path = write(source)
    with open(path, "r+b"):
        job = scan(source, store)
    assert store.job(job)["counts"] == {"deferred": 1}
    assert store.documents(source)["total"] == 0
    assert store.job(scan(source, store))["counts"] == {"captured": 1}


def test_reparse_flag_rejected_without_link_privileges(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from home_manager.paths import is_link
    monkeypatch.setattr(Path, "lstat", lambda _: SimpleNamespace(st_mode=0, st_file_attributes=0x400))
    assert is_link(tmp_path / "junction")


def test_rejected_replacement_does_not_claim_old_snapshot_is_current(setup):
    source, store = setup
    path = write(source)
    scan(source, store)
    original_hash = store.documents(source)["items"][0]["current_hash"]
    path.write_bytes(b"")
    scan(source, store)
    document = store.documents(source)["items"][0]
    assert document["source_status"] == "not_captured"
    assert document["current_hash"] == original_hash
    assert document["version_count"] == 1
