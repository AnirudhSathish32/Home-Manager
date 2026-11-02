```yaml
slice: SL-02
round: fix-2
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 8e464cd
end_head: 4359a37     # the code commit; the handoff commit follows it
commit: 4359a37
changed_files:
  - src/home_manager/finance/splits.py
  - tests/test_splits_by_code.py
  - tests/test_receipt_tax_codes.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_splits_by_code.py tests/test_receipt_tax_codes.py -q"
    exit_code: 0     # 51 passed
  - command: ".venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_item_table.py tests/test_family_inbox.py tests/test_returns.py -q"
    exit_code: 0     # 87 passed
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

## Fix
`tax_parts` returned the empty plan as soon as the tax was 0/None. It now tries `by_tax_line` first when `source == "tax_lines"` and there are tax lines, passing `tax or 0`; the `not tax` early return moved after that block, so tax_source NULL / legend / printed behave as before.

`by_tax_line` with a zero tax: lines that don't add up (None counts as 0 in the text) give the usual reason plus any per-item issues, no parts, `by_code` False, so the whole charge difference is spread by amount. Lines that add up to 0 with tax 0 give no reason and an empty plan (per-item issues, if any, still listed). A nonzero tax is unchanged. `ledger.py` needed no change: `record()` already reads `plan.issues` for `tax_issues` and `issues`.

## Tests
- `test_splits_by_code.py`: tax 0 and None with R0's lines → the issue, no parts (shares 449/4384/1359, worked in a comment); a zero tax still names a two-code item; zero lines with zero tax → no issue; zero tax without usable lines or with other sources → unchanged empty plan.
- `test_receipt_tax_codes.py`: `test_correcting_the_tax_to_zero_falls_back_with_the_reason_and_back` publishes R0, corrects Tax to 0.00 via `manager.correct_record`, asserts the issue in `tax_issues` and `issues`, shares 449/4384/1359 (arithmetic in a comment), then corrects back to 2.74 through the API → no issue, shares 445/4347/1400.
- Removed the round-1 `test_no_tax_means_no_parts_and_no_issues`: it asserted no issue for tax 0 with R0's lines and a two-code item, which is the behavior this finding reverses. Its "no parts" and "unchanged total" assertions live on in the new tests.

## Open issues
None.
