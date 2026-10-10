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
- **Returns** ([money](money.md#returns)):
  - A credit smaller than its return receipt (a restocking fee kept) isn't matched automatically. The user links it by
    hand.
  - A return to a gift card or store credit has no card or bank credit to replace it, so its receipt counts as the
    refund.
  - A refund with no receipt takes its purchase's category, not the purchase's item categories.
  - A Sale or return correction flips a whole receipt. An exchange's single lines can't be flipped yet.

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
- **Retirement distributions** aren't split into IRA and pension.
- **State returns.** Full state returns: OpenTax has composers for IL, VA, CA, NY and PA, which aren't wired in.
  Everything else uses the simplified state return.
- **Form 2210:** there is no annualized-income method (Schedule AI).
- **Tax lots:** no wash sales, no specific identification, no basis adjustments.
- **RMD exceptions:** the still-working exception, inherited IRAs, the joint-life table, and QCDs.
- **Schedule C lines** for cost of goods sold, depreciation, home office and mileage.
- **Not built from the design:** an IRS Withholding Estimator adapter, and recalculation triggered by investment
  events.
- **Before distributing Home Manager:** offer OpenTax's source (AGPL §6), buy its commercial license, or replace the
  Engine 1 adapter ([taxes](taxes.md#engine-1-opentax)).

## Household

- **Product recall checks** (CPSC/FDA): undecided.
- **Returned items** ([household](household.md#returned-items)) are asked on the Inventory page only. They aren't in
  Review or its count yet.
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

- **The redesign** is listed under [UI redesign](#ui-redesign) below.
- **Home:** live balances, customizable panels, a month-end projection, and a daily or weekly view.
- **UX findings from the 2026-09-30 review:**
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

## UI redesign

The design is in [ui](ui.md#redesign-calculation-observability). The items below are in build order, with
one or two per session. Paths are under `src/home_manager/`. Each item is done when its test passes; remove it from
this list once it's built. Items 1–4 (the backend: correct numbers, traces, provenance, and every engine line traced,
Engine 2's included) are built: ui.md "Trace contract", "What's built"; taxes.md "The engines' worksheets". Phase 0
is done: direction C · Family, in `design-system/home-manager/MASTER.md`. Phase 1a (tokens in light and dark, the
theme switch, self-hosted fonts, chart colors as tokens, base components, and the shell with a top bar under 820px)
is built: ui.md "Design system". Phase 1b (item 5: `pageState()` on five pages, the `trace.js` components, the
`ui_v2_screens` flag and `tests/test_ui_parity.py`) is built: ui.md "Design system", "Observability components",
"Migration". Phase 2 Taxes is next; see `design-system/home-manager/README.md`.

**6. Screens, one per session.** Taxes → Today → To check and the document page (with Correct) → This month,
Transactions (Add, Import), Bills, Accounts (Import) → Investments, Forecast, What If → Inventory (Item insights) →
Processing (Data health), Settings (Independent checks editable, Donate) → Search, Ask.

The To check and document page session also builds the remaining components in ui.md "Observability components":
`confirmCorrect()`, `sourceViewer()` and `historyList()`. It plans a correction-preview endpoint for Correct (none
exists yet), and pulls `receipt.js`'s `highlightEvidence()` out of its global `receipt` state for `sourceViewer()`.

Today's session starts from what the user asked for in Phase 0 (MASTER.md "Decided for later screens"):
- **Budgets in the breakdown style:** category lines with a budget meter (from `get_budgets`) instead of a running
  total. The meter is amber when ahead of pace or over, never red.
- **Cash and Net worth** side by side (`worth.today`). Cash adds up every account's latest statement balance, shows the
  date range, and flags accounts over 35 days old as stale.
- The rest of the Phase 0 mock-up (October figures, weekly chart, Coming up) was a placeholder. Ask the user for their
  layout notes on the remaining sections.

**7. Surface backend-only features.** Give a screen to `GET /api/finance/health`, `PUT /api/reviewer-settings`,
`POST /api/decision-model-tests`, `PUT/DELETE /api/tax/businesses/{id}`, and `GET /api/tax-tags/on/{receipt|receipt_item}`.
Each is tested at the API already; the bill payment endpoint was removed.

**8. Cleanup.** Remove the old loaders, the duplicate helpers (`asyncButton`/`actionButton`, the five table builders)
and dead CSS. Then rewrite ui.md "Design system" and "Pages" to match what was built.

## Database

These are left over from the 2026-09-30 audit ([development](development.md#database-checks)):
- **`library_query()`** is one 70-line SQL string with about 30 correlated subqueries. It was left alone on purpose;
  revisit only if the library page gets slow with real data.
- **Run `scripts/db_checks.py` on your live data** yourself, and paste the output redacted as you like.
