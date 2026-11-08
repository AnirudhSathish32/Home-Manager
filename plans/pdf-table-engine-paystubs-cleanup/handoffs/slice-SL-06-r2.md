```yaml
slice: SL-06
round: 2
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: b2d1842
end_head: 38351b0   # the fix's commit; this handoff is committed on top of it
commit: [38351b0]
changed_files:
  - src/home_manager/documents/pay_tables.py   # wide_heading: a word must lie over the next pay line's amounts
  - tests/test_paystub_cleanup.py              # new: LITERALS, stacked_stub_with_title, test_sc91_f_r2_...; no existing test edited
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py -q"
    exit_code: 0   # 972 passed in 340.46s (run at 38351b0 code)
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py -k r2 with src/.../pay_tables.py stashed (b2d1842 code)"
    exit_code: 1   # fails: Right contains one more item: ('Vision', ['6.00', '6.00'])
  - command: ".venv/bin/ruff check src/home_manager/documents/pay_tables.py tests/test_paystub_cleanup.py"
    exit_code: 0
escalations: []
```

## Rule built (FR-92 f, FR-89)
`pay_tables.wide_heading(bl, position)` keeps its old conditions (one-run all-text line, 3+ words and at least as many as the next pay line's
amounts, that pay line is the next non-empty line) and adds one: some word of the line must horizontally overlap the extent of that pay line's amounts
(`min` left to `max` right of `amounts_of(following)`). A title confined to the label column ("Pre Tax Deductions", "Before Tax Deductions Withheld")
never overlaps the amounts, so it no longer cuts, whatever its length; the R1-2 heading "Accrued Vacation Used Leave Balance" runs over the leave amounts
(113 onwards, amounts at 125/200/265), so it still cuts. `tables_cut` is unchanged.

## Root cause of the "silent drop"
It was not silent in the engine. After the wrong cut the second list (`Pre Tax Deductions`, `Vision 6.00 6.00`) has no heading and one pay row, so
`choose_alignments` forms no column from it and `read_block` returns the row as `lost`; `read` adds it to `PayReading.unplaced` (the first table is on
the page, so the `without` branch isn't taken), and `extraction` turns every unplaced line into a note through `paystub_tables.unplaced_notes`. The
probe's `brief()` printed tables, other_tables, pages_without_tables and notes but not `unplaced` (the engine's `notes` field is not where those notes
are built), so the row looked lost. Checked at b2d1842: for "Pre Tax Deductions" and "Before Tax Deductions Withheld" the Vision row is in
`found.unplaced` (`'Vision 6.00 6.00'`), which at the extraction level reads `Page 1: a printed line wasn't placed in any column, so it wasn't recorded: "Vision 6.00 6.00"`.
So a cut can't drop a pay row without a trace: `read_block` puts every pay line either into a builder or into `unplaced`, and `read` keeps `lost` whenever a
table exists on the page (otherwise the page goes to `pages_without_tables`). No change was needed outside `wide_heading`. The new test asserts
`unplaced == []` and `pages_without_tables == []` for the fixed layouts. The real defect was the unintended cut; the "no trace" report was a probe gap.
The two-row section split (`[Regular, Overtime]` + `[Medical, Dental]` as a second table) is that same cut, also gone.

## Test
`test_sc91_f_r2_a_section_title_in_the_label_column_never_cuts_the_block`: titles "Deductions", "Pre Tax Deductions", "Before Tax Deductions Withheld"
x (a) one Vision row without total, (b) Medical/Dental + Total Deductions. Asserts ONE pay table, roles `["current", "ytd"]`, the literal rows and amounts
(Regular 2,000.00/24,000.00, Overtime 150.00/900.00, then Vision 6.00/6.00 or Medical 40.00/480.00, Dental 8.00/96.00), totals (Total Earnings
[, Total Deductions]), and no other_tables/unplaced/pages_without_tables. At b2d1842 it fails (checked above, first failing combination: Pre Tax
Deductions with Vision). Checked separately at b2d1842 with all four title/rows combinations: both one-row cases leave Vision in `unplaced`; both two-row
cases split into two tables `[Regular, Overtime]`, `[Medical, Dental]`. R1-2's test (`..._under_a_one_run_heading_...`) still passes.

## Probe output (at 38351b0 code)
probe_title.py: all three titles give one table, columns `[['Current'], ['YTD']]`, roles `['current', 'ytd']`, rows Regular 2,000.00/24,000.00,
Overtime 150.00/900.00, Vision 6.00/6.00; other `[]`, without `[]`, notes `[]`.
review_paystub_tables_cut.py: original, one_run and two_runs all give tables `[('page-1-pay-1', ['Base Pay', 'Retro Pay'], ['current'], [['2,662.41'], ['225.58']])]`,
other `[('page-1-pay-2', ['Vacation', 'Sick'])]`, without `[]`; heading runs for one_run `[['Accrued', 'Vacation', 'Used', 'Leave', 'Balance']]`.

## Open issues
- `wide_heading` remains a heuristic: a short (2-word) one-run heading over the amounts, or a 3+ word centred title that reaches into the amount
  columns, is still misjudged. Not touched; SL-07 (whole-number rows, R1-1) not touched.
