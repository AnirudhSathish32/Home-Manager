"""The agent test instance: a synthetic Home Manager that Playwright agents explore (docs/development.md "Agent test instance").

    python scripts/test_instance.py reset    # rebuild <root> with the synthetic household (the instance must be stopped)
    python scripts/test_instance.py start    # serve it on 127.0.0.1:<port> in the background; writes <root>/session.json
    python scripts/test_instance.py verify   # server, seed, guards, LM Studio
    python scripts/test_instance.py stop
    python scripts/test_instance.py finding --url PAGE_URL --route R --symptom S --kind bug|friction|console-error
        --severity low|medium|high --steps S --expected E --actual A --screenshot <root>/evidence/X.png --agent NAME
        [--target docs/bugs.md]   # the only way agents record findings, under "## Agent findings"

Settings, by flag or environment: --root / HM_TEST_ROOT (tests/.tmp), --port / HM_TEST_PORT (8775), --lmstudio /
HM_TEST_LMSTUDIO (http://127.0.0.1:1234/v1), and for reset --vision-model / HM_TEST_VISION_MODEL and --reasoning-model /
HM_TEST_REASONING_MODEL (default: the previous instance's). Tests only: HM_TEST_PROTECTED (extra protected folders,
os.pathsep-separated), HM_TEST_SEED_FAIL (a seed step to break), HM_TEST_SERVE_FAIL (serve exits before listening),
HM_TEST_FINDING_DATE (an ISO date that finding records instead of today).

The server runs in test mode (core/sandbox.py): real data is off limits and nothing leaves this computer. Only this
script turns test mode on; `python -m home_manager` never does.
"""

import argparse
from datetime import date
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit

CHECKOUT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(CHECKOUT / "src"), str(CHECKOUT / "tests"), str(CHECKOUT)]

from home_manager.core import sandbox  # noqa: E402
from home_manager.core.paths import write_atomic  # noqa: E402

DEFAULT_ROOT = CHECKOUT / "tests" / ".tmp"
DEFAULT_PORT = 8775
DEFAULT_LMSTUDIO = "http://127.0.0.1:1234/v1"
LIVE_PORT = 8765
SENTINEL = ".hm-test-instance"
INCOMPLETE = ".seed-incomplete"
SETTLE_SECONDS = 120
START_SECONDS = 30
STOP_SECONDS = 10
DEFAULT_TARGET = CHECKOUT / "docs" / "bugs.md"
FINDING_FIELDS = ("url", "route", "symptom", "kind", "severity", "steps", "expected", "actual", "screenshot", "agent")
KINDS, SEVERITIES = ("bug", "friction", "console-error"), ("low", "medium", "high")
SECTION = "## Agent findings"
LOCK_SECONDS = 10
SHARED_WARNING = ("Something is listening on 127.0.0.1:8765 (the live app?). It shares LM Studio with this instance: "
                  "don't upload documents here while it is scanning.")


class Refused(Exception):
    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


# Settings and the root -----------------------------------------------------------------------------------------------

def parse(argv):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["reset", "start", "serve", "stop", "verify", "finding"])
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("HM_TEST_ROOT") or DEFAULT_ROOT))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HM_TEST_PORT") or DEFAULT_PORT))
    parser.add_argument("--lmstudio", default=os.environ.get("HM_TEST_LMSTUDIO"))
    parser.add_argument("--vision-model", default=os.environ.get("HM_TEST_VISION_MODEL"))
    parser.add_argument("--reasoning-model", default=os.environ.get("HM_TEST_REASONING_MODEL"))
    parser.add_argument("--fresh", action="store_true", help="verify: seed counts must equal the manifest exactly (right after reset)")
    for name in FINDING_FIELDS:  # finding; checked by finding itself, so a refusal can still delete the screenshot.
        parser.add_argument(f"--{name}")
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    args = parser.parse_args(argv)
    args.root = Path(os.path.abspath(args.root))
    return args


def extra_protected():
    return [item for item in os.environ.get("HM_TEST_PROTECTED", "").split(os.pathsep) if item]


def check_root(root):
    """Before any filesystem call: refuse a root that overlaps real data in either direction (lexical only)."""
    path = sandbox.norm(root)
    for protected in (*sandbox.default_protected(), *extra_protected()):
        key = sandbox.norm(protected)
        if sandbox.under(path, key) or sandbox.under(key, path):
            raise Refused(f"Test instance root overlaps protected data: {root}", 2)


def is_default(root):
    return sandbox.norm(root) == sandbox.norm(DEFAULT_ROOT)


def check_sentinel(root):
    if not is_default(root) and not (root / SENTINEL).is_file():
        raise Refused(f"not a test instance folder: {root}", 2)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


# Processes and ports -------------------------------------------------------------------------------------------------

def creation_time(pid):
    """The process's creation time if it is alive, else None. With the pid, it names one process (pids are reused)."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, *[ctypes.POINTER(wintypes.FILETIME)] * 4]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:  # STILL_ACTIVE
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(item) for item in times)):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            kernel.CloseHandle(handle)
    try:
        return int(Path(f"/proc/{int(pid)}/stat").read_text().rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def our_server(root):
    """The pid in server.pid if that process is alive and was created when the file says; a stale file is removed."""
    path = root / "server.pid"
    record = read_json(path) if path.exists() else None
    if record is None:
        path.unlink(missing_ok=True)
        return None
    if creation_time(record.get("pid", 0)) == record.get("created"):
        return int(record["pid"])
    path.unlink(missing_ok=True)
    return None


def terminate(pid):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass


def bindable(port):
    """True if 127.0.0.1:port can be bound right now. A bind test, never a connection."""
    with socket.socket() as sock:
        if os.name == "nt":
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def session_port(root, default):
    session = read_json(root / "session.json") or {}
    try:
        return int(str(session.get("base_url", "")).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return default


# reset ---------------------------------------------------------------------------------------------------------------

def kept_models(root):
    """The vision and reasoning model IDs the previous instance used, so a reset keeps the developer's choice."""
    found = {}
    for role, name in (("vision", "vision.json"), ("reasoning", "reasoning.json")):
        value = read_json(root / "control" / name) if (root / "control" / name).exists() else None
        found[role] = (value or {}).get("model", "")
    return found


def deletable(root):
    """reset may empty root: it is absent or empty, holds the sentinel, or is exactly tests/.tmp."""
    return not root.exists() or is_default(root) or (root / SENTINEL).is_file() or not any(root.iterdir())


def library_uri(root):
    return (root / "library" / "inventory.sqlite3").as_uri() + "?mode=ro"


def clear(root):
    """Everything in root but evidence/ (screenshots cited in docs/bugs.md stay valid)."""
    if root.exists():
        for item in root.iterdir():
            if item.name == "evidence":
                continue
            if item.is_dir() and not item.is_symlink():
                shutil.rmtree(item)
            else:
                item.unlink()
    root.mkdir(parents=True, exist_ok=True)
    (root / SENTINEL).write_text("Home Manager agent test instance. scripts/test_instance.py reset deletes this folder's contents.\n", encoding="utf-8")


def wait_idle(manager, queue=None):
    deadline = time.monotonic() + SETTLE_SECONDS
    while manager.busy(queue):
        if time.monotonic() > deadline:
            return False
        time.sleep(0.2)
    return True


def reset(args):
    check_root(args.root)
    root = args.root
    if not deletable(root):
        raise Refused(f"not a test instance folder: {root}", 2)
    if root.exists() and our_server(root):
        raise Refused("The test instance is running: stop the instance first.")
    if not bindable(args.port):
        raise Refused(f"Port {args.port} is in use by another program; stop it or pass --port.")
    lmstudio = args.lmstudio or DEFAULT_LMSTUDIO
    from home_manager.models.vision import VisionConfig
    try:
        VisionConfig(base_url=lmstudio)
    except ValueError:
        raise Refused(f"LM Studio must be http://127.0.0.1:PORT/v1, not {lmstudio}", 2) from None
    previous = kept_models(root)
    models = {"vision": args.vision_model if args.vision_model is not None else previous["vision"],
              "reasoning": args.reasoning_model if args.reasoning_model is not None else previous["reasoning"]}
    clear(root)
    for name in ("control", "uploads", "evidence"):
        (root / name).mkdir(exist_ok=True)
    (root / INCOMPLETE).write_text("seeding\n", encoding="utf-8")
    seed_date = date.today().isoformat()
    try:
        taxes_seeded = seed_instance(root, lmstudio, models)
    except Exception as exc:
        from seed_household import SeedStepFailed
        step = exc.step if isinstance(exc, SeedStepFailed) else "setup"
        print(f"seed step failed: {step}", file=sys.stderr)
        raise Refused(f"Reset failed in {step}; {INCOMPLETE} is kept, so start refuses. Fix the cause and reset again.") from exc
    from seed_household import manifest
    with sqlite3.connect(library_uri(root), uri=True) as db:
        seeded = manifest(db, taxes_seeded)
    write_uploads(root / "uploads")
    write_json(root / "seed.json", {"seed_date": seed_date, "manifest": seeded, "lmstudio": lmstudio, "models": models})
    (root / INCOMPLETE).unlink()
    print(f"Seeded {root} ({seed_date}).")
    if not (models["vision"] and models["reasoning"]):
        print("No vision or reasoning model ID yet: uploads won't be read until you pick models in Settings > Models "
              "(or reset with --vision-model / --reasoning-model).")


def seed_instance(root, lmstudio, models):
    """Seed the household with the fake models, then point every model setting at LM Studio. Returns taxes_seeded."""
    from home_manager.app.manager import Manager
    from home_manager.core.logs import configure
    from home_manager.documents.reasoning import ReasoningConfig
    from home_manager.documents.reviewer import ReviewerConfig
    from home_manager.library.scanner import ScanLimits
    from home_manager.models.vision import VisionConfig
    from model_server import start_model_server
    from seed_household import SeedStepFailed, seed

    sandbox.activate(root, protected=extra_protected())
    configure(root / "control")
    manager = Manager(root / "control", ScanLimits(stability_seconds=0))
    model, stop_model = start_model_server()
    try:
        profile = manager.create_profile("Test", str(root / "library"))
        manager.switch_profile(profile["id"])
        _, seeded = seed(manager, root, model, fail_step=os.environ.get("HM_TEST_SEED_FAIL") or None)
        if not wait_idle(manager, "inference"):
            raise SeedStepFailed("settle")
        manager.configure_vision(VisionConfig(base_url=lmstudio, model=models["vision"]))
        manager.configure_reasoning(ReasoningConfig(base_url=lmstudio, model=models["reasoning"]))
        manager.configure_reviewer(ReviewerConfig(provider="chat", base_url=lmstudio, model=models["reasoning"]) if models["reasoning"]
                                   else ReviewerConfig(provider="off"))
        if not wait_idle(manager):
            raise SeedStepFailed("settle")
        return seeded["taxes_seeded"]
    finally:
        stop_model()
        manager.close()
        sandbox.deactivate()


# The documents agents add: one per kind, from evals/synthetic.py, plus an offer letter (not a receipt).
UPLOADS = {"grocery-receipt.png": 2, "dining-receipt.png": 4, "fuel-receipt.png": 6, "parking-receipt.png": 15,
           "injection-receipt.png": 14, "refund-receipt.png": 40, "bank-statement.png": 22, "bank-statement.pdf": 26,
           "card-statement.png": 28, "pay-stub.png": 33, "bill.png": 42}
OFFER_LETTER = ["EXAMPLE WIDGETS LLC", "100 Sample Street, Springfield", "", "Dear Alex Example,",
                "We are pleased to offer you the position of", "Operations Analyst, starting on the first Monday",
                "of next month, at an annual salary of 72,000.00 USD.", "", "Please sign and return this letter.",
                "Sincerely,", "Jordan Sample, Hiring Manager"]


def write_uploads(folder):
    import random

    from evals import synthetic
    documents = synthetic.documents()
    rng = random.Random(synthetic.SEED)
    lines = ["Synthetic documents for agents to add to the test instance (evals/synthetic.py). None is real.", ""]
    for name, index in UPLOADS.items():
        document = documents[index]
        if name.endswith(".pdf"):
            synthetic.write_pdf(synthetic.pages(document), folder / name)
        else:
            synthetic.draw(document["lines"], folder / name, document["faded"], rng)
        tags = f" ({', '.join(document['tags'])})" if document["tags"] else ""
        lines.append(f"{name}: {document['document_type'].replace('_', ' ')}, {document['lines'][0]}{tags}")
    synthetic.draw(OFFER_LETTER, folder / "offer-letter.png")
    lines.append("offer-letter.png: not a receipt (a job offer letter)")
    (folder / "README.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


# start, serve, stop --------------------------------------------------------------------------------------------------

def start(args):
    check_root(args.root)
    root = args.root
    check_sentinel(root)
    if (root / INCOMPLETE).exists() or not (root / "seed.json").exists():
        raise Refused("seed incomplete, run reset")
    if our_server(root):
        raise Refused(f"The test instance is already running on port {session_port(root, args.port)}.")
    for name in ("session.json", "stop.request"):
        (root / name).unlink(missing_ok=True)
    if not bindable(args.port):
        raise Refused(f"Port {args.port} is in use; stop that program or pass --port. No other port is tried.")
    if not bindable(LIVE_PORT):
        print(f"Warning: {SHARED_WARNING}")
    command = [sys.executable, str(Path(__file__).resolve()), "serve", "--root", str(root), "--port", str(args.port)]
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with open(root / "server.log", "w", encoding="utf-8") as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, cwd=CHECKOUT,
                                   creationflags=flags, start_new_session=os.name != "nt")
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline and process.poll() is None:
        if (root / "server.pid").exists() and (root / "session.json").exists():
            session = read_json(root / "session.json")
            print(f"Test instance: {session['base_url']}\nOpen: {session['link']}\nSession file: {root / 'session.json'}")
            return
        time.sleep(0.1)
    tail = (root / "server.log").read_text(encoding="utf-8", errors="replace").splitlines()[-20:]
    pid = our_server(root)
    if pid:
        stop_server(root, pid)
    else:
        terminate(process.pid)
    for name in ("session.json", "server.pid", "stop.request"):
        (root / name).unlink(missing_ok=True)
    raise Refused("server did not start\n" + "\n".join(tail))


def serve(args):
    check_root(args.root)
    root = args.root
    check_sentinel(root)
    if os.environ.get("HM_TEST_SERVE_FAIL"):
        raise Refused("HM_TEST_SERVE_FAIL is set: not serving (test).")
    import uvicorn

    from home_manager.app.api import create_app
    from home_manager.core.logs import configure

    sandbox.activate(root, protected=extra_protected())
    configure(root / "control")
    seeded = read_json(root / "seed.json") or {}
    token = secrets.token_urlsafe(32)
    base = f"http://127.0.0.1:{args.port}"
    server = uvicorn.Server(uvicorn.Config(create_app(root / "control", token, args.port), host="127.0.0.1", port=args.port,
                                           access_log=False, log_level="warning"))

    def announce():
        while not server.started:
            if server.should_exit:
                return
            time.sleep(0.05)
        write_json(root / "server.pid", {"pid": os.getpid(), "created": creation_time(os.getpid())})
        write_json(root / "session.json", {"base_url": base, "link": f"{base}/#token={token}", "seed_date": seeded.get("seed_date"),
                                           "seed_counts": seeded.get("manifest", {}).get("counts"), "model_mode": "lmstudio",
                                           "lmstudio": seeded.get("lmstudio"), "models": seeded.get("models")})
        print(f"serving {base}", flush=True)

    def watch():
        # stop writes stop.request: a clean shutdown from any console (a CTRL_BREAK only reaches the caller's own).
        while not server.should_exit:
            if (root / "stop.request").exists():
                server.should_exit = True
            time.sleep(1)

    threading.Thread(target=announce, daemon=True).start()
    threading.Thread(target=watch, daemon=True).start()
    try:
        server.run()
    finally:
        record = read_json(root / "server.pid") or {}
        if record.get("pid") == os.getpid():
            for name in ("session.json", "server.pid"):
                (root / name).unlink(missing_ok=True)


def stop_server(root, pid):
    (root / "stop.request").write_text("stop\n", encoding="utf-8")
    created = creation_time(pid)
    deadline = time.monotonic() + STOP_SECONDS
    while time.monotonic() < deadline and creation_time(pid) == created:
        time.sleep(0.1)
    if creation_time(pid) == created:
        terminate(pid)


def stop(args):
    check_root(args.root)
    root = args.root
    check_sentinel(root)
    port = session_port(root, args.port)
    pid = our_server(root)
    if pid:
        stop_server(root, pid)
    for name in ("session.json", "server.pid", "stop.request"):
        (root / name).unlink(missing_ok=True)
    if not pid:
        print("The test instance is not running.")
        return
    deadline = time.monotonic() + STOP_SECONDS
    while not bindable(port) and time.monotonic() < deadline:
        time.sleep(0.1)
    print(f"Stopped. Port {port} is {'free' if bindable(port) else 'still in use'}.")


# verify --------------------------------------------------------------------------------------------------------------

def get(url, token=None, timeout=5):
    """(status, body). Keep-alive, and the client closes first once it has read the body: a server closing right behind
    a multi-segment reply sometimes loses a segment on Windows loopback (docs/development.md "Windows loopback resets"),
    and urllib's Connection: close asks uvicorn to do exactly that."""
    parts = urlsplit(url)
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
    try:
        connection.request("GET", (parts.path or "/") + (f"?{parts.query}" if parts.query else ""),
                           headers={"Authorization": f"Bearer {token}"} if token else {})
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def verify(args):
    check_root(args.root)
    root = args.root
    check_sentinel(root)
    results = []  # (level, name, detail); level is PASS, FAIL or WARN

    def report(level, name, detail):
        results.append(level)
        print(f"{level} {name}: {detail}")

    session = read_json(root / "session.json")
    seeded = read_json(root / "seed.json")
    base = (session or {}).get("base_url", "")
    token = str((session or {}).get("link", "")).partition("#token=")[2]
    loopback = base.startswith("http://127.0.0.1:") and base.rsplit(":", 1)[1].isdigit()
    if not session:
        report("FAIL", "server", "not running (no session.json); run start")
    elif not loopback:
        report("FAIL", "server", f"session.json names {base}, not http://127.0.0.1:PORT")
    else:
        try:
            report("PASS", "server", f"{base} answers ({get(base + '/')[0]})")
        except (OSError, http.client.HTTPException) as exc:
            report("FAIL", "server", f"{base} doesn't answer ({type(exc).__name__})")
            loopback = False

    if (root / INCOMPLETE).exists() or not seeded:
        report("FAIL", "seed manifest", "incomplete, run reset")
    else:
        from seed_household import SECTIONS
        expected = seeded["manifest"]["counts"]
        try:
            with sqlite3.connect(library_uri(root), uri=True) as db:
                found = {name: db.execute(SECTIONS[name]).fetchone()[0] for name in expected}
        except sqlite3.Error as exc:
            report("FAIL", "seed manifest", f"the library database can't be read ({exc})")
        else:
            drift = {name: (expected[name], found[name]) for name in expected if expected[name] != found[name]}
            if args.fresh and drift:
                report("FAIL", "seed manifest", "counts differ from the seed: " + ", ".join(f"{name} {a} -> {b}" for name, (a, b) in drift.items()))
            else:
                report("PASS", "seed manifest", f"seeded {seeded['seed_date']}" + (f"; changed since: {', '.join(drift)}" if drift else ""))

    guards = None
    if session and loopback:
        try:
            guards = json.loads(get(base + "/api/settings", token)[1]).get("test_instance")
        except (OSError, http.client.HTTPException, ValueError) as exc:
            report("FAIL", "guards", f"settings couldn't be read ({type(exc).__name__})")
            guards = False
    if guards is None and session and loopback:
        report("FAIL", "guards", "test mode is off")
    elif guards:
        for key, name in (("paths", "path guard"), ("egress", "network guard")):
            report("PASS" if guards.get(key) else "FAIL", name, "refuses" if guards.get(key) else "not refusing: test mode is off or broken")
    elif guards is None:
        report("FAIL", "guards", "no running instance to ask")

    lmstudio = args.lmstudio or (session or {}).get("lmstudio") or (seeded or {}).get("lmstudio") or DEFAULT_LMSTUDIO
    try:
        if get(lmstudio.rstrip("/") + "/models", timeout=3)[0] != 200:
            raise ValueError("not a model server")
        report("PASS", "LM Studio", f"{lmstudio} answers")
    except (OSError, http.client.HTTPException, ValueError):
        report("WARN", "LM Studio", f"{lmstudio} doesn't answer; uploads will show the model-unavailable state")
    models = (session or seeded or {}).get("models") or {}
    if not (models.get("vision") and models.get("reasoning")):
        report("WARN", "models", "no vision or reasoning model ID: uploads won't be read until you pick models in Settings > Models")
    if not bindable(LIVE_PORT):
        report("WARN", "port 8765", SHARED_WARNING)
    if "FAIL" in results:
        raise Refused("verify failed")


# finding -------------------------------------------------------------------------------------------------------------

_before_replace = None  # Tests only: called between reading the target and replacing it.
ENTRY_MARKER = re.compile(r"^<!-- finding:([0-9a-f]{16}) -->", re.M)


def finding_key(route, symptom):
    """The duplicate key: the route without spaces, case or a trailing slash, and the symptom lower-cased with its
    whitespace collapsed."""
    route = re.sub(r"\s+", "", route).lower().rstrip("/")
    return hashlib.sha256(f"{route}\n{' '.join(symptom.lower().split())}".encode()).hexdigest()[:16]


def field(value, newline):
    """A field's text, unable to end the section or forge a marker: <!-- is escaped, a line starting # gets a backslash,
    and later lines are indented under their bullet."""
    lines = [("\\" + line if line.lstrip().startswith("#") else line) for line in value.replace("<!--", "&lt;!--").splitlines() or [""]]
    return (newline + "  ").join(lines)


def one_line(value):
    return " ".join(value.replace("<!--", "&lt;!--").split())


def shown_path(path):
    """A path under the checkout as the repo writes it (tests/.tmp/evidence/x.png); anything else in full."""
    try:
        return path.relative_to(CHECKOUT).as_posix()
    except ValueError:
        return str(path)


def section_bounds(text):
    """(start, end) of the "## Agent findings" section, or None: from its header to the next "## " line or the end."""
    header = re.search(rf"^{re.escape(SECTION)}[ \t]*\r?$", text, re.M)
    if not header:
        return None
    following = re.compile(r"^## ", re.M).search(text, header.end())
    return header.start(), following.start() if following else len(text)


def add_finding(text, newline, key, today, seed_date, args, shot):
    """(new text, the existing entry's title for a "Seen again" or None for a new entry), or None when this key was
    already recorded on this date. Only the section's own bytes change."""
    bounds = section_bounds(text)
    if bounds is None:
        text += ("" if not text or text.endswith(newline) else newline) + SECTION
        bounds = (len(text) - len(SECTION), len(text))
    start, end = bounds
    markers = [(match.start() + start, match.group(1)) for match in ENTRY_MARKER.finditer(text[start:end])]
    evidence = shown_path(shot)
    for index, (at, found) in enumerate(markers):
        if found != key:
            continue
        stop = markers[index + 1][0] if index + 1 < len(markers) else end
        entry = text[at:stop]
        if re.search(rf"^- (Date|Seen again): {today} ", entry, re.M):
            return None
        body = entry.rstrip("\r\n")
        insert = at + len(body)
        title = re.search(r"^### (.*?)\r?$", entry, re.M)
        return (text[:insert] + f"{newline}- Seen again: {today} (seed {seed_date}) — evidence: {evidence}" + text[insert:],
                title.group(1) if title else key)
    lines = [f"<!-- finding:{key} -->", f"### {one_line(args.route)}: {one_line(args.symptom)}",
             f"- Date: {today} (seed {seed_date})", f"- Agent: {one_line(args.agent)}", f"- Page: {one_line(args.url)}",
             f"- Kind: {args.kind} · Severity: {args.severity}", f"- Steps: {field(args.steps, newline)}",
             f"- Expected: {field(args.expected, newline)}", f"- Actual: {field(args.actual, newline)}", f"- Evidence: {evidence}"]
    insert = start + len(text[start:end].rstrip("\r\n"))
    return text[:insert] + newline + newline + newline.join(lines) + (text[insert:] or newline), None


def finding(args):
    """Record one finding in the target's "## Agent findings" section (FR-10, FR-16). Every refusal leaves the target as
    it was and deletes the screenshot, but only one inside <root>/evidence; nothing else is ever deleted."""
    check_root(args.root)
    root = args.root
    check_sentinel(root)
    evidence = root / "evidence"
    shot = Path(os.path.abspath(args.screenshot or evidence))
    if not args.screenshot or shot == evidence or not sandbox.under(sandbox.norm(shot), sandbox.norm(evidence)):
        raise Refused(f"the screenshot must be a file inside {evidence}; nothing was recorded or deleted", 2)

    def refuse(message, code=2):
        if shot.is_symlink() or shot.is_file():
            shot.unlink()  # A link itself, never what it points at.
        return Refused(f"{message}. The finding wasn't recorded and the screenshot was deleted.", code)

    if not shot.is_file():
        raise Refused(f"no screenshot at {shot}", 2)
    missing = [f"--{name}" for name in FINDING_FIELDS if not (getattr(args, name) or "").strip()]
    if missing:
        raise refuse(f"missing {', '.join(missing)}")
    if args.kind not in KINDS or args.severity not in SEVERITIES:
        raise refuse(f"--kind must be one of {', '.join(KINDS)} and --severity one of {', '.join(SEVERITIES)}")
    session = read_json(root / "session.json")
    base = str((session or {}).get("base_url", ""))
    if not re.fullmatch(r"http://127\.0\.0\.1:\d+", base):
        raise refuse(f"no running test instance: {root / 'session.json'} is missing or doesn't name http://127.0.0.1:PORT")
    target = Path(os.path.abspath(args.target))
    if not (sandbox.norm(target) == sandbox.norm(DEFAULT_TARGET) or (target != root and sandbox.under(sandbox.norm(target), sandbox.norm(root)))):
        raise refuse(f"findings go only to {DEFAULT_TARGET} or a file inside {root}, not {target}")
    page = urlsplit(args.url)
    if f"{page.scheme}://{page.netloc}".lower() != base:
        raise refuse(f"not the test instance: the page {args.url} isn't on {base}")
    try:
        status, body = get(base + "/api/settings", str(session.get("link", "")).partition("#token=")[2])
        marked = status == 200 and bool(json.loads(body).get("test_instance"))
    except (OSError, http.client.HTTPException, ValueError):
        marked = False
    if not marked:
        raise refuse(f"not the test instance: {base} doesn't report test mode, so its pages show no \"Test data\" marker")

    today = os.environ.get("HM_TEST_FINDING_DATE") or date.today().isoformat()
    lock = target.with_name(target.name + ".lock")
    deadline = time.monotonic() + LOCK_SECONDS
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise refuse(f"{lock} is still held after {LOCK_SECONDS} s (another finding, or a crashed one: delete it if none is running)", 3) from None
            time.sleep(0.1)
    try:
        before = target.read_bytes() if target.exists() else b""
        text = before.decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        updated = add_finding(text, newline, finding_key(args.route, args.symptom), today, session.get("seed_date", "unknown"), args, shot)
        if updated is None:
            print(f"already recorded today; the screenshot is kept: {shot}")
            return
        if _before_replace:
            _before_replace(target)
        if (target.read_bytes() if target.exists() else b"") != before:
            raise refuse(f"{target} changed while recording; run again", 3)
        updated, seen = updated
        write_atomic(target, updated.encode("utf-8"))
    finally:
        lock.unlink(missing_ok=True)
    if seen:
        print(f"Seen again ({today}) in {target}: {seen}; no new entry.")
    else:
        print(f"Recorded a new entry in {target}: {one_line(args.route)}: {one_line(args.symptom)}")


def main(argv=None):
    args = parse(argv)
    try:
        {"reset": reset, "start": start, "serve": serve, "stop": stop, "verify": verify, "finding": finding}[args.command](args)
    except Refused as exc:
        print(exc, file=sys.stderr)
        return exc.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
