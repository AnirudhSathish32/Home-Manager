```yaml
slice: SL-04
result: ready_for_verification
scope: code review round 1 fixes (CR1-M1, CR1-m1)
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 24950d0
end_head: c90a340            # the fix commit; the commit adding this handoff follows it and changes only this file
commit: c90a340
changed_files:
  - src/home_manager/finance/ledger.py
  - tests/test_receipt_item_table.py
  - docs/money.md
checks:
  - command: ".venv/bin/python -m pytest tests/test_receipt_item_table.py -q"
    exit_code: 0            # 60 passed
  - command: ".venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_kinds.py -q"
    exit_code: 0            # 51 passed
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks:
  - "full suite: deferred to the final verification"
escalations: []
```

## CR1-M1 (major) — fixed
`item_table` (ledger.py) no longer uses `abs(counted) != 1`, which applied the Decimal context (Overflow on "1e1000000";
rounding of 29-digit fractions to 1). It now tests `counted not in (Decimal(1), Decimal(-1))` after the `is_finite()` check.
Equality is exact and context-free, and the finite check keeps sNaN/NaN/Infinity from reaching the comparison. Nothing else in
`item_table` touches the quantity text with context-dependent arithmetic.

Tests added in tests/test_receipt_item_table.py: a parametrized never-raises test ("1e1000000", "-1e1000000", "1E-1000000",
"1.00000000000000000000000000001", "0.99999999999999999999999999999", "-1.00000000000000000000000000001": unit_price None, qty
echoes the text), and `test_a_quantity_too_large_for_decimal_still_loads_through_record` (stores "1e1000000" on a Ledger.record
receipt's first item and checks the record loads with unit_price None). The existing "1"/"-1"/"1.0"/" 1 "/"-1.00" cases still take the line
total. I confirmed the 6 new cases fail against the old code and pass with the fix. No contract or existing expected value changed.

## CR1-m1 (minor) — fixed
docs/money.md "Item categories and splits" (heading kept): the Unit price bullet says a quantity of exactly 1 or −1 (or none)
shows the line total and any other count with no unit price shows "—". The Paid bullet states the tax rule per
`splits.tax_basis` and `item_table`: tax is spread over the taxed items, or over every item when the taxed items' amounts add
up to zero; "with tax" shows when the receipt has tax, the item has a share and its weight in that spread is non-zero.

## Notes
The uncommitted specs/receipt-tax-codes/ changes were left untouched and unstaged. Nothing was pushed.
