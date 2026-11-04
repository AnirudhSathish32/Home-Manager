```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 688916f
end_head: 0394f13   # the code commit; the handoff file is committed right after it
commit: 0394f13
checks:
  - command: ".venv/bin/python -m pytest tests/test_paystub_engine_record.py -q"
    exit_code: 0   # 33 passed
  - command: ".venv/bin/python -m pytest tests/test_layout_consumers.py tests/test_paystub_forms.py tests/test_table_engine_record.py tests/test_statement_forms.py -q"
    exit_code: 0   # 154 passed, 2 warnings
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1   # only the 2 errors that exist at START_HEAD (tests/test_document_v2_browser.py:410, tests/test_receipt_kinds.py:977); my files are clean
escalations: []   # none blocking; E1 below is a contract inconsistency the orchestrator should know about
```

# SL-04 handoff: unclassified rows, summary box, mismatch/unplaced/guess notes on the record

This is a resume: a previous worker stopped on a rate limit leaving an uncommitted diff. I read all of it against the plan (P5–P7) and the contract (SC-56, 60, 61, 62, 64, 70), found it complete and correct, changed nothing in it, ran both verification commands and ruff, and committed it. Not committed: `plans/.../progress.yaml` (untracked, orchestrator-owned).

Files: `src/home_manager/documents/extraction.py`, `src/home_manager/finance/paystub_tables.py`, `tests/test_paystub_engine_record.py` (+14 tests, 33 in the module), `tests/test_layout_consumers.py` (the one test the contract names).

## What now happens
- **FR-62 unclassified rows** (`unclassified_rows`, `with_unclassified`, `guess_groups` in `extraction.py`): an engine row (not a totals row, not a totals label) with an amount in the this-period/YTD column that no model line took is added as a pay line in printed order, category `other`, amounts copied from its cells, evidence citing every line of its label. Its group: the section title's words (`paystub_tables.section_group`: employer, pre-tax/before tax, post-tax/after tax, earn, tax/statutory/withholding, deduction/voluntary), else the first of earnings, tax, pre_tax, post_tax under which the stub's earnings = gross and gross − deductions − taxes = net checks hold (`checks_hold`), else the nearest classified line above (below for the first). Each gets a `group_guessed` guess and the record note `Page N: the printed pay line "…" wasn't classified, so it was recorded as … (why).` The "native table row(s) were not accounted for" note is not added for `pay_engine` tables.
- **FR-75 / FR-61 summary box** (`paystub_tables.adapt_boxes` → `PaystubTables.box_cells`, `BoxRead.heads`; `box_cell`/`box_field`/`settle_box` in `extraction.py`): gross/net/taxes/deductions (this period) and gross/net YTD come from the box after the totals rows and before the model, cited at the box cell with its row label and column heading, with a value reference. A totals row and the box disagreeing → the one equal to the pay lines' sum is kept, with a record note naming page, both amounts and which was used.
- **FR-63**: `paystub_tables.mismatches`: a gross/earnings/taxes/deductions total that differs from its covered rows' sum in a this-period or YTD column → record note `Page N: the printed total "…" X (this period) doesn't match the lines above it, which add up to Y.` (`covered_rows` is the extracted shared rule of `pay_columns`). No review reason; net pay is not a section total, so a misprinted net still goes through today's arithmetic check (SC-62 b).
- **FR-56**: `paystub_tables.unplaced_notes` → `Page N: a printed line wasn't placed in any column, so it wasn't recorded: "…"`.
- **FR-58/59/74**: the engine's guess notes were already carried (SL-03); `read` now also stores the guesses Record makes (`extras.guesses`) in `reading["guesses"]`, so `details["guesses"]` holds `headings_overruled` / `columns_guessed` / `box_columns_guessed` / `group_guessed`. FR-58: the overruled heading is not cited for the column (`adapt` sets `table.overruled`; `cell_labels` skips it).
- Every note added is a record note (`reading["record_notes"]`); nothing was added to `notes`/`issues`.

## Test-contract coverage (`tests/test_paystub_engine_record.py`)
SC-56 (engine-level: two other tables, no unplaced; Record: EXP-PS six lines, deposit splits 155189/50000, no note, C-auto), SC-60 (engine unplaced on page 1; Medicare `(tax, 3897, 48756)` via the `Taxes` title, notes with `Medicare`, `Page 1`, `Bonus advance memo`, none in issues, count note gone, C-auto; plus two plan-rule tests: group from the totals, group from the line above), SC-61 a / b1 / b2 (notes, guess kinds, C-auto / C-no-feature-review / FR-22 reason only), SC-62 a (taxes 51023, note naming `510.23` and `501.23`, C-auto) and b (net 206189, `needs_review`, today's net-pay issue), SC-70 SB and SB-SHUF (parametrised; no note, no guess, C-auto, each field cites its box cell) and SB-NOHEAD (left-as-taxes note, one `box_columns_guessed`), a totals-line-vs-box disagreement test (box kept, both notes), and a determinism test for the new notes and guesses. SC-70's engine-level step 1 (box columns/rows) is SL-02's.

## tests/test_layout_consumers.py (SC-64)
`test_missing_native_rows_are_reviewed_and_blank_current_is_not_ytd` is the only test changed. **Its `native_result` reading has an engine pay table**, and the test used to call `read` with `pay=None` (today's path, hence the count note). It now passes `pay=paystub_tables.read(result)` plus an import line. Its blank-current assertion is kept (Bonus current None, ytd `500.00`); the "2 native table row(s)" assertion is replaced by: the two unclassified rows (Regular pay, Adjustment) recorded as earnings in printed order, no count note, a record note naming each, two `group_guessed` guesses. No other existing test changed.

## E1: contract inconsistency (SC-61 b2), not a blocker
B2 expected lists `(Shift Premium, earnings, 30000, 15000)` and also says FR-22 (b) fires for it so "that line's this period is null and ambiguous". Both can't hold for `current_minor`. The test asserts the engine copies 30000 and today's FR-22 (b) nulls it (`current_minor` None, `details.current_status == "ambiguous"`), `needs_review`, and every reason names Shift Premium (apart from the reader's own "PDF layout needs review" message, as in SL-03). Everything else in B2 expected is asserted as written. The orchestrator may want the contract wording fixed.

## Notes
- `docs/` were not updated (not in this slice's file list); the final slice or docs pass should describe the notes/guesses on the record.
- Checked against the plan's decisions: note texts follow P5/P7 wording with a trailing `(why)` for the group guess; `GROUP_WORDS` order puts employer and pre/post-tax before the generic tax/earn words so "Pre-tax" never reads as tax.
