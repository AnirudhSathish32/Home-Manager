"""Crypto market prices (finance/prices.py) and exchange exports: off by default, at most daily, never over a document's value.
A fake fetch stands in for CoinGecko; synthetic data only."""

from datetime import date
import json

import pytest

from conftest import documents_by_name, inbox_scan
from home_manager.finance.investments import Investments
from home_manager.finance.prices import CryptoPrices, PriceError, positions
from home_manager.library.storage import Store

TODAY = date(2026, 10, 1)
COINBASE = "\n".join([
    "Transactions",
    "User,someone,0000",
    "ID,Timestamp,Transaction Type,Asset,Quantity Transacted,Price Currency,Price at Transaction,Subtotal,Total (inclusive of fees and/or spread),Fees and/or Spread,Notes",
    "a1,2026-09-15 10:00:00 UTC,Buy,BTC,0.05,USD,\"$60,000.00\",\"$3,000.00\",\"$3,015.00\",$15.00,Bought 0.05 BTC for $3015.00 USD",
    "a2,2026-09-16 10:00:00 UTC,Deposit,USD,100,USD,$1.00,$100.00,$100.00,$0.00,",
    "a3,2026-09-17 10:00:00 UTC,Convert,ETH,0.5,USD,\"$2,000.00\",\"$1,000.00\",\"$1,010.00\",$10.00,Converted 0.5 ETH to 0.016 BTC",
    "a4,2026-09-18 10:00:00 UTC,Airdrop party,BTC,0.01,USD,$1.00,$1.00,$1.00,$0.00,",
    "a5,2026-09-19 10:00:00 UTC,Staking Income,ETH,0.6,USD,\"$2,000.00\",\"$1,200.00\",\"$1,200.00\",$0.00,",
]).encode()


class FakeCoinGecko:
    def __init__(self, prices):
        self.prices, self.calls = prices, []

    def __call__(self, url, headers=None, max_bytes=None):
        self.calls.append(url)
        return 200, "application/json", json.dumps(self.prices).encode(), url


@pytest.fixture
def wallet(tmp_path):
    store = Store(tmp_path / "managed")
    inbox_scan(store, {"september.png": b"september statement", "october.png": b"october statement", "coinbase.csv": COINBASE})
    docs = {name.rsplit("/", 1)[-1]: doc for name, doc in documents_by_name(store).items()}
    investments = Investments(store, TODAY)
    try:
        yield store, investments, docs
    finally:
        store.close()


def statement(investments, docs, name, period_end, holdings):
    record = {"investment_kind": "crypto", "institution": "Coinbase", "account_name": "Crypto", "last_four": "7777", "currency": "USD", "issues": [],
              "value_minor": sum(holding["value_minor"] for holding in holdings), "period_end": period_end, "holdings": holdings}
    result = investments.publish_statement(record, {"document_id": docs[name]["id"], "blob_hash": docs[name]["current_hash"], "run_id": name})
    return result


BTC = {"instrument_class": "crypto", "name": "Bitcoin", "identifier": "BTC", "value_minor": 600000, "quantity": "0.1"}
CASH = {"instrument_class": "cash", "name": "US dollars", "identifier": None, "value_minor": 10000}


def confirmed_statement(investments, docs, name="september.png", period_end="2026-09-10", holdings=(BTC, CASH)):
    result = statement(investments, docs, name, period_end, list(holdings))
    investments.review(result["id"], "verified")
    return result["account_id"]


def test_prices_are_off_by_default_and_never_fetched_then(wallet):
    store, investments, docs = wallet
    confirmed_statement(investments, docs)
    fetch = FakeCoinGecko({"bitcoin": {"usd": 65000}})
    prices = CryptoPrices(store, fetch, today=TODAY)
    assert not prices.due() and prices.status()["enabled"] is False
    with pytest.raises(PriceError, match="turned off"):
        prices.refresh()
    assert fetch.calls == []


def test_a_quote_values_units_held_and_refreshes_at_most_daily(wallet):
    store, investments, docs = wallet
    account_id = confirmed_statement(investments, docs)
    fetch = FakeCoinGecko({"bitcoin": {"usd": 65000.5}})
    prices = CryptoPrices(store, fetch, enabled=True, today=TODAY)
    assert prices.due()
    result = prices.refresh()
    assert fetch.calls == ["https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"]  # Coin ids only, never amounts.
    assert result["valued"] == 1 and result["prices"][0]["price"] == "65000.5"
    account = investments.get(account_id)
    # 0.1 BTC × $65,000.50 = $6,500.05, plus the $100.00 of cash carried from the statement.
    assert (account["current"]["value_minor"], account["current"]["source"], account["current"]["as_of"]) == (660005, "quote", "2026-10-01")
    bitcoin = next(holding for holding in account["holdings"] if holding["identifier"] == "BTC")
    assert (bitcoin["value_minor"], bitcoin["price"]["display"], bitcoin["value_source"]) == (650005, "65,000.50 USD", "quote")
    assert not prices.due()  # Fetched today: nothing more until tomorrow, unless asked.
    fetch.prices = {"bitcoin": {"usd": 70000}}
    prices.refresh()  # The user's Refresh prices replaces today's quote rather than adding another.
    assert investments.get(account_id)["current"]["value_minor"] == 710000
    with store.connection() as db:
        assert db.execute("SELECT count(*) FROM investment_valuations WHERE source='quote' AND holding_id IS NULL").fetchone()[0] == 1


def test_a_quote_never_overrides_a_newer_statement_and_gives_way_on_the_same_day(wallet):
    store, investments, docs = wallet
    account_id = confirmed_statement(investments, docs)
    prices = CryptoPrices(store, FakeCoinGecko({"bitcoin": {"usd": 65000}}), enabled=True, today=TODAY)
    prices.refresh()
    # A statement for the same day replaces the quote, and its value counts once confirmed.
    october = statement(investments, docs, "october.png", "2026-10-01", [{**BTC, "value_minor": 640000}, CASH])
    assert october["status"] == "published"
    investments.review(october["id"], "verified")
    account = investments.get(account_id)
    assert (account["current"]["value_minor"], account["current"]["source"]) == (650000, "statement")
    # Today's quote no longer applies once a statement for today (or later) exists.
    assert prices.refresh()["valued"] == 0
    assert investments.get(account_id)["current"]["source"] == "statement"
    later = CryptoPrices(store, FakeCoinGecko({"bitcoin": {"usd": 1}}), enabled=True, today=date(2026, 9, 30))
    assert later.refresh()["valued"] == 0  # The statement of Oct 1 is newer than a quote for Sep 30.


def test_something_without_a_price_leaves_the_account_on_its_statement(wallet):
    store, investments, docs = wallet
    fund = {"instrument_class": "etf", "name": "Bitcoin ETF", "identifier": "IBIT", "value_minor": 50000, "quantity": "10"}
    account_id = confirmed_statement(investments, docs, holdings=(BTC, fund))
    result = CryptoPrices(store, FakeCoinGecko({"bitcoin": {"usd": 65000}}), enabled=True, today=TODAY).refresh()
    assert result["valued"] == 0 and "Bitcoin ETF has no market price" in result["skipped"][0]
    assert investments.get(account_id)["current"]["source"] == "statement"


def test_a_coinbase_export_moves_units_and_opens_lots(wallet):
    store, investments, docs = wallet
    account_id = confirmed_statement(investments, docs)
    imported = investments.import_crypto(account_id, docs["coinbase.csv"]["id"])
    # Buy BTC; convert ETH to BTC (a sale and a purchase); staking income. The fiat deposit is skipped; an unknown type is reported.
    assert imported["added"] == 4 and len(imported["issues"]) == 1 and "Airdrop party" in imported["issues"][0]
    assert investments.import_crypto(account_id, docs["coinbase.csv"]["id"])["added"] == 0  # Importing again adds nothing twice.
    with store.connection() as db:
        held = {position.symbol: position.units for position in positions(db, account_id)}
    assert str(held["BTC"]) == "0.166" and str(held["ETH"]) == "0.1"
    account = investments.get(account_id)
    assert {event["type_label"] for event in account["events"]} == {"Buy", "Sell", "Reward"}
    fetch = FakeCoinGecko({"bitcoin": {"usd": 60000}, "ethereum": {"usd": 2500}})
    CryptoPrices(store, fetch, enabled=True, today=TODAY).refresh()
    assert fetch.calls == ["https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,ethereum&vs_currencies=usd"]
    # 0.166 BTC × $60,000 + 0.1 ETH × $2,500 + $100 cash.
    assert investments.get(account_id)["current"]["value_minor"] == 996000 + 25000 + 10000
