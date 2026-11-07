```yaml
slice: SL-02
result: escalated   # code and the slice's own tests are done; verification command 2 fails on two tests the contract does not list as changed (see escalations)
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 40423ef
end_head: 83d7dfe   # the slice's commit; the handoff itself is committed on top of it
commit: 83d7dfe
changed_files:
  - src/home_manager/documents/pay_tables.py        # P0, P1
  - src/home_manager/finance/paystub_tables.py      # P2
  - tests/test_paystub_cleanup.py                   # new; the sc90 engine step (4 tests)
  - tests/test_paystub_engine_record.py             # only test_a_table_whose_columns_all_end_other_is_not_trusted_on_its_page, rewritten and renamed
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py -q"
    exit_code: 0   # 913 passed (5 min 13 s)
  - command: ".venv/bin/python -m pytest tests/test_layout_consumers.py -q"
    exit_code: 1   # 2 failed, 15 passed; both pass at 40423ef (17 passed, checked by stashing the change)
  - command: ".venv/bin/python -m ruff check src tests/test_paystub_cleanup.py tests/test_paystub_engine_record.py"
    exit_code: 0
  - command: "revert-and-fail, one per rule (table below)"
    exit_code: 1   # each reverted run fails the named tests of tests/test_paystub_cleanup.py
escalations:
  - id: E-1
    what: >
      `tests/test_layout_consumers.py::test_a_sectioned_payslip_records_when_the_model_quotes_rows_without_separators` and
      `::test_a_pay_row_listed_again_is_one_pay_line` fail now that the engine trusts page 1 of the sectioned payslip. Both give model stubs that
      classify only some of the payslip's rows (4 and 2 of the 11) and assert exactly those lines; at 40423ef page 1 was read by the table_grid fallback,
      which records only the cited rows. With the engine on page 1, every row the model did not classify is recorded as an unclassified row
      (phase 2 FR-62, `extraction.unclassified_rows`), so the record has 11 lines (the first test sees 7 extra, the second 9).
    why_escalated: >
      SC-94 says test_layout_consumers.py passes unchanged and lists the tests this change edits "and only these"; neither test is listed, and the plan's
      SL-02 row says to run all of the file. I did not edit them or the unclassified-row behaviour (that is phase 2, not this slice).
    proposed_resolution: >
      Add both tests to SC-94's "tests this change edits" list and change their model stubs to classify every row of the sectioned payslip (or assert the
      eleven lines, the nine extra ones being the unclassified rows with their guessed groups). The main parity test
      (`test_a_sectioned_payslip_copies_every_line_total_and_benefit`) classifies every row and passes unchanged.
```

# SL-02 handoff: heading phrases split by column, whole-number amounts, totals over several sections (FR-89, FR-90, FR-91)

## What changed

`documents/pay_tables.py` (P0, P1; `table_engine.tokenize`, `tokenize_page` and `Line` untouched, FR-67):
- **P0.** `heading_runs(view, lines, zones, edge)` stops at the first word at or past `edge` (the left block's `block_split − tolerance`, passed from
  `read` to `read_block`; the right block's label printed in the left block's run is cut off). `splits_by_column` makes an all-text one-run line a
  heading line when its pieces lie over two or more zones; `heads_above` takes it through a new optional `wide=(view, zones, edge)` argument. In
  `read_block` the `attached` set is recomputed after the zones exist, and a heading line is also recognised when one of its pieces (not only a whole
  run) lies in a zone.
- **P1.** `group_starts` and `split_tails` ignore a run made of one integer. `whole_columns` finds tentative columns (single-integer runs that are not the
  label run and are further than `ALIGN` font sizes from every decimal column at every alignment, grouped with `choose_alignments`). Zones are drawn from
  decimal plus tentative columns; a column is kept when a heading piece sits in its zone or two rows line up in it; `with_whole_numbers` swaps its
  integers for `Token("amount", …, amount_of(text))` with the run no longer led by text (via `amount_of`, so the module's import test, which lists the
  allowed imports, is unchanged), and the kept columns join `found`/`groups` directly. A rejected column's integers stay text and its zone is dropped
  before the final zones. Only integers on lines that are already pay lines are candidates, so the details-box line stays no row (m7).

`finance/paystub_tables.py` (P2): `covered_rows` returns the two candidate sets (since the previous total; since the previous total or section title);
`pay_columns` (b) holds a total when either sums to it; `mismatches` (FR-63) judges the same way and, when neither holds, prints the wider sum (28,314.00).

## Results on the sectioned payslip (engine level, synthetic fixture)

Earnings columns Rate / Hours / This Period / Year To Date with roles rate, hours, current, ytd; deductions This Period / Year To Date, roles current,
ytd; `80` is Regular Salary's Hours cell; Federal Tax … 401K Plan carry their `Statutory` / `Voluntary` section; `pay_columns` of the deductions table is
the This Period column only; one `mismatches` note naming 28,434.00 and 28,314.00 and none for 1,354.00; `fallback_pages` is empty; page 2's one-row table
is a pay table.

## Tests

`tests/test_paystub_cleanup.py` (new, `-k sc90`): the sectioned payslip through the engine (also covering FR-89/FR-91 cell-level assertions); the same page
with a lone `2` at the right edge of the This Period deductions column on the `Federal Allowances` line (m7: still no row, no unplaced line); the contract's
whole-hours page (heading `Description` x 40, `Rate` r 260, `Hours` r 330, `Current` r 430, `YTD` r 520, rows with hours 40, 4, 8: one block, one table,
labels `Regular`, `Overtime`, `Holiday`, roles rate, hours, current, ytd); and a one-row `40` under no heading that stays label text.
`tests/test_paystub_engine_record.py`: the untrusted-page test is rewritten as `test_the_sectioned_payslip_page_is_trusted_and_read_in_full_by_the_engine`
(renamed because page 1 is no longer untrusted; the name no longer fit): `fallback_pages == set()`, three adapted tables, their roles, no page without
tables. The untrusted case itself (a table whose columns all end `other`) is covered by SC-92's m4 unit test in SL-04.

## Revert-and-fail checks (temporary edits restored by `/tmp/sl02/revert.py`, outside the repo)

| Rule | Temporary edit | Failing tests (of 4) |
|---|---|---|
| P0 one-run heading detection | `splits_by_column` always False | sectioned payslip, m7 |
| P0 cut at the block edge | the `edge` check in `heading_runs` off | sectioned payslip, m7 |
| P1 whole columns | `whole_columns` returns `[]` | sectioned payslip, m7, whole hours |
| P1 lone integer starts a group | `not lone_integer(...)` removed from `group_starts` | whole hours |
| P1 keep rule (heading or two rows) | every tentative column kept | one-row `40` stays text |
| P2 one set only | `covered_rows` returns the narrow set twice | sectioned payslip, m7 |

## Notes and open issues

- **E-1 above is the one open issue**: command 2 exits 1 until the orchestrator decides how those two layout-consumer tests change.
- A whole number printed within 1.5 font sizes after an amount in the same run (`25.00 40` with tight columns) stays inside the amount's run and is not
  seen as a column; `split_tails` does not cut a trailing lone integer (it would otherwise read as a second label). The contract's hours page and the
  sectioned payslip print them as runs of their own. No fixture needed the tight case.
- Docs (FR-97) are SL-05's; `docs/open-work.md` still lists the work as open.
- Command 1 takes about five minutes (the generator sweep); command 2 about ten seconds.
