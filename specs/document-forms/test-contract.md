# Test contract: document-forms
Spec sha256: the bundle hash (spec.md + this file) from `gate.py hash --feature document-forms --stage spec`. It isn't
copied here, because writing it into this file would change it.

## Conventions for every scenario

- **Environment:** `tmp_path` library and database built by the existing helpers (`transcribe`, `make_receipt` in
  `tests/test_extraction.py` / `tests/test_receipts.py`). Synthetic transcriptions only. Never `P:\Finances`,
  `%LOCALAPPDATA%\HomeManager` or `P:\EvalCorpus`.
- **Model double:** the `local_model` fixture (`tests/conftest.py:117`), a loopback server that returns scripted JSON
  and records each request. New tests answer **by the requested `json_schema.name`**, through a keyed variant of the
  output list, so the contract doesn't fix the order of calls. Every assertion on requests reads
  `local_model["requests"]`.
- **No live model output** is asserted anywhere. Accuracy belongs to the eval tasks (SC-17), which also run on stubs in
  CI.
- **Shared checks** (apply wherever a record is published):
  - **C-cite:** every stored non-null new value has a locator whose quote is an exact substring of its line.
  - **C-money:** all money columns are SQLite `integer` (`typeof()` = 'integer'). Volume, prices per unit, weights,
    hours, rates and percentages are stored as their printed decimal text, with no float type.
  - **C-noimg:** no extraction request contains `image_url`, and the count of `parse_runs` is unchanged by extraction.
  - **C-ids:** no stored record field outside `parse_runs` holds more than four digits of an account or card number,
    gift cards included (FR-30).
- **Test files** (new): `tests/test_receipt_kinds.py`, `tests/test_paystub_forms.py`, `tests/test_statement_forms.py`.
  Existing files are extended where named.
- **Cleanup:** `tmp_path` is removed by pytest. No other files are written.

Arithmetic used below (worked from the spec, not from running code):
- 10.312 × 3.459 = 35.669208, which rounds half-up to 35.67. 10.000 × 3.459 = 34.59. 2.31 × 0.59 = 1.3629, which
  rounds to 1.36. 2 × 2.00 = 4.00.
- 3.49 + 1.36 + 4.00 + 0.10 + 0.10 − 0.50 = 8.55. Tenders 5.00 + 3.55 = 8.55. Amount paid 8.55 − 5.00 = 3.55, and
  8.55 − 4.00 = 4.55.
- 80.00 × 31.25 = 2,500.00. 80.00 × 31.00 = 2,480.00.
- 1,500.00 + 412.34 = 1,912.34.
- 1,000.00 + 2,500.00 − 1,200.50 = 2,299.50.
- 500.00 − 500.00 − 20.00 + 812.45 + 0.00 + 0.00 = 792.45.

**Pay stub fixture P** (used by SC-20 and SC-21). Biweekly, period 2026-06-15 to 2026-06-28, paid 2026-07-03,
employer SYNTH WORKS. Its year-to-date column is exactly 13 periods:
| Line | Group | This period | Year to date |
|---|---|---|---|
| Regular 80.00 h @ 31.25 | earnings | 2,500.00 | 32,500.00 |
| Federal income tax | tax | 250.00 | 3,250.00 |
| Social Security | tax | 155.00 | 2,015.00 |
| Medicare | tax | 36.25 | 471.25 |
| GA state tax | tax | 96.41 | 1,253.33 |
| 401(k) | pre_tax | 50.00 | 650.00 |
| **Gross pay** | | 2,500.00 | 32,500.00 |
| **Net pay** | | 1,912.34 | 24,860.42 |

Also printed: `PTO BALANCE 56.00 HRS`, `DIRECT DEPOSIT CHECKING ****1234 1,500.00`, `SAVINGS ****9876 412.34`,
`SSN XXX-XX-1234`, `EMPLOYEE ID 445566`.

Two layouts of P are used:
- **P-table:** a validated vision table with headings `Description | This period | Year to date`.
- **P-flat:** flat text with no table, in sections: a `THIS PERIOD` heading line followed by `GROSS PAY 2,500.00` …
  `NET PAY 1,912.34`, then a `YEAR TO DATE` heading line followed by `GROSS PAY 32,500.00` … `NET PAY 24,860.42`. Each
  line holds one amount.

---

## SC-01: fuel receipt is read with the fuel form
Requirement IDs: FR-01, FR-03, FR-04, FR-05, FR-06, FR-07
Nondeterministic components: model stubbed (classification gives a receipt of kind `fuel` citing line 4; fuel form;
items; identity; description; rewards)
Initial state: empty library. Lines `1 SYNTH FUEL #12`, `2 2026-10-01`, `3 PUMP 17`, `4 REG UNL 10.312 GAL @ 3.459`,
`5 FUEL SALE 35.67`, `6 COFFEE 2.19`, `7 TOTAL 37.86`, `8 VISA ****4242`
Actions/checkpoints:
1. Extract → `succeeded`.
2. Requests → exactly one asks for the fuel form, and none for the dining or grocery form. The fuel schema contains
   volume, unit, price per unit, grade, pump and fuel amount.
3. Record → `receipt_kind = fuel`. Volume `10.312`, gallon, price `3.459`, grade `REG UNL`, pump `17`, fuel amount 3567.
Expected final state:
- Database: total 3786 USD. Two items (fuel 3567 `transportation`, COFFEE 219). No `PUMP` item. Cross-checks ≥ 1.
  Verified, `review_source = automatic`. C-cite, C-money and C-noimg hold.
Failure variants:
- 1a: grade not printed → null, and still verified.
- 1b: `10.312 L` → unit litre, and the check uses the printed numbers.
Evidence: `pytest tests/test_receipt_kinds.py -k sc01`

## SC-02: fuel arithmetic mismatch
Requirement IDs: FR-07
Initial state: SC-01, with line 5 = `FUEL SALE 36.67` and line 7 = `TOTAL 38.86`.
Expected final state: `needs_review`. The issue names `10.312`, `3.459` and `36.67`. Values are stored as printed.
Failure variants:
- 2a: price per unit ambiguous → the fuel check is skipped and no fuel issue is raised.
Evidence: `pytest tests/test_receipt_kinds.py -k sc02`

## SC-03: dining with included gratuity and a blank tip line
Requirement IDs: FR-04, FR-08
Initial state: `1 SYNTH BISTRO`, `2 2026-10-02`, `3 SERVER: SAM TABLE 9 GUESTS 4`, `4 PASTA 30.00`, `5 SALAD 20.00`,
`6 SUBTOTAL 50.00`, `7 TAX 4.00`, `8 GRATUITY 18% INCLUDED 9.00`, `9 TIP ______`, `10 TOTAL 63.00`
Expected final state: `dining`. Gratuity included, 900. Tip null (not 0). Party size `4`, and the server or table are
cited. 5000 + 400 + 900 = 6300 reconciles, and the total is counted once.
Failure variants:
- 3a: `TIP 10.00`, `TOTAL 64.00`, and no gratuity → tip 1000, and the check passes.
- 3b: the stub fills the tip with `0.00` citing line 9 → rejected by the amount-printed check after one correction.
Evidence: `pytest tests/test_receipt_kinds.py -k sc03`

## SC-04: grocery receipt
Requirement IDs: FR-04, FR-09, FR-30
Initial state: `1 SYNTH MARKET`, `2 2026-10-03`, `3 MILK 3.49`, `4 BANANAS 2.31 lb @ 0.59/lb 1.36`,
`5 2x CHIPS @ 2.00 4.00`, `6 BOTTLE DEPOSIT 0.10`, `7 BAG FEE 0.10`, `8 MEMBER SAVINGS -0.50`, `9 SUBTOTAL 8.55`,
`10 TAX 0.00`, `11 TOTAL 8.55`, `12 GIFT CARD 6006491234565555 -5.00`, `13 EBT SNAP 3.55`
Expected final state:
- `grocery`. BANANAS has weight `2.31`, `lb`, `0.59` and 136.
- CHIPS has quantity 2, unit price 200 and line total 400. The multi-unit check passes and adds to `cross_checks`.
- Deposit 10 and bag fee 10 are their own rows. Savings −50 is kept as a row and as the stored savings total.
- Tenders: gift card 500 with last four `5555`, and `EBT` 355. The gift card is not an item and not a discount.
- 349 + 136 + 400 + 10 + 10 − 50 = 855 = subtotal, so the check counts. The gift card takes no part in it.
- Printed total 855 is stored unchanged. Amount paid is 355, and that is the counted amount: the receipt's category
  split rows sum to exactly 355, and the ledger health check passes.
- C-ids: nothing stored outside `parse_runs` contains `6006491234565555`.
Failure variants:
- 4a: no printed per-weight price → that field is null, and the line total is still 136.
- 4b: line 5 = `2x CHIPS @ 2.00 4.50`, with subtotal and total `9.05` → `needs_review`, with a reason naming `2`,
  `2.00` and `4.50`. The item-sum check still passes, and the values are stored as printed.
- 4c: `CHIPS 4.00` with no count printed → quantity null, and no multi-unit check or issue.
- 4d: the stub returns the gift card as an item of −500 → item sum 355 ≠ subtotal 855, so `needs_review` through the
  existing check. The total stays 855, and with no gift card tender stored, amount paid is 855.
- 4e: line 12 = `GIFT CARD 6006491234565555 -9.00`, more than the total → `needs_review` with "gift card deductions
  exceed the total", and the receipt counts 855.
- 4f: no gift card line (EBT 8.55) → amount paid equals the total 855, exactly as today.
Evidence: `pytest tests/test_receipt_kinds.py -k sc04`

## SC-05: general receipt unchanged (regression)
Requirement IDs: FR-01, FR-13
Initial state: the `RECEIPT` fixture and stubs from
`test_receipt_extraction_publishes_exact_evidence_linked_records_and_files`, plus kind `general`.
Expected final state: every assertion of that test holds, and `receipt_kind = general`. No kind-specific form is
requested. The existing receipt tests pass with only their expected schema-name lists updated (if the plan adds a
call).
Evidence: `pytest tests/test_extraction.py tests/test_receipt_kinds.py -k "sc05 or receipt"`

## SC-06: invoice stays a bill (regression)
Expected final state: `document_kind = bill`, with `invoice_json` populated and no receipt kind. The existing invoice
tests pass unchanged.
Evidence: `pytest tests/test_invoice_ingestion.py`

## SC-07: an invalid kind proposal falls back to general
Requirement IDs: FR-02
Stub: kind `fuel`, citing `line-3` with a quote not in that line.
Expected final state: `general`, with no fuel-form request, an issue explaining the citation, and `needs_review`.
Failure variants:
- 7a: kind `pharmacy` → the same fallback.
- 7b: no citation → the same fallback.
Evidence: `pytest tests/test_receipt_kinds.py -k sc07`

## SC-08 and SC-26: new fields fail twice, but today's fields still publish
Requirement IDs: FR-14
- **SC-08:** on the SC-01 transcription, the fuel form returns an invalid answer twice (amount not printed in its
  citation).
  - Expected: the run `succeeded`. The second fuel request is a correction. The receipt is published with merchant,
    date, total 3786 and its items, with no fuel details (none partial). `needs_review` with "document details could
    not be read".
- **SC-26:** on the SC-22 transcription, the bank statement's new fields are invalid twice.
  - Expected: the statement and its transactions are published as today, with no new fields and the same reason.
- **Variant 8a:** the *shared* summary fails twice → the run fails and nothing is published (as today).
Evidence: `pytest tests/test_receipt_kinds.py -k sc08`, `pytest tests/test_statement_forms.py -k sc26`

## Journey (SC-09, SC-10, SC-13): changing the kind, reading again and review protection
Requirement IDs: FR-06, FR-11, FR-12, FR-16
Environment: one library across all checkpoints (a stateful journey, so this is one test function)
Initial state: the SC-01 transcription, extracted at v22 with the old single form. That gives a receipt in Review
with a `PUMP 17` item, seeded by publishing a v22-shaped record through the ledger.
Actions/checkpoints:
1. Read again at the new version (kind `general`, no PUMP item) → a new run, with v22 not reused. `PUMP 17` is removed
   along with its split rows, and no orphan split rows remain.
2. `PATCH` the kind to `fuel` → a correction id. Exactly one fuel-form request is made. C-noimg holds.
3. Record → `fuel` with details. History shows "Receipt kind: general → fuel" with Undo.
4. Read again (the stub says `general`) → the kind stays `fuel`.
5. Undo the kind correction → `general`, and fuel details are not current.
6. Verify the record, then correct the total to 3800.
7. `PATCH` the kind to `dining` → the correction is recorded. Total 3800, items and `verified` are unchanged. Dining
   details are pending, and **Apply details** is offered.
8. Restart (a new manager on the same database) → the proposal is still pending.
9. Apply details → the details are current, as a correction with Undo. Total 3800, still `verified`.
10. Undo the apply → pending again.
Expected final state: one receipt row. The corrections hold the kind changes, undo, total, apply and its undo. The
record is verified with total 3800.
Failure/retry/restart variants:
- J-a: duplicate `PATCH` → no-op (no second request or correction).
- J-b: cancelled re-extraction after step 2 → `cancelled`, and the state is exactly as before step 2. A retry
  succeeds.
- J-c: restart while it's `running` → the run is interrupted and can be retried, with no partial details.
- J-d: `PATCH kind=pharmacy` → 4xx, nothing changes.
- J-e: a second kind change before applying → it replaces the proposal (one pending).
- J-f: apply with nothing pending → 4xx "There are no details waiting to be applied.".
Evidence: `pytest tests/test_receipt_kinds.py -k journey`

## SC-11: upgrading the database leaves existing records untouched
Requirement IDs: FR-13
Environment: the `tests/test_migrations.py` pattern. A database at the last pre-feature `user_version` with a fuel-like
receipt (`PUMP 17` item), a dining receipt, a pay stub with lines, and a bank statement with transactions.
Expected final state:
- Every money, item, line, transaction, category and review column is equal before and after. `PUMP 17` is still
  present.
- `receipt_kind` is null (not `general`), and every new pay stub and statement field is null.
- There are 0 extraction runs and 0 queued jobs, and the ledger health check passes.
- The record view shows no kind and no new-field traces.
Evidence: `pytest tests/test_migrations.py -k document_forms`

## SC-12: a split file gets a kind per receipt
Requirement IDs: FR-15
Initial state: a two-page synthetic PDF, page 1 with the SC-01 lines and page 2 with the SC-03 lines. Part stubs return
`fuel` and `dining`.
Expected final state: two receipts, segment 1 `fuel` and segment 2 `dining` (gratuity 900), each with the split note.
Evidence: `pytest tests/test_receipt_segments.py -k kind`

## SC-14: the document page shows the new fields
Requirement IDs: FR-10, FR-11 (UI path)
Environment: the browser fixture in `tests/test_document_v2_browser.py`, seeded through `tests/seed_documents.py` with
the SC-01, SC-04, SC-21, SC-22 and SC-23 records.
Actions/checkpoints:
1. Fuel receipt → a Kind row shows Fuel, with volume `10.312 gal`, price `3.459`, grade and pump. Clicking volume's
   source highlights `line-4`.
2. Grocery receipt → BANANAS `2.31 lb @ 0.59/lb`, CHIPS `2 × 2.00`, deposit and bag fee as separate rows, and the
   gift card (`****5555`, 5.00) and EBT shown as tenders, not items. The money summary reads "Total 8.55 · Gift card
   −5.00 · Paid 3.55", and Paid opens its trace.
3. Pay stub → hours and rate on Regular, PTO `56.00 hrs`, and two deposit splits `****1234` and `****9876`. Each amount
   shows its printed column heading.
4. Bank statement → account type, deposits and withdrawals totals, interest, APY and fees.
5. Card statement → APRs, limit, available credit and rewards.
6. Fuel receipt → change the kind to Dining, preview and save → reloads as Dining after one stubbed extraction.
   Reload → still Dining.
Expected final state: as above, with no console errors and no CSP violations.
Evidence: `pytest tests/test_document_v2_browser.py -k "kind or forms"`, and synthetic screenshots through
`scripts/ui_shots.py`

## SC-15: version changes, and old readings are not reused
Requirement IDs: FR-16
Expected: `EXTRACTION_VERSION != "typed-extraction-v22-native-cells"`. A parse with only a v22 run gets a new run
(`reused: False`).
Evidence: `pytest tests/test_receipt_kinds.py -k version`

## SC-16: docs updated
Requirement IDs: FR-17
Not an automated test. It's checked in review of `git diff docs/ text_extraction_plan.md` against FR-17. The headings
"Typed extraction" and "PDFs" stay stable.

## SC-17: eval tasks on synthetic fixtures
Requirement IDs: spec section "Nondeterministic outputs", FR-24
Environment: `evals/tasks/` (new tasks beside `identify.py`), with synthetic fixtures in Git. The model is stubbed in
CI.
Expected:
- `summary.json` reports kind accuracy per receipt kind, and field present/correct counts per form (receipt kinds,
  pay stub, bank, card).
- It reports **wrong-column values that would count automatically** per pay stub fixture.
- The test uses one fixture per receipt kind, P-table, P-flat, and one bank and one card fixture. One stubbed answer is
  deliberately wrong, and one pay stub answer puts year to date into this period. The assertions are the report's
  shape and exact counts, with the wrong-column count 0 after FR-22.
Evidence: `pytest tests/test_eval_tasks.py -k "receipt_kind or document_forms"`

## SC-18: a kind change is refused while a reading is in progress
Requirement IDs: FR-18
Nondeterministic components: the stub holds its reply until released (a threading event, as in the existing
cancellation test).
Actions/checkpoints:
1. An extraction is `running` → `PATCH` kind gives 409 "A reading is in progress; try again when it finishes", with no
   correction row and no extra requests.
2. A second reading is `queued` → `PATCH` gives 409 again.
3. Release → both runs `succeeded`.
4. `PATCH` the kind to `dining` → succeeds, with one dining-form request.
Failure variants:
- 18a: only a *different* document is being read → not refused.
Evidence: `pytest tests/test_receipt_kinds.py -k sc18`

## SC-19: receipt traces
Requirement IDs: FR-19
Actions/checkpoints:
1. SC-01 fuel trace → `result` 35.67, and `reconciles` true. The steps include volume `10.312` and price `3.459`, each
   `extracted` from `line-4` with a substring quote. Rounding is half-up to the minor unit, compared with 35.67.
2. SC-02 → result 35.67 compared with 36.67, and `reconciles` false.
3. Correct SC-01's volume to `10.000` → `override` provenance with original `10.312`. The result is 34.59, and
   `reconciles` false.
4. SC-03 dining trace → steps 50.00, 4.00, gratuity 9.00, and a tip step with no value. The result is 63.00, and
   `reconciles` true.
5. SC-04 CHIPS multi-unit trace → steps count `2` and unit price `2.00`, `extracted` from `line-5`. The result is
   4.00 compared with 4.00, and `reconciles` true. On variant 4b it is compared with 4.50, and `reconciles` false.
6. SC-04 amount-paid trace → steps total 8.55 (`line-11`) and gift card −5.00 (`line-12`), both `extracted`. The
   result is 3.55, compared with the other printed tender (EBT 3.55, `line-13`), and `reconciles` true.
7. A fuel trace on SC-03, a dining trace on SC-01, a multi-unit trace on MILK, and an amount-paid trace on SC-01 (no
   gift card) → "This isn't worked out for this record.".
8. Browser: SC-01's fuel figure opens its trace. The result equals the page figure, and clicking an input highlights
   `line-4`.
Evidence: `pytest tests/test_receipt_kinds.py -k sc19`, `pytest tests/test_document_v2_browser.py -k kind_trace`

## SC-20: this period never takes a year-to-date or annual amount (the reported defect)
Requirement IDs: FR-22, FR-23, FR-24
Environment: isolated; synthetic, with fixture P in the stated layout. One test per variant, independent of each other.
Nondeterministic components: the stub plays the faulty model in each variant. The decision model is not configured,
so it can't be the reason a record goes to review.

**Characterization first (FR-24).** Variant 20-e is committed with the fix. Run against the pre-change code (the
commit before implementation), it must **fail**, because there the stub is `verified` with `gross_pay_minor` 3250000.
That run's output is recorded as the evidence that the defect is reproduced. After the change it must pass.

| Variant | Layout | What the stub does | Rule | Expected |
|---|---|---|---|---|
| 20-a | P-flat | `gross_pay` = `32,500.00`, cites the YEAR TO DATE section's `GROSS PAY 32,500.00`, column heading `YEAR TO DATE` | (a) label | `gross_pay` null and ambiguous. The reason names gross pay, 32,500.00 and its line |
| 20-b | P-flat, with the Regular line's amounts on their own unlabelled lines (`2,500.00`, `32,500.00`) | swaps them: Regular current `32,500.00`, ytd `2,500.00` | (b) larger than YTD | Regular current null and ambiguous. The reason names both values |
| 20-c | P-flat | `gross_pay` and `gross_pay_ytd` both `32,500.00`, column heading null, period 2026-06-15 | (c) equal mid-year | `gross_pay` null and ambiguous |
| 20-d | P-flat, plus the line `ANNUAL SALARY 65,000.00` | `gross_pay` = `65,000.00` citing it, row label `ANNUAL SALARY` | (a) and (b) | null and ambiguous. The reason mentions annual |
| 20-e | P-flat | **every** this-period value (gross, net and all six lines) copied from the YEAR TO DATE section, column heading null. They add up: 32,500.00 − 7,639.58 = 24,860.42 | (c) on each | Every this-period value null and ambiguous. `needs_review`, never verified, though the year-to-date checks pass |
| 20-f | P-table | the stub's gross summary cites the YTD cell | (a) heading `Year to date` | as today: the cell copy gives 2,500.00 from This period, and no FR-22 reason |
| 20-g | P-flat, period 2026-01-01 to 2026-01-14, every YTD equal to this period | correct values | (c) first period | accepted. Verified if the other checks pass, with no FR-22 reason |
| 20-h | P-flat, no period dates or frequency printed, current = YTD | correct values | (c) unknown period | `needs_review` with the equality reason |

Follow-on checkpoints (one test, after 20-e):
1. Correct `gross_pay` to 2,500.00 and `net_pay` to 1,912.34 with **Edit details** → those reasons clear, and the line
   reasons remain.
2. Read again with the same faulty stub → your corrections are kept, and the line reasons are raised again.

Expected final state: in no variant except 20-f and 20-g is the stub `verified`. C-cite holds for every value that
is kept.
Evidence: `pytest tests/test_paystub_forms.py -k sc20`. Pre-change run: `git stash` the implementation, or check out
the base commit into a worktree, and run `-k sc20_e`, recording the failure.

## SC-21: pay stub fields and checks
Requirement IDs: FR-20, FR-21, FR-19, FR-30
Initial state: fixture P-table, with correct stubs.
Actions/checkpoints:
1. Extract → `succeeded`, and verified.
2. Record:
   - Regular has hours `80.00`, rate `31.25`, current 250000 and ytd 3250000;
   - PTO `56.00 hrs`, with its label;
   - splits (`1234`, 150000) and (`9876`, 41234);
   - every amount's row label and column heading are stored and are substrings of their lines.
3. Cross-checks include hours × rate and the deposit split sum, along with the existing earnings and net checks.
4. Traces → hours × rate gives 2,500.00 (reconciles), and the split sum gives 1,912.34 (reconciles). The inputs are
   `extracted` with their lines.
5. C-ids: nothing stored contains `445566` or `XXX-XX-1234`.
Failure variants:
- 21a: rate `31.00` → `needs_review` naming 80.00, 31.00 and 2,500.00. The trace gives 2,480.00, not reconciling.
- 21b: salaried, with no hours or rate → no hours check and no issue.
- 21c: only one split printed, with no amount on the second → the split check is skipped.
Evidence: `pytest tests/test_paystub_forms.py -k sc21`

## SC-22: bank statement fields and summary check
Requirement IDs: FR-25, FR-26, FR-19
Initial state: `SYNTH BANK`, `EVERYDAY CHECKING ACCOUNT 000123456789`, `ROUTING 021000021`, period 2026-09-01 to
2026-09-30, `OPENING BALANCE 1,000.00`, `DEPOSITS 2,500.00`, `WITHDRAWALS 1,200.50`, `CLOSING BALANCE 2,299.50`,
`INTEREST EARNED 0.42`, `APY 0.50%`, `FEES 0.00`. Transactions: `09/03 PAYROLL SYNTH WORKS +2,500.00` and
`09/05 RENT -1,200.50`, which sum to +1,299.50. Interest is printed in the summary only, with no transaction row.
Expected final state:
- Account type `checking`. Deposits 250000, withdrawals 120050, interest 42, APY `0.50%`, fees 0.
- The summary check passes, and the existing transaction check passes too (1,000.00 + 1,299.50 = 2,299.50).
- The summary trace gives 2,299.50 and reconciles. `last_four = 6789`, and C-ids holds (no `000123456789` or
  `021000021`).
Failure variants:
- 22a: closing `2,300.50` → `needs_review`, with both checks failing and the summary reason naming the four values.
- 22b: no type word printed → `other`.
- 22c: no withdrawals total printed → the summary check is skipped, and the transaction check is still used.
Evidence: `pytest tests/test_statement_forms.py -k sc22`

## SC-23: credit card statement fields and summary check
Requirement IDs: FR-27, FR-28, FR-19
Initial state: `SYNTH CARD`, `ACCOUNT ENDING 4242`, `PREVIOUS BALANCE 500.00`, `PAYMENTS -500.00`, `CREDITS -20.00`,
`PURCHASES 812.45`, `FEES CHARGED 0.00`, `INTEREST CHARGED 0.00`, `NEW BALANCE 792.45`,
`PURCHASE APR 24.99%`, `CASH ADVANCE APR 29.99%`, `CREDIT LIMIT 5,000.00`, `AVAILABLE CREDIT 4,207.55`,
`POINTS EARNED 812`. Transactions: payment +500.00, refund +20.00, purchase −812.45.
Expected final state:
- APRs `24.99%` and `29.99%`, limit 500000, available 420755, rewards `812 points` (text, no money).
- The summary check passes (792.45), along with the existing transaction check (500.00 − (−292.45) = 792.45). The trace
  reconciles.
Failure variants:
- 23a: new balance `795.45` → `needs_review`.
- 23b: the fees line not printed → the summary check is skipped.
Evidence: `pytest tests/test_statement_forms.py -k sc23`

## SC-24: counting is unchanged
Requirement IDs: FR-29
Initial state: the SC-21, SC-22 and SC-23 records in one library, with the bank statement released for reconciliation.
Expected:
- September 2026 money in and spending equal what today's rules give from the fixture rows: the paycheck counted at
  net 1,912.34, the bank's transactions, and the card purchase −812.45 net of its 20.00 refund.
- Interest 0.42 is counted only through its transaction row, if one exists, and never from the new summary field.
- The account balance is 2,299.50.
- The values are written into the test from this arithmetic. A second assertion runs the same figures with the
  new-field writes disabled (the fields set to null) and expects equality.
Evidence: `pytest tests/test_statement_forms.py -k sc24`

## SC-25: sensitive identifiers are never stored
Requirement IDs: FR-30
Initial state: fixture P and the SC-22 statement. The stubs deliberately return full numbers in split, account and
any free-text fields.
Expected: C-ids holds across every record table and JSON column (scanned by SQL over all non-`parse_runs` tables).
Splits are `1234` and `9876`, the account `6789`, and a note says digits were dropped.
Evidence: `pytest tests/test_paystub_forms.py -k sc25`, `pytest tests/test_statement_forms.py -k sc25`

## SC-27: a gift card lowers what is charged and what counts
Requirement IDs: FR-09, FR-19, FR-29
Environment: one library across all checkpoints (a stateful journey, so this is one test function)
Initial state:
- Receipt: `1 SYNTH MARKET`, `2 2026-10-03`, `3 GROCERIES 8.55`, `4 SUBTOTAL 8.55`, `5 TAX 0.00`, `6 TOTAL 8.55`,
  `7 GIFT CARD ****5555 -5.00`, `8 VISA ****4242 3.55`. The stub gives the category `groceries`.
- Card statement for card `4242`: `10/05 SYNTH MARKET -3.55`, and `10/06 SYNTH MARKET -8.55` belonging to another
  purchase that has no receipt.
Actions/checkpoints:
1. Extract the receipt → total 855, gift card tender 500, amount paid 355. Before reconciling, October `groceries`
   spending is 3.55.
2. Extract the statement and reconcile → the receipt links to the −3.55 line, not the −8.55 one. The link's method
   and points are recorded as for any exact match.
3. October spending → `groceries` is 3.55 + 8.55 = 12.10: the linked line counts once, carrying the receipt's
   categories scaled to 3.55, and the unmatched line counts on its own. The receipt doesn't count standalone.
4. Amount-paid trace → result 3.55, compared with VISA 3.55, and `reconciles` true.
5. Correct the gift card to 4.00 with **Edit details** → amount paid 455, and the trace shows the gift card step as
   `override` with original 5.00. The link is kept, and the receipt goes to `needs_review` with a note that amount
   paid (4.55) no longer equals the linked charge (3.55).
6. Undo the correction → amount paid 355, and the note clears.
Expected final state: one receipt and one link. October `groceries` is 12.10. The ledger health check passes, with
every receipt's split rows summing to its counted amount.
Failure variants:
- 27a: the same receipt without the gift card line (VISA 8.55) → it links to the −8.55 line, exactly as today.
- 27b: the statement has only the −8.55 line → no exact match. The near-match rule doesn't apply, because the line is
  larger than 3.55 by more than `NEAR_PERCENT` allows. The receipt counts 3.55 standalone and the line counts 8.55.
Evidence: `pytest tests/test_receipt_kinds.py -k sc27`

---

## Traceability

| FR | Scenarios | Test file / command |
|---|---|---|
| FR-01 | SC-01, SC-05 | `tests/test_receipt_kinds.py`, `tests/test_extraction.py` |
| FR-02 | SC-07 | `tests/test_receipt_kinds.py -k sc07` |
| FR-03 | SC-01 | `tests/test_receipt_kinds.py -k sc01` |
| FR-04 | SC-01, SC-03, SC-04 | `tests/test_receipt_kinds.py` |
| FR-05 | SC-01, SC-04 | `tests/test_receipt_kinds.py` |
| FR-06 | SC-01, journey 1 | `tests/test_receipt_kinds.py -k "sc01 or journey"` |
| FR-07 | SC-01, SC-02 | `tests/test_receipt_kinds.py -k "sc01 or sc02"` |
| FR-08 | SC-03 | `tests/test_receipt_kinds.py -k sc03` |
| FR-09 | SC-04, SC-19 steps 5–6, SC-27 | `tests/test_receipt_kinds.py -k "sc04 or sc19 or sc27"` |
| FR-10 | SC-14 | `tests/test_document_v2_browser.py -k "kind or forms"` |
| FR-11 | journey 2–5, SC-14 | `tests/test_receipt_kinds.py -k journey`, browser |
| FR-12 | journey 6–10, J-e, J-f | `tests/test_receipt_kinds.py -k journey` |
| FR-13 | SC-05, SC-11 | `tests/test_migrations.py -k document_forms` |
| FR-14 | SC-08, SC-26 | `tests/test_receipt_kinds.py -k sc08`, `tests/test_statement_forms.py -k sc26` |
| FR-15 | SC-12 | `tests/test_receipt_segments.py -k kind` |
| FR-16 | SC-15, journey 1 | `tests/test_receipt_kinds.py -k version` |
| FR-17 | SC-16 | review of `git diff docs/ text_extraction_plan.md` |
| FR-18 | SC-18 | `tests/test_receipt_kinds.py -k sc18` |
| FR-19 | SC-19, SC-21, SC-22, SC-23 | the files above, plus `tests/test_document_v2_browser.py -k kind_trace` |
| FR-20 | SC-21, SC-14 | `tests/test_paystub_forms.py -k sc21` |
| FR-21 | SC-21 | `tests/test_paystub_forms.py -k sc21` |
| FR-22 | SC-20 | `tests/test_paystub_forms.py -k sc20` |
| FR-23 | SC-20 (20-e and the follow-on) | `tests/test_paystub_forms.py -k sc20` |
| FR-24 | SC-20 characterization, SC-17 | `tests/test_paystub_forms.py -k sc20_e` (before and after), `tests/test_eval_tasks.py` |
| FR-25 | SC-22 | `tests/test_statement_forms.py -k sc22` |
| FR-26 | SC-22 | `tests/test_statement_forms.py -k sc22` |
| FR-27 | SC-23 | `tests/test_statement_forms.py -k sc23` |
| FR-28 | SC-23 | `tests/test_statement_forms.py -k sc23` |
| FR-29 | SC-24, SC-27 | `tests/test_statement_forms.py -k sc24`, `tests/test_receipt_kinds.py -k sc27` |
| FR-30 | SC-04, SC-21, SC-22, SC-25 | `tests/test_paystub_forms.py -k sc25`, `tests/test_statement_forms.py -k sc25` |
| (D1 regression) | SC-06 | `tests/test_invoice_ingestion.py` |

Targeted run:
```
python -m pytest tests/test_receipt_kinds.py tests/test_paystub_forms.py tests/test_statement_forms.py
tests/test_extraction.py tests/test_invoice_ingestion.py tests/test_receipt_segments.py tests/test_migrations.py
tests/test_eval_tasks.py tests/test_document_v2_browser.py -q
```
Also run the existing pay stub and table suites (`tests/test_vision_tables.py`, `tests/test_pdf.py`,
`tests/test_layout_consumers.py`), because FR-22 runs on their paths.

## Gaps in the spec

Resolved by the user on 2026-10-17: G1 is D6, G2 is D7, G3 is D8 and G4 is D9.

Still open:
- **G5, FR-17.** Covered by review only (SC-16).
- **G6, FR-24.** The user's own failing paystub is reproduced only in their terminal. Whether this fix covers it
  depends on that run's `summary.json` (wrong-column count 0), which no automated test here can show.
