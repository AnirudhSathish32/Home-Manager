"""The family hub (app/family_hub.py) and its member side (app/family_client.py), with two Managers on synthetic data.

Tests can't bind a Tailscale address, so the family computer's hub listens on 127.0.0.1 through Manager(hub_loopback=True).
"""

import http.client
import json
import socket

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app import family_hub
from home_manager.app.family_client import pending_copy
from home_manager.app.family_sync import OLD_INVITE_MAGIC, read_invite, seal_blob, seal_copy, write_delivery
from home_manager.app.manager import Manager
from home_manager.app.profiles import encode_key, public
from home_manager.core import actor
from home_manager.finance.ledger import Ledger
from home_manager.finance.tools import FinanceTools
from home_manager.library.scanner import ScanLimits
from home_manager.library.share import ShareError
from home_manager.models import gpu_host
from home_manager.models.http_server import check_bind
from test_profiles import books

PASSPHRASE = "correct horse battery staple"


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def call(address, method, path, token=None, body=b""):
    host, port = address.rsplit(":", 1)
    connection = http.client.HTTPConnection(host, int(port), timeout=10)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if method == "PUT":
        headers["Content-Length"] = str(len(body))
    try:
        connection.request(method, path, body=body or None, headers=headers)
        response = connection.getresponse()
        data = response.read()
    finally:
        connection.close()
    return response.status, json.loads(data) if response.getheader("Content-Type") == "application/json" else data


@pytest.fixture
def family(tmp_path):
    """Mom's computer holds the family (and its hub); Dad joined from his own computer and sent a first copy."""
    port = free_port()
    mom = Manager(tmp_path / "mom-pc", ScanLimits(stability_seconds=0), hub_port=port, hub_loopback=True)
    dad = Manager(tmp_path / "dad-pc", ScanLimits(stability_seconds=0))
    try:
        mom.configure(str(tmp_path / "mom-lib"))
        profile = mom.create_family("The Smiths", str(tmp_path / "family"), ["Dad", "Kid"])
        folder = mom.family_for(profile["id"])[0]
        dad_id, kid_id = (member["member_id"] for member in folder.data["members"])
        (tmp_path / "invites").mkdir()
        invite = mom.invite_member(profile["id"], dad_id, str(tmp_path / "invites"), PASSPHRASE)["path"]
        dad.configure(str(tmp_path / "dad-lib"))
        inbox_scan(dad.store, {"dad.csv": b"dad,amount\n"})
        dad.join_family(invite, PASSPHRASE)
        dad.future.result(timeout=30)
        yield {"mom": mom, "dad": dad, "folder": folder, "profile": profile, "dad_id": dad_id, "kid_id": kid_id, "port": port,
               "address": mom.hub.status()["address"], "fid": folder.data["family_id"], "tmp": tmp_path}
    finally:
        mom.close()
        dad.close()


def dad_link(family):
    dad = family["dad"]
    return dad.profiles.get(dad.profile["id"])["family"]


def sealed(family, tmp_path, seq, **changes):
    """A copy of Dad's library sealed as Dad's computer would, with header fields or the key changed."""
    target = tmp_path / f"copy-{seq}.hmfamily"
    seal_copy(family["dad"].store, {**dad_link(family), **changes}, target, seq, "Dad")
    return target.read_bytes()


def copy_path(family, member=None):
    return f"/v1/families/{family['fid']}/members/{member or family['dad_id']}/copy"


def test_listens_only_on_tailnet_or_test_loopback(monkeypatch):
    for address, loopback in (("192.168.1.5", False), ("0.0.0.0", False), ("127.0.0.1", False), ("8.8.8.8", False),
                              ("0.0.0.0", True), ("100.64.0.1", True)):
        with pytest.raises(ValueError):
            check_bind(address, loopback, "The family hub")
    check_bind("100.101.102.103", False)
    # Whatever address lookup finds, a LAN address is never bound.
    monkeypatch.setattr(family_hub, "tailnet_address", lambda: "192.168.1.5")
    hub = family_hub.Hub(port=0)
    hub.families["x"] = object()  # One family to serve.
    status = hub.start()
    assert not status["listening"] and "Tailscale address" in status["reason"]


def test_join_sends_a_first_copy_through_the_hub(family):
    link = dad_link(family)
    assert link["hub"] == family["address"] and link["hub_state"] == "ok" and link["seq"] == 1 and link["last_sync"]
    member = family["folder"].member(family["dad_id"])
    assert member["status"] == "current" and member["last_seq"] == 1
    assert (family["folder"].members_dir / f"{family['dad_id']}.sqlite3").is_file()
    assert not pending_copy(family["dad"].control, link).exists()  # Sent, so nothing waits.
    view = public(family["dad"].profile)["family"]
    assert "token" not in view and "key" not in view and view["rejoin"] is False
    assert not any((family["folder"].root / "incoming").iterdir())  # The upload's staging file is gone.
    status, body = call(family["address"], "GET", "/v1/ping", link["token"])
    assert status == 200 and body["family_id"] == family["fid"] and body["member_id"] == family["dad_id"]


def test_refusals(family, monkeypatch):
    address, link, tmp = family["address"], dad_link(family), family["tmp"]
    kid_token = family["folder"].new_token(family["kid_id"])
    copy = sealed(family, tmp, 5)
    # No token, a wrong token, another member's token, or the right token on another member's path.
    assert call(address, "PUT", copy_path(family), None, copy)[0] == 401
    assert call(address, "PUT", copy_path(family), "not-a-token", copy)[0] == 401
    assert call(address, "PUT", copy_path(family), kid_token, copy)[0] == 401
    assert call(address, "GET", f"/v1/families/{family['fid']}/members/{family['kid_id']}/deliveries", link["token"])[0] == 401
    assert call(address, "GET", f"/v1/families/{'0' * 32}/members/{family['dad_id']}/deliveries", link["token"])[0] == 401
    # Paths outside the fixed grammar.
    assert call(address, "GET", f"/v1/families/{family['fid']}/members/../deliveries", link["token"])[0] == 404
    assert call(address, "GET", "/api/settings", link["token"])[0] == 404
    # A GPU relay token is no hub token, and a hub token is no GPU token.
    gpu_token = gpu_host.add_member(family["mom"].control, "Dad")
    assert call(address, "GET", "/v1/ping", gpu_token)[0] == 401
    assert gpu_host.GpuHost(family["mom"].control).authenticate("Bearer " + link["token"], loopback=False) is None

    # A copy for another family or member (sealed with this family's key) is refused.
    assert call(address, "PUT", copy_path(family), link["token"], sealed(family, tmp, 6, family_id="f" * 32))[0] == 403
    assert call(address, "PUT", copy_path(family), link["token"], sealed(family, tmp, 7, member_id=family["kid_id"]))[0] == 403
    # One not sealed with the family key, or damaged.
    assert call(address, "PUT", copy_path(family), link["token"], sealed(family, tmp, 8, key=encode_key(b"k" * 32)))[0] == 422
    assert call(address, "PUT", copy_path(family), link["token"], copy[:-20])[0] == 422
    # Replays: the same seq again, or a lower one.
    assert call(address, "PUT", copy_path(family), link["token"], copy)[0] == 200
    status, body = call(address, "PUT", copy_path(family), link["token"], copy)
    assert status == 409 and body["last_seq"] == 5
    assert call(address, "PUT", copy_path(family), link["token"], sealed(family, tmp, 4))[0] == 409
    # Too large: refused before the body is read.
    monkeypatch.setattr(family_hub, "MAX_UPLOAD", 1000)
    assert call(address, "PUT", copy_path(family), link["token"], b"x" * 2000)[0] == 413
    assert family["folder"].member(family["dad_id"])["last_seq"] == 5

    # A new invite replaces the token; removing the member ends it at once.
    family["folder"].new_token(family["dad_id"])
    assert call(address, "GET", "/v1/ping", link["token"])[0] == 401
    kid_path = f"/v1/families/{family['fid']}/members/{family['kid_id']}/deliveries"
    assert call(address, "GET", kid_path, kid_token)[0] == 200
    family["mom"].remove_family_member(family["profile"]["id"], family["kid_id"])
    assert call(address, "GET", kid_path, kid_token)[0] == 401


def test_a_delivery_is_pulled_applied_and_acknowledged(family):
    folder, link = family["folder"], dad_link(family)
    key = "a" * 32
    delivery = {"key": key, "action": "retract", "record_type": "receipt"}  # Retracting something Dad never had changes nothing.
    write_delivery(folder.root, folder.data["family_id"], folder.data["key"], family["dad_id"], delivery)
    path = f"/v1/families/{family['fid']}/members/{family['dad_id']}/deliveries"
    status, listing = call(family["address"], "GET", path, link["token"])
    assert status == 200 and [item["key"] for item in listing["deliveries"]] == [key]
    status, body = call(family["address"], "GET", f"{path}/{key}", link["token"])
    assert status == 200 and body.startswith(b"HMDELIV1") and b"retract" not in body  # Sealed bytes, as stored.

    family["dad"].check_family()
    family["dad"].future.result(timeout=30)
    assert folder.deliveries(family["dad_id"]) == []  # Acknowledged, so the hub deleted it.
    assert dad_link(family)["hub_state"] == "ok"


def test_offline_member_waits_then_syncs(family, tmp_path):
    mom, dad = family["mom"], family["dad"]
    mom.hub.stop()  # The family computer is off.
    inbox_scan(dad.store, {"more.csv": b"more,amount\n"})
    dad.start_family_publish()
    dad.future.result(timeout=30)
    link = dad_link(family)
    assert link["hub_state"] == "waiting" and "can't be reached" in link["hub_error"]
    assert pending_copy(dad.control, link).is_file() and link["seq"] == 2  # Sealed and kept for later.
    assert dad.hub_retry["failures"] == 1 and dad.hub_retry["next"] > 0
    dad.check_family()  # Backing off: nothing is tried yet.
    assert not dad.busy("capture") and dad_link(family)["hub_state"] == "waiting"

    status = mom.refresh_hub()  # The family computer is back, on the same port.
    assert status["listening"] and status["address"] == family["address"]
    dad.hub_retry["next"] = 0.0
    dad.check_family()
    dad.future.result(timeout=30)
    link = dad_link(family)
    assert link["hub_state"] == "ok" and not pending_copy(dad.control, link).exists()
    assert mom.family_for(family["profile"]["id"])[0].member(family["dad_id"])["last_seq"] == 2


def test_rejoin_numbers_copies_above_the_family_s_last(family):
    """A member who joins again (a new invite) starts at seq 1; the hub's 409 tells it where to continue."""
    dad, folder = family["dad"], family["folder"]
    folder.member(family["dad_id"])["last_seq"] = 9  # As if an earlier membership sent nine copies.
    dad.start_family_publish()
    dad.future.result(timeout=30)
    link = dad_link(family)
    assert link["hub_state"] == "ok" and link["seq"] == 10 and folder.member(family["dad_id"])["last_seq"] == 10


RECEIPT_BYTES = b"\x89PNG synthetic receipt HARDWARE STORE 42.00"


def dad_receipt(family):
    """A receipt in Dad's library, citing its preserved document. Returns the document's id."""
    store = family["dad"].store
    inbox_scan(store, {"hardware.png": RECEIPT_BYTES})
    doc = documents_by_name(store)["hardware.png"]
    Ledger(store).publish_receipt({"merchant": "Hardware", "purchase_date": "2026-09-09", "subtotal_minor": None, "tax_minor": None,
                                   "tip_minor": None, "total_minor": 4200, "currency": "USD", "issues": [], "items": [], "locator": {}},
                                  {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "x", "run_id": None}, "verified")
    return doc["id"], doc["current_hash"]


def test_documents_reach_the_family_and_open_while_the_member_is_stopped(family):
    mom, dad = family["mom"], family["dad"]
    document_id, digest = dad_receipt(family)
    dad.start_family_publish()
    dad.future.result(timeout=30)
    link = dad_link(family)
    assert link["hub_state"] == "ok" and link["documents_due"] is False, link["hub_error"]
    folder = mom.family_for(family["profile"]["id"])[0]
    stored = folder.blob_file(digest)
    assert stored.is_file() and RECEIPT_BYTES not in stored.read_bytes()  # Encrypted at rest.
    assert folder.summary()["documents_bytes"] == stored.stat().st_size
    assert folder.missing_blobs([digest]) == []
    dad.close()  # Dad's computer is off.

    mom.switch_profile(family["profile"]["id"])
    mom.future.result(timeout=30)
    media_type, chunks = mom.family_original(family["dad_id"], document_id, None, lambda path: "image/png")
    assert media_type == "image/png" and b"".join(chunks) == RECEIPT_BYTES
    with pytest.raises(ValueError, match="not previewable"):
        mom.family_original(family["dad_id"], document_id, None, lambda path: (_ for _ in ()).throw(ValueError("not previewable")))


def test_documents_are_checked_against_their_hash(family, tmp_path):
    address, link, dad = family["address"], dad_link(family), family["dad"]
    _, digest = dad_receipt(family)
    path = f"/v1/families/{family['fid']}/members/{family['dad_id']}/blobs"
    status, body = call(address, "POST", f"{path}/missing", link["token"], json.dumps({"hashes": [digest]}).encode())
    assert status == 200 and body["missing"] == [digest]
    assert call(address, "POST", f"{path}/missing", link["token"], b'{"hashes": ["../x"]}')[0] == 400
    assert call(address, "POST", f"{path}/missing", "not-a-token", b'{"hashes": []}')[0] == 401

    def sealed_blob(name, **changes):
        target = tmp_path / name
        seal_blob(dad.store, {**link, **changes}, digest, target)
        return target.read_bytes()

    other = "0" * 64
    # Sent under another hash than its header names, for another member, or under another key.
    assert call(address, "PUT", f"{path}/{other}", link["token"], sealed_blob("a.hmblob"))[0] == 403
    assert call(address, "PUT", f"{path}/{digest}", link["token"], sealed_blob("b.hmblob", member_id=family["kid_id"]))[0] == 403
    assert call(address, "PUT", f"{path}/{digest}", link["token"], sealed_blob("c.hmblob", key=encode_key(b"k" * 32)))[0] == 422
    folder = family["folder"]
    assert not folder.blob_file(digest).exists() and not folder.blob_file(other).exists()
    # The header and the path agree, but the content is something else.
    real = dad.store.blob_path(digest)
    saved = real.read_bytes()
    real.write_bytes(b"not the receipt")
    try:
        bad = sealed_blob("d.hmblob")
    finally:
        real.write_bytes(saved)
    status, body = call(address, "PUT", f"{path}/{digest}", link["token"], bad)
    assert status == 422 and "match" in body["error"]
    assert call(address, "PUT", f"{path}/{digest}", link["token"], sealed_blob("e.hmblob"))[0] == 200
    assert folder.missing_blobs([digest]) == []


def dad_transactions(family):
    """Two of Dad's card charges, sent to the family; returns their ids by description."""
    dad = family["dad"]
    books(dad, "card", {("Dad Card", "4321"): [("2026-09-14", "LUMBER YARD", -3000), ("2026-09-15", "PIZZA", -2000)]})
    dad.start_family_publish()
    dad.future.result(timeout=30)
    with dad.store.connection() as db:
        return {row[0]: row[1] for row in db.execute("SELECT description_raw,id FROM transactions WHERE description_raw IN ('LUMBER YARD','PIZZA')")}


def test_a_correction_travels_to_the_member_and_back(family):
    mom, dad, dad_id = family["mom"], family["dad"], family["dad_id"]
    ids = dad_transactions(family)
    mom.switch_profile(family["profile"]["id"])
    mom.future.result(timeout=30)
    with actor.acting_as("Mom"):
        record = mom.correct_family_record(dad_id, "transaction", ids["LUMBER YARD"], {"category": "Home improvement", "merchant": "Home Depot"})
    # Shown at once, waiting for Dad; a delivery waits for his computer.
    assert record["category"] == "home improvement" and sorted(record["pending_fields"]) == ["category", "merchant"]
    rows = mom.family_finance_tool("get_transactions", {"limit": 200, "start": "2026-09-01", "end": "2026-09-30"})["transactions"]
    assert next(row for row in rows if row["id"] == ids["LUMBER YARD"])["pending_fields"]
    assert len(mom.family.deliveries(dad_id)) == 2

    dad.check_family()  # Pulls both, applies them under the family's name.
    dad.future.result(timeout=30)
    corrected = Ledger(dad.store).record("transaction", ids["LUMBER YARD"])
    assert corrected["category"] == "home improvement" and corrected["merchant"] == "Home Depot"
    assert {change["actor"] for change in corrected["family_corrections"]} == {"Family · Mom"}
    assert mom.family.deliveries(dad_id) == []

    dad.start_family_publish()  # His next copy answers; the tag goes.
    dad.future.result(timeout=30)
    record = mom.family_record(dad_id, "transaction", ids["LUMBER YARD"])
    assert record["pending_fields"] == [] and record["category"] == "home improvement"


def test_a_conflicting_correction_becomes_a_review_question(family):
    mom, dad, dad_id = family["mom"], family["dad"], family["dad_id"]
    ids = dad_transactions(family)
    mom.switch_profile(family["profile"]["id"])
    mom.future.result(timeout=30)
    for description in ("LUMBER YARD", "PIZZA"):
        mom.correct_family_record(dad_id, "transaction", ids[description], {"category": "Family stuff"})
    # Meanwhile Dad set both categories himself.
    for description in ("LUMBER YARD", "PIZZA"):
        Ledger(dad.store).set_category(ids[description], "Mine")
    dad.check_family()
    dad.future.result(timeout=30)
    questions = [issue for issue in FinanceTools(dad.store).review_queue()["issues"] if issue["issue_type"] == "family_correction"]
    assert len(questions) == 2 and questions[0]["detail"]["corrections"][0]["current"] == "mine"
    by_record = {issue["record_id"]: issue["id"] for issue in questions}
    dad.resolve_issue(by_record[ids["LUMBER YARD"]], family_choice="family")
    dad.resolve_issue(by_record[ids["PIZZA"]], family_choice="mine")
    ledger = Ledger(dad.store)
    assert ledger.record("transaction", ids["LUMBER YARD"])["category"] == "family stuff"
    assert ledger.record("transaction", ids["PIZZA"])["category"] == "mine"
    with pytest.raises(ValueError, match="already answered"):
        dad.resolve_issue(by_record[ids["PIZZA"]], family_choice="family")

    dad.start_family_publish()
    dad.future.result(timeout=30)
    with mom.store.connection() as db:
        statuses = {row[0]: row[1] for row in db.execute("SELECT record_id,status FROM family_corrections WHERE direction='sent'")}
    assert statuses == {ids["LUMBER YARD"]: "applied", ids["PIZZA"]: "rejected"}
    # Kept mine: the family view shows Dad's value again.
    assert mom.family_record(dad_id, "transaction", ids["PIZZA"])["category"] == "mine"


def test_old_invites_and_links_ask_for_a_new_invite(tmp_path):
    old = tmp_path / "old.hminvite"
    old.write_bytes(OLD_INVITE_MAGIC + b"\x00" * 64)
    with pytest.raises(ShareError, match="Ask the family computer for a new invite"):
        read_invite(old, PASSPHRASE)
    profile = {"id": "p", "name": "Dad", "kind": "individual", "folder": "x",
               "family": {"family_id": "f" * 32, "member_id": "a" * 12, "key": "k", "sync": "C:/OneDrive", "local": False}}
    assert public(profile)["family"]["rejoin"] is True


def test_invites_need_a_listening_hub(tmp_path):
    manager = Manager(tmp_path / "pc", ScanLimits(stability_seconds=0))  # No Tailscale in tests.
    try:
        profile = manager.create_family("Us", str(tmp_path / "family"), ["Kid"])
        family, temporary = manager.family_for(profile["id"])
        kid = family.data["members"][0]["member_id"]
        if temporary:
            family.close()
        (tmp_path / "out").mkdir()
        with pytest.raises(ValueError, match="Tailscale isn't running"):
            manager.invite_member(profile["id"], kid, str(tmp_path / "out"), PASSPHRASE)
    finally:
        manager.close()
