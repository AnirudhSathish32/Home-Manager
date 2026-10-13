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
- **Ingestion by document content** ([bugs.md](bugs.md)). Today one pathway reads every document as if it might be a
  receipt. Offer letters, contracts and other keep-only documents should take a deterministic path to their folder.
  Grocery, dining and gas-station receipts should each get their own handling.
- **Gas-station receipts.** The pump number is read as an item, and the gallons and price per gallon are lost. These
  receipts need their own extraction shape.

## Models and evals

- **Structured vision evaluation:** the vision model now reports validated table cells beside its text; paystub extraction
  copies current and YTD amounts from named cells when available. Run the [text extraction plan](../text_extraction_plan.md)
  evaluation gate on the local model and private corpus before default trust in its visual placement.
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
- **Bills and money in, still open** ([money](money.md#bills-and-their-lines)):
  - Manually linking a paystub deposit split across two accounts.
  - A bill line's person can be chosen only in the family's inbox, where the family's people are known; a person's own
    library shows who each line is for as printed.
  - A member's request to share a bill by line reaches the family's inbox when the inbox is next opened on the family
    computer, not at the moment their copy arrives.
- **Family corrections.** Records corrected in the family library after they were sent need **Send** again.
- **Returns** ([money](money.md#returns)):
  - A credit smaller than its return receipt (a restocking fee kept) isn't matched automatically. The user links it by
    hand.
  - A return to a gift card or store credit has no card or bank credit to replace it, so its receipt counts as the
    refund.
  - A refund with no receipt takes its purchase's category, not the purchase's item categories.
  - A Sale or return correction flips a whole receipt. An exchange's single lines can't be flipped yet.
  - **Refund documents are misread** ([bugs.md](bugs.md)). A refund with cleanly extracted text, which says "refund"
    outright, wasn't recognized as one. The refund amount and the item (furniture) were missed. The refund reasoning
    needs another pass.

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

- **Today:** live balances, customizable panels, a month-end projection, and a daily or weekly view.
- **Merchants** show as the statement's upper case (server display text; a merchant-naming decision).
- **UX findings from the 2026-09-30 review that the redesign left open:**
  - **One action, many names:** Read, Record, Count it, Reject, Remove; and "Reconcile now" means two things.
  - **Forms:** some form errors are still toasts instead of messages next to the field (the Money screens, Investments,
    Inventory and Settings show them by the field). Asset currencies are free text.
  - **Deep links** from Today, To check and Search open the Documents library, which leaves out receipts and statements.
  - **Dead ends:** no link from a receipt to its matched charge, and CSV/XLSX files can't be opened.
  - **Internal wording** in the document page's default tab and in Processing titles.
  - **Not built:** a first-run welcome, a `?` shortcut overlay, a non-modal drawer, and skeletons.

## Database

These are left over from the 2026-09-30 audit ([development](development.md#database-checks)):
- **`library_query()`** is one 70-line SQL string with about 30 correlated subqueries. It was left alone on purpose;
  revisit only if the library page gets slow with real data.
- **Run `scripts/db_checks.py` on your live data** yourself, and paste the output redacted as you like.
