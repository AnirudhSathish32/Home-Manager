"""Several pay stubs in one file (specs/pdf-table-engine-paystubs, FR-80 – FR-84). This slice: how they are stored and listed
(SC-75 the segment migration, SC-73 step 4 the library row). Synthetic data only; no model, no network."""

import re
import sqlite3

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.library import storage
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import MIGRATIONS, MigrationError, Store
from test_reconcile_tools import add, source_of

PREVIOUS = 76  # 076_receipt_discounts.sql: the last schema before income records had a segment.
SEGMENT_STEP = 77
STUB_COLUMNS = ("id", "document_id", "blob_hash", "extraction_run_id", "payer_merchant_id", "pay_date", "period_start", "period_end",
                "gross_pay_minor", "net_pay_minor", "taxes_minor", "deductions_minor", "currency", "review_status", "validation_json",
                "review_source", "gross_pay_ytd_minor", "net_pay_ytd_minor", "work_state", "pay_frequency", "details_json")


def stub(employer, pay_date, gross, net, lines):
    """A pay stub as Record hands it to Ledger.publish_income: lines are (description, group, category, current, ytd)."""
    return {"payer_or_employer": employer, "pay_date": pay_date, "period_start": None, "period_end": None, "gross_pay_minor": gross,
            "net_pay_minor": net, "gross_pay_ytd_minor": gross * 10, "net_pay_ytd_minor": net * 10, "taxes_minor": gross - net,
            "deductions_minor": 0, "currency": "USD", "work_state": "NY", "pay_frequency": 26, "issues": [], "locator": {},
            "lines": [{"description": description, "line_group": group, "category": category, "current_minor": current, "ytd_minor": ytd,
                       "locator": {}} for description, group, category, current, ytd in lines]}


EARLIER = stub("SYNTH PAYROLL CO", "2026-06-05", 200000, 180000,
               [("Regular", "earnings", "regular_pay", 200000, 2000000), ("Federal tax", "tax", "federal_tax", 20000, 200000)])
LATER = stub("OTHER SYNTH CO", "2026-06-19", 210000, 190000,
             [("Regular", "earnings", "regular_pay", 210000, 2100000), ("Federal tax", "tax", "federal_tax", 20000, 200000)])


def segment_source(doc, segment, key="extraction:stubs"):
    return {**source_of(doc, f"{key}:{segment}"), "segment": segment}


def library_at_076(root):
    """A library whose income records were published by Ledger.publish_income, then put back to the schema of 076: the same
    rebuild 077 undoes (blob_hash unique on its own, no segment column), taken from the 076 script's own table text.
    Returns the ids of the two pay stubs' documents and the deposit's transaction."""
    store = Store(root)
    inbox_scan(store, {"first.png": b"synthetic first stub", "second.png": b"synthetic second stub"})
    docs = documents_by_name(store)
    ledger = Ledger(store)
    first = ledger.publish_income(EARLIER, source_of(docs["first.png"], "extraction:first"), "verified")
    second = ledger.publish_income(LATER, source_of(docs["second.png"], "extraction:second"), "needs_review")
    assert (first["id"], second["id"], first["lines"], second["lines"]) == (1, 2, 2, 2)
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    add(store, ledger, checking, docs["first.png"], [("2026-06-06", "SYNTH PAYROLL CO DIRDEP", 180000)])
    assert Reconciler(store).run()["income_links"] == 1  # transaction_income_links points at income_records(id)
    store.close()
    old = sqlite3.connect(":memory:")
    for number, script in MIGRATIONS:
        if number <= PREVIOUS:
            old.executescript(script.read_text())
    create = old.execute("SELECT sql FROM sqlite_schema WHERE name='income_records'").fetchone()[0]
    old.close()
    assert "segment" not in create
    db = sqlite3.connect(root / "inventory.sqlite3")  # Foreign keys are off on this connection: the rebuild keeps the lines.
    try:
        db.executescript(re.sub(r'^CREATE TABLE\s+"?income_records"?', "CREATE TABLE income_records_old", create) + ";\n"
                         f"INSERT INTO income_records_old({','.join(STUB_COLUMNS)}, created_at, updated_at) "
                         f"SELECT {','.join(STUB_COLUMNS)}, created_at, updated_at FROM income_records;\n"
                         "DROP TABLE income_records;\nALTER TABLE income_records_old RENAME TO income_records;\n"
                         f"PRAGMA user_version={PREVIOUS};")
    finally:
        db.close()
    return docs


def snapshot(root):
    """The income rows (without segment), their lines and links, as stored."""
    db = sqlite3.connect(root / "inventory.sqlite3")
    db.row_factory = sqlite3.Row
    try:
        return {"records": [tuple(row) for row in db.execute(f"SELECT {','.join(STUB_COLUMNS)},created_at,updated_at FROM income_records ORDER BY id")],
                "lines": [tuple(row) for row in db.execute("SELECT * FROM income_lines ORDER BY id")],
                "links": [tuple(row) for row in db.execute("SELECT * FROM transaction_income_links ORDER BY id")],
                "version": db.execute("PRAGMA user_version").fetchone()[0],
                "columns": [row[1] for row in db.execute("PRAGMA table_info(income_records)")],
                "unique": sorted(tuple(column[2] for column in db.execute(f"PRAGMA index_info({index[1]})"))
                                 for index in db.execute("PRAGMA index_list(income_records)") if index[2])}
    finally:
        db.close()


def test_sc75_the_segment_migration_keeps_every_record_id_value_and_line(tmp_path):
    """SC-75 step 1: both records keep their ids, every column value and their lines; each is segment 0; income_records
    is unique by file and segment (a second segment-0 row for the same file is refused)."""
    root = tmp_path / "managed"
    docs = library_at_076(root)
    before = snapshot(root)
    assert before["version"] == PREVIOUS and "segment" not in before["columns"] and before["unique"] == [("blob_hash",)]
    assert [(row[0], row[9], row[5]) for row in before["records"]] == [(1, 180000, "2026-06-05"), (2, 190000, "2026-06-19")]
    assert len(before["lines"]) == 4 and len(before["links"]) == 1
    store = Store(root)  # Start: the upgrade.
    try:
        with store.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == max(number for number, _ in MIGRATIONS) >= SEGMENT_STEP
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
            rows = db.execute("SELECT id,segment,blob_hash,net_pay_minor,pay_date FROM income_records ORDER BY id").fetchall()
            assert [(row["id"], row["segment"], row["net_pay_minor"], row["pay_date"]) for row in rows] == [
                (1, 0, 180000, "2026-06-05"), (2, 0, 190000, "2026-06-19")]
            first = rows[0]["blob_hash"]
            with pytest.raises(sqlite3.IntegrityError):  # A second segment 0 for the same file.
                db.execute("INSERT INTO income_records(document_id,blob_hash,segment,currency,review_status,created_at,updated_at) "
                           "VALUES(?,?,0,'USD','proposed','t','t')", (docs["first.png"]["id"], first))
            with pytest.raises(sqlite3.IntegrityError):  # Segments are 0 – 199.
                db.execute("INSERT INTO income_records(document_id,blob_hash,segment,currency,review_status,created_at,updated_at) "
                           "VALUES(?,?,200,'USD','proposed','t','t')", (docs["first.png"]["id"], first))
            # Another segment of the same file is what the column is for; it can hold lines and a link of its own.
            added = db.execute("INSERT INTO income_records(document_id,blob_hash,segment,currency,review_status,created_at,updated_at) "
                               "VALUES(?,?,1,'USD','proposed','t','t')", (docs["first.png"]["id"], first)).lastrowid
            assert added == 3
            db.rollback()
    finally:
        store.close()
    after = snapshot(root)
    assert after["columns"] == before["columns"][:3] + ["segment"] + before["columns"][3:]
    assert after["unique"] == [("blob_hash", "segment")]
    assert {key: after[key] for key in ("records", "lines", "links")} == {key: before[key] for key in ("records", "lines", "links")}


def test_sc75_a_failed_upgrade_leaves_the_old_schema_and_data_untouched(tmp_path, monkeypatch):
    """SC-75 failure variant: the upgrade made to fail midway (after the table was rebuilt) keeps the library as it was and
    says so (docs/documents.md "Schema upgrades and recovering from a failed one"); the next start, fixed, finishes it."""
    root = tmp_path / "managed"
    library_at_076(root)
    before = snapshot(root)
    real = dict(MIGRATIONS)[SEGMENT_STEP]
    broken = tmp_path / real.name
    broken.write_text(real.read_text().replace(f"PRAGMA user_version={SEGMENT_STEP};", f"THIS IS NOT SQL;\nPRAGMA user_version={SEGMENT_STEP};"))
    monkeypatch.setattr(storage, "MIGRATIONS", [(number, broken if number == SEGMENT_STEP else path) for number, path in MIGRATIONS])
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert (failure.value.number, failure.value.version) == (SEGMENT_STEP, PREVIOUS)
    assert snapshot(root) == before
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        assert "income_records_new" not in {row[0] for row in db.execute("SELECT name FROM sqlite_schema")}
    finally:
        db.close()
    monkeypatch.undo()
    Store(root).close()
    assert snapshot(root)["version"] == max(number for number, _ in MIGRATIONS) and "segment" in snapshot(root)["columns"]


@pytest.fixture
def two_stub_file(tmp_path):
    """A file whose two pay stubs are published directly through Ledger.publish_income as segments 0 and 1 (no split yet)."""
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        manager = app.state.manager
        inbox_scan(manager.store, {"stubs.pdf": b"synthetic file holding two pay stubs", "single.pdf": b"synthetic file holding one pay stub"})
        yield client, manager, documents_by_name(manager.store)


def test_library_row_of_a_file_with_two_pay_stubs_has_no_single_amount_and_the_earliest_date(two_stub_file):
    """SC-73 step 4 at the library row: no single amount, dated by the earliest pay date, filed under segment 0's employer.
    Here segment 0 is the later stub and segment 1 the earlier, published first, so neither insertion order, pay date nor
    employer name stands in for the segment."""
    client, manager, docs = two_stub_file
    ledger, document = manager.ledger, docs["stubs.pdf"]
    segment_one = ledger.publish_income(EARLIER, segment_source(document, 1), "needs_review")
    segment_zero = ledger.publish_income(LATER, segment_source(document, 0), "verified")
    assert segment_one["id"] != segment_zero["id"]
    again = ledger.publish_income(LATER, segment_source(document, 0), "verified")  # Read again: the same record.
    assert again["id"] == segment_zero["id"]
    with manager.store.connection() as db:
        assert [tuple(row) for row in db.execute("SELECT segment,pay_date,net_pay_minor FROM income_records WHERE blob_hash=? ORDER BY segment",
                                                 (document["current_hash"],))] == [(0, "2026-06-19", 190000), (1, "2026-06-05", 180000)]
    shown = client.get(f"/api/documents/{document['id']}").json()
    assert shown["ledger_amount"] is None and shown["ledger_amount_minor"] is None and shown["ledger_currency"] is None
    assert shown["document_date"] == "2026-06-05" and shown["pay_date"] == "2026-06-05"
    assert shown["merchant"] == "OTHER SYNTH CO"  # Segment 0's employer, not the earlier stub's.
    assert shown["ledger_status"] == "needs_review"  # The stub that still needs a look, as for split receipts.
    # A file with one pay stub is listed as before: its amount, date and employer.
    ledger.publish_income(EARLIER, source_of(docs["single.pdf"], "extraction:single"), "verified")
    one = client.get(f"/api/documents/{docs['single.pdf']['id']}").json()
    assert (one["ledger_amount_minor"], one["ledger_currency"], one["document_date"], one["merchant"], one["ledger_status"]) == (
        180000, "USD", "2026-06-05", "SYNTH PAYROLL CO", "verified")


def test_library_row_counts_only_pay_stubs_that_are_not_rejected(two_stub_file):
    """A segment a later reading no longer finds stops counting: the one left gives the file its amount again, and the
    reading that finds it again restores it (FR-83)."""
    client, manager, docs = two_stub_file
    ledger, document = manager.ledger, docs["stubs.pdf"]
    ledger.publish_income(EARLIER, segment_source(document, 0), "verified")
    ledger.publish_income(LATER, segment_source(document, 1), "verified")
    assert client.get(f"/api/documents/{document['id']}").json()["ledger_amount_minor"] is None
    assert ledger.retire_segments(document["current_hash"], [0]) == 1
    with manager.store.connection() as db:
        retired = db.execute("SELECT review_status,review_source,validation_json FROM income_records WHERE segment=1").fetchone()
    assert (retired["review_status"], retired["review_source"]) == ("rejected", "automatic")
    assert "The latest reading of this file no longer finds this pay stub; check how the file was split." in retired["validation_json"]
    shown = client.get(f"/api/documents/{document['id']}").json()
    assert (shown["ledger_amount_minor"], shown["document_date"], shown["merchant"]) == (180000, "2026-06-05", "SYNTH PAYROLL CO")
    assert ledger.publish_income(LATER, segment_source(document, 1), "verified")["status"] == "published"  # Found again: restored.
    assert client.get(f"/api/documents/{document['id']}").json()["ledger_amount_minor"] is None


def test_library_retiring_a_pay_stub_the_user_decided_keeps_their_decision_and_adds_the_note(two_stub_file):
    client, manager, docs = two_stub_file
    ledger, document = manager.ledger, docs["stubs.pdf"]
    ledger.publish_income(EARLIER, segment_source(document, 0), "verified")
    kept = ledger.publish_income(LATER, segment_source(document, 1), "needs_review")["id"]
    with manager.store.connection() as db:
        db.execute("UPDATE income_records SET review_status='verified',review_source='user' WHERE id=?", (kept,))
    assert ledger.retire_segments(document["current_hash"], [0]) == 1
    with manager.store.connection() as db:
        row = db.execute("SELECT review_status,review_source,validation_json FROM income_records WHERE id=?", (kept,)).fetchone()
    assert (row["review_status"], row["review_source"]) == ("verified", "user")
    assert row["validation_json"].count("no longer finds this pay stub") == 1
    ledger.retire_segments(document["current_hash"], [0])  # Again: the note is not doubled.
    with manager.store.connection() as db:
        assert db.execute("SELECT validation_json FROM income_records WHERE id=?", (kept,)).fetchone()[0].count("no longer finds this pay stub") == 1
