```yaml
slice: SL-10
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 45cc6a6
end_head: d995239   # the code commit; this handoff is committed on top of it
commit: [d995239]
changed_files:
  - src/home_manager/documents/pay_tables.py   # LEAVE_HEADING_WORDS; wide_heading back to SL-08's seating plus the word test; amount_columns and `above` removed
  - tests/test_paystub_cleanup.py              # 2 new tests; docstrings of 3 SL-09/SL-07 tests updated (no assertion edited)
  - docs/documents.md                          # the heading-rule paragraph and the "Known limits" entry
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py -q"
    exit_code: 0   # 987 passed (985 + 2 new), 2 warnings in 341.22s
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -q with src from 45cc6a6 (git stash push src)"
    exit_code: 1   # exactly the 2 new tests fail; the other 33 pass
  - command: ".venv/bin/python -B -m pytest -q -p no:cacheprovider /tmp/claude-fv/r3/sparse_title_regression.py /tmp/claude-fv/r3/review_r2_assertions.py"
    exit_code: 0   # 3 passed
  - command: ".venv/bin/python /tmp/claude-fv/r3/<each probe>.py"
    exit_code: 0   # setup_probes, title_repro, leave_probes, title_probes, review_r2_long_title, review_r2_short_heading, review_r2_compare, review_r2_edges: all 0
  - command: ".venv/bin/python /tmp/claude-fv/r3/geometry_probes.py"
    exit_code: 1   # REPORTED, not edited: see "Probe report"
  - command: ".venv/bin/ruff check src scripts tests evals"
    exit_code: 1   # only the 2 pre-existing errors (tests/test_document_v2_browser.py:410 I001, tests/test_receipt_kinds.py:977 F402)
escalations: []
```

## Rule built (FR-92 f, plan P3 (f) "One-run headings after a totals line")
`wide_heading(view, bl, position)` cuts a one-run title-like line only when (1) it holds a word of the new `LEAVE_HEADING_WORDS` (accrued, accrual, accruals, balance,
balances, used, available, remaining, carryover, deposit, deposits, account, routing; whole words, lower-cased, leading and trailing punctuation stripped with
`re.sub(r"^\W+|\W+$", ...)`), (2) it starts more than ALIGN right of the next pay line's label, (3) it has its own unit over each amount of that next pay line
(SL-08's seating, unchanged: a `run_pieces` piece over it, or a word aligned by one common edge, no word serving two amounts). SL-09's `amount_columns`, the
`above` parameter and the boxes `tables_cut` collected are removed (`tables_cut` is as at SL-08 again, only its docstring now names the word list). Lines of two or
more runs (`is_heading_like`) cut as before, without the word list. I used `re`, not `string`, for the stripping: `tests/test_paystub_engine.py::test_rows_the_module_imports_no_finance_store_or_model_code`
pins the module's import list, and a first version with `import string` failed it (caught in the first full run, then fixed).

## Tests (tests/test_paystub_cleanup.py)
New, after SL-09's:
- `test_sc91_f_r3_a_a_title_without_a_leave_heading_word_never_cuts_wherever_it_is_placed`: Current 430 / YTD 520 table after `Total Earnings`; (1) `Health Insurance Premiums` exactly centred
  over the two columns, then `Vision 6.00 6.00` -> Vision is a pay row of the one table with both literals, nothing unplaced; (2) centred `Reimbursements` then `Travel 6.00` (YTD blank) stays.
  **Fails at 45cc6a6** (case 1: `AssertionError: Health Insurance Premiums`, the Vision row is missing from the pay table); case 2 passes there and is kept as a guard.
- `test_sc91_f_r3_a_a_one_piece_leave_heading_over_a_one_column_leave_row_is_a_table_of_its_own`: the same pay table, then the one-run `Leave Balance` placed so it ends at 430 (a single piece
  over the one amount of `Vacation 8.00` / `Sick 0.00`, the YTD blank), so rule 3 holds with the heading over the leave amount. Regular and Overtime keep both literals, Vacation and Sick are the
  other table, nothing unplaced. **Fails at 45cc6a6** (`KeyError: 'page-1-pay-1-column-2'`: the leave rows merge into the pay table, SL-09's table-above rule not cutting a one-piece heading).
  The literals needed no redesign.
- Already existing and unchanged, still passing: `Accrued Vacation Used Leave Balance` (R1-2, `test_sc91_f_a_leave_table_under_a_one_run_heading_...`) and the two-piece `Used Balance`
  (R2-2 `..._under_a_two_word_one_run_heading_...`, and SL-09's `..._sparse_leave_row_under_a_heading_over_every_pay_column...`, both of its cases: Retro Pay 225.58 stays, leave rows give no pay line).
Edited existing tests (docstrings only, no assertion or literal changed; each docstring encoded the removed table-above rule or called the case a known limit):
- `test_sc91_f_r3_a_one_word_section_title_over_a_sparse_row_does_not_cut_the_block` (SL-09 (a)): the reason is now "no leave heading word", not "the YTD column has no unit".
- `test_sc91_f_r3_a_three_word_title_with_words_off_the_amounts_does_not_cut_a_sparse_row` (SL-09 (b)): same; the exactly centred title is now covered by the new test instead of being "the known limit".
- `test_sc91_f_r3_a_centred_section_title_over_both_columns_does_not_cut_the_block` (SL-07 R2-1): its closing remark that a title shifted 15 is the cut's known limit is replaced by the word-list reason.
SL-09's "fewer pieces than columns doesn't cut" has no test of its own, so none needed changing.

## Docs (docs/documents.md)
The heading-rule paragraph (Rows) now lists the word list and the three conditions; the "Known limits" entry says: a section title holding one of the words that lines up by one edge with the amounts of the
row below still cuts, one without such a word never does wherever it is placed, and a leave or deposit heading printed as one run without any of the words is not cut and its table merges with the pay columns.
Heading names kept. `wide_heading` and `tables_cut` docstrings updated.

## Probe report (geometry-only expectation changed by the word list; not edited)
`/tmp/claude-fv/r3/geometry_probes.py` exits 1 on `assert evaluate('four pieces over four amounts', [('Rate',..),('Hours',..),('Current',..),('YTD',..)], ...)[0]`: output `four pieces over four amounts wide= False`.
That heading is `Rate Hours Current YTD`, none a word of the list, so rule 1 now keeps it from cutting by design. A copy of the script without that single assert line (`/tmp/claude-fv/sl10-geometry_probes_without_four.py`) runs all its other asserts to the
end with exit 0 (including the 1000-layout `heading_runs` equivalence). Side effect on my part: I also ran `cp /tmp/claude-fv/r3/*.py /tmp/claude-fv/` once by mistake, which may have overwritten same-named files directly in /tmp/claude-fv (the r3 originals are untouched).
`title_repro.py`: HEAD equals fe54dae in all 7 cases (the two SL-09 differences are gone).

## FR-67 / version
`git diff 721ed9b -- src/home_manager/documents/table_engine.py` is empty (`tokenize`, `tokenize_page`, `Line` untouched). EXTRACTION_VERSION untouched.

## Open issues
- The `geometry_probes` expectation above (a four-piece heading with no list word no longer cuts, by the approved rule).
- No approved-rule break among the passing tests: the generator's FR-92 (f) leave tables (test_paystub_engine_generator) pass with the word list.
