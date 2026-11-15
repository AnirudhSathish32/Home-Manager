```yaml
slice: SL-04
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 045bb57
end_head: 39aba82   # the code commit; the handoff itself is committed on top of it
commit: 39aba82
checks:
  - command: ".venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_migrations.py tests/test_receipt_kinds.py tests/test_reextraction.py tests/test_traces.py tests/test_receipt_discounts.py -q -p no:cacheprovider -rf"
    exit_code: 1     # 152 passed, 3 failed: exactly the 3 tax-trace failures of tests/test_traces.py listed in baseline-failures.txt (2m18s)
  - command: "grep -ciE '^[[:space:]]*(update|insert|delete|drop|create|replace)' src/home_manager/library/migrations/081_dining_receipts.sql   (C-SL04)"
    exit_code: 1     # prints 0 (grep -c exits 1 when nothing matches)
  - command: ".venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_migrations.py tests/test_receipt_side_lines.py tests/test_vision_indent.py tests/test_bill_engine_record.py::test_sc121_no_migration_is_added_by_this_feature -q -p no:cacheprovider   (after the last fixture lint fix; side-lines and indent files rerun because record() changed)"
    exit_code: 0     # 122 passed
  - command: ".venv/bin/ruff check src tests/test_dining_receipts.py tests/dining_receipt_fixtures.py tests/test_migrations.py tests/test_bill_engine_record.py"
    exit_code: 0
  - command: "git diff --exit-code 045bb57 -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```
SL-04 is built: amounts, citations, review state, the exact link and C-sum. Every C-cat / "By category" / stored-item-category check is left for SL-05 (marked `# SL-05: C-cat` in the tests).

## What was done
- `documents/dining_total.py` (new, P4): pure `decide(header, lines) -> DiningDecision(header, tip_basis, issues, total_changed, tip_changed)`. Suggested-tip table = maximal run of consecutive lines with a percentage and another amount (a run of one counts only if it names a tip or has a heading before it) plus a directly preceding "Suggested Tip / Tip Guide / Tip Suggestions" heading. Pre-tip amount = a non-table line starting with Total / Grand Total (not Total Tax, Item Count, Savings, Discounts… ) or Bill / Amount due / Balance due and ending in an amount; post-tip total = the latest Total line larger than the nearest pre-tip amount before it. Results: the total is the post-tip line (whole-line citation); a table-only total is dropped and replaced by the post-tip total, else the nearest pre-tip amount before the table, else missing; a table-only tip is dropped; a missing/dropped/unprinted tip is worked out as post − nearest pre-tip when a non-table `Tip` line is printed and the earlier pre-tip amounts agree (cites the pre-tip line then the post-tip line, `tip_basis` has both lines); disagreeing amounts add the D23/D29 issue and no tip; a printed tip that doesn't make the total adds the FR-03 issue. Issues keep their amounts as decimals (`Issue(template, amounts)`) until the currency is known.
- `extraction.py`: `record` runs `decide` for a receipt read as dining (before `result` is built, so the saved header holds the decided values), drops the model's table-cell references for a total/tip it replaced, saves `result["dining"]`, and passes the decision to `publish(..., dining=)`. `publish` writes the issue texts (with `amount_text`) into `notes` before `issues.extend(notes)`, and adds FR-06's reason after `review_reasons`: "Tip $8.79 was worked out from Total $61.55 less Bill $52.76, not printed; check it." and sets `record["tip_worked_out"]` (tip_basis + `total_minor`/`bill_minor`).
- `core/money.py`: `amount_text(minor, currency)` ($, €, £ prefixed; `format_minor` text otherwise).
- `library/migrations/081_dining_receipts.sql`: three `ALTER TABLE … ADD COLUMN` only: `receipts.one_category INTEGER NOT NULL DEFAULT 0 CHECK (0,1)`, `receipts.tip_worked_out_json TEXT`, `record_corrections.item_categories_json TEXT` (the last two columns are for SL-05/06; `one_category` is not read or written by anything yet).
- `finance/ledger.py`: `publish_receipt` writes `tip_worked_out_json`; `Ledger.worked_out_tip(db, row)` (the P6 marker: set and no tip correction in force, an undo back to the first value shows it again); the record payload gains `tip_worked_out` (bool) and `tip_note` ("Worked out: Total $61.55 − Bill $52.76", U+2212) and no longer exposes the raw column. `finance/document_traces.py`: the dining check's Tip input is labelled "Tip (worked out)" while the marker holds (provenance cites both lines from the saved header).
- Tests: `tests/test_dining_receipts.py` (new, 50 tests): SC-01 steps 1–5, 7 (tip note only), 8 (+a, b, d), SC-02 (+a), SC-03 (+a–d), SC-04 (steps 1–3, a–d), SC-06 (+a, b), SC-19, unit tests of `decide` for every rule branch (Sub Total, Grand Total, every label, a table without heading, no tip line, the latest total, disagreement, printed tip good/bad, heading is not a tip line, a tax-rate line is not a table, determinism) and `amount_text`. `tests/dining_receipt_fixtures.py` gains `insert_old_receipts(db, names)` (plain SQL: old receipts A–E, G, H with items, receipt splits, a v6 parse run holding the R6 capture, a v56 extraction run, one memory row). `tests/test_migrations.py`: X-UPG (`test_081_dining_receipts_adds_three_columns_and_changes_nothing_else`) and C-SL04 as a test.

## Notes for later slices
- **Existing test changed beyond the plan's list:** `tests/test_bill_engine_record.py::test_sc121_no_migration_is_added_by_this_feature` asserted exactly 80 migrations (001–080); it now expects 81 with `081_dining_receipts.sql` last. Not avoidable once a migration exists.
- Re-reads in tests need `start_extraction(doc, parse, True)` (force); with `False` an unchanged parse/config reuses the extraction run and sends no request. `read_again` in `test_dining_receipts.py` does this; `read`/`breakfast` helpers drop the unused `ReceiptStarts` reply when the lines hold a single total line (`looks_like_several`).
- The old-library builder is rows only (no folders, no charges): SL-05+ add the `ReceiptService.folder` files, K52/K61/K60 charges and the "recording through the old reading" part as they need them.
- `tip_basis` is stored as the plan says; the stored `tip_worked_out_json` is `tip_basis` + `total_minor` + `bill_minor`. The dining category at recording (`record["category"] = "dining"`) and every FR-10 piece are SL-05's; `publish` does not touch the category yet.
- The "Tip" FR-06 reason starts with "Tip", so `Ledger.correct` resolves it; SC-06 (auto-verified, `totals_mismatch`, Extract again keeps 900, Undo brings the marker back) is covered.
- The three `tests/test_traces.py` failures are the baseline's.

## Open issues
None. Not run (outside the slice's command): the full suite, browser tests, the other slices' commands except the side-line/indent files noted above.
