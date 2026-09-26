"""Encrypted .hmshare files and temporary shared-library sessions."""

import io
import json
import tarfile

from fastapi.testclient import TestClient
import pytest

from conftest import inbox_scan
from home_manager import share
from home_manager.api import create_app
from home_manager.manager import Manager
from home_manager.paths import PathError
from home_manager.scanner import ScanLimits
from home_manager.share import DecryptingReader, EncryptingWriter, ShareError, export_share, open_share
from home_manager.storage import Store

PASSPHRASE = "correct horse battery staple"


@pytest.fixture(autouse=True)
def fast_keys(monkeypatch):
    monkeypatch.setattr(share, "SCRYPT_LOG_N", 10)  # The real cost is 2^17; tests only need the format.
    monkeypatch.setattr(share, "CHUNK", 64)  # Many chunks from small data.


def seal(data, passphrase=PASSPHRASE):
    target = io.BytesIO()
    writer = EncryptingWriter(target, passphrase)
    writer.write(data)
    writer.finish()
    return target.getvalue()


def unseal(blob, passphrase=PASSPHRASE):
    return DecryptingReader(io.BytesIO(blob), passphrase).read()


def test_chunked_encryption_detects_wrong_keys_truncation_reordering_and_tampering():
    data = bytes(range(256)) * 3
    blob = seal(data)
    assert unseal(blob) == data and data not in blob
    assert unseal(seal(b"")) == b""
    assert unseal(seal(b"x" * 64)) == b"x" * 64  # An exact chunk still ends with a sealed final chunk.
    with pytest.raises(ShareError, match="Wrong passphrase"):
        unseal(blob, "incorrect horse battery")
    size = share.HEADER.size
    chunk = share.CHUNK + share.TAG
    with pytest.raises(ShareError, match="damaged or incomplete"):
        unseal(blob[:size + chunk * 2])  # Cut at a chunk boundary: the last chunk was never marked last.
    reordered = blob[:size] + blob[size + chunk:size + 2 * chunk] + blob[size:size + chunk] + blob[size + 2 * chunk:]
    with pytest.raises(ShareError):
        unseal(reordered)
    tampered = bytearray(blob)
    tampered[size + 5] ^= 1
    with pytest.raises(ShareError):
        unseal(bytes(tampered))
    header = bytearray(blob)
    header[12] ^= 1  # Salt: the header is authenticated with every chunk.
    with pytest.raises(ShareError):
        unseal(bytes(header))
    with pytest.raises(ShareError, match="not a Home Manager share"):
        unseal(b"PK\x03\x04 not a share")
    with pytest.raises(ShareError, match="at least 12"):
        seal(b"data", "short")


def make_library(root, files):
    store = Store(root)
    inbox_scan(store, files)
    return store


def test_export_and_open_rebuild_an_identical_library(tmp_path):
    mom = make_library(tmp_path / "mom", {"groceries.png": b"mom's receipt", "bank.csv": b"date,amount\n2026-09-01,-5.00\n"})
    try:
        (tmp_path / "outbox").mkdir()
        result = export_share(mom, tmp_path / "outbox", PASSPHRASE, "  Mom's   library ")
        titles = sorted(doc["relative_path"] for doc in mom.documents()["items"])
    finally:
        mom.close()
    shared = tmp_path / "outbox" / result["path"].split("\\")[-1].split("/")[-1]
    assert shared.suffix == ".hmshare" and result["label"] == "Mom's library"
    assert b"mom's receipt" not in shared.read_bytes() and not list((tmp_path / "outbox").glob("*.partial"))
    with pytest.raises(ShareError, match="Wrong passphrase"):
        open_share(shared, "not the passphrase at all", tmp_path / "wrong")
    assert not (tmp_path / "wrong").exists() and not (tmp_path / "wrong-unpacked").exists()
    opened = open_share(shared, PASSPHRASE, tmp_path / "copy")
    assert opened["label"] == "Mom's library" and not (tmp_path / "copy-unpacked").exists()
    copy = Store(tmp_path / "copy")
    try:
        assert sorted(doc["relative_path"] for doc in copy.documents()["items"]) == titles
        doc = next(doc for doc in copy.documents()["items"] if doc["relative_path"] == "groceries.png")
        assert copy.blob_path(doc["current_hash"]).read_bytes() == b"mom's receipt"
        assert copy.library.path(doc["managed_path"]).read_bytes() == b"mom's receipt"
    finally:
        copy.close()


@pytest.mark.parametrize("name,kind", [("../escape.txt", tarfile.REGTYPE), ("originals/aa/../../escape", tarfile.REGTYPE),
                                        ("C:/escape", tarfile.REGTYPE), ("Library/link", tarfile.SYMTYPE)])
def test_hostile_archive_entries_are_refused_before_anything_is_written_outside(tmp_path, name, kind):
    stream = io.BytesIO()
    writer = EncryptingWriter(stream, PASSPHRASE)
    with tarfile.open(fileobj=writer, mode="w|") as archive:
        entry = tarfile.TarInfo(name)
        entry.type = kind
        if kind == tarfile.SYMTYPE:
            entry.linkname = str(tmp_path / "outside")
            archive.addfile(entry)
        else:
            entry.size = 4
            archive.addfile(entry, io.BytesIO(b"evil"))
    writer.finish()
    hostile = tmp_path / "hostile.hmshare"
    hostile.write_bytes(stream.getvalue())
    with pytest.raises((ShareError, PathError)):
        open_share(hostile, PASSPHRASE, tmp_path / "sessions" / "x" / "library")
    assert not (tmp_path / "escape.txt").exists() and not (tmp_path / "sessions" / "escape").exists()
    assert not (tmp_path / "sessions" / "x" / "library").exists()


def test_session_uses_a_temporary_copy_and_never_touches_your_library(tmp_path):
    mom = make_library(tmp_path / "mom", {"mom.png": b"mom's receipt"})
    try:
        (tmp_path / "outbox").mkdir()
        shared = export_share(mom, tmp_path / "outbox", PASSPHRASE, "Mom")["path"]
    finally:
        mom.close()
    control = tmp_path / "control"
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "mine"))
        inbox_scan(manager.store, {"mine.png": b"my receipt"})
        settings = (control / "settings.json").read_bytes()
        with pytest.raises(ShareError, match="at least 12"):
            manager.start_session(shared, "short")
        manager.start_session(shared, PASSPHRASE)
        manager.future.result(timeout=30)
        assert manager.session_opening["status"] == "succeeded", manager.session_opening
        view = manager.settings()
        assert view["session"]["label"] == "Mom" and view["managed_directory"] == str(tmp_path / "mine")
        assert [doc["relative_path"] for doc in manager.store.documents()["items"]] == ["mom.png"]
        doc = manager.store.documents()["items"][0]
        manager.store.set_description(doc["id"], "Written only to the copy")
        for blocked in (lambda: manager.configure(str(tmp_path / "other")), lambda: manager.start_backup(str(tmp_path)),
                        lambda: manager.start_share_export(str(tmp_path / "outbox"), PASSPHRASE, "x"),
                        lambda: manager.start_session(shared, PASSPHRASE)):
            with pytest.raises(RuntimeError):
                blocked()
        session_folder = control / "sessions" / view["session"]["id"]
        assert session_folder.is_dir()
        manager.end_session()
        assert manager.session is None and not session_folder.exists()
        assert [doc["relative_path"] for doc in manager.store.documents()["items"]] == ["mine.png"]
        assert manager.store.documents(query="Written only")["total"] == 0
        assert (control / "settings.json").read_bytes() == settings  # The session was never saved as your library.
        with pytest.raises(ValueError, match="No shared library"):
            manager.end_session()
        # A session the app never ended is deleted at the next start; you are back in your own library.
        manager.start_session(shared, PASSPHRASE)
        manager.future.result(timeout=30)
        leftover = control / "sessions" / manager.session["id"]
    finally:
        manager.lock.close()  # Simulate a crash: no close(), so no cleanup.
        manager.store.close()
    assert leftover.exists()
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        assert not leftover.exists() and manager.session is None
        assert [doc["relative_path"] for doc in manager.store.documents()["items"]] == ["mine.png"]
    finally:
        manager.close()


def test_share_endpoints_never_echo_passphrases(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        (tmp_path / "outbox").mkdir()
        refused = client.post("/api/shares", json={"destination": str(tmp_path / "outbox"), "passphrase": "tiny-secret"})
        assert refused.status_code == 400 and "tiny-secret" not in refused.text
        wrong_type = client.post("/api/sessions", json={"share_file": str(tmp_path / "x.hmshare"), "passphrase": 12345678901234})
        assert wrong_type.status_code == 422 and "12345678901234" not in wrong_type.text
        started = client.post("/api/shares", json={"destination": str(tmp_path / "outbox"), "passphrase": PASSPHRASE, "label": "Me"})
        assert started.status_code == 202
        app.state.manager.future.result(timeout=30)
        record = client.get(f"/api/shares/{started.json()['share_id']}").json()
        assert record["status"] == "succeeded" and PASSPHRASE not in json.dumps(record)
        opened = client.post("/api/sessions", json={"share_file": record["result"]["path"], "passphrase": PASSPHRASE})
        assert opened.status_code == 202
        app.state.manager.future.result(timeout=30)
        assert client.get("/api/settings").json()["session"]["label"] == "Me"
        assert client.delete("/api/sessions/current").json()["session"] is None


@pytest.mark.skipif(__import__("os").environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")
def test_browser_shares_opens_and_ends_a_session(tmp_path):
    import socket
    import threading
    import time
    import uvicorn
    playwright = pytest.importorskip("playwright.sync_api")
    mom = make_library(tmp_path / "mom", {"mom-only.png": b"mom's receipt"})
    mom.close()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    app = create_app(tmp_path / "control", "share-test", port, ScanLimits(stability_seconds=0))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    threading.Thread(target=server.run, daemon=True).start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(.05)
        manager = app.state.manager
        # Mom's side: her library exports a share file through the same page.
        manager.configure(str(tmp_path / "mom"))
        (tmp_path / "outbox").mkdir()
        with playwright.sync_playwright() as driver:
            browser = driver.chromium.launch(channel="msedge", headless=True)
            page = browser.new_page()
            failures = []
            page.on("pageerror", lambda error: failures.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}/#token=share-test")
            page.locator("#nav-settings").click()
            page.locator("#sharing-tab").click()
            page.locator("#share-destination").fill(str(tmp_path / "outbox"))
            page.locator("#share-label").fill("Mom")
            page.locator("#share-passphrase").fill(PASSPHRASE)
            page.locator("#share-passphrase-again").fill(PASSPHRASE + "x")
            page.locator("#share-export").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("The two passphrases differ")
            page.locator("#share-passphrase-again").fill(PASSPHRASE)
            page.locator("#share-export").click()
            playwright.expect(page.locator("#toasts")).to_contain_text("Share file saved", timeout=30000)
            [shared] = (tmp_path / "outbox").glob("*.hmshare")
            # Your side: your own library, then her file.
            manager.configure(str(tmp_path / "mine"))
            inbox_scan(manager.store, {"mine-only.png": b"my receipt"})
            page.reload()
            page.locator("#nav-settings").click()
            page.locator("#sharing-tab").click()
            page.locator("#session-file").fill(str(shared))
            page.locator("#session-passphrase").fill(PASSPHRASE)
            page.locator("#session-open").click()
            playwright.expect(page.locator("#session-banner")).to_contain_text("You are viewing “Mom”", timeout=30000)
            page.locator("#nav-documents").click()
            playwright.expect(page.locator("#documents")).to_contain_text("mom-only.png")
            playwright.expect(page.locator("#documents")).not_to_contain_text("mine-only.png")
            page.locator("#session-end").click()
            playwright.expect(page.locator("#session-banner")).to_be_empty(timeout=15000)
            playwright.expect(page.locator("#documents")).to_contain_text("mine-only.png")
            assert not failures, failures
            browser.close()
    finally:
        server.should_exit = True
