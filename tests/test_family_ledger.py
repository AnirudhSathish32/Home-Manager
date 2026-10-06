"""The family ledger (docs/family.md "Family ledger"): Transactions, Spending, Bills and Accounts across members' copies."""

from datetime import date

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.family_sync import FamilyFolder
from home_manager.finance.family import family_dashboard
from home_manager.finance.ledger import Ledger
from home_manager.library.scanner import ScanLimits
from test_profiles import books

TODAY = date(2026, 9, 25)
SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}


@pytest.fixture
def family(tmp_path):
    """Mom and Dad on one computer, sharing a joint account, with a Zelle between them; the family view is open."""
    app = create_app(tmp_path / "control", "token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        manager = app.state.manager
        manager.configure(str(tmp_path / "mom"))
        manager.rename_profile(manager.profile["id"], "Mom")
        mom = manager.profile["id"]
        books(manager, "mom", {("Shared Bank", "1234"): [("2026-09-02", "GROCERY", -4000), ("2026-09-03", "PAYROLL", 100000)],
                               ("Mom Card", "9999"): [("2026-09-05", "ZELLE TO DAD", -5000), ("2026-09-10", "BOOKS", -1500)]})
        dad = manager.create_profile("Dad", str(tmp_path / "dad"))
        manager.switch_profile(dad["id"])
        books(manager, "dad", {("Shared Bank", "1234"): [("2026-09-02", "GROCERY", -4000), ("2026-09-03", "PAYROLL", 100000)],
                               ("Dad Bank", "5555"): [("2026-09-06", "ZELLE FROM MOM", 5000), ("2026-09-12", "HARDWARE", -2500)]})
        inbox_scan(manager.store, {"hardware.png": b"\x89PNG dad's hardware receipt"})
        doc = documents_by_name(manager.store)["hardware.png"]
        Ledger(manager.store).publish_receipt({"merchant": "Hardware", "purchase_date": "2026-09-12", "subtotal_minor": None, "tax_minor": None,
                                               "tip_minor": None, "total_minor": 2500, "currency": "USD", "issues": [], "items": [], "locator": {}},
                                              {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "x", "run_id": None}, "verified")
        manager.switch_profile(mom)
        profile = manager.create_family("The Smiths", str(tmp_path / "family"), ["Dad"], my_profile=mom)
        folder = FamilyFolder(tmp_path / "family")
        ids = {member["name"]: member["member_id"] for member in folder.data["members"]}
        folder.close()
        manager.set_up_local_member(profile["id"], ids["Dad"], dad["id"], None)
        manager.switch_profile(profile["id"])
        manager.future.result(timeout=30)
        yield {"client": client, "manager": manager, "ids": ids, "headers": {"Authorization": "Bearer token"}, "receipt_document": doc["id"]}


def tool(family, name, arguments=None):
    response = family["client"].post(f"/api/finance/tools/{name}?members=true", json=arguments or {}, headers=family["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def test_transactions_span_members_with_owners_and_count_shared_money_once(family):
    everything = tool(family, "get_transactions", {**SEPTEMBER, "limit": 200})
    rows = everything["transactions"]
    # Dad (listed first) carries the joint account; Mom's copy of it is left out, so the grocery appears once.
    assert [row["description_raw"] for row in rows].count("GROCERY") == 1
    assert {row["owner"] for row in rows} == {"Mom", "Dad"} and all(row["member_id"] in family["ids"].values() for row in rows)
    assert everything["total_matching"] == len(rows) == 6
    assert [row["posted_date"] for row in rows] == sorted((row["posted_date"] for row in rows), reverse=True)
    # A page is the same slice of the merged list.
    page = tool(family, "get_transactions", {**SEPTEMBER, "limit": 2, "offset": 2})
    assert [(row["member_id"], row["id"]) for row in page["transactions"]] == [(row["member_id"], row["id"]) for row in rows[2:4]]
    assert page["total_matching"] == 6
    # One member's account.
    accounts = tool(family, "get_accounts")["accounts"]
    card = next(account for account in accounts if account["display_name"].startswith("Mom Card"))
    assert card["owner"] == "Mom"
    only = tool(family, "get_transactions", {**SEPTEMBER, "member": card["member_id"], "account_id": card["id"], "limit": 200})
    assert {row["description_raw"] for row in only["transactions"]} == {"ZELLE TO DAD", "BOOKS"}


def test_spending_adds_up_to_the_family_dashboard(family):
    manager = family["manager"]
    spending = tool(family, "get_spending", SEPTEMBER)
    [usd] = spending["by_currency"]
    with manager.family.mutex:
        dashboard = family_dashboard(manager.family_members(), "2026-09", today=TODAY)
    # Grocery once (4000) + books (1500) + hardware (2500), and Dad's hardware receipt (2500) until a charge replaces it.
    assert usd["net_spending"]["minor"] == dashboard["totals"]["net_spending"]["minor"] == 10500
    categories = tool(family, "get_spending_by_category", SEPTEMBER)
    assert sum(row["spending"]["minor"] for row in categories["categories"]) == usd["spending"]["minor"]
    compared = tool(family, "compare_categories", {"first": {"start": "2026-08-01", "end": "2026-08-31"}, "second": SEPTEMBER})
    assert sum(row["second"]["minor"] for row in compared["categories"]) == usd["spending"]["minor"]
    assert tool(family, "get_upcoming_bills", {"as_of": TODAY.isoformat(), "days": 30})["bills"] == []


def test_records_and_originals_open_from_the_owners_copy(family):
    client, headers, dad = family["client"], family["headers"], family["ids"]["Dad"]
    row = next(row for row in tool(family, "get_transactions", {**SEPTEMBER, "limit": 200})["transactions"] if row["description_raw"] == "HARDWARE")
    record = client.get(f"/api/finance/records/transaction/{row['id']}?member={dad}", headers=headers)
    assert record.status_code == 200 and record.json()["owner"] == "Dad" and record.json()["description_raw"] == "HARDWARE"
    # Dad is on this computer: his original is read from his library folder.
    original = client.get(f"/api/documents/{family['receipt_document']}/image?member={dad}", headers=headers)
    assert original.status_code == 200 and original.content == b"\x89PNG dad's hardware receipt"
    # Tools that aren't part of the family ledger are refused, not run on someone's copy.
    refused = client.post("/api/finance/tools/get_budgets?members=true", json={"month": "2026-09"}, headers=headers)
    assert refused.status_code == 400 and "own profile" in refused.json()["detail"]
    # Without members=true a family profile's tools read its own library (the inbox), as Review and Home expect.
    assert client.post("/api/finance/tools/get_accounts", json={}, headers=headers).json()["accounts"] == []


def test_a_correction_to_a_member_here_applies_and_can_be_rejected(family):
    """Dad's profile is on this computer: the family's correction applies to his library at once, under the family's name."""
    client, headers, manager, dad = family["client"], {**family["headers"], "X-HM-Actor": "Mom"}, family["manager"], family["ids"]["Dad"]
    row = next(row for row in tool(family, "get_transactions", {**SEPTEMBER, "limit": 200})["transactions"] if row["description_raw"] == "HARDWARE")
    path = f"/api/finance/records/transaction/{row['id']}?member={dad}"
    refused = client.patch(path, json={"changes": {"posted_date": "2026-13-01"}}, headers=headers)
    assert refused.status_code == 400 and "full date" in refused.json()["detail"]
    assert client.patch(path, json={"changes": {"category": None}}, headers=headers).status_code == 400  # Already says that.
    sent = client.patch(path, json={"changes": {"category": "Home improvement"}}, headers=headers)
    assert sent.status_code == 200, sent.text
    record = sent.json()["record"]
    assert record["category"] == "home improvement" and record["pending_fields"] == []  # Applied and answered at once.
    with manager.store.connection() as db:
        assert [tuple(item) for item in db.execute("SELECT direction,status,actor FROM family_corrections")] == [("sent", "applied", "Mom")]

    # In Dad's own profile: changed by the family, with Reject.
    profiles = {profile["name"]: profile["id"] for profile in manager.profiles.all()}
    manager.switch_profile(profiles["Dad"])
    plain = family["headers"]  # Dad's profile has one person: him.
    mine = client.get(f"/api/finance/records/transaction/{row['id']}", headers=plain).json()
    [change] = mine["family_corrections"]
    assert mine["category"] == "home improvement" and change["actor"] == "Family · Mom" and change["status"] == "applied"
    assert mine["corrections"][-1]["actor"] == "Family · Mom"
    rejected = client.post(f"/api/finance/family-corrections/{change['key']}/reject", json={}, headers=plain)
    assert rejected.status_code == 200, rejected.text
    assert client.get(f"/api/finance/records/transaction/{row['id']}", headers=plain).json()["category"] is None
    assert client.post(f"/api/finance/family-corrections/{change['key']}/reject", json={}, headers=plain).status_code == 400

    # Back in the family view: the next copy shows the record as Dad has it, and the family's row says rejected.
    manager.switch_profile(profiles["The Smiths"])
    manager.future.result(timeout=30)
    again = client.get(path, headers=headers).json()
    assert again["category"] is None and again["pending_fields"] == []
    with manager.store.connection() as db:
        assert db.execute("SELECT status FROM family_corrections").fetchone()[0] == "rejected"
