"""Investments phase 4 (docs/planning.md "Investments"): contributions from pay stubs, payments into investments, the forecast's flows.
Synthetic data only."""

from datetime import date
import json

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.finance.investments import AccountInput, AccountUpdate, Investments
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.library.storage import Store

TODAY = date(2026, 9, 28)
# A pay stub's 401(k), Roth and HSA deductions and the employer's match: (description, group, category, amount).
LINES = [("401K PRE-TAX", "pre_tax", "retirement_pretax", 25000), ("ROTH 401K", "post_tax", "retirement_roth", 10000),
         ("401K MATCH", "employer_paid", "retirement_pretax", 12500), ("HSA", "pre_tax", "hsa", 5000), ("DENTAL", "pre_tax", "dental", 1500)]


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    names = ["jul15.png", "jul31.png", "aug14.png", "q3.png", "sep.png"]
    inbox_scan(store, {name: name.encode() for name in names})
    try:
        yield store, Investments(store, TODAY), documents_by_name(store)
    finally:
        store.close()


def employer(store, name):
    with store.connection() as db:
        return db.execute("INSERT INTO merchants(canonical_name,normalized_name,created_at,updated_at) VALUES(?,?,'t','t')", (name, name.upper())).lastrowid


def paystub(store, doc, employer_id, pay_date, lines=LINES, status="verified"):
    with store.connection() as db:
        record = db.execute("INSERT INTO income_records(document_id,blob_hash,payer_merchant_id,pay_date,currency,review_status,created_at,updated_at) "
                            "VALUES(?,?,?,?,'USD',?,'t','t')", (doc["id"], doc["current_hash"], employer_id, pay_date, status)).lastrowid
        db.executemany("INSERT INTO income_lines(income_record_id,position,description,line_group,category,current_minor,locator_json) VALUES(?,?,?,?,?,?,'{}')",
                       [(record, position, *line) for position, line in enumerate(lines, 1)])


def statement(investments, doc, institution, account_name, period_end, value_minor, activity):
    record = {"investment_kind": "401k", "institution": institution, "account_name": account_name, "last_four": None, "value_minor": value_minor,
              "period_end": period_end, "currency": "USD", "issues": [], "activity": activity}
    return investments.publish_statement(record, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "run_id": doc["relative_path"]})


def three_paychecks(store, docs, employer_id):
    for name, day in (("jul15.png", "2026-07-15"), ("jul31.png", "2026-07-31"), ("aug14.png", "2026-08-14")):
        paystub(store, docs[name], employer_id, day)


def test_pay_stub_contributions_reach_the_account_named_for_the_employer(books):
    store, investments, docs = books
    acme = employer(store, "Acme Corp")
    ira = investments.add(AccountInput(name="Rollover IRA", kind="ira", institution="Vanguard", currency="USD", value="5000", as_of="2026-06-30"))
    hsa = investments.add(AccountInput(name="Health savings", kind="hsa", institution="HealthEquity", currency="USD", value="1000", as_of="2026-06-30"))
    # The plan's statement lists one paycheck's deferral: it is the same money as that pay stub line, shown once.
    plan = statement(investments, docs["q3.png"], "Fidelity", "Acme Corp 401(k) Plan", "2026-07-31", 2100000,
                     [{"name": "Employee deferral", "event_date": "2026-07-16", "event_type": "contribution", "contribution_source": "employee", "amount_minor": 25000}])
    investments.review(plan["id"], "verified")
    three_paychecks(store, docs, acme)
    summary = investments.summary()
    linked = {account["name"]: (account["payroll_employer"], account["payroll_link"]) for account in summary["accounts"]}
    # The plan named for the employer, not the IRA; the only HSA.
    assert linked == {"Fidelity Acme Corp 401(k) Plan": ("Acme Corp", "auto"), "Rollover IRA": (None, None), "Health savings": ("Acme Corp", "auto")}
    assert summary["payroll_questions"] == []
    events = investments.get(plan["account_id"])["events"]
    assert len(events) == 9 and {event["source"] for event in events} == {"paystub"}
    assert sorted({(event["note"], event["source_label"]) for event in events}) == [
        ("401K MATCH", "From your employer"), ("401K PRE-TAX", "From your pay"), ("ROTH 401K", "From your pay")]
    assert [event["also_on_statement"] for event in events if event["event_date"] == "2026-07-15" and event["amount_minor"] == 25000] == [True]
    assert [event["amount"]["display"] for event in investments.get(hsa["id"])["events"]] == ["50.00 USD"] * 3
    assert investments.get(ira["id"])["events"] == []
    # The forecast adds six months' average (three paychecks) each month, employee and employer together.
    assets = {asset["name"]: asset for asset in Investments(store, TODAY).forecast_assets("2026-03-01", "2026-08-31", 6)}
    assert assets["Fidelity Acme Corp 401(k) Plan"]["payroll_monthly_minor"] == 3 * (25000 + 10000 + 12500) // 6
    assert assets["Health savings"]["payroll_monthly_minor"] == 2500 and assets["Rollover IRA"]["payroll_monthly_minor"] == 0


def test_a_statement_listing_the_contributions_decides_and_otherwise_you_are_asked(books):
    store, investments, docs = books
    acme = employer(store, "Acme Corp")
    fidelity = investments.add(AccountInput(name="Fidelity 401(k)", kind="401k", institution="Fidelity", currency="USD", value="1", as_of="2026-06-30"))
    vanguard = investments.add(AccountInput(name="Vanguard 401(k)", kind="401k", institution="Vanguard", currency="USD", value="1", as_of="2026-06-30"))
    three_paychecks(store, docs, acme)
    health, retirement = investments.summary()["payroll_questions"]
    assert (retirement["employer"], retirement["label"], [row["name"] for row in retirement["accounts"]]) == (
        "Acme Corp", "401(k) or retirement", ["Fidelity 401(k)", "Vanguard 401(k)"])
    assert (health["label"], health["accounts"]) == ("HSA", [])  # No HSA yet: the page asks you to add it.
    # A quarterly statement listing the quarter's deferrals (three paychecks added up) settles it.
    with store.connection() as db:
        db.execute("INSERT INTO investment_events(account_id,event_date,event_type,contribution_source,amount_minor,review_status,created_at) "
                   "VALUES(?,'2026-08-31','contribution','employee',?,'verified','t')", (vanguard["id"], 3 * 25000))
    summary = investments.summary()
    assert [question["label"] for question in summary["payroll_questions"]] == ["HSA"] and investments.get(vanguard["id"])["payroll_link"] == "auto"
    # Your own choice wins and is kept; "no employer" is kept too.
    chosen = investments.choose_payroll_account(fidelity["id"], acme)
    assert (chosen["payroll_employer"], chosen["payroll_link"]) == ("Acme Corp", "user")
    with pytest.raises(ValueError, match="already go to Fidelity"):
        investments.update(vanguard["id"], AccountUpdate(name="Vanguard 401(k)", kind="401k", payroll_employer_id=acme))
    investments.update(vanguard["id"], AccountUpdate(name="Vanguard 401(k)", kind="401k", payroll_employer_id=0))
    assert investments.get(vanguard["id"])["payroll_link"] == "none" and investments.get(fidelity["id"])["payroll_link"] == "user"
    with pytest.raises(ValueError, match="retirement accounts and HSAs"):
        investments.add(AccountInput(name="Brokerage", kind="brokerage", currency="USD", value="1", as_of="2026-06-30", payroll_employer_id=acme))


def test_bank_payments_into_an_investment_are_transfers_not_spending(books):
    store, investments, docs = books
    ledger = Ledger(store)
    checking = ledger.create_account("First Bank", "checking", "USD", last_four="1234")
    with store.connection() as db:
        for number, (day, text, amount, kind) in enumerate([("2026-09-14", "VANGUARD BUY INVESTMENT", -50000, "purchase"),
                                                             ("2026-09-03", "GROCERY MART", -20000, "purchase"),
                                                             ("2026-09-02", "ONLINE TRANSFER", -20000, "transfer"),
                                                             ("2026-09-04", "ONLINE TRANSFER", -20000, "transfer")]):
            db.execute("INSERT INTO transactions(account_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,source_fingerprint,"
                       "created_at,updated_at) VALUES(?,?,?,?,'USD',?,'manual','proposed',?,'t','t')", (checking["id"], day, text, amount, kind, f"f{number}"))
    published = statement(investments, docs["sep.png"], "Vanguard", "Brokerage", "2026-09-30", 900000,
                          [{"name": "Deposit", "event_date": "2026-09-15", "event_type": "contribution", "contribution_source": "personal", "amount_minor": 50000},
                           {"name": "Deposit", "event_date": "2026-09-03", "event_type": "contribution", "contribution_source": "personal", "amount_minor": 20000}])
    investments.review(published["id"], "verified")
    summary = Reconciler(store).run("manual")
    assert summary["investment_transfers"] == 1
    with store.connection() as db:
        kinds = dict(db.execute("SELECT description_raw || ' ' || posted_date, transaction_type FROM transactions"))
        [issue] = db.execute("SELECT * FROM reconciliation_issues WHERE issue_type='ambiguous_investment_transfer'").fetchall()
    # The purchase line naming Vanguard paid the first deposit, so it's a transfer; the grocery charge of the same size as the
    # second is never a candidate, and the two transfers around it are a question for you.
    assert kinds["VANGUARD BUY INVESTMENT 2026-09-14"] == "transfer" and kinds["GROCERY MART 2026-09-03"] == "purchase"
    account = investments.get(published["account_id"])
    assert [event["paid_from"] for event in account["events"]] == [checking["display_name"], None]
    with store.connection() as db:
        candidates = db.execute("SELECT id FROM transactions WHERE posted_date='2026-09-04'").fetchone()[0]
    Reconciler(store).resolve_issue(issue["id"], candidates)
    assert [bool(event["paid_from"]) for event in investments.get(published["account_id"])["events"]] == [True, True]
    # The forecast takes your recent payments in from cash, six months' average.
    [asset] = Investments(store, TODAY).forecast_assets("2026-03-01", "2026-09-30", 6)
    assert asset["personal_monthly_minor"] == (50000 + 20000) // 6 + 1  # 11666.67 rounds half-even to 11667.
    # Undoing the automatic match: the purchase line is a purchase again, and with no other line it stays unmatched for good.
    deposit, chosen = investments.get(published["account_id"])["events"]
    assert (deposit["paid_from_link"], chosen["paid_from_link"]) == ("auto", "user")
    assert Reconciler(store).unlink_investment(deposit["id"]) == {"event_id": deposit["id"], "question": False, "candidates": 0}
    Reconciler(store).run("manual")
    with store.connection() as db:
        assert db.execute("SELECT transaction_type FROM transactions WHERE posted_date='2026-09-14'").fetchone()[0] == "purchase"
    assert investments.get(published["account_id"])["events"][0]["paid_from"] is None
    with pytest.raises(ValueError, match="No bank or card payment"):
        Reconciler(store).unlink_investment(deposit["id"])
    # Undoing your own choice: the other line that could have paid it becomes the question, even alone; the pass leaves it to you.
    assert Reconciler(store).unlink_investment(chosen["id"])["question"] is True
    Reconciler(store).run("manual")
    with store.connection() as db:
        issue = db.execute("SELECT * FROM reconciliation_issues WHERE record_id=? AND status='open'", (chosen["id"],)).fetchone()
        other = db.execute("SELECT id FROM transactions WHERE posted_date='2026-09-02'").fetchone()[0]
        assert db.execute("SELECT transaction_type FROM transactions WHERE posted_date='2026-09-04'").fetchone()[0] == "transfer"  # It was a transfer already.
    assert json.loads(issue["detail_json"])["candidate_transaction_ids"] == [other]
    assert investments.get(published["account_id"])["events"][1]["paid_from"] is None
    Reconciler(store).resolve_issue(issue["id"], other)
    assert investments.get(published["account_id"])["events"][1]["paid_from_link"] == "user"
