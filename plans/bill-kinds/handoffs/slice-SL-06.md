# Handoff: slice SL-06 — change a bill's kind, correct a rent line's type

```yaml
result: done
start_head: 860384950ad50cac98ff3d2390c87246c1b52986
end_head: 47b04d8
commit: 47b04d8
verification_command: python -m pytest tests/test_bill_kinds.py -k "journey or sc43" -q; python -m pytest tests/test_receipt_kinds.py tests/test_bills_ledger.py -q
verification_result: passed (22 passed; 55 passed, 1 skipped)
log: plans/bill-kinds/logs/slice-SL-06.log
escalations: 0
```

## What was built
- `Manager.change_receipt_kind` is now `change_kind`. A receipt takes fuel, dining, grocery or general. A bill takes rent or general, and an invoice takes general only. Any other kind gives a 400 with a named message. The 409, 200-unchanged and enqueue behaviour is as before. The enqueue key stays `receipt_kind` (P4).
- API: `ReceiptKindInput` adds `rent`, and `LineInput.field` adds `line_type`.
- `requested_kinds(..., document_type, notes)` reads the kind correction that fits the reading's type (`chosen_kind(blob, segment, field)`). A kind change that doesn't fit is ignored and adds the note "Rent was not used: this document was read as a receipt.". It isn't marked as asked, so no correction is written.
- Ledger:
  - `_undo_kind` and `undo_corrections` handle `bill_kind`. Undoing back to a kind other than rent sets every line's `line_type` to NULL, and `line_kind` is kept.
  - `LINE_FIELDS` adds `line_type`. `correct_line` refuses a bad value, a `line_type` on a bill that isn't rent, and a `line_kind` on a rent line that already has a `line_type`.
  - `_set_line` sets `line_type` and the mapped `line_kind`.
  - `apply_corrections` replays `line_type:N` first, and only on a rent bill, then `line_kind:N`.
  - `delete_item` clears `line_type:N`.
  - New labels: "Bill kind" and "Type of".
- `RENT_LINE_TYPES` and `RENT_LINE_KINDS` move to `core/categories.py`, because the ledger can't import extraction (circular import). extraction.py imports them from there.
- Tests in `tests/test_bill_kinds.py`:
  - Journey steps 1–8 as one function.
  - J-a (fuel on a bill, rent on an invoice, rent on a receipt), J-b, J-c and J-d.
  - A kind change that doesn't fit the reading's type.
  - Line-type rules, including undo and delete.
  - SC-43 step 5 over the endpoints. After it, October shows housing 1,488.42 and utilities 0, and the health check passes.
  - Replay on a bill read again as general.

## Decisions and deviations
- `tests/test_receipt_kinds.py` changed in 2 places: the call to the renamed method, and the expected message for fuel on a bill. It was "A bill has no receipt kind." and is now "Choose one of a bill's kinds: rent or general.", the plan's J-a message.
- I changed `docs/documents.md` by one word (`change_kind`) so the code citation stays correct. All other doc work is left for SL-08.
- Journey step 7 undoes Apply details before step 8, so the details are still pending after the restart.
- Clearing a line's `line_type` (setting it to None, or undoing back to None) keeps the line's current `line_kind`. Its line kind from before the rent type isn't restored. This is minor.

## Open issues / escalations
- None.
- mypy on extraction.py, manager.py and api.py reports 103 errors, none on changed lines. They are `Literal[*X]`, `create_model` overloads and `manager()` returning a value typed as possibly None. ledger.py and categories.py are clean. ruff is clean on every touched file.
- The handoff template under `$HOME/.agent-harness` was not read, so this follows SL-05's format.
- Git state after the commit: clean except the existing `M progress.yaml`, plus this handoff. The log is git-ignored.
