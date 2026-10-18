"""Agent test instance guards (core/sandbox.py, docs/development.md "Agent test instance"), in-process.

No test here reads, lists or stats P:\\Finances, P:\\EvalCorpus or the real %LOCALAPPDATA%\\HomeManager: the real-path
spies raise on any such argument, and every non-loopback lookup or connection goes to the no_egress double, which never
calls the real socket function for it. Decoys under tmp_path stand in for protected folders.
"""

import builtins
import ctypes
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import socket
import sys

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app import family_hub
from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder, write_invite
from home_manager.core import paths, sandbox
from home_manager.finance.investments import AccountInput, Investments
from home_manager.finance.ledger import Ledger
from home_manager.finance.prices import CryptoPrices
from home_manager.library.scanner import ScanLimits
from home_manager.models.web_lookup import LookupFailed, https_get

URL = "http://127.0.0.1:8765"
AUTH = {"Authorization": "Bearer t"}
PASSPHRASE = "correct horse battery staple"
REFUSED_LOG = "test instance: refused outbound host="
GTIN = "4006381333931"  # Valid EAN-13 check digit.


# Network double ------------------------------------------------------------------------------------------------------

_REAL = {"getaddrinfo": socket.getaddrinfo, "create_connection": socket.create_connection, "connect": socket.socket.connect}


@dataclass
class Attempt:
    host: str
    stage: str  # "getaddrinfo" or "connect"
    refused_by: str  # "sandbox" or "double"


class Egress:
    def __init__(self):
        self.attempts: list[Attempt] = []

    @property
    def outbound(self):
        """Attempts other than the guard's own status probe (settings report sandbox.status(), which probes)."""
        return [item for item in self.attempts if item.host != sandbox.PROBE_HOST]

    def hosts(self, refused_by=None):
        return [item.host for item in self.outbound if refused_by in (None, item.refused_by)]


@pytest.fixture
def no_egress(monkeypatch):
    """Record every non-loopback lookup and connection and refuse it, never calling the real function for it. The spy
    raises the audit event the real function would, so an active sandbox refuses first (refused_by="sandbox"); otherwise
    the double refuses with the same exception type the sandbox uses (refused_by="double")."""
    egress = Egress()

    def lookup(host, port, family=0, type=0, proto=0, flags=0):
        if host in (None, "", b"") or sandbox.loopback(host):
            return _REAL["getaddrinfo"](host, port, family, type, proto, flags)
        try:
            sys.audit("socket.getaddrinfo", host, port, family, type, proto)
        except socket.gaierror:
            egress.attempts.append(Attempt(str(host), "getaddrinfo", "sandbox"))
            raise
        egress.attempts.append(Attempt(str(host), "getaddrinfo", "double"))
        raise socket.gaierror(socket.EAI_NONAME, f"no_egress refused {host}")

    def create_connection(address, *args, **kwargs):
        if not sandbox.loopback(address[0]):
            lookup(address[0], address[1])  # Always raises for a non-loopback host.
        return _REAL["create_connection"](address, *args, **kwargs)

    def connect(sock, address):
        if isinstance(address, tuple) and not sandbox.loopback(address[0]):
            try:
                sys.audit("socket.connect", sock, address)
            except ConnectionRefusedError:
                egress.attempts.append(Attempt(str(address[0]), "connect", "sandbox"))
                raise
            egress.attempts.append(Attempt(str(address[0]), "connect", "double"))
            raise ConnectionRefusedError(f"no_egress refused {address[0]}")
        return _REAL["connect"](sock, address)

    monkeypatch.setattr(socket, "getaddrinfo", lookup)
    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket.socket, "connect", connect)
    return egress


# Real-path spies -----------------------------------------------------------------------------------------------------

def real_roots():
    """The real protected roots, as strings only: never passed to a filesystem call."""
    roots = [r"P:\Finances", r"P:\EvalCorpus"]
    if os.environ.get("LOCALAPPDATA"):
        roots.append(os.path.join(os.environ["LOCALAPPDATA"], "HomeManager"))
    return roots


class TouchedRealData(AssertionError):
    pass


@pytest.fixture
def real_path_spies(monkeypatch):
    """safe_path, os.lstat, os.stat, os.scandir and open raise on any argument under a real protected root."""
    roots = [sandbox.norm(root) for root in real_roots()]
    calls = []

    def guard(name, real):
        def spy(target, *args, **kwargs):
            if isinstance(target, (str, bytes, os.PathLike)):
                value = os.fsdecode(target)
                if any(sandbox.under(sandbox.norm(value), root) for root in roots):
                    calls.append((name, value))
                    raise TouchedRealData(f"{name} touched {value}")
            return real(target, *args, **kwargs)
        return spy

    monkeypatch.setattr(paths, "safe_path", guard("safe_path", paths.safe_path))
    monkeypatch.setattr(os, "lstat", guard("lstat", os.lstat))
    monkeypatch.setattr(os, "stat", guard("stat", os.stat))
    monkeypatch.setattr(os, "scandir", guard("scandir", os.scandir))
    monkeypatch.setattr(builtins, "open", guard("open", builtins.open))
    return calls


# The sandboxed app ---------------------------------------------------------------------------------------------------

def make_decoy(folder: Path):
    (folder / "library").mkdir(parents=True)
    (folder / "canary.txt").write_text("canary", encoding="utf-8")
    (folder / "library" / "inventory.sqlite3").write_bytes(b"placeholder")
    return folder


def snapshot(folder: Path):
    """Names, sizes and mtimes of everything under folder."""
    return sorted((str(item.relative_to(folder)), item.stat().st_size, item.stat().st_mtime_ns) for item in folder.rglob("*"))


@dataclass
class Instance:
    client: TestClient
    manager: object
    root: Path
    decoy: Path
    control: Path


@pytest.fixture
def sandboxed(tmp_path):
    """An in-process app in test mode: instance root tmp_path/instance with its library open, a protected decoy."""
    root = tmp_path / "instance"
    root.mkdir()
    decoy = make_decoy(tmp_path / "decoy-protected-folder")
    sandbox.activate(root, protected=[decoy])
    try:
        app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
        with TestClient(app, base_url=URL, headers=AUTH) as client:
            assert client.put("/api/settings", json={"managed_directory": str(root / "library")}).status_code == 200
            yield Instance(client, app.state.manager, root, decoy, tmp_path / "control")
    finally:
        sandbox.deactivate()


@pytest.fixture
def plain(tmp_path):
    """The same app with test mode off (SC-11)."""
    assert not sandbox.active()
    app = create_app(tmp_path / "plain", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url=URL, headers=AUTH) as client:
        assert client.put("/api/settings", json={"managed_directory": str(tmp_path / "library")}).status_code == 200
        yield client, app.state.manager


def path_inputs(client, manager, root):
    """Every API input that takes a path (spec U1 P1–P10, plus P12 the local member folder), as name -> call(path)."""
    family = client.post("/api/families", json={"name": "Family", "folder": str(root / "family"), "members": ["Kid"]})
    assert family.status_code == 201, family.text
    family_id = family.json()["id"]
    folder, temporary = manager.family_for(family_id)
    member_id = folder.data["members"][0]["member_id"]
    if temporary:
        folder.close()
    members = f"/api/families/{family_id}/members/{member_id}"
    return {
        "P1 library folder": lambda p: client.put("/api/settings", json={"managed_directory": p}),
        "P2 new profile": lambda p: client.post("/api/profiles", json={"name": "Other", "folder": p}),
        "P3 new family": lambda p: client.post("/api/families", json={"name": "Other family", "folder": p}),
        "P4 invite": lambda p: client.post(f"{members}/invites", json={"destination": p, "passphrase": PASSPHRASE}),
        "P5 join": lambda p: client.post("/api/family-membership", json={"invite_file": p, "passphrase": PASSPHRASE}),
        "P6 watched folder": lambda p: client.post("/api/sources", json={"path": p}),
        "P7 backup": lambda p: client.post("/api/backups", json={"destination": p}),
        "P8 restore source": lambda p: client.post("/api/restores", json={"backup": p, "target": str(root / "restored")}),
        "P8 restore target": lambda p: client.post("/api/restores", json={"backup": str(root / "backups"), "target": p}),
        "P9 share export": lambda p: client.post("/api/shares", json={"destination": p, "passphrase": PASSPHRASE}),
        "P10 shared copy": lambda p: client.post("/api/sessions", json={"share_file": p, "passphrase": PASSPHRASE}),
        "P12 local member": lambda p: client.post(f"{members}/local", json={"folder": p}),
    }


def state(client):
    return {name: client.get(route).json() for name, route in
            (("settings", "/api/settings"), ("profiles", "/api/profiles"), ("sources", "/api/sources"))}


def short_name(path: Path):
    """The 8.3 short form of path, or None when the volume makes none."""
    buffer = ctypes.create_unicode_buffer(1024)
    if os.name != "nt" or not ctypes.windll.kernel32.GetShortPathNameW(str(path), buffer, 1024):
        return None
    return buffer.value if buffer.value.lower() != str(path).lower() else None


# The network double itself -------------------------------------------------------------------------------------------

def test_no_egress_never_calls_real_socket(no_egress, tmp_path, monkeypatch):
    reached = []
    for name in _REAL:
        monkeypatch.setitem(_REAL, name, lambda *args, name=name, **kwargs: reached.append(name))
    for active in (False, True):
        if active:
            sandbox.activate(tmp_path)
        try:
            with pytest.raises(socket.gaierror):
                socket.getaddrinfo("example.invalid", 443)
            with pytest.raises(socket.gaierror):
                socket.create_connection(("192.0.2.1", 443))
            with socket.socket() as sock, pytest.raises(ConnectionRefusedError):
                sock.connect(("192.0.2.1", 443))
        finally:
            sandbox.deactivate()
    assert reached == []
    assert [item.refused_by for item in no_egress.attempts] == ["double"] * 3 + ["sandbox"] * 3
    assert [item.stage for item in no_egress.attempts] == ["getaddrinfo", "getaddrinfo", "connect"] * 2


def test_hook_allows_passive_bind_lookup(no_egress, tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="home_manager.sandbox")
    sandbox.activate(tmp_path)
    try:
        assert socket.getaddrinfo(None, 0, flags=socket.AI_PASSIVE)
        assert socket.getaddrinfo("", 0) is not None
        assert socket.getaddrinfo("127.0.0.1", 0) and socket.getaddrinfo("localhost", 0)
        with pytest.raises(socket.gaierror, match="outbound internet is off"):
            socket.getaddrinfo("example.invalid", 443)
        assert sandbox.status() == {"paths": True, "egress": True}
    finally:
        sandbox.deactivate()
    # The status probe is refused by the sandbox too, and adds no log line.
    assert no_egress.attempts == [Attempt(host, "getaddrinfo", "sandbox") for host in ("example.invalid", sandbox.PROBE_HOST)]
    assert refusals(caplog) == [REFUSED_LOG + "example.invalid"]
    assert sandbox.status() == {"paths": False, "egress": False}


# SC-03, SC-04, SC-14: paths ------------------------------------------------------------------------------------------

def test_sc03_protected_paths_refused_at_every_input(sandboxed, real_path_spies, no_egress, tmp_path):
    client, root = sandboxed.client, sandboxed.root
    inputs = path_inputs(client, sandboxed.manager, root)
    before, decoy_before = state(client), snapshot(sandboxed.decoy)
    files_before = {item for item in tmp_path.rglob("*") if "logs" not in item.parts}
    targets = [os.path.join(item, "x") for item in (*real_roots(), sandboxed.decoy)]
    targets += [r"p:\fInAnCeS\x", "P:\\Finances\\x\\", r"P:\Dev\..\Finances\x", r"P:\EvalCorpus", str(sandboxed.decoy) + os.sep]
    failures = []
    for name, call in inputs.items():
        for target in targets:
            response = call(target)
            detail = response.json().get("detail") if response.headers.get("content-type", "").startswith("application/json") else None
            if not (response.status_code == 400 and isinstance(detail, str) and "holds real data and is off limits." in detail):
                failures.append((name, target, response.status_code, response.text[:200]))
    assert failures == []
    assert real_path_spies == []
    assert state(client) == before
    assert snapshot(sandboxed.decoy) == decoy_before
    assert {item for item in tmp_path.rglob("*") if "logs" not in item.parts} == files_before
    assert no_egress.outbound == []


def test_sc03_short_name_is_refused(sandboxed, real_path_spies):
    short = short_name(sandboxed.decoy)
    if short is None:
        pytest.skip("This volume makes no 8.3 short names.")
    response = sandboxed.client.post("/api/sources", json={"path": os.path.join(short, "library")})
    assert response.status_code == 400 and response.json()["detail"].startswith("Test instance:")


def test_sc04_paths_outside_the_root_are_refused(sandboxed, tmp_path):
    client, root = sandboxed.client, sandboxed.root
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "canary.txt").write_text("canary", encoding="utf-8")
    listing = snapshot(outside)
    sources = len(client.get("/api/sources").json())
    response = client.post("/api/sources", json={"path": str(outside)})
    assert response.status_code == 400 and "only folders inside" in response.json()["detail"]
    for call in (lambda p: client.put("/api/settings", json={"managed_directory": p}),
                 lambda p: client.post("/api/profiles", json={"name": "Other", "folder": p}),
                 lambda p: client.post("/api/backups", json={"destination": p})):
        response = call(str(outside))
        assert response.status_code == 400 and "only folders inside" in response.json()["detail"]
    (root / "uploads").mkdir()
    assert client.post("/api/sources", json={"path": str(root / "uploads")}).status_code == 201
    assert len(client.get("/api/sources").json()) == sources + 1
    assert snapshot(outside) == listing


def test_sc14_profile_and_restore_folders_refused(sandboxed, real_path_spies, tmp_path):
    client, root = sandboxed.client, sandboxed.root
    profiles_file = sandboxed.control / "profiles.json"
    before = profiles_file.read_bytes()
    (tmp_path / "elsewhere").mkdir()
    for folder in (r"P:\Finances\y", str(tmp_path / "elsewhere" / "y")):
        response = client.post("/api/profiles", json={"name": "Agent", "folder": folder})
        assert response.status_code == 400 and response.json()["detail"].startswith("Test instance:")
    response = client.post("/api/restores", json={"backup": str(root / "backups"), "target": r"P:\Finances\y"})
    assert response.status_code == 400 and "holds real data" in response.json()["detail"]
    assert profiles_file.read_bytes() == before
    assert real_path_spies == []


def test_watch_folder_in_root_inside_checkout(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    root = checkout / "tests" / ".tmp"
    (root / "uploads").mkdir(parents=True)
    (root / "scanner").mkdir()
    monkeypatch.setattr(paths, "reserved_paths", lambda control: (checkout, control))
    sandbox.activate(root)
    try:
        app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
        with TestClient(app, base_url=URL, headers=AUTH) as client:
            assert client.put("/api/settings", json={"managed_directory": str(root / "library")}).status_code == 200
            assert client.post("/api/sources", json={"path": str(root / "uploads")}).status_code == 201
            sandbox.deactivate()  # As today: a watched folder inside the checkout is refused.
            response = client.post("/api/sources", json={"path": str(root / "scanner")})
            assert response.status_code == 400 and "application's own folders" in response.json()["detail"]
    finally:
        sandbox.deactivate()


# SC-05: no outbound internet -----------------------------------------------------------------------------------------

def counts(store):
    with store.connection() as db:
        return {table: db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] for table in ("price_quotes", "fx_rate_sets", "fx_rates")}


def refusals(caplog):
    return [record.getMessage() for record in caplog.records if record.getMessage().startswith(REFUSED_LOG)]


def test_sc05_outbound_calls_refused(sandboxed, no_egress, caplog):
    caplog.set_level(logging.WARNING, logger="home_manager.sandbox")
    client, manager = sandboxed.client, sandboxed.manager
    store = manager.store
    household = client.get("/api/settings").json()["household"]
    assert client.put("/api/household-settings", json={**household, "fetch_crypto_prices": True, "fetch_exchange_rates": True}).status_code == 200
    wallet = Investments(store).add(AccountInput(name="Coinbase", kind="crypto", institution="Coinbase", currency="USD", value="1", as_of="2026-01-01"))
    with store.connection() as db:
        holding = db.execute("INSERT INTO holdings(account_id,instrument_class,name,identifier,holding_key,source,created_at,updated_at) "
                             "VALUES(?,'crypto','Bitcoin','BTC','id:BTC','manual','t','t')", (wallet["id"],)).lastrowid
        db.execute("INSERT INTO investment_events(account_id,holding_id,event_date,event_type,amount_minor,quantity,review_status,created_at) "
                   "VALUES(?,?,'2026-01-01','buy',300000,'0.1','verified','t')", (wallet["id"], holding))
        assert CryptoPrices(store).wanted(db)[0], "the setup must leave a coin to price"
    inbox_scan(store, {"shop.png": b"synthetic shop receipt"})
    doc = documents_by_name(store)["shop.png"]
    receipt_id = Ledger(store).publish_receipt(
        {"merchant": "Corner Shop", "purchase_date": "2026-09-10", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
         "total_minor": 299, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-0"]},
         "items": [{"description": "PENCILS", "product_code": GTIN, "quantity": "1", "unit_price_minor": 299, "line_total_minor": 299,
                    "discount_minor": None, "locator": {"line_ids": ["line-1"]}}]},
        {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "shop.png", "run_id": "shop.png"}, "proposed")["id"]
    assert manager.reasoning_config.model == ""
    before = counts(store)
    for _ in range(2):  # The retry gives the same result.
        prices = client.post("/api/prices/refresh")
        assert prices.status_code == 400, prices.text
        rates = client.post("/api/rates/refresh")
        assert rates.status_code == 400, rates.text
        run = client.post(f"/api/receipts/{receipt_id}/item-resolution-runs")
        assert run.status_code == 202, run.text
        manager.future.result(timeout=30)
        result = client.get(f"/api/item-resolution-runs/{run.json()['run_id']}").json()
        assert result["status"] == "succeeded", result["error"]
        assert [line["method"] for line in result["result"]["lines"]] == [None]
        assert all(line["proposal_id"] is None for line in result["result"]["lines"])
    hosts = {"api.coingecko.com", "www.ecb.europa.eu", "world.openfoodfacts.org"}
    assert set(no_egress.hosts()) == hosts
    assert set(no_egress.hosts("sandbox")) == hosts and no_egress.hosts("double") == []
    assert sorted(refusals(caplog)) == sorted(REFUSED_LOG + host for host in hosts)
    assert counts(store) == before


def test_sc05_family_sync_to_tailnet_refused(sandboxed, no_egress, caplog):
    caplog.set_level(logging.WARNING, logger="home_manager.sandbox")
    root = sandboxed.root
    family = FamilyFolder.create(root / "remote-family", "Remote family")
    try:
        member = family.add_member("Me", "remote")
        token = family.new_token(member["member_id"])
        data = family.data
    finally:
        family.close()
    (root / "invites").mkdir()
    invite = write_invite(data, member, root / "invites", PASSPHRASE, "100.64.0.1:8767", token)
    response = sandboxed.client.post("/api/family-membership", json={"invite_file": str(invite), "passphrase": PASSPHRASE})
    assert response.status_code == 201, response.text
    sandboxed.manager.future.result(timeout=30)
    assert [item for item in no_egress.attempts if item.host == "100.64.0.1"] == [Attempt("100.64.0.1", "getaddrinfo", "sandbox")]
    assert REFUSED_LOG + "100.64.0.1" in refusals(caplog)


def test_hub_stays_off_in_test_mode(sandboxed, monkeypatch):
    asked = []
    monkeypatch.setattr(family_hub, "tailnet_address", lambda: asked.append(True) or "100.64.0.1")
    assert sandboxed.client.post("/api/families", json={"name": "Family", "folder": str(sandboxed.root / "family")}).status_code == 201
    status = sandboxed.manager.refresh_hub()
    assert not status["listening"] and status["reason"].startswith("Tailscale isn't running")
    assert asked == []


# SC-08, SC-11: model addresses and test mode off ---------------------------------------------------------------------

MODEL_ROUTES = {"vision": ("/api/vision-settings", {}), "reasoning": ("/api/reasoning-settings", {}),
                "reviewer": ("/api/reviewer-settings", {"provider": "chat"}), "decision": ("/api/decision-settings", {"provider": "lmstudio"})}
REFUSED_EVERYWHERE = ["http://192.168.1.50:1234/v1", "http://example.invalid/v1", "http://100.64.0.1:1234/v1", "http://localhost:1234/v1"]
TAILNET = ["http://100.64.0.1:1234/v1", "http://gpu.example.ts.net:1234/v1"]
TOKEN = "t" * 43


def model_computer(client, url):
    return client.put("/api/model-computer", json={"provider": "family_gpu", "gpu_host_url": url, "token": TOKEN})


def check_model_settings(client, egress, test_mode):
    for name, (route, extra) in MODEL_ROUTES.items():
        for url in REFUSED_EVERYWHERE:
            before = client.get("/api/settings").json()[name]
            response = client.put(route, json={**extra, "base_url": url, "model": "m"})
            assert 400 <= response.status_code < 500, (name, url, response.text)
            assert client.get("/api/settings").json()[name] == before
        assert client.put(route, json={**extra, "base_url": "http://127.0.0.1:1235/v1", "model": "m"}).status_code == 200
        assert client.get("/api/settings").json()[name]["base_url"] == "http://127.0.0.1:1235/v1"
    for url in ("http://192.168.1.50:1234/v1", "http://example.invalid/v1"):
        assert 400 <= model_computer(client, url).status_code < 500
    for url in TAILNET:
        before = client.get("/api/settings").json()["model_computer"]
        response = model_computer(client, url)
        if test_mode:
            assert 400 <= response.status_code < 500 and "Test instance" in response.text, response.text
            assert client.get("/api/settings").json()["model_computer"] == before
        else:
            assert response.status_code == 200, response.text
            assert client.get("/api/settings").json()["model_computer"]["gpu_host_url"] == url
    assert egress.outbound == []


def test_sc08_model_addresses_in_test_mode(sandboxed, no_egress):
    check_model_settings(sandboxed.client, no_egress, test_mode=True)


def test_sc11_test_mode_off_changes_nothing(plain, no_egress, tmp_path):
    client, manager = plain
    # Step 2: a folder the test-mode list would treat as protected is an ordinary folder.
    decoy = make_decoy(tmp_path / "decoy-protected-folder")
    assert client.post("/api/sources", json={"path": str(decoy)}).status_code == 201
    # Step 3: a tailnet model computer is accepted, as today; the local model settings refuse what they refuse today.
    check_model_settings(client, no_egress, test_mode=False)
    # Step 4: the app doesn't block https_get; the attempt reaches the socket layer and only the double refuses it.
    with pytest.raises(LookupFailed):
        https_get("https://example.invalid/")
    assert no_egress.outbound == [Attempt("example.invalid", "getaddrinfo", "double")]
    assert sandbox.status() == {"paths": False, "egress": False}
