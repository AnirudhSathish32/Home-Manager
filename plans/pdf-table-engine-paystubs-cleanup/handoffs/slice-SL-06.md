```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c1cbcf3
end_head: 114ae6e   # the fixes' last commit; this handoff is committed on top of it
commit: [e990f8a, 114ae6e]   # e990f8a R1-2, 114ae6e R1-3
changed_files:
  - src/home_manager/documents/pay_tables.py       # wide_heading; tables_cut uses it (R1-2)
  - src/home_manager/finance/paystub_tables.py     # PaystubTables.untrusted; read keeps distrusted pages in pages_without_tables; for_lines filters untrusted (R1-3)
  - src/home_manager/documents/extraction.py       # NO_PAY_TABLE also for part.untrusted pages (R1-3)
  - tests/test_paystub_cleanup.py                  # 3 new tests, no existing test edited
  - docs/documents.md                              # Known limits: summary-box limitation dropped
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py -q"
    exit_code: 0   # 971 passed in 342.94s (run at 114ae6e)
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -k 'one_run_heading' with src/.../pay_tables.py stashed (c1cbcf3 code)"
    exit_code: 1   # fails: [['Base Pay']] != [['Base Pay', 'Retro Pay']]
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -k r1_3 with src stashed (c1cbcf3 code)"
    exit_code: 1   # both fail: pages_without_tables == [] (not [1]); the end-to-end run lacks the 'Page 1: no pay table' note
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -k 'sc91_f or r1_3'"
    exit_code: 0   # with the fixes
  - command: ".venv/bin/ruff check <the 4 changed py files>"
    exit_code: 0
escalations: []
```

## R1-2 (FR-92 f)
Rule: `pay_tables.wide_heading(bl, position)` — a one-run, all-text line with at least 3 words and at least as many words as the next
pay line prints amounts, when that pay line is the next non-empty line. `tables_cut` now cuts at the first line after a totals line when
a following line `is_heading_like` or `wide_heading`; the cut stays at the first text-only line after the total, so a separate "Leave"
title goes with the new table. Section titles ("Statutory Deductions", fewer than 3 words) don't cut, so a totals line covering several
sections (FR-91) is unaffected. Test: `test_sc91_f_a_leave_table_under_a_one_run_heading_is_a_table_of_its_own` (heading with and
without a title line; asserts Base Pay 2,662.41 and Retro Pay 225.58 as the pay rows, totals Total Earnings/Net Pay, and leave rows
Vacation/Sick in `other_tables`). Fails at c1cbcf3 (checked, above). The reviewer's probe now shows all three variants identical.

## R1-3 (FR-93 / FR-64)
Cause: `read` computed `without = ... | distrusted - pages`, and a summary box puts the page into `pages`. Rule built: a distrusted page is
always in `pages_without_tables` and in a new `PaystubTables.untrusted` set (the box's cells and `pages` unchanged); `for_lines` keeps
both for the part's pages; `extraction` emits NO_PAY_TABLE for `page not in part.pages or page in part.untrusted` (a box-only page with
no untrusted table still gets no note, as before). Tests: `test_sc92_r1_3_an_untrusted_page_holding_a_summary_box_is_still_a_page_without_a_pay_table`
(engine, including `for_lines`) and `test_sc92_r1_3_an_untrusted_page_holding_a_summary_box_gets_the_no_pay_table_note` (end to end, exact
note text). Both fail at c1cbcf3 (checked). docs/documents.md "Known limits": dropped "a summary box on such a page does not add the note"; no heading changed.

## Open issues
- `wide_heading` is a heuristic: a one-run heading of 2 words ("Accrued Balance") over a 2+ column leave table, or a 3+ word section
  title above rows with fewer amounts, is still misjudged. Not documented as a limit; say if the orchestrator wants one added.
- R1-1 not touched (escalated).
