```yaml
slice: SL-08
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 1e5a909
end_head: 4c8d3cb   # the fix's commit; this handoff is committed on top of it
commit: [4c8d3cb]
changed_files:
  - src/home_manager/documents/pay_tables.py   # wide_heading rewritten (geometry); new run_pieces shared with heading_runs; tables_cut takes view
  - tests/test_paystub_cleanup.py              # 3 new tests + helper section_title_is_no_cut; the `table_engine_fixtures` import gains `width`; no existing test edited
  - docs/documents.md                          # "Rows" bullet states the cut rule; one new "Known limits" bullet
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py -q"
    exit_code: 0   # 982 passed, 2 warnings in 372.74s (log /tmp/claude-fv/sl08-verify.log)
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -q -k r3 with pay_tables.py stashed (1e5a909 code)"
    exit_code: 1   # all 3 new tests FAIL at 1e5a909 (3 failed, 27 deselected)
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -q -k r3 (fix applied)"
    exit_code: 0   # 3 passed
  - command: ".venv/bin/ruff check src scripts tests evals"
    exit_code: 1   # only the 2 pre-existing errors (tests/test_document_v2_browser.py, tests/test_receipt_kinds.py:977 F402)
  - command: ".venv/bin/python -m pytest /tmp/claude-fv/review_r2_assertions.py -q -p no:cacheprovider"
    exit_code: 0   # 2 passed (both failed at 1e5a909)
escalations: []   # one deviation from the approved wording, explained under "Deviation" below; no requirement or contract changed
```

## Rule built (FR-92 f, FR-89)
`tables_cut(view, bl, starts)` (now takes the page view) cuts at a line after a totals line when `is_heading_like(line)` (two or more runs; unchanged) or
`wide_heading(view, bl, position)`. `wide_heading` no longer counts words. A one-run all-text line is a heading for the cut when:

1. the next non-empty line is a pay line (unchanged);
2. **(b)** the line does not start in the label column: its first word's left edge is more than `ALIGN` (0.75) font sizes right of the pay line's label
   (first word of its first run). A title at the label column never cuts, whatever its length (R2-1 long title);
3. **(a)** every amount of that pay line has a unit of the line of its own (a backtracking assignment; a word serves at most one amount):
   - a **piece** over it: `run_pieces(view, run)` splits the run where the gap between words exceeds `view.size / 2` (new helper; `heading_runs` now calls it
     with its zones, so P0 and this share one piece rule); a piece takes all its words and matches by horizontal overlap with the amount; or
   - a **word** aligned with it: one edge (right, left or centre; the same edge for every word-matched amount) within `ALIGN` font sizes.

A continuous title is one piece, so it can serve one amount; a second amount needs a word aligned to it by the same edge, which a centred title almost never
has. "Used Balance" (gap 22 > size/2 = 10) is two pieces, each over a leave amount: it cuts, with or without a "Leave" title line above it.

## Deviation from the approved wording, and why
The approved rule tested (a) on **pieces only**. That breaks the existing `test_sc91_f_a_leave_table_under_a_one_run_heading_is_a_table_of_its_own`
(R1-2, "Accrued Vacation Used Leave Balance", printed at one pitch with gaps of 0.33–0.37 size, so it is ONE piece over THREE leave amounts; and the
`one_run` probe). No piece-only rule can tell it from a continuous title centred over two columns, since both are one piece over several amounts and both
start right of the label. The minimal adjustment: a word aligned with an amount by an edge also counts as a unit of its own (the heading's words sit at the
amounts' right edges: 299/299, 434/439, 573/579 at 20pt, tolerance 15), with two guards that keep titles out: the same edge for every word-matched amount,
and no word counted for two amounts (a piece overlapping one amount takes all its words). Probe check: the 4-word centred title "Before Tax Deductions
Withheld" at the reviewer's x=310 and 360 does not cut (second amount has no unit).

## Known limit (documented in docs/documents.md "Known limits")
A section title that starts right of the label column and whose words line up by one edge with each amount below (the 4-word "Before Tax Deductions
Withheld" centred over two columns shifted by 0 or -15 units; with a shift of +15, +30, -30 or -40, or "Pre Tax Deductions" at any shift tried, it does not) is still cut:
the row below it goes to its own table or is unplaced with the note (1e5a909 cut these placements too, as it cut every such title; fe54dae did not). It cannot be
told geometrically from the R1-2 heading. Escalate only if you want that gone at the price of R1-2's test.

## Tests (tests/test_paystub_cleanup.py, additions only)
- `test_sc91_f_r3_a_long_section_title_in_the_label_column_does_not_cut_the_block` (R2-1): the 11-word title at x=40, one table Regular / Overtime / Vision,
  literals 2,000.00/24,000.00, 150.00/900.00, 6.00/6.00, roles current/ytd, totals Total Earnings, no unplaced, no other table.
- `test_sc91_f_r3_a_centred_section_title_over_both_columns_does_not_cut_the_block` (R2-1): "Pre Tax Deductions" centred over the two columns and shifted
  -30, and "Before Tax Deductions Withheld" shifted -40 (a placement that is not a known-limit one); same assertions.
- `test_sc91_f_r3_a_leave_table_under_a_two_word_one_run_heading_is_a_table_of_its_own` (R2-2): "Used Balance" with and without the separate "Leave" title;
  pay rows Base Pay 2,662.41 and Retro Pay 225.58, totals Total Earnings / Net Pay, other table rows Vacation / Sick, nothing unplaced.
- Fails at 1e5a909: all three (pay_tables.py stashed): 3 failed. Pass with the fix: 3 passed.

## Probe outputs (/tmp/claude-fv/sl08-probes.log)
- `review_r2_long_title.py`: both titles (404.6 and 474.63 wide) NOW = one table Regular, Overtime, Vision (6.00, 6.00), unplaced [] (identical to BEFORE).
- `review_r2_short_heading.py` (copy `sl08_short_heading.py`/`sl08_edges.py`/`sl08_compare.py`, because the original calls `wide_heading(bl, i)`; only that
  debug call changed to `wide_heading(view, bl, i)`): both variants: tables [Base Pay 2,662.41, Retro Pay 225.58], other [[Vacation, Sick]], unplaced [];
  `wide True` for the one-run "Used Balance", `wide False` for the two-run "Leave | Used Balance" (is_heading_like cuts it).
- `review_r2_assertions.py`: 2 passed.
- `review_paystub_tables_cut.py`: original, one_run, two_runs all: tables [Base Pay, Retro Pay] with 2,662.41 / 225.58; other [Vacation, Sick].
- `probe_title.py`: "Deductions", "Pre Tax Deductions", "Before Tax Deductions Withheld" each one table Regular, Overtime, Vision with the literals.
- `sl08_edges.py` (reviewer's edge cases): title-x-40/310/360 keep Vision in the table, unplaced []; two-word-gap-8 and -20 and leave-integers read the
  pay table with Retro Pay; `pay-integers` and `details-under-*` as before.

## Open issues
- The known limit above (a 4-word title whose words line up by one edge with both amounts).
- The reviewer's `review_r2_short_heading.py` and `review_r2_edges.py` call `pay_tables.wide_heading(bl, i)`; the signature is now `(view, bl, position)`.
- Ruff: only the 2 pre-existing errors.
