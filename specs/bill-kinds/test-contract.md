# Test contract: bill-kinds
Spec sha256: the bundle hash (spec.md + this file) from `gate.py hash --feature bill-kinds --stage spec`. It isn't copied
here, because writing it into this file would change it.

## Conventions for every scenario

- **Environment:** a `tmp_path` library and database, built with the existing helpers: `transcribe` / `extract` /
  `value` / `cite` / `MISSING` in `tests/test_extraction.py`, and `open_books` / `add` / `Reconciler` as in
  `tests/test_bills_ledger.py`. Synthetic transcriptions only. Never `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or
  `P:\EvalCorpus`.
- **Model double:** the `local_model` fixture (`tests/conftest.py`), a loopback server that records each request.
  Answers are keyed **by `json_schema.name`** (`by_schema` in `tests/model_server.py`), so the contract doesn't fix the
  order of calls. Request assertions read `local_model["requests"]`. "Correct answers" means the classification answers
  `bill` with kind `rent` citing line 3 (`Rent and Leasing Charges Due 10/01/2026`), and the rent form answers every
  printed value with an exact citation, Issued missing, the bill's period the rent line's, and line categories as
  FR-45 types them.
- **Clock:** no test reads today's date. Budgets pass `as_of`; reconcile windows come from the bill's dates.
- **No live model output** is asserted. Accuracy belongs to the eval (SC-51), which also runs on stubs in CI.
- **Shared checks** (wherever a bill is published):
  - **C-cite:** every stored non-null value, dates and line periods and usage included, has a locator whose quote is an
    exact substring of its line.
  - **C-date:** every stored date is printed in its cited quote in one of the forms FR-48 lists, except dates code works
    out (FR-47 whole month, FR-55 year), which carry a note saying so.
  - **C-money:** money columns are SQLite `integer`. Usage is stored as its printed text (`3,200 GAL`), never a float.
  - **C-ids:** nothing stored outside `parse_runs` holds more than the last four digits of the resident account
    (`4821`). No tenant name, unit or address field exists on the record.
  - **C-calls:** the number of model requests for a rent bill equals that of a general bill on the same lines (no new
    call, spec "Invariants"), and no request contains `image_url`.
- **Test files** (new): `tests/test_bill_kinds.py`, `tests/test_bill_kinds_browser.py`. Existing files are extended
  where named.
- **Cleanup:** `tmp_path` is removed by pytest. No other files are written.

### Fixtures (synthetic; numbered lines are the transcription)

**RENT** (spec "Scenarios"):
```
1 SYNTH PROPERTY MANAGEMENT
2 Resident Account ****4821
3 Rent and Leasing Charges Due 10/01/2026
4 Rent 10/01/2026 - 10/31/2026 $1,450.00
5 Water Usage 08/15/2026 - 09/14/2026 3,200 GAL $38.42
6 Due Date ........................................................... 10/01/2026
7 Amount Due......................................................... $1,488.42
```
Variants (each changes only the lines named):
- **RENT-MONTH:** line 4 = `Rent for October 2026 $1,450.00`.
- **RENT-PLAIN:** line 5 = `Water $38.42`.
- **RENT-CARRIED:** adds `Previous Balance $100.00`, `Payment Received 09/03/2026 -$100.00` and
  `New Charges $1,488.42` before line 6. (a) line 7 as RENT; (b) line 7 = `Amount Due ... $1,588.42`.
- **RENT-LEDGER:** adds `Rent 09/01/2026 - 09/30/2026 $1,450.00` and `Payment 09/01/2026 -$1,450.00` above line 4, and
  `Previous Balance $0.00` after line 5. **RENT-LEDGER-NOPREV** leaves out `Previous Balance $0.00`.
- **RENT-NOYEAR:** line 4 = `Rent 10/1 - 10/31 $1,450.00`, line 5 = `Water Usage 5/15 - 6/14 3,200 GAL $38.42`.
- **RENT-PRORATED:** line 4 = `Rent 10/15/2026 - 10/31/2026 $795.16`, line 7 = `Amount Due ... $833.58`.
  **RENT-PRORATED-RATE** adds `Monthly Rent $1,450.00` after line 4.
- **RENT-WARNING:** adds `A late fee of $75.00 applies after 10/05/2026` after line 7.
- **INVOICE:** the existing fixtures in `tests/test_invoice_ingestion.py`, unchanged.
- **PHONE:** `PHONE_TEXT` in `tests/test_bills_ledger.py`, unchanged.

Arithmetic (worked from the spec, not from running code):
- 1,450.00 + 38.42 = 1,488.42.
- RENT-CARRIED: 100.00 − 100.00 + 1,488.42 = 1,488.42. With due 1,588.42 the gap is 1,588.42 − 1,488.42 = 100.00.
- RENT-PRORATED: 10/15–10/31 is 17 days. 1,450.00 × 17 / 31 = 795.16. 795.16 + 38.42 = 833.58.
- RENT-WARNING (b): 1,450.00 + 38.42 + 75.00 = 1,563.42. Due 1,488.42 − 1,563.42 = −75.00.
- Payment window with no Issued: due 2026-10-01 less one month = 2026-09-01, to due + 5 days = 2026-10-06
  (`reconcile.py` `bill_payment`). 2026-09-28 is inside it. With Issued wrongly 2026-10-01 it is outside.
- Next due of a monthly bill due 2026-10-01 is 2026-11-01, inside November 2026.

---

## SC-38: a rent bill is read with the rent form
Requirement IDs: FR-40, FR-43, FR-44, FR-47, FR-49
Nondeterministic components: model stubbed with correct answers (classification, rent form, lines).
Initial state: empty library, RENT transcription.
Actions/checkpoints:
1. Extract → run `succeeded`.
2. Requests → exactly one bill-form request, and its schema is the rent schema: it has `previous_balance` and
   `payments_received` with their own instructions, the rent line types, a line period and a line usage. It has no
   fuel, dining or grocery field. No general-bill request is made. C-calls holds.
3. Record → `document_kind = bill`, bill kind `rent`, with its kind citation on line 3 passing C-cite.
Expected final state:
- Database: one bill. Due 2026-10-01. Issued null. Period 2026-10-01 – 2026-10-31. Recurrence `monthly`. Previous
  balance and payments **null** (not 0). Two lines in printed order: `Rent` 145000, type `rent`, period
  2026-10-01 – 2026-10-31; `Water Usage` 3842, type `utility`, period 2026-08-15 – 2026-09-14, usage `3,200 GAL`.
  `total_minor = amount_due_minor = 148842`. Cross-checks ≥ 1. `verified`, `review_source = automatic`. No issues.
  Account last four `4821`. C-cite, C-date, C-money, C-ids hold.
- The lines-add-up check is a traceable figure: its trace sums 1,450.00 and 38.42 to 1,488.42 and compares it with
  Amount due 1,488.42, `reconciles` true.
Failure variants:
- 38a: FR-44 citation guard. The water line answered with period 2026-08-15 – 2026-09-14 citing line 4 → the line
  period is dropped with a note naming it. The same for usage `3,200 GAL` cited on line 4.
- 38b: the water line answered folded into rent (one line, 1,488.42, citing line 4) → rejected by the amount-printed
  check, and after its one correction the bill needs review. It is never stored as one rent line of 1,488.42.
- 38c (spec "Errors"): the rent form fails validation twice → the bill is read with the general form, with the note
  "Read as a general bill: …". The bill is published, never lost.
- 38d (spec "Errors"): no rent line read on a bill proposed as rent → kind `rent`, no period from lines, and the note
  "No rent line was read".
Evidence: `pytest tests/test_bill_kinds.py -k sc38`

## SC-39: Issued is never a due date, and early rent is matched
Requirement IDs: FR-46, FR-48
Nondeterministic components: RENT correct answers, except Issued = 2026-10-01 citing line 3.
Initial state: empty library, RENT; a checking account.
Actions/checkpoints:
1. Extract → Issued null, with the note "Issued: the cited line is a due date". The page leaves out the Issued row.
   No review reason comes from the missing Issued; status `verified`.
2. Add a statement line 2026-09-28 `SYNTH PROPERTY MGMT` −1,488.42, then reconcile → the line is linked (proposed) as
   the bill's payment.
Expected final state: one bill, one proposed link to the 2026-09-28 line. The ledger health check passes.
Failure variants:
- 39a (control, shows the defect): the same bill published directly with Issued 2026-10-01 → the line is **not**
  matched. It proves the window, not the name match, decides.
- 39b: Issued answered 2026-10-01 citing line 6 (`Due Date ... 10/01/2026`) → dropped with the same note.
- 39c: a general bill printing `Statement Date 09/12/2026` and answered with it → Issued 2026-09-12 is kept.
Evidence: `pytest tests/test_bill_kinds.py -k sc39`

## SC-40: a water period never becomes the bill's period
Requirement IDs: FR-47
Initial state: RENT; the bill's period answered 2026-08-15 – 2026-09-14 citing line 5; the lines answered correctly.
Expected final state: period 2026-10-01 – 2026-10-31 (from the rent line), recurrence `monthly`. The water line keeps
2026-08-15 – 2026-09-14.
Evidence: `pytest tests/test_bill_kinds.py -k sc40`

## SC-41: a month without days becomes the whole month
Requirement IDs: FR-47
Initial state: RENT-MONTH, correct answers (the rent line's period answered as `October 2026` citing line 4).
Expected final state: rent line period and bill period 2026-10-01 – 2026-10-31, marked as worked out from
"Rent for October 2026", not printed. Monthly. `verified`.
Failure variants:
- 41a: the model answers 2026-10-01 – 2026-10-31 itself for that line → the stored period is the same, and the dates
  are still marked worked out (the days aren't printed, so C-date allows them only as worked out).
Evidence: `pytest tests/test_bill_kinds.py -k sc41`

## SC-42: dates must be printed where cited, and in order
Requirement IDs: FR-48
Initial state: RENT. Two separate extractions in separate libraries.
Expected final state:
- (a) Due answered 2026-10-02 citing line 6 → due null, a note naming Due, `needs_review`.
- (b) The bill's period answered 2026-10-31 – 2026-10-01 citing line 4 → period null with the order note,
  `needs_review`.
Failure variants:
- 42c: Issued 2026-10-05 printed and cited correctly, due 2026-10-01 → Issued and due dropped with the order note,
  `needs_review`.
- 42d: date forms. The same date cited as `10/1/2026`, `Oct 1, 2026` and `2026-10-01` in the line is kept each time.
- 42e: a PHONE bill (general) with its bill date answered 2026-09-06 citing `Bill date 2026-09-05` → dropped with the
  note (FR-48 is for every bill kind).
Evidence: `pytest tests/test_bill_kinds.py -k sc42`

## SC-43: each line's category comes from its type, and counts there
Requirement IDs: FR-45
Initial state: RENT; line categories answered null. A utilities budget of 100.00 USD.
Actions/checkpoints:
1. Extract → Rent `housing`, Water `utilities`. The bill's category `housing`. No note about categories.
2. Verify the bill (if not already verified).
3. October 2026 spending by category → housing 1,450.00, utilities 38.42.
4. `get_budgets` for 2026-10 (`as_of` 2026-10-31) → the utilities budget's spent is 38.42.
5. Correct the Water line's category to `housing` (`PUT /api/receipts/{id}/items/{position}/category`) and its type to
   `other` (`PATCH /api/receipts/{id}/lines/{position}`), then read again with Water answered `utilities`, type
   `utility` → the user's `housing` and `other` stay.
Expected final state: one bill with two lines. After step 5, October utilities 0, housing 1,488.42. The ledger health
check passes.
Failure variants:
- 43a: Water answered `housing` → stored `utilities`, no note.
- 43b: Rent answered `utilities` → stored `housing`, no note.
Evidence: `pytest tests/test_bill_kinds.py -k sc43`

## SC-43a: the projected budget splits a rent bill's recurring bill by line
Requirement IDs: FR-45a
Initial state: SC-43 through step 4 (no step 5). Its proposed recurring bill. Housing and utilities budgets for USD.
Actions/checkpoints:
1. Recurring bills → one proposed for SYNTH PROPERTY MANAGEMENT, monthly, expected 1,488.42, next due 2026-11-01.
2. Confirm it (`POST /api/finance/recurring/{id}/review`, status confirmed).
3. `get_budgets` for 2026-11, `as_of` 2026-11-01, nothing paid → housing projected 1,450.00, utilities projected 38.42.
   Neither holds 1,488.42, and no `bills` row picks it up.
4. Trace `budget.projected` for each → the step names the payee and its amount (1,450.00 and 38.42).
Expected final state: one confirmed recurring bill; the budgets' amounts unchanged.
Failure variants:
- 43a-1 (regression): a recurring bill confirmed from a PHONE bill → its whole expected amount projects to its one
  category, as today (`test_recurring_bills.py::test_confirmed_bills_are_forecast_on_schedule_and_budgeted`).
Evidence: `pytest tests/test_bill_kinds.py -k sc43a`

## SC-43b: a bare water line is still a utility line
Requirement IDs: FR-45b
Initial state: RENT-PLAIN, correct answers (Water period and usage missing).
Expected final state: Water: type `utility`, category `utilities`, period and usage null, **no** note. `verified`,
`review_source = automatic`.
Failure variants:
- 43b-1: the model answers the bare line as type `other` → stored `utility` (the line names water). The same for
  `Sewer`, `Trash`, `Gas`, `Electric` lines.
Evidence: `pytest tests/test_bill_kinds.py -k sc43b`

## SC-44: an invalid kind proposal falls back to general
Requirement IDs: FR-40, FR-41
Expected final state:
- RENT with kind `rent` and no citation → kind `general`, a note saying why, `needs_review`. The general-form request
  is made, no rent-form request.
Failure variants:
- 44a: kind `rent` citing line 3 with a quote not in it → the same.
- 44b: kind `utility` (unlisted) → the same.
- 44c: kind null → `general`, no note, and the review status comes only from the rest of the bill.
- 44d: INVOICE answered `rent` with a valid citation → stored `general`.
Evidence: `pytest tests/test_bill_kinds.py -k sc44`

## Journey (SC-45): changing a bill's kind
Requirement IDs: FR-42
Environment: one library across all checkpoints (a stateful journey, so one test function).
Initial state: RENT extracted with kind answered `general` (so read with the general form).
Actions/checkpoints:
1. `PATCH /api/receipts/{id}/kind` `{"kind": "rent"}` → 202 with a run id. Exactly one rent-form request. The run
   `succeeded`.
2. Record → kind `rent`, two typed lines as SC-38. History shows "Bill kind: general → rent" with Undo.
3. `PATCH` `rent` again → 200 unchanged: no request, no correction row.
4. Read again (the stub says `general`) → kind stays `rent`.
5. Hold a reading of the same file (the stub waits on an event) → `PATCH` `general` gives 409, no correction row, no
   request. Release → the run succeeds.
6. Undo the kind correction → `general`.
7. Verify, correct the Amount due, then `PATCH` `rent` → the correction stays and the record stays `verified`; the rent
   details wait as pending, as document-forms D7.
8. Restart (a new manager on the same database) → still pending.
Expected final state: one bill row. Corrections hold the kind changes, the undo and the amount. The ledger health check
passes.
Failure/retry/restart variants:
- J-a: `PATCH` `{"kind": "fuel"}` on a bill → 4xx, nothing changes. `{"kind": "rent"}` on a receipt → 4xx.
- J-b: the reading started by step 1 is cancelled → the state is exactly as before step 1; a retry succeeds.
- J-c: restart while it's `running` → interrupted and retryable; the stored kind is unchanged (spec "Errors").
- J-d: only a different document is being read → not refused.
Evidence: `pytest tests/test_bill_kinds.py -k journey`

## SC-46: carried amounts, the cross-check and the page rows
Requirement IDs: FR-49, FR-50
Initial state: RENT-CARRIED (a) and (b), correct answers, in separate libraries.
Actions/checkpoints:
1. (a) Extract → previous balance 10000, payments 10000. Both checks pass, cross-checks ≥ 2, `verified`.
2. (a) Open the document page → rows in order: Rent 1,450.00; Water Usage 38.42; Previous balance 100.00; Payment
   received −100.00; a rule; Amount due 1,488.42. No New charges, Counts as or Not accounted for row. Counts in is
   shown.
3. (b) Extract → `needs_review` with a reason naming 100.00, 100.00, 1,488.42 and 1,588.42.
4. (b) Open the page → the same rows, then "Not accounted for 100.00" with the reason, then Amount due 1,588.42 last.
Expected final state: two bills; (a) verified, (b) in Review. The cross-check's trace lists the four values.
Evidence: `pytest tests/test_bill_kinds.py -k sc46`, `pytest tests/test_bill_kinds_browser.py -k sc46`

## SC-46a: a resident ledger counts only this bill's lines
Requirement IDs: FR-54
Expected final state:
- RENT-LEDGER → lines: October rent 145000 and water 3842 only. The water line stays, with its own period
  2026-08-15 – 2026-09-14, although that period ends before the bill's. A note naming each September line (the rent
  and the payment). `verified`.
- RENT-LEDGER-NOPREV → the same two lines and notes, `needs_review`.
Evidence: `pytest tests/test_bill_kinds.py -k sc46a`

## SC-46b: dates without a year
Requirement IDs: FR-55, FR-48
Initial state: RENT-NOYEAR, the stub answering the rent period 2026-10-01 – 2026-10-31 and the water period
2026-05-15 – 2026-06-14, both citing their lines.
Expected final state: rent line and bill period 2026-10-01 – 2026-10-31, with the note "Year taken from the due date".
Water period null with FR-48's note. A dropped line date is a note only, so the bill is `verified`,
`review_source = automatic`.
Failure variants:
- 46b-1: a rent line `Rent 11/1 - 11/30` with due 10/01/2026 → 2026-11-01 – 2026-11-30 with the note (next month).
- 46b-2: a due date printed `Due Date 10/01` (no year) → due dropped with FR-48's note; no year is taken for the lines.
Evidence: `pytest tests/test_bill_kinds.py -k sc46b`

## SC-46c: prorated rent
Requirement IDs: FR-56
Initial state: RENT-PRORATED, correct answers.
Actions/checkpoints:
1. Extract → recurrence `monthly`, period 2026-10-15 – 2026-10-31, the note "Prorated rent: 17 days. The recurring
   bill is proposed from the next full month." The lines add up to 833.58, so the bill is `verified`.
2. Recurring bills → none proposed for SYNTH PROPERTY MANAGEMENT.
3. Extract and verify RENT-NOV (RENT with line 3 `... Due 11/01/2026`, line 4 `Rent 11/01/2026 - 11/30/2026 $1,450.00`
   and line 6 `Due Date ... 11/01/2026`) → one recurring bill is proposed, monthly, expecting 1,488.42.
Failure variants:
- 46c-2: RENT-PRORATED-RATE → the note "Prorated rent: 17 days" alone, and a recurring bill is proposed, monthly,
  expecting 1,450.00 + 38.42 = 1,488.42. Confirmed, it projects 1,450.00 to housing and 38.42 to utilities for
  November 2026, as in SC-43a.
- 46c-1: a prorated line plus a full November line → period 2026-10-15 – 2026-11-30, monthly (spec "Errors").
Evidence: `pytest tests/test_bill_kinds.py -k sc46c`

## SC-46d: rent shared by line (regression)
Requirement IDs: FR-57
Initial state: a verified RENT bill in a family library, published through `publish_bill`.
Actions/checkpoints: share by line, Rent to one member and Water to another; reconcile the first payer's payment.
Expected final state: each payer's part counts as in
`test_bills_ledger.py::test_a_phone_bill_is_shared_by_line_and_the_payers_charge_counts_only_their_part`.
Evidence: `pytest tests/test_bill_kinds.py -k sc46d`

## SC-46e: a printed warning is not a charge
Requirement IDs: FR-58, FR-49, FR-50
Expected final state:
- (a) Correct answers → 2 lines, no note, `verified`. The rent-form request's instructions say warnings and fees that
  may apply later are not lines.
- (b) An extra line `Late fee` 75.00 citing the warning → `needs_review` with the FR-49 reason; the page shows
  "Not accounted for −75.00" (amount due minus the rows) above Amount due 1,488.42.
Evidence: `pytest tests/test_bill_kinds.py -k sc46e`, `pytest tests/test_bill_kinds_browser.py -k sc46e`

## SC-47: invoices keep their rows (regression)
Requirement IDs: FR-40, FR-50
Expected final state: INVOICE → bill kind `general`. The document page shows Invoice total and Remaining balance as
today, with no Not accounted for row. The existing invoice tests pass unchanged.
Evidence: `pytest tests/test_invoice_ingestion.py`, `pytest tests/test_document_v2_browser.py -k invoice`

## SC-48: the document page for a rent bill
Requirement IDs: FR-42 (UI path), FR-50, FR-51
Environment: the browser fixture pattern of `tests/test_document_v2_browser.py`, seeded with the SC-38 bill.
Actions/checkpoints (user terms):
1. Open the bill's document page → the top fields show Provider, Due, Period and Billed with no money rows. The Issued
   row is absent.
2. The Bill kind control shows Rent.
3. The Water Usage row shows "Utility", "Aug 15 – Sep 14, 2026" and "3,200 GAL". Find on it highlights line 5.
4. The Rent row shows its type and "Oct 1 – Oct 31, 2026"; Find highlights line 4.
5. Amount due 1,488.42 is the last row of the section. Find highlights `Amount Due......$1,488.42`; Correct opens the
   correction form.
6. No New charges or Counts as row anywhere on the page.
7. Change the kind to General and save → after one stubbed reading the page shows General. Reload → still General.
8. Records → the bill's row shows the period Oct 1 – Oct 31, 2026.
Expected final state: no console errors and no CSP violations. The 360 px width has no horizontal scroll.
Evidence: `pytest tests/test_bill_kinds_browser.py -k sc48`, synthetic screenshots through `scripts/ui_shots.py`

## SC-49: the version changes and old bills stay as they are
Requirement IDs: FR-52
Initial state: a database at the last pre-feature `user_version` with a v30-read PHONE bill (verified) and a
v30-read rent-like bill (in Review, with a user line-type correction).
Actions/checkpoints:
1. Upgrade → every money, line, date, category and review column is equal before and after. Bill kind null on both.
   0 extraction runs and 0 queued jobs. The ledger health check passes.
2. `EXTRACTION_VERSION != "typed-extraction-v30-pre-tax-deductions"`. A parse with only a v30 run gets a new run
   (`reused: False`).
3. Extract again the rent-like bill → kind set; the user's line-type correction stays.
Evidence: `pytest tests/test_migrations.py -k bill_kinds`, `pytest tests/test_bill_kinds.py -k version`

## SC-50: existing bill suites (regression)
Expected: pass unchanged. A PHONE bill is read with kind `general`; its lines, holders, categories and splits are as in
`test_a_bill_is_read_by_line_and_counts_its_new_charges`.
Evidence: `pytest tests/test_bills_ledger.py tests/test_recurring_bills.py tests/test_invoice_ingestion.py
tests/test_bills_v2_browser.py`

## SC-51: eval and docs
Requirement IDs: FR-53
Expected:
- `document_forms` gains a RENT case. With stubbed correct answers its report row is all correct: kind `rent`, Issued
  missing, period 2026-10-01 – 2026-10-31, due 2026-10-01, 2 lines, water present as `utility`, amount due 1,488.42.
- With one stubbed wrong answer (Issued 2026-10-01) the row shows Issued wrong, and nothing else.
- Docs: not an automated test. Review `git diff docs/` for `docs/money.md` "Bills and their lines" (kinds, rent form,
  date rules), `docs/documents.md` "Bill kinds" beside "Receipt kinds", and utility/phone/insurance kinds in
  `docs/open-work.md`.
Evidence: `pytest tests/test_eval_tasks.py -k "document_forms and rent"`

---

## Traceability

| FR | Scenarios | Test file / command |
|---|---|---|
| FR-40 | SC-38, SC-44d, SC-47 | `tests/test_bill_kinds.py -k "sc38 or sc44"` |
| FR-41 | SC-44 | `tests/test_bill_kinds.py -k sc44` |
| FR-42 | Journey SC-45, SC-48 step 7 | `tests/test_bill_kinds.py -k journey`, `tests/test_bill_kinds_browser.py -k sc48` |
| FR-43 | SC-38 step 2 | `tests/test_bill_kinds.py -k sc38` |
| FR-44 | SC-38, 38a, 38b | `tests/test_bill_kinds.py -k sc38` |
| FR-45 | SC-43 | `tests/test_bill_kinds.py -k sc43` |
| FR-45a | SC-43a | `tests/test_bill_kinds.py -k sc43a` |
| FR-45b | SC-43b | `tests/test_bill_kinds.py -k sc43b` |
| FR-46 | SC-39 | `tests/test_bill_kinds.py -k sc39` |
| FR-47 | SC-38, SC-40, SC-41, 46c-1 | `tests/test_bill_kinds.py -k "sc40 or sc41"` |
| FR-48 | SC-39, SC-42, SC-46b | `tests/test_bill_kinds.py -k "sc42 or sc46b"` |
| FR-49 | SC-38, SC-46, SC-46e | `tests/test_bill_kinds.py -k "sc46"` |
| FR-50 | SC-46, SC-46e, SC-47, SC-48 | `tests/test_bill_kinds_browser.py`, `tests/test_document_v2_browser.py -k invoice` |
| FR-51 | SC-48 | `tests/test_bill_kinds_browser.py -k sc48` |
| FR-52 | SC-49 | `tests/test_migrations.py -k bill_kinds`, `tests/test_bill_kinds.py -k version` |
| FR-53 | SC-51 | `tests/test_eval_tasks.py -k document_forms`, review of `git diff docs/` |
| FR-54 | SC-46a | `tests/test_bill_kinds.py -k sc46a` |
| FR-55 | SC-46b | `tests/test_bill_kinds.py -k sc46b` |
| FR-56 | SC-46c | `tests/test_bill_kinds.py -k sc46c` |
| FR-57 | SC-46d | `tests/test_bill_kinds.py -k sc46d` |
| FR-58 | SC-46e | `tests/test_bill_kinds.py -k sc46e` |
| Invariants | C-cite, C-date, C-money, C-ids, C-calls | every scenario that publishes |
| Regression | SC-47, SC-50, 43a-1 | the existing bill suites |

Targeted run:
```
python -m pytest tests/test_bill_kinds.py tests/test_bill_kinds_browser.py tests/test_bills_ledger.py
tests/test_recurring_bills.py tests/test_invoice_ingestion.py tests/test_migrations.py tests/test_eval_tasks.py
tests/test_document_v2_browser.py tests/test_budgets.py -q
```

Needs a real integration: none in CI. The live model's accuracy is measured only by the user's own eval run on their
bill (U3), which reports through `summary.json`.

## Gaps in the spec

Resolved by the user on 2026-10-19, and written into the spec:
- **G1:** RENT-CARRIED prints `New Charges $1,488.42` (spec "Scenarios").
- **G2:** FR-54 leaves out only earlier rent and payment lines; a utility line keeps its earlier period.
- **G3:** FR-48: a dropped due date or bill period, or an order failure, sends the bill to review; a dropped line date
  or Issued is a note only.
- **G4:** FR-50: "Not accounted for" is the amount due minus the rows above it, negative when they add up to more.
- **G5:** FR-56: with no printed monthly rate, a prorated rent bill proposes no recurring bill, and its note says the
  next full month will. (The spec's earlier example, an empty expected amount, would have needed a migration:
  `recurring_obligations.expected_amount_minor` is `NOT NULL` and the table has no note column.)
- **G6:** RENT-PRORATED prints `Amount Due $833.58` (spec "Scenarios").

- **G7:** FR-56: with a printed monthly rate, the recurring bill expects the rate plus the bill's utility lines
  (1,488.42 in 46c-2), split by FR-45a.

No gaps remain open.

Notes for the plan (not spec changes):
- FR-45 says category and type are corrected through `PATCH /api/receipts/{id}/lines/{position}`, but `LineInput`
  accepts only `line_kind` and `member` today (`app/api.py:189`); category goes through
  `PUT /api/receipts/{id}/items/{position}/category`. The new rent types (`rent`, `parking`, `pet`, `utility`, `fee`)
  are not in today's `line_kind` set or its database CHECK (067), so the plan must say where a rent type lives.
- The `document_forms` eval passes a known classification (`evals/tasks/document_forms.py` `run`), which carries no
  bill kind. For SC-51 to grade the kind, the RENT case must run the sorting step or take the kind from it.
- SC-39 relies on today's name match (`name_tokens` overlap of SYNTH/PROPERTY) for `SYNTH PROPERTY MGMT`. 39a keeps the
  test honest about the window.
