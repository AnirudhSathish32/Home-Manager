```yaml
slice: SL-05
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 9b09d4b
end_head: 655dfc9   # the code commit; the handoff itself is committed on top of it
commit: 655dfc9
checks:
  - command: ".venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_spending_splits.py tests/test_family_routing.py tests/test_family_ledger.py tests/test_receipt_counting.py tests/test_receipt_item_table.py tests/test_receipt_kinds.py tests/test_bills_ledger.py -q -p no:cacheprovider -rf"
    exit_code: 0     # 259 passed, 2 skipped (3m56s). Run before the last two small tests were added; those two and the whole of test_dining_receipts.py ran again in the next check.
  - command: ".venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_traces.py tests/test_splits_by_code.py tests/test_reextraction.py tests/test_migrations.py tests/test_receipt_tax_codes.py tests/test_health.py tests/test_family_inbox.py tests/test_plan_tracking.py tests/test_receipt_segments.py tests/test_receipt_side_lines.py tests/test_vision_indent.py tests/test_receipt_discounts.py -q -p no:cacheprovider -rf   (extra regression files that mention dining, not part of the slice command)"
    exit_code: 1     # 335 passed, 3 failed: exactly the 3 tax-trace failures of tests/test_traces.py listed in baseline-failures.txt (lines 54-56)
  - command: ".venv/bin/ruff check src tests/test_dining_receipts.py tests/dining_receipt_fixtures.py"
    exit_code: 0
  - command: "git diff --exit-code 9b09d4b -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```
SL-05 is built: a dining receipt counts wholly under its category once FR-10 has applied, the Category column / dropdown rules, and the footer's "Not matched to an item" without the tip. No UI change (SL-08), no migration, no change to `tests/dining_receipt_data/`.

## What was done
- `finance/splits.py` `allocate(..., one_category=False, tip_category=None)` (P8, D18): with `one_category` every item row takes the receipt's category whatever the item says, the tip row takes it (dining when the receipt has none), and a positive difference is one no-item row in it, never spread. A negative difference is spread as before. Without the flag, rules 4 and 5 are exactly as before. `tip_category` replaces only the tip row's category.
- `finance/ledger.py`:
  - `Ledger.one_category(receipt)`: the flag and `receipt_kind == dining` and `document_kind == receipt`. `shares` passes it (and `tip_category`) to all three `allocate` calls, so every rebuild reads the flag and none sets it (D8).
  - `Ledger.apply_one_category(db, receipt_id)`: sets `receipts.one_category = 1` for a dining receipt and stores the receipt's category with source `receipt` on every item whose source isn't `user` (D20). Called only from `publish_receipt` (after `apply_corrections`, when `written` and the record is a dining receipt, so also a family-sent receipt) and from `_apply_correction` when `category` changes to a different value (Q1: the same value does nothing).
  - `publish_receipt` writes `one_category = 0` with every written reading, then `apply_one_category` for dining, so a reading as another kind clears the flag (FR-13's "away" case in the written branch; the reviewed kind-change branch and `_undo_kind` are untouched, they are SL-06's).
  - `_replace_items(..., dining)` reads no `item_category_memory` for a dining receipt.
  - `Ledger.category_column(db, row)` (P9): False (hidden) only for a dining receipt whose own-split item rows all have the receipt's category; with no split yet, decided from `fallback` for all when `one_category`, else each item's category. The record payload sends `category_column`.
  - `set_item_category` raises `ValueError(CATEGORY_REFUSED)` (the API turns it into the 400 with the exact FR-12 text) exactly when `category_column` is False, before anything is written.
  - `Ledger.unmatched_minor` (P10, FR-27): the stored no-item rows less the tip's own row, found by rebuilding the receipt's split once with `tip_category=TIP_MARK`. No stored row is written.
- `documents/extraction.py` `publish`: `record["category"] = "dining"` for a dining receipt (a category you corrected is replayed by `apply_corrections` and wins).
- `finance/traces.py`: the split trace says ", a tip and any difference under the receipt's category" when FR-10 has applied, else today's text.
- Tests (`tests/test_dining_receipts.py` now 107 tests): the `# SL-05: C-cat` places are filled (SC-01 step 8, SC-02 step 3, SC-03 step 2, (c), (d), SC-06 step 5); new tests for SC-01 steps 6–7 and (c), SC-05 (steps 1–4, 5 and 6, (a)), SC-07 (+a–c, and the API 400/200 through `app_session`), SC-09 steps 1–5, SC-16, SC-18 (+a), X-D8 (old rules for C, mirror for dining and travel, old-rules case for H, the contrast), X-Q1, allocate unit tests, the trace text, the dining category at recording and a corrected category surviving a re-read.

## Fixture and contract notes for later slices
- **Fixture fixes in `tests/dining_receipt_fixtures.py`** (SL-04's builder was inexact): receipt G's stored split is now 444/556 (what today's `allocate` gives for 900 + 100 tax; a reconciliation rebuild otherwise changed it); the item category memory row now uses `normalize_name` keys ("GACHA S BREAKFAST BAR", "COFFEE"; the old lowercase keys never matched what the ledger writes); each old document gets a `versions` row (Extract again needs it); `insert_old_receipts(..., memory=True)` takes `memory=False`, because SC-05/09/16 expect no memory rows. The X-UPG test still passes.
- `old_manager(tmp_path, local_model, names)` in `tests/test_dining_receipts.py` builds the old library (migrations below 081 + `insert_old_receipts`, then opened with the changed code); `read_again_of`, `reopen`, `splits_of`, `table_rows`, `charge_split`, `link_of` are the helpers SL-06/SL-07 can reuse.
- **SC-05 step 5 link branch is SL-07's.** In `test_sc05_old_receipts_stay_until_read_again` receipt A (the lower id) holds K52's link, so the "A held" branch runs. SL-05 asserts only what FR-10 does there (A's total, tip, categories, FR-06 reason `in` issues). When FR-28 exists the A-held branch gains the removal note and B takes K52; the test's `if holder == "B"` guard and the unchanged-B-split checks should still hold, but SL-07 should tighten them.
- **SC-09 steps 6–7** (link removal, note) are not tested here; after step 5 the K52 link still stands.
- **X-D8 "other Edit details fields"**: the contract's `{description: "Breakfast"}` is not a correctable field in this app (the answer is "Choose fields this record allows"); the tests use `{order_number: "179580"}`. "Family share" is driven as the family routing path writes it (a `record_shares` row, then `refresh_splits`), not through a second library.
- SL-06 needs: `apply_one_category` for the reviewed kind-change branch and `_undo_kind`, `recategorise_items`, the kind-correction snapshot in `record_corrections.item_categories_json`. None of that is started. `TIP_MARK` and `unmatched_minor` are in place for SL-08's footer.

## Open issues
None. Not run (outside the slice's command): the full suite, browser tests, the other slices' commands.
