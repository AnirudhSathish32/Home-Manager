# Pay stub columns on photos: keep this period beside year to date
Feature: paystub-columns
Amends: specs/document-forms (approved, built 2026-10-18; its approval and plan are unchanged by this file)

<!-- Approval state lives in approvals/<slug>.json and is bound to this file's content hash.
     Do not add a Status line: changing it would change the hash. Check with gate.py. -->

## Goal / users / scope / non-goals

**Goal.** A photographed or scanned pay stub keeps the amounts the model reads correctly, including when a row prints
its this-period and year-to-date amounts side by side and no table was validated. The protection against a value from
the wrong column moves from blanking every such row to the document-forms guards (FR-22) plus a column-position check.

**Users.** The household user who photographs or scans a pay stub and reviews it on the document page.

**In scope:**
- Pay stub readings from images and scanned PDF pages, where the vision model reported no validated table.
- Summary amounts (gross and net pay, this period and year to date) and pay lines, on those readings.
- Rows printed in one column only, such as a bonus paid in an earlier period.
- Digits inside a line's label ("401k", "403(b)", "Section 125").

**Non-goals:**
- Readings with a validated table (vision or native PDF cells). Code keeps copying amounts from cells there, unchanged.
- Native PDF text with positions. Cells already resolve columns there.
- Other document types.
- Reading positions from the image: no geometry pass, and no second vision call.
- Existing records: no bulk re-reading (as document-forms D5).

## Existing behavior (verified paths, assumptions, unknowns)

**Verified** (`src/home_manager/documents/extraction.py` at commit 50154b6):
- Every vision reading stores `vision_tables` (`{"version": 1, "origin": "reported", "tables": []}` when no table was
  found). Seen on the test instance's `pay-stub.png`.
- `read()` sets `has_table_contract` when `vision_tables` is not None (`:2512`), so every photographed pay stub runs
  `anchor_paystub` (`:2515`), even with no tables at all.
- With no validated row for a line, `anchor_paystub` sets current and year to date to null when any cited line prints
  more than one number (`:775`, note "Pay line N has multiple amounts without a validated source row"). The same holds
  for summary amounts (`:799`, "… has multiple amounts without a validated source cell").
- The count uses `NUMBER.findall` on the whole line, label included, so "401k 184.98" counts two numbers.
- document-forms recorded this as existing, intended behavior ("A cited line with several numbers and no validated row
  is set to null and goes to review", its "Existing behavior"). The fixtures there avoided it on purpose (P-flat prints
  one amount per line).
- Reproduced through the extraction entry point: `tests/test_paystub_forms.py::test_a_photo_stub_keeps_this_period_beside_year_to_date`
  (strict xfail).
  - With the model answering every value correctly, gross, net, Regular and Federal income tax are all null, and only
    the relocation bonus's year-to-date 5,000.00 is kept.
  - This matches the user's report (2026-10-19): only a relocation bonus, already paid in an earlier period, was
    recorded, and the rest was empty. That stub was not inspected.
- document-forms FR-22 (`this_period_guards`) already rejects a this-period value that is labelled year to date, is
  larger than its year to date, or equals it after the first pay period. It runs after `anchor_paystub`, in
  `normalize`, on every path.

**Assumptions:**
- A1. Photographed stubs print a column header line naming both columns (Current / This period, and YTD / Year to
  date), usually once above the rows. Where none is printed, there is no column order to check.
- A2. In a row, amounts appear in the same left-to-right order as the header's column words.

**Unknowns:**
- U1. How often the live model swaps columns on such rows. It's measured by the eval tasks (FR-38), not asserted.

## Functional requirements

| ID | Observable requirement | Acceptance criterion |
|---|---|---|
| FR-31 | Cell anchoring for a pay stub runs only when the reading has at least one validated table. A reading that supports tables but found none is read like flat text. | A photographed stub whose `vision_tables` has no tables gets no "multiple amounts without a validated source row/cell" note. A stub with a validated table keeps today's cell copy (document-forms 20-f, SC-21 and the existing table tests pass unchanged). |
| FR-32 | On a stub read like flat text, a line or summary amount that prints both columns keeps the model's this-period and year-to-date values, when each is printed in its cited line (today's citation check). FR-22 then judges them, unchanged. | SIDE_BY_SIDE with correct answers: gross 2,500.00, net 2,250.00, Regular 2,500.00 / 32,500.00, Federal income tax 250.00 / 3,250.00, all kept. |
| FR-33 | **Column position.** When the stub prints a header line holding both column words (Current/This period and YTD/Year to date), and a line prints exactly as many amounts as the header names columns, the model's this-period value must be the amount in the this-period position, and its year-to-date value the one in the year-to-date position. Otherwise both values become null and ambiguous, with a note naming the line ("Pay line N: this period and year to date don't match the printed columns"). Header columns other than amounts (Hours, Rate) count by position too. When the counts differ, the check is skipped and FR-22 alone applies. | SIDE_BY_SIDE with Regular answered swapped (32,500.00 / 2,500.00): Regular is null and ambiguous with the note, and the stub needs review. A header "DESCRIPTION HOURS RATE CURRENT YTD" with "REGULAR 80.00 31.25 2,500.00 32,500.00" maps 2,500.00 to this period. |
| FR-34 | **Label digits aren't amounts.** Numbers inside a line's label (digits joined to letters, or inside parentheses: "401k", "403(b)", "Section 125") don't count as the line's amounts, for FR-33 and for any check that counts a line's amounts. | "PRE-TAX 401K 184.98 2,404.74" counts two amounts. On a validated-table reading, a "401k \| 184.98 \| 2,404.74" row keeps 184.98. On flat text, "401k 184.98" (one column printed) keeps 184.98 where the model put it, unless FR-35 applies. |
| FR-35 | **A row printed in one column only.** On a stub whose header names both columns, a line that prints one amount keeps it where the model put it only when it is year to date. A this-period value on such a line becomes null and ambiguous, with the note "Pay line N prints one amount; check whether it is this period or year to date". When the stub prints no such header, the model's choice is kept and FR-22 applies. | SIDE_BY_SIDE's "RELOCATION BONUS 5,000.00" answered as year to date: kept as YTD 5,000.00, this period null, no note. Answered as this period: this period null and ambiguous with the note, and the stub needs review. |
| FR-36 | A stub where FR-33 or FR-35 fired never counts automatically. Correcting the line with Edit details clears the note, as for other fields (document-forms FR-23). | After correcting the swapped Regular line in FR-33's case, its note clears; other notes stay. |
| FR-37 | The extraction version changes, so readings made before this change aren't reused. | `EXTRACTION_VERSION` differs from `typed-extraction-v23-document-forms`; a parse with only a v23 run gets a new run. |
| FR-38 | The `document_forms` eval task gains a photographed-layout pay stub fixture (both columns on one line, no table), and reports per fixture: values kept, values blanked, and wrong-column values that would count automatically. | With stubbed correct answers on that fixture, the report shows every value kept, none blanked, and wrong-column 0. |
| FR-39 | Docs: `docs/money.md` "Money in and paystubs" describes what a photographed stub keeps and checks. The document-forms "Existing behavior" bullet stays as the historical baseline, superseded by this spec. `text_extraction_plan.md` notes the change. | Doc diff present. |

**Superseded:** this spec replaces the document-forms "Existing behavior" bullet "A cited line with several numbers and
no validated row is set to null and goes to review (`:608`, `:631`)", for readings with no validated table. It stays
true where a validated table exists but the cited row isn't in it. document-forms FR-22 and FR-23 are unchanged and now
carry the wrong-column protection on these stubs.

## Invariants, privacy, security and data retention
- **Nothing is invented.** Kept values are the model's, each printed in its cited line (today's check). No value is
  moved, swapped or calculated by code. A value that fails FR-33 or FR-35 is null, never replaced by the other column's
  amount.
- **This period and year to date stay apart.** FR-22's guards run after these rules, unchanged. A stub where any of
  FR-22, FR-33 or FR-35 fired never counts automatically.
- **Nothing leaves the machine.** No new model call, no extra vision pass.
- **Development data.** Synthetic fixtures only. The user's failing stub is reproduced only by the user (document-forms
  FR-24 rules).
- **Existing records** keep their values until read again. A stub read under the old rule needs **Extract again** to
  recover its amounts; reviewed records aren't rewritten (document-forms D5, FR-12).

## Errors, recovery, duplicates, restart behavior
- **Header ambiguous** (several header lines with different column orders, or column words only partly printed) → the
  FR-33 position check is skipped, with no note; FR-22 applies.
- **A line holding two rows side by side** (earnings on the left, deductions on the right) prints more amounts than the
  header names columns → FR-33 is skipped for that line, FR-22 applies, and its values are kept only when each is
  printed in its cited line.
- **Reading again** follows document-forms: corrections re-apply, guards and FR-33/FR-35 notes fire again on the model's
  values, then your corrections clear theirs.

## Nondeterministic outputs and how they are verified
- Model answers are fixed stub replies keyed by schema name (`tests/model_server.py` `by_schema`). No test asserts live
  output.
- Live behavior is measured by the `document_forms` eval task (FR-38) on synthetic fixtures, and by the user on their
  own stub (only `summary.json` shared).

## Scenarios

Fixture SIDE_BY_SIDE (as in `tests/test_paystub_forms.py`), a vision reading with an empty `vision_tables`:
`SYNTH WORKS`, `EARNINGS STATEMENT`, `PAY DATE 2026-07-03`, `PAY PERIOD 2026-06-15 TO 2026-06-28`, `CURRENCY USD`,
`DESCRIPTION CURRENT YTD`, `REGULAR 2,500.00 32,500.00`, `RELOCATION BONUS 5,000.00`, `FEDERAL INCOME TAX 250.00 3,250.00`,
`GROSS PAY 2,500.00 37,500.00`, `NET PAY 2,250.00 34,250.00`.

| ID | FR IDs | Initial state | User/API actions | Expected final DB/files/UI state |
|---|---|---|---|---|
| SC-28 | FR-31, FR-32 | SIDE_BY_SIDE; the stub answers every value correctly; the bonus as year to date only. | Extract. | gross 250000, net 225000; Regular 250000/3250000; Federal 25000/325000; Relocation bonus null/500000. No "multiple amounts" note. The existing strict-xfail test passes (its mark removed). |
| SC-29 | FR-33, FR-36 | SIDE_BY_SIDE; Regular answered swapped (32,500.00 / 2,500.00). | Extract; then correct Regular's this period to 2,500.00 and year to date to 32,500.00. | Regular null and ambiguous, with the column note (FR-22 b also names it); `needs_review`. After the correction the column note clears and the line holds 250000/3250000. |
| SC-30 | FR-33 | SIDE_BY_SIDE with the header `DESCRIPTION HOURS RATE CURRENT YTD` and `REGULAR 80.00 31.25 2,500.00 32,500.00`; correct answers including hours 80.00 and rate 31.25. | Extract. | Regular 250000/3250000 kept; hours × rate checks (document-forms FR-21). |
| SC-31 | FR-35, FR-36 | SIDE_BY_SIDE; the bonus answered as this period 5,000.00 (the user's report). | Extract. | Relocation bonus this period null and ambiguous with the one-amount note; `needs_review`. Its year to date is null (the model didn't give one). |
| SC-32 | FR-34 | (a) SIDE_BY_SIDE plus `401K 184.98 2,404.74`, answered correctly; (b) a validated-table stub with `401(k) \| 184.98 \| 2,404.74`. | Extract each. | (a) 401k kept 18498/240474 with no note. (b) 18498 from the cell, as today. |
| SC-33 | FR-31 | Fixture P-table (document-forms) and the existing table and native PDF suites. | Extract. | Unchanged: SC-21 and 20-f pass, and `test_vision_tables`, `test_pdf`, `test_layout_consumers` pass. |
| SC-34 | FR-32, document-forms FR-22 | SIDE_BY_SIDE where every this-period answer copies its row's year to date (document-forms 20-e on this layout). | Extract. | Every this-period value null and ambiguous through FR-22 (and FR-33 on the two-amount rows); `needs_review`; never verified. |
| SC-35 | FR-37 | A parse with only a v23 run. | Extract. | New run (`reused: False`). |
| SC-36 | FR-38 | The new eval fixture with stubbed correct answers. | Run `document_forms`. | Report row: values kept, 0 blanked, wrong-column 0. |
| SC-37 | FR-39 | Change implemented. | Review `git diff docs/ text_extraction_plan.md`. | Docs updated as FR-39 says. |

## Out of scope / product decisions requiring approval

**Decisions taken in this spec (recommended defaults; approving the spec accepts them):**
- **D18.** The wrong-column protection on photos is FR-22 plus FR-33, not blanking. It prefers keeping printed values
  and sending doubtful ones to review over dropping everything.
- **D19.** A one-amount row (FR-35) on a stub with both column headings is kept only as year to date. That costs a
  review for a row genuinely paid only this period with no YTD printed (rare: YTD includes this period), in exchange
  for never counting a prior-period bonus as this paycheck. That was the user's report.
- **D20.** Column positions come from the printed header line's words and the line's amount order only. No image
  geometry.

**Domain risk candidates (not in scope; accept or reject each):**
1. **Two rows on one line** (earnings and deductions side by side in two blocks).
   - *If unhandled:* FR-33 is skipped and FR-22 alone judges.
   - *Recommended:* accept as is, and add an eval fixture to measure it.
2. **Multi-line headers** ("Current" on one line, "Period" under it).
   - *If unhandled:* no header is recognized, so FR-33 and FR-35 don't run.
   - *Recommended:* treat a header split over two adjacent lines as one, if the eval shows it's common.
3. **Negative or parenthesized adjustments** ("(50.00)" in the current column).
   - *Recommended:* count them as amounts by position, as now; document-forms domain risk 7 covers their meaning.
4. **Hours and rate printed for this period but not year to date** (the header names HOURS RATE CURRENT YTD, and the
   line has YTD only).
   - *If unhandled:* counts differ, so FR-33 is skipped.
   - *Recommended:* accept.
5. **Old records read under the blanking rule** (gross and net empty).
   - *Recommended:* add a one-line note on the pay stub page when its last reading predates FR-37, offering **Extract
     again**. The alternative is nothing, since D5 rules out bulk re-reading.
