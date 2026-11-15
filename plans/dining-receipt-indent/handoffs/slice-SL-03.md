```yaml
slice: SL-03
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 0aa10d0
end_head: aa6dd06   # the code commit; the handoff itself is committed on top of it
commit: aa6dd06
checks:
  - command: ".venv/bin/python -m pytest tests/test_receipt_side_lines.py tests/test_vision_indent.py tests/test_extraction.py tests/test_receipt_kinds.py tests/test_bill_account_holder.py tests/test_bill_engine_record.py tests/test_bill_printed_total.py tests/test_receipt_tax_codes.py tests/test_layout_consumers.py -q -p no:cacheprovider"
    exit_code: 0     # 779 passed in 665s (needs a background run: over the 10 min foreground limit)
  - command: ".venv/bin/ruff check src scripts <the seven edited/new test files>"
    exit_code: 0
  - command: "git diff --exit-code 0aa10d0 -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```
SL-03 is built. This is a retry: a previous worker wrote the code uncommitted, and it was reviewed against the plan and spec, then verified and committed unchanged apart from the note below.

- `extraction.py`: `EXTRACTION_VERSION = "typed-extraction-v57-dining-indent"` (P1); `line_payload(line)` (`{line_id, text}` plus `indent` only when known) used at all six places (`chunks`, both `paystub_chunks` measures, `table_summary.measure`, `whole`, `ask`); `SIDE_LINES_RULE` (FR-22) appended to the receipt row instruction before the kind's `KIND_ROWS` text, receipts only; the P12 backstop `attach_side_lines`, called from `record` for receipts only. A row is dropped when every cited line has known indent >= 1, none prints an amount, and a kept row precedes it. Its citations join the previous kept row, `item_categories` and `cell_references` drop the same index, and there is one note per dropped row (at most three, then "and N more"). Unknown indent keeps the row (SC-14).
- Notes reach the receipt as issues (P11); `result["notes"]` carries them too.
- Tests: the three version asserts moved to v57; new `tests/test_receipt_side_lines.py` (SC-13 + a–e, SC-14, step 2 from an old reading, indent 0/None variants); `tests/test_vision_indent.py` gains SC-10 step 4, SC-12 step 3 + (e) (byte compare of R6/P3/G2 requests with `q56_*.json`, masking the old and new row instruction), and SC-12a (embedded-text page sends no indent). `dining_receipt_fixtures.py` stubs gained the grocery form's `savings_total`/`tenders` and category alignment fixes.
- SC-13 step 5 (the receipt split, C-sum 6155, C-cat dining) needs FR-01/FR-10 and is not checked here (SL-04/SL-05).
- Not run: the full suite and the other slices' commands (orchestrator's job).
