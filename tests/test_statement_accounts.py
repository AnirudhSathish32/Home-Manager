"""Accounts that wait for Confirm, and the upgrade that sorts existing ones (specs/statement-accounts, FR-01 – FR-03, FR-07, FR-08).

SC-04 and SC-07 (and the ledger/API side of SC-02 and SC-03) at the ledger and API level. Journey J1 and SC-06 come last: Record of S
through the service, its account waiting for Confirm, Undo, and a re-read that moves the statement. The accounts that wait in the SC-04
tests are made through `publish_statement(origin='record')`, which is what Record calls. Everything is synthetic and lives under tmp_path.
"""

from datetime import date
import hashlib
import json
import sqlite3

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.app.family_sync import FamilyFolder
from home_manager.core.jobs import Work
from home_manager.documents.extraction import ExtractionService
from home_manager.documents.pdf_reader import read_result
from home_manager.documents.reasoning import ReasoningConfig
from home_manager.documents.receipt_service import ReceiptService
from home_manager.finance.family_routing import apply_delivery, member_facts
from home_manager.finance.forecast import Assets, baseline
from home_manager.finance.investments import AccountInput, Investments
from home_manager.finance.ledger import CONFIRMED, Ledger
from home_manager.finance.tools import FinanceTools, PeriodInput, scope_of
from home_manager.library import storage
from home_manager.library.storage import Store
import pdf_import_fixtures as fx  # noqa: F401  (keeps the shared fixture path on sys.path, as the other PDF test files do)
import statement_account_fixtures as sf
from test_pdf_imports import env, no_network  # noqa: F401  (the API environment of PDF import, and the autouse C-net guard)
from test_statement_rebuild import Recorded, bank_replies, s_replies

CSV = b"Date,Description,Amount\n2026-09-04,SYNTH BAKERY,-6.25\n2026-09-05,SYNTH PAYROLL,2000.00\n"
MIGRATION = storage.MIGRATIONS[-1][1]


def statement(last_four="3456", rows=((("2026-09-03"), "SYNTH COFFEE SHOP", -450),), closing=100000):
    """A bank statement for SYNTH BANK …last_four, as Record hands it to the ledger."""
    return {"statement_type": "bank", "institution": "SYNTH BANK", "last_four": last_four, "currency": "USD", "period_start": "2026-09-01",
            "period_end": "2026-09-30", "opening_balance_minor": 0, "closing_balance_minor": closing, "summary": {}, "issues": [],
            "locator": {"line_ids": ["page-1-line-1"]},
            "transactions": [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD", "locator": {"line_ids": ["page-1-line-2"]}}
                             for day, text, amount in rows]}


def source_of(doc, key="extraction:test"):
    return {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": key, "run_id": "test"}


def waiting(env_, last_four="3456", name=None, status="proposed", **changes):
    """An account Record made: publish a statement the way Record will (origin 'record'), into a document of its own."""
    name = name or f"record-{last_four}.pdf"
    doc = env_.add(name, sf.s2_pages() if last_four != "3456" else sf.w_pages(), read=False)
    published = env_.manager.ledger.publish_statement(statement(last_four, **changes), source_of(doc), status, origin="record")
    return published["account_id"], published["id"], doc


# --- C-visible / C-hidden ----------------------------------------------------------------------------------------------------

def surfaces(env_, account_id, last_four="3456"):
    """Whether each FR-02 surface lists the account: the API list, get_accounts (the assistant, the Add transaction and Import pickers,
    Transactions and Month), Today's cash and Forecast, Spending's coverage, PDF import's last-four preselection and the investment link list."""
    tools, ledger = FinanceTools(env_.store), env_.manager.ledger
    scope, params = scope_of("2026-09-01", "2026-09-30", None)
    with env_.store.connection() as db:
        match = ledger.account_match(db, {last_four: 1}, "USD")
    investments = Investments(env_.store)
    probe = investments.add(AccountInput(name="Probe", kind="hysa", currency="USD", value="1", as_of="2026-06-30"))
    try:
        linkable = [option["id"] for option in probe["linkable_accounts"]]
    finally:
        with env_.store.connection() as db:
            db.execute("DELETE FROM investment_valuations WHERE account_id=?", (probe["id"],))
            db.execute("DELETE FROM investment_accounts WHERE id=?", (probe["id"],))
    return {"api": account_id in [row["id"] for row in env_.client.get("/api/finance/accounts").json()],
            "get_accounts": account_id in [row["id"] for row in tools.get_accounts()["accounts"]],
            "today": account_id in [row["account_id"] for row in baseline(tools, Assets(env_.store), 3, "USD", date(2026, 10, 15))["balances"]],
            "coverage": account_id in [row["account_id"] for row in tools._coverage(scope, params)],
            "preselection": bool(match) and match["account_id"] == account_id,
            "investment_links": account_id in linkable}


def c_visible(env_, account_id, last_four="3456"):
    shown = surfaces(env_, account_id, last_four)
    assert all(shown.values()), shown


def c_hidden(env_, account_id, last_four="3456"):
    shown = surfaces(env_, account_id, last_four)
    assert not any(shown.values()), shown


def origin_of(env_, account_id):
    return env_.sql("SELECT origin FROM accounts WHERE id=?", account_id)[0][0]


# --- FR-01, FR-02: an account Record makes is hidden; one you make is confirmed ---------------------------------------------

def test_sc04_an_account_you_make_is_confirmed_at_once_and_one_record_makes_waits(env):
    made = env.client.post("/api/finance/accounts", json={"institution": "SYNTH BANK", "account_type": "checking", "currency": "USD", "last_four": "1111"})
    assert made.status_code == 201 and made.json()["origin"] == "user"
    account, statement_id, _ = waiting(env, "3456")
    assert origin_of(env, account) == "record"
    c_hidden(env, account)
    assert [row["id"] for row in env.client.get("/api/finance/accounts").json()] == [made.json()["id"]]
    [row] = env.client.get("/api/finance/accounts/waiting").json()
    assert (row["id"], row["statement_id"], row["account_last_four"]) == (account, statement_id, "3456")
    # Add transaction's pickers don't offer it; a crafted request into it is refused, and nothing is written.
    before = env.counts()
    with pytest.raises(ValueError, match="waits for you to confirm its statement"):
        env.manager.ledger.add_manual_transaction(account, "2026-09-10", "SYNTH LUNCH", "5.00", "out")
    assert env.counts() == before


def test_sc04_adding_the_account_by_hand_confirms_the_one_that_waits(env):
    account, _, _ = waiting(env, "3456")
    c_hidden(env, account)
    for institution in ("SYNTH BANK", "synth bank"):  # The same identity, whatever the case.
        again = env.client.post("/api/finance/accounts", json={"institution": institution, "account_type": "checking", "currency": "USD", "last_four": "3456"})
        assert again.status_code == 201 and again.json()["id"] == account
    assert origin_of(env, account) == "user"
    c_visible(env, account)
    assert env.client.get("/api/finance/accounts/waiting").json() == []


def test_sc04_a_second_record_into_the_account_still_finds_it(env):
    account, first, _ = waiting(env, "3456")
    doc = env.add("again.pdf", sf.c_pages(), read=False)
    again = env.manager.ledger.publish_statement(statement("3456", closing=200000), source_of(doc, "extraction:again"), "proposed", origin="record")
    assert again["account_id"] == account and again["id"] != first  # find_account still sees an account that waits.
    assert env.sql("SELECT count(*) FROM accounts")[0][0] == 1
    c_hidden(env, account)  # Finding it again doesn't confirm it.


# --- FR-03, FR-07 (SC-02, SC-03 at the ledger and API level) ---------------------------------------------------------------

def test_sc04_sc02_sc03_confirming_a_statement_confirms_its_account_and_undo_takes_it_back(env):
    account, statement_id, _ = waiting(env)
    c_hidden(env, account)
    review = f"/api/finance/records/statement/{statement_id}/review"
    assert env.client.post(review, json={"status": "verified"}).status_code == 200
    assert env.sql("SELECT review_status,review_source FROM statements WHERE id=?", statement_id) == [("verified", "user")]
    c_visible(env, account)  # In the same state the Confirm response reports, with no other step.
    assert env.client.get(f"/api/finance/records/statement/{statement_id}").json()["account_confirmed"] is True
    # The toast's Undo sends needs_review: nothing else confirmed the account, so it is unconfirmed again.
    assert env.client.post(review, json={"status": "needs_review"}).status_code == 200
    c_hidden(env, account)
    assert env.client.get(f"/api/finance/records/statement/{statement_id}").json()["account_confirmed"] is False
    assert [row["id"] for row in env.client.get("/api/finance/accounts/waiting").json()] == [account]
    # Both decisions are in review history as before, and no stored decision was rewritten by the account.
    assert [(row["previous_status"], row["new_status"]) for row in env.manager.ledger.review_history("statement", statement_id)] == [
        ("proposed", "verified"), ("verified", "needs_review")]


def test_sc04_undo_keeps_the_account_when_something_else_confirmed_it(env):
    account, statement_id, _ = waiting(env)
    other = env.add("other.pdf", sf.c_pages(), read=False)
    second = env.manager.ledger.publish_statement(statement("3456", closing=300000), source_of(other, "extraction:second"), "proposed", origin="record")
    review = lambda record, status: env.client.post(f"/api/finance/records/statement/{record}/review", json={"status": status})  # noqa: E731
    assert review(statement_id, "verified").status_code == 200 and review(second["id"], "verified").status_code == 200
    assert review(statement_id, "needs_review").status_code == 200
    c_visible(env, account)  # The other statement you confirmed still confirms it.


def test_sc04_rejecting_a_statement_does_not_confirm_its_account(env):
    account, statement_id, _ = waiting(env)
    assert env.client.post(f"/api/finance/records/statement/{statement_id}/review", json={"status": "rejected"}).status_code == 200
    c_hidden(env, account)
    assert [row["id"] for row in env.client.get("/api/finance/accounts/waiting").json()] == [account]


def test_sc04_reconciling_its_statement_confirms_the_account(env):
    account, statement_id, _ = waiting(env)
    c_hidden(env, account)
    assert env.client.post(f"/api/finance/statements/{statement_id}/reconcile").status_code == 200
    assert env.sql("SELECT reconciliation FROM statements WHERE id=?", statement_id) == [("reconciled",)]
    c_visible(env, account)


def test_sc04_a_csv_import_into_the_account_confirms_it(env):
    account, _, _ = waiting(env)
    c_hidden(env, account)
    doc = env.add("export.csv", CSV, read=False)
    first = env.run(doc, account_id=account)  # The Import dialog doesn't offer the account; the API takes its id.
    assert first.status_code == 201 and first.json()["inserted"] == 2, first.text
    c_visible(env, account)


def test_sc04_a_pdf_import_into_the_account_confirms_it(env):
    account, _, _ = waiting(env)
    c_hidden(env, account)
    doc = env.add("s.pdf", sf.s_pages())
    imported = env.ok_import(doc, account_id=account, year=2026)
    assert imported["inserted"] == 5, imported
    c_visible(env, account)


def test_sc04_a_family_delivery_makes_a_confirmed_account(env, tmp_path):
    document = b"a statement the family confirmed"
    delivery = {"key": "family-key-9", "action": "record", "record_type": "statement", "record": statement("9999"), "name": "SYNTH BANK statement",
                "blob_hash": hashlib.sha256(document).hexdigest()}
    person = Store(tmp_path / "person")
    try:
        result = apply_delivery(person, delivery, document)
        ledger = Ledger(person)
        [account] = ledger.accounts()
        assert (account["account_last_four"], account["origin"]) == ("9999", "family") and ledger.waiting_accounts() == []
        with person.connection() as db:
            assert db.execute("SELECT review_status FROM statements WHERE id=?", (result["record"][1],)).fetchone()[0] == "verified"
    finally:
        person.close()


def test_sc04_the_family_view_does_not_count_an_account_that_waits(tmp_path):
    """member_facts and _joint_accounts read each member's copy: an account waiting for Confirm offers nothing and owns no shared identity."""
    stores = {name: Store(tmp_path / name) for name in ("mom", "dad")}
    try:
        ledgers = {name: Ledger(store) for name, store in stores.items()}
        with stores["mom"].connection() as db:
            ledgers["mom"].account_in(db, "SYNTH BANK", "checking", "USD", last_four="3456", origin="record")
        with stores["dad"].connection() as db:
            dad = ledgers["dad"].account_in(db, "SYNTH BANK", "checking", "USD", last_four="3456")["id"]
            db.execute("INSERT INTO transactions(account_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,source_fingerprint,"
                       "created_at,updated_at) VALUES(?,'2026-09-03','SYNTH COFFEE',-450,'USD','purchase','manual','verified','f1','t','t')", (dad,))
        members = [({"member_id": name}, stores[name]) for name in ("mom", "dad")]
        facts = member_facts(members)
        assert facts["mom"]["accounts"] == [] and [row["last_four"] for row in facts["dad"]["accounts"]] == ["3456"]
        present, names = [{"member_id": "mom"}, {"member_id": "dad"}], {"mom": "Mom", "dad": "Dad"}
        with stores["mom"].connection() as mom_db, stores["dad"].connection() as dad_db:
            connections = {"mom": mom_db, "dad": dad_db}
            # Mom is listed first, but her account waits: it owns nothing, so Dad's real transactions are not rejected as a copy.
            assert FamilyFolder._joint_accounts(present, connections, names) == []
            assert dad_db.execute("SELECT review_status FROM transactions").fetchone()[0] == "verified"
        with stores["mom"].connection() as db:
            ledgers["mom"].account_in(db, "SYNTH BANK", "checking", "USD", last_four="3456")  # Adding it by hand confirms it.
        assert [row["last_four"] for row in member_facts(members)["mom"]["accounts"]] == ["3456"]
        with stores["mom"].connection() as mom_db, stores["dad"].connection() as dad_db:
            [joint] = FamilyFolder._joint_accounts(present, {"mom": mom_db, "dad": dad_db}, names)
            assert (joint["counted_for"], joint["also_recorded_by"]) == ("Mom", ["Dad"])
            assert dad_db.execute("SELECT review_status FROM transactions").fetchone()[0] == "rejected"
    finally:
        for store in stores.values():
            store.close()


# --- FR-08, SC-07: the upgrade ------------------------------------------------------------------------------------------------

def references_to(db, parent, row_id):
    """C-orphans: every row in any table whose foreign key to `parent` holds `row_id`, from sqlite_master and pragma_foreign_key_list at run time."""
    found = []
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for key in db.execute(f"PRAGMA foreign_key_list({table})").fetchall():
            if key[2] == parent:
                found += [(table, key[3], row[0]) for row in db.execute(f'SELECT rowid FROM "{table}" WHERE "{key[3]}"=?', (row_id,))]
    return found


class Old:
    """A library the previous release left: built through the public paths at the current schema, then taken back to version 072."""

    def __init__(self, root):
        self.root = root
        self.store = Store(root)
        inbox_scan(self.store, {"a.pdf": b"statement a", "b1.pdf": b"statement b first", "b2.pdf": b"statement b moved", "c.csv": CSV,
                                "c.pdf": b"statement c", "e.pdf": b"statement e", "f.pdf": b"statement f", "g.pdf": b"statement g"})
        self.docs = documents_by_name(self.store)
        self.ledger = Ledger(self.store)
        self.ids = {}

    def publish(self, key, last_four, document, status="proposed", institution="SYNTH BANK"):
        record = {**statement(last_four), "institution": institution}
        published = self.ledger.publish_statement(record, source_of(self.docs[document], f"extraction:{key}"), status)
        self.ids[key] = published["account_id"]
        self.ids[f"{key}-statement"] = published["id"]
        return published

    def build(self):
        # (a) only an automatically checked statement: verified, automatic, reconciliation awaiting.
        self.publish("a", "1111", "a.pdf", "verified")
        # (b) an account a re-read left empty: the statement moved to another last four, and the run still names the old account.
        old = self.publish("b", "2222", "b1.pdf")
        moved = self.ledger.publish_statement(statement("2223"), source_of(self.docs["b1.pdf"], "extraction:b"), "proposed")
        assert moved["id"] == old["id"] and moved["account_id"] != old["account_id"]
        self.ids["b-moved"] = moved["account_id"]
        with self.store.connection() as db:
            assert db.execute("SELECT count(*) FROM statements WHERE account_id=?", (self.ids["b"],)).fetchone()[0] == 0
            db.execute("INSERT INTO parse_runs(id,blob_hash,parser_version,options_json,status,created_at,updated_at) VALUES('p1',?,'v','{}','succeeded','t','t')",
                       (self.docs["b1.pdf"]["current_hash"],))
            db.execute("INSERT INTO extraction_runs(id,document_id,parse_run_id,config_json,prompt_version,status,created_at,updated_at,publication_json) "
                       "VALUES('r1',?,'p1','{}','v','succeeded','t','t',?)",
                       (self.docs["b1.pdf"]["id"], json.dumps({"record_type": "statement", "id": old["id"], "status": "published", "account_id": self.ids["b"]})))
            # What hangs off it: a rule, a tax rule, a recurring payment and an investment link, all of which the removal has to let go of.
            db.execute("INSERT INTO category_rules(pattern,category,account_id,created_at,updated_at) VALUES('SYNTH','dining',?, 't','t')", (self.ids["b"],))
            db.execute("INSERT INTO tax_rules(pattern,account_id,kind,line,created_at,updated_at) VALUES('SYNTH',?,'tax_payment','x','t','t')", (self.ids["b"],))
            db.execute("INSERT INTO merchants(canonical_name,normalized_name,created_at,updated_at) VALUES('SYNTH GYM','synth gym','t','t')")
            db.execute("INSERT INTO recurring_obligations(merchant_id,account_id,obligation_type,expected_amount_minor,currency,frequency,status,confidence_source,"
                       "created_at,updated_at) VALUES((SELECT id FROM merchants WHERE normalized_name='synth gym'),?,'subscription',1000,'USD','monthly','verified','user','t','t')",
                       (self.ids["b"],))
        Investments(self.store).add(AccountInput(name="Linked", kind="hysa", currency="USD", value="1", as_of="2026-06-30", ledger_account_id=self.ids["b"]))
        # (c) an account with a statement and a CSV import.
        self.publish("c", "3333", "c.pdf", "verified")
        assert self.ledger.import_transactions(self.docs["c.csv"]["id"], self.ids["c"])["inserted"] == 2
        # (d) an account made by hand.
        self.ids["d"] = self.ledger.create_account("SYNTH BANK", "checking", "USD", last_four="4444")["id"]
        # (e) a statement you confirmed, (f) one that was reconciled.
        self.publish("e", "5555", "e.pdf")
        self.ledger.review("statement", self.ids["e-statement"], "verified")
        self.publish("f", "6666", "f.pdf", "verified")
        with self.store.connection() as db:
            db.execute("UPDATE statements SET reconciliation='reconciled' WHERE id=?", (self.ids["f-statement"],))
        # (g) a statement a family delivery published.
        self.publish("g", "7777", "g.pdf", "verified")
        with self.store.connection() as db:
            db.execute("UPDATE financial_evidence_links SET source_key='family:g' WHERE record_type='statement' AND record_id=?", (self.ids["g-statement"],))
        self.take_back()

    def take_back(self):
        """The previous release's schema: no origin column, version 072. The statements written above are what the old code left."""
        self.store.close()
        db = sqlite3.connect(self.root / "inventory.sqlite3")
        try:
            db.execute("ALTER TABLE accounts DROP COLUMN origin")
            db.execute("PRAGMA user_version=72")
            db.commit()
        finally:
            db.close()

    def snapshot(self):
        db = sqlite3.connect(self.root / "inventory.sqlite3")
        try:
            names = [row[0] for row in db.execute("SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {name: db.execute(f'SELECT * FROM "{name}" ORDER BY 1').fetchall() for name in names} | {"user_version": db.execute("PRAGMA user_version").fetchone()[0]}
        finally:
            db.close()


def test_sc07_the_upgrade_sorts_existing_accounts_and_running_it_again_changes_nothing(tmp_path):
    old = Old(tmp_path / "managed")
    old.build()
    assert "origin" not in {row[1] for row in sqlite3.connect(tmp_path / "managed" / "inventory.sqlite3").execute("PRAGMA table_info(accounts)")}
    ids = old.ids
    store = Store(tmp_path / "managed")  # Opening the library applies 073.
    try:
        ledger = Ledger(store)
        with store.connection() as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 73 and db.execute("PRAGMA foreign_key_check").fetchall() == []
            origins = {row["id"]: row["origin"] for row in db.execute("SELECT id,origin FROM accounts")}
            # (b) is gone, with everything that named only it, and nothing refers to it.
            assert ids["b"] not in origins and references_to(db, "accounts", ids["b"]) == []
            assert db.execute("SELECT count(*) FROM category_rules").fetchone()[0] == 0 and db.execute("SELECT count(*) FROM tax_rules").fetchone()[0] == 0
            assert db.execute("SELECT account_id FROM recurring_obligations").fetchall()[0][0] is None  # The payment stays, unlinked.
            assert db.execute("SELECT ledger_account_id FROM investment_accounts").fetchone()[0] is None
            # The account its statement moved to is an ordinary one that waits.
            assert origins[ids["b-moved"]] == "record"
            assert {key: origins[ids[key]] for key in "acdefg"} == {"a": "record", "c": "record", "d": "user", "e": "record", "f": "record", "g": "family"}
            confirmed = {row["id"] for row in db.execute(f"SELECT a.id FROM accounts a WHERE {CONFIRMED}")}
        assert confirmed == {ids[key] for key in "cdefg"}
        assert {account["id"] for account in ledger.accounts()} == confirmed
        assert {account["id"] for account in ledger.waiting_accounts()} == {ids["a"], ids["b-moved"]}
        # No stored decision was rewritten: (a)'s statement is still verified and automatic, which Confirm still offers (P4).
        with store.connection() as db:
            assert tuple(db.execute("SELECT review_status,review_source FROM statements WHERE id=?", (ids["a-statement"],)).fetchone()) == ("verified", "automatic")
        # The statement of an account that waits says so.
        assert ledger.record("statement", ids["a-statement"])["account_confirmed"] is False
        assert ledger.record("statement", ids["e-statement"])["account_confirmed"] is True
    finally:
        store.close()
    after_first = old.snapshot()
    # Run the part after the marker again: the rows are equal, table by table.
    script = MIGRATION.read_text()
    assert script.count("-- sort:") == 1
    db = sqlite3.connect(tmp_path / "managed" / "inventory.sqlite3")
    try:
        db.executescript("BEGIN IMMEDIATE;\n" + script.split("-- sort:", 1)[1].split("\n", 1)[1])
        db.commit()
    finally:
        db.close()
    assert old.snapshot() == after_first
    # Opening the library again is no upgrade at all.
    Store(tmp_path / "managed").close()
    assert old.snapshot() == after_first


def test_sc07_a_new_library_has_the_origin_column_and_only_three_origins(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        ledger = Ledger(store)
        with store.connection() as db:
            assert ledger.account_in(db, "SYNTH BANK", "checking", "USD", last_four="1234")["origin"] == "user"
            for origin in ("record", "family"):
                assert ledger.account_in(db, "SYNTH BANK", "savings", "USD", last_four="1234", origin=origin)["origin"] == origin
                db.execute("DELETE FROM accounts WHERE account_type='savings'")
            with pytest.raises(ValueError, match="Unknown account origin"):
                ledger.account_in(db, "SYNTH BANK", "loan", "USD", origin="model")
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("UPDATE accounts SET origin='model'")
    finally:
        store.close()


# === Journey J1 and SC-06: Record of S, Confirm, Undo and a re-read that moves the statement =====================================

ACCOUNT_NOTE = "New account: SYNTH BANK savings 3456 — added to Accounts when you confirm this statement."
TABLES = ("accounts", "statements", "transactions", "financial_evidence_links", "review_events", "category_rules", "transaction_imports")


def recorded_s(env_, model, name="s.pdf", pages=None):
    """A synthetic PDF captured and read by the real reader, ready for Record through the service (the model is the `local_model` stub)."""
    doc = env_.add(name, pages or sf.s_pages())
    service = ReceiptService(env_.store)
    parse_id = env_.reading(doc)
    return Recorded(env_.store, service, doc, parse_id, sf.reading_lines(read_result(service.get(parse_id)["result"])), model)


def moved(lines):
    """S's summary as a re-read that takes the statement to …7890: the model gives that reference, citing the printed number line the
    document has. (S2's own stub cites S2's number line; the same document version has only S's.)"""
    line = "Account Number 000009000123456"
    return {**sf.s_summary(lines), "account_reference": sf.proposed(lines, "7890", line, line)}


def attempt(recorded, replies):
    """Record again without asserting the run succeeded; returns the extraction run."""
    recorded.model["by_schema"] = replies(recorded.lines)
    config = ReasoningConfig(base_url=recorded.model["config"].base_url, model="synthetic-reasoning")
    run_id, _ = ExtractionService(recorded.store, recorded.service).enqueue(recorded.doc["id"], recorded.parse_id, config, force=True, home_currency="USD")
    ExtractionService(recorded.store, recorded.service).run(run_id, Work.detached())
    return ExtractionService(recorded.store, recorded.service).get(run_id)


def snapshot(env_):
    return {table: env_.sql(f'SELECT * FROM "{table}" ORDER BY 1') for table in TABLES}


def amounts(env_, statement_id):
    return [row[0] for row in env_.sql("SELECT amount_minor FROM transactions WHERE statement_id=? ORDER BY id", statement_id)]


def september(env_):
    """What September 2026 counts for: money in and spending, summed over currencies (FinanceTools, as the API)."""
    tools, period = FinanceTools(env_.store), PeriodInput(start="2026-09-01", end="2026-09-30")
    return (sum(row["inflow"]["minor"] for row in tools.calculate_cashflow(period)["by_currency"]),
            sum(row["net_spending"]["minor"] for row in tools.get_spending(period)["by_currency"]))


def review(env_, statement_id, status):
    response = env_.client.post(f"/api/finance/records/statement/{statement_id}/review", json={"status": status})
    assert response.status_code == 200, response.text
    return response.json()


def shown(env_, statement_id):
    return env_.client.get(f"/api/finance/records/statement/{statement_id}").json()


def test_journey_j1_a_statements_account_waits_for_confirm_and_a_re_read_moves_it(env, local_model):
    recorded = recorded_s(env, local_model)
    files = env.files()
    # 1 (SC-01): the account exists but waits, and so does the statement, though the rows it records reconcile.
    record = recorded.run(s_replies())
    statement_id = record["id"]
    [(account_id, name, kind, origin)] = env.sql("SELECT id,display_name,account_type,origin FROM accounts")
    assert (name, kind, origin) == ("SYNTH BANK savings 3456", "savings", "record")
    c_hidden(env, account_id)
    assert (record["review_status"], record["issues"]) == ("proposed", [])
    assert recorded.extraction["publication"]["review_status"] == "proposed"
    view = shown(env, statement_id)  # Confirm and Reject are what a proposed record offers; the account's note is under it.
    assert (view["review_status"], view["account_confirmed"], view["account_note"]) == ("proposed", False, ACCOUNT_NOTE)
    assert amounts(env, statement_id) == sf.S_AMOUNTS == [36, 2, -38, 150000, -50000]
    assert september(env) == (0, 0)  # Its rows count for nothing until the statement is confirmed and reconciled.
    # 2 (SC-02): Confirm confirms the account at once.
    assert review(env, statement_id, "verified")["review_status"] == "verified"
    assert env.sql("SELECT review_status,review_source FROM statements WHERE id=?", statement_id) == [("verified", "user")]
    c_visible(env, account_id)
    assert "account_note" not in shown(env, statement_id) and shown(env, statement_id)["account_confirmed"] is True
    # 3 (SC-03, FR-07): Undo (the toast's body) puts everything back: the account waits again, and so do the rows the Confirm cascaded (P15).
    review(env, statement_id, "needs_review")
    c_hidden(env, account_id)
    assert env.sql("SELECT review_status,review_source FROM transactions WHERE statement_id=?", statement_id) == [("needs_review", None)] * 5
    assert shown(env, statement_id)["account_note"] == ACCOUNT_NOTE
    # 4 (SC-05, FR-06): a re-read that moves the statement removes the account it leaves, in the same transaction.
    before = snapshot(env)
    with env.store.connection() as db:
        db.execute("CREATE TRIGGER fault BEFORE DELETE ON accounts BEGIN SELECT RAISE(ABORT,'injected fault'); END")
    failed = attempt(recorded, bank_replies(moved, sf.s_bad_rows))
    assert failed["status"] == "failed" and failed["publication"] is None, failed
    assert snapshot(env) == before  # The account, the statement and its rows are as after step 3.
    with env.store.connection() as db:
        db.execute("DROP TRIGGER fault")
    record = recorded.run(bank_replies(moved, sf.s_bad_rows), force=True)
    [(moved_id, name, origin)] = env.sql("SELECT id,display_name,origin FROM accounts")
    assert (name, origin) == ("SYNTH BANK savings 7890", "record") and moved_id != account_id
    c_hidden(env, moved_id, "7890")
    with env.store.connection() as db:
        assert sf.orphans(db, account_id) == []  # C-orphans: nothing names …3456 any more.
    assert env.sql("SELECT count(*) FROM statements") == [(1,)] and record["id"] == statement_id and record["review_status"] == "proposed"
    assert amounts(env, statement_id) == [36, 2, -38, 150000, -50000]  # From the rebuild, not the S-bad stub.
    assert env.sql("SELECT count(DISTINCT account_id) FROM transactions") == [(1,)] and env.sql("SELECT account_id FROM statements") == [(moved_id,)]
    assert env.files() == files  # C-docs: the documents are untouched.


def test_journey_j1_a_a_re_read_of_a_statement_you_confirmed_keeps_it_as_you_reviewed_it(env, local_model):
    """SC-06 (E2): the re-read is `kept_reviewed`: one account, …3456, with its statement and rows, and no …7890 account (P16)."""
    recorded = recorded_s(env, local_model)
    record = recorded.run(s_replies())
    review(env, record["id"], "verified")
    [(account_id,)] = env.sql("SELECT id FROM accounts")
    before, files = snapshot(env), env.files()
    again = recorded.run(bank_replies(moved, sf.s_bad_rows), force=True)
    assert recorded.extraction["publication"]["status"] == "kept_reviewed" and again["id"] == record["id"]
    assert env.sql("SELECT id,display_name FROM accounts") == [(account_id, "SYNTH BANK savings 3456")]
    assert env.sql("SELECT count(*) FROM accounts WHERE display_name LIKE '%7890'") == [(0,)]
    c_visible(env, account_id)
    assert snapshot(env) == before and amounts(env, record["id"]) == [36, 2, -38, 150000, -50000]
    assert env.files() == files


def test_journey_j1_b_a_second_statement_of_a_confirmed_account_keeps_the_automatic_check(env, local_model):
    first = recorded_s(env, local_model)
    first_id = first.run(s_replies())["id"]
    review(env, first_id, "verified")
    [(account_id,)] = env.sql("SELECT id FROM accounts")
    second = recorded_s(env, local_model, "s-again.pdf", sf.s_pages(above=(*sf.S_ABOVE[:2], "Household copy B", *sf.S_ABOVE[2:])))
    record = second.run(s_replies())
    assert record["account_id"] == account_id and record["issues"] == []
    assert env.sql("SELECT review_status,review_source FROM statements WHERE id=?", record["id"]) == [("verified", "automatic")]
    assert second.extraction["publication"]["review_status"] == "verified"
    assert env.sql("SELECT count(*) FROM accounts") == [(1,)]
    c_visible(env, account_id)


def test_journey_j1_a_correction_does_not_skip_the_wait_but_does_for_a_confirmed_account(env):
    """FR-04: the automatic promotion after a correction stays `proposed` while the account waits, and is `verified` otherwise."""
    account, statement_id, _ = waiting(env, status="needs_review")
    corrected = env.manager.ledger.correct("statement", statement_id, {"closing_balance": "1,000.01"})
    assert corrected["review_status"] == "proposed" and env.sql("SELECT review_source FROM statements WHERE id=?", statement_id) == [(None,)]
    c_hidden(env, account)
    doc = env.add("made-by-hand.pdf", sf.c_pages(), read=False)
    hand = env.manager.ledger.create_account("SYNTH BANK", "checking", "USD", last_four="5678")["id"]
    published = env.manager.ledger.publish_statement(statement("5678"), source_of(doc, "extraction:hand"), "needs_review", origin="record")
    assert published["account_id"] == hand
    assert env.manager.ledger.correct("statement", published["id"], {"closing_balance": "1,000.01"})["review_status"] == "verified"


def test_journey_j1_a_undo_keeps_a_row_you_reviewed_one_by_one(env):
    """P15: Undo of a Confirm returns the rows the Confirm decided, not a row with a decision of its own."""
    rows = (("2026-09-03", "SYNTH COFFEE SHOP", -450), ("2026-09-04", "SYNTH BAKERY", -625), ("2026-09-05", "SYNTH PAYROLL", 200000))
    _, statement_id, _ = waiting(env, rows=rows)
    review(env, statement_id, "verified")
    [first, second, third] = [row[0] for row in env.sql("SELECT id FROM transactions WHERE statement_id=? ORDER BY id", statement_id)]
    env.manager.ledger.review("transaction", second, "rejected")
    review(env, statement_id, "needs_review")
    assert env.sql("SELECT id,review_status,review_source FROM transactions WHERE statement_id=? ORDER BY id", statement_id) == [
        (first, "needs_review", None), (second, "rejected", "user"), (third, "needs_review", None)]


def test_journey_j1_a_a_family_deliverys_statement_is_not_held_and_a_record_one_into_its_account_is(env):
    """FR-04 leaves origin 'family' alone; a Record statement into a family-made account that is confirmed keeps the automatic check."""
    doc = env.add("family.pdf", sf.s_pages(), read=False)
    delivered = env.manager.ledger.publish_statement(statement("3456"), source_of(doc, "family:key"), "verified", origin="family")
    assert (delivered["review_status"], delivered["account_confirmed"]) == ("verified", True)
    other = env.add("record.pdf", sf.c_pages(), read=False)
    second = env.manager.ledger.publish_statement(statement("3456", closing=300000), source_of(other, "extraction:second"), "verified", origin="record")
    assert (second["review_status"], second["account_confirmed"], second["account_id"]) == ("verified", True, delivered["account_id"])
