```yaml
slice: SL-09
result: ready_for_verification   # with ONE escalation: the approved rule leaves the exactly centred 3-word title cut (see "Escalation")
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 721ed9b
end_head: 967698c   # the fix's commit; this handoff is committed on top of it
commit: [967698c]
changed_files:
  - src/home_manager/documents/pay_tables.py   # new amount_columns; wide_heading(view, bl, position, above=None) seats every column of the table above; tables_cut collects `above`
  - tests/test_paystub_cleanup.py              # 3 new tests after SL-08's; no existing test edited
  - docs/documents.md                          # "Rows" sentence and the "Known limits" SL-08 entry
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py -q"
    exit_code: 0   # 985 passed (982 + 3 new), 2 warnings in 343.19s (log /tmp/claude-fv/sl09/verify.log)
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -q -k r3_a with pay_tables.py from 721ed9b"
    exit_code: 1   # 2 failed (test (a) and test (b)), 4 passed (test (c) and SL-08's three); 27 deselected
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -q -k r3_a (fix applied)"
    exit_code: 0   # 6 passed
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider /tmp/claude-fv/r3/sparse_title_regression.py /tmp/claude-fv/r3/review_r2_assertions.py"
    exit_code: 0   # 3 passed (sparse_title_regression failed at 721ed9b)
  - command: ".venv/bin/python /tmp/claude-fv/r3/<each of the 8 probe scripts>.py (logs /tmp/claude-fv/sl09/<name>.log)"
    exit_code: 0   # title_repro 0, geometry_probes 0, leave_probes 0, title_probes 0, review_r2_long_title 0, review_r2_short_heading 0, review_r2_compare 0, review_r2_edges 0
  - command: ".venv/bin/ruff check src scripts tests evals"
    exit_code: 1   # only the 2 pre-existing errors (tests/test_document_v2_browser.py I001, tests/test_receipt_kinds.py:977 F402)
escalations:
  - "The approved rule does not restore the exactly centred 3-word title with full or sparse rows (see below). Not worked around."
```

## Rule built (FR-92 f)
`tables_cut` now keeps `above`, the boxes of the amounts of every pay line since the last cut (or stub start), and passes it to
`wide_heading(view, bl, position, above=None)`. The columns to cover are `amount_columns([*above, *amounts of the next pay line])`: boxes that overlap
horizontally are one column, represented by the last box (so the next row's own amount stands for its column, the table above's latest amount for a
column the row leaves blank). The SL-08 seating is unchanged but runs over these columns instead of the next row's amounts: a piece overlapping the
column, or a word aligned by one edge (the same edge for all word-matched columns), no word serving two columns. The SL-08 guards stay (title starts
more than ALIGN right of the label; next non-empty line is a pay line).

Why pay-line amounts rather than the totals line: a totals line can itself be sparse (Total Earnings with the Current only), while the union over all pay
lines since the cut is every column the table occupies, and needs no new geometry (`amounts_of` boxes already on the page lines). Overlap-merge is
simplest because right-, left- and centre-aligned amounts of one column all overlap; two columns chained into one by a very wide amount would only
demand fewer units (weaker, never a false cut). `above` resets at every cut and stub start. `above=None` (the probes' 3-argument calls) means every pay line of `bl`
before the line, which is the same for a single-table probe.

R1-2 / R2-2 stay cut: the leave heading's pieces ("Used", "Balance") or aligned words sit over the pay column(s) (which overlap the leave columns in
`stub_left`), and `review_r2_*`, `leave_probes`, `geometry_probes` pass.

## Tests (tests/test_paystub_cleanup.py, after SL-08's)
- `test_sc91_f_r3_a_one_word_section_title_over_a_sparse_row_does_not_cut_the_block` (a): Reimbursements (centred), Deductions (centred), Deductions
  shifted -45; Regular 2,000.00/24,000.00, Overtime 150.00/900.00, Travel 6.00 (YTD blank); one table, nothing unplaced. FAILS at 721ed9b, passes now.
- `test_sc91_f_r3_a_three_word_title_with_words_off_the_amounts_does_not_cut_a_sparse_row` (b, see Escalation for why shifted): Health Insurance Premiums
  at -15 and +30, Employee Benefit Contributions at +15 and -30, Vision 6.00 sparse; stays. FAILS at 721ed9b (all four placements were cut: Vision 6.00 unplaced;
  checked with `/tmp/claude-fv/sl09/hip.py` on the 721ed9b code), passes now.
- `test_sc91_f_r3_a_sparse_leave_row_under_a_heading_over_every_pay_column_is_a_table_of_its_own` (c): (1) one pay column, heading "Used Balance",
  sparse rows Vacation 8.00 / Sick 0.00 -> Base Pay 2,662.41, Retro Pay 225.58 stay, other table Vacation, Sick; (2) Current 430 / YTD 520 with "Used"
  ending at 430 and "Balance" at 520 and sparse leave rows -> Regular/Overtime keep both literals, other table Vacation, Sick. Passes at 721ed9b and now
  (positive guard that the new rule does not stop the cut).

## Escalation (the user's requirement (b) as worded cannot be met by the approved rule)
`Health Insurance Premiums` exactly centred over Current / YTD (shift 0) is cut with `Vision 6.00 6.00` AND with the sparse `Vision 6.00`; so is
`Employee Benefit Contributions` at shifts 0 (full row) and -15 (both). Its three words line up by one edge with BOTH columns of the table above, which
is what the approved rule accepts as a heading, and it cannot be told from the R1-2 heading "Accrued Vacation Used Leave Balance" (see SL-08's
deviation). Hence `title_repro.py` HEAD != fe54dae for two cases (Health Insurance Premiums and Employee Benefit Contributions at shift 0 with
6.00/6.00); the other five cases (Deductions, Tax Deductions, Before Tax Deductions Withheld, Reimbursements, Deductions -45) equal fe54dae. The
sparse one-word cases (a) are fixed; the sparse exactly-centred 3-word title is not (`/tmp/claude-fv/sl09/hip.py` lists a grid of shifts). I did not invent
another rule. The "Known limits" entry now says exactly this (three words or more with a word over each column, or two words printed apart; one-word
titles, titles at the label column, and sparse rows under a title covering only one column never cut). To close it the R1-2 test (heading words at one
pitch) would have to go, or a text-level cue (e.g. title contains no heading-like word) would be needed: a requirement decision.

## Other limit (documented)
A one-run leave heading with fewer pieces than the pay table above has columns no longer cuts and the leave rows merge as before SL-08 (fe54dae behaviour);
this follows from "a unit over every column".

## FR-67 / version
`git diff 721ed9b -- src/home_manager/documents/table_engine.py` is empty. EXTRACTION_VERSION untouched.

## Open issues
- The escalation above.
- Ruff: only the 2 pre-existing errors.
