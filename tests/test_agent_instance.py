"""The agent test instance (docs/development.md "Agent test instance"): the shared seed and the harness lifecycle.

Every instance here runs at a tmp_path root on a free port with LOCALAPPDATA/APPDATA pointed at an empty decoy, never at
tests/.tmp:8775. "LM Studio" is a second fake model server (tests/model_server.py); the real one is used only by tests
marked lmstudio, which run with `pytest -m lmstudio`.
"""

import ast
from datetime import date
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import time

from fastapi.testclient import TestClient
import pytest

from home_manager.app.api import create_app
from home_manager.core import sandbox
from home_manager.library.scanner import ScanLimits
from model_server import start_model_server
import seed_household
from seed_household import STEPS, SeedStepFailed, seed
from test_agent_guards import no_egress  # noqa: F401  (a fixture)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "test_instance.py"
PYTHON = sys.executable
# Everything that seeds a whole household: each imports seed from seed_household and defines no seed of its own.
SEED_CALLERS = [ROOT / ".claude" / "skills" / "ui-redesign" / "scripts" / "ui_shots.py", SCRIPT,
                ROOT / "tests" / "test_agent_instance_browser.py"]
SEED_FUNCTIONS = {"seed", "seed_ledger", "seed_today", "seed_money", "seed_settings"}
SECTIONS = ("accounts", "transactions", "documents", "to_check", "investments", "plans", "items", "recurring")
MODELS = ["--vision-model", "synthetic-vision", "--reasoning-model", "synthetic-reasoning"]
browser_test = pytest.mark.skipif(os.environ.get("RUN_BROWSER_TESTS") != "1", reason="Opt-in local browser test")


# The shared seed (in-process) ----------------------------------------------------------------------------------------

def test_one_household_seed():
    for path in SEED_CALLERS:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported = {(node.module, alias.name) for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) for alias in node.names}
        assert ("seed_household", "seed") in imported, path
        defined = {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}
        assert not defined & SEED_FUNCTIONS, (path, defined & SEED_FUNCTIONS)
    tree = ast.parse(Path(seed_household.__file__).read_text(encoding="utf-8"))
    assert SEED_FUNCTIONS <= {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}


@pytest.fixture
def household(tmp_path, local_model):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}):
        yield app.state.manager, tmp_path, local_model


def raw_counts(library):
    """Read-only counts per manifest section, written here independently of the manifest code."""
    queries = {"accounts": "SELECT count(*) FROM accounts", "transactions": "SELECT count(*) FROM transactions",
               "documents": "SELECT count(*) FROM occurrences", "investments": "SELECT count(*) FROM investment_accounts",
               "plans": "SELECT count(*) FROM scenarios", "items": "SELECT count(*) FROM inventory_lots",
               "recurring": "SELECT count(*) FROM recurring_obligations",
               "to_check": "SELECT (SELECT count(*) FROM receipts WHERE review_status IN ('proposed','needs_review'))"
                           "+(SELECT count(*) FROM statements WHERE review_status IN ('proposed','needs_review'))"
                           "+(SELECT count(*) FROM income_records WHERE review_status IN ('proposed','needs_review'))"
                           "+(SELECT count(*) FROM item_resolutions WHERE review_status='proposed')"}
    db = sqlite3.connect((library / "inventory.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        return {name: db.execute(sql).fetchone()[0] for name, sql in queries.items()}
    finally:
        db.close()


def test_seed_fills_the_open_library_and_returns_a_manifest(household):
    manager, root, model = household
    manager.configure(str(root / "managed"))
    ids, manifest = seed(manager, root, model)
    assert {"receipt_doc", "plan", "drill_lot", "old_statement_doc", "brokerage_account"} <= ids.keys()
    assert manifest["values"] == {"groceries_budget_minor": 25000, "car_loan_minor": 600000}
    assert isinstance(manifest["taxes_seeded"], bool)
    raw = raw_counts(root / "managed")
    assert raw == {name: manifest["counts"][name] for name in raw}
    assert all(manifest["counts"][name] > 0 for name in SECTIONS)
    assert manager.settings()["managed_directory"] == str(root / "managed")  # Seeded where it was opened; no configure.
    assert (root / "scanner").is_dir()


def test_a_broken_step_names_itself(household):
    manager, root, model = household
    manager.configure(str(root / "managed"))
    with pytest.raises(SeedStepFailed) as failed:
        seed(manager, root, model, fail_step="seed_investments")
    assert failed.value.step == "seed_investments" and str(failed.value) == "seed step failed: seed_investments"
    raw = raw_counts(root / "managed")
    assert raw["investments"] == 0 and raw["plans"] == 0  # Later steps never ran.


def test_seed_refuses_unknown_steps_and_no_library(household):
    manager, root, model = household
    assert "seed_investments" in STEPS
    with pytest.raises(ValueError, match="Unknown seed step"):
        seed(manager, root, model, fail_step="seed_nothing")
    with pytest.raises(RuntimeError, match="Open a library"):
        seed(manager, root, model)
    assert not (root / "scanner").exists()


def test_status_probes_guards(tmp_path, monkeypatch, no_egress):  # noqa: F811
    sandbox.activate(tmp_path)
    try:
        assert sandbox.status() == {"paths": True, "egress": True}
        with monkeypatch.context() as patch:
            patch.setattr(sandbox, "check_path", lambda value: None)
            assert sandbox.status()["paths"] is False
        with monkeypatch.context() as patch:
            patch.setattr(sandbox, "_audit", lambda event, args: None)
            assert sandbox.status()["egress"] is False
    finally:
        sandbox.deactivate()
    assert [(item.host, item.refused_by) for item in no_egress.attempts] == [
        (sandbox.PROBE_HOST, "sandbox"), (sandbox.PROBE_HOST, "sandbox"), (sandbox.PROBE_HOST, "double")]


# Harness helpers -----------------------------------------------------------------------------------------------------

def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def port_free(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


class Harness:
    """Runs scripts/test_instance.py in subprocesses against one root and port, with a decoy LOCALAPPDATA."""

    def __init__(self, root, fake_appdata, lmstudio, port=None, extra=None):
        self.root, self.port, self.lmstudio = Path(root), port or free_port(), lmstudio
        fake_appdata.mkdir(parents=True, exist_ok=True)
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("HM_TEST_")}
        self.env.update(LOCALAPPDATA=str(fake_appdata), APPDATA=str(fake_appdata), HM_TEST_ROOT=str(self.root),
                        HM_TEST_PORT=str(self.port), HM_TEST_LMSTUDIO=lmstudio, **(extra or {}))

    def run(self, *args, env=None, timeout=300, check=None):
        result = subprocess.run([PYTHON, str(SCRIPT), *args], env={**self.env, **(env or {})}, cwd=ROOT,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if check is not None:
            assert result.returncode == check, (args, result.returncode, result.stdout, result.stderr, self.logs())
        return result

    def logs(self):
        """The instance's server output and app log tails, for failure messages."""
        found = {}
        for path in (self.root / "server.log", self.root / "control" / "logs" / "home-manager.log"):
            if path.exists():
                found[path.name] = path.read_text(encoding="utf-8", errors="replace")[-3000:]
        return found

    def session(self):
        return json.loads((self.root / "session.json").read_text(encoding="utf-8"))

    def seeded(self):
        return json.loads((self.root / "seed.json").read_text(encoding="utf-8"))

    def api(self, method, path, body=None):
        """Keep-alive, and the client closes first (docs/development.md "Windows loopback resets")."""
        session = self.session()
        token = session["link"].partition("#token=")[2]
        connection = http.client.HTTPConnection("127.0.0.1", int(session["base_url"].rsplit(":", 1)[1]), timeout=30)
        try:
            connection.request(method, path, body=json.dumps(body) if body is not None else None,
                               headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            response = connection.getresponse()
            data = response.read()
        finally:
            connection.close()
        assert response.status < 400, (method, path, response.status, data[:300])
        return json.loads(data or b"null")

    def stop(self):
        if (self.root / ".hm-test-instance").exists():
            self.run("stop", timeout=60)
        assert port_free(self.port)


def rebase(value, old, new):
    """value with the old root replaced by the new one, in the same spelling (raw, lower-cased, forward slashes); only
    where the root is the whole value or is followed by a separator."""
    forms = [(old, new), (os.path.normcase(old), os.path.normcase(new))]
    forms += [(o.replace("\\", "/"), n.replace("\\", "/")) for o, n in forms]
    for o, n in forms:
        if value == o or value.startswith((o + "\\", o + "/")):
            return n + value[len(o):]
    return value


def rebase_json(data, old, new):
    if isinstance(data, dict):
        return {key: rebase_json(item, old, new) for key, item in data.items()}
    if isinstance(data, list):
        return [rebase_json(item, old, new) for item in data]
    return rebase(data, old, new) if isinstance(data, str) else data


def ordinary_tables(db):
    rows = db.execute("SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    virtual = [name for name, sql in rows if (sql or "").upper().startswith("CREATE VIRTUAL")]
    return [name for name, _ in rows if name not in virtual and not any(name.startswith(item + "_") for item in virtual)]


def restore(template, run):
    """Copy the stopped template instance to run, rewriting every absolute path that names the template root."""
    if run.exists():
        shutil.rmtree(run)
    shutil.copytree(template, run, ignore=shutil.ignore_patterns("logs", "server.log"))
    old, new = str(template), str(run)
    for path in run.rglob("*.json"):
        path.write_text(json.dumps(rebase_json(json.loads(path.read_text(encoding="utf-8")), old, new), indent=2), encoding="utf-8")
    db = sqlite3.connect(run / "library" / "inventory.sqlite3")
    try:
        with db:
            for table in ordinary_tables(db):
                for column in [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]:
                    values = [row[0] for row in db.execute(f'SELECT DISTINCT "{column}" FROM "{table}" WHERE typeof("{column}")=\'text\'')]
                    for value in values:
                        if (changed := rebase(value, old, new)) != value:
                            db.execute(f'UPDATE "{table}" SET "{column}"=? WHERE "{column}"=?', (changed, value))
        leftovers = [(table, column) for table in ordinary_tables(db) for column in [row[1] for row in db.execute(f'PRAGMA table_info("{table}")')]
                     if db.execute(f'SELECT 1 FROM "{table}" WHERE typeof("{column}")=\'text\' AND instr(lower("{column}"), ?) '
                                   f'OR instr(lower(replace("{column}", \'\\\', \'/\')), ?) LIMIT 1',
                                   (old.lower(), old.lower().replace("\\", "/"))).fetchone()]
    finally:
        db.close()
    assert leftovers == [], leftovers
    needles = {old.lower(), old.lower().replace("\\", "/"), old.lower().replace("\\", "\\\\")}
    for path in run.rglob("*"):
        if path.suffix in (".json", ".txt", ".yaml", ".log"):
            text = path.read_text(encoding="utf-8", errors="replace").lower()
            assert not any(needle in text for needle in needles), path
    profiles = json.loads((run / "control" / "profiles.json").read_text(encoding="utf-8"))
    assert all(Path(item["folder"]).is_relative_to(run) for item in profiles["profiles"])


@pytest.fixture(scope="module")
def lmstudio():
    """The "LM Studio" double: a second fake model server that records every request."""
    state, stop = start_model_server()
    try:
        yield state
    finally:
        stop()


@pytest.fixture(scope="module")
def template(tmp_path_factory, lmstudio):
    """One real reset, kept stopped as the template that seeded_instance copies."""
    base = tmp_path_factory.mktemp("template")
    harness = Harness(base / "instance", base / "fake-localappdata", lmstudio["config"].base_url)
    harness.run("reset", *MODELS, check=0)
    return harness


@pytest.fixture
def seeded_instance(tmp_path_factory, template, lmstudio):
    """A fresh copy of the template at one fixed run root (tests run one after another), not started."""
    base = tmp_path_factory.getbasetemp() / "run"
    harness = Harness(base / "instance", base / "fake-localappdata", lmstudio["config"].base_url)
    if (harness.root / ".hm-test-instance").exists():
        harness.run("stop", timeout=60)
    restore(template.root, harness.root)
    try:
        yield harness
    finally:
        harness.stop()


@pytest.fixture
def fresh(tmp_path, lmstudio):
    """A harness for a real reset at tmp_path/instance."""
    harness = Harness(tmp_path / "instance", tmp_path / "fake-localappdata", lmstudio["config"].base_url)
    try:
        yield harness
    finally:
        harness.stop()


def listing(folder):
    return sorted(str(path.relative_to(folder)) for path in folder.rglob("*"))


# SC-01, SC-13, SC-10: real resets ------------------------------------------------------------------------------------

def load_script():
    spec = importlib.util.spec_from_file_location("test_instance_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sc01_reset_start_verify(fresh, tmp_path):
    # Step 1 (static): the harness commands use the defaults and take the overrides.
    environment = json.loads((ROOT / "tests" / "environment.json").read_text(encoding="utf-8"))
    for name in ("start", "stop", "reset", "verify"):
        assert environment["commands"][name] == f"python scripts/test_instance.py {name}"
    assert environment["models"] == {"mode": "live_opt_in", "live_inference_opt_in": True}  # The harness preflight's name for LM Studio.
    script = load_script()
    assert (script.DEFAULT_ROOT, script.DEFAULT_PORT, script.DEFAULT_LMSTUDIO) == (ROOT / "tests" / ".tmp", 8775, "http://127.0.0.1:1234/v1")
    args = script.parse(["start", "--root", str(tmp_path / "x"), "--port", "9999", "--lmstudio", "http://127.0.0.1:1/v1"])
    assert (args.root, args.port, args.lmstudio) == (tmp_path / "x", 9999, "http://127.0.0.1:1/v1")
    # Step 2: reset.
    fresh.run("reset", *MODELS, check=0)
    profiles = json.loads((fresh.root / "control" / "profiles.json").read_text(encoding="utf-8"))["profiles"]
    assert [(item["name"], Path(item["folder"]).resolve()) for item in profiles] == [("Test", (fresh.root / "library").resolve())]
    uploads = {path.name for path in (fresh.root / "uploads").iterdir()}
    assert {"grocery-receipt.png", "dining-receipt.png", "fuel-receipt.png", "pay-stub.png", "bank-statement.pdf", "bill.png",
            "refund-receipt.png", "offer-letter.png", "README.txt"} <= uploads
    # Step 3: start.
    started = time.monotonic()
    fresh.run("start", check=0)
    assert time.monotonic() - started < 30
    session = fresh.session()
    assert session["base_url"] == f"http://127.0.0.1:{fresh.port}"
    token = session["link"].removeprefix(session["base_url"] + "/#token=")
    assert len(token) >= 32 and all(char.isalnum() or char in "-_" for char in token)
    assert session["seed_date"] == date.today().isoformat() and session["model_mode"] == "lmstudio"
    assert all(session["seed_counts"][name] > 0 for name in SECTIONS), session["seed_counts"]
    # Step 4: verify.
    result = fresh.run("verify", "--fresh", check=0)
    for name in ("server", "seed manifest", "path guard", "network guard", "LM Studio"):
        assert f"PASS {name}:" in result.stdout, result.stdout
    assert raw_counts(fresh.root / "library") == {name: session["seed_counts"][name] for name in SECTIONS}
    assert listing(tmp_path / "fake-localappdata") == []
    log = (fresh.root / "control" / "logs" / "home-manager.log").read_text(encoding="utf-8")
    assert "refused outbound host" not in log  # Nothing in the seeded household reaches for the internet.


def test_sc13_broken_seed_step(fresh, template):
    failed = fresh.run("reset", *MODELS, env={"HM_TEST_SEED_FAIL": "seed_investments"})
    assert failed.returncode != 0 and "seed step failed: seed_investments" in failed.stderr
    refused = fresh.run("start")
    assert refused.returncode != 0 and "seed incomplete, run reset" in refused.stderr
    assert not (fresh.root / "session.json").exists()
    fresh.run("reset", *MODELS, check=0)
    fresh.run("start", check=0)
    if fresh.seeded()["seed_date"] == template.seeded()["seed_date"]:
        assert fresh.seeded()["manifest"] == template.seeded()["manifest"]


def test_sc10_stop_reset_start_returns_to_the_seed(seeded_instance, template):
    harness = seeded_instance
    harness.run("start", check=0)
    first = harness.seeded()["manifest"]
    pid = json.loads((harness.root / "server.pid").read_text())["pid"]
    checking = harness.api("GET", "/api/finance/accounts")[0]
    harness.api("POST", "/api/finance/transactions", {"account_id": checking["id"], "date": date.today().isoformat(),
                                                       "description": "AGENT CHANGE", "amount": "1.23"})
    document = harness.api("GET", "/api/documents?limit=1")["items"][0]
    harness.api("POST", f"/api/documents/{document['id']}/trash", {"expected_hash": document["current_hash"], "confirmed": True})
    started = time.monotonic()
    harness.run("stop", check=0)
    assert port_free(harness.port) and time.monotonic() - started < 10
    assert load_script().creation_time(pid) is None
    harness.run("reset", check=0)
    harness.run("start", check=0)
    if harness.seeded()["seed_date"] == template.seeded()["seed_date"]:
        assert harness.seeded()["manifest"] == first  # Counts and the named seed values (budget, car loan).
    assert raw_counts(harness.root / "library") == {name: harness.session()["seed_counts"][name] for name in SECTIONS}
    db = sqlite3.connect((harness.root / "library" / "inventory.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        assert db.execute("SELECT count(*) FROM transactions WHERE description_raw='AGENT CHANGE'").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM occurrences WHERE deleted_at IS NOT NULL").fetchone()[0] == 0
    finally:
        db.close()


def test_reset_settles_before_manifest(fresh, template):
    for _ in range(2):
        fresh.run("reset", *MODELS, check=0)
        wal = fresh.root / "library" / "inventory.sqlite3-wal"
        assert not wal.exists() or wal.stat().st_size == 0
        from home_manager.core.paths import DirectoryLock
        DirectoryLock(fresh.root / "control").close()  # Not held: the seeding Manager closed.
        if fresh.seeded()["seed_date"] == template.seeded()["seed_date"]:
            assert fresh.seeded()["manifest"] == template.seeded()["manifest"]
            return
    pytest.fail("The date changed during both attempts.")


def test_reset_models(fresh, template, tmp_path, lmstudio):
    def model_settings(root):
        return {name: json.loads((root / "control" / f"{name}.json").read_text(encoding="utf-8")) for name in ("vision", "reasoning", "reviewer")}

    address = lmstudio["config"].base_url
    saved = model_settings(template.root)
    assert (saved["vision"]["base_url"], saved["vision"]["model"]) == (address, "synthetic-vision")
    assert (saved["reasoning"]["base_url"], saved["reasoning"]["model"]) == (address, "synthetic-reasoning")
    assert (saved["reviewer"]["provider"], saved["reviewer"]["base_url"], saved["reviewer"]["model"]) == ("chat", address, "synthetic-reasoning")
    # A second reset without the flags keeps the models.
    restore(template.root, fresh.root)
    fresh.run("reset", check=0)
    kept = model_settings(fresh.root)
    assert (kept["vision"]["model"], kept["reasoning"]["model"]) == ("synthetic-vision", "synthetic-reasoning")
    # With no IDs at all, the reviewer is off and verify warns; every model address is LM Studio's.
    bare = Harness(tmp_path / "bare", tmp_path / "fake-localappdata", address)
    bare.run("reset", check=0)
    settings = model_settings(bare.root)
    assert settings["reviewer"]["provider"] == "off"
    assert {settings["vision"]["base_url"], settings["reasoning"]["base_url"]} == {address}
    bare.run("start", check=0)
    try:
        result = bare.run("verify", check=0)
        assert "WARN models:" in result.stdout
    finally:
        bare.stop()


def test_reset_keeps_evidence(seeded_instance):
    shot = seeded_instance.root / "evidence" / "x.png"
    shot.write_bytes(b"evidence")
    seeded_instance.run("reset", check=0)
    assert shot.read_bytes() == b"evidence"


# Refusals ------------------------------------------------------------------------------------------------------------

def test_reset_refuses_root_without_sentinel(tmp_path, lmstudio):
    folder = tmp_path / "project"
    folder.mkdir()
    (folder / "keep.txt").write_text("mine", encoding="utf-8")
    harness = Harness(folder, tmp_path / "fake-localappdata", lmstudio["config"].base_url)
    result = harness.run("reset")
    assert result.returncode == 2 and "not a test instance folder" in result.stderr
    assert listing(folder) == ["keep.txt"]


def test_root_overlapping_protected_refused(tmp_path, lmstudio):
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    canary = decoy / "canary.txt"
    canary.write_text("canary", encoding="utf-8")
    (tmp_path / "fake-localappdata").mkdir()
    mtime, before = canary.stat().st_mtime_ns, listing(tmp_path)
    for root in (decoy / "agent", decoy, tmp_path):
        harness = Harness(root, tmp_path / "fake-localappdata", lmstudio["config"].base_url, extra={"HM_TEST_PROTECTED": str(decoy)})
        for command in ("reset", "start", "stop", "verify"):
            result = harness.run(command)
            assert result.returncode == 2 and "overlaps protected data" in result.stderr, (root, command, result.stderr)
    assert listing(tmp_path) == before and canary.stat().st_mtime_ns == mtime


def test_commands_refuse_root_without_sentinel(tmp_path, lmstudio):
    folder = tmp_path / "project"
    (folder / "evidence").mkdir(parents=True)
    decoys = {"evidence/x.png": b"png", "session.json": b"{}", "server.pid": b'{"pid": 1, "created": 1}', "stop.request": b"stop"}
    for name, data in decoys.items():
        (folder / name).write_bytes(data)
    stamps = {name: (folder / name).stat().st_mtime_ns for name in decoys}
    harness = Harness(folder, tmp_path / "fake-localappdata", lmstudio["config"].base_url)
    finding = ["finding", "--screenshot", str(folder / "evidence" / "x.png"), "--target", str(folder / "bugs.md"), "--url", "http://127.0.0.1:1/",
               "--route", "#/home", "--symptom", "s", "--kind", "bug", "--severity", "low", "--steps", "s", "--expected", "e",
               "--actual", "a", "--agent", "agent"]
    for command in (["start"], ["stop"], ["verify"], finding):
        result = harness.run(*command)
        assert result.returncode == 2 and "not a test instance folder" in result.stderr, (command, result.stderr)
    for name, data in decoys.items():
        assert (folder / name).read_bytes() == data and (folder / name).stat().st_mtime_ns == stamps[name]


def test_sc17_port_in_use(seeded_instance):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", seeded_instance.port))
        listener.listen()
        started = time.monotonic()
        result = seeded_instance.run("start")
        assert result.returncode != 0 and str(seeded_instance.port) in result.stderr
        assert time.monotonic() - started < 10
        assert not (seeded_instance.root / "session.json").exists()


def test_reset_refuses_foreign_port(seeded_instance):
    before = listing(seeded_instance.root)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", seeded_instance.port))
        listener.listen()
        result = seeded_instance.run("reset")
    assert result.returncode == 1 and "in use by another program" in result.stderr
    assert listing(seeded_instance.root) == before


def test_sc19_reset_while_running(seeded_instance):
    seeded_instance.run("start", check=0)
    before = listing(seeded_instance.root)
    result = seeded_instance.run("reset")
    assert result.returncode != 0 and "stop the instance first" in result.stderr
    assert listing(seeded_instance.root) == before
    seeded_instance.run("verify", check=0)


def test_verify_incomplete_seed(seeded_instance):
    seeded_instance.run("start", check=0)
    (seeded_instance.root / ".seed-incomplete").write_text("x", encoding="utf-8")
    result = seeded_instance.run("verify")
    assert result.returncode == 1 and "FAIL seed manifest: incomplete, run reset" in result.stdout


def test_start_reports_failed_serve(seeded_instance):
    started = time.monotonic()
    result = seeded_instance.run("start", env={"HM_TEST_SERVE_FAIL": "1"})
    assert result.returncode == 1 and "server did not start" in result.stderr and "HM_TEST_SERVE_FAIL" in result.stderr
    assert time.monotonic() - started < 30
    assert not (seeded_instance.root / "session.json").exists() and not (seeded_instance.root / "server.pid").exists()
    assert port_free(seeded_instance.port)


# Restarts and processes ----------------------------------------------------------------------------------------------

def test_restored_instance_is_independent(seeded_instance, template):
    harness = seeded_instance
    sources = sqlite3.connect((harness.root / "library" / "inventory.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        paths = [row[0] for row in sources.execute("SELECT path FROM sources")]
    finally:
        sources.close()
    assert paths and all(Path(path).is_relative_to(harness.root) for path in paths)
    harness.run("start", check=0)
    harness.run("verify", "--fresh", check=0)
    documents = raw_counts(harness.root / "library")["documents"]
    receipt = harness.root / "uploads" / "grocery-receipt.png"
    shutil.copy(receipt, harness.root / "library" / "Library" / "Inbox" /"dropped.png")
    harness.api("POST", "/api/inbox-scans", {})
    deadline = time.monotonic() + 60
    while raw_counts(harness.root / "library")["documents"] == documents and time.monotonic() < deadline:
        time.sleep(0.5)
    time.sleep(2)  # Any second capture of the seeded Inbox would land now.
    assert raw_counts(harness.root / "library")["documents"] == documents + 1
    harness.api("POST", "/api/finance/transactions", {"account_id": harness.api("GET", "/api/finance/accounts")[0]["id"],
                                                       "date": date.today().isoformat(), "description": "LEFTOVER", "amount": "1.00"})


def test_changes_from_one_test_are_gone_in_the_next(seeded_instance):
    db = sqlite3.connect((seeded_instance.root / "library" / "inventory.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        assert db.execute("SELECT count(*) FROM transactions WHERE description_raw='LEFTOVER'").fetchone()[0] == 0
    finally:
        db.close()


def test_sc18_restart_keeps_changes(seeded_instance):
    harness = seeded_instance
    harness.run("start", check=0)
    first = harness.session()
    account = harness.api("GET", "/api/finance/accounts")[0]
    harness.api("POST", "/api/finance/transactions", {"account_id": account["id"], "date": date.today().isoformat(),
                                                       "description": "KEPT ACROSS RESTART", "amount": "2.00"})
    harness.run("stop", check=0)
    harness.run("start", check=0)
    second = harness.session()
    assert second["link"] != first["link"] and second["seed_date"] == first["seed_date"]
    db = sqlite3.connect((harness.root / "library" / "inventory.sqlite3").as_uri() + "?mode=ro", uri=True)
    try:
        assert db.execute("SELECT count(*) FROM transactions WHERE description_raw='KEPT ACROSS RESTART'").fetchone()[0] == 1
    finally:
        db.close()
    result = harness.run("verify", check=0)
    assert "changed since" in result.stdout


def test_verify_after_agent_change(seeded_instance):
    harness = seeded_instance
    harness.run("start", check=0)
    account = harness.api("GET", "/api/finance/accounts")[0]
    harness.api("POST", "/api/finance/transactions", {"account_id": account["id"], "date": date.today().isoformat(),
                                                       "description": "AGENT", "amount": "3.00"})
    harness.run("verify", check=0)
    result = harness.run("verify", "--fresh")
    assert result.returncode == 1 and "FAIL seed manifest: counts differ" in result.stdout and "transactions" in result.stdout


def listening_pid(port):
    """The pid that owns the listening socket on 127.0.0.1:port, from netstat (independent of the harness)."""
    output = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True).stdout
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 5 and parts[1] == f"127.0.0.1:{port}" and parts[3] == "LISTENING":
            return int(parts[4])
    return None


def test_pid_is_the_server(seeded_instance):
    seeded_instance.run("start", check=0)
    record = json.loads((seeded_instance.root / "server.pid").read_text())
    assert record["pid"] == listening_pid(seeded_instance.port)
    assert load_script().creation_time(record["pid"]) == record["created"]


def test_stop_from_another_console(seeded_instance):
    harness = seeded_instance
    harness.run("start", check=0)
    pid = json.loads((harness.root / "server.pid").read_text())["pid"]
    started = time.monotonic()
    process = subprocess.Popen([PYTHON, str(SCRIPT), "stop"], env=harness.env, cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
    assert process.wait(timeout=60) == 0
    assert time.monotonic() - started < 8  # The stop request, well before the 10 s fallback.
    assert port_free(harness.port) and load_script().creation_time(pid) is None


def test_stale_pid_is_not_signalled(seeded_instance):
    helper = subprocess.Popen([PYTHON, "-c", "import time; time.sleep(120)"])
    try:
        created = load_script().creation_time(helper.pid)
        (seeded_instance.root / "server.pid").write_text(json.dumps({"pid": helper.pid, "created": created + 1}))
        result = seeded_instance.run("stop", check=0)
        assert "not running" in result.stdout
        assert helper.poll() is None and not (seeded_instance.root / "server.pid").exists()
    finally:
        helper.kill()


# Warnings, guards and models -----------------------------------------------------------------------------------------

def test_sc12_and_start_warn_on_8765(seeded_instance):
    if not port_free(8765):
        pytest.skip("Port 8765 is in use (the live app?); this test never connects to it.")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 8765))
        listener.listen()
        started = seeded_instance.run("start", check=0)
        assert "listening on 127.0.0.1:8765" in started.stdout
        result = seeded_instance.run("verify", check=0)
        assert "WARN port 8765:" in result.stdout
    result = seeded_instance.run("verify", check=0)
    assert "8765" not in result.stdout


def test_verify_fails_without_guards(seeded_instance):
    """FR-09's "a guard is off": the plain launcher on the instance's settings folder has no test mode."""
    harness = seeded_instance
    launcher = subprocess.Popen([PYTHON, "-m", "home_manager", "--control-dir", str(harness.root / "control"), "--port", str(harness.port)],
                                env=harness.env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        link = None
        deadline = time.monotonic() + 30
        while link is None and time.monotonic() < deadline:
            line = launcher.stdout.readline()
            if line.startswith("http://127.0.0.1:"):
                link = line.strip()
        assert link, "the launcher printed no link"
        while port_free(harness.port) and time.monotonic() < deadline:
            time.sleep(0.1)
        base = f"http://127.0.0.1:{harness.port}"
        (harness.root / "session.json").write_text(json.dumps({"base_url": base, "link": link, "seed_date": harness.seeded()["seed_date"],
                                                               "lmstudio": harness.lmstudio}), encoding="utf-8")
        result = harness.run("verify")
        assert result.returncode == 1 and "FAIL guards: test mode is off" in result.stdout, result.stdout
    finally:
        launcher.kill()
        launcher.wait(timeout=30)
        (harness.root / "session.json").unlink(missing_ok=True)


def test_lmstudio_deselected_by_default():
    collected = subprocess.run([PYTHON, "-m", "pytest", "--collect-only", "-q", str(Path(__file__))], cwd=ROOT,
                               capture_output=True, text=True).stdout
    assert "test_sc06_real_lmstudio" not in collected and "test_sc01_reset_start_verify" in collected
    opted = subprocess.run([PYTHON, "-m", "pytest", "--collect-only", "-q", "-m", "lmstudio", str(Path(__file__))], cwd=ROOT,
                           capture_output=True, text=True).stdout
    assert "test_sc06_real_lmstudio" in opted


# Uploads read through LM Studio (browser) ----------------------------------------------------------------------------

def grocery_outputs():
    """The double's replies for uploads/grocery-receipt.png, as seed_documents scripts them: its text, then the reading."""
    from evals.synthetic import documents
    from test_extraction import MISSING, cite, value
    lines = documents()[2]["lines"]
    items = [(5, "RICE 2LB", "3.49"), (6, "WHOLE MILK 1GAL", "3.89"), (7, "EGGS DOZEN", "4.59"), (8, "TOMATO SAUCE", "2.89"), (9, "PASTA", "1.99")]
    shown = "Green Leaf Grocery"
    return [{"full_text": "\n".join(lines)},
            {"document_type": "receipt", "evidence": cite(1, lines[0]), "issuer": value(shown, 1, lines[0]), "document_date": value(lines[1], 2)},
            {"merchant": value(shown, 1, lines[0]), "purchase_date": value(lines[1], 2), "currency": value("USD", 3, lines[2]),
             "subtotal": value("16.85", 10, lines[9]), "tax": value("1.39", 11, lines[10]), "tip": MISSING, "total": value("18.24", 12, lines[11])},
            {"seller": value(shown, 1, lines[0]), "seller_basis": "printed", "location": MISSING},
            {"items": [{"description": text, "product_code": None, "quantity": "1", "unit_price": price, "line_total": price, "discount": None,
                        "taxed": None, "evidence": cite(number, lines[number - 1])} for number, text, price in items]},
            {"description": "groceries", "category": "groceries", "recurrence": None, "item_categories": ["groceries"] * len(items)},
            {"rewards": []}]


def scan_upload(harness, name, page):
    """Drop uploads/<name> into the library Inbox and press Scan Inbox on Processing, as an agent would. Returns its hash."""
    upload = harness.root / "uploads" / name
    shutil.copy(upload, harness.root / "library" / "Library" / "Inbox" /name)
    page.goto(harness.session()["base_url"] + "/#/processing")
    page.locator("#pr2-scan").click()
    return hashlib.sha256(upload.read_bytes()).hexdigest()


def parse_status(harness, blob_hash, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        db = sqlite3.connect((harness.root / "library" / "inventory.sqlite3").as_uri() + "?mode=ro", uri=True)
        try:
            row = db.execute("SELECT status, error FROM parse_runs WHERE blob_hash=? ORDER BY created_at DESC LIMIT 1", (blob_hash,)).fetchone()
            present = db.execute("SELECT count(*) FROM occurrences WHERE current_hash=?", (blob_hash,)).fetchone()[0]
        finally:
            db.close()
        if row and row[0] not in ("queued", "running"):
            return row, present
        time.sleep(0.5)
    return row, present


def open_browser(driver, harness):
    browser = driver.chromium.launch(channel="msedge", headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(harness.session()["link"])
    page.wait_for_load_state("networkidle")
    return browser, page, errors


@browser_test
def test_sc06d_upload_read_by_the_lmstudio_double(seeded_instance, lmstudio):
    playwright = pytest.importorskip("playwright.sync_api")
    harness = seeded_instance
    harness.run("start", check=0)
    lmstudio["requests"].clear()
    lmstudio["outputs"] = grocery_outputs()
    with playwright.sync_playwright() as driver:
        browser, page, errors = open_browser(driver, harness)
        blob_hash = scan_upload(harness, "grocery-receipt.png", page)
        (status, error), present = parse_status(harness, blob_hash, 120)
        browser.close()
    assert present == 1 and status == "succeeded", error
    models = [request.get("model") for request in lmstudio["requests"]]
    assert models and models[0] == "synthetic-vision" and set(models) <= {"synthetic-vision", "synthetic-reasoning"}, models
    assert "synthetic-reasoning" in models
    assert errors == []
    log = (harness.root / "control" / "logs" / "home-manager.log").read_text(encoding="utf-8")
    assert "refused outbound host" not in log


@browser_test
def test_sc07_lmstudio_down(fresh):
    playwright = pytest.importorskip("playwright.sync_api")
    harness = fresh
    closed = f"http://127.0.0.1:{free_port()}/v1"
    harness.env["HM_TEST_LMSTUDIO"] = closed
    harness.run("reset", *MODELS, check=0)
    harness.run("start", check=0)
    result = harness.run("verify", check=0)
    assert f"WARN LM Studio: {closed}" in result.stdout
    before = raw_counts(harness.root / "library")
    with playwright.sync_playwright() as driver:
        browser, page, errors = open_browser(driver, harness)
        blob_hash = scan_upload(harness, "grocery-receipt.png", page)
        row, present = parse_status(harness, blob_hash, 120)
        for route in ("home", "documents"):
            page.goto(harness.session()["base_url"] + f"/#/{route}")
            page.wait_for_selector("[aria-busy='true']", state="detached", timeout=120000)
        browser.close()
    assert present == 1  # The document isn't lost.
    assert row is None or row[0] == "failed", row
    after = raw_counts(harness.root / "library")
    assert after["documents"] == before["documents"] + 1
    assert {key: value for key, value in after.items() if key != "documents"} == {key: value for key, value in before.items() if key != "documents"}
    assert errors == []


@pytest.mark.lmstudio
def test_sc06_real_lmstudio(tmp_path):
    """The developer's LM Studio reads an upload (states only, never values). Run with `pytest -m lmstudio`, passing model IDs
    through HM_TEST_VISION_MODEL / HM_TEST_REASONING_MODEL and the address through HM_TEST_LMSTUDIO if not the default."""
    playwright = pytest.importorskip("playwright.sync_api")
    harness = Harness(tmp_path / "instance", tmp_path / "fake-localappdata", os.environ.get("HM_TEST_LMSTUDIO") or "http://127.0.0.1:1234/v1",
                      extra={key: os.environ[key] for key in ("HM_TEST_VISION_MODEL", "HM_TEST_REASONING_MODEL") if os.environ.get(key)})
    try:
        harness.run("reset", check=0)
        harness.run("start", check=0)
        with playwright.sync_playwright() as driver:
            browser, page, errors = open_browser(driver, harness)
            blob_hash = scan_upload(harness, "grocery-receipt.png", page)
            (status, error), present = parse_status(harness, blob_hash, 300)
            browser.close()
        assert present == 1 and status in ("succeeded", "needs_review", "failed"), (status, error)
        assert errors == []
        log = (harness.root / "control" / "logs" / "home-manager.log").read_text(encoding="utf-8")
        assert "refused outbound host" not in log
    finally:
        harness.stop()
