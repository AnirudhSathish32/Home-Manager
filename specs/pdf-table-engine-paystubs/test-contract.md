# Test contract: pdf-table-engine-paystubs
Spec sha256: the bundle hash (spec.md + this file) from `~/.agent-harness/gate.py hash --feature pdf-table-engine-paystubs
--stage spec`. It isn't copied here, because writing it in would change it.

Every expected value comes from `spec.md`, or is worked out by hand from the synthetic fixtures below. None comes from
running the current code or the engine. Where the spec leaves an outcome open, it is listed under "Gaps", not invented.

## Conventions for every scenario
- **Environment.** A `tmp_path` library and database only. Never `P:\Finances`, `%LOCALAPPDATA%\HomeManager` or
  `P:\EvalCorpus`. Record tests go through the real services, as `tests/test_layout_consumers.py`
  `test_native_paystub_reaches_ledger_search_and_source_cells` does: `make_pdf` into the Inbox, `capture`,
  `ReceiptService.enqueue` + `run` with `VisionConfig()`-equivalent config (no vision call for text pages), then
  `ExtractionService.enqueue` + `run` with `ReasoningConfig(base_url=local_model …, model="synthetic-reasoning")`, then
  `Ledger(store).record("income_record", run["publication"]["id"])`. API steps use `create_app(…)` with `TestClient`.
  Browser steps are opt-in (`RUN_BROWSER_TESTS=1`, the `served()` helper of `tests/test_transactions_v2_browser.py`).
- **Engine-level tests** call the engine on the saved reading (`read_result(parse["result"])`) as a pay stub, with no
  store and no model. They stay independent of one another. The engine's entry point and result names are the plan's;
  the observable facts asserted (tables, rows, labels, column roles, totals, unplaced lines, notes) are the spec's.
- **Synthetic PDFs only:** `tests/test_pdf.py` `make_pdf` with positioned items `(x, y, text)`, 10 pt Helvetica.
  Every page ends with the words-only footer `This pay statement is for your records. Amounts are in US dollars ($).`
  at (40, 60), so the reader never sends the page to the vision model and no amount is in it.
- **Right-aligned amounts.** "right edge R" means the amount's left x is R minus its Helvetica width at 10 pt: digits
  5.56 pt, `,` and `.` 2.78 pt, `-`, `(` and `)` 3.33 pt. Labels start at the stated left x.
- **P-checks.** Before a scenario's first checkpoint the test asserts the reading has the intended shape: every page is
  `embedded_text` (except SC-72 d), and each amount column's saved word boxes agree on their right edge within 0.5 pt.
  A failed P-check is a fixture or reader problem, never a reason to change an expected value.
- **C-net.** An autouse fixture blocks non-loopback sockets. Only the `local_model` stub on loopback is reachable.
- **Shared checks**
  - **C-money:** every `income_records` amount and every `income_lines.current_minor`/`ytd_minor` is an integer or null;
    currency `USD`.
  - **C-docs:** the sha256 of each fixture's original and every file of its reading folder is unchanged by Extract,
    Extract again, the segment actions and the upgrade.
  - **C-lines(expected):** the record's `lines`, in printed order, equal the expected
    `(description, line_group, current_minor, ytd_minor)` list exactly (descriptions with runs of spaces collapsed), with
    no extra line; where hours and rate are listed, each line's `hours`/`rate` details are the printed text exactly.
  - **C-note(text):** the text is among the record notes (`run["result"]["normalized"]["notes"]`, shown with the record)
    and is **not** among `record["issues"]`. "Contains" means a substring match where the spec gives no exact wording.
  - **C-auto:** `record["review_status"] == "verified"` and `record["issues"] == []` (counted automatically).
  - **C-no-feature-review:** no issue in `record["issues"]` mentions a column, a guess, an unplaced or unclassified line,
    a pay table or a split (whatever else the scenario names may still be there).
  - **C-model-calls:** `local_model["requests"]` grows only by the reasoning calls the scenario's stubs answer; the engine
    and the split rule add none.
- **Doubles**

| Component | Real or double | Specification |
|---|---|---|
| PDF reader | Real | Every PDF fixture is read by the real reader; SC-72 (d) is the only vision reading. |
| Reasoning model | `local_model` by schema (`tests/model_server.py` `by_schema`) | `Classification`: `paystub`, citing the employer line. `PaystubSummary`: employer, pay date, period, currency with their printed values and lines; amount fields as the scenario says. `PayRowClasses` and `PayLines`: one entry per pay line of the fixture with `description`, `group`, `category`, evidence citing the row's first line; in `PayLines` the amounts as the scenario says. Unasked schemas are harmless. For split files, each list holds one answer per part, in file order. |
| Vision model (SC-72 d) | `local_model` vision stub | Returns the transcription lines given in the fixture, as `tests/test_paystub_forms.py` builds vision readings. |
| Engine fault (SC-63) | `monkeypatch` | The engine's pay-stub entry point raises `RuntimeError("injected engine fault")`. |
| Deposits (SC-73) | Fixture | 26 checking transactions made by the smallest direct path (named in the test's docstring); no expected value depends on how. |
| Previous schema (SC-75) | Fixture | A library migrated through `076_receipt_discounts.sql` with income records published by `Ledger.publish_income`. |
| Clock | Real | No assertion depends on today's date (every pay date is before 2026-11-03). |
| Layout generator (SC-67) | Real, seeded | Expected values come from the generator's inputs, never from the engine. |

- **Test files (new unless stated):** `tests/paystub_engine_fixtures.py` (builders and hand-written expected values
  below); `tests/test_paystub_engine.py` (engine-level); `tests/test_paystub_engine_record.py` (Record, notes, fallback,
  version, determinism); `tests/test_paystub_split.py` (SC-72 – SC-76); `tests/paystub_engine_generator.py` and
  `tests/test_paystub_engine_generator.py` (SC-67); `tests/test_paystub_engine_browser.py` (SC-71, opt-in);
  `tests/test_evals.py` (extended, SC-68). The plan may rename them; this table and the traceability table move with it.
- **Cleanup.** pytest removes `tmp_path`; browser tests close through `served()`.

## Fixtures
Money is written as printed; expected values are minor units. Every fixture's lines above the table are printed from
y 780 down, 12 pt apart, at x 40: `SYNTH PAYROLL CO`, `Earnings Statement`, `Pay date 2026-07-03`,
`Pay period 2026-06-15 to 2026-06-28`, `Currency USD` (unless stated).

### PS: the base stub (SC-50)
Heading at y 700: `Description` left x 40; `Hours` right edge 260; `Rate` right edge 330; `Current` right edge 430;
`YTD` right edge 520. Rows from y 680, 16 pt apart (680, 664, … 536). Amounts right-aligned at those edges.

| # | Label (x 40) | Hours | Rate | Current | YTD | Kind |
|---|---|---|---|---|---|---|
| 1 | Regular | 80.00 | 31.25 | 2,500.00 | 32,500.00 | row |
| 2 | Overtime | 4.00 | 46.8750 | 187.50 | 1,125.00 | row |
| 3 | Gross Pay | | | 2,687.50 | 33,625.00 | total |
| 4 | Federal Income Tax | | | 295.63 | 3,698.75 | row |
| 5 | Social Security | | | 166.63 | 2,084.75 | row |
| 6 | Medicare | | | 38.97 | 487.56 | row |
| 7 | Total Taxes | | | 501.23 | 6,271.06 | total |
| 8 | 401K | | | 134.38 | 1,681.25 | row |
| 9 | Total Pre-Tax Deductions | | | 134.38 | 1,681.25 | total |
| 10 | Net Pay | | | 2,051.89 | 25,672.69 | total |

Worked by hand: 80.00 × 31.25 = 2,500.00; 4.00 × 46.8750 = 187.50; 2,500.00 + 187.50 = 2,687.50 and 32,500.00 + 1,125.00
= 33,625.00; 295.63 + 166.63 + 38.97 = 501.23 and 3,698.75 + 2,084.75 + 487.56 = 6,271.06; 2,687.50 − 134.38 − 501.23 =
2,051.89 and 33,625.00 − 1,681.25 − 6,271.06 = 25,672.69. Every this-period amount is smaller than its year to date, so
FR-57 (c) decides the Current column; hours × rate (FR-57 a) decides it too. The Hours and Rate columns hold no total, so
neither is a pay column (FR-57 b). "Total Pre-Tax Deductions" names pre-tax, so today's rule keeps it as pre-tax
deductions (`DEDUCTIONS_TOTAL`, `PRE_TAX_WORDS`, `extraction.py:204–205`).

**PS expected** (`EXP-PS`):
- C-lines: `(Regular, earnings, 250000, 3250000)` hours `80.00` rate `31.25`; `(Overtime, earnings, 18750, 112500)`
  hours `4.00` rate `46.8750`; `(Federal Income Tax, tax, 29563, 369875)`; `(Social Security, tax, 16663, 208475)`;
  `(Medicare, tax, 3897, 48756)`; `(401K, pre_tax, 13438, 168125)`.
- `gross_pay_minor` 268750, `gross_pay_ytd_minor` 3362500, `net_pay_minor` 205189, `net_pay_ytd_minor` 2567269,
  `taxes_minor` 50123, `deductions_minor` 13438.

**Model stub for PS** (`STUB-PS-SWAPPED`): classes as in EXP-PS. Every amount in `PayLines` and `PaystubSummary` is
swapped (this period given the year-to-date value and back), so a value from the model would be wrong everywhere.

### Variants of PS
- **PS-2L (SC-51):** the heading is two lines. y 712: `This` right edge 430, `Year to` right edge 520. y 700:
  `Description` x 40, `Hours` r 260, `Rate` r 330, `Period` r 430, `Date` r 520.
- **PS-NH (SC-55):** no heading line; the Current amounts are printed at right edge 520 and the YTD amounts at 430.
- **PS-WRAP (SC-54):** row 4 prints `Federal Income` (x 40) with its amounts at y 632; the line `Tax Withholding` at x 52,
  y 624, holds no amount. Rows 5 – 10 move down 8 pt.
- **PS-SEC (SC-60):** text-only section titles at x 40, each followed by its rows, 16 pt apart: `Earnings` above row 1,
  `Taxes` above row 4, `Pre-tax` above row 8; the rows move down accordingly.
- **PS-OTHER (SC-56):** PS plus, from y 440: title `Direct Deposit` x 40; heading `Account` x 40, `Amount` r 430; rows
  `Checking 1234` 1,551.89 and `Savings 5678` 500.00. Then from y 360: heading `Leave` x 40, `Accrued` r 260, `Used` r 330,
  `Balance` r 430; rows `Vacation` 40.00 8.00 32.00 and `Sick` 24.00 0.00 24.00.
- **PS-YTDH (SC-57 a):** heading `Description`, `Hours` r 220, `Rate` r 290, `Current` r 370, `YTD Hours` r 450, `YTD` r 530.
  Regular prints YTD hours 1,040.00 and Overtime 24.00 (1,040.00 × 31.25 = 32,500.00 and 24.00 × 46.8750 = 1,125.00, so
  two pairs share the rate column); all other values as PS.
- **PS-EMP (SC-57 b):** PS plus a column `Employer` right edge 600 that prints only on row 8: 80.63.
- **PS-DIGITS (SC-58):** row 8 is `PRE-TAX 401K` 134.38 1,681.25; a new row after it `SECTION 125` 85.00 1,105.00; row 9
  is `Total Pre-Tax Deductions` 219.38 2,786.25; Net Pay is 1,966.89 24,567.69 (2,687.50 − 219.38 − 501.23 = 1,966.89;
  33,625.00 − 2,786.25 − 6,271.06 = 24,567.69).
- **PS-BONUS (SC-69):** a row after Overtime: `Relocation Bonus`, Current blank, YTD 5,000.00. Gross Pay YTD 38,625.00, Net
  Pay YTD 30,672.69 (38,625.00 − 1,681.25 − 6,271.06).
- **PS-SWAPHEAD (SC-61 a):** PS with the heading words exchanged: `YTD` over right edge 430 and `Current` over 520; the
  amounts as PS.
- **PS-BADTOTAL (SC-62 a):** PS with Total Taxes Current printed 510.23.
- **PS-BADNET (SC-62 b):** PS with Net Pay Current printed 2,061.89.

### SBS: side-by-side blocks (SC-52)
Left heading at y 700: `Earnings` x 40, `Current` r 200, `YTD` r 270. Right heading at y 700: `Deductions` x 300,
`Current` r 460, `YTD` r 530. Rows from y 680, 16 pt apart:

| # | Left label | Left Current | Left YTD | Right label | Right Current | Right YTD |
|---|---|---|---|---|---|---|
| 1 | Regular | 2,500.00 | 32,500.00 | Federal Income Tax | 295.63 | 3,698.75 |
| 2 | Overtime | 187.50 | 1,125.00 | Social Security | 166.63 | 2,084.75 |
| 3 | Gross Pay | 2,687.50 | 33,625.00 | Medicare | 38.97 | 487.56 |
| 4 | | | | Total Taxes | 501.23 | 6,271.06 |
| 5 | Net Pay | 2,051.89 | 25,672.69 | 401K | 134.38 | 1,681.25 |
| 6 | | | | Total Pre-Tax Deductions | 134.38 | 1,681.25 |

**SBS expected:** EXP-PS with no hours or rate on any line.

### STK: stacked tables (SC-53)
Heading at y 700 as PS; rows 1 – 3 of PS from y 680. Title `Statutory` x 40 at y 620; then rows 4 – 7 of PS with their
amounts at right edges 400 (Current) and 500 (YTD), from y 604. Title `Voluntary` x 40 at y 524; rows 8 – 9 at the same
400/500 edges from y 508. `Net Pay` 2,051.89 25,672.69 at y 460, edges 400/500. No heading over the second table.

**STK expected:** EXP-PS (hours and rate on Regular and Overtime). Engine-level: two pay tables (the first with PS's
columns, the second with the 400/500 columns, holding rows 4 – 9); the rows Federal Income Tax, Social Security and
Medicare have section `Statutory`, 401K has `Voluntary`; `Statutory` and `Voluntary` are no rows.

### B1 and B2: columns the numbers don't settle (SC-61 b)
- **B1:** no heading. Rows from y 680, 16 pt apart: `Regular` 2,500.00 at right edge 430 only; `Relocation Bonus` 5,000.00
  at right edge 520 only; `Gross Pay` 2,500.00 (r 430) 5,000.00 (r 520); `Net Pay` 2,500.00 5,000.00. Each column's
  rows add up to its Gross Pay total, so both are pay columns (FR-57 b), and no row prints both, so (c) has no voting row:
  FR-59 guesses, a 0–0 tie, so the left column (r 430) is this period.
  **B1 expected:** C-lines `(Regular, earnings, 250000, null)`, `(Relocation Bonus, earnings, null, 500000)`; gross
  250000 / 500000; net 250000 / 500000.
- **B2:** no heading. Rows: `Regular` 1,000.00 (r 430) 2,000.00 (r 520); `Shift Premium` 300.00 / 150.00;
  `Bonus` 50.00 / 400.00; `Gross Pay` 1,350.00 / 2,550.00; `Net Pay` 1,350.00 / 2,550.00. Rows 1 and 3 vote for the left
  column as this period, row 2 for the right: FR-59 takes the left (smaller on more voting rows).
  **B2 expected:** C-lines `(Regular, earnings, 100000, 200000)`, `(Shift Premium, earnings, 30000, 15000)`,
  `(Bonus, earnings, 5000, 40000)`; gross 135000 / 255000; net 135000 / 255000. FR-22 (b) fires for Shift Premium
  (30000 larger than its year to date 15000): that line's this period is null and ambiguous and the stub needs review for
  that reason only.

### SB: summary box (SC-70)
Lines above as usual, the last at y 732. Box heading at y 712: `Gross Pay` r 200, `Taxes` r 280, `Deductions` r 370,
`Net Pay` r 460. y 696: `Current` x 40, 2,687.50 501.23 134.38 2,051.89. y 680: `YTD` x 40, 33,625.00 6,271.06 1,681.25
25,672.69. Then PS's heading at y 650 and PS rows 1, 2, 4, 5, 6, 8 from y 630 (no totals rows).
Worked by hand: 501.23 + 134.38 + 2,051.89 = 2,687.50 and 6,271.06 + 1,681.25 + 25,672.69 = 33,625.00; 2,051.89 is
the largest of the three on the Current row, so it is net.
- **SB-SHUF:** box columns in the order `Net Pay` r 200, `Taxes` r 280, `Gross Pay` r 370, `Deductions` r 460, headings
  kept, values moved with them.
- **SB-NOHEAD:** SB with no box heading line (columns in SB's order: gross, taxes, deductions, net).
**SB expected (all three):** EXP-PS lines and gross 268750 / 3362500, taxes 50123, deductions 13438, net 205189 /
2567269 (YTD taxes and deductions are not record fields).

### MINI: the stub used in files of several (SC-72 – SC-76)
For a stub starting at top y T with pay date D and multiplier n: `SYNTH PAYROLL CO` (T), `Pay date D` (T − 12),
`Currency USD` (T − 24), heading at T − 48 (`Description` x 40, `Current` r 430, `YTD` r 520), then from T − 64, 16 pt
apart: `Regular` 2,000.00 / 2,000.00 × n; `Gross Pay` 2,000.00 / 2,000.00 × n; `Federal Income Tax` 200.00 / 200.00 × n;
`Total Taxes` 200.00 / 200.00 × n; `Net Pay` 1,800.00 / 1,800.00 × n.
**MINI(n) expected:** C-lines `(Regular, earnings, 200000, 200000·n)`, `(Federal Income Tax, tax, 20000, 20000·n)`;
gross 200000 / 200000·n; net 180000 / 180000·n.
- **MINI-C:** the same with no YTD column and no `YTD` heading. Expected net 180000, gross 200000.

### GEN: the generator (SC-67)
Seeded (`SEED` fixed in `tests/paystub_engine_generator.py`), at least 100 files, covering every variation FR-70 lists;
each case carries its own expected pay lines, totals and split from its inputs.

## SC-50 — every value from its printed cell
Requirement IDs: FR-50, FR-57, FR-60, FR-61
Nondeterministic components: `local_model` with STUB-PS-SWAPPED.
Initial state: empty library; PS in the Inbox.
Actions/checkpoints:
1. Capture and read -> P-checks pass; one page, `embedded_text`.
2. Engine-level on the reading -> one pay table; columns: Hours r 260 role hours, Rate r 330 role rate, Current r 430
   role this period, YTD r 520 role year to date; rows 1, 2, 4, 5, 6, 8 are rows; rows 3, 7, 9, 10 are totals; no
   unplaced line; no note.
3. Extract -> run succeeded; C-lines(EXP-PS) and EXP-PS totals although the stub gave every amount swapped.
Expected final state:
- Database: one `income_records` row with EXP-PS values; six `income_lines`; C-money; C-auto.
- UI: the document page shows the pay stub with these values (as today's pay stub page).
Failure variants: the same PDF with every item's order shuffled in the content stream (as the existing native stub test
does) gives the same record.
Evidence: `pytest tests/test_paystub_engine.py tests/test_paystub_engine_record.py -k sc50`. C-docs; C-model-calls.

## SC-51 — two-line headings and totals lines
Requirement IDs: FR-52, FR-55, FR-61
Initial state: PS-2L. Stub: STUB-PS-SWAPPED.
Actions/checkpoints: Extract -> EXP-PS; engine-level: the Current column's labels are `This`, `Period`; Gross Pay is a
total in both amount columns and no row.
Expected final state: as SC-50. Evidence: `-k sc51`.

## SC-52 — side-by-side blocks
Requirement IDs: FR-53
Initial state: SBS. Stub: classes as EXP-PS, amounts swapped.
Actions/checkpoints:
1. Engine-level -> two pay tables on the same lines; the left holds Regular and Overtime (and the Gross Pay, Net Pay
   totals), the right holds Federal Income Tax, Social Security, Medicare, 401K (and its two totals); no row holds words
   of both blocks.
2. Extract -> SBS expected; C-auto.
Evidence: `-k sc52`. The existing `test_a_side_by_side_payslip_copies_every_line_and_total` passes unchanged (SC-64).

## SC-53 — stacked tables and section titles
Requirement IDs: FR-54
Initial state: STK. Stub: classes as EXP-PS, amounts swapped.
Actions/checkpoints: engine-level as STK expected; Extract -> EXP-PS; C-auto.
Evidence: `-k sc53`.

## SC-54 — a wrapped label and its evidence
Requirement IDs: FR-54, FR-66
Initial state: PS-WRAP. Stub: classes as EXP-PS, Federal's description `Federal Income Tax Withholding`, citing the
`Federal Income` line.
Actions/checkpoints:
1. Extract -> C-lines(EXP-PS) except Federal's description is `Federal Income Tax Withholding`; still six lines.
2. The Federal line's `locator.line_ids` lists the `Federal Income` line and the `Tax Withholding` line, in that order.
3. `provenance_for(db, "income_record", id, "net_pay")` cites the Net Pay line's `2,051.89` words (or its native cell);
   the Federal line's this-period evidence cites the word `295.63`.
4. Browser (opt-in): open the pay stub's page, choose the Federal line's source -> the page lights both lines' words.
Evidence: `-k sc54`; `tests/test_paystub_engine_browser.py -k sc54`.

## SC-55 — no headings, columns reversed
Requirement IDs: FR-50, FR-52, FR-57
Initial state: PS-NH. Stub: STUB-PS-SWAPPED.
Actions/checkpoints: engine-level -> the column at r 520 is this period, r 430 year to date (hours × rate and the
ordering both say so); no note. Extract -> EXP-PS, C-auto; no record note about columns.
Evidence: `-k sc55`.

## SC-56 — deposit and leave tables are set aside
Requirement IDs: FR-56
Initial state: PS-OTHER. Stub: classes as EXP-PS; `PaystubSummary` deposit splits as the printed ones.
Actions/checkpoints: engine-level -> two other tables (deposit, leave), no rows of theirs in a pay table, no unplaced
line. Extract -> C-lines(EXP-PS) (six lines, none from those tables); no unplaced or unclassified note; C-auto; the
deposit splits are the model's, as today (`details` deposit splits 155189 and 50000).
Evidence: `-k sc56`.

## SC-57 — YTD hours and an employer column are other
Requirement IDs: FR-57
Initial state: (a) PS-YTDH; (b) PS-EMP. Stub: classes as EXP-PS.
Actions/checkpoints:
1. (a) engine-level -> roles: r 220 hours, r 290 rate, r 370 this period, r 450 other, r 530 year to date. Extract ->
   EXP-PS (Regular's hours `80.00`, not `1,040.00`).
2. (b) engine-level -> the Employer column is other (it holds no total). Extract -> EXP-PS; 80.63 is in no amount.
Evidence: `-k sc57`.

## SC-58 — label digits
Requirement IDs: FR-51
Initial state: PS-DIGITS. Stub: classes with `PRE-TAX 401K` and `SECTION 125` as pre_tax.
Actions/checkpoints:
1. Engine-level -> the row labels are `PRE-TAX 401K` and `SECTION 125`; each row has exactly two amounts (Current, YTD).
2. Extract -> C-lines: EXP-PS's first five lines, then `(PRE-TAX 401K, pre_tax, 13438, 168125)`,
   `(SECTION 125, pre_tax, 8500, 110500)`; deductions 21938; net 196689 / 2456769; C-auto.
Evidence: `-k sc58`.

## SC-59 — a page with no pay table
Requirement IDs: FR-64
Initial state: a two-page PDF: page 1 = PS; page 2 prints at x 40 from y 780 the prose lines `Message from payroll`,
`Your employer HSA contribution this period was 50.00 and is not part of your net pay.` and the footer.
Stub: PS classes plus a `PayLines` entry `Employer HSA`, group `employer_paid`, current `50.00`, citing the page 2 line.
Actions/checkpoints: Extract -> C-lines(EXP-PS) plus a seventh line `(Employer HSA, employer_paid, 5000, null)` from the
model; C-note(`Page 2: no pay table was found in the printed columns, so its amounts are the reading's; check them.`);
the page 2 line is not an unplaced line; C-no-feature-review.
Evidence: `-k sc59`.

## SC-60 — an unplaced line and an unclassified row
Requirement IDs: FR-56, FR-62
Initial state: PS-SEC plus, below Net Pay, the line `Bonus advance memo` x 40 with `75.00` at right edge 600 (outside
every column). Stub: classes as EXP-PS **without** Medicare.
Actions/checkpoints:
1. Engine-level -> one unplaced line on page 1 with that text.
2. Extract -> C-lines(EXP-PS): Medicare is recorded as `(Medicare, tax, 3897, 48756)`, its group guessed from the `Taxes`
   title; C-note contains `Medicare`; C-note contains `Page 1` and `Bonus advance memo`; neither text in `issues`;
   C-auto (the checks hold).
Expected final state: six income lines; no "native table row(s) were not accounted for" note.
Evidence: `-k sc60`.

## SC-61 — guesses about the columns
Requirement IDs: FR-58, FR-59, FR-74
Actions/checkpoints:
1. (a) PS-SWAPHEAD, stub classes as EXP-PS -> EXP-PS (the numbers win); C-note contains `Page 1`, `YTD` and `Current`;
   C-auto. The record's guess list has one entry of the headings-overruled kind.
2. (b1) B1 -> B1 expected; C-note contains `Page 1` and `left column`; C-no-feature-review; the guess list has one entry
   of the columns-guessed kind.
3. (b2) B2 -> B2 expected; the guess note as (b1); `review_status` `needs_review` with FR-22's reason naming Shift
   Premium as its only reason; no issue about the columns.
Evidence: `-k sc61`.

## SC-62 — misprinted totals
Requirement IDs: FR-63
Actions/checkpoints:
1. (a) PS-BADTOTAL -> C-lines(EXP-PS); `taxes_minor` 51023 (the printed total, FR-61); C-note contains `Page 1` and
   `510.23`; C-auto.
2. (b) PS-BADNET -> C-lines(EXP-PS); `net_pay_minor` 206189; `review_status` `needs_review`; `issues` holds today's
   net-pay check issue (it starts `Gross pay less deductions and taxes` and contains `is not net pay`).
Evidence: `-k sc62`.

## SC-63 — engine failure
Requirement IDs: FR-65
Initial state: PS; the engine fault double.
Actions/checkpoints: Extract -> run succeeded; C-note(`The pay table couldn't be read from the printed columns, so the
reading's amounts were used; check them.`); today's path ran (the record's line cell evidence has `source` `pdf_text`,
as `test_native_paystub_reaches_ledger_search_and_source_cells` shows today); the log has one failure record naming the
exception class and no fixture text (`caplog`: no record contains `Regular` or `2,500.00`).
Evidence: `-k sc63`.

## SC-64 — nothing else changes
Requirement IDs: FR-67, FR-72
Actions/checkpoints, each passing unchanged:
- `pytest tests/test_table_engine.py tests/test_table_engine_record.py tests/test_table_engine_generator.py
  tests/test_statement_rebuild.py tests/test_statement_forms.py` (phase 1 and statements; the 200 generated statements
  give identical rows).
- `pytest tests/test_paystub_forms.py tests/test_paycheck.py tests/test_vision_tables.py tests/test_pdf_layout.py`.
- `pytest tests/test_layout_consumers.py`, except the test listed below.
- `pytest tests/test_evals.py` (the 48 existing cases keep their ids and answers).
**Tests this spec changes** (each with its requirement):
- `tests/test_layout_consumers.py::test_missing_native_rows_are_reviewed_and_blank_current_is_not_ytd` (FR-62): when its
  reading goes through the engine, the "2 native table row(s)" count note is replaced by the unclassified rows being
  recorded with a guessed group and a note naming each. Its blank-current assertion (current null, ytd 500.00) stays.
  If its `native_result` reading has no pay table for the engine, it stays unchanged; the implementation records which.
Any other test whose expected value changes is a defect against this contract, not a reason to edit the test.
Evidence: the commands above.

## SC-65 — version and existing records
Requirement IDs: FR-68
Initial state: two PS stubs captured and recorded under the previous `EXTRACTION_VERSION`
(`typed-extraction-v34-order-discounts`, or whatever the version is when this is built): one left undecided, one
confirmed through the review API.
Actions/checkpoints:
1. `EXTRACTION_VERSION` differs from the previous value.
2. Extract again on both -> the undecided one gets a new run (`reused: False`) read by the engine (EXP-PS); the confirmed
   one's record is byte-identical in `income_records` and `income_lines`.
Evidence: `-k sc65`.

## SC-66 — determinism
Requirement IDs: FR-69
Initial state: PS-SEC with SC-60's additions, and the MINI three-stub file of SC-72 (a).
Actions/checkpoints: Extract, then Extract again (same reading) on each -> identical `income_records` and `income_lines`
rows (ids included), notes, guess lists, evidence and `document_segments`; engine-level reads run twice give equal
results; C-model-calls.
Evidence: `-k sc66`.

## SC-67 — the generator
Requirement IDs: FR-70
Actions/checkpoints: every generated file is built with `make_pdf`, read, and recorded with stubs drawn from its inputs
-> every pay line, hours, rate and total exact; every file split into exactly its stubs; every stub's checks hold;
the run covers each FR-70 variation at least once (asserted from the cases' choices). A miss prints seed, index and
layout choices.
Evidence: `pytest tests/test_paystub_engine_generator.py`.

## SC-68 — evals, with guesses counted
Requirement IDs: FR-71, FR-74
Uses `tests/test_evals.py`'s pattern (`evals.run.run` on a synthetic corpus with `local_model`).
- `python -m evals.synthetic` writes the existing 48 cases unchanged plus five aligned pay stub files after them:
  one table with Hours/Rate/Current/YTD; stacked sections with no headings; side-by-side blocks with a summary box;
  two-line headings with a YTD-only row; a file of three stubs. Their answers come from their generator inputs.
- On those five, the engine records every pay value exactly and splits the three-stub file into three.
- `summary.json` has, for text-PDF pay stubs and for each reader (today's path and the engine): the share of pay values
  recorded exactly, stubs whose checks hold, stubs sent to review, files split right, and unplaced lines; and per guess
  kind, guesses made and guesses right. On the synthetic corpus every guess is right.
- `summary.json` still passes the report's allowlist (`evals/report.py`) and holds no description, amount or date.
- The engine's value is ≥ today's path's on each metric for the synthetic corpus.
Evidence: `pytest tests/test_evals.py -k paystub`.

## SC-69 — a row printed only under YTD
Requirement IDs: FR-57, FR-60
Initial state: PS-BONUS. Stub: classes with `Relocation Bonus` as earnings; amounts swapped, the bonus given as this
period 5,000.00.
Actions/checkpoints: Extract -> C-lines: EXP-PS's lines with `(Relocation Bonus, earnings, null, 500000)` after Overtime;
gross 268750 / 3862500; net 205189 / 3067269; no note about the bonus; C-auto.
Evidence: `-k sc69`.

## SC-70 — the summary box
Requirement IDs: FR-61, FR-75
Actions/checkpoints:
1. SB -> SB expected; engine-level: the box is found with columns gross, taxes, deductions, net and rows this period,
   year to date; no note.
2. SB-SHUF -> SB expected; no note.
3. SB-NOHEAD -> SB expected; C-note about taking the left of the two columns as taxes; the guess list has one entry of
   the summary-box kind.
All three: C-auto.
Evidence: `-k sc70`.

## SC-71 — the document page shows what the engine read
Requirement IDs: FR-76
Environment: opt-in browser test on the isolated test library (`served()`); synthetic records from SC-50 and SC-61 (b1).
Actions/checkpoints:
1. Open the SC-50 pay stub's document page and its source viewer's **Tables** tab -> one table from the engine (no
   `table_grid` table for page 1); its columns are marked This period, Year to date, Hours and Rate; ten rows as printed.
2. Choose the `2,500.00` cell -> the page view lights that word on page 1.
3. Open the SC-61 (b1) stub's Tables tab -> the guess note's text is shown beside its table.
4. The page loads no external resource (the CSP test the other browser tests use) and every amount shown is the server's
   text.
Evidence: `RUN_BROWSER_TESTS=1 pytest tests/test_paystub_engine_browser.py`.

## SC-72 — finding the stubs in a file
Requirement IDs: FR-80
Actions/checkpoints (each a fresh library):
1. (a) Three pages, MINI(11) dated 2026-06-05, MINI(12) 2026-06-19, MINI(13) 2026-07-03, each at T 780 -> three pay stub
   records, segments 0, 1, 2, with those pay dates and MINI(n) expected values.
2. (b) MINI(13) over two pages: page 1 holds its lines down to Gross Pay; page 2 repeats `SYNTH PAYROLL CO`,
   `Pay date 2026-07-03`, `Currency USD` and the heading, then Federal Income Tax, Total Taxes, Net Pay -> one record with
   MINI(13) expected values; no split note.
3. (c) One page: MINI(11) at T 780 dated 2026-06-05, MINI(12) at T 560 dated 2026-06-19 -> two records as in (a).
4. (d) A PNG whose vision stub transcribes MINI(11) then MINI(12) as lines (`Regular 2,000.00 22,000.00` …) -> two
   records with pay dates 2026-06-05 and 2026-06-19 and net 180000 each (values from the model stubs on the flat path).
Expected: `document_segments` holds one row per stub with its first and last line; every line of the file is in exactly
one segment. Evidence: `pytest tests/test_paystub_split.py -k sc72`.

## SC-73 — 26 stubs and their deposits
Requirement IDs: FR-81, FR-84
Initial state: a checking account with 26 deposits of +1,800.00 described `SYNTH PAYROLL CO DIRDEP`, one on each pay date
below. A 26-page PDF, one MINI-C per page, pay dates 2025-11-07, 2025-11-21, 2025-12-05, 2025-12-19, 2026-01-02,
2026-01-16, 2026-01-30, 2026-02-13, 2026-02-27, 2026-03-13, 2026-03-27, 2026-04-10, 2026-04-24, 2026-05-08, 2026-05-22,
2026-06-05, 2026-06-19, 2026-07-03, 2026-07-17, 2026-07-31, 2026-08-14, 2026-08-28, 2026-09-11, 2026-09-25,
2026-10-09, 2026-10-23.
Actions/checkpoints:
1. Extract -> 26 `income_records`, segments 0 – 25, each with its pay date, gross 200000, net 180000.
2. Each record has one proposed link in `transaction_income_links` to the deposit on its own pay date; 26 links, 26
   distinct transactions.
3. `calculate_cashflow` from 2025-11-01 to 2026-10-31: money in from these is 4,680,000 minor (each deposit once, no pay
   stub counted besides).
4. `GET /api/documents/{id}` -> no single amount; date 2025-11-07; filed under SYNTH PAYROLL CO and 2025-11-07.
Evidence: `-k sc73`.

## SC-74 — the split needs no review, and can be changed
Requirement IDs: FR-82
Initial state: SC-72 (a).
Actions/checkpoints:
1. After Extract -> each of the three records carries C-note(`Split from a file holding several pay stubs`); none has
   `needs_review` for the split (each is C-auto); `GET /api/documents/{id}/segments` shows three segments, not confirmed.
2. Browser (opt-in): the document page shows the file's three pay stubs with **Confirm split**, **Merge with next** and
   **Split here**; no warning that they wait in To check.
3. `PUT /api/documents/{id}/segments` with the first two stubs' first lines (Merge with next on stub 2) -> two segments;
   segment 0 still MINI(11)'s values.
4. Extract again -> still two segments (the user's split wins).
5. `POST /api/documents/{id}/segments/confirm` -> confirmed; the split note is gone from both records.
Evidence: `-k sc74`. (The merged segment's values are not asserted: see G3.)

## SC-75 — the segment migration
Requirement IDs: FR-83
Initial state: the previous-schema library with two income records (ids 1 and 2) and their lines.
Actions/checkpoints:
1. Start (upgrade) -> both records keep their ids, every column value and their lines; each is segment 0;
   `income_records` is unique by file and segment (a second segment-0 row for the same file is refused).
2. Extract a three-stub file (SC-72 a) twice -> the same three record ids both times.
Failure variant: the upgrade made to fail midway (as the existing migration-failure tests do) leaves the old schema and
data untouched and reports the failure (docs/documents.md "Schema upgrades and recovering from a failed one").
Evidence: `-k sc75`.

## SC-76 — a void stub
Requirement IDs: FR-85
Initial state: SC-72 (a) with the line `VOID` at x 40, T − 36 on page 2 (MINI(12)).
Actions/checkpoints: Extract -> three records; MINI(12)'s carries a note naming it void and adds nothing to money in;
`calculate_cashflow` for 2026-06-01 to 2026-07-31 counts 360000 minor from these stubs (MINI(11) and MINI(13)).
Evidence: `-k sc76`.

## Failure, retry and duplicate variants (across scenarios)
- **Retry after a failed run.** SC-72 (a) with the `PaystubSummary` stub failing for the second part on the first run
  (a model error) -> the run fails as runs fail today; Extract again with working stubs gives exactly three records, no
  duplicate segment.
- **Duplicate capture.** The SC-72 (a) file dropped into the Inbox twice -> one file (duplicate link, as today) and still
  three records.
- **Restart.** Extraction interrupted (process stopped) after reading and before publishing -> on restart the queued run
  resumes or is re-run as runs are today; the end state equals SC-72 (a).

## Traceability
| FR | Scenarios | Test file / command |
|---|---|---|
| FR-50 | SC-50, SC-55 | `tests/test_paystub_engine.py`, `tests/test_paystub_engine_record.py` |
| FR-51 | SC-58 | same |
| FR-52 | SC-51, SC-55 | same |
| FR-53 | SC-52 | same |
| FR-54 | SC-53, SC-54 | same; browser for SC-54 step 4 |
| FR-55 | SC-51 | same |
| FR-56 | SC-56, SC-60 | same |
| FR-57 | SC-50, SC-55, SC-57, SC-69 | same |
| FR-58 | SC-61 (a) | `tests/test_paystub_engine_record.py` |
| FR-59 | SC-61 (b1, b2) | same |
| FR-60 | SC-50, SC-69 | same |
| FR-61 | SC-50, SC-51, SC-62, SC-70 | same |
| FR-62 | SC-60, SC-64 | same; `tests/test_layout_consumers.py` |
| FR-63 | SC-62 | `tests/test_paystub_engine_record.py` |
| FR-64 | SC-59 | same |
| FR-65 | SC-63 | same |
| FR-66 | SC-54 | same; browser |
| FR-67 | SC-64 | phase 1 and statement suites |
| FR-68 | SC-65 | `tests/test_paystub_engine_record.py` |
| FR-69 | SC-66 | same |
| FR-70 | SC-67 | `tests/test_paystub_engine_generator.py` |
| FR-71 | SC-68 | `tests/test_evals.py -k paystub` |
| FR-72 | SC-64 | existing suites |
| FR-73 | — | Doc diff review at code review (not a test) |
| FR-74 | SC-61, SC-68, SC-70 | `tests/test_paystub_engine_record.py`, `tests/test_evals.py` |
| FR-75 | SC-70 | `tests/test_paystub_engine.py`, `tests/test_paystub_engine_record.py` |
| FR-76 | SC-71 | `tests/test_paystub_engine_browser.py` (opt-in) |
| FR-80 | SC-72 | `tests/test_paystub_split.py` |
| FR-81 | SC-73 | same |
| FR-82 | SC-74 | same; browser step |
| FR-83 | SC-75 | same |
| FR-84 | SC-73 | same |
| FR-85 | SC-76 | same |

## Gaps (the spec leaves these open; not invented here)
- **G1 Where the Tables tab gets the engine's tables.** FR-76 says what the page shows, not which API carries it (the
  reading's `layout_context` today comes from the reading alone, before the document's kind is known). SC-71 tests the
  page; the plan picks the API and adds an API-level check for it.
- **G2 Names in `summary.json` and of guess kinds.** FR-71 and FR-74 name the metrics, not their keys. SC-68 asserts the
  metrics are present and allowlisted; the plan names the keys and the guess kinds (at least: headings overruled,
  columns guessed, group guessed, summary box columns guessed, split changed by the user).
- **G3 Values of a merged segment.** FR-82 doesn't say what a stub merged from two stubs records (it prints two net pays).
  SC-74 asserts only the segment count and that the user's split wins.
- **G4 What "prints VOID" covers.** FR-85 doesn't say whether VOID must be a line of its own or a word anywhere (a
  "void after 90 days" check notice would match a word rule). SC-76 uses a line of its own; the plan should choose the
  narrower rule.
- **G5 Note wording.** The spec gives exact wording only for the FR-64 and FR-65 notes and the split note; other notes are
  checked by the facts they must name (page, line text, headings, value).
