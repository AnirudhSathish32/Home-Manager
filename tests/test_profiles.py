"""Profiles (each person's own library) and the family view that adds members' copies together."""

from datetime import date
import io
import json
import secrets

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder
from home_manager.app.manager import Manager
from home_manager.finance.family import family_dashboard, family_net_worth
from home_manager.finance.ledger import HouseholdConfig, Ledger
from home_manager.library.scanner import ScanLimits
from home_manager.library.share import DecryptingReader, EncryptingWriter, ShareError
from home_manager.library.storage import Store
from test_reconcile_tools import add

PASSPHRASE = "correct horse battery staple"
TODAY = date(2026, 9, 25)


def manager_at(path, hub=False):
    """hub: this computer runs a family hub, on loopback with a free port (tests/test_family_hub.py)."""
    return Manager(path, ScanLimits(stability_seconds=0), hub_port=0, hub_loopback=hub)


def books(manager, name, rows_by_account):
    """Record synthetic transactions in the open library: {(institution, last four): [(day, text, minor)]}."""
    inbox_scan(manager.store, {f"{name}.csv": f"{name},amount\n".encode()})
    doc = documents_by_name(manager.store)[f"{name}.csv"]
    ledger = Ledger(manager.store)
    for (institution, last_four), rows in rows_by_account.items():
        account = ledger.create_account(institution, "checking", "USD", last_four=last_four)
        add(manager.store, ledger, account, doc, rows, status="verified")


def test_key_encryption_round_trip_and_wrong_key():
    key, other = secrets.token_bytes(32), secrets.token_bytes(32)
    sink = io.BytesIO()
    writer = EncryptingWriter(sink, key=key, magic=b"HMFAMLY1")
    writer.write(b"family totals" * 1000)
    writer.finish()
    data = sink.getvalue()
    assert DecryptingReader(io.BytesIO(data), key=key, magic=b"HMFAMLY1", noun="family").read() == b"family totals" * 1000
    with pytest.raises(ShareError, match="Wrong family key"):
        DecryptingReader(io.BytesIO(data), key=other, magic=b"HMFAMLY1", noun="family").read()
    with pytest.raises(ShareError, match="not a Home Manager share"):
        DecryptingReader(io.BytesIO(data), PASSPHRASE)  # A family file is never read as a passphrase share.
    with pytest.raises(ShareError, match="damaged or incomplete"):
        DecryptingReader(io.BytesIO(data[:-5]), key=key, magic=b"HMFAMLY1", noun="family").read()


def test_existing_library_becomes_the_first_profile(tmp_path):
    control = tmp_path / "control"
    manager = manager_at(control)
    try:
        manager.configure(str(tmp_path / "mine"))
    finally:
        manager.close()
    # Simulate an install from before profiles: only settings.json and the computer's preferences.
    (control / "profiles.json").unlink()
    (control / "household.json").write_text(HouseholdConfig(home_currency="EUR", filing_status="married_joint").model_dump_json())
    manager = manager_at(control)
    try:
        view = manager.settings()
        assert view["configured"] and view["profile"]["name"] == "My profile" and view["profile"]["kind"] == "individual"
        assert view["profile"]["folder"] == str(tmp_path / "mine")
        assert manager.household.home_currency == "EUR" and manager.household.filing_status == "married_joint"
    finally:
        manager.close()


def test_profiles_keep_separate_libraries_and_preferences(tmp_path):
    manager = manager_at(tmp_path / "control")
    try:
        manager.configure(str(tmp_path / "mine"))
        mine = manager.profile["id"]
        manager.configure_household(HouseholdConfig(home_currency="GBP"))
        inbox_scan(manager.store, {"mine.png": b"my receipt"})
        other = manager.create_profile("Sam", str(tmp_path / "sam"))
        manager.switch_profile(other["id"])
        assert manager.store.root == tmp_path / "sam" and manager.household.home_currency is None
        assert manager.store.documents()["total"] == 0
        Store(tmp_path / "mine").close()  # The previous profile's library lock was released.
        manager.switch_profile(mine)
        assert manager.household.home_currency == "GBP"
        assert [doc["relative_path"] for doc in manager.store.documents()["items"]] == ["mine.png"]
        with pytest.raises(RuntimeError, match="Switch to another profile"):
            manager.remove_profile(mine)
        manager.remove_profile(other["id"])
        assert (tmp_path / "sam" / "inventory.sqlite3").exists()  # Forgetting a profile keeps its library.
    finally:
        manager.close()


def test_family_across_two_computers_adds_members_and_counts_shared_money_once(tmp_path):
    outbox = tmp_path / "outbox"
    outbox.mkdir()
    mom = manager_at(tmp_path / "mom-pc", hub=True)
    dad = manager_at(tmp_path / "dad-pc")
    try:
        mom.configure(str(tmp_path / "mom-lib"))
        mom.rename_profile(mom.profile["id"], "Mom")
        books(mom, "mom", {("Shared Bank", "1234"): [("2026-09-02", "GROCERY", -4000), ("2026-09-03", "PAYROLL", 100000)],
                           ("Mom Card", "9999"): [("2026-09-05", "ZELLE TO DAD", -5000), ("2026-09-10", "BOOKS", -1500)]})
        family = mom.create_family("The Smiths", str(tmp_path / "family"), ["Dad"], my_profile=mom.profile["id"])
        assert mom.profile["name"] == "Mom" and mom.profiles.get(mom.profile["id"])["family"]["local"] is True
        dad_member = next(member for member in mom.family_for(family["id"])[0].data["members"] if member["name"] == "Dad")
        invite = mom.invite_member(family["id"], dad_member["member_id"], str(outbox), PASSPHRASE)["path"]
        assert invite.endswith(".hminvite")

        dad.configure(str(tmp_path / "dad-lib"))
        books(dad, "dad", {("Shared Bank", "1234"): [("2026-09-02", "GROCERY", -4000), ("2026-09-03", "PAYROLL", 100000)],
                           ("Dad Bank", "5555"): [("2026-09-06", "ZELLE FROM MOM", 5000), ("2026-09-12", "HARDWARE", -2500)]})
        with pytest.raises(ShareError, match="Wrong passphrase"):
            dad.join_family(invite, "wrong passphrase here")
        dad.join_family(invite, PASSPHRASE)
        dad.future.result(timeout=30)
        link = dad.profiles.get(dad.profile["id"])["family"]
        assert link["published_at"] and link["hub_state"] == "ok" and link["seq"] == 1, link["hub_error"]

        mom.switch_profile(family["id"])
        mom.future.result(timeout=30)
        assert mom.family and mom.store.root == tmp_path / "family" / "library"  # The family's own inbox, never counted itself.
        summary = mom.family.summary()
        assert [member["status"] for member in summary["members"]] == ["current", "current"], summary
        assert summary["adjustments"]["joint_accounts"][0]["counted_for"] == "Dad"  # Dad was listed first.
        assert [(pair["from"], pair["to"], pair["amount"]["minor"]) for pair in summary["adjustments"]["transfers"]] == [("Mom", "Dad", 5000)]
        with mom.family.mutex:
            members = mom.family_members()
            result = family_dashboard(members, "2026-09", today=TODAY)
            worth = family_net_worth(members, "USD", today=TODAY)
        # Grocery once (4000) + books (1500) + hardware (2500); the Zelle between them is neither spending nor income.
        assert result["totals"]["net_spending"]["minor"] == 8000
        assert result["cashflow"]["inflow"]["minor"] == 100000
        assert {row["name"]: row["totals"]["net_spending"]["minor"] for row in result["members"]} == {"Dad": 6500, "Mom": 1500}
        assert sum(row["totals"]["net_spending"]["minor"] for row in result["members"]) == result["totals"]["net_spending"]["minor"]
        assert result["gross"]["minor"] == sum(row["spending"]["minor"] for row in result["categories"])
        assert worth["total"]["net_worth"]["minor"] == sum(row["net_worth"]["minor"] for row in worth["members"])
        # A record waiting in the family's inbox counts for nobody until it is routed and delivered.
        inbox_scan(mom.store, {"unrouted.png": b"family receipt"})
        doc = documents_by_name(mom.store)["unrouted.png"]
        Ledger(mom.store).publish_receipt({"merchant": "Market", "purchase_date": "2026-09-09", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                           "total_minor": 9900, "currency": "USD", "issues": [], "items": [], "locator": {}},
                                          {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "x", "run_id": None}, "verified")
        with mom.family.mutex:
            assert family_dashboard(mom.family_members(), "2026-09", today=TODAY)["totals"]["net_spending"]["minor"] == 8000
    finally:
        mom.close()
        dad.close()


def test_profile_and_family_api(tmp_path):
    app = create_app(tmp_path / "control", "token", limits=ScanLimits(stability_seconds=0))
    headers = {"Authorization": "Bearer token"}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        app.state.manager.configure(str(tmp_path / "mine"))
        created = client.post("/api/profiles", json={"name": "Sam", "folder": str(tmp_path / "sam")}, headers=headers)
        assert created.status_code == 201, created.text
        family = client.post("/api/families", json={"name": "Us", "folder": str(tmp_path / "family"), "members": ["Grandma"]}, headers=headers).json()
        listed = client.get("/api/profiles", headers=headers).json()
        assert [profile["kind"] for profile in listed["profiles"]] == ["individual", "individual", "family"]
        assert all("key" not in json.dumps(profile) for profile in listed["profiles"])
        # No Tailscale in tests: the hub says why it isn't listening, and an invite can't be made.
        assert listed["hub_status"] == {"listening": False, "address": None, "reason": "Tailscale isn't running on this computer, so members' computers can't reach it."}
        members = FamilyFolder(tmp_path / "family")
        grandma = members.data["members"][0]["member_id"]
        members.close()
        local = client.post(f"/api/families/{family['id']}/members/{grandma}/local", json={"profile_id": created.json()["id"]}, headers=headers)
        assert local.status_code == 200, local.text
        switched = client.put("/api/profiles/active", json={"id": family["id"]}, headers=headers)
        assert switched.status_code == 200 and switched.json()["family"]["name"] == "Us"
        app.state.manager.future.result(timeout=30)
        dashboard = client.get("/api/dashboard?month=2026-09", headers=headers).json()
        assert dashboard.get("family_empty") or dashboard["family"]["name"] == "Us"
        assert client.post("/api/inbox-scans", headers=headers).status_code == 202  # Uploads go to the family's inbox.
        routing = client.get("/api/family/routing", headers=headers)
        assert routing.status_code == 200 and [person["name"] for person in routing.json()["people"]] == ["Grandma"]
        assert client.get("/api/family/net-worth", headers=headers).status_code == 200
        app.state.manager.future.result(timeout=30)  # Switching waits for the inbox scan to finish.
        back = client.put("/api/profiles/active", json={"id": listed["profiles"][0]["id"]}, headers=headers).json()
        assert back["configured"] and back["family"] is None
