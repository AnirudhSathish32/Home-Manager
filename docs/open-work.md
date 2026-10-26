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
  (Receipts now have kinds with their own forms: [documents](documents.md#receipt-kinds).)
- **Analytics on document details** (specs/document-forms D4): fuel-price history, miles per gallon, dining per person,
  grocery unit prices, rate history (APR, APY) and rewards tracking. The details are recorded and shown only.
- **Pay stubs, beyond the guards** (specs/document-forms non-goals): a second, focused vision pass over a pay stub's
  columns, and saved payroll templates per employer (`text_extraction_plan.md`).
- **Document-forms risks not handled** (specs/document-forms domain risks, decision D-P6):
  - mixed-purpose receipts (a gas-station store run, fuel points on a grocery receipt): the kind may flip between
    readings;
  - pump prepay or card holds: a prepay could be read as the total;
  - two copies of one dining receipt (merchant copy with the tip, customer copy): left to duplicate handling;
  - fuel prices printed with 9/10 of a cent, in litres, or with no unit: the fuel check is skipped when the unit isn't
    printed;
  - EBT/SNAP is sensitive: only the tender type is stored, and family routing and donation redaction don't treat it
    specially yet;
  - combined statements (several accounts or cardholders): the summary check may compare one account's totals with
    another's;
  - negative or retro pay lines have no rule of their own (the year-to-date comparison uses magnitudes).
- **Document-forms follow-ups:** pay stub and statement details can't be corrected with Edit details (receipt details
  can); a reviewed receipt's new kind proposes summary details only, never item details (weights); a family member's
  copy of a gift-card receipt shows the amount paid, not the printed total; a full account number quoted inside an item
  row's citation isn't masked (product codes look the same); a document in a running batch whose reading hasn't
  started yet doesn't refuse a kind change (the kind still wins).
- **Complex PDF layout:** merged/stacked headers, wrapped cells, rich form-field association, cross-page tables in the
  reader itself (the transaction import links a table across pages for its own rows only,
  [documents](documents.md#transaction-imports)) and repeated-header/footer detection remain open. Shared native layout is connected to extraction, search and source
  highlighting; see the [text extraction plan](../text_extraction_plan.md) for implemented behavior and limits.

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
- **Statement accounts** (`specs/statement-accounts/spec.md`, approved 2026-10-26; plan in
  `plans/statement-accounts/plan.md`): accounts that Record creates wait for Confirm; Delete account on the Accounts
  tab; Record takes a statement's dates and amounts from its rebuilt columns, never Balance. Until built, re-reading a statement can leave an empty account, and a row
  can take its running balance as its amount (only sent to review).
  - **A value line above the transactions heading** (accepted gap, spec D6 Q7; it stays once the feature is built).
    The spec's FR-27 takes the row directly above a heading as the table's title, and a title that names a balance
    makes the table a balance table. So a statement that prints a value line such as `Ending Balance 1,000.00`
    directly above its transactions heading has none of that table's rows rebuilt, and the page falls back to the
    model's reading, the one that can take a running balance as an amount (the plan adds a record note saying so). Deferred
    fix: count the row above a heading as its title only when that row holds no amount-shaped word. A daily balance
    table's title (`DAILY ENDING BALANCE`) holds none, so it is still excluded. Whether real statements print a value
    line there is unverified (spec A1).
- **PDF transaction import, still open** ([documents](documents.md#transaction-imports)):
  - Scanned (vision) pages are listed but never imported; Record is the way to bring them in.
  - A second transactions heading below a native table: the next page still continues the **first** table, so a table
    with different columns could be read with the first one's. The preview shows each row's columns and signed amount.
  - Any later-page line with a date and an amount in the continued table's columns is counted, schedules included.
    The preview totals are the only check.
  - A card statement listed newest first can get dates a year off after the year rollover.
  - Import primary can leave a PDF never Recorded, so its balances are never checked. Record is in More actions.
  - Record finds an account by its institution text, ignoring case and spacing only. A PDF import account named
    differently ("Chase" for "JPMORGAN CHASE BANK") gets a second account and duplicate rows when the PDF is Recorded
    later, or nothing is published when the statement prints no currency.
  - The source badge fetches the full provenance for every imported transaction input in an open breakdown (one request
    each, up to 200). The trace could carry the page and row itself.
  - The import index's `refused` kind is read from the refusal message text (`pdf_import.REFUSED`), and the dialog finds
    an unread PDF by comparing the error text `Read this document first.`. Both want a structured value from the server.
  - The row status badges reuse existing statuses with the server's text; there is no vocabulary of their own yet.
  - Accuracy on real bank PDFs is unmeasured. The manual run covered only synthetic statements.
- **Record of a statement with no transactions.** With openai/gpt-oss-20b, Record of synthetic K (9 printed rows)
  once came back with an empty transactions list and the run succeeded. Nothing checks the row count against the
  printed rows; the balance check is the only catch. Found 2026-10-25 while tracing the K Record failure.
- **Bills and money in, still open** ([money](money.md#bills-and-their-lines)):
  - Manually linking a paystub deposit split across two accounts.
  - A bill line's person can be chosen only in the family's inbox, where the family's people are known; a person's own
    library shows who each line is for as printed.
  - A member's request to share a bill by line reaches the family's inbox when the inbox is next opened on the family
    computer, not at the moment their copy arrives.
- **Bill kinds, still open** ([documents](documents.md#bill-kinds)):
  - Only `rent` has its own form. Utility (electric, gas, water: meter reads and usage), phone (per-line plans and
    devices) and insurance (policy period and coverage) bills are read with the general form.
  - Family routing doesn't carry a bill's `bill_kind`, its lines' `line_type` or the bill's details yet: a rent bill
    sent to a member arrives with no kind, with the same lines, categories and amounts.
  - The rent form's live accuracy is measured only by the `document_forms` eval on synthetic RENT; run it on your own
    bill and compare ([evals](evals.md)).
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

## App server

- **Uvicorn and `Connection: close` clients** (found 2026-10-18 while building the agent test instance): a client that
  sends `Connection: close` (curl, urllib) asks uvicorn to close right behind a multi-segment reply such as
  `index.html`, which hits the Windows loopback segment loss ([development](development.md#windows-loopback-resets)):
  a 19 s stall, then a reset. Browsers and the project's own clients keep connections alive and aren't affected;
  `scripts/test_instance.py` uses a keep-alive client that closes first.

## Database

These are left over from the 2026-09-30 audit ([development](development.md#database-checks)):
- **`library_query()`** is one 70-line SQL string with about 30 correlated subqueries. It was left alone on purpose;
  revisit only if the library page gets slow with real data.
- **Run `scripts/db_checks.py` on your live data** yourself, and paste the output redacted as you like.

## Tests

- **`test_receipt_kinds.py::test_sc18_a_kind_change_waits_for_a_reading_of_the_same_document` fails now and then**
  (found 2026-10-20 while building bill kinds): it counted 8 model requests instead of 7 in a broad run, then passed
  alone. It likely counts requests as soon as the run reports `running`, before the held request reaches the stub;
  wait for the stub to receive it before counting.
