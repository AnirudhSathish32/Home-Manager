# Forecast

A deterministic projection of income, spending, cash, assets, loans and net worth, month by month, for 1 to 100 years. Implemented 2026-09-25: `forecast.py` (calculation), `charts.py` (SVG charts), `static/forecast.js` (page), migration 022 (`assets`). No model is involved; the same records and assumptions always give the same numbers and byte-identical charts.

## Starting point

- **Cash:** each account's latest statement balance (credit-card balances count as owed). Accounts without a statement balance start at zero and are listed in the notes.
- **Income:** average monthly counted income (deposits, interest) over the last *N* full months (default 6).
- **Spending:** average monthly counted spending per category over the same months; refunds appear as a negative line. Transfers and card payments are excluded, as everywhere else.
- **Assets and loans:** the `assets` table. Values you type in (car, house) count at once. Values read from investment, retirement, bond or loan statements are proposed until reviewed and are listed in the notes until then.
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

Cash each month = previous cash + income − spending − loan payments + one-offs. Net worth = cash + assets − loans. All arithmetic is exact decimal; each monthly amount is rounded half-even to the cent.

## Output

`POST /api/forecast` returns every month, a per-year summary with exact display text, the starting point, notes (missing balances, thin history, other currencies, pending statement values, unknown categories), the first month cash falls below zero, and three SVG charts: net worth (nominal and today's dollars), income and spending per year, and cash/assets/loans. Each chart has a per-year table view. Assets: `GET/POST /api/assets`, `PUT/DELETE /api/assets/{id}` (delete archives).

Charts use the validated categorical order blue `#2a78d6`, orange `#eb6834`, aqua `#1baf7a` on white (all checks pass; aqua's contrast warning is relieved by visible end labels and the table view).

## Not yet

- ~~Reading investment, retirement, bond and loan statements into `assets` rows~~: done 2026-09-25, see [items-assets-search.md](items-assets-search.md) §6.
- Taxes, contributions to retirement accounts and investment income are not modelled separately; set an asset's growth rate to include them.
