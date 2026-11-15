```yaml
slice: SL-06
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 74127d4
end_head: 01ceea7   # the code commit; the handoff itself is committed on top of it
commit: 01ceea7
checks:
  - command: ".venv/bin/python -m pytest tests/test_dining_receipts.py tests/test_receipt_kinds.py tests/test_spending_splits.py -q -p no:cacheprovider -rf"
    exit_code: 0     # 184 passed (3m52s)
  - command: ".venv/bin/ruff check src tests/test_dining_receipts.py tests/dining_receipt_fixtures.py"
    exit_code: 0     # after `ruff check --fix` sorted two imports in the test file (run after the pytest check; imports only)
  - command: "git diff --exit-code 74127d4 -- tests/dining_receipt_data"
    exit_code: 0
escalations: []
```
SL-06 is built: a kind change keeps what Undo needs and rebuilds the split at once, and the backfill gives a dining receipt's items its category. No UI change, no migration, no change to `tests/dining_receipt_data/`.

## What was done
- `finance/ledger.py`
  - `publish_receipt`: for a receipt-kind change (`source["kind_change"]`, `receipt_kind` column only, bills untouched) it takes `category_snapshot` (`{"one_category", "items": [[id, category, source]…]}`) **before `_upsert`**, so both branches have the pre-change state, and stores it in the kind correction row's `item_categories_json`. In the reviewed branch (not written) it then calls `apply_one_category` (to dining) or clears `one_category` and calls `recategorise_items` with `record["items"]` (away), then `refresh_splits`, so the split follows the change in the same publication. The written branch needed nothing more: `_upsert` already writes `one_category = 0` and `apply_one_category` already runs for dining.
  - `_undo_kind` (receipt kind only): its own correction row stores a snapshot of the state just before the Undo (so undoing the Undo is exact), then `_undo_categories` and `refresh_splits`. `_undo_categories` with a snapshot restores the flag and each listed item still present and applies nothing else. With no snapshot (a kind correction from before 081): the kind put back is dining → `apply_one_category`; otherwise `one_category = 0` and `recategorise_items` from the latest succeeded run's `result["normalized"]["items"]` for the receipt's document.
  - `recategorise_items(db, receipt_id, rows, merchant)`: each non-`user` item takes memory, else the reading's category (`receipt_category(..., legacy=True)`; source model, or none if the reading gives none), matching by `item_keys` (description, line total, ordinal). An item the reading doesn't list keeps its category unless memory has one.
- `finance/item_categories.py`: on a dining receipt every item the backfill would categorise (first time, or `legacy` source) takes the receipt's category (after a retired receipt category is replaced) with source `receipt`, whatever memory and the model say. It still ends with the same `refresh_splits`, with the flag unchanged (the backfill is not an FR-14 event, so rules 4 and 5 stay). A dining receipt with no category uses the old rule.
- Tests (`tests/test_dining_receipts.py` 117 tests): `test_sc08_kind_change_and_undo` (steps 1–4, plus undo of the Undo twice), `test_sc08a_…` (verified grocery receipt → dining counts under groceries, the receipt's category, then Undo gives back the earlier split, categories and flag: the C-snap test), `test_sc08b_…` (refused while a reading runs), written-branch snapshot test, old receipt D away and Undo (unset flag, own categories), Undo with no snapshot in both directions, `test_sc17_…` and (a) (retired category, its split row moves), (b) (grocery receipt, memory then model), (c) (H, tip stays dining, difference stays spread).

## Notes for later slices
- The SC-08 grocery reading is driven through `Manager.change_kind` + `manager.future.result` (helper `kind_change`); `undo_kind` undoes the latest `receipt_kind` correction. A grocery receipt is built by reading the breakfast file as dining and changing it to grocery (a first read with `grocery_re_read_stub` fails validation: that stub has the kind-change reply shape).
- A reviewed grocery → dining change keeps the receipt's own category (groceries), so the whole receipt counts under groceries (FR-10 wording: "the receipt's category"); SC-08 (a) says "the receipt's category" and the test asserts that.
- A kind change in the written branch (receipt nobody decided) rewrites amounts from the new reading; Undo then restores categories and the flag, not the amounts (as for any Undo of a written kind change today).
- The "no snapshot, away from dining" fallback reads the latest succeeded run of the receipt's document, whichever segment; fine for one receipt per file.

## Open issues
None. Not run (outside the slice's command): the full suite, browser tests, the other slices' commands.
