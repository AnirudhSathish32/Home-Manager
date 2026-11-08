```yaml
slice: SL-11
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 4dbe899
end_head: 0d804bd   # the code commit; this handoff is committed on top of it
commit: [0d804bd]
changed_files:
  - src/home_manager/documents/pay_tables.py   # read_block.supported: also the edges of each run's run_pieces pieces (2 lines + 1 comment)
  - tests/test_paystub_cleanup.py              # 4 new tests (a, b, c, guard); sectioned_run gets a `benefits=BENEFITS` parameter
  - docs/documents.md                          # "Pay stub rows from the printed columns", Rows bullet: a heading piece lined up with a one-row column supports it
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py tests/test_pdf_layout.py -q"
    exit_code: 0   # 1029 passed, 2 warnings in 392.92s (987 before without test_pdf_layout + 4 new = 991; test_pdf_layout adds 38)
  - command: ".venv/bin/python -m pytest tests/test_paystub_forms.py tests/test_paystub_split.py tests/test_vision_tables.py tests/test_evals.py -q"
    exit_code: 0   # 130 passed, 2 warnings in 164.10s
  - command: ".venv/bin/python -B -m pytest -q -p no:cacheprovider /tmp/claude-fv/r3/sparse_title_regression.py /tmp/claude-fv/r3/review_r2_assertions.py"
    exit_code: 0   # 3 passed
  - command: ".venv/bin/python /tmp/claude-fv/r3/title_repro.py"
    exit_code: 0   # HEAD == fe54dae in all 7 cases
  - command: ".venv/bin/ruff check src scripts tests evals"
    exit_code: 1   # only the 2 pre-existing errors (tests/test_document_v2_browser.py I001, tests/test_receipt_kinds.py:977 F402)
  - command: "git diff 4dbe899 -- src/home_manager/documents/table_engine.py"
    exit_code: 0   # empty (FR-67)
escalations: []
```

## The fix
`read_block.supported(rows, alignment, centre)` (pay_tables.py ~721) gave a one-row column its second support only when a whole heading RUN's edge lay within ALIGN of the
column's edge. `This Period` and `Year to Date` printed less than ~a font size apart are one run, whose right edge matches only 266.10. Now it checks, for each run of
each attached heading line, the run and `run_pieces(view, run, edge=edge)` (split where words lie > half a font size apart, as `heading_runs` and `wide_heading` do).
`edge` is `read_block`'s own parameter (the left block's right limit, None for a single block), in scope in the closure; with it the pieces of the left block drop the
right block's words, as `heading_runs` does. `table_engine.py` untouched. One comment line cites `docs/documents.md "Pay stub rows from the printed columns"`.

## Tests (tests/test_paystub_cleanup.py, new section before SL-04's), all with literals in the test
- (a) `test_sc89_sl11_a_one_row_table_under_two_headings_read_as_one_run_has_both_columns`: label x 40, `This Period` centred over 133.05 (ends 290) moved -3 / 0 / +3, `Year to Date`
  and 266.10 end at 365; a spy on `read_block` asserts the heading line has exactly 2 runs (title, then one run starting `This Period`), so the test can't stop covering the tight case. One pay table,
  roles current/ytd, `133.05`/`266.10`, labels `This Period`/`Year to Date`. **Fails at 4dbe899**: `AssertionError: -3`, `[(['ytd'], [('Co Match 401K', ['266.10'])])] != [(['current','ytd'], ...)]`.
- (b) `..._b_the_same_one_row_table_under_net_payment_with_the_earnings_edges_has_both_columns`: sectioned payslip page 1 + the table at x 30, y 85/70, headings and amounts right-aligned at 268 and 334
  (probe2's case); asserts the joined run, then Co Match 401K current 133.05 / ytd 266.10. **Fails at 4dbe899**: `IndexError: list index out of range` (the table has one column, so `table.columns[1]`).
- (c) `..._c_the_tight_benefits_page_gives_the_record_line_both_amounts`: `sectioned_run(..., benefits={"items": co_match(60, 700, 290, 365)})` through Record: Co Match 401K current 13305, ytd 26610.
  **Fails at 4dbe899**: `assert (None, 26610) == (13305, 26610)`.
- guard `..._guard_a_one_row_amount_under_pieces_that_do_not_line_up_with_it_gets_no_column`: `This Period` ends at 268, `Year to Date` at 334 (one run, asserted), 133.05 ends at 280 (12 from the piece's right edge; tolerance 7.5; no left edge or centre
  of the run or pieces is within 7.5 either), 266.10 at 334: only the ytd column, `266.10`; 133.05 is a stray of the row. Passes at 4dbe899 and after (it guards the rule against widening). I probed 262 as well:
  with the fix it is a column (6 from 268), without it not; 286-296 give no pay table at all (both).
Stash check: `git stash push src; pytest tests/test_paystub_cleanup.py -k sl11` -> 3 failed (a, b, c), 1 passed (guard); with the fix 4 passed.
Edited helper: `sectioned_run(pdf_store, local_model, benefits=BENEFITS)` (default unchanged).

## Docs
docs/documents.md, "Pay stub rows from the printed columns", Rows bullet: "A column of one row has the second point of support (`choose_alignments`) from a heading run only when its edge lines up with the
amount's; where two close headings read as one run (`This Period Year to Date`), the edge of a piece of the run (`This Period`) counts too." Heading names kept.

## FR-67 / version
`git diff 4dbe899 -- src/home_manager/documents/table_engine.py` is empty. EXTRACTION_VERSION is `typed-extraction-v36-paystub-one-path` (extraction.py:49) and is **not bumped**. Found: docs/documents.md says Extract again never reuses a run
of an older `EXTRACTION_VERSION`, i.e. a bump makes saved readings re-extract. The change alters what the pay engine reads from a text PDF, which is what the version is for, but v36 is this unreleased feature's own version
(docs/documents.md ~793 says readings made before v36 are read again), so no installed reading carries v36 yet; I propose no bump unless v36 has already shipped to a library.

## Open issues
- The full 9-file run was started before I shortened the one comment line in pay_tables.py (comment only); the four sl11 tests were re-run after it (4 passed).
- Out of scope, seen in the probe: with `This Period` shifted +6 or more from centred (headings overlapping or touching the other heading), the page gives no pay table (one other table); unchanged by this fix.
