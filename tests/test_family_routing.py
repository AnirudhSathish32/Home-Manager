"""Family routing rules: owners are only suggested when exactly one person fits, assignments are validated, and a
delivery applied twice updates rather than duplicates. The end-to-end flow is in test_family_inbox.py."""

import hashlib

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.finance.family_routing import FamilyRouting, apply_delivery, filing, suggest
from home_manager.finance.ledger import Ledger, normalize_name
from home_manager.finance.tools import FinanceTools, PeriodInput
from home_manager.library.storage import Store
from test_family_inbox import costco

FACTS = {"mom": {"last_four": {"1234", "5555"}, "employers": {normalize_name("Acme Corp")}},  # As member_facts builds them.
         "dad": {"last_four": {"9876", "5555"}, "employers": set()}}


def row(record_type="receipt", last_four=None, name=None):
    return {"record_type": record_type, "last_four": last_four, "name": name}


def test_an_owner_is_suggested_only_when_exactly_one_person_fits():
    assert suggest(row(last_four="1234"), FACTS) == ("mom", "Paid with a card or account ending 1234")
    assert suggest(row(last_four="5555"), FACTS) == (None, "More than one person has an account ending 5555")
    assert suggest(row(last_four="0000"), FACTS) == (None, "Nothing on it says whose it is")
    assert suggest(row(), FACTS) == (None, "Nothing on it says whose it is")


def test_pay_stubs_are_suggested_by_employer_and_receipts_are_not():
    assert suggest(row("income_record", name="Acme Corp"), FACTS) == ("mom", "Earlier pay stubs from Acme Corp")
    assert suggest(row("receipt", name="Acme Corp"), FACTS)[0] is None  # A shop's name says nothing about who paid.
    assert suggest(row("income_record", name="Other Employer"), FACTS)[0] is None


def test_filing_follows_what_extraction_would_have_chosen():
    assert filing("receipt", {"merchant": "Costco", "purchase_date": "2026-09-10"}) == ("receipt", "Costco", "2026-09-10")
    assert filing("bill", {"provider": "City Power", "due_date": None, "issue_date": "2026-09-01"}) == ("bill", "City Power", "2026-09-01")
    assert filing("statement", {"statement_type": "credit_card", "institution": "Chase", "period_end": "2026-09-30"})[0] == "credit_card_statement"
    assert filing("statement", {"statement_type": "bank", "institution": "Chase", "period_end": "2026-09-30"})[0] == "bank_statement"
    assert filing("income_record", {"payer_or_employer": "Acme", "pay_date": "2026-09-15"}) == ("paystub", "Acme", "2026-09-15")


@pytest.fixture
def family(tmp_path):
    """A family's own library with one uploaded receipt, refreshed into an assignment."""
    store = Store(tmp_path / "family")
    inbox_scan(store, {"costco.png": b"family costco receipt"})
    receipt = costco(Ledger(store), documents_by_name(store)["costco.png"], card="1234", total=5001)
    routing = FamilyRouting(store)
    routing.refresh(FACTS)
    try:
        yield store, routing, receipt
    finally:
        store.close()


def test_assignments_are_validated(family):
    store, routing, receipt = family
    [listed] = routing.list()
    assert (listed["routing"], listed["suggested"]["member_id"], listed["shareable"]) == ("suggested", "mom", True)
    known = ["dad", "mom"]
    for mode, members, message in [("member", ["mom", "dad"], "the one person"), ("member", ["stranger"], "in the family"),
                                    ("shared", [], "at least one person"), ("elsewhere", ["mom"], "a person or Shared")]:
        with pytest.raises(ValueError, match=message):
            routing.assign("receipt", receipt, mode, members, known)
    with pytest.raises(ValueError, match="only receipts and bills"):
        routing.assign("statement", receipt, "shared", ["mom"], known)
    with pytest.raises(ValueError, match="no family assignment"):
        routing.assign("receipt", receipt + 100, "member", ["mom"], known)
    # Refreshing again never replaces an assignment or its suggestion.
    routing.refresh({})
    assert routing.get("receipt", receipt)["members"] == ["mom"]


def test_a_shared_record_is_divided_exactly_and_withdrawn_people_are_retracted(family):
    store, routing, receipt = family
    known = ["dad", "mom"]
    routing.assign("receipt", receipt, "shared", ["mom", "dad"], known)
    assignment, plan = routing.deliveries("receipt", receipt)
    assert assignment["members"] == ["dad", "mom"]  # In family order, whatever order they were chosen in.
    assert plan == [("dad", "record", 2501), ("mom", "record", 2500)]
    routing.mark_delivered("receipt", receipt, {"dad": "delivered", "mom": "delivered"})
    assert routing.pending() == []
    routing.assign("receipt", receipt, "member", ["mom"], known)
    assert routing.pending() == [("receipt", receipt)]
    assert routing.deliveries("receipt", receipt)[1] == [("mom", "record", None), ("dad", "retract", None)]


def test_a_delivery_applied_twice_updates_rather_than_duplicates(family, tmp_path):
    store, routing, receipt = family
    record, name, document = routing.payload("receipt", receipt)
    delivery = {"key": "family-key-1", "action": "record", "record_type": "receipt", "record": record, "name": name,
                "blob_hash": hashlib.sha256(document).hexdigest(), "share": 2500, "people": ["dad", "mom"]}
    person = Store(tmp_path / "person")
    try:
        first = apply_delivery(person, delivery, document)
        again = apply_delivery(person, delivery, document)
        assert first["record"] == again["record"]
        with person.connection() as db:
            assert db.execute("SELECT count(*) FROM receipts").fetchone()[0] == 1
            assert db.execute("SELECT count(*) FROM occurrences").fetchone()[0] == 1
            assert tuple(db.execute("SELECT share_minor,total_minor FROM record_shares").fetchone()) == (2500, 5001)
        september = PeriodInput(start="2026-09-01", end="2026-09-30")
        assert FinanceTools(person).get_spending(september)["by_currency"][0]["net_spending"]["minor"] == 2500
        assert_ledger_healthy(person)
        # A tampered document is refused; a retraction rejects the record so it stops counting.
        with pytest.raises(ValueError, match="does not match"):
            apply_delivery(person, {**delivery, "blob_hash": "0" * 64}, document)
        assert apply_delivery(person, {"key": "family-key-1", "action": "retract"}, b"")["record"] == first["record"]
        assert FinanceTools(person).get_spending(september)["by_currency"] == []
        assert_ledger_healthy(person)
    finally:
        person.close()
