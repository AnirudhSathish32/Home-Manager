"""Crypto market prices from CoinGecko, only when the household turns them on (docs/planning.md "Crypto").

The only network access is refresh(): one HTTPS request to CoinGecko's public simple-price endpoint (no key), naming only
coin ids and currencies, never amounts or accounts. It is off by default (HouseholdConfig.fetch_crypto_prices), runs at
most once a day on its own, and again when the user presses Refresh prices. Prices are cached in price_quotes as exact
decimal text, one per coin, currency and day.

A price becomes a 'quote' value: each crypto holding's units times its price, plus cash carried from the statement, for
today. Units come from the newest confirmed statement's holdings, moved by confirmed activity since (buys, sells,
transfers and rewards, as an exchange export records them). Values are append-only and documents win:
- an account with a statement or typed value dated today or later gets no quote;
- a statement for the same date later replaces the quote (Investments.publish_statement);
- an account holding something that has no price here (a fund, an unknown coin) gets no quote at all, never a partial one.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_EVEN, Decimal
import json

from ..core.money import EXPONENTS, money
from ..library.storage import now
from ..models.web_lookup import LookupFailed, https_get
from .investments import QUANTITY_SIGNS
from .tax_lots import share_text, shares

SOURCE = "coingecko"
ENDPOINT = "https://api.coingecko.com/api/v3/simple/price?ids={ids}&vs_currencies={currencies}"
MAX_BYTES = 200_000
REFRESH_AFTER = timedelta(hours=20)
# Ticker symbol -> CoinGecko coin id. A coin not listed here is never priced (its account keeps its statement values).
COINGECKO_IDS = {"BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "USDC": "usd-coin", "USDT": "tether", "ADA": "cardano",
                 "DOGE": "dogecoin", "XRP": "ripple", "LTC": "litecoin", "DOT": "polkadot", "AVAX": "avalanche-2", "LINK": "chainlink",
                 "BCH": "bitcoin-cash", "XLM": "stellar", "SHIB": "shiba-inu", "MATIC": "matic-network", "POL": "polygon-ecosystem-token",
                 "ATOM": "cosmos", "UNI": "uniswap", "ALGO": "algorand", "XTZ": "tezos", "ETC": "ethereum-classic", "DAI": "dai"}
CARRIED = ("cash", "money_market")  # Holdings whose statement value is carried forward as it is.


class PriceError(ValueError):
    """A price refresh that could not be made, for a reason the user may see."""


@dataclass(frozen=True)
class Position:
    holding_id: int
    name: str
    symbol: str
    instrument_class: str
    units: Decimal
    carried_minor: int | None


def positions(db, account_id):
    """Each holding's units now: the newest confirmed statement's quantities, moved by confirmed activity dated after it (a
    trade a confirmation and a statement both list counts once). Cash and money market funds carry their statement value."""
    base = db.execute("SELECT max(as_of) FROM investment_valuations WHERE account_id=? AND holding_id IS NOT NULL AND source<>'quote' "
                      "AND review_status='verified'", (account_id,)).fetchone()[0]
    held = {}
    if base:
        for row in db.execute("SELECT v.holding_id,v.quantity,v.value_minor,h.instrument_class,h.identifier,h.name FROM investment_valuations v "
                              "JOIN holdings h ON h.id=v.holding_id WHERE v.account_id=? AND v.as_of=? AND v.source<>'quote' AND v.review_status='verified'",
                              (account_id, base)):
            held[row["holding_id"]] = {"name": row["name"], "symbol": (row["identifier"] or "").upper(), "class": row["instrument_class"],
                                       "units": shares(row["quantity"]) or Decimal(0), "carried": row["value_minor"]}
    seen = set()
    for row in db.execute(f"SELECT e.holding_id,e.event_type,e.event_date,e.amount_minor,e.quantity,h.instrument_class,h.identifier,h.name "
                          "FROM investment_events e JOIN holdings h ON h.id=e.holding_id WHERE e.account_id=? AND e.review_status='verified' "
                          f"AND e.quantity IS NOT NULL AND e.event_date>? AND e.event_type IN ({','.join('?' * len(QUANTITY_SIGNS))}) "
                          "ORDER BY e.event_date,e.confirmation_id IS NULL,e.id", (account_id, base or "", *QUANTITY_SIGNS)):
        key = (row["holding_id"], row["event_type"], row["event_date"], row["amount_minor"])
        units = shares(row["quantity"])
        if key in seen or units is None:
            continue
        seen.add(key)
        entry = held.setdefault(row["holding_id"], {"name": row["name"], "symbol": (row["identifier"] or "").upper(), "class": row["instrument_class"],
                                                    "units": Decimal(0), "carried": None})
        entry["units"] += QUANTITY_SIGNS[row["event_type"]] * units
    return [Position(holding_id, entry["name"], entry["symbol"], entry["class"], entry["units"], entry["carried"]) for holding_id, entry in held.items()]


def parse_prices(body, wanted):
    """{(coin id, currency): price text} from CoinGecko's simple-price JSON, for the ids and currencies asked for."""
    try:
        data = json.loads(body.decode("utf-8"), parse_float=Decimal, parse_int=Decimal)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PriceError("The price service sent something that isn't JSON.") from exc
    if not isinstance(data, dict):
        raise PriceError("The price service's reply doesn't have the expected layout.")
    found = {}
    for coin, currency in wanted:
        value = (data.get(coin) or {}).get(currency.lower()) if isinstance(data.get(coin), dict) else None
        if value is None:
            continue
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            raise PriceError("The price service sent a price that isn't a positive number.")
        found[(coin, currency)] = f"{value.normalize():f}"
    return found


class CryptoPrices:
    def __init__(self, store, fetch=https_get, enabled=False, today=None):
        self.store, self.fetch, self.enabled, self._today = store, fetch, enabled, today

    @property
    def today(self):
        return (self._today or date.today()).isoformat()

    def accounts(self, db):
        """Open market-valued accounts holding coins: [(account row, positions)]."""
        found = []
        for account in db.execute("SELECT a.id,a.name,a.currency FROM investment_accounts a JOIN investment_kinds k ON k.key=a.kind "
                                  "WHERE a.archived_at IS NULL AND k.value_model='market' ORDER BY a.id"):
            held = positions(db, account["id"])
            if any(position.instrument_class == "crypto" and position.units > 0 for position in held):
                found.append((account, held))
        return found

    def wanted(self, db):
        """(coin id, currency) pairs to ask for, and coin symbols held that have no price source here."""
        pairs, unknown = set(), set()
        for account, held in self.accounts(db):
            for position in held:
                if position.instrument_class != "crypto" or position.units <= 0:
                    continue
                if position.symbol in COINGECKO_IDS:
                    pairs.add((COINGECKO_IDS[position.symbol], account["currency"]))
                else:
                    unknown.add(position.symbol or position.name)
        return sorted(pairs), sorted(unknown)

    # Network: the only method that leaves this device.
    def refresh(self):
        if not self.enabled:
            raise PriceError("Crypto prices are turned off in Settings.")
        with self.store.connection() as db:
            pairs, unknown = self.wanted(db)
        if not pairs:
            return {**self.status(), "valued": 0, "skipped": []}
        url = ENDPOINT.format(ids=",".join(sorted({coin for coin, _ in pairs})), currencies=",".join(sorted({code.lower() for _, code in pairs})))
        try:
            status, _, body, _ = self.fetch(url, {"Accept": "application/json"}, MAX_BYTES)
        except LookupFailed as exc:
            raise PriceError(f"Prices could not be fetched: {exc}") from exc
        if status != 200:
            raise PriceError(f"The price service answered with HTTP {status}.")
        prices = parse_prices(body, pairs)
        symbols = {coin: symbol for symbol, coin in COINGECKO_IDS.items()}
        with self.store.connection() as db:
            db.executemany("INSERT OR REPLACE INTO price_quotes(source,symbol,currency,as_of,price,fetched_at) VALUES(?,?,?,?,?,?)",
                           [(SOURCE, symbols[coin], currency, self.today, price, now()) for (coin, currency), price in sorted(prices.items())])
            valued, skipped = self.value_accounts(db)
        return {**self.status(), "valued": valued, "skipped": skipped}

    # Cache only from here on.
    def value_accounts(self, db):
        """Add today's quote values from today's cached prices. Returns (accounts valued, [why others weren't])."""
        quotes = {(row["symbol"], row["currency"]): Decimal(row["price"]) for row in db.execute(
            "SELECT symbol,currency,price FROM price_quotes WHERE source=? AND as_of=?", (SOURCE, self.today))}
        valued, skipped = 0, []
        for account, held in self.accounts(db):
            if db.execute("SELECT 1 FROM investment_valuations WHERE account_id=? AND holding_id IS NULL AND source<>'quote' AND review_status<>'rejected' "
                          "AND as_of>=?", (account["id"], self.today)).fetchone():
                continue  # A statement or a value you typed for today or later wins.
            currency, scale = account["currency"], Decimal(10) ** EXPONENTS[account["currency"]]
            lines, reason = [], None
            for position in held:
                if position.instrument_class == "crypto":
                    if position.units <= 0:
                        continue
                    price = quotes.get((position.symbol, currency))
                    if price is None:
                        reason = f"{account['name']}: no {currency} price for {position.symbol or position.name}, so it keeps its statement value."
                        break
                    lines.append((position, int((position.units * price * scale).to_integral_value(ROUND_HALF_EVEN)),
                                  int((price * scale).to_integral_value(ROUND_HALF_EVEN))))
                elif position.instrument_class in CARRIED and position.carried_minor is not None:
                    lines.append((position, position.carried_minor, None))
                else:
                    reason = f"{account['name']}: {position.name} has no market price here, so the account keeps its statement value."
                    break
            if reason:
                skipped.append(reason)
                continue
            db.execute("DELETE FROM investment_valuations WHERE account_id=? AND as_of=? AND source='quote'", (account["id"], self.today))
            for position, value, price in lines:
                db.execute("INSERT INTO investment_valuations(account_id,holding_id,as_of,value_minor,quantity,price_minor,source,review_status,created_at,updated_at) "
                           "VALUES(?,?,?,?,?,?,'quote','verified',?,?)", (account["id"], position.holding_id, self.today, value,
                                                                          share_text(position.units) if position.units else None, price, now(), now()))
            db.execute("INSERT INTO investment_valuations(account_id,as_of,value_minor,source,review_status,created_at,updated_at) VALUES(?,?,?,'quote','verified',?,?)",
                       (account["id"], self.today, sum(value for _, value, _ in lines), now(), now()))
            valued += 1
        return valued, skipped

    def status(self):
        with self.store.connection() as db:
            row = db.execute("SELECT max(fetched_at) AS fetched, max(as_of) AS as_of FROM price_quotes WHERE source=?", (SOURCE,)).fetchone()
            pairs, unknown = self.wanted(db)
            latest = [{"symbol": quote["symbol"], "currency": quote["currency"], "as_of": quote["as_of"], "price": quote["price"],
                       "display": money(int((Decimal(quote["price"]) * Decimal(10) ** EXPONENTS[quote["currency"]]).to_integral_value(ROUND_HALF_EVEN)),
                                        quote["currency"])["display"]}
                      for quote in db.execute("SELECT q.* FROM price_quotes q WHERE source=? AND as_of=(SELECT max(as_of) FROM price_quotes p "
                                              "WHERE p.source=q.source AND p.symbol=q.symbol AND p.currency=q.currency) ORDER BY symbol,currency", (SOURCE,))]
        return {"enabled": self.enabled, "fetched_at": row["fetched"], "as_of": row["as_of"], "needed": bool(pairs), "unpriced": unknown,
                "prices": latest, "source": "CoinGecko"}

    def due(self):
        """True when prices are on, coins are held, and nothing was fetched in the last 20 hours (at most daily on its own)."""
        if not self.enabled:
            return False
        state = self.status()
        if not state["needed"]:
            return False
        return not state["fetched_at"] or datetime.fromisoformat(state["fetched_at"]) < datetime.now(timezone.utc) - REFRESH_AFTER
