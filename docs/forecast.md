# Forecast

A deterministic projection of income, spending, cash, assets, loans and net worth, month by month, for 1 to 100 years. Implemented 2026-09-25: `finance/forecast.py` (calculation), `finance/charts.py` (SVG charts), `static/forecast.js` (page), migration 022 (`assets`). No model is involved; the same records and assumptions always give the same numbers and byte-identical charts.

## Starting point

- **Cash:** each account's latest statement balance (credit-card balances count as owed). Accounts without a statement balance start at zero and are listed in the notes. A savings account linked to an investment account (a HYSA) is counted there instead, not as cash.
- **Income:** average monthly counted income (deposits, interest) over the last *N* full months (default 6).
- **Spending:** average monthly counted spending per category over the same months; refunds appear as a negative line. Transfers and card payments are excluded, as everywhere else.
- **Recurring bills:** each confirmed recurring bill is projected at its expected amount in its due months, counting on from its next due date (weekly bills are spread evenly, 52/12 a month), grown with inflation and changed by its category's spending change. Past payments to it are taken out of the category averages. See [receipts-and-statements.md](receipts-and-statements.md).
- **Assets and loans:** the `assets` table (homes, cars, other assets, loans). Values you type in count at once. Values read from loan statements are proposed until reviewed and are listed in the notes until then.
- **Investments:** each investment account's newest confirmed value ([investments.md](investments.md)), growing at the account's yearly rate or its kind's default, plus its monthly contributions: from pay (the linked employer's confirmed pay stub 401(k), HSA and match lines, averaged over the history window; cash is untouched) and from you (the amount set on the account, else your recent payments in from the ledger; taken from cash). A CD or Treasury grows at its own terms to its maturity value and is paid to cash in its maturity month unless it renews. Accounts with a statement value waiting for review are named in the notes.
- One currency per forecast; amounts in other currencies are left out and named in the notes.

## Assumptions

| Assumption | Default | Effect |
|---|---|---|
| Inflation | 2% a year | Spending grows with it, compounded monthly; "today's dollars" divide it back out |
| Income growth | 0% | Income stays flat unless changed |
| Asset growth | per asset; car −15%, others 0% until set | Compounded monthly |
| Loans | rate and payment per loan | Monthly interest (rounded to the cent), then the payment, until repaid; a payment below the interest is flagged |
| Spending changes | none | A category's average times (1 + percent) |
| Income changes | none | Added to monthly income from a month on |
| One-off amounts | none | Added to cash in their month (expenses negative) |
| Planned paychecks (`pay_plans`) | none | What If: take-home pay a month from a month on (to a last month, or until retirement). *Replace* takes the place of confirmed pay stubs' take-home pay and payroll contributions; *add* is another earner. Contributions go to a linked investment account or a new planned one. Yearly bonuses are paid (after withholding) in their calendar month |
| Set spending (`category_amounts`) | none | What If: a category's monthly amount from a month on, in today's money (grown with inflation); replaces its average and its recurring bills |

Cash each month = previous cash + income − spending − loan payments − contributions from you + maturities paid out + withdrawals from investments + one-offs.

## Retirement and required distributions

`ForecastInput.retirement` (`RetirementPlan`) is one self-contained input, never stored, so a later What If feature can
run several side by side.

**From the start month:**
- Take-home pay stops: the average net pay of confirmed pay stubs in the history window, grown with income. Income
  after that never goes below zero.
- Contributions from pay stop, and so do your own contributions.

**Withdrawals** come from taxable accounts first, then tax-deferred, then tax-free, then HSAs, and each takes from the
account's balance before its CDs:
- **Fixed:** a monthly amount in today's dollars, grown with inflation.
- **Cover the shortfall:** whatever keeps cash at a floor, also in today's dollars.
- **Tax:** a withdrawal from a tax-deferred account is grossed up at the flat tax rate you set, so the planned amount
  reaches cash. The tax is shown per year.
- **Running out:** when the accounts can't meet a withdrawal, a note says when investments run out.

**RMDs:** with a birth year in Settings, every December from the start year each tax-deferred account pays out at least
its end-of-last-year balance over the Uniform Lifetime divisor ([investments.md](investments.md)), after tax, into cash.
This happens with or without a retirement plan. The year table shows "From investments", "Tax withheld" and
"Required (RMD)", which is the part taken only because it was required.

**Pensions and 529s** ([investments.md](investments.md#kinds-made-specific)):
- A pension is income, not an asset. It pays its monthly benefit from its start month, raised by its COLA each January,
  and a tax-deferred one is taxed at the retirement plan's flat rate. A What If can add pensions (`pensions`).
- A 529 is never drawn on by retirement withdrawals. Planned education costs (`education_withdrawals`: month, amount,
  optionally a 529's account id) are paid from the 529, and from cash once it runs short.
- The year table adds "Pension", "Pension tax", "Education" and "Paid by the 529" when there are any.

Net worth = cash + assets − loans. All arithmetic is exact decimal; each monthly amount is rounded half-even to the cent.

## Output

`POST /api/forecast` returns every month, a per-year summary with exact display text, the starting point, notes (missing balances, thin history, other currencies, pending statement values, unknown categories), the first month cash falls below zero, and three SVG charts: net worth (nominal and today's dollars), income and spending per year, and cash/assets/loans. Each chart has a per-year table view. Assets: `GET/POST /api/assets`, `PUT/DELETE /api/assets/{id}` (delete archives).

Charts use the validated categorical order blue `#2a78d6`, orange `#eb6834`, aqua `#1baf7a` on white (all checks pass; aqua's contrast warning is relieved by visible end labels and the table view).

## Not yet

- ~~Reading investment, retirement, bond and loan statements into `assets` rows~~: done 2026-09-25, see [items-assets-search.md](items-assets-search.md) §6.
- Taxes other than the flat rate on tax-deferred withdrawals, and investment income, are not modelled separately; set an investment account's yearly rate to include them.
- ~~What If: several forecasts with different assumptions side by side~~: saved plans compared with Now, see
  [what-if.md](what-if.md).
