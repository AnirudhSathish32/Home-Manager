# Open work

This is the only list of known open work, gathered from every doc on 2026-10-04. Feature docs describe what is built
and link here for what isn't. When an item is built, remove it from this list and describe it in its feature doc.

## Ingestion

- **Email ingestion (Gmail first)**, including bill notices from email (the exact amount and due date before paying,
  linked to their recurring bill). The approved design (on hold while you decide whether to include email):
  - Gmail API with your OAuth and the `gmail.readonly` scope only: no modify or send, and never mark read, move, label
    or delete.
  - The refresh token goes in Windows-protected credential storage, outside prompts and logs.
  - Bounded historical backfill, incremental cursors, rate limits, and a visible sync status that tells an empty result
    apart from incomplete sync.
  - Attachments are downloaded into the library like any capture, and processing stays local.
  - Before ingesting mail, set a retention and user-controlled deletion policy. Deleting mail at Google doesn't delete
    local evidence.
- **Split receipts and combined images can't be donated** yet ([evals](evals.md#donating-documents)).
- **Which document languages are required?** This affects vision evaluation and parsing conventions.
- **A native folder picker** for choosing the library folder (paths are pasted today).

## Models and evals

- **Decision model:**
  - check the `/v1/responses` log-probability shape against the installed LM Studio;
  - calibrate a chosen model on real documents before it gets any routing role;
  - the documents suite doesn't yet report decision-model calibration.
- **Evaluate the vision and reasoning models on real documents** (the donated corpus); accuracy has only been measured
  on synthetic data.
- **Judge.** No hand labels exist yet, so no judge is calibrated.
- **Assistant eval:** compare tool arguments, and add document-search questions.
- **Eval open questions:** candidate models, gate thresholds, eval temperature, task weights, and a latency limit
  ([evals](evals.md#open-questions)).
- **Donation consent:** fill in the retention date in [donation-consent.md](donation-consent.md) before the first
  donation.

## Money

- **Per-currency totals.** Category totals, budgets and the Home dashboard are still per currency, with no USD total.
- **Family shared bills.** A shared recurring bill's payments still count in full for whoever paid.
- **Family corrections.** Records corrected in the family library after they were sent need **Send** again.

## Planning and investments

- **Investment income modelled separately** in the forecast (`yield_bp`, `reinvest`, `investment_tax_percent`). The
  spec is in [planning](planning.md#planned-investment-income).
- **Forecast taxes** beyond the flat rate on tax-deferred withdrawals and pensions.
- **Not computed:**
  - the Education Savings Bond exclusion;
  - pension survivor benefits in the forecast;
  - the 10% additional tax on non-qualified 529 earnings;
  - separating paper I bonds bought with a tax refund.
- **What If doesn't model:**
  - the pre-2020 W-4;
  - payroll rounding to whole dollars;
  - state withholding formulas beyond brackets, deduction or exemption and typed credits;
  - state rules for pre-tax deductions.

## Taxes

- **Returns Engine 1 doesn't cover** (some fall back to Engine 2):
  - both spouses self-employed;
  - educator expenses on a joint return;
  - forcing the standard deduction;
  - the energy credit;
  - other credits typed in;
  - more than three AOTC students.

  Engine 2 also doesn't take other itemized deductions typed in.
- **MFS and QSS filing statuses** aren't offered (the engine supports them).
- **1099-R box 4 withholding** isn't gathered.
- **Retirement distributions** aren't split into IRA and pension.
- **State returns.** Full state returns: OpenTax has composers for IL, VA, CA, NY and PA, which aren't wired in.
  Everything else uses the simplified state return.
- **Additional Medicare.** Payroll starts Additional Medicare withholding at $200k regardless of filing status, but the
  pay stub explanation uses the filing-status table's threshold.
- **1040-ES and Form 2210.** 1040-ES due dates aren't shifted for holidays, and there is no annualized-income method
  (Form 2210 Schedule AI).
- **Tax lots:** no wash sales, no specific identification, no basis adjustments.
- **RMD exceptions:** the still-working exception, inherited IRAs, the joint-life table, and QCDs.
- **Schedule C lines** for cost of goods sold, depreciation, home office and mileage.
- **Not built from the design:** an IRS Withholding Estimator adapter, and recalculation triggered by investment
  events.
- **Before distributing Home Manager:** offer OpenTax's source (AGPL §6), buy its commercial license, or replace the
  Engine 1 adapter ([taxes](taxes.md#engine-1-opentax)).

## Household

- **Product recall checks** (CPSC/FDA): undecided.
- **Brave free-tier limits:** unconfirmed.

## Security

- **The Brave API key in Windows Credential Manager** (it is an environment variable today).
- **OS-level confinement of the reader worker**, which has resource limits only today. The design:
  - a restricted Windows token and identity;
  - explicit file ACLs (read-only on the one snapshot, write only to the job's scratch space);
  - network denial;
  - a Job Object for process-tree cleanup and CPU and memory limits.

  The confinement must be validated by tests before claiming a sandbox.

## UI

- **The "Household ledger" restyle**, both rounds: not started ([ui](ui.md#proposed-restyle-household-ledger-not-started)).
- **Home:** live balances, customizable panels, a month-end projection, and a daily or weekly view.
- **Bugs found in the 2026-09-30 review.** #5 and #7 are confirmed still present on 2026-10-04; recheck the others before
  fixing.
  1. The Backup list doesn't load when its tab is reached with the arrow keys (`app.js`, `processing.js`).
  2. The document page is stuck on "Loading…" if the preview fetch fails (`receipt.js`).
  3. "Ended" is offered on recurring rows that are already ended or rejected, with no confirmation (`finance.js`).
  4. Clicking an earlier Assistant question duplicates its answer (`assistant.js`).
  5. The Review badge (limit 1000) and the queue (limit 200) can disagree (`review.js`).
  6. Home and chart drill-downs pass `currency`/`metric`, which the Items view ignores (`finance.js`).
  7. Tax-table source URLs are live links with `target=_blank` (`receipt.js`). They must be text (the `app-ux` rule).
  8. Share, Backup, "Look up warranty" and "Look for recurring bills" aren't disabled while running, so a double click
     starts duplicate runs.
- **UX findings from the same review:**
  - **Decisions below the fold:** Review's buttons sit under a late-loading thumbnail, Home's "Needs attention" comes
    after the charts, and the document page's Read and Record buttons are in its footer.
  - **One action, many names:** Read, Record, Count it, Reject, Remove; and "Reconcile now" means two things.
  - **Missing states:** loading and error states exist only on Home, Review and Spending. Unconfigured pages show empty
    tables.
  - **Forms:** form errors are toasts instead of messages next to the field. Budget and asset currencies are free text.
  - **Filters lost on reload:** Documents, Inventory, the Spending month, Forecast assumptions and the Settings tab.
  - **Deep links** from Home, Review and Search open the Documents library, which leaves out receipts and statements.
  - **Too many primary buttons** in Documents rows and Review questions.
  - **Dead ends:** no link from a receipt to its matched charge, no Import on Accounts, and CSV/XLSX files can't be
    opened.
  - **Internal wording** in the document page's default tab and in Processing titles.
  - **The Assistant panel** covers the page and toasts.
  - **Not built:** a first-run welcome, a `?` shortcut overlay, a non-modal drawer, and skeletons.

## Code cleanups

- `library.js` still has the bill payment labels ("Paid" / "Marked unpaid"), and `POST /api/finance/bills/{id}/payment`
  is still registered, though bills are no longer tracked.
- A stale `__pycache__/tax_figures.cpython-313.pyc` remains after `household/tax_figures.py` was deleted.

## Database

These are left over from the 2026-09-30 audit ([development](development.md#database-checks)):
- **Dead columns** to drop when their tables are next rebuilt: `investment_events.reverses_event_id`, `jobs.year` and
  `jobs.month`, and `occurrences.folder_year` and `occurrences.folder_month` (which also make up most of index
  `occurrences_root`).
- **`library_query()`** is one 70-line SQL string with about 30 correlated subqueries. It was left alone on purpose;
  revisit only if the library page gets slow with real data.
- **Run `scripts/db_checks.py` on your live data** yourself, and paste the output redacted as you like.
