"""Line corrections after a reading again (specs/pdf-table-engine-bills/test-contract.md SC-119, plan P9; FR-119, FR-121, FR-122).

A previous-version bill is made the way tests/test_bill_engine_record.py makes SC-121's: the version patched and the engine fault double, so the model's
lines are used, then the stored lines edited by SQL to what that reading left. The new reading is the real bill engine with the contract's stubs.
"""

from decimal import ROUND_HALF_UP, Decimal
import json

import bill_engine_fixtures as bf
from bill_kinds_fixtures import RENT, rent_replies, rent_row, water_row
from conftest import assert_ledger_healthy
from home_manager.documents import extraction
from home_manager.finance import bill_tables
from home_manager.finance.ledger import LINE_CORRECTIONS, Ledger
from test_bill_engine_record import (  # noqa: F401  (no_network is autouse: C-net)
    PHONE_FIELDS,
    UTIL_FIELDS,
    UTIL_WRONG_AMOUNTS,
    V39,
    BillRun,
    expect_util,
    finished,
    lines_of,
    model_rows,
    no_network,
    started,
)
from test_bill_kinds import read_bill
from test_bills_ledger import bill, line, open_books
from test_extraction import extract
from test_pdf import pdf_store  # noqa: F401
from test_reconcile_tools import source_of

MEMBERS = ["alex", "blair"]
ADVICE = "Check the bill's lines and make the change again on the right line."
PHONE_V39 = ("Unlimited Plan", "Basic Plan", "International Pack (Canada and Mexico)", "Autopay Discount")


def seed_v39(run, rows_of, fields, monkeypatch, classify):
    """What the previous version left: the engine fault double (the model's lines are used) with the version patched."""
    def fault(evidence, firsts=None):
        raise RuntimeError("injected engine fault")
    run.stub_bill({}, fields, extra=rows_of, single_run=True, classify=classify)
    with monkeypatch.context() as patch:
        patch.setattr(extraction, "EXTRACTION_VERSION", V39)
        patch.setattr(bill_tables, "read", fault)
        run.extract()
    assert run.run["status"] == "succeeded"
    with run.store.connection() as db:
        assert db.execute("SELECT prompt_version FROM extraction_runs WHERE id=?", (run.run["id"],)).fetchone()[0] == V39


def phone_v39(pdf_store, local_model, monkeypatch):
    """SC-119 Journey A's seed: BL-PHONE as the previous version read it (no Device Payment; position 3 misread 8.15), in To check."""
    run = started(pdf_store, local_model, bf.phone_pages())
    run.__class__ = BillRun
    seed_v39(run, [run.model_line(key, bf.STUB_PHONE[key]) for key in PHONE_V39], PHONE_FIELDS, monkeypatch, "METRO WIRELESS")
    receipt_id = run.run["publication"]["id"]
    with run.store.connection() as db:
        db.execute("UPDATE receipt_items SET line_total_minor=815 WHERE receipt_id=? AND position=3", (receipt_id,))
        db.execute("UPDATE receipts SET review_status='needs_review' WHERE id=?", (receipt_id,))
    assert [(item["description"], item["line_total_minor"]) for item in run.record["items"]] == [
        ("Unlimited Plan", 5500), ("Basic Plan", 3500), ("International Pack (Canada and Mexico)", 815), ("Autopay Discount", -500)]
    return run, receipt_id


def read_phone_again(run, force=False):
    """The new version's reading of BL-PHONE with STUB-PHONE."""
    run.stub_bill(bf.STUB_PHONE, PHONE_FIELDS, classify="METRO WIRELESS")
    return run.extract(force=force)


def stored(run, receipt_id):
    """The bill's lines as stored: (id, position, description, amount, member, member source, line holder)."""
    with run.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT id,position,description,line_total_minor,member_id,member_source,line_holder FROM receipt_items "
                                                 "WHERE receipt_id=? ORDER BY position", (receipt_id,))]


def kept(run, receipt_id):
    """The line corrections as kept: (field, value, previous) in the order they were made."""
    with run.store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT field,value,previous FROM record_corrections WHERE record_type='receipt_item' AND record_id=? "
                                                 "ORDER BY id", (receipt_id,))]


def correction_id(run, receipt_id, field):
    with run.store.connection() as db:
        return db.execute("SELECT max(id) FROM record_corrections WHERE record_type='receipt_item' AND record_id=? AND field=?", (receipt_id, field)).fetchone()[0]


def line_state(store, receipt_id):
    """The bill's remembered line amounts, held ids and undone undo rows (plan P9's storage)."""
    with store.connection() as db:
        details = json.loads(db.execute("SELECT details_json FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0])
    return details.get(LINE_CORRECTIONS)


def held_reasons(record):
    return [issue for issue in record["issues"] if "wasn't applied" in issue]


def only_reason(record, *facts):
    """C-reason: exactly one issue holds every fact, and the bill waits in To check."""
    assert len([issue for issue in record["issues"] if all(fact in issue for fact in facts)]) == 1, (facts, record["issues"])
    assert record["review_status"] == "needs_review"


def corrected_phone(run, receipt_id):
    """SC-119 Journey A step 1: member Blair on line 2, price 8.51 on line 3."""
    ledger = Ledger(run.store)
    ledger.correct_line(receipt_id, 2, "member", "blair", members=MEMBERS)
    ledger.correct_item(receipt_id, 3, "8.51")


def held_phone(pdf_store, local_model, monkeypatch):
    """Journey A through step 3: the corrected bill read again with the line the previous reading missed."""
    run, receipt_id = phone_v39(pdf_store, local_model, monkeypatch)
    before = stored(run, receipt_id)
    corrected_phone(run, receipt_id)
    previous_run = run.run["id"]
    read_phone_again(run)
    assert run.run["id"] != previous_run and run.run["status"] == "succeeded"  # `reused` False: the version moved
    return run, receipt_id, before


def assert_held_after_the_reading(run, receipt_id, before):
    """Journey A step 2 and step 3: the lines of EXP-PHONE, the member kept by identity, and the two held reasons."""
    record = run.record
    assert lines_of(record) == bf.EXP_PHONE_LINES
    unlimited, device, basic, intl, credit = stored(run, receipt_id)
    assert (device[4], device[5], device[6]) == (None, None, "Alex 555-201-1111")  # Device Payment: no member, its title's holder
    assert basic[0] == before[1][0] and (basic[4], basic[5]) == ("blair", "user")  # Basic Plan: the same receipt_items id, kept by identity
    assert [item[3] for item in (unlimited, device, basic, intl, credit)] == [5500, 2499, 3500, 851, -500]
    assert record["review_status"] == "needs_review"
    only_reason(record, "line 2", "wasn't applied", "24.99", "35.00")
    only_reason(record, "line 3", "wasn't applied", "35.00", "8.15")
    assert all(reason.endswith(ADVICE) for reason in held_reasons(record)) and len(record["issues"]) == 2, record["issues"]  # No other issue


def test_sc119_a_a_correction_made_on_a_line_that_shifted_is_held_and_one_made_on_a_line_that_stayed_goes_with_it(pdf_store, local_model, monkeypatch):
    """Journey A: BL-PHONE, steps 1 – 6."""
    run, receipt_id = phone_v39(pdf_store, local_model, monkeypatch)
    before = stored(run, receipt_id)
    ledger = Ledger(run.store)
    # 1. Two corrections, as they were always written (SC-119 step 1: nothing about the rows changes).
    corrected_phone(run, receipt_id)
    assert kept(run, receipt_id) == [("member:2", "blair", None), ("price:3", "8.51", "8.15")]
    assert [(item[3], item[4], item[5]) for item in stored(run, receipt_id)[1:3]] == [(3500, "blair", "user"), (851, None, None)]
    member_row, price_row = correction_id(run, receipt_id, "member:2"), correction_id(run, receipt_id, "price:3")
    assert line_state(run.store, receipt_id)["amounts"] == {str(member_row): 3500, str(price_row): 815}  # The amounts as read, before your price correction
    # 2. Extract again under the new version.
    read_phone_again(run)
    receipt_after = run.run["publication"]["id"]
    assert receipt_after == receipt_id
    # 3. Held.
    assert_held_after_the_reading(run, receipt_id, before)
    assert line_state(run.store, receipt_id)["held"] == [str(member_row), str(price_row)]
    # 4. Kept: both rows unchanged, still the latest of their fields, and History lists them.
    assert kept(run, receipt_id) == [("member:2", "blair", None), ("price:3", "8.51", "8.15")]
    history = {entry["field"]: entry for entry in ledger.history("receipt", receipt_id) if entry["kind"] == "correction"}
    assert history["member:2"]["id"] == member_row and history["member:2"]["undoable"] and history["price:3"]["id"] == price_row and history["price:3"]["undoable"]
    # 5. Extract again on the unchanged reading: the same two reasons, nothing applied, the same item ids (FR-122).
    first = stored(run, receipt_id)
    first_issues = run.record["issues"]
    read_phone_again(run, force=True)
    assert stored(run, receipt_id) == first and run.record["issues"] == first_issues
    assert_held_after_the_reading(run, receipt_id, before)
    # 6. Make the changes again on the right lines: they replace the held ones, and their reasons go.
    ledger.correct_item(receipt_id, 3, "35.00")
    assert held_reasons(ledger.record("receipt", receipt_id)) != [] and not [issue for issue in ledger.record("receipt", receipt_id)["issues"] if "line 3" in issue]
    ledger.correct_line(receipt_id, 2, "member", "alex", members=MEMBERS)
    assert held_reasons(ledger.record("receipt", receipt_id)) == []
    assert line_state(run.store, receipt_id)["held"] == []
    read_phone_again(run, force=True)
    record = run.record
    assert lines_of(record) == bf.EXP_PHONE_LINES and held_reasons(record) == []
    lines = stored(run, receipt_id)
    assert (lines[1][3], lines[1][4]) == (2499, "alex")  # Line 2 prints 24.99, the amount the member was set on.
    assert (lines[2][3], lines[2][4]) == (3500, "blair")  # Line 3 prints 35.00, the corrected price; Basic Plan keeps its member by identity.
    assert line_state(run.store, receipt_id)["held"] == []
    finished(run)


def test_sc119_a_undoing_a_held_correction_puts_nothing_back_and_extract_again_leaves_the_field_alone(pdf_store, local_model, monkeypatch):
    """Review pass 1, M4: Journey A, then undo the held price:3."""
    run, receipt_id, before = held_phone(pdf_store, local_model, monkeypatch)
    assert_held_after_the_reading(run, receipt_id, before)
    ledger = Ledger(run.store)
    lines = stored(run, receipt_id)
    price_row = correction_id(run, receipt_id, "price:3")
    record = ledger.undo_corrections("receipt", receipt_id, [price_row])
    assert stored(run, receipt_id) == lines  # Nothing was applied, so nothing is put back: Basic Plan stays 3500.
    assert [item["line_total_minor"] for item in record["items"]][2] == 3500
    assert [issue for issue in record["issues"] if "line 3" in issue] == []  # Its reason is gone; the other stays.
    only_reason(record, "line 2", "wasn't applied", "24.99", "35.00")
    undo_row = correction_id(run, receipt_id, "price:3")
    assert undo_row > price_row and kept(run, receipt_id)[-1] == ("price:3", "8.15", "8.51")  # The undo is written as for any correction.
    history = [entry for entry in ledger.history("receipt", receipt_id) if entry["kind"] == "correction" and entry["field"] == "price:3"]
    assert [entry["id"] for entry in history] == [undo_row, price_row] and history[0]["reason"] == "Undid a change"
    state = line_state(run.store, receipt_id)
    assert state["undone"] == [str(undo_row)] and state["held"] == [str(correction_id(run, receipt_id, "member:2"))]
    read_phone_again(run, force=True)  # Extract again changes nothing, now or on any later reading.
    assert [(item[1], item[3]) for item in stored(run, receipt_id)] == [(1, 5500), (2, 2499), (3, 3500), (4, 851), (5, -500)]
    record = run.record
    assert [issue for issue in record["issues"] if "line 3" in issue] == []
    only_reason(record, "line 2", "wasn't applied", "24.99", "35.00")
    read_phone_again(run, force=True)
    assert stored(run, receipt_id)[2][3] == 3500 and len(held_reasons(run.record)) == 1
    finished(run)


def test_sc119_variant_corrections_made_before_this_change_are_compared_with_the_amounts_the_previous_reading_stored(pdf_store, local_model, monkeypatch):
    """Variant "Made before this change": step 1's rows inserted as they always were, with no remembered amount."""
    run, receipt_id = phone_v39(pdf_store, local_model, monkeypatch)
    before = stored(run, receipt_id)
    with run.store.connection() as db:
        for field, value, previous in (("member:2", "blair", None), ("price:3", "8.51", "8.15")):
            db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,actor,created_at) "
                       "VALUES('receipt_item',?,?,?,?,'[]','test','2026-11-01T00:00:00+00:00')", (receipt_id, field, value, previous))
        db.execute("UPDATE receipt_items SET member_id='blair',member_source='user' WHERE receipt_id=? AND position=2", (receipt_id,))
        db.execute("UPDATE receipt_items SET line_total_minor=851 WHERE receipt_id=? AND position=3", (receipt_id,))
    assert line_state(run.store, receipt_id) is None
    read_phone_again(run)
    assert_held_after_the_reading(run, receipt_id, before)
    state = line_state(run.store, receipt_id)  # Found once from the old reading, then kept, so later readings agree (FR-122).
    assert sorted(state["amounts"].values()) == [815, 3500] and len(state["held"]) == 2
    first = stored(run, receipt_id)
    read_phone_again(run, force=True)
    assert stored(run, receipt_id) == first and line_state(run.store, receipt_id) == state
    assert_held_after_the_reading(run, receipt_id, before)
    finished(run)


def test_sc119_variant_a_bill_you_decided_is_never_written_and_nothing_is_held_on_it(pdf_store, local_model, monkeypatch):
    run, receipt_id = phone_v39(pdf_store, local_model, monkeypatch)
    corrected_phone(run, receipt_id)
    Ledger(run.store).review("receipt", receipt_id, "verified")

    def rows():
        with run.store.connection() as db:
            return ([tuple(row) for row in db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,))],
                    [tuple(row) for row in db.execute("SELECT * FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt_id,))])
    before = rows()
    read_phone_again(run)
    assert rows() == before
    assert held_reasons(run.record) == [] and run.record["review_status"] == "verified"
    finished(run)


# --- Journey B: nothing shifted -----------------------------------------------------------------------------------------------------

def test_sc119_b_a_price_the_engine_now_reads_exactly_and_a_member_on_an_unshifted_line_apply_with_no_reason(pdf_store, local_model, monkeypatch):
    """Journey B: BL-UTIL, State Tax misread 5.35 and corrected to 5.53, member Alex on Customer Charge."""
    from home_manager.documents.extraction import EXTRACTION_VERSION
    assert EXTRACTION_VERSION != V39
    run = started(pdf_store, local_model, bf.util_pages())
    run.__class__ = BillRun
    seed_v39(run, model_rows(run), {**UTIL_FIELDS, "amount_due": ("97.55", "97.55", "97.55"), "new_charges": ("97.55", "97.55", "97.55")}, monkeypatch, "CITY POWER & WATER")
    receipt_id = run.run["publication"]["id"]
    with run.store.connection() as db:
        db.execute("UPDATE receipt_items SET line_total_minor=535 WHERE receipt_id=? AND position=4", (receipt_id,))  # The misread
        db.execute("UPDATE receipts SET review_status='needs_review' WHERE id=?", (receipt_id,))
    assert [(item["description"], item["line_total_minor"]) for item in run.record["items"]] == [
        ("Energy Tier 1", 6000), ("Energy Tier 2", 2002), ("Customer Charge", 1200), ("State Tax", 535)]
    ledger = Ledger(run.store)
    ledger.correct_item(receipt_id, 4, "5.53")
    ledger.correct_line(receipt_id, 3, "member", "alex", members=MEMBERS)
    run.stub_bill(bf.STUB_UTIL_WRONG, {**UTIL_FIELDS, **UTIL_WRONG_AMOUNTS})
    run.extract()
    record = expect_util(run)  # EXP-UTIL: line 4 is 553 and C-auto
    assert record["items"][2]["member_id"] == "alex" and held_reasons(record) == []
    assert (line_state(run.store, receipt_id) or {}).get("held", []) == []
    finished(run)


# --- Journey C: a photographed rent bill (D15) --------------------------------------------------------------------------------------

def test_sc119_c_a_photographed_bill_holds_a_member_when_a_line_is_added_above_it_and_applies_it_when_it_is_back(tmp_path, local_model):
    with read_bill(tmp_path, local_model, RENT, rent_replies()) as (manager, _run, record, row):
        receipt_id = row["id"]
        assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("Rent", 145000), ("Water Usage", 3842)]
        manager.ledger.correct_line(receipt_id, 2, "member", "blair", members=MEMBERS)
        water_id = next(item["id"] for item in manager.ledger.record("receipt", receipt_id)["items"] if item["description"] == "Water Usage")
        doc = manager.store.documents()["items"][0]

        def read_again(lines, replies):
            local_model["output"] = {"full_text": "\n".join(lines)}
            manager.start_receipt(doc["id"], force=True)
            manager.future.result(timeout=30)
            parse_id = manager.receipts.history(doc["id"])[0]["id"]
            local_model["by_schema"] = replies
            run = extract(manager, doc, parse_id, force=True)
            assert run["status"] == "succeeded", run["error"]
            assert run["publication"]["id"] == receipt_id
            return manager.ledger.record("receipt", receipt_id)
        # 1. RENT with Pet Fee $25.00 between the Rent and Water lines.
        pet = [*RENT[:4], "Pet Fee $25.00", *RENT[4:6], "Amount Due......................................................... $1,513.42"]
        pet_row = rent_row("Pet Fee", "25.00", 5, pet, "other", "housing", None)
        replies = rent_replies(pet, [rent_row(lines=pet), pet_row, water_row(pet, line=6)],
                               amount_due={"value": "1,513.42", "status": "proposed", "evidence": [{"line_id": "line-8", "quote": pet[7]}]},
                               due_date={"value": "2026-10-01", "status": "proposed", "evidence": [{"line_id": "line-7", "quote": pet[6]}]})
        record = read_again(pet, replies)
        assert [(item["description"], item["line_total_minor"]) for item in record["items"]] == [("Rent", 145000), ("Pet Fee", 2500), ("Water Usage", 3842)]
        assert [item["member_id"] for item in record["items"]] == [None, None, "blair"]  # Water Usage keeps its member by identity.
        assert record["items"][2]["id"] == water_id
        only_reason(record, "line 2", "wasn't applied", "25.00", "38.42")
        # 2. The original RENT again: line 2 is Water Usage 38.42 again, so the member is applied and the reason goes.
        record = read_again(RENT, rent_replies())
        assert [(item["description"], item["line_total_minor"], item["member_id"]) for item in record["items"]] == [("Rent", 145000, None), ("Water Usage", 3842, "blair")]
        assert held_reasons(record) == []
        assert_ledger_healthy(manager.store)


# --- A receipt is unchanged ---------------------------------------------------------------------------------------------------------

def test_sc119_variant_a_receipts_price_correction_still_lands_on_its_position_with_no_reason(tmp_path):
    store, ledger, docs = open_books(tmp_path / "managed")
    try:
        def reading(items):
            return {"merchant": "Corner Market", "purchase_date": "2026-09-18", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                    "total_minor": sum(amount for _, amount in items), "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]},
                    "items": [{"description": name, "line_total_minor": amount, "locator": {"line_ids": ["line-2"]}} for name, amount in items]}
        source = source_of(docs["rent.png"], "extraction:rent.png")
        receipt_id = ledger.publish_receipt(reading([("Coffee", 300), ("Bagel", 450)]), source, "needs_review")["id"]
        ledger.correct_item(receipt_id, 2, "5.00")
        ledger.publish_receipt(reading([("Napkins", 50), ("Coffee", 300), ("Bagel", 450)]), {**source, "run_id": "again"}, "needs_review")
        with store.connection() as db:
            assert [tuple(row) for row in db.execute("SELECT position,description,line_total_minor FROM receipt_items WHERE receipt_id=? ORDER BY position",
                                                     (receipt_id,))] == [(1, "Napkins", 50), (2, "Coffee", 500), (3, "Bagel", 450)]
            assert db.execute("SELECT details_json FROM receipts WHERE id=?", (receipt_id,)).fetchone()[0] is None
        assert ledger.record("receipt", receipt_id)["issues"] == []
        assert_ledger_healthy(store)
    finally:
        store.close()


# --- G4: a correction made before this change, on a line that also has a price correction ----------------------------------------------

def test_sc119_g4_a_correction_made_before_this_change_is_compared_with_the_amount_before_the_price_correction(tmp_path):
    """Plan G4: with no remembered amount, a member set on a line whose price you corrected is compared with the amount that line printed before
    the price correction (the start of its unbroken price chain), not with the corrected price the line was stored with."""
    store, ledger, docs = open_books(tmp_path / "managed")
    try:
        def read(amount):
            lines = [line("Energy", 6000, "utilities", "usage"), line("State Tax", amount, "utilities", "tax_fee")]
            return bill(ledger, docs["phone.png"], "City Power", "2026-10-15", lines, status="needs_review")
        receipt_id = read(535)  # The previous reading misread the tax.
        with store.connection() as db:  # Made before this change, as always written: a price chain 5.35 -> 5.53, then a member, no remembered amount.
            for field, value, previous in (("price:2", "5.53", "5.35"), ("member:2", "blair", None)):
                db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,actor,created_at) "
                           "VALUES('receipt_item',?,?,?,?,'[]','test','2026-11-01T00:00:00+00:00')", (receipt_id, field, value, previous))
            db.execute("UPDATE receipt_items SET line_total_minor=553,member_id='blair',member_source='user' WHERE receipt_id=? AND position=2", (receipt_id,))
        # The new reading prints the tax right: the price correction fits (it prints exactly your price), the member is held: that line printed 5.35.
        assert read(553) == receipt_id
        record = ledger.record("receipt", receipt_id)
        only_reason(record, "line 2", "person: blair", "wasn't applied", "5.53", "5.35")
        assert len(held_reasons(record)) == 1 and [item["line_total_minor"] for item in record["items"]] == [6000, 553]
        assert_ledger_healthy(store)
    finally:
        store.close()


# --- Review round 1, finding 6 (SL-11): a fresh correction remembers the current reading's amount, not an earlier one's ---------------------------------

def caught_up_tax(tmp_path):
    """BL: the tax line misread 5.35, its price corrected to 5.53, then a reading that prints 5.53 itself (the reading caught up). Returns the books and a
    `read(amount)` that publishes a reading of the same bill."""
    store, ledger, docs = open_books(tmp_path / "managed")

    def read(amount):
        lines = [line("Energy", 6000, "utilities", "usage"), line("State Tax", amount, "utilities", "tax_fee")]
        return bill(ledger, docs["phone.png"], "City Power", "2026-10-15", lines, status="needs_review")
    receipt_id = read(535)
    ledger.correct_item(receipt_id, 2, "5.53")
    assert read(553) == receipt_id
    record = ledger.record("receipt", receipt_id)
    assert held_reasons(record) == [] and [item["line_total_minor"] for item in record["items"]] == [6000, 553]
    return store, ledger, receipt_id, read


def test_sl11_f6_a_code_set_after_the_reading_caught_up_with_the_price_correction_is_kept_on_an_unchanged_reread(tmp_path):
    store, ledger, receipt_id, read = caught_up_tax(tmp_path)
    try:
        ledger.correct_item_fields(receipt_id, 2, {"product_code": "TAX-CODE"})
        with store.connection() as db:
            code_row = db.execute("SELECT max(id) FROM record_corrections WHERE record_type='receipt_item' AND record_id=? AND field='product_code:2'",
                                  (receipt_id,)).fetchone()[0]
        assert line_state(store, receipt_id)["amounts"][str(code_row)] == 553  # The line as the current reading prints it, not the earlier 5.35.
        assert read(553) == receipt_id  # An unchanged reread.
        record = ledger.record("receipt", receipt_id)
        assert held_reasons(record) == [] and record["items"][1]["product_code"] == "TAX-CODE"
        assert line_state(store, receipt_id)["held"] == []
        assert_ledger_healthy(store)
    finally:
        store.close()


def test_sl11_f6_a_member_set_after_the_reading_caught_up_is_not_held_on_an_unchanged_reread(tmp_path):
    store, ledger, receipt_id, read = caught_up_tax(tmp_path)
    try:
        ledger.correct_line(receipt_id, 2, "member", "blair", members=MEMBERS)
        assert read(553) == receipt_id
        record = ledger.record("receipt", receipt_id)
        assert held_reasons(record) == [] and (record["items"][1]["member_id"], record["items"][1]["member_source"]) == ("blair", "user")
        assert_ledger_healthy(store)
    finally:
        store.close()


def test_sl11_f6_the_fresh_correction_is_held_for_a_shifted_line_that_happens_to_print_the_older_amount(tmp_path):
    store, ledger, receipt_id, read = caught_up_tax(tmp_path)
    try:
        ledger.correct_item_fields(receipt_id, 2, {"product_code": "TAX-CODE"})
        assert read(535) == receipt_id  # The line at position 2 now prints 5.35, the amount an earlier reading had: it is not the line the code was set on.
        record = ledger.record("receipt", receipt_id)
        only_reason(record, "line 2", "wasn't applied", "5.35", "5.53")
        assert record["items"][1]["product_code"] is None
        assert_ledger_healthy(store)
    finally:
        store.close()


# --- Review round 1, findings 8 and 9 (SL-11): one effective-rate rule for the shown rate and the product check -------------------------------------

def rate_books(tmp_path):
    """A kinded bill with a fee line and an energy line (position 2: 100 units), and `read(rate, line)` that publishes a reading of it whose energy line prints
    that rate (text, with its rounded cents) and that line total."""
    store, ledger, docs = open_books(tmp_path / "managed")

    def read(rate_text, line_minor):
        cents = int((Decimal(rate_text) * 100).quantize(Decimal(1), ROUND_HALF_UP))
        energy = {**line("Energy", line_minor, "utilities", "usage"), "quantity": "100", "unit_price_minor": cents,
                  "details": {"unit_price": {"text": rate_text, "locator": {"line_ids": ["line-2"]}}}}
        lines = [line("Fee", 500, "utilities"), energy]
        total = sum(item["line_total_minor"] for item in lines)
        return ledger.publish_bill({"provider": "City Power", "issue_date": None, "due_date": "2026-10-15", "period_start": None, "period_end": None,
                                    "amount_due_minor": total, "total_minor": total, "currency": "USD", "issues": [], "locator": {"line_ids": ["line-1"]},
                                    "items": lines, "category": None, "recurrence": "monthly", "last_four": None, "bill_kind": "general", "details": {}},
                                   source_of(docs["phone.png"], "extraction:" + docs["phone.png"]["relative_path"]), "needs_review")["id"]
    return store, ledger, read


def shown_and_checked(store, ledger, receipt_id):
    """(the rate the page shows for the energy line, the rate its product check is run with, the check's (computed, compared, passes))."""
    from home_manager.finance.document_traces import bill_checks
    shown = ledger.record("receipt", receipt_id)["items"][1]["display"]["unit_price_minor"]
    with store.connection() as db:
        row = db.execute("SELECT * FROM receipts WHERE id=?", (receipt_id,)).fetchone()
        [check] = [found for found in bill_checks(db, row) if found["name"] == "product:2"]
    quantity, rate, line_minor = check["args"]
    return shown, rate, check["check"](quantity, rate, line_minor, "USD")


def test_sl11_f8_f9_an_applied_unit_price_correction_shows_and_checks_the_corrected_rate(tmp_path):
    store, ledger, read = rate_books(tmp_path)
    try:
        receipt_id = read("0.1430", 1430)
        assert shown_and_checked(store, ledger, receipt_id)[:2] == ("0.1430", "0.1430")  # Nothing corrected: the exact printed rate, not 0.14.
        ledger.correct_item_fields(receipt_id, 2, {"unit_price": "0.15"})
        shown, rate, result = shown_and_checked(store, ledger, receipt_id)
        assert (shown, rate, result[:2]) == ("0.15 USD", "0.15", (1500, 1430))  # Applied: the correction wins in the display and in the check (100 x 0.15 = 15.00).
        assert_ledger_healthy(store)
    finally:
        store.close()


def test_sl11_f8_f9_a_held_unit_price_correction_shows_and_checks_the_current_printed_rate(tmp_path):
    store, ledger, read = rate_books(tmp_path)
    try:
        receipt_id = read("0.1430", 1430)
        ledger.correct_item_fields(receipt_id, 2, {"unit_price": "0.15"})
        assert read("0.1435", 1435) == receipt_id  # The line now prints 14.35 at 0.1435: the correction was made on 14.30, so it is held.
        only_reason(ledger.record("receipt", receipt_id), "line 2", "unit price: 0.15", "wasn't applied", "14.35", "14.30")
        shown, rate, passes = shown_and_checked(store, ledger, receipt_id)
        assert (shown, rate, passes) == ("0.1435", "0.1435", (1435, 1435, True))  # Not 0.14 USD, and the check runs on the rate the line prints (100 x 0.1435 = 14.35).
        assert_ledger_healthy(store)
    finally:
        store.close()


def test_sl11_f8_f9_a_unit_price_correction_undone_while_held_shows_and_checks_the_current_printed_rate(tmp_path):
    store, ledger, read = rate_books(tmp_path)
    try:
        receipt_id = read("0.1430", 1430)
        ledger.correct_item_fields(receipt_id, 2, {"unit_price": "0.15"})
        read("0.1435", 1435)
        with store.connection() as db:
            held = db.execute("SELECT max(id) FROM record_corrections WHERE record_type='receipt_item' AND record_id=? AND field='unit_price:2'",
                              (receipt_id,)).fetchone()[0]
        ledger.undo_corrections("receipt", receipt_id, [held])
        assert shown_and_checked(store, ledger, receipt_id)[:2] == ("0.1435", "0.1435")
        read("0.1435", 1435)  # An unchanged reading leaves the field alone.
        assert shown_and_checked(store, ledger, receipt_id)[:2] == ("0.1435", "0.1435")
        assert_ledger_healthy(store)
    finally:
        store.close()


def test_sl11_f8_f9_a_held_unit_price_correction_that_fits_again_is_applied_and_shows_and_checks_the_corrected_rate(tmp_path):
    store, ledger, read = rate_books(tmp_path)
    try:
        receipt_id = read("0.1430", 1430)
        ledger.correct_item_fields(receipt_id, 2, {"unit_price": "0.15"})
        read("0.1435", 1435)
        assert shown_and_checked(store, ledger, receipt_id)[:2] == ("0.1435", "0.1435")
        read("0.1430", 1430)  # Recovery: the line prints the amount the correction was made on again.
        record = ledger.record("receipt", receipt_id)
        assert held_reasons(record) == [] and shown_and_checked(store, ledger, receipt_id)[:2] == ("0.15 USD", "0.15")
        assert_ledger_healthy(store)
    finally:
        store.close()
