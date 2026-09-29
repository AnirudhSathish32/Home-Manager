"""Backups: a failed or cancelled run leaves nothing half-written, gaps are reported, and verification catches every
kind of mismatch. The full backup-and-restore round trip is in test_backend_dependencies.py (B13)."""

import json
import sqlite3

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.core.jobs import Work
from home_manager.core.paths import PathError
from home_manager.library.backup import BackupService, manifest_path, verify_backup
from home_manager.library.storage import MIGRATIONS, Store


@pytest.fixture
def library(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n2026-09-01,10.00\n", "receipt.png": b"synthetic receipt bytes"})
    destination = tmp_path / "backups"
    destination.mkdir()
    try:
        yield store, BackupService(store), destination
    finally:
        store.close()


def backup(service, destination, work=None):
    service.run(service.begin(destination), destination, work or Work.detached())
    [record] = service.history()
    return record


def test_a_damaged_original_stops_the_backup_and_leaves_nothing_behind(library):
    store, service, destination = library
    doc = documents_by_name(store)["receipt.png"]
    store.blob_path(doc["current_hash"]).write_bytes(b"changed on disk")
    with pytest.raises(ValueError, match="integrity check"):
        backup(service, destination)
    [record] = service.history()
    assert record["status"] == "failed" and "integrity check" in record["error"]
    assert list(destination.iterdir()) == []  # The .partial staging folder was removed.


def test_a_cancelled_backup_is_recorded_and_leaves_nothing_behind(library):
    store, service, destination = library
    work = Work.detached()
    work.cancel()
    record = backup(service, destination, work)  # Cancelling is not an error.
    assert (record["status"], record["error"]) == ("cancelled", "Cancelled by the user.")
    assert list(destination.iterdir()) == []


def test_missing_library_files_and_previews_are_reported_not_fatal(library):
    store, service, destination = library
    doc = documents_by_name(store)["export.csv"]
    store.library.path(doc["managed_path"]).unlink()
    with store.connection() as db:
        db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,preview_hash,created_at,updated_at) VALUES('run-1',?,'v','{}','succeeded',?,'t','t')",
                   (doc["current_hash"], "0" * 64))
    record = backup(service, destination)
    assert record["status"] == "succeeded"
    [folder] = destination.iterdir()
    manifest, problems = verify_backup(folder)
    assert problems == []
    assert any("was missing; its preserved original is included" in issue for issue in manifest["issues"])
    assert any("Preview for reading run-1" in issue for issue in manifest["issues"])
    assert any(entry["path"] == f"originals/{doc['current_hash'][:2]}/{doc['current_hash']}.blob" for entry in manifest["files"])


def test_a_backup_running_when_the_app_stopped_is_marked_interrupted(library):
    store, service, destination = library
    service.begin(destination)
    service.recover()
    [record] = service.history()
    assert record["status"] == "interrupted" and "stopped during the backup" in record["error"]


@pytest.fixture
def made(library):
    store, service, destination = library
    backup(service, destination)
    [folder] = destination.iterdir()
    return folder


def rewrite(folder, change):
    manifest = json.loads((folder / "manifest.json").read_text())
    change(manifest)
    (folder / "manifest.json").write_text(json.dumps(manifest))


def test_verification_reports_missing_and_changed_files(made):
    original = next(entry for entry in json.loads((made / "manifest.json").read_text())["files"] if entry["kind"] == "original")
    made.joinpath(*original["path"].split("/")).unlink()
    library_file = next(path for path in (made / "Library").rglob("*") if path.is_file())
    library_file.write_bytes(library_file.read_bytes() + b"!")
    manifest, problems = verify_backup(made)
    assert manifest is not None
    assert f"{original['path']} is missing." in problems
    assert any(problem.endswith("does not match the manifest.") for problem in problems)


def test_verification_refuses_newer_or_foreign_backups(made, tmp_path):
    assert verify_backup(tmp_path)[0] is None  # Not a backup folder.
    rewrite(made, lambda manifest: manifest.update(schema_version=MIGRATIONS[-1][0] + 1))
    assert any("newer Home Manager" in problem for problem in verify_backup(made)[1])
    rewrite(made, lambda manifest: manifest.update(format="something-else"))
    assert verify_backup(made) == (None, ["This backup was made in an unsupported format."])


def test_verification_checks_the_database_version_against_the_manifest(made):
    database = made / "inventory.sqlite3"
    db = sqlite3.connect(database)
    try:
        db.execute("PRAGMA user_version=1")
        db.commit()
    finally:
        db.close()
    # Keep the manifest's size and digest in step with the edited database, so only the version differs.
    from home_manager.library.backup import file_digest
    size, digest = file_digest(database)
    rewrite(made, lambda manifest: [entry.update(size=size, sha256=digest) for entry in manifest["files"] if entry["path"] == "inventory.sqlite3"])
    assert verify_backup(made)[1] == ["The backed-up database version differs from the manifest."]


@pytest.mark.parametrize("relative", ["../outside.txt", "originals/../../outside.txt", "/etc/passwd", "C:/Windows/x", "originals\\ab\\x.blob",
                                      "notes/readme.txt", "inventory.sqlite3/extra"])
def test_manifest_entries_are_confined_to_the_backup_layout(relative):
    with pytest.raises(PathError):
        manifest_path(relative)


def test_manifest_entries_inside_the_layout_are_accepted():
    for relative in ("inventory.sqlite3", "originals/ab/abc.blob", "Library/Receipts/a.png", "extracted/run-1/preview.png"):
        assert str(manifest_path(relative)) == relative
    # "." and empty parts are normalized away by the path type, so they cannot leave the layout either.
    assert str(manifest_path("originals/./ab//x.blob")) == "originals/ab/x.blob"
