```yaml
slice: SL-01
result: ready_for_verification   # round 2
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 814fe16
end_head: <the commit; see `git log -1`>
commit: <this commit>
changed_files:
  - tests/pdf_import_fixtures.py      # plan shapes for date-like/amount-like, candidate_rows, below_table_rows, 7-c fixture fix
  - tests/test_pdf_imports.py         # V gate test replaced; assert_row_cells uses the plan's candidate rule; V added to helper-agreement test
  - plans/account-import-pdf/handoffs/slice-SL-01.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_pdf_imports.py -k pcheck -q"
    exit_code: 0   # 35 passed
  - command: ".venv/bin/python -m pytest tests/test_pdf.py tests/test_pdf_layout.py -q"
    exit_code: 0   # 39 passed (test_pdf.py not edited this round)
escalations: []
```

# SL-01 handoff, round 2: fixtures and the G1/U2 gate

No application code changed. Spec, plan, `progress.yaml`, approvals and `~/.agent-harness` untouched.

## What changed

- `test_pcheck_sc25_v_v5_cell_is_one_native_cell_without_a_layout_review` (failed on purpose in round 1) and
  `..._v_page_keeps_the_long_cell_clear_of_the_other_columns` are replaced by one test,
  `test_pcheck_sc25_v_native_table_is_the_heading_v1_and_v2_and_v3_to_v5_are_one_visual_row_each_below_it`, that asserts
  the reworded V bullet.
- `DATE_WORD` / `AMOUNT_WORD` now follow the plan's "Rows" shapes (FR-06 dates only, so no 3-digit years; amount-like is a
  digit-led run of digits, `,` and `.` with optional sign, symbol and suffix, so `1.2.3` and `12345` are amount-like).
- New helpers `candidate_rows` (date-like in the Date span and amount-like in an Amount/Debit/Credit/Withdrawals/Deposits
  span; a Balance-only amount is not a candidate) and `below_table_rows` (visual rows below the native transactions
  table's last row). `assert_row_cells` now uses `candidate_rows`.
- **Fixture fix found by the new candidate rule:** X variant 7-c blanked only the Deposits cell, so A2 printed only a
  Balance amount and was not a candidate. The contract says A2 is a withdrawal of 20.00 (7-c totals out 31.00, in 2.00), so
  `x_cells(only_withdrawals=True)` now prints every amount in the Withdrawals column. No expected value changed.
- V is added to the visual-rows / heading-texts agreement test.

## Gate bullets

1. **Every intended native page reads as `embedded_text` with no model: MET.** Every `read()` asserts it with no model
   config; M reads `["embedded_text", "vision_model"]` with one model request.
2. **The amended P-checks hold: MET.** All 35 P-check tests pass against the plan's candidate rule: headerless pages have no
   native transactions table, every rebuilt heading is one visual row with boxes, X pages 1 and 3 have the stated native
   tables, and footers are words-only, so no page meant to be clean carries `unresolved_columns`.
3. **SC-16's 2,001-character cell reads as one native cell with no `pdf_layout_review`: MET**
   (`test_pcheck_sc16_long_cell_reads_as_one_native_cell_without_a_layout_review`).
4. **V (reworded): MET**, all in the one V test:
   - the native transactions table equals the heading, v1, v2 (and is the page's only native table);
   - `layout.issues == ["unresolved_columns"]`;
   - the heading is one visual row equal to the table's row 0;
   - the rows below the table's last row are v3, v4, v5 and the footer: v3 to v5 are each one visual row, and they are
     exactly the page's candidate rows;
   - each maps to the heading's column spans with no straddling word (v3: date, 1.00, 989.00 with no description; v4: 1.2.3);
   - v5's 480-character description is one text lying inside the Description span;
   - no `glyph_outside_page`, `overlapping_text` or `unsupported_text_rotation`.

## Notes for SL-02

- `fx.below_table_rows` and `fx.candidate_rows` are test helpers re-implementing the plan's text, not application code.
- The `-k pcheck` filter deselects `tests/test_pdf.py` and `tests/test_pdf_layout.py` when they are on the same command line,
  so they are run separately.

## Round 1 note

Round 1 (commit abc1509, start 803c588): built `make_pdf` options, `tests/pdf_import_fixtures.py` and 36 P-check tests. Every gate bullet held except V: the reader cuts V's native table short at v3's blank description, so the then-gate ("V reads as one native table with v5 as one cell") could not be met and the slice escalated with evidence. The plan was then revised (P13, below-table rows) and the V bullet reworded.
