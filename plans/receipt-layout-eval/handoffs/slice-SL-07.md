```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: b80b099
end_head: 96c82cf   # the code commit; the handoff commit follows it
commit: 96c82cf
checks:
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reading_formats.py tests/test_reading_format_capture.py tests/test_vision_layout.py tests/test_receipt_layouts.py tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py"
    exit_code: 0   # 368 passed, 1 skipped (the baseline capture, needs CAPTURE_READING_BASELINE=1); run after the last code edit
  - command: ".venv/bin/ruff check evals/layout_grading.py src/home_manager/documents/vision_layout.py tests/test_receipt_layout_task.py tests/test_vision_layout.py"
    exit_code: 0
escalations: []
```

## Per finding

1. **Fixed** (`evals/layout_grading.py`). Split/merge evidence is now ordered and non-overlapping: `Aligner.find` looks for a part from the
   end of the previous one (exact first, else the closest stretch within `max(1, floor(HELD*len))` edits for pieces of 3+ characters;
   pieces of 1-2 characters (`SHORT_PIECE`) must be exact), `Aligner.in_order` chains them. The combined-distance cutoff (`HELD`) stays.
   A misread piece of 1-2 characters is therefore no evidence (that row reads whole with an extra line); documented in `docs/evals.md`.
   Tests: `test_a_misread_split_row_is_still_one_split_row_and_not_two_whole_ones` (the two reviewer examples), the 24-case sweep
   `test_splitting_any_multi_cell_row_into_misread_cells_is_still_one_split_row` (one substituted character per piece of 3+ chars, a
   non-digit where there is one; split 1, missing/extra/merged 0), `test_split_pieces_and_merged_rows_may_not_share_characters`.
2. **Fixed** (same change). Tests: `test_a_heading_deleted_before_a_row_that_repeats_it_is_missing_and_never_merged` (reviewer example, plus the
   two real orders), the sweep `test_deleting_a_row_whose_text_is_inside_another_row_counts_it_missing_and_never_merged` (24 cases,
   292 repeated-text rows), and the existing every-row deletion sweep still passes. Failing tests were confirmed to fail on the old grader.
3. **Fixed** (`vision_layout.py`). The margin is the leftmost *printed* row's start; a row's extent is its printed cells' (handwriting only
   when a row has none). A lone printed row under `STRAY_CHARS` (3) characters or narrower than `STRAY_WIDTH` (2) character widths, with no
   other printed row starting within `INDENT_GROUP_GAP` of it, is skipped. `middle`, `edge_right` and every row's offset use the same extents.
   A longer stray printed word still sets the margin (cannot be told from a main row followed by deeper ones; commented in code and docs).
   SL-06's "one main row then ten side rows" test still gives 0 then 1s; all 24 drawn cases still build exactly (test_receipt_layouts passes).
   Tests: `test_one_stray_short_box_left_of_the_margin_does_not_indent_every_main_row[False/True]` (printed and handwritten "x"),
   `test_a_stray_handwritten_word_left_of_the_margin_does_not_set_it_however_long`, `test_a_stray_row_that_is_not_short_still_sets_the_margin`,
   `test_short_rows_starting_together_in_the_margin_still_set_it`.
4. **Fixed** (`vision_layout.py`). For 4-5 pieces a non-zero searched slope is kept only if `tilt_supported`: at least `FEW_ROWS` (2) rows of
   two or more pieces spanning `FEW_SPAN` (10) character widths, every neighbouring pair within the row tolerance (`SLOPE_ROW`) once tilted;
   otherwise level. SL-06's two-row tilted tests (0, ±2.5°, ±3°) pass. Tests: `test_a_title_and_a_price_four_text_heights_below_are_not_one_tilted_row`
   (the CAFE example), `..._above_...` (mirrored), `test_five_pieces_in_one_row_of_two_are_read_level`.

Other: regression tests for 3 and 4 were confirmed to fail on the old `vision_layout.py` (5 failures; the five-piece one passes on both).
`docs/evals.md` updated (split/merge evidence, margin, tilt); `docs/documents.md` has no passage on these rules, so unchanged.
`tests/reading_format_data` untouched. Full suite not run.
