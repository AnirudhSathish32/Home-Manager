```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0707b6652b00603f549d60e946fc1e3fb18d19d1
end_head: 73ee8823dffd6026e9ca5ce45eaee2a3a067419f   # the code commit; the handoff commit follows it
commit: 73ee8823dffd6026e9ca5ce45eaee2a3a067419f
checks:
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reading_formats.py tests/test_reading_format_capture.py tests/test_vision_layout.py tests/test_receipt_layouts.py tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py"
    exit_code: 1   # first run: 3 failures in test_evals.py caused by finding 1's first draft (`split` is also a status count); fixed, see below
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_evals.py"
    exit_code: 0   # 42 passed after the fix; the other six files had passed in the first run (306 passed with the 3 failures)
  - command: ".venv/bin/ruff check <changed evals/src/tests files>"
    exit_code: 0
escalations: []
```

## Per finding

1. **Fixed.** `check_summary` checks an enum key's value (a str in the allowed set) before recursing; scoped to the top-level
   `format`/`split` and to `reading_format`, because `split` is also a status count deeper down. `summary()` copies `reading_format`
   only when it is a str in `READING_FORMATS`, else raises. Tests: `test_an_enum_key_holds_only_one_allowed_string_never_a_nested_value`
   (dict, list, int, bool, None, unknown string) and the dict/list/int/bool cases added to
   `test_a_format_run_summary_holds_only_the_format_label_and_never_a_seeded_private_value` (through `rebuild`).
2. **Fixed.** `vision._scope_lock` (RLock) is held for the whole `reading_format` block; `active_format()` takes only `_format_lock`.
   Test: `test_scopes_in_two_threads_run_one_after_another_and_leave_the_default` (fails before; checks each scope saw its own format, a
   worker thread inside sees it, default afterwards). Default v7 path untouched; capture tests pass.
3. **Fixed.** All exact matches anywhere are reserved for all rows first; wrong-digit spares come from what remains. Test
   `test_an_amount_read_exactly_on_another_rows_line_is_not_taken_as_that_rows_wrong_digits`. **Result differs from the brief's guess:**
   Apple $1.00 / Coffee $2.00 read as $2.00 / $3.00 gives amounts_read 1 (Coffee's $2.00, elsewhere), wrong 0, missing 1. Apple's
   own line holds only the $2.00 that Coffee's exact match consumed, so there is no spare left to call wrong. Counting it wrong too
   would count one printed amount twice. A plain wrong digit (Apple $1.50) still counts wrong.
4. **Fixed.** `indent_reported` is True for v7-lines, layout-text and spans, False for v6-text; unlabelled output falls back to
   "any indent present". Test `test_a_format_that_reports_indents_but_lost_them_all_does_not_pass` (dining as spans, every box unusable:
   all unknown, case not passed). The task's `indents_right` already used the counts, so no task change was needed.
5. **Fixed.** A split needs `holds(piece, row)` for every line piece, a merge `holds(row, line)` for every row; and the joined text
   must be within HELD (0.3), not PAIRABLE (0.5), of the other side (needed so rows 18%/20%/22% suggested tip, which differ by a
   few characters, don't absorb a deletion). Tests `test_a_deleted_short_row_is_missing_and_never_merged_into_its_neighbour` and the
   24-case sweep `test_deleting_any_one_row_counts_one_missing_row_and_nothing_else`: no exceptions (missing 1, merged 0, split 0, extra 0
   for every row of every case).
6. **Fixed.** `MOST_PIECES` is now 4 and `align` takes `most = max(4, largest cell count)`. This changes the plan's `MOST_PIECES = 3` in
   favour of FR-13 (dining's suggested-tip rows have four cells). Tests `test_a_row_of_four_cells_split_into_its_four_cells_is_one_split_row`
   and the 24-case sweep `test_splitting_any_multi_cell_row_into_its_cells_counts_one_split_row_and_nothing_else`: no exceptions.
7. **Fixed.** `whole = len(sole)`; the `sole` key is gone (it was the same number), task uses `whole`. `docs/evals.md` already said
   "on one line of their own". The accounting identity whole+split+merged+missing=rows never held for merges (merged counts k-1), and the
   SC-03 test that asserted it now asserts `(whole, rows) == (26, 28)` (dining with subtotal and tax merged).
8. **Fixed.** `edge_left` is the leftmost row's start (`min`), not the 10th percentile. Test
   `test_one_main_row_followed_by_side_rows_leaves_the_side_rows_indented`. All 24 drawn cases still build exactly. Trade-off: one
   stray box left of the margin by 1+ character now indents every other row; unusable boxes are already excluded before this.
9. **Fixed (small change).** 4 or 5 usable pieces now search slopes up to ±0.06 (about 3.4°; `FEW_SLOPE_LIMIT`), 6+ keep ±0.15, fewer than 4
   stay level. The limit keeps `test_a_few_pieces_are_read_level` (a title and a price 4 text heights apart) from merging. Test
   `test_a_two_row_receipt_tilted_a_little_is_still_two_rows` (0, ±2.5, ±3°). Documented in `docs/evals.md`. Two or three pieces tilted are still read level.
10. **Fixed.** `output_characters = len(output text)` in `receipt_layout.grade`, as the transcription task does; asserted in
    `test_the_exact_rows_in_each_formats_shape_pass_with_every_count_perfect` for every format. Not added to the report table.
11. **Fixed.** The assertion is now `(amounts, amounts_read, amounts_missing, amounts_wrong) == (18, 17, 1, 0)`.

Also: `docs/evals.md` updated (splits/merges, money, indent, spans margin and tilt). Regression tests were each confirmed to fail on the
old code (checked by reverting the code file only). `tests/reading_format_data` untouched. Full suite not run.
