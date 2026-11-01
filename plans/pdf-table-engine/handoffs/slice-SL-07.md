```yaml
slice: SL-07
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: a59932c
end_head: b65eb87        # code and docs; this handoff file is committed on top of it
commit: b65eb87
code_commits: [2f4d462, 28f6f63, b65eb87]
changed_files:
  - evals/synthetic.py        # 48 documents: four aligned-column text-PDF statements appended (aligned_statement, write_layout_pdf, assemble)
  - evals/corpus.py           # TAGS gains "aligned"
  - evals/graders.py          # table_reader(answers, rebuild, unplaced, failed)
  - evals/run.py              # table_readers(case, answers, evidence): old reader and engine on the saved reading; details["table_readers"]
  - evals/report.py           # aggregate, summary (table_readers, allowlist keys), report.md side-by-side table
  - tests/test_evals.py       # counts 44 -> 48; unchanged-documents pin; table_reader unit test; SC-20 comparison tests
  - docs/evals.md             # 44 -> 48; new section "The two table readers"; summary.json contents
  - evals/README.md           # 48 documents, tag aligned, "The two table readers", tests list
  - docs/open-work.md         # new section "PDF table engine"
  - plans/pdf-table-engine/handoffs/slice-SL-07.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_evals.py -q"
    exit_code: 0     # 21 passed (29 s). `-k table_engine` selects the 4 SC-20 tests.
  - command: ".venv/bin/python -m evals.synthetic /tmp/sl07b"
    exit_code: 0     # "Synthetic corpus with 48 cases"; 48 case folders
  - command: ".venv/bin/ruff check src tests evals scripts"
    exit_code: 0     # All checks passed
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider"
    exit_code: 1     # 54 failed, 2071 passed, 102 skipped, 1 deselected, 20 errors (24 min). Failure set identical to START_HEAD (below)
  - command: "PYTHONPATH=<worktree of a59932c>/src:... .venv/bin/python -m pytest -q tests/test_agent_findings.py tests/test_agent_guards.py tests/test_agent_instance.py tests/test_traces.py tests/test_tax_year.py tests/test_tax_zen.py tests/test_tax_family.py tests/test_scenarios.py tests/test_cpa_pack.py tests/test_tax_engines.py tests/test_engine_worksheets.py"
    exit_code: 1     # at START_HEAD: 54 failed, 137 passed, 20 errors; sorted FAILED/ERROR ids diffed against the full run: identical (74 lines); worktree removed
  - command: "RUN_BROWSER_TESTS=1 .venv/bin/python -m pytest tests/test_table_engine_browser.py tests/test_statement_accounts_browser.py tests/test_pdf_imports_browser.py tests/test_document_v2_browser.py -q"
    exit_code: 0     # 28 passed (193 s)
skipped_checks: [mypy]
escalations: []
```

## What was built
- **Corpus (48 cases).** `evals/synthetic.py` appends four statements drawn by `evals/statement_layouts.make(SEED + 1, index, **overrides)` after the 44 existing documents: index 37 a Wells Fargo-style statement (in/out/balance columns, two-line headings `Deposits/ Additions`, `Withdrawals/ Subtractions`, `Ending daily balance`, dates without a year, the period printed, a `Daily ending balance` table after the rows), index 1 dates printed DD/MM/YYYY, index 2 descriptions wrapped over up to three lines on two pages, index 3 a card statement with `Payments…`/`Purchases…` sections. Tag `aligned` only (added to `corpus.TAGS`). The indices were picked by scanning what the generator prints (labels, a day over 12, two pages, wrap 3), never by a reader's result. Answers (rows, period, opening, closing) are the generator's inputs; the card's due date and minimum payment are `None` (not printed). Each page's footer gets `, amounts shown in $ (USD), kept` like the generator test's `with_dollar_footer`, so the app reads USD. A small positioned writer (`write_layout_pdf`, sharing `assemble` with `write_pdf`) writes the PDFs; `write_pdf`'s bytes are unchanged. A test pins the first 44 documents (sha256 of their type, lines, fields, rows, tags, source and faded, computed from the HEAD version of `evals/synthetic.py`), so their case ids and answers are unchanged. Counts: 24 receipts, 9 bank, 6 card, 7 pay stubs, 2 bills; 38 images, 10 PDFs.
- **Comparison.** `evals/run.py table_readers` runs, for a native-PDF bank or card statement whose row list is confirmed complete, `statement_rows.rebuild` (old; builds on `analyze_legacy`) and `statement_tables.read(...).as_rebuild()` (engine) on the saved reading (`read_result(reading["result"])`), both given the answers' currency and period (the engine as `fallback_period`, as Record gives it). It runs right after the reading, with no model, so it is the same for every candidate and does not depend on extraction succeeding. `graders.table_reader` returns `{rows, recorded, exact, reconciled, dropped, unplaced, failed}` (exact = multiset match on date and signed amount; reconciled = opening ± recorded amounts == closing, `None` when a balance is unchecked; a reader that raises is `failed` and recorded nothing). `report.aggregate` sums them; `summary.json` gets `table_readers: {legacy, engine}` per candidate (counts plus `exact_share`, `reconciled_share`; `{"suppressed": true}` under 3 statements), `allowed_keys` gains the new keys, and `report.md` has a side-by-side table in each candidate's section.
- **Tests (`tests/test_evals.py`).** Counts 44 → 48 (dry run, corpus test); `test_table_engine_aligned_statements_are_added_after…` (pin, the four are bank, bank, bank, card, tags, what they print); `test_table_reader_counts…` (unit); `test_table_engine_and_the_old_reader_are_compared_on_text_pdf_statements` (runs `run` with the `local_model` stub on the 7 native-PDF statements of a generated corpus; asserts on the four aligned cases `engine == {rows: n, recorded: n, exact: n, reconciled: True, dropped: 0, unplaced: 0, failed: False}`, engine ≥ old on exact and reconciled in total and per statement, the summary passes `check_summary` and holds no description, amount or date, report.md shows both rows); `…leaves_out_what_is_not_a_text_pdf_statement_and_counts_a_failing_reader` (receipt and scanned statement have no `table_readers`; an injected engine fault is counted `failed`); `…is_suppressed_in_the_summary_for_few_statements`.
- **Docs.** `docs/evals.md` new `## The two table readers` (what, how, the metrics, summary keys, the aligned cases, the flowed-text caveat); the corpus is 48; the "what may leave the corpus" line names the new counts. `evals/README.md`: 48 documents, tag `aligned`, `### The two table readers`, tests. `docs/open-work.md` new `## PDF table engine`: D4 (remove the old path and the FR-24 fallback after your corpus run; move `scripts/statement_diagnose.py` first), accuracy on real statements unmeasured, FR-40 – FR-44, G10, the four SL-04 limits, P6's mid-page cut, out-of-scope items, index backfill time. No heading renamed.

## What the comparison showed on the synthetic corpus (observed, not asserted as expected values)
The four aligned statements: engine 11/11, 15/15, 29/29, 11/11 rows exact, all four reconcile, 0 unplaced. Old reader: 0, 0, 5 of 29 (with 39 counted as left out), 0; none reconciles. The three existing PDF statements (70, 300 and 60 rows) are one flowed text line per row with no columns: both readers record 0 rows there (the engine lists 59, 246 and 43 unplaced lines and counts 71, 301 and 45 as dropped; the old reader counts 0), so the engine ties at zero and Record keeps using the model's rows for them. Totals over the 7: engine 66 of 499 rows exact (4 of 7 reconcile), old 5 of 499 (0 of 7).

## Deviations and judgement calls
- **`dropped` is shown but not compared.** Plan P12 says the engine should be ≤ the old reader on `dropped`. It can't be: on the flowed-text statements the engine lists every dated line as unplaced (and counts it dropped) while the old reader never takes those lines for rows and so counts nothing. The comparison asserts engine ≥ old on exact rows and on reconciled statements (SC-20's text), and `dropped` stays in the results and summary for information with a note in the report and docs. No contract value is involved.
- **The old reader's `unplaced` is `null`** (report: "n/a"): it names no unplaced lines; a 0 would read as "perfect".
- **Both readers get the answers' period.** P12 said the engine uses its own period. The engine gets it as `fallback_period` only (used just when no period is printed, exactly as Record passes the model's); all four aligned statements print theirs.
- Summary keys beyond the plan's list: `recorded`, `reconcilable`, `failed`, `exact_share`, `reconciled_share`. `documents` counts statements per reader line (so per repeat).
- The comparison also runs on the three existing flowed-text PDF statements and on donated native-PDF statements; it skips images, scans and anything whose row list isn't confirmed complete.

## Open issues
- `docs/open-work.md` older entries ("PDF transaction import, still open") were not re-audited; some, for example the second-heading continuation and "accuracy on real bank PDFs is unmeasured", may be partly stale after SL-02 – SL-06. I did not edit them.
- Full-suite failures are unchanged: 54 failed and 20 errors, the same 74 ids as at START_HEAD (the brief said 55 failed; at START_HEAD I measured 54). They include `test_agent_findings.py` (9) and `test_agent_guards.py` (3), which the brief's list didn't name; they fail identically at START_HEAD (the Windows-only `socket.SO_EXCLUSIVEADDRUSE`, and the agent-instance fixtures).
- The old reader scores 0 on three of the four aligned statements because it needs recognised headings; this is the intended contrast, but it means the synthetic corpus can't show a case where the old reader beats the engine. The user's corpus run is the real gate (D4).
