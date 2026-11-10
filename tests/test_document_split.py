"""Documents merged under one Inbox name are split by the upgrade (specs/inbox-document-identity FR-06, FR-07; test-contract.md SC-05 – SC-14).

Before capture gave a different file under a filed file's name a document of its own, every download called `document.pdf` became the
next version of the first one. `merged_library` makes that old shape from files and records the real code makes (capture, organize and
`Ledger`), rewrites the database into one occurrence with several versions, and sets the schema back to 079. Reopening the store is the
upgrade under test (migration 080). The fixture hands back the expected split computed from its plan, never from the repair.
Everything is synthetic and lives under tmp_path.
"""
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import pytest

from conftest import inbox_scan
from home_manager.finance.ledger import Ledger
from home_manager.library import storage
from home_manager.library.storage import RELEASED_PATH, MigrationError, Store
from home_manager.library.trash import empty
from scripts.document_splits import MERGED_IN
from test_paystub_split import stub
from test_statement_accounts import statement
from test_table_engine import no_network  # noqa: F401  (the autouse C-net guard)

SPLIT_STEP = 80
SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "document_splits.py"
MIGRATION = next(path for number, path in storage.MIGRATIONS if number == SPLIT_STEP)  # 080_split_merged_documents.sql
CSV = b"Date,Description,Amount\n2026-09-04,SYNTH BAKERY,-6.25\n2026-09-05,SYNTH PAYROLL,2000.00\n"


def at(day):
    return f"2026-10-{day:02d}T09:00:00+00:00"


T1, T2, T3, T4, T5, T6, T7, T8, T9 = (at(day) for day in range(1, 10))
A, B, C = b"synthetic statement A", b"synthetic pay stub B", b"synthetic reading C"
A2 = b"synthetic statement A, edited"
FILED = ("Bank_Statements", "Supported metadata")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def entry(data, captured, left, **records):
    """One file dropped in the Inbox as `document.pdf`. captured and left (the time it was filed or archived out of the Inbox, else
    None) are fixed strings. records: statement=<rows>, stub=True, reading=True, imports=True (a CSV import of the file), folder=<name>,
    event=True, donation=True, edit=True (this file changes the Inbox file before it is filed: a version, not a new document),
    no_history=True (its filing events are lost)."""
    return {"data": data, "captured": captured, "left": left, **records}


def standard(**changes):
    """SC-05: A filed at T2 and B at T4, then C filed at T6, all merged under one name."""
    return {"files": [entry(A, T1, T2, statement=3), entry(B, T3, T4, stub=True), entry(C, T5, T6, reading=True)], **changes}


# --- the database as the tests read it ----------------------------------------------------------------------------------------

DOCUMENT_COLUMNS = {"document_id", "occurrence_id", "source_document_id", "other_occurrence_id"}
VERSION_TABLES = ("managed_files", "managed_organization_intents", "managed_organization_events", "library_events", "document_folders", "document_segments",
                  "organization_runs", "job_filings", "donation_checks", "statements", "receipts", "income_records", "assets", "tax_forms",
                  "investment_confirmations", "investment_events", "investment_valuations", "transaction_imports", "financial_evidence_links")
# Rows that name a document and a reading or another record, not a version: the upgrade moves them with it (test-contract.md "Definitions").
OTHER_TABLES = ("extraction_runs", "receipt_batch_items", "transactions", "recurring_obligations", "occurrence_links")
# Document-level: they stay with the merged document (document_splits is the repair's own record).
STAYING = ("document_descriptions", "document_group_pages", "document_splits")


def open_db(root):
    db = sqlite3.connect(root / "inventory.sqlite3")
    db.row_factory = sqlite3.Row
    return db


def document_columns(db):
    """{table: columns naming a document}, from the schema as it is now."""
    found = {}
    for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall():
        columns = [row[1] for row in db.execute(f'PRAGMA table_info("{table}")') if row[1] in DOCUMENT_COLUMNS]
        if columns:
            found[table] = columns
    return found


def user_version(root):
    with sqlite3.connect(root / "inventory.sqlite3") as db:
        return db.execute("PRAGMA user_version").fetchone()[0]


def dump(root, without=()):
    """Every statement of the database but those mentioning a name in `without` (the test's own fault trigger)."""
    with sqlite3.connect(root / "inventory.sqlite3") as db:
        return [line for line in db.iterdump() if not any(name in line for name in without)]


def counts(db):
    """Row count of every table. The renames of FR-08 (organization rows with action 'layout') are not the repair's, so they are left out."""
    found = {}
    for (table,) in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        where = " WHERE action<>'layout'" if table in ("managed_organization_intents", "managed_organization_events") else ""
        found[table] = db.execute(f'SELECT count(*) FROM "{table}"{where}').fetchone()[0]
    return found


def files_under(folder):
    return Counter(sha(path.read_bytes()) for path in folder.rglob("*") if path.is_file())


@dataclass
class Snapshot:
    counts: dict
    blobs: dict
    library: Counter


def snapshot(root):
    with open_db(root) as db:
        rows = counts(db)
    return Snapshot(rows, {path.name: sha(path.read_bytes()) for path in (root / "originals").rglob("*.blob")}, files_under(root / "Library"))


def document_of(db, digest):
    """The one Inbox document whose versions include the hash."""
    rows = db.execute("SELECT v.occurrence_id FROM versions v JOIN occurrences o ON o.id=v.occurrence_id WHERE v.hash=? AND o.relative_path<>'copy.pdf'", (digest,)).fetchall()
    assert len(rows) == 1, f"{len(rows)} documents hold this version"
    return rows[0][0]


@contextmanager
def reopened(root):
    """The upgrade under test: opening the store runs every step above the one the database is at, then the startup recovery."""
    store = Store(root)
    try:
        yield store
    finally:
        store.close()


# --- the fixture ----------------------------------------------------------------------------------------------------------

@dataclass
class Merged:
    root: Path
    plan: dict
    hashes: list
    ids: list                    # the document each file really got when it was captured
    runs: list                   # the files of each run, in order: the expected split, computed from the plan
    records: list = field(default_factory=list)  # per file: the ids of what was recorded on it
    other: int | None = None     # the document dropped after the merge (the already-released variant), or the duplicate of SC-12
    copies: list = field(default_factory=list)  # the documents each "copy" entry made, before they were merged
    before: Snapshot | None = None

    @property
    def new(self):
        return len(self.runs) - 1


def expected_runs(files):
    """A file after a filed file starts a run, unless the filing left no history or the file edited the Inbox file."""
    runs = []
    for index, item in enumerate(files):
        previous = files[index - 1] if index else None
        merged = bool(previous) and not item.get("edit") and previous["left"] is not None and previous["left"] < item["captured"] and not previous.get("no_history")
        if merged:
            runs.append([index])
        elif runs:
            runs[-1].append(index)
        else:
            runs.append([index])
    return runs


def record_on(store, ledger, item, doc, hash_):
    """What the plan records on one file, through the real ledger. No model: the records are the synthetic statement and pay stub."""
    source = {"document_id": doc, "blob_hash": hash_, "source_key": "extraction:test", "run_id": "test"}
    made = {}
    if item.get("statement"):
        rows = tuple((f"2026-09-0{n}", f"SYNTH SHOP {n}", -100 * n) for n in range(1, item["statement"] + 1))
        published = ledger.publish_statement(statement("3456", rows=rows), source, "proposed")
        ledger.review("statement", published["id"], "verified")
        made["statement"], made["account"] = published["id"], published["account_id"]
        with store.connection() as db:
            made["transactions"] = [row[0] for row in db.execute("SELECT id FROM transactions WHERE statement_id=? ORDER BY id", (published["id"],))]
    if item.get("stub"):
        made["stub"] = ledger.publish_income(stub("SYNTH PAYROLL CO", "2026-09-15", 200000, 180000, [("Regular", "earnings", "regular_pay", 200000, 2000000)]),
                                             {**source, "source_key": "extraction:stub"}, "verified")["id"]
    with store.connection() as db:
        if item.get("reading"):
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at) VALUES(?,?,'test','{}','succeeded',?,?)",
                       (f"parse-{doc}-{hash_[:8]}", hash_, T1, T1))
            made["run"] = f"extraction-{doc}-{hash_[:8]}"
            db.execute("INSERT INTO extraction_runs(id,document_id,parse_run_id,config_json,prompt_version,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                       (made["run"], doc, f"parse-{doc}-{hash_[:8]}", "{}", "test", "succeeded", T1, T1))
        if item.get("folder"):
            db.execute("INSERT INTO document_folders VALUES(?,?,?,?)", (doc, hash_, item["folder"], T1))
        if item.get("event"):
            db.execute("INSERT INTO library_events(document_id,blob_hash,action,detail,created_at) VALUES(?,?,'move','Housing',?)", (doc, hash_, T1))
        if item.get("donation"):
            db.execute("INSERT INTO donation_checks(document_id,blob_hash,record_type,record_id,document_type,extraction_run_id,extraction_version,proposal_json,"
                       "answers_json,source_kind,status,created_at,updated_at) VALUES(?,?,'income_record',?,'paystub','run','1','{}','{}','scan','draft',?,?)",
                       (doc, hash_, made.get("stub", 1), T1, T1))
    if item.get("imports"):
        account = made.get("account") or ledger.create_account("SYNTH BANK", "checking", "USD")["id"]
        imported = ledger.import_transactions(doc, account)
        made["import"] = imported["import_id"]
        with store.connection() as db:
            made["transactions"] = [row[0] for row in db.execute("SELECT id FROM transactions WHERE source_document_id=? AND origin='import' ORDER BY id", (doc,))]
    return made


def merge_documents(root, plan, ids, hashes):
    """The old capture's shape: one occurrence for every file after the first, in the first one's id. Rows naming a later document name the
    first, each Library copy keeps the `__d1` name the old capture gave it, and the first document holds the last file's hash and Inbox path."""
    first, later = ids[0], [doc for doc in dict.fromkeys(ids) if doc != ids[0]]
    if not later:
        return
    marks = ",".join("?" * len(later))
    db = open_db(root)
    try:
        with db:
            for number in later:  # Library copies: on disk, in managed_files and in the intents and events that name them.
                for (path,) in db.execute("SELECT relative_path FROM managed_files WHERE relative_path LIKE ?", (f"%__d{number}.%",)).fetchall():
                    renamed = path.replace(f"__d{number}.", f"__d{first}.")
                    (root / "Library" / path).rename(root / "Library" / renamed)
                for table, columns in (("managed_files", ("relative_path",)), ("managed_organization_intents", ("source_path", "target_path")),
                                       ("managed_organization_events", ("source_path", "target_path"))):
                    for column in columns:
                        db.execute(f"UPDATE {table} SET {column}=replace({column}, ?, ?) WHERE {column} LIKE ?", (f"__d{number}.", f"__d{first}.", f"%__d{number}.%"))
            for table, columns in document_columns(db).items():
                for column in columns:
                    replace = "OR REPLACE " if table in ("document_folders", "document_descriptions") else ""
                    db.execute(f"UPDATE {replace}{table} SET {column}=? WHERE {column} IN ({marks})", (first, *later))
            last = db.execute("SELECT * FROM occurrences WHERE id=?", (ids[-1],)).fetchone()
            db.execute(f"DELETE FROM occurrences WHERE id IN ({marks})", later)
            db.execute("UPDATE occurrences SET current_hash=?,path_key=?,source_status=?,last_seen=?,last_job=? WHERE id=?",
                       (last["current_hash"], last["path_key"], last["source_status"], last["last_seen"], last["last_job"], first))
    finally:
        db.close()


def fix_times(root, plan, hashes):
    """versions.captured_at and the time each file left the Inbox are the plan's fixed strings."""
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        with db:
            for item, hash_ in zip(plan["files"], hashes, strict=True):
                db.execute("UPDATE versions SET captured_at=? WHERE hash=?", (item["captured"], hash_))
                if item["left"] is not None:
                    db.execute("UPDATE managed_organization_events SET created_at=? WHERE blob_hash=? AND substr(source_path,1,6)='Inbox/'", (item["left"], hash_))
                if item.get("no_history"):
                    db.execute("DELETE FROM managed_organization_events WHERE blob_hash=?", (hash_,))
    finally:
        db.close()


def merged_library(tmp_path, plan):
    """A library at schema 079 whose files merged under one Inbox name (test-contract.md "Fixtures"). plan: {"files": [entry(...)], plus
    "name" (default document.pdf), "merge" (False keeps each file its own document), "trash", "description", "duplicate" (SC-12: the index of the file whose bytes are dropped again as copy.pdf),
    "copy" (entries dropped as copy.pdf after the others, merged under that name too: a same_bytes link between two merged documents) and "released"
    (a later file D dropped under the same name and filed, after the merge: the already-released variant)}."""
    root = tmp_path / "managed"
    name = plan.get("name", "document.pdf")
    files = plan["files"]
    store = Store(root)
    ids, hashes, records, other, copies = [], [], [], None, []
    try:
        ledger = Ledger(store)
        for index, item in enumerate(files):
            (store.library.inbox / name).write_bytes(item["data"])
            inbox_scan(store)
            hashes.append(sha(item["data"]))
            with store.connection() as db:
                doc = db.execute("SELECT id FROM occurrences WHERE current_hash=? AND source_kind='inbox'", (hashes[-1],)).fetchone()[0]
            ids.append(doc)
            records.append(record_on(store, ledger, item, doc, hashes[-1]))
            if item["left"] is not None and not (index + 1 < len(files) and files[index + 1].get("edit")):  # An edit archives it; else it is filed.
                store.library.organize(doc, hashes[-1], *FILED, merchant="Bank", document_date="2026-10-31")
            if plan.get("duplicate") == index:  # SC-12: the same bytes at another path are another document with a same_bytes link.
                (store.library.inbox / "copy.pdf").write_bytes(item["data"])
                inbox_scan(store)
                with store.connection() as db:
                    other = db.execute("SELECT id FROM occurrences WHERE relative_path='copy.pdf'").fetchone()[0]
                assert other not in ids
        for item in plan.get("copy", ()):  # The same bytes as a file above make a same_bytes link at capture.
            (store.library.inbox / "copy.pdf").write_bytes(item["data"])
            inbox_scan(store)
            with store.connection() as db:
                copies.append(db.execute("SELECT id FROM occurrences WHERE relative_path='copy.pdf' AND current_hash=?", (sha(item["data"]),)).fetchone()[0])
            if item["left"] is not None:
                store.library.organize(copies[-1], sha(item["data"]), *FILED, merchant="Bank", document_date="2026-10-31")
        if plan.get("description"):
            with store.connection() as db:
                db.execute("INSERT INTO document_descriptions VALUES(?,?,?)", (ids[0], plan["description"], T1))
    finally:
        store.close()
    runs = expected_runs(files)
    if plan.get("merge", True):
        merge_documents(root, plan, ids, hashes)
        if copies:
            merge_documents(root, plan, copies, [sha(item["data"]) for item in plan["copy"]])
    merged = Merged(root, plan, hashes, ids, runs, records, other, copies)
    if plan.get("released"):
        merged.other = drop_later_file(root, plan)
    fix_times(root, plan, hashes)
    if copies:
        fix_times(root, {"files": plan["copy"]}, [sha(item["data"]) for item in plan["copy"]])
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        with db:
            if plan.get("released"):
                db.execute("UPDATE versions SET captured_at=? WHERE hash=?", (T8, sha(plan["released"])))
                db.execute("UPDATE managed_organization_events SET created_at=? WHERE blob_hash=?", (T9, sha(plan["released"])))
            if plan.get("trash"):
                db.execute("UPDATE occurrences SET deleted_at=? WHERE id=?", (datetime.now(timezone.utc).isoformat(), ids[0]))
            if plan.get("fault"):  # SC-09: the repair aborts at its second new document.
                db.execute("CREATE TRIGGER test_fault BEFORE INSERT ON occurrences WHEN (SELECT count(*) FROM occurrences) >= 2 "
                           "BEGIN SELECT RAISE(ABORT, 'test fault'); END")
            db.execute("DROP TABLE document_splits")  # The latest schema holds it; a library at 079 does not.
            db.execute(f"PRAGMA user_version={SPLIT_STEP - 1}")
    finally:
        db.close()
    merged.before = snapshot(root)
    return merged


def drop_later_file(root, plan):
    """The already-released variant: today's capture drops D as `document.pdf` after C is filed, and files it. Document 1 is released and D holds the bare key."""
    with reopened(root) as store:
        (store.library.inbox / plan.get("name", "document.pdf")).write_bytes(plan["released"])
        inbox_scan(store)
        with store.connection() as db:
            doc = db.execute("SELECT id FROM occurrences WHERE current_hash=?", (sha(plan["released"]),)).fetchone()[0]
        store.library.organize(doc, sha(plan["released"]), FILED[0], FILED[1], merchant="Bank", document_date="2026-10-31")
    return doc


# --- the oracle every scenario applies --------------------------------------------------------------------------------------

def check_split(merged, expected_new=None):
    """After the upgrade: (a) row counts against the snapshot, (b) every version-keyed row names a document holding its version, (c) each
    run is a document of its own, (d) blobs and Library files have the same bytes. Returns {run: document id}."""
    root, before = merged.root, merged.before
    new = merged.new if expected_new is None else expected_new
    assert user_version(root) == len(storage.MIGRATIONS) and storage.MIGRATIONS[-1][0] >= SPLIT_STEP
    with open_db(root) as db:
        after = counts(db)
        want = {**before.counts, "occurrences": before.counts["occurrences"] + new, "document_splits": new}
        assert after == want
        for table, columns in document_columns(db).items():
            if "document_id" in columns and "blob_hash" in {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}:
                orphans = db.execute(f'SELECT count(*) FROM "{table}" t WHERE NOT EXISTS (SELECT 1 FROM versions v WHERE v.occurrence_id=t.document_id AND v.hash=t.blob_hash)').fetchone()[0]
                assert orphans == 0, f"{table}: {orphans} rows name a document that does not hold their version"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        owner = {}
        for run, indexes in enumerate(merged.runs):
            document = document_of(db, merged.hashes[indexes[0]])
            owner[run] = document
            versions = [row[0] for row in db.execute("SELECT hash FROM versions WHERE occurrence_id=? ORDER BY captured_at,id", (document,))]
            assert versions == [merged.hashes[index] for index in indexes]
            row = db.execute("SELECT * FROM occurrences WHERE id=?", (document,)).fetchone()
            assert row["current_hash"] == merged.hashes[indexes[-1]]
            assert row["relative_path"] == merged.plan.get("name", "document.pdf") and row["source_kind"] == "inbox"
            if run:
                assert row["first_seen"] == merged.plan["files"][indexes[0]]["captured"]
        assert owner[0] == merged.ids[0]
        assert len(set(owner.values())) == len(owner)
    assert snapshot(root).blobs == before.blobs
    assert snapshot(root).library == before.library
    return owner


def inbox_keys(db, owner):
    return {run: tuple(db.execute("SELECT path_key,source_status FROM occurrences WHERE id=?", (document,)).fetchone()) for run, document in owner.items()}


# --- SC-05 – SC-07: the split, and what follows each piece --------------------------------------------------------------------

def test_sc05_three_files_merged_under_document_pdf_are_split_each_with_its_own_records(tmp_path):
    merged = merged_library(tmp_path, standard())
    assert [len(run) for run in merged.runs] == [1, 1, 1] and user_version(merged.root) == 79
    with reopened(merged.root):
        pass
    owner = check_split(merged)
    a, b, c = owner[0], owner[1], owner[2]
    assert a == 1 and len({a, b, c}) == 3
    statement_id, stub_id, run_id = merged.records[0]["statement"], merged.records[1]["stub"], merged.records[2]["run"]
    with open_db(merged.root) as db:
        assert tuple(db.execute("SELECT document_id,blob_hash FROM statements WHERE id=?", (statement_id,)).fetchone()) == (a, merged.hashes[0])
        evidence = db.execute("SELECT document_id,blob_hash FROM financial_evidence_links WHERE record_type='statement' AND record_id=?", (statement_id,)).fetchall()
        assert evidence and {tuple(row) for row in evidence} == {(a, merged.hashes[0])}
        rows = merged.records[0]["transactions"]
        assert len(rows) == 3
        assert [row[0] for row in db.execute(f"SELECT source_document_id FROM transactions WHERE id IN ({','.join('?' * 3)})", rows)] == [a] * 3
        assert tuple(db.execute("SELECT document_id,blob_hash FROM income_records WHERE id=?", (stub_id,)).fetchone()) == (b, merged.hashes[1])
        assert db.execute("SELECT document_id FROM extraction_runs WHERE id=?", (run_id,)).fetchone()[0] == c
        # The statement keeps the review the user gave it.
        assert tuple(db.execute("SELECT review_status,review_source FROM statements WHERE id=?", (statement_id,)).fetchone()) == ("verified", "user")
        assert db.execute("SELECT count(*) FROM review_events WHERE record_type='statement' AND record_id=?", (statement_id,)).fetchone()[0] >= 1
        # The Inbox path: C holds the bare key; A and B hold released keys and count as filed.
        keys = inbox_keys(db, owner)
        assert keys[2] == ("document.pdf", "organized")
        assert keys[0] == (f"document.pdf{RELEASED_PATH}{a}", "organized") and keys[1] == (f"document.pdf{RELEASED_PATH}{b}", "organized")
        assert [tuple(row) for row in db.execute("SELECT document_id,from_document_id,versions FROM document_splits ORDER BY document_id")] == [(b, a, 1), (c, a, 1)]


def test_sc05_the_pages_see_one_version_each(tmp_path):
    from fastapi.testclient import TestClient

    from home_manager.app.api import create_app
    from home_manager.library.scanner import ScanLimits
    merged = merged_library(tmp_path, standard())
    with reopened(merged.root):
        pass
    app = create_app(tmp_path / "control", "test-session-token", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer test-session-token"}) as client:
        app.state.manager.configure(str(merged.root))
        assert client.get("/api/documents").json()["total"] == 3
        with open_db(merged.root) as db:
            owner = {run: document_of(db, merged.hashes[indexes[0]]) for run, indexes in enumerate(merged.runs)}
        for document in owner.values():
            assert len(client.get(f"/api/documents/{document}/versions").json()) == 1
        row = merged.records[0]["transactions"][0]
        evidence = client.get(f"/api/finance/records/transaction/{row}").json()["evidence"]
        assert {(item["document_id"], item["blob_hash"]) for item in evidence} == {(owner[0], merged.hashes[0])}
        assert client.get(f"/api/documents/{owner[0]}").json()["current_hash"] == merged.hashes[0]  # So the page opens A with no earlier-version banner.


def test_sc06_a_real_edit_made_in_the_inbox_stays_a_version(tmp_path):
    """A and A' both arrive before any filing; A is archived out of the Inbox after A' was captured, A' is filed after."""
    plan = {"files": [entry(A, T1, T3), entry(A2, T2, T4, edit=True)]}
    merged = merged_library(tmp_path, plan)
    assert merged.runs == [[0, 1]] and len(set(merged.ids)) == 1
    with reopened(merged.root):
        pass
    check_split(merged)
    with open_db(merged.root) as db:
        assert [row[0] for row in db.execute("SELECT hash FROM versions WHERE occurrence_id=? ORDER BY captured_at", (merged.ids[0],))] == [sha(A), sha(A2)]
        assert db.execute("SELECT count(*) FROM document_splits").fetchone()[0] == 0


def test_sc07_a_folder_event_import_and_donation_on_b_follow_b_and_the_trash_state_follows_all(tmp_path):
    csv_b = CSV
    plan = {"name": "document.csv", "trash": True, "description": "Synthetic note", "files": [
        entry(A, T1, T2, statement=3), entry(csv_b, T3, T4, stub=True, imports=True, folder="Housing", event=True, donation=True), entry(C, T5, T6, reading=True)]}
    merged = merged_library(tmp_path, plan)
    with open_db(merged.root) as db:
        deleted = db.execute("SELECT deleted_at FROM occurrences WHERE id=1").fetchone()[0]
    with reopened(merged.root):
        pass
    owner = check_split(merged)
    b = owner[1]
    with open_db(merged.root) as db:
        digest = sha(csv_b)
        assert db.execute("SELECT document_id FROM document_folders WHERE blob_hash=?", (digest,)).fetchone()[0] == b
        assert db.execute("SELECT document_id FROM library_events WHERE blob_hash=?", (digest,)).fetchone()[0] == b
        assert db.execute("SELECT document_id FROM transaction_imports WHERE id=?", (merged.records[1]["import"],)).fetchone()[0] == b
        assert db.execute("SELECT document_id FROM donation_checks WHERE blob_hash=?", (digest,)).fetchone()[0] == b
        imported = merged.records[1]["transactions"]
        assert len(imported) == 2
        assert {row[0] for row in db.execute(f"SELECT source_document_id FROM transactions WHERE id IN ({','.join('?' * 2)})", imported)} == {b}
        assert {row[0] for row in db.execute(f"SELECT document_id FROM financial_evidence_links WHERE record_type='transaction' AND record_id IN ({','.join('?' * 2)})", imported)} == {b}
        assert db.execute("SELECT document_id FROM document_descriptions").fetchall()[0][0] == owner[0]  # Document-level: it stays with the first.
        assert [row[0] for row in db.execute("SELECT deleted_at FROM occurrences ORDER BY id")] == [deleted] * 3  # Every piece stays in Trash.
        assert db.execute("SELECT count(*) FROM transactions WHERE source_document_id=?", (owner[0],)).fetchone()[0] == 3  # The statement's three rows stay with A.


# --- SC-08: the Library copies take their new ids, durably ---------------------------------------------------------------------

def managed(db, digest):
    row = db.execute("SELECT document_id,relative_path FROM managed_files WHERE blob_hash=?", (digest,)).fetchone()
    return row["document_id"], row["relative_path"]


def fail_once_for(monkeypatch, tail):
    """The library publishes with os.link on Linux and os.rename on Windows. Neither sees the source path, so the fault matches C's target
    name: it raises OSError once for the path ending `tail` and otherwise calls the real function."""
    name = "rename" if os.name == "nt" else "link"
    real, seen = getattr(os, name), []

    def faulty(source, target, *args, **kwargs):
        if str(target).endswith(tail) and not seen:
            seen.append(target)
            raise OSError("test fault")
        return real(source, target, *args, **kwargs)

    monkeypatch.setattr(os, name, faulty)
    return seen


def test_sc08_split_copies_are_renamed_to_their_ids_durably(tmp_path, monkeypatch):
    merged = merged_library(tmp_path, standard())
    root = merged.root
    with sqlite3.connect(root / "inventory.sqlite3") as db:  # Step 1: the upgrade alone, before any organization pass.
        storage.apply_migrations(db, SPLIT_STEP - 1)
    with open_db(root) as db:
        owner = {run: document_of(db, merged.hashes[indexes[0]]) for run, indexes in enumerate(merged.runs)}
        a, b, c = owner[0], owner[1], owner[2]
        before = {run: managed(db, merged.hashes[run]) for run in owner}
    assert len({a, b, c}) == 3 and a == 1
    for run, data in ((1, B), (2, C)):  # Each still names its `__d1` file, and that file opens with its own bytes.
        document, path = before[run]
        assert document == owner[run] and f"__d{a}." in path
        assert (root / "Library" / path).read_bytes() == data
    # The same pass first moves B's copy into the month of its pay stub (September), keeping its name; the rename follows there.
    old_b = before[1][1].replace("/2026/10/", "/2026/09/")
    assert old_b != before[1][1]
    # Step 4's decoy: a different file already at B's target name.
    target_b = old_b.replace(f"__d{a}.", f"__d{b}.")
    (root / "Library" / target_b).parent.mkdir(parents=True, exist_ok=True)
    (root / "Library" / target_b).write_bytes(b"synthetic decoy")
    # Step 2: one pass, with the publication of C's copy failing once.
    target_c = before[2][1].replace(f"__d{a}.", f"__d{c}.")
    seen = fail_once_for(monkeypatch, target_c)
    store = Store(root)
    try:
        assert seen, "C's rename was attempted and failed once"
        with store.connection() as db:
            assert managed(db, merged.hashes[1]) == (b, old_b)  # B: blocked by the decoy, still at its old name.
            blocked = db.execute("SELECT error FROM managed_organization_intents WHERE document_id=? AND action='layout' AND status='blocked'", (b,)).fetchone()
            assert "different bytes" in blocked["error"] and "not overwritten" in blocked["error"]
            assert managed(db, merged.hashes[2]) == (c, before[2][1])  # C: the fault left it at its old name, and it still opens.
            assert db.execute("SELECT count(*) FROM managed_organization_intents WHERE document_id=? AND status IN ('pending','blocked')", (c,)).fetchone()[0] == 1
    finally:
        store.close()
    assert (root / "Library" / before[2][1]).read_bytes() == C
    assert (root / "Library" / old_b).read_bytes() == B and (root / "Library" / target_b).read_bytes() == b"synthetic decoy"
    # Step 3: reopen. The interrupted rename finishes; B stays blocked by the decoy and nothing is overwritten.
    with reopened(root) as store:
        with store.connection() as db:
            assert managed(db, merged.hashes[2]) == (c, target_c)
            assert db.execute("SELECT count(*) FROM managed_organization_intents WHERE document_id=? AND status IN ('pending','blocked')", (c,)).fetchone()[0] == 0
            assert managed(db, merged.hashes[1]) == (b, old_b)
    assert (root / "Library" / target_c).read_bytes() == C and not (root / "Library" / before[2][1]).exists()
    assert (root / "Library" / old_b).read_bytes() == B and (root / "Library" / target_b).read_bytes() == b"synthetic decoy"
    # Without the decoy B takes its id too (step 2's B), and a later pass renames nothing twice.
    (root / "Library" / target_b).unlink()
    with open_db(root) as db:
        db.execute("DELETE FROM managed_organization_intents WHERE document_id=? AND status='blocked'", (b,))
        db.commit()
    with reopened(root):
        pass
    with open_db(root) as db:
        for run, data in ((0, A), (1, B), (2, C)):
            document, path = managed(db, merged.hashes[run])
            assert document == owner[run] and path.endswith(f"__d{document}.pdf")
            assert (root / "Library" / path).read_bytes() == data
        assert len({managed(db, merged.hashes[run])[1] for run in owner}) == 3
        assert db.execute("SELECT count(*) FROM managed_organization_intents WHERE status IN ('pending','blocked')").fetchone()[0] == 0
        first = [tuple(row) for row in db.execute("SELECT id,target_path FROM managed_organization_intents ORDER BY id")]
    with reopened(root):
        pass
    with open_db(root) as db:
        assert [tuple(row) for row in db.execute("SELECT id,target_path FROM managed_organization_intents ORDER BY id")] == first
    assert snapshot(root).library == merged.before.library  # Names changed, bytes did not.
    check_split(merged)


def test_sc08_a_given_name_never_falls_back_to_a_full_hash_name(tmp_path):
    with reopened(tmp_path / "managed") as store:
        (store.library.inbox / "x.pdf").write_bytes(A)
        inbox_scan(store)
        with store.connection() as db:
            doc = db.execute("SELECT id FROM occurrences").fetchone()[0]
        store.library.organize(doc, sha(A), *FILED, merchant="Bank", document_date="2026-10-31")
        with store.connection() as db:
            path = db.execute("SELECT relative_path FROM managed_files").fetchone()[0]
        for bad in ("a/b.pdf", "a..pdf", "x" * 200 + ".pdf"):
            with pytest.raises(ValueError, match="safe limits"):
                store.library.organize(doc, sha(A), *FILED, action="layout", name=bad)
        folder = (store.library.root / path).parent
        (folder / "taken.pdf").write_bytes(b"synthetic decoy")
        with pytest.raises(ValueError, match="different bytes"):
            store.library.organize(doc, sha(A), *FILED, action="layout", name="taken.pdf")
        assert (folder / "taken.pdf").read_bytes() == b"synthetic decoy" and (store.library.root / path).read_bytes() == A


# --- SC-09: all or nothing ---------------------------------------------------------------------------------------------------

def test_cr1_4_a_restored_piece_is_still_renamed_after_the_original_is_emptied_from_trash(tmp_path):
    """Code review round 1, finding 4: Trash holds every piece. B is restored, then Trash is emptied (A and C go). The purge's foreign-key
    walk must not take B's document_splits row with the original, or B's Library copy keeps document 1's id for good."""
    merged = merged_library(tmp_path, standard(trash=True))
    with reopened(merged.root):
        pass
    with open_db(merged.root) as db:
        b = document_of(db, merged.hashes[1])
        assert [row["from"] for row in db.execute("PRAGMA foreign_key_list(document_splits)")] == ["document_id"]  # from_document_id is provenance only.
        assert db.execute("SELECT relative_path FROM managed_files WHERE document_id=?", (b,)).fetchone()[0].endswith("__d1.pdf")
    with reopened(merged.root) as store:
        store.library_action(b, merged.hashes[1], "restore")
        assert empty(store)["deleted"] == 2
        store.library.recover()
    with open_db(merged.root) as db:
        assert [row[0] for row in db.execute("SELECT id FROM occurrences ORDER BY id")] == [b]
        assert db.execute("SELECT deleted_at FROM occurrences WHERE id=?", (b,)).fetchone()[0] is None
        assert [tuple(row) for row in db.execute("SELECT document_id,from_document_id FROM document_splits")] == [(b, 1)]
        path = db.execute("SELECT relative_path FROM managed_files WHERE document_id=?", (b,)).fetchone()[0]
        assert db.execute("SELECT count(*) FROM managed_files").fetchone()[0] == 1
        assert db.execute("SELECT status FROM managed_organization_intents WHERE document_id=? AND action='layout'", (b,)).fetchone()[0] == "succeeded"
    assert path.endswith(f"__d{b}.pdf") and sha((merged.root / "Library" / path).read_bytes()) == merged.hashes[1]
    assert files_under(merged.root / "Library") == Counter([merged.hashes[1]])


def test_sc09_a_failure_in_the_middle_of_the_repair_leaves_the_library_as_it_was(tmp_path):
    merged = merged_library(tmp_path, standard(fault=True))
    root = merged.root
    before = dump(root)
    with pytest.raises(MigrationError) as failed:
        Store(root)
    assert failed.value.number == SPLIT_STEP and failed.value.version == SPLIT_STEP - 1 and "test fault" in str(failed.value.__cause__)
    assert user_version(root) == SPLIT_STEP - 1 and dump(root) == before
    assert snapshot(root).blobs == merged.before.blobs and snapshot(root).library == merged.before.library
    assert (root / f"inventory.before-v{storage.MIGRATIONS[-1][0]}.sqlite3").exists()
    with sqlite3.connect(root / "inventory.sqlite3") as db:
        db.execute("DROP TRIGGER test_fault")
    with reopened(root):
        pass
    check_split(merged)


# --- SC-11: a missing filing history keeps the version ----------------------------------------------------------------------------

def test_sc11_version_missing_filing_history_keeps_the_version(tmp_path):
    plan = {"files": [entry(A, T1, T2, no_history=True), entry(B, T3, None)]}
    merged = merged_library(tmp_path, plan)
    assert merged.runs == [[0, 1]]
    with reopened(merged.root):
        pass
    check_split(merged)
    with open_db(merged.root) as db:
        assert [row[0] for row in db.execute("SELECT hash FROM versions WHERE occurrence_id=1 ORDER BY captured_at")] == [sha(A), sha(B)]


def test_sc11_count_the_diagnostic_counts_the_version_left_without_history(tmp_path):
    plan = {"files": [entry(A, T1, T2, no_history=True), entry(B, T3, None)]}
    merged = merged_library(tmp_path, plan)
    assert report(merged.root)[3] == "left as a version, history incomplete: 1"
    with reopened(merged.root):
        pass
    assert report(merged.root) == ["would split: 0 documents", "split: 0 documents", "versions moved: 0", "left as a version, history incomplete: 1"]


# --- SC-10: the diagnostic reports counts only ---------------------------------------------------------------------------------------

REPORT_LINE = re.compile(r"^[a-z ,:()]+: \d+( documents?)?$")


def report(root):
    """`python scripts/document_splits.py <database>`: the four lines it prints, after checking it exited 0 and held to the contract's shape."""
    done = subprocess.run([sys.executable, str(SCRIPT), str(root / "inventory.sqlite3")], capture_output=True, text=True, check=False)
    assert done.returncode == 0 and done.stderr == ""
    lines = done.stdout.splitlines()
    assert len(lines) == 4 and all(REPORT_LINE.match(line) for line in lines)
    return lines


def test_sc10_the_diagnostic_reports_counts_only_before_and_after_the_upgrade(tmp_path):
    merged = merged_library(tmp_path, standard(name="zz-unique-name.pdf"))
    database = merged.root / "inventory.sqlite3"
    stamp, content = database.stat().st_mtime_ns, database.read_bytes()
    before = report(merged.root)
    assert before == ["would split: 1 document", "split: 0 documents", "versions moved: 2", "left as a version, history incomplete: 0"]
    assert database.stat().st_mtime_ns == stamp and database.read_bytes() == content  # Opened read-only: not a byte changed.
    with reopened(merged.root):
        pass
    after_content = (merged.root / "inventory.sqlite3").read_bytes()
    after = report(merged.root)
    assert after == ["would split: 0 documents", "split: 1 document", "versions moved: 2", "left as a version, history incomplete: 0"]
    assert (merged.root / "inventory.sqlite3").read_bytes() == after_content
    with open_db(merged.root) as db:
        secrets = {"zz-unique-name", "SYNTH", "Bank", "Supported metadata", "2026"}
        secrets |= {row[0] for row in db.execute("SELECT relative_path FROM managed_files")} | {row[0] for row in db.execute("SELECT path_key FROM occurrences")}
    for text in ("\n".join(before), "\n".join(after)):
        assert not any(secret in text for secret in secrets | set(merged.hashes))
        assert not re.search(r"[0-9a-f]{16}", text)


def test_sc10_the_diagnostic_prints_all_four_lines_for_a_library_that_never_merged(tmp_path):
    with reopened(tmp_path / "managed"):
        pass
    assert report(tmp_path / "managed") == ["would split: 0 documents", "split: 0 documents", "versions moved: 0", "left as a version, history incomplete: 0"]


# --- SC-12: a merged-in version whose bytes exist elsewhere ---------------------------------------------------------------------------

def test_sc12_a_merged_in_version_whose_bytes_exist_elsewhere_keeps_its_same_bytes_link(tmp_path):
    merged = merged_library(tmp_path, standard(duplicate=1))
    with reopened(merged.root):
        pass
    owner = check_split(merged)
    with open_db(merged.root) as db:
        links = [tuple(row) for row in db.execute("SELECT occurrence_id,other_occurrence_id,reason FROM occurrence_links")]
    assert len(links) == 1 and links[0][2] == "same_bytes" and set(links[0][:2]) == {owner[1], merged.other}
    assert links[0][0] < links[0][1]


def test_cr1_2_a_link_between_two_merged_documents_names_the_pieces_that_share_a_file(tmp_path):
    """Code review round 1, finding 2: document 1 is A, B, C and copy.pdf is B, D, both split. The link made when B arrived twice must end
    on the two pieces holding B, though neither side's current file is the other's."""
    later = b"synthetic later copy D"
    merged = merged_library(tmp_path, standard(copy=[entry(B, T3, T4), entry(later, T5, None)]))
    twin = merged.copies[0]
    assert len(merged.copies) == 2 and twin != merged.ids[1]
    with open_db(merged.root) as db:
        assert [tuple(row) for row in db.execute("SELECT occurrence_id,other_occurrence_id,reason FROM occurrence_links")] == [(1, twin, "same_bytes")]
        assert db.execute("SELECT count(*) FROM versions WHERE occurrence_id=?", (twin,)).fetchone()[0] == 2
    with reopened(merged.root):
        pass
    owner = check_split(merged, expected_new=3)
    with open_db(merged.root) as db:
        b_copy = db.execute("SELECT occurrence_id FROM versions v JOIN occurrences o ON o.id=v.occurrence_id WHERE v.hash=? AND o.relative_path='copy.pdf'", (sha(B),)).fetchone()[0]
        assert b_copy == twin and db.execute("SELECT count(*) FROM versions WHERE occurrence_id=?", (twin,)).fetchone()[0] == 1
        links = [tuple(row) for row in db.execute("SELECT occurrence_id,other_occurrence_id,reason FROM occurrence_links")]
    assert links == [(min(owner[1], twin), max(owner[1], twin), "same_bytes")]


def test_cr1_2_a_same_bytes_link_with_no_shared_file_left_is_dropped(tmp_path):
    """The link names a merged document and one that shares no file with any of its pieces: no pair, so no link."""
    merged = merged_library(tmp_path, standard(duplicate=1))
    other = merged.other
    with open_db(merged.root) as db:
        with db:
            db.execute("INSERT INTO blobs VALUES(?,?,?)", (sha(b"unrelated"), 9, T9))
            db.execute("UPDATE versions SET hash=? WHERE occurrence_id=?", (sha(b"unrelated"), other))
            db.execute("UPDATE occurrences SET current_hash=? WHERE id=?", (sha(b"unrelated"), other))
    merged.before = snapshot(merged.root)
    with sqlite3.connect(merged.root / "inventory.sqlite3") as db:
        storage.apply_migrations(db, SPLIT_STEP - 1)
    with open_db(merged.root) as db:
        assert db.execute("SELECT count(*) FROM occurrence_links").fetchone()[0] == 0


# --- SC-13, SC-14: once, and the Inbox path ---------------------------------------------------------------------------------------

def test_sc13_the_repair_runs_once_and_changes_nothing_in_a_library_that_never_merged(tmp_path):
    merged = merged_library(tmp_path, standard())
    with reopened(merged.root):
        pass
    first = dump(merged.root)
    for _ in range(2):
        with reopened(merged.root):
            pass
        assert dump(merged.root) == first
    assert user_version(merged.root) == len(storage.MIGRATIONS)
    check_split(merged)
    # A library whose files were each their own document: the step changes no row.
    apart = merged_library(tmp_path / "apart", {"merge": False, "files": [entry(A, T1, T2, statement=3), entry(B, T3, T4, stub=True)]})
    assert apart.runs == [[0], [1]] and len(set(apart.ids)) == 2
    before = dump(apart.root, without=("document_splits",))
    with sqlite3.connect(apart.root / "inventory.sqlite3") as db:  # The step alone: opening the store also runs the startup recovery.
        storage.apply_migrations(db, SPLIT_STEP - 1)
    assert user_version(apart.root) == len(storage.MIGRATIONS)
    assert dump(apart.root, without=("document_splits",)) == before


def test_sc14_the_newest_file_still_in_the_inbox_keeps_the_inbox_path(tmp_path):
    plan = {"files": [entry(A, T1, T2, statement=3), entry(B, T3, T4, stub=True), entry(C, T5, None, reading=True)]}
    merged = merged_library(tmp_path, plan)
    with reopened(merged.root) as store:
        owner = check_split(merged)
        a, b, c = owner[0], owner[1], owner[2]
        with store.connection() as db:
            keys = inbox_keys(db, owner)
        assert keys[2] == ("document.pdf", "present")
        assert keys[0] == (f"document.pdf{RELEASED_PATH}{a}", "organized") and keys[1] == (f"document.pdf{RELEASED_PATH}{b}", "organized")
        assert (store.library.inbox / "document.pdf").read_bytes() == C
        assert store.job(inbox_scan(store))["counts"] == {"unchanged": 1}
        assert store.documents(limit=100)["total"] == 3
        # Once C is filed, another file under the name is a new document (specs/inbox-document-identity FR-01).
        store.library.organize(c, merged.hashes[2], *FILED, merchant="Bank", document_date="2026-10-31")
        (store.library.inbox / "document.pdf").write_bytes(b"synthetic later file D")
        assert store.job(inbox_scan(store))["counts"] == {"captured": 1}
        assert store.documents(limit=100)["total"] == 4


def test_sc14_already_released(tmp_path):
    """Capture since 3466ebb may already have released document 1 for a later file D: D holds the bare key. The upgrade must succeed, D keeps the
    key, every piece of document 1 takes a released key built from the base, and dropping C's bytes again finds C's piece unchanged."""
    later = b"synthetic later file D"
    merged = merged_library(tmp_path, standard(released=later))
    d = merged.other
    with open_db(merged.root) as db:
        assert db.execute("SELECT path_key FROM occurrences WHERE id=1").fetchone()[0] == f"document.pdf{RELEASED_PATH}1"
        assert db.execute("SELECT path_key FROM occurrences WHERE id=?", (d,)).fetchone()[0] == "document.pdf"
    with reopened(merged.root) as store:
        owner = check_split(merged)
        with store.connection() as db:
            keys = inbox_keys(db, owner)
            assert db.execute("SELECT path_key,source_status FROM occurrences WHERE id=?", (d,)).fetchone()[:] == ("document.pdf", "organized")
        assert all(key == (f"document.pdf{RELEASED_PATH}{owner[run]}", "organized") for run, key in keys.items())
        assert keys[0][0] == f"document.pdf{RELEASED_PATH}1"
        (store.library.inbox / "document.pdf").write_bytes(C)
        assert store.job(inbox_scan(store))["counts"] == {"unchanged": 1}
        assert store.documents(limit=100)["total"] == 4
    with open_db(merged.root) as db:
        assert db.execute("SELECT count(*) FROM occurrences WHERE path_key='document.pdf'").fetchone()[0] == 1


# --- the step and its constant ------------------------------------------------------------------------------------------------------

def test_merged_in_constant_finds_the_versions_the_step_moves(tmp_path):
    merged = merged_library(tmp_path, standard())
    with open_db(merged.root) as db:
        found = {(row["occurrence_id"], row["hash"]) for row in db.execute(MERGED_IN)}
    assert found == {(1, merged.hashes[1]), (1, merged.hashes[2])}
    shared = " ".join(MERGED_IN.split())
    assert shared.endswith(" WHERE run > 0")
    assert shared[: -len(" WHERE run > 0")] in " ".join(MIGRATION.read_text().split())  # The step repeats the query, since a migration can't import.
    with reopened(merged.root):
        pass
    with open_db(merged.root) as db:
        moved = {(row["from_document_id"], row["hash"]) for row in db.execute("SELECT s.from_document_id,v.hash FROM document_splits s JOIN versions v ON v.occurrence_id=s.document_id")}
    assert moved == found


def test_coverage_every_table_naming_a_document_is_moved_by_the_step_or_stays(tmp_path):
    """A table added later that names a document must be moved by 080 or named here as staying with the first document."""
    with reopened(tmp_path / "managed"):  # A new library at the latest schema.
        pass
    with open_db(tmp_path / "managed") as db:
        found = set(document_columns(db))
        for table in VERSION_TABLES:
            assert {"document_id", "blob_hash"} <= {row[1] for row in db.execute(f'PRAGMA table_info("{table}")')}
    known = {"versions", "occurrences", *VERSION_TABLES, *OTHER_TABLES, *STAYING}
    assert found <= known, f"not handled by 080 and not named as staying: {sorted(found - known)}"
    text = MIGRATION.read_text()
    for table in ("versions", *VERSION_TABLES, *OTHER_TABLES):
        assert re.search(rf"(UPDATE|DELETE FROM|INSERT OR IGNORE INTO) {table}\b", text), f"080 does not touch {table}"
