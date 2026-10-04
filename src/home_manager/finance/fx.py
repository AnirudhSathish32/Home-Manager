"""USD conversion from ECB reference rates cached on this device (docs/money.md "Currency conversion").

The only network access is refresh(): one HTTPS download of the ECB's public history file, which carries no
household data. Everything else reads the local cache, so totals and assistant tools are deterministic and work
offline. A published (date, currency) rate is stored once and never changes (migration 051), and every conversion
cites it by a rate id ("ecb:2026-09-29:MXN") that resolves to the same value later.

Policy (application rules, not exchange-market or tax rules):
- USD needs no rate. Other currencies cross through the euro: USD per unit = (USD per EUR) / (X per EUR).
- Use the latest ECB publication on or before the date, at most seven days earlier (weekends and holidays).
- A date the cache can't speak for yet (rates not downloaded since that day) is missing, never filled with an older
  rate. A future date, an unsupported currency, or a gap over seven days stays unresolved; there is no 1:1, zero or
  today's-rate substitute.
- Each line is converted and rounded half-even on its own, then summed.
"""

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import re
import zipfile

from ..core.money import EXPONENTS, MoneyError, convert_minor, currency_code, money
from ..library.storage import now
from ..models.web_lookup import LookupFailed, https_get

ECB_HISTORY = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
SOURCE, REPORTING = "ecb", "USD"
LOOKBACK_DAYS = 7
MAX_DOWNLOAD_BYTES, MAX_CSV_BYTES, MAX_RATIO = 8_000_000, 40_000_000, 50
REFRESH_AFTER = timedelta(hours=20)
RATE_ID = re.compile(r"ecb:(\d{4}-\d{2}-\d{2}):([A-Z]{3})")
RATE_TEXT = re.compile(r"\d{1,9}(?:\.\d{1,12})?")


class FxError(ValueError):
    """A conversion that could not be made, for a reason the user and the model may see."""

    code = "fx_error"


class RateUnsupported(FxError):
    code = "unsupported_currency"


class RateMissing(FxError):
    code = "rate_missing"


class RateStale(FxError):
    code = "rate_stale"


class ProviderError(FxError):
    code = "provider_error"


@dataclass(frozen=True)
class RateHandle:
    rate_id: str
    currency: str
    requested_date: str
    rate_date: str
    usd_per_unit: Decimal
    usd_per_eur: str
    currency_per_eur: str
    rate_set_id: int
    set_sha256: str

    def view(self):
        return {"rate_id": self.rate_id, "currency": self.currency, "requested_date": self.requested_date,
                "rate_date": self.rate_date, "usd_per_unit": f"{self.usd_per_unit:.10f}",
                "usd_per_eur": self.usd_per_eur, "currency_per_eur": self.currency_per_eur,
                "source": "ECB euro reference rates", "rate_set_id": self.rate_set_id, "set_sha256": self.set_sha256}

    def convert(self, minor):
        return convert_minor(minor, self.currency, self.usd_per_unit, REPORTING)


def _day(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError as exc:
        raise FxError("Dates must be YYYY-MM-DD.") from exc


def parse_history(data):
    """{(date, currency): per_eur text} from the ECB eurofxref-hist.zip, for the currencies this app supports."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ProviderError("The ECB download is not a valid zip file.") from exc
    with archive:
        members = [info for info in archive.infolist() if info.filename.lower().endswith(".csv")]
        if len(archive.infolist()) > 10 or len(members) != 1:
            raise ProviderError("The ECB download does not have the expected layout.")
        info = members[0]
        if info.file_size > MAX_CSV_BYTES or info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise ProviderError("The ECB download is larger than expected.")
        text = archive.read(info).decode("utf-8-sig", errors="strict")
    rows = csv.reader(io.StringIO(text))
    header = [cell.strip().upper() for cell in next(rows, [])]
    if not header or header[0] != "DATE" or "USD" not in header:
        raise ProviderError("The ECB download does not have the expected columns.")
    wanted = {index: code for index, code in enumerate(header) if code in EXPONENTS and code != "EUR"}
    rates = {}
    for row in rows:
        if not row or not row[0].strip():
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0].strip()):
            raise ProviderError("The ECB download has a row without a valid date.")
        day = row[0].strip()
        for index, code in wanted.items():
            value = row[index].strip() if index < len(row) else ""
            if value in ("", "N/A"):
                continue
            if not RATE_TEXT.fullmatch(value) or Decimal(value) <= 0:
                raise ProviderError("The ECB download has a malformed rate.")
            rates[(day, code)] = value
    if not rates:
        raise ProviderError("The ECB download has no rates.")
    return rates


class EcbRates:
    def __init__(self, store, fetch=https_get, enabled=True):
        self.store, self.fetch, self.enabled = store, fetch, enabled

    # Network: the only method that leaves this device.
    def refresh(self):
        if not self.enabled:
            raise RateMissing("Exchange-rate downloads are turned off in settings.")
        try:
            status, _, body, _ = self.fetch(ECB_HISTORY, {"Accept": "application/zip"}, MAX_DOWNLOAD_BYTES)
        except LookupFailed as exc:
            raise ProviderError(f"The ECB rates could not be downloaded: {exc}") from exc
        if status != 200:
            raise ProviderError(f"The ECB rates download failed with HTTP {status}.")
        rates = parse_history(body)
        days = sorted({day for day, _ in rates})
        sha = hashlib.sha256(body).hexdigest()
        with self.store.connection() as db:
            existing = {(row["rate_date"], row["currency"]): row["per_eur"]
                        for row in db.execute("SELECT rate_date,currency,per_eur FROM fx_rates WHERE source=?", (SOURCE,))}
            new = {key: value for key, value in rates.items() if key not in existing}
            conflicts = sum(1 for key, value in rates.items() if key in existing and Decimal(existing[key]) != Decimal(value))
            set_id = db.execute(
                "INSERT INTO fx_rate_sets(source,fetched_at,first_date,last_date,sha256,byte_size,rates_added,conflicts) "
                "VALUES(?,?,?,?,?,?,?,?)", (SOURCE, now(), days[0], days[-1], sha, len(body), len(new), conflicts)).lastrowid
            db.executemany("INSERT INTO fx_rates(source,rate_date,currency,per_eur,rate_set_id) VALUES(?,?,?,?,?)",
                           [(SOURCE, day, code, value, set_id) for (day, code), value in sorted(new.items())])
        return {"rate_set_id": set_id, "last_date": days[-1], "rates_added": len(new), "conflicts": conflicts}

    # Cache only from here on.
    def status(self, db=None):
        with self._db(db) as conn:
            row = conn.execute("SELECT id,fetched_at,last_date,conflicts FROM fx_rate_sets WHERE source=? ORDER BY id DESC LIMIT 1",
                               (SOURCE,)).fetchone()
            count = conn.execute("SELECT count(*) FROM fx_rates WHERE source=?", (SOURCE,)).fetchone()[0]
        return {"enabled": self.enabled, "downloaded": bool(row), "fetched_at": row["fetched_at"] if row else None,
                "last_rate_date": row["last_date"] if row else None, "rates": count,
                "conflicts": row["conflicts"] if row else 0, "source": "ECB euro reference rates"}

    def due(self, db=None):
        state = self.status(db)
        if not self.enabled:
            return False
        return not state["fetched_at"] or datetime.fromisoformat(state["fetched_at"]) < datetime.now(timezone.utc) - REFRESH_AFTER

    def lookup(self, currency, day, db=None) -> RateHandle | None:
        """The rate for converting currency on day into USD; None for USD itself. Raises an FxError otherwise."""
        try:
            code = currency_code(currency)
        except MoneyError as exc:
            raise RateUnsupported(str(exc)) from exc
        wanted = _day(day)
        if code == REPORTING:
            return None
        if wanted > datetime.now(timezone.utc).date():
            raise FxError("No exchange rate exists for a future date.")
        with self._db(db) as conn:
            if not conn.execute("SELECT 1 FROM fx_rates WHERE source=? AND currency=? LIMIT 1", (SOURCE, code)).fetchone() and code != "EUR":
                if self._any(conn):
                    raise RateUnsupported(f"ECB reference rates do not include {code}.")
                raise RateMissing("Exchange rates have not been downloaded yet.")
            if not self._covers(conn, wanted):
                raise RateMissing(f"Exchange rates for {wanted.isoformat()} have not been downloaded yet.")
            earliest = (wanted - timedelta(days=LOOKBACK_DAYS)).isoformat()
            row = conn.execute(
                "SELECT u.rate_date, u.per_eur AS usd, u.rate_set_id AS usd_set, x.per_eur AS cur, x.rate_set_id AS cur_set "
                "FROM fx_rates u LEFT JOIN fx_rates x ON x.source=u.source AND x.rate_date=u.rate_date AND x.currency=? "
                "WHERE u.source=? AND u.currency='USD' AND u.rate_date<=? AND u.rate_date>=? "
                "AND (x.per_eur IS NOT NULL OR ?='EUR') ORDER BY u.rate_date DESC LIMIT 1",
                (code, SOURCE, wanted.isoformat(), earliest, code)).fetchone()
            if not row:
                raise RateStale(f"No ECB {code} rate was published in the {LOOKBACK_DAYS} days up to {wanted.isoformat()}.")
            return self._handle(conn, code, wanted.isoformat(), row)

    def resolve(self, rate_id, db=None) -> RateHandle:
        """The handle a rate id names, exactly as it was. An unknown or invented id is refused."""
        match = RATE_ID.fullmatch(str(rate_id or ""))
        if not match:
            raise FxError("Unknown rate id. Use a rate_id returned by lookup_exchange_rate.")
        day, code = match.groups()
        with self._db(db) as conn:
            row = conn.execute(
                "SELECT u.rate_date, u.per_eur AS usd, u.rate_set_id AS usd_set, x.per_eur AS cur, x.rate_set_id AS cur_set "
                "FROM fx_rates u LEFT JOIN fx_rates x ON x.source=u.source AND x.rate_date=u.rate_date AND x.currency=? "
                "WHERE u.source=? AND u.currency='USD' AND u.rate_date=?", (code, SOURCE, day)).fetchone()
            if not row or (row["cur"] is None and code != "EUR"):
                raise FxError("Unknown rate id. Use a rate_id returned by lookup_exchange_rate.")
            return self._handle(conn, code, day, row)

    def consolidate(self, rows, db=None):
        """USD total of (day, currency, minor) rows: USD as is, others converted line by line from the cache.

        Rows that can't be converted are left out of the USD figure and listed, and the status says partial.
        """
        total, rates, unresolved, converted = 0, {}, {}, 0
        with self._db(db) as conn:
            for day, currency, minor in rows:
                if currency == REPORTING:
                    total += minor
                    continue
                try:
                    handle = self.lookup(currency, day, conn)
                except FxError as exc:
                    entry = unresolved.setdefault((currency, exc.code), {"currency": currency, "reason": str(exc), "code": exc.code, "rows": 0, "minor": 0})
                    entry["rows"] += 1
                    entry["minor"] += minor
                    continue
                assert handle is not None
                total += handle.convert(minor)
                rates[handle.rate_id] = handle
                converted += 1
        return {"usd": money(total, REPORTING), "status": "partial" if unresolved else "complete",
                "basis": "reference_conversion" if converted else "usd", "converted_rows": converted,
                "rate_ids": sorted(rates),
                "unresolved": [{"currency": item["currency"], "reason": item["reason"], "code": item["code"],
                                "rows": item["rows"], "amount": money(item["minor"], item["currency"])}
                               for _, item in sorted(unresolved.items())]}

    def _handle(self, conn, code, requested, row):
        set_id = row["cur_set"] if code != "EUR" and row["cur_set"] > row["usd_set"] else row["usd_set"]
        sha = conn.execute("SELECT sha256 FROM fx_rate_sets WHERE id=?", (set_id,)).fetchone()["sha256"]
        per_eur = "1" if code == "EUR" else row["cur"]
        with localcontext() as context:
            context.prec = 28
            try:
                rate = Decimal(row["usd"]) / Decimal(per_eur)
            except InvalidOperation as exc:
                raise ProviderError("A cached exchange rate is not a valid number.") from exc
        return RateHandle(f"{SOURCE}:{row['rate_date']}:{code}", code, requested, row["rate_date"], rate,
                          row["usd"], per_eur, set_id, sha)

    def _any(self, conn):
        return conn.execute("SELECT 1 FROM fx_rate_sets WHERE source=? LIMIT 1", (SOURCE,)).fetchone() is not None

    def _covers(self, conn, wanted):
        """True once a download made after that day (UTC), or one already holding a later rate, has been stored."""
        row = conn.execute("SELECT max(last_date) AS last, max(fetched_at) AS fetched FROM fx_rate_sets WHERE source=?", (SOURCE,)).fetchone()
        if not row or not row["last"]:
            return False
        return row["last"] >= wanted.isoformat() or datetime.fromisoformat(row["fetched"]).date() > wanted

    def _db(self, db):
        return _Borrowed(db) if db is not None else self.store.connection()


class _Borrowed:
    """Use a caller's connection (a snapshot) without closing or committing it."""

    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_):
        return False
