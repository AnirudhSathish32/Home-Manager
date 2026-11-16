```yaml
slice: SL-08
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: a647594
end_head: 4ae7640   # the code commit; the handoff commit follows it
commit: 4ae7640
checks:
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reading_formats.py tests/test_reading_format_capture.py tests/test_vision_layout.py tests/test_receipt_layouts.py tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py"
    exit_code: 0   # 437 passed, 1 skipped (baseline capture, needs CAPTURE_READING_BASELINE=1); run after the last code edit
  - command: ".venv/bin/ruff check evals/layout_grading.py src/home_manager/documents/vision_layout.py tests/test_receipt_layout_task.py tests/test_vision_layout.py"
    exit_code: 0
escalations: []
```

## Per finding

All three **fixed**. New regression tests were confirmed to fail on the previous `layout_grading.py` (22 failures) / `vision_layout.py` (5 failures).

**R3-1 (greedy in_order), `evals/layout_grading.py`.** `find` is replaced by `stretches(part, text)` (every start/end whose edit distance
to the part is within its budget: exact for 1-2 characters, `max(1, floor(HELD*len))` from 3) and `in_order` is now a feasibility search over
all of them: a part may start only at or after the end of the one before, and as only that end matters to the next, taking the *earliest*
end of every part's candidates is optimal (a repeated word, or a misread piece that also occurs exactly later, can no longer strand the rest).
Exact-first and the `(previous[j], -j)` endpoint are gone. Result is a bool; the cost preference stays in the alignment DP (`near` + `EXTRA_PIECE`).
Tests: `test_a_split_row_with_a_misread_piece_that_reads_exactly_later_is_one_split_row` (a), `test_a_merged_row_with_a_truncated_piece_is_one_merged_row_and_not_a_missing_one` (b),
`test_a_misread_split_piece_that_reads_exactly_inside_a_later_one_takes_its_own_place` (c; the real row is "9 Duct Tape 5.75 51.75" in itemized/angled/1, price misread "1.75", which is inside the total),
sweep `test_a_split_row_whose_misread_piece_reads_like_a_later_piece_is_still_one_split_row` (24 cases; piece misread by one substitution into a window of a later piece; only itemized/angled/1 has such a row, so also)
`test_random_misread_splits_and_merges_of_repeated_words_are_never_mistaken_for_missing_or_extra` (seeded fuzz, 400 draws, repeats-heavy vocabulary, split and merge). The existing misread-split sweep still passes. Ad hoc: 6 seeds x 1,500 draws with 2-5 cells, 0 failures.

**R3-2 (heading deleted before a row repeating it), same file.** New `Aligner.supported(whole, parts)`, required for every k:1 merge and 1:k split
beside `in_order`: the whole must differ from the joined pieces by *fewer* characters (spaces removed) than from any single piece paired 1:1
with the other pieces charged as missing/extra at their length, which is how the grader's own `distance` would charge that pairing.
So a merge must rest on characters 1:1 cannot explain; a tie rejects (a deleted row always ties or loses; a genuine merge wins by at least
the other row's length). Commented in code and `docs/evals.md`. Tests: `test_a_row_deleted_before_a_row_that_repeats_it_is_missing_in_every_position_of_the_repeat`
(reviewer's "Tea with lemon", "Iced Tea", "Green Tea Large", plus "Tea", "Sweet Tea", "Tea Tea"; deleted -> missing 1, merged 0; also with both lines present and truly shared line -> merged),
`test_a_line_deleted_after_a_split_pieces_that_repeats_it_is_extra_not_a_split` (mirror), sweep
`test_deleting_a_row_that_is_a_prefix_of_the_next_is_missing_and_never_merged_but_really_sharing_a_line_is_merged` (24 cases, every adjacent pair made prefix/extension; delete first -> missing 1, merged 0; both on one line -> merged 1, missing 0).

**R3-3 (stray length counted handwriting), `src/home_manager/documents/vision_layout.py`.** The short-text criterion now joins the row's printed cells only
(as the extent already did). Tests: `test_a_handwritten_note_beside_a_short_stray_does_not_make_the_stray_a_margin` parametrised over strays ("x", "x2", "-") and notes of 1 to 54 characters (includes the reviewer's x2 + scribble).

## Timing
Grading all 24 drawn cases, every multi-cell row split into cells: 0.52 s total, 0.08 s worst case (old grader 0.41 s); with one substitution per piece (noisy): 0.57 s total, 0.08 s worst. The 90-row evaluation-count bounds in the existing test still hold.

Docs: `docs/evals.md` (margin rule wording; split/merge evidence now "ordered and apart" + "better than one alone"). `tests/reading_format_data`, spec, plan, progress.yaml untouched. Full suite not run.
