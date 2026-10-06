"""The family hub: the family computer receives members' copies and hands out their deliveries over Tailscale.

It runs inside the app on the computer holding a family folder, whichever profile is open, and listens only on this
computer's Tailscale address (models/http_server.py check_bind), on its own port. It has no route into the main app,
which stays on 127.0.0.1. Security: docs/family.md "Families" (approved 2026-10-05).

- Each member on another computer has a bearer token, made with their invite. Only its SHA-256 is kept, in family.json,
  and a token works only for its own family and member (the ids in the path).
- Everything that crosses is still sealed with the family key (library/share.py); a stolen token alone can't read or
  forge a copy or a delivery. A copy's sealed header carries a seq, and an older or repeated one is refused.
- Request bodies are streamed to disk in 1 MiB chunks and never logged: only member, route, status and time.

Routes (all need the member's token):
  GET    /v1/ping                                              the family id and the server time
  PUT    /v1/families/{fid}/members/{mid}/copy                 a sealed .hmfamily copy
  GET    /v1/families/{fid}/members/{mid}/deliveries           the keys waiting for the member
  GET    /v1/families/{fid}/members/{mid}/deliveries/{key}     one sealed .hmdelivery
  DELETE /v1/families/{fid}/members/{mid}/deliveries/{key}     acknowledge it (the hub deletes it)
  POST   /v1/families/{fid}/members/{mid}/blobs/missing        which of these document hashes the family lacks
  PUT    /v1/families/{fid}/members/{mid}/blobs/{hash}         one sealed document (.hmblob), checked against its hash
"""

from http.server import BaseHTTPRequestHandler
import json
import logging
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit
import uuid

from ..core.logs import log_failure
from ..core.paths import PathError, path_key, safe_path
from ..library.share import ShareError
from ..library.storage import now
from ..models.http_server import GracefulHTTPServer, check_bind, tailnet_address
from .family_sync import HASH, MAX_BLOB, MAX_SNAPSHOT, CopyRefused, FamilyFolder

log = logging.getLogger("home_manager.family_hub")

PORT = 8767
MAX_UPLOAD = MAX_SNAPSHOT + 64 * 1024 ** 2  # A 4 GiB copy plus its sealing overhead.
CHUNK = 1024 * 1024
MAX_LIST = 16 * 1024 ** 2  # The hashes a member asks about: about 250,000 documents.
MEMBER_PATH = re.compile(r"^/v1/families/(?P<fid>[0-9a-f]{32})/members/(?P<mid>[0-9a-f]{12})/"
                         r"(?P<route>copy|deliveries(?:/(?P<key>[0-9a-f]{32}))?|blobs/(?:missing|(?P<hash>[0-9a-f]{64})))$")
TOKEN_REFUSED = "A valid family hub token is required. Ask the family computer for a new invite."


class Hub:
    """The family folders this computer holds and the server for them. The app opens each family folder once, here, and
    shares it with the family view (a folder's lock admits one opening)."""

    def __init__(self, port=PORT, loopback=False):
        self.port, self.loopback = port, loopback  # loopback: tests only; a real hub never listens on 127.0.0.1.
        self.lock = threading.RLock()
        self.families: dict[str, FamilyFolder] = {}  # path_key(root) -> open folder
        self.errors: dict[str, str] = {}  # path_key(root) -> why that folder could not be opened
        self.server = None
        self.address = None
        self.reason = "No family folder on this computer."

    # Folders --------------------------------------------------------------------------

    def folder(self, root):
        with self.lock:
            return self.families.get(path_key(root))

    def hold(self, roots, active=None):
        """Hold exactly these family folders open. active is the family view's open folder: adopted rather than opened twice,
        and when let go, left open for the family view."""
        wanted = {path_key(root): Path(root) for root in roots}
        with self.lock:
            for key in list(self.families):
                if key not in wanted:
                    family = self.families.pop(key)
                    if family is not active:
                        family.close()
            self.errors = {key: value for key, value in self.errors.items() if key in wanted}
            for key, root in wanted.items():
                if key in self.families:
                    continue
                if active is not None and path_key(active.root) == key:
                    self.families[key] = active
                    continue
                try:
                    self.families[key] = FamilyFolder(root)
                    self.errors.pop(key, None)
                except (PathError, ValueError, OSError) as exc:
                    self.errors[key] = str(exc) if isinstance(exc, (PathError, ValueError)) else "The family folder could not be opened."

    def by_id(self, family_id):
        with self.lock:
            return next((family for family in self.families.values() if family.data["family_id"] == family_id), None)

    # Server ---------------------------------------------------------------------------

    def start(self):
        """Listen if there is a family to serve and a Tailscale address to listen on; otherwise record why not. Safe to
        call again: the app retries every family check, so starting Tailscale later is enough."""
        with self.lock:
            if self.server is not None:
                return self.status()
            if not self.families:
                self.reason = "No family folder on this computer." if not self.errors else next(iter(self.errors.values()))
                return self.status()
            address = "127.0.0.1" if self.loopback else tailnet_address()
            if not address:
                self.reason = "Tailscale isn't running on this computer, so members' computers can't reach it."
                return self.status()
            try:
                check_bind(address, self.loopback, "The family hub")
                server = HubServer((address, self.port), Handler)
            except ValueError as exc:
                self.reason = str(exc)
                return self.status()
            except OSError as exc:
                log_failure(log, "family hub bind", exc)
                self.reason = f"Port {self.port} is in use by another program."
                return self.status()
            server.hub = self
            self.server, self.address, self.reason = server, f"{address}:{server.server_port}", None
            threading.Thread(target=server.serve_forever, name="family-hub", daemon=True).start()
            log.info("family hub listening on %s", self.address)
            return self.status()

    def stop(self):
        with self.lock:
            server, self.server, self.address = self.server, None, None
            self.reason = "The family hub stopped."
            for family in self.families.values():
                family.close()
            self.families.clear()
        if server is not None:
            server.shutdown()
            server.server_close()

    def status(self):
        with self.lock:
            return {"listening": self.server is not None, "address": self.address, "reason": self.reason}

    # Requests -------------------------------------------------------------------------

    def authenticate(self, header, family_id, member_id):
        """(family, member) for a token that belongs to exactly this family and member, else None."""
        if not header or not header.startswith("Bearer "):
            return None
        family = self.by_id(family_id)
        if family is None:
            return None
        member = family.token_member(member_id, header[7:].strip())
        return (family, member) if member is not None else None

    def find(self, header):
        """(family, member) for a token from any family held here (the ping), else None."""
        if not header or not header.startswith("Bearer "):
            return None
        with self.lock:
            families = list(self.families.values())
        for family in families:
            for member in list(family.data["members"]):
                found = family.token_member(member["member_id"], header[7:].strip())
                if found is not None:
                    return family, found
        return None


class HubServer(GracefulHTTPServer):
    """Waits for each client to close before closing (models/http_server.py)."""

    hub: Hub


class Handler(BaseHTTPRequestHandler):
    server_version = "HomeManagerFamily/1"
    sys_version = ""
    server: HubServer

    def log_message(self, *args):
        pass  # Request lines are not logged; each request logs its own one-line summary.

    @property
    def hub(self) -> Hub:
        return self.server.hub

    def reply(self, status, value=None):
        body = json.dumps(value if value is not None else {}).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return status

    def refuse(self, status, message):
        # Replies before reading the body: GracefulHTTPServer.shutdown_request drains it before closing, so the reply isn't lost.
        return self.reply(status, {"error": message})

    def route(self):
        """(family, member, route, key, hash) after checking the path and token, or None after replying. route is "copy",
        "deliveries" or "blobs"; key is a delivery's, hash a document's."""
        match = MEMBER_PATH.match(urlsplit(self.path).path)
        if match is None:
            self.refuse(404, "Not available on the family computer.")
            return None
        found = self.hub.authenticate(self.headers.get("Authorization"), match["fid"], match["mid"])
        if found is None:
            self.refuse(401, TOKEN_REFUSED)
            return None
        family, member = found
        return family, member, match["route"].split("/")[0], match["key"], match["hash"]

    def handle_one_request(self):
        self.started = time.monotonic()
        super().handle_one_request()

    def done(self, member, route, status):
        log.info("%s — %s %s — %s — %.1fs", member.get("name") if member else "?", self.command, route, status, time.monotonic() - self.started)

    def do_GET(self):
        if urlsplit(self.path).path == "/v1/ping":
            found = self.hub.find(self.headers.get("Authorization"))
            if found is None:
                return self.refuse(401, TOKEN_REFUSED)
            family, member = found
            return self.done(member, "ping", self.reply(200, {"family_id": family.data["family_id"], "member_id": member["member_id"],
                                                              "time": now()}))
        found = self.route()
        if found is None:
            return
        family, member, route, key, _ = found
        if route != "deliveries":
            return self.done(member, route, self.refuse(405, "Only deliveries can be fetched."))
        if key is None:
            return self.done(member, route, self.reply(200, {"deliveries": family.deliveries(member["member_id"])}))
        path = family.delivery_path(member["member_id"], key)
        try:
            source = open(path, "rb")
        except FileNotFoundError:
            return self.done(member, route, self.reply(404, {"error": "No such delivery."}))
        with source:
            size = path.stat().st_size
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(size))
            self.end_headers()
            while chunk := source.read(CHUNK):
                self.wfile.write(chunk)
        self.done(member, route, 200)

    def do_DELETE(self):
        found = self.route()
        if found is None:
            return
        family, member, route, key, _ = found
        if route != "deliveries" or key is None:
            return self.done(member, route, self.refuse(405, "Only a delivery can be acknowledged."))
        family.delivery_path(member["member_id"], key).unlink(missing_ok=True)  # Acknowledging twice is fine.
        self.done(member, route, self.reply(200, {"key": key}))

    def do_POST(self):
        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            return self.refuse(411, "Content-Length is required.")
        found = self.route()
        if found is None:
            return
        family, member, route, _, digest = found
        if route != "blobs" or digest is not None:
            return self.done(member, route, self.refuse(405, "Only the missing-documents question is asked with POST."))
        if int(length) > MAX_LIST:
            return self.done(member, route, self.refuse(413, "Too many documents in one question."))
        try:
            asked = json.loads(self.rfile.read(int(length))).get("hashes")
        except (ValueError, AttributeError):
            asked = None
        if not isinstance(asked, list) or not all(isinstance(item, str) and HASH.match(item) for item in asked):
            return self.done(member, route, self.reply(400, {"error": "Send {\"hashes\": [...]} with SHA-256 hashes."}))
        self.done(member, route, self.reply(200, {"missing": family.missing_blobs(asked)}))

    def do_PUT(self):
        length = self.headers.get("Content-Length", "")
        if not length.isdigit():
            return self.refuse(411, "Content-Length is required.")
        found = self.route()
        if found is None:
            return
        family, member, route, _, digest = found
        if route == "blobs" and digest is None:
            return self.done(member, route, self.refuse(405, "Use POST to ask which documents are missing."))
        if route not in ("copy", "blobs"):
            return self.done(member, route, self.refuse(405, "Only a copy or a document can be sent."))
        noun, limit = ("copy", MAX_UPLOAD) if route == "copy" else ("document", MAX_BLOB + 64 * 1024 ** 2)
        if int(length) > limit:
            return self.done(member, route, self.refuse(413, f"{member['name']}'s {noun} is larger than Home Manager accepts."))
        incoming = safe_path(family.root / "incoming")
        incoming.mkdir(exist_ok=True)
        staged = safe_path(incoming / f"{member['member_id']}-{uuid.uuid4().hex[:8]}.upload")
        try:
            remaining = int(length)
            with open(staged, "wb") as target:
                while remaining:
                    chunk = self.rfile.read(min(CHUNK, remaining))
                    if not chunk:
                        self.close_connection = True
                        return self.done(member, route, "disconnected")
                    target.write(chunk)
                    remaining -= len(chunk)
            try:
                state = family.import_copy(member["member_id"], staged) if route == "copy" else family.store_blob(member["member_id"], digest, staged)
            except CopyRefused as exc:
                return self.done(member, route, self.reply(exc.status, {"error": str(exc), **exc.extra}))
            except ShareError:
                return self.done(member, route, self.reply(422, {"error": f"The {noun} is damaged or wasn't sealed with this family's key."}))
            except (ValueError, OSError) as exc:
                log_failure(log, f"family hub {noun}", exc, member=member["member_id"])
                return self.done(member, route, self.reply(500, {"error": f"The family computer couldn't save the {noun}."}))
            self.done(member, route, self.reply(200, state))
        finally:
            staged.unlink(missing_ok=True)
