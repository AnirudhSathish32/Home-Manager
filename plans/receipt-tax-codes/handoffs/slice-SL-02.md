```yaml
slice: SL-02
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 2197ef4
end_head: bb35893          # the code commit; the handoff commit follows it
commit: bb35893
changed_files:
  - src/home_manager/finance/splits.py
  - src/home_manager/finance/ledger.py
  - src/home_manager/finance/traces.py
  - tests/test_splits_by_code.py          # new
  - tests/test_receipt_tax_codes.py
  - tests/test_family_inbox.py
checks:
  - command: ".venv/bin/python -m pytest tests/test_splits_by_code.py tests/test_receipt_tax_codes.py -q"
    exit_code: 0            # 46 passed (24 unit + 22 ledger-level)
  - command: ".venv/bin/python -m pytest tests/test_spending_splits.py tests/test_receipt_item_table.py tests/test_traces.py tests/test_family_routing.py tests/test_family_inbox.py tests/test_health.py tests/test_returns.py tests/test_bills_ledger.py -q"
    exit_code: 1            # 128 passed, 3 failed, 1 skipped; the 3 failures are tests/test_traces.py tax-engine tests, failing identically at START_HEAD
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
escalations: []
```

## What changed
- **`finance/splits.py`**: `TaxPlan` (`parts`, `by_code`, `issues`, `codes`, `included(index)`), `tax_parts(items, tax, tax_lines, source, currency=None)`
  and `by_tax_line`. `allocate(..., tax_parts=None)` spreads each part with the existing `spread`; `None` keeps today's single
  `spread(tax, tax_basis(items))`.
  - `tax_minor` 0/None: no parts. `source == 'tax_lines'` with at least one coded line: lines grouped by code (amounts added, FR-23),
    membership by FR-10 on the items' codes (spaces and case ignored). Consistent (readable amounts, sum == |tax|, every group has
    a member, every group > 0 has members with a non-zero weight sum): one part per code, `sign(tax) × amount`. Otherwise: the
    stored flags (`tax_basis`) plus the reason(s). `printed` with any `taxed` NULL: one part over every item's amount (FR-29).
    Everything else (`NULL`, `legend`, `printed` with all flags answered) is exactly the old expression.
  - FR-18 issues (two line codes, or a non-empty code matching no line) are reported with or without the fallback. An empty code is
    not named (P2). Issue amounts use the server's money text (P3), e.g. "2.74 USD".
  - Extra reason I worded myself (the plan gave none): "The B tax line's items add up to nothing, so tax was shared across the taxed items."
- **`ledger.py`**: `split_inputs` selects `tax_code` and returns `receipt` as a dict with `tax_lines` (`[(code, amount_minor)]` by
  position) beside the stored `tax_source`; `Ledger.tax_plan(receipt, items)`; `shares` passes the parts to all three `allocate`
  calls. `record()` (receipts, not bills) returns `tax_lines_used`, `tax_issues` (also appended to `issues`, deduplicated, never
  stored) and `item["table"]["tax_note"]`; `tax_included` now comes from `TaxPlan.included`, which equals the old condition for a
  single part.
- **`traces.py`**: the split trace's formula says "the tax shared by amount within each tax code" only when the plan is by code.

## Deviation to know about (SL-04 consumes it)
`item["table"]["tax_note"]` is present only as `"with B tax"` (for an item that holds part of a tax line's amount). It is **absent**,
not `"with tax"` or `None`, for every other item. The plan said `"with tax"` when `tax_included`, else `None`, but
`tests/test_receipt_item_table.py` pins the whole `table` dict (`{"qty","unit_price","tax_included"}`) for receipts without tax lines,
and the task says those tests pass unchanged. SL-04's page should show `row.table.tax_note`, else `"with tax"` when
`row.table.tax_included`, which is today's behavior. A code-matched item with `tax_included` false (zero amount) gets no note.

## Tests
- `tests/test_splits_by_code.py` (no database): R0 445/4347/1400; SC-04 450/4391/1361; SC-05 454/4439/1299; SC-06 429/4363/1400; SC-07
  449/4384/1359 and back; SC-15 same-code sum; SC-16 and SC-18 (+ all-answered variant 429/4190/1573); B unreadable (449/4384/1359, issue);
  zero-weight line; 0.00 line without members (fallback) and with one (429/4399/1364, worked out by hand in the test); return
  (negative tax); no tax; unmatched and empty codes; `source None`/`legend` equals `tax_basis` on D (162/53999/8000), RA (429/4190/1573)
  and the no-flags case, and `source None` ignores stored lines; a discount and tip still sum to the target.
  `rate_display` cases already live in SL-01's test file.
- `tests/test_receipt_tax_codes.py` (ledger level, through `Ledger.publish_receipt`): `record()` fields for R0; the SC-04 fallback record
  (issue in `tax_issues` and `issues`, not stored, lines kept, no `tax_note`); the BT item named; **SC-07** through
  `manager.correct_record("receipt", id, {"tax": "3.00"})` and `PATCH /api/finance/records/receipt/{id}` back to 2.74 (total, subtotal,
  tip unchanged by SQL; issue added then cleared); **SC-10** (matched −61.92 USD charge 445/4347/1400; 50/50 share sums to 3096 with each
  category within a cent of half; −57.00 EUR charge sums to 5700 with each within a cent); the split trace wording. New helper
  `r_derived_receipt` stores R0 with the flags FR-11 derives (all taxed), as recording will in SL-03.
- `tests/test_family_inbox.py`: the delivery test now asserts the member's copy has 445/4347/1400.

## Notes for the orchestrator
- The 3 `tests/test_traces.py` failures (`test_the_return_and_tax_zen_trace_to_the_engines_lines_and_the_records`,
  `test_the_engines_own_steps_trace_down_to_the_return_inputs_and_the_law`, `test_family_figures_trace_to_each_members_own`) fail the same way
  at START_HEAD (checked by stashing my source changes): the tax engine subprocess dies with `node: bad option: --allow-fs-read`. They're part
  of the recorded pre-existing baseline, unrelated to this slice. Every other test in the second command passes, including
  `test_spending_splits`, `test_receipt_item_table`, `test_returns`, `test_health` and `test_bills_ledger` unchanged.
- SC-10's EUR link is inserted by SQL: a USD receipt matched to a EUR charge is a link the user has to choose (`check_ledger` flags it), so
  that test runs the health check before adding it and not after.
- No docs, extraction, prompt or page changes (later slices). `progress.yaml` was left as the orchestrator had it, uncommitted.
- Skipped: the full suite and browser tests (not in the slice's commands).
