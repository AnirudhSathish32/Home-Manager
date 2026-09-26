import hashlib
import os
from pathlib import Path
import uuid

import pytest

from conftest import inbox_scan
from home_manager.paths import DirectoryLock, PathError, source_reader, validate_managed
from home_manager.storage import Store


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "managed")
    yield store
    store.close()


def scan(store, **limits):
    return inbox_scan(store, **limits)


def write(store, name="statement.csv", data=b"date,amount\n2026-09-01,123.45\n"):
    path = store.library.inbox / name
    path.write_bytes(data)
    return path


def test_capture_unchanged_and_duplicates_preserve_inbox_files(store):
    first = write(store)
    original = first.read_bytes()
    job = scan(store)
    assert store.job(job)["status"] == "completed"
    assert store.job(job)["counts"] == {"captured": 1}
    digest = hashlib.sha256(original).hexdigest()
    assert store.blob_path(digest).read_bytes() == original
    again = scan(store)
    assert store.job(again)["counts"] == {"unchanged": 1}
    second = write(store, "copy.csv", original)
    third = scan(store)
    assert store.job(third)["counts"] == {"duplicate": 1, "unchanged": 1}
    assert first.read_bytes() == second.read_bytes() == original
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM blobs").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM versions").fetchone()[0] == 2


def test_change_rename_and_delete(store):
    path = write(store)
    old = path.read_bytes()
    scan(store)
    path.write_bytes(b"new values")
    job = scan(store)
    assert store.job(job)["counts"] == {"new_version": 1}
    doc = store.documents()["items"][0]
    assert len(store.versions(doc["id"])) == 2
    assert store.blob_path(hashlib.sha256(old).hexdigest()).read_bytes() == old
    renamed = path.rename(store.library.inbox / "renamed.csv")
    job = scan(store)
    assert store.job(job)["counts"]["missing"] == 1
    renamed.unlink()
    scan(store)
    assert all(row["source_status"] == "missing" for row in store.documents()["items"])
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM blobs").fetchone()[0] == 2


def test_same_size_timestamp_edit_is_detected(store):
    path = write(store, data=b"aaaa")
    stamp = path.stat()
    scan(store)
    path.write_bytes(b"bbbb")
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert store.job(scan(store))["counts"] == {"new_version": 1}


def test_ignored_unsupported_subfolders_empty_and_limits(store):
    write(store, "~$statement.xlsx", b"lock")
    write(store, "file.csv.part", b"copying")
    write(store, "notes.txt", b"text")
    write(store, "empty.csv", b"")
    write(store, "big.csv", b"123456")
    (store.library.inbox / "2026").mkdir()
    (store.library.inbox / "2026" / "nested.csv").write_text("nested")
    job = scan(store, max_file_bytes=5)
    assert store.job(job)["status"] == "partial"
    assert store.job(job)["counts"] == {"ignored": 2, "unsupported": 1, "invalid_folder": 1, "rejected": 2}
    assert store.documents()["total"] == 0


def test_changed_during_stability_is_deferred(store, monkeypatch):
    path = write(store)
    monkeypatch.setattr("home_manager.scanner.time.sleep", lambda _: path.write_bytes(b"changed"))
    job = scan(store)
    assert store.job(job)["counts"] == {"deferred": 1}
    assert store.documents()["total"] == 0


def test_failed_enumeration_does_not_mark_missing(store, monkeypatch):
    path = write(store)
    scan(store)
    path.unlink()
    original = os.scandir
    def denied(path):
        if Path(path).name == "Inbox":
            raise PermissionError("denied")
        return original(path)
    monkeypatch.setattr("home_manager.scanner.os.scandir", denied)
    job = scan(store)
    assert store.job(job)["status"] == "partial"
    assert store.documents()["items"][0]["source_status"] == "present"


def test_capture_recovery_after_atomic_publication(tmp_path):
    managed = tmp_path / "managed"
    store = Store(managed)
    job = store.create_job()
    store.job_state(job, "running")
    capture = uuid.uuid4().hex
    data = b"preserve even if the original disappears"
    digest = hashlib.sha256(data).hexdigest()
    temp = store.work / (capture + ".part")
    temp.write_bytes(data)
    store.prepare(capture, job, "test.csv", digest, len(data), 123)
    final = store.blob_path(digest)
    final.parent.mkdir()
    os.link(temp, final)  # simulate death before SQLite metadata commit
    store.close()
    reopened = Store(managed)
    try:
        assert reopened.job(job)["status"] == "interrupted"
        assert reopened.documents()["items"][0]["current_hash"] == digest
        assert final.read_bytes() == data
        assert not temp.exists()
        reopened.recover()
        assert reopened.documents()["total"] == 1
    finally:
        reopened.close()


def test_quota_and_integrity_failure_do_not_overwrite(store):
    path = write(store, data=b"1234")
    assert store.job(scan(store, max_store_bytes=3))["counts"] == {"deferred": 1}
    scan(store)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    store.blob_path(digest).write_bytes(b"corrupt")
    job = scan(store)
    assert store.job(job)["status"] == "partial"
    assert store.blob_path(digest).read_bytes() == b"corrupt"
    assert path.read_bytes() == b"1234"


def test_library_folder_and_store_ownership(tmp_path):
    control = tmp_path / "control"
    control.mkdir()
    with pytest.raises(PathError):
        validate_managed(str(control / "managed"), control)
    with pytest.raises(PathError):
        validate_managed("relative", control)
    assert validate_managed(str(tmp_path / "managed"), control) == tmp_path / "managed"
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
def test_windows_capture_handle_denies_writes(store):
    path = write(store)
    with source_reader(path):
        with pytest.raises(OSError):
            path.write_bytes(b"should not be written")


def test_link_not_followed(store, tmp_path):
    outside = tmp_path / "outside.csv"
    outside.write_bytes(b"private")
    link = store.library.inbox / "link.csv"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("Creating symbolic links requires Windows developer mode or elevated permissions")
    job = scan(store)
    assert store.job(job)["counts"] == {"rejected": 1}
    assert store.documents()["total"] == 0


def test_recovery_preserves_newer_current_version(store):
    path = write(store, data=b"initial")
    scan(store)
    old_job = store.create_job()
    capture = uuid.uuid4().hex
    data = b"older interrupted capture"
    digest = hashlib.sha256(data).hexdigest()
    (store.work / (capture + ".part")).write_bytes(data)
    store.prepare(capture, old_job, "statement.csv", digest, len(data), 123)
    path.write_bytes(b"newest")
    scan(store)
    store.recover()
    doc = store.documents()["items"][0]
    assert doc["current_hash"] == hashlib.sha256(b"newest").hexdigest()
    assert len(store.versions(doc["id"])) == 3
    assert store.job(old_job)["counts"] == {"recovered_version": 1}


def test_recover_staged_bytes_and_orphan_cleanup(store):
    job = store.create_job()
    capture = uuid.uuid4().hex
    data = b"not published yet"
    digest = hashlib.sha256(data).hexdigest()
    (store.work / (capture + ".part")).write_bytes(data)
    orphan = store.work / (uuid.uuid4().hex + ".part")
    orphan.write_bytes(b"interrupted before intent")
    store.prepare(capture, job, "staged.csv", digest, len(data), 123)
    store.recover()
    assert store.blob_path(digest).read_bytes() == data
    assert store.documents()["total"] == 1
    assert not orphan.exists()


def test_missing_capture_is_visible_as_recovery_failure(store):
    job = store.create_job()
    store.prepare(uuid.uuid4().hex, job, "staged.csv", "a" * 64, 10, 123)
    store.recover()
    assert store.job(job)["counts"] == {"recovery_failed": 1}
    assert store.documents()["total"] == 0


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_locked_file_is_deferred_and_can_be_retried(store):
    path = write(store)
    with open(path, "r+b"):
        job = scan(store)
    assert store.job(job)["counts"] == {"deferred": 1}
    assert store.documents()["total"] == 0
    assert store.job(scan(store))["counts"] == {"captured": 1}


def test_reparse_flag_rejected_without_link_privileges(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from home_manager.paths import is_link
    monkeypatch.setattr(Path, "lstat", lambda _: SimpleNamespace(st_mode=0, st_file_attributes=0x400))
    assert is_link(tmp_path / "junction")


def test_rejected_replacement_does_not_claim_old_snapshot_is_current(store):
    path = write(store)
    scan(store)
    original_hash = store.documents()["items"][0]["current_hash"]
    path.write_bytes(b"")
    scan(store)
    document = store.documents()["items"][0]
    assert document["source_status"] == "not_captured"
    assert document["current_hash"] == original_hash
    assert document["version_count"] == 1
