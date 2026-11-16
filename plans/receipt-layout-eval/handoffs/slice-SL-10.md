```yaml
slice: SL-10
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 8a23014
end_head: 5e4d339   # the code commit; the handoff commit follows it
commit: 5e4d339
checks:
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reading_formats.py tests/test_reading_format_capture.py tests/test_vision_layout.py tests/test_receipt_layouts.py tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py"
    exit_code: 0   # 515 passed, 1 skipped (baseline capture); run after the last edit (2m38s)
  - command: ".venv/bin/ruff check evals/layout_grading.py tests/test_receipt_layout_task.py"
    exit_code: 0
escalations: []
```

## Per finding

**R5-1 (anchored rows skip the split tie rule), fixed, `evals/layout_grading.py` `Aligner.split_anchored`.** `align` still pairs anchor runs 1:1, then
`split_anchored` looks at each anchored row: for k = 2..most and every window of k contiguous lines that contains the row's line and whose other lines are unpaired,
the same test `gap` applies (`near(row, joined) <= HELD`, `in_order`, `supported(tie=True)`) makes it a candidate split, cost `step + EXTRA_PIECE*(k-1)`.
Candidates are taken cheapest first, each line once, so a line beside two anchored rows goes to the one it fits best (the row before and the row after
can both see it).
- Reproduction: rows ["Tea with lemon $3.95"], ["Orange juice"], ["End of receipt"], lines "Tea", row 1, ... now (whole 2, split 1, extra 0), as the isolated case. itemized/clean/0 with "4" before "4 Wood Screws Box 6.40 25.60" now counts split.
- Merge side: nothing to change, not code. An anchored line equals its row, so for a neighbouring unpaired row `together = lev(line, row + other) >= len(other) = alone`: a merge needs strict `<`, so a tie at an anchor is always whole + missing. Tested (deleted heading "Tea" before an anchored "Tea with lemon $3.95" run: whole 3, missing 1).

**R5-2 (`earliest_end("", ...)`), fixed.** An empty part returns `start`, as `in_order` skips an empty part. Test `test_a_part_that_is_empty_ends_where_it_starts`.

### Sweep numbers (24 cases, every row, every cell, before and after the row's line)
- 2,976 insertions in total: 399 are ties for their own row (the reviewer's 399; `test_the_sweep_has_every_tie_in_it` pins it): all now split 1, whole N-1, extra 0, and the case fails. Counts equal grading the row alone with the inserted line.
- 2,550 other insertions (27 more are neighbour ties, below): whole N + extra 1, no other change; the row alone gives the same.
- **27 insertions are not the row's own tie but a tie for the NEIGHBOURING row** (e.g. grocery/faded/1: "10.99 F" before "OLIVE OIL 500ML 10.99 F" is also a tie for the row above, "CHEDDAR BLOCK 5.99 F", whose price is two edits from it; return/blurred/1 "(35.00)" before "RETURN Wool Throw (35.00)" with "(24.00)" above; long/clean/0 ...). The same lines graded alone for the neighbour are a split (that is the existing `gap` rule, pre-existing looseness of `in_order`'s budget), so the case counts split 1 and fails: ambiguous, so fails, as the policy says. The sweep therefore expects a split when the line is a tie for either the row beside it or the row on its other side. The first version of the test (own row only) failed on exactly these 27 (and 14 where `near > HELD` makes the isolated rule say no, so the sweep predicate includes `near <= HELD`, as the grader does).
- Unrelated lines: "Xylophone Quartz" and "qq" before and after each row, 3,400 readings (1,700 per string): all whole + extra 1.
- New tests (all in tests/test_receipt_layout_task.py): `test_a_cell_repeated_as_a_line_beside_its_anchored_row_counts_exactly_as_it_does_alone` (24 cases), `test_the_sweep_has_every_tie_in_it`, `test_an_unrelated_line_beside_any_row_stays_one_extra_line` (24 cases), `test_a_split_row_inside_a_run_of_equal_rows_is_split_and_a_merge_tie_there_stays_missing`, `test_a_part_that_is_empty_ends_where_it_starts`. With the old `layout_grading.py`, 26 of these fail. No existing test or sweep changed.
- Sweep run time: ~7 s for the new tests (48 cases) together.

### Timing (150 near-duplicate rows, 48-char labels, adjacent pairs merged; `test_merging_adjacent_near_duplicate_rows...`)
10.06 s now, 10.1 s in SL-09: no slowdown (`split_anchored` only runs on anchored rows, with cached distances; this test has no anchors).

Docs: `docs/evals.md` "A tie must fail the case": two sentences that a row inside a run of equal rows and lines follows the same tie rule.

Untouched: spec, plan, approvals, progress.yaml, `tests/reading_format_data`. Full suite not run.
