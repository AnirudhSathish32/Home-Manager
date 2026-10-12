"""Synthetic Processing states for Processing v2's browser test and ui_shots.py (design-system/home-manager/phase2-system-plan.md
"Seeding"): a failed reading, a failed model run, a watched folder, and two ledger health warnings, one on a record that
opens (a statement whose balances don't meet) and one that doesn't (a note naming a deleted record). Synthetic data only."""
from datetime import date, timedelta

from conftest import inbox_scan
from home_manager.documents.receipt_service import ReceiptService
from home_manager.models.vision import VisionConfig


def seed_processing(manager, folder):
    """folder: an empty scratch folder to watch. Returns {"old_statement_doc": id} for the statement health warning."""
    store, now = manager.store, date.today()
    inbox_scan(store, {"bad-scan.jpg": b"not an image", "old-statement.pdf": b"synthetic old checking statement"})
    docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in store.documents()["items"]}
    # A failed text reading: the image can't be decoded, so no model is asked (tests/test_receipts.py).
    service = ReceiptService(store)
    run_id, _ = service.enqueue(docs["bad-scan.jpg"]["id"], vision=VisionConfig(base_url="http://127.0.0.1:9/v1", model="synthetic-vision"))
    service.run(run_id)
    started = (now - timedelta(days=1)).isoformat() + "T15:31:00+00:00"
    with store.connection() as db:
        # A failed model request, as the recorder writes an HTTP 500 (tests/test_sampling.py).
        db.execute("INSERT INTO model_runs(task,model_id,base_url,started_at,finished_at,total_ms,metrics_source,input_bytes,output_bytes,status,error_category) "
                   "VALUES('transcription','synthetic-vision','http://127.0.0.1:9/v1',?,?,120,'estimated',2048,0,'failed','http_500')", (started, started))
        # A review note naming a transaction that no longer exists (orphan_reference; no page to open).
        db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,created_at) VALUES('transaction',99999,'proposed','verified','t')")
        # A two-year-old statement whose one line doesn't take its opening balance to its closing one (statement_balance).
        account = db.execute("SELECT id FROM accounts ORDER BY id LIMIT 1").fetchone()
        account_id = account[0] if account else db.execute(
            "INSERT INTO accounts(institution,account_type,currency,display_name,created_at,updated_at) VALUES('First Local Bank','checking','USD','Household checking','t','t')").lastrowid
        old = now.replace(year=now.year - 2, day=1)
        doc = docs["old-statement.pdf"]
        statement = db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_start,period_end,opening_balance_minor,closing_balance_minor,"
                               "currency,review_status,created_at,updated_at) VALUES(?,?,?,'bank',?,?,100000,90000,'USD','verified','t','t')",
                               (account_id, doc["id"], doc["current_hash"], old.isoformat(), (old + timedelta(days=27)).isoformat())).lastrowid
        db.execute("INSERT INTO transactions(account_id,statement_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,"
                   "source_fingerprint,created_at,updated_at) VALUES(?,?,?,'CORNER HARDWARE',-2500,'USD','purchase','import','verified','seed-processing-old',"
                   "'t','t')", (account_id, statement, (old + timedelta(days=9)).isoformat()))
    manager.add_source(str(folder), "Scanner", True)
    return {"old_statement_doc": doc["id"]}
