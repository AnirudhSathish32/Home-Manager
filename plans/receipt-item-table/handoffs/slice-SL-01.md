```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: c81cd11
end_head: ddf1443        # the slice commit; the handoff itself is committed after it
commit: ddf1443
changed_files:
  - src/home_manager/finance/splits.py
  - src/home_manager/finance/ledger.py
  - tests/receipt_item_fixtures.py        # new
  - tests/test_receipt_item_table.py      # new
checks:
  - command: ".venv/bin/python -m pytest tests/test_receipt_item_table.py -q"
    exit_code: 0          # 53 passed
  - command: ".venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_kinds.py tests/test_reextraction.py tests/test_bills_ledger.py -q"
    exit_code: 0          # 68 passed, 1 skipped (opt-in browser test)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
  - command: ".venv/bin/python -m pytest -q"
    exit_code: 1          # 54 failed, 20 errors, 2165 passed, 102 skipped; all pre-existing, see below
escalations: []
```

## What was built
- `splits.tax_basis(items)`: the taxed items' amounts, or every item's amount when no taxed item has one. `allocate` now calls
  it in place of the inline expression (`spread(tax, tax_basis(items))`). Same expression, so stored shares don't change.
- `ledger.item_table(item, receipt, basis_by_id, currency)` beside `shown_details`, implementing the plan's rules 1–5 for
  qty and unit_price and the `tax_included` rule. `Ledger.record` sets `item["table"]` on every non-bill receipt item; bills
  get no key. `basis_by_id` comes from `split_inputs` + `tax_basis`, matched by id (empty when `split_inputs` is `None`).
- `tests/receipt_item_fixtures.py`: R/RA, D, G and N/NA exactly as the contract prints them (`R_LINES`, `ra_replies()`, etc.),
  with the hand-worked amounts and shares as constants.
- `tests/test_receipt_item_table.py` (53 tests): `item_table` unit tests for every rule branch (R's three items, G's
  bananas/yogurt/milk, quantity "1", "-1", "0.5", "2x", "NaN", U+2212 minus, price-per-weight text forms, weight without a
  price per weight, no line total), `tax_included` (R, D, no taxed item, tax 0, no share, rejected item, [+1000, −1000]
  with tax, N's filter), `tax_basis`, `allocate` still giving D's 162/53999/8000, and `Ledger.record` tests for R/RA
  (P-check 5918/274/6192, shares 429/4190/1573, the three `table`s, Ruffles' stored quantity still NULL), D, G, N/NA
  (`direction` "return", −1299/−101/−1400, share −1400, `table` qty "1", unit price "-12.99 USD", `tax_included` true) and a
  bill without `table`.
- Expected values are the plan's and contract's. None was taken from running the code. Every fixture P-check passed on the
  first run, including RA's tax 2.74 (cited to both GA TAX lines).

## Notes for the verifier
- The full suite is **not** green: 54 failed + 20 errors in `test_agent_instance`, `test_agent_findings`, `test_agent_guards`,
  `test_cpa_pack`, `test_engine_worksheets`, `test_scenarios`, `test_tax_engines`, `test_tax_family`, `test_tax_year`,
  `test_tax_zen`, `test_traces` (tax engines and the agent harness; e.g. `KeyError: 'result_minor'`, `AttributeError`). I ran
  those 11 files against `git archive c81cd11 src` (START_HEAD, without my change) via `PYTHONPATH`: the same 54 failed and
  20 errors. So they predate SL-01 and are unrelated to receipts. Nothing in the receipt, splits, bills or re-extraction
  suites fails. The orchestrator should decide whether these block the "full suite green" rule in the plan.
- The full run takes about 22 minutes here. I ran it once after the code was final (the only later edit was ruff's import
  reorder in my two test files).
- `uncommitted` files left alone: `plans/receipt-item-table/progress.yaml`, `specs/receipt-tax-codes/*`.
- Browser tests were not run (SL-01 doesn't touch the browser); `RUN_BROWSER_TESTS` is unset, so they are skipped.
- Dimension of judgement: a weight whose `price_per_weight` has no text yields `unit_price: None`; a weight detail without
  a `display` is ignored (treated as no weight). Neither case is in the plan's text; both follow rule 2 and the "never
  raises" line.

## Open issues
None for SL-01.
