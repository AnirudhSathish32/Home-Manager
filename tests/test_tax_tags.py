"""Tax tags (docs/taxes.md): write-offs, business income and tax paid ahead on ledger items; rules; same-payee and tax
payment suggestions; each item counted once in the year. Synthetic records only."""

from fastapi.testclient import TestClient
import pytest

from conftest import inbox_scan
from home_manager.app.api import create_app
from home_manager.finance.ledger import Ledger
from home_manager.finance.tax_tags import TaxTags
from home_manager.library.scanner import ScanLimits
from home_manager.library.storage import Store
from test_reconcile_tools import receipt


@pytest.fixture
def books(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"export.csv": b"date,amount\n", "receipt.png": b"r"})
    docs = {doc["relative_path"].split("/")[-1]: doc for doc in store.documents()["items"]}
    ledger = Ledger(store)
    account = ledger.create_account("First Local Bank", "checking", "USD")
    doc = next(doc for name, doc in docs.items() if name.endswith(".csv"))
    source = {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:test"}

    def add(*items):
        rows = [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD", "locator": {"rows": [index]}}
                for index, (day, text, amount) in enumerate(items, 1)]
        with store.connection() as db:
            return ledger.insert_transactions(db, account, rows, "import", source)[0]
    try:
        yield store, ledger, TaxTags(store), add, docs
    finally:
        store.close()


def tags_by_id(tags, ids):
    return {tag["transaction_id"]: tag for tag in tags.list() if tag["transaction_id"] in ids}


def test_tagging_by_hand(books):
    _, _, tags, add, _ = books
    work = tags.add_business("Contract work")
    [paid, lunch, gift] = add(("2026-03-02", "ACME CLIENT ACH PAYMENT", 250000), ("2026-03-05", "CAFE LUNCH", -4000), ("2026-03-09", "RED CROSS DONATION", -10000))
    income = tags.tag("transaction", paid, "business_income", "gross_receipts", work["id"])
    assert (income["amount_minor"], income["review_status"], income["source"], income["line_label"]) == (250000, "verified", "user", "Gross receipts (1099-NEC, 1099-K, clients)")
    # Business meals count at 50%.
    meal = tags.tag("transaction", lunch, "business_expense", "meals", work["id"])
    assert (meal["amount_minor"], meal["counted_minor"]) == (4000, 2000)
    assert tags.tag("transaction", gift, "itemized", "charity_cash", amount="60")["amount_minor"] == 6000  # Part of it.
    for kind, line, business, amount, message in (("business_expense", "supplies", None, None, "Choose the business"),
                                                  ("itemized", "charity_cash", work["id"], None, "only for them"),
                                                  ("itemized", "rent", None, None, "isn't a itemized deduction line"),
                                                  ("business_income", "gross_receipts", work["id"], None, "money coming in"),
                                                  ("itemized", "charity_cash", None, "200", "can't be more than")):
        with pytest.raises(ValueError, match=message):
            tags.tag("transaction", gift, kind, line, business, amount)
    assert tags.on("transaction", gift)["line"] == "charity_cash" and tags.on("transaction", 999) is None


def test_rules_tag_bank_lines_and_hand_tags_win(books):
    _, _, tags, add, _ = books
    work = tags.add_business("Contract work")
    [first, mine] = add(("2026-01-05", "ADOBE *CREATIVE CLD 800-833", -5999), ("2026-02-05", "ADOBE *CREATIVE CLD 800-833", -5999))
    tags.tag("transaction", mine, "business_expense", "other", work["id"])
    rule = tags.add_rule("adobe creative", "business_expense", "office", work["id"])
    assert rule["changed"] == 1  # The first line; the one tagged by hand keeps its tag.
    found = tags_by_id(tags, [first, mine])
    assert (found[first]["source"], found[first]["line"], found[mine]["line"]) == ("rule", "office", "other")
    # Lines added later are tagged as they arrive.
    [later] = add(("2026-03-05", "ADOBE *CREATIVE CLD 800-833", -5999))
    assert tags.on("transaction", later)["source"] == "rule"
    # A rule for money out never tags money in.
    [refund] = add(("2026-03-06", "ADOBE *CREATIVE CLD REFUND", 5999))
    assert tags.on("transaction", refund) is None
    assert tags.delete_rule(rule["id"])["changed"] == 2 and tags.on("transaction", first)["source"] == "suggestion"


def test_payees_you_tagged_are_suggested_and_a_no_is_remembered(books):
    store, _, tags, add, _ = books
    [january] = add(("2026-01-10", "BRIGHT HORIZONS TUITION 0110", -120000))
    tags.tag("transaction", january, "credit_spending", "dependent_care")
    [february] = add(("2026-02-10", "BRIGHT HORIZONS TUITION 0210", -120000))
    suggestion = tags.on("transaction", february)
    assert (suggestion["review_status"], suggestion["source"], suggestion["line"]) == ("proposed", "suggestion", "dependent_care")
    assert "this is the same payee" in suggestion["reason"]
    # Confirmed with a rule: later lines are tagged by the rule, without asking.
    tags.review(suggestion["id"], "verified", rule_words="BRIGHT HORIZONS")
    [march] = add(("2026-03-10", "BRIGHT HORIZONS TUITION 0310", -120000))
    assert tags.on("transaction", march)["source"] == "rule"
    # Another payee: tagged once, then "not a write-off" on its next line stops the suggestions.
    [gym] = add(("2026-01-02", "CITY GYM MEMBERSHIP", -5000))
    tags.tag("transaction", gym, "business_expense", "other", tags.add_business("Training")["id"])
    [gym2] = add(("2026-02-02", "CITY GYM MEMBERSHIP", -5000))
    tags.review(tags.on("transaction", gym2)["id"], "rejected")
    [gym3] = add(("2026-03-02", "CITY GYM MEMBERSHIP", -5000))
    assert tags.on("transaction", gym3) is None
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM review_events WHERE record_type='tax_tag'").fetchone()[0] == 2


def test_tax_payments_made_ahead_are_recognized(books):
    _, _, tags, add, _ = books
    [irs, state, other] = add(("2026-04-15", "IRS USATAXPYMT 270612345", -300000), ("2026-04-15", "GA DEPT OF REVENUE PAYMENT", -50000),
                              ("2026-04-16", "IRS REFUND TREAS 310", 20000))
    assert (tags.on("transaction", irs)["line"], tags.on("transaction", irs)["review_status"]) == ("federal_estimated", "proposed")
    assert tags.on("transaction", state)["line"] == "state_estimated"
    assert tags.on("transaction", other) is None  # Money in isn't a payment.


def test_the_year_counts_each_item_once(books):
    store, ledger, tags, add, docs = books
    work = tags.add_business("Contract work")
    [lunch, dropped, next_year] = add(("2026-05-01", "CAFE LUNCH", -4000), ("2026-05-02", "OFFICE DEPOT", -2500), ("2027-01-02", "OFFICE DEPOT", -1000))
    tags.tag("transaction", lunch, "business_expense", "meals", work["id"])
    tags.tag("transaction", dropped, "business_expense", "supplies", work["id"])
    tags.tag("transaction", next_year, "business_expense", "supplies", work["id"])
    ledger.review("transaction", dropped, "rejected")  # Not a real transaction: its tag doesn't count.
    # A standalone receipt counts once it's confirmed.
    receipt_id = receipt(ledger, docs["receipt.png"], "Goodwill", "2026-06-01", 8000)
    tags.tag("receipt", receipt_id, "itemized", "charity_cash")
    year = tags.year(2026, "USD")
    assert [(line["line"], line["amount_minor"], line["counted_minor"]) for line in year["lines"]] == [("meals", 4000, 2000)]
    ledger.review("receipt", receipt_id, "verified")
    assert [(line["kind"], line["line"], line["counted_minor"]) for line in tags.year(2026, "USD")["lines"]] == [
        ("business_expense", "meals", 2000), ("itemized", "charity_cash", 8000)]


def test_tax_tag_endpoints(tmp_path):
    app = create_app(tmp_path / "control", "t", limits=ScanLimits(stability_seconds=0))
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"Authorization": "Bearer t"}) as client:
        client.put("/api/settings", json={"managed_directory": str(tmp_path / "managed")})
        setup = client.get("/api/tax/setup").json()
        assert setup["kinds"]["itemized"] == "Itemized deduction" and any(line["key"] == "meals" for line in setup["lines"]["business_expense"])
        business = client.post("/api/tax/businesses", json={"name": "Contract work"}).json()
        assert client.get("/api/tax/setup").json()["businesses"][0]["name"] == "Contract work"
        rule = client.post("/api/tax/rules", json={"pattern": "adobe", "kind": "business_expense", "line": "office", "business_id": business["id"]})
        assert rule.status_code == 201 and client.get("/api/tax/rules").json()["rules"][0]["line_label"] == "Office expense and software"
        assert client.post("/api/tax/rules", json={"pattern": "x", "kind": "nope", "line": "office"}).status_code == 400
        assert client.post("/api/tax-tags", json={"target_type": "transaction", "target_id": 1, "kind": "itemized", "line": "medical"}).status_code == 400
        assert client.get("/api/tax-tags", params={"status": "proposed"}).json() == {"tags": []}
        assert client.get("/api/tax-tags/on/transaction/1").json() == {"tag": None}
        assert client.get("/api/tax/write-offs/2026").json()["lines"] == []
        assert client.delete(f"/api/tax/rules/{rule.json()['id']}").json()["deleted"]
