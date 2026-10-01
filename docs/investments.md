# Investments

Retirement accounts (401(k), 403(b), IRAs), pensions, HSAs, high-yield savings, CDs, Treasuries, I bonds, brokerage
accounts, crypto and 529 plans, on their own page: Money → Investments.
Values come from documents and what you type. The one exception is crypto market prices, fetched only when you turn
them on in Settings (see [crypto](#crypto)). Investments are not spending.

## One model for every kind

Each account is described by four independent things. The page, the forecast and extraction branch on the
**section**, **tax treatment** and **value model**, never on the kind itself. A new kind is therefore a
row in `investment_kinds`, not new code or a schema change.

| Dimension | Values | Used for |
|---|---|---|
| **Kind** (`investment_kinds` row) | `401k` `403b` `457b` `ira` `roth_ira` `pension` `retirement` `hsa` `hysa` `money_market` `cd` `treasury` `i_bond` `bonds` `brokerage` `crypto` `education_529` `other` | Label, defaults |
| **Section** | Retirement · Health savings · Cash and savings · CDs, bonds and Treasuries · Stocks and funds · Education · Other | Page groups, the share of each |
| **Tax treatment** | taxable · tax-deferred · tax-free · HSA | Share by tax treatment; withdrawal order in the forecast's retirement plan. Each account can override its kind's |
| **Value model** | `market`: the last reported value. `accrual`: principal plus a rate to maturity (CD, Treasury bill or note, I bond). `cash`: a balance earning a yearly rate (HYSA, money market). `income`: a monthly benefit from a start date (pension), never a balance | How the value is projected. In phase 1 every model grows at the yearly rate |

A statement whose kind isn't recognized becomes `other`; the user renames or reclassifies it on the page.

## Tables (migration 036)

- `investment_kinds`: key, label, section, tax treatment, value model, has_maturity, default yearly rate.
- `investment_accounts`: kind, name, institution, currency, `account_key` (institution | last four or
  name | currency, for statements), and optional overrides for tax treatment and yearly rate.
  `ledger_account_id` links a HYSA to its ledger savings account so its cash is counted once (see below).
- `holdings`: positions in an account (fund, stock, CD, Treasury bill) with nullable terms: rate, issue
  and maturity dates, principal. Ticker or CUSIP in `identifier`.
- `investment_valuations`: **append-only values over time**. A row with no holding is the whole account.
  There is one per account, holding and date. Each row records its source (manual or statement), the
  document, and its review status.
- `investment_events`: append-only activity: contributions (employee, employer or personal), withdrawals,
  dividends, interest, fees, buys, sells, maturities and rollovers. Each can link to the bank transaction
  or paystub line it came from. A correction is a new event that names the event it reverses.

036 moved the old `assets` rows of kind investment, retirement and bond into these tables. They keep their
ids, values, review status and source documents, and `legacy_asset_id` lets older extraction results
still open in the document inspector. `assets` keeps homes, cars, other assets and loans.

## Reading statements (phase 2)

An `investment_statement` is read in three questions: its classification, its summary, and then its rows
(`InvestmentLine` in `documents/extraction.py`), chunk by chunk. Each row is either a **holding** or an
**activity** entry:

- **Holding:** printed name, ticker or CUSIP, instrument class (fund, stock, ETF, CD, Treasury, cash sweep, …),
  quantity, price, market value, cost basis, and for CDs, bonds and Treasuries the rate and maturity date.
- **Activity:** date, type (contribution, withdrawal, dividend, interest, fee, buy, sell, maturity, rollover,
  transfer), amount, and for a contribution whether it came from pay, the employer or you.

What is kept, and how it's checked:
- Money is checked against its citation, like every other amount.
- A quantity, rate or ticker is kept only when it is printed on its cited line. Otherwise it is dropped, with a
  note for quantities.
- An activity row without a clear date and amount is not recorded.
- When every holding has a value, the holdings must add up to the ending value. This is the statement's cross-check,
  and a difference is listed on the value in Review.

On publishing:
- Holdings are matched from one statement to the next by ticker or CUSIP, or else by name.
- Each holding gets a value for the statement date.
- Activity entries become events. An entry another statement already recorded (overlapping periods) is not added
  twice.
- Reading the same statement again replaces what the earlier reading listed, unless you already decided on it.
- Confirming or rejecting the statement's value in Review applies the same decision to its holdings and activity.

The account shows the holdings on its newest statement date, with the gain where a cost basis is printed, and the
activity from newest to oldest.

## Savings accounts kept as investments (phase 2)

A HYSA's statements are bank statements, already read into Accounts. On the Investments page, an investment
account can be linked to one savings, checking or brokerage account in the same currency; each ledger account
can be linked only once (migration 037). The link then does three things:

- The linked account's statement closing balances become the investment account's values. They are read when the
  page loads, never copied, so they follow the statements exactly. They are reviewed as statements in Review,
  and a value you type for a date still wins over the statement for that date.
- Interest transactions from that account appear as interest activity.
- The forecast and net worth leave the linked account out of cash and count it once, as an investment.

## Purchase confirmations, estimates and maturities (phase 3)

An `investment_confirmation` (a trade, a CD opened, a Treasury bill, note or bond or an I bond bought) is its own
document type, filed under Investments. It is read as a summary (institution, account, trade date) and its trades
(`TradeLine`):
- Each trade has an action (buy, sell, reinvest, redeem, deposit), the security, the quantity, the price, the net
  amount, the principal, the face value, fees, rate, issue date and maturity date.
- Money is checked against its citation. A quantity or rate is kept only when it's printed where it's cited.
- For shares, quantity × price plus fees (on a buy) or less fees (on a sale) must give the amount.
- An I bond can first be cashed 12 months after it's issued. That date is computed in code.

Publishing (migration 038):
- The confirmation is recorded in `investment_confirmations` and waits in Review.
- Each trade becomes a buy, sell or contribution event.
- Buying a CD, Treasury or bond sets that holding's terms: principal, rate, face value, issue, maturity and
  redeemable dates, and whether it renews.
- Confirming the confirmation confirms its trades. Re-reading one you've decided on changes nothing.

You can also add a CD or Treasury with its terms by hand ("Add a CD or Treasury" on an account). It counts at once.

**Estimated values:**
- Where they apply: an account valued by accrual (CD, Treasury or I bond kinds) that has no value newer than today
  gets an estimate for today. It's the sum of its open holdings, each carried forward from its terms:
  - A holding with a face value rises in a straight line from its price to the face at maturity.
  - Otherwise it compounds at its yearly rate: principal × (1 + rate)^(days/365), exact and rounded half-even.
  - A holding on the newest statement starts from its statement value.
- What's left out:
  - holdings that matured
  - holdings that wait for review
  - holdings from a rejected confirmation
- An account whose CDs all matured is estimated at zero.
- The estimate is worked out when read, never stored. A statement or a value you type for a date always wins over it.
- Totals count it, and the page labels it "Estimated".

**Maturities:**
- "Coming due" on the page, and in Home's bills panel (three soonest), lists CDs, Treasuries and bonds maturing within
  90 days, I bonds whose lock ends, and holdings that matured with no answer yet.
- A matured holding is answered with "Paid out" or "Renewed". Either one records a maturity event at the amount its
  terms pay, and closes the holding. A renewal is then added as a new holding.
- A statement dated after a statement holding's maturity already answers it.

## Contributions and payments in (phase 4)

**From pay (migration 039):**
- Pay stub lines are read into the account at read time, never copied:
  - A retirement account takes the employer's `retirement_pretax` and `retirement_roth` lines.
  - An HSA takes its `hsa` lines.
  - Lines in the `employer_paid` group are the employer's (the match). The rest come from your pay.
- They follow the pay stub's review.
- A statement contribution with the same payer and amount within 7 days is the same money, shown once as the pay
  stub's ("also on a statement").

**Which account an employer's lines go to** is decided from the documents, after each pay stub or statement is
published and when the page loads:
1. The only account whose name or institution shares a word with the employer (an "Acme Corp 401(k) Plan").
2. Otherwise, the only account whose statement lists those contributions: one paycheck's amount within a week, or a
   quarter's lines added up, all together or one kind of line.
3. Otherwise, the only account of that kind.

When it stays ambiguous, the page asks which account. If there is no such account, it asks you to add one. Your choice
in the account's settings, or "No employer", is kept and never changed automatically. A choice replaces an automatic
match on another account.

**Payments in are transfers, not spending:**
- `Reconciler.investment_transfers` matches a bank or card outflow of exactly the amount, within 5 days, to a
  contribution or deposit you made, or to a confirmed CD or Treasury bought. This applies to accounts kept outside the
  ledger.
- Candidates:
  - A purchase line is a candidate only when it names the institution.
  - Lines already in a ledger transfer are skipped.
- One candidate is linked, and the line becomes a transfer unless you verified it. Several candidates are a question in
  Review. "Leave unmatched" is respected by later passes.
- The activity shows "Paid from <account>".
- **"Not this payment"** undoes a match, automatic or yours (migration 041, `Reconciler.unlink_investment`):
  1. The line goes back to its type before the match, unless you verified it.
  2. The pair is recorded in `investment_payment_rejections` and never proposed again.
  3. If other lines could have paid it, Review asks which one, even when there's only one. Otherwise the contribution is
     left unmatched for good.

## Required minimum distributions

- The birth year is set in Settings and kept per profile (`HouseholdConfig.birth_year`).
- `finance/retirement.py` holds the Uniform Lifetime Table: 26 CFR 1.401(a)(9)-9(c), Table 2, the same as
  Pub. 590-B Table III. It was checked against the regulation on 2026-09-28.
- Distributions begin in the year you reach:
  - 72, if born 1950 or earlier
  - 73, if born 1951–1959
  - 75, if born 1960 or later
- Only tax-deferred accounts have them, decided by tax treatment.
- Each account's amount is its confirmed balance at the end of the year before (the newest value on or before Dec 31,
  flagged when older than a month), divided by the divisor for the age reached that year, rounded half-even.
- The Investments page shows this year's amount per account, what confirmed withdrawals already took, what's left, and
  the deadline. The first year's deadline is April 1 of the next year.
- Not modeled:
  - the still-working exception for a current employer's plan
  - inherited accounts
  - the joint table for a spouse more than ten years younger

**The forecast:**
- Each account gains its monthly contributions over the history window:
  - From pay: confirmed pay stub lines, employee and employer. This money is already outside take-home pay, so cash
    is untouched.
  - From you: the monthly amount set on the account, else the average of your contributions paid from the ledger.
    This comes out of cash.
- Accrual holdings grow at their own pace to their value at maturity. In that month the value is paid to cash, unless
  it renews or the account isn't valued by accrual; then it stays in the account.

## Tax lots, gains and tax forms (phase 5)

**Lots** (`finance/tax_lots.py`, taxable accounts only) are worked out when read:
- Each confirmed buy with a printed quantity is a lot. A statement listing a confirmed trade again adds nothing.
- So is each lot you enter for shares bought before the documents here begin (`tax_lots`, migration 040).
- Confirmed sales close lots first in, first out:
  - The cost is taken in proportion to shares.
  - The proceeds are split in proportion to shares, and the last piece takes the rounding remainder.
  - A lot held more than a year (sold after its first anniversary) gives a long-term gain.
- Shares sold with no lot are reported and give no gain. The account view lists lots under "Tax lots", with
  unrealized gain by lot cost when the lots hold exactly the statement's shares.

**1099 and 5498 forms:**
- `investment_tax_form` is a new document type, filed under Taxes. It covers 1099-INT, -DIV, -B, -R, -SA, 5498 and
  5498-SA, including a consolidated 1099.
- Its summary has the payer, account, tax year and date. Its rows are boxes (`TaxBox`: form, box, label, amount),
  each citation-checked.
- The form is linked to an account by institution and last four digits, else to the only account at that institution.
  Otherwise it's kept unlinked. It waits for review.

**Taxes on the page** (year in the URL, `#/investments?year=2026`) compares each confirmed or waiting form with the
account's confirmed records for the year:

| Box | Compared with |
|---|---|
| INT 1 and 3 | interest |
| DIV 1a | dividends |
| B 1d / 1e | lot proceeds and cost |
| R 1 and SA 1 | withdrawals |
| 5498 1 and 10, and 5498-SA 2 | contributions, including pay stub lines |

It also shows realized short- and long-term gains in taxable accounts.

## Kinds made specific

Built 2026-10-01 (migration 056; plan in [investments-next](investments-next.md)). 1099-Q and 1099-DA join the tax forms:
1099-Q box 1 is compared with the year's withdrawals, and 1099-DA boxes 1f and 1g with sale proceeds and cost, as 1099-B 1d and 1e are.

### I bonds

- An I bond holding (`instrument_class='i_bond'`, with its principal and issue date) is valued by `ibond_value()` in
  `finance/investments.py` from the published rates in `ibond_rates`. Migration 056 seeds every rate from May 2015 to May 2026.
  Add each new one (each May 1 and November 1) under "I bond rates" on the account, or with `PUT /api/investments/ibond-rates`.
- The method follows TreasuryDirect:
  - The composite rate is fixed + 2 × semiannual inflation + fixed × semiannual inflation, never below zero.
  - The fixed rate is the one for the issue month. The inflation rate resets every six months from the issue month,
    to the one in force at the start of each period.
  - The value is worked out for a $25 bond, rounded to the cent at each six-month step and at the month reached, then
    scaled to the principal. Interest is added on the first of each month and stops after 30 years.
  - A period that starts after the newest rate uses that newest rate until you add the next one.
- The maturity defaults to 30 years. The 12-month lock stays (the "redeemable" date).
- "If cashed today" is the value three months earlier while the bond is under five years old, and nothing in its first year.
  No value at maturity is shown, since it depends on rates not yet published.
- Purchases over $10,000 in a calendar year get a warning on the page and on the account. A profile is one person, and
  purchases waiting for review count too. Paper bonds bought with a tax refund aren't separated out.
- Tax: I bond and Treasury interest (accounts of kind `i_bond` or `treasury`, or 1099-INT box 3) is federal-taxable and
  state-exempt. `tax_year.gather()` reports it as `us_obligation_interest`, and the simplified state return leaves it
  out. The Education Savings Bond exclusion isn't worked out; type it over the records.

### 529 plans

- The account settings add a **beneficiary** (a profile's name or anyone's) and the **plan state**.
- Withdrawals are `qualified_withdrawal` (tuition, books, room and board) or `nonqualified_withdrawal`. A statement's
  plain `withdrawal` is listed as "Not marked" with buttons to mark it. You can also record a withdrawal yourself; it
  counts at once.
- The Taxes panel shows each 529's non-qualified withdrawals for the year. Their taxable earnings are the withdrawal times
  the confirmed 1099-Q's box 2 (earnings) over box 1 (gross distribution). `tax_year.gather()` adds them to other income;
  the 10% additional tax usually applies too and isn't computed.
- Forecast: a 529 (section `education`) is never drawn on by retirement withdrawals. Planned **education costs** (a month
  and an amount, optionally from one 529) are paid from the 529, and from cash once it runs short.

### Pensions

- A pension is an income stream (value model `income`), not a balance. Its account has `pension_terms`: the monthly
  benefit, start date, yearly raise (COLA, each January), survivor share, and a lump sum offered instead.
  The lump sum is shown for comparison and never counted.
- Pensions are left out of totals and shares, required minimum distributions, and the forecast's balances and withdrawals.
- Forecast: `Investments.forecast_pensions()` feeds `ForecastInput`-shaped `PensionIncome` streams into `project()`.
  - Each pays from its start month and is raised by its COLA each January after.
  - A tax-deferred pension is taxed at the retirement plan's flat rate (untaxed when no plan sets one).
  - A What If can add pensions of its own (`ForecastInput.pensions`). The family forecast adds every member's.
  - Survivor benefits aren't projected.
- 1099-R import is unchanged.

### Crypto

- **Prices** (`finance/prices.py`, modelled on `finance/fx.py`) come from CoinGecko's public simple-price endpoint.
  - They are fetched only when **Settings → Fetch crypto market prices** (`fetch_crypto_prices`, off by default) is on.
  - Requests go out at most once a day at startup, plus whenever you press **Refresh prices** on the account.
  - The request names only coin ids and currencies, never amounts.
  - Prices are cached in `price_quotes` as exact decimal text.
  - Coins are matched by ticker (`COINGECKO_IDS`: BTC, ETH, SOL…). A coin not listed there isn't priced.
- A price adds a `quote` value for today (labelled "Market price"):
  - Each coin's units × price, plus cash carried from the statement.
  - Units are the newest confirmed statement's quantities, moved by confirmed buys, sells, transfers and rewards since.
  - An account holding anything without a price (a fund, an unknown coin) gets no quote at all, never a partial one.
  - Valuations stay append-only, and a document always wins. An account with a statement or typed value dated today
    or later gets no quote. A statement for the same date later replaces the quote.
- **Coinbase export**: "Import a Coinbase export" reads the transaction-history CSV (or XLSX) from the library
  (`parse_crypto_export`, preset `coinbase`).
  - Buys, sells, sends, receives and rewards become the account's activity; a conversion is a sale and a purchase.
  - Holdings are created by symbol. Fiat deposits and withdrawals are skipped, and unknown types are reported.
  - Importing the same file again adds nothing twice. The rows count at once, like a transaction import.
- Tax: crypto is taxable, so confirmed buys open FIFO lots (`finance/tax_lots.py`) and sales give realized gains.

## Rules

- A value you type counts at once. If you type a value for a date that already has one, yours replaces it,
  and later statements for that date don't change it.
- A statement value waits in Review under "Investment and loan documents to confirm", with purchase confirmations and tax forms. A newer statement adds a value.
  An older one is kept as history and doesn't change today's value. Re-extracting a statement you already
  decided on changes nothing.
- An account's current value is its newest confirmed value. The change shown is the difference from the
  confirmed value before it.
- Totals, section shares and tax shares use confirmed values only, per currency. They are computed on the
  server, and the page only shows the text it receives.

## API

`GET /api/investment-kinds` · `GET /api/investments` (accounts, totals, shares) · `POST /api/investments` ·
`GET|PUT|DELETE /api/investments/{id}` (delete archives) · `POST /api/investments/{id}/values` ·
`GET /api/investments/review` · `POST /api/investments/valuations/{id}/review` ·
`GET /api/investments/valuations/{id}` and `…/valuations/by-asset/{asset_id}` (inspector) ·
`GET /api/investments/confirmations/{id}`, `POST …/confirmations/{id}/review` ·
`POST /api/investments/{id}/holdings`, `PUT|DELETE /api/investments/holdings/{id}`, `POST …/holdings/{id}/matured` ·
`POST /api/investments/{id}/payroll` (answer the payroll question) · `POST /api/investments/events/{id}/unlink` ·
`GET /api/investments/rmd?year=` ·
`POST /api/investments/holdings/{id}/lots`, `DELETE /api/investments/lots/{id}` ·
`GET /api/investments/tax-forms/{id}`, `POST …/tax-forms/{id}/review`, `GET /api/investments/tax-years/{year}` ·
`PUT /api/investments/{id}/pension` · `POST /api/investments/{id}/events` · `POST /api/investments/events/{id}/qualified` ·
`GET|PUT /api/investments/ibond-rates` · `POST /api/investments/{id}/crypto-import` · `GET /api/prices`, `POST /api/prices/refresh`.

## Phases

1. **Done 2026-09-28.** Migration 036 with the kinds registry and the move from `assets`; `finance/investments.py`;
   statements publish values over time; Review; the forecast reads confirmed values; the page shows totals,
   section and tax shares, accounts by section, and one account's settings and values over time.
2. **Done 2026-09-28.** Holdings and activity read from statements, following the value's review; the account view
   shows holdings (with gains) and activity; a HYSA linked to its savings account's statements and interest, counted
   once. Migration 037, extraction prompt `typed-extraction-v15`.
3. **Done 2026-09-28.** `investment_confirmation` document type, estimated accrual values, holdings entered by hand,
   maturities on the page and on Home. Migration 038, extraction prompt `typed-extraction-v16`.
4. **Done 2026-09-28.** Pay stub contributions linked to their account automatically; payments into investments matched
   as transfers; the forecast's monthly contributions and maturities paid to cash. Migration 039.
5. **Done 2026-09-28** (tax lots, realized gains, 1099/5498 import and comparison; migration 040). Required minimum
   distributions, retirement withdrawals in the forecast, and undoing payment matches followed the same day (migration 041).
   The What If forecast that followed (scenarios run side by side with "Now") is built; see [What If](what-if.md).
   Forecast inputs, including the retirement plan, are kept pure and stateless for it.
6. **Done 2026-10-01.** Kinds made specific: I bonds, 529 plans, pensions and crypto (with opt-in prices and the Coinbase
   import), 1099-Q and 1099-DA. Migration 056. See [Kinds made specific](#kinds-made-specific).
