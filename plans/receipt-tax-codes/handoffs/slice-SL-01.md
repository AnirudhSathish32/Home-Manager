```yaml
slice: SL-01
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 5c9f014
end_head: 3dde201          # the code commit; the handoff commit follows it
commit: 3dde201
changed_files:
  - src/home_manager/library/migrations/075_receipt_tax_codes.sql   # new
  - src/home_manager/finance/ledger.py
  - src/home_manager/finance/family_routing.py
  - tests/test_migrations.py
  - tests/test_family_inbox.py
  - tests/test_receipt_tax_codes.py                                  # new
checks:
  - command: ".venv/bin/python -m pytest tests/test_migrations.py -k 075 -q"
    exit_code: 0            # 1 passed, 22 deselected
  - command: ".venv/bin/python -m pytest tests/test_receipt_tax_codes.py -q"
    exit_code: 0            # 16 passed
  - command: ".venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_item_table.py tests/test_reextraction.py tests/test_bills_ledger.py tests/test_migrations.py tests/test_family_inbox.py tests/test_family_routing.py -q"
    exit_code: 0            # 120 passed, 1 skipped (opt-in browser test)
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

## What changed
- **Migration 075** exactly as the plan's "Stored data": `receipt_items.tax_code`, `receipts.tax_source` (CHECK on
  `tax_lines|legend|printed`), STRICT `receipt_tax_lines` (cascade on receipt, `UNIQUE(receipt_id, position)`),
  `user_version=75`. Nothing existing is touched.
- **`ledger.publish_receipt`** writes `tax_source` with the receipt (`record.get("tax_source")`, so bills and records without a
  reading get NULL). When `written`, it deletes and re-inserts `receipt_tax_lines` from `record["tax_lines"]`
  (`{code, rate_text, taxable_minor, amount_minor, locator}`), like `receipt_rewards`. A reviewed record writes nothing.
- **`_replace_items`** writes `item["tax_code"]` in both the UPDATE and INSERT.
- **`Ledger.record`** returns `tax_lines` (printed order; `taxable_minor` and `amount_minor` signed by the sign of `tax_minor`,
  `rate_display`, `line_ids`, and `display` through the existing display loop) and `tax_source`/items' `tax_code` (already
  carried by `SELECT *`). New module function `rate_display` ("7.75000" gives "7.75%", "10.000" gives "10%", `None` when not a
  finite number; a trailing "%" is tolerated).
- **`family_routing.record_payload`** (P6) carries each item's `tax_code`, the receipt's `tax_source` and its tax lines
  (locator `{"family": True}`); `apply_delivery` needed no change because it already goes through `publish_receipt`.
- No split rule, reading, API-note or page changes (SL-02 onward). `category_splits` are unchanged for every receipt.

## Tests added
- `test_migrations.py::test_075_…`: v74 database by SQL (receipt, 3 items, splits); after 075 every pre-existing column of
  `receipts`, `receipt_items` and `category_splits` equal, `tax_code`/`tax_source` NULL, table empty; CHECK, STRICT and cascade.
- `test_receipt_tax_codes.py`: publish with tax lines through `Ledger.publish_receipt`; same reading twice (no duplicates) and a
  new reading replacing codes and lines; reopen the store; a reviewed record isn't rewritten; return sign; unreadable
  amount and unparseable rate; `rate_display` cases; **SC-09** (R and D published the old way: splits and flags identical after
  `refresh_splits(db)`, `Reconciler.run`, reopen; R is 429/4190/1573; no codes/lines; `check_ledger` clean).
- `test_family_inbox.py::test_a_delivered_receipt_keeps_its_tax_codes_lines_and_source`: R with two tax lines through
  `record_payload` (JSON round trip) and `apply_delivery` into a member library, applied twice: same codes, `tax_source`, lines
  and splits as the sender's, no duplicates. It asserts equality with the sender's shares; the exact 445/4347/1400 numbers are
  SL-02's job as the plan says (the rule doesn't exist yet).

## Notes for the orchestrator
- The tests publish through `Ledger.publish_receipt` with hand-built records (no extraction), as SL-01 has no producer.
- `plans/receipt-tax-codes/progress.yaml` was already modified in the checkout before I started; I left it alone and did not
  commit it.
- Skipped: the full suite and browser tests (not in the slice's commands).
