```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 49729a8
end_head: 7255210            # the docs commit; the handoff itself is committed on top of it
commit: 7255210
changed_files:
  - docs/money.md
  - plans/receipt-item-table/handoffs/slice-SL-05.md
checks:
  - command: ".venv/bin/ruff check src tests"
    exit_code: 0
skipped_checks:
  - "pytest: docs-only; the orchestrator's full-suite run covers the code"
escalations: []
```

# SL-05: docs-only fix for code review round 2 (CR2-m1)

Rewrote the parenthetical in the **Paid** bullet of `docs/money.md` "Item categories and splits" (heading unchanged).

New text, verbatim:

> (an item whose amount is zero never carries tax. An untaxed item carries none unless the taxed items' amounts add up to zero, when every item's amount is its weight)

Justification against the code: `splits.tax_basis` returns the taxed items' amounts unless they sum to zero, then every item's amount, and `ledger.item_table` sets `tax_included` only when the item's basis is nonzero, so a zero-amount item never carries tax and an untaxed item carries tax only through that fallback (taxed 100, −100 and untaxed 200 give [100, −100, 200]).

Note: the doc does not spell out the edge where every item's amount also sums to zero. `item_table` then shows no "with tax" on any item (`sum(basis) != 0` fails). The surrounding bullet text is unchanged; flagging only.

Only `docs/money.md` and this handoff changed. The uncommitted `specs/receipt-tax-codes/` files and `progress.yaml` were left alone. Nothing pushed.
