```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 7a10aaf
end_head: 9c5ddb5   # the slice's test commit; the handoff itself is committed on top of it
commit: 9c5ddb5
changed_files:
  - tests/test_pay_tables_repairs.py   # new; no source file changed
checks:
  - command: ".venv/bin/python -m pytest tests/test_pay_tables_repairs.py tests/test_paystub_engine.py -q"
    exit_code: 0   # 226 passed (8 new)
  - command: ".venv/bin/python -m ruff check tests/test_pay_tables_repairs.py"
    exit_code: 0
  - command: "revert-and-fail, one per repair (table below)"
    exit_code: 1   # each reverted run: 1 failed, 7 passed; the failed test is the one named
escalations: []
```

# SL-01 handoff: a unit test for each of the eight repairs (FR-98, SC-96)

`tests/test_pay_tables_repairs.py` holds eight tests, one per repair listed in `docs/open-work.md`. Each reads a hand-built page (positions and
texts as literals in the test, the words-only footer from `paystub_engine_fixtures`) through the real reader, then `pay_tables.read`. No source file
changed (`git diff 7a10aaf -- src` is empty). No helper subagents. Only the file's own tests and `tests/test_paystub_engine.py` were run, never the full suite.

## Revert-and-fail checks

For each repair I made a temporary local edit to `src/home_manager/documents/pay_tables.py` with a script (`/tmp/sl01/revert.py`, outside the repo),
ran `pytest tests/test_pay_tables_repairs.py`, and restored the file in a `finally` block. Every run failed exactly the one named test and passed the
other seven. The tree ended with no source diff (`git status` shows only the new test file and `progress.yaml`, untracked, before the commit).

| # | Test | Revert (temporary edit) | Result with the repair reverted |
|---|---|---|---|
| 1 | `test_repair_summary_box_above_side_by_side_blocks` | `taken = find_boxes(number, view, lines, view.size * ALIGN, boxes)` in `read` becomes `taken = frozenset()` | that test failed, 7 passed |
| 2 | `test_repair_repeated_stub_heading_on_a_later_page` | `if cur is not None and dates <= stub:` becomes `if False:` | that test failed, 7 passed |
| 3 | `test_repair_start_line_ends_an_empty_blocks_table` | `if index in starts and index not in consumed:` gains `and line.runs` (an empty block's part of the line no longer ends its table) | that test failed, 7 passed |
| 4 | `test_repair_second_table_with_the_same_heading_words` | `repeats` returns `True` in place of its check that the row after the heading prints in the table's own columns | that test failed, 7 passed |
| 5 | `test_repair_partner_table_beside_several_tables` | the `else:` branch pairing a right table with the left one it shares lines with becomes `elif False:` | that test failed, 7 passed |
| 6 | `test_repair_two_heading_phrases_printed_close_together` | `heading_runs(view, heads, zones)` becomes `heading_runs(view, heads)` (no split by column zone) | that test failed, 7 passed |
| 7 | `test_repair_text_only_line_of_several_runs` | ` and whole.get(index, len(line.runs)) == 1` removed from the wrapped-label condition | that test failed, 7 passed |
| 8 | `test_repair_continuation_column_at_another_alignment` | back to the old rule in three places: `cur.frame` keeps only each column's own alignment, `offset_of` skips a group whose alignment differs from the column's, and the mapping matches a group only to a column kept at its alignment | that test failed, 7 passed |

Revert 8 is an emulation of the pre-repair `offset_of`/`frame` (a diff of `02026cf` shows the old code); the others undo the repair's own lines.

## What each page is

1. A box (heading, `Current` row, `YTD` row of four amounts, gross = sum of the other three) spanning the page above a left and a right block.
2. Page 1: `Pay date 2026-07-03`, heading, three rows, no net pay; page 2 prints the same pay date line, then three more rows.
3. Two side-by-side pages; the pay date line (`2026-07-03`, then `2026-07-10`) is at x 40, over the left block only.
4. Heading `Description Current YTD`, three rows, the same heading again at columns 330/400, three rows.
5. Left block (earnings), a second left table (`Account Amount Balance`) under it, and a right block (deductions): three tables on one page.
6. Headings `This Period` (right edge 450) and `Year to Date` (right edge 515), about 14 pt apart, which the reader joins into one run.
7. A row followed by an indented line of two runs (`Rate change`, `effective July`) at x 60 and 200.
8. Page 1 right-aligned amounts; page 2 amounts left-aligned at x 397 and 476 (the median left edges of page 1's columns) with differing widths.

## Notes

- Page layouts were checked by hand with a scratch script before the assertions were written; the assertions state the repaired behaviour (tables, pages,
  partners, labels), not whatever came out.
- Test 7 uses one block. The repair's `whole` count also guards blocks that cut a line, but the old code had no run-count check at all, so a single-block
  line of several runs fails without the repair too.
- `ruff check` flagged an import order in the first draft; fixed with `ruff --fix` and the commit amended before the handoff.

## Open issues

None. `docs/open-work.md` still lists the eight repairs as untested; the docs slice (FR-97) is not this one's to edit.
