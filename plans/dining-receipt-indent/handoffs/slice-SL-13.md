```yaml
slice: SL-13
result: ready_for_verification
provider: claude
model: claude-sonnet-5-5
model_family: anthropic
helper_subagents: 0
start_head: 80d4012
end_head: 8628365   # the code commit; the handoff itself is committed on top of it
commit: 8628365
checks:
  - command: ".venv/bin/python -m pytest -q -p no:cacheprovider tests/test_dining_receipts.py tests/test_receipt_kinds.py tests/test_family_routing.py"
    exit_code: 0     # 201 passed
  - command: "git stash (src only) && pytest -k sc08 tests/test_dining_receipts.py"
    exit_code: 1     # 3 failed (a, c-undone, d), 3 passed at START_HEAD behaviour; all 6 pass with the change
  - command: ".venv/bin/ruff check src tests"
    exit_code: 1     # only the 2 known findings: test_document_v2_browser.py I001, test_receipt_kinds.py F402
  - command: "git diff 80d4012 -- specs approvals plans/dining-receipt-indent/plan.md tests/dining_receipt_data"
    exit_code: 0     # empty
escalations: []
```
SL-13 implements D42. No requirement or test-contract value changed; no migration.

## What was done
- `finance/ledger.py` `publish_receipt` (the reviewed/`not written` kind-change branch, the only place a reviewed receipt's kind change writes the split): for a change to dining, set `receipts.category` to `splits.DINING` before `apply_one_category`, unless `Ledger.category_corrected` says a category correction stands. New `category_corrected(db, receipt_id)`: a `record_corrections` row (receipt, field `category`) exists and the latest is not an undo (`UNDO_REASON`) back to the first one's `previous` (same pattern as `worked_out_tip`).
- Other paths checked, no change needed: the unreviewed (written) path already gets dining from the reading (`extraction.py` sets `record["category"]=DINING`), `apply_corrections` replays a standing category correction, then `apply_one_category`; `_undo_kind`/`_undo_categories` already snapshot and restore `category` (SL-10) unless a later `category` correction exists, and the Undo's own snapshot holds the dining category, so undoing the Undo is exact. A change away from dining writes no category.
- Tests (`tests/test_dining_receipts.py`): (a) rewritten — verified grocery receipt → dining: category dining, split all dining, sum unchanged, column hidden, snapshot holds groceries; Undo → groceries and the earlier split/items/flag; undo of the Undo → dining. (c) category Travel before the change stays travel and Undo keeps it, plus an extra test that a category correction you undid doesn't stand. (d) Travel after the change; Undo of the kind change keeps travel, items and flag back per the snapshot. SC-08 steps 1–4 and (b) unchanged and pass.
- Docs: `docs/money.md` "A dining receipt" (the event list and "Changing the kind") says what D42 says. No other doc stated the old behaviour.

## Open issues
- (c) "category stays travel" passes at START_HEAD too (the reviewed receipt never had its category rewritten), so that test guards the "your correction stands" rule rather than failing before the change; the extra undone-correction test and (a), (d) do fail at START_HEAD.
- A category correction made, then undone, then a later category set by a reading isn't distinguished from "none stands"; only the correction history decides.
- Not run: the full suite; browser tests.
