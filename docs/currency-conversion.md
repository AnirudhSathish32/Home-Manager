# Currency conversion

Built 2026-09-30 (milestones M2c and M4a). Code: `finance/fx.py`, `core/money.py` (`convert_minor`), the cross-currency
match in `finance/reconcile.py`, `usd_total` in `finance/tools.py`. Tests: `tests/test_fx.py`. Policy background:
[architecture](architecture.md#usd-conversion-policy-v1).

## What it does

Totals are still kept per currency. When a period has anything other than USD, `get_spending`, `compare_periods` and
`calculate_cashflow` also return `usd_total`: everything added up in USD, with the rate ids used and a status of
`complete` or `partial`. USD-only data has no `usd_total` and never touches rates.

## Rates

- Source: the ECB's euro reference rates, downloaded as one public file (`eurofxref-hist.zip`). The request carries
  no household data. USD per unit of X = (USD per EUR) / (X per EUR), in exact decimals.
- Only `EcbRates.refresh()` goes to the network. It runs in the background when a profile opens (rates on, foreign
  amounts present, last download over 20 hours ago) and from **Refresh rates** on the Taxes page. Settings → "Download
  ECB exchange rates" turns it off; then nothing is downloaded and foreign amounts stay unconverted.
- Every download is recorded in `fx_rate_sets` (SHA-256, size, date range). A published (date, currency) rate is
  stored once, by the first download that brings it, and is never changed: triggers refuse updates and deletes. A later
  file disagreeing about a stored rate is counted in `conflicts`; the first value stands.
- A rate id is `ecb:<ECB date>:<currency>` and always resolves to the same values.
- Currencies the ECB doesn't publish (BHD, KWD, JOD, OMR, TND) are `unsupported`.

## Which rate a line gets

1. A line is dated by its transaction date when it has one, else its posted date; a receipt by its purchase date.
2. The latest ECB publication on or before that date, at most 7 days earlier (weekends and holidays).
3. No rate for a future date. A date after the last download is `rate_missing` until rates are refreshed. A gap over 7
   days is `rate_stale`. Nothing is ever filled with today's rate, zero or 1:1.
4. Each line is converted and rounded half-even on its own, then the lines are summed.

Lines that can't be converted are left out of the USD figure, listed under `unresolved`, and make the status `partial`.

## A foreign receipt and its USD card charge

A receipt in another currency can be matched to the USD card charge that paid it. When no same-currency charge fits,
reconciliation looks for USD charges within the posting window at 97–106% of the receipt's ECB estimate (cards add
foreign-transaction fees; their network rate can be a little better). Charges naming the merchant are preferred. It is
always a question in Review, never linked automatically. Once the user picks the charge, the charge is what counts, once;
the receipt's estimate and rate id stay on the link (`estimate_rate_id`, `estimate_minor`) as provenance. Its item
categories are shared out in the receipt's currency, then resized to the charge.

## "Pesos"

A document that says pesos without a currency code is not given a currency: pesos can be Mexican (MXN) or Philippine
(PHP). Publishing is blocked until the user chooses. A printed `MXN` or `PHP`, or a statement account's own currency,
settles it.

## Assistant tools

`lookup_exchange_rate` (currency, date) returns the cached rate and its `rate_id`, or `unavailable` with the reason.
`convert_document_amount` (receipt id, rate id) converts using exactly that rate, and refuses an invented id, another
currency or a rate that isn't the receipt date's. The model never supplies a rate or a URL, and converting approves
nothing. See [assistant](assistant.md).
