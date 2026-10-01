"""ECB rate cache, lookups and USD conversion (docs/currency-conversion.md), with a synthetic ECB file only."""

from decimal import Decimal
import io
import sqlite3
import zipfile

import pytest

from conftest import assert_ledger_healthy, documents_by_name, inbox_scan
from home_manager.core.money import MoneyError, convert_minor
from home_manager.finance.fx import EcbRates, FxError, ProviderError, RateMissing, RateStale, RateUnsupported
from home_manager.finance.ledger import Ledger
from home_manager.finance.reconcile import Reconciler
from home_manager.finance.tools import FinanceTools, call_tool
from home_manager.library.storage import Store
from home_manager.models.web_lookup import LookupFailed

HISTORY = ("Date,USD,JPY,MXN,PHP,HUF,\n"
           "2025-03-14,1.0900,161.50,21.80,62.40,400.1,\n"
           "2025-03-13,1.0850,160.00,21.70,N/A,399.0,\n"
           "2025-03-03,1.0500,157.00,21.40,60.00,398.0,\n")


def ecb_zip(text=HISTORY):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("eurofxref-hist.csv", text)
    return buffer.getvalue()


class FakeEcb:
    def __init__(self, body=None, status=200, error=None):
        self.body, self.status, self.error, self.calls = body if body is not None else ecb_zip(), status, error, []

    def __call__(self, url, headers=None, max_bytes=None):
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.status, "application/zip", self.body, url


@pytest.fixture
def store(tmp_path):
    store = Store(tmp_path / "managed")
    try:
        yield store
    finally:
        store.close()


@pytest.fixture
def rates(store):
    rates = EcbRates(store, FakeEcb())
    rates.refresh()
    return rates


def test_weekend_uses_the_latest_prior_publication_and_converts_half_even(rates):
    handle = rates.lookup("MXN", "2025-03-15")  # Saturday
    assert (handle.rate_id, handle.rate_date, handle.requested_date) == ("ecb:2025-03-14:MXN", "2025-03-14", "2025-03-15")
    assert handle.usd_per_unit == Decimal("1.0900") / Decimal("21.80")
    assert handle.convert(100_000) == 5_000  # 1,000.00 MXN at 0.05
    assert rates.lookup("JPY", "2025-03-14").convert(1_000) == 675  # 1,000 JPY = 6.7492… USD
    assert rates.lookup("EUR", "2025-03-14").convert(1_000) == 1_090
    assert rates.lookup("USD", "2025-03-14") is None
    assert rates.resolve("ecb:2025-03-14:MXN") == rates.lookup("MXN", "2025-03-14")


def test_gaps_future_and_unsupported_currencies_never_produce_a_rate(rates):
    with pytest.raises(RateStale):
        rates.lookup("MXN", "2025-03-12")  # 03-03 is nine days earlier
    with pytest.raises(RateStale):
        rates.lookup("PHP", "2025-03-13")  # N/A that day, and 03-03 is too old
    with pytest.raises(FxError):
        rates.lookup("MXN", "2999-01-01")
    with pytest.raises(RateUnsupported):
        rates.lookup("BHD", "2025-03-14")  # A supported money currency the ECB doesn't publish
    with pytest.raises(RateUnsupported):
        rates.lookup("XYZ", "2025-03-14")
    for invented in ("ecb:2025-03-15:MXN", "ecb:2025-03-14:BHD", "1.09", "", None):
        with pytest.raises(FxError):
            rates.resolve(invented)


def test_an_empty_or_outdated_cache_is_missing_not_guessed(store):
    with pytest.raises(RateMissing):
        EcbRates(store, FakeEcb()).lookup("MXN", "2025-03-14")
    with store.connection() as db:
        set_id = db.execute("INSERT INTO fx_rate_sets(source,fetched_at,first_date,last_date,sha256,byte_size,rates_added) "
                            "VALUES('ecb','2025-03-10T08:00:00+00:00','2025-03-07','2025-03-07',?,1,2)", ("a" * 64,)).lastrowid
        db.executemany("INSERT INTO fx_rates(source,rate_date,currency,per_eur,rate_set_id) VALUES('ecb','2025-03-07',?,?,?)",
                       [("USD", "1.08", set_id), ("MXN", "21.5", set_id)])
    rates = EcbRates(store, FakeEcb())
    assert rates.lookup("MXN", "2025-03-09").rate_date == "2025-03-07"  # Downloaded after that Sunday
    with pytest.raises(RateMissing):
        rates.lookup("MXN", "2025-03-11")  # The cache was downloaded before this day, so a newer rate may exist


def test_downloads_add_new_rates_only_and_rates_are_immutable(store, rates):
    again = EcbRates(store, FakeEcb(ecb_zip(HISTORY.replace("21.80", "99.99") + "2025-03-17,1.1,162,22,63,401,\n")))
    result = again.refresh()
    assert (result["rates_added"], result["conflicts"]) == (4, 1)
    assert rates.lookup("MXN", "2025-03-14").currency_per_eur == "21.80"  # The first published value stands
    assert rates.lookup("MXN", "2025-03-17").currency_per_eur == "22"
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM fx_rates WHERE currency='HUF'").fetchone()[0] == 0  # Only supported currencies
    for statement in ("UPDATE fx_rates SET per_eur='1'", "DELETE FROM fx_rates", "UPDATE fx_rate_sets SET sha256=sha256", "DELETE FROM fx_rate_sets"):
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            with store.connection() as db:
                db.execute(statement)


@pytest.mark.parametrize("fake", [FakeEcb(b"not a zip"), FakeEcb(status=503), FakeEcb(error=LookupFailed("The request failed (TimeoutError).")),
                                  FakeEcb(ecb_zip("Date,USD\n2025-03-14,abc\n")), FakeEcb(ecb_zip("When,USD\n"))])
def test_provider_failures_are_typed_and_store_nothing(store, fake):
    with pytest.raises(ProviderError):
        EcbRates(store, fake).refresh()
    assert EcbRates(store, fake).status()["downloaded"] is False


def test_turned_off_means_no_request(store):
    fake = FakeEcb()
    with pytest.raises(RateMissing):
        EcbRates(store, fake, enabled=False).refresh()
    assert fake.calls == [] and EcbRates(store, fake, enabled=False).due() is False
    assert EcbRates(store, fake).due() is True


def test_consolidate_converts_line_by_line_and_reports_what_it_could_not(store, rates):
    result = rates.consolidate([("2025-03-14", "USD", 1_000), ("2025-03-15", "MXN", 100_000), ("2025-03-15", "MXN", 1),
                                ("2025-03-14", "BHD", 5_000)])
    assert result["usd"]["minor"] == 6_000  # 0.01 MXN rounds to 0.00 USD on its own line
    assert result["status"] == "partial" and result["rate_ids"] == ["ecb:2025-03-14:MXN"]
    assert [(item["currency"], item["code"], item["rows"], item["amount"]["decimal"]) for item in result["unresolved"]] == [("BHD", "unsupported_currency", 1, "5.000")]


def test_usd_only_needs_no_rates_at_all(store):
    fake = FakeEcb()
    result = EcbRates(store, fake).consolidate([("2025-03-14", "USD", 1_000), ("2025-03-15", "USD", -250)])
    assert (result["usd"]["minor"], result["status"], result["basis"], fake.calls) == (750, "complete", "usd", [])


@pytest.fixture
def trip(store, rates):
    """A USD card used in Mexico, and an approved MXN receipt for one of its charges."""
    inbox_scan(store, {"card.csv": b"date,amount\n", "oxxo.png": b"synthetic mxn receipt"})
    docs = documents_by_name(store)
    ledger = Ledger(store)
    card = ledger.create_account("Travel Card", "credit_card", "USD")
    rows = [("2025-03-17", "OXXO CANCUN QR", -5_150), ("2025-03-16", "OXXO PLAYA", -6_200), ("2025-03-16", "HOTEL ZONA", -9_000)]
    with store.connection() as db:
        charges, _ = ledger.insert_transactions(db, card, [{"posted_date": day, "description": text, "amount_minor": amount, "currency": "USD",
                                                            "locator": {"rows": [index]}} for index, (day, text, amount) in enumerate(rows, 1)],
                                                "import", {"document_id": docs["card.csv"]["id"], "blob_hash": docs["card.csv"]["current_hash"],
                                                           "source_key": "import:card"})
    doc = docs["oxxo.png"]
    receipt = ledger.publish_receipt({"merchant": "OXXO", "purchase_date": "2025-03-15", "subtotal_minor": None, "tax_minor": None, "tip_minor": None,
                                      "total_minor": 100_000, "currency": "MXN", "issues": [], "items": [], "locator": {"line_ids": ["line-1"]}},
                                     {"document_id": doc["id"], "blob_hash": doc["current_hash"], "source_key": "extraction:oxxo", "run_id": "r"},
                                     "verified")["id"]
    return ledger, charges, receipt


MARCH = {"start": "2025-03-01", "end": "2025-03-31"}


def test_a_foreign_receipt_and_its_card_charge_count_once(store, trip):
    _, charges, receipt = trip
    tools = FinanceTools(store)
    before = call_tool(tools, "get_spending", MARCH)
    assert [(row["currency"], row["net_spending"]["decimal"]) for row in before["by_currency"]] == [("MXN", "1000.00"), ("USD", "203.50")]
    assert (before["usd_total"]["net"]["decimal"], before["usd_total"]["status"], before["usd_total"]["rate_ids"]) == ("253.50", "complete", ["ecb:2025-03-14:MXN"])
    assert call_tool(tools, "calculate_cashflow", MARCH)["usd_total"]["outflow"]["decimal"] == "253.50"

    reconciler = Reconciler(store)
    reconciler.run()
    with store.connection() as db:
        issue = db.execute("SELECT id,record_id,detail_json FROM reconciliation_issues WHERE status='open'").fetchone()
    # 51.50 is 3% over the 50.00 estimate, 62.00 is 24% over; the hotel names another merchant and is out of range.
    assert issue["record_id"] == receipt and issue["detail_json"] == f'{{"candidate_transaction_ids": [{charges[0]}]}}'
    reconciler.resolve_issue(issue["id"], charges[0])
    with store.connection() as db:
        link = db.execute("SELECT review_status,match_method,estimate_rate_id,estimate_minor FROM transaction_receipt_links").fetchone()
    assert tuple(link) == ("verified", "cross_currency+date+merchant+user_choice", "ecb:2025-03-14:MXN", 5_000)

    after = call_tool(tools, "get_spending", MARCH)
    assert [(row["currency"], row["net_spending"]["decimal"]) for row in after["by_currency"]] == [("USD", "203.50")]
    assert after["usd_total"] is None  # USD only again: no rates involved
    assert_ledger_healthy(store)


def test_rate_tools_use_exactly_the_cached_rate_and_refuse_anything_else(store, trip):
    _, charges, receipt = trip
    tools = FinanceTools(store)
    found = call_tool(tools, "lookup_exchange_rate", {"currency": "mxn", "date": "2025-03-15"})
    assert (found["status"], found["rate_id"], found["rate_date"]) == ("found", "ecb:2025-03-14:MXN", "2025-03-14")
    converted = call_tool(tools, "convert_document_amount", {"receipt_id": receipt, "rate_id": found["rate_id"]})
    assert (converted["original"]["display"], converted["usd"]["display"], converted["provisional"], converted["matched_charge"]) == (
        "1,000.00 MXN", "50.00 USD", False, None)
    for wrong in ("ecb:2025-03-14:JPY", "ecb:2025-03-13:MXN", "ecb:2025-03-15:MXN", "1.09"):
        with pytest.raises(ValueError):
            call_tool(tools, "convert_document_amount", {"receipt_id": receipt, "rate_id": wrong})
    with pytest.raises(ValueError):
        call_tool(tools, "convert_document_amount", {"receipt_id": receipt, "rate_id": found["rate_id"], "rate": "1"})
    assert call_tool(tools, "lookup_exchange_rate", {"currency": "BHD", "date": "2025-03-15"})["code"] == "unsupported_currency"
    assert call_tool(tools, "lookup_exchange_rate", {"currency": "USD", "date": "2025-03-15"})["status"] == "not_needed"


def test_convert_minor_rescales_between_exponents_half_even():
    assert convert_minor(250, "USD", Decimal("1"), "JPY") == 2
    assert convert_minor(350, "USD", Decimal("1"), "JPY") == 4
    assert convert_minor(1_005, "BHD", Decimal("1"), "USD") == 100
    assert convert_minor(-1_015, "BHD", Decimal("1"), "USD") == -102
    assert convert_minor(10**15, "MXN", Decimal("0.05"), "USD") == 5 * 10**13
    for bad in (Decimal("0"), Decimal("-1"), Decimal("NaN"), 1.5):
        with pytest.raises(MoneyError):
            convert_minor(100, "MXN", bad, "USD")
