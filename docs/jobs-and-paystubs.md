# Jobs and pay stubs

Status: implemented 2026-09-28 (migration 031; `library/managed_library.py`, `documents/extraction.py`,
`finance/paystub.py`, `household/tax_tables.py`, `finance/charts.py`, `app/static/receipt.js`, `library.js`, `review.js`).
Tests: `tests/test_employers.py`, `tests/test_withholding.py`.

## Folders

The Income folder is gone. Everything about work lives in **Jobs**, one folder per employer, on disk too:

```
Library/Jobs/Google/Paystubs/2026/09/2026-09-15__Paystub__Google__<hash>__d<id>.pdf
Library/Jobs/Google/Documents/2026/08/2026-08-01__Offer_Letter__Google__<hash>__d<id>.pdf
```

- **Which employer.** The local model reads the employer from the document (never the payroll provider such as ADP,
  Paychex or Gusto, or a bank) and is given the employers that already have folders: if the document's employer is one
  of them, even printed differently, it answers with that name. The system then drops a trailing legal form (LLC, Inc,
  Corp …) and keeps letters only: "Google LLC" files under `Google`. A new employer gets its folder with `Paystubs` and
  `Documents` at once (`employers` table; `ManagedLibrary.employer`).
- **Which section.** A pay stub (type `paystub`) goes to Paystubs. Offer letters, employment agreements, benefits
  enrollment, separation letters and employer W-2s (type `employment_document`) go to Documents; they are read only to
  be filed and never reach the ledger. Tax returns and other tax forms stay in Taxes.
- **Titles.** A pay stub is titled "Paystub MM/DD/YYYY" from its pay date; an employment document by its printed name
  ("Offer Letter", "W-2"). Your own description, if you add one, follows the title.
- **Sidebar.** Documents › Jobs › employer › All / Paystubs / Documents (`/api/documents?employer=&section=`).
- **Older libraries.** Files in `Library/Income` move into Jobs on startup: a pay stub into its payer's Paystubs folder
  with the new name, anything else into `Jobs/YYYY/MM`. A document moved into Jobs by hand has no employer and stays
  in `Jobs/YYYY/MM`.

## Gross to net

A pay stub's printed lines are recorded (`income_lines`), each with this period's and the year-to-date amount and a
group: earnings, pre-tax deductions (401(k), health, dental, vision, HSA, FSA), taxes (federal, state and local income
tax, Social Security, Medicare, state disability), post-tax deductions (Roth 401(k) …) and amounts paid by the employer
(a 401(k) match), which are shown but never taken from pay. The page shows them grouped from gross pay down to net pay,
with subtotals and FICA as Social Security plus Medicare.

Two checks run on each column: earnings add up to gross pay, and gross pay less pre-tax deductions, taxes and post-tax
deductions is net pay. A stub that fails either waits in Review with the difference named; one that passes counts on
its own (exception-based review, as for receipts).

## How the taxes were figured

The page explains the stub's withholding (`finance/paystub.py`), as an estimate beside what was actually withheld:

- **Wages.** Income-tax wages are gross pay less the pre-tax deductions; FICA wages are gross pay less the
  cafeteria-plan ones (health, dental, vision, HSA, FSA) — a 401(k) lowers income tax, not FICA.
- **Buckets.** Federal and state income tax: a paycheck's wages times the paychecks in a year (from the printed pay
  frequency, else the pay period's length); the standard deduction is the 0% bucket (with its share of each
  paycheck); each bracket taxes only its own slice. The year's tax spread over the paychecks is the estimate. A bar
  chart splits the year's wages into the buckets, with a table of each bucket's wages and tax per year and paycheck.
- **FICA.** Social Security at its rate up to the year's wage base (year-to-date wages decide how much of this paycheck
  is still under it); Medicare at its rate, plus the additional rate above its threshold.
- **Why they differ.** Payroll uses IRS Publication 15-T and your W-4 (extra withholding, credits, other income).
- **Filing status** is a household setting (Settings › Household), Single by default.
- The state is the one whose income tax line is on the stub (`work_state`); states without a wage income tax need no
  table.

## Tax tables

A table is one jurisdiction's (federal or a state's) standard deduction and brackets for a tax year and filing status,
plus, for federal, the Social Security and Medicare rates, wage base and threshold (`tax_tables`).

- When a pay stub from a year without tables is recorded, the local model looks them up on the web (Brave Search key
  needed), in the same model job. The pay stub page also has a "Look up" button.
- Every number must be printed in a passage the model quotes from a page it opened; the brackets must start at 0 and
  rise. Anything else is refused and sent back to the model.
- A table is a proposal until you confirm it in Review (with its quoted sources). Until then the page says it is
  waiting. A rejected table can be looked up again.
