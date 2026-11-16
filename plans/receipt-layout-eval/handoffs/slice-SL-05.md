```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 64f249a
end_head: 71af223f6c7e9bbf81b8ef9ecbfec1fa1ba744e9   # the code commit; the handoff commit follows it
commit: 71af223f6c7e9bbf81b8ef9ecbfec1fa1ba744e9
changed_files:
  - evals/run.py                  # check_formats, format_variants, format_context, token/budget helpers, run(formats=), dry-run lines, labels
  - evals/tasks/runner.py         # run_tasks(formats=), run_one(candidate), vision-only default tasks, --formats
  - evals/tasks/report.py         # format variants not ranked, "not ranked" leaderboard cell, budget-retry line
  - evals/report.py               # summary reading_format (allowlist + enum), decision_rows skip, format_run/format_decision
  - evals/tasks/transcription.py  # output "format", spans table cases "not produced"
  - evals/models.toml             # comment naming --formats
  - tests/test_eval_tasks.py      # SC-11 and related
  - tests/test_evals.py           # SC-12, SC-15, leak test
  - docs/evals.md, evals/README.md, docs/documents.md, docs/open-work.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_eval_tasks.py tests/test_evals.py tests/test_receipt_layout_task.py tests/test_reading_formats.py -q -p no:cacheprovider"
    exit_code: 0   # 168 passed, 2 warnings (redirected to a file, so the code is pytest's own)
  - command: ".venv/bin/python -m evals.tasks --help"
    exit_code: 0   # lists --formats
  - command: ".venv/bin/python -m evals.run --help"
    exit_code: 0   # lists --formats
  - command: ".venv/bin/python -m pytest tests/test_layout_consumers.py -q -p no:cacheprovider"
    exit_code: 0   # 17 passed; it imports evals.tasks
  - command: ".venv/bin/ruff check evals tests/test_eval_tasks.py tests/test_evals.py"
    exit_code: 0
  - command: "git diff --exit-code 64f249a -- src tests/reading_format_data specs plans/receipt-layout-eval/plan.md approvals"
    exit_code: 0   # nothing protected, and nothing under src/, touched
escalations: []
```

## What was done
- **P9, `evals/run.py`.** `check_formats(names)` (unknown or repeated → `ValueError` naming the known formats) is the first thing `run` and `run_tasks` do, before the guard, server or model checks. `format_variants(candidates, formats)` makes `<name>@<format>` copies with `reading_format` set; it runs before `schema_variants`, so `X@spans` pairs with `X@spans@no-schema`. `format_context(candidate)` is `reading_format(...)` only when the candidate has one, else `nullcontext()`; `run_case` and `run_one` use it. Result lines gain `reading_format` and `prompt_version` (the documents suite on every line; the task suite on vision-role tasks; the default is `v7-lines` / v7's label). Task lines also gain `tokens {completion, partial}` and `budget_retry`; the documents suite's `details` gain `budget_retry` (counted on transcription attempts only). Both manifests gain `formats` (a list, empty without `--formats`), and their vision candidates carry `prompt_version`. Dry runs add one line per format (tasks: cases and "at least N vision calls"; documents: "about N vision calls", the pages of cases that aren't `native_pdf`).
- **`evals/tasks/runner.py`.** With `--formats`, the default task list is the vision tasks (`transcription`, `receipt_layout`); naming another task is refused with the list of vision tasks. `--formats` is a comma list on both CLIs (`--formats ""` is refused as an unknown name).
- **P10, `evals/report.py`.** `summary()` adds `reading_format` to a candidate when present; `ENUM_VALUES["reading_format"] = set(READING_FORMATS)`; `allowed_keys()` adds the key. Nothing else is new in the summary (no prompt version). `decision_rows` skip format variants. `format_run(manifest)` / `format_decision()` give "Format comparison: no model is ranked." in place of the decision section when every candidate is a format variant (both suites). The documents report adds "Reading format: spans (receipt-vision-spans-1)." under a variant's heading.
- **`evals/tasks/report.py`.** `decision_rows` skip format variants; the leaderboard still lists a (non-`@no-schema`) format variant, with "not ranked" in the accuracy cell; a task section adds "N answers ran out at 8,192 tokens and were asked for again with 16,384." when any line has `budget_retry`.
- **P11, `transcription.py`.** `run` returns `format`; for a `spans` output a table case is graded on its text alone, with `checks["tables"] = "not produced"` and no table checks; `report_lines` prints "not produced" for such a candidate.
- **Docs.** `docs/evals.md`: a task-table row 18 and a new "Reading formats" section (the four formats, the task and its measures, the output limit with P13, measured only, running, refusals, dry run, cost, no winner, tables not produced, what decides, R3's dev-split rule). The heading is exactly "Reading formats", which the code comments already cite. `evals/README.md`: `--formats` in both command lines, the task-table row, a "Reading formats" subsection with commands, the test list. `docs/documents.md` "Images (vision transcription)": one bullet. `docs/open-work.md` "Models and evals": choosing the image reading from the results, and tables from positions. `evals/models.toml`: a comment naming `--formats`.
- **Tests.** `tests/test_eval_tasks.py` (SC-11): the dry run lists both formats with case and call counts and sends nothing; unknown, repeated and non-vision-task refusals before any request (function and CLI `main`, exit 1, the known list on stderr); a run names `<candidate>@v7-lines` and `<candidate>@spans`, lines carry `reading_format`, `prompt_version`, `tokens` (completion 50, not partial) and `budget_retry`, the requests carry each format's schema name, `run.json` carries `formats` and `prompt_version`, the report says no model is ranked; a `length`/`stop` pair gives `budget_retry` true (max_tokens 8192 then 16384); no `--formats` leaves labels and the ranked decision; `--formats` with `--compare-schema` keeps the schema table; spans table cases show "not produced". `tests/test_evals.py` (SC-12, SC-15): the donated-case run with `formats=["v7-lines","spans"]` (both ok and perfect, labels on lines, manifest and summary, `check_summary` passes, no ranking; a plain run afterwards has no `reading_format` in its summary); the documents dry run per format with 38 vision calls (73 pages in all, 35 of them text pages of native PDFs); formats checked before `check_server` is called; a non-loopback URL and the relay port are refused with and without formats in both runners; a format-run summary holds the label and no seeded value, and a private string as `reading_format` is refused by `check_summary` and by `rebuild`.

## Deviations from the plan (local, within the spec)
1. **Leaderboard cell.** The plan says only that format variants aren't ranked. The task-report leaderboard skipped any candidate missing from `decision["accuracy"]`, which would have hidden every format variant, so a format variant shows "not ranked" there (a `@no-schema` variant is still hidden, as before).
2. **`run_one(module, case, config, candidate=None)`** takes the candidate to read its format; the plan said `run_one` wraps the work without saying how it learns the format. SL-04's tests call it without a candidate and are unchanged.
3. **`budget_retry` in the documents suite** is counted on the transcription stage's attempts only (a format changes only that), in the task suite on all attempts.
4. **Extra report line** (the budget-retry sentence above) and a "Reading format:" line in the documents report; neither is in the plan. They only appear when there is something to say.
5. **`formats` is always written to `run.json`** (an empty list without `--formats`).

## Notes
- The first `pytest` run of the new SC-12 test failed on my own assertion (the `extracted` fixture makes one transcription request before the run); fixed in the test, no code change.
- SL-04's `format_of` now finds `line["reading_format"]` on every vision-task result line, so the "Reading formats" tables group by it (the `@format` suffix fallback is no longer needed but harmless).
- Nothing under `src/` changed in this slice; SL-01's captures and SC-10 are untouched.
- The full suite is for the orchestrator, once, after this slice.

## Open issues
None.
