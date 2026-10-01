# Investments: next phases (plan)

Status, 2026-10-01: phase 4 built (migration 056, which also adds phase 5's `yield_bp` and `reinvest` columns); phase 5
not started. Built as described below, with these differences: a crypto price is stored as exact decimal text (`price`), not
`price_minor`, so coins worth less than a cent still value correctly; the Coinbase preset is its own exchange-export import
(`finance/tabular.py` `parse_crypto_export`), since the transaction CSV import writes ledger transactions, not holdings;
1099-INT box 3 now counts in taxable interest. These are phases 4 and 5 of the plan for the open items in
[milestones](milestones.md): "529 plans, crypto, pensions, I bonds" and the forecast's "investment income modelled
separately". Phases 1–3 of the same plan (watched folders, several receipts in one file, several images as one
document) were built on 2026-10-01; migrations 053–055 are theirs, so this work starts at **056**.

Line numbers below were checked on 2026-09-30/10-01 and drift as code changes; find the named function before editing.
Read [investments](investments.md) and [forecast](forecast.md) first.

## Where things stand

- All four kinds already exist as rows in `investment_kinds` (migration 036, rebuilt STRICT in 050). The table has a
  CHECK on `section`, `tax_treatment` (taxable, tax_deferred, tax_free, hsa) and `value_model` (market, accrual, cash),
  so a new value model needs a table rebuild.
  | Kind | Section | Tax treatment | Value model |
  |---|---|---|---|
  | `pension` | retirement | tax_deferred | market |
  | `i_bond` | fixed_income | taxable | accrual, `has_maturity`=1 |
  | `crypto` | market | taxable | market |
  | `education_529` | education | tax_free | market |
- Nothing is specific to them yet. The only exception is the I bond's 12-month lock (`redeemable_date = add_months(issued, 12)`
  in `documents/extraction.py`, the confirmation rows).
  - A pension is a drawable, tax-deferred balance with RMDs.
  - A 529 can be drawn by the forecast's retirement withdrawals.
- `finance/investments.py`:
  - `accrued()` grows a value in a straight line to face, or compounds at one fixed rate.
  - `TAX_FORMS` has 1099-INT/DIV/B/R/SA and 5498/5498-SA. There is no 1099-Q, 1099-DA or 5498-ESA.
- `finance/forecast.py` grows each investment at one total-return rate. Dividends and interest stay inside the balance,
  and only accrual maturities pay out to cash (`project()`, `draw()`, `WITHDRAWAL_ORDER`, `RetirementPlan`, `ForecastInput`).
- Values come from documents only. `finance/fx.py` (`EcbRates`) is the pattern for a gated, cached outbound lookup.

## Decisions (made with the user)

- A pension is an **income stream**, not a balance.
- Crypto gets a **live price lookup**: CoinGecko, behind a setting that is off by default.

## Phase 4: investment kinds made specific

**Schema (`056_investment_kinds_v2.sql`)**
- A STRICT rebuild of `investment_kinds`, following the 050 pattern, adds value model `income`. The `pension` kind changes to
  `value_model='income'`.
- `pension_terms(account_id PK, monthly_benefit_minor, start_date, cola_bp, survivor_pct, lump_sum_minor NULL)`.
- `price_quotes(source, symbol, as_of, price_minor, currency)` for crypto.
- `investment_valuations.source` gains `'quote'`. This is a table rebuild, because `source` has a CHECK.
- `ibond_rates(period_start, fixed_bp, inflation_semiannual_bp)`: maintained by the user, and seeded with the published
  TreasuryDirect rates, so it needs no network.
- Phase 5's `yield_bp` and `reinvest` columns go in this same migration.

**I bonds** (`finance/investments.py`)
- Add `ibond_value(principal, issue_date, on, rates)`, used beside `accrued()` for `instrument_class='i_bond'`:
  - The composite rate resets every 6 months from the issue month, and interest compounds semiannually.
  - Redeemed within 5 years, the bond loses its last 3 months of interest. Show a "cash-out value" next to "value".
  - The maturity defaults to 30 years.
- The existing 12-month lock stays.
- Purchases of more than $10k per person per calendar year get a warning when one is added or confirmed.
- Tax: the interest is federal-taxable and state-exempt. Mark it in `tax_year.gather()` (`finance/tax_year.py`) so a state
  view can exclude it. The Education Savings Bond exclusion is out of scope; say so in the docs.

**529 plans**
- Add `beneficiary` (a profile or free text) and `state` to the account settings.
- Add the events `qualified_withdrawal` and `nonqualified_withdrawal`.
- Exclude the `education` section from forecast retirement withdrawals in `draw()`. It is never drawn on for living costs.
- Add a planned "education withdrawal" input to the forecast: a month and an amount, paid from the 529 as an expense.
- Import 1099-Q: add it to `TAX_FORMS`, with a `TAX_CHECKS` entry comparing box 1 to the recorded withdrawals.
- Show the taxable earnings portion on the Taxes page, only for withdrawals marked non-qualified.

**Pensions**
- The account detail shows a `pension_terms` form instead of holdings and valuations.
- `forecast_assets` emits the pension as an income stream:
  - `ForecastInput` gets `pensions: list[PensionIncome]` (amount, start month, COLA, a tax_deferred flag).
  - Keep it pure and stateless so What If scenarios can run side by side.
- `project()` adds the pension to monthly income, applies the COLA each January, and taxes it at the plan's flat rate.
- The pension has no RMD and can't be drawn. An optional lump sum is shown as an alternative value and not counted in totals.
- 1099-R import is unchanged.

**Crypto with live prices**
- New `finance/prices.py`, modelled on `finance/fx.py`: `refresh`, `due`, `status`, and an injectable `fetch=https_get`
  from `models/web_lookup.py`.
  - The provider is the CoinGecko simple-price endpoint, which needs no key.
  - It is gated by a new household setting, `fetch_crypto_prices`, off by default, next to `fetch_exchange_rates`
    (`HouseholdConfig` in `finance/ledger.py`; checked in `Manager.refresh_rates`).
  - Prices refresh at most daily, plus on a "Refresh prices" button.
- A quote adds a `quote`-source valuation, labelled "market price, <date>".
  - A statement or CSV value is never overwritten; valuations are append-only.
  - The newest document value wins when it is from the same day or later.
- Holdings are matched by `identifier` (BTC, ETH…), with quantities from statements or exchange CSV exports. Add a
  Coinbase-style mapping preset to the existing CSV import.
- Tax: lots use the existing FIFO in `finance/tax_lots.py` (crypto is taxable). Add 1099-DA to `TAX_FORMS` and treat it
  like 1099-B in `tax_year.gather()`.

**UI**: `static/investments.js` (account detail, settings form). Apply the `app-ux` skill. Charts, if any, follow `forecast-charts`.

**Docs**: add a section per kind to [investments](investments.md), and strike the item through in [milestones](milestones.md).

## Phase 5: investment income modelled separately (forecast)

- Each investment account gets `yield_bp`: the part of the yearly return paid as dividends or interest. The rest is growth.
- In `project()`, each month's yield on **taxable** accounts goes to cash, or is reinvested when the account's `reinvest`
  flag is set (on by default). It is reported as "investment income".
- That income is taxed at a new `investment_tax_percent` in `RetirementPlan` / `ForecastInput`.
- Tax-advantaged accounts keep compounding inside the balance, as today.
- The default `yield_bp=0` keeps today's results, so existing forecasts and `tests/test_forecast.py` stay unchanged.
- Update the "not modelled" note in [forecast](forecast.md) and the Forecast row in [milestones](milestones.md).

## Verification

Run only the tests for touched components; never run against `P:\Finances`.
- **`tests/test_investments.py`:**
  - I bond values against TreasuryDirect worked examples.
  - The 3-month penalty before and after 5 years.
  - The $10k warning.
  - The 1099-Q and 1099-DA checks.
- **`tests/test_forecast.py`:** a pension stream with a COLA, a 529 that is never drawn, an education withdrawal, and a
  zero yield matching the old output while a set yield moves cash and is taxed.
- **`tests/test_scenarios.py`:** What If with pensions and yields.
- **New `tests/test_prices.py`:** a fake fetch, the gating setting, daily refresh, and a quote never overriding a newer
  statement value.
- **`tests/test_migrations.py`:** migration 056.
- **Browser:** the investments page at 390, 768 and 1440 widths (`tests/test_browser.py`, `--browser`).
- **Last:** ruff and mypy on the touched modules.
