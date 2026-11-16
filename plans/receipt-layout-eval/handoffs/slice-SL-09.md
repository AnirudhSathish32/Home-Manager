```yaml
slice: SL-09
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 82145d5
end_head: 5942a3b   # the code commit; the handoff commit follows it
commit: 5942a3b
checks:
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_reading_formats.py tests/test_reading_format_capture.py tests/test_vision_layout.py tests/test_receipt_layouts.py tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py"
    exit_code: 0   # 464 passed, 1 skipped (baseline capture); run after the last code edit
  - command: ".venv/bin/ruff check evals/layout_grading.py tests/test_receipt_layout_task.py"
    exit_code: 0
escalations: []
```

## Per finding

**R4-1 (tie on a split), fixed, `evals/layout_grading.py` `Aligner.supported(whole, parts, tie=False)`.** Policy as decided: a tie goes to the reading that fails the case.
`receipt_layout.grade` requires `no_split_rows`, `no_merged_rows`, `no_missing_rows` (and amounts, indents); extra lines are not required, so whole + extra can pass
while split fails. Split (1 row : k lines) calls `supported(..., tie=True)` and accepts `together <= alone`; merge (k rows : 1 line) keeps strict `<`, so a tie is whole + missing
(missing fails, as merged does) and R3-2's deleted heading ("Tea" / "Tea with lemon $3.95") stays missing 1. Policy is a comment on `supported` and in `docs/evals.md`
("A tie must fail the case"; the "truncated row beside a one-character row is still merged" line is corrected: "Baguette"+"X" read "Baguet X" merges, "Baguette"+"e" read "Baguett e" ties and is not merged).
- (a) rows ["$","3.95"], lines ["$","$3.95"]: now split 1, extra 0 (case fails).
- (b) rows ["Baguette"],["e"], line ["Baguett e"]: whole 1 + missing 1 (unchanged; fails).
- Expectation changed: `test_a_line_deleted_after_a_split_pieces_that_repeats_it_is_extra_not_a_split` is renamed `test_a_line_that_repeats_a_split_pieces_is_a_split_because_a_tie_must_fail_the_case`;
  `["Tea with lemon $3.95"]` read `["Tea","Tea with lemon $3.95"]` is now (whole 0, split 1, merged 0, missing 0, extra 0) (was whole 1 + extra 1), commented as a tie counted as split by policy.
  The reverse order (`["Tea with lemon $3.95","Tea"]`) is out of order, not a tie, and stays whole 1 + extra 1. No other test expectation changed.
- Regressions: `test_a_noisy_short_piece_never_passes_as_one_whole_row_with_an_extra_line` ((a), (b), R3-2 heading),
  `test_a_short_edge_cell_read_alone_and_again_in_a_noisy_row_never_passes` (24 cases; every multi-cell row whose first or last cell is 1-2 characters, itemized 11 rows, fuel 2 rows). Both confirmed to fail with the old strict `<` on splits.
  Existing sweeps (exact splits, adjacent merges, noisy splits, deleted rows, prefix pairs, fuzz) pass unchanged.
- **Limit worth the reviewer's eye:** for a LAST short cell the literal sweep order ("short cell alone, then the full text") is out of order against the row (the short cell belongs last), so it is a plain extra line and still passes as whole + extra,
  e.g. row ["Pump","11"], lines ["zump 11","11"] or ["11","zump 11"] -> whole 1 + extra 1. That is the existing "extra lines don't fail" design, not a tie, so I did not widen the policy. The sweep for last cells therefore uses the
  mirror that can be a tie: the full text with its last character off, then the short cell (["zump 1","11"] -> split). Only first-cell rows follow the literal order.

**R4-2 (stretches cost), fixed.** `stretches` is gone; `Aligner.earliest_end(part, text, start)` is one semi-global edit distance (free start at any column >= start, last row gives the earliest end within budget; nonempty stretch),
cached on (part, text, start); `Aligner.budget(part)` holds the unchanged budget (exact for <=2 chars, max(1, floor(HELD*len)) otherwise); `in_order` keeps the earliest-end greedy. New counter `Aligner.cells` (table cells filled by the search).
Tests: `test_the_earliest_end_of_a_stretch_is_what_trying_every_stretch_finds` (3,000 seeded random pairs with repeats and edited near-duplicates of the part inside the text, random start, versus brute force over every (begin, end);
both outcomes covered), `test_merging_adjacent_near_duplicate_rows_of_long_labels_costs_a_bounded_amount_of_work` (150 rows, 48-char labels, adjacent pairs merged: 75 merged, no missing/extra; `cells <= 50M`
(31.4M measured), evaluations <= 60,000 (43,665 measured), wall clock < 40 s as a secondary guard).

Timings (150 near-duplicate rows, adjacent pairs merged, this machine):

| label length | before | after |
|---|---|---|
| 24 chars | 8.0 s | 2.8 s |
| 48 chars | 48.7 s | 10.1 s |

Honest note: the 48-char case is not under ~10 s on a wall clock alone (10.1 s), which is why the test bounds work, not time. What remains is mostly the pre-existing `near`/`supported` edit distances
(`lev`, ~75% of the profile), plus ~30M cells of `earliest_end`; I tried cutting `supported`'s `lev` calls with limits and it gave no gain, so left it as it was.

Untouched: spec, plan, approvals, progress.yaml, `tests/reading_format_data`. Full suite not run.
