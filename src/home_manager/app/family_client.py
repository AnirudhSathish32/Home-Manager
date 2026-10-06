"""Member side of the family hub (app/family_hub.py): push this library's copy, pull what the family sent.

The copy is sealed first into <control>/family/<family_id>/outbox/copy.hmfamily and sent from there, so it waits while
the family computer is off or away from Tailscale; a newer copy replaces an unsent older one. http.client is used, as in
models/model_client.py, so no proxy setting is consulted and no redirect is followed.
"""

import http.client
import ipaddress
import json
from pathlib import Path
import uuid

from ..core.paths import safe_path
from ..models.http_server import TAILNET
from .family_sync import cited_blobs, open_delivery, seal_blob, seal_copy

TIMEOUT = 20  # Seconds to connect, and between bytes once connected.
CHUNK = 1024 * 1024
OFFLINE = "The family computer can't be reached. It may be off, or not connected to Tailscale."


class HubError(Exception):
    """state is "waiting" (try again later) or "refused" (the hub said no; trying again won't help until something changes)."""

    def __init__(self, state, message, last_seq=None):
        super().__init__(message)
        self.state, self.last_seq = state, last_seq


def hub_address(value):
    """(host, port) from an invite's "100.x.y.z:port". Only a Tailscale address (or loopback, which the tests use)."""
    host, _, port = str(value or "").rpartition(":")
    try:
        ip = ipaddress.ip_address(host)
        port_number = int(port)
    except ValueError:
        raise HubError("refused", "The family hub address is not valid. Ask the family computer for a new invite.") from None
    if not (ip in TAILNET or str(ip) == "127.0.0.1") or not 1 <= port_number <= 65535:
        raise HubError("refused", "The family hub address is not a Tailscale address. Ask the family computer for a new invite.")
    return host, port_number


def member_path(link, tail=""):
    return f"/v1/families/{link['family_id']}/members/{link['member_id']}/{tail}"


def _request(link, method, path, body: Path | bytes | None = None):
    """Send one request and return (connection, response) with the response unread; the caller closes the connection.
    A file body is streamed; a bytes body is JSON."""
    host, port = hub_address(link.get("hub"))
    connection = http.client.HTTPConnection(host, port, timeout=TIMEOUT)
    try:
        connection.putrequest(method, path, skip_accept_encoding=True)
        connection.putheader("Authorization", "Bearer " + str(link.get("token") or ""))
        if isinstance(body, bytes):
            connection.putheader("Content-Type", "application/json")
            connection.putheader("Content-Length", str(len(body)))
        elif body is not None:
            connection.putheader("Content-Type", "application/octet-stream")
            connection.putheader("Content-Length", str(body.stat().st_size))
        elif method in ("PUT", "DELETE", "POST"):
            connection.putheader("Content-Length", "0")
        connection.endheaders()
        if isinstance(body, bytes):
            connection.send(body)
        elif body is not None:
            with open(body, "rb") as source:
                while chunk := source.read(CHUNK):
                    connection.send(chunk)
        response = connection.getresponse()
    except (OSError, http.client.HTTPException):
        connection.close()
        raise HubError("waiting", OFFLINE) from None
    return connection, response


def _json(link, method, path, body=None):
    connection, response = _request(link, method, path, body)
    try:
        data = response.read(1024 * 1024)
    except (OSError, http.client.HTTPException):
        raise HubError("waiting", OFFLINE) from None
    finally:
        connection.close()
    try:
        value = json.loads(data or b"{}")
    except ValueError:
        value = {}
    if not isinstance(value, dict):
        value = {}
    if response.status != 200:
        raise _refusal(response.status, value)
    return value


def _refusal(status, value):
    message = str(value.get("error") or "The family computer refused the request.")[:300]
    if status >= 500:
        return HubError("waiting", message)
    return HubError("refused", message, value.get("last_seq") if isinstance(value.get("last_seq"), int) else None)


# Copies -------------------------------------------------------------------------------

def pending_copy(control: Path, link) -> Path:
    folder = safe_path(Path(control) / "family" / link["family_id"] / "outbox")
    folder.mkdir(parents=True, exist_ok=True)
    return safe_path(folder / "copy.hmfamily")


def seal_pending(store, control, link, member_name, birth_year=None):
    """Seal a new copy into the outbox, replacing an unsent older one. Returns the link's new seq and publish time."""
    seq = int(link.get("seq") or 0) + 1
    published_at = seal_copy(store, link, pending_copy(control, link), seq, member_name, birth_year)
    return {"seq": seq, "published_at": published_at}


def upload_pending(control, link):
    """Send the waiting copy, if any. True when one was accepted. A copy the hub already has a newer one of is dropped,
    and the hub's last seq returned in the error so the next copy starts above it."""
    path = pending_copy(control, link)
    if not path.is_file():
        return False
    try:
        _json(link, "PUT", member_path(link, "copy"), path)
    except HubError as exc:
        if exc.last_seq is not None:
            path.unlink(missing_ok=True)
        raise
    path.unlink(missing_ok=True)
    return True


# Documents ----------------------------------------------------------------------------

def push_documents(store, link, work=None):
    """Send each document this library's records cite that the family doesn't hold yet, sealed with the family key.
    Returns how many were sent. A document missing from this library (never preserved) is skipped."""
    digests = cited_blobs(store)
    if not digests:
        return 0
    missing = _json(link, "POST", member_path(link, "blobs/missing"), json.dumps({"hashes": digests}).encode()).get("missing")
    sent = 0
    for digest in missing if isinstance(missing, list) else []:
        if work:
            work.check()
        if digest not in digests or not store.blob_path(digest).is_file():
            continue
        target = safe_path(store.work / f"blob-{uuid.uuid4().hex}.hmblob")
        try:
            seal_blob(store, link, digest, target)
            _json(link, "PUT", member_path(link, f"blobs/{digest}"), target)
        finally:
            target.unlink(missing_ok=True)
        sent += 1
    return sent


# Deliveries ---------------------------------------------------------------------------

def list_deliveries(link):
    found = _json(link, "GET", member_path(link, "deliveries")).get("deliveries")
    return [item["key"] for item in found if isinstance(item, dict) and isinstance(item.get("key"), str)] if isinstance(found, list) else []


def pull_deliveries(store, link, apply, keys=None, work=None):
    """Download each waiting delivery, apply(delivery, document), then acknowledge it so the hub deletes it. Returns how many
    were applied. One that fails to apply stays on the hub for the next check."""
    applied = 0
    for key in list_deliveries(link) if keys is None else keys:
        if work:
            work.check()
        target = safe_path(store.work / f"delivery-{uuid.uuid4().hex}.hmdelivery")
        try:
            connection, response = _request(link, "GET", member_path(link, f"deliveries/{key}"))
            try:
                if response.status != 200:
                    try:
                        value = json.loads(response.read(65536) or b"{}")
                    except ValueError:
                        value = {}
                    raise _refusal(response.status, value if isinstance(value, dict) else {})
                with open(target, "wb") as sink:
                    while chunk := response.read(CHUNK):
                        sink.write(chunk)
            except (OSError, http.client.HTTPException):
                raise HubError("waiting", OFFLINE) from None
            finally:
                connection.close()
            try:
                delivery, document = open_delivery(target, link)
                if delivery["key"] != key:
                    raise ValueError("The delivery's key doesn't match.")
                apply(delivery, document)
            except (ValueError, OSError):
                continue  # Left on the hub; the next check tries again.
        finally:
            target.unlink(missing_ok=True)
        _json(link, "DELETE", member_path(link, f"deliveries/{key}"))
        applied += 1
    return applied
