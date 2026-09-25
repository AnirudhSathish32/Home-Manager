"""Phase 4: canonical finance storage with exact money, evidence links and review states."""

import sqlite3

import pytest

from home_manager.finance import Ledger, classify_transaction, normalize_name
from decimal import Decimal

from home_manager.money import MoneyError, as_decimal_text, decimals_in, format_minor, printed_decimal, to_minor
from home_manager.scanner import Scanner, ScanLimits
from home_manager.storage import Store


@pytest.mark.parametrize("text,currency,expected", [
    ("25.00", "USD", 2500), ("-1,234.56", "USD", -123456), ("(45.10)", "USD", -4510), ("45.10-", "USD", -4510),
    ("+2,000.00", "USD", 200000), ("$19.99", "USD", 1999), ("25.00 USD", "usd", 2500), ("€3.50", "EUR", 350),
    ("1200", "JPY", 1200), ("0.1", "USD", 10), (".5", "USD", 50), ("12.345", "KWD", 12345), (7, "USD", 700),
])
def test_money_parses_exactly(text, currency, expected):
    assert to_minor(text, currency) == expected


@pytest.mark.parametrize("text,currency", [
    ("1.234,56", "EUR"), ("12,34", "USD"), ("25.001", "USD"), ("1.5", "JPY"), ("25.00 EUR", "USD"), ("€5", "USD"),
    ("$5", "XYZ"), ("", "USD"), ("abc", "USD"), ("1e3", "USD"), (19.99, "USD"), (True, "USD"), ("5", None),
])
def test_money_rejects_ambiguous_or_lossy_values(text, currency):
    with pytest.raises(MoneyError):
        to_minor(text, currency)


def test_money_arithmetic_has_no_float_drift():
    assert sum(to_minor("0.10", "USD") for _ in range(3)) == to_minor("0.30", "USD")
    assert as_decimal_text(-4510, "USD") == "-45.10" and as_decimal_text(1200, "JPY") == "1200"
    assert format_minor(123456789, "USD") == "1,234,567.89 USD"
    assert decimals_in("2026-08-03 GROCERY MART -1,045.10 bal 12.00") >= {Decimal("1045.10"), Decimal("12")}
    assert printed_decimal("$1,045.10") == Decimal("1045.10") and printed_decimal("10 or 12") is None


def test_merchant_and_transaction_classification_are_deterministic():
    assert normalize_name("Costco Whse #1234, Inc.") == normalize_name("COSTCO WHSE 1234") == "COSTCO WHSE"
    assert classify_transaction("PAYMENT - THANK YOU", 50000, "credit_card") == "payment"
    assert classify_transaction("ONLINE PAYMENT TO CREDIT CARD 7314", -50000, "checking") == "payment"
    assert classify_transaction("ONLINE TRANSFER TO SAVINGS", -10000, "checking") == "transfer"
    assert classify_transaction("PAYMENT TO LANDLORD", -150000, "checking") == "purchase"
    assert classify_transaction("AMAZON MKTPLACE", 2599, "credit_card") == "refund"
    assert classify_transaction("PAYROLL ACME", 200000, "checking") == "deposit"
    assert classify_transaction("MONTHLY SERVICE FEE", -500, "checking") == "fee"


@pytest.fixture
def ledger(tmp_path):
    source = tmp_path / "source"
    (source / "2026" / "09").mkdir(parents=True)
    (source / "2026" / "09" / "export.csv").write_text("date,amount\n")
    store = Store(tmp_path / "managed")
    Scanner(store, ScanLimits(stability_seconds=0)).run(store.create_job(source), source)
    doc = store.documents(source)["items"][0]
    try:
        yield Ledger(store), store, {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "import:test"}
    finally:
        store.close()


def rows(*items):
    return [{"posted_date": date, "description": text, "amount_minor": amount, "currency": "USD", "locator": {"rows": [index]}}
            for index, (date, text, amount) in enumerate(items, 1)]


def test_database_rejects_float_money_and_full_account_numbers(ledger):
    finance, store, source = ledger
    account = finance.create_account("First Local Bank", "checking", "USD", last_four="4821")
    with store.connection() as db:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO transactions(account_id,posted_date,description_raw,amount_minor,currency,transaction_type,origin,review_status,source_fingerprint,created_at,updated_at) "
                       "VALUES(?,'2026-08-01','X',12.5,'USD','purchase','manual','proposed','f','t','t')", (account["id"],))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE accounts SET account_last_four='123456789' WHERE id=?", (account["id"],))
    with pytest.raises(ValueError, match="last four"):
        finance.create_account("Other Bank", "checking", "USD", last_four="1234567890")
    assert finance.create_account("First Local Bank", "checking", "USD", last_four="4821")["id"] == account["id"]
    with pytest.raises(ValueError, match="different currency"):
        finance.create_account("First Local Bank", "checking", "EUR", last_four="4821")


def test_equal_entries_stay_distinct_and_reimports_or_second_sources_do_not_double_count(ledger):
    finance, store, source = ledger
    account = finance.create_account("First Local Bank", "checking", "USD")
    first = rows(("2026-08-03", "COFFEE", -450), ("2026-08-03", "COFFEE", -450), ("2026-08-04", "PAYROLL", 200000))
    with store.connection() as db:
        inserted, duplicates = finance.insert_transactions(db, account, first, "import", source)
    assert len(inserted) == 3 and not duplicates
    with store.connection() as db:
        again, duplicates = finance.insert_transactions(db, account, first, "import", source)
    assert not again and duplicates == inserted
    # The same charges described differently by a statement are recognised, not added.
    statement_source = {**source, "source_key": "extraction:statement"}
    with store.connection() as db:
        extra, duplicates = finance.insert_transactions(db, account, rows(("2026-08-03", "COFFEE SHOP #12 SEATTLE", -450),
                                                                         ("2026-08-03", "COFFEE SHOP #12 SEATTLE", -450)), "extraction", statement_source)
    assert not extra and duplicates == inserted[:2]
    with store.connection() as db:
        assert db.execute("SELECT count(*), sum(amount_minor) FROM transactions").fetchone()[:] == (3, 199100)
    evidence = finance.evidence("transaction", inserted[0])
    assert [item["source_key"] for item in evidence] == ["import:test", "extraction:statement"]
    assert evidence[0]["relative_path"] == "2026/09/export.csv" and evidence[0]["locator"] == {"rows": [1]}


def test_review_is_explicit_and_audited(ledger):
    finance, store, source = ledger
    account = finance.create_account("First Local Bank", "checking", "USD")
    with store.connection() as db:
        [record], _ = finance.insert_transactions(db, account, rows(("2026-08-05", "GROCERY", -1299)), "import", source)
    with pytest.raises(ValueError):
        finance.review("transaction", record, "proposed")
    assert finance.review("transaction", record, "verified", "Matches my bank app.")["review_status"] == "verified"
    finance.review("transaction", record, "rejected")
    assert [(event["previous_status"], event["new_status"]) for event in finance.review_history("transaction", record)] == [
        ("proposed", "verified"), ("verified", "rejected")]
    with pytest.raises(ValueError, match="not found"):
        finance.review("receipt", 999, "verified")
