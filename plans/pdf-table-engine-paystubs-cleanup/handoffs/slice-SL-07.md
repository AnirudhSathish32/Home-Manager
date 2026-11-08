---
slice: SL-07
round: 2
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 6102d16
end_head: bcc038f   # plus the handoff commit on top
commit: bcc038f
changed_files:
  - src/home_manager/documents/pay_tables.py
  - tests/test_paystub_cleanup.py
  - docs/documents.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_cleanup.py tests/test_pay_tables_repairs.py tests/test_paystub_engine.py tests/test_paystub_engine_record.py tests/test_paystub_engine_generator.py tests/test_table_engine.py tests/test_layout_consumers.py tests/test_extraction.py -q"
    exit_code: 0   # 979 passed in 5:57
  - command: ".venv/bin/ruff check src scripts tests evals"
    exit_code: 1   # only the 2 pre-existing F402 errors (tests/test_document_v2_browser.py, tests/test_receipt_kinds.py)
  - command: "pay_tables.py reverted to 6102d16, pytest tests/test_paystub_cleanup.py -q"
    exit_code: 1   # 5 failed, 22 passed (see Tests); restored afterwards
escalations: []
---

# SL-07 round 2: rows printed in whole numbers only (R1-1, plan P1 step 7)

## Kept from round 1's partial work, and changed
- **Kept, unchanged:** the whole `pay_tables.py` change (`integer_only`, `nearest_column`, `whole_numbers`, and `read_block` calling it in
  place of the old inline tentative-column block) and the new tests. I read it against step 7 and it matches it; it also passes SC-94.
- **Changed:** one hunk the round-1 worker had added to the *existing* test `test_sc90_a_lone_integer_on_the_details_box_line_gives_no_row`
  (it referenced an undefined `result`). I reverted it; no existing test is edited (`git diff 6102d16 -- tests` is additions only).
- **Added:** the docs paragraph in `docs/documents.md` "Rows".

## Rule as built (`pay_tables.py`)
- `integer_only(line)`: at least two runs, led by text whose label run has no readable amount, and every later run holds one integer.
- `whole_numbers(...)` replaces the inline block of step 2 to 5. Integer-only lines (not consumed, not box lines) join the pay lines for
  the tentative integer columns (`whole_columns`), and zones, heading pieces and `heads_above` are computed as before.
  - An integer-only line counts only with a heading line above it, walking up over rows and section titles, so a details box above the first
    heading stays text.
  - A tentative column made only of integer-only lines' integers is kept only with a heading piece over it **and** two rows. A column that
    pay lines share follows step 5 (piece or two rows).
  - `nearest_column`: an integer within `ALIGN` font sizes of a decimal column's edge (at any alignment) becomes an amount of that column.
  - An integer-only line whose every integer is not read (kept column or decimal column) is dropped, and the loop repeats with the rest;
    its integers stay text.
- `read_block` then converts the kept and near tokens with `with_whole_numbers` and rebuilds `found` / `groups`, with the near tokens added
  to their decimal column. `table_engine.tokenize`, `tokenize_page` and `Line` are untouched (FR-67).

## Tests (tests/test_paystub_cleanup.py, SC-90 R1-1; literal values)
Run with `pay_tables.py` at 6102d16: 5 fail, the other 2 pass because they guard behaviour that was already right (recorded):
- FAIL before: `test_sc90_r1_1_a_table_printed_in_whole_numbers_only_reads_three_rows_with_the_total_holding` (case 1; also asserts values 100, 1300, 20, 260)
- FAIL before: `test_sc90_r1_1_a_whole_number_total_that_does_not_add_up_is_noted` (125 vs 120 gives a note)
- FAIL before: `test_sc90_r1_1_a_whole_number_in_a_table_of_decimal_amounts_is_an_amount_of_its_column` (case 2)
- FAIL before: `test_sc90_r1_1_a_details_box_above_the_whole_number_table_forms_no_row` (case 3)
- FAIL before: `test_sc90_r1_1_a_stub_printed_in_whole_numbers_records_its_lines_in_minor_units` (end to end, case 1: 10000/130000, 2000/26000, gross 12000/156000, each line cites a cell)
- pass before (guards): `test_sc90_r1_1_a_one_row_whole_number_column_under_no_heading_stays_text` (case 4), and
  `test_sc90_r1_1_a_column_of_integer_only_rows_with_no_heading_over_it_stays_text_though_two_rows_line_up` (the R-B stricter rule).

## Reviewer probe (/tmp/claude-fv/review_paystub_cleanup.py, rerun at bcc038f)
- `integers_only`: one table, columns Current / YTD with roles current / ytd, rows Regular {current 100, ytd 1300}, Bonus {current 20, ytd 260}; notes [], unplaced [].
- `integer_row_in_decimal_table`: same columns and roles, rows Regular {current 100, ytd 1300}, Bonus {current 20.00, ytd 260.00}; notes [], unplaced [].

## Open issues
- The extraction version string (`typed-extraction-v36-paystub-one-path`) is not bumped; the plan doesn't ask for it. Stubs read before this fix with whole-number-only rows are not re-read automatically.
- `docs/open-work.md` does not list this case; no change there. "Known limits" needed no change (the existing headless one-row limit still holds).
