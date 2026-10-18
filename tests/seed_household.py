"""The synthetic household: one seed shared by ui_shots.py and the agent test instance (scripts/test_instance.py reset).

seed() fills the library the caller already opened, in named steps, and returns the ids routes can name plus a manifest
of what it made. A step that raises is reported as SeedStepFailed(step), so a broken helper names itself. Synthetic data
only; dates are relative to today.
"""

from datetime import date, timedelta

from conftest import inbox_scan
from home_manager.documents.reviewer import ReviewerConfig
from home_manager.finance.forecast import AssetInput, Assets
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools
from seed_documents import seed_documents, seed_review_items
from seed_items import seed_items
from seed_processing import seed_processing
from seed_taxes import seed_tax_year
from seed_wealth import seed_investments, seed_plans
from test_reconcile_tools import add, receipt

STEPS = ("seed_ledger", "seed_today", "seed_money", "seed_taxes", "seed_investments", "seed_plans", "seed_documents",
         "seed_review_items", "seed_items", "seed_processing", "seed_settings")

# Each manifest section as one count over the library database. Waiting for review: records still proposed or needing review.
SECTIONS = {
    "accounts": "SELECT count(*) FROM accounts",
    "transactions": "SELECT count(*) FROM transactions",
    "receipts": "SELECT count(*) FROM receipts",
    "budgets": "SELECT count(*) FROM budgets",
    "assets": "SELECT count(*) FROM assets",
    "documents": "SELECT count(*) FROM occurrences",
    "to_check": "SELECT (SELECT count(*) FROM receipts WHERE review_status IN ('proposed','needs_review'))"
                " + (SELECT count(*) FROM statements WHERE review_status IN ('proposed','needs_review'))"
                " + (SELECT count(*) FROM income_records WHERE review_status IN ('proposed','needs_review'))"
                " + (SELECT count(*) FROM item_resolutions WHERE review_status='proposed')",
    "investments": "SELECT count(*) FROM investment_accounts",
    "plans": "SELECT count(*) FROM scenarios",
    "items": "SELECT count(*) FROM inventory_lots",
    "recurring": "SELECT count(*) FROM recurring_obligations",
}
VALUES = {
    "groceries_budget_minor": "SELECT amount_minor FROM budgets WHERE category='groceries' AND currency='USD'",
    "car_loan_minor": "SELECT value_minor FROM assets WHERE name='Car loan'",
}


class SeedStepFailed(RuntimeError):
    def __init__(self, step):
        super().__init__(f"seed step failed: {step}")
        self.step = step


def manifest(db, taxes_seeded):
    """Counts per section and the named values, from any connection to the library database (sqlite3 rows or tuples)."""
    return {"counts": {name: db.execute(sql).fetchone()[0] for name, sql in SECTIONS.items()},
            "values": {name: (db.execute(sql).fetchone() or [None])[0] for name, sql in VALUES.items()},
            "taxes_seeded": taxes_seeded}


def seed(manager, root, model, fail_step=None):
    """A household in the open library: accounts, a month of spending, budgets, statements, a car and its loan, recurring
    payments, this year's taxes, investments, two What If plans, read and recorded documents and To check items, household
    items, processing failures and settings. Folders it watches go under root. fail_step makes that step raise (tests).
    Returns (ids for --routes placeholders, manifest)."""
    if fail_step is not None and fail_step not in STEPS:
        raise ValueError(f"Unknown seed step: {fail_step}")
    if manager.store is None:
        raise RuntimeError("Open a library before seeding it.")

    def run(name, call, *args):
        try:
            if name == fail_step:
                raise RuntimeError(f"Deliberate failure in {name} (test).")
            return call(*args)
        except Exception as exc:
            raise SeedStepFailed(name) from exc

    checking, card = run("seed_ledger", seed_ledger, manager)
    run("seed_today", seed_today, manager, checking, card)
    run("seed_money", seed_money, manager, checking, card)
    # This year's taxes (a pay stub, interest, the federal table), when the tax engine covers this year.
    taxes_seeded = run("seed_taxes", seed_tax_year, manager, manager.store, manager.ledger)
    # Investment accounts of every kind (tests/seed_wealth.py); {ira_account}, {brokerage_account} and so on name them.
    ids = {f"{name}_account": account_id for name, account_id in run("seed_investments", seed_investments, manager).items()}
    # Two What If plans (tests/seed_wealth.py); {plan} is Tom's move, {raise_plan} the raise.
    ids.update(run("seed_plans", seed_plans, manager))
    # Last: once a reasoning model is set, newly captured documents are recorded as well as read. Then one of each other
    # To check kind (a product, a warranty, a tax table, images that look like one document).
    documents = run("seed_documents", seed_documents, manager, model)
    ids.update(documents)
    ids.update(run("seed_review_items", seed_review_items, manager, documents))
    # Household items after the To check kinds, so the Acme toaster gets its extended warranty (tests/seed_items.py);
    # {drill_lot}, {towel_lot} and {cereal_lot} name lots.
    ids.update(run("seed_items", seed_items, manager))
    # Processing: a failed reading and model run, a watched folder and two health warnings (tests/seed_processing.py).
    ids.update(run("seed_processing", _seed_processing, manager, root))
    run("seed_settings", seed_settings, manager, model)
    with manager.store.connection() as db:
        return ids, manifest(db, bool(taxes_seeded))


def seed_ledger(manager):
    """Two accounts, a month of spending across categories, a receipt, and budgets. Returns (checking, card)."""
    inbox_scan(manager.store, {"checking-statement.csv": b"Date,Description,Amount\n",
                               "card-statement.csv": b"Date,Description,Amount\n"})
    docs = manager.store.documents()["items"]
    checking = manager.ledger.create_account("Household checking", "checking", "USD")
    card = manager.ledger.create_account("Everyday card", "credit_card", "USD")
    # Every date falls in this month, on or before today, so the Home period counts it.
    first = date.today().replace(day=1)
    day = lambda n: first.replace(day=min(n, date.today().day)).isoformat()  # noqa: E731
    verified = add(manager.store, manager.ledger, checking, docs[0], [
        (day(1), "PAYROLL ACME CORP", 412500), (day(1), "CITY UTILITIES", -8950),
        (day(1), "Rent - Maple Street", -165000), (day(2), "Fresh Market", -12480),
        (day(3), "Corner Cafe", -1860), (day(4), "Metro Transit", -4500)], status="verified")
    proposed = add(manager.store, manager.ledger, card, docs[-1], [
        (day(2), "Hardware Depot", -6342), (day(3), "Streaming Plus", -1599),
        (day(4), "Fresh Market", -9875)])
    receipt(manager.ledger, docs[0], "Fresh Market", day(4), 9875)
    categories = ["income", "utilities", "housing", "groceries", "dining", "transport"]
    with manager.store.connection() as db:
        for txn_id, category in zip(verified, categories):
            db.execute("UPDATE transactions SET category=?,category_source='user' WHERE id=?", (category, txn_id))
        db.execute("UPDATE transactions SET category='groceries',category_source='user' WHERE id=?", (proposed[-1],))
    manager.ledger.set_budget("groceries", "USD", "250.00")
    manager.ledger.set_budget("dining", "USD", "120.00")
    return checking, card


def _seed_processing(manager, root):
    (root / "scanner").mkdir()
    return seed_processing(manager, root / "scanner")


def seed_settings(manager, model):
    """Settings › Independent checks shows a second chat model as the reviewer, and Donate has one checked receipt."""
    manager.configure_reviewer(ReviewerConfig(provider="chat", base_url=model["config"].base_url, model="synthetic-reasoning"))
    donations = manager.donations()
    receipt_row = next(row for row in donations.candidates() if row["record_type"] == "receipt")
    check = donations.start("receipt", receipt_row["id"])
    donations.save(check["id"], {"merchant": {"text": "Fresh Market", "state": "fixed"}}, finish=True)


def seed_today(manager, checking, card):
    """What Today shows beyond one month: statement balances (the card's over 35 days old), a car and its loan, a
    confirmed monthly rent due in about ten days, and spending in the two months before, so the trend has bars."""
    store, ledger = manager.store, manager.ledger
    inbox_scan(store, {"checking-statement.pdf": b"synthetic checking statement", "card-statement.pdf": b"synthetic card statement",
                       "rent-receipt.png": b"synthetic rent receipt", "history.csv": b"Date,Description,Amount\n"})
    docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in store.documents()["items"]}
    today = date.today()
    with store.connection() as db:
        for account, name, back, closing, kind in ((checking, "checking-statement.pdf", 5, 841230, "bank"), (card, "card-statement.pdf", 60, 31245, "credit_card")):
            doc = docs[name]
            db.execute("INSERT INTO statements(account_id,document_id,blob_hash,statement_type,period_end,closing_balance_minor,currency,review_status,"
                       "created_at,updated_at) VALUES(?,?,?,?,?,?,'USD','verified','t','t')",
                       (account["id"], doc["id"], doc["current_hash"], kind, (today - timedelta(days=back)).isoformat(), closing))
    assets = Assets(store)
    assets.add(AssetInput(name="Family car", kind="vehicle", value="18000", currency="USD", as_of=today.isoformat()))
    # A rate and payment so the forecast pays it down (at 0% its notes say the loan never shrinks).
    assets.add(AssetInput(name="Car loan", kind="loan", value="6000", currency="USD", as_of=today.isoformat(),
                          annual_rate_percent="6", monthly_payment="350.00"))
    # A confirmed monthly rent paid 20 days ago, so it is next due in about ten.
    rent = docs["rent-receipt.png"]
    ledger.publish_receipt({"merchant": "Maple Street Rentals", "purchase_date": (today - timedelta(days=20)).isoformat(), "subtotal_minor": None,
                            "tax_minor": None, "tip_minor": None, "total_minor": 165000, "currency": "USD", "issues": [], "items": [],
                            "category": "housing", "recurrence": "monthly", "locator": {"line_ids": ["line-1"]}},
                           {"document_id": rent["id"], "blob_hash": rent["current_hash"], "source_key": "extraction:rent", "run_id": "extraction:rent"}, "verified")
    reconciler = Reconciler(store)
    reconciler.run()
    bill = next(row for row in FinanceTools(store).get_recurring_obligations()["obligations"] if row["merchant"] == "Maple Street Rentals")
    reconciler.review_obligation(bill["id"], "verified")
    earlier = lambda months: (today.replace(day=1) - timedelta(days=1 + 31 * (months - 1))).replace(day=12).isoformat()  # noqa: E731
    add(store, ledger, checking, docs["history.csv"], [(earlier(1), "Fresh Market", -21040), (earlier(1), "Corner Cafe", -4210),
                                                        (earlier(2), "Fresh Market", -18825), (earlier(2), "Metro Transit", -4500)], status="verified")


def seed_money(manager, checking, card):
    """What the Money screens show beyond Today's seed: a confirmed subscription, a proposed recurring payment, a refund
    credit this month, a payment entered by hand, a bank export waiting in the inbox, and a category rule."""
    store, ledger = manager.store, manager.ledger
    inbox_scan(store, {"money-history.csv": b"Date,Description,Amount\n",
                       "bank-export.csv": b"Date,Description,Amount\n2026-01-05,BAKERY ROW,-6.40\n2026-01-06,METRO TRANSIT,-45.00\n2026-01-07,PAYROLL ACME CORP,4125.00\n"})
    docs = {doc["relative_path"].rsplit("/", 1)[-1]: doc for doc in store.documents()["items"]}
    today = date.today()
    first = today.replace(day=1)
    def month_back(months, day):
        year, month = divmod(first.year * 12 + first.month - 1 - months, 12)
        return date(year, month + 1, day).isoformat()
    add(store, ledger, checking, docs["money-history.csv"],
        [(month_back(m, 5), "STREAMING PLUS", -1599) for m in (1, 2, 3)]
        + [(month_back(m, 9), "HARBOR INSURANCE", -10000) for m in (1, 2, 3)], status="verified")
    add(store, ledger, card, docs["money-history.csv"], [(first.replace(day=min(3, today.day)).isoformat(), "Fresh Market", 1248)], status="verified")
    ledger.add_manual_transaction(checking["id"], first.replace(day=min(6, today.day)).isoformat(), "Farmers market", "23.00", "out", "groceries")
    ledger.add_rule("METRO", "transport", None)
    reconciler = Reconciler(store)
    reconciler.run()
    for row in FinanceTools(store).get_recurring_obligations()["obligations"]:
        if row["merchant"].upper().startswith("STREAMING PLUS") and row["status"] == "proposed":
            reconciler.review_obligation(row["id"], "verified", kind="subscription")
