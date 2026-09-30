"""The family's tax returns (docs/taxes.md): who files together, and a joint return gathered from both members' copies."""

from datetime import date

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.family_sync import FamilyFolder
from home_manager.app.manager import Manager
from home_manager.finance.tax_family import TaxUnits, combine
from home_manager.household.tax_tables import TaxTables
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_plan_tracking import stub
from test_tax_return import JOINT


def gathered(key, wages, interest, state=None):
    return {"values": {"interest": interest}, "sources": {"interest": "bank"}, "state": state, "notes": [],
            "jobs": [{"key": key, "name": "Acme", "values": {"wages": wages}}], "businesses": [],
            "estimated_payments": {"federal_estimated": [{"date": "2026-04-15", "amount_minor": 1000}], "state_estimated": []}}


def test_a_joint_return_adds_up_its_members_and_lists_whose_jobs_are_whose():
    combined = combine([("Ana", gathered("employer-1", 100, 5, "GA")), ("Tom", gathered("employer-1", 200, 7))])
    assert combined["values"]["interest"] == 12 and combined["state"] == "GA"
    assert [(job["key"], job["name"], job["owner"]) for job in combined["jobs"]] == [("Ana:employer-1", "Ana · Acme", "Ana"), ("Tom:employer-1", "Tom · Acme", "Tom")]
    assert len(combined["estimated_payments"]["federal_estimated"]) == 2 and combined["sources"]["interest"] == "Ana: bank; Tom: bank"
    alone = combine([("Ana", gathered("employer-1", 100, 5))])
    assert alone["jobs"][0]["name"] == "Acme" and alone["sources"]["interest"] == "bank"


def test_returns_are_one_person_or_a_married_couple(tmp_path):
    store = Store(tmp_path / "family")
    try:
        units, known = TaxUnits(store), {"a": "Ana", "t": "Tom", "k": "Kid"}
        joint = units.add("", ["a", "t"], "married_joint", known)
        assert joint["name"] == "Ana & Tom" and joint["members"] == ["a", "t"]
        with pytest.raises(ValueError, match="already on another return"):
            units.add("", ["t"], "single", known)
        with pytest.raises(ValueError, match="A joint return is two people"):
            units.add("", ["k"], "married_joint", known)
        with pytest.raises(ValueError, match="members of this family"):
            units.add("", ["zz"], "single", known)
        assert units.add("", ["k"], "single", known)["name"] == "Kid"
        units.delete(joint["id"])
        assert [unit["name"] for unit in units.list()] == ["Kid"]
    finally:
        store.close()


def paid(manager, name, federal):
    """This year's pay stub in the open library: 4,000 gross every two weeks."""
    inbox_scan(manager.store, {f"{name}.png": name.encode()})
    stub(manager.store, documents_by_name(manager.store)[f"{name}.png"], f"{date.today().year}-01-02", federal, 270000)
    with manager.store.connection() as db:
        db.execute("UPDATE income_records SET pay_frequency=26")


def test_the_family_computes_a_couples_joint_return(tmp_path):
    year = date.today().year
    manager = Manager(tmp_path / "control", ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(tmp_path / "mom"))
        manager.rename_profile(manager.profile["id"], "Mom")
        mom = manager.profile["id"]
        paid(manager, "mom", 30000)
        tables = TaxTables(manager.store)
        tables.review(tables.propose("US", year, "married_joint", JOINT, [])["id"], "verified")
        dad = manager.create_profile("Dad", str(tmp_path / "dad"))
        manager.switch_profile(dad["id"])
        paid(manager, "dad", 20000)
        manager.switch_profile(mom)
        family = manager.create_family("The Smiths", str(tmp_path / "family"), str(tmp_path), ["Dad"], my_profile=mom)
        folder = FamilyFolder(tmp_path / "family")
        members = {member["name"]: member["member_id"] for member in folder.data["members"]}
        folder.close()
        manager.set_up_local_member(family["id"], members["Dad"], dad["id"], None)
        manager.switch_profile(family["id"])
        manager.future.result(timeout=30)
        before = manager.family_tax(year)
        assert before["returns"] == [] and {member["name"] for member in before["members"]} == {"Mom", "Dad"}
        manager.add_tax_unit("", [members["Mom"], members["Dad"]], "married_joint")
        view = manager.family_tax(year)
        [joint] = view["returns"]
        assert joint["name"] == "Mom & Dad" and joint["member_names"] == ["Mom", "Dad"]
        jobs = joint["view"]["gathered"]["jobs"]
        assert sorted(job["owner"] for job in jobs) == ["Dad", "Mom"]
        result = joint["view"]["return"]
        # Both paychecks on one return, on the joint table (from Mom's copy), with Tax Zen for the couple.
        assert result["result_minor"] is not None and joint["view"]["tables"]["US"] == "verified"
        wages = next(line for line in result["lines"] if line["key"] == "wages")["amount_minor"]
        assert wages == sum(job["values"]["wages"] for job in jobs)
        assert joint["view"]["zen"]["ready"] and joint["view"]["zen"]["job"]["key"] in {job["key"] for job in jobs}
    finally:
        manager.close()
