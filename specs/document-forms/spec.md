# Document forms: receipt kinds, pay stubs and statements
Feature: document-forms

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

Amends: no earlier spec exists. The baseline is the built behavior in `docs/documents.md` "Typed extraction" and
"PDFs", `docs/money.md` "Reading a statement or receipt again" and "Corrections", and the implementation record in
`text_extraction_plan.md`, with the code cited below. This spec was first drafted as `receipt-kinds` and was renamed
before any approval (decision D13). The `receipt-kinds` draft was merged into this file and removed.

## Goal / users / scope / non-goals

**Goal.** Each kind of document the household records gets a JSON form shaped for what that document prints. The
reasoning model fills the form from the saved transcription (from the vision model or PDF text). Code checks every
value, works out the document's arithmetic, and shows the results with their sources and traces.
1. **Receipts** are split into kinds, each with its own form: `fuel`, `dining`, `grocery` and `general`.
2. **Pay stubs, bank statements and credit card statements** keep their single type each and gain the printed fields
   they lose today (decision D10). Pay stubs also get guards so that a year-to-date or annual amount can never count
   as this paycheck. This fixes the reported defect (D14).

**Users.** The household user who scans documents and reviews them on the document page.

**In scope.** The receipt kinds:
| Kind | What tells it apart (proposed by the model, with cited lines) |
|---|---|
| `fuel` | A gas-station purchase: a volume of fuel at a printed price per unit, a pump number, fuel grade |
| `dining` | A restaurant, cafe, bar or takeout: food and drink for here or to go, tip or gratuity lines, server or table |
| `grocery` | A supermarket or market: groceries, items priced by weight, loyalty savings, bottle deposits, bag fees, giftcard deductions, number of a unit (2x Chips @ 2.00 showing $4.00 as the line total) |
| `general` | Every other purchase receipt. This is the fallback and keeps today's form unchanged |

New fields for the other three types:
| Type | New printed fields (each optional, cited, never guessed) |
|---|---|
| Pay stub | For each earning line, its hours and rate. Paid-time-off and sick-leave balances. Each direct-deposit split, with the account's last four digits and the amount. For every pay amount, the printed row label and column heading it was read under |
| Bank statement | Account type (checking, savings, money market or other, from printed words only). Deposits total, withdrawals total, interest earned, interest rate (APY) and fees total |
| Credit card statement | Purchase rate (APR) and cash-advance rate (APR), credit limit, available credit, rewards earned and rewards balance |

**Non-goals:**
- Invoices. They stay on the existing `bill` path (`extraction.py:59–60`, `:106–113`; migration 069) (D1).
- Sub-kinds of pay stubs or statements, such as hourly vs salaried or checking vs savings statements (D10). Account
  type is a field, not a separate form.
- Changes to what is counted. Interest earned, card interest and fees, and deposit splits stay counted exactly as
  today. Reconciliation and category splits don't change, except where FR-06 fixes a misread row (D12) and where a
  gift card lowers a receipt's amount paid (FR-09, D15).
- Analytics on the new fields, such as fuel-price history, MPG, dining-per-person, grocery unit prices, rate history
  or rewards tracking. These go to `docs/open-work.md` (D4).
- A second, focused vision pass, or saved payroll templates, for pay stubs. These are proposed in
  `text_extraction_plan.md:48–49` and stay open work. This spec reads the saved transcription only.
- Bulk re-processing of existing records (D5).
- Bills, investment documents, tax forms and loan documents.

## Existing behavior (verified paths, assumptions, unknowns)

**Verified (all in `src/home_manager/documents/extraction.py` unless named):**
- **Two-step typed extraction.** `ExtractionService.extract` (`:1471`) asks `Classification` (`:174`, prompt
  `CLASSIFY` `:431`). It then asks for the type's summary form, `HEADER_MODELS[kind]` (from `HEADERS`, `:53`, `:339`),
  and its rows in bounded chunks (`ROWS`, `:354`). The version is `typed-extraction-v22-native-cells` (`:42`). The
  model is the local reasoning model from Settings (`ReasoningConfig`, `:1792`).
- **Receipts.**
  - Every receipt uses one form (`:54`, `Item` `:218`). The only thing that tells receipts apart is the category
    picked per item afterwards (`describe_purchase`, `:1596`).
  - Arithmetic is in `normalize` (`:996–1018`).
  - A pump number is read as an item (`docs/bugs.md:16`, `docs/open-work.md:24–25`).
- **Pay stubs.**
  - The summary is employer, pay date, period, frequency, work state, gross and net pay (this period and year to
    date), taxes and deductions (`:61`).
  - Each line is a `PayLine` (`:254`) with group, category, current and ytd.
  - Arithmetic checks that earnings equal gross, and that gross less pre-tax deductions, taxes and post-tax
    deductions equals net. Both run on the current column, and on the year-to-date column when it's fully printed
    (`paystub_lines`, `:1308`).
- **Pay stub column safeguards built by the text-extraction work** (`text_extraction_plan.md` "Consumer wiring" and
  "Implementation record"):
  - When a validated table, from vision or native PDF, has headings that map to Current or YTD, code copies the money
    from the cells (`anchor_paystub` `:569`, `paystub_columns` `:467`). Hours and rate columns are never treated as
    pay.
  - A cited line with several numbers and no validated row is set to null and goes to review (`:608`, `:631`).
- **Bank and credit card statements.**
  - The bank summary is institution, account, period, opening and closing balance (`:55`).
  - The card summary is issuer, account, period, previous balance, payments, credits, purchases, fees, interest,
    statement balance, minimum payment and due date (`:56`).
  - Transactions are rows (`Transaction` `:231`).
  - The only arithmetic check is opening balance plus transactions equals closing balance (`:1038–1046`). Nothing
    checks the printed summary against itself.
- **Counting, corrections and storage.**
  - A record counts automatically only when its required fields are present, at least one cross-check agreed,
    nothing is ambiguous and the decision model raised no doubt (`REQUIRED` `:136`, `CROSS_CHECKED` `:142`,
    `review_reasons` `:1355`).
  - Corrections outlive reading again, and records you reviewed are never overwritten (`docs/money.md`).
  - Account numbers are stored as their last four digits only (`:984–987`).
  - Traces follow `docs/ui.md` "Trace contract" (`finance/traces.py`).

**Reported defect (D14).** The user reports that the reasoning model keeps putting year-to-date or yearly income into
this paycheck's fields. The code shows a path for this:
- When no validated Current/YTD table applies (photos without reported tables, or headings that don't map), a summary
  value comes from the model.
- A single-number line such as `YTD GROSS 32,500.00` passes every citation check when cited for `gross_pay`.
- If the model puts year-to-date figures into gross, net and the lines alike, the arithmetic checks still agree. The
  stub can then **count automatically**.
- Nothing compares this period with year to date, or rejects a citation labelled YTD, annual or salary.

This explanation is a hypothesis: the user's paystub has not been inspected (`text_extraction_plan.md:3`) and must not
be read by an agent.

**Assumptions:**
- A1. A kind and the new fields can be asked for without an extra model call per document. The plan decides this.
- A2. Price per unit, volume, hours, rates and percentages can have three or more decimals. They are stored as exact
  decimals or text, never as minor units.

**Unknowns:**
- U1. How accurate the live model is on kinds and the new fields. Only synthetic fixtures are used here. The user runs
  the corpus evaluation themselves.
- U2. Which path the user's failing paystub took: table or flat text, and image or PDF. It is settled by the
  user-run reproduction in SC-20, not by an agent reading it.

## Functional requirements

### Receipts (FR-01 – FR-19)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-01 | A document classified as `receipt` gets a receipt kind from {`fuel`, `dining`, `grocery`, `general`} and the line evidence for it. | With a stubbed model, the extraction result and stored receipt carry `receipt_kind` and its citations. Citations must pass the existing exact-quote check. |
| FR-02 | If the proposed kind is uncited, its citation fails checks, or the value is not in the list, the receipt is read as `general` with a review note saying why. | A stub that returns an uncited `fuel` gives `receipt_kind=general` plus the note, and the record is `needs_review`. |
| FR-03 | Each kind has its own form: the common receipt fields plus the kind's fields. The model is asked for that form, and code checks it with the same citation, amount and date rules as today. | The schema sent for each kind contains the fields in FR-04 and no other kind's fields (checked on the captured request payload). |
| FR-04 | The kind's fields: **fuel**: volume, volume unit (gallon or litre), price per unit, fuel grade, pump number, fuel amount. **dining**: tip, gratuity or service charge included (and its amount), party size, server or table. **grocery**: per item, weight and unit and price per weight unit; for a line sold as several units, the printed count and unit price (`2x CHIPS @ 2.00 4.00` → quantity 2, unit price 200, line total 400); loyalty or member savings total; bottle deposit and bag fees as their own lines; tender type such as EBT/SNAP; each gift card deduction as a tender with its amount and the card's last four digits, never as an item or a discount. **general**: none beyond today's form. Each field is optional: `proposed` with a citation, or `missing`/`ambiguous` with a null value. | For each kind, a stubbed fixture produces stored values for every printed field and null for unprinted ones. A field that is not printed is never filled in. |
| FR-05 | Amounts follow the existing money rules: integer minor units with an ISO currency, printed in their cited line. Price per unit and volume are stored as exact decimals (not floats, not rounded to minor units), along with their unit. | `3.459` per gallon is stored and shown as `3.459`. A fuel amount printed as `32.15` is stored as `3215` USD minor units. No floats are written. |
| FR-06 | A fuel receipt's pump number, grade, volume and price per unit are details, never items. The fuel purchase is one item whose line total is the fuel amount, in category `transportation`. Car-wash or in-store goods stay separate items. | Fixture "Pump 17, 10.312 GAL @ 3.459, REG UNL 35.67, COFFEE 2.19" stores 2 items (fuel 35.67, coffee 2.19) and no "Pump 17" item. |
| FR-07 | A fuel receipt gets one more arithmetic cross-check: volume × price per unit, rounded half-up to the minor unit, equals the fuel amount within 1 minor unit. Passing adds to `cross_checks`. Failing adds a review reason naming the three printed values. | Matching fixture: `cross_checks` increases and it can count automatically. Mismatching fixture: `needs_review` with the reason. |
| FR-08 | A dining receipt's tip, and any included gratuity or service charge, keep the existing subtotal + tax + tip = total check. An included gratuity counts toward that sum, not on top of it. | A fixture with an 18% included gratuity reconciles without double counting. A fixture with a blank tip line leaves `tip` missing (not 0). |
| FR-09 | On a grocery receipt, items priced by weight keep weight, unit and price per weight unit next to the line total, and loyalty savings, deposits and bag fees are not lost. Item sum = subtotal still applies. Savings printed as their own lines take part in it. **Multi-unit lines:** when a line prints a count and a unit price, count × unit price, rounded half-up to the minor unit, equals the line total within 1 minor unit. Passing adds to `cross_checks`, and failing adds a review reason naming the three printed values. A line without a printed count skips the check. **Gift cards (D15):** a gift card deduction is a way of paying, not a discount, and it never takes part in item sum = subtotal. The receipt keeps its printed total and gets a separate **amount paid**: the printed total minus its gift card deductions. Amount paid is what the receipt counts toward spending, budgets and money out. Its category splits are scaled to it, each category keeping its proportion (`finance/splits.py` `scale`). It is also the amount a card or bank statement line must match (`finance/reconcile.py:392`). The document page shows both, as "Total 8.55 · Gift card −5.00 · Paid 3.55". With no gift card, amount paid equals the total, and nothing changes from today. Deductions larger than the total go to review with "gift card deductions exceed the total", and the receipt counts its printed total until you correct it. | "BANANAS 2.31 lb @ 0.59/lb 1.36" stores weight 2.31, unit lb, price 0.59 and line total 1.36. Deposit and bag fee are separate lines. "2x CHIPS @ 2.00 4.00" stores quantity 2 and unit price 200, and the check passes; printed as 4.50 it goes to review. A gift card deduction of 5.00 on an 8.55 total is stored as a 500 tender. The receipt shows total 8.55 and counts 3.55, its category splits sum to 3.55, and a −3.55 card line matches it (SC-27). |
| FR-10 | The document page shows each record's new fields: the receipt kind and its details (grocery weights with their items), and the pay stub and statement fields from FR-20 – FR-28. Each value links to its source line like other fields. | Browser test on synthetic fixtures: the fields are visible, and each has a citation link that highlights its line. |
| FR-11 | The user can change a receipt's kind on the document page. Saving re-extracts that receipt's details and rows with the new kind's form from the saved transcription. There is no new vision call. The user's choice persists across later readings. | Changing `general` to `fuel` sends one extraction with the fuel form and zero vision requests. A later re-read keeps `fuel`. The change appears in history with Undo. |
| FR-12 | Changing the kind, or reading again, follows the existing rule for reading again: a record you approved or rejected is never rewritten. The kind change is saved as a correction. On such a record, the new kind's details are kept as a pending proposal and shown with an **Apply details** action. Applying saves them as a correction, with Undo, and doesn't change the amounts or the review state. An unapplied proposal stays pending with no expiry, until it's applied or replaced by a later kind change. Your corrections to amounts are kept. | On a verified receipt, a kind change stores the correction, the amounts and review state are unchanged, and the new details are pending. **Apply details** makes them current as a correction with Undo. |
| FR-13 | Existing records keep their current data until they are extracted again. After the upgrade, receipts have kind **null** ("not read with kinds"), not `general`. Existing pay stubs and statements have null for every new field. Nothing is re-processed in bulk. | Migration test: pre-existing receipts, pay stubs and statements are unchanged in every money, item, line and review column. New columns or fields are null, and no extraction is queued. |
| FR-14 | If a receipt kind's form, or the new fields of a pay stub or statement, fail validation after the single existing correction request, the record is still published with today's fields and rows. It waits in Review with the reason "document details could not be read" and has no new fields (none partially stored). | A stub that returns invalid fuel details twice gives a published receipt with merchant, date, total and items, plus that reason. The same holds for a bank statement whose new fields fail twice. |
| FR-15 | Each receipt in a file split into several receipts gets its own kind. | A synthetic file with a fuel receipt and a dining receipt gives two segments with kinds `fuel` and `dining`. |
| FR-16 | The extraction version changes, so new readings are told apart from old ones and finished readings are not reused across versions. | `EXTRACTION_VERSION` differs from `typed-extraction-v22-native-cells`, and a reading at the old version is not reused. |
| FR-17 | The docs are updated. The receipt kinds and the new fields are described in `docs/documents.md` "Typed extraction". The pay stub guards are described where pay stub reading is documented. The new trace refs are documented where trace refs are listed. The gas-station and receipt-kind items are removed from `docs/open-work.md` "Ingestion", and the deferred analytics and pay stub alternatives (D4, non-goals) are added there. `text_extraction_plan.md` is updated to say which of its open pay stub items this feature closes. | Doc diff present when the change is implemented. |
| FR-18 | A kind change is refused while a reading or extraction of the same document is queued or running. The message is "A reading is in progress; try again when it finishes" (HTTP 409), and nothing changes. | While a stubbed extraction is held running, `PATCH` kind returns 409, with no correction row and no extra request. Afterwards, the same `PATCH` succeeds. |
| FR-19 | Every arithmetic check this feature adds is a traceable figure through `GET /api/traces/{ref}`, under `docs/ui.md` "Trace contract". The checks are the fuel check (FR-07), the dining total (FR-08), multi-unit lines and amount paid after gift cards (FR-09, compared with the other printed tenders when they're printed), hours × rate and deposit splits (FR-21), the bank summary (FR-26) and the card summary (FR-28). Each trace shows its inputs as steps with their provenance: `extracted` (document line and quote), or `override` when you corrected them. It also shows its rounding method, the printed amount it is compared with, and `reconciles`, which is true exactly when the check passes. The document page links each figure to its trace. Asking for a figure a record doesn't have returns "This isn't worked out for this record.", not an empty trace. | Each trace's `result` equals the figure shown on the page, and `reconciles` matches the check's outcome in SC-19, SC-21, SC-22 and SC-23. |

### Pay stubs (FR-20 – FR-24)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-20 | A pay stub's form adds, for each earning line, hours and rate, stored as exact decimals. It also adds paid-time-off and sick-leave balances (the hours or amount as printed, with their label), and each direct-deposit split (account last four digits and amount in minor units). **Every pay amount, whether a summary field or a line's this-period or year-to-date amount, carries the printed row label and the printed column heading it was read under** (null when none is printed), each cited. | A stubbed fixture stores hours `80.00`, rate `31.25`, PTO `56.00 hrs`, and splits `1234`/150000 and `9876`/41234. Each amount's stored row label and column heading are exact substrings of their cited lines. |
| FR-21 | Two more pay stub cross-checks. **Hours × rate:** for each earning line with hours, rate and a this-period amount, hours × rate rounded half-up to the minor unit equals the amount within 1 minor unit. **Deposit splits:** when every split has an amount, their sum equals net pay. Passing adds to `cross_checks`. Failing adds a review reason naming the printed values. A line or stub without these values skips the check (it doesn't fail). | Matching fixture: both checks pass. A mismatching rate gives `needs_review` with the reason. A salaried line with no hours raises no hours issue. |
| FR-22 | **This period never takes a year-to-date or annual amount (D14).** A this-period value (gross pay, net pay, taxes, deductions, or a line's current amount) is rejected, set to null and `ambiguous`, with a review reason, when any of these hold: (a) its row label or column heading reads as year-to-date or annual (YTD, year to date, annual, yearly, per year; "salary" alone doesn't, since stubs label this paycheck's pay "Regular Salary" — amended 2026-10-19); (b) its magnitude exceeds that field's or line's printed year-to-date magnitude; (c) every this-period amount on the stub equals its year-to-date amount while the pay period does not start within the first pay period of the calendar year (worked out from the period dates and pay frequency; when those are unknown, all-equal amounts go to review). Some amounts equal to their year to date are kept, since a pay line or benefit can start mid-year — amended 2026-10-19; before, any one equal amount was rejected. These guards apply on every path: validated table cells, native PDF cells and flat text. Rejections are never filled with a calculated value. | Each rule has a stubbed fixture where the model puts the year-to-date or annual figure in a this-period field. The value ends null and ambiguous, with a reason naming the field, both values and their lines. A first paycheck of the year with equal amounts is accepted. |
| FR-23 | A pay stub where any FR-22 rule fired never counts automatically, even when its arithmetic cross-checks agree. It waits in Review until you correct or approve it. Correcting the field with **Edit details** clears that reason, as for other fields. | The "all year-to-date" fixture, where gross, net and lines are all year-to-date values that add up, is `needs_review`, not verified. After you correct gross and net to the this-period values, the reasons clear. |
| FR-24 | The reported defect is reproduced before it is fixed. A synthetic test reproduces the year-to-date-as-this-paycheck mistake through the public extraction entry point on the current code. It is committed alongside the fix. The user can also run a redacted reproduction of their own paystub through the eval tools in their own terminal, sharing only `summary.json`. | The characterization test fails on the pre-change code because the stub is verified with gross equal to the YTD value, and passes after the change. The eval task reports wrong-column values that would have counted automatically, per fixture. |

### Bank and credit card statements (FR-25 – FR-28)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-25 | A bank statement's form adds the account type (checking, savings, money market or other, only from printed words such as "Everyday Checking"), deposits total, withdrawals total, interest earned, fees total (minor units), and interest rate (APY), stored as printed percentage text. | A stubbed fixture stores each value cited. Account type is `other` when no type word is printed, never guessed from the transactions. |
| FR-26 | A bank statement gets a summary check from printed totals: opening balance + deposits − withdrawals = closing balance. It runs only when all four are printed, and passing adds to `cross_checks`. A failing check adds a review reason naming the four values. The existing check from the transaction rows is unchanged and separate. | Matching: 1,000.00 + 2,500.00 − 1,200.50 = 2,299.50 counts. Mismatching: `needs_review` with the reason. |
| FR-27 | A credit card statement's form adds the purchase rate (APR) and cash-advance rate (APR) as printed percentage text, credit limit and available credit (minor units), and rewards earned and rewards balance (as printed, with an amount in minor units when it's money). | A stubbed fixture stores each value cited. Points stay text (`812 points`) and are never converted to money. |
| FR-28 | A credit card statement gets a summary check from its printed summary: previous balance − payments − credits + purchases + fees + interest = statement balance. It runs only when all are printed (a printed 0.00 counts as printed), and passing adds to `cross_checks`. A failing check adds a review reason naming the values. | Matching: 500.00 − 500.00 − 20.00 + 812.45 + 0.00 + 0.00 = 792.45 counts. Mismatching: `needs_review`. |

### All types (FR-29 – FR-30)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-29 | The new fields don't change what is counted or reconciled (D12). Spending, money in, category splits, account balances and reconciliation give the same results as today for the same transactions and records, except where FR-06 fixes a receipt row, where FR-09 counts a receipt's amount paid after gift cards (D15), and where FR-22 sends a wrong this-period amount to review. | For the bank, card and pay stub fixtures, the month's spending, money-in and balance figures equal the values worked out from their transaction rows and this-period amounts under today's rules. |
| FR-30 | Sensitive identifiers are never stored in new fields: full account or card numbers, routing numbers, SSNs and employee IDs. Account references keep only their last four digits. If the model returns more, only the last four are kept. Values that are not account numbers are dropped, with a note. | With a fixture that prints `SSN XXX-XX-1234`, `Employee ID 445566`, `Routing 021000021` and `Account 000123456789`, no stored record column or JSON outside the saved transcription contains `445566`, `021000021` or `000123456789`. The split account is stored as `6789`. |

## Invariants, privacy, security and data retention

- **Nothing leaves the machine.** All model calls go to the configured local or tailnet reasoning model, under the
  existing endpoint validation. No new external service is used.
- **The transcription is untrusted.** The existing `RULES` preamble applies to every form. Instructions inside a
  document are never followed.
- **Money integrity.**
  - Amounts are integer minor units with a currency.
  - Decimals that are not money (volume, prices per unit, weights, hours, rates, percentages) are exact text or
    decimals with their unit.
  - Each record's counted amount is chosen exactly as today (FR-29), except that a receipt paid partly by gift card
    counts its amount paid (FR-09). Its printed total is kept and shown, never overwritten.
- **Nothing is invented.** Every non-null value cites an exact quote. Values that are not printed stay null. The new
  checks only compare values; they never fill one in. A rejected this-period value stays null (FR-22).
- **This period and year to date stay apart.** No path lets a year-to-date or annual figure count as a paycheck
  without your decision (FR-22, FR-23).
- **User decisions win.** Verified or rejected records, corrections, and a kind the user set are never overwritten by
  the model.
- **Identifiers.** Only the last four digits of account numbers are kept (FR-30).
- **Development data.** Only synthetic fixtures in Git are used. `P:\Finances`, `%LOCALAPPDATA%\HomeManager` and
  `P:\EvalCorpus` are never read. The user's failing paystub is reproduced only by the user (FR-24).

## Errors, recovery, duplicates, restart behavior

- **Kind proposal is invalid** → `general` with a note (FR-02).
- **New fields or a kind's form fail validation twice** → today's fields are published and the new ones are left out
  (FR-14).
- **Cancelled or interrupted run** → nothing is published, and the run can be retried after a restart. A record's
  kind, new fields, items and lines are written together or not at all.
- **Kind change during a reading** → 409, nothing changed (FR-18).
- **Duplicates** → identical bytes share one reading, as today.
- **Reading again** → the item- and line-matching rules in `docs/money.md` apply. A fuel item matches the earlier
  item by description and line total. A former "Pump 17" item that you
  haven't worked on is removed, and one you did work on is kept, with a note. A pay stub that FR-22 rejected keeps
  your corrections across readings.

## Nondeterministic outputs and how they are verified

- **Model output** (the kind chosen and the form contents) is checked only through fixed stubbed responses (the
  `local_model` server in `tests/conftest.py`). No test asserts live-model output.
- **Live accuracy** is measured by eval tasks on synthetic fixtures in `evals/`. That covers the kind chosen, how each
  form's fields are filled, and the pay stub wrong-column count. The user runs them on the donated corpus, and their
  own redacted paystub, in their own terminal, and only `summary.json` may be shared (`docs/evals.md`). The pay stub
  target follows `text_extraction_plan.md:237`: **zero wrong-column values counted automatically** on critical pay
  stub fixtures. The other thresholds stay open.
- **Timestamps and IDs** are compared for presence and ordering, not for exact values.

## Scenarios

All scenarios run on synthetic transcriptions with stubbed model replies.

| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-01 | FR-01,03,04,05,06,07 | Fuel receipt: Pump 17, 10.312 GAL @ 3.459, REG UNL 35.67, COFFEE 2.19, total 37.86. | Extract. | `fuel`. Details are stored. Two items (35.67 transportation, 2.19). Fuel check passed. Counts automatically. |
| SC-02 | FR-07 | As SC-01, fuel amount 36.67. | Extract. | `needs_review`, with a reason naming 10.312, 3.459 and 36.67. |
| SC-03 | FR-04,08 | Dining: subtotal 50.00, tax 4.00, gratuity 18% included 9.00, total 63.00, blank tip. | Extract. | `dining`. Gratuity 9.00, tip missing, reconciles to 63.00. |
| SC-04 | FR-04,09,30 | Grocery with a weighed item, a multi-unit line (2x CHIPS @ 2.00 4.00), savings, deposit, bag fee, a gift card deduction of 5.00 and EBT for the rest. Variant: CHIPS printed 4.50. | Extract. | `grocery`. Weight, unit and price stored. Quantity 2 and unit price 200, multi-unit check passes. Separate lines. Item sum = subtotal. Gift card stored as a tender with its last four only. Total 8.55 shown, amount paid 3.55 counted. The variant gives `needs_review`. |
| SC-05 | FR-01,13 | Existing general-retail fixture. | Extract. | As today, plus `receipt_kind=general`. |
| SC-06 | (regression) | Invoice fixture. | Extract. | `bill` with `invoice_json`, and no receipt kind. |
| SC-07 | FR-02 | Kind `fuel` with a bad citation. | Extract. | `general` plus a note, `needs_review`. |
| SC-08 | FR-14 | Fuel form invalid twice. | Extract. | Today's receipt fields published, no details, the review reason. |
| SC-09 | FR-11,12 | `general` receipt in Review. | Change the kind to `fuel`. | One fuel-form request, no vision. History with Undo. Re-read keeps `fuel`. |
| SC-10 | FR-12 | Verified receipt with a corrected total. | Change the kind to `dining`, then Apply details. | Amounts and review state unchanged. Details pending, then current after Apply, with Undo. |
| SC-11 | FR-13 | Pre-upgrade database with receipts, a pay stub and a bank statement. | Migrate. | Data unchanged. New fields null, receipt kind null. Nothing queued. |
| SC-12 | FR-15 | Two-page PDF: a fuel receipt and a dining receipt. | Extract. | Two segments, `fuel` and `dining`. |
| SC-13 | FR-06 | v22 fuel receipt with a "Pump 17" item. | Read again. | Pump item removed, fuel item present. |
| SC-14 | FR-10 | SC-01, SC-04, SC-21, SC-22, SC-23 records. | Open the document pages. | New fields visible with source links. |
| SC-15 | FR-16 | Parse with only a v22 run. | Extract. | New run (`reused: False`). |
| SC-16 | FR-17 | Feature implemented. | Review `git diff docs/ text_extraction_plan.md`. | Docs updated as FR-17 says. |
| SC-17 | (evals) | Synthetic fixtures per receipt kind and type. One stubbed answer wrong. | Run the eval tasks with a stubbed model. | `summary.json` reports per-kind or per-type accuracy, field counts and the wrong-column count. |
| SC-18 | FR-18 | Extraction held running. | `PATCH` the kind, release the run, `PATCH` again. | 409, then success. |
| SC-19 | FR-19 | SC-01, SC-02, SC-03 and SC-04 records. | Get the fuel, dining and multi-unit traces. | Results, provenance and `reconciles` as in FR-19. |
| SC-20 | FR-22,23,24 | Pay stub fixtures where the stub puts year-to-date or annual figures in this-period fields (a YTD-labelled line, a larger-than-YTD value, equality mid-year, an annual salary line, all year-to-date consistently), plus a first-of-year paycheck. | Extract each one. Correct one. | Each wrong value is null and ambiguous with its reason. None counts automatically. First-of-year is accepted. The correction clears its reason. The characterization variant fails before the change. |
| SC-21 | FR-20,21,19 | Pay stub: Regular 80.00 h × 31.25 = 2,500.00, YTD 32,500.00. PTO 56.00 hrs. Splits ****1234 1,500.00 and ****9876 412.34. Net 1,912.34. | Extract. Get the traces. Variant: rate 31.00. | Fields stored. Both checks pass and are traced. The variant gives `needs_review`. |
| SC-22 | FR-25,26,19 | Bank: Everyday Checking. Opening 1,000.00, deposits 2,500.00, withdrawals 1,200.50, closing 2,299.50. Interest 0.42, APY 0.50%, fees 0.00. | Extract. Trace. Variant: closing 2,300.50. | Fields stored. Summary check passes and is traced. The variant gives `needs_review`. |
| SC-23 | FR-27,28,19 | Card: previous 500.00, payments 500.00, credits 20.00, purchases 812.45, fees 0.00, interest 0.00, balance 792.45. APR 24.99%, limit 5,000.00, available 4,207.55, 812 points earned. | Extract. Trace. Variant: balance 795.45. | Fields stored. Check passes and is traced. The variant gives `needs_review`. |
| SC-24 | FR-29 | SC-21's pay stub dated in September 2026 (fixture P-sept), plus the SC-22 and SC-23 records. | Read September's spending, money in and balances. | Equal to the values worked out from the fixtures under today's rules. |
| SC-25 | FR-30 | Pay stub and bank fixtures printing an SSN, employee ID, routing number and full account number. | Extract. | No identifier in any stored record field. Last four only. |
| SC-26 | FR-14 | Bank statement whose new fields are invalid twice. | Extract. | Today's statement and transactions published, no new fields, review reason. |
| SC-27 | FR-09,19,29 | Grocery receipt: total 8.55, gift card 5.00, VISA ****4242 3.55. A card statement with a −3.55 line at the same merchant two days later, and an unrelated −8.55 line at the same merchant (another purchase, with no receipt). | Extract both, reconcile, read October's spending. Correct the gift card to 4.00. | The −3.55 line matches the receipt and replaces it, and the −8.55 line is not matched to it. October groceries spending is 12.10: the linked −3.55 line counted once, with the receipt's categories scaled to 3.55, plus the unrelated 8.55 line. The receipt's printed 8.55 is never counted as well. After the correction, amount paid is 4.55 with `override` provenance in its trace, The link is kept, and the receipt goes to review with a note that amount paid (4.55) no longer equals the linked charge (3.55). |

The scenarios are expanded in `test-contract.md`.

## Out of scope / product decisions requiring approval

**Decisions recorded (user answered "defaults ok", 2026-10-17):**
- **D1.** v1 receipt kinds are fuel, dining, grocery and general (the fallback). Invoices stay on the existing bill
  path.
- **D2.** The model proposes the receipt kind in the existing sorting step, with cited lines. The user can change it,
  which re-extracts the receipt with that kind's form.
- **D3.** Each receipt kind's fields are as listed in FR-04. Unprinted fields stay blank, never guessed.
- **D4.** New values are shown on the document page with their traces. Analytics are deferred to
  `docs/open-work.md`.
- **D5.** Existing records are unchanged until they are extracted again. There is no bulk re-processing, and
  user-reviewed records are never overwritten.
- **D6 (G1).** Pending receipt details on a reviewed record are applied with **Apply details**, saved as a correction.
  An unapplied proposal never expires.
- **D7 (G2).** A kind change is refused with 409 while a reading of the same document is in progress.
- **D8 (G3).** After the upgrade, existing receipts have kind null, not `general`.
- **D9 (G4).** The arithmetic checks are traceable figures (FR-19).
- **D10.** Pay stubs, bank statements and credit card statements get richer fields on their existing forms, with no
  sub-kinds.
- **D11.** New arithmetic checks are added (hours × rate, deposit splits, bank summary, card summary). A mismatch sends
  the record to Review, and each check is traced.
- **D12.** The new fields are shown, checked and traced only. What is counted doesn't change, except for gift cards
  (D15).
- **D13.** The feature is renamed from `receipt-kinds` to `document-forms`, keeping all IDs and decisions.
- **D14.** The user reports that the reasoning model fills a pay stub's this-period fields with year-to-date or yearly
  income. This is fixed by FR-22 – FR-24 on every path, and reproduced before it's fixed.
- **D15 (2026-10-17).** A gift card is a way of paying. The amount charged to a card, and the amount that counts
  against budgets and spending, is the printed total minus gift card deductions. The printed total stays on the
  record and is shown beside it (FR-09). This is the one deliberate exception to D12.
- **D16 (2026-10-18, from plan review E-1).** SC-24 uses fixture P-sept: fixture P with its period moved to 2026-09-01 –
  2026-09-14 and its pay date to 2026-09-19, so the paycheck falls in the September month being read. Fixture P keeps
  its June dates for SC-20 and SC-21. The SC-22 and SC-23 fixtures don't change.
- **D17 (2026-10-18, from plan review E-2).** SC-27's statement has an unrelated −8.55 line beside the −3.55 one, as the
  test contract says. That proves the receipt matches its amount paid and not its printed total. October groceries are
  12.10 (3.55 linked + 8.55 unrelated). The earlier wording "(not 8.55 or 12.10)" meant the receipt's printed total
  must not be counted on top of its charge. That rule is unchanged.
- These amendments were made in place before any implementation and need a new spec approval.

**Domain risk candidates (not yet in scope; accept or reject each):**
1. **Mixed-purpose receipts.** Examples: a gas-station convenience store run that is mostly snacks, fuel points on
   a grocery receipt, or a warehouse club with a gas pump.
   - *If unhandled:* the kind flips unpredictably between readings.
   - *Recommended:* the kind follows the main purchase. Fuel points are rewards, not fuel, and a fuel line on a
     grocery receipt is still kept as an item.
2. **Prepay or pre-authorisation at the pump.** Example: "PREPAY 50.00 / FUEL 32.15 / CHANGE 17.85", or a card hold
   larger than the sale.
   - *If unhandled:* 50.00 is counted, or the charge never reconciles.
   - *Recommended:* the counted total is the actual fuel sale, and the prepay or hold amount is a detail only.
3. **Two copies of one dining receipt** (the merchant copy with a handwritten tip and the customer copy) captured
   separately.
   - *If unhandled:* the meal counts twice.
   - *Recommended:* defer to the existing duplicate and near-match reconciliation, and note it in open work.
4. **Fuel price printed with ⁹⁄₁₀ (such as 3.45⁹), in litres, or with the unit not printed.**
   - *If unhandled:* the cross-check fails, or the price is misstored.
   - *Recommended:* accept the ⁹⁄₁₀ form as an exact decimal. A missing unit stays ambiguous and the FR-07 check is
     skipped.
5. **EBT/SNAP tender** marks government benefits, which are sensitive data.
   - *If unhandled:* it flows into family sharing and donations without notice.
   - *Recommended:* store the tender type only, exclude it from family routing notes, and make sure donation
     redaction covers it.
6. **Combined statements** (checking and savings on one statement, or several cardholders).
   - *If unhandled:* the summary checks compare one account's totals with another's.
   - *Recommended:* when several account summaries are printed, skip the summary check and add a review note, rather
     than splitting the statement in v1.
7. **Retro pay, corrections or negative adjustments on a pay stub** (this period larger than usual, or negative).
   - *If unhandled:* FR-22(b) can't fire wrongly, because year to date includes this period, but a negative current
     line may confuse the rules.
   - *Recommended:* compare magnitudes only for positive amounts, and send negative this-period earnings to review
     with a note.
**Open (recommended defaults):**
- **Eval thresholds** beyond the pay stub zero-wrong-column target. Default: report only, with no blocking gate until
  the first corpus run.
- **Field names and the storage shape** (columns, or JSON details like `invoice_json`). This is left to
  `plan-feature`.
