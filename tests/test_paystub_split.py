"""Several pay stubs in one file (specs/pdf-table-engine-paystubs, FR-80 – FR-85): how they are stored and listed (SC-75 the segment migration,
SC-73 step 4 the library row), found in a file and recorded one by one (SC-72, SC-73, SC-74, SC-75 step 2, SC-76, SC-66 for the three-stub file and the
contract's retry, duplicate and restart variants), the layout-review notes of a split file, the user's changed split as a guess (FR-74) and duplicate
stubs (FR-84, FR-85). Synthetic data only; the model is the contract's `local_model` double and no other network is reachable.

Expected values are the contract's literals (MINI(n) and MINI-C, tests/paystub_engine_fixtures.py), never what the code produced. For a split file
each model schema's list holds one answer per part in file order."""

from collections import Counter
import json
import re
import sqlite3
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.api import create_app
from home_manager.app.manager import Manager
from home_manager.core.jobs import Work
from home_manager.documents import extraction
from home_manager.documents.extraction import HEADERS, PAY_SPLIT_NOTE, VOID_NOTE, ExtractionService
from home_manager.documents.paystub_split import stub_parts
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.finance import paystub_tables
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, PeriodInput
from home_manager.library import storage
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import MIGRATIONS, MigrationError, Store
import paystub_engine_fixtures as pf
from test_extraction import MISSING, extract, transcribe
from test_paystub_engine_record import Run, auto, expect, no_feature_review, no_network, started  # noqa: F401 - no_network is the autouse C-net fixture
from test_pdf import make_pdf, pdf_store  # noqa: F401
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


# === Files holding several stubs: the doubles ===============================================================================

EMPLOYER = "SYNTH PAYROLL CO"
MINI_CLASSES = [("Regular", "earnings", "regular_pay", "Regular"), ("Federal Income Tax", "tax", "federal_income_tax", "Federal Income Tax")]
THREE = (("2026-06-05", 11), ("2026-06-19", 12), ("2026-07-03", 13))  # SC-72 (a): MINI(11), MINI(12), MINI(13)
CONFIRMED_NOTE = PAY_SPLIT_NOTE


def mini_page(top, date, n, ytd=True, extra=(), heading=True):
    """The items of one MINI stub, plus extra items; without its heading line when heading is False."""
    items = pf.mini_items(top, date, n, ytd)
    if not heading:
        items = [item for item in items if not (abs(item[1] - (top - 48)) < 0.01)]
    return [*items, *extra]


def mini_file(*stubs, ytd=True, extras=None):
    """One page per stub (MINI), each at T 780: stubs are (date, n); extras: {index: items} printed on that stub's page."""
    return [{"items": [*mini_page(780, date, n, ytd, (extras or {}).get(index, ())), pf.footer(pf.FOOTER, 60)]} for index, (date, n) in enumerate(stubs)]


class Stubs(Run):
    """A file of pay stubs, read by the real services, answered by the contract's `local_model` double with one answer per part in file order."""

    def parts(self):
        """The lines of each stub by the employer heading line each starts with (the test's own idea of the split, not the code under test's)."""
        lines = [line for line in self.lines if line.text.strip()]
        heads = [index for index, line in enumerate(lines) if line.text == EMPLOYER]
        return [lines[first:last] for first, last in zip(heads, [*heads[1:], len(lines)])]

    def answer(self, stubs, parts=None, ytd=True, classes=MINI_CLASSES, fail_summary_at=None):
        """The stubs' answers. stubs: (date, n) per part; parts: the lines of each part (default: split at the employer headings, one part for one stub)."""
        if parts is None:
            parts = self.parts() if len(stubs) > 1 else [[line for line in self.lines if line.text.strip()]]
        covered = {line_id for table in paystub_tables.read(self.evidence).adapted for line_id in [*(row.line_id for row in table.rows), *table.spans]}
        replies = {"Classification": [], "PaystubSummary": [], "PayRowClasses": [], "PayLines": []}
        for part, (date, n, *amounts) in zip(parts, stubs):
            gross, net = amounts or ("2,000.00", "1,800.00")

            def find(text, part=part):
                return next(line for line in part if line.text.startswith(text))

            def cite(text, quote=None, find=find):
                return [{"line_id": find(text).id, "quote": quote or find(text).text}]

            def value(text, label, cite=cite):
                return {"value": text, "status": "proposed", "evidence": cite(label, text)}
            fields = {name: MISSING for name in HEADERS["paystub"]}
            fields.update(payer_or_employer=value(EMPLOYER, EMPLOYER), pay_date=value(date, ("Pay date", "Statement date")), currency=value("USD", "Currency"),
                          gross_pay=value(gross, "Gross Pay"), net_pay=value(net, "Net Pay"), taxes=value("200.00", "Total Taxes"))
            if ytd:
                fields.update(gross_pay_ytd=value(f"{2000 * n:,}.00", "Gross Pay"), net_pay_ytd=value(f"{1800 * n:,}.00", "Net Pay"))
            replies["Classification"].append({"document_type": "paystub", "evidence": cite(EMPLOYER), "issuer": fields["payer_or_employer"],
                                              "document_date": fields["pay_date"]})
            replies["PaystubSummary"].append(fields)
            runs = []  # The part's runs of lines the engine covers with rows, and the runs it doesn't: each is one question.
            for line in part:
                if not runs or (line.id in covered) != runs[-1][0]:
                    runs.append([line.id in covered, []])
                runs[-1][1].append(line.id)
            rows = [{"description": description, "group": group, "category": category, "evidence": cite(label)} for description, group, category, label in classes]
            for engine, ids in runs:
                if engine:
                    replies["PayRowClasses"].append({"lines": [row for row in rows if row["evidence"][0]["line_id"] in ids]})
                else:
                    replies["PayLines"].append({"lines": []})
        if fail_summary_at is not None:
            replies["PaystubSummary"][fail_summary_at] = {"unexpected": "not a summary"}  # A model error: the run fails as runs fail today.
        replies["Classification"].insert(0, replies["Classification"][0])  # The file's own classification comes first.
        self.local_model["by_schema"] = replies
        self.before = len(self.local_model["requests"])
        return replies

    def records(self):
        """The income records of the file, by segment: (segment, id, Ledger record)."""
        with self.store.connection() as db:
            found = [(row["segment"], row["id"]) for row in db.execute("SELECT segment,id FROM income_records WHERE blob_hash=? ORDER BY segment",
                                                                         (self.service.get(self.parse_id)["blob_hash"],))]
        return [(segment, income_id, Ledger(self.store).record("income_record", income_id)) for segment, income_id in found]

    def stubs_read(self, count):
        """C-money, C-lines and the totals of MINI(n) per segment are checked by the caller; here the segments are 0 … count - 1."""
        records = self.records()
        assert [segment for segment, _, _ in records] == list(range(count))
        return [record for _, _, record in records]


def mini_expect(record, n, ytd=True):
    """MINI(n) expected: C-lines, gross and net (MINI-C has no year to date: expect the this-period figures only)."""
    wanted = pf.mini_expected(n)
    if ytd:
        expect(record, wanted["lines"], {"gross_pay_minor": 200000, "gross_pay_ytd_minor": wanted["gross"][1], "net_pay_minor": 180000,
                                         "net_pay_ytd_minor": wanted["net"][1]})
    else:
        expect(record, [(description, group, current, None) for description, group, current, _ in wanted["lines"]], {"gross_pay_minor": 200000, "net_pay_minor": 180000})


def started_stubs(pdf_store, local_model, pages, name="stubs.pdf"):
    run = started(pdf_store, local_model, pages, name)
    run.__class__ = Stubs
    return run


def segments_of(store, document_id):
    with store.connection() as db:
        return [tuple(row) for row in db.execute("SELECT ordinal,first_line_id,last_line_id,status,source FROM document_segments WHERE document_id=? ORDER BY ordinal",
                                                 (document_id,))]


# === SC-72: finding the stubs in a file =====================================================================================

def test_sc72a_three_stubs_one_per_page_give_three_records(pdf_store, local_model):
    run = started_stubs(pdf_store, local_model, mini_file(*THREE))
    run.answer(THREE)
    run.extract()
    records = run.stubs_read(3)
    for record, (date, n) in zip(records, THREE):
        assert record["pay_date"] == date
        mini_expect(record, n)
        auto(record)
        assert PAY_SPLIT_NOTE in record["details"]["notes"] and PAY_SPLIT_NOTE not in record["issues"]  # C-note
    # Every line of the file is in exactly one segment, which holds one stub's first and last line.
    segments = segments_of(run.store, run.doc["id"])
    lines = [line.id for line in run.lines if line.text.strip()]
    assert [segment[0] for segment in segments] == [0, 1, 2] and segments[0][1] == lines[0] and segments[-1][2] == lines[-1]
    for (_, _, last, _, _), (_, first, _, _, _) in zip(segments, segments[1:]):
        assert lines.index(first) == lines.index(last) + 1
    assert [row[4] for row in segments] == ["model"] * 3
    assert Counter(run.asked())["Classification"] == 4 and Counter(run.asked())["PaystubSummary"] == 3  # The engine and the split rule asked nothing.


def test_sc72b_one_stub_over_two_pages_repeating_its_heading_is_one_record(pdf_store, local_model):
    """MINI(13) with page 1 down to Gross Pay and page 2 repeating the heading lines before Federal Income Tax, Total Taxes and Net Pay."""
    items = pf.mini_items(780, "2026-07-03", 13)
    first = [item for item in items if item[1] >= 700]  # Down to Gross Pay (y 700).
    head = [item for item in items if item[1] >= 732]  # Employer, pay date, currency and the heading.
    rest = [(x, y + 32, text) for x, y, text in items if y < 700]  # Federal Income Tax (684), Total Taxes (668), Net Pay (652) move up to 716, 700, 684.
    pages = [{"items": [*first, pf.footer(pf.FOOTER, 60)]}, {"items": [*head, *rest, pf.footer(pf.FOOTER, 60)]}]
    run = started_stubs(pdf_store, local_model, pages)
    run.answer([("2026-07-03", 13)])
    run.extract()
    [record] = run.stubs_read(1)
    mini_expect(record, 13)
    auto(record)
    assert PAY_SPLIT_NOTE not in (record["details"] or {}).get("notes", []) and segments_of(run.store, run.doc["id"]) == []  # No split note, no segments.


def test_sc72c_two_stubs_on_one_page_give_two_records(pdf_store, local_model):
    page = {"items": [*pf.mini_items(780, "2026-06-05", 11), *pf.mini_items(560, "2026-06-19", 12), pf.footer(pf.FOOTER, 60)]}
    run = started_stubs(pdf_store, local_model, [page])
    run.answer(THREE[:2])
    run.extract()
    first, second = run.stubs_read(2)
    for record, (date, n) in zip((first, second), THREE[:2]):
        assert record["pay_date"] == date
        mini_expect(record, n)
        auto(record)
    segments = segments_of(run.store, run.doc["id"])
    lines = [line.id for line in run.lines if line.text.strip()]
    assert len(segments) == 2 and lines.index(segments[1][1]) == lines.index(segments[0][2]) + 1 and segments[0][1] == lines[0] and segments[1][2] == lines[-1]


def test_sc72d_a_scanned_file_of_two_stubs_is_split_from_its_transcribed_lines(tmp_path, local_model):
    """A PNG whose vision stub transcribes MINI(11) then MINI(12) as lines: two records on the flat path, the values from the model stubs."""
    def stub_lines(date, n):
        return [EMPLOYER, f"Pay date {date}", "Currency USD", "Description Current YTD", f"Regular 2,000.00 {2000 * n:,}.00", f"Gross Pay 2,000.00 {2000 * n:,}.00",
                f"Federal Income Tax 200.00 {200 * n:,}.00", f"Total Taxes 200.00 {200 * n:,}.00", f"Net Pay 1,800.00 {1800 * n:,}.00"]
    lines = [*stub_lines(*THREE[0]), *stub_lines(*THREE[1])]
    manager, doc, parse_id = transcribe(tmp_path, local_model, lines)
    try:
        def cite(number, quote=None):
            return [{"line_id": f"line-{number}", "quote": quote or lines[number - 1]}]

        def value(text, number):
            return {"value": text, "status": "proposed", "evidence": cite(number, text)}
        replies = {"Classification": [], "PaystubSummary": [], "PayLines": []}
        for base, (date, n) in ((1, THREE[0]), (10, THREE[1])):
            fields = {name: MISSING for name in HEADERS["paystub"]}
            fields.update(payer_or_employer=value(EMPLOYER, base), pay_date=value(date, base + 1), currency=value("USD", base + 2),
                          gross_pay=value("2,000.00", base + 5), gross_pay_ytd=value(f"{2000 * n:,}.00", base + 5), net_pay=value("1,800.00", base + 8),
                          net_pay_ytd=value(f"{1800 * n:,}.00", base + 8), taxes=value("200.00", base + 7))
            replies["Classification"].append({"document_type": "paystub", "evidence": cite(base), "issuer": fields["payer_or_employer"], "document_date": fields["pay_date"]})
            replies["PaystubSummary"].append(fields)
            replies["PayLines"].append({"lines": [
                {"description": "Regular", "group": "earnings", "category": "regular_pay", "current": "2,000.00", "ytd": f"{2000 * n:,}.00", "evidence": cite(base + 4)},
                {"description": "Federal Income Tax", "group": "tax", "category": "federal_income_tax", "current": "200.00", "ytd": f"{200 * n:,}.00",
                 "evidence": cite(base + 6)}]})
        replies["Classification"].insert(0, replies["Classification"][0])
        local_model["by_schema"] = replies
        run = extract(manager, doc, parse_id)
        assert run["status"] == "succeeded", run["error"]
        with manager.store.connection() as db:
            found = [dict(row) for row in db.execute("SELECT segment,pay_date,net_pay_minor,currency FROM income_records ORDER BY segment")]
        assert [(row["segment"], row["pay_date"], row["net_pay_minor"]) for row in found] == [(0, "2026-06-05", 180000), (1, "2026-06-19", 180000)]
        assert [(row["first_line_id"], row["last_line_id"]) for row in manager.extractions.split(doc["id"])["segments"]] == [("line-1", "line-9"), ("line-10", "line-18")]
    finally:
        manager.close()


def snapshot_of(run):
    """Every income record, line, evidence link and segment, without what names the run or the clock (a segment keeps no id of its own across runs)."""
    drop = {"created_at", "updated_at", "extraction_run_id", "source_key", "run_id"}
    with run.store.connection() as db:
        found = {table: [{key: value for key, value in dict(row).items() if key not in drop | ({"id"} if table == "document_segments" else set())}
                         for row in db.execute(f"SELECT * FROM {table} ORDER BY id")] for table in ("income_records", "income_lines", "document_segments")}
        found["evidence"] = sorted({(row["record_type"], row["record_id"], row["document_id"], row["locator_json"]) for row in db.execute("SELECT * FROM financial_evidence_links")})
    return found


def three_stub_run(pdf_store, local_model, **options):
    run = started_stubs(pdf_store, local_model, mini_file(*THREE, **options))
    run.answer(THREE)
    return run


# === SC-73: 26 stubs and their deposits =====================================================================================

PAY_DATES = ["2025-11-07", "2025-11-21", "2025-12-05", "2025-12-19", "2026-01-02", "2026-01-16", "2026-01-30", "2026-02-13", "2026-02-27", "2026-03-13",
             "2026-03-27", "2026-04-10", "2026-04-24", "2026-05-08", "2026-05-22", "2026-06-05", "2026-06-19", "2026-07-03", "2026-07-17", "2026-07-31",
             "2026-08-14", "2026-08-28", "2026-09-11", "2026-09-25", "2026-10-09", "2026-10-23"]


def test_sc73_twenty_six_stubs_each_link_to_their_own_deposit_and_count_once(pdf_store, local_model):
    """The 26 deposits are inserted with Ledger.insert_transactions through tests/test_reconcile_tools.add (the smallest direct path)."""
    stubs = [(date, 1) for date in PAY_DATES]
    run = started_stubs(pdf_store, local_model, mini_file(*stubs, ytd=False))
    ledger = Ledger(run.store)
    inbox_scan(run.store, {"deposits.csv": b"synthetic deposits"})
    checking = ledger.create_account("First Local Bank", "checking", "USD")
    deposits = add(run.store, ledger, checking, documents_by_name(run.store)["deposits.csv"], [(date, f"{EMPLOYER} DIRDEP", 180000) for date in PAY_DATES])
    assert len(deposits) == 26
    run.answer(stubs, ytd=False)
    published = run.extract()["publication"]["segments"]
    assert len(published) == 26
    # Step 1: 26 records, segments 0 – 25, each with its pay date, gross 200000 and net 180000.
    records = run.stubs_read(26)
    assert [record["pay_date"] for record in records] == PAY_DATES
    for record in records:
        mini_expect(record, 1, ytd=False)
        auto(record)
    # Step 2: each record has one proposed link to the deposit on its own pay date; 26 links to 26 distinct transactions.
    assert Reconciler(run.store).run()["income_links"] == 26
    with run.store.connection() as db:
        links = [tuple(row) for row in db.execute(
            "SELECT i.pay_date,t.posted_date,t.amount_minor,l.review_status FROM transaction_income_links l JOIN income_records i ON i.id=l.income_record_id "
            "JOIN transactions t ON t.id=l.transaction_id ORDER BY i.segment")]
        assert len(db.execute("SELECT DISTINCT transaction_id FROM transaction_income_links").fetchall()) == 26
    assert links == [(date, date, 180000, "proposed") for date in PAY_DATES]
    # Step 3: money in is the 26 deposits once, and no pay stub besides.
    flow = FinanceTools(run.store).calculate_cashflow(PeriodInput(start="2025-11-01", end="2026-10-31"))["by_currency"]
    assert [(row["currency"], row["inflow"]["minor"]) for row in flow] == [("USD", 4680000)]
    # Step 4: the library shows the file with no single amount, dated by the earliest stub, filed under the first stub's employer and pay date.
    shown = run.store.document(run.doc["id"])
    assert shown["ledger_amount"] is None and shown["ledger_amount_minor"] is None and shown["document_date"] == "2025-11-07" and shown["merchant"] == EMPLOYER
    assert run.extraction.filing_identity(run.run) == ("paystub", EMPLOYER, "2025-11-07", None)


# === SC-74: the split needs no review, and can be changed ====================================================================

def starts_of(store, document_id):
    return [first for _, first, _, _, _ in segments_of(store, document_id)]


def test_sc74_the_split_needs_no_review_and_the_users_change_wins(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    before = run.fingerprint()
    run.extract()
    # Step 1: each record carries the split note, none waits in review for the split, three segments, not confirmed.
    for record in run.stubs_read(3):
        assert PAY_SPLIT_NOTE in record["details"]["notes"] and PAY_SPLIT_NOTE not in record["issues"]  # C-note
        auto(record)
    for segment, _, _ in run.records():
        assert PAY_SPLIT_NOTE in run.run["result"]["segments"][segment]["normalized"]["notes"]
    shown = run.extraction.split(run.doc["id"])
    assert shown["confirmed"] is False and [row["status"] for row in shown["segments"]] == ["proposed"] * 3
    assert [(row["kind"], row["employer"], row["pay_date"], row["display"]) for row in shown["segments"]] == [
        ("paystub", EMPLOYER, date, {"net_pay": "1,800.00 USD"}) for date, _ in THREE]
    assert all(row["income_record_id"] and row["receipt_id"] is None for row in shown["segments"])
    starts = starts_of(run.store, run.doc["id"])
    # Step 3: Merge with next on stub 2 (the first two stubs' first lines); segment 0 is still MINI(11).
    run.extraction.set_split(run.doc["id"], starts[:2])
    run.answer(THREE[:2], parts=[run.parts()[0], run.parts()[1] + run.parts()[2]])
    run.extract(force=True)
    records = [record for segment, _, record in run.records() if record["review_status"] != "rejected"]
    assert len(records) == 2
    mini_expect(records[0], 11)
    assert [[guess["kind"] for guess in record["details"]["guesses"]].count("split_changed") for record in records] == [1, 1]  # FR-74: the user's change.
    assert run.records()[2][2]["review_status"] == "rejected"  # The third segment is no longer found: it stops counting.
    assert [(row[0], row[1], row[3], row[4]) for row in segments_of(run.store, run.doc["id"])] == [(0, starts[0], "confirmed", "user"), (1, starts[1], "confirmed", "user")]
    # Step 4: Extract again still has two segments: the user's split wins.
    run.answer(THREE[:2], parts=[run.parts()[0], run.parts()[1] + run.parts()[2]])
    run.extract(force=True)
    assert [row[0] for row in segments_of(run.store, run.doc["id"])] == [0, 1] and len(run.run["publication"]["segments"]) == 2
    # Step 5: Confirm split leaves both records without the note.
    assert run.extraction.confirm_split(run.doc["id"])["confirmed"] is True
    for record in (run.records()[0][2], run.records()[1][2]):
        assert PAY_SPLIT_NOTE not in (record["details"].get("notes") or [])
    assert run.fingerprint() == before  # C-docs


def test_sc74_confirm_split_drops_the_note_without_changing_any_status(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    run.extract()
    with run.store.connection() as db:
        db.execute("UPDATE income_records SET review_status='verified',review_source='user' WHERE segment=1")  # The user decided stub 2.
    before = [(record["review_status"], record["issues"]) for _, _, record in run.records()]
    assert all(PAY_SPLIT_NOTE in record["details"]["notes"] for _, _, record in run.records())
    run.extraction.confirm_split(run.doc["id"])
    after = run.records()
    assert [(record["review_status"], record["issues"]) for _, _, record in after] == before
    assert all(PAY_SPLIT_NOTE not in (record["details"].get("notes") or []) for _, _, record in after)
    assert {status for _, _, _, status, _ in segments_of(run.store, run.doc["id"])} == {"confirmed"}
    run.answer(THREE)
    run.extract(force=True)  # Reading it again finds the same, now confirmed, split: no note comes back.
    assert all(PAY_SPLIT_NOTE not in (record["details"].get("notes") or []) for _, _, record in run.records())


# === SC-75 step 2: the same three records both times =========================================================================

def test_sc75_extracting_a_three_stub_file_twice_gives_the_same_three_records(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    run.extract()
    first = [(segment, income_id) for segment, income_id, _ in run.records()]
    run.answer(THREE)
    run.extract(force=True)
    assert [(segment, income_id) for segment, income_id, _ in run.records()] == first and len(first) == 3
    with run.store.connection() as db:
        assert db.execute("SELECT count(*) FROM income_records").fetchone()[0] == 3


# === SC-76: a void stub =====================================================================================================

def test_sc76_a_void_stub_is_recorded_with_a_note_and_adds_nothing_to_money_in(pdf_store, local_model):
    run = started_stubs(pdf_store, local_model, mini_file(*THREE, extras={1: [(40, 744, "VOID")]}))
    run.answer(THREE)
    run.extract()
    first, second, third = run.stubs_read(3)
    assert [first["review_status"], third["review_status"]] == ["verified", "verified"]
    assert VOID_NOTE in second["details"]["notes"] and VOID_NOTE not in second["issues"]
    assert (second["review_status"], second["review_source"]) == ("rejected", "automatic")
    assert second["pay_date"] == "2026-06-19" and second["net_pay_minor"] == 180000  # Recorded with its lines; it just doesn't count.
    mini_expect(first, 11)
    mini_expect(third, 13)
    flow = FinanceTools(run.store).calculate_cashflow(PeriodInput(start="2026-06-01", end="2026-07-31"))["by_currency"]
    assert [row["inflow"]["minor"] for row in flow] == [360000]
    run.answer(THREE)
    run.extract(force=True)  # Extract again: the same.
    assert [record["review_status"] for record in run.stubs_read(3)] == ["verified", "rejected", "verified"]


def test_void_is_a_line_of_its_own_not_a_word():
    for line in ("VOID", "void", "*** VOID ***", "- Void -", "  VOID  "):
        assert extraction.VOID_LINE.fullmatch(line.strip()), line
    for line in ("Void after 90 days", "This check is void if altered", "AVOID", "VOID 2,000.00"):
        assert not extraction.VOID_LINE.fullmatch(line.strip()), line


def test_a_void_stub_the_user_decided_is_left_alone(pdf_store, local_model):
    run = started_stubs(pdf_store, local_model, mini_file(*THREE, extras={1: [(40, 744, "VOID")]}))
    run.answer(THREE)
    run.extract()
    with run.store.connection() as db:
        db.execute("UPDATE income_records SET review_status='verified',review_source='user' WHERE segment=1")
    run.answer(THREE)
    run.extract(force=True)
    kept = run.stubs_read(3)[1]
    assert (kept["review_status"], kept["review_source"]) == ("verified", "user")


# === SC-66 for the three-stub file ===========================================================================================

def test_sc66_extract_again_on_the_three_stub_file_changes_nothing(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    run.extract()
    first, records = snapshot_of(run), [(record["issues"], record["details"]) for record in run.stubs_read(3)]
    engine = [json.dumps(paystub_tables.read(run.evidence), default=str, sort_keys=True) for _ in range(2)]
    assert engine[0] == engine[1]
    assert [stub_parts([line for line in run.lines if line.text.strip()]) for _ in range(2)][0] == stub_parts([line for line in run.lines if line.text.strip()])
    run.answer(THREE)
    run.extract(force=True)
    assert snapshot_of(run) == first
    assert [(record["issues"], record["details"]) for record in run.stubs_read(3)] == records
    assert Counter(run.asked()) == Counter({"Classification": 4, "PaystubSummary": 3, "PayRowClasses": 3, "PayLines": Counter(run.asked())["PayLines"]})  # C-model-calls


# === The rule on lines alone (FR-80) ========================================================================================

def lines_of_pages(*pages):
    return [SimpleNamespace(id=f"page-{number}-layout-line-{index}", text=text) for number, texts in enumerate(pages, 1) for index, text in enumerate(texts, 1)]


def printed(date, label="Pay date"):
    return ["SYNTH PAYROLL CO", "Earnings Statement", f"{label} {date}", "Description | Current | YTD", "Regular | 2,000.00 | 2,000.00", "Net Pay | 1,800.00 | 1,800.00"]


def test_stub_parts_splits_where_a_stub_starts_after_the_open_stub_printed_its_net_pay():
    lines = lines_of_pages(printed("2026-06-05"), printed("2026-06-19"), printed("2026-07-03"))
    assert stub_parts(lines) == [(0, 6), (6, 12), (12, 18)]  # Each stub's heading lines come with it.
    assert stub_parts(lines[:6]) == [(0, 6)] and stub_parts([]) == [(0, 0)]


def test_stub_parts_reads_a_stubs_pay_period_and_second_page_as_part_of_it():
    both = [*printed("2026-07-03"), "Pay period 2026-06-15 to 2026-06-28"]
    again = ["SYNTH PAYROLL CO", "Pay date 2026-07-03", "Federal Income Tax | 200.00 | 200.00"]
    lines = lines_of_pages(both[:3] + both[6:] + both[3:6], again)  # Pay date and Pay period before the net pay: one stub; its second page repeats the heading.
    assert stub_parts(lines) == [(0, len(lines))]


def test_stub_parts_joins_a_part_without_a_net_pay_to_the_stub_before():
    lines = lines_of_pages(printed("2026-06-05"), printed("2026-06-19")[:5] + ["Memo | 5.00 | 5.00"], printed("2026-07-03"))
    # The second stub printed no net pay line, so the third pay date line continues it instead of opening a stub.
    assert stub_parts(lines) == [(0, 6)] + [(6, 18)]


def test_stub_parts_moves_a_start_up_over_its_heading_lines_on_the_same_page_only():
    page = ["SYNTH PAYROLL CO", "Earnings Statement", "Pay date 2026-06-05", "Net Pay | 1,800.00 | 1,800.00", "Remarks go here",
            "SYNTH PAYROLL CO", "123 Main Street", "Earnings Statement", "Pay date 2026-06-19", "Net Pay | 1,900.00 | 1,900.00"]
    assert stub_parts(lines_of_pages(page)) == [(0, 4), (4, 10)]  # "Remarks go here" has no amount and sits after the first net pay: it goes with stub 2.
    far = ["SYNTH PAYROLL CO", "Pay date 2026-06-05", "Net Pay | 1,800.00 | 1,800.00", *[f"Note {number}" for number in range(6)], "Pay date 2026-06-19", "Net Pay 1,900.00"]
    assert stub_parts(lines_of_pages(far)) == [(0, 5), (5, 11)]  # At most four lines above the start.
    footer = ["SYNTH PAYROLL CO", "Pay date 2026-06-05", "Net Pay | 1,800.00 | 1,800.00", "This pay statement is for your records."]
    assert stub_parts(lines_of_pages(footer, ["SYNTH PAYROLL CO", "Pay date 2026-06-19", "Net Pay | 1,900.00 | 1,900.00"])) == [(0, 4), (4, 7)]  # Never the previous page's footer.
    amount = ["SYNTH PAYROLL CO", "Pay date 2026-06-05", "Net Pay | 1,800.00 | 1,800.00", "Ref 55.00", "Pay date 2026-06-19", "Net Pay | 1,900.00 | 1,900.00"]
    assert stub_parts(lines_of_pages(amount)) == [(0, 4), (4, 6)]  # A line holding an amount stays with the stub above.


def test_stub_parts_reads_every_start_label_and_a_label_without_a_date_is_no_start():
    for label in ("Check date", "Payment date", "Pay period", "Period ending", "Pay Date:"):
        lines = lines_of_pages(printed("2026-06-05", label), printed("2026-06-19", label))
        assert len(stub_parts(lines)) == 2, label
    lines = lines_of_pages(printed("2026-06-05"), ["SYNTH PAYROLL CO", "Pay date to be announced", "Net Pay | 1,800.00 | 1,800.00"])
    assert stub_parts(lines) == [(0, 9)]


# === The two layout-review cases (plan P7.1a, review pass 2 MAJOR-1 and pass 3 MINOR-A) ==============================================

def test_a_headerless_table_on_page_two_sends_neither_stub_to_review(pdf_store, local_model):
    pages = [{"items": [*mini_page(780, "2026-06-05", 11), pf.footer(pf.FOOTER, 60)]},
             {"items": [*mini_page(780, "2026-06-19", 12, heading=False), pf.footer(pf.FOOTER, 60)]}]
    run = started_stubs(pdf_store, local_model, pages)
    assert run.evidence.pages[0].layout.issues == [] and run.evidence.pages[1].layout.issues == ["unresolved_columns"]  # P-check
    run.answer(THREE[:2])
    run.extract()
    first, second = run.stubs_read(2)
    for record, (_, n) in zip((first, second), THREE[:2]):
        mini_expect(record, n)
        auto(record)  # The pay engine read the table the layout reader couldn't: its review message is no reason.


def test_page_two_also_carrying_overlapping_text_sends_only_stub_two_to_review(pdf_store, local_model):
    pages = [{"items": [*mini_page(780, "2026-06-05", 11), pf.footer(pf.FOOTER, 60)]},
             {"items": [*mini_page(780, "2026-06-19", 12, extra=[(300, 400, "STAMPED"), (300, 400, "OVERLAID")], heading=False), pf.footer(pf.FOOTER, 60)]}]
    run = started_stubs(pdf_store, local_model, pages)
    assert "overlapping_text" in run.evidence.pages[1].layout.issues and "unresolved_columns" in run.evidence.pages[1].layout.issues  # P-check
    assert run.evidence.pages[0].layout.issues == []
    run.answer(THREE[:2])
    run.extract()
    first, second = run.stubs_read(2)
    mini_expect(first, 11)
    auto(first)  # Page 2's problem is not stub 1's.
    assert second["review_status"] == "needs_review" and any(issue.startswith("Page 2") for issue in second["issues"]), second["issues"]
    assert not [issue for issue in second["issues"] if issue.startswith("Page 1")]


# === FR-74: a split the user changes is a guess =============================================================================

def test_a_one_stub_file_the_user_splits_in_two_gets_a_split_changed_guess_on_each(pdf_store, local_model):
    """The rule reads two stubs as one when the second prints "Statement date" (no start label); the user's Split here makes two."""
    items = [(x, y, "Statement date 2026-06-19" if text == "Pay date 2026-06-19" else text) for x, y, text in
             [*pf.mini_items(780, "2026-06-05", 11), *pf.mini_items(560, "2026-06-19", 12)]]
    run = started_stubs(pdf_store, local_model, [{"items": [*items, pf.footer(pf.FOOTER, 60)]}])
    run.answer([("2026-06-05", 11)])
    run.extract()
    assert len(run.records()) == 1 and "split_changed" not in str(run.records()[0][2]["details"]) and segments_of(run.store, run.doc["id"]) == []
    heads = [line.id for line in run.lines if line.text == EMPLOYER]
    run.extraction.set_split(run.doc["id"], heads)
    with run.store.connection() as db:  # The user's rows carry the run they replaced, which is the latest reading's.
        assert {row[0] for row in db.execute("SELECT extraction_run_id FROM document_segments")} == {run.run["id"]}
    run.answer([("2026-06-05", 11), ("2026-06-19", 12)], parts=run.parts())
    run.extract(force=True)
    first, second = run.stubs_read(2)
    for record in (first, second):
        assert [guess["kind"] for guess in record["details"]["guesses"]] == ["split_changed"]
        assert PAY_SPLIT_NOTE not in (record["details"].get("notes") or [])  # The user's own split is confirmed: no split note.
    mini_expect(first, 11)
    mini_expect(second, 12)
    run.answer([("2026-06-05", 11), ("2026-06-19", 12)], parts=run.parts())
    run.extract(force=True)  # Extract again: still one guess each.
    assert [[guess["kind"] for guess in record["details"]["guesses"]] for record in run.stubs_read(2)] == [["split_changed"]] * 2


def test_confirming_the_rules_own_split_is_not_a_change(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    run.extract()
    run.extraction.set_split(run.doc["id"], starts_of(run.store, run.doc["id"]))  # The same starts.
    run.answer(THREE)
    run.extract(force=True)
    assert all("guesses" not in (record["details"] or {}) for record in run.stubs_read(3))


# === The failure, retry, duplicate-capture and restart variants =============================================================

def test_a_failed_run_publishes_nothing_and_extract_again_gives_exactly_three_records(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    run.answer(THREE, fail_summary_at=1)
    run_id, _ = run.extraction.enqueue(run.doc["id"], run.parse_id, ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning"))
    run.extraction.run(run_id, Work.detached())
    assert run.extraction.get(run_id)["status"] == "failed"
    assert run.records() == [] and segments_of(run.store, run.doc["id"]) == []
    run.answer(THREE)
    run.extract()
    assert [segment for segment, _, _ in run.records()] == [0, 1, 2]
    with run.store.connection() as db:
        assert db.execute("SELECT count(*) FROM income_records").fetchone()[0] == 3 and len(segments_of(run.store, run.doc["id"])) == 3


def test_the_file_dropped_twice_is_one_file_with_the_same_three_records(pdf_store, local_model):
    inbox, store = pdf_store
    run = three_stub_run(pdf_store, local_model)
    run.extract()
    first = [(segment, income_id) for segment, income_id, _ in run.records()]
    (inbox / "again.pdf").write_bytes(store.blob_path(run.service.get(run.parse_id)["blob_hash"]).read_bytes())
    inbox_scan(store)
    names = {item["relative_path"]: item for item in store.documents()["items"]}
    assert set(names) == {"stubs.pdf", "again.pdf"} and names["again.pdf"]["current_hash"] == names["stubs.pdf"]["current_hash"]  # One file's bytes, twice.
    assert [link["relative_path"] for link in store.linked_documents(names["again.pdf"]["id"])] == ["stubs.pdf"]  # The visible duplicate link, as today.
    with store.connection() as db:
        assert len(db.execute("SELECT DISTINCT blob_hash FROM income_records").fetchall()) == 1
    run.answer(THREE)
    run.extract()
    assert [(segment, income_id) for segment, income_id, _ in run.records()] == first
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM income_records").fetchone()[0] == 3


def test_a_run_stopped_after_reading_and_before_publishing_is_recovered_and_read_again(pdf_store, local_model, monkeypatch):
    run = three_stub_run(pdf_store, local_model)
    config = ReasoningConfig(base_url=local_model["config"].base_url, model="synthetic-reasoning")
    run_id, _ = run.extraction.enqueue(run.doc["id"], run.parse_id, config)

    def stopped(*args, **kwargs):
        raise KeyboardInterrupt  # The process stops: nothing catches it, so the run stays "running".

    with monkeypatch.context() as patch:
        patch.setattr(ExtractionService, "record", stopped)
        with pytest.raises(KeyboardInterrupt):
            run.extraction.run(run_id, Work.detached())
    assert run.extraction.get(run_id)["status"] == "running" and run.records() == []
    run.extraction.recover()  # On restart.
    assert run.extraction.get(run_id)["status"] == "interrupted"
    run.answer(THREE)
    run.extract()
    for record, (date, n) in zip(run.stubs_read(3), THREE):  # The end state equals SC-72 (a).
        assert record["pay_date"] == date
        mini_expect(record, n)
        auto(record)


# === Failures of the split itself ==========================================================================================

def test_a_failure_of_the_split_rule_reads_the_file_as_one_stub_with_a_record_note(pdf_store, local_model, monkeypatch, caplog):
    run = three_stub_run(pdf_store, local_model)

    def broken(lines):
        raise RuntimeError("injected split fault")

    monkeypatch.setattr(extraction, "stub_parts", broken)
    run.answer([THREE[0]])
    run.extract()
    [record] = [record for _, _, record in run.records()]
    assert extraction.PAY_SPLIT_FAILED == "Where each pay stub starts couldn't be read, so the file was read as one."
    assert extraction.PAY_SPLIT_FAILED in record["details"]["notes"] and extraction.PAY_SPLIT_FAILED not in record["issues"]
    assert segments_of(run.store, run.doc["id"]) == []
    assert [entry.getMessage() for entry in caplog.records if "pay stub split" in entry.getMessage()]
    assert not [entry for entry in caplog.records if "Regular" in entry.getMessage() or "2,000.00" in entry.getMessage()]


def test_a_part_that_is_not_a_pay_stub_makes_the_file_read_as_one(pdf_store, local_model):
    run = three_stub_run(pdf_store, local_model)
    replies = run.answer(THREE[:2] + THREE[2:], parts=run.parts())
    replies["Classification"][2] = {**replies["Classification"][2], "document_type": "receipt"}  # The second part (after the file's and the first part's).
    run.extract()
    assert run.run["result"]["split_notes"] == ["A part of this file is not a pay stub, so the file was read as one document."]
    assert "segments" not in run.run["publication"] and segments_of(run.store, run.doc["id"]) == []


# === Duplicates (FR-84, FR-85; plan P8 "Duplicates") ========================================================================

def repeated(pdf_store, local_model, third_net="1,800.00"):
    """A three-stub file (MINI-C) whose third stub has the employer and pay date of the first; with another net pay when third_net differs."""
    pages = mini_file(("2026-06-05", 1), ("2026-06-19", 1), ("2026-06-05", 1), ytd=False)
    if third_net != "1,800.00":  # Gross 2,100.00, net 1,900.00: the arithmetic still holds.
        pages[2]["items"] = [(x, y, {"2,000.00": "2,100.00", "1,800.00": third_net}.get(text, text)) for x, y, text in pages[2]["items"]]
    run = started_stubs(pdf_store, local_model, pages)
    run.answer([("2026-06-05", 1), ("2026-06-19", 1), ("2026-06-05", 1, "2,100.00", third_net) if third_net != "1,800.00" else ("2026-06-05", 1)], ytd=False)
    return run


def money_in(store, start="2026-06-01", end="2026-07-31"):
    return [row["inflow"]["minor"] for row in FinanceTools(store).calculate_cashflow(PeriodInput(start=start, end=end))["by_currency"]]


def test_a_stub_repeating_an_earlier_one_in_the_same_file_is_recorded_and_rejected_automatically(pdf_store, local_model):
    run = repeated(pdf_store, local_model)
    run.extract()
    first, second, third = run.stubs_read(3)
    note = "This pay stub repeats the one paid by SYNTH PAYROLL CO on 2026-06-05 (1,800.00 USD), so it doesn't count."
    assert (first["review_status"], second["review_status"]) == ("verified", "verified")
    assert (third["review_status"], third["review_source"]) == ("rejected", "automatic") and note in third["details"]["notes"] and note not in third["issues"]
    assert len(third["lines"]) == 2 and third["net_pay_minor"] == 180000  # Recorded with its lines.
    assert not [text for text in first["details"].get("notes", []) if "repeats" in text]
    assert money_in(run.store) == [360000]  # The first counts once; so does the second.
    snapshot = snapshot_of(run)
    run.answer([("2026-06-05", 1), ("2026-06-19", 1), ("2026-06-05", 1)], ytd=False)
    run.extract(force=True)  # Extract again gives the same result.
    assert snapshot_of(run) == snapshot and money_in(run.store) == [360000]


def test_a_reissued_stub_with_another_net_pay_counts_and_carries_the_same_pay_date_note(pdf_store, local_model):
    run = repeated(pdf_store, local_model, third_net="1,900.00")
    run.extract()
    first, second, third = run.stubs_read(3)
    note = "Another pay stub from SYNTH PAYROLL CO has the same pay date."
    assert [record["review_status"] for record in (first, second, third)] == ["verified"] * 3 and third["net_pay_minor"] == 190000
    assert note in third["details"]["notes"] and note not in third["issues"]
    assert not [text for record in (first, second) for text in record["details"].get("notes", []) if "same pay date" in text]
    assert money_in(run.store) == [180000 + 180000 + 190000]
    snapshot = snapshot_of(run)
    run.answer([("2026-06-05", 1), ("2026-06-19", 1), ("2026-06-05", 1, "2,100.00", "1,900.00")], ytd=False)
    run.extract(force=True)
    assert snapshot_of(run) == snapshot  # The first stub still carries no note: the later one does.


def test_the_same_stub_in_a_second_file_makes_the_second_files_record_the_duplicate(pdf_store, local_model):
    stubs = [("2026-06-05", 1)]
    one = started_stubs(pdf_store, local_model, mini_file(*stubs, ytd=False), name="one.pdf")
    one.answer(stubs, ytd=False)
    one.extract()
    two = started_stubs(pdf_store, local_model, mini_file(*stubs, ytd=False, extras={0: [(300, 400, "second copy")]}), name="two.pdf")
    two.answer(stubs, ytd=False)
    two.extract()
    [original], [copy] = [[record for _, _, record in run.records()] for run in (one, two)]
    assert original["review_status"] == "verified" and (copy["review_status"], copy["review_source"]) == ("rejected", "automatic")
    assert "This pay stub repeats the one paid by SYNTH PAYROLL CO on 2026-06-05 (1,800.00 USD), so it doesn't count." in copy["details"]["notes"]
    assert money_in(one.store) == [180000]
    # Extract again of the first file: it was recorded first, so it still counts.
    one.answer(stubs, ytd=False)
    one.extract(force=True)
    assert one.records()[0][2]["review_status"] == "verified" and two.records()[0][2]["review_status"] == "rejected"
    # When the original is rejected, the next Extract again of the duplicate lets it count.
    Ledger(one.store).review("income_record", original["id"], "rejected")
    two.answer(stubs, ytd=False)
    two.extract(force=True)
    counted = two.records()[0][2]
    assert counted["review_status"] == "verified" and not [text for text in counted["details"].get("notes", []) if "repeats" in text]
    assert money_in(one.store) == [180000]


def test_marking_a_stub_never_overrides_the_users_decision(two_stub_file):
    client, manager, docs = two_stub_file
    ledger = manager.ledger
    original = ledger.publish_income(EARLIER, segment_source(docs["stubs.pdf"], 0), "verified")["id"]
    copy = ledger.publish_income(EARLIER, segment_source(docs["stubs.pdf"], 1), "verified")["id"]
    with manager.store.connection() as db:
        db.execute("UPDATE income_records SET review_status='verified',review_source='user' WHERE id=?", (copy,))
    assert ledger.pay_stub_twin(EARLIER, segment_source(docs["stubs.pdf"], 1)) == {"original": original, "same_date": True}
    assert ledger.mark_duplicate(copy, original) is False and ledger.mark_void(copy) is False
    with manager.store.connection() as db:
        assert tuple(db.execute("SELECT review_status,review_source FROM income_records WHERE id=?", (copy,)).fetchone()) == ("verified", "user")
        db.execute("UPDATE income_records SET review_status='rejected' WHERE id=?", (original,))
    assert ledger.mark_duplicate(original + 100, original) is False  # Its original no longer counts.
    assert ledger.pay_stub_twin(EARLIER, segment_source(docs["stubs.pdf"], 1)) is None


# === the tax tables of every year a split file's stubs were paid in =========================================================

def asked_for_tax_tables(run):
    """Manager.extract_and_file on the run's file with the real look_up_tax_tables, no table known yet and tax_tables.enqueue recorded: the
    (jurisdiction, year) it was asked for, in order. enqueue raises ValueError ("no web search key or model"), so no model or network call happens."""
    asked = []

    def enqueue(jurisdiction, year, filing_status, config):
        asked.append((jurisdiction, year))
        raise ValueError("no web search key")

    manager = SimpleNamespace(
        extractions=run.extraction, reconciler=SimpleNamespace(run=lambda *_: None), file_extraction=lambda *_: None, identify_items=lambda *_: None,
        scan_payees=lambda *_: None, ledger=Ledger(run.store), household=SimpleNamespace(filing_status="single"), reasoning_config=None,
        tax_tables=SimpleNamespace(tables=SimpleNamespace(needed=lambda year, state, filing_status: [f"federal-{year}"]), enqueue=enqueue))
    manager.look_up_tax_tables = lambda income_id, work: Manager.look_up_tax_tables(manager, income_id, work)
    run_id, _ = run.extraction.enqueue(run.doc["id"], run.parse_id, ReasoningConfig(base_url=run.local_model["config"].base_url, model="synthetic-reasoning"))
    Manager.extract_and_file(manager, run.doc["id"], run_id, Work.detached())
    assert run.extraction.get(run_id)["status"] == "succeeded"
    return asked


def test_a_file_of_stubs_paid_in_two_years_looks_up_the_tax_tables_of_both_years(pdf_store, local_model):
    stubs = (("2025-12-19", 1), ("2026-01-02", 2))
    run = started_stubs(pdf_store, local_model, mini_file(*stubs, ytd=False))
    run.answer(stubs, ytd=False)
    assert asked_for_tax_tables(run) == [("federal-2025", 2025), ("federal-2026", 2026)]


def test_a_one_stub_file_looks_up_its_tax_tables_once(pdf_store, local_model):
    run = started_stubs(pdf_store, local_model, mini_file(("2026-01-02", 1), ytd=False))
    run.answer((("2026-01-02", 1),), ytd=False)
    assert asked_for_tax_tables(run) == [("federal-2026", 2026)]
