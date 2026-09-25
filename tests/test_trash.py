from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from home_manager.api import create_app
from home_manager.finance import Ledger
from home_manager.scanner import ScanLimits
from home_manager.storage import now
from home_manager.trash import empty, cleanup
from test_managed_library import library, scan


def capture(store, source, name, content=b"date,amount\n2026-09-24,25.00\n"):
    original = source / "2026" / "09" / name
    original.write_bytes(content)
    scan(store, source)
    return next(doc for doc in store.documents(source)["items"] if doc["relative_path"].endswith(name))


def trash(store, source, doc):
    store.library_action(source, doc["id"], doc["current_hash"], "trash")


def test_empty_trash_preserves_live_duplicates_and_removes_all_versions(library):
    store, source = library
    first = capture(store, source, "first.csv")
    second = capture(store, source, "second.csv")
    old_path = store.library.path(first["managed_path"])
    first = capture(store, source, "first.csv", b"date,amount\n2026-09-25,99.00\n")
    new_path = store.library.path(first["managed_path"])
    trash(store, source, first)
    assert empty(store, source) == {"deleted": 1, "cleanup_pending": 0}
    assert not old_path.exists() and not new_path.exists()
    assert store.blob_path(second["current_hash"]).exists()
    assert not store.blob_path(first["current_hash"]).exists()
    assert store.documents(source)["total"] == 1
    assert store.documents(source, folder="trash")["total"] == 0
    assert (source / "2026" / "09" / "first.csv").exists()
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    trash(store, source, second)
    assert empty(store, source)["deleted"] == 1
    assert not store.blob_path(second["current_hash"]).exists()
    assert empty(store, source)["deleted"] == 0


def test_empty_trash_removes_readings_artifacts_and_ledger(library):
    store, source = library
    doc = capture(store, source, "read.csv")
    run_id = "a" * 32
    folder = store.root / "extracted" / run_id
    folder.mkdir(parents=True)
    (folder / "preview.png").write_bytes(b"preview")
    with store.connection() as db:
        db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at) VALUES(?,?,'test','{}','succeeded',?,?)",
                   (run_id, doc["current_hash"], now(), now()))
        db.execute("INSERT INTO receipts(document_id,blob_hash,purchase_date,total_minor,currency,review_status,created_at,updated_at) VALUES(?,?,'2026-09-24',2500,'USD','verified',?,?)",
                   (doc["id"], doc["current_hash"], now(), now()))
        receipt_id = db.execute("SELECT id FROM receipts").fetchone()[0]
        db.execute("INSERT INTO receipt_items(receipt_id,position,description,review_status) VALUES(?,1,'Lunch','verified')", (receipt_id,))
        db.execute("INSERT INTO financial_evidence_links(record_type,record_id,document_id,blob_hash,parse_run_id,source_key,locator_json,created_at) VALUES('receipt',?,?,?,?,?,'{}',?)",
                   (receipt_id, doc["id"], doc["current_hash"], run_id, "test", now()))
    trash(store, source, doc)
    assert empty(store, source)["deleted"] == 1
    assert not folder.exists()
    with store.connection() as db:
        for table in ("receipts", "receipt_items", "financial_evidence_links", "parse_runs", "versions", "occurrences", "trash_cleanup"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_empty_trash_keeps_shared_imported_transactions(library):
    store, source = library
    content = b"Date,Description,Amount\n2026-09-24,COFFEE,-5.00\n"
    first = capture(store, source, "first.csv", content)
    second = capture(store, source, "second.csv", content)
    ledger = Ledger(store)
    account = ledger.create_account("Bank", "checking", "USD")
    ledger.import_transactions(first["id"], account["id"])
    ledger.import_transactions(second["id"], account["id"])
    trash(store, source, first)
    empty(store, source)
    with store.connection() as db:
        transaction = db.execute("SELECT * FROM transactions").fetchone()
        assert transaction["source_document_id"] == second["id"]
        assert db.execute("SELECT count(*) FROM financial_evidence_links").fetchone()[0] > 0
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    trash(store, source, second)
    empty(store, source)
    with store.connection() as db:
        assert not db.execute("SELECT * FROM transactions").fetchall()


def publish_test_statement(ledger, doc):
    return ledger.publish_statement({
        "statement_type": "bank", "institution": "Bank", "last_four": None, "currency": "USD",
        "period_start": "2026-09-01", "period_end": "2026-09-30", "summary": {}, "issues": [],
        "locator": {"line_ids": ["line-1"]},
        "transactions": [{"posted_date": "2026-09-24", "description": "COFFEE", "amount_minor": -500,
                          "currency": "USD", "locator": {"line_ids": ["line-2"]}}],
    }, {"document_id": doc["id"], "blob_hash": doc["current_hash"],
        "source_key": f"extraction:{doc['id']}", "run_id": f"statement-{doc['id']}"}, "proposed")["id"]


@pytest.mark.parametrize("import_first", [True, False])
def test_deleting_statement_preserves_transaction_supported_by_csv(library, import_first):
    store, source = library
    csv = capture(store, source, "transactions.csv", b"Date,Description,Amount\n2026-09-24,COFFEE,-5.00\n")
    statement = capture(store, source, "statement.pdf", b"synthetic statement")
    ledger = Ledger(store)
    account = ledger.create_account("Bank", "checking", "USD")
    if import_first:
        ledger.import_transactions(csv["id"], account["id"])
    statement_id = publish_test_statement(ledger, statement)
    if not import_first:
        ledger.import_transactions(csv["id"], account["id"])
    with store.connection() as db:
        [before] = db.execute("SELECT * FROM transactions").fetchall()
        assert before["statement_id"] == statement_id
        assert db.execute("SELECT count(*) FROM financial_evidence_links WHERE record_type='transaction'").fetchone()[0] == 2
    trash(store, source, statement)
    assert empty(store, source) == {"deleted": 1, "cleanup_pending": 0}
    transaction = ledger.record("transaction", before["id"])
    assert transaction["source_document_id"] == csv["id"]
    assert transaction["statement_id"] is None
    assert transaction["amount_minor"] == -500
    with store.connection() as db:
        assert not db.execute("SELECT * FROM statements").fetchall()
        assert {row[0] for row in db.execute("SELECT document_id FROM financial_evidence_links WHERE record_type='transaction'")} == {csv["id"]}
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    # Removing the last independent source still deletes the transaction.
    trash(store, source, csv)
    empty(store, source)
    with store.connection() as db:
        assert not db.execute("SELECT * FROM transactions").fetchall()


@pytest.mark.parametrize("decision", ["verified", "rejected"])
def test_duplicate_statement_keeps_transactions_and_review_propagation(library, decision):
    store, source = library
    first = capture(store, source, "statement.pdf", b"synthetic statement")
    duplicate = capture(store, source, "statement-copy.pdf", b"synthetic statement")
    ledger = Ledger(store)
    statement_id = publish_test_statement(ledger, first)
    transaction_id = ledger.record("statement", statement_id)["transactions"][0]["id"]
    trash(store, source, first)
    empty(store, source)
    retained = ledger.record("statement", statement_id)
    assert retained["document_id"] == duplicate["id"]
    assert [row["id"] for row in retained["transactions"]] == [transaction_id]
    assert retained["transactions"][0]["source_document_id"] == duplicate["id"]
    ledger.review("statement", statement_id, decision)
    assert ledger.record("transaction", transaction_id)["review_status"] == decision
    with store.connection() as db:
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    trash(store, source, duplicate)
    empty(store, source)
    with store.connection() as db:
        assert not db.execute("SELECT * FROM statements").fetchall()
        assert not db.execute("SELECT * FROM transactions").fetchall()
        assert not db.execute("PRAGMA foreign_key_check").fetchall()


def test_edited_files_block_deletion_and_failed_cleanup_can_retry(library, monkeypatch):
    store, source = library
    doc = capture(store, source, "edited.csv")
    path = store.library.path(doc["managed_path"])
    original = path.read_bytes()
    path.write_bytes(b"edited")
    trash(store, source, doc)
    with pytest.raises(ValueError, match="edited"):
        empty(store, source)
    assert store.documents(source, folder="trash")["total"] == 1
    path.write_bytes(original)
    unlink = Path.unlink
    def locked(self, *args, **kwargs):
        if self == path:
            raise PermissionError("open elsewhere")
        return unlink(self, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", locked)
    assert empty(store, source) == {"deleted": 1, "cleanup_pending": 1}
    assert path.exists()
    monkeypatch.setattr(Path, "unlink", unlink)
    assert cleanup(store) == 0
    assert not path.exists()


def test_empty_trash_api_requires_confirmation(tmp_path):
    app = create_app(tmp_path / "control", "test-token", limits=ScanLimits(stability_seconds=0))
    source = tmp_path / "source"
    (source / "2026" / "09").mkdir(parents=True)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        app.state.manager.configure(str(source), str(tmp_path / "managed"))
        doc = capture(app.state.manager.store, source, "test.csv")
        trash(app.state.manager.store, source, doc)
        assert client.post("/api/trash/empty", json={"confirmed": True}).status_code == 401
        headers = {"Authorization": "Bearer test-token"}
        for body in ({}, {"confirmed": False}):
            assert client.post("/api/trash/empty", headers=headers, json=body).status_code == 422
        response = client.post("/api/trash/empty", headers=headers, json={"confirmed": True})
        assert response.status_code == 200, response.text
        assert response.json() == {"deleted": 1, "cleanup_pending": 0}
