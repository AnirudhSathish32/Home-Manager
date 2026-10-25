"""A failed schema upgrade keeps earlier steps and the pre-upgrade copy, and the app still starts and says what happened."""

import re
import sqlite3

import pytest

from home_manager.app.manager import Manager
from home_manager.library import storage
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import MIGRATIONS, MigrationError, Store, readable_database

LATEST = MIGRATIONS[-1][0]
NEXT = LATEST + 1


def version_of(root):
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        return db.execute("PRAGMA user_version").fetchone()[0]
    finally:
        db.close()


def tables(root):
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        return {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
    finally:
        db.close()


@pytest.fixture
def next_step(tmp_path, monkeypatch):
    """next_step(text) adds one more schema script after the real ones (or rewrites it) and returns its path."""
    script = tmp_path / f"{NEXT:03d}_test_step.sql"

    def add(text):
        script.write_text(text)
        monkeypatch.setattr(storage, "MIGRATIONS", [*MIGRATIONS, (NEXT, script)])
        return script
    return add


def test_a_failing_step_keeps_earlier_steps_and_the_pre_upgrade_copy(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    next_step(f"CREATE TABLE half_done(x);\nTHIS IS NOT SQL;\nPRAGMA user_version={NEXT};")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    error = failure.value
    assert (error.number, error.version) == (NEXT, LATEST)
    assert f"step {NEXT:03d}" in str(error) and error.snapshot.name in str(error)
    assert error.snapshot == root / f"inventory.before-v{NEXT}.sqlite3" and readable_database(error.snapshot)
    assert version_of(root) == LATEST
    assert "half_done" not in tables(root)  # The failed step left nothing behind.
    # Fixed script: the next start resumes and keeps the copy it already had.
    next_step(f"CREATE TABLE half_done(x);\nPRAGMA user_version={NEXT};")
    Store(root).close()
    assert version_of(root) == NEXT and "half_done" in tables(root)
    assert error.snapshot.exists()


def receipt_with_lines(store):
    """One receipt with an item and a reward: rows that cascade from receipts."""
    stamp, digest = "2026-09-30T00:00:00+00:00", "a" * 64
    with store.connection() as db:
        db.execute("INSERT INTO blobs VALUES(?,1,?)", (digest, stamp))
        db.execute("INSERT INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','root','completed',?,?)", (stamp, stamp))
        db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                   "VALUES('root','r.png','r.png',?,?,?,'job')", (digest, stamp, stamp))
        db.execute("INSERT INTO receipts(document_id,blob_hash,currency,review_status,created_at,updated_at) VALUES(1,?,'USD','verified',?,?)", (digest, stamp, stamp))
        db.execute("INSERT INTO receipt_items(receipt_id,position,description,review_status) VALUES(1,1,'MILK','verified')")
        db.execute("INSERT INTO receipt_rewards(receipt_id,position,kind,description,locator_json) VALUES(1,1,'earned','points','{}')")


def counts(root, *names):
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        return [db.execute(f"SELECT count(*) FROM {name}").fetchone()[0] for name in names]
    finally:
        db.close()


def test_a_table_rebuild_keeps_the_rows_that_cascade_from_it(tmp_path, next_step):
    # SQLite's rebuild procedure (new table, copy, drop, rename): with foreign keys on, the DROP would delete the receipt's lines.
    root = tmp_path / "managed"
    store = Store(root)
    receipt_with_lines(store)
    with store.connection() as db:
        create = re.sub(r'^CREATE TABLE\s+"?receipts"?', "CREATE TABLE receipts_new", db.execute("SELECT sql FROM sqlite_schema WHERE name='receipts'").fetchone()[0])
    store.close()
    next_step(f"{create};\nINSERT INTO receipts_new SELECT * FROM receipts;\nDROP TABLE receipts;\n"
              f"ALTER TABLE receipts_new RENAME TO receipts;\nPRAGMA user_version={NEXT};")
    store = Store(root)
    try:
        with store.connection() as db:
            assert db.execute("PRAGMA foreign_keys").fetchone()[0] == 1  # Back on for the app.
    finally:
        store.close()
    assert version_of(root) == NEXT
    assert counts(root, "receipts", "receipt_items", "receipt_rewards") == [1, 1, 1]


def test_a_step_that_breaks_references_is_rolled_back(tmp_path, next_step):
    root = tmp_path / "managed"
    store = Store(root)
    receipt_with_lines(store)
    store.close()
    next_step(f"DELETE FROM receipts;\nPRAGMA user_version={NEXT};")  # Would orphan the item and the reward.
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number == NEXT and "broken references" in str(failure.value.__cause__)
    assert version_of(root) == LATEST
    assert counts(root, "receipts", "receipt_items", "receipt_rewards") == [1, 1, 1]


def test_a_step_that_does_not_record_its_version_is_refused(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    next_step("CREATE TABLE forgot_version(x);")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number == NEXT
    assert version_of(root) == LATEST
    assert "forgot_version" not in tables(root)  # Checked before the step commits.


def test_an_unreadable_pre_upgrade_copy_is_replaced(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    copy = root / f"inventory.before-v{NEXT}.sqlite3"
    copy.write_bytes(b"damaged")
    next_step(f"PRAGMA user_version={NEXT};")
    Store(root).close()
    assert readable_database(copy)
    db = sqlite3.connect(copy)
    try:
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
    finally:
        db.close()


def test_a_damaged_database_is_not_upgraded(tmp_path, next_step):
    root = tmp_path / "managed"
    Store(root).close()
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        db.execute("PRAGMA journal_mode=DELETE")
        db.execute("CREATE TABLE filler(id INTEGER PRIMARY KEY, body TEXT)")
        db.execute("CREATE INDEX filler_body ON filler(body)")
        db.executemany("INSERT INTO filler(body) VALUES(?)", [(f"row {i} " * 20,) for i in range(2000)])
        db.commit()
        page = db.execute("PRAGMA page_size").fetchone()[0]
    finally:
        db.close()
    data = bytearray((root / "inventory.sqlite3").read_bytes())
    for start in range(len(data) - 6 * page, len(data), page):  # Scribble over the last pages (filler rows and index).
        data[start + 100:start + page - 100] = b"\xff" * (page - 200)
    (root / "inventory.sqlite3").write_bytes(bytes(data))
    next_step(f"CREATE TABLE never(x);\nPRAGMA user_version={NEXT};")
    with pytest.raises(MigrationError) as failure:
        Store(root)
    assert failure.value.number is None and "integrity check" in str(failure.value)
    assert version_of(root) == LATEST
    assert not (root / f"inventory.before-v{NEXT}.sqlite3").exists()


def test_056_makes_pensions_income_and_keeps_values_and_forms():
    """Investment kinds made specific (docs/planning.md "Kinds made specific"): rebuilt tables keep their rows and take the new values."""
    db = sqlite3.connect(":memory:")
    try:
        for number, script in MIGRATIONS:
            if number < 56:
                db.executescript(script.read_text())
        db.execute("INSERT INTO blobs(hash,size,created_at) VALUES(?,1,'t')", ("a" * 64,))
        account = db.execute("INSERT INTO investment_accounts(kind,name,currency,source,created_at,updated_at) VALUES('pension','Pension','USD','manual','t','t')").lastrowid
        db.execute("INSERT INTO investment_valuations(account_id,as_of,value_minor,source,review_status,created_at,updated_at) VALUES(?,'2026-09-01',5,'manual','verified','t','t')",
                   (account,))
        form = db.execute("INSERT INTO tax_forms(institution,tax_year,currency,blob_hash,review_status,created_at,updated_at) VALUES('X',2026,'USD',?,'verified','t','t')",
                          ("a" * 64,)).lastrowid
        db.execute("INSERT INTO tax_form_boxes(form_id,form,box,label,amount_minor) VALUES(?,'1099-INT','1','Interest',100)", (form,))
        db.commit()
        storage.apply_migrations(db, 55)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        assert db.execute("SELECT value_model FROM investment_kinds WHERE key='pension'").fetchone()[0] == "income"
        assert db.execute("SELECT value_minor FROM investment_valuations WHERE account_id=?", (account,)).fetchone()[0] == 5
        assert db.execute("SELECT yield_bp,reinvest,beneficiary FROM investment_accounts WHERE id=?", (account,)).fetchone() == (0, 1, None)
        assert db.execute("SELECT count(*) FROM tax_form_boxes WHERE form_id=?", (form,)).fetchone()[0] == 1
        assert db.execute("SELECT fixed_bp,inflation_semiannual_bp FROM ibond_rates WHERE period_start='2023-11-01'").fetchone() == (130, 197)
        db.execute("INSERT INTO tax_form_boxes(form_id,form,box,label,amount_minor) VALUES(?,'1099-Q','1','Gross distribution',100)", (form,))
        db.execute("INSERT INTO investment_valuations(account_id,as_of,value_minor,source,review_status,created_at,updated_at) VALUES(?,'2026-10-01',5,'quote','verified','t','t')",
                   (account,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO price_quotes(source,symbol,currency,as_of,price,fetched_at) VALUES('elsewhere','BTC','USD','2026-10-01','1','t')")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO ibond_rates(period_start,fixed_bp,inflation_semiannual_bp) VALUES('2026-11-15',0,0)")
    finally:
        db.close()


def test_064_drops_the_dead_columns_and_keeps_the_rows():
    """The 2026-09-30 audit's dead columns (docs/development.md "Database checks") go; the rows and what links to them stay."""
    db = sqlite3.connect(":memory:")
    try:
        for number, script in MIGRATIONS:
            if number < 64:
                db.executescript(script.read_text())
        db.execute("INSERT INTO blobs(hash,size,created_at) VALUES(?,1,'t')", ("a" * 64,))
        db.execute("INSERT INTO jobs(id,source_root,year,month,status,created_at,updated_at) VALUES('job','root',2026,9,'completed','t','t')")
        db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,folder_year,folder_month,current_hash,first_seen,last_seen,last_job) "
                   "VALUES('root','r.png','r.png',2026,9,?,'t','t','job')", ("a" * 64,))
        account = db.execute("INSERT INTO investment_accounts(kind,name,currency,source,created_at,updated_at) VALUES('brokerage','B','USD','manual','t','t')").lastrowid
        first = db.execute("INSERT INTO investment_events(account_id,event_date,event_type,amount_minor,document_id,review_status,created_at) "
                           "VALUES(?,'2026-09-01','dividend',500,1,'verified','t')", (account,)).lastrowid
        db.execute("INSERT INTO investment_events(account_id,event_date,event_type,amount_minor,reverses_event_id,review_status,created_at) "
                   "VALUES(?,'2026-09-02','dividend',-500,?,'verified','t')", (account, first))
        db.commit()
        storage.apply_migrations(db, 63)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST

        def columns(table):
            return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        assert not {"year", "month"} & columns("jobs") and not {"folder_year", "folder_month"} & columns("occurrences")
        assert "reverses_event_id" not in columns("investment_events")
        assert db.execute("SELECT count(*) FROM investment_events WHERE account_id=?", (account,)).fetchone()[0] == 2
        assert db.execute("SELECT document_id FROM investment_events WHERE id=?", (first,)).fetchone()[0] == 1
        assert db.execute("SELECT strict FROM pragma_table_list WHERE name='investment_events'").fetchone()[0] == 1
        assert {"investment_events_account", "investment_events_confirmation", "investment_events_source"} <= \
            {row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='index' AND tbl_name='investment_events'")}
    finally:
        db.close()


def test_065_drops_the_doubled_type_from_generated_account_names_only():
    """"Household checking checking" becomes "Household checking"; a name the user chose stays as it is."""
    db = sqlite3.connect(":memory:")
    try:
        for number, script in MIGRATIONS:
            if number < 65:
                db.executescript(script.read_text())
        rows = [("Household checking", "checking", "Household checking checking", None),
                ("Family Savings", "savings", "Family Savings savings 1234", "1234"),
                ("Chase", "checking", "Chase checking", None),  # The type isn't in the institution.
                ("Superchecking", "checking", "Superchecking checking", None),  # Not the type as a word.
                ("Household checking", "savings", "Household checking savings", None),
                ("My credit card", "credit_card", "Groceries card", None)]  # Chosen by the user.
        for institution, kind, name, last_four in rows:
            db.execute("INSERT INTO accounts(institution,account_type,display_name,account_last_four,currency,created_at,updated_at) VALUES(?,?,?,?,'USD','t','t')",
                       (institution, kind, name, last_four))
        db.commit()
        storage.apply_migrations(db, 64)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        assert [row[0] for row in db.execute("SELECT display_name FROM accounts ORDER BY id")] == [
            "Household checking", "Family Savings 1234", "Chase checking", "Superchecking checking", "Household checking savings", "Groceries card"]
    finally:
        db.close()


def test_067_makes_bills_receipts_and_keeps_what_named_them():
    """A bill becomes a receipt with document_kind 'bill' (docs/money.md "Bills and their lines"): its correction, review,
    evidence and family assignment follow it, the payment a person named becomes its verified match, and model-assigned
    housing items wait to be re-sorted."""
    db = sqlite3.connect(":memory:")
    try:
        for number, script in MIGRATIONS:
            if number < 67:
                db.executescript(script.read_text())
        for digest in ("a" * 64, "b" * 64):
            db.execute("INSERT INTO blobs(hash,size,created_at) VALUES(?,1,'t')", (digest,))
        db.execute("INSERT INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','root','completed','t','t')")
        bill_doc, receipt_doc = (db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                                            "VALUES('root',?,?,?,'t','t','job')", (name, name, digest)).lastrowid
                                 for name, digest in (("bill.png", "a" * 64), ("receipt.png", "b" * 64)))
        provider = db.execute("INSERT INTO merchants(canonical_name,normalized_name,created_at,updated_at) VALUES('City Power','CITY POWER','t','t')").lastrowid
        account = db.execute("INSERT INTO accounts(institution,account_type,display_name,currency,created_at,updated_at) "
                             "VALUES('Bank','checking','Bank','USD','t','t')").lastrowid
        payment = db.execute("INSERT INTO transactions(account_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,"
                             "source_fingerprint,created_at,updated_at) VALUES(?,'2026-09-22','CITY POWER',-4500,'USD','purchase','import','verified','f','t','t')",
                             (account,)).lastrowid
        bill = db.execute("INSERT INTO bills(document_id,blob_hash,provider_merchant_id,issue_date,due_date,amount_due_minor,currency,payment_status,"
                          "review_status,created_at,updated_at,payment_transaction_id) VALUES(?,?,?,'2026-09-01','2026-09-20',4500,'USD','paid','verified','t','t',?)",
                          (bill_doc, "a" * 64, provider, payment)).lastrowid
        db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,created_at) VALUES('bill',?,'provider','City Power','CITY PWR','t')", (bill,))
        db.execute("INSERT INTO review_events(record_type,record_id,previous_status,new_status,created_at) VALUES('bill',?,'proposed','verified','t')", (bill,))
        db.execute("INSERT INTO financial_evidence_links(record_type,record_id,document_id,blob_hash,source_key,locator_json,created_at) "
                   "VALUES('bill',?,?,?,'extraction:x','{}','t')", (bill, bill_doc, "a" * 64))
        db.execute("INSERT INTO family_assignments(record_type,record_id,family_record_key,status,updated_at) VALUES('bill',?,'key','unassigned','t')", (bill,))
        receipt = db.execute("INSERT INTO receipts(document_id,blob_hash,currency,review_status,created_at,updated_at) VALUES(?,?,'USD','verified','t','t')",
                             (receipt_doc, "b" * 64)).lastrowid
        for position, (category, source) in enumerate((("housing", "model"), ("housing", "user"), ("groceries", "model")), 1):
            db.execute("INSERT INTO receipt_items(receipt_id,position,description,category,category_source,review_status) VALUES(?,?,'x',?,?,'verified')",
                       (receipt, position, category, source))
        db.commit()
        storage.apply_migrations(db, 66)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        assert db.execute("SELECT count(*) FROM sqlite_schema WHERE name='bills'").fetchone()[0] == 0
        moved = db.execute("SELECT id,document_kind,merchant_id,purchase_date,total_minor,amount_due_minor,due_date FROM receipts WHERE blob_hash=?",
                           ("a" * 64,)).fetchone()
        assert moved[1:] == ("bill", provider, "2026-09-20", 4500, 4500, "2026-09-20")
        assert db.execute("SELECT record_type,record_id,field FROM record_corrections").fetchone() == ("receipt", moved[0], "merchant")
        for table in ("review_events", "financial_evidence_links", "family_assignments"):
            assert db.execute(f"SELECT record_type,record_id FROM {table}").fetchone() == ("receipt", moved[0]), table
        assert db.execute("SELECT transaction_id,review_status FROM transaction_receipt_links WHERE receipt_id=?", (moved[0],)).fetchone() == (payment, "verified")
        assert [row[0] for row in db.execute("SELECT category_source FROM receipt_items WHERE receipt_id=? ORDER BY position", (receipt,))] == [
            "legacy", "user", "model"]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        db.close()


DOCUMENT_FORM_COLUMNS = {"receipts": ("receipt_kind", "details_json", "pending_details_json", "printed_total_minor"),
                         "receipt_items": ("details_json",), "income_records": ("details_json",), "income_lines": ("details_json",),
                         "statements": ("details_json",)}


def pre_document_forms(db):
    """A library at the last version before document forms (069): a fuel-like receipt with a PUMP 17 item, a dining
    receipt, a pay stub with a line and a bank statement with transactions. Returns their ids."""
    for digest in ("a" * 64, "b" * 64, "c" * 64, "d" * 64):
        db.execute("INSERT INTO blobs(hash,size,created_at) VALUES(?,1,'t')", (digest,))
    db.execute("INSERT INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','root','completed','t','t')")
    docs = [db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                       "VALUES('root',?,?,?,'t','t','job')", (name, name, digest)).lastrowid
            for name, digest in (("fuel.png", "a" * 64), ("dining.png", "b" * 64), ("stub.png", "c" * 64), ("bank.pdf", "d" * 64))]
    fuel = db.execute("INSERT INTO receipts(document_id,blob_hash,purchase_date,subtotal_minor,tax_minor,total_minor,currency,review_status,"
                      "review_source,created_at,updated_at) VALUES(?,?,'2026-10-01',3786,0,3786,'USD','needs_review',NULL,'t','t')",
                      (docs[0], "a" * 64)).lastrowid
    dining = db.execute("INSERT INTO receipts(document_id,blob_hash,purchase_date,subtotal_minor,tax_minor,tip_minor,total_minor,currency,"
                        "review_status,review_source,created_at,updated_at) VALUES(?,?,'2026-10-02',5000,400,900,6300,'USD','verified','user','t','t')",
                        (docs[1], "b" * 64)).lastrowid
    for receipt, position, name, amount, category in ((fuel, 1, "PUMP 17", 0, "transportation"), (fuel, 2, "REG UNL", 3567, "transportation"),
                                                      (fuel, 3, "COFFEE", 219, "dining"), (dining, 1, "PASTA", 6300, "dining")):
        item = db.execute("INSERT INTO receipt_items(receipt_id,position,description,line_total_minor,category,review_status) VALUES(?,?,?,?,?,'proposed')",
                          (receipt, position, name, amount, category)).lastrowid
        if amount:
            db.execute("INSERT INTO category_splits(receipt_id,receipt_item_id,category,amount_minor) VALUES(?,?,?,?)", (receipt, item, category, amount))
    income = db.execute("INSERT INTO income_records(document_id,blob_hash,pay_date,period_start,period_end,gross_pay_minor,net_pay_minor,"
                        "gross_pay_ytd_minor,net_pay_ytd_minor,currency,review_status,pay_frequency,created_at,updated_at) "
                        "VALUES(?,?,'2026-07-03','2026-06-15','2026-06-28',250000,191234,3250000,2486042,'USD','verified',26,'t','t')",
                        (docs[2], "c" * 64)).lastrowid
    db.execute("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,ytd_minor,locator_json) "
               "VALUES(?,1,'Regular','earnings','regular_pay',250000,3250000,'{}')", (income,))
    account = db.execute("INSERT INTO accounts(institution,account_type,display_name,account_last_four,currency,created_at,updated_at) "
                         "VALUES('Synth Bank','checking','Synth Bank checking','6789','USD','t','t')").lastrowid
    statement = db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_start,period_end,opening_balance_minor,"
                           "closing_balance_minor,currency,review_status,created_at,updated_at) "
                           "VALUES(?,?,?,'bank','2026-09-01','2026-09-30',100000,229950,'USD','verified','t','t')",
                           (account, docs[3], "d" * 64)).lastrowid
    for posted, text, amount, kind in (("2026-09-03", "PAYROLL", 250000, "deposit"), ("2026-09-05", "RENT", -120050, "payment")):
        db.execute("INSERT INTO transactions(account_id,statement_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,"
                   "review_status,source_fingerprint,created_at,updated_at) VALUES(?,?,?,?,?,'USD',?,'extraction','verified',?,'t','t')",
                   (account, statement, posted, text, amount, kind, text))
    return {"fuel": fuel, "dining": dining, "income": income, "statement": statement}


def test_070_document_forms_leaves_existing_records_untouched():
    """SC-11 (FR-13): records read before document forms keep every value; receipt kind and the new details are null
    (not general), nothing is queued, and the ledger health check still passes."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for number, script in MIGRATIONS:
            if number < 70:
                db.executescript(script.read_text())
        ids = pre_document_forms(db)
        fuel = ids["fuel"]
        db.commit()
        before = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
                  for table in ("receipts", "receipt_items", "category_splits", "income_records", "income_lines", "statements", "transactions")}
        storage.apply_migrations(db, 69)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        for table, rows in before.items():
            after = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
            assert [{key: row[key] for key in old} for row, old in zip(after, rows)] == rows, table
            for row in after:
                assert all(row[column] is None for column in DOCUMENT_FORM_COLUMNS.get(table, ())), table
        assert db.execute("SELECT count(*) FROM receipt_items WHERE description='PUMP 17'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM extraction_runs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM jobs WHERE status<>'completed'").fetchone()[0] == 0
        from home_manager.finance.health import check_ledger
        assert [problem for problem in check_ledger(db) if problem.severity == "error"] == []
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE receipts SET receipt_kind='pharmacy' WHERE id=?", (fuel,))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE receipts SET printed_total_minor='8.55' WHERE id=?", (fuel,))
        db.execute("UPDATE receipts SET receipt_kind='fuel',printed_total_minor=855 WHERE id=?", (fuel,))
        assert db.execute("SELECT strict FROM pragma_table_list WHERE name='receipts'").fetchone()[0] == 1
    finally:
        db.close()


def test_070_document_forms_record_view_shows_nothing_new(tmp_path):
    """SC-11's last checkpoint: after the upgrade, the record view of a receipt, pay stub and statement read before it
    shows no receipt kind, no details and no check figures."""
    root = tmp_path / "managed"
    Store(root).close()  # A store, whose database is then replaced by one at version 69.
    for name in ("inventory.sqlite3", "inventory.sqlite3-wal", "inventory.sqlite3-shm"):
        (root / name).unlink(missing_ok=True)
    db = sqlite3.connect(root / "inventory.sqlite3")
    db.row_factory = sqlite3.Row
    try:
        for number, script in MIGRATIONS:
            if number < 70:
                db.executescript(script.read_text())
        ids = pre_document_forms(db)
        db.commit()
    finally:
        db.close()
    store = Store(root)
    try:
        from home_manager.finance.ledger import Ledger
        ledger = Ledger(store)
        for record_type, record_id in (("receipt", ids["fuel"]), ("receipt", ids["dining"]), ("income_record", ids["income"]),
                                       ("statement", ids["statement"])):
            record = ledger.record(record_type, record_id)
            assert (record.get("receipt_kind"), record["details"], record["checks"]) == (None, None, []), record_type
        assert all(item["details"] is None for item in ledger.record("receipt", ids["fuel"])["items"])
        assert all(line["details"] is None for line in ledger.record("income_record", ids["income"])["lines"])
    finally:
        store.close()


def pre_bill_kinds(db):
    """A library at the last version before bill kinds (070), as read under typed-extraction-v30: a verified phone bill
    and a rent-like bill in Review whose Trash line's type the user corrected. Returns their ids."""
    for digest in ("e" * 64, "f" * 64):
        db.execute("INSERT INTO blobs(hash,size,created_at) VALUES(?,1,'t')", (digest,))
    db.execute("INSERT INTO jobs(id,source_root,status,created_at,updated_at) VALUES('job','root','completed','t','t')")
    phone_doc, rent_doc = (db.execute("INSERT INTO occurrences(source_root,path_key,relative_path,current_hash,first_seen,last_seen,last_job) "
                                      "VALUES('root',?,?,?,'t','t','job')", (name, name, digest)).lastrowid
                           for name, digest in (("phone.png", "e" * 64), ("rent.png", "f" * 64)))
    provider = db.execute("INSERT INTO merchants(canonical_name,normalized_name,created_at,updated_at) VALUES('Acme Wireless','ACME WIRELESS','t','t')").lastrowid
    landlord = db.execute("INSERT INTO merchants(canonical_name,normalized_name,created_at,updated_at) VALUES('Synth Property','SYNTH PROPERTY','t','t')").lastrowid
    ids = {}
    for name, doc, digest, merchant, total, due, issue, status, source, category, lines in (
            ("phone", phone_doc, "e" * 64, provider, 6799, "2026-09-28", "2026-09-05", "verified", "automatic", "phone & internet",
             (("Unlimited", 4000, "phone & internet", "service"), ("Apple TV+", 999, "subscriptions", "subscription"), ("Taxes and fees", 1800, None, "tax_fee"))),
            ("rent", rent_doc, "f" * 64, landlord, 148842, "2026-10-01", None, "needs_review", None, "housing",
             (("Rent", 145000, "housing", "service"), ("Water", 3842, "utilities", "tax_fee")))):
        receipt = db.execute("INSERT INTO receipts(document_id,blob_hash,merchant_id,purchase_date,total_minor,currency,category,recurrence,review_status,"
                             "review_source,validation_json,document_kind,issue_date,due_date,amount_due_minor,account_last_four,created_at,updated_at) "
                             "VALUES(?,?,?,?,?,'USD',?,'monthly',?,?,'[]','bill',?,?,?,'4821','t','t')",
                             (doc, digest, merchant, due, total, category, status, source, issue, due, total + (1200 if name == "phone" else 0))).lastrowid
        for position, (description, amount, line_category, kind) in enumerate(lines, 1):
            item = db.execute("INSERT INTO receipt_items(receipt_id,position,description,line_total_minor,category,category_source,line_kind,review_status) "
                              "VALUES(?,?,?,?,?,'model',?,?)", (receipt, position, description, amount, line_category, kind,
                                                                 "verified" if status == "verified" else "proposed")).lastrowid
            db.execute("INSERT INTO category_splits(receipt_id,receipt_item_id,category,amount_minor) VALUES(?,?,?,?)",
                       (receipt, item, line_category or category, amount))
        ids[name] = receipt
    # The user's type for the Water line ("line_kind:2"), as Ledger.correct_line keeps it.
    db.execute("INSERT INTO record_corrections(record_type,record_id,field,value,previous,resolved_issues_json,created_at) "
               "VALUES('receipt_item',?,'line_kind:2','usage','tax_fee','[]','t')", (ids["rent"],))
    db.execute("UPDATE receipt_items SET line_kind='usage' WHERE receipt_id=? AND position=2", (ids["rent"],))
    return ids


def test_071_bill_kinds_leaves_existing_bills_untouched():
    """SC-49 step 1 (FR-52): bills read before bill kinds keep every value and correction; bill kind and line type are
    null, nothing is read or queued, and the ledger health check still passes."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for number, script in MIGRATIONS:
            if number < 71:
                db.executescript(script.read_text())
        ids = pre_bill_kinds(db)
        db.commit()
        before = {table: [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
                  for table in ("receipts", "receipt_items", "category_splits", "record_corrections")}
        storage.apply_migrations(db, 70)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
        for table, rows in before.items():
            after = [dict(row) for row in db.execute(f"SELECT * FROM {table} ORDER BY id")]
            assert len(after) == len(rows) and [{key: row[key] for key in old} for row, old in zip(after, rows)] == rows, table
        assert [tuple(row) for row in db.execute("SELECT id,bill_kind,receipt_kind FROM receipts ORDER BY id")] == [
            (ids["phone"], None, None), (ids["rent"], None, None)]
        assert db.execute("SELECT count(*) FROM receipt_items WHERE line_type IS NOT NULL").fetchone()[0] == 0
        assert db.execute("SELECT line_kind FROM receipt_items WHERE receipt_id=? AND position=2", (ids["rent"],)).fetchone()[0] == "usage"
        assert db.execute("SELECT count(*) FROM extraction_runs").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM jobs WHERE status<>'completed'").fetchone()[0] == 0
        from home_manager.finance.health import check_ledger
        assert [problem for problem in check_ledger(db) if problem.severity == "error"] == []
        for statement in ("UPDATE receipts SET bill_kind='utility' WHERE id=?", "UPDATE receipt_items SET line_type='snacks' WHERE receipt_id=?"):
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(statement, (ids["rent"],))
        db.execute("UPDATE receipts SET bill_kind='rent' WHERE id=?", (ids["rent"],))
        db.execute("UPDATE receipt_items SET line_type='utility' WHERE receipt_id=? AND position=2", (ids["rent"],))
        assert db.execute("SELECT strict FROM pragma_table_list WHERE name='receipts'").fetchone()[0] == 1
    finally:
        db.close()


def test_071_bill_kinds_record_view_of_an_old_bill(tmp_path):
    """SC-49 step 1, through the ledger: an old bill's record shows no kind, no details and no line types."""
    root = tmp_path / "managed"
    Store(root).close()
    for name in ("inventory.sqlite3", "inventory.sqlite3-wal", "inventory.sqlite3-shm"):
        (root / name).unlink(missing_ok=True)
    db = sqlite3.connect(root / "inventory.sqlite3")
    try:
        for number, script in MIGRATIONS:
            if number < 71:
                db.executescript(script.read_text())
        ids = pre_bill_kinds(db)
        db.commit()
    finally:
        db.close()
    store = Store(root)
    try:
        from home_manager.finance.ledger import Ledger
        ledger = Ledger(store)
        for name in ("phone", "rent"):
            record = ledger.record("receipt", ids[name])
            assert (record["bill_kind"], record["receipt_kind"], record["details"]) == (None, None, None), name
            assert all(item["line_type"] is None and item["details"] is None for item in record["items"]), name
        assert [item["line_kind"] for item in ledger.record("receipt", ids["rent"])["items"]] == ["service", "usage"]
        assert ledger.record("receipt", ids["phone"])["review_status"] == "verified"
    finally:
        store.close()


def test_the_app_starts_and_explains_a_failed_upgrade(tmp_path, next_step):
    control, managed = tmp_path / "control", tmp_path / "managed"
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        manager.configure(str(managed))
    finally:
        manager.close()
    next_step(f"THIS IS NOT SQL;\nPRAGMA user_version={NEXT};")
    manager = Manager(control, ScanLimits(stability_seconds=0))
    try:
        assert manager.store is None
        assert f"step {NEXT:03d}" in manager.settings()["startup_error"]
    finally:
        manager.close()


def test_072_pdf_import_index_adds_one_derived_table_and_changes_nothing_else():
    """The PDF import index (specs/account-import-pdf): the upgrade from 071 leaves every existing table's rows as they were, sets
    user_version=72 and adds a STRICT table that follows its reading. Nothing is backfilled by the migration."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        for number, script in MIGRATIONS:
            if number < 72:
                db.executescript(script.read_text())
        pre_document_forms(db)
        db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at) "
                   "VALUES('run1',?,'pdf-pages-v3-layout','{}','succeeded','t','t')", ("d" * 64,))
        db.commit()
        names = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        before = {name: db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names}
        assert "pdf_import_index" not in names and db.execute("PRAGMA user_version").fetchone()[0] == 71
        storage.apply_migrations(db, 71)
        assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST == 72
        assert {name: db.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0] for name in names} == before
        assert db.execute("SELECT count(*) FROM pdf_import_index").fetchone()[0] == 0  # No backfill in the migration.
        assert db.execute("SELECT strict FROM pragma_table_list WHERE name='pdf_import_index'").fetchone()[0] == 1
        assert [row["name"] for row in db.execute("PRAGMA table_info(pdf_import_index)")] == [
            "parse_run_id", "analyzer_version", "transactions_tables", "last_fours_json", "document_currency", "error", "created_at"]
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("INSERT INTO pdf_import_index VALUES('run1',1,1,'{}',NULL,NULL,'t')")
        for row in ("('run1',1,1,'{}',NULL,NULL,'t')", "('missing',1,1,'{}',NULL,NULL,'t')", "('run1',NULL,1,'{}',NULL,NULL,'t')"):
            with pytest.raises(sqlite3.IntegrityError):  # A second row for a reading, a reading that is not there, a missing version.
                db.execute(f"INSERT INTO pdf_import_index VALUES{row}")
        db.execute("DELETE FROM parse_runs WHERE id='run1'")
        assert db.execute("SELECT count(*) FROM pdf_import_index").fetchone()[0] == 0  # ON DELETE CASCADE.
    finally:
        db.close()


def test_migration_numbers_are_unique_and_a_new_library_has_every_step(tmp_path):
    """Two branches once both added an 071; the runner applies one script per number, so a new library lacked
    pdf_import_index and every open failed. Each number appears once, and a new library has both 071 and 072."""
    numbers = [number for number, _ in MIGRATIONS]
    assert len(numbers) == len(set(numbers))
    store = Store(tmp_path / "managed")
    try:
        with store.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == LATEST
            assert {"bill_kind"} <= {row[1] for row in db.execute("PRAGMA table_info(receipts)")}
            assert {"line_type"} <= {row[1] for row in db.execute("PRAGMA table_info(receipt_items)")}
            assert db.execute("SELECT count(*) FROM pdf_import_index").fetchone()[0] == 0
    finally:
        store.close()
