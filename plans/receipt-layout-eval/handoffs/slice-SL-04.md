```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: fa898d8
end_head: a2fea832eacc32357e9c73fd86e704b46ce02358   # the code commit; the handoff commit follows it
commit: a2fea832eacc32357e9c73fd86e704b46ce02358
changed_files:
  - evals/layout_grading.py            # new (P8)
  - evals/tasks/receipt_layout.py      # new (P12, P14)
  - evals/tasks/__init__.py            # receipt_layout appended last
  - evals/tasks/report.py              # measured-only tasks out of decision_rows, leaderboard sums and the schema comparison
  - evals/graders.py                   # failure_kind: `truncated` (P13)
  - evals/receipt_layouts.py           # parse_amounts now imported from layout_grading (one definition)
  - tests/model_server.py              # optional state["finish_reasons"]
  - tests/test_eval_tasks.py           # oracle branch, wrong-answer line, P14 test
  - tests/test_evals.py                # failure-kind table rows
  - tests/test_receipt_layout_task.py  # new
checks:
  - command: ".venv/bin/python -m pytest tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py tests/test_receipt_layouts.py tests/test_vision_layout.py -q"
    exit_code: 0   # 189 passed (the shell pipe to `tail` hid pytest's own status; the summary line reads "189 passed", no failures, no skips)
  - command: ".venv/bin/ruff check evals tests/test_receipt_layout_task.py tests/test_eval_tasks.py tests/test_evals.py tests/model_server.py"
    exit_code: 0
  - command: ".venv/bin/python -m pytest tests/test_layout_consumers.py -q"
    exit_code: 0   # 17 passed; run because it imports evals.tasks
escalations: []
```

## What was done
- **`evals/layout_grading.py`** (P8, pure). `grade_reading(expected, output) -> counts`, `Aligner`, `normalize`, `split_cells`, `box_overlap`, `parse_amounts`. Alignment is anchors, then a banded DP (±15 lines around the proportional diagonal) with 1:1, 1:k split, k:1 merge (k ≤ 3, +0.05 per extra piece), skip a row and skip a line (1.0 each), nothing paired above 0.5. Then the price-after-a-side-line check (a 1:1 row whose line lacks a cell that an unpaired line within 3 lines holds becomes a split and that line is no longer extra), then out of order (a row left missing that sits on an unpaired line at ≤ 0.3). The edit-distance cost is counted in `Aligner.evaluations` and returned as `evaluations`. It is 0 on a perfect dining case, and 11–14 thousand on the four `long` cases with every row split in two (bound 60,000).
- **Counts returned**: `rows, lines, whole, sole, split, merged, missing, extra, out_of_order`; `amounts, amounts_read, amounts_on_row, amounts_wrong, amounts_missing`; `indent_reported` and `indented_*` / `edge_*` (rows, right, wrong, unknown); `cells_reported`, `cell_rows`, `cell_rows_match`; `position_reported`, `align_rows`, `align_right`, `handwritten_expected/reported/correct`; `distance`, `characters`, `cer`; `usable_share`, `overlap`.
- **`evals/tasks/receipt_layout.py`** (P12, P14). `NAME="receipt_layout"`, `ROLE="vision"`, `VERSION="receipt-layout-v1"`, `PROMPT_VERSION=VISION_VERSION`, `MEASURED_ONLY=True`. `cases()` is the 24 drawn cases (input `{family, condition, index}`, expected = `answers(...)`, tags `[family, condition]`; cached, each call returns a new list). `run` draws to a temp PNG and returns `{format, lines, rows, spans, notes, text, table_issue}`. `grade` returns the counts as `checks` plus the required booleans (`no_split_rows`, `no_merged_rows`, `no_missing_rows`, `amounts_on_their_rows`, `indents_right`); the score is the mean of whole-row share, amounts-on-row share, indent share (left out when not reported) and 1 − CER. `report_lines` writes "### Reading formats": per format a rows/amounts table with denominators and 95% Wilson intervals, a "Positions the model reported" table, then rows read whole and amounts on row by family and by photo condition, with "(few)" under `MIN_CELL`. The format of a result line is the reading's own `output["format"]`, else `reading_format`, else the candidate's `@format` suffix, else `v7-lines` (SL-05's labels will fill the middle one).
- **P13** in `graders.failure_kind` (before the failed-attempt branch): an error containing "final response was incomplete or truncated", or a last failed attempt with category `invalid_or_truncated_output` and `params.max_tokens == 16384`, is `truncated`. "Model response was incomplete or truncated" at 8,192 stays `other`.
- **P14** in `evals/tasks/report.py`: `measured_only()` lists the tasks with `MEASURED_ONLY`; `decision_rows` leaves them out of `mine` (so `runs`, `valid`, `money_errors`, `pass_all`, `scores`, `p95` come from the other tasks alone; a candidate that ran only measured-only tasks gets no decision row). The leaderboard's "valid of runs" and the schema-comparison sums leave them out too; the task still has its own table and column. The report says so under the task.
- **`tests/model_server.py`**: `state["finish_reasons"]` (one per request, popped before `finish_reason`).
- **Tests** (`tests/test_receipt_layout_task.py`, 66 tests): grader units for SC-02 (one split row; amount read, not on its row), the price after a side line (one split, no extra), SC-03, SC-04, SC-05, out of order, extra lines and a missing row, `v6-text` indent "not reported", an unknown indent, FR-16 (one missed handwritten flag lowers recall only), FR-17 (per-axis scaled exact boxes → 1.0, shifted → < 0.9, usable share), a `layout-text` row written with " | ", the shared amount rule, the cost bound by count; `build_rows` on the exact drawn boxes of all 24 cases (shuffled), and with each axis scaled differently (SC-06, SC-07), and the 0–1000 frame through the grader (overlap 1.0); SC-01 for each of the four formats through `run_one` under `reading_format(f)`; per format, `finish_reasons` "length","length" on the main call → `truncated`, a rescue that runs out → `truncated`, a budget retry that succeeds → ok, a blank answer → "Model response was blank."; the report section with denominators; and a `run_tasks` run with `transcription` + `receipt_layout` and with `receipt_layout` alone. `test_eval_tasks.py` has the oracle (a perfect spans-shaped reading), the wrong-answer line and the P14 test (every `receipt_layout` case failing or erroring leaves `runs`, `valid`, `p95`, money errors, scores and pass_all as the other task's alone). `test_evals.py` has the three new `failure_kind` rows.

## Deviations from the plan (local, within the spec)
1. **Anchors are runs of at least two equal rows** (`ANCHOR_RUN = 2`), not every equal row. With single equal rows as anchors, a split row's left half that repeats another row's text ("ORGANIC BANANAS", "No Allergies") pinned the wrong pair and wrecked everything between (a fully split 99-row case read 58 rows missing). With runs, the same case reads 99 split, 0 missing; the perfect-answer count stays 0.
2. **Merged count.** SC-03 says two rows on one line are "1 merged row", so `merged` counts k − 1 rows per shared line. The first row of a shared line is counted in `whole` (so `whole + split + merged + missing = rows`) but not in `sole` (alone on a line), and only `sole` rows are graded for amounts on row, indent, cells, alignment and handwriting.
3. **CER** is taken from the alignment (edit distance of each paired group's joined texts, plus the length of each missing row and each extra line, over the printed characters) instead of one edit distance over the whole text, which would take seconds on a 3,600-character case.
4. **SC-04 direction.** The spec reads "48.85 for 49.85", but the fixture prints 48.85 (subtotal), so the test reads "49.85" for it; the counts are the same.
5. **`parse_amounts` moved** to `evals/layout_grading.py` (and `MONEY` with it); `evals/receipt_layouts.py` imports it back, so `from evals.receipt_layouts import parse_amounts` still works and SL-03's tests are untouched. `import re` left that file.
6. **`evals/tasks/report.py` also drops measured-only tasks** from the leaderboard's "valid of runs" and the schema-comparison sums (the plan names `decision_rows`); without it a candidate failing every `receipt_layout` case would show a lower valid count in the leaderboard than the decision used.
7. Cells are reported only by `layout-text` and `spans` (v6 rows are one cell each); alignment, handwriting and boxes only by `spans`. A row's handwriting is graded on rows whose cells match.

## Notes
- `row builder` constants needed no tuning: `build_rows` on all 24 drawn cases (shuffled, and with each axis scaled differently) reproduces every case's rows, indents and alignments with no notes.
- SL-05 needs: `reading_format` and `prompt_version` on result lines (then `format_of` reads `line["reading_format"]`), `tokens` and `budget_retry`, and no-ranking for format runs. `decision_rows` still skips only `schema_enforced is False`; a candidate with only `receipt_layout` results already gets no decision row.
- The DP runs in about 0.05 s on a 99-row split case; grading all 24 oracle cases is instant.

## Open issues
None.
