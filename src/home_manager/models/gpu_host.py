"""Shared GPU relay: family members' and testers' model calls run on this computer's LM Studio.

A small process of its own (`home-manager gpu-host`), so it can run as a startup task.
It listens on this computer's Tailscale address and on loopback, and forwards only
model listings and chat completions to LM Studio at 127.0.0.1. Members' documents and
databases never leave their computers: requests carry rendered page images and text.

- Each member has a bearer token; only its SHA-256 is stored, so a token can be revoked.
  Tailscale already encrypts the traffic and identifies the device. Loopback needs no token.
- Members are family or testers (friends outside the family). Testers' tokens expire, and
  their requests wait behind the family's (docs/family.md "Shared GPU").
- Members ask for a role (home-manager/vision, /reasoning, /reviewer). The roles map to
  the models set in this computer's own Home Manager settings, so models change centrally.
- One queue for everyone, including this computer's own app: one request runs at a time,
  and the others wait with SSE comment keepalives. Waiting requests for the model already
  loaded go first, but never skip the oldest more than MAX_SKIPS times.
- Request and response bodies are never logged or stored: only member, role, tokens, time.
"""

import argparse
from datetime import date, timedelta
import hashlib
import hmac
import http.client
from http.server import BaseHTTPRequestHandler
import json
import logging
from pathlib import Path
import re
import secrets
import threading
import time
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

from pydantic import Field, field_validator

from ..core.jobs import Work
from ..core.paths import safe_path, write_atomic
from ..documents.receipt_schema import StrictModel
from .http_server import GracefulHTTPServer, check_bind, tailnet_address
from .model_client import ModelHTTPError, get_json
from .model_stream import IDLE_SECONDS
from .residency import MANAGED_MARKER, ensure_loaded
from .vision import ROLE_ALIASES, VisionConfig, endpoint_url

log = logging.getLogger("home_manager.gpu_host")

HOST_FILE = "gpu_host.json"
PORT = 8766
MAX_BODY = 32 * 1024**2  # A 16 MiB page image, base64-encoded, plus its prompt.
MAX_SKIPS = 3
KEEPALIVE_SECONDS = 15
LOCAL_MEMBER = "This computer"
MEMBER_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,60}$")
TESTER_DAYS = 30


class Member(StrictModel):
    token_sha256: str
    kind: Literal["family", "tester"] = "family"
    expires: date | None = None  # Testers' tokens stop working after this day.

    def expired(self, today=None):
        return self.expires is not None and (today or date.today()) > self.expires


class HostConfig(StrictModel):
    port: int = Field(default=PORT, ge=1024, le=65535)
    upstream: str = "http://127.0.0.1:1234/v1"  # LM Studio on this computer.
    members: dict[str, Member] = Field(default_factory=dict)  # Only the SHA-256 of each token is kept.

    @field_validator("upstream")
    @classmethod
    def loopback(cls, value):
        return endpoint_url(value)

    @field_validator("members", mode="before")
    @classmethod
    def plain_hashes(cls, value):
        # Files written before kinds existed hold name -> hash: those are family members with no expiry.
        if isinstance(value, dict):
            return {name: {"token_sha256": saved} if isinstance(saved, str) else saved for name, saved in value.items()}
        return value


def _digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def load_host(control: Path) -> HostConfig:
    path = safe_path(control / HOST_FILE)
    return HostConfig.model_validate_json(path.read_bytes()) if path.exists() else HostConfig()


def save_host(control: Path, config: HostConfig):
    control.mkdir(parents=True, exist_ok=True)
    write_atomic(safe_path(control / HOST_FILE), config.model_dump_json(indent=2))


def add_member(control: Path, name: str, kind="family", expires: date | None = None) -> str:
    """Create (or replace) a member's token. Returns it once; only its hash is kept.
    A tester is someone outside the family trying the app: their token expires (TESTER_DAYS by default)."""
    name = name.strip()
    if not MEMBER_NAME.match(name):
        raise ValueError("Use a name of 1–60 characters.")
    if kind == "tester" and expires is None:
        expires = date.today() + timedelta(days=TESTER_DAYS)
    if expires is not None and expires < date.today():
        raise ValueError("The expiry date has already passed.")
    token = secrets.token_urlsafe(32)
    config = load_host(control)
    config.members[name] = Member(token_sha256=_digest(token), kind=kind, expires=expires)
    save_host(control, config)
    return token


def member_line(name, member: Member):
    if member.expires is None:
        return f"{name} ({member.kind})"
    return f"{name} ({member.kind}, {'expired' if member.expired() else 'until'} {member.expires.isoformat()})"


def remove_member(control: Path, name: str) -> bool:
    config = load_host(control)
    removed = config.members.pop(name.strip(), None) is not None
    save_host(control, config)
    return removed


def role_models(control: Path) -> dict:
    """Role alias -> model ID, from this computer's own Home Manager model settings."""
    def saved(name):
        try:
            data = json.loads(safe_path(control / name).read_bytes())
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def model(data):
        value = data.get("model")
        return value.strip() if isinstance(value, str) else ""

    vision, reasoning, reviewer, decision = saved("vision.json"), saved("reasoning.json"), saved("reviewer.json"), saved("decision.json")
    review = model(reviewer) if reviewer.get("provider") == "chat" and model(reviewer) else model(reasoning)
    # Only an LM Studio decision model is shared; a /v1/systemone server is not behind this relay.
    decide = model(decision) if decision.get("provider") == "lmstudio" else ""
    return {ROLE_ALIASES["vision"]: model(vision), ROLE_ALIASES["reasoning_config"]: model(reasoning),
            ROLE_ALIASES["reviewer_config"]: review, ROLE_ALIASES["decision_config"]: decide}


def role_label(alias):
    return alias.rsplit("/", 1)[-1] if alias else "direct"


class Ticket:
    def __init__(self, model, member, role, tester=False):
        self.model, self.member, self.role, self.tester = model, member, role, tester
        self.queued, self.started, self.skipped = time.monotonic(), None, 0


class Scheduler:
    """Single-flight FIFO across every client, grouped by model to minimise swaps.
    Testers' requests wait behind this computer's and the family's, but are never skipped more than max_skips times."""

    def __init__(self, max_skips=MAX_SKIPS):
        self.max_skips = max_skips
        self.condition = threading.Condition()
        self.waiting, self.running, self.loaded = [], None, None

    def _next(self):
        oldest = self.waiting[0]
        if oldest.skipped >= self.max_skips:
            return oldest
        ahead = [ticket for ticket in self.waiting if not ticket.tester] or self.waiting
        return next((ticket for ticket in ahead if ticket.model == self.loaded), ahead[0])

    def acquire(self, model, member, role, on_wait=None, poll=KEEPALIVE_SECONDS, tester=False):
        """Wait for this request's turn. on_wait(position) runs between waits; if it raises
        (the client went away), the request leaves the queue and the error propagates."""
        ticket = Ticket(model, member, role, tester)
        with self.condition:
            self.waiting.append(ticket)
        try:
            while True:
                with self.condition:
                    if self.running is None and self._next() is ticket:
                        index = self.waiting.index(ticket)
                        for ahead in self.waiting[:index]:
                            ahead.skipped += 1
                        self.waiting.remove(ticket)
                        self.running, self.loaded, ticket.started = ticket, model, time.monotonic()
                        return ticket
                    self.condition.wait(timeout=poll)
                    position = self.waiting.index(ticket) + 1
                    ready = self.running is None and self._next() is ticket
                if on_wait and not ready:
                    on_wait(position)
        except BaseException:
            with self.condition:
                if ticket in self.waiting:
                    self.waiting.remove(ticket)
                self.condition.notify_all()
            raise

    def release(self, ticket):
        with self.condition:
            if self.running is ticket:
                self.running = None
            self.condition.notify_all()

    def status(self):
        current = time.monotonic()
        with self.condition:
            running = self.running and {"member": self.running.member, "role": self.running.role,
                                        "seconds": int(current - self.running.started)}
            queued = [{"member": item.member, "role": item.role, "seconds": int(current - item.queued)} for item in self.waiting]
        return {"running": running or None, "queued": queued}


def _clock(seconds):
    return f"{int(seconds) // 60:02d}:{int(seconds) % 60:02d}"


class GpuHost:
    def __init__(self, control: Path, keepalive_seconds=KEEPALIVE_SECONDS):
        self.control = safe_path(control)
        self.config = load_host(self.control)
        self.keepalive_seconds = keepalive_seconds
        self.scheduler = Scheduler()

    def upstream(self, model=""):
        return VisionConfig(base_url=self.config.upstream, model=model)

    def authenticate(self, header, loopback):
        """(name, Member) for a valid token, (name, None) for this computer, or None.
        Members are re-read so a removed or expired token stops working at once."""
        if loopback:
            return LOCAL_MEMBER, None
        if not header or not header.startswith("Bearer "):
            return None
        digest = _digest(header[7:].strip())
        try:
            members = load_host(self.control).members
        except (OSError, ValueError):
            return None
        found = next(((name, saved) for name, saved in members.items() if hmac.compare_digest(saved.token_sha256, digest)), None)
        return None if found is None or found[1].expired() else found

    def resolve(self, model, loopback):
        """(model ID to run, role alias) for a requested model, or an error message."""
        if not isinstance(model, str) or not model:
            return "Name a model role."
        roles = role_models(self.control)
        if model in roles:
            return (roles[model], model) if roles[model] else "The GPU computer has no model set for this role yet."
        alias = next((name for name, target in roles.items() if target == model), None)
        if alias or loopback:  # This computer's own app may use any model LM Studio serves.
            return model, alias
        return "This model is not shared by the GPU computer."

    def list_models(self, loopback):
        try:
            listing = get_json(self.upstream(), "/v1/models")
        except ModelHTTPError as exc:
            return exc.status, {"error": "LM Studio on the GPU computer rejected the model listing."}
        except (OSError, ValueError, http.client.HTTPException):
            return 502, {"error": "LM Studio is not running on the GPU computer."}
        entries = [item for item in listing.get("data", []) if isinstance(item, dict)] if isinstance(listing, dict) else []
        by_id = {item.get("id"): item for item in entries}
        shared = [{**by_id[target], "id": alias} for alias, target in role_models(self.control).items() if target in by_id]
        return 200, {"object": "list", "data": (entries if loopback else []) + shared}

    def model_details(self, model, loopback):
        resolved = self.resolve(model, loopback)
        if isinstance(resolved, str):
            return 404, {"error": resolved}
        try:
            details = get_json(self.upstream(), "/api/v0/models/" + quote(resolved[0], safe=""))
        except ModelHTTPError as exc:
            return exc.status, {"error": "LM Studio on the GPU computer has no details for this model."}
        except (OSError, ValueError, http.client.HTTPException):
            return 502, {"error": "LM Studio is not running on the GPU computer."}
        return 200, {**details, "id": model} if isinstance(details, dict) else details

    def relay_chat(self, handler, member, body, path="/chat/completions", tester=False):
        """Relay one request. /chat/completions streams; /responses (decision models only) is one JSON reply."""
        try:
            payload = json.loads(body)
        except ValueError:
            return handler.reply(400, {"error": "The request is not valid JSON."})
        if not isinstance(payload, dict):
            return handler.reply(400, {"error": "The request is not valid JSON."})
        resolved = self.resolve(payload.get("model"), handler.loopback)
        if isinstance(resolved, str):
            return handler.reply(403, {"error": resolved})
        target, alias = resolved
        streaming = path == "/chat/completions"
        if not streaming and alias != ROLE_ALIASES["decision_config"] and not handler.loopback:
            return handler.reply(403, {"error": "Only the decision model role is shared on this endpoint."})
        payload["model"] = target
        body = json.dumps(payload).encode()
        del payload
        stream = {"started": False}

        def keepalive(position):
            handler.start_stream(stream)
            handler.wfile.write(f": queued {position}\n\n".encode())

        t0, usage = time.monotonic(), {}
        try:
            # A JSON reply can't carry keep-alive comments, so a queued decision request waits silently.
            ticket = self.scheduler.acquire(target, member, role_label(alias), keepalive if streaming else None,
                                            self.keepalive_seconds, tester)
        except OSError:
            return  # The member disconnected while waiting.
        try:
            self.forward(handler, target, body, stream, usage, path)
        except OSError:
            pass  # The member disconnected; closing the upstream connection stops generation.
        finally:
            self.scheduler.release(ticket)
            log.info("%s — %s — %s — %s prompt / %s completion tokens", member, role_label(alias), _clock(time.monotonic() - t0),
                     usage.get("prompt_tokens", "?"), usage.get("completion_tokens", "?"))

    def forward(self, handler, target, body, stream, usage, path="/chat/completions"):
        try:
            ensure_loaded(self.upstream(target), Work.detached())
        except (ModelHTTPError, ValueError) as exc:
            return handler.fail(stream, 502, str(exc))
        url = urlsplit(self.config.upstream)
        connection = http.client.HTTPConnection(url.hostname, url.port, timeout=IDLE_SECONDS)
        accept = "text/event-stream" if path == "/chat/completions" else "application/json"
        try:
            try:
                connection.request("POST", url.path + path, body, {"Content-Type": "application/json", "Accept": accept})
                response = connection.getresponse()
            except (OSError, http.client.HTTPException):
                return handler.fail(stream, 502, "LM Studio is not running on the GPU computer.")
            if response.status != 200:
                detail = response.read(65536)
                if stream["started"]:
                    return handler.fail(stream, response.status, "LM Studio on the GPU computer rejected the request.")
                # The member's own request echoed back: passed through for diagnosis, never logged.
                return handler.reply_raw(response.status, detail, response.getheader("Content-Type") or "application/json")
            handler.start_stream(stream, response.getheader("Content-Type") or "text/event-stream")
            event = []
            while True:
                try:
                    line = response.readline(65537)
                except (OSError, http.client.HTTPException):
                    line = b""
                if line.startswith(b"data:") and b'"usage"' in line:
                    try:
                        found = json.loads(line[5:]).get("usage")
                        if isinstance(found, dict):
                            usage.update(found)
                    except (ValueError, AttributeError):
                        pass
                if line:
                    event.append(line)
                if event and (not line or line in (b"\n", b"\r\n")):
                    handler.wfile.write(b"".join(event))  # One write per event.
                    event.clear()
                if not line:
                    return
        finally:
            connection.close()

    def status(self):
        return self.scheduler.status()


class Handler(BaseHTTPRequestHandler):
    server_version = "HomeManagerGPU/1"
    sys_version = ""

    def log_message(self, *args):
        pass  # Request lines are not logged; GpuHost logs its own summary.

    @property
    def host(self):
        return self.server.gpu_host

    @property
    def loopback(self):
        return self.server.loopback

    def reply_raw(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def reply(self, status, value):
        self.reply_raw(status, json.dumps(value).encode(), "application/json")

    def start_stream(self, stream, content_type="text/event-stream"):
        if not stream["started"]:
            stream["started"] = True
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()

    def fail(self, stream, status, message):
        if stream["started"]:
            self.wfile.write(b"data: " + json.dumps({"error": {"message": message}}).encode() + b"\n\n")
        else:
            self.reply(status, {"error": {"message": message}})

    def member(self):
        """(name, Member or None for this computer), or None after replying 401."""
        found = self.host.authenticate(self.headers.get("Authorization"), self.loopback)
        if found is None:
            self.reply(401, {"error": "A valid shared GPU token is required. Tokens can be revoked or expire."})
        return found

    def do_GET(self):
        if self.member() is None:
            return
        path = urlsplit(self.path).path
        if path == "/v1/models":
            self.reply(*self.host.list_models(self.loopback))
        elif path == "/api/v1/models":
            self.reply(200, {"models": [], "managed_by": MANAGED_MARKER})  # Clients leave residency to this host.
        elif path.startswith("/api/v0/models/"):
            self.reply(*self.host.model_details(unquote(path[len("/api/v0/models/"):]), self.loopback))
        elif path == "/status" and self.loopback:
            self.reply(200, self.host.status())
        else:
            self.reply(404, {"error": "Not available on the shared GPU computer."})

    def do_POST(self):
        # Read the body before any reply: answering with it unread resets the connection on Windows,
        # and the client would see a connection failure instead of the reason.
        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            return self.reply(411, {"error": "Content-Length is required."})
        if int(length) > MAX_BODY:
            self.close_connection = True
            return self.reply(413, {"error": "The request exceeds the 32 MiB limit."})
        body = self.rfile.read(int(length))
        found = self.member()
        if found is None:
            return
        path = urlsplit(self.path).path
        if path not in ("/v1/chat/completions", "/v1/responses"):
            return self.reply(404, {"error": "Not available on the shared GPU computer."})
        name, member = found
        self.host.relay_chat(self, name, body, path.removeprefix("/v1"), tester=member is not None and member.kind == "tester")


class RelayServer(GracefulHTTPServer):
    """Waits for each client to close before closing (models/http_server.py): replies are long event streams."""

    gpu_host: GpuHost
    loopback: bool


def make_server(host: GpuHost, address: str, port: int, loopback: bool) -> RelayServer:
    """Bind to loopback, or to a Tailscale address (100.64.0.0/10) and nothing else."""
    check_bind(address, loopback, "The GPU host")
    server = RelayServer((address, port), Handler)
    server.gpu_host, server.loopback = host, loopback
    return server


def serve(control: Path, bind=None):
    host = GpuHost(control)
    address = bind or tailnet_address()
    if not address:
        raise SystemExit("No Tailscale address found. Start Tailscale, or pass --bind with this computer's 100.x.y.z address.")
    port = host.config.port
    try:
        remote = make_server(host, address, port, loopback=False)
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    local = make_server(host, "127.0.0.1", port, loopback=True)
    threading.Thread(target=local.serve_forever, name="gpu-host-loopback", daemon=True).start()
    roles = role_models(host.control)
    print(f"Shared GPU host on http://{address}:{port}/v1 (and http://127.0.0.1:{port}/v1 for this computer).", flush=True)
    print(f"Forwarding to LM Studio at {host.config.upstream}. Members: {', '.join(host.config.members) or 'none yet'}.", flush=True)
    for alias, model in roles.items():
        print(f"  {role_label(alias)}: {model or 'not set'}", flush=True)
    try:
        remote.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        remote.server_close()
        local.shutdown()
        local.server_close()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="home-manager gpu-host",
                                     description="Share this computer's LM Studio with family members and testers over Tailscale.")
    parser.add_argument("--control-dir", type=Path, help="Settings location; default is %%LOCALAPPDATA%%/HomeManager on Windows.")
    commands = parser.add_subparsers(dest="command")
    run = commands.add_parser("serve", help="Run the relay (the default).")
    run.add_argument("--bind", help="This computer's Tailscale IPv4 address; found automatically when omitted.")
    add = commands.add_parser("add-member", help="Create a member's token (printed once).")
    add.add_argument("name")
    add.add_argument("--tester", action="store_true",
                     help=f"Someone outside the family: their token expires ({TESTER_DAYS} days unless --expires) "
                          "and their requests wait behind the family's.")
    add.add_argument("--expires", type=date.fromisoformat, help="Last day the token works (YYYY-MM-DD).")
    remove = commands.add_parser("remove-member", help="Revoke a member's token.")
    remove.add_argument("name")
    commands.add_parser("members", help="List members.")
    args = parser.parse_args(argv)
    from ..app.manager import default_control_dir
    control = args.control_dir or default_control_dir()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if args.command == "add-member":
        try:
            token = add_member(control, args.name, "tester" if args.tester else "family", args.expires)
        except ValueError as exc:
            parser.error(str(exc))
        member = load_host(control).members[args.name.strip()]
        until = f", works until {member.expires.isoformat()}" if member.expires else ""
        print(f"Token for {args.name.strip()} ({member.kind}{until}; shown once, give it to them privately):\n{token}")
    elif args.command == "remove-member":
        print("Removed." if remove_member(control, args.name) else "No member has that name.")
    elif args.command == "members":
        print("\n".join(member_line(name, member) for name, member in load_host(control).members.items()) or "No members yet.")
    else:
        serve(control, getattr(args, "bind", None))
