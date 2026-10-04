-- ECB reference exchange rates cached on this device, for USD conversion (docs/money.md "Currency conversion").
-- Each download is one fx_rate_sets row. A published (date, currency) rate is stored once, by the download that first
-- brought it, and never changes: triggers refuse updates and deletes, so a rate id cited by a total or a CPA pack always
-- resolves to the same value. Rates are exact decimal text (units per euro), never REAL.
-- A receipt matched to a card charge in another currency keeps the reference estimate it was matched on as provenance.

CREATE TABLE fx_rate_sets (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('ecb')),
    fetched_at TEXT NOT NULL,
    first_date TEXT NOT NULL,
    last_date TEXT NOT NULL,
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64),
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    rates_added INTEGER NOT NULL CHECK (rates_added >= 0),
    conflicts INTEGER NOT NULL DEFAULT 0 CHECK (conflicts >= 0)
) STRICT;

CREATE TABLE fx_rates (
    source TEXT NOT NULL CHECK (source IN ('ecb')),
    rate_date TEXT NOT NULL,
    currency TEXT NOT NULL CHECK (length(currency) = 3),
    per_eur TEXT NOT NULL,
    rate_set_id INTEGER NOT NULL REFERENCES fx_rate_sets(id),
    PRIMARY KEY (source, rate_date, currency)
) STRICT;
CREATE INDEX fx_rates_currency ON fx_rates(source, currency, rate_date);

CREATE TRIGGER fx_rates_no_update BEFORE UPDATE ON fx_rates BEGIN SELECT RAISE(ABORT, 'Exchange rates are immutable.'); END;
CREATE TRIGGER fx_rates_no_delete BEFORE DELETE ON fx_rates BEGIN SELECT RAISE(ABORT, 'Exchange rates are immutable.'); END;
CREATE TRIGGER fx_rate_sets_no_update BEFORE UPDATE ON fx_rate_sets BEGIN SELECT RAISE(ABORT, 'Exchange rate sets are immutable.'); END;
CREATE TRIGGER fx_rate_sets_no_delete BEFORE DELETE ON fx_rate_sets BEGIN SELECT RAISE(ABORT, 'Exchange rate sets are immutable.'); END;

ALTER TABLE transaction_receipt_links ADD COLUMN estimate_rate_id TEXT;
ALTER TABLE transaction_receipt_links ADD COLUMN estimate_minor INTEGER;

PRAGMA user_version=51;
