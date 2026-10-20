# Bill kinds: a rent form beside the general bill form
Feature: bill-kinds
Amends: specs/document-forms (approved, built 2026-10-18) and specs/paystub-columns (approved, built 2026-10-19); their
approvals and plans are unchanged by this file. IDs continue after paystub-columns (FR-39, SC-37, D20).

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

## Goal / users / scope / non-goals

**Goal.** A rent bill is read with a form made for rent. Its issued date and period are the ones it prints, its water
or other utility line is a line of its own, and the document page shows one clear amount instead of three equal ones.
Bills get kinds the way receipts did in document-forms: **rent** first, and **general**, which is today's bill form.

**Users.** The household user who scans or photographs a rent bill and reviews it on the document page. The user and
the people they asked (2026-10-19) found the page's "New charges", "Amount due" and "Counts as" rows confusing.

**In scope:**
- A bill kind (`rent` or `general`) proposed when a document is sorted, checked in code, and changeable on the document
  page.
- The rent form: its header fields, its line types and each line's printed period.
- Date rules for every bill kind: what Issued and Period mean, and that each date is printed where it is cited.
- The amount rows on a bill's document page, for every bill kind (invoices keep their own labels).
- An eval fixture for a rent bill.

**Non-goals:**
- Utility, phone, insurance or other bill kinds. They go in `docs/open-work.md` as next kinds.
- Lease documents (`housing_document`) and their payment terms (`TERMS`): unchanged.
- How a bill counts in the ledger, and its payment matching, apart from what a corrected issued date changes (FR-46)
  and how a rent bill's recurring bill is projected in budgets (FR-45a).
- Existing records: no bulk re-reading (document-forms D5). A bill changes when it is extracted again.
- Reading positions from the image or a second vision call.

## Existing behavior (verified paths, assumptions, unknowns)

**Verified** (`src/home_manager/documents/extraction.py` and others, working tree on 2026-10-19):
- Every bill uses one form: `HEADERS["bill"]` (`:61`) and the `LABELS["bill"]` instructions (`:120-127`). Those
  instructions explain provider, account, amount due, new charges and the invoice fields. They say nothing about
  `issue_date`, `period_start` or `period_end`, so the model gets only the bare names and the general date rule in
  `RULES` (`:508-509`).
- Dates are only parsed as ISO (`normalize`, `:1422-1425`). Unlike amounts (`amount_supported`) and names
  (`name_supported`), `problems_in` (`:1169-1211`) never checks that a date is printed in its cited line.
- `bill_lines` (`:1726-1809`) checks no date order (period start ≤ end, issued ≤ due). It works out `recurrence` from
  the period's length, and calls a bill monthly when no period was read (`:1773-1775`).
- `BillLine` (`:319-330`) has no period of its own. Its `line_kind` is one of service, usage, subscription, device,
  tax_fee, credit or other (`core/categories.py:32`; database CHECK in `migrations/067_bills_as_receipts.sql:19`).
- Receipt kinds exist: `RECEIPT_KINDS` (`:228`), `Classification.receipt_kind` with its cited evidence (`:237-239`),
  `receipt_kind()` falling back to general with a note (`:588-606`), and `KIND_FIELDS`/`KIND_LABELS` (`:450-460`).
  The stored `receipts.receipt_kind` CHECK allows only fuel, dining, grocery or general (`migrations/070_document_forms.sql:3`).
  Changing kind is refused for bills ("A bill has no receipt kind.", `app/manager.py:1520-1521`), and the document page
  shows the kind control only for non-bills (`static/document_v2.js:523`).
- `receipts.details_json` and `receipt_items.details_json` exist (070) and hold printed details for receipts and items.
- The document page shows a bill's fields from `RECORD_FIELDS.bill` (`static/receipt.js:40-41`): Record as, Provider,
  Issued, Due, Period, Categories, Billed, **New charges** (`total_minor`), **Amount due** (`amount_due_minor`). It then
  adds **Counts as** (the `split.receipt` figure) for every receipt, bills included (`document_v2.js:504`,
  `app/manager.py:2174`). With no past-due balance, all three are the same number.
- A bill's payment is looked for between its issue date (a month before the due date when none) and five days after the
  due date (`finance/reconcile.py:419-420`). **An issued date read as the due date shrinks that window to the due date
  onward, so rent paid a few days early isn't matched.**

**The user's rent bill** (described 2026-10-19; not inspected) prints, among other lines:
`Rent 10/01/2026 - 10/31/2026`, `Rent and Leasing Charges Due 10/01/2026`,
`Due Date ........................................................... 10/01/2026`,
`Amount Due......................................................... $<amount>`, and a water usage charge line. It prints
**no issue or statement date**. The transcription was correct; the dates on the record were not.

**Assumptions:**
- A1. The model, given no guidance, put a printed date into Issued (likely the due date from the heading line). It read
  Period from a line other than the rent line, or not at all. Not verified: the record was not inspected.
- A2. The rent line's amount is printed on the same line as its period, or on the next line.
- A3. The water line may print its own service or meter-read period, which is often earlier than the rent month.

- A budget's spent amount counts a verified bill by its lines' categories (`FinanceTools._category_totals`, as
  `docs/money.md` "Bills and their lines"), so a water line in `utilities` already counts toward a utilities budget.
  The projected amount adds each unpaid confirmed recurring bill's whole expected amount to **one** category
  (`finance/tools.py:829-836`, `bill["category"]`). A rent bill's recurring bill would therefore project its water
  under housing.

**Unknowns:**
- U1. How the user's water line prints. The user won't know until next month's bill (2026-10-19). The spec must not
  depend on it: the fixtures cover a water line with its own dates and usage, and a bare one (D26).
- U2. Whether the bill prints a currency code. Today a bill with no code uses the currency setting (`normalize`, `:1415`),
  unchanged here.
- U3. How often the live model picks the right kind and dates. Measured by the eval (FR-50), not asserted.

## Functional requirements

### Bill kinds (FR-40 – FR-42)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-40 | A document sorted as `bill` gets a bill kind from {`rent`, `general`}, with the lines that show it (a heading or line naming rent, a resident or lease charge). An invoice (`invoice_marker`/`invoice_number`) is always `general`. | With a stubbed model, the stored bill carries kind `rent` and its citations, which pass the exact-quote check. An invoice fixture answered `rent` is stored `general`. |
| FR-41 | An uncited, mis-cited or unlisted proposed kind means `general`, with a review note saying why (as document-forms FR-02). A null proposal is `general` with no note. | A stub returning an uncited `rent` gives `general` plus the note and `needs_review`. |
| FR-42 | The bill kind can be changed on the document page. That reads the bill again from its saved transcription with the new form, is refused while a reading of the same file is in progress, is kept across readings and can be undone, the same way a receipt kind change works (document-forms FR-11, FR-12, FR-18, D7). | `PATCH` the kind of a general bill to `rent`: 202 with a run, and the result is read with the rent form. A repeat with the same kind: 200 unchanged. While a reading runs: 409. |

### The rent form (FR-43 – FR-45)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-43 | **Rent header.** The rent form asks for the general bill fields plus `previous_balance` and `payments_received` (printed amounts carried from before and paid since), each with its own instructions. Unprinted fields stay missing, never guessed or calculated. | The schema sent for `rent` contains these fields and no receipt-kind fields (checked on the captured request). On the RENT fixture, previous balance and payments are missing, not 0. |
| FR-44 | **Rent lines.** Each charge line has a rent type: `rent`, `parking`, `pet`, `utility` (water, sewer, trash, gas, electric), `fee` (late, admin, amenity), `credit` (concession, discount) or `other`. It also has its printed period and, for a utility, its printed usage (such as 3,200 GAL), each printed in its cited line. A credit is money off, as today. The water line is its own line, never folded into rent. | RENT fixture: 2 lines. Rent 1,450.00, type rent, period 2026-10-01–2026-10-31. Water Usage 38.42, type utility, period 2026-08-15–2026-09-14, usage 3,200 GAL. A line period or usage not printed in its citation is dropped with a note. |
| FR-45 | **Category by type.** A rent line's category comes from its type: utility → `utilities`; rent, parking, pet and fee → `housing`. A model category that disagrees with the type is replaced, with no note (the type decides). The user can correct a line's category and type as today (`PATCH /api/receipts/{id}/lines/{position}`); the correction is kept across readings and wins. The water line stays on the rent bill: it is one of the bill's lines, never a separate record. | RENT fixture with categories answered null, and again with Water answered `housing`: Rent `housing`, Water `utilities` both times. The bill's own category is `housing` (most of its money). Once verified, October 2026 spending shows 1,450.00 housing and 38.42 utilities, and a utilities budget's spent includes 38.42. |
| FR-45a | **Budgets project by line.** An unpaid confirmed recurring bill proposed from a rent bill adds its expected amount to budgets' projected amount split by its latest bill's lines' categories, not to one category. The utility part is that bill's utility lines' total; the rest goes to housing. A recurring bill from any other bill is unchanged. | A verified RENT bill proposes its recurring bill; the user confirms it. For November 2026, with nothing paid yet, the housing budget's projected adds 1,450.00 and the utilities budget's adds 38.42. The trace (`budget.projected`) lists both steps under the payee. |
| FR-45b | **The water line is found whatever its layout.** A charge line naming water, sewer, trash, gas or electric is a utility line, whether or not it prints its own dates, usage or meter reads. What it doesn't print stays empty, with no note. | Fixture RENT-PLAIN (`Water $38.42`, no dates or usage): Water is type utility, category `utilities`, period and usage empty, no note; the bill can count automatically. |

### Dates on every bill (FR-46 – FR-48)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-46 | **Issued** is a printed statement, bill or invoice date only. It is never the due date or a date printed on a "Due" line or heading. When none is printed, Issued is missing: the page leaves the row out and no review reason is added. Payment matching then uses its existing fallback (a month before the due date). | RENT fixture answered with Issued 2026-10-01 citing `Rent and Leasing Charges Due 10/01/2026`: Issued is dropped with the note "Issued: the cited line is a due date". The rent payment posted 2026-09-28 is proposed as the bill's match. |
| FR-47 | **Period.** On a rent bill, the bill's period is the rent line's printed period. A utility line's period never becomes the bill's period. When the rent line prints a month without days ("Rent for October 2026"), the period is that whole month (code works it out, not the model). On a general bill, the period is the printed billing or service period, as instructed in `LABELS`. | RENT fixture: period 2026-10-01–2026-10-31 and Billed monthly, even when the model answers the water period for the bill. Fixture RENT-MONTH (`Rent for October 2026 1,450.00`): 2026-10-01–2026-10-31. |
| FR-48 | **Dates must be printed where they are cited**, on every bill kind and every bill line: the cited quote must hold the same date in a written form (10/01/2026, 10/1/2026, Oct 1, 2026, 2026-10-01). Otherwise the date is dropped with a note naming the field. The date must also be in order: a period whose start is after its end, or an issued date after the due date, drops the dates involved and sends the bill to review with a note. A dropped due date or bill period sends the bill to review. A dropped line date (a line's period) and a dropped Issued (FR-46) are a note only. | A due date answered 2026-10-02 citing `Due Date ... 10/01/2026` is dropped with the note and `needs_review`. A period answered 10/31–10/01 is dropped with the note and `needs_review`. A water line period not printed in its citation is dropped with the note, and the bill can still count automatically. |

### Checks, the page, versions and evals (FR-49 – FR-53)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-49 | **Rent checks.** The existing check stays: the lines add up to the new charges, or to the amount due when no new charges are printed. When previous balance, payments and new charges are all printed, previous balance − payments + new charges = amount due is one more cross-check; a mismatch is a review reason naming the four values. Each check is a traceable figure, like document-forms FR-19. | RENT fixture: lines 1,488.42 = amount due 1,488.42, so it can count automatically. RENT-CARRIED (previous 100.00, payments 100.00, new 1,488.42, due 1,488.42) passes both; with due 1,588.42 it needs review with the reason. |
| FR-50 | **The page reads like a receipt (every bill except invoices).** The bill's fields (provider, due, issued, period, billed) stay at the top, without any money rows. Below them, the charge lines (rent, water, …) are listed, credits as money off. When the bill prints a previous balance or payments, those rows follow the lines. Last comes one **Amount due** row, the bill's total, under a rule, so the rows above visibly add up to it. "New charges" and "Counts as" are no longer shown for bills; "Counts in" stays. When the rows don't add up to the amount due, the gap is shown as a row "Not accounted for" with the check's review reason (FR-49). The gap is the amount due minus the rows above it, so it is negative when the rows add up to more. Invoices keep Invoice total and Remaining balance. | RENT: rows Rent 1,450.00, Water Usage 38.42, then Amount due 1,488.42 last; no New charges or Counts as row. RENT-CARRIED (due 1,488.42): Rent, Water, Previous balance 100.00, Payment received −100.00, Amount due 1,488.42. With due 1,588.42: the same rows plus "Not accounted for 100.00" above Amount due. An invoice fixture's rows are unchanged. |
| FR-51 | **The page's lines.** Each line of a rent bill shows its type, its printed period and, for a utility, its usage, each with Find. The Amount due row has Find (its printed line) and Correct. Rent bills show the bill-kind control (FR-42). Records shows the rent line's period, as it shows a bill's period today. | Browser test on RENT: the Water Usage row shows "Utility", "Aug 15 – Sep 14, 2026" and "3,200 GAL"; Find highlights its line; Amount due is the last row of the section and Find highlights `Amount Due......$1,488.42`. |
| FR-52 | The extraction version changes, so readings made before this change aren't reused. Existing bills keep their values and have no bill kind until they are extracted again (document-forms D5, D8). Reviewed bills keep the user's corrections when read again (document-forms FR-12). | `EXTRACTION_VERSION` differs from `typed-extraction-v30-pre-tax-deductions`; a parse with only a v30 run gets a new run. An existing bill's row is unchanged after the upgrade. |
| FR-53 | **Eval and docs.** The `document_forms` eval task gains the RENT fixture and reports kind, Issued, Period, due date, line count, water line present with its type, and amount due. `docs/money.md` "Bills and their lines" describes bill kinds, the rent form and the date rules; `docs/documents.md` gets a "Bill kinds" section beside "Receipt kinds"; other bill kinds go in `docs/open-work.md`. | With stubbed correct answers, the RENT report row is all correct. Doc diff present. |

### Accepted domain risks (FR-54 – FR-58, user, 2026-10-19)

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-54 | **A resident ledger with several months.** A rent or payment line whose printed period ends before the bill's period starts (or, with no period, is dated before it) isn't one of this bill's lines. A utility line keeps its own earlier period and stays (A3, D24). It is left out with a note naming it, and the printed previous balance stands for it. With no previous balance printed, the bill needs review. | Fixture RENT-LEDGER adds `Rent 09/01/2026 - 09/30/2026 $1,450.00` and `Payment 09/01/2026 -$1,450.00` above October's lines, with `Previous Balance $0.00`: lines are October's rent and water only, two notes, and the bill can count automatically. Without the previous balance line: `needs_review`. |
| FR-55 | **Dates printed without a year** ("10/1 - 10/31"). The year comes from the due date when the month is the due month or one month before or after it, with a note "Year taken from the due date". Otherwise the date is dropped (FR-48). The due date itself must print its year. | RENT-NOYEAR (`Rent 10/1 - 10/31 $1,450.00`, due 10/01/2026): period 2026-10-01–2026-10-31 with the note. A water line `5/15 - 6/14` on the same bill: its period is dropped with FR-48's note. |
| FR-56 | **Prorated or move-in rent.** A rent bill is Billed monthly unless its rent lines' periods show another schedule. A rent line whose period is shorter than its calendar month gets a note "Prorated rent: N days". When the bill prints the rent's monthly rate, its proposed recurring bill expects that rate plus the bill's utility lines, split by FR-45a like a full-month bill. Otherwise it proposes no recurring bill, and the note adds "The recurring bill is proposed from the next full month." The next full-month bill proposes it as any bill does. | RENT-PRORATED (`Rent 10/15/2026 - 10/31/2026 $795.16`, Amount Due $833.58): Billed monthly, the note "Prorated rent: 17 days. The recurring bill is proposed from the next full month.", and once verified no recurring bill is proposed. |
| FR-57 | **Rent shared in the household.** A rent bill shares by line like any bill ([family](../../docs/family.md) "Sharing a bill by line"); nothing new. | Regression: a RENT bill shared by line between two members counts only each payer's part, as the phone bill test does today. |
| FR-58 | **A fee printed as a warning** ("A late fee of $75.00 applies after 10/05/2026"). The rent form's instructions say only charges on this bill are lines, never warnings, terms or fees that may apply later. If one is read as a line anyway, the lines-add-up check (FR-49) catches it and the bill needs review. | RENT-WARNING adds that sentence. Answered correctly: 2 lines, no note. Answered with a 75.00 line: "Not accounted for" (FR-50), the FR-49 reason, `needs_review`. |

**Superseded:** FR-46–FR-48 replace "Issued, Period: no guidance, no citation check" for every bill. FR-50 replaces
the New charges / Amount due / Counts as rows for non-invoice bills. FR-45a replaces one-category projection for
recurring bills proposed from rent bills. Payment matching (`reconcile.py`) and counting on the due date are unchanged.

## Invariants, privacy, security and data retention
- **Nothing is invented.** Every kept value is printed in its cited line. Code works out only: a month's first and last
  day (FR-47), the category from a line's type when the model gave none (FR-45), and the carried amount shown on the page
  (FR-50). Each is shown as worked out, not printed.
- **What counts doesn't change** for a correctly read bill: the new charges, by line category, on the due date, until
  its payment replaces it (`docs/money.md` "Bills and their lines").
- **Nothing leaves the machine.** No new model call: the kind is proposed in the existing sorting step, and the rent form
  replaces the general form's call.
- **Identifiers** follow FR-30: an account or resident number keeps only its last four digits, and citations stay masked.
  No tenant name, unit or address is stored as a new field.
- **Development data.** Synthetic fixtures only. Never read P:\Finances or P:\EvalCorpus; the user runs the eval on
  their own bill and shares only `summary.json` (docs/evals.md).
- **Schema.** Storing the bill kind needs a migration (the current CHECK allows only receipt kinds). It follows
  `docs/development.md` "Adding a migration" (runner FK-off rebuild) with nullable columns and no backfill.

## Errors, recovery, duplicates, restart behavior
- **Rent form fails validation** after its one correction → today's rule: identifying fields drop with a note; if the
  form still fails, the bill is read with the general form and a note "Read as a general bill: …". It is never lost.
- **Several rent lines with different periods** (a prorated move-in plus a full month) → the bill's period is the
  earliest start to the latest end of its `rent` lines, and Billed comes from the bill kind: rent is monthly unless the
  lines' periods say otherwise.
- **No rent line** on a bill proposed as rent → it is read as rent with no period from lines. FR-47's general rule
  applies, plus a note "No rent line was read".
- **A kind change while a reading runs** → 409 (FR-42). **Restart** mid-reading → the run resumes or fails as today; the
  stored kind changes only with a finished reading.

## Nondeterministic outputs and how they are verified
- Model answers are fixed stub replies keyed by schema name (`tests/model_server.py` `by_schema`). No test asserts live
  output.
- Live behavior is measured by the `document_forms` eval task on the synthetic RENT fixtures (FR-53), and by the user
  on their own bill.

## Scenarios

Fixture RENT (synthetic, amounts printed with $ and no currency code, as the user's bill):
`SYNTH PROPERTY MANAGEMENT`, `Resident Account ****4821`, `Rent and Leasing Charges Due 10/01/2026`,
`Rent 10/01/2026 - 10/31/2026 $1,450.00`, `Water Usage 08/15/2026 - 09/14/2026 3,200 GAL $38.42`,
`Due Date ........................................................... 10/01/2026`,
`Amount Due......................................................... $1,488.42`.
RENT-MONTH replaces the rent line with `Rent for October 2026 $1,450.00`. RENT-PLAIN replaces the water line with
`Water $38.42`. RENT-CARRIED adds
`Previous Balance $100.00`, `Payment Received 09/03/2026 -$100.00` and `New Charges $1,488.42`. RENT-PRORATED replaces
the rent line with `Rent 10/15/2026 - 10/31/2026 $795.16` and the amount due with `$833.58`.

| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-38 | FR-40, FR-43, FR-44, FR-47, FR-49 | RENT; stub answers kind `rent` (citing the heading) and every value correctly. | Extract. | Bill kind `rent`; due 2026-10-01; Issued null; period 2026-10-01–2026-10-31; monthly; 2 lines (rent 145000, utility 3842 with period and 3,200 GAL); total 148842 = amount due; cross_checks ≥ 1; can count automatically. |
| SC-39 | FR-46, FR-48 | RENT; Issued answered 2026-10-01 citing the "Due" heading. | Extract; then a statement line −1,488.42 "SYNTH PROPERTY MGMT" posted 2026-09-28 is reconciled. | Issued null with the note; the line is proposed as the bill's payment (window starts 2026-09-01). |
| SC-40 | FR-47 | RENT; the bill's period answered as the water period 2026-08-15–2026-09-14. | Extract. | Period 2026-10-01–2026-10-31 from the rent line; Billed monthly. |
| SC-41 | FR-47 | RENT-MONTH, correct answers. | Extract. | Period 2026-10-01–2026-10-31, shown as worked out from "Rent for October 2026". |
| SC-42 | FR-48 | RENT; due answered 2026-10-02; in a second run, period answered 10/31 to 10/01. | Extract each. | First: due null with the note, `needs_review`. Second: period null with the order note, `needs_review`. |
| SC-43 | FR-45 | RENT; line categories answered null; a utilities budget of 100.00 for October 2026. | Extract; verify. | Rent `housing`, Water `utilities`; October 2026 spending: housing 1,450.00, utilities 38.42; the utilities budget's spent is 38.42. |
| SC-43a | FR-45a | SC-43 done; its proposed recurring bill confirmed; housing and utilities budgets for November 2026. | Get budgets for November 2026 before any payment. | Housing projected includes 1,450.00 and utilities projected includes 38.42, each traced to the payee. |
| SC-43b | FR-45b | RENT-PLAIN, correct answers. | Extract. | Water: utility, `utilities`, no period or usage, no note; can count automatically. |
| SC-44 | FR-41 | RENT; kind `rent` with no citation. | Extract. | Kind `general` with the note; `needs_review`. |
| SC-45 | FR-42 | A RENT bill read as `general`. | `PATCH` kind `rent`; repeat; `PATCH` again while a reading runs. | 202 with a run, then the rent form result; 200 unchanged; 409. Undo puts `general` back. |
| SC-46 | FR-49, FR-50 | RENT-CARRIED: (a) due 1,488.42; (b) due 1,588.42. | Extract; open the document page. | (a) both checks pass; rows Rent, Water, Previous balance, Payment received, then Amount due 1,488.42 last. (b) needs review with the four values; the same rows plus "Not accounted for 100.00", then Amount due 1,588.42. No New charges or Counts as. |
| SC-46a | FR-54 | RENT-LEDGER, with and without the previous balance line. | Extract each. | With: October's 2 lines, a note for each September line, can count automatically. Without: `needs_review`. |
| SC-46b | FR-55 | RENT-NOYEAR plus a water line `5/15 - 6/14`. | Extract. | Rent period 2026-10-01–2026-10-31 with the year note; water period dropped with FR-48's note. |
| SC-46c | FR-56 | RENT-PRORATED. | Extract; verify. | Billed monthly; the prorated note; no recurring bill is proposed. |
| SC-46d | FR-57 | A verified RENT bill in a family library. | Share by line between two members; reconcile the payer's payment. | Each payer's part counts, as `test_a_phone_bill_is_shared_by_line_and_the_payers_charge_counts_only_their_part`. |
| SC-46e | FR-58, FR-49, FR-50 | RENT-WARNING, answered (a) correctly and (b) with a 75.00 late fee line. | Extract each. | (a) 2 lines, no note. (b) "Not accounted for −75.00", the FR-49 reason, `needs_review`. |
| SC-47 | FR-50 | An existing invoice fixture (`tests/test_invoice_ingestion.py`). | Open its document page. | Invoice total and Remaining balance as today. |
| SC-48 | FR-51 | SC-38 done. | Open the document page in the browser test. | Water Usage row: Utility, its period, 3,200 GAL, Find highlights its line; the kind control shows Rent. |
| SC-49 | FR-52 | A bill read under v30. | Upgrade; Extract again. | Before Extract again: row unchanged, kind null. After: new run, kind set. A reviewed bill keeps its corrections. |
| SC-50 | regression | The existing bill suites (`test_bills_ledger`, `test_recurring_bills`, `test_invoice_ingestion`, `test_bills_v2_browser`). | Run. | Pass. A phone bill fixture is read `general`, with lines and line holders unchanged. |
| SC-51 | FR-53 | RENT with stubbed correct answers. | Run `document_forms`; review `git diff docs/`. | Report row all correct; docs updated as FR-53 says. |

## Out of scope / product decisions requiring approval

**Decisions taken in this spec (recommended defaults; approving the spec accepts them):**
- **D21.** Bill kinds work like receipt kinds: proposed when sorting, checked in code, changeable on the page. v1 kinds
  are `rent` and `general`. They are not a new document type, so counting, matching, Records and family sharing don't
  change.
- **D22 (user, 2026-10-19).** A bill's page reads like a receipt: its charge lines (rent, water), then any printed previous
  balance and payments, then one Amount due row as the total, so the rows visibly add up to it (FR-50). New charges
  and Counts as are not shown for bills.
- **D23.** Issued is only a printed statement date. A rent bill usually prints none, and that's fine: it is not a
  required field.
- **D24.** The rent line's period is the bill's period; a utility line keeps its own period.
- **D25.** Category comes from a line's type: utilities for a utility line, housing for the rest. The user's correction
  wins.
- **D26 (user, 2026-10-19).** The water line stays part of the rent bill, but it counts toward the utilities budget,
  both in spent and in projected (FR-45, FR-45a). The user won't see how it prints until next month's bill, so nothing
  depends on its layout (FR-45b). After that bill arrives, the user runs the eval on it and Extract again, and a layout
  the fixtures miss becomes a new fixture.

**Domain risk candidates:** the user accepted all five recommended defaults on 2026-10-19. They are FR-54–FR-58 and
SC-46a–SC-46e. The list below is kept as asked.
1. **A resident ledger with several months** (a portal printout listing past charges and payments).
   - *If unhandled:* past months' lines are counted as this bill's charges.
   - *Recommended:* lines whose period ends before the bill's period are left out with a note, and the printed previous
     balance stands for them.
2. **Dates printed without a year** ("10/1 – 10/31").
   - *If unhandled:* FR-48 drops them.
   - *Recommended:* take the year from the due date when the month is the due month or next to it, with a note.
3. **Prorated or move-in rent** (a 17-day period).
   - *If unhandled:* Billed comes out as weekly or nothing from the period length.
   - *Recommended:* the error rule above (rent is monthly unless the lines' periods say otherwise), plus a note on
     prorated lines.
4. **Rent shared between household members** (roommates or a family split).
   - *If unhandled:* sharing by line works as for phone bills, since rent lines are bill lines.
   - *Recommended:* accept as is; no change.
5. **A late fee printed but not yet charged** ("A late fee of $75.00 applies after 10/05").
   - *If unhandled:* the model may list it as a charge, so the lines no longer add up.
   - *Recommended:* the instructions say only charged lines are lines; the line-sum check catches the rest.
