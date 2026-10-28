```yaml
slice: SL-02
result: ready_for_verification_with_escalation   # all checks pass; two plan rules were repaired/extended to reach contract values, see escalations
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: fd0c65a
end_head: 5e82e70              # the code commit; this handoff is committed on top of it in a second commit
commit: 5e82e70
changed_files:
  - src/home_manager/documents/table_engine.py        # extent/cuts, continuation, line classes, unplaced, rejections
  - tests/table_engine_fixtures.py                    # NB amended (n4, 674.80); OR and CS-split added
  - tests/test_table_engine.py                        # NB xfail and its companion removed; SL-02 tests added
  - plans/pdf-table-engine/handoffs/slice-SL-02.md    # this file
checks:
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py -k \"sc08 or sc09 or sc10 or rejected or section_titles or one_row_continuation or description_above\" -q"
    exit_code: 0     # 69 passed, 120 deselected
  - command: ".venv/bin/python -m pytest tests/test_table_engine.py -q"
    exit_code: 0     # 189 passed
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py tests/test_statement_rebuild.py -q"
    exit_code: 0     # 218 passed, 2 warnings, 225 s; unchanged tests
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks: [mypy, browser tests, test_table_engine_record/generator/evals (not written yet), anything outside the four commands above]
escalations:
  - id: ZONES-X-T
    summary: "Plan P3/P4 zones (extent and half-gap reach) can't produce statement-accounts X's x2 (unplaced) and x3 (more than one amount), or T's t1 (12.34 stays an amount). Implemented bound_by_headings; needs plan approval."
  - id: P5.7-CRITERION
    summary: "P5.7 as written can't read its own fixture WR-above (every row but the last has a text line directly below its date line: the next row's description). Implemented a repaired criterion; needs a plan amendment."
  - id: CURRENCY-PARAM
    summary: "FR-16's currency rejection ('The amount \"4.00 EUR\" is not in USD.') needs the statement's currency, which P2 says the engine doesn't have. Added optional read(result, currency=None); None leaves the code on the token."
```

## What was built (all in `documents/table_engine.py`, pure, no `finance/` import)
- **First step.** NB now has n4 `11/25/2026 SYNTH REFUND` with 50.00 in B and ending balance 674.80; the strict xfail and the "column A alone" test are gone. NB rows pass.
- **Segments (P6 extent).** A page is cut at a single-run text-only title at or left of the date column that names a balance, totals or summary (`balance(s)`, `total(s)`, `subtotal`, `summary`) and sits directly above a line with a date or an amount (heading-like lines in between are skipped). Each segment is one table. BL gives main / daily; `Fee summary` gives no table (no dated lines). A heading line is never a title or an end, so a repeated heading is ignored.
- **Continuation (FR-06, P4).** Per segment, `continuation` tries the previous page's tables, latest first: offset = median difference of the date column's left edge; most rows must have their dates and at least one amount at a column's edge + offset within `ALIGN` (any of left, right, centre edge, because K's equal-width balances tie to "right" on page 1). One-row pages use the same path (`OR`). A row amount that fits no column makes a **new column of the table** only when the page repeats the table's exact heading text and ≥2 rows (or 1 row + its heading label) support it. K3 needs this: page 1 prints no deposits, so its table has no Deposits column until page 2. Labels are re-read from the heading's runs after a column is added (`Open.relabel`), so page 1's "Deposits" label moves off Balance. A page with a different heading (CC page 2) is its own table. One `EngineTable` spans its pages (`pages=[1,2,3]`); `continues` stays None; `row.page` and `row.row` (1-based per page, candidates counted) say where a row is; `table_id` is the first piece's id.
- **Line classes.** Balance words (opening/beginning/previous/starting, closing/ending/new, with `balance`) + exactly one readable amount: inside a table (amount fits a zone) → a **candidate**: the row stays in `table.rows` with `row.candidate = "opening"|"closing"` and an `Anchor(inside_table=True)` is added to `table.anchors`; outside every table, on any page with a layout → `reading.summary_anchors` (dated or not; new `Anchor.dated`). Values are signed `Decimal`s (minus / parentheses negative). Total lines (`total`, `subtotal`, no date, amount fits a zone) → `table.totals`. Both are in reading order; SL-03 picks first opening / last closing and decides candidates by the balance column. Candidate numbering stays in `row.row`; SL-03 renumbers for messages.
- **Unplaced (FR-08).** After a page is read: every line on a page with a table that holds a date token and an amount token and is not cited by a row, rejected row, anchor or total → `Unplaced(page, first layout line id, visual-row text, "no_column")`. `pending` is SL-03's.
- **Rejections (FR-16), today's texts, today's order** (amount-column rules, date, blank description, amount): `More than one amount sits in the {label} column.`; `Text that is not an amount sits in the {label} column.` (text wholly inside an amount zone, in a run that starts outside the description zone); `The date "…" is not a real date.` (a date-shaped word, e.g. `02/30/2026`, in the date zone on a line with an amount; the row gets no date and no carried date); `The description is blank.` (transactions tables only); `The amount "…" can't be read.`; `The amount "…" is not in USD.` (only with `currency`); `No amount is printed.` / the joined-amount text for a dated line with no amount (SL-01). Labels now exist before rows are read (SL-01 printed `unlabelled`). Not in the engine, because they need roles or the currency's precision: "both a debit and a credit", too-much-precision, and the unreadable-amount rule is applied in every amount column (P3 limits it to money columns; SL-03 can clear it for `other` columns).
- **Kinds.** Decided over all of a table's rows after the last page: transactions if ≥ half the non-candidate rows have a description; else balance when one amount column; else other. Native reader tables that no row, anchor or total cites are in `other_native_tables` (account-import X's summary and fee tables).
- **Section titles.** A single run of text between rows labels the rows below it until the next title, carried onto the same table's continuation pages; a title needs a row below it on the same page, so a footer is never a title (CS and PD, `CS-split`).
- **Rule 7.** Descriptions above amounts: see escalation.

## Tests (`tests/test_table_engine.py`, 189 pass; SL-01's 112 unchanged except NB)
K3 (one table, pages 1-3, repeated heading no row, 6 pt offset), BL (candidates, totals, daily balance table, fee lines, identity), WF dated summary anchors, summary anchors for 15 fixtures, UP (one unplaced line quoting its text), the FR-08 identity for **every** fixture in the registry against hand counts (lines counted from the printed words, not the engine), WR-split (one row citing two lines, memo line rejected with its reason), WR-above, X (x1 row, x2 unplaced, x3 - x6 rejected with today's reasons, also compared with `pdf_import.analyze`'s), T and T-edge, blank description, text in an amount column, section titles (CS, PD, carried, footer), one-row continuation, native tables listed as other.
**Identity for BL in this slice:** the two schedule lines on page 2 are rows of the table they continue (the schedule needs the period, SL-03). The test asserts rows 5 + anchors 2 + other 3 = 10; the contract's "5 other-table rows" is reached in SL-03 when those two move.

## Escalations
1. **ZONES-X-T.** With the plan's zones (outermost zone = extent ± half the median gap, or `LONE_REACH` for a lone column): T's `12.34` (x 272) is outside every amount zone (the amount zone starts near x 335), so t1 is rejected, but SC-15 needs `1234`. X's x2 (`100.00`, centre 440.8) falls inside a zone ending 465 when `LONE_REACH` = 4, so it is a row; with `LONE_REACH` = 2, x2 is unplaced but x3's `REF` falls into the description zone by 0.3 pt, so `55.55` is joined text and x3 is not rejected. No single reach gives both. What gives all three, and what the old spans were: bound the **first amount zone's start** by the midpoint between the previous heading label and its own label (T: 270), and the **last zone's end** by the midpoint between its own label and the next label (X: Balance at 470 → 441.5). `bound_by_headings` does this only when a heading is printed and only moves the outer ends. Because the description zone then ends earlier (WR's wrapped line runs to x 283 past the heading-based 245), description tests use `in_description` (first word starts in the description zone; no word reaches the first amount column's extent). All 112 SL-01 tests still pass. **Decision for the user/orchestrator:** approve this (amend P4's zones), or amend the contract (T's t1 rejected; x2/x3 as the plan's zones give them). The change is isolated in `bound_by_headings` and `in_description`.
2. **P5.7-CRITERION.** The plan's criterion ("every row's date line has a text-only line directly above it and no row's date line has one directly below") fails on WR-above, because the next row's description is directly below the previous date line. Implemented: ≥2 rows, every row's date line has a text-only description-zone line directly above it (the first row's included, so a text line sits between the heading and the first row), and the **last** row's date line has none below it. Normal wrapped tables fail the first-row test (the heading is above it); CS's titles are in the date zone, not the description zone. Please amend P5.7.
3. **CURRENCY-PARAM.** `read(result, currency=None)`: additive. SL-03 may pass the currency or apply the check itself from `token.value[2]`.

## Deviations and notes for later slices
- Added fields (additive): `EngineRow.candidate`, `Anchor.dated`. `Anchor.inside_table` True means a candidate whose row is also in `table.rows`. `EngineReading.period_lines` is still empty (period is SL-03).
- Not implemented from P6: a mid-page cut "at a line with a different column set that starts a run of ≥ 2 rows". Cuts are titles only (and a different column set on the next page is a new table: CC). A run of ≥2 rows with new columns in the middle of a page becomes extra columns of the same table (when ≥2 rows support them). If SL-03/SL-04 shows a miss, add it here.
- Cut titles do not seed the new table's first section (`Daily ending balance` is not the daily rows' section); the schedule's `Payment schedule` is (it sits directly above the first row on page 2).
- `bound_by_headings` narrows the description zone for headed tables only; headless tables keep the plan's zones. WF and WF-bare read the same rows.
- The page-offset match accepts any of left, right, centre. A column's `align` stays what page 1 chose (K's Balance says `right`).
- Docs: nothing written (docs/documents.md is SL-05; it should say what ZONES-X-T decides).

## Open issues
- ZONES-X-T and P5.7-CRITERION need a decision before SL-03 relies on them.
- The mid-page "different column set" cut above.
